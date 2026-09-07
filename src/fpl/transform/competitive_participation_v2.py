"""Additive formation-precedence interpretation; the frozen V1 parser is untouched.

This is not a prospective feature source. Raw records and capture knowledge times survive;
new interpretation evidence has its own availability time. Unknown exposure stays NULL.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime
from typing import Any

from fpl.ingest.pl_sdp import parse_match_summary
from fpl.transform.competitive_participation import (
    DISMISSALS,
    ParticipationError,
    _event_time,
    aware,
    parse_participation,
    records,
    uint,
)

INTERPRETATION_ID = "competitive_participation_formation_precedence_v2"
POSITIONS = frozenset({"Goalkeeper", "Defender", "Midfielder", "Forward", "Substitute"})
RESULT_TYPES = frozenset({"NormalResult", "PenaltyShootout", "Aggregate", "AfterExtraTime"})


def _ids(value: Any, label: str) -> list[int]:
    if not isinstance(value, list):
        raise ParticipationError(f"{label}: array required")
    result = [uint(item, label) for item in value]
    if len(result) != len(set(result)):
        raise ParticipationError(f"{label}: duplicate identity")
    return result


def _membership(lineup: dict[str, Any]) -> tuple[dict[int, str], str]:
    players = records(lineup.get("players"), "players")
    roster = {uint(row.get("id"), "roster id"): row for row in players}
    if len(roster) != len(players):
        raise ParticipationError("duplicate raw roster identity")
    if any(row.get("position") not in POSITIONS for row in players):
        raise ParticipationError("unknown raw provider position")
    formation = lineup.get("formation")
    if formation is None or formation == {}:
        return {
            pid: "bench" if row["position"] == "Substitute" else "starting_xi"
            for pid, row in roster.items()
        }, "validated_v1_position_fallback_formation_absent"
    if not isinstance(formation, dict):
        raise ParticipationError("malformed present formation")
    if uint(formation.get("teamId"), "formation team") != uint(lineup.get("teamId"), "team"):
        raise ParticipationError("formation team identity contradiction")
    lines = formation.get("lineup")
    if (
        not isinstance(lines, list)
        or not lines
        or any(not isinstance(line, list) for line in lines)
    ):
        raise ParticipationError("malformed present formation lineup")
    xi = _ids([pid for line in lines for pid in line], "formation XI")
    bench = _ids(formation.get("subs"), "formation bench")
    if len(xi) != 11:
        raise ParticipationError("formation requires exactly 11 unique starters")
    if set(xi) & set(bench):
        raise ParticipationError("formation XI and bench overlap")
    if not set(xi + bench) <= roster.keys():
        raise ParticipationError("formation references unknown roster identity")
    return {
        pid: "starting_xi" if pid in xi else "bench" if pid in bench else "unassigned_roster"
        for pid in roster
    }, "explicit_formation_membership_v2"


def parse_participation_v2(
    match: Mapping[str, Any],
    lineups: Mapping[str, Any],
    events: Mapping[str, Any],
    *,
    known_at: datetime,
    interpretation_known_at: datetime,
    event_known_at: datetime | None = None,
) -> dict[str, Any]:
    """Use validated formation membership without rewriting any source payload.

    The private V1 adapter encodes selected membership in temporary position fields;
    every published player position/raw record is restored from the unchanged source.
    Unassigned roster entries are retained separately with unknown participation/minutes.
    """
    source_known_at = aware(known_at)
    interpretation_known_at = aware(interpretation_known_at)
    event_capture = aware(event_known_at) if event_known_at is not None else source_known_at
    if match.get("resultType") not in RESULT_TYPES:
        raise ParticipationError("unknown completed result type")
    summary = parse_match_summary(dict(match))
    if summary.kickoff is None:
        raise ParticipationError("unknown kickoff")
    adapted_lineups = deepcopy(dict(lineups))
    adapted_events = deepcopy(dict(events))
    memberships: dict[str, dict[int, str]] = {}
    policies: dict[str, str] = {}
    originals: dict[str, dict[int, dict[str, Any]]] = {}
    removed_cards: dict[str, list[dict[str, Any]]] = {}
    all_roster_ids: set[int] = set()
    all_unassigned: set[int] = set()
    for label in ("home", "away"):
        lineup = adapted_lineups.get(f"{label}_team")
        if not isinstance(lineup, dict):
            raise ParticipationError("missing reciprocal lineup")
        membership, policy = _membership(lineup)
        if all_roster_ids & membership.keys():
            raise ParticipationError("raw player appears on both fixture sides")
        all_roster_ids.update(membership)
        all_unassigned.update(
            pid for pid, status in membership.items() if status == "unassigned_roster"
        )
        memberships[label], policies[label] = membership, policy
        originals[label] = {
            uint(row["id"], "player id"): deepcopy(row)
            for row in records(lineup["players"], "players")
        }
        selected = []
        for pid, original in originals[label].items():
            status = membership[pid]
            if status == "unassigned_roster":
                continue
            player = deepcopy(original)
            if status == "bench":
                player["position"] = "Substitute"
            elif player["position"] == "Substitute":
                if player.get("subPosition") not in POSITIONS - {"Substitute"}:
                    raise ParticipationError("formation starter lacks a known broad position")
                player["position"] = player["subPosition"]
            selected.append(player)
        lineup["players"] = selected

    for label, node in (("home", "homeTeam"), ("away", "awayTeam")):
        detail = adapted_events.get(node)
        if not isinstance(detail, dict):
            raise ParticipationError("missing reciprocal event side")
        removed_cards[label] = []
        remaining_cards = []
        for card in records(detail.get("cards"), "cards"):
            actor = (
                uint(card["playerId"], "card actor") if card.get("playerId") is not None else None
            )
            if actor is not None and actor in all_unassigned:
                if actor not in memberships[label]:
                    raise ParticipationError("card attributed to opposite side unassigned player")
                stamp, _ = _event_time(card)
                if stamp > event_capture or card.get("type") not in {"Yellow", *DISMISSALS}:
                    raise ParticipationError("invalid unassigned-player card")
                if any(previous["raw"] == card for previous in removed_cards[label]):
                    raise ParticipationError("duplicate unassigned-player card")
                removed_cards[label].append(
                    {
                        "provider_player_id": actor,
                        "context": "unassigned_roster",
                        "raw": deepcopy(card),
                        "timestamp_utc": stamp.isoformat(),
                    }
                )
            else:
                remaining_cards.append(card)
        detail["cards"] = remaining_cards
        for substitution in records(detail.get("subs"), "subs"):
            for key in ("playerOnId", "playerOffId"):
                if uint(substitution.get(key), key) in all_unassigned:
                    raise ParticipationError("unassigned roster player has participation event")
        for goal in records(detail.get("goals"), "goals"):
            stamp, _ = _event_time(goal)
            if not summary.kickoff <= stamp <= event_capture:
                raise ParticipationError("goal event outside kickoff/capture bounds")
            # Own-goal attribution may name the opposite side, never a fabricated identity.
            for key in ("playerId", "assistPlayerId"):
                if goal.get(key) is None:
                    continue
                actor = uint(goal[key], key)
                if actor not in all_roster_ids or actor in all_unassigned:
                    raise ParticipationError(
                        "goal actor unknown or outside selected formation roster"
                    )

    adapted_match = deepcopy(dict(match))
    if match["resultType"] in {"Aggregate", "AfterExtraTime"}:
        # Outcome-of-tie annotation is not a duration instruction. V1's clock + explicit
        # extra-period witnesses continue to decide nominal duration, not this adapter.
        adapted_match["resultType"] = "NormalResult"
    result = parse_participation(
        adapted_match,
        adapted_lineups,
        adapted_events,
        known_at=source_known_at,
        event_known_at=event_capture,
    )
    for side in result["sides"]:
        label = side["side"]
        if match["resultType"] == "AfterExtraTime" and side["nominal_match_minutes"] != 120:
            side["errors"].append("AfterExtraTime lacks corroborated 120-minute period evidence")
            side["nominal_match_minutes"] = None
            for row in side["rows"]:
                row["nominal_minutes"] = None
                row["nominal_intervals"] = []
        for row in side["rows"]:
            pid = row["provider_player_id"]
            row["raw_player"] = deepcopy(originals[label][pid])
            row["provider_position"] = originals[label][pid]["position"]
            row["membership"] = memberships[label][pid]
        for pid, member_state in memberships[label].items():
            if member_state != "unassigned_roster":
                continue
            side["rows"].append(
                {
                    "provider_player_id": pid,
                    "started": None,
                    "on_bench": None,
                    "appeared": None,
                    "nominal_minutes": None,
                    "nominal_intervals": [],
                    "provider_position": originals[label][pid]["position"],
                    "raw_player": deepcopy(originals[label][pid]),
                    "membership": member_state,
                    "unavailability_reason": (
                        "roster entry absent from authoritative formation; no inferred exposure"
                    ),
                }
            )
        side["rows"].sort(key=lambda row: row["provider_player_id"])
        side["discipline"].extend(removed_cards[label])
        side["membership_policy"] = policies[label]
        side["unassigned_roster_ids"] = sorted(
            pid
            for pid, membership in memberships[label].items()
            if membership == "unassigned_roster"
        )
    result.update(
        {
            "interpretation_id": INTERPRETATION_ID,
            "interpretation_known_at": interpretation_known_at.isoformat(),
            "available_at": max(source_known_at, interpretation_known_at).isoformat(),
            "raw_result_type": match["resultType"],
            "raw_match": deepcopy(dict(match)),
            "raw_lineups": deepcopy(dict(lineups)),
            "raw_events": deepcopy(dict(events)),
        }
    )
    return result
