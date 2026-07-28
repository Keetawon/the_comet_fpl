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
from collections import Counter, defaultdict
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
    distributions: dict[str, list[Distribution | None]]
    observed: list[int]
    cold_starts: dict[str, list[bool]]
    promoted_status: list[str]
    home_away: list[str]
    parameters: dict[str, dict[str, float | int | str]]


@dataclass(frozen=True, slots=True)
class PredictionRecord:
    distribution: Distribution | None
    observed: int
    fold: str
    season: str
    promoted_status: str
    home_away: str
    cold_start: bool


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
    con: duckdb.DuckDBPyConnection,
    fold: Fold,
    baselines: list[StageABaseline],
    *,
    promoted: dict[str, frozenset[int]] | None = None,
) -> FoldPredictions | None:
    """Fit every baseline on the fold's training window and predict its gameweek."""
    assert_no_leakage(con, fold)

    window = _training_window(con, fold)
    if window.is_empty:
        return None
    fixtures = _fold_fixtures(con, fold)
    if fixtures.is_empty():
        return None

    distributions: dict[str, list[Distribution | None]] = {}
    cold_starts: dict[str, list[bool]] = {}
    parameters: dict[str, dict[str, float | int | str]] = {}
    for baseline in baselines:
        # Refitted inside every fold: the contract requires transforms fitted within the fold,
        # so nothing learned from the future can survive into an earlier prediction.
        baseline.set_prediction_season(fold.season)
        baseline.fit(window)
        predicted = list(baseline.predict(fixtures))
        if len(predicted) != fixtures.height:
            raise ValueError(
                f"{baseline.name} returned {len(predicted)} predictions for "
                f"{fixtures.height} eligible rows"
            )
        distributions[baseline.name] = predicted
        cold_starts[baseline.name] = [
            baseline.is_cold_start(row) for row in fixtures.iter_rows(named=True)
        ]
        parameters[baseline.name] = baseline.parameters()

    observed = [int(value) for value in fixtures["goals_for"].to_list()]
    promoted_codes = (promoted or promoted_team_codes(con)).get(fold.season, frozenset())
    promoted_status = [
        "promoted" if int(value) in promoted_codes else "established"
        for value in fixtures["team_code"].to_list()
    ]
    home_away = ["home" if bool(value) else "away" for value in fixtures["was_home"].to_list()]
    return FoldPredictions(
        fold=fold,
        distributions=distributions,
        observed=observed,
        cold_starts=cold_starts,
        promoted_status=promoted_status,
        home_away=home_away,
        parameters=parameters,
    )


@dataclass(frozen=True, slots=True)
class HarnessResult:
    folds_evaluated: int
    folds_by_season: dict[str, int]
    predictions: int
    eligible_predictions: int
    leakage_failures: int
    required_baselines: frozenset[str]
    overall: dict[str, ScoreReport]
    by_fold: dict[str, dict[str, ScoreReport]]
    by_season: dict[str, dict[str, ScoreReport]]
    by_promoted_status: dict[str, dict[str, ScoreReport]]
    by_home_away: dict[str, dict[str, ScoreReport]]
    parameters_by_fold: dict[str, dict[str, dict[str, float | int | str]]]

    def best_baseline(self) -> str:
        """Lowest mean log score overall -- what a candidate must beat."""
        eligible = {
            name: self.overall[name] for name in self.required_baselines if name in self.overall
        }
        return min(eligible, key=lambda name: eligible[name].mean_log_score)


def _score_records(name: str, records: Sequence[PredictionRecord], *, seed: int) -> ScoreReport:
    scored = [record for record in records if record.distribution is not None]
    return score_predictions(
        name,
        [record.distribution for record in scored if record.distribution is not None],
        [record.observed for record in scored],
        seed=seed,
        eligible_predictions=len(records),
        cold_starts=[record.cold_start for record in scored],
        rank_groups=[record.fold for record in scored],
    )


def _slice_records(
    records: dict[str, list[PredictionRecord]],
    attribute: str,
) -> dict[str, dict[str, list[PredictionRecord]]]:
    sliced: dict[str, dict[str, list[PredictionRecord]]] = defaultdict(lambda: defaultdict(list))
    for name, predictions in records.items():
        for prediction in predictions:
            key = str(getattr(prediction, attribute))
            sliced[key][name].append(prediction)
    return sliced


def _score_slices(
    sliced: dict[str, dict[str, list[PredictionRecord]]], *, seed: int
) -> dict[str, dict[str, ScoreReport]]:
    return {
        key: {
            name: _score_records(name, predictions, seed=seed)
            for name, predictions in names.items()
        }
        for key, names in sliced.items()
    }


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

    records: dict[str, list[PredictionRecord]] = defaultdict(list)
    parameters_by_fold: dict[str, dict[str, dict[str, float | int | str]]] = {}
    folds_by_season: dict[str, int] = defaultdict(int)

    evaluated = 0
    for fold in folds:
        result = run_fold(con, fold, baselines, promoted=promoted)
        if result is None:
            continue
        evaluated += 1
        folds_by_season[fold.season] += 1
        fold_key = f"{fold.season}-GW{fold.gw}"
        parameters_by_fold[fold_key] = result.parameters
        for name, distributions in result.distributions.items():
            for index, distribution in enumerate(distributions):
                records[name].append(
                    PredictionRecord(
                        distribution=distribution,
                        observed=result.observed[index],
                        fold=fold_key,
                        season=fold.season,
                        promoted_status=result.promoted_status[index],
                        home_away=result.home_away[index],
                        cold_start=result.cold_starts[name][index],
                    )
                )

    seed = resolved.training.seed
    overall = {
        name: _score_records(name, predictions, seed=seed) for name, predictions in records.items()
    }
    by_fold = _score_slices(_slice_records(records, "fold"), seed=seed)
    by_season = _score_slices(_slice_records(records, "season"), seed=seed)
    by_promoted_status = _score_slices(_slice_records(records, "promoted_status"), seed=seed)
    by_home_away = _score_slices(_slice_records(records, "home_away"), seed=seed)
    predictions = len(next(iter(records.values()))) if records else 0
    return HarnessResult(
        folds_evaluated=evaluated,
        folds_by_season=dict(folds_by_season),
        predictions=predictions,
        eligible_predictions=predictions,
        leakage_failures=0,
        required_baselines=resolved.baselines.stage_a,
        overall=overall,
        by_fold=by_fold,
        by_season=by_season,
        by_promoted_status=by_promoted_status,
        by_home_away=by_home_away,
        parameters_by_fold=parameters_by_fold,
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
        f"predictions     : {result.predictions} / {result.eligible_predictions} eligible",
        f"leakage failures: {result.leakage_failures}",
        f"report slices   : {len(result.by_fold)} folds, {len(result.by_season)} seasons, "
        f"{len(result.by_promoted_status)} promoted-status, {len(result.by_home_away)} venue",
        "",
        f"{'model':<32}{'log':>8}{'SE':>8}{'CRPS':>8}{'dev':>8}{'var':>8}"
        f"{'raw80':>8}{'PIT80':>8}{'MAE':>8}{'rank':>8}{'cover':>8}"
        f"{'n':>7}{'excl':>7}{'cold':>7}",
        "-" * 143,
    ]
    ordered = sorted(result.overall.values(), key=lambda report: report.mean_log_score)
    for report in ordered:
        lines.append(
            f"{report.name:<32}{report.mean_log_score:>8.4f}"
            f"{report.mean_log_score_standard_error:>8.4f}{report.mean_crps:>8.4f}"
            f"{report.mean_poisson_deviance:>8.4f}{report.mean_predictive_variance:>8.3f}"
            f"{report.interval_80_coverage:>8.3f}{report.pit_interval_80_coverage:>8.3f}"
            f"{report.mean_absolute_error:>8.3f}{report.spearman_within_gameweek:>8.3f}"
            f"{report.fixture_coverage:>8.3f}{report.predictions:>7d}"
            f"{report.exclusions:>7d}{report.cold_starts:>7d}"
        )
    lines.append(
        f"calibration gate: |PIT 80% - 0.80| <= {tolerance:.2f}  "
        f"(contract {resolved.contract_version}; the raw 80% column is reported, not gated)"
    )

    best_name = result.best_baseline()
    best = result.overall[best_name]
    lines += [
        "",
        f"best required baseline: {best.name} (log score {best.mean_log_score:.4f})",
        "",
    ]

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

    for title, slices in (
        ("by promoted status", result.by_promoted_status),
        ("by home/away", result.by_home_away),
    ):
        lines += ["", f"{title} (mean log score):"]
        slice_header = "slice".ljust(12) + "".join(name[:14].rjust(16) for name in names)
        lines += [slice_header, "-" * len(slice_header)]
        for key in sorted(slices):
            row = key.ljust(12)
            for name in names:
                scored = slices[key].get(name)
                row += (f"{scored.mean_log_score:.4f}" if scored else "-").rjust(16)
            lines.append(row)

    parameter_values: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    for models in result.parameters_by_fold.values():
        for model, parameters in models.items():
            for key, value in parameters.items():
                parameter_values[model][key][str(value)] += 1
    parameter_values = {
        model: parameters for model, parameters in parameter_values.items() if parameters
    }
    if parameter_values:
        lines += ["", "fold-local selected parameters:"]
        for model in sorted(parameter_values):
            lines.append(f"  {model}")
            for key in sorted(parameter_values[model]):
                counts = ", ".join(
                    f"{value}={count}"
                    for value, count in sorted(parameter_values[model][key].items())
                )
                lines.append(f"    {key}: {counts}")
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
            "same eligible prediction population",
            scored.eligible_predictions == baseline.eligible_predictions
            and scored.predictions == baseline.predictions,
            f"candidate {scored.predictions}/{scored.eligible_predictions}, "
            f"baseline {baseline.predictions}/{baseline.eligible_predictions}",
        ),
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
            "fixture coverage",
            scored.fixture_coverage >= gate.minimum_fixture_coverage,
            f"{scored.fixture_coverage:.2%} against a required {gate.minimum_fixture_coverage:.0%}",
        ),
        GateCheck(
            "fold count",
            result.folds_evaluated >= gate.minimum_fold_count,
            f"{result.folds_evaluated} folds against a required {gate.minimum_fold_count}",
        ),
        GateCheck(
            "zero leakage failures",
            result.leakage_failures == 0,
            f"{result.leakage_failures} leakage failures",
        ),
    ]

    if gate.require_each_reported_season_to_pass:
        log_failures = []
        crps_failures = []
        calibration_failures = []
        coverage_failures = []
        fold_failures = []
        population_failures = []
        for season in sorted(result.by_season):
            reports = result.by_season[season]
            if candidate not in reports or comparator not in reports:
                population_failures.append(f"{season} missing report")
                continue
            season_baseline = reports[comparator]
            season_candidate = reports[candidate]
            season_lift = relative_lift(
                season_baseline.mean_log_score, season_candidate.mean_log_score
            )
            if season_lift < gate.minimum_primary_relative_lift:
                log_failures.append(f"{season} {season_lift:+.2%}")
            season_crps = relative_lift(season_baseline.mean_crps, season_candidate.mean_crps)
            if season_crps < -gate.maximum_crps_relative_regression:
                crps_failures.append(f"{season} {season_crps:+.2%}")
            if not passes_calibration_gate(season_candidate, resolved):
                calibration_failures.append(
                    f"{season} error {season_candidate.pit_interval_80_absolute_error:.3f}"
                )
            if season_candidate.fixture_coverage < gate.minimum_fixture_coverage:
                coverage_failures.append(f"{season} {season_candidate.fixture_coverage:.2%}")
            if result.folds_by_season.get(season, 0) < gate.minimum_fold_count:
                fold_failures.append(f"{season} {result.folds_by_season.get(season, 0)}")
            if (
                season_candidate.eligible_predictions != season_baseline.eligible_predictions
                or season_candidate.predictions != season_baseline.predictions
            ):
                population_failures.append(season)

        for name, failures in (
            ("every season clears log-score lift", log_failures),
            ("every season avoids CRPS regression", crps_failures),
            ("every season passes calibration", calibration_failures),
            ("every season passes fixture coverage", coverage_failures),
            ("every season has enough folds", fold_failures),
            ("every season uses the same population", population_failures),
        ):
            checks.append(
                GateCheck(
                    name,
                    not failures,
                    "all seasons pass" if not failures else ", ".join(failures),
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
    contract = load_phase1_evaluation()
    candidates: list[StageABaseline] = []
    if not args.baselines_only:
        # Imported here rather than at module scope: the harness defines the contract the
        # models are judged against, so it must not depend on any particular model existing.
        from fpl.models.team_goals import StageATeamModel

        candidates.append(
            StageATeamModel(
                contract.stage_a_candidate,
                minimum_team_matches=contract.training.minimum_team_matches,
            )
        )

    con = connect(args.db, read_only=True)
    try:
        result = run(con, config=contract, seasons=args.seasons, candidates=candidates)
    finally:
        con.close()

    print(format_report(result))
    print(compare_xg_against_goals(result))
    if candidates:
        print(format_gate(result, [candidate.name for candidate in candidates]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
