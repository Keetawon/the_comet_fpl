"""One retrospective SOT increment over the exactly reproduced weekly goals+xG control.

The frozen estimators, source interpretation and prior results are reused unchanged. This
entry point requires an explicit immutable historical database and cannot promote a model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import platform
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, replace
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any, Literal

import duckdb
import polars as pl
import yaml
from pydantic import BaseModel, ConfigDict, Field

from fpl.config import V2RealSotRetrospectiveContract, config_dir, repo_root
from fpl.features.pit import AsOf
from fpl.models.football_engine_v2 import SignalSpec
from fpl.storage.db import connect
from fpl.validate import dev_v2_corroborated_sot as corroborated
from fpl.validate import dev_v2_real_sot as prior
from fpl.validate import dev_v2_weekly_inner as weekly
from fpl.validate.metrics import log_score, poisson_pmf, relative_lift
from fpl.validate.minutes_metrics import _reliability_curve
from fpl.validate.sot_zero_audit import INTERPRETED_COLUMN, CorroboratedSotBackfillView
from fpl.validate.v2_environment_harness import (
    Prediction,
    load_team_frame,
    observed_folds,
    promoted_team_codes,
)
from fpl.validate.weekly_inner_selection import SIGNALS, WeeklyRefitTeamEngine

CONFIG_FILE = "v2_weekly_sot_evaluation.yaml"
RESULT_FILE = "v2_weekly_sot_development.json"
CANDIDATE = "retrospective_goals_xg_sot_weekly_inner_selection_v1"
CONTROL = weekly.CANDIDATE
EVIDENCE_CLASS = "retrospective_backfill_development"
DATABASE_SHA256 = "0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8"
MANIFEST_SHA256 = "084137d2e03babbf9d8361e49be0f23ba19ae3baed34c5d9d0605264ea37057f"
COVERAGE_SHA256 = "7b37ce3998f1f252a6b1d7ea7978b1f916f7bf414eb8c942eae87e2bc50c5a6d"
WeeklySotEvaluationError = prior.RetrospectiveEvaluationError
WalkForwardRun = weekly.WalkForwardRun
logger = logging.getLogger(__name__)
_KEYS = ["season", "fixture", "team_code"]
_INPUT_COLUMNS = [*weekly._INPUT_COLUMNS, INTERPRETED_COLUMN]


class WeeklySotEvaluationContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_version: Literal["1.0"]
    candidate: Literal["retrospective_goals_xg_sot_weekly_inner_selection_v1"]
    control: Literal["retrospective_goals_xg_weekly_inner_selection_v1"]
    evidence_class: Literal["retrospective_backfill_development"]
    base_contract: Literal["config/v2_real_sot_retrospective_evaluation.yaml"]
    base_contract_sha256: Literal[
        "73ebf92613b8efb39838079b42b576afea2f2d43c775758372293c4d64edaed0"
    ]
    sot_contract: Literal["config/v2_corroborated_zero_sot_evaluation.yaml"]
    sot_contract_sha256: Literal["ef0bc8a6068931a13b0331451abaa728eba7936c314228bca76bd4622aeaf8d0"]
    control_reference: Literal["results/v2_weekly_inner_selection_development.json"]
    control_reference_sha256: Literal[
        "79f3a0815271a95cd0e39874aaa20fa89d3b1df0875a5e780c0317a961424d35"
    ]
    signals: tuple[
        Literal["goals"], Literal["expected_goals"], Literal["shots_on_target_corroborated"]
    ]
    selection_schedule: Literal["weekly_refit"]
    expected_rows: Literal[2280]
    expected_folds: Literal[114]
    control_absolute_tolerance: float = Field(ge=1e-12, le=1e-12)
    formal_outer_runs: Literal[1]
    retain_fixture_distributions: Literal[True]
    require_clean_worktree: Literal[True]
    promotion_permitted: Literal[False]


def load_contract(
    path: Path, *, root: Path
) -> tuple[
    WeeklySotEvaluationContract,
    V2RealSotRetrospectiveContract,
    corroborated.SotZeroEvaluationContract,
]:
    contract = WeeklySotEvaluationContract.model_validate(yaml.safe_load(path.read_bytes()))
    for relative, expected in (
        (contract.base_contract, contract.base_contract_sha256),
        (contract.sot_contract, contract.sot_contract_sha256),
        (contract.control_reference, contract.control_reference_sha256),
    ):
        if prior.file_sha256(root / relative) != expected:
            raise WeeklySotEvaluationError(f"frozen registration input changed: {relative}")
    base, _ = prior._load_contract(root / contract.base_contract)
    sot = corroborated.SotZeroEvaluationContract.model_validate(
        yaml.safe_load((root / contract.sot_contract).read_bytes())
    )
    if sot.base_contract != contract.base_contract or (
        sot.base_contract_sha256 != contract.base_contract_sha256
    ):
        raise WeeklySotEvaluationError("SOT and weekly control inherit different estimators")
    return contract, base, sot


class WeeklySotTeamEngine(WeeklyRefitTeamEngine):
    """The same weekly selector with exactly one additional, licensed SOT column."""

    name = CANDIDATE
    evidence_class = EVIDENCE_CLASS

    def __init__(self, base: V2RealSotRetrospectiveContract) -> None:
        policy, walk = base.engine, base.walk_forward
        super().__init__(
            half_life_days=policy.half_life_days,
            prior_matches=policy.prior_matches,
            minimum_team_matches=walk.minimum_team_matches,
            inner_holdout_gameweeks=walk.inner_holdout_observed_gameweeks,
            minimum_inner_training_gameweeks=walk.minimum_inner_training_observed_gameweeks,
            weight_step=policy.weight_step,
            minimum_signal_coverage=policy.minimum_signal_coverage,
            promoted_attack_prior=policy.promoted_attack_prior,
            promoted_defence_prior=policy.promoted_defence_prior,
            rate_floor=policy.rate_floor,
            maximum_goals=policy.maximum_goals,
        )
        self._signals = (*SIGNALS, SignalSpec("shots_on_target", INTERPRETED_COLUMN))


def run_control_walk_forward(
    con: duckdb.DuckDBPyConnection, base: V2RealSotRetrospectiveContract
) -> WalkForwardRun:
    return weekly.run_candidate_walk_forward(con, base)


def verify_control_reproduction(
    control_run: WalkForwardRun,
    frozen_result: Mapping[str, Any],
    base: V2RealSotRetrospectiveContract,
    *,
    tolerance: float = 1e-12,
    expected_rows: int = 2280,
    expected_folds: int = 114,
) -> dict[str, Any]:
    """Reproduce the frozen weekly model, including its reference-owned reporting slices."""
    check = weekly._assert_equal
    for actual, expected, label in (
        (len(control_run.predictions), expected_rows, "current rows"),
        (len(control_run.folds), expected_folds, "current folds"),
        (frozen_result["rows_scored"], expected_rows, "reference rows"),
        (frozen_result["folds"], expected_folds, "reference folds"),
        (frozen_result["candidate"], CONTROL, "reference weekly candidate"),
        (frozen_result["eligible_seasons"], list(base.population.eligible_seasons), "seasons"),
    ):
        check(actual, expected, tolerance=tolerance, path=label)
    references = frozen_result["fixture_predictions"]
    if len(references) != expected_rows or len(control_run.contexts) != expected_rows:
        raise WeeklySotEvaluationError("control reference has incomplete fixture evidence")
    contexts: dict[str, dict[str, Any]] = {}
    predictions: list[Prediction] = []
    maximum_difference, cold_disagreements = 0.0, 0
    for row, reference in zip(control_run.predictions, references, strict=True):
        context = control_run.contexts[row.key]
        identity = {
            "key": row.key,
            "observed_goals": row.observed,
            **{
                key: value
                for key, value in context.items()
                if key not in {"cold_start", "model_cold_start"}
            },
        }
        check(identity, {k: reference[k] for k in identity}, tolerance=tolerance, path=row.key)
        pmf = reference["distributions"][CONTROL]
        check(row.distribution, pmf, tolerance=tolerance, path=f"{row.key}.PMF")
        check(
            log_score(row.distribution, row.observed),
            reference["log_losses"][CONTROL],
            tolerance=tolerance,
            path=f"{row.key}.log_loss",
        )
        maximum_difference = max(
            maximum_difference,
            max(abs(a - b) for a, b in zip(row.distribution, pmf, strict=True)),
        )
        if not isinstance(reference["cold_start"], bool):
            raise WeeklySotEvaluationError("reference cold-start label is not Boolean")
        model_cold = context.get("model_cold_start", row.cold_start)
        cold_disagreements += model_cold != reference["cold_start"]
        predictions.append(replace(row, cold_start=reference["cold_start"]))
        contexts[row.key] = {
            **context,
            "cold_start": reference["cold_start"],
            "model_cold_start": model_cold,
        }
    blocks = {CONTROL: predictions}
    overall = prior._score_models(blocks, seed=base.random_seed)
    check(overall[CONTROL], frozen_result["overall"][CONTROL], tolerance=tolerance, path="overall")
    slices = weekly._slice_scores(blocks, contexts, seed=base.random_seed)
    check(sorted(slices), sorted(frozen_result["by_slice"]), tolerance=tolerance, path="slice keys")
    for label, scores in slices.items():
        check(
            scores[CONTROL],
            frozen_result["by_slice"][label][CONTROL],
            tolerance=tolerance,
            path=label,
        )
    reference_folds = frozen_result["fold_parameters"]
    reference_scores = frozen_result["by_fold"]
    if len(reference_folds) != expected_folds or len(reference_scores) != expected_folds:
        raise WeeklySotEvaluationError("reference fold evidence is incomplete")
    for fold, reference, scores in zip(
        control_run.folds, reference_folds, reference_scores, strict=True
    ):
        label = f"fold:{fold['season']}:{fold['gw']}"
        for key, value in fold.items():
            reference_key = (
                f"candidate_{key}"
                if key
                in {"parameters", "signal_fit", "inner_scores", "inner_diagnostics", "guards"}
                else key
            )
            check(value, reference[reference_key], tolerance=tolerance, path=f"{label}.{key}")
        identity = {k: fold[k] for k in ("season", "gw", "as_of")}
        check(identity, {k: scores[k] for k in identity}, tolerance=tolerance, path=label)
        selected = [p for p in predictions if (p.season, p.gw) == (fold["season"], fold["gw"])]
        check(
            prior._score_block(CONTROL, selected, seed=base.random_seed),
            scores["models"][CONTROL],
            tolerance=tolerance,
            path=f"{label}.scores",
        )
    # The old comparison deliberately scored both models on its older control's labels.
    # Preserve those immutable populations; keep the weekly engine's own label explicitly.
    control_run.predictions, control_run.contexts = predictions, contexts
    return {
        "pass": True,
        "rows": expected_rows,
        "folds": expected_folds,
        "absolute_tolerance": tolerance,
        "maximum_pmf_absolute_difference": maximum_difference,
        "mean_log_score": overall[CONTROL]["mean_log_score"],
        "crps": overall[CONTROL]["crps"],
        "all_fixture_scores_parameters_and_inner_diagnostics_agree": True,
        "cold_start_slice_owner": "frozen weekly artifact reference labels",
        "model_vs_reference_cold_start_disagreements": cold_disagreements,
    }


def run_candidate_walk_forward(
    con: duckdb.DuckDBPyConnection,
    base: V2RealSotRetrospectiveContract,
    audit: Mapping[str, Any],
) -> WalkForwardRun:
    frame = load_team_frame(con, provider="fpl_archive").select(weekly._INPUT_COLUMNS)
    promoted = promoted_team_codes(con)
    folds = [
        fold
        for fold in observed_folds(
            frame, minimum_prior_gameweeks=base.walk_forward.minimum_training_observed_gameweeks
        )
        if fold[0] in base.population.eligible_seasons
    ]
    run = WalkForwardRun([], {}, [])
    for index, (season, gw, cutoff) in enumerate(folds, 1):
        logger.info("Weekly SOT candidate fold %s/%s: %s GW%s", index, len(folds), season, gw)
        training = frame.filter(pl.col("kickoff_time") < cutoff)
        target = frame.filter((pl.col("season") == season) & (pl.col("gw") == gw))
        history = CorroboratedSotBackfillView(con, AsOf(cutoff), audit).observed_corroborated_sot()
        if (
            training.join(target.select(_KEYS), on=_KEYS, how="inner").height
            or history.filter(pl.col("kickoff_time") >= cutoff).height
            or history.join(target.select(_KEYS), on=_KEYS, how="inner").height
        ):
            raise WeeklySotEvaluationError("future event or target GW entered training")
        augmented = training.join(
            history.select([*_KEYS, INTERPRETED_COLUMN]),
            on=_KEYS,
            how="left",
            validate="1:1",
            maintain_order="left",
        ).select(_INPUT_COLUMNS)
        if not augmented.select(weekly._INPUT_COLUMNS).equals(training):
            raise WeeklySotEvaluationError("SOT join changed ordered archive inputs")
        engine = WeeklySotTeamEngine(base)
        engine.set_promoted(promoted)
        engine.set_prediction_season(season)
        engine.fit_as_of(augmented, AsOf(cutoff))
        measured = history.filter(pl.col(INTERPRETED_COLUMN).is_not_null())
        attack_counts = dict(measured.group_by("team_code").len().iter_rows())
        defence_counts = dict(measured.group_by("opponent_team_code").len().iter_rows())
        for row in target.iter_rows(named=True):
            if row["goals"] is None:
                raise WeeklySotEvaluationError("a preregistered target was not scored")
            team, opponent, home = (
                int(row["team_code"]),
                int(row["opponent_team_code"]),
                bool(row["was_home"]),
            )
            key = f"{season}:{row['fixture']}:{team}"
            if key in run.contexts:
                raise WeeklySotEvaluationError(f"duplicate prediction identity: {key}")
            pmf = poisson_pmf(
                engine.goal_rate(team, opponent, home), max_goals=base.engine.maximum_goals
            )
            if any(not math.isfinite(p) or p < 0 for p in pmf) or not math.isclose(
                sum(pmf), 1, rel_tol=0, abs_tol=1e-12
            ):
                raise WeeklySotEvaluationError("invalid probability distribution")
            cold = engine.is_cold_start(team, opponent)
            count = min(int(attack_counts.get(team, 0)), int(defence_counts.get(opponent, 0)))
            run.predictions.append(
                Prediction(
                    season,
                    gw,
                    key,
                    pmf,
                    int(row["goals"]),
                    home,
                    cold,
                    engine.parameters.weights.get("shots_on_target", 0) > 0,
                )
            )
            run.contexts[key] = {
                "season": season,
                "gw": gw,
                "fixture": int(row["fixture"]),
                "team_code": team,
                "opponent_team_code": opponent,
                "was_home": home,
                "promoted": team in promoted.get(season, frozenset()),
                "early_season": gw <= base.reporting.early_season_observed_gameweeks,
                "cold_start": cold,
                "as_of": cutoff.isoformat(),
                "kickoff_time": row["kickoff_time"].isoformat(),
                "sot_history_band": prior._sot_history_band(count, base.reporting.sot_history_bins),
            }
        diagnostics = engine.selector_diagnostics
        identity_columns = [
            *_KEYS,
            "capture_id",
            "source_known_at",
            "payload_sha256",
            "shots_on_target",
            INTERPRETED_COLUMN,
            "sot_interpretation",
        ]
        run.folds.append(
            {
                "season": season,
                "gw": gw,
                "as_of": cutoff.isoformat(),
                "training_rows": training.height,
                "target_rows": target.height,
                "training_input_sha256": hashlib.sha256(training.write_json().encode()).hexdigest(),
                "candidate_input_sha256": hashlib.sha256(
                    augmented.write_json().encode()
                ).hexdigest(),
                "sot_training_identity_sha256": hashlib.sha256(
                    history.select(identity_columns).sort(_KEYS).write_json().encode()
                ).hexdigest(),
                "retrospective_rows": history.height,
                "retrospective_sot_non_null": measured.height,
                "later_known_rows_permitted": history.filter(
                    pl.col("source_known_at") > cutoff
                ).height,
                "sot_interpretation_counts": dict(Counter(history["sot_interpretation"].to_list())),
                "parameters": engine.parameters.as_report(),
                "signal_fit": prior._fitted_signal_report(engine),
                "inner_scores": {
                    name: stage.get("selected_score") for name, stage in diagnostics.items()
                },
                "inner_diagnostics": diagnostics,
                "guards": {"future_training_rows": 0, "target_gw_training_rows": 0},
            }
        )
    return run


def _p_zero_diagnostics(rows: Sequence[Prediction]) -> dict[str, Any]:
    probabilities = [row.distribution[0] for row in rows]
    observations = [int(row.observed == 0) for row in rows]
    return {
        "diagnostic_only": True,
        "rows": len(rows),
        "mean_brier_p_zero": prior._mean(
            [(p - y) ** 2 for p, y in zip(probabilities, observations, strict=True)]
        ),
        "mean_predicted_p_zero": prior._mean(probabilities),
        "observed_zero_rate": sum(observations) / len(rows),
        "reliability": asdict(
            _reliability_curve(probabilities, observations, [round(i / 10, 1) for i in range(11)])
        ),
    }


def score_run(
    control_run: WalkForwardRun,
    candidate_run: WalkForwardRun,
    base: V2RealSotRetrospectiveContract,
) -> dict[str, Any]:
    deltas = weekly._paired_rows(control_run.predictions, candidate_run.predictions)
    if control_run.contexts.keys() != candidate_run.contexts.keys():
        raise WeeklySotEvaluationError("candidate context population differs")
    for key, context in control_run.contexts.items():
        identity = {
            field: value
            for field, value in context.items()
            if field not in {"cold_start", "model_cold_start"}
        }
        weekly._assert_equal(
            identity,
            {field: candidate_run.contexts[key][field] for field in identity},
            tolerance=0,
            path=f"paired context {key}",
        )
    predictions = [
        replace(new, cold_start=old.cold_start)
        for old, new in zip(control_run.predictions, candidate_run.predictions, strict=True)
    ]
    blocks = {CONTROL: control_run.predictions, CANDIDATE: predictions}
    overall = prior._score_models(blocks, seed=base.random_seed)
    contexts = control_run.contexts
    slices = weekly._slice_scores(blocks, contexts, seed=base.random_seed)
    history_groups: dict[str, set[str]] = {}
    for key, context in candidate_run.contexts.items():
        history_groups.setdefault(f"sot_history:{context['sot_history_band']}", set()).add(key)
    for label, keys in sorted(history_groups.items()):
        slices[label] = prior._score_models(
            prior._filtered_blocks(blocks, keys), seed=base.random_seed
        )
    folds, by_fold = [], []
    checked_batches = 0
    if not control_run.folds or len(control_run.folds) != len(candidate_run.folds):
        raise WeeklySotEvaluationError("candidate fold population differs")
    for old, new in zip(control_run.folds, candidate_run.folds, strict=True):
        for key in (
            "season",
            "gw",
            "as_of",
            "training_rows",
            "target_rows",
            "training_input_sha256",
        ):
            weekly._assert_equal(old[key], new[key], tolerance=0, path=f"candidate fold {key}")
        # Adding SOT can change only the blend, never the goals-only search or its fitted system.
        for key in ("half_life_days", "prior_matches"):
            weekly._assert_equal(
                old["parameters"][key], new["parameters"][key], tolerance=0, path=key
            )
        weekly._assert_equal(
            old["inner_diagnostics"]["decay_prior"],
            new["inner_diagnostics"]["decay_prior"],
            tolerance=0,
            path="goals selector",
        )
        for evidence in (old, new):
            if any(evidence["guards"].values()):
                raise WeeklySotEvaluationError("outer event-time/batch guard failure")
            for stage in evidence["inner_diagnostics"].values():
                for batch in stage["batches"]:
                    checked_batches += 1
                    latest = batch["training_latest_kickoff"]
                    if (
                        batch["event_time_violations"]
                        or batch["target_gameweek_overlap"]
                        or (
                            latest is not None
                            and datetime.fromisoformat(latest)
                            >= datetime.fromisoformat(batch["as_of"])
                        )
                    ):
                        raise WeeklySotEvaluationError("inner event-time/batch guard failure")
        fold = {
            k: old[k]
            for k in (
                "season",
                "gw",
                "as_of",
                "training_rows",
                "target_rows",
                "training_input_sha256",
            )
        }
        fold.update(
            {
                f"{name}_{key}": value
                for name, evidence in (("control", old), ("candidate", new))
                for key, value in evidence.items()
                if key not in fold
            }
        )
        folds.append(fold)
        selected = {
            name: [p for p in rows if (p.season, p.gw) == (old["season"], old["gw"])]
            for name, rows in blocks.items()
        }
        scores = prior._score_models(selected, seed=base.random_seed)
        by_fold.append(
            {
                "season": old["season"],
                "gw": old["gw"],
                "as_of": old["as_of"],
                "models": scores,
                "candidate_minus_control_mean_log_loss": scores[CANDIDATE]["mean_log_score"]
                - scores[CONTROL]["mean_log_score"],
            }
        )
    control, candidate = overall[CONTROL], overall[CANDIDATE]
    log_lift = relative_lift(control["mean_log_score"], candidate["mean_log_score"])
    crps_lift = relative_lift(control["crps"], candidate["crps"])
    policy = base.development_gate
    season_checks = {
        s: slices[f"season:{s}"][CANDIDATE]["mean_log_score"]
        <= slices[f"season:{s}"][CONTROL]["mean_log_score"]
        for s in base.population.eligible_seasons
        if f"season:{s}" in slices
    }
    checks = {
        "minimum_relative_log_lift": {
            "threshold": policy.minimum_relative_log_lift,
            "actual": log_lift,
            "pass": log_lift >= policy.minimum_relative_log_lift,
        },
        "maximum_crps_relative_regression": {
            "threshold": policy.maximum_crps_relative_regression,
            "actual_relative_lift": crps_lift,
            "pass": crps_lift >= -policy.maximum_crps_relative_regression,
        },
        "pit_interval_80_maximum_absolute_error": {
            "threshold": policy.pit_interval_80_maximum_absolute_error,
            "actual": candidate["pit_interval_80_absolute_error"],
            "pass": candidate["pit_interval_80_absolute_error"]
            <= policy.pit_interval_80_maximum_absolute_error,
        },
        "no_season_log_score_regression": {
            "by_season": season_checks,
            "pass": all(season_checks.values()),
        },
        "event_time_and_batch_isolation": {
            "pass": True,
            "violations": 0,
            "checked_inner_stage_batches": checked_batches,
        },
        "identical_population": {"pass": True, "rows": len(deltas)},
    }
    passed = all(check["pass"] for check in checks.values())
    paired = prior._paired_diagnostics(control_run.predictions, predictions)
    paired["unweighted_gw_mean_log_loss_standard_error"] = paired.pop(
        "paired_gameweek_log_loss_standard_error"
    )
    uncertainty = weekly.clustered_loss_uncertainty(control_run.predictions, predictions)
    uncertainty["negative_difference_favours"] = CANDIDATE
    fixture_predictions: list[dict[str, Any]] = []
    fixture_losses: dict[tuple[str, int], list[float]] = {}
    for old_row, new_row, delta in zip(control_run.predictions, predictions, deltas, strict=True):
        context = contexts[old_row.key]
        fixture_predictions.append(
            {
                "key": old_row.key,
                **context,
                "observed_goals": old_row.observed,
                "candidate_model_cold_start": candidate_run.contexts[old_row.key]["cold_start"],
                "sot_history_band": candidate_run.contexts[old_row.key]["sot_history_band"],
                "distributions": {CONTROL: old_row.distribution, CANDIDATE: new_row.distribution},
                "log_losses": {
                    CONTROL: log_score(old_row.distribution, old_row.observed),
                    CANDIDATE: log_score(new_row.distribution, new_row.observed),
                },
                "candidate_minus_control_log_loss": delta,
            }
        )
        fixture_losses.setdefault((old_row.season, context["fixture"]), []).append(delta)
    zero_diagnostics = {
        "overall": {name: _p_zero_diagnostics(rows) for name, rows in blocks.items()}
    }
    for season in base.population.eligible_seasons:
        selected = {name: [p for p in rows if p.season == season] for name, rows in blocks.items()}
        if selected[CONTROL]:
            zero_diagnostics[f"season:{season}"] = {
                name: _p_zero_diagnostics(rows) for name, rows in selected.items()
            }
    return {
        "schema_version": 1,
        "candidate": CANDIDATE,
        "control": CONTROL,
        "status": "development_only",
        "evidence_class": EVIDENCE_CLASS,
        "verdict": "SUPPORTED_FOR_DEVELOPMENT"
        if passed
        else "REFUTED"
        if log_lift <= 0
        else "INCONCLUSIVE",
        "promotion_permitted": False,
        "signals": ["goals", "expected_goals", INTERPRETED_COLUMN],
        "eligible_seasons": base.population.eligible_seasons,
        "rows_scored": len(deltas),
        "folds": len(folds),
        "overall": overall,
        "by_slice": slices,
        "by_fold": by_fold,
        "candidate_vs_control": {
            "relative_log_score_lift": log_lift,
            "relative_crps_lift": crps_lift,
            **paired,
            **uncertainty,
        },
        "development_gate": {"pass": passed, "checks": checks},
        "fold_parameters": folds,
        "fixture_predictions": fixture_predictions,
        "paired_fixture_loss_differences": [
            {
                "season": s,
                "fixture": f,
                "team_rows": len(values),
                "sum": sum(values),
                "mean": prior._mean(values),
            }
            for (s, f), values in fixture_losses.items()
        ],
        "parameter_diagnostics": {
            "candidate_sot_weight_distribution": dict(
                sorted(
                    Counter(
                        str(f["candidate_parameters"].get("weight_shots_on_target", 0))
                        for f in folds
                    ).items()
                )
            ),
            "candidate_sot_weight_zero_folds": sum(
                f["candidate_parameters"].get("weight_shots_on_target", 0) == 0 for f in folds
            ),
            "goals_decay_prior_identical": True,
        },
        "p_zero_diagnostics": zero_diagnostics,
        "caveat": (
            "Previously inspected historical archive with later-captured SOT; not independent "
            "confirmation or historical deadline knowledge-time evidence."
        ),
    }


def reserve_execution_claim(root: Path, provenance: Mapping[str, Any]) -> Path:
    path = root / "data" / "evaluation-claims" / f"{CANDIDATE}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **provenance,
        "candidate": CANDIDATE,
        "started_at_utc": datetime.now(UTC).isoformat(),
    }
    try:
        with path.open("xb") as handle:
            handle.write(prior._json_bytes(payload))
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise WeeklySotEvaluationError(
            "candidate execution already claimed; never restart after interruption"
        ) from exc
    return path


def _publish_result(path: Path, report: Mapping[str, Any]) -> None:
    payload = prior._json_bytes(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _runtime_versions() -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "python_build": sys.version,
        "executable": sys.executable,
        "implementation": platform.python_implementation(),
        "libraries": {
            name: version(name) for name in ("duckdb", "polars", "pydantic", "PyYAML", "pyarrow")
        },
    }


def run(*, root: Path, db_path: Path, config_path: Path, output_path: Path) -> dict[str, Any]:
    prior.require_clean_worktree(root)
    claim_path = root / "data" / "evaluation-claims" / f"{CANDIDATE}.json"
    if output_path.exists() or claim_path.exists():
        raise WeeklySotEvaluationError(
            "formal result or execution claim already exists; no second run"
        )
    if not db_path.is_file() or Path(f"{db_path}.wal").exists():
        raise WeeklySotEvaluationError(
            "explicit historical database must exist with no pending WAL"
        )
    contract, base, sot = load_contract(config_path, root=root)
    runtime = _runtime_versions()
    coverage_path = root / base.population.coverage_report
    manifest_path = root / "results" / prior.CAPTURE_MANIFEST_FILE
    snapshot = prior._snapshot(
        root=root,
        db_path=db_path,
        config_path=config_path,
        coverage_path=coverage_path,
        manifest_path=manifest_path,
    )
    for key, expected in (
        ("database_sha256", DATABASE_SHA256),
        ("coverage_report_sha256", COVERAGE_SHA256),
        ("capture_manifest_sha256", MANIFEST_SHA256),
    ):
        if getattr(snapshot, key) != expected:
            raise WeeklySotEvaluationError(f"frozen historical evidence changed: {key}")
    additional = (
        "src/fpl/validate/dev_v2_weekly_sot.py",
        "src/fpl/validate/weekly_inner_selection.py",
        "src/fpl/validate/dev_v2_weekly_inner.py",
        "src/fpl/validate/dev_v2_corroborated_sot.py",
        "src/fpl/validate/sot_zero_audit.py",
        "src/fpl/validate/minutes_metrics.py",
        "src/fpl/ingest/pl_sdp.py",
        "src/fpl/features/pit.py",
        "src/fpl/storage/db.py",
        "src/fpl/storage/schema.sql",
        "src/fpl/transform/pl_sdp.py",
        "src/fpl/transform/football_v2.py",
        "src/fpl/transform/football_versions.py",
        "config/pl_sdp_metrics.yaml",
        "docs/v2-weekly-sot-design.md",
        contract.base_contract,
        contract.sot_contract,
        contract.control_reference,
        sot.policy,
        sot.coverage_audit,
        "config/v2_weekly_inner_selection_evaluation.yaml",
        "results/v2_real_sot_development.json",
        "results/v2_corroborated_zero_sot_development.json",
    )
    snapshot = replace(
        snapshot,
        source_sha256={
            **snapshot.source_sha256,
            **{p: prior.file_sha256(root / p) for p in additional},
        },
    )
    frozen = json.loads((root / contract.control_reference).read_bytes())
    # New PIT infrastructure has its own committed hashes above. Every source in the
    # weekly estimator's original provenance remains unchanged, as do its prior results.
    for relative, expected in frozen["provenance"]["source_sha256"].items():
        if prior.file_sha256(root / relative) != expected:
            raise WeeklySotEvaluationError(f"frozen weekly implementation changed: {relative}")
    snapshot_args = {
        "root": root,
        "db_path": db_path,
        "config_path": config_path,
        "coverage_path": coverage_path,
        "manifest_path": manifest_path,
    }
    con = connect(db_path, read_only=True)
    try:
        audit = corroborated.validate_audit(con, sot, base)
        if (
            audit["database_sha256"] != snapshot.database_sha256
            or audit["canonical_capture_manifest_sha256"] != snapshot.capture_manifest_sha256
        ):
            raise WeeklySotEvaluationError("SOT audit belongs to different historical evidence")
        current_coverage, current_manifest = prior.build_coverage_evidence(con, base)
        frozen_coverage = json.loads(coverage_path.read_bytes())
        for key, value in current_coverage.items():
            if key != "generated_at" and frozen_coverage.get(key) != value:
                raise WeeklySotEvaluationError(f"source coverage changed: {key}")
        if current_manifest != json.loads(manifest_path.read_bytes()):
            raise WeeklySotEvaluationError("canonical SDP capture manifest changed")
        control_run = run_control_walk_forward(con, base)
        reproduction = verify_control_reproduction(
            control_run,
            frozen,
            base,
            tolerance=contract.control_absolute_tolerance,
            expected_rows=contract.expected_rows,
            expected_folds=contract.expected_folds,
        )
        prior._verify_snapshot(snapshot, **snapshot_args)
        if _runtime_versions() != runtime:
            raise WeeklySotEvaluationError("runtime libraries changed before candidate claim")
        logger.info(
            "Weekly control reproduced on %s rows / %s folds; claiming candidate ONCE",
            contract.expected_rows,
            contract.expected_folds,
        )
        claim = reserve_execution_claim(
            root,
            {
                "git_head": snapshot.head,
                "config_sha256": snapshot.config_sha256,
                "database_sha256": snapshot.database_sha256,
                "control_reference_sha256": contract.control_reference_sha256,
            },
        )
        candidate_run = run_candidate_walk_forward(con, base, audit)
    finally:
        con.close()
    if (
        len(candidate_run.predictions) != contract.expected_rows
        or len(candidate_run.folds) != contract.expected_folds
    ):
        raise WeeklySotEvaluationError("candidate population differs from preregistration")
    report = score_run(control_run, candidate_run, base)
    report["control_reproduction"] = reproduction
    report["provenance"] = {
        **asdict(snapshot),
        "git_head": snapshot.head,
        "clean_worktree": True,
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "random_seed": base.random_seed,
        "evidence_class": contract.evidence_class,
        "execution_claim_sha256": prior.file_sha256(claim),
        "runtime_versions": runtime,
        "inherited_contract_sha256": contract.base_contract_sha256,
        "sot_contract_sha256": contract.sot_contract_sha256,
        "control_reference_sha256": contract.control_reference_sha256,
        "interpretation_policy_sha256": sot.policy_sha256,
        "sdp_version_selection": base.source.version_selection,
        "original_capture_known_at_preserved": True,
        "input_columns": _INPUT_COLUMNS,
        "providers": {
            "goals": "fpl_archive",
            "expected_goals": "fpl_archive",
            INTERPRETED_COLUMN: "pl_sdp_with_frozen_corroboration",
        },
    }
    prior._verify_snapshot(snapshot, **snapshot_args)
    if _runtime_versions() != runtime:
        raise WeeklySotEvaluationError("runtime libraries changed during evaluation")
    _publish_result(output_path, report)
    logger.info(
        "%s: log lift %.6f%%",
        report["verdict"],
        report["candidate_vs_control"]["relative_log_score_lift"] * 100,
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    run(
        root=repo_root(),
        db_path=args.db,
        config_path=config_dir() / CONFIG_FILE,
        output_path=repo_root() / "results" / RESULT_FILE,
    )


if __name__ == "__main__":
    main()
