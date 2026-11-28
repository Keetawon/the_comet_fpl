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
NORMALIZATION_VERSION_CORROBORATED_ZERO_SOT = "sdp_production_health_v2_corroborated_zero_sot"
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
_ZERO_SOT_OWN_CONFLICT_FIELDS = (
    "goals",
    "goalsOpenplay",
    "expectedGoalsOnTarget",
    "attIboxTarget",
    "attOboxTarget",
    "attHdTarget",
    "attLfTarget",
    "attRfTarget",
    "attObpTarget",
    "attIboxGoal",
    "attOboxGoal",
    "attHdGoal",
    "attLfGoal",
    "attRfGoal",
    "attObpGoal",
    "attPenGoal",
    "attPenTarget",
    "attFreekickGoal",
    "attFreekickTarget",
)
_ZERO_SOT_OPPONENT_CONFLICT_FIELDS = (
    "goalsConceded",
    "goalsConcededIbox",
    "goalsConcededObox",
    "penGoalsConceded",
    "expectedGoalsOnTargetConceded",
    "saves",
    "savedIbox",
    "savedObox",
    "divingSave",
    "penaltySave",
)


def _nonneg_int(stats: dict[str, Any], key: str) -> int | None:
    raw = stats.get(key)
    if raw is None or isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        return None
    try:
        value = float(raw)
    except (ValueError, OverflowError):
        return None
    if not math.isfinite(value) or value < 0 or value != int(value):
        return None
    return int(value)


def _is_zero_field(stats: dict[str, Any], key: str) -> bool:
    if key not in stats:
        return True
    raw = stats[key]
    if raw is None or isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        return False
    try:
        value = float(raw)
    except (ValueError, OverflowError):
        return False
    return math.isfinite(value) and value == 0.0


def blocked_target_allowance(stats: dict[str, Any], *, sot: float, total: float | None) -> int:
    """Upper bound on outfield-blocked on-target attempts excluded from Opta SOT.

    Opta's ``ontargetScoringAtt`` counts goals plus goalkeeper saves only; on-target
    attempts blocked by an outfielder are partitioned into ``blockedScoringAtt`` and
    recorded in ``attIboxTarget`` / ``attOboxTarget`` while still contributing to
    ``expectedGoalsOnTarget``. An allowance above zero requires an exact non-negative
    integer shot partition and explicit box-target counts.
    """
    if total is None:
        return 0
    blocked = _nonneg_int(stats, "blockedScoringAtt")
    if blocked is None or blocked == 0:
        return 0
    if "shotOffTarget" in stats:
        off_target = _nonneg_int(stats, "shotOffTarget")
        if off_target is None:
            return 0
    else:
        off_target = 0
    if int(sot) + blocked + off_target != int(total):
        return 0
    zone_target = 0
    saw_zone_target = False
    for key in ("attIboxTarget", "attOboxTarget"):
        if key in stats:
            count = _nonneg_int(stats, key)
            if count is None:
                return 0
            zone_target += count
            saw_zone_target = True
    if not saw_zone_target:
        return 0
    return min(blocked, zone_target)


def corroborated_zero_sot(
    stats: Any,
    *,
    official_goals: int | None,
    opponent_stats: Any,
) -> bool:
    """True only when cutoff-known shot partition, score, and opponent stats prove SOT == 0."""
    if not isinstance(stats, dict) or not isinstance(opponent_stats, dict):
        return False
    if "ontargetScoringAtt" in stats:
        return False
    if official_goals != 0:
        return False
    total = _nonneg_int(stats, "totalScoringAtt")
    if total is None:
        return False
    has_off = "shotOffTarget" in stats
    has_blocked = "blockedScoringAtt" in stats
    if total > 0 and not (has_off or has_blocked):
        return False
    off_target = _nonneg_int(stats, "shotOffTarget") if has_off else 0
    blocked = _nonneg_int(stats, "blockedScoringAtt") if has_blocked else 0
    if off_target is None or blocked is None or off_target + blocked != total:
        return False
    if not all(_is_zero_field(stats, key) for key in _ZERO_SOT_OWN_CONFLICT_FIELDS):
        return False
    return all(_is_zero_field(opponent_stats, key) for key in _ZERO_SOT_OPPONENT_CONFLICT_FIELDS)


_ZERO_IBOX_CONFLICT_FIELDS = (
    "attIboxGoal",
    "attIboxTarget",
    "attIboxMiss",
    "attIboxBlocked",
    "attIboxPost",
    "attPenGoal",
    "attPenTarget",
    "attPenMiss",
    "attPenPost",
)


def corroborated_zero_ibox(stats: Any) -> bool:
    """An omitted inside-box count is zero only when the shot counts prove it."""
    if not isinstance(stats, dict) or "attemptsIbox" in stats:
        return False
    total = _nonneg_int(stats, "totalScoringAtt")
    return (
        total is not None
        and (total == 0 or _nonneg_int(stats, "attemptsObox") == total)
        and all(_is_zero_field(stats, key) for key in _ZERO_IBOX_CONFLICT_FIELDS)
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
        ("expectedGoalsOnTarget", "totalScoringAtt"),
        ("accuratePass", "totalPass"),
        ("fwdPass", "totalPass"),
        ("backwardPass", "totalPass"),
        ("accurateCross", "totalCross"),
        ("wonTackle", "totalTackle"),
    ):
        left, right = result.get(part), result.get(total)
        if left is not None and right is not None and left > right:
            raise SdpHealthError("SDP_SCHEMA_FALLBACK", f"{part} exceeds {total}")
    xgot = result.get("expectedGoalsOnTarget")
    sot = result.get("ontargetScoringAtt")
    if xgot is not None and sot is not None:
        cap = sot + blocked_target_allowance(stats, sot=sot, total=result.get("totalScoringAtt"))
        if xgot > cap:
            raise SdpHealthError(
                "SDP_SCHEMA_FALLBACK", "expectedGoalsOnTarget exceeds ontargetScoringAtt"
            )
    return result


def checked_match_metrics(
    home_stats: Any,
    away_stats: Any,
    *,
    home_score: int | None,
    away_score: int | None,
    corroborate_zero_sot: bool = True,
) -> tuple[dict[str, dict[str, float | None]], bool]:
    """Check match stats; the legacy flag gates both deductive zero-count rules."""
    prepared: dict[str, Any] = {"home": home_stats, "away": away_stats}
    used_corroboration = False
    if corroborate_zero_sot:
        for side, own, opposite, score in (
            ("home", home_stats, away_stats, home_score),
            ("away", away_stats, home_stats, away_score),
        ):
            inferred = {}
            if corroborated_zero_sot(own, official_goals=score, opponent_stats=opposite):
                inferred["ontargetScoringAtt"] = 0.0
            if corroborated_zero_ibox(own):
                inferred["attemptsIbox"] = 0.0
            if inferred:
                prepared[side] = {**own, **inferred}
                used_corroboration = True
    return {label: checked_metrics(value) for label, value in prepared.items()}, used_corroboration


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


def load_sdp_state(
    con: duckdb.DuckDBPyConnection,
    *,
    cutoff: datetime,
    season: str,
    corroborate_zero_sot: bool = True,
) -> SdpState:
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
                metrics, used_corroboration = checked_match_metrics(
                    dict(parsed["home"].stats),
                    dict(parsed["away"].stats),
                    home_score=match.home_score,
                    away_score=match.away_score,
                    corroborate_zero_sot=corroborate_zero_sot,
                )
                normalization_version = (
                    NORMALIZATION_VERSION_CORROBORATED_ZERO_SOT
                    if used_corroboration
                    else NORMALIZATION_VERSION
                )
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
                        "normalization_version": normalization_version,
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
