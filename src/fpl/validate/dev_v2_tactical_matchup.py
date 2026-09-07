"""One claimed, clean-provenance retrospective tactical development experiment.

No forecast/optimizer wiring. The original archive database and prior results are read-only.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import platform
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from typing import Any, Literal

import duckdb
import polars as pl
import yaml
from pydantic import BaseModel, ConfigDict

from fpl.config import repo_root
from fpl.features.pit import AsOf
from fpl.jobs.prospective_points_v1 import prospective_team_scored
from fpl.storage.db import connect
from fpl.validate import dev_v2_real_sot as scoring
from fpl.validate.baselines import TrailingGoalsAttackDefence, TrainingWindow
from fpl.validate.dev_v2_weekly_sot import _publish_result
from fpl.validate.metrics import Distribution, log_score
from fpl.validate.minutes_metrics import _reliability_curve
from fpl.validate.tactical_metric_audit import build_audit
from fpl.validate.v2_environment_harness import (
    Prediction,
    load_team_frame,
    observed_folds,
    promoted_team_codes,
)

CANDIDATE = "retrospective_tactical_matchup_team_environment_v1"
INCUMBENT = "trailing_goals_attack_defence"
CONFIG = "config/v2_tactical_matchup_evaluation.yaml"
RESULT = "results/v2_tactical_matchup_development.json"
MODEL_LABELS = {
    "incumbent": INCUMBENT,
    "candidate": CANDIDATE,
    "recent_state_only_no_interactions": "diagnostic_recent_state_only_no_interactions",
    "predicted_state_no_interactions": "diagnostic_predicted_state_no_interactions",
}
DIMENSIONS = (
    "attack_precision",
    "dangerous_territory",
    "control",
    "directness",
    "defensive_suppression",
)
logger = logging.getLogger(__name__)


class TacticalContract(BaseModel):
    """V1 procedure pins: unsupported configuration cannot silently change the experiment."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_version: Literal["1.0"]
    candidate: Literal["retrospective_tactical_matchup_team_environment_v1"]
    incumbent: Literal["trailing_goals_attack_defence"]
    evidence_class: Literal["retrospective_backfill_development"]
    database_sha256: Literal["0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8"]
    coverage_report: Literal["results/v2_tactical_metric_audit.json"]
    coverage_sha256: Literal["66a7364de7af030361640db56c922e963ebf8e2853ab500e2ca0d124f4ad0f92"]
    reference: Literal["results/v2_corroborated_zero_sot_development.json"]
    reference_sha256: Literal["e8d1a5c0fcce42946d3bf8e798f52e208ac79168c2453e4c0840c1be65c009c5"]
    eligible_seasons: tuple[Literal["2023-24"], Literal["2025-26"]]
    expected_rows: Literal[1520]
    expected_folds: Literal[76]
    coverage_threshold: float
    coverage_rule: str
    dimensions: tuple[str, ...]
    provider_fields: tuple[str, ...]
    version_policy: str
    recent_weights: tuple[float, ...]
    shrinkage_matches: float
    season_carryover: str
    style_ridge_penalty: float
    minimum_fit_rows: Literal[160]
    goal_penalties: tuple[float | None, ...]
    inner_holdout_gameweeks: Literal[6]
    minimum_inner_training_gameweeks: Literal[10]
    tie_tolerance: float
    maximum_log_correction: float
    rate_floor: float
    maximum_goals: Literal[10]
    interactions: tuple[str, ...]
    diagnostics: tuple[str, ...]
    diagnostic_selection: str
    seed: Literal[20260904]
    minimum_log_lift: float
    minimum_cs_brier_lift: float
    maximum_crps_regression: float
    maximum_season_log_regression: float
    maximum_season_cs_brier_regression: float
    maximum_pit80_absolute_error: float
    formal_runs: Literal[1]
    require_clean_worktree: Literal[True]
    promotion_permitted: Literal[False]


def load_contract(path: Path) -> TacticalContract:
    contract = TacticalContract.model_validate(yaml.safe_load(path.read_bytes()))
    pins: dict[str, Any] = {
        "coverage_threshold": 0.95,
        "coverage_rule": "complete_season_both_sides_all_five_dimensions_and_one_prior_full_season",
        "dimensions": DIMENSIONS,
        "provider_fields": (
            "ontargetScoringAtt",
            "totalScoringAtt",
            "touchesInOppBox",
            "possessionPercentage",
            "fwdPass",
            "totalPass",
        ),
        "version_policy": (
            "earliest_successful_complete_match_stats_payload_by_fetched_at_then_payload_id"
        ),
        "recent_weights": (1.0, 0.707, 0.5, 0.354, 0.25),
        "shrinkage_matches": 2.0,
        "season_carryover": "none_recent_state_league_prior_expands",
        "style_ridge_penalty": 1.0,
        "goal_penalties": (None, 10.0, 1.0, 0.1),
        "tie_tolerance": 1e-12,
        "maximum_log_correction": 0.5,
        "rate_floor": 0.05,
        "interactions": (
            "own_precision_x_opponent_suppression",
            "own_territory_x_opponent_suppression",
            "own_directness_x_opponent_control",
        ),
        "diagnostics": ("recent_state_only_no_interactions", "predicted_state_no_interactions"),
        "diagnostic_selection": "reuse_primary_selected_penalty_no_independent_search_or_gate",
        "minimum_log_lift": 0.01,
        "minimum_cs_brier_lift": 0.01,
        "maximum_crps_regression": 0.0,
        "maximum_season_log_regression": 0.0,
        "maximum_season_cs_brier_regression": 0.0,
        "maximum_pit80_absolute_error": 0.05,
    }
    for name, expected in pins.items():
        if getattr(contract, name) != expected:
            raise ValueError(f"unsupported V1 procedure: {name}")
    return contract


def identity(row: Mapping[str, Any]) -> str:
    return f"{row['season']}:{row['fixture']}:{row['team_code']}"


def reproduce_incumbent(
    con: duckdb.DuckDBPyConnection, contract: TacticalContract, reference: Mapping[str, Any]
) -> tuple[dict[str, tuple[float, Distribution]], dict[str, Any]]:
    """Compute exact prior-GW incumbent predictions FIRST; never fit a tactical estimator."""
    frame = load_team_frame(con, provider="fpl_archive")
    reference_rows = {
        row["key"]: row
        for row in reference["fixture_predictions"]
        if row["season"] in contract.eligible_seasons
    }
    cache: dict[str, tuple[float, Distribution]] = {}
    matched: set[str] = set()
    maximum = 0.0
    folds = 0
    reference_predictions: list[Prediction] = []
    actual_predictions: list[Prediction] = []
    for season, gw, cutoff in observed_folds(frame, minimum_prior_gameweeks=0):
        training = scoring._baseline_frame(frame.filter(pl.col("kickoff_time") < cutoff))
        target = frame.filter((pl.col("season") == season) & (pl.col("gw") == gw))
        model = TrailingGoalsAttackDefence()
        model.fit(TrainingWindow(training))
        target = target.sort(["kickoff_time", "fixture", "team_code"])
        pmfs = model.predict(target)
        for row, pmf in zip(target.iter_rows(named=True), pmfs, strict=True):
            key = identity(row)
            if key in cache:
                raise ValueError(f"duplicate incumbent identity: {key}")
            cache[key] = (model.rate_for(row), pmf)
        if season not in contract.eligible_seasons:
            continue
        folds += 1
        # Independent production adapter, with a schedule whose IDs are deliberately mapped
        # one-to-one to stable codes. No retrospective capability reaches this helper.
        schedule = target.with_columns(
            pl.col("team_code").alias("team_id"),
            pl.col("opponent_team_code").alias("opponent_team_id"),
        )
        team_map = {int(code): int(code) for code in target["team_code"].unique()}
        prospective, _ = prospective_team_scored(
            con,
            season=season,
            as_of=cutoff,
            team_map=team_map,
            schedule=schedule,
        )
        for row, pmf in zip(target.iter_rows(named=True), pmfs, strict=True):
            key = identity(row)
            stored = reference_rows.get(key)
            if stored is None or key in matched:
                raise ValueError(f"reference population mismatch: {key}")
            matched.add(key)
            expected = stored["distributions"][INCUMBENT]
            for other in (expected, prospective[(int(row["fixture"]), int(row["team_code"]))]):
                difference = max(abs(a - b) for a, b in zip(pmf, other, strict=True))
                maximum = max(maximum, difference)
                if difference > 1e-12:
                    raise ValueError(f"incumbent PMF reproduction failed: {key}: {difference}")
            if (row["goals"], row["was_home"], gw, cutoff.isoformat()) != (
                stored["observed_goals"],
                stored["was_home"],
                stored["gw"],
                stored["as_of"],
            ):
                raise ValueError(f"incumbent target/cutoff mismatch: {key}")
            common: dict[str, Any] = {
                "season": season,
                "gw": gw,
                "key": key,
                "observed": int(row["goals"]),
                "was_home": bool(row["was_home"]),
            }
            actual_predictions.append(Prediction(distribution=pmf, **common))
            reference_predictions.append(Prediction(distribution=tuple(expected), **common))
    if matched != set(reference_rows) or len(matched) != contract.expected_rows:
        raise ValueError("incumbent reference population is incomplete")
    if folds != contract.expected_folds:
        raise ValueError("incumbent fold count differs")
    actual = scoring._score_block(INCUMBENT, actual_predictions, seed=contract.seed)
    retained = scoring._score_block(INCUMBENT, reference_predictions, seed=contract.seed)
    for metric in ("mean_log_score", "crps", "pit_interval_80_coverage"):
        if abs(actual[metric] - retained[metric]) > 1e-12:
            raise ValueError(f"incumbent metric differs: {metric}")
    return cache, {
        "rows": len(matched),
        "folds": folds,
        "maximum_absolute_pmf_difference": maximum,
        "absolute_tolerance": 1e-12,
        "retained_reference_checked": True,
        "actual_prospective_adapter_checked": True,
        "same_population": True,
        "current_metrics": actual,
        "reference_metrics": retained,
    }


def _mean(values: Sequence[float]) -> float:
    return math.fsum(values) / len(values) if values else 0.0


def _clustered(deltas: Sequence[float], rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[float]] = {}
    for delta, row in zip(deltas, rows, strict=True):
        groups.setdefault(f"{row['season']}:{row['gw']}", []).append(delta)
    mean, count = _mean(deltas), len(groups)
    se = (
        math.sqrt(
            count
            / (count - 1)
            * math.fsum((math.fsum(values) - len(values) * mean) ** 2 for values in groups.values())
        )
        / len(deltas)
        if count > 1
        else None
    )
    return {
        "paired_mean": mean,
        "gw_clustered_standard_error": se,
        "clusters": count,
        "normal_95_interval": [mean - 1.96 * se, mean + 1.96 * se] if se is not None else None,
        "negative_favours": CANDIDATE,
        "serial_dependence_adjusted": False,
    }


def _predictions(rows: Sequence[Mapping[str, Any]], arm: str) -> list[Prediction]:
    return [
        Prediction(
            season=row["season"],
            gw=row["gw"],
            key=row["key"],
            observed=row["observed_goals"],
            was_home=row["was_home"],
            distribution=tuple(row["distributions"][arm]),
            cold_start=row["state_cold_start"],
        )
        for row in rows
    ]


def _score_rows(rows: Sequence[Mapping[str, Any]], *, seed: int) -> dict[str, Any]:
    blocks: dict[str, Any] = {}
    for arm, name in MODEL_LABELS.items():
        block = scoring._score_block(name, _predictions(rows, arm), seed=seed)
        probabilities = [float(row["clean_sheet_probabilities"][arm]) for row in rows]
        outcomes = [int(row["goals_allowed"] == 0) for row in rows]
        block["clean_sheet_brier"] = _mean(
            [(p - y) ** 2 for p, y in zip(probabilities, outcomes, strict=True)]
        )
        block["clean_sheet_mean_probability"] = _mean(probabilities)
        block["clean_sheet_observed_frequency"] = _mean(outcomes)
        block["clean_sheet_reliability"] = asdict(
            _reliability_curve(probabilities, outcomes, tuple(i / 10 for i in range(11)))
        )
        blocks[arm] = block
    return blocks


def _styles(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for index, name in enumerate(DIMENSIONS):
        measured = [
            r
            for r in rows
            if all(
                r[field][index] is not None
                for field in ("actual_state", "predicted_state", "persistence_prediction")
            )
        ]
        block: dict[str, Any] = {"rows": len(measured)}
        if not measured:
            report[name] = block
            continue
        actual = [float(r["actual_state"][index]) for r in measured]
        for field, label in (
            ("predicted_state", "forecaster"),
            ("persistence_prediction", "persistence"),
        ):
            predicted = [float(r[field][index]) for r in measured]
            errors = [a - b for a, b in zip(predicted, actual, strict=True)]
            mse = _mean([e * e for e in errors])
            standardized = []
            for row, error in zip(measured, errors, strict=True):
                scales = row.get("prior_style_target_sd", [None] * 5)
                scale = scales[index]
                if scale is not None and scale > 0:
                    standardized.append((error / scale) ** 2)
            block[label] = {
                "mae": _mean([abs(e) for e in errors]),
                "mse": mse,
                "rmse": math.sqrt(mse),
                "standardized_mse": _mean(standardized) if standardized else None,
                "standardized_rows": len(standardized),
                "pearson": scoring._pearson(predicted, actual),
                "spearman": _rank_correlation(predicted, actual),
            }
        block["relative_mse_lift"] = _lift(block["persistence"]["mse"], block["forecaster"]["mse"])
        for field in ("style_venue_contribution", "style_opponent_contribution"):
            values = [abs(float(r[field][index])) for r in measured if r[field][index] is not None]
            block[field + "_mean_absolute"] = _mean(values) if values else None
        report[name] = block
    return report


def _rank_correlation(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) < 2:
        return None

    def ranks(values: Sequence[float]) -> list[float]:
        ordered = sorted(enumerate(values), key=lambda pair: pair[1])
        out = [0.0] * len(values)
        start = 0
        while start < len(ordered):
            end = start + 1
            while end < len(ordered) and ordered[end][1] == ordered[start][1]:
                end += 1
            rank = (start + end - 1) / 2
            for item in ordered[start:end]:
                out[item[0]] = rank
            start = end
        return out

    return scoring._pearson(ranks(left), ranks(right))


def _lift(old: float, new: float) -> float:
    return (old - new) / old if old else 0.0


def verify_temporal_trace(run: Mapping[str, Any]) -> dict[str, int]:
    """Recheck retained event boundaries independently of the fitting loop."""
    checks = 0
    for row in run["history_rows"]:
        cutoff = datetime.fromisoformat(row["as_of"])
        if cutoff > datetime.fromisoformat(row["kickoff_time"]):
            raise ValueError("prediction cutoff is after target event")
        maximum = row["maximum_state_source_event"]
        if maximum is not None and datetime.fromisoformat(maximum) >= cutoff:
            raise ValueError("future event in current tactical state")
        checks += 2
    fit_blocks = 0
    for fold in run["historical_folds"]:
        cutoff = datetime.fromisoformat(fold["as_of"])
        for counter in (
            "event_time_violations",
            "same_gameweek_violations",
            "stacking_in_sample_rows",
        ):
            if fold[counter] != 0:
                raise ValueError(f"temporal guard failed: {counter}")
            checks += 1
        for family in ("style_fits", "goal_fits", "diagnostic_goal_fits"):
            for block in fold[family].values():
                for key in ("maximum_training_event", "maximum_training_prediction_cutoff"):
                    value = block[key]
                    if value is not None and datetime.fromisoformat(value) >= cutoff:
                        raise ValueError(f"future/in-sample {family} training: {key}")
                    checks += 1
                fit_blocks += 1
    return {"boundary_checks": checks, "fit_blocks": fit_blocks, "violations": 0}


def attach_reciprocal_and_slices(
    rows: list[dict[str, Any]], promoted: Mapping[str, frozenset[int]]
) -> None:
    by_key = {r["key"]: r for r in rows}
    if len(by_key) != len(rows):
        raise ValueError("duplicate candidate identity")
    for row in rows:
        opponent = by_key.get(f"{row['season']}:{row['fixture']}:{row['opponent_team_code']}")
        if opponent is None or opponent["opponent_team_code"] != row["team_code"]:
            raise ValueError("missing reciprocal candidate side")
        if (
            row["goals_allowed"] != opponent["observed_goals"]
            or row["was_home"] == opponent["was_home"]
            or row["as_of"] != opponent["as_of"]
            or row["gw"] != opponent["gw"]
        ):
            raise ValueError("reciprocal side outcome/venue/cutoff contradiction")
        row["clean_sheet_probabilities"] = {
            arm: float(opponent["distributions"][arm][0]) for arm in MODEL_LABELS
        }
        row["promoted"] = row["team_code"] in promoted.get(row["season"], frozenset())
        row["early_season"] = row["gw"] <= 6
        row["log_losses"] = {
            arm: log_score(tuple(row["distributions"][arm]), row["observed_goals"])
            for arm in MODEL_LABELS
        }
        row["clean_sheet_brier_losses"] = {
            arm: (row["clean_sheet_probabilities"][arm] - int(row["goals_allowed"] == 0)) ** 2
            for arm in MODEL_LABELS
        }
        for arm in MODEL_LABELS:
            pmf = row["distributions"][arm]
            if len(pmf) != 11 or any(not math.isfinite(v) or v < 0 for v in pmf):
                raise ValueError("invalid candidate distribution")
            if abs(sum(pmf) - 1) > 1e-12:
                raise ValueError("candidate distribution mass differs from one")


def score_experiment(run: dict[str, Any], contract: TacticalContract) -> dict[str, Any]:
    rows = run["rows"]
    if len(rows) != contract.expected_rows or len(run["folds"]) != contract.expected_folds:
        raise ValueError("candidate population differs from preregistration")
    overall = _score_rows(rows, seed=contract.seed)
    slices: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        labels = [
            "season:" + row["season"],
            "home" if row["was_home"] else "away",
            "GW1-6" if row["early_season"] else "GW7+",
            "promoted" if row["promoted"] else "established",
            "cold_start" if row["state_cold_start"] else "non_cold_start",
            "confidence_high" if row["high_confidence"] else "confidence_low",
            "style_error_risk:" + str(row["style_error_risk"]),
        ]
        for label in labels:
            slices.setdefault(label, []).append(row)
    by_slice = {k: _score_rows(v, seed=contract.seed) for k, v in sorted(slices.items())}
    styles = _styles(rows)
    old, new = overall["incumbent"], overall["candidate"]
    log_lift = _lift(old["mean_log_score"], new["mean_log_score"])
    cs_lift = _lift(old["clean_sheet_brier"], new["clean_sheet_brier"])
    checks = {
        "goal_log_materiality": log_lift >= contract.minimum_log_lift,
        "cs_brier_materiality": cs_lift >= contract.minimum_cs_brier_lift,
        "crps_nonregression": new["crps"] <= old["crps"],
        "pit80": new["pit_interval_80_absolute_error"] <= contract.maximum_pit80_absolute_error,
        "all_seasons_log_nonregression": all(
            by_slice["season:" + s]["candidate"]["mean_log_score"]
            <= by_slice["season:" + s]["incumbent"]["mean_log_score"]
            for s in contract.eligible_seasons
        ),
        "all_seasons_cs_nonregression": all(
            by_slice["season:" + s]["candidate"]["clean_sheet_brier"]
            <= by_slice["season:" + s]["incumbent"]["clean_sheet_brier"]
            for s in contract.eligible_seasons
        ),
        "same_population": True,
        "zero_temporal_violations": verify_temporal_trace(run)["violations"] == 0,
    }
    style_fails = not any(b.get("relative_mse_lift", 0) > 0 for b in styles.values())
    verdict = (
        "REFUTED"
        if log_lift <= -0.01 or cs_lift <= -0.01 or style_fails
        else "SUPPORTED"
        if all(checks.values())
        else "INCONCLUSIVE"
    )
    log_deltas = [r["log_losses"]["candidate"] - r["log_losses"]["incumbent"] for r in rows]
    cs_deltas = [
        r["clean_sheet_brier_losses"]["candidate"] - r["clean_sheet_brier_losses"]["incumbent"]
        for r in rows
    ]
    per_gw: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        per_gw.setdefault(f"{row['season']}:{row['gw']}", []).append(row)
    rate_changes = []
    for row in rows:
        means = {
            arm: sum(i * p for i, p in enumerate(row["distributions"][arm]))
            for arm in ("incumbent", "candidate")
        }
        rate_changes.append(means["candidate"] - means["incumbent"])
    return {
        "schema_version": 1,
        "candidate": CANDIDATE,
        "incumbent": INCUMBENT,
        "evidence_class": contract.evidence_class,
        "development_only": True,
        "promotion_permitted": False,
        "verdict": verdict,
        "gate_checks": checks,
        "temporal_trace": verify_temporal_trace(run),
        "eligible_seasons": list(contract.eligible_seasons),
        "rows_scored": len(rows),
        "fold_count": len(run["folds"]),
        "overall": overall,
        "by_slice": by_slice,
        "style_forecast": styles,
        "style_forecast_by_slice": {k: _styles(v) for k, v in sorted(slices.items())},
        "relative_goal_log_lift": log_lift,
        "relative_clean_sheet_brier_lift": cs_lift,
        "paired_log_uncertainty": _clustered(log_deltas, rows),
        "paired_cs_uncertainty": _clustered(cs_deltas, rows),
        "by_gameweek": {k: _score_rows(v, seed=contract.seed) for k, v in per_gw.items()},
        "selected_penalties": dict(Counter(str(f["chosen_penalty"]) for f in run["folds"])),
        "mean_absolute_rate_change": _mean([abs(x) for x in rate_changes]),
        "mean_signed_rate_change": _mean(rate_changes),
        "fixture_predictions": rows,
        "fold_diagnostics": run["folds"],
        "historical_style_predictions": run["history_rows"],
        "historical_fit_provenance": run["historical_folds"],
        "diagnostics_are_not_independently_selected_candidates": True,
    }


def _snapshot(root: Path, db: Path) -> dict[str, Any]:
    scoring.require_clean_worktree(root)
    if scoring._git(root, "branch", "--show-current") != "claude/comet-fpl-v2-architecture-mqrj8f":
        raise RuntimeError("formal tactical run requires the V2 branch")
    paths = scoring._git(root, "ls-files", "src", "config", "results").splitlines()
    paths.extend(
        [
            "AGENTS.md",
            "DEV-ROADMAP.md",
            "README.md",
            "docs/v2-tactical-state-design.md",
            "docs/v2-next-match-style-forecaster-design.md",
            "docs/v2-tactical-matchup-design.md",
            "docs/v2-tactical-metric-audit.md",
            ".claude/skills/guard-fpl-point-in-time/SKILL.md",
            ".claude/skills/validate-fpl-walk-forward/SKILL.md",
        ]
    )
    return {
        "git_head": scoring._git(root, "rev-parse", "HEAD"),
        "clean_worktree": True,
        "database_path": str(db.resolve()),
        "database_sha256": scoring.file_sha256(db),
        "config_sha256": scoring.file_sha256(root / CONFIG),
        "source_sha256": {p: scoring.file_sha256(root / p) for p in sorted(set(paths))},
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
            "executable": sys.executable,
            "libraries": {p: version(p) for p in ("duckdb", "polars", "pydantic", "PyYAML")},
        },
    }


def reserve_claim(root: Path, provenance: Mapping[str, Any]) -> Path:
    path = root / "data" / "evaluation-claims" / f"{CANDIDATE}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(
            {
                "candidate": CANDIDATE,
                "claimed_at": datetime.now(UTC).isoformat(),
                "git_head": provenance["git_head"],
                "config_sha256": provenance["config_sha256"],
                "database_sha256": provenance["database_sha256"],
            },
            stream,
            sort_keys=True,
        )
        stream.flush()
        os.fsync(stream.fileno())
    return path


def run_formal(root: Path, db: Path) -> dict[str, Any]:
    # No fitting (including incumbent) occurs before these refusal guards.
    scoring.require_clean_worktree(root)
    output = root / RESULT
    claim = root / "data" / "evaluation-claims" / f"{CANDIDATE}.json"
    if output.exists() or claim.exists():
        raise FileExistsError("tactical formal result/claim exists; no second run")
    if not db.is_file() or Path(str(db) + ".wal").exists():
        raise RuntimeError("explicit immutable research DB must exist without a WAL")
    contract = load_contract(root / CONFIG)
    snapshot = _snapshot(root, db)
    if snapshot["database_sha256"] != contract.database_sha256:
        raise RuntimeError("wrong historical database fingerprint")
    for path, expected in (
        (contract.coverage_report, contract.coverage_sha256),
        (contract.reference, contract.reference_sha256),
    ):
        if scoring.file_sha256(root / path) != expected:
            raise RuntimeError(f"frozen input changed: {path}")
    started = datetime.now(UTC).isoformat()
    with connect(db, read_only=True) as con:
        audit = build_audit(con)
        frozen_audit = json.loads((root / contract.coverage_report).read_bytes())
        for key, value in audit.items():
            if value != frozen_audit[key]:
                raise RuntimeError(f"coverage/source audit differs: {key}")
        if audit["season_eligibility_decision"]["selected_seasons"] != list(
            contract.eligible_seasons
        ):
            raise RuntimeError("coverage-derived seasons differ from contract")
        reference = json.loads((root / contract.reference).read_bytes())
        incumbent, reproduction = reproduce_incumbent(con, contract, reference)
        logger.info("Incumbent reproduced: %s; no tactical fit yet", reproduction)
        if _snapshot(root, db) != snapshot:
            raise RuntimeError("provenance changed during incumbent reproduction")
        claim = reserve_claim(root, snapshot)
        logger.info("Claim reserved. Starting ONE tactical candidate walk-forward.")
        # Deliberately imported only after the prerequisite reproduction and durable claim.
        from fpl.validate.tactical_matchup import run_tactical_walk_forward
        from fpl.validate.tactical_state import load_observations

        frame = load_team_frame(con, provider="fpl_archive")
        latest = frame["kickoff_time"].max()
        if not isinstance(latest, datetime):
            raise RuntimeError("archive has no event boundary")
        observations = load_observations(con, AsOf(latest + timedelta(microseconds=1)))
        measured = run_tactical_walk_forward(
            list(observations), incumbent, contract.eligible_seasons
        )
        attach_reciprocal_and_slices(measured["rows"], promoted_team_codes(con))
        # Exact incumbent cache survived candidate plumbing unchanged.
        for row in measured["rows"]:
            if tuple(row["distributions"]["incumbent"]) != incumbent[row["key"]][1]:
                raise RuntimeError("candidate plumbing changed incumbent PMF")
        report = score_experiment(measured, contract)
    if _snapshot(root, db) != snapshot:
        raise RuntimeError("provenance changed during formal tactical run")
    report["control_reproduction"] = reproduction
    report["provenance"] = {
        **snapshot,
        "started_at_utc": started,
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "seed": contract.seed,
        "evidence_class": contract.evidence_class,
        "execution_claim_sha256": scoring.file_sha256(claim),
        "sdp_capture_manifest_sha256": audit["manifest_sha256"],
        "sdp_version_policy": contract.version_policy,
        "known_at_rewritten": False,
    }
    _publish_result(output, report)
    logger.info(
        "Completed %s: log lift %.6f%%, CS Brier lift %.6f%%",
        report["verdict"],
        100 * report["relative_goal_log_lift"],
        100 * report["relative_clean_sheet_brier_lift"],
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    run_formal(repo_root(), args.db)


if __name__ == "__main__":
    main()
