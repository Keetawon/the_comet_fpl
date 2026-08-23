"""Canonical deadline-known selectable-player registry identity.

The full ``bootstrap-static`` payload contains volatile performance, ownership, and event
fields.  Those fields are intentionally excluded here: transfer planning needs a stable binding
to player identity, club/position, and prices, not bit equality with unrelated live statistics.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Final, cast


class PlayerRegistryError(ValueError):
    """The bootstrap payload cannot produce an unambiguous selectable-player registry."""


_POSITIONS: Final[dict[int, str]] = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def _required_positive_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool):
        raise PlayerRegistryError(f"{label} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise PlayerRegistryError(f"{label} must be a positive integer") from exc
    if parsed <= 0:
        raise PlayerRegistryError(f"{label} must be a positive integer")
    return parsed


def selectable_player_registry_records(
    bootstrap: Mapping[str, Any],
    *,
    season: str,
) -> tuple[dict[str, object], ...]:
    """Return the canonical full selectable-player registry from one bootstrap payload.

    Playing elements with no positive ``now_cost`` are not selectable and are excluded, matching
    the prospective artifact/optimizer boundary. Assistant Manager elements are also excluded.
    Every retained row binds the season-scoped element id to stable player ``code`` plus the
    season-scoped club id, permanent club code, position, and current price.
    """
    if not season.strip():
        raise PlayerRegistryError("season is required for the player registry")
    raw_teams = bootstrap.get("teams")
    raw_elements = bootstrap.get("elements")
    if not isinstance(raw_teams, list) or not isinstance(raw_elements, list):
        raise PlayerRegistryError("bootstrap teams and elements must both be lists")

    team_codes: dict[int, int] = {}
    for raw_team in raw_teams:
        if not isinstance(raw_team, Mapping):
            raise PlayerRegistryError("bootstrap team rows must be objects")
        team_id = _required_positive_int(raw_team.get("id"), label="team id")
        team_code = _required_positive_int(raw_team.get("code"), label=f"team {team_id} code")
        if team_id in team_codes:
            raise PlayerRegistryError(f"duplicate team id {team_id} in bootstrap")
        team_codes[team_id] = team_code

    records: list[dict[str, object]] = []
    seen_elements: set[int] = set()
    seen_codes: set[int] = set()
    for raw_element in raw_elements:
        if not isinstance(raw_element, Mapping):
            raise PlayerRegistryError("bootstrap element rows must be objects")
        raw_type = raw_element.get("element_type")
        if isinstance(raw_type, bool):
            continue
        try:
            element_type = int(cast(Any, raw_type))
        except (TypeError, ValueError):
            continue
        position = _POSITIONS.get(element_type)
        if position is None:
            continue
        raw_cost = raw_element.get("now_cost")
        if raw_cost is None:
            continue
        now_cost = _required_positive_int(raw_cost, label="player now_cost")
        element_id = _required_positive_int(raw_element.get("id"), label="player element id")
        code = _required_positive_int(raw_element.get("code"), label="player code")
        team_id = _required_positive_int(raw_element.get("team"), label=f"player {code} team id")
        resolved_team_code = team_codes.get(team_id)
        if resolved_team_code is None:
            raise PlayerRegistryError(f"player {code} references unknown team id {team_id}")
        if element_id in seen_elements:
            raise PlayerRegistryError(f"duplicate player element id {element_id} in bootstrap")
        if code in seen_codes:
            raise PlayerRegistryError(f"duplicate stable player code {code} in bootstrap")
        seen_elements.add(element_id)
        seen_codes.add(code)
        records.append(
            {
                "season": season,
                "element_id": element_id,
                "code": code,
                "position": position,
                "team_id": team_id,
                "team_code": resolved_team_code,
                "now_cost": now_cost,
            }
        )
    if not records:
        raise PlayerRegistryError("bootstrap contains no selectable playing elements")
    return tuple(sorted(records, key=lambda record: cast(int, record["code"])))


def selectable_player_registry_sha256(
    bootstrap: Mapping[str, Any],
    *,
    season: str,
) -> str:
    """SHA-256 of the canonical full selectable-player registry."""
    payload = selectable_player_registry_records(bootstrap, season=season)
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "PlayerRegistryError",
    "selectable_player_registry_records",
    "selectable_player_registry_sha256",
]
