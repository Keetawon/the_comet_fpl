"""Run the Stage C (player attacking goals) walk-forward defined by `config/phase3_evaluation.yaml`.

    uv run python -m fpl.validate.attacking_harness

Stage C predicts a discrete Poisson count distribution over player goals (0..10)
at `(season, code, fixture)` grain over the registered FPL player population.
This harness fits and refits the two frozen Stage C attacking baselines inside
every fold and scores them on identical rows.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from fpl.config import Phase3EvaluationConfig, load_phase3_evaluation
from fpl.models.attacking_baselines import (
    GoalCountDistribution,
    PlayerHistoryRow,
    PositionalGoalRateBaseline,
    TargetRowProjection,
    TrailingPlayerGoalRateBaseline,
)
from fpl.storage.db import connect
from fpl.types import Position
from fpl.validate.attacking_metrics import AttackingScoreReport, score_attacking_predictions

logger = logging.getLogger("fpl.validate.attacking_harness")

STAGE_C_ATTACKING_BASELINE_ORDER: tuple[str, ...] = (
    "positional_goal_rate_poisson",
    "trailing_player_goal_rate_poisson",
)


@dataclass(frozen=True, slots=True)
class TargetPredictionRecord:
    target: TargetRowProjection
    observed_goals: int
    predictions: dict[str, GoalCountDistribution]
    is_cold_start: bool


@dataclass(frozen=True, slots=True)
class AttackingHarnessResult:
    overall: dict[str, AttackingScoreReport]
    by_season: dict[str, dict[str, AttackingScoreReport]]
    by_position: dict[str, dict[str, AttackingScoreReport]]
    by_home_away: dict[str, dict[str, AttackingScoreReport]]
    by_fold: dict[str, dict[str, AttackingScoreReport]]
    folds_by_season: dict[str, int]
    baseline_names: tuple[str, ...]
    total_predictions: int
    leakage_failures: int
    best_baseline_name: str


def assert_no_attacking_leakage(targets: Sequence[TargetRowProjection], as_of: str) -> None:
    """Verify that no target row has kickoff_time < as_of (as_of is min kickoff of the GW)."""
    for target in targets:
        if target.kickoff_time < as_of:
            msg = (
                f"Leakage failure: target row {target.season} GW{target.gw} "
                f"fixture {target.fixture} code {target.code} kickoff {target.kickoff_time} "
                f"is before fold cutoff as_of {as_of}"
            )
            raise ValueError(msg)


def run_attacking_fold(
    con: duckdb.DuckDBPyConnection,
    season: str,
    gw: int,
) -> tuple[str, list[TargetPredictionRecord]]:
    """Run fit and prediction for one (season, gw) fold."""
    # 1. Determine as_of (minimum kickoff_time in predicted observed GW)
    as_of_row = con.sql(
        """
        SELECT strftime(MIN(kickoff_time), '%Y-%m-%dT%H:%M:%SZ') AS as_of
        FROM mart_fact_player_fixture
        WHERE minutes IS NOT NULL AND season = ? AND gw = ?
        """,
        params=[season, gw],
    ).fetchone()
    if not as_of_row or as_of_row[0] is None:
        raise ValueError(f"No valid kickoff_time found for fold {season} GW{gw}")
    as_of: str = as_of_row[0]

    # 2. Query prior training history (kickoff_time < as_of)
    history_df = con.sql(
        """
        SELECT season, gw, fixture,
               strftime(kickoff_time, '%Y-%m-%dT%H:%M:%SZ') AS kickoff_time,
               code, position, COALESCE(goals_scored, 0) AS goals
        FROM mart_fact_player_fixture
        WHERE minutes IS NOT NULL AND kickoff_time < ?
        ORDER BY kickoff_time, season, fixture, code
        """,
        params=[as_of],
    ).pl()
    # Pin order via maintain_order=True
    history_df = history_df.sort(["kickoff_time", "season", "fixture", "code"], maintain_order=True)

    history_rows = [
        PlayerHistoryRow(
            season=r["season"],
            gw=r["gw"],
            fixture=r["fixture"],
            kickoff_time=r["kickoff_time"],
            code=r["code"],
            position=Position.from_archive_label(r["position"]),
            goals=r["goals"],
        )
        for r in history_df.iter_rows(named=True)
    ]

    # 3. Query target prediction rows
    target_df = con.sql(
        """
        SELECT season, gw, fixture,
               strftime(kickoff_time, '%Y-%m-%dT%H:%M:%SZ') AS kickoff_time,
               code, position, team_id, opponent_team_id, was_home,
               COALESCE(goals_scored, 0) AS goals
        FROM mart_fact_player_fixture
        WHERE minutes IS NOT NULL AND season = ? AND gw = ?
        ORDER BY kickoff_time, fixture, code
        """,
        params=[season, gw],
    ).pl()
    target_df = target_df.sort(["kickoff_time", "fixture", "code"], maintain_order=True)

    targets: list[TargetRowProjection] = []
    observed_goals: list[int] = []
    for r in target_df.iter_rows(named=True):
        targets.append(
            TargetRowProjection(
                season=r["season"],
                gw=r["gw"],
                fixture=r["fixture"],
                kickoff_time=r["kickoff_time"],
                code=r["code"],
                position=Position.from_archive_label(r["position"]),
                team_id=r["team_id"],
                opponent_team_id=r["opponent_team_id"],
                was_home=bool(r["was_home"]),
            )
        )
        observed_goals.append(r["goals"])

    assert_no_attacking_leakage(targets, as_of)

    # Track prior history codes for cold start check
    prior_codes = {r.code for r in history_rows}

    # Fit baselines
    b_pos = PositionalGoalRateBaseline()
    b_pos.fit(history_rows)

    b_trail = TrailingPlayerGoalRateBaseline(alpha=5.0)
    b_trail.fit(history_rows)

    # Predict
    records: list[TargetPredictionRecord] = []
    for target, goals in zip(targets, observed_goals, strict=True):
        p_pos = b_pos.predict(target)
        p_trail = b_trail.predict(target)

        is_cold = target.code not in prior_codes
        preds = {
            "positional_goal_rate_poisson": p_pos,
            "trailing_player_goal_rate_poisson": p_trail,
        }
        records.append(
            TargetPredictionRecord(
                target=target,
                observed_goals=goals,
                predictions=preds,
                is_cold_start=is_cold,
            )
        )

    fold_label = f"{season}-GW{gw:02d}"
    return fold_label, records


def run_attacking_harness(
    con: duckdb.DuckDBPyConnection,
    *,
    config: Phase3EvaluationConfig | None = None,
    seasons: Sequence[str] | None = None,
) -> AttackingHarnessResult:
    """Run the 181-fold Stage C attacking goals walk-forward evaluation."""
    if config is None:
        config = load_phase3_evaluation()

    # Query observed gameweek folds
    folds_df = con.sql(
        """
        SELECT DISTINCT season, gw
        FROM mart_fact_player_fixture
        WHERE minutes IS NOT NULL
        ORDER BY season, gw
        """
    ).pl()
    folds_df = folds_df.sort(["season", "gw"], maintain_order=True)

    all_observed_folds = [(r["season"], r["gw"]) for r in folds_df.iter_rows(named=True)]
    # Skip first minimum_observed_gameweeks (8) across seasons
    warmup_n = config.training.minimum_observed_gameweeks
    scoring_folds = all_observed_folds[warmup_n:]

    if seasons is not None:
        season_set = set(seasons)
        scoring_folds = [f for f in scoring_folds if f[0] in season_set]

    all_records_by_fold: dict[str, list[TargetPredictionRecord]] = {}
    folds_by_season: dict[str, int] = defaultdict(int)

    for ssn, gw in scoring_folds:
        fold_label, records = run_attacking_fold(con, ssn, gw)
        all_records_by_fold[fold_label] = records
        folds_by_season[ssn] += 1

    baseline_names = STAGE_C_ATTACKING_BASELINE_ORDER

    # Helper to score a collection of records for a given baseline
    def score_collection(
        recs: Sequence[TargetPredictionRecord], b_name: str
    ) -> AttackingScoreReport:
        preds = [r.predictions[b_name] for r in recs]
        targets = [r.observed_goals for r in recs]
        cold_count = sum(1 for r in recs if r.is_cold_start)
        return score_attacking_predictions(
            preds, targets, cold_starts=cold_count, seed=config.training.seed
        )

    # Flatten all records
    all_recs: list[TargetPredictionRecord] = [
        r for rec_list in all_records_by_fold.values() for r in rec_list
    ]
    total_preds = len(all_recs)

    # Slices
    overall: dict[str, AttackingScoreReport] = {
        b_name: score_collection(all_recs, b_name) for b_name in baseline_names
    }

    # by_fold
    by_fold: dict[str, dict[str, AttackingScoreReport]] = {}
    for f_label, recs in all_records_by_fold.items():
        by_fold[f_label] = {b_name: score_collection(recs, b_name) for b_name in baseline_names}

    # by_season
    recs_by_season: dict[str, list[TargetPredictionRecord]] = defaultdict(list)
    for r in all_recs:
        recs_by_season[r.target.season].append(r)

    by_season: dict[str, dict[str, AttackingScoreReport]] = {}
    for ssn in sorted(recs_by_season.keys()):
        s_recs = recs_by_season[ssn]
        by_season[ssn] = {b_name: score_collection(s_recs, b_name) for b_name in baseline_names}

    # by_position
    recs_by_pos: dict[str, list[TargetPredictionRecord]] = defaultdict(list)
    for r in all_recs:
        recs_by_pos[r.target.position.value].append(r)

    by_position: dict[str, dict[str, AttackingScoreReport]] = {}
    for pos in sorted(recs_by_pos.keys()):
        p_recs = recs_by_pos[pos]
        by_position[pos] = {b_name: score_collection(p_recs, b_name) for b_name in baseline_names}

    # by_home_away
    recs_by_ha: dict[str, list[TargetPredictionRecord]] = defaultdict(list)
    for r in all_recs:
        ha_key = "home" if r.target.was_home else "away"
        recs_by_ha[ha_key].append(r)

    by_home_away: dict[str, dict[str, AttackingScoreReport]] = {}
    for ha in ("home", "away"):
        ha_recs = recs_by_ha[ha]
        by_home_away[ha] = {b_name: score_collection(ha_recs, b_name) for b_name in baseline_names}

    best_b_name = min(baseline_names, key=lambda b: overall[b].mean_log_score)

    return AttackingHarnessResult(
        overall=overall,
        by_season=by_season,
        by_position=by_position,
        by_home_away=by_home_away,
        by_fold=by_fold,
        folds_by_season=dict(folds_by_season),
        baseline_names=baseline_names,
        total_predictions=total_preds,
        leakage_failures=0,
        best_baseline_name=best_b_name,
    )


def serialize_report(rep: AttackingScoreReport) -> dict[str, Any]:
    buckets = [
        {
            "lower": b.lower,
            "upper": b.upper,
            "n": b.n,
            "mean_predicted": b.mean_predicted,
            "observed_rate": b.observed_rate,
        }
        for b in rep.reliability_at_least_one_goal.buckets
    ]
    return {
        "predictions": rep.predictions,
        "exclusions": rep.exclusions,
        "cold_starts": rep.cold_starts,
        "uncertainty": round(rep.uncertainty, 6),
        "mean_log_score": round(rep.mean_log_score, 6),
        "mean_ranked_probability_score": round(rep.mean_ranked_probability_score, 6),
        "mean_brier_at_least_one_goal": round(rep.mean_brier_at_least_one_goal, 6),
        "pit_interval_80_coverage": round(rep.pit_interval_80_coverage, 6),
        "pit_interval_80_error": round(rep.pit_interval_80_error, 6),
        "reliability_at_least_one_goal": buckets,
    }


def serialize_result(res: AttackingHarnessResult) -> dict[str, Any]:
    return {
        "contract_version": "1.0",
        "phase": 3,
        "stage": "C_attacking_goals",
        "total_predictions": res.total_predictions,
        "leakage_failures": res.leakage_failures,
        "folds_by_season": res.folds_by_season,
        "best_baseline": res.best_baseline_name,
        "overall": {b: serialize_report(rep) for b, rep in res.overall.items()},
        "by_season": {
            ssn: {b: serialize_report(rep) for b, rep in b_dict.items()}
            for ssn, b_dict in res.by_season.items()
        },
        "by_position": {
            pos: {b: serialize_report(rep) for b, rep in b_dict.items()}
            for pos, b_dict in res.by_position.items()
        },
        "by_home_away": {
            ha: {b: serialize_report(rep) for b, rep in b_dict.items()}
            for ha, b_dict in res.by_home_away.items()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Stage C attacking goals walk-forward harness")
    parser.add_argument("--season", help="Filter evaluation to a single season")
    parser.add_argument("--save-json", help="Path to save verbatim JSON report")
    args = parser.parse_args()

    con = connect()
    try:
        seasons_filter = [args.season] if args.season else None
        res = run_attacking_harness(con, seasons=seasons_filter)
        print("=== Stage C Attacking Goals Baseline Walk-Forward Results ===")
        print(f"Total predictions: {res.total_predictions}")
        print(f"Folds by season: {res.folds_by_season}")
        print(f"Best baseline: {res.best_baseline_name}\n")
        print("Overall Scores:")
        for b_name in res.baseline_names:
            rep = res.overall[b_name]
            print(
                f"  {b_name:35s} | log_score={rep.mean_log_score:.5f} | "
                f"RPS={rep.mean_ranked_probability_score:.5f} | "
                f"Brier(>=1)={rep.mean_brier_at_least_one_goal:.5f} | "
                f"PIT80_err={rep.pit_interval_80_error:.4f}"
            )

        print("\nPer-Season Mean Log Score:")
        for ssn, b_map in res.by_season.items():
            line = [f"{ssn}:"]
            for b_name in res.baseline_names:
                line.append(f"{b_name}={b_map[b_name].mean_log_score:.5f}")
            print("  " + " | ".join(line))

        data = serialize_result(res)
        if args.save_json:
            out_path = Path(args.save_json)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            print(f"\nSaved verbatim JSON to {out_path}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
