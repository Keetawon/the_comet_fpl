"""Strict production SDP source boundary, over the existing immutable raw/version stores.

Unlike retrospective research readers, every source AND metadata receipt must exist at
the requested cutoff. Health is evaluated on whole payloads, never field-wise revisions.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import duckdb

from fpl.config import load_sources
from fpl.features.pit import AsOf, FeatureSource, PointInTimeView
from fpl.ingest.pl_sdp import (
    extract_items,
    is_completed_scored_match,
    parse_match_summary,
    parse_team_stats,
)
from fpl.storage.db import table_exists
from fpl.transform.competitive_participation import uint
from fpl.transform.pl_sdp import KICKOFF_TOLERANCE_SECONDS
from fpl.validate.tactical_state import StateVector, tactical_values

NORMALIZATION_VERSION = "sdp_production_health_v1"
CORE_FIELDS = (
    "expectedGoals",
    "totalScoringAtt",
    "ontargetScoringAtt",
    "attemptsIbox",
    "touchesInOppBox",
    "possessionPercentage",
    "totalPass",
    "accuratePass",
)
EXTRA_FIELDS = (
    "expectedGoalsOnTarget",
    "finalThirdEntries",
    "penAreaEntries",
    "fwdPass",
    "backwardPass",
    "totalCross",
    "accurateCross",
    "totalTackle",
    "wonTackle",
    "interception",
    "totalClearance",
    "outfielderBlock",
    "ballRecovery",
    "possWonAtt3rd",
    "possWonMid3rd",
    "possWonDef3rd",
    "aerialWon",
    "aerialLost",
    "duelWon",
    "duelLost",
    "yellowCard",
    "redCard",
)


class SdpHealthError(ValueError):
    def __init__(self, reason: str, detail: str) -> None:
        self.reason = reason
        super().__init__(detail)


@dataclass(frozen=True)
class SdpStateRow:
    season: str
    gw: int
    fixture: int
    team_code: int
    opponent_team_code: int
    was_home: bool
    kickoff: datetime
    values: StateVector
    metrics: dict[str, float | None]
    provenance: dict[str, Any]

    @property
    def key(self) -> tuple[str, int, int]:
        return self.season, self.fixture, self.team_code


@dataclass
class SdpState:
    rows: list[SdpStateRow] = field(default_factory=list)
    # All officially completed current-season matches, including missing SDP matches.
    expected: dict[tuple[str, int, int], datetime] = field(default_factory=dict)
    failures: dict[tuple[str, int], str] = field(default_factory=dict)
    global_failure: str | None = None
    diagnostics: list[str] = field(default_factory=list)


def checked_metrics(stats: Any) -> dict[str, float | None]:
    if not isinstance(stats, dict):
        raise SdpHealthError("SDP_SCHEMA_FALLBACK", "stats mapping required")
    result: dict[str, float | None] = {}
    for key in (*CORE_FIELDS, *EXTRA_FIELDS):
        raw = stats.get(key)
        if raw is None:
            result[key] = None
            if key in CORE_FIELDS:
                raise SdpHealthError("SDP_INCOMPLETE_FALLBACK", f"required field absent: {key}")
            continue
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
            raise SdpHealthError("SDP_SCHEMA_FALLBACK", f"non-numeric field: {key}")
        try:
            value = float(raw)
        except ValueError as error:
            raise SdpHealthError("SDP_SCHEMA_FALLBACK", f"non-numeric field: {key}") from error
        if not math.isfinite(value) or value < 0:
            raise SdpHealthError("SDP_SCHEMA_FALLBACK", f"invalid field: {key}")
        if key == "possessionPercentage":
            if value > 100:
                raise SdpHealthError("SDP_SCHEMA_FALLBACK", "possession exceeds 100")
        elif key not in {"expectedGoals", "expectedGoalsOnTarget"} and value != int(value):
            raise SdpHealthError("SDP_SCHEMA_FALLBACK", f"nonintegral count: {key}")
        result[key] = value
    for part, total in (
        ("ontargetScoringAtt", "totalScoringAtt"),
        ("attemptsIbox", "totalScoringAtt"),
        ("expectedGoals", "totalScoringAtt"),
        ("expectedGoalsOnTarget", "ontargetScoringAtt"),
        ("accuratePass", "totalPass"),
        ("fwdPass", "totalPass"),
        ("backwardPass", "totalPass"),
        ("accurateCross", "totalCross"),
        ("wonTackle", "totalTackle"),
    ):
        left, right = result.get(part), result.get(total)
        if left is not None and right is not None and left > right:
            raise SdpHealthError("SDP_SCHEMA_FALLBACK", f"{part} exceeds {total}")
    return result


def _body(row: dict[str, Any]) -> Any:
    body = row["body"].encode("utf-8")
    if (
        row["status_code"] != 200
        or hashlib.sha256(body).hexdigest() != row["sha256"]
        or len(body) != row["byte_count"]
    ):
        raise SdpHealthError(
            "SDP_SCHEMA_FALLBACK", "raw payload unavailable or hash/status mismatch"
        )
    return json.loads(row["body"])


def raw_at(con: duckdb.DuckDBPyConnection, cutoff: datetime) -> list[dict[str, Any]]:
    AsOf(cutoff)
    if not table_exists(con, "raw_pl_sdp_payload"):
        return []
    return (
        con.execute(
            """SELECT payload_id, endpoint, season, sdp_match_id, fetched_at, status_code,
                  CAST(payload AS VARCHAR) AS body, sha256, byte_count, params_json
           FROM raw_pl_sdp_payload WHERE provider='pl_sdp' AND fetched_at <= ?
           ORDER BY fetched_at, payload_id""",
            [cutoff],
        )
        .pl()
        .to_dicts()
    )


def workload_at(con: duckdb.DuckDBPyConnection, cutoff: datetime) -> list[dict[str, Any]]:
    """Production interpretations only; dev_* retrospective tables are never read."""
    AsOf(cutoff)
    if not table_exists(con, "sdp_competitive_match_version"):
        return []
    records = con.execute(
        """SELECT CAST(record_json AS VARCHAR) FROM sdp_competitive_match_version
           WHERE known_at<=? AND kickoff_time<?
           QUALIFY row_number() OVER(PARTITION BY season,competition,provider_match_id
               ORDER BY known_at DESC,version_id DESC)=1
           ORDER BY season,competition,provider_match_id""",
        [cutoff, cutoff],
    ).fetchall()
    raw = {row["payload_id"]: row for row in raw_at(con, cutoff)}
    result = []
    for (body,) in records:
        record = json.loads(body)
        try:
            for source in record["source_versions"].values():
                retained = raw.get(source["payload_id"])
                if retained is None or retained["sha256"] != source["sha256"]:
                    raise ValueError("workload raw source missing or inconsistent")
                if datetime.fromisoformat(source["known_at"]) != retained["fetched_at"]:
                    raise ValueError("workload source knowledge time contradicts raw receipt")
                _body(retained)
        except (ValueError, KeyError, TypeError) as error:
            record["valid"] = False
            record["errors"].append(str(error))
        result.append(record)
    return result


def load_sdp_state(con: duckdb.DuckDBPyConnection, *, cutoff: datetime, season: str) -> SdpState:
    """Revalidate raw bytes/identity behind cutoff-selected football facts.

    Latest known malformed revisions fail for that match; another match cannot borrow
    its fields. Old cutoffs cannot see later captures, even when the database grew.
    """
    AsOf(cutoff)
    state = SdpState()
    view = PointInTimeView(FeatureSource(con), AsOf(cutoff))
    if table_exists(con, "stg_live_fixture_version"):
        official = (
            con.execute(
                """WITH f AS (
                SELECT * FROM stg_live_fixture_version WHERE season=? AND known_at<=?
                QUALIFY row_number() OVER(PARTITION BY fixture
                    ORDER BY known_at DESC,capture_id DESC)=1
            ) SELECT f.fixture, f.kickoff_time, h.team_code AS home, a.team_code AS away
              FROM f
              JOIN stg_live_team_version h ON h.season=f.season AND h.capture_id=f.capture_id
                AND h.team_id=f.team_h AND h.known_at<=?
              JOIN stg_live_team_version a ON a.season=f.season AND a.capture_id=f.capture_id
                AND a.team_id=f.team_a AND a.known_at<=?
              WHERE (f.finished OR f.finished_provisional) AND f.kickoff_time<?""",
                [season, cutoff, cutoff, cutoff, cutoff],
            )
            .pl()
            .to_dicts()
        )
        for fixture in official:
            for side in ("home", "away"):
                if fixture[side] is not None:
                    state.expected[season, fixture["fixture"], fixture[side]] = fixture[
                        "kickoff_time"
                    ]
    try:
        archive = view.observed_team_football(
            providers=["fpl_archive"],
            seasons=[season],
            columns=["season", "fixture", "team_code", "kickoff_time"],
        )
        for fixture in archive.iter_rows(named=True):
            state.expected[fixture["season"], fixture["fixture"], fixture["team_code"]] = fixture[
                "kickoff_time"
            ]
        raw = raw_at(con, cutoff)
        if not raw:
            state.global_failure = "SDP_MISSING_FALLBACK"
            return state
        by_id = {row["payload_id"]: row for row in raw}
        latest_stats = {
            (row["season"], row["sdp_match_id"]): row
            for row in raw
            if row["endpoint"] == "match_stats"
        }
        matches: dict[tuple[str, int], tuple[Any, dict[str, Any]]] = {}
        config = load_sources().pl_sdp
        assert config is not None
        metadata_requests = {
            (row["endpoint"], row["season"], row["sdp_match_id"], row["params_json"]): row
            for row in raw
            if row["endpoint"] in {"matches", "match"}
        }
        for row in sorted(
            metadata_requests.values(),
            key=lambda r: (r["fetched_at"], r["payload_id"]),
            reverse=True,
        ):
            payload = _body(row)
            records = [payload] if row["endpoint"] == "match" else extract_items(payload)
            ids: set[int] = set()
            for record in records:
                identifier = uint(record.get("matchId", record.get("id")), "metadata match")
                if identifier in ids:
                    raise SdpHealthError("SDP_IDENTITY_FALLBACK", "duplicate provider match record")
                ids.add(identifier)
                if (row["season"], identifier) in matches:
                    continue
                match = parse_match_summary(record)
                if match.season_id != config.season_id(row["season"]):
                    raise SdpHealthError(
                        "SDP_IDENTITY_FALLBACK", "provider competition/season mismatch"
                    )
                matches[row["season"], match.match_id] = (record, row)
        fields = [
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
        ]
        football = view.observed_team_football(providers=["pl_sdp"], columns=fields).to_dicts()
        pairs: dict[tuple[str, int], list[dict[str, Any]]] = {}
        for row in football:
            pairs.setdefault((row["season"], row["fixture"]), []).append(row)
        for key, sides in sorted(pairs.items()):
            try:
                if len(sides) != 2 or {s["was_home"] for s in sides} != {True, False}:
                    raise SdpHealthError("SDP_IDENTITY_FALLBACK", "nonreciprocal fixture")
                home, away = sorted(sides, key=lambda side: not side["was_home"])
                capture = by_id.get(home["capture_id"])
                latest = latest_stats.get((home["season"], home["sdp_match_id"]))
                if capture is None or latest is None:
                    raise SdpHealthError("SDP_MISSING_FALLBACK", "missing raw version")
                # A rejected revision must not silently revive an older valid one.
                if latest["payload_id"] != capture["payload_id"]:
                    raise SdpHealthError(
                        "SDP_INCOMPLETE_FALLBACK", "latest raw revision is unstaged/incomplete"
                    )
                source = matches.get((home["season"], home["sdp_match_id"]))
                if source is None:
                    raise SdpHealthError("SDP_IDENTITY_FALLBACK", "no PL metadata known at cutoff")
                record, receipt = source
                # Validate the selected metadata version; older incomplete metadata cannot
                # poison a later valid revision or license a cup observation as EPL evidence.
                if uint(record.get("competitionId"), "competition") != config.competition:
                    raise SdpHealthError("SDP_IDENTITY_FALLBACK", "non-PL competition identity")
                match = parse_match_summary(record)
                if not is_completed_scored_match(match, now=cutoff):
                    raise SdpHealthError("SDP_INCOMPLETE_FALLBACK", "match is not complete")
                if (
                    match.kickoff is None
                    or home["kickoff_time"] != away["kickoff_time"]
                    or abs((match.kickoff - home["kickoff_time"]).total_seconds())
                    > KICKOFF_TOLERANCE_SECONDS
                    or (home["team_code"], away["team_code"])
                    != (match.home_team_id, match.away_team_id)
                    or home["opponent_team_code"] != away["team_code"]
                    or away["opponent_team_code"] != home["team_code"]
                    or home["capture_id"] != away["capture_id"]
                    or home["payload_sha256"] != capture["sha256"]
                ):
                    raise SdpHealthError(
                        "SDP_IDENTITY_FALLBACK", "raw/crosswalk/fixture identity mismatch"
                    )
                stats_body = _body(capture)
                if isinstance(stats_body, dict) and "matchId" in stats_body:
                    if uint(stats_body["matchId"], "stats match") != match.match_id:
                        raise SdpHealthError("SDP_IDENTITY_FALLBACK", "stats match id mismatch")
                parsed = {
                    side.side: side
                    for side in parse_team_stats(stats_body, match_id=match.match_id)
                }
                if (parsed["home"].team_id, parsed["away"].team_id) != (
                    home["team_code"],
                    away["team_code"],
                ):
                    raise SdpHealthError("SDP_IDENTITY_FALLBACK", "stats club identity mismatch")
                metrics = {
                    label: checked_metrics(dict(side.stats)) for label, side in parsed.items()
                }
                pending = []
                for label, row in (("home", home), ("away", away)):
                    opposite = "away" if label == "home" else "home"
                    provenance = {
                        "provider": "pl_sdp",
                        "provider_match_id": match.match_id,
                        "competition": 8,
                        "season": row["season"],
                        "payload_id": capture["payload_id"],
                        "payload_sha256": capture["sha256"],
                        "fetched_at": capture["fetched_at"].isoformat(),
                        "known_at": max(row["known_at"], receipt["fetched_at"]).isoformat(),
                        "match_metadata_payload_id": receipt["payload_id"],
                        "match_metadata_sha256": receipt["sha256"],
                        "fpl_metadata_capture_id": row["metadata_capture_id"],
                        "fpl_metadata_known_at": row["metadata_known_at"].isoformat(),
                        "normalization_version": NORMALIZATION_VERSION,
                        "schema_version": record.get("schemaVersion"),
                    }
                    pending.append(
                        SdpStateRow(
                            row["season"],
                            row["gw"],
                            row["fixture"],
                            row["team_code"],
                            row["opponent_team_code"],
                            row["was_home"],
                            row["kickoff_time"],
                            tactical_values(metrics[label], metrics[opposite]),
                            metrics[label],
                            provenance,
                        )
                    )
                state.rows.extend(pending)
            except SdpHealthError as error:
                state.failures[key] = error.reason
                state.diagnostics.append(f"{key}: {error}")
            except (ValueError, TypeError, KeyError, RuntimeError) as error:
                state.failures[key] = "SDP_SCHEMA_FALLBACK"
                state.diagnostics.append(f"{key}: {type(error).__name__}: {error}")
    except SdpHealthError as error:
        state.global_failure = error.reason
        state.diagnostics.append(str(error))
    except (duckdb.Error, ValueError, TypeError, KeyError, RuntimeError) as error:
        state.global_failure = "SDP_SCHEMA_FALLBACK"
        state.diagnostics.append(f"{type(error).__name__}: {error}")
    return state
