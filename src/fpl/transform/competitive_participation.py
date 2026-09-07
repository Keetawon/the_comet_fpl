"""Pure, fail-closed participation interpretation; not a model/PIT source.

Nominal period-clock intervals are deliberately NOT FPL minutes or physical elapsed time.
Raw provider events and original capture timestamps must accompany every interpretation.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from itertools import groupby
from typing import Any

from fpl.ingest.pl_sdp import parse_match_summary

PERIODS = {
    "FirstHalf": (0, 45),
    "SecondHalf": (45, 90),
    "ExtraFirstHalf": (90, 105),
    "ExtraSecondHalf": (105, 120),
}
DISMISSALS = frozenset({"Red", "SecondYellow"})


class ParticipationError(ValueError):
    """Required source evidence cannot support a deterministic interpretation."""


def uint(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ParticipationError(f"{label}: expected unsigned decimal integer")
    text = str(value)
    if not text.isascii() or not text.isdecimal():
        raise ParticipationError(f"{label}: expected unsigned decimal integer")
    return int(text)


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ParticipationError("timezone-aware timestamp required")
    return value.astimezone(UTC)


def records(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ParticipationError(f"{label}: complete object array required")
    return [dict(row) for row in value]


def exact_crosswalk(
    provider_ids: Sequence[int], registry: Sequence[Mapping[str, Any]], *, season: str
) -> tuple[dict[int, int | None], list[str]]:
    """An already season-filtered FPL roster; no name or bare-code fallback."""
    index: dict[str, list[int]] = defaultdict(list)
    for row in registry:
        if row.get("season") != season:
            continue
        opta = row.get("opta_code")
        if isinstance(opta, str) and opta:
            index[opta].append(uint(row.get("code"), "FPL code"))
    result: dict[int, int | None] = {}
    errors: list[str] = []
    for player_id in provider_ids:
        matches = index.get(f"p{player_id}", [])
        result[player_id] = matches[0] if len(matches) == 1 else None
        if len(matches) != 1:
            errors.append(f"player {player_id}: {len(matches)} exact FPL Opta anchors")
    mapped = [code for code in result.values() if code is not None]
    if len(mapped) != len(set(mapped)):
        raise ParticipationError("multiple provider identities resolve to one FPL code")
    return result, errors


def _event_time(event: Mapping[str, Any]) -> tuple[datetime, int]:
    try:
        stamp = datetime.fromisoformat(str(event["timestamp"]))
    except (KeyError, ValueError) as error:
        raise ParticipationError("unknown event timestamp") from error
    stamp = aware(stamp)
    period = event.get("period")
    if period not in PERIODS:
        raise ParticipationError(f"unknown event period: {period!r}")
    start, end = PERIODS[period]
    minute = uint(event.get("time"), "event time")
    if minute < start:
        raise ParticipationError("event minute precedes its period")
    return stamp, min(minute, end)


def _nominal_end(
    match: Mapping[str, Any], events: Mapping[str, Any], *, kickoff: datetime, known_at: datetime
) -> int | None:
    try:
        clock = uint(match.get("clock"), "completed match clock")
    except ParticipationError:
        return None
    extra = False
    for side in ("homeTeam", "awayTeam"):
        if not isinstance(events.get(side), dict):
            raise ParticipationError("missing reciprocal events side")
        for kind in ("subs", "cards", "goals"):
            for row in records(events[side].get(kind), f"{side}.{kind}"):
                if row.get("period") in {"ExtraFirstHalf", "ExtraSecondHalf"}:
                    stamp, _ = _event_time(row)
                    if not kickoff <= stamp <= known_at:
                        raise ParticipationError(
                            "extra-time evidence outside kickoff/capture bounds"
                        )
                    extra = True
    if clock >= 120 and extra:
        return 120
    if 90 <= clock < 120 and not extra:
        return 90
    return None


def _side(
    lineup: Mapping[str, Any],
    event_side: Mapping[str, Any],
    *,
    kickoff: datetime,
    known_at: datetime,
    nominal_end: int | None,
) -> dict[str, Any]:
    players = records(lineup.get("players"), "players")
    roster: dict[int, dict[str, Any]] = {}
    for player in players:
        pid = uint(player.get("id"), "lineup player id")
        if pid in roster:
            raise ParticipationError(f"duplicate lineup player {pid}")
        if player.get("position") not in {
            "Goalkeeper",
            "Defender",
            "Midfielder",
            "Forward",
            "Substitute",
        }:
            raise ParticipationError(f"unknown lineup position for {pid}")
        roster[pid] = player
    starters = {pid for pid, row in roster.items() if row["position"] != "Substitute"}
    if len(starters) != 11:
        raise ParticipationError(f"expected 11 starters, observed {len(starters)}")
    active = dict.fromkeys(starters, 0)
    appeared = set(starters)
    exited: set[int] = set()
    dismissed: set[int] = set()
    intervals: dict[int, list[list[int]]] = {pid: [] for pid in roster}
    discipline: list[dict[str, Any]] = []
    timed: list[tuple[datetime, int, str, dict[str, Any]]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for kind in ("subs", "cards"):
        for event in records(event_side.get(kind), kind):
            digest = json.dumps([kind, event], sort_keys=True)
            if digest in seen:
                raise ParticipationError("duplicate event")
            seen.add(digest)
            stamp, minute = _event_time(event)
            if stamp > known_at:
                raise ParticipationError("event timestamp follows actual capture")
            if kind == "cards" and event.get("type") not in {"Yellow", *DISMISSALS}:
                raise ParticipationError(f"unknown card type: {event.get('type')!r}")
            raw_actor = event.get("playerId")
            if stamp < kickoff:
                if kind != "cards" or raw_actor is None or uint(raw_actor, "card id") in starters:
                    raise ParticipationError("required field event precedes kickoff")
                if uint(raw_actor, "card id") not in roster:
                    raise ParticipationError("pre-kickoff card actor outside roster")
            timed.append((stamp, minute, kind, event))
    for _, batch in groupby(sorted(timed, key=lambda row: row[0]), key=lambda row: row[0]):
        current = list(batch)
        changing: set[int] = set()
        for _, _, kind, event in current:
            actors = (
                [uint(event.get("playerOnId"), "on id"), uint(event.get("playerOffId"), "off id")]
                if kind == "subs"
                else [uint(event["playerId"], "dismissal id")]
                if event.get("type") in DISMISSALS and event.get("playerId") is not None
                else []
            )
            if len(set(actors)) != len(actors) or changing.intersection(actors):
                raise ParticipationError("ambiguous simultaneous actor changes")
            changing.update(actors)
        for stamp, minute, kind, event in current:
            if kind == "subs":
                on = uint(event.get("playerOnId"), "on id")
                off = uint(event.get("playerOffId"), "off id")
                if off not in active or on not in roster or on in active or on in exited:
                    raise ParticipationError("impossible substitution state or unknown actor")
                start = active.pop(off)
                if minute < start:
                    raise ParticipationError("event timestamp and nominal interval order disagree")
                intervals[off].append([start, minute])
                exited.add(off)
                active[on] = minute
                appeared.add(on)
            else:
                raw_id = event.get("playerId")
                card_id = uint(raw_id, "card id") if raw_id is not None else None
                context = (
                    "active"
                    if card_id in active
                    else "already_off"
                    if card_id in exited
                    else "bench"
                    if card_id in roster
                    else "unattributed"
                )
                discipline.append(
                    {
                        "provider_player_id": card_id,
                        "context": context,
                        "raw": event,
                        "timestamp_utc": stamp.isoformat(),
                    }
                )
                if event["type"] in DISMISSALS:
                    if context == "unattributed":
                        errors.append("unknown dismissal actor; side duration unavailable")
                    elif card_id is not None:
                        if card_id in dismissed:
                            raise ParticipationError("duplicate/conflicting dismissal")
                        dismissed.add(card_id)
                        if context == "already_off":
                            # A red card after substitution is discipline, not another field exit.
                            continue
                        if context == "active":
                            start = active.pop(card_id)
                            if minute < start:
                                raise ParticipationError("dismissal precedes entry")
                            intervals[card_id].append([start, minute])
                        exited.add(card_id)
    if nominal_end is None:
        errors.append("insufficient or contradictory final-period clock evidence")
    if nominal_end is not None:
        for pid, start in active.items():
            if start > nominal_end:
                raise ParticipationError("entry beyond nominal completed period")
            intervals[pid].append([start, nominal_end])
    rows = [
        {
            "provider_player_id": pid,
            "started": pid in starters,
            "on_bench": pid not in starters,
            "appeared": pid in appeared,
            "nominal_minutes": None
            if errors
            else sum(end - start for start, end in intervals[pid]),
            "nominal_intervals": intervals[pid],
            "provider_position": player["position"],
            "raw_player": player,
        }
        for pid, player in sorted(roster.items())
    ]
    return {
        "rows": rows,
        "discipline": discipline,
        "errors": errors,
        "formation": lineup.get("formation"),
        "nominal_match_minutes": nominal_end,
    }


def parse_participation(
    match: Mapping[str, Any],
    lineups: Mapping[str, Any],
    events: Mapping[str, Any],
    *,
    known_at: datetime,
    event_known_at: datetime | None = None,
) -> dict[str, Any]:
    """Return two reciprocal provider sides, or reject required inconsistent evidence.

    `known_at` is the maximum actual capture time of the complete source bundle. This parser
    does not pretend the provider event timestamp is a verified physical wall-clock measurement.
    """
    known_at = aware(known_at)
    event_known_at = aware(event_known_at) if event_known_at is not None else known_at
    if event_known_at > known_at:
        raise ParticipationError("event capture follows bundle known_at")
    summary = parse_match_summary(dict(match))
    if (
        match.get("period") != "FullTime"
        or match.get("resultType") not in {"NormalResult", "PenaltyShootout"}
        or summary.kickoff is None
        or summary.kickoff >= known_at
        or summary.home_score is None
        or summary.away_score is None
        or summary.home_score < 0
        or summary.away_score < 0
    ):
        raise ParticipationError("unknown, incomplete or contradictory completed match")
    sides = []
    all_players: set[int] = set()
    for label, node, team in (
        ("home", "homeTeam", summary.home_team_id),
        ("away", "awayTeam", summary.away_team_id),
    ):
        lineup = lineups.get(f"{label}_team")
        detail = events.get(node)
        if not isinstance(lineup, dict) or not isinstance(detail, dict) or team is None:
            raise ParticipationError("missing reciprocal lineup/events/team identity")
        if (
            uint(lineup.get("teamId"), "lineup team") != team
            or uint(detail.get("id"), "events team") != team
        ):
            raise ParticipationError("fixture/lineup/events team contradiction")
        result = _side(
            lineup,
            detail,
            kickoff=summary.kickoff,
            known_at=event_known_at,
            nominal_end=_nominal_end(
                match, events, kickoff=summary.kickoff, known_at=event_known_at
            ),
        )
        ids = {row["provider_player_id"] for row in result["rows"]}
        if all_players.intersection(ids):
            raise ParticipationError("player appears on both fixture sides")
        all_players.update(ids)
        sides.append({"side": label, "provider_team_id": team, **result})
    if summary.home_team_id == summary.away_team_id:
        raise ParticipationError("fixture has the same club on both sides")
    return {
        "sdp_match_id": summary.match_id,
        "provider_season_id": summary.season_id,
        "provider_competition_id": uint(match.get("competitionId"), "competition"),
        "kickoff_utc": summary.kickoff.isoformat(),
        "known_at": known_at.isoformat(),
        "evidence_class": "retrospective_backfill_development",
        "duration_definition": "nominal_period_clock_intervals_v1_not_fpl_minutes",
        "exact_match_end_timestamp": None,
        "exact_rest_hours": None,
        "sides": sides,
    }
