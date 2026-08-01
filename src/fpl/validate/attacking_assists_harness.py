"""Run the Stage C (player attacking assists) walk-forward defined by
`config/phase3_stage_c_assists_evaluation.yaml`.

    uv run python -m fpl.validate.attacking_assists_harness

A clean mirror of ``fpl.validate.attacking_harness`` (the goals component) for the assists
label. Stage C assists predicts a discrete Poisson count distribution over player assists
(0..10) at ``(season, code, fixture)`` grain over the registered FPL player population. This
harness fits and refits the two frozen Stage C attacking assists baselines inside every fold
and scores them on identical rows. It reuses the goals harness's fold and population machinery
(the same observed-gameweek folds, the same expanding-window warmup, the same leakage assertion)
and the generic count-distribution scorer ``score_attacking_predictions``; only the label
(assists) and its signals (expected_assists / creativity) differ from the goals path.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import duckdb

from fpl.config import Phase3StageCAssistsEvaluationConfig, load_phase3_stage_c_assists_evaluation
from fpl.models.attacking_assists_baselines import (
    AssistHistoryRow,
    PositionalAssistRateBaseline,
    TrailingPlayerAssistRateBaseline,
)
from fpl.models.attacking_baselines import GoalCountDistribution, TargetRowProjection
from fpl.storage.db import connect
from fpl.types import Position
from fpl.validate.attacking_metrics import AttackingScoreReport, score_attacking_predictions

logger = logging.getLogger("fpl.validate.attacking_assists_harness")

STAGE_C_ATTACKING_ASSISTS_BASELINE_ORDER: tuple[str, ...] = (
    "positional_assist_rate_poisson",
    "trailing_player_assist_rate_poisson",
)


class AssistsCandidate(Protocol):
    """A fold-local fitted attacking-assists predictor with the baseline predict/parameters shape.

    Mirrors ``AttackingCandidate``. A Stage C assists candidate is fitted inside
    :func:`run_assists_fold` on the exact history the baselines use, so it is scored on the
    identical eligible rows. The harness never imports a candidate model: a development runner
    supplies a factory returning an object conforming to this protocol. The default harness path
    passes no factory and is baseline-only.

    A fixture-coupled candidate may additionally define ``prepare(self, *, targets, con, as_of)``;
    the harness calls it (duck-typed) after fitting.
    """

    name: str

    def predict(self, target: TargetRowProjection) -> GoalCountDistribution: ...

    def parameters(self) -> Mapping[str, float | int | bool | str]: ...

    def path_for(self, target: TargetRowProjection) -> str:
        """The estimator path taken for one target (development diagnostic, never a gate)."""


AssistsCandidateFactory = Callable[[Sequence[AssistHistoryRow]], AssistsCandidate]


@dataclass(frozen=True, slots=True)
class AssistsTargetPredictionRecord:
    target: TargetRowProjection
    observed_assists: int
    predictions: dict[str, GoalCountDistribution]
    is_cold_start: bool
    candidate_paths: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AssistsHarnessResult:
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
    candidate_names: tuple[str, ...] = ()
    parameters_by_fold: dict[str, dict[str, dict[str, float | int | bool | str]]] = field(
        default_factory=dict
    )
    candidate_path_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    candidate_path_counts_by_season: dict[str, dict[str, dict[str, int]]] = field(
        default_factory=dict
    )


def assert_no_assists_leakage(targets: Sequence[TargetRowProjection], as_of: str) -> None:
    """Verify that no target row has kickoff_time < as_of (as_of is min kickoff of the GW)."""
    for target in targets:
        if target.kickoff_time < as_of:
            msg = (
                f"Leakage failure: target row {target.season} GW{target.gw} "
                f"fixture {target.fixture} code {target.code} kickoff {target.kickoff_time} "
                f"is before fold cutoff as_of {as_of}"
            )
            raise ValueError(msg)


def run_assists_fold(
    con: duckdb.DuckDBPyConnection,
    season: str,
    gw: int,
    *,
    candidate_factory: AssistsCandidateFactory | None = None,
) -> tuple[
    str, list[AssistsTargetPredictionRecord], dict[str, dict[str, float | int | bool | str]]
]:
    """Run fit and prediction for one (season, gw) assists fold.

    When ``candidate_factory`` is supplied the candidate is fitted on the same ``history_rows``
    the baselines use and predicts the same ``targets``, so identical eligible rows is structural.
    """
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

    # 2. Query prior training history (kickoff_time < as_of). `expected_assists` (xA) and
    # `creativity` are selected raw -- NULL means unmeasured and is preserved (never zero-filled);
    # the v1.0 baselines ignore them and Candidate V1 reads them.
    history_df = con.sql(
        """
        SELECT season, gw, fixture,
               strftime(kickoff_time, '%Y-%m-%dT%H:%M:%SZ') AS kickoff_time,
               code, position, COALESCE(assists, 0) AS assists,
               expected_assists, creativity
        FROM mart_fact_player_fixture
        WHERE minutes IS NOT NULL AND kickoff_time < ?
        ORDER BY kickoff_time, season, fixture, code
        """,
        params=[as_of],
    ).pl()
    history_df = history_df.sort(["kickoff_time", "season", "fixture", "code"], maintain_order=True)

    history_rows = [
        AssistHistoryRow(
            season=r["season"],
            gw=r["gw"],
            fixture=r["fixture"],
            kickoff_time=r["kickoff_time"],
            code=r["code"],
            position=Position.from_archive_label(r["position"]),
            assists=r["assists"],
            expected_assists=r["expected_assists"],
            creativity=r["creativity"],
        )
        for r in history_df.iter_rows(named=True)
    ]

    # 3. Query target prediction rows
    target_df = con.sql(
        """
        SELECT season, gw, fixture,
               strftime(kickoff_time, '%Y-%m-%dT%H:%M:%SZ') AS kickoff_time,
               code, position, team_id, opponent_team_id, was_home,
               COALESCE(assists, 0) AS assists
        FROM mart_fact_player_fixture
        WHERE minutes IS NOT NULL AND season = ? AND gw = ?
        ORDER BY kickoff_time, fixture, code
        """,
        params=[season, gw],
    ).pl()
    target_df = target_df.sort(["kickoff_time", "fixture", "code"], maintain_order=True)

    targets: list[TargetRowProjection] = []
    observed_assists: list[int] = []
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
        observed_assists.append(r["assists"])

    assert_no_assists_leakage(targets, as_of)

    prior_codes = {r.code for r in history_rows}

    # Fit baselines
    b_pos = PositionalAssistRateBaseline()
    b_pos.fit(history_rows)

    b_trail = TrailingPlayerAssistRateBaseline(alpha=5.0)
    b_trail.fit(history_rows)

    # Fit the development candidate (if any) on the SAME history the baselines used.
    candidate_parameters: dict[str, dict[str, float | int | bool | str]] = {}
    fitted_candidate: AssistsCandidate | None = None
    if candidate_factory is not None:
        fitted_candidate = candidate_factory(history_rows)
        if fitted_candidate.name in {
            "positional_assist_rate_poisson",
            "trailing_player_assist_rate_poisson",
        }:
            raise RuntimeError(
                f"development candidate name {fitted_candidate.name!r} collides with a required "
                "Stage C attacking assists baseline"
            )
        candidate_parameters[fitted_candidate.name] = dict(fitted_candidate.parameters())

    # Optional fixture-coupled prepare hook (duck-typed; the baselines-only path is unchanged).
    if fitted_candidate is not None and hasattr(fitted_candidate, "prepare"):
        fitted_candidate.prepare(targets=targets, con=con, as_of=as_of)

    # Predict
    records: list[AssistsTargetPredictionRecord] = []
    for target, assists in zip(targets, observed_assists, strict=True):
        p_pos = b_pos.predict(target)
        p_trail = b_trail.predict(target)

        is_cold = target.code not in prior_codes
        preds: dict[str, GoalCountDistribution] = {
            "positional_assist_rate_poisson": p_pos,
            "trailing_player_assist_rate_poisson": p_trail,
        }
        cand_paths: dict[str, str] = {}
        if fitted_candidate is not None:
            preds[fitted_candidate.name] = fitted_candidate.predict(target)
            cand_paths[fitted_candidate.name] = fitted_candidate.path_for(target)
        records.append(
            AssistsTargetPredictionRecord(
                target=target,
                observed_assists=assists,
                predictions=preds,
                is_cold_start=is_cold,
                candidate_paths=cand_paths,
            )
        )

    fold_label = f"{season}-GW{gw:02d}"
    return fold_label, records, candidate_parameters


def run_assists_harness(
    con: duckdb.DuckDBPyConnection,
    *,
    config: Phase3StageCAssistsEvaluationConfig | None = None,
    seasons: Sequence[str] | None = None,
    candidate_factory: AssistsCandidateFactory | None = None,
) -> AssistsHarnessResult:
    """Run the 181-fold Stage C attacking assists walk-forward evaluation.

    By default this is baselines-only. A separately named development runner may opt in one
    fold-local candidate via ``candidate_factory``; the candidate is fitted on the identical fold
    history and predicts the identical targets, so identical eligible rows is structural. No
    promotion gate is executed on either path.
    """
    if config is None:
        config = load_phase3_stage_c_assists_evaluation()

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
    warmup_n = config.training.minimum_observed_gameweeks
    scoring_folds = all_observed_folds[warmup_n:]

    if seasons is not None:
        season_set = set(seasons)
        scoring_folds = [f for f in scoring_folds if f[0] in season_set]

    all_records_by_fold: dict[str, list[AssistsTargetPredictionRecord]] = {}
    folds_by_season: dict[str, int] = defaultdict(int)
    parameters_by_fold: dict[str, dict[str, dict[str, float | int | bool | str]]] = {}

    for ssn, gw in scoring_folds:
        fold_label, records, fold_cand_params = run_assists_fold(
            con, ssn, gw, candidate_factory=candidate_factory
        )
        all_records_by_fold[fold_label] = records
        folds_by_season[ssn] += 1
        if fold_cand_params:
            parameters_by_fold[fold_label] = fold_cand_params

    baseline_names = STAGE_C_ATTACKING_ASSISTS_BASELINE_ORDER

    cand_name_set: set[str] = set()
    for recs in all_records_by_fold.values():
        for record in recs:
            cand_name_set.update(record.predictions.keys())
    candidate_names: tuple[str, ...] = tuple(
        name for name in sorted(cand_name_set) if name not in baseline_names
    )
    all_model_names: tuple[str, ...] = (*baseline_names, *candidate_names)

    def score_collection(
        recs: Sequence[AssistsTargetPredictionRecord], model_name: str
    ) -> AttackingScoreReport:
        preds = [r.predictions[model_name] for r in recs]
        targets = [r.observed_assists for r in recs]
        cold_count = sum(1 for r in recs if r.is_cold_start)
        return score_attacking_predictions(
            preds, targets, cold_starts=cold_count, seed=config.training.seed
        )

    all_recs: list[AssistsTargetPredictionRecord] = [
        r for rec_list in all_records_by_fold.values() for r in rec_list
    ]
    total_preds = len(all_recs)

    # Population equality: every model scored the same eligible rows.
    if all_model_names:
        per_model_counts = {
            name: sum(1 for r in all_recs if name in r.predictions) for name in all_model_names
        }
        if set(per_model_counts.values()) != {total_preds}:
            raise RuntimeError(
                "Stage C assists models did not score the same eligible population: "
                f"{per_model_counts}, eligible={total_preds}"
            )

    overall: dict[str, AttackingScoreReport] = {
        name: score_collection(all_recs, name) for name in all_model_names
    }

    by_fold: dict[str, dict[str, AttackingScoreReport]] = {}
    for f_label, recs in all_records_by_fold.items():
        by_fold[f_label] = {name: score_collection(recs, name) for name in all_model_names}

    recs_by_season: dict[str, list[AssistsTargetPredictionRecord]] = defaultdict(list)
    for r in all_recs:
        recs_by_season[r.target.season].append(r)

    by_season: dict[str, dict[str, AttackingScoreReport]] = {}
    for ssn in sorted(recs_by_season.keys()):
        s_recs = recs_by_season[ssn]
        by_season[ssn] = {name: score_collection(s_recs, name) for name in all_model_names}

    recs_by_pos: dict[str, list[AssistsTargetPredictionRecord]] = defaultdict(list)
    for r in all_recs:
        recs_by_pos[r.target.position.value].append(r)

    by_position: dict[str, dict[str, AttackingScoreReport]] = {}
    for pos in sorted(recs_by_pos.keys()):
        p_recs = recs_by_pos[pos]
        by_position[pos] = {name: score_collection(p_recs, name) for name in all_model_names}

    recs_by_ha: dict[str, list[AssistsTargetPredictionRecord]] = defaultdict(list)
    for r in all_recs:
        ha_key = "home" if r.target.was_home else "away"
        recs_by_ha[ha_key].append(r)

    by_home_away: dict[str, dict[str, AttackingScoreReport]] = {}
    for ha in ("home", "away"):
        ha_recs = recs_by_ha[ha]
        by_home_away[ha] = {name: score_collection(ha_recs, name) for name in all_model_names}

    candidate_path_counts: dict[str, dict[str, int]] = {name: {} for name in candidate_names}
    for r in all_recs:
        for cname, path in r.candidate_paths.items():
            tally = candidate_path_counts[cname]
            tally[path] = tally.get(path, 0) + 1
    candidate_path_counts_by_season: dict[str, dict[str, dict[str, int]]] = {
        name: {} for name in candidate_names
    }
    for ssn, s_recs in recs_by_season.items():
        for cname in candidate_names:
            season_tally: dict[str, int] = {}
            for r in s_recs:
                path_label = r.candidate_paths.get(cname)
                if path_label is not None:
                    season_tally[path_label] = season_tally.get(path_label, 0) + 1
            if season_tally:
                candidate_path_counts_by_season[cname][ssn] = season_tally

    best_b_name = min(baseline_names, key=lambda b: overall[b].mean_log_score)

    return AssistsHarnessResult(
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
        candidate_names=candidate_names,
        parameters_by_fold=parameters_by_fold,
        candidate_path_counts=candidate_path_counts,
        candidate_path_counts_by_season=candidate_path_counts_by_season,
    )


def serialize_report(rep: AttackingScoreReport) -> dict[str, Any]:
    """Serialize an assists score report. Assist-named keys (the reused report's
    ``mean_brier_at_least_one_goal`` field is the generic P(count >= 1) Brier)."""
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
        "mean_brier_at_least_one_assist": round(rep.mean_brier_at_least_one_goal, 6),
        "pit_interval_80_coverage": round(rep.pit_interval_80_coverage, 6),
        "pit_interval_80_error": round(rep.pit_interval_80_error, 6),
        "reliability_at_least_one_assist": buckets,
    }


def serialize_result(res: AssistsHarnessResult, *, contract_version: str = "1.0") -> dict[str, Any]:
    return {
        "contract_version": contract_version,
        "phase": 3,
        "stage": "C_attacking_assists",
        "total_predictions": res.total_predictions,
        "leakage_failures": res.leakage_failures,
        "folds_by_season": res.folds_by_season,
        "best_baseline": res.best_baseline_name,
        "candidate_names": list(res.candidate_names),
        "candidate_path_counts": res.candidate_path_counts,
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
    parser = argparse.ArgumentParser(
        description="Run Stage C attacking assists walk-forward harness"
    )
    parser.add_argument("--season", help="Filter evaluation to a single season")
    parser.add_argument("--save-json", help="Path to save verbatim JSON report")
    args = parser.parse_args()

    con = connect()
    try:
        seasons_filter = [args.season] if args.season else None
        res = run_assists_harness(con, seasons=seasons_filter)
        contract = load_phase3_stage_c_assists_evaluation()
        print("=== Stage C Attacking Assists Baseline Walk-Forward Results ===")
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

        data = serialize_result(res, contract_version=contract.contract_version)
        if args.save_json:
            out_path = Path(args.save_json)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            print(f"\nSaved verbatim JSON to {out_path}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
