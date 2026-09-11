"""Versioned SOT interpretation for retrospective research, never a raw-data repair.

Omission alone is NOT zero. A zero needs either a matched independent match report, or
concordant shot accounting AND the separate FPL goalkeeper proxy, without positive target
evidence. Raw SOT, provider identity and original capture time are always retained.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Self

import duckdb
import polars as pl
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from fpl.config import config_dir, repo_root
from fpl.features.pit import AsOf
from fpl.ingest.pl_sdp import parse_team_stats
from fpl.storage.db import connect, default_db_path
from fpl.validate.dev_v2_real_sot import (
    _capture_manifest,
    _json_bytes,
    _latest_archive_cutoff,
    file_sha256,
)
from fpl.validate.retrospective_sdp import EVIDENCE_CLASS, RetrospectiveBackfillView
from fpl.validate.v2_environment_harness import load_team_frame

POLICY = "corroborated_omitted_sot_zero_v1"
POLICY_FILE = "pl_sdp_sot_zero_interpretation.yaml"
AUDIT_FILE = "pl_sdp_sot_zero_audit.json"
INTERPRETED_COLUMN = "shots_on_target_corroborated"
_SOT = "ontargetScoringAtt"
_SHOT_FIELDS = ("totalScoringAtt", "shotOffTarget", "blockedScoringAtt")
_TARGET_FIELDS = (
    "goals",
    "expectedGoalsOnTarget",
    "attIboxTarget",
    "attOboxTarget",
    "attHdTarget",
    "attLfTarget",
    "attRfTarget",
    "attObpTarget",
    "attIboxGoal",
    "attOboxGoal",
    "attPenGoal",
    "attFreekickGoal",
)
_KEYS = ["season", "fixture", "team_code"]


class IndependentZero(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    season: str
    fixture: int = Field(gt=0)
    team_code: int = Field(gt=0)
    sdp_match_id: int = Field(gt=0)
    source_url: str = Field(pattern=r"^https://")
    evidence: str = Field(min_length=20)


class SotZeroPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    policy: Literal["corroborated_omitted_sot_zero_v1"]
    evidence_class: Literal["retrospective_backfill_development"]
    reviewed_at: datetime
    definition_source: Literal["https://www.statsperform.com/opta-event-definitions/"]
    independent_zeros: tuple[IndependentZero, ...]

    @model_validator(mode="after")
    def _unique_evidence(self) -> Self:
        AsOf(self.reviewed_at)
        keys = [(r.season, r.fixture, r.team_code) for r in self.independent_zeros]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate independently reported zero identity")
        return self


def load_policy(path: Path | None = None) -> SotZeroPolicy:
    return SotZeroPolicy.model_validate(
        yaml.safe_load((path or config_dir() / POLICY_FILE).read_bytes())
    )


def _count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if not math.isfinite(value) or value < 0 or value != int(value):
        return None
    return int(value)


def interpret_omission(
    stats: Mapping[str, object], *, proxy: object, independent: IndependentZero | None
) -> tuple[int | None, str]:
    """Return a labelled interpretation; never treat explicit NULL as omitted zero."""
    if _SOT in stats:
        value = _count(stats[_SOT])
        if stats[_SOT] is not None and value is None:
            raise ValueError("provider SOT is not a non-negative integer count")
        return value, "provider_explicit" if value is not None else "unresolved_explicit_null"
    if independent is not None:
        return 0, "independent_report_zero"
    total = _count(stats.get("totalScoringAtt"))
    parts = [stats[k] for k in _SHOT_FIELDS[1:] if k in stats]
    counts = [_count(v) for v in parts]
    target_evidence = [stats[k] for k in _TARGET_FIELDS if k in stats]
    # Explicit NULL/malformed target evidence is uncertainty, not evidence of absence.
    positive_target = any(
        isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v) or v != 0
        for v in target_evidence
    )
    if (
        total is not None
        and total > 0
        and counts
        and None not in counts
        and sum(v for v in counts if v is not None) == total
        and _count(proxy) == 0
        and not positive_target
    ):
        return 0, "shot_accounting_and_fpl_proxy_zero"
    return None, "unresolved_omission"


def build_audit(con: duckdb.DuckDBPyConnection, policy: SotZeroPolicy) -> dict[str, Any]:
    """Audit every canonical historical side, without fitting/scoring any model."""
    archive = load_team_frame(con, provider="fpl_archive")
    history = RetrospectiveBackfillView(con, _latest_archive_cutoff(archive)).observed_real_sot()
    independent = {(r.season, r.fixture, r.team_code): r for r in policy.independent_zeros}
    con.register("sot_zero_audit_history", history.to_arrow())
    try:
        source_rows = con.execute("""
            SELECT h.season, h.fixture, h.team_code, r.payload, r.sha256,
                   s.stats_json, o.shots_on_target_allowed_proxy, t.team_name
            FROM sot_zero_audit_history h
            LEFT JOIN raw_pl_sdp_payload r ON r.payload_id = h.capture_id
            LEFT JOIN stg_pl_sdp_team_match_stats s ON s.payload_id = h.capture_id
              AND s.sdp_match_id = h.sdp_match_id
              AND s.side = CASE WHEN h.was_home THEN 'home' ELSE 'away' END
            JOIN mart_fact_team_match_stats_v2 o
              ON o.provider = 'fpl_archive' AND o.season = h.season
              AND o.fixture = h.fixture AND o.team_code = h.opponent_team_code
            JOIN mart_dim_team t ON t.season = h.season AND t.team_code = h.team_code
            ORDER BY h.season, h.fixture, h.team_code
        """).fetchall()
    finally:
        con.unregister("sot_zero_audit_history")
    source = {tuple(r[:3]): r[3:] for r in source_rows}
    if len(source_rows) != history.height or len(source) != history.height:
        raise ValueError("audit source join changed the team-fixture grain")
    parsed: dict[str, dict[str, tuple[int | None, Mapping[str, Any]]]] = {}
    counts: dict[str, Counter[str]] = {}
    decisions: list[dict[str, Any]] = []
    partition_exceptions: list[dict[str, Any]] = []
    observed_references: set[tuple[str, int, int]] = set()
    for row in history.sort(_KEYS).iter_rows(named=True):
        key = tuple(row[k] for k in _KEYS)
        raw, sha, staged, proxy, team_name = source[key]
        capture = row["capture_id"]
        stats: Mapping[str, Any] = {}
        if capture is not None:
            if capture not in parsed:
                if raw is None or hashlib.sha256(raw.encode()).hexdigest() != sha:
                    raise ValueError(f"raw payload content SHA mismatch: {capture}")
                parsed[capture] = {
                    side.side: (side.team_id, side.stats)
                    for side in parse_team_stats(json.loads(raw), match_id=row["sdp_match_id"])
                }
            provider_team, stats = parsed[capture]["home" if row["was_home"] else "away"]
            if provider_team != row["team_code"]:
                raise ValueError(f"raw payload team identity differs from archive: {key}")
            if staged is None or dict(stats) != json.loads(staged):
                raise ValueError(f"staging differs from retained raw payload: {key}")
        reference = independent.get(key)
        if reference is not None:
            if reference.sdp_match_id != row["sdp_match_id"] or capture is None:
                raise ValueError(f"independent report has wrong provider match identity: {key}")
            observed_references.add(key)
        value, reason = interpret_omission(stats, proxy=proxy, independent=reference)
        raw_value = row["shots_on_target"]
        if raw_value != _count(stats.get(_SOT)):
            raise ValueError(f"canonical SOT differs from retained exact field: {key}")
        if reference is not None and raw_value not in (None, 0):
            raise ValueError(f"independent zero contradicts explicit provider SOT: {key}")
        season_counts = counts.setdefault(row["season"], Counter())
        season_counts["team_rows"] += 1
        season_counts["xg_non_null"] += row["expected_goals"] is not None
        season_counts["raw_sot_non_null"] += raw_value is not None
        season_counts["interpreted_sot_non_null"] += value is not None
        season_counts["corroborated_zeros"] += raw_value is None and value == 0
        season_counts["unresolved"] += value is None
        season_counts["joint_non_null"] += row["expected_goals"] is not None and value is not None
        season_counts[reason] += 1
        components = {k: stats.get(k) for k in _SHOT_FIELDS}
        complete = [_count(components[k]) for k in _SHOT_FIELDS]
        if raw_value is not None and None not in complete:
            total, off, blocked = (int(v) for v in complete if v is not None)
            season_counts["complete_shot_partition_rows"] += 1
            delta = total - off - blocked - raw_value
            if delta:
                partition_exceptions.append(
                    {
                        **{k: row[k] for k in _KEYS},
                        "sdp_match_id": row["sdp_match_id"],
                        "shots_on_target": raw_value,
                        "components": components,
                        "residual": delta,
                        "capture_id": capture,
                        "payload_sha256": sha,
                    }
                )
        if raw_value is None:
            decisions.append(
                {
                    **{
                        k: row[k]
                        for k in (*_KEYS, "sdp_match_id", "was_home", "opponent_team_code")
                    },
                    "team_name": team_name,
                    "kickoff_time": row["kickoff_time"].isoformat(),
                    "capture_id": capture,
                    "source_known_at": row["source_known_at"].isoformat()
                    if row["source_known_at"] is not None
                    else None,
                    "payload_sha256": sha,
                    "raw_sot": None,
                    "raw_field_present": _SOT in stats,
                    "interpreted_sot": value,
                    "reason": reason,
                    "shot_components": components,
                    "fpl_opponent_sot_proxy": proxy,
                    "positive_target_fields": {k: stats[k] for k in _TARGET_FIELDS if stats.get(k)},
                    "independent_source": reference.model_dump() if reference is not None else None,
                }
            )
    if set(independent) != observed_references:
        raise ValueError("independent zero reference does not match a completed archive side")
    season_reports: dict[str, dict[str, Any]] = {}
    for season, values in sorted(counts.items()):
        coverage = values["joint_non_null"] / values["team_rows"]
        season_reports[season] = {
            **dict(values),
            "joint_coverage": coverage,
            "eligible": coverage >= 0.95,
        }
    return {
        "schema_version": 1,
        "policy": policy.policy,
        "evidence_class": EVIDENCE_CLASS,
        "audit_type": "semantics_and_coverage_only_no_model_scoring",
        "interpretation_reviewed_at": policy.reviewed_at.isoformat(),
        "definition_source": policy.definition_source,
        "seasons": season_reports,
        "eligible_seasons": [s for s, r in season_reports.items() if r["eligible"]],
        "canonical_capture_manifest_sha256": hashlib.sha256(
            _json_bytes(_capture_manifest(history))
        ).hexdigest(),
        "raw_payloads_verified": len(parsed),
        "missing_sot_decisions": decisions,
        "explicit_sot_partition_exceptions": partition_exceptions,
        "raw_values_changed": False,
        "known_at_rewritten": False,
        "interpretation_is_direct_provider_observation": False,
    }


class CorroboratedSotBackfillView:
    """Explicit validation-only interpretation over the unchanged retrospective capability."""

    def __init__(self, con: duckdb.DuckDBPyConnection, as_of: AsOf, audit: Mapping[str, Any]):
        if audit.get("policy") != POLICY or audit.get("evidence_class") != EVIDENCE_CLASS:
            raise ValueError("unlicensed SOT interpretation/evidence class")
        self._view = RetrospectiveBackfillView(con, as_of)
        rows = audit["missing_sot_decisions"]
        self._decisions = {(r["season"], r["fixture"], r["team_code"]): r for r in rows}
        if len(self._decisions) != len(rows):
            raise ValueError("duplicate SOT interpretation identity")

    def observed_corroborated_sot(self) -> pl.DataFrame:
        history = self._view.observed_real_sot()
        values: list[int | None] = []
        reasons: list[str] = []
        for row in history.iter_rows(named=True):
            decision = self._decisions.get(tuple(row[k] for k in _KEYS))
            value = row["shots_on_target"]
            reason = "provider_explicit" if value is not None else "unresolved_omission"
            if decision is not None:
                known = row["source_known_at"]
                identity = {
                    "capture_id": row["capture_id"],
                    "payload_sha256": row["payload_sha256"],
                    "sdp_match_id": row["sdp_match_id"],
                    "was_home": row["was_home"],
                    "opponent_team_code": row["opponent_team_code"],
                    "source_known_at": known.isoformat() if known is not None else None,
                    "kickoff_time": row["kickoff_time"].isoformat(),
                }
                if any(decision.get(k) != v for k, v in identity.items()) or value is not None:
                    raise ValueError("SOT interpretation no longer matches canonical raw evidence")
                interpreted = decision["interpreted_sot"]
                if interpreted is not None and (
                    isinstance(interpreted, bool)
                    or interpreted != 0
                    or decision["raw_field_present"]
                    or row["capture_id"] is None
                    or decision["reason"]
                    not in {"independent_report_zero", "shot_accounting_and_fpl_proxy_zero"}
                ):
                    raise ValueError("unlicensed zero interpretation")
                value, reason = interpreted, decision["reason"]
            values.append(value)
            reasons.append(reason)
        return history.with_columns(
            pl.Series(INTERPRETED_COLUMN, values, dtype=pl.Int64),
            pl.Series("sot_interpretation", reasons, dtype=pl.String),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=default_db_path())
    args = parser.parse_args()
    path = repo_root() / "results" / AUDIT_FILE
    if path.exists():
        raise FileExistsError(f"refusing to overwrite frozen SOT audit: {path}")
    policy_path = config_dir() / POLICY_FILE
    con = connect(args.db, read_only=True)
    try:
        report = build_audit(con, load_policy(policy_path))
    finally:
        con.close()
    report["policy_sha256"] = file_sha256(policy_path)
    report["database_sha256"] = file_sha256(args.db)
    with path.open("xb") as output:
        output.write(_json_bytes(report))
    print(json.dumps(report["seasons"], indent=2))


if __name__ == "__main__":
    main()
