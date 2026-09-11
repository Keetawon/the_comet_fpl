"""Read-only, deterministic attribution of SDP primary-selector fallbacks.

This module never stages, captures, fits, or promotes anything. Given a saved primary
artifact, it reads the artifact's recorded ``football_environment.provenance`` decisions
as the authoritative account of which fixture used which selector, then re-derives the
same attribution independently at the artifact's own cutoff (via
``sdp_runtime.load_sdp_state`` / ``raw_at`` and the strict ``PointInTimeView``
crosswalk) so agreement and disagreement are both visible. Original decisions are never
rewritten; an environment-disabled artifact, a missing decision, or an identity
disagreement fails closed.

Every category is attributed with positive proof from cutoff-eligible evidence;
``OTHER`` is reserved for genuinely unknown causes and zeros are never fabricated for
missing measurements. Later-only source versions are at most counted and labelled
EXCLUDED; they are never selector, history, or fixability input.

Fixability rule: a root cause is ``FIXABLE_NOW`` only when the LATEST cutoff-eligible
raw version and the newest cutoff-eligible metadata for that match are fully valid
(body hash, identity, ``checked_metrics``) yet unstaged/unselected -- a stale or missing
normalization. An older valid version under a newer defective eligible revision cannot
be resurrected (newest-valid selection is by design), and identity/revision failures are
never fixable. Everything else is ``LEGITIMATE_FAIL_CLOSED``. A fixture with several
blocking matches is fixable only when every blocker is resolvable and the saved failure
is not a global model/source outage; all blockers are reported.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from fpl.artifacts.prospective_points import ProspectivePointsArtifact
from fpl.config import load_sources, repo_root
from fpl.features.pit import AsOf, FeatureSource, PointInTimeView
from fpl.football_configuration import FootballEnvironmentConfig, load_football_environment
from fpl.ingest.pl_sdp import (
    extract_items,
    is_completed_scored_match,
    parse_match_summary,
    parse_team_stats,
)
from fpl.models.sdp_environment import FrozenSdpModel
from fpl.storage.db import table_exists
from fpl.storage.sdp_runtime import (
    CORE_FIELDS,
    EXTRA_FIELDS,
    SdpHealthError,
    SdpState,
    SdpStateRow,
    checked_metrics,
    load_sdp_state,
    raw_at,
)
from fpl.transform.competitive_participation import uint
from fpl.transform.pl_sdp import KICKOFF_TOLERANCE_SECONDS

CATEGORY_PRIMARY = "SDP_PRIMARY"
CATEGORY_SDP_MISSING = "SDP_MISSING"
CATEGORY_SDP_INCOMPLETE = "SDP_INCOMPLETE"
CATEGORY_SDP_SCHEMA = "SDP_SCHEMA"
CATEGORY_SDP_IDENTITY = "SDP_IDENTITY"
CATEGORY_SDP_INVALID_NUMERIC = "SDP_INVALID_NUMERIC"
CATEGORY_SDP_DUPLICATE = "SDP_DUPLICATE"
CATEGORY_SDP_SOURCE = "SDP_SOURCE"
CATEGORY_INSUFFICIENT_RECENT_HISTORY = "INSUFFICIENT_RECENT_HISTORY"
CATEGORY_COLD_START = "COLD_START"
CATEGORY_SOURCE_NOT_CUTOFF_ELIGIBLE = "SOURCE_NOT_CUTOFF_ELIGIBLE"
CATEGORY_MISSING_REQUIRED_ARTIFACT = "MISSING_REQUIRED_ARTIFACT"
CATEGORY_OTHER = "OTHER"

FIXABLE_NOW = "FIXABLE_NOW"
LEGITIMATE_FAIL_CLOSED = "LEGITIMATE_FAIL_CLOSED"

REQUIRED_RECENT_MATCHES = 5
PROVENANCE_KEY = "football_environment.provenance"
FROZEN_PRIOR_PROCEDURE = (
    "fpl.validate.tactical_state.current_state: fixed last-five current-season EWMA "
    "(weights 1, 0.707, 0.5, 0.354, 0.25) shrunk toward the measured league prior; "
    "missing raw values consume a chronological slot and are never zero-filled"
)
_NOT_CUTOFF_KNOWN_DETAIL = "model was not known at prediction cutoff"
_ARTIFACT_DETAIL_MARKER = "frozen model artifact"
_NUMERIC_DETAIL_MARKERS = (
    "invalid field:",
    "nonintegral count:",
    "possession exceeds",
    " exceeds ",
)
_DUPLICATE_DETAIL_MARKER = "duplicate provider match record"
_CROSSWALK_COLUMNS = (
    "season",
    "gw",
    "fixture",
    "team_code",
    "opponent_team_code",
    "was_home",
    "kickoff_time",
    "sdp_match_id",
    "capture_id",
    "payload_sha256",
    "source_known_at",
    "metadata_capture_id",
    "metadata_known_at",
    "known_at",
)
_LATER_ONLY_USAGE = "EXCLUDED: later-only capture; never selector, history, or fixability input"


def _iso(value: datetime) -> str:
    return value.isoformat()


def categorize(reason: str | None, detail: str = "") -> str:
    """Map a recorded selector reason (and its detail) to a report category."""
    if _NOT_CUTOFF_KNOWN_DETAIL in detail:
        return CATEGORY_SOURCE_NOT_CUTOFF_ELIGIBLE
    if _ARTIFACT_DETAIL_MARKER in detail:
        return CATEGORY_MISSING_REQUIRED_ARTIFACT
    if reason is None or reason == CATEGORY_PRIMARY:
        return CATEGORY_PRIMARY
    if reason == "SDP_MISSING_FALLBACK":
        return CATEGORY_SDP_MISSING
    if reason == "SDP_SOURCE_FALLBACK":
        return CATEGORY_SDP_SOURCE
    if reason == "SDP_INCOMPLETE_FALLBACK":
        return CATEGORY_SDP_INCOMPLETE
    if reason == "SDP_IDENTITY_FALLBACK":
        if _DUPLICATE_DETAIL_MARKER in detail:
            return CATEGORY_SDP_DUPLICATE
        return CATEGORY_SDP_IDENTITY
    if reason == "SDP_SCHEMA_FALLBACK":
        if any(marker in detail for marker in _NUMERIC_DETAIL_MARKERS):
            return CATEGORY_SDP_INVALID_NUMERIC
        return CATEGORY_SDP_SCHEMA
    return CATEGORY_OTHER


def metric_issues(stats: Any) -> list[dict[str, str]]:
    """Enumerate field-level problems for the report.

    ``checked_metrics`` stays the authoritative validity gate; this enumeration only
    explains WHICH fields were absent or invalid. Absent optional (``EXTRA_FIELDS``)
    values are unavailable, not issues.
    """
    if not isinstance(stats, dict):
        return [{"field": "*", "status": "schema", "detail": "stats mapping required"}]
    issues: list[dict[str, str]] = []
    values: dict[str, float] = {}
    for key in (*CORE_FIELDS, *EXTRA_FIELDS):
        raw = stats.get(key)
        if raw is None:
            if key in CORE_FIELDS:
                issues.append(
                    {"field": key, "status": "absent_required", "detail": "required field absent"}
                )
            continue
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
            issues.append({"field": key, "status": "non_numeric", "detail": "non-numeric field"})
            continue
        try:
            value = float(raw)
        except ValueError:
            issues.append({"field": key, "status": "non_numeric", "detail": "non-numeric field"})
            continue
        if not math.isfinite(value) or value < 0:
            issues.append({"field": key, "status": "invalid_numeric", "detail": "invalid field"})
            continue
        if key == "possessionPercentage":
            if value > 100:
                issues.append(
                    {"field": key, "status": "out_of_range", "detail": "possession exceeds 100"}
                )
                continue
        elif key not in {"expectedGoals", "expectedGoalsOnTarget"} and value != int(value):
            issues.append({"field": key, "status": "nonintegral", "detail": "nonintegral count"})
            continue
        values[key] = value
    for part, total in _CONSISTENCY_PAIRS:
        left, right = values.get(part), values.get(total)
        if left is not None and right is not None and left > right:
            issues.append(
                {"field": part, "status": "inconsistent", "detail": f"{part} exceeds {total}"}
            )
    return issues


_CONSISTENCY_PAIRS = (
    ("ontargetScoringAtt", "totalScoringAtt"),
    ("attemptsIbox", "totalScoringAtt"),
    ("expectedGoals", "totalScoringAtt"),
    ("expectedGoalsOnTarget", "ontargetScoringAtt"),
    ("accuratePass", "totalPass"),
    ("fwdPass", "totalPass"),
    ("backwardPass", "totalPass"),
    ("accurateCross", "totalCross"),
    ("wonTackle", "totalTackle"),
)


def _side_issues(stats: Any) -> dict[str, Any]:
    issues = metric_issues(stats)
    optional_absent = sorted(
        key for key in EXTRA_FIELDS if isinstance(stats, dict) and stats.get(key) is None
    )
    return {
        "issues": issues,
        "absent_optional_fields": optional_absent,
        "missing_required_fields": [
            issue["field"] for issue in issues if issue["status"] == "absent_required"
        ],
        "invalid_fields": [
            issue["field"]
            for issue in issues
            if issue["status"] not in {"absent_required", "schema"}
        ],
    }


@dataclass(frozen=True)
class FixtureInput:
    """One horizon fixture reconstructed from the artifact's team-fixture rows."""

    fixture: int
    gw: int
    kickoff: datetime
    home_team_id: int
    away_team_id: int
    home_code: int | None
    away_code: int | None


def fixtures_from_artifact(
    artifact: ProspectivePointsArtifact,
) -> tuple[list[FixtureInput], dict[int, int]]:
    """Rebuild the selector's schedule view and team map from the saved artifact only."""
    sides: dict[int, dict[str, Any]] = {}
    team_map: dict[int, int] = {}
    for row in artifact.team_fixture_rows:
        code = row.team_code or 0
        known = team_map.setdefault(row.team_id, code)
        if known != code:
            raise ValueError(f"artifact team_id {row.team_id} maps to conflicting team codes")
        pair = sides.setdefault(row.fixture, {})
        if row.was_home:
            pair["home"] = row
        else:
            pair["away"] = row
    fixtures: list[FixtureInput] = []
    for fixture, pair in sorted(sides.items()):
        home, away = pair.get("home"), pair.get("away")
        if home is None or away is None:
            raise ValueError(f"artifact fixture {fixture} does not carry both team sides")
        fixtures.append(
            FixtureInput(
                fixture=fixture,
                gw=home.gw,
                kickoff=home.kickoff_time,
                home_team_id=home.team_id,
                away_team_id=away.team_id,
                home_code=home.team_code,
                away_code=away.team_code,
            )
        )
    if not fixtures:
        raise ValueError("artifact carries no team-fixture rows; horizon cannot be reconstructed")
    return fixtures, team_map


def _saved_decisions(
    artifact: ProspectivePointsArtifact, fixtures: list[FixtureInput]
) -> dict[int, dict[str, Any]]:
    """The artifact's recorded selector decisions, authoritative and never rewritten."""
    payload = artifact.manifest.component_modes.get(PROVENANCE_KEY)
    if payload is None:
        raise ValueError(
            "artifact is environment-disabled or lacks "
            f"{PROVENANCE_KEY}; there is no recorded selection to audit"
        )
    provenance = json.loads(payload) if isinstance(payload, str) else payload
    decisions = provenance["decisions"]
    by_fixture: dict[int, dict[str, Any]] = {}
    for decision in decisions:
        fixture = int(decision["fixture"])
        if fixture in by_fixture:
            raise ValueError(f"artifact records multiple decisions for fixture {fixture}")
        by_fixture[fixture] = decision
    for entry in fixtures:
        decision = by_fixture.get(entry.fixture)
        if decision is None:
            raise ValueError(f"artifact records no decision for fixture {entry.fixture}")
        identity = (
            str(decision.get("season")) != str(artifact.manifest.season)
            or int(decision["gw"]) != entry.gw
            or decision.get("home_team_code") != entry.home_code
            or decision.get("away_team_code") != entry.away_code
        )
        if identity:
            raise ValueError(
                f"saved decision identity disagrees with artifact fixture {entry.fixture}"
            )
    return by_fixture


def _safe_rows(state: SdpState, cutoff: datetime) -> list[SdpStateRow]:
    """The selector's defence-in-depth knowledge-time filter, byte for byte."""
    return [
        row
        for row in state.rows
        if row.kickoff < cutoff and datetime.fromisoformat(row.provenance["known_at"]) <= cutoff
    ]


def _required_history(
    state: SdpState,
    valid_keys: set[tuple[str, int, int]],
    *,
    season: str,
    code: int,
    cutoff: datetime,
) -> list[dict[str, Any]]:
    """The selector's required recent matches, with per-key validity and failure."""
    required = sorted(
        (
            (key, time)
            for key, time in state.expected.items()
            if key[0] == season and key[2] == code and time < cutoff
        ),
        key=lambda item: (item[1], item[0]),
        reverse=True,
    )[:REQUIRED_RECENT_MATCHES]
    return [
        {
            "season": key[0],
            "fixture": key[1],
            "team_code": key[2],
            "kickoff": _iso(time),
            "valid": key in valid_keys,
            "failure_reason": None if key in valid_keys else state.failures.get(key[:2]),
        }
        for key, time in required
    ]


def _club_history(
    state: SdpState,
    safe: list[SdpStateRow],
    valid_keys: set[tuple[str, int, int]],
    *,
    season: str,
    code: int | None,
    cutoff: datetime,
    excluded_gw: int,
) -> dict[str, Any]:
    if code is None:
        return {
            "team_code": None,
            "note": "club identity unavailable in the artifact; selector category SDP_IDENTITY",
            "category": None,
            "frozen_prior": {"procedure": FROZEN_PRIOR_PROCEDURE, "requirement_waived": False},
        }
    expected_completed = sorted(
        (
            (key, time)
            for key, time in state.expected.items()
            if key[0] == season and key[2] == code and time < cutoff
        ),
        key=lambda item: (item[1], item[0]),
    )
    required = _required_history(state, valid_keys, season=season, code=code, cutoff=cutoff)
    valid_current = [row for row in safe if row.season == season and row.team_code == code]
    latest = max(valid_current, key=lambda row: (row.kickoff, row.fixture), default=None)
    required_valid = sum(entry["valid"] for entry in required)
    cold_start = not expected_completed and not valid_current
    insufficient = bool(expected_completed) and required_valid < len(required)
    if cold_start:
        club_category: str | None = CATEGORY_COLD_START
    elif insufficient:
        club_category = CATEGORY_INSUFFICIENT_RECENT_HISTORY
    else:
        club_category = None
    return {
        "team_code": code,
        "expected_completed_matches": len(expected_completed),
        "eligible_valid_matches": len(valid_current),
        "required_recent_matches": len(required),
        "required_valid_matches": required_valid,
        "requirement_met": not required or required_valid == len(required),
        "latest_valid_match": None
        if latest is None
        else {
            "fixture": latest.fixture,
            "kickoff": _iso(latest.kickoff),
            "known_at": latest.provenance["known_at"],
        },
        "category": club_category,
        "frozen_prior": {
            "procedure": FROZEN_PRIOR_PROCEDURE,
            "league_prior_computable": any(
                not (row.season == season and row.gw == excluded_gw) for row in safe
            ),
            "state_estimate_computable": bool(valid_current),
            "requirement_waived": False,
            "note": (
                "a missing observed completed match is a fail-closed requirement gap; it is "
                "not a cold start while expected completed rows exist and never licenses a "
                "zero fill"
            ),
        },
    }


def _validated_body(row: dict[str, Any]) -> tuple[bool, Any]:
    body = row["body"].encode("utf-8")
    if (
        row["status_code"] != 200
        or hashlib.sha256(body).hexdigest() != row["sha256"]
        or len(body) != row["byte_count"]
    ):
        return False, None
    try:
        return True, json.loads(body)
    except (ValueError, TypeError):
        return False, None


def _team_names(con: duckdb.DuckDBPyConnection, *, season: str, cutoff: datetime) -> dict[int, str]:
    """Season-qualified latest live club names known at the cutoff; NULL otherwise."""
    if not table_exists(con, "stg_live_team_version"):
        return {}
    rows = con.execute(
        """
        SELECT team_code, team_name FROM stg_live_team_version
        WHERE season = ? AND known_at <= ? AND team_code IS NOT NULL
        QUALIFY row_number() OVER (
            PARTITION BY team_code ORDER BY known_at DESC, capture_id DESC
        ) = 1
        """,
        [season, cutoff],
    ).fetchall()
    return {int(code): str(name) for code, name in rows}


def _crosswalk_sides(
    con: duckdb.DuckDBPyConnection, cutoff: datetime, season: str
) -> dict[tuple[str, int], dict[int, dict[str, Any]]]:
    """Strict cutoff-known crosswalk sides, exactly as the runtime selected them."""
    view = PointInTimeView(FeatureSource(con), AsOf(cutoff))
    sides: dict[tuple[str, int], dict[int, dict[str, Any]]] = {}
    frame = view.observed_team_football(
        providers=["pl_sdp"], seasons=[season], columns=_CROSSWALK_COLUMNS
    )
    for row in frame.to_dicts():
        sides.setdefault((row["season"], row["fixture"]), {})[row["team_code"]] = row
    return sides


def _metadata_index(raw: list[dict[str, Any]], season: str) -> dict[int, list[dict[str, Any]]]:
    """Cutoff-eligible metadata receipts per provider match id, newest first."""
    index: dict[int, list[dict[str, Any]]] = {}
    receipts = [
        row for row in raw if row["season"] == season and row["endpoint"] in {"matches", "match"}
    ]
    for row in sorted(receipts, key=lambda r: (r["fetched_at"], r["payload_id"]), reverse=True):
        body_ok, payload = _validated_body(row)
        if not body_ok or payload is None:
            continue
        records = [payload] if row["endpoint"] == "match" else extract_items(payload)
        for record in records:
            if not isinstance(record, dict):
                continue
            try:
                identifier = uint(record.get("matchId", record.get("id")), "metadata match")
            except ValueError:
                continue
            index.setdefault(identifier, []).append({"receipt": row, "record": record})
    return index


def _version_identity(
    entry: dict[str, Any],
    match_id: int,
    home_code: int,
    away_code: int,
    kickoff: datetime,
    cutoff: datetime,
) -> dict[str, Any]:
    """Identity re-derivation for one metadata record against the crosswalk sides."""
    issues: list[str] = []
    record = entry["record"]
    config = load_sources().pl_sdp
    try:
        if config is None or uint(record.get("competitionId"), "competition") != config.competition:
            issues.append("non-PL competition identity")
        match = parse_match_summary(record)
        if match.match_id != match_id:
            issues.append("metadata match id mismatch")
        if config is not None and match.season_id != config.season_id(
            str(entry["receipt"]["season"])
        ):
            issues.append("provider competition/season mismatch")
        if not is_completed_scored_match(match, now=cutoff):
            issues.append("match is not complete at the cutoff")
        if (
            match.kickoff is None
            or abs((match.kickoff - kickoff).total_seconds()) > KICKOFF_TOLERANCE_SECONDS
            or (match.home_team_id, match.away_team_id) != (home_code, away_code)
        ):
            issues.append("raw/crosswalk/fixture identity mismatch")
    except (ValueError, TypeError, KeyError) as error:
        issues.append(f"{type(error).__name__}: {error}")
    return {"identity_issues": issues, "identity_valid": not issues}


def _stats_for(body: Any, team_code: int, match_id: int) -> Any:
    """One side's stats mapping from a stats payload, or None when unusable."""
    if isinstance(body, dict) and "matchId" in body:
        try:
            if uint(body["matchId"], "stats match") != match_id:
                return None
        except ValueError:
            return None
    try:
        parsed = {side.side: side for side in parse_team_stats(body, match_id=match_id)}
    except (ValueError, TypeError, KeyError):
        return None
    home = parsed.get("home")
    side = (
        parsed.get("home") if home is not None and home.team_id == team_code else parsed.get("away")
    )
    if side is None or side.team_id != team_code:
        return None
    return dict(side.stats)


def _hash_invalid_sides() -> dict[str, Any]:
    return {
        label: {
            "issues": [
                {
                    "field": "*",
                    "status": "schema",
                    "detail": "raw payload unavailable or hash/status mismatch",
                }
            ],
            "absent_optional_fields": [],
            "missing_required_fields": [],
            "invalid_fields": [],
        }
        for label in ("home", "away")
    }


def _later_stats_inventory(
    con: duckdb.DuckDBPyConnection, *, season: str, cutoff: datetime, match_ids: list[int]
) -> dict[int, dict[str, Any]]:
    """Count-only inventory of later-only stats versions; contents are never read."""
    if not match_ids:
        return {}
    placeholders = ",".join("?" for _ in match_ids)
    rows = con.execute(
        f"""
        SELECT sdp_match_id, count(*), epoch_us(min(fetched_at))
        FROM raw_pl_sdp_payload
        WHERE provider = 'pl_sdp' AND endpoint = 'match_stats' AND season = ?
          AND fetched_at > ? AND sdp_match_id IN ({placeholders})
        GROUP BY sdp_match_id
        """,
        [season, cutoff, *match_ids],
    ).fetchall()
    inventory: dict[int, dict[str, Any]] = {}
    for match_id, count, earliest_us in rows:
        inventory[int(match_id)] = {
            "count": int(count),
            "earliest_fetched_at": datetime.fromtimestamp(
                int(earliest_us) / 1_000_000, UTC
            ).isoformat(),
            "usage": _LATER_ONLY_USAGE,
        }
    return inventory


def completed_match_evidence(
    *,
    key: tuple[str, int],
    sides: dict[int, dict[str, Any]] | None,
    raw: list[dict[str, Any]],
    metadata: dict[int, list[dict[str, Any]]],
    runtime_reason: str | None,
    diagnostics: list[str],
    cutoff: datetime,
) -> dict[str, Any]:
    """Root-cause evidence for one completed match key, cutoff-safe throughout."""
    season, fixture = key
    prefix = f"{key}: "
    record: dict[str, Any] = {
        "season": season,
        "fixture": fixture,
        "runtime_reason": runtime_reason,
        "diagnostics": [line for line in diagnostics if line.startswith(prefix)],
        "identity_link": "absent",
        "sdp_match_id": None,
        "sides": {},
        "raw_versions": [],
        "metadata_versions": [],
        "selected": None,
        "latest_eligible_raw_valid": False,
        "classification": LEGITIMATE_FAIL_CLOSED,
        "proposed_action": "",
        "later_only_versions": None,
    }
    if not sides or len(sides) != 2 or any(row.get("was_home") is None for row in sides.values()):
        record["category"] = categorize(runtime_reason, " | ".join(record["diagnostics"]))
        record["proposed_action"] = (
            "no cutoff-known crosswalk identity links this completed match to raw evidence; "
            "do not fuzzy-match -- await capture/staging and keep the incumbent fallback"
        )
        return record
    home_row = next(row for row in sides.values() if row["was_home"])
    away_row = next(row for row in sides.values() if not row["was_home"])
    match_id = home_row["sdp_match_id"]
    record["identity_link"] = "present"
    record["sdp_match_id"] = None if match_id is None else int(match_id)
    home_code, away_code = int(home_row["team_code"]), int(away_row["team_code"])
    kickoff = home_row["kickoff_time"]
    if match_id is None or match_id != away_row["sdp_match_id"]:
        record["diagnostics"].append("crosswalk sides disagree on sdp_match_id")
        record["category"] = CATEGORY_SDP_IDENTITY
        record["proposed_action"] = (
            "crosswalk identity is contradictory; failing closed -- re-stage from raw with "
            "exact identity, never fuzzy matching"
        )
        return record
    stats_versions = sorted(
        (
            row
            for row in raw
            if row["endpoint"] == "match_stats"
            and row["season"] == season
            and row["sdp_match_id"] == match_id
        ),
        key=lambda r: (r["fetched_at"], r["payload_id"]),
    )
    selected_id = home_row["capture_id"]
    metadata_candidates = metadata.get(int(match_id), [])
    newest_metadata: dict[str, Any] = (
        _version_identity(
            metadata_candidates[0], int(match_id), home_code, away_code, kickoff, cutoff
        )
        if metadata_candidates
        else {
            "identity_issues": ["no cutoff-eligible metadata receipt"],
            "identity_valid": False,
        }
    )
    for row in stats_versions:
        body_ok, body = _validated_body(row)
        side_reports: dict[str, Any] = {}
        metrics_valid = False
        if body_ok:
            stats = {
                label: _stats_for(body, code, int(match_id))
                for label, code in (("home", home_code), ("away", away_code))
            }
            side_reports = {label: _side_issues(value) for label, value in stats.items()}
            try:
                for value in stats.values():
                    checked_metrics(value)
                metrics_valid = True
            except SdpHealthError:
                metrics_valid = False
        else:
            side_reports = _hash_invalid_sides()
        valid = body_ok and metrics_valid and newest_metadata["identity_valid"]
        record["raw_versions"].append(
            {
                "payload_id": row["payload_id"],
                "sha256": row["sha256"],
                "fetched_at": _iso(row["fetched_at"]),
                "known_at": _iso(row["fetched_at"]),
                "status_code": row["status_code"],
                "byte_count": row["byte_count"],
                "cutoff_eligible": True,
                "selected_by_runtime": row["payload_id"] == selected_id,
                "body_valid": body_ok,
                "metrics_valid_checked_metrics": metrics_valid,
                "identity_valid_newest_metadata": newest_metadata["identity_valid"],
                "identity_note": (
                    "identity-valid against the newest cutoff-eligible metadata"
                    if newest_metadata["identity_valid"]
                    else "; ".join(newest_metadata["identity_issues"])
                ),
                "sides": side_reports,
                "valid": valid,
            }
        )
    record["metadata_versions"] = [
        {
            "payload_id": entry["receipt"]["payload_id"],
            "fetched_at": _iso(entry["receipt"]["fetched_at"]),
            "sha256": entry["receipt"]["sha256"],
        }
        for entry in metadata_candidates
    ]
    record["sides"] = {
        str(code): {
            "side": "home" if row["was_home"] else "away",
            "team_code": int(code),
            "selected_payload_sha256": row["payload_sha256"],
            "known_at": _iso(row["known_at"]),
        }
        for code, row in sides.items()
    }
    latest_sides = record["raw_versions"][-1]["sides"] if record["raw_versions"] else {}
    for _code, side in record["sides"].items():
        report = latest_sides.get("home" if side["side"] == "home" else "away")
        side["field_issues"] = report["issues"] if report else []
        side["missing_required_fields"] = report["missing_required_fields"] if report else []
        side["invalid_fields"] = report["invalid_fields"] if report else []
    selected = next((v for v in record["raw_versions"] if v["selected_by_runtime"]), None)
    if selected is not None:
        record["selected"] = {
            "payload_id": selected["payload_id"],
            "sha256": selected["sha256"],
            "fetched_at": selected["fetched_at"],
        }
    latest = record["raw_versions"][-1] if record["raw_versions"] else None
    record["latest_eligible_raw_valid"] = bool(latest and latest["valid"])
    record["category"] = categorize(runtime_reason, " | ".join(record["diagnostics"]))
    stats_level = runtime_reason in {
        "SDP_INCOMPLETE_FALLBACK",
        "SDP_SCHEMA_FALLBACK",
        "SDP_MISSING_FALLBACK",
    }
    contradiction = bool(latest and latest["valid"] and latest["selected_by_runtime"])
    fixable = (
        stats_level and latest is not None and latest["valid"] and not latest["selected_by_runtime"]
    )
    if fixable and latest is not None:
        record["classification"] = FIXABLE_NOW
        record["proposed_action"] = (
            "the latest cutoff-eligible raw version is fully valid (hash, identity, "
            "checked_metrics) but unstaged/unselected -- restage from payload "
            f"{latest['payload_id']} (fetched_at {latest['fetched_at']}) and re-run the "
            "forecast; no provider data repair and no zero fill"
        )
    elif contradiction:
        record["proposed_action"] = (
            "re-derivation contradicts the recorded failure; failing closed pending manual "
            "investigation -- never auto-repair a contradiction"
        )
    elif runtime_reason == "SDP_IDENTITY_FALLBACK":
        record["proposed_action"] = (
            "identity and revision selection is newest-valid-by-design; reselecting an older "
            "valid revision is not permitted, so keep the incumbent fallback and await a "
            "corrected provider revision"
        )
    elif not stats_versions:
        record["proposed_action"] = (
            "no stats raw version existed at the cutoff; keep the incumbent fallback and await "
            "a cutoff-eligible provider capture"
        )
    else:
        missing = sorted(
            {
                field
                for version in record["raw_versions"]
                for side in version["sides"].values()
                for field in side["missing_required_fields"] + side["invalid_fields"]
            }
        )
        detail = ", ".join(missing) if missing else "no version validates completely"
        earlier_valid = any(version["valid"] for version in record["raw_versions"][:-1])
        resurrect = (
            " (older valid revisions cannot be resurrected under newest-valid selection)"
            if earlier_valid
            else ""
        )
        record["proposed_action"] = (
            "the latest cutoff-eligible raw version fails validation ("
            + detail
            + ")"
            + resurrect
            + "; keep the incumbent fallback and await a corrected provider revision -- "
            "never zero-fill the missing fields"
        )
    return record


def _model_availability(
    repo: Path, config: FootballEnvironmentConfig, cutoff: datetime
) -> dict[str, Any]:
    try:
        model = FrozenSdpModel.load(repo, config, cutoff)
    except SdpHealthError as error:
        return {
            "available": False,
            "runtime_reason": error.reason,
            "detail": str(error),
            "category": categorize(error.reason, str(error)),
            "sha256": None,
            "known_at": None,
        }
    except (OSError, ValueError, TypeError, KeyError) as error:
        return {
            "available": False,
            "runtime_reason": None,
            "detail": f"{type(error).__name__}: {error}",
            "category": CATEGORY_MISSING_REQUIRED_ARTIFACT,
            "sha256": None,
            "known_at": None,
        }
    return {
        "available": True,
        "runtime_reason": None,
        "detail": None,
        "category": CATEGORY_PRIMARY,
        "sha256": model.sha256,
        "known_at": model.payload.get("known_at"),
    }


def _reason_detail(
    state: SdpState,
    reason: str,
    contributing: list[tuple[str, int, int]],
    model_failure: str | None,
    model_failure_detail: str | None,
) -> str:
    if model_failure is not None and reason == model_failure:
        return model_failure_detail or reason
    lines: list[str] = []
    for key in contributing:
        prefix = f"{key[:2]}: "
        lines.extend(line for line in state.diagnostics if line.startswith(prefix))
    if lines:
        return " | ".join(lines)
    if reason == state.global_failure:
        return " | ".join(state.diagnostics) if state.diagnostics else reason
    return reason


def _selector_reason(
    state: SdpState,
    safe: list[SdpStateRow],
    valid_keys: set[tuple[str, int, int]],
    *,
    fixture_input: FixtureInput,
    season: str,
    cutoff: datetime,
    model_failure: str | None,
    model_failure_detail: str | None,
) -> tuple[str | None, list[tuple[str, int, int]], str | None]:
    """Independent re-derivation of the pre-prediction reason logic.

    The returned reason mirrors the runtime exactly (its first blocker, in its own
    iteration order); ``contributing`` additionally collects EVERY missing required
    latest-five key across both clubs so attribution and fixability see all blockers.
    """
    home, away = fixture_input.home_code, fixture_input.away_code
    reason = model_failure or state.global_failure
    if home is None or away is None or home == away:
        reason = "SDP_IDENTITY_FALLBACK"
    history = [row for row in safe if not (row.season == season and row.gw == fixture_input.gw)]
    contributing: list[tuple[str, int, int]] = []
    if reason is None:
        for code in (home, away):
            if code is None:
                reason = "SDP_IDENTITY_FALLBACK"
                break
            required = sorted(
                (
                    (key, time)
                    for key, time in state.expected.items()
                    if key[0] == season and key[2] == code and time < cutoff
                ),
                key=lambda item: (item[1], item[0]),
                reverse=True,
            )[:REQUIRED_RECENT_MATCHES]
            for key, _ in required:
                if key not in valid_keys:
                    if reason is None:
                        reason = state.failures.get(key[:2], "SDP_MISSING_FALLBACK")
                    contributing.append(key)
    if reason is None and not history:
        reason = "SDP_MISSING_FALLBACK"
    detail = (
        None
        if reason is None
        else _reason_detail(state, reason, contributing, model_failure, model_failure_detail)
    )
    return reason, contributing, detail


def audit_fallbacks(
    con: duckdb.DuckDBPyConnection,
    artifact: ProspectivePointsArtifact,
    *,
    artifact_path: str | None = None,
    artifact_sha256: str | None = None,
    db_path: str | None = None,
    repo: Path | None = None,
    environment_config: FootballEnvironmentConfig | None = None,
) -> dict[str, Any]:
    """Attribute every horizon-fixture fallback recorded in a saved primary artifact.

    Read-only over ``con``: no staging, capture, forecast, or ledger state is touched.
    The saved provenance decisions are authoritative; the cutoff is the artifact
    manifest's own ``as_of``; every selected read is cutoff-safe.
    """
    manifest = artifact.manifest
    cutoff = manifest.as_of
    AsOf(cutoff)
    season = manifest.season
    fixtures, team_map = fixtures_from_artifact(artifact)
    decisions = _saved_decisions(artifact, fixtures)
    state = load_sdp_state(con, cutoff=cutoff, season=season)
    safe = _safe_rows(state, cutoff)
    valid_keys = {(row.season, row.fixture, row.team_code) for row in safe}
    raw = raw_at(con, cutoff)
    metadata = _metadata_index(raw, season)
    crosswalk = _crosswalk_sides(con, cutoff, season)
    names = _team_names(con, season=season, cutoff=cutoff)
    model_report = _model_availability(
        repo or repo_root(), environment_config or load_football_environment(), cutoff
    )
    model_failure = None
    if not model_report["available"]:
        model_failure = model_report["runtime_reason"] or "SDP_SCHEMA_FALLBACK"

    root_causes: dict[tuple[str, int], dict[str, Any]] = {}
    fixture_reports: list[dict[str, Any]] = []
    fallback_counts: Counter[str] = Counter()
    classification_counts: Counter[str] = Counter()
    fallback_fixtures = 0
    primary_saved = 0
    rederived_agrees = 0
    club_categories: dict[int, str] = {}

    for fixture_input in fixtures:
        decision = decisions[fixture_input.fixture]
        saved_reason = str(decision["selector"])
        saved_detail = decision.get("detail")
        reason_r, contributing, detail_r = _selector_reason(
            state,
            safe,
            valid_keys,
            fixture_input=fixture_input,
            season=season,
            cutoff=cutoff,
            model_failure=model_failure,
            model_failure_detail=model_report["detail"],
        )
        club_blocks = [
            _club_history(
                state,
                safe,
                valid_keys,
                season=season,
                code=code,
                cutoff=cutoff,
                excluded_gw=fixture_input.gw,
            )
            for code in (fixture_input.home_code, fixture_input.away_code)
        ]
        for block in club_blocks:
            if block.get("category") is not None and block.get("team_code") is not None:
                club_categories.setdefault(int(block["team_code"]), str(block["category"]))
        primary = saved_reason == CATEGORY_PRIMARY
        driven_by_model = model_failure is not None and reason_r == model_failure
        rederived_category = (
            str(model_report["category"])
            if driven_by_model
            else categorize(reason_r, detail_r or "")
        )
        if primary:
            saved_category = CATEGORY_PRIMARY
        else:
            saved_category = categorize(saved_reason, saved_detail or detail_r or "")
        entry: dict[str, Any] = {
            "fixture": fixture_input.fixture,
            "gw": fixture_input.gw,
            "kickoff": _iso(fixture_input.kickoff),
            "cutoff": _iso(cutoff),
            "home": {
                "team_id": fixture_input.home_team_id,
                "team_code": fixture_input.home_code,
                "name": names.get(fixture_input.home_code) if fixture_input.home_code else None,
            },
            "away": {
                "team_id": fixture_input.away_team_id,
                "team_code": fixture_input.away_code,
                "name": names.get(fixture_input.away_code) if fixture_input.away_code else None,
            },
            "selector": {
                "authoritative": True,
                "runtime_reason": saved_reason,
                "category": saved_category,
                "detail": saved_detail,
            },
            "rederived": {
                "reason": reason_r or CATEGORY_PRIMARY,
                "category": rederived_category,
                "agrees_with_saved": (reason_r or CATEGORY_PRIMARY) == saved_reason,
            },
            "contributing_failures": [],
            "clubs": club_blocks,
            "classification": None,
            "proposed_action": None,
        }
        rederived_agrees += int(entry["rederived"]["agrees_with_saved"])
        for key in contributing:
            cause_key = (key[0], key[1])
            item: dict[str, Any] = {
                "season": key[0],
                "fixture": key[1],
                "team_code": key[2],
                "failure_reason": state.failures.get(cause_key, "SDP_MISSING_FALLBACK"),
                "category": None,
                "classification": None,
            }
            cause = root_causes.get(cause_key)
            if cause is None:
                cause = completed_match_evidence(
                    key=cause_key,
                    sides=crosswalk.get(cause_key),
                    raw=raw,
                    metadata=metadata,
                    runtime_reason=item["failure_reason"],
                    diagnostics=state.diagnostics,
                    cutoff=cutoff,
                )
                root_causes[cause_key] = cause
            item["category"] = cause["category"]
            item["classification"] = cause["classification"]
            entry["contributing_failures"].append(item)
        if primary:
            primary_saved += 1
        else:
            fallback_fixtures += 1
            fallback_counts[saved_category] += 1
            if contributing:
                causes = [
                    root_causes[(item["season"], item["fixture"])]
                    for item in entry["contributing_failures"]
                ]
                saved_source_outage = saved_reason == "SDP_SOURCE_FALLBACK"
                stats_only = (
                    not saved_source_outage
                    and model_failure is None
                    and state.global_failure is None
                    and saved_reason == reason_r
                    and not saved_detail
                )
                if all(cause["classification"] == FIXABLE_NOW for cause in causes) and (stats_only):
                    entry["classification"] = FIXABLE_NOW
                else:
                    entry["classification"] = LEGITIMATE_FAIL_CLOSED
                actions: list[str] = []
                for cause in causes:
                    if cause["proposed_action"] not in actions:
                        actions.append(cause["proposed_action"])
                if saved_source_outage:
                    actions.append(
                        "the recorded saved failure is a source outage; fixing stats "
                        "normalization alone does not resolve it -- rerun the SDP refresh "
                        "and re-forecast"
                    )
                elif not stats_only:
                    actions.append(
                        "a model/global failure, saved prediction error or attribution "
                        "disagreement also needs investigation; stats repair alone is not proven"
                    )
                entry["proposed_action"] = " | ".join(actions)
            else:
                entry["classification"] = LEGITIMATE_FAIL_CLOSED
                if saved_reason == "SDP_SOURCE_FALLBACK":
                    entry["proposed_action"] = (
                        "transient source/capture outage recorded at prediction time; rerun "
                        "the SDP refresh and re-forecast; older valid raw is not reselected"
                    )
                else:
                    entry["proposed_action"] = (
                        "global selector failure (model/source availability) recorded at "
                        "prediction time; resolve the recorded cause and re-forecast"
                    )
        fixture_reports.append(entry)

    match_ids = sorted(
        {int(cause["sdp_match_id"]) for cause in root_causes.values() if cause["sdp_match_id"]}
    )
    later_only = _later_stats_inventory(con, season=season, cutoff=cutoff, match_ids=match_ids)
    for cause in root_causes.values():
        if cause["sdp_match_id"] is not None:
            cause["later_only_versions"] = later_only.get(int(cause["sdp_match_id"]))
    cause_counts: Counter[str] = Counter()
    for cause in root_causes.values():
        cause_counts[cause["category"]] += 1
        classification_counts[cause["classification"]] += 1
    return {
        "schema_version": 1,
        "generated_at": _iso(datetime.now(UTC)),
        "cutoff": _iso(cutoff),
        "season": season,
        "primary_engine": "sdp_v2",
        "fallback_engine": "trailing_goals_attack_defence",
        "inputs": {
            "artifact_path": artifact_path,
            "artifact_sha256": artifact_sha256,
            "db_path": db_path,
            "manifest": {
                "schema_version": manifest.schema_version,
                "as_of": _iso(manifest.as_of),
                "gw_from": manifest.gw_from,
                "gw_to": manifest.gw_to,
                "row_count": manifest.row_count,
                "database_sha256": manifest.database_sha256,
                "commit_sha": manifest.commit_sha,
                "component_modes": dict(manifest.component_modes),
            },
            "team_map": {str(team_id): code for team_id, code in sorted(team_map.items())},
        },
        "frozen_model": model_report,
        "category_map": {
            "SDP_MISSING_FALLBACK": CATEGORY_SDP_MISSING,
            "SDP_INCOMPLETE_FALLBACK": CATEGORY_SDP_INCOMPLETE,
            "SDP_SCHEMA_FALLBACK(numeric)": CATEGORY_SDP_INVALID_NUMERIC,
            "SDP_SCHEMA_FALLBACK(structural)": CATEGORY_SDP_SCHEMA,
            "SDP_IDENTITY_FALLBACK": CATEGORY_SDP_IDENTITY,
            "SDP_IDENTITY_FALLBACK(duplicate)": CATEGORY_SDP_DUPLICATE,
            "SDP_SOURCE_FALLBACK(network outage)": CATEGORY_SDP_SOURCE,
            "model not known at prediction cutoff": CATEGORY_SOURCE_NOT_CUTOFF_ELIGIBLE,
            "missing or hash-broken frozen model artifact": CATEGORY_MISSING_REQUIRED_ARTIFACT,
            "unrecognized": CATEGORY_OTHER,
        },
        "summary": {
            "horizon_fixtures": len(fixtures),
            "fallback_fixtures": fallback_fixtures,
            "primary_saved_fixtures": primary_saved,
            "rederived_agrees_with_saved": rederived_agrees,
            "fallback_categories": dict(sorted(fallback_counts.items())),
            "fixture_classification": {
                FIXABLE_NOW: sum(
                    1 for entry in fixture_reports if entry["classification"] == FIXABLE_NOW
                ),
                LEGITIMATE_FAIL_CLOSED: sum(
                    1
                    for entry in fixture_reports
                    if entry["classification"] == LEGITIMATE_FAIL_CLOSED
                ),
            },
            "completed_match_root_causes": len(root_causes),
            "root_cause_categories": dict(sorted(cause_counts.items())),
            "root_cause_classification": dict(sorted(classification_counts.items())),
            "clubs_by_history_category": {
                str(code): category for code, category in sorted(club_categories.items())
            },
        },
        "fixtures": fixture_reports,
        "completed_match_failures": [
            root_causes[key] for key in sorted(root_causes, key=lambda k: (k[0], k[1]))
        ],
    }
