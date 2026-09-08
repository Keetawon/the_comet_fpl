"""Development-only observed SDP structure, never a same-match forecast feature.

Formation rows and member indices are source order, not proven tactical side or function.
The unchanged participation V2 parser owns XI/bench and event validation.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime
from typing import Any

from fpl.transform.competitive_participation import (
    ParticipationError,
    _event_time,
    aware,
    exact_crosswalk,
    records,
    uint,
)
from fpl.transform.competitive_participation_v2 import parse_participation_v2

INTERPRETATION_ID = "player_role_source_structure_audit_v1"
BROAD_POSITIONS = frozenset({"Goalkeeper", "Defender", "Midfielder", "Forward"})
FPL_POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def _identities(
    ids: list[int], registry: list[dict[str, Any]], season: str
) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    code_anchors: dict[int, set[str]] = {}
    for anchor in registry:
        opta = anchor.get("opta_code")
        if anchor.get("season") != season or not isinstance(opta, str) or not opta:
            continue
        try:
            anchor_code = uint(anchor.get("code"), "FPL code")
        except ParticipationError:
            continue
        code_anchors.setdefault(anchor_code, set()).add(opta)
    # The bounded audit has tens of players per match; reuse the existing exact join.
    for pid in ids:
        matching = [
            row
            for row in registry
            if row.get("season") == season and row.get("opta_code") == f"p{pid}"
        ]
        try:
            mapping, errors = exact_crosswalk([pid], matching, season=season)
            code = mapping[pid]
        except ParticipationError as error:
            code, errors = None, [str(error)]
        position = matching[0].get("position") if len(matching) == 1 else None
        if position is None and len(matching) == 1:
            position = matching[0].get("element_type")
        if isinstance(position, int) and not isinstance(position, bool):
            position = FPL_POSITIONS.get(position)
        if position not in FPL_POSITIONS.values():
            position = None
        if code is not None and len(code_anchors.get(code, set())) != 1:
            code = None
            errors.append("FPL code has contradictory provider anchors in season registry")
        result[pid] = {
            "fpl_code": code,
            "fpl_position": position if code is not None else None,
            "fpl_web_name": matching[0].get("web_name") if code is not None else None,
            "identity_errors": errors,
        }
    return result


def _formation(
    raw: Any, rows: list[dict[str, Any]]
) -> tuple[list[list[Any]] | None, bool | None, list[str]]:
    if raw is None or raw == {}:
        return None, None, []
    lines: list[list[Any]] = deepcopy(raw["lineup"])
    if any(not line for line in lines):
        raise ParticipationError("empty formation line")
    annotation = raw.get("formation")
    errors = []
    annotation_matches: bool | None = None
    if not isinstance(annotation, str) or not re.fullmatch(r"[1-9](?:-[1-9])+", annotation):
        errors.append("missing or uninterpretable formation annotation")
    else:
        annotation_matches = [len(line) for line in lines] == [
            1,
            *(int(size) for size in annotation.split("-")),
        ]
        if not annotation_matches:
            errors.append("formation annotation and source line sizes disagree")
    players = {row["provider_player_id"]: row["raw_player"] for row in rows}
    first = players[uint(lines[0][0], "formation first player")]
    if len(lines[0]) != 1 or (
        first.get("position") != "Goalkeeper"
        and not (first.get("position") == "Substitute" and first.get("subPosition") == "Goalkeeper")
    ):
        errors.append("initial single goalkeeper row is not corroborated")
    return lines, annotation_matches, errors


def _band(line_index: int, line_count: int) -> str:
    if line_index == 0:
        return "goalkeeper_line"
    if line_index == 1:
        return "defensive_line"
    if line_index == line_count - 1:
        return "forward_line"
    return f"interior_line_{line_index - 1}"


def parse_role_structure(
    match: Mapping[str, Any],
    lineups: Mapping[str, Any],
    events: Mapping[str, Any],
    *,
    season: str,
    fixture: int | None,
    registry: list[dict[str, Any]],
    source_known_at: datetime | None,
    capture_known_at: datetime,
    interpretation_known_at: datetime,
    identity_known_at: datetime,
    provenance: dict[str, Any],
    event_capture_known_at: datetime | None = None,
) -> dict[str, Any]:
    """Preserve validated membership/structure without claiming functional role labels.

    Source publication time is NULL unless witnessed independently of the receipt clock.
    Every row becomes available only after all source, identity and interpretation evidence.
    Missing durations do not erase a separately validated starting formation.
    """
    capture = aware(capture_known_at)
    interpretation = aware(interpretation_known_at)
    identity = aware(identity_known_at)
    publication = aware(source_known_at) if source_known_at is not None else None
    event_capture = aware(event_capture_known_at) if event_capture_known_at is not None else capture
    if event_capture > capture:
        raise ParticipationError("event capture follows bundle capture")
    times = [capture, identity, *([publication] if publication is not None else [])]
    if interpretation < max(times):
        raise ParticipationError("interpretation predates required evidence")
    parsed = parse_participation_v2(
        match,
        lineups,
        events,
        known_at=capture,
        interpretation_known_at=interpretation,
        event_known_at=event_capture,
    )
    for payload in (lineups, events):
        if payload.get("matchId") is not None:
            if uint(payload["matchId"], "payload match") != parsed["sdp_match_id"]:
                raise ParticipationError("payload match identity contradiction")
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}", season) is None:
        raise ParticipationError("canonical season required")
    if parsed["provider_season_id"] != int(season[:4]):
        raise ParticipationError("provider season identity contradiction")
    ids = [row["provider_player_id"] for side in parsed["sides"] for row in side["rows"]]
    identities = _identities(ids, registry, season)
    common = {
        "interpretation_id": INTERPRETATION_ID,
        "development_only": True,
        "season": season,
        "fixture": uint(fixture, "FPL fixture") if fixture is not None else None,
        "provider": "pl_sdp",
        "provider_match_id": parsed["sdp_match_id"],
        "provider_competition_id": parsed["provider_competition_id"],
        "kickoff": parsed["kickoff_utc"],
        "source_known_at": publication.isoformat() if publication is not None else None,
        "capture_known_at": capture.isoformat(),
        "event_capture_known_at": event_capture.isoformat(),
        "interpretation_known_at": interpretation.isoformat(),
        "identity_known_at": identity.isoformat(),
        "available_at": max(*times, interpretation).isoformat(),
        "provenance": deepcopy(provenance),
    }
    sides = []
    for side in parsed["sides"]:
        lines, annotation_matches, band_errors = _formation(side["formation"], side["rows"])
        indices = (
            {
                uint(pid, "formation player"): (line_index, member_index)
                for line_index, line in enumerate(lines)
                for member_index, pid in enumerate(line)
            }
            if lines is not None
            else {}
        )
        rows = []
        for original in side["rows"]:
            pid = original["provider_player_id"]
            line_index, member_index = indices.get(pid, (None, None))
            raw = original["raw_player"]
            band = (
                _band(line_index, len(lines))
                if line_index is not None and lines is not None and not band_errors
                else None
            )
            broad = (
                raw.get("position")
                if raw.get("position") in BROAD_POSITIONS
                else raw.get("subPosition")
                if raw.get("position") == "Substitute" and raw.get("subPosition") in BROAD_POSITIONS
                else None
            )
            rows.append(
                {
                    **deepcopy(common),
                    **deepcopy(original),
                    **identities[pid],
                    "provider_team_id": side["provider_team_id"],
                    "team_code": None,
                    "side": side["side"],
                    "formation": deepcopy(side["formation"]),
                    "formation_line_index": line_index,
                    "formation_member_index": member_index,
                    "formation_band": band,
                    "provider_sub_position": raw.get("subPosition"),
                    "provider_broad_position": broad,
                    "evidence_level": 2
                    if band is not None
                    else 1
                    if broad is not None
                    else 0
                    if identities[pid]["fpl_position"] is not None
                    else None,
                    "oop_diagnostic": "UNKNOWN",
                    "oop_reason": "structural/broad evidence does not establish functional OOP",
                }
            )
        substitutions = []
        detail = events["homeTeam" if side["side"] == "home" else "awayTeam"]
        for event in records(detail.get("subs"), "substitutions"):
            stamp, _ = _event_time(event)
            substitutions.append(
                {
                    "playerOnId": event["playerOnId"],
                    "playerOffId": event["playerOffId"],
                    "time": event["time"],
                    "period": event["period"],
                    "timestamp": event["timestamp"],
                    "timestamp_utc": stamp.isoformat(),
                    "raw": deepcopy(event),
                }
            )
        sides.append(
            {
                "side": side["side"],
                "provider_team_id": side["provider_team_id"],
                "formation": deepcopy(side["formation"]),
                "formation_lineup": lines,
                "formation_line_sizes": [len(line) for line in lines] if lines else None,
                "formation_annotation_matches": annotation_matches,
                "formation_band_errors": band_errors,
                "membership_policy": side["membership_policy"],
                "unassigned_roster_ids": side["unassigned_roster_ids"],
                "participation_errors": deepcopy(side["errors"]),
                "within_line_semantics_validated": False,
                "substitutions": substitutions,
                "rows": rows,
            }
        )
    return {**common, "sides": sides}


def available_before(row: Mapping[str, Any], cutoff: datetime) -> bool:
    """A past-match observation is usable only after every retained knowledge boundary."""
    cutoff = aware(cutoff)
    try:
        times = {
            key: aware(datetime.fromisoformat(str(row[key])))
            for key in (
                "capture_known_at",
                "event_capture_known_at",
                "interpretation_known_at",
                "identity_known_at",
                "available_at",
                "kickoff",
            )
        }
        if row.get("source_known_at") is not None:
            times["source_known_at"] = aware(datetime.fromisoformat(str(row["source_known_at"])))
    except (KeyError, ValueError):
        return False
    known = [value for key, value in times.items() if key not in {"available_at", "kickoff"}]
    return (
        times["kickoff"] < times["capture_known_at"]
        and times["event_capture_known_at"] <= times["capture_known_at"]
        and times["kickoff"] < cutoff
        and times["available_at"] == max(known)
        and times["interpretation_known_at"] == max(known)
        and all(value <= cutoff for value in known)
    )
