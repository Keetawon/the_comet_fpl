"""Run the walk-forward evaluation defined by `config/phase1_evaluation.yaml`.

    python -m fpl.validate.harness                 # every baseline, every fold
    python -m fpl.validate.harness --season 2025-26

The harness reads outcomes, which the feature layer may not. That asymmetry is deliberate:
scoring a prediction requires the label, and the label is exactly what a feature must never
see. Training data is restricted to `kickoff_time < as_of` by the fold, and every fold asserts
that its own gameweek is invisible before it is used.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import duckdb
import polars as pl

from fpl.config import Phase1EvaluationConfig, load_phase1_evaluation
from fpl.storage.db import connect
from fpl.validate.baselines import StageABaseline, TrainingWindow, build_baselines
from fpl.validate.folds import (
    Fold,
    assert_no_leakage,
    generate_folds,
    promoted_team_codes,
)
from fpl.validate.metrics import Distribution, ScoreReport, relative_lift, score_predictions

logger = logging.getLogger("fpl.validate.harness")

# Every read of the team-match facts goes through this projection, and it carries `team_code`
# for both sides. Team ids are season-scoped and get reassigned between seasons -- id 17 is
# Spurs, Southampton, Sheffield United, Southampton, then Sunderland across the five seasons
# here -- so a rating keyed on the bare id silently pools different clubs. `team_code` is 1:1
# with the club and is the only key permitted for following one between seasons.
_TEAM_MATCH_SELECT = """
    m.season, m.gw, m.fixture, m.kickoff_time,
    m.team_id, m.opponent_team_id,
    club.team_code AS team_code,
    opponent.team_code AS opponent_team_code,
    m.was_home, m.goals_for, m.goals_against,
    m.team_xg, m.team_xgc, m.fdr
"""

_TEAM_MATCH_FROM = """
    FROM mart_fact_team_match AS m
    JOIN mart_dim_team AS club
      ON club.season = m.season AND club.team_id = m.team_id
    JOIN mart_dim_team AS opponent
      ON opponent.season = m.season AND opponent.team_id = m.opponent_team_id
"""


@dataclass(frozen=True, slots=True)
class FoldPredictions:
    fold: Fold
    distributions: dict[str, list[Distribution]]
    observed: list[int]


def _training_window(con: duckdb.DuckDBPyConnection, fold: Fold) -> TrainingWindow:
    """Everything that had kicked off before this fold's cutoff, across all seasons.

    The window expands rather than rolling: a team model needs cross-season history to have
    any prior at all at the start of a season.
    """
    frame = con.execute(
        f"SELECT {_TEAM_MATCH_SELECT} {_TEAM_MATCH_FROM} WHERE m.kickoff_time < ?",
        [fold.as_of],
    ).pl()
    return TrainingWindow(frame)


def _fold_fixtures(con: duckdb.DuckDBPyConnection, fold: Fold) -> pl.DataFrame:
    return con.execute(
        f"""
        SELECT {_TEAM_MATCH_SELECT} {_TEAM_MATCH_FROM}
        WHERE m.season = ? AND m.gw = ? AND m.goals_for IS NOT NULL
        ORDER BY m.fixture, m.team_id
        """,
        [fold.season, fold.gw],
    ).pl()


def run_fold(
    con: duckdb.DuckDBPyConnection, fold: Fold, baselines: list[StageABaseline]
) -> FoldPredictions | None:
    """Fit every baseline on the fold's training window and predict its gameweek."""
    assert_no_leakage(con, fold)

    window = _training_window(con, fold)
    if window.is_empty:
        return None
    fixtures = _fold_fixtures(con, fold)
    if fixtures.is_empty():
        return None

    distributions: dict[str, list[Distribution]] = {}
    for baseline in baselines:
        # Refitted inside every fold: the contract requires transforms fitted within the fold,
        # so nothing learned from the future can survive into an earlier prediction.
        baseline.fit(window)
        distributions[baseline.name] = baseline.predict(fixtures)

    observed = [int(value) for value in fixtures["goals_for"].to_list()]
    return FoldPredictions(fold=fold, distributions=distributions, observed=observed)


@dataclass(frozen=True, slots=True)
class HarnessResult:
    folds_evaluated: int
    predictions: int
    overall: dict[str, ScoreReport]
    by_season: dict[str, dict[str, ScoreReport]]

    def best_baseline(self) -> str:
        """Lowest mean log score overall -- what a candidate must beat."""
        return min(self.overall, key=lambda name: self.overall[name].mean_log_score)


def run(
    con: duckdb.DuckDBPyConnection,
    *,
    config: Phase1EvaluationConfig | None = None,
    seasons: list[str] | None = None,
    candidates: Sequence[StageABaseline] | None = None,
) -> HarnessResult:
    """Score every baseline, plus any candidates, on exactly the same predictions.

    Candidates go through the identical fold loop rather than a parallel one, because
    `comparison_population: same_eligible_predictions` is only true if the rows are literally
    the same rows -- a candidate evaluated on its own population is not comparable at all.
    """
    resolved = config or load_phase1_evaluation()
    baselines = [*build_baselines(resolved.training.minimum_team_matches), *(candidates or [])]
    # Which clubs came up is reference data, known before a season starts, so supplying it
    # to the cold-start baseline is not leakage.
    promoted = promoted_team_codes(con)
    for baseline in baselines:
        setter = getattr(baseline, "set_promoted", None)
        if setter is not None:
            setter(promoted)
    folds = generate_folds(con, resolved)
    if seasons:
        folds = [fold for fold in folds if fold.season in seasons]

    pooled: dict[str, list[Distribution]] = defaultdict(list)
    pooled_observed: list[int] = []
    per_season: dict[str, dict[str, list[Distribution]]] = defaultdict(lambda: defaultdict(list))
    per_season_observed: dict[str, list[int]] = defaultdict(list)

    evaluated = 0
    for fold in folds:
        result = run_fold(con, fold, baselines)
        if result is None:
            continue
        evaluated += 1
        pooled_observed.extend(result.observed)
        per_season_observed[fold.season].extend(result.observed)
        for name, distributions in result.distributions.items():
            pooled[name].extend(distributions)
            per_season[fold.season][name].extend(distributions)

    seed = resolved.training.seed
    overall = {
        name: score_predictions(name, distributions, pooled_observed, seed=seed)
        for name, distributions in pooled.items()
    }
    by_season = {
        season: {
            name: score_predictions(name, distributions, per_season_observed[season], seed=seed)
            for name, distributions in names.items()
        }
        for season, names in per_season.items()
    }
    return HarnessResult(
        folds_evaluated=evaluated,
        predictions=len(pooled_observed),
        overall=overall,
        by_season=by_season,
    )


def passes_calibration_gate(
    report: ScoreReport, config: Phase1EvaluationConfig | None = None
) -> bool:
    """Apply the contract's calibration gate to one scored population.

    Written as code rather than left in the YAML because the gate's whole history is an
    ambiguity about which coverage it meant. Reading it from the typed config means a future
    change to the tolerance takes effect here without anyone remembering to update a constant.
    """
    resolved = config or load_phase1_evaluation()
    return (
        report.pit_interval_80_absolute_error
        <= resolved.promotion.pit_interval_80_maximum_absolute_error
    )


def format_report(result: HarnessResult, config: Phase1EvaluationConfig | None = None) -> str:
    resolved = config or load_phase1_evaluation()
    tolerance = resolved.promotion.pit_interval_80_maximum_absolute_error
    lines = [
        f"folds evaluated : {result.folds_evaluated}",
        f"predictions     : {result.predictions}",
        "",
        f"{'baseline':<32}{'log score':>11}{'CRPS':>9}{'PIT 80%':>9}{'raw 80%':>9}{'MAE':>8}"
        f"{'calib':>8}",
        "-" * 86,
    ]
    ordered = sorted(result.overall.values(), key=lambda report: report.mean_log_score)
    for report in ordered:
        gate = "pass" if passes_calibration_gate(report, resolved) else "FAIL"
        lines.append(
            f"{report.name:<32}{report.mean_log_score:>11.4f}{report.mean_crps:>9.4f}"
            f"{report.pit_interval_80_coverage:>9.3f}{report.interval_80_coverage:>9.3f}"
            f"{report.mean_absolute_error:>8.3f}{gate:>8}"
        )
    lines.append(
        f"calibration gate: |PIT 80% - 0.80| <= {tolerance:.2f}  "
        f"(contract {resolved.contract_version}; the raw 80% column is reported, not gated)"
    )

    best = ordered[0]
    lines += ["", f"best baseline: {best.name} (log score {best.mean_log_score:.4f})", ""]

    lines.append("by season (mean log score):")
    names = [report.name for report in ordered]
    header = "season".ljust(10) + "".join(name[:14].rjust(16) for name in names)
    lines += [header, "-" * len(header)]
    for season in sorted(result.by_season):
        row = season.ljust(10)
        for name in names:
            scored = result.by_season[season].get(name)
            row += (f"{scored.mean_log_score:.4f}" if scored else "-").rjust(16)
        lines.append(row)
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class GateCheck:
    name: str
    passed: bool
    detail: str


def evaluate_gate(
    result: HarnessResult,
    candidate: str,
    config: Phase1EvaluationConfig | None = None,
) -> list[GateCheck]:
    """Apply the contract's promotion gate to one candidate.

    Written as code so the verdict is computed rather than argued. The comparator is the best
    *pre-registered* baseline by overall mean log score -- the candidate never gets to pick
    which baseline it is measured against, and the same comparator is used in every season.
    """
    resolved = config or load_phase1_evaluation()
    gate = resolved.promotion
    contracted = set(resolved.baselines.stage_a)

    eligible = {name: report for name, report in result.overall.items() if name in contracted}
    comparator = min(eligible, key=lambda name: eligible[name].mean_log_score)
    baseline = eligible[comparator]
    scored = result.overall[candidate]

    lift = relative_lift(baseline.mean_log_score, scored.mean_log_score)
    crps_change = relative_lift(baseline.mean_crps, scored.mean_crps)
    checks = [
        GateCheck(
            f"log score lift over {comparator}",
            lift >= gate.minimum_primary_relative_lift,
            f"{lift:+.4%} against a required {gate.minimum_primary_relative_lift:.0%} "
            f"({scored.mean_log_score:.4f} vs {baseline.mean_log_score:.4f})",
        ),
        GateCheck(
            "CRPS does not regress",
            crps_change >= -gate.maximum_crps_relative_regression,
            f"{crps_change:+.4%} ({scored.mean_crps:.4f} vs {baseline.mean_crps:.4f})",
        ),
        GateCheck(
            "calibration",
            passes_calibration_gate(scored, resolved),
            f"PIT 80% coverage {scored.pit_interval_80_coverage:.3f}, "
            f"error {scored.pit_interval_80_absolute_error:.3f} "
            f"<= {gate.pit_interval_80_maximum_absolute_error}",
        ),
        GateCheck(
            "fold count",
            result.folds_evaluated >= gate.minimum_fold_count,
            f"{result.folds_evaluated} folds against a required {gate.minimum_fold_count}",
        ),
    ]

    if gate.require_each_reported_season_to_pass:
        failures = []
        for season in sorted(result.by_season):
            reports = result.by_season[season]
            if candidate not in reports or comparator not in reports:
                continue
            season_lift = relative_lift(
                reports[comparator].mean_log_score, reports[candidate].mean_log_score
            )
            if season_lift < gate.minimum_primary_relative_lift:
                failures.append(f"{season} {season_lift:+.2%}")
        checks.append(
            GateCheck(
                "every reported season clears the gate",
                not failures,
                "all seasons pass" if not failures else "below the bar in " + ", ".join(failures),
            )
        )
    return checks


def format_gate(result: HarnessResult, candidates: Sequence[str]) -> str:
    lines = ["", "promotion gate", "-" * 78]
    for candidate in candidates:
        if candidate not in result.overall:
            continue
        checks = evaluate_gate(result, candidate)
        verdict = "PROMOTE" if all(check.passed for check in checks) else "DO NOT PROMOTE"
        lines.append(f"{candidate}: {verdict}")
        for check in checks:
            mark = "pass" if check.passed else "FAIL"
            lines.append(f"    [{mark}] {check.name}: {check.detail}")
    lines.append("")
    lines.append("A failed gate is a documented non-promotion, not an invitation to move the bar.")
    return "\n".join(lines)


def compare_xg_against_goals(result: HarnessResult) -> str:
    """The specification's open question, answered on the contract's own metric."""
    goals = result.overall.get("trailing_goals_attack_defence")
    xg = result.overall.get("trailing_xg_attack_defence")
    if goals is None or xg is None:
        return "xG-versus-goals comparison unavailable: a baseline did not run."

    lift = relative_lift(goals.mean_log_score, xg.mean_log_score)
    winner = "xG" if xg.mean_log_score < goals.mean_log_score else "goals"
    lines = [
        "",
        "xG versus goals as the training signal",
        "-" * 69,
        f"  trailing goals : log score {goals.mean_log_score:.4f}  CRPS {goals.mean_crps:.4f}",
        f"  trailing xG    : log score {xg.mean_log_score:.4f}  CRPS {xg.mean_crps:.4f}",
        f"  relative lift of xG over goals: {lift:+.4%}",
        f"  winner on the contract's primary metric: {winner}",
    ]
    per_season = []
    for season in sorted(result.by_season):
        reports = result.by_season[season]
        if "trailing_goals_attack_defence" in reports and "trailing_xg_attack_defence" in reports:
            g = reports["trailing_goals_attack_defence"].mean_log_score
            x = reports["trailing_xg_attack_defence"].mean_log_score
            winner_here = "xG" if x < g else "goals"
            per_season.append(f"    {season}  goals {g:.4f}  xG {x:.4f}  -> {winner_here}")
    if per_season:
        lines += ["  by season:", *per_season]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Stage A walk-forward harness.")
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--season", action="append", dest="seasons", default=None)
    parser.add_argument(
        "--baselines-only",
        action="store_true",
        help="score only the pre-registered baselines, without the Stage A candidate",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    candidates: list[StageABaseline] = []
    if not args.baselines_only:
        # Imported here rather than at module scope: the harness defines the contract the
        # models are judged against, so it must not depend on any particular model existing.
        from fpl.models.team_goals import StageATeamModel

        candidates.append(StageATeamModel())

    con = connect(args.db, read_only=True)
    try:
        result = run(con, seasons=args.seasons, candidates=candidates)
    finally:
        con.close()

    print(format_report(result))
    print(compare_xg_against_goals(result))
    if candidates:
        print(format_gate(result, [candidate.name for candidate in candidates]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
