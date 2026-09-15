"""Coverage-only licensing of historical chance targets; no model fitting."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

import duckdb

from fpl.features.pit import AsOf
from fpl.validate.retrospective_sdp import RetrospectiveBackfillView
from fpl.validate.v2_environment_harness import load_team_frame

TARGETS = {
    "shots": "totalScoringAtt",
    "shots_inside_box": "attemptsIbox",
    "shots_on_target": "ontargetScoringAtt",
    "box_touches": "touchesInOppBox",
    "big_chances_created": "bigChanceCreated",
    "provider_expected_goals": "expectedGoals",
}


def load_chance_targets(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    frame = load_team_frame(con, provider="fpl_archive")
    latest = frame["kickoff_time"].max()
    if not isinstance(latest, datetime):
        raise ValueError("no historical archive event boundary")
    anchor = RetrospectiveBackfillView(con, AsOf(latest + timedelta(microseconds=1)))
    rows = anchor.observed_real_sot().to_dicts()
    metrics: dict[tuple[str, str, str], float | None] = {}
    for capture, side, field, value in con.execute(
        "SELECT payload_id, side, provider_field, value_numeric "
        "FROM stg_pl_sdp_team_match_metric WHERE provider_field IN "
        "(SELECT unnest(?))",
        [list(TARGETS.values())],
    ).fetchall():
        key = (str(capture), str(side), str(field))
        if key in metrics:
            raise ValueError("duplicate provider metric version")
        metrics[key] = None if value is None else float(value)
    for row in rows:
        row["key"] = f"{row['season']}:{row['fixture']}:{row['team_code']}"
        side = "home" if row["was_home"] else "away"
        for local, provider in TARGETS.items():
            value = metrics.get((row["capture_id"], side, provider))
            if value is not None and (
                not math.isfinite(value)
                or value < 0
                or (local != "provider_expected_goals" and value != round(value))
            ):
                raise ValueError(f"invalid measured {provider}: {row['key']}")
            row[local] = value
    return rows


def eligible_seasons(rows: Sequence[dict[str, Any]], threshold: float = 0.95) -> list[str]:
    """Complete 380-fixture seasons, paired targets, and an earlier complete season."""
    if not math.isfinite(threshold) or not 0 < threshold <= 1:
        raise ValueError("coverage threshold must be in (0,1]")
    report = coverage(rows)
    complete = {s for s, r in report.items() if r["sides"] == 760 and r["fixtures"] == 380}
    return [
        s
        for s in sorted(complete)
        if any(p < s for p in complete) and report[s]["paired_joint_coverage"] >= threshold
    ]


def coverage(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    keyed = {r["key"]: r for r in rows}
    if len(keyed) != len(rows):
        raise ValueError("duplicate chance identity")
    report: dict[str, Any] = {}
    for season in sorted({r["season"] for r in rows}):
        selected = [r for r in rows if r["season"] == season]
        paired = 0
        for row in selected:
            other = keyed.get(f"{season}:{row['fixture']}:{row['opponent_team_code']}")
            if (
                other is None
                or other["opponent_team_code"] != row["team_code"]
                or other["was_home"] == row["was_home"]
                or any(
                    other[k] != row[k] for k in ("gw", "kickoff_time", "sdp_match_id", "capture_id")
                )
                or other["goals"] != row["goals_allowed"]
                or other["goals_allowed"] != row["goals"]
            ):
                raise ValueError("missing reciprocal chance identity")
            paired += int(
                all(
                    r.get(k) is not None
                    for r in (row, other)
                    for k in ("goals", "expected_goals", "shots")
                )
            )
        report[season] = {
            "sides": len(selected),
            "fixtures": len({r["fixture"] for r in selected}),
            "paired_joint_sides": paired,
            "paired_joint_coverage": paired / len(selected),
            "targets": {
                name: {
                    "measured": sum(r.get(name) is not None for r in selected),
                    "explicit_zero": sum(r.get(name) == 0 for r in selected),
                    "missing": sum(r.get(name) is None for r in selected),
                }
                for name in ("goals", "expected_goals", *TARGETS)
            },
        }
    return report


def build_audit(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    rows = load_chance_targets(con)
    versions = sorted(
        {
            (
                r["sdp_match_id"],
                r["capture_id"],
                r["source_known_at"].isoformat(),
                r["payload_sha256"],
            )
            for r in rows
            if r["capture_id"] is not None
        }
    )
    return {
        "audit_kind": "chance_targets_coverage_only_no_model_scores",
        "evidence_class": "retrospective_backfill_development",
        "version_policy": RetrospectiveBackfillView.VERSION_POLICY,
        "capture_versions": versions,
        "capture_versions_sha256": hashlib.sha256(
            json.dumps(versions, separators=(",", ":")).encode()
        ).hexdigest(),
        "by_season": coverage(rows),
        "eligible_seasons": eligible_seasons(rows),
        "threshold": 0.95,
        "licensed_targets": ["archive_expected_goals", "SDP_totalScoringAtt"],
        "semantics": {
            "goals": "existing trusted recorded archive target",
            "expected_goals": "existing summed FPL/archive player xG; provider unchanged",
            "totalScoringAtt": "provider-labelled total attempts; development licensed",
            "quality": "archive xG divided by SDP attempts: cross-source descriptive ratio, "
            "not provider-reported per-shot quality; no rounding or zero filling",
            "excluded": "SDP xG, big chances and box-only counts not required targets; "
            "semantic/coverage audit cannot license missing-as-zero",
        },
        "model_fitting_performed": False,
    }
