"""The scoring calculator. Components in, points out.

R1: we never model `total_points`. We model the underlying events and apply a season's
scoring function, which is why this module exists and why it takes a `ScoringRules`
argument rather than reading any constant of its own.

R2: no scoring value is hard-coded here. Every number comes from
`config/scoring_<ruleset>.yaml`. Adding 2027/28 is a new config file, not a code change.

Validated by `tests/test_scoring.py`, which replays all 29,747 player-fixture rows of
2025-26 against that season's rules and reproduces the recorded total exactly.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from fpl.config import ScoringRules
from fpl.types import PlayerMatchStats, Position


@dataclass(frozen=True, slots=True)
class PointsBreakdown:
    """Points by source. Sums to the player's match total.

    Kept as a first-class result because the dashboard's player-detail view decomposes
    xP into exactly these buckets, and because a failing replay row is far easier to
    diagnose from a breakdown than from a single integer.
    """

    appearance: int = 0
    goals: int = 0
    assists: int = 0
    clean_sheet: int = 0
    goals_conceded: int = 0
    saves: int = 0
    penalties_saved: int = 0
    penalties_missed: int = 0
    own_goals: int = 0
    cards: int = 0
    defensive_contribution: int = 0
    bonus: int = 0

    @property
    def total(self) -> int:
        return sum(getattr(self, field.name) for field in fields(self))

    def as_dict(self) -> dict[str, int]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


def decompose_points(
    stats: PlayerMatchStats, rules: ScoringRules, position: Position
) -> PointsBreakdown:
    """Points by source, under `rules`, for a player in `position`."""
    minutes = stats.minutes

    # --- Appearance. Steps at exactly `long_play_minutes`; 51-60% of all points scored.
    if minutes <= 0:
        appearance = 0
    elif minutes >= rules.appearance.long_play_minutes:
        appearance = rules.appearance.long_play_points
    else:
        appearance = rules.appearance.short_play_points

    # --- Goals. GK is worth 10 in 2026/27, but see the note in `_UNEXERCISED_RULES`:
    # no goalkeeper scored in the validation data, so that branch is untested either way.
    goals = rules.goals_scored[position] * stats.goals_scored

    assists = rules.assists * stats.assists

    # --- Clean sheet. Requires the 60-minute threshold AND the recorded flag.
    #
    # We read the recorded `clean_sheets` flag rather than deriving it from
    # `goals_conceded`, because FPL's real rule is "the team did not concede while the
    # player was on the pitch", which a player-level conceded count does not determine.
    # Stage D must derive this from simulated team goals conceded during the player's
    # minutes; it must not reuse this branch.
    clean_sheet = 0
    if minutes >= rules.clean_sheets.minimum_minutes and stats.clean_sheets > 0:
        clean_sheet = rules.clean_sheets.points.get(position, 0)

    # --- Goals conceded: -1 per 2, GK and DEF only. Integer division, so 3 conceded
    # costs 1 point, not 1.5. R3 in miniature: this is a step function, and computing it
    # from an expected value is wrong.
    goals_conceded = 0
    if position in rules.goals_conceded.positions:
        units = stats.goals_conceded // rules.goals_conceded.unit
        goals_conceded = rules.goals_conceded.points_per_unit * units

    # --- Saves: +1 per 3, GK only.
    saves = 0
    if position in rules.saves.positions:
        units = stats.saves // rules.saves.unit
        saves = rules.saves.points_per_unit * units

    penalties_saved = rules.penalties_saved * stats.penalties_saved
    penalties_missed = rules.penalties_missed * stats.penalties_missed
    own_goals = rules.own_goals * stats.own_goals

    # --- Cards are NOT gated on minutes played.
    #
    # FPL scores a booking for an unused substitute. Measured: Ashley Barnes, 2025-26
    # GW22, 0 minutes, 1 yellow, bps -3, recorded total_points -1. Gating cards behind
    # `minutes > 0` returns 0 for that row and is the difference between a
    # 29,746/29,747 replay and an exact one. tests/test_scoring.py pins this row
    # specifically so the behaviour cannot be refactored away.
    cards = rules.yellow_cards * stats.yellow_cards + rules.red_cards * stats.red_cards

    # --- Defensive contribution: rules-gated AND stat-gated.
    #
    # Two independent reasons this may score nothing, and they must not be conflated:
    #   - the position has no threshold (GK never earns it, gotcha 7), or
    #   - the statistic was not measured at all (NULL before 2025-26, gotcha 5).
    # A NULL is never read as a zero, so a 2021-22 row scores no DC without pretending
    # the player made zero defensive actions.
    defensive_contribution = 0
    threshold = rules.defensive_contribution.thresholds.get(position)
    if threshold is not None and stats.defensive_contribution is not None:
        if stats.defensive_contribution >= threshold:
            defensive_contribution = rules.defensive_contribution.points

    # --- Bonus is a rank within the match, never a per-player quantity.
    #
    # Phase 0 passes the recorded value through. Deriving it means computing BPS for all
    # 22 players in a match and ranking them, which only simulation can do: a defender
    # on 30 BPS may or may not earn bonus depending on whether someone else got a
    # hat-trick. It must never be regressed on player features.
    if rules.bonus.mode == "passthrough":
        bonus = stats.bonus
    else:
        raise NotImplementedError(
            "bonus.mode='bps_rank' requires match-level BPS ranking; that is Stage D. "
            "Phase 0 passes the recorded bonus through."
        )

    return PointsBreakdown(
        appearance=appearance,
        goals=goals,
        assists=assists,
        clean_sheet=clean_sheet,
        goals_conceded=goals_conceded,
        saves=saves,
        penalties_saved=penalties_saved,
        penalties_missed=penalties_missed,
        own_goals=own_goals,
        cards=cards,
        defensive_contribution=defensive_contribution,
        bonus=bonus,
    )


def calculate_points(stats: PlayerMatchStats, rules: ScoringRules, position: Position) -> int:
    """Total fantasy points for one player in one match under `rules`."""
    return decompose_points(stats, rules, position).total


# Rules that no replay can exercise, recorded here so the gap is visible in code rather
# than only in a config comment. Asserted against config by tests/test_config.py.
_UNEXERCISED_RULES: frozenset[str] = frozenset(
    {
        # No goalkeeper scored in 2025-26 -- measured 0 GK goals across 29,747 rows --
        # so the GK goal value of 10 is untested either way. A bootstrap payload can
        # confirm the number FPL publishes; it cannot confirm this code handles it.
        "goals_scored.GK",
        # Zero-valued, so a correct 0 is indistinguishable from an omitted rule.
        "clean_sheets.points.FWD",
    }
)


def components_required_by(rules: ScoringRules) -> frozenset[str]:
    """Component columns `rules` reads. Drives target-table completeness reporting.

    Recomputing points under a ruleset whose components a season never measured
    produces a systematically biased target -- applying 2026/27 rules to 2021-22
    understates defenders, because defensive_contribution did not exist. Callers use
    this to record what was missing rather than silently shipping the bias.
    """
    required = {
        "minutes",
        "goals_scored",
        "assists",
        "clean_sheets",
        "goals_conceded",
        "saves",
        "penalties_saved",
        "penalties_missed",
        "own_goals",
        "yellow_cards",
        "red_cards",
    }
    if rules.defensive_contribution.thresholds:
        required.add("defensive_contribution")
    if rules.bonus.mode == "passthrough":
        required.add("bonus")
    return frozenset(required)
