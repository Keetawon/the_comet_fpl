"""One preregistered goals+xG procedural experiment; never a prospective entry point.

Reproduce the unchanged control completely before starting the weekly-inner candidate.
No SDP feature reader, mutable evaluation option, or dirty-worktree escape hatch exists.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal

import duckdb
import polars as pl
import yaml
from pydantic import BaseModel, ConfigDict, Field

from fpl.config import V2RealSotRetrospectiveContract, config_dir, repo_root
from fpl.features.pit import AsOf
from fpl.storage.db import connect, default_db_path
from fpl.validate import dev_v2_real_sot as prior
from fpl.validate.metrics import log_score, poisson_pmf, relative_lift
from fpl.validate.v2_environment_harness import (
    Prediction,
    load_team_frame,
    observed_folds,
    promoted_team_codes,
)
from fpl.validate.weekly_inner_selection import (
    WeeklyRefitTeamEngine,
    frozen_selected_inner_scores,
)

CONFIG_FILE = "v2_weekly_inner_selection_evaluation.yaml"
RESULT_FILE = "v2_weekly_inner_selection_development.json"
CANDIDATE = "retrospective_goals_xg_weekly_inner_selection_v1"
CONTROL = "retrospective_goals_xg_control_v1"
WeeklyInnerEvaluationError = prior.RetrospectiveEvaluationError
logger = logging.getLogger(__name__)
_KEYS = ["season", "fixture", "team_code"]
_INPUT_COLUMNS = [
    "season",
    "gw",
    "fixture",
    "kickoff_time",
    "team_code",
    "opponent_team_code",
    "was_home",
    "goals",
    "expected_goals",
]
_CONTEXT_FIELDS = (
    "season",
    "gw",
    "was_home",
    "promoted",
    "early_season",
    "cold_start",
    "as_of",
)


class WeeklyInnerEvaluationContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_version: Literal["1.0"]
    candidate: Literal["retrospective_goals_xg_weekly_inner_selection_v1"]
    control: Literal["retrospective_goals_xg_control_v1"]
    evidence_class: Literal["retrospective_archive_development"]
    base_contract: Literal["config/v2_real_sot_retrospective_evaluation.yaml"]
    base_contract_sha256: Literal[
        "73ebf92613b8efb39838079b42b576afea2f2d43c775758372293c4d64edaed0"
    ]
    control_reference: Literal["results/v2_corroborated_zero_sot_development.json"]
    control_reference_sha256: Literal[
        "e8d1a5c0fcce42946d3bf8e798f52e208ac79168c2453e4c0840c1be65c009c5"
    ]
    signals: tuple[Literal["goals"], Literal["expected_goals"]]
    provider: Literal["fpl_archive"]
    selection_schedule: Literal["weekly_refit"]
    search_stages: Literal["goals_decay_prior_then_blend_weights"]
    inner_aggregation: Literal["mean_over_scored_team_fixture_rows"]
    tie_breaking: Literal["exact_equal_keep_first_in_explicit_configured_order"]
    inner_prior_context: Literal["unchanged_outer_prediction_season"]
    expected_rows: Literal[2280]
    expected_folds: Literal[114]
    control_absolute_tolerance: float = Field(ge=1e-12, le=1e-12)
    uncertainty: Literal["row_weighted_gw_cluster_sandwich_finite_sample_correction"]
    formal_outer_runs: Literal[1]
    retain_fixture_distributions: Literal[True]
    require_clean_worktree: Literal[True]
    promotion_permitted: Literal[False]


@dataclass
class WalkForwardRun:
    predictions: list[Prediction]
    contexts: dict[str, dict[str, Any]]
    folds: list[dict[str, Any]]


def load_contract(
    path: Path, *, root: Path
) -> tuple[WeeklyInnerEvaluationContract, V2RealSotRetrospectiveContract]:
    contract = WeeklyInnerEvaluationContract.model_validate(yaml.safe_load(path.read_bytes()))
    base, digest = prior._load_contract(root / contract.base_contract)
    if digest != contract.base_contract_sha256:
        raise WeeklyInnerEvaluationError("inherited frozen goals+xG contract changed")
    return contract, base


def _weekly_engine(base: V2RealSotRetrospectiveContract) -> WeeklyRefitTeamEngine:
    policy, walk = base.engine, base.walk_forward
    return WeeklyRefitTeamEngine(
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


def _walk_forward(
    con: duckdb.DuckDBPyConnection,
    base: V2RealSotRetrospectiveContract,
    *,
    schedule: Literal["frozen", "weekly"],
) -> WalkForwardRun:
    # Project before fitting: even already-loaded unrelated mart columns cannot enter the model.
    frame = load_team_frame(con, provider="fpl_archive").select(_INPUT_COLUMNS)
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
        logger.info("%s selector fold %s/%s: %s GW%s", schedule, index, len(folds), season, gw)
        training = frame.filter(pl.col("kickoff_time") < cutoff)
        target = frame.filter((pl.col("season") == season) & (pl.col("gw") == gw))
        if training.join(target.select(_KEYS), on=_KEYS, how="inner").height:
            raise WeeklyInnerEvaluationError("outer target GW entered training")
        engine = (
            _weekly_engine(base)
            if schedule == "weekly"
            else prior._engine(base, prior._CONTROL_SIGNALS)
        )
        engine.set_promoted(promoted)
        engine.set_prediction_season(season)
        if isinstance(engine, WeeklyRefitTeamEngine):
            engine.fit_as_of(training, AsOf(cutoff))
            diagnostics = engine.selector_diagnostics
            inner_scores = {
                name: block.get("selected_score") for name, block in diagnostics.items()
            }
        else:
            engine.fit(training)
            diagnostics = {}
            inner_scores = frozen_selected_inner_scores(engine, training)
        for row in target.iter_rows(named=True):
            if row["goals"] is None:
                raise WeeklyInnerEvaluationError("a preregistered target was not scored")
            team, opponent = int(row["team_code"]), int(row["opponent_team_code"])
            was_home = bool(row["was_home"])
            key = f"{season}:{row['fixture']}:{team}"
            if key in run.contexts:
                raise WeeklyInnerEvaluationError(f"duplicate prediction identity: {key}")
            cold = engine.is_cold_start(team, opponent)
            pmf = poisson_pmf(
                engine.goal_rate(team, opponent, was_home), max_goals=base.engine.maximum_goals
            )
            if any(not math.isfinite(p) or p < 0 for p in pmf) or not math.isclose(
                sum(pmf), 1.0, rel_tol=0, abs_tol=1e-12
            ):
                raise WeeklyInnerEvaluationError("invalid probability distribution")
            run.predictions.append(
                Prediction(season, gw, key, pmf, int(row["goals"]), was_home, cold)
            )
            run.contexts[key] = {
                "season": season,
                "gw": gw,
                "fixture": int(row["fixture"]),
                "team_code": team,
                "opponent_team_code": opponent,
                "was_home": was_home,
                "promoted": team in promoted.get(season, frozenset()),
                "early_season": gw <= base.reporting.early_season_observed_gameweeks,
                "cold_start": cold,
                "as_of": cutoff.isoformat(),
                "kickoff_time": row["kickoff_time"].isoformat(),
            }
        run.folds.append(
            {
                "season": season,
                "gw": gw,
                "as_of": cutoff.isoformat(),
                "training_rows": training.height,
                "target_rows": target.height,
                "training_input_sha256": hashlib.sha256(training.write_json().encode()).hexdigest(),
                "parameters": engine.parameters.as_report(),
                "signal_fit": prior._fitted_signal_report(engine),
                "inner_scores": inner_scores,
                "inner_diagnostics": diagnostics,
                "guards": {
                    "future_training_rows": training.filter(
                        pl.col("kickoff_time") >= cutoff
                    ).height,
                    "target_gw_training_rows": 0,
                },
            }
        )
    return run


def run_control_walk_forward(
    con: duckdb.DuckDBPyConnection, base_contract: V2RealSotRetrospectiveContract
) -> WalkForwardRun:
    return _walk_forward(con, base_contract, schedule="frozen")


def run_candidate_walk_forward(
    con: duckdb.DuckDBPyConnection, base_contract: V2RealSotRetrospectiveContract
) -> WalkForwardRun:
    return _walk_forward(con, base_contract, schedule="weekly")


def _slice_scores(
    blocks: Mapping[str, Sequence[Prediction]],
    contexts: Mapping[str, Mapping[str, Any]],
    *,
    seed: int,
) -> dict[str, dict[str, dict[str, Any]]]:
    groups: dict[str, set[str]] = {}
    for key, row in contexts.items():
        phase = "early" if row["early_season"] else "later"
        labels = (
            f"season:{row['season']}",
            "venue:home" if row["was_home"] else "venue:away",
            "promoted:promoted" if row["promoted"] else "promoted:established",
            f"season_phase:{phase}",
            "cold_start:cold_start" if row["cold_start"] else "cold_start:established",
            f"season_phase_by_season:{row['season']}:{phase}",
        )
        for label in labels:
            groups.setdefault(label, set()).add(key)
    return {
        label: prior._score_models(prior._filtered_blocks(blocks, keys), seed=seed)
        for label, keys in sorted(groups.items())
    }


def _assert_equal(actual: Any, expected: Any, *, tolerance: float, path: str) -> None:
    if isinstance(expected, bool) or expected is None or isinstance(expected, str):
        equal = type(actual) is type(expected) and actual == expected
    elif isinstance(expected, int):
        equal = type(actual) is int and actual == expected
    elif isinstance(expected, float):
        equal = (
            isinstance(actual, (float, int))
            and not isinstance(actual, bool)
            and math.isclose(actual, expected, rel_tol=0, abs_tol=tolerance)
        )
    elif isinstance(expected, dict) and isinstance(actual, dict):
        if actual.keys() != expected.keys():
            raise WeeklyInnerEvaluationError(f"control reproduction keys differ: {path}")
        for key, value in expected.items():
            _assert_equal(actual[key], value, tolerance=tolerance, path=f"{path}.{key}")
        return
    elif isinstance(expected, (list, tuple)) and isinstance(actual, (list, tuple)):
        if len(actual) != len(expected):
            raise WeeklyInnerEvaluationError(f"control reproduction length differs: {path}")
        for index, (left, right) in enumerate(zip(actual, expected, strict=True)):
            _assert_equal(left, right, tolerance=tolerance, path=f"{path}[{index}]")
        return
    else:
        equal = False
    if not equal:
        raise WeeklyInnerEvaluationError(
            f"control reproduction mismatch: {path}: {actual!r} != {expected!r}"
        )


def verify_control_reproduction(
    control_run: WalkForwardRun,
    frozen_result: Mapping[str, Any],
    base_contract: V2RealSotRetrospectiveContract,
    *,
    tolerance: float = 1e-12,
    expected_rows: int = 2280,
    expected_folds: int = 114,
) -> dict[str, Any]:
    if len(control_run.predictions) != expected_rows or len(control_run.folds) != expected_folds:
        raise WeeklyInnerEvaluationError("control reproduction row/fold count changed")
    for field, expected in (
        ("rows_scored", expected_rows),
        ("folds", expected_folds),
        ("control", CONTROL),
        ("eligible_seasons", list(base_contract.population.eligible_seasons)),
    ):
        _assert_equal(frozen_result[field], expected, tolerance=tolerance, path=field)
    blocks = {CONTROL: control_run.predictions}
    actual = prior._score_block(CONTROL, control_run.predictions, seed=base_contract.random_seed)
    _assert_equal(actual, frozen_result["overall"][CONTROL], tolerance=tolerance, path="overall")
    slices = _slice_scores(blocks, control_run.contexts, seed=base_contract.random_seed)
    for label, models in frozen_result["by_slice"].items():
        if label.startswith("sot_history:"):
            continue
        if label not in slices:
            raise WeeklyInnerEvaluationError(f"control reproduction missing slice: {label}")
        _assert_equal(slices[label][CONTROL], models[CONTROL], tolerance=tolerance, path=label)
    reference_rows = frozen_result["fixture_predictions"]
    if len(reference_rows) != expected_rows:
        raise WeeklyInnerEvaluationError("frozen control lacks fixture identities")
    max_pmf_difference = 0.0
    for row, reference in zip(control_run.predictions, reference_rows, strict=True):
        current = {
            "key": row.key,
            "observed_goals": row.observed,
            **{field: control_run.contexts[row.key][field] for field in _CONTEXT_FIELDS},
        }
        _assert_equal(
            current, {key: reference[key] for key in current}, tolerance=tolerance, path=row.key
        )
        pmf = reference["distributions"][CONTROL]
        _assert_equal(row.distribution, pmf, tolerance=tolerance, path=f"{row.key}.PMF")
        max_pmf_difference = max(
            max_pmf_difference, max(abs(a - b) for a, b in zip(row.distribution, pmf, strict=True))
        )
    reference_folds = frozen_result["fold_parameters"]
    if len(reference_folds) != expected_folds:
        raise WeeklyInnerEvaluationError("frozen control fold count changed")
    for fold, reference in zip(control_run.folds, reference_folds, strict=True):
        current = {
            key: fold[key] for key in ("season", "gw", "as_of", "training_rows", "target_rows")
        }
        current.update(control_parameters=fold["parameters"], control_signal_fit=fold["signal_fit"])
        _assert_equal(
            current,
            {key: reference[key] for key in current},
            tolerance=tolerance,
            path=f"fold:{fold['season']}:{fold['gw']}",
        )
    return {
        "pass": True,
        "rows": expected_rows,
        "folds": expected_folds,
        "absolute_tolerance": tolerance,
        "mean_log_score": actual["mean_log_score"],
        "crps": actual["crps"],
        "maximum_pmf_absolute_difference": max_pmf_difference,
        "mean_log_score_absolute_difference": abs(
            actual["mean_log_score"] - frozen_result["overall"][CONTROL]["mean_log_score"]
        ),
        "fixture_identity_and_outcome_agreement": True,
        "all_fixed_population_scores_and_parameters_agree": True,
    }


def _paired_rows(control: Sequence[Prediction], candidate: Sequence[Prediction]) -> list[float]:
    if not control or len(control) != len(candidate):
        raise WeeklyInnerEvaluationError("paired prediction population differs or is empty")
    deltas: list[float] = []
    for old, new in zip(control, candidate, strict=True):
        if (old.key, old.season, old.gw, old.observed, old.was_home) != (
            new.key,
            new.season,
            new.gw,
            new.observed,
            new.was_home,
        ):
            raise WeeklyInnerEvaluationError("paired prediction identities/outcomes differ")
        deltas.append(
            log_score(new.distribution, new.observed) - log_score(old.distribution, old.observed)
        )
    return deltas


def clustered_loss_uncertainty(
    control_predictions: Sequence[Prediction], candidate_predictions: Sequence[Prediction]
) -> dict[str, Any]:
    deltas = _paired_rows(control_predictions, candidate_predictions)
    groups: dict[tuple[str, int], list[float]] = {}
    for row, delta in zip(control_predictions, deltas, strict=True):
        groups.setdefault((row.season, row.gw), []).append(delta)
    mean, n, g = prior._mean(deltas), len(deltas), len(groups)
    se = (
        math.sqrt(
            g / (g - 1) * sum((sum(values) - len(values) * mean) ** 2 for values in groups.values())
        )
        / n
        if g > 1
        else None
    )
    return {
        "paired_row_weighted_mean_log_loss": mean,
        "rows": n,
        "clusters": g,
        "paired_gw_cluster_log_loss_standard_error": se,
        "normal_95_interval": [mean - 1.96 * se, mean + 1.96 * se] if se is not None else None,
        "cluster": "season-qualified target GW",
        "serial_dependence_adjusted": False,
        "negative_difference_favours": CANDIDATE,
    }


def _parameter_diagnostics(folds: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    fields = ("half_life_days", "prior_matches", "weight_expected_goals")
    result: dict[str, Any] = {"folds": len(folds), "parameter_fields": fields}
    for model in ("control", "candidate"):
        subset_reports: dict[str, Any] = {}
        for label, selected in (
            ("overall", list(folds)),
            ("early", [f for f in folds if f["gw"] <= 6]),
        ):
            records: dict[str, Any] = {}
            for field in (*fields, "joint"):

                def key(fold: Mapping[str, Any], model: str = model, field: str = field) -> str:
                    parameters = fold[f"{model}_parameters"]
                    value = (
                        tuple(parameters.get(p) for p in fields)
                        if field == "joint"
                        else parameters.get(field)
                    )
                    return json.dumps(value, separators=(",", ":"))

                counts = Counter(key(fold) for fold in selected)
                n = len(selected)
                transitions = [(a, b) for a, b in pairwise(selected) if a["season"] == b["season"]]
                records[field] = {
                    "distribution": dict(sorted(counts.items())),
                    "entropy_bits": -sum(
                        (count / n) * math.log2(count / n) for count in counts.values()
                    )
                    if n
                    else None,
                    "adjacent_within_season_pairs": len(transitions),
                    "adjacent_parameter_changes": sum(key(a) != key(b) for a, b in transitions),
                }
            subset_reports[label] = records
        subset_reports["xg_weight_zero_folds"] = sum(
            f[f"{model}_parameters"].get("weight_expected_goals", 0) == 0 for f in folds
        )
        result[model] = subset_reports
    result["selector_disagreements"] = {
        field: sum(
            f["control_parameters"].get(field) != f["candidate_parameters"].get(field)
            for f in folds
        )
        for field in fields
    }
    result["any_setting_disagrees"] = sum(
        any(f["control_parameters"].get(p) != f["candidate_parameters"].get(p) for p in fields)
        for f in folds
    )
    return result


def score_run(
    control_run: WalkForwardRun,
    candidate_run: WalkForwardRun,
    base_contract: V2RealSotRetrospectiveContract,
) -> dict[str, Any]:
    deltas = _paired_rows(control_run.predictions, candidate_run.predictions)
    # Inherited cold-start status depends on selected goals prior/rating history; the scored
    # slice must be the SAME control-defined population even if the candidate reports another.
    candidate_predictions = [
        replace(new, cold_start=old.cold_start)
        for old, new in zip(control_run.predictions, candidate_run.predictions, strict=True)
    ]
    blocks = {CONTROL: control_run.predictions, CANDIDATE: candidate_predictions}
    overall = prior._score_models(blocks, seed=base_contract.random_seed)
    slices = _slice_scores(blocks, control_run.contexts, seed=base_contract.random_seed)
    folds: list[dict[str, Any]] = []
    by_fold: list[dict[str, Any]] = []
    checked_inner_batches = 0
    for old, new in zip(control_run.folds, candidate_run.folds, strict=True):
        for field in (
            "season",
            "gw",
            "as_of",
            "training_rows",
            "target_rows",
            "training_input_sha256",
        ):
            if old[field] != new[field]:
                raise WeeklyInnerEvaluationError(f"candidate changed outer fold: {field}")
        if any(old["guards"].values()) or any(new["guards"].values()):
            raise WeeklyInnerEvaluationError("event-time/batch guard failure")
        for stage in new["inner_diagnostics"].values():
            for batch in stage["batches"]:
                checked_inner_batches += 1
                latest = batch["training_latest_kickoff"]
                if (
                    batch["event_time_violations"]
                    or batch["target_gameweek_overlap"]
                    or (
                        latest is not None
                        and datetime.fromisoformat(latest) >= datetime.fromisoformat(batch["as_of"])
                    )
                ):
                    raise WeeklyInnerEvaluationError("inner event-time/batch guard failure")
        fold = {
            key: old[key]
            for key in (
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
                f"{name}_{field}": run[field]
                for name, run in (("control", old), ("candidate", new))
                for field in (
                    "parameters",
                    "signal_fit",
                    "inner_scores",
                    "inner_diagnostics",
                    "guards",
                )
            }
        )
        folds.append(fold)
        keys = {
            p.key for p in control_run.predictions if (p.season, p.gw) == (old["season"], old["gw"])
        }
        metrics = prior._score_models(
            prior._filtered_blocks(blocks, keys), seed=base_contract.random_seed
        )
        by_fold.append(
            {
                "season": old["season"],
                "gw": old["gw"],
                "as_of": old["as_of"],
                "models": metrics,
                "candidate_minus_control_mean_log_loss": metrics[CANDIDATE]["mean_log_score"]
                - metrics[CONTROL]["mean_log_score"],
            }
        )
    fixture_predictions: list[dict[str, Any]] = []
    fixture_losses: dict[tuple[str, int], list[float]] = {}
    for old_row, new_row, delta in zip(
        control_run.predictions, candidate_predictions, deltas, strict=True
    ):
        context = control_run.contexts[old_row.key]
        fixture_predictions.append(
            {
                "key": old_row.key,
                **context,
                "observed_goals": old_row.observed,
                "distributions": {CONTROL: old_row.distribution, CANDIDATE: new_row.distribution},
                "log_losses": {
                    CONTROL: log_score(old_row.distribution, old_row.observed),
                    CANDIDATE: log_score(new_row.distribution, new_row.observed),
                },
                "candidate_minus_control_log_loss": delta,
            }
        )
        fixture_losses.setdefault((old_row.season, context["fixture"]), []).append(delta)
    control, candidate = overall[CONTROL], overall[CANDIDATE]
    log_lift = relative_lift(control["mean_log_score"], candidate["mean_log_score"])
    crps_lift = relative_lift(control["crps"], candidate["crps"])
    policy = base_contract.development_gate
    season_checks = {
        s: slices[f"season:{s}"][CANDIDATE]["mean_log_score"]
        <= slices[f"season:{s}"][CONTROL]["mean_log_score"]
        for s in base_contract.population.eligible_seasons
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
            "violations": 0,
            "checked_inner_stage_batches": checked_inner_batches,
            "pass": True,
        },
        "identical_population": {"rows": len(deltas), "pass": True},
    }
    passed = all(check["pass"] for check in checks.values())
    paired = prior._paired_diagnostics(control_run.predictions, candidate_predictions)
    paired["unweighted_gw_mean_log_loss_standard_error"] = paired.pop(
        "paired_gameweek_log_loss_standard_error"
    )
    return {
        "schema_version": 1,
        "candidate": CANDIDATE,
        "control": CONTROL,
        "status": "development_only",
        "evidence_class": "retrospective_archive_development",
        "verdict": "SUPPORTED_FOR_DEVELOPMENT"
        if passed
        else "REFUTED"
        if log_lift <= 0
        else "INCONCLUSIVE",
        "promotion_permitted": False,
        "signals": ["goals", "expected_goals"],
        "provider": "fpl_archive",
        "eligible_seasons": base_contract.population.eligible_seasons,
        "rows_scored": len(deltas),
        "folds": len(folds),
        "overall": overall,
        "by_slice": slices,
        "by_fold": by_fold,
        "candidate_vs_control": {
            "relative_log_score_lift": log_lift,
            "relative_crps_lift": crps_lift,
            **paired,
            **clustered_loss_uncertainty(control_run.predictions, candidate_predictions),
        },
        "development_gate": {"pass": passed, "checks": checks},
        "fold_parameters": folds,
        "parameter_diagnostics": _parameter_diagnostics(folds),
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
    }


def reserve_execution_claim(root: Path, provenance: Mapping[str, Any]) -> Path:
    path = root / "data" / "evaluation-claims" / f"{CANDIDATE}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(
                prior._json_bytes(
                    {
                        "candidate": CANDIDATE,
                        "started_at_utc": datetime.now(UTC).isoformat(),
                        **provenance,
                    }
                )
            )
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise WeeklyInnerEvaluationError(
            "candidate execution already claimed; do not rerun after interruption"
        ) from exc
    return path


def run(*, root: Path, db_path: Path, config_path: Path, output_path: Path) -> dict[str, Any]:
    prior.require_clean_worktree(root)
    if output_path.exists():
        raise WeeklyInnerEvaluationError("formal result already exists; evaluation is write-once")
    claim_path = root / "data" / "evaluation-claims" / f"{CANDIDATE}.json"
    if claim_path.exists():
        raise WeeklyInnerEvaluationError(
            "candidate execution already claimed; no second formal run"
        )
    contract, base = load_contract(config_path, root=root)
    coverage_path = root / base.population.coverage_report
    manifest_path = root / "results" / prior.CAPTURE_MANIFEST_FILE
    snapshot = prior._snapshot(
        root=root,
        db_path=db_path,
        config_path=config_path,
        coverage_path=coverage_path,
        manifest_path=manifest_path,
    )
    additional = (
        "src/fpl/validate/weekly_inner_selection.py",
        "src/fpl/validate/dev_v2_weekly_inner.py",
        contract.base_contract,
        contract.control_reference,
        "results/v2_real_sot_development.json",
        "results/v2_team_environment_development.json",
        "docs/v2-weekly-inner-selection-design.md",
        "docs/v2-weekly-inner-selection-diagnostic.md",
    )
    snapshot = replace(
        snapshot,
        source_sha256={
            **snapshot.source_sha256,
            **{p: prior.file_sha256(root / p) for p in additional},
        },
    )
    if snapshot.source_sha256[contract.control_reference] != contract.control_reference_sha256:
        raise WeeklyInnerEvaluationError("frozen control reference changed")
    if (
        snapshot.source_sha256["results/v2_real_sot_development.json"]
        != "32a3332dd92e30b160a632d6ad68ee268cbfd3367a27340e365583c2e9ca7e7d"
    ):
        raise WeeklyInnerEvaluationError("frozen first SOT result changed")
    original = json.loads((root / "results/v2_real_sot_development.json").read_bytes())
    for path, expected in original["provenance"]["source_sha256"].items():
        if prior.file_sha256(root / path) != expected:
            raise WeeklyInnerEvaluationError(f"frozen control implementation changed: {path}")
    for field in ("database_sha256", "coverage_report_sha256", "capture_manifest_sha256"):
        if getattr(snapshot, field) != original["provenance"][field]:
            raise WeeklyInnerEvaluationError(
                f"unchanged archive/population provenance differs: {field}"
            )
    frozen = json.loads((root / contract.control_reference).read_bytes())
    con = connect(db_path, read_only=True)
    try:
        control_run = run_control_walk_forward(con, base)
        reproduction = verify_control_reproduction(
            control_run,
            frozen,
            base,
            tolerance=contract.control_absolute_tolerance,
            expected_rows=contract.expected_rows,
            expected_folds=contract.expected_folds,
        )
        _assert_equal(
            frozen["overall"][CONTROL],
            original["overall"][CONTROL],
            tolerance=contract.control_absolute_tolerance,
            path="first_SOT_control",
        )
        for label, models in original["by_slice"].items():
            if not label.startswith("sot_history:"):
                _assert_equal(
                    frozen["by_slice"][label][CONTROL],
                    models[CONTROL],
                    tolerance=contract.control_absolute_tolerance,
                    path=f"first_SOT:{label}",
                )
        prior._verify_snapshot(
            snapshot,
            root=root,
            db_path=db_path,
            config_path=config_path,
            coverage_path=coverage_path,
            manifest_path=manifest_path,
        )
        logger.info(
            "Control reproduced: %s rows / %s folds, maximum PMF delta %s. "
            "Starting candidate ONCE.",
            reproduction["rows"],
            reproduction["folds"],
            reproduction["maximum_pmf_absolute_difference"],
        )
        claim = reserve_execution_claim(
            root,
            {
                "git_head": snapshot.head,
                "config_sha256": snapshot.config_sha256,
                "database_sha256": snapshot.database_sha256,
            },
        )
        candidate_run = run_candidate_walk_forward(con, base)
    finally:
        con.close()
    report = score_run(control_run, candidate_run, base)
    report["control_reproduction"] = reproduction
    report["provenance"] = {
        **asdict(snapshot),
        "clean_worktree": True,
        "git_head": snapshot.head,
        "random_seed": base.random_seed,
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "evidence_class": contract.evidence_class,
        "inherited_contract_sha256": contract.base_contract_sha256,
        "execution_claim_sha256": prior.file_sha256(claim),
        "sdp_role": "ancestral coverage population fingerprint only; no SDP model input",
        "provider": contract.provider,
        "input_columns": _INPUT_COLUMNS,
    }
    prior._verify_snapshot(
        snapshot,
        root=root,
        db_path=db_path,
        config_path=config_path,
        coverage_path=coverage_path,
        manifest_path=manifest_path,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("xb") as handle:
        handle.write(prior._json_bytes(report))
    logger.info(
        "%s: log lift %.6f%%",
        report["verdict"],
        report["candidate_vs_control"]["relative_log_score_lift"] * 100,
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=default_db_path())
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
