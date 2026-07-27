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
    promoted_team_ids,
)
from fpl.validate.metrics import Distribution, ScoreReport, relative_lift, score_predictions

logger = logging.getLogger("fpl.validate.harness")

_TEAM_MATCH_COLUMNS = (
    "season",
    "gw",
    "fixture",
    "kickoff_time",
    "team_id",
    "opponent_team_id",
    "was_home",
    "goals_for",
    "goals_against",
    "team_xg",
    "team_xgc",
    "fdr",
)


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
    columns = ", ".join(_TEAM_MATCH_COLUMNS)
    frame = con.execute(
        f"SELECT {columns} FROM mart_fact_team_match WHERE kickoff_time < ?",
        [fold.as_of],
    ).pl()
    return TrainingWindow(frame)


def _fold_fixtures(con: duckdb.DuckDBPyConnection, fold: Fold) -> pl.DataFrame:
    columns = ", ".join(_TEAM_MATCH_COLUMNS)
    return con.execute(
        f"""
        SELECT {columns} FROM mart_fact_team_match
        WHERE season = ? AND gw = ? AND goals_for IS NOT NULL
        ORDER BY fixture, team_id
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
) -> HarnessResult:
    resolved = config or load_phase1_evaluation()
    baselines = build_baselines(resolved.training.minimum_team_matches)
    # Which clubs came up is reference data, known before a season starts, so supplying it
    # to the cold-start baseline is not leakage.
    promoted = promoted_team_ids(con)
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


def format_report(result: HarnessResult) -> str:
    lines = [
        f"folds evaluated : {result.folds_evaluated}",
        f"predictions     : {result.predictions}",
        "",
        f"{'baseline':<32}{'log score':>11}{'CRPS':>9}{'PIT 80%':>9}{'raw 80%':>9}{'MAE':>8}",
        "-" * 78,
    ]
    ordered = sorted(result.overall.values(), key=lambda report: report.mean_log_score)
    for report in ordered:
        lines.append(
            f"{report.name:<32}{report.mean_log_score:>11.4f}{report.mean_crps:>9.4f}"
            f"{report.pit_interval_80_coverage:>9.3f}{report.interval_80_coverage:>9.3f}"
            f"{report.mean_absolute_error:>8.3f}"
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
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    con = connect(args.db, read_only=True)
    try:
        result = run(con, seasons=args.seasons)
    finally:
        con.close()

    print(format_report(result))
    print(compare_xg_against_goals(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
