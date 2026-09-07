"""Read the frozen transition-role forecasts; no fitting or diagnostic-arm selection.

This boundary reconstructs the original retrospective DTOs, not a lossy role label.
The separately retained actual starting labels are never exposed as predictors.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import fields
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

from fpl.jobs.competitive_participation_pilot import file_sha256
from fpl.validate.player_role_history import (
    EVIDENCE_CLASS,
    NAME,
    ROLES,
    RoleBatchForecast,
    RoleDistribution,
    RoleHistoryRow,
    RolePrediction,
    RoleTarget,
)

RESULT_SHA256 = "c330d44a227ff6ff10cce1d5813f582d48dadfa181816c9333d6389358940809"
EVALUATION_HEAD = "9e1b34d9881cefdb45165c3e564b99b5c57141bc"
EXPECTED_ROWS = 29747
EXPECTED_PROXY_ROWS = 270


def _time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.utcoffset() is None:
        raise ValueError("role-cache timestamp must be timezone aware")
    return result


def _optional_time(value: str | None) -> datetime | None:
    return None if value is None else _time(value)


def _pmf(value: Any) -> RoleDistribution:
    if (
        not isinstance(value, (tuple, list))
        or len(value) != 4
        or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in value)
        or not math.isclose(math.fsum(value), 1, rel_tol=0, abs_tol=1e-12)
    ):
        raise ValueError("role cache requires four finite probabilities of unit mass")
    return cast(RoleDistribution, tuple(value))


def _exact_fields(raw: dict[str, Any], cls: type[Any], extras: set[str] | None = None) -> None:
    if set(raw) != {f.name for f in fields(cls)} | (extras or set()):
        raise ValueError(f"unexpected/missing {cls.__name__} cache fields")


def _source(raw: dict[str, Any]) -> RoleHistoryRow:
    _exact_fields(raw, RoleHistoryRow)
    decoded = dict(raw)
    for name in ("kickoff", "known_at", "interpretation_known_at"):
        decoded[name] = _time(raw[name])
    for name in ("max_event_at", "verified_end_at"):
        decoded[name] = _optional_time(raw[name])
    return RoleHistoryRow(**decoded)


def decode_role_batch(raw: dict[str, Any]) -> RoleBatchForecast:
    """Validate one hash-bound original fold, preserving every original DTO field."""
    _exact_fields(raw, RoleBatchForecast)
    if raw["name"] != NAME or raw["evidence_class"] != EVIDENCE_CLASS:
        raise ValueError("only the preregistered transition-role candidate is accepted")
    cutoff = _time(raw["as_of"])
    predictions = []
    keys = set()
    for item in raw["predictions"]:
        _exact_fields(item, RolePrediction, {"key", "arm_probabilities", "cache_reference"})
        target_raw = item["target"]
        _exact_fields(target_raw, RoleTarget)
        target = RoleTarget(
            **{
                **target_raw,
                "kickoff": _time(target_raw["kickoff"]),
                "as_of": _time(target_raw["as_of"]),
            }
        )
        key = f"{target.season}:{target.fixture}:{target.code}"
        if (
            (target.season, target.gw, target.as_of) != (raw["season"], raw["gw"], cutoff)
            or item["key"] != key
            or key in keys
        ):
            raise ValueError("role cache target identity/batch/duplicate differs")
        keys.add(key)
        decoded = {f.name: item[f.name] for f in fields(RolePrediction)}
        decoded["target"] = target
        for name in (
            "probabilities",
            "pooled_prior_baseline",
            "smoothed_last_role_baseline",
            "recent_state_persistence_baseline",
        ):
            decoded[name] = _pmf(item[name])
        decoded["recent_distribution"] = (
            None if item["recent_distribution"] is None else _pmf(item["recent_distribution"])
        )
        for name in (
            "maximum_prior_event",
            "maximum_source_known_at",
            "maximum_interpretation_known_at",
            "maximum_retained_event",
        ):
            decoded[name] = _optional_time(item[name])
        decoded["recent_sources"] = tuple(_source(s) for s in item["recent_sources"])
        prediction = RolePrediction(**decoded)
        if (
            prediction.evidence_class != EVIDENCE_CLASS
            or prediction.promotion_permitted is not False
            or prediction.conditionality != "role_given_hypothetical_start_not_start_probability"
            or prediction.membership_limitation
            != "observed_club_spell_only_unobserved_transfers_unresolved"
            or prediction.latest_observed_role not in (*ROLES, None)
            or type(prediction.recent_measured_starts) is not int
            or prediction.recent_measured_starts != len(prediction.recent_sources)
            or not 0 <= prediction.recent_measured_starts <= 5
            or prediction.recent_weight
            != prediction.recent_measured_starts / (prediction.recent_measured_starts + 2)
            or type(prediction.witnessed_current_club_spell) is not bool
        ):
            raise ValueError("role conditionality/current-club evidence differs")
        for maximum in (prediction.maximum_prior_event, prediction.maximum_retained_event):
            if maximum is not None and maximum >= cutoff:
                raise ValueError("role upstream event reaches prediction cutoff")
        for source in prediction.recent_sources:
            end = source.verified_end_at or source.kickoff + timedelta(hours=6)
            if (
                source.completed is not True
                or source.role is None
                or (source.code, source.team_code) != (target.code, target.team_code)
                or source.kickoff >= cutoff
                or end >= cutoff
                or (source.max_event_at is not None and source.max_event_at >= cutoff)
                or (
                    source.competition_id == 8
                    and (source.season, source.gw) == (target.season, target.gw)
                )
            ):
                raise ValueError("role source is unmeasured, future, target-GW or wrong club")
        arms = item["arm_probabilities"]
        expected_arms = {
            "candidate": prediction.probabilities,
            "pooled_prior": prediction.pooled_prior_baseline,
            "smoothed_last_role": prediction.smoothed_last_role_baseline,
            "recent_state_persistence": prediction.recent_state_persistence_baseline,
        }
        if set(arms) != set(expected_arms) or any(
            _pmf(arms[k]) != v for k, v in expected_arms.items()
        ):
            raise ValueError("role candidate was replaced by another diagnostic arm")
        ref = item["cache_reference"]
        if ref["price_proxy_not_role_predictor"] is not True:
            raise ValueError("role reference must not use target price as a role predictor")
        predictions.append(prediction)
    if not predictions or min(p.target.kickoff for p in predictions) != cutoff:
        raise ValueError("role fold must contain the complete first-kickoff target batch")
    decoded_batch = dict(raw)
    decoded_batch.update(
        as_of=cutoff,
        predictions=tuple(predictions),
        global_prior=_pmf(raw["global_prior"]),
        role_counts=tuple(raw["role_counts"]),
        transition_counts=tuple(tuple(r) for r in raw["transition_counts"]),
        transition_matrix=tuple(_pmf(r) for r in raw["transition_matrix"]),
        source_versions=tuple(tuple(r) for r in raw["source_versions"]),
    )
    batch = RoleBatchForecast(**decoded_batch)
    if (
        len(batch.role_counts) != 4
        or len(batch.transition_counts) != 4
        or any(len(r) != 4 for r in batch.transition_counts)
        or len(batch.transition_matrix) != 4
        or any(type(v) is not int or v < 0 for v in batch.role_counts)
        or any(type(v) is not int or v < 0 for r in batch.transition_counts for v in r)
        or sum(batch.role_counts) != batch.prior_role_targets
        or len(batch.source_rows_sha256) != 64
        or any(c not in "0123456789abcdef" for c in batch.source_rows_sha256)
    ):
        raise ValueError("role batch training certificate is malformed")
    for prediction in batch.predictions:
        for source in prediction.recent_sources:
            certificate = (
                source.capture_id,
                source.payload_sha256,
                source.known_at.isoformat(),
                source.interpretation_known_at.isoformat(),
            )
            if certificate not in batch.source_versions:
                raise ValueError("role recent source missing from training version certificate")
    return batch


def load_role_cache(
    result_path: Path, *, root: Path, expected_result_sha256: str = RESULT_SHA256
) -> dict[tuple[str, int], RoleBatchForecast]:
    """Load all 29,747 frozen OOS forecasts, never actual target roles or refit calls."""
    if expected_result_sha256 != RESULT_SHA256 or file_sha256(result_path) != RESULT_SHA256:
        raise ValueError("role result differs from the sole frozen transition candidate")
    result = json.loads(result_path.read_bytes())
    provenance = result["provenance"]
    if (
        result["completed"] is not True
        or result["promotion_permitted"] is not False
        or provenance["identity"] != NAME
        or provenance["evidence_class"] != EVIDENCE_CLASS
        or provenance["git_head"] != EVALUATION_HEAD
        or provenance["clean_worktree"] is not True
        or provenance["historical_deadline_knowledge_validity"] is not False
    ):
        raise ValueError("role completed-run evidence does not match preregistration")
    for name, digest in provenance["source_sha256"].items():
        if file_sha256(root / name) != digest:
            raise ValueError(f"frozen role source changed: {name}")
    directory = result_path.resolve().parent
    source_versions = json.loads((directory / "source_versions.json").read_bytes())
    encoded = json.dumps(
        source_versions, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    if hashlib.sha256(encoded).hexdigest() != result["coverage"]["source_version_identity"]:
        raise ValueError("role source version ledger differs")
    output = {}
    row_count, proxies = 0, 0
    for entry in result["folds"]:
        path = (directory / entry["file"]).resolve()
        if path.parent != directory or path.name != f"2025-26-gw{entry['gw']:02d}.json":
            raise ValueError("role fold path escapes expected immutable cache")
        if file_sha256(path) != entry["sha256"]:
            raise ValueError("role fold hash differs")
        payload = json.loads(path.read_bytes())
        batch = decode_role_batch(payload)
        key = batch.season, batch.gw
        if key in output or batch.gw != entry["gw"] or len(batch.predictions) != entry["rows"]:
            raise ValueError("role fold counts/identities differ")
        output[key] = batch
        row_count += len(batch.predictions)
        proxies += sum(
            p["cache_reference"]["price_proxy_dependent"] for p in payload["predictions"]
        )
    if (
        set(output) != {("2025-26", gw) for gw in range(1, 39)}
        or row_count != EXPECTED_ROWS
        or proxies != EXPECTED_PROXY_ROWS
    ):
        raise ValueError("role all-roster population or price-proxy lineage differs")
    return output
