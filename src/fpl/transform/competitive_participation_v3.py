"""Corroborated StraightRed dismissal alias; original source and V2 remain untouched."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime
from typing import Any

from fpl.transform.competitive_participation import ParticipationError, records
from fpl.transform.competitive_participation_v2 import parse_participation_v2

INTERPRETATION_ID = "competitive_participation_straight_red_v3"


def parse_participation_v3(
    match: Mapping[str, Any],
    lineups: Mapping[str, Any],
    events: Mapping[str, Any],
    *,
    known_at: datetime,
    interpretation_known_at: datetime,
    event_known_at: datetime | None = None,
) -> dict[str, Any]:
    """Apply one enum alias to a private copy, retaining originals and its complete alias log."""
    adapted = deepcopy(dict(events))
    aliases: list[dict[str, Any]] = []
    original_by_alias: dict[tuple[str, str], dict[str, Any]] = {}
    for label, node in (("home", "homeTeam"), ("away", "awayTeam")):
        side = adapted.get(node)
        if not isinstance(side, dict):
            raise ParticipationError("missing reciprocal event side")
        for index, card in enumerate(records(side.get("cards"), "cards")):
            if card.get("type") != "StraightRed":
                continue
            original = deepcopy(card)
            card["type"] = "Red"
            side["cards"][index] = card
            key = (label, json.dumps(card, sort_keys=True))
            if key in original_by_alias:
                raise ParticipationError("duplicate event")
            original_by_alias[key] = original
            aliases.append(
                {
                    "source_field": f"{node}.cards[{index}].type",
                    "provider_value": "StraightRed",
                    "private_state_transition": "Red",
                    "raw_event": original,
                }
            )
    result = parse_participation_v2(
        match,
        lineups,
        adapted,
        known_at=known_at,
        interpretation_known_at=interpretation_known_at,
        event_known_at=event_known_at,
    )
    for side in result["sides"]:
        for discipline in side["discipline"]:
            raw_original = original_by_alias.get(
                (side["side"], json.dumps(discipline["raw"], sort_keys=True))
            )
            if raw_original is not None:
                discipline["raw"] = deepcopy(raw_original)
    result["raw_events"] = deepcopy(dict(events))
    result["interpretation_id"] = INTERPRETATION_ID
    result["source_enum_alias_log"] = aliases
    return result
