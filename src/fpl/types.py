"""Core domain types.

`PlayerMatchStats` is deliberately narrow: it holds exactly the component statistics
the scoring calculator consumes, and nothing else. R1 -- we model events, then apply a
season's scoring function -- only holds if the calculator's input is components.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Self


class Position(StrEnum):
    """Season-scoped playing position.

    Canonical source is `players_raw.element_type` (1..4), not the archive's
    `merged_gw.position` label. The label's vocabulary drifts between seasons --
    2021-22 contains both `GK` and `GKP`, and 2024-25 contains `AM` -- which inflates
    the measured position-change rate from 2.8% to 7.3% (gotcha 10). Within 2025-26
    the two sources agree on all 29,747 rows, so scoring is unaffected by the choice,
    but cross-season identity is not.
    """

    GK = "GK"
    DEF = "DEF"
    MID = "MID"
    FWD = "FWD"

    @classmethod
    def from_element_type(cls, element_type: int) -> Position:
        """Map FPL's `element_type` to a position. The canonical path.

        Raises on the manager element rather than inventing a position for it.
        """
        if element_type == MANAGER_ELEMENT_TYPE:
            raise ValueError(
                f"element_type {element_type} is the Assistant Manager element, not a "
                "playing position; manager rows must be excluded"
            )
        try:
            return _ELEMENT_TYPE_TO_POSITION[element_type]
        except KeyError:
            raise ValueError(f"unknown element_type: {element_type!r}") from None

    @classmethod
    def from_archive_label(cls, label: str) -> Position:
        """Map an archive `position` label, normalising the drifted vocabulary.

        `GKP` (2021-22 only) is an alias for `GK`, not a distinct position.

        `AM` is NOT a position -- it is the Assistant Manager element (element_type 5)
        and raises. Use `from_element_type` where possible; this exists for reading raw
        archive rows and for asserting the two sources agree.
        """
        normalised = label.strip().upper()
        if normalised in MANAGER_POSITION_LABELS:
            raise ValueError(
                f"{label!r} is the Assistant Manager element, not a playing position; "
                "manager rows must be excluded, not coerced"
            )
        normalised = _ARCHIVE_LABEL_ALIASES.get(normalised, normalised)
        try:
            return cls(normalised)
        except ValueError:
            raise ValueError(f"unknown archive position label: {label!r}") from None

    @classmethod
    def is_manager_label(cls, label: str) -> bool:
        return label.strip().upper() in MANAGER_POSITION_LABELS


_ELEMENT_TYPE_TO_POSITION: Final[dict[int, Position]] = {
    1: Position.GK,
    2: Position.DEF,
    3: Position.MID,
    4: Position.FWD,
}

# element_type 5 is the Assistant Manager element, present in 2024-25 only. It was
# removed in 2025-26 (not 2026-27) -- confirmed: element_type 5 appears in the 2024-25
# players_raw and in no other season.
#
# Managers are out of scope. They are excluded from the player facts rather than coerced
# into a playing position: measured 322 manager rows across 20 managers in 2024-25, all
# with 0 minutes, scored entirely through the `mng_*` columns. Giving them a Position
# would feed 322 zero-minute non-players into every rate and minutes model.
MANAGER_ELEMENT_TYPE: Final[int] = 5
MANAGER_POSITION_LABELS: Final[frozenset[str]] = frozenset({"AM"})

_ARCHIVE_LABEL_ALIASES: Final[dict[str, str]] = {
    "GKP": "GK",  # 2021-22 uses GK and GKP interchangeably
}


@dataclass(frozen=True, slots=True)
class PlayerMatchStats:
    """Component statistics for one player in one match.

    `None` means "not measured" and is never coerced to zero (gotcha 5). The
    distinction is load-bearing: `defensive_contribution` is unmeasured before
    2025-26, and a zero there would understate every defender's DC rate.
    """

    minutes: int
    goals_scored: int
    assists: int
    clean_sheets: int
    goals_conceded: int
    saves: int
    penalties_saved: int
    penalties_missed: int
    own_goals: int
    yellow_cards: int
    red_cards: int
    bonus: int
    defensive_contribution: int | None = None

    @staticmethod
    def _as_int(key: str, value: object) -> int:
        """Narrow a database value to int without silently accepting nonsense."""
        if isinstance(value, bool):
            raise TypeError(f"component {key!r} is a bool, not a count: {value!r}")
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str) and value.strip():
            return int(float(value))
        raise TypeError(f"component {key!r} is not numeric: {value!r}")

    @classmethod
    def from_row(cls, row: dict[str, object]) -> Self:
        """Build from a fact-table row, tolerating absent optional columns."""

        def req(key: str) -> int:
            value = row.get(key)
            if value is None:
                raise ValueError(f"required component {key!r} is NULL in row: {row!r}")
            return cls._as_int(key, value)

        def opt(key: str) -> int | None:
            """Preserves NULL. `defensive_contribution` depends on this (gotcha 5)."""
            value = row.get(key)
            return None if value is None else cls._as_int(key, value)

        return cls(
            minutes=req("minutes"),
            goals_scored=req("goals_scored"),
            assists=req("assists"),
            clean_sheets=req("clean_sheets"),
            goals_conceded=req("goals_conceded"),
            saves=req("saves"),
            penalties_saved=req("penalties_saved"),
            penalties_missed=req("penalties_missed"),
            own_goals=req("own_goals"),
            yellow_cards=req("yellow_cards"),
            red_cards=req("red_cards"),
            bonus=req("bonus"),
            defensive_contribution=opt("defensive_contribution"),
        )


# Seasons are identified by their archive directory name, e.g. "2025-26". Ruleset ids
# use an underscore so they are valid SQL identifier fragments -- `points_under_rules_2026_27`.
type Season = str
type RulesetId = str


def ruleset_id_for_season(season: Season) -> RulesetId:
    """ "2026-27" -> "2026_27"."""
    return season.replace("-", "_")
