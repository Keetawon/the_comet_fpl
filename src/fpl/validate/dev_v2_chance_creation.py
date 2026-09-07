"""Write-once development runner for the separately preregistered chance architecture.

The only fitted tactical inputs are pinned, historical OOS predictions. This module
has no production adapter and never changes the strict point-in-time interface.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import platform
import sys
import traceback
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import polars as pl
import yaml

from fpl.config import repo_root
from fpl.jobs.prospective_points_v1 import prospective_team_scored
from fpl.validate import chance_creation as model
from fpl.validate import dev_v2_real_sot as scoring
from fpl.validate.baselines import TrailingGoalsAttackDefence, TrainingWindow
from fpl.validate.chance_coverage import build_audit, load_chance_targets
from fpl.validate.dev_v2_tactical_matchup import _clustered, _rank_correlation
from fpl.validate.dev_v2_tactical_numeric import _safe_json
from fpl.validate.dev_v2_weekly_sot import _publish_result
from fpl.validate.metrics import Distribution, log_score, poisson_pmf
from fpl.validate.minutes_metrics import _reliability_curve
from fpl.validate.retrospective_sdp import RetrospectiveBackfillView
from fpl.validate.v2_environment_harness import (
    Prediction,
    load_team_frame,
    observed_folds,
    promoted_team_codes,
)

CANDIDATE = "retrospective_chance_creation_team_environment_v1"
INCUMBENT = "trailing_goals_attack_defence"
BRANCH = "claude/comet-fpl-v2-architecture-mqrj8f"
CONFIG = "config/v2_chance_creation_evaluation.yaml"
CONFIG_SHA256 = "3edb29cd29cbe7b3ab42e11eda9ab53dc061c7902602dd16ce7893f9b8640728"
RESULT = "results/v2_chance_creation_development.json"
DIMENSIONS = (
    "attack_precision",
    "dangerous_territory",
    "control",
    "directness",
    "defensive_suppression",
)
HISTORICAL_ROWS = 3800
TOLERANCE = 1e-12
logger = logging.getLogger(__name__)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _timestamp(value: str | datetime) -> datetime:
    result = datetime.fromisoformat(value) if isinstance(value, str) else value
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("naive event/capture timestamp")
    return result


def load_contract(root: Path) -> dict[str, Any]:
    """Pin every byte, including unknown keys; there is no runtime parameter override."""
    if scoring.file_sha256(root / CONFIG) != CONFIG_SHA256:
        raise ValueError("chance preregistration bytes changed")
    contract: dict[str, Any] = yaml.safe_load((root / CONFIG).read_bytes())
    bindings = {
        "candidate": model.NAME,
        "evidence_class": model.EVIDENCE_CLASS,
        "shot_ridge_penalty": model.RIDGE,
        "quality_ridge_penalty": model.RIDGE,
        "minimum_fit_rows": model.MINIMUM_FIT_ROWS,
        "minimum_conversion_rows": model.MINIMUM_CONVERSION_ROWS,
        "conversion_prior_xg_units": model.CONVERSION_PRIOR_EXPOSURE,
        "quality_bounds": [model.QUALITY_FLOOR, model.QUALITY_CEILING],
        "rate_floor": model.RATE_FLOOR,
        "maximum_goals": model.MAX_GOALS,
        "dimensions": list(DIMENSIONS),
    }
    for key, actual in bindings.items():
        if actual != contract[key]:
            raise ValueError(f"model constant differs from frozen contract: {key}")
    return contract


def _assert_clean(root: Path) -> None:
    scoring.require_clean_worktree(root)
    if scoring._git(root, "branch", "--show-current") != BRANCH:
        raise RuntimeError("formal chance run requires the exact V2 branch")


def _assert_database(db: Path) -> None:
    if not db.is_file():
        raise ValueError("explicit existing database required")
    wal = Path(str(db) + ".wal")
    if wal.exists() or wal.is_symlink():
        raise RuntimeError("unresolved database WAL; no recovery or write is authorized")


def _snapshot(root: Path, db: Path, contract: Mapping[str, Any]) -> dict[str, Any]:
    _assert_clean(root)
    _assert_database(db)
    if scoring.file_sha256(db) != contract["database_sha256"]:
        raise RuntimeError("database differs from the coverage-pinned archive")
    if scoring.file_sha256(root / CONFIG) != CONFIG_SHA256:
        raise RuntimeError("preregistered config changed")
    for path_key, hash_key in (
        ("upstream", "upstream_sha256"),
        ("coverage_report", "coverage_sha256"),
    ):
        if scoring.file_sha256(root / contract[path_key]) != contract[hash_key]:
            raise RuntimeError(f"frozen evidence changed: {path_key}")
    files = sorted(
        {
            *root.glob("src/**/*.py"),
            *root.glob("config/*.yaml"),
            *root.glob("docs/*.md"),
            *root.glob("results/*.json"),
            root / "AGENTS.md",
            root / "DEV-ROADMAP.md",
            root / "README.md",
        }
    )
    return {
        "git_head": scoring._git(root, "rev-parse", "HEAD"),
        "branch": BRANCH,
        "clean_worktree": True,
        "config_sha256": CONFIG_SHA256,
        "database_path": str(db),
        "database_sha256": contract["database_sha256"],
        "source_sha256": {
            str(p.relative_to(root)).replace("\\", "/"): scoring.file_sha256(p)
            for p in files
            if p != root / RESULT
        },
        "model_source_sha256": scoring.file_sha256(root / "src/fpl/validate/chance_creation.py"),
        "coverage_sha256": contract["coverage_sha256"],
        "upstream_sha256": contract["upstream_sha256"],
        "evidence_class": model.EVIDENCE_CLASS,
        "sdp_version_policy": RetrospectiveBackfillView.VERSION_POLICY,
        "known_at_rewritten": False,
        "cutoff_policy": "historical_first_kickoff_proxy_not_real_deadline_knowledge",
        "eligible_seasons": contract["eligible_seasons"],
        "seed": contract["seed"],
        "python": platform.python_version(),
        "python_executable": sys.executable,
    }


def _claim_path(root: Path) -> Path:
    return root / "data" / "evaluation-claims" / f"{CANDIDATE}.json"


def reserve_claim(root: Path, provenance: Mapping[str, Any]) -> None:
    _publish_result(
        _claim_path(root),
        {
            "candidate": CANDIDATE,
            "claimed_at_utc": datetime.now(UTC).isoformat(),
            "resume_permitted": False,
            "provenance": provenance,
        },
    )


def _unclaimed(root: Path) -> None:
    for path in (_claim_path(root), root / RESULT):
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"candidate identity already consumed: {path}")


def _load_upstream(root: Path, contract: Mapping[str, Any]) -> dict[str, Any]:
    artifact: dict[str, Any] = json.loads((root / contract["upstream"]).read_bytes())
    provenance = artifact["provenance"]
    if (
        artifact.get("completed") is not True
        or artifact.get("candidate")
        != "retrospective_tactical_matchup_team_environment_v1_numeric1"
        or provenance["clean_worktree"] is not True
        or provenance["known_at_rewritten"] is not False
        or provenance["evidence_class"] != model.EVIDENCE_CLASS
        or provenance["database_sha256"] != contract["database_sha256"]
        or provenance["sdp_version_policy"] != RetrospectiveBackfillView.VERSION_POLICY
    ):
        raise ValueError("upstream is not the pinned clean retrospective OOS artifact")
    # Explicit projection: observed style, old goal corrections and old performance never
    # cross this boundary. Observed goals below are only a target-reproduction witness.
    fields = (
        "key",
        "season",
        "gw",
        "fixture",
        "team_code",
        "opponent_team_code",
        "was_home",
        "kickoff_time",
        "as_of",
        "observed_goals",
        "predicted_state",
        "predicted_opponent_state",
        "maximum_state_source_event",
        "maximum_style_training_event",
        "incumbent_latent_rate",
        "recent_counts",
        "opponent_counts",
        "source_capture_id",
        "source_known_at",
        "payload_sha256",
        "provider",
        "sdp_match_id",
        "state_source_keys_sha256",
        "state_source_rows",
    )
    rows = [
        {**{key: r[key] for key in fields}, "incumbent_pmf": r["distributions"]["incumbent"]}
        for r in artifact["historical_style_predictions"]
    ]
    folds = [
        {
            key: f[key]
            for key in (
                "season",
                "gw",
                "as_of",
                "target_rows",
                "style_fits",
                "maximum_state_source_event",
                "maximum_style_training_event",
                "event_time_violations",
                "same_gameweek_violations",
                "stacking_in_sample_rows",
                "target_fixture_source_overlap",
            )
        }
        for f in artifact["historical_fit_provenance"]
    ]
    if len(rows) != HISTORICAL_ROWS or len(folds) != contract["maximum_historical_batches"]:
        raise ValueError("upstream historical population differs")
    return {"rows": rows, "folds": folds, "provenance": provenance}


def _verify_upstream_trace(upstream: Mapping[str, Any]) -> None:
    folds = {(f["season"], f["gw"]): f for f in upstream["folds"]}
    if len(folds) != len(upstream["folds"]):
        raise ValueError("duplicate upstream fold")
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in upstream["rows"]:
        grouped[(row["season"], row["gw"])].append(row)
    if set(grouped) != set(folds):
        raise ValueError("upstream fold identities differ")
    for key, rows in grouped.items():
        fold = folds[key]
        cutoff = _timestamp(fold["as_of"])
        if (
            len(rows) != fold["target_rows"]
            or cutoff != min(_timestamp(r["kickoff_time"]) for r in rows)
            or any(_timestamp(r["as_of"]) != cutoff for r in rows)
        ):
            raise ValueError("upstream target-GW isolation/cutoff differs")
        for metric in (
            "event_time_violations",
            "same_gameweek_violations",
            "stacking_in_sample_rows",
            "target_fixture_source_overlap",
        ):
            if fold[metric] != 0:
                raise ValueError(f"upstream temporal violation: {metric}")
        for block in [fold, *rows, *fold["style_fits"].values()]:
            for field in (
                "maximum_state_source_event",
                "maximum_style_training_event",
                "maximum_training_event",
                "maximum_training_prediction_cutoff",
            ):
                if block.get(field) is not None and _timestamp(block[field]) >= cutoff:
                    raise ValueError(f"upstream future event or in-sample style fit: {field}")
        if set(fold["style_fits"]) != set(DIMENSIONS):
            raise ValueError("unexpected upstream style dimensions")
        for fit in fold["style_fits"].values():
            if fit.get("model") is not None and fit["model"]["penalty"] != 1.0:
                raise ValueError("upstream style regularization changed")


def reproduce_incumbent(
    con: duckdb.DuckDBPyConnection, contract: Mapping[str, Any], upstream: Mapping[str, Any]
) -> tuple[dict[str, tuple[float, Distribution]], dict[str, Any]]:
    """No chance fit: independently reproduce EVERY historical incumbent PMF first."""
    frame = load_team_frame(con, provider="fpl_archive")
    references = {r["key"]: r for r in upstream["rows"]}
    if len(references) != len(upstream["rows"]):
        raise ValueError("duplicate cached incumbent identity")
    cache: dict[str, tuple[float, Distribution]] = {}
    actual: list[Prediction] = []
    retained: list[Prediction] = []
    maximum = 0.0
    eligible_folds = 0
    all_folds = 0
    for season, gw, cutoff in observed_folds(frame, minimum_prior_gameweeks=0):
        all_folds += 1
        training = scoring._baseline_frame(frame.filter(pl.col("kickoff_time") < cutoff))
        target = frame.filter((pl.col("season") == season) & (pl.col("gw") == gw)).sort(
            ["kickoff_time", "fixture", "team_code"]
        )
        incumbent = TrailingGoalsAttackDefence()
        incumbent.fit(TrainingWindow(training))
        pmfs = incumbent.predict(target)
        schedule = target.with_columns(
            pl.col("team_code").alias("team_id"),
            pl.col("opponent_team_code").alias("opponent_team_id"),
        )
        team_map = {int(c): int(c) for c in target["team_code"].unique()}
        prospective, _ = prospective_team_scored(
            con, season=season, as_of=cutoff, team_map=team_map, schedule=schedule
        )
        eligible = season in contract["eligible_seasons"]
        eligible_folds += int(eligible)
        for row, pmf in zip(target.iter_rows(named=True), pmfs, strict=True):
            key = f"{season}:{row['fixture']}:{row['team_code']}"
            if key in cache or key not in references:
                raise ValueError(f"incumbent population differs: {key}")
            stored = references[key]
            if any(
                row[k] != stored[k]
                for k in ("season", "gw", "fixture", "team_code", "opponent_team_code", "was_home")
            ) or (
                row["goals"] != stored["observed_goals"]
                or _timestamp(row["kickoff_time"]) != _timestamp(stored["kickoff_time"])
                or cutoff != _timestamp(stored["as_of"])
            ):
                raise ValueError(f"incumbent target/cutoff identity differs: {key}")
            rate = incumbent.rate_for(row)
            if abs(rate - stored["incumbent_latent_rate"]) > TOLERANCE:
                raise ValueError(f"incumbent latent rate differs: {key}")
            for other in (stored["incumbent_pmf"], prospective[(row["fixture"], row["team_code"])]):
                difference = max(abs(a - b) for a, b in zip(pmf, other, strict=True))
                maximum = max(maximum, difference)
                if difference > TOLERANCE:
                    raise ValueError(f"incumbent PMF reproduction differs: {key}")
            cache[key] = (rate, pmf)
            if eligible:
                common: dict[str, Any] = {
                    "season": season,
                    "gw": gw,
                    "key": key,
                    "observed": int(row["goals"]),
                    "was_home": bool(row["was_home"]),
                }
                actual.append(Prediction(distribution=pmf, **common))
                retained.append(Prediction(distribution=tuple(stored["incumbent_pmf"]), **common))
    if set(cache) != set(references) or len(cache) != HISTORICAL_ROWS:
        raise ValueError("historical incumbent population is incomplete")
    if (
        len(actual) != contract["expected_rows"]
        or eligible_folds != contract["expected_folds"]
        or all_folds != contract["maximum_historical_batches"]
    ):
        raise ValueError("incumbent eligible rows/folds changed")
    current = scoring._score_block(INCUMBENT, actual, seed=contract["seed"])
    reference = scoring._score_block(INCUMBENT, retained, seed=contract["seed"])
    for metric in ("mean_log_score", "crps", "pit_interval_80_coverage"):
        if abs(current[metric] - reference[metric]) > TOLERANCE:
            raise ValueError(f"incumbent metric reproduction differs: {metric}")
    return cache, {
        "historical_rows": len(cache),
        "historical_folds": all_folds,
        "rows": len(actual),
        "folds": eligible_folds,
        "fixture_keys_sha256": _digest(sorted(p.key for p in actual)),
        "maximum_absolute_pmf_difference": maximum,
        "absolute_tolerance": TOLERANCE,
        "same_population": True,
        "actual_prospective_adapter_checked": True,
        "retained_reference_checked": True,
        "current_metrics": current,
        "reference_metrics": reference,
        "by_season": {
            season: {
                "current": scoring._score_block(
                    INCUMBENT, [p for p in actual if p.season == season], seed=contract["seed"]
                ),
                "reference": scoring._score_block(
                    INCUMBENT, [p for p in retained if p.season == season], seed=contract["seed"]
                ),
            }
            for season in contract["eligible_seasons"]
        },
    }


def make_observations(
    targets: Sequence[Mapping[str, Any]],
    upstream: Mapping[str, Any],
    cache: Mapping[str, tuple[float, Distribution]],
) -> list[model.ChanceObservation]:
    """Construct predictors only from the whitelisted OOS fields; retain true known_at."""
    references = {r["key"]: r for r in upstream["rows"]}
    target_map = {r["key"]: r for r in targets}
    if (
        len(target_map) != len(targets)
        or set(target_map) != set(references)
        or set(cache) != set(references)
    ):
        raise ValueError("chance targets, upstream and incumbent identity sets differ")
    observations = []
    for key, target in target_map.items():
        row = references[key]
        goals = target["goals"]
        if isinstance(goals, bool) or not isinstance(goals, int) or goals < 0:
            raise ValueError("trusted goal targets must be measured nonnegative integers")
        if row["provider"] != "pl_sdp":
            raise ValueError("canonical tactical provider identity changed")
        for field in ("season", "gw", "fixture", "team_code", "opponent_team_code", "was_home"):
            if target[field] != row[field]:
                raise ValueError(f"chance target identity differs: {key}: {field}")
        if target["goals"] != row["observed_goals"] or _timestamp(
            target["kickoff_time"]
        ) != _timestamp(row["kickoff_time"]):
            raise ValueError(f"chance target outcome/event differs: {key}")
        for target_field, source_field in (
            ("capture_id", "source_capture_id"),
            ("payload_sha256", "payload_sha256"),
            ("sdp_match_id", "sdp_match_id"),
        ):
            if target[target_field] != row[source_field]:
                raise ValueError(f"canonical provider revision differs: {key}: {target_field}")
        if (target["source_known_at"] is None) != (row["source_known_at"] is None) or (
            target["source_known_at"] is not None
            and _timestamp(target["source_known_at"]) != _timestamp(row["source_known_at"])
        ):
            raise ValueError(f"capture known_at differs: {key}")
        opponent = f"{row['season']}:{row['fixture']}:{row['opponent_team_code']}"
        shots = target["shots"]
        if shots is not None and (
            isinstance(shots, bool) or not math.isfinite(shots) or shots != int(shots)
        ):
            raise ValueError("measured shots must be an integer, never rounded")
        observations.append(
            model.ChanceObservation(
                season=row["season"],
                gw=row["gw"],
                fixture=row["fixture"],
                team_code=row["team_code"],
                opponent_team_code=row["opponent_team_code"],
                was_home=row["was_home"],
                kickoff=_timestamp(row["kickoff_time"]),
                as_of=_timestamp(row["as_of"]),
                goals=goals,
                shots=None if shots is None else int(shots),
                expected_goals=target["expected_goals"],
                predicted_state=tuple(row["predicted_state"]),
                predicted_opponent_state=tuple(row["predicted_opponent_state"]),
                incumbent_rate=cache[key][0],
                opponent_incumbent_rate=cache[opponent][0],
                incumbent_pmf=cache[key][1],
                maximum_state_source_event=_timestamp(row["maximum_state_source_event"])
                if row["maximum_state_source_event"]
                else None,
                maximum_style_training_event=_timestamp(row["maximum_style_training_event"])
                if row["maximum_style_training_event"]
                else None,
            )
        )
    model._validate(observations)
    return observations


def _mean(values: Sequence[float]) -> float:
    return math.fsum(values) / len(values) if values else 0.0


def _score_rows(rows: Sequence[Mapping[str, Any]], seed: int) -> dict[str, Any]:
    blocks: dict[str, Any] = {}
    for arm, name in (("incumbent", INCUMBENT), ("candidate", CANDIDATE)):
        predictions = [
            Prediction(
                season=r["season"],
                gw=r["gw"],
                key=r["key"],
                observed=r["observed_goals"],
                was_home=r["was_home"],
                distribution=tuple(r["distributions"][arm]),
                cold_start=r["state_cold_start"],
            )
            for r in rows
        ]
        block = scoring._score_block(name, predictions, seed=seed)
        probabilities = [float(r["clean_sheet_probabilities"][arm]) for r in rows]
        outcomes = [int(r["goals_allowed"] == 0) for r in rows]
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


def attach_evidence(
    experiment: dict[str, Any], upstream: Mapping[str, Any], promoted: Mapping[str, frozenset[int]]
) -> None:
    references = {r["key"]: r for r in upstream["rows"]}
    rows = experiment["history_rows"]
    keyed = {r["key"]: r for r in rows}
    if len(keyed) != len(rows) or set(keyed) != set(references):
        raise ValueError("candidate historical row population changed")
    for row in rows:
        source = references[row["key"]]
        counts = [*source["recent_counts"], *source["opponent_counts"]]
        if len(counts) != 10 or any(not isinstance(n, int) or not 0 <= n <= 5 for n in counts):
            raise ValueError("invalid frozen state history counts")
        row.update(
            {
                k: source[k]
                for k in (
                    "provider",
                    "sdp_match_id",
                    "source_capture_id",
                    "source_known_at",
                    "payload_sha256",
                    "state_source_keys_sha256",
                    "state_source_rows",
                    "recent_counts",
                    "opponent_counts",
                )
            }
        )
        row["state_cold_start"] = min(counts) < 3
        row["high_confidence"] = min(counts) == 5
        row["promoted_team"] = row["team_code"] in promoted.get(row["season"], frozenset())
        other = keyed[f"{row['season']}:{row['fixture']}:{row['opponent_team_code']}"]
        if row["goals_allowed"] != other["observed_goals"]:
            raise ValueError("reciprocal target goals differ")
        for arm in ("incumbent", "candidate"):
            pmf = row["distributions"][arm]
            if (
                len(pmf) != model.MAX_GOALS + 1
                or any(not math.isfinite(p) or p < 0 for p in pmf)
                or abs(math.fsum(pmf) - 1) > TOLERANCE
            ):
                raise ValueError("invalid retained goal PMF")
            if row["clean_sheet_probabilities"][arm] != other["distributions"][arm][0]:
                raise ValueError("clean sheet probability is not reciprocal PMF zero mass")
        row["paired_log_loss_difference"] = log_score(
            tuple(row["distributions"]["candidate"]), row["observed_goals"]
        ) - log_score(tuple(row["distributions"]["incumbent"]), row["observed_goals"])
        row["paired_cs_brier_difference"] = (
            row["clean_sheet_probabilities"]["candidate"] - row["observed_clean_sheet"]
        ) ** 2 - (row["clean_sheet_probabilities"]["incumbent"] - row["observed_clean_sheet"]) ** 2


def verify_run(
    experiment: Mapping[str, Any],
    observations: Sequence[model.ChanceObservation],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    expected = {r.key for r in observations if r.season in contract["eligible_seasons"]}
    rows = experiment["rows"]
    if (
        len(rows) != len(expected)
        or {r["key"] for r in rows} != expected
        or len(rows) != contract["expected_rows"]
    ):
        raise ValueError("outer scored population changed")
    if (
        len(experiment["folds"]) != contract["expected_folds"]
        or len(experiment["historical_folds"]) != contract["maximum_historical_batches"]
    ):
        raise ValueError("outer/historical fold count changed")
    observed = {r.key: r for r in observations}
    history = experiment["history_rows"]
    if len(history) != len(observed) or {r["key"] for r in history} != set(observed):
        raise ValueError("historical candidate population changed")
    for row in history:
        source = observed[row["key"]]
        if (
            row["observed_goals"] != source.goals
            or row["observed_shots"] != source.shots
            or row["observed_archive_xg"] != source.expected_goals
            or _timestamp(row["as_of"]) != source.as_of
            or _timestamp(row["kickoff_time"]) != source.kickoff
            or tuple(row["predicted_state"]) != source.predicted_state
            or tuple(row["predicted_opponent_state"]) != source.predicted_opponent_state
            or row["predictors"] != model.predictors(source)
            or tuple(row["distributions"]["incumbent"]) != source.incumbent_pmf
        ):
            raise ValueError("candidate changed trusted targets, inputs, cutoff or comparator")
        expected_pmf = (
            source.incumbent_pmf
            if row["incumbent_fallback"]
            else poisson_pmf(row["candidate_latent_rate"], max_goals=model.MAX_GOALS)
        )
        if tuple(row["distributions"]["candidate"]) != expected_pmf:
            raise ValueError("candidate distribution family or exact incumbent fallback changed")
    fits = 0
    for fold in experiment["historical_folds"]:
        cutoff = _timestamp(fold["as_of"])
        for name in (
            "event_time_violations",
            "same_gameweek_violations",
            "stacking_in_sample_rows",
        ):
            if fold[name] != 0:
                raise ValueError(f"candidate temporal violation: {name}")
        for fit in [*fold["stage_fits"].values(), fold["conversion_fit"]]:
            for key in ("maximum_training_event", "maximum_training_prediction_cutoff"):
                if fit.get(key) is not None and _timestamp(fit[key]) >= cutoff:
                    raise ValueError("future event or in-sample downstream training")
            if fit.get("model") is not None:
                fits += 1
                if fit["model"]["converged"] is not True or fit["model"]["penalty"] != model.RIDGE:
                    raise ValueError("uncertified chance fit")
    if fits > contract["maximum_stage_fits"]:
        raise ValueError("bounded chance-fit budget exceeded")
    return {
        "same_population": True,
        "event_time_violations": 0,
        "same_gameweek_violations": 0,
        "stacking_in_sample_rows": 0,
        "fitted_stage_models": fits,
        "prediction_keys_sha256": _digest(sorted(expected)),
    }


def score_experiment(experiment: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    rows = experiment["rows"]
    seed = contract["seed"]
    overall = _score_rows(rows, seed)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        for label in (
            f"season:{r['season']}",
            "GW1-6" if r["gw"] <= 6 else "GW7+",
            "home" if r["was_home"] else "away",
            "promoted" if r["promoted_team"] else "established",
            "cold_start" if r["state_cold_start"] else "non_cold_start",
            "confidence_high" if r["high_confidence"] else "confidence_low",
        ):
            grouped[label].append(r)
    slices = {label: _score_rows(group, seed) for label, group in sorted(grouped.items())}
    by_gw: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_gw[f"{r['season']}:{r['gw']:02d}"].append(r)
    control, candidate = overall["incumbent"], overall["candidate"]
    log_lift = 1 - candidate["mean_log_score"] / control["mean_log_score"]
    cs_lift = 1 - candidate["clean_sheet_brier"] / control["clean_sheet_brier"]
    checks = {
        "minimum_log_lift": log_lift >= contract["minimum_log_lift"],
        "minimum_cs_brier_lift": cs_lift >= contract["minimum_cs_brier_lift"],
        "no_crps_regression": candidate["crps"] <= control["crps"],
        "pit80": abs(candidate["pit_interval_80_coverage"] - 0.8)
        <= contract["maximum_pit80_absolute_error"],
        "no_season_log_regression": all(
            slices[f"season:{s}"]["candidate"]["mean_log_score"]
            <= slices[f"season:{s}"]["incumbent"]["mean_log_score"]
            for s in contract["eligible_seasons"]
        ),
        "no_season_cs_regression": all(
            slices[f"season:{s}"]["candidate"]["clean_sheet_brier"]
            <= slices[f"season:{s}"]["incumbent"]["clean_sheet_brier"]
            for s in contract["eligible_seasons"]
        ),
        "same_population": len(rows) == contract["expected_rows"],
        "zero_leakage": all(
            f[k] == 0
            for f in experiment["historical_folds"]
            for k in (
                "event_time_violations",
                "same_gameweek_violations",
                "stacking_in_sample_rows",
            )
        ),
    }
    verdict = "SUPPORTED" if all(checks.values()) else "INCONCLUSIVE"
    if min(log_lift, cs_lift) <= -contract["refutation_relative_regression"]:
        verdict = "REFUTED"
    return {
        "overall": overall,
        "slices": slices,
        "relative_log_lift": log_lift,
        "relative_cs_brier_lift": cs_lift,
        "gate": checks,
        "verdict": verdict,
        "paired_uncertainty": {
            metric: _clustered([r[field] for r in rows], rows, candidate=CANDIDATE)
            for metric, field in (
                ("log_score", "paired_log_loss_difference"),
                ("clean_sheet_brier", "paired_cs_brier_difference"),
            )
        },
        "by_gameweek": {
            key: {
                "scores": _score_rows(group, seed),
                "paired_log_loss_mean": _mean([r["paired_log_loss_difference"] for r in group]),
                "paired_cs_brier_mean": _mean([r["paired_cs_brier_difference"] for r in group]),
            }
            for key, group in sorted(by_gw.items())
        },
    }


def chance_diagnostics(experiment: Mapping[str, Any]) -> dict[str, Any]:
    history = experiment["history_rows"]
    folds = {(f["season"], f["gw"]): f for f in experiment["historical_folds"]}
    prior: list[dict[str, Any]] = []
    groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in history:
        groups[(row["season"], row["gw"])].append(row)
    for _, batch in sorted(
        groups.items(), key=lambda item: min(_timestamp(r["as_of"]) for r in item[1])
    ):
        cutoff = _timestamp(batch[0]["as_of"])
        visible = [r for r in prior if _timestamp(r["kickoff_time"]) < cutoff]
        for row in batch:
            own = sorted(
                [r for r in visible if r["team_code"] == row["team_code"]],
                key=lambda r: (_timestamp(r["kickoff_time"]), r["key"]),
                reverse=True,
            )
            row["diagnostic_prior_means"] = {
                label: _mean(measured[:5])
                if (measured := [r[field] for r in own if r[field] is not None])
                else None
                for label, field in (("shots", "observed_shots"), ("xg", "observed_archive_xg"))
            }
            row["diagnostic_quality_anchor"] = folds[(row["season"], row["gw"])]["stage_fits"][
                "quality"
            ]["anchor"]
        prior.extend(batch)
    rows = experiment["rows"]
    comparisons: dict[str, Any] = {}
    for name, prediction, target, baseline in (
        ("shots_vs_trailing_five", "predicted_shots", "observed_shots", "shots"),
        ("xg_vs_trailing_five", "predicted_xg", "observed_archive_xg", "xg"),
        ("xg_vs_incumbent_goal_rate", "predicted_xg", "observed_archive_xg", "incumbent"),
    ):
        pairs = [
            (
                r[prediction],
                r[target],
                r["incumbent_latent_rate"]
                if baseline == "incumbent"
                else r["diagnostic_prior_means"][baseline],
            )
            for r in rows
        ]
        measured = [
            (p, y, b) for p, y, b in pairs if p is not None and y is not None and b is not None
        ]
        comparisons[name] = {
            "paired_rows": len(measured),
            **{
                arm: {
                    "mae": _mean([abs(r[index] - r[1]) for r in measured]) if measured else None,
                    "rmse": math.sqrt(_mean([(r[index] - r[1]) ** 2 for r in measured]))
                    if measured
                    else None,
                }
                for arm, index in (("candidate", 0), ("baseline", 2))
            },
        }
    quality = [
        (
            r["predicted_quality"],
            r["observed_archive_xg"],
            r["observed_shots"],
            r["diagnostic_quality_anchor"],
        )
        for r in rows
    ]
    usable = [
        (p, xg, shots, anchor)
        for p, xg, shots, anchor in quality
        if p is not None
        and xg is not None
        and shots is not None
        and shots > 0
        and anchor is not None
    ]
    exposure = math.fsum(r[2] for r in usable)
    comparisons["quality_vs_pooled_prior"] = {
        "paired_rows": len(usable),
        "shot_exposure": exposure,
        **{
            arm: {
                "exposure_weighted_mae": math.fsum(
                    abs(r[index] - r[1] / r[2]) * r[2] for r in usable
                )
                / exposure
                if exposure
                else None,
                "exposure_weighted_rmse": math.sqrt(
                    math.fsum((r[index] - r[1] / r[2]) ** 2 * r[2] for r in usable) / exposure
                )
                if exposure
                else None,
            }
            for arm, index in (("candidate", 0), ("baseline", 3))
        },
    }
    rank_groups = [[r for r in rows if (r["season"], r["gw"]) == key] for key in groups]
    correlations = [
        _rank_correlation(
            [r["candidate_latent_rate"] for r in group], [r["incumbent_latent_rate"] for r in group]
        )
        for group in rank_groups
        if group
    ]
    reversals = comparable = 0
    for group in rank_groups:
        for i, left in enumerate(group):
            for right in group[i + 1 :]:
                old = left["incumbent_latent_rate"] - right["incumbent_latent_rate"]
                new = left["candidate_latent_rate"] - right["candidate_latent_rate"]
                comparable += int(old != 0)
                reversals += int(old * new < 0)
    return {
        "stages": model.chance_target_metrics(rows),
        "paired_baselines": comparisons,
        "by_season": {
            s: model.chance_target_metrics([r for r in rows if r["season"] == s])
            for s in sorted({r["season"] for r in rows})
        },
        "fallback_rows": sum(r["incumbent_fallback"] for r in rows),
        "conversion_by_fold": [
            {"season": f["season"], "gw": f["gw"], **f["conversion_fit"]}
            for f in experiment["folds"]
        ],
        "mean_absolute_log_rate_adjustment": _mean(
            [abs(r["log_rate_attribution"]["relative_to_incumbent"]) for r in rows]
        ),
        "candidate_vs_incumbent_within_gw_rank_correlation": (
            _mean(defined) if (defined := [v for v in correlations if v is not None]) else None
        ),
        "within_gw_strict_pair_order_reversals": reversals,
        "non_tied_incumbent_pairs": comparable,
        "diagnostic_only": True,
        "incumbent_rate_is_not_a_pure_xg_forecast": True,
    }


def run(root: Path, db: Path) -> dict[str, Any]:
    root, db = root.resolve(), db.resolve()
    _unclaimed(root)
    contract = load_contract(root)
    snapshot = _snapshot(root, db, contract)
    started = datetime.now(UTC).isoformat()
    with duckdb.connect(str(db), read_only=True) as con:
        coverage = build_audit(con)
        if _canonical(coverage) != _canonical(
            json.loads((root / contract["coverage_report"]).read_bytes())
        ):
            raise ValueError("coverage-only audit no longer reproduces exactly")
        if coverage["eligible_seasons"] != contract["eligible_seasons"]:
            raise ValueError("coverage-selected seasons changed")
        upstream = _load_upstream(root, contract)
        _verify_upstream_trace(upstream)
        targets = load_chance_targets(con)
        logger.info("Reproducing all 3,800 incumbent PMFs; no chance fit has started")
        cache, reproduction = reproduce_incumbent(con, contract, upstream)
        observations = make_observations(targets, upstream, cache)
        promoted = promoted_team_codes(con)
        if snapshot != _snapshot(root, db, contract):
            raise RuntimeError("provenance changed during incumbent reproduction")
        provenance = {
            **snapshot,
            "started_at_utc": started,
            "sdp_capture_versions_sha256": coverage["capture_versions_sha256"],
            "upstream_provenance": upstream["provenance"],
            "historical_rows": len(observations),
            "rows": contract["expected_rows"],
            "folds": contract["expected_folds"],
        }
        _unclaimed(root)
        reserve_claim(root, provenance)
        logger.info("Exclusive candidate identity reserved; beginning its one chance walk-forward")
        try:

            def progress(batch: dict[str, Any]) -> None:
                fold = batch["fold"]
                logger.info(
                    "Completed chance batch %s GW%s (%s prior completed rows)",
                    fold["season"],
                    fold["gw"],
                    fold["prior_completed_rows"],
                )

            experiment = model.run_chance_walk_forward(
                observations, tuple(contract["eligible_seasons"]), checkpoint=progress
            )
            attach_evidence(experiment, upstream, promoted)
            assertions = verify_run(experiment, observations, contract)
            diagnostics = chance_diagnostics(experiment)
            scores = score_experiment(experiment, contract)
            for metric in ("mean_log_score", "crps", "pit_interval_80_coverage"):
                if (
                    abs(
                        scores["overall"]["incumbent"][metric]
                        - reproduction["current_metrics"][metric]
                    )
                    > TOLERANCE
                ):
                    raise ValueError(f"retained comparator changed during candidate run: {metric}")
            if snapshot != _snapshot(root, db, contract):
                raise RuntimeError("provenance changed during formal candidate run")
            report = {
                "candidate": CANDIDATE,
                "artifact_kind": "completed_development_evaluation",
                "completed": True,
                "development_only": True,
                "promotion_permitted": False,
                "evidence_class": model.EVIDENCE_CLASS,
                "provenance": provenance,
                "completed_at_utc": datetime.now(UTC).isoformat(),
                "contract": contract,
                "coverage": coverage,
                "incumbent_reproduction": reproduction,
                "assertions": assertions,
                **scores,
                "chance_diagnostics": diagnostics,
                "fixture_predictions": experiment["rows"],
                "folds": experiment["folds"],
                "historical_chance_predictions": experiment["history_rows"],
                "historical_fit_provenance": experiment["historical_folds"],
                "upstream_style_fit_provenance": upstream["folds"],
                "prediction_count_by_season": dict(
                    Counter(r["season"] for r in experiment["rows"])
                ),
            }
            _publish_result(root / RESULT, report)
            return report
        except Exception as exc:
            failure = {
                "candidate": CANDIDATE,
                "artifact_kind": "execution_failure",
                "completed": False,
                "development_only": True,
                "promotion_permitted": False,
                "scientific_verdict_available": False,
                "candidate_identity_consumed": True,
                "resume_permitted": False,
                "evidence_class": model.EVIDENCE_CLASS,
                "attempt_provenance": provenance,
                "incumbent_reproduction": reproduction,
                "failed_at_utc": datetime.now(UTC).isoformat(),
                "failure": {
                    "class": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                    "state": _safe_json(getattr(exc, "state", None)),
                },
            }
            _publish_result(root / RESULT, failure)
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", type=Path, required=True, help="Explicit read-only hash-pinned archive database"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    report = run(repo_root(), args.db)
    logger.info("Completed %s: %s", CANDIDATE, report["verdict"])


if __name__ == "__main__":
    main()
