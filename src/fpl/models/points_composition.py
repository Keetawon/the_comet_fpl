"""Stage D v1: compose independent component distributions into a points distribution.

This is the first end-to-end composer. Stages A (team goals), B (player minutes), and C
(player attacking goals + assists) each produce a *component* distribution for a player-fixture;
nothing before this turned them into a distribution over fantasy points (xP). This module does,
by a seeded Monte-Carlo draw over the components followed by the exact scoring calculator.

Design and its **documented Stage-D-v1 limitations** (see
``docs/phase4-stage-d-points-composition-v1-development.md``):

* **Components are composed independently per player.** The Stage C attacking candidates predict a
  per-player Poisson rate, not a share of a team goal total, so nothing here couples one player's
  goals to another's or conserves a team goal total. Team-coupling / goal-conservation is left as a
  Stage-D-v1 limitation, not invented here.
* **Bonus is deferred.** No bonus / BPS is modelled. The prediction is scored against the realised
  *non-bonus* points (``total_points - bonus``, recomputed from components under the target rules in
  the validation layer), so prediction and label share the same support with respect to bonus.
* **Defensive contribution is zero in this composer.** DC data exists only for 2025-26 and is not
  backtestable across the archive, so composed stats carry ``defensive_contribution=0``.
* **Only the main scoring drivers are drawn.** Appearance, goals, assists, team clean sheet, and
  goals conceded are composed. Saves, penalties, own goals, and cards are held at zero (they are
  their own future components); the realised label still includes them, a small documented gap.
* **Negative composed points are folded to 0.** The only negative source drawn here is the
  GK/DEF goals-conceded penalty; the count-distribution metrics clamp a negative observation to 0,
  so the composed pmf folds negatives to 0 to keep prediction and label on the same non-negative
  support.

The composer is pure: no database, SQL, Polars, or config-file read. It receives already-fitted
component distributions and a prebuilt :class:`PointsLookup`, takes an explicit integer ``seed`` and
draw count, and draws in a fixed order, so the same inputs reproduce the same pmf bit-for-bit.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from random import Random

from fpl.config import ScoringRules
from fpl.models.scoring import calculate_points
from fpl.types import PlayerMatchStats, Position

# A probability distribution over an ordered discrete support, as a tuple of masses. Mirrors
# ``fpl.validate.metrics.Distribution`` without importing it (this module stays model-only).
type Distribution = tuple[float, ...]

# The composer's points support is 0..DEFAULT_MAX_POINTS with the tail folded into the last bin.
# A hat-trick midfielder with two assists and a clean sheet scores 15 + 6 + 2 + 1 = 24 non-bonus
# points; 30 leaves headroom while keeping the pmf short.
DEFAULT_MAX_POINTS = 30

# The number of count bins the Stage C Poisson components use (goals / assists / team conceded are
# distributions over 0..MAX_COUNT). Matches ``fpl.validate.metrics.MAX_GOALS``.
MAX_COUNT = 10


@dataclass(frozen=True, slots=True)
class ComponentDistributions:
    """The four component distributions the composer draws for one player-fixture.

    ``minutes`` is the four-bin Stage B distribution over ``(0, 1-59, 60-89, 90)``. ``goals`` and
    ``assists`` are the player's own Stage C Poisson count distributions. ``team_goals_conceded`` is
    the Poisson distribution over goals the player's team concedes in the fixture -- the OPPONENT's
    Stage A scored-goals distribution -- used both to derive the clean sheet and to score the
    goals-conceded penalty.
    """

    position: Position
    minutes: tuple[float, float, float, float]
    goals: Distribution
    assists: Distribution
    team_goals_conceded: Distribution


def representative_minutes(
    bin_ranges: Sequence[tuple[int, int | None]],
) -> tuple[int, ...]:
    """A representative minutes value per Stage B bin, derived from the contract's bin ranges.

    The exact value only has to land the appearance and clean-sheet step functions correctly -- it
    must be on the right side of the 60-minute threshold for its bin -- so the bin's upper edge (or
    its lower edge for the open-ended top bin) is used. For the frozen four bins this yields
    ``(0, 59, 89, 90)``: bin 0 short-circuits to zero points, bin 1 is a sub-60 appearance, and bins
    2 and 3 are 60+ appearances eligible for a clean sheet.
    """
    values: list[int] = []
    for low, high in bin_ranges:
        values.append(low if high is None else high)
    return tuple(values)


class PointsLookup:
    """A prebuilt table of ``calculate_points`` over the finite drawn-stat space.

    The Monte-Carlo draw ranges over a small finite space -- four positions, three scoring minute
    bins (bin 0 short-circuits), and goals / assists / team-conceded each in ``0..MAX_COUNT`` -- so
    the exact calculator is evaluated once per cell here and the hot draw loop only indexes. The
    clean sheet is derived inside the table exactly as the composer requires it: it needs BOTH zero
    team goals conceded AND at least the rule's clean-sheet minimum minutes.
    """

    def __init__(
        self,
        rules: ScoringRules,
        *,
        bin_minutes: Sequence[int],
        max_count: int = MAX_COUNT,
    ) -> None:
        self._rules = rules
        self._bin_minutes = tuple(bin_minutes)
        self._max_count = max_count
        self._table: dict[tuple[Position, int, int, int, int], int] = {}
        cs_minimum = rules.clean_sheets.minimum_minutes
        for position in Position:
            # Bin 0 (no appearance) is never looked up: the composer scores it as exactly 0.
            for bin_index in range(1, len(self._bin_minutes)):
                minutes = self._bin_minutes[bin_index]
                for goals in range(max_count + 1):
                    for assists in range(max_count + 1):
                        for conceded in range(max_count + 1):
                            clean_sheet = 1 if (conceded == 0 and minutes >= cs_minimum) else 0
                            stats = PlayerMatchStats(
                                minutes=minutes,
                                goals_scored=goals,
                                assists=assists,
                                clean_sheets=clean_sheet,
                                goals_conceded=conceded,
                                saves=0,
                                penalties_saved=0,
                                penalties_missed=0,
                                own_goals=0,
                                yellow_cards=0,
                                red_cards=0,
                                bonus=0,
                                defensive_contribution=0,
                            )
                            self._table[(position, bin_index, goals, assists, conceded)] = (
                                calculate_points(stats, rules, position)
                            )

    def points(
        self, position: Position, bin_index: int, goals: int, assists: int, conceded: int
    ) -> int:
        """Non-bonus points for a drawn cell (clamped counts). Bin 0 must not reach here."""
        goals = min(goals, self._max_count)
        assists = min(assists, self._max_count)
        conceded = min(conceded, self._max_count)
        return self._table[(position, bin_index, goals, assists, conceded)]


def _cumulative(distribution: Sequence[float]) -> list[float]:
    running = 0.0
    out: list[float] = []
    for mass in distribution:
        running += mass
        out.append(running)
    return out


def _sample_index(cumulative: Sequence[float], u: float) -> int:
    """Inverse-CDF sample: the smallest index whose cumulative mass exceeds ``u``.

    ``bisect_right`` places ``u`` at the first bin whose cumulative edge is strictly above it, so a
    bin with zero mass is never selected. The result is clamped to the final bin to absorb any
    floating-point shortfall of the cumulative sum below 1.0.
    """
    index = bisect_right(cumulative, u)
    if index >= len(cumulative):
        index = len(cumulative) - 1
    return index


def compose_points_distribution(
    components: ComponentDistributions,
    lookup: PointsLookup,
    *,
    seed: int,
    draws: int,
    max_points: int = DEFAULT_MAX_POINTS,
) -> Distribution:
    """Monte-Carlo compose one player-fixture's components into a non-bonus points distribution.

    For each of ``draws`` iterations, in a fixed draw order, four uniforms are drawn -- minutes bin,
    goals, assists, team goals conceded -- and mapped through their inverse CDFs. A minutes bin of 0
    is the appearance gate: the draw scores exactly 0 (everything else zeroed), while the three
    remaining uniforms are still consumed so the random stream length is fixed at ``4 * draws`` and
    the pmf is reproducible bit-for-bit for the same inputs. Otherwise the drawn counts index the
    prebuilt :class:`PointsLookup`. Negative points (the GK/DEF concede penalty) fold into bin 0.

    Returns the empirical pmf over ``0..max_points`` (length ``max_points + 1``) as
    ``count / draws`` per bin, with the tail folded into the final bin.
    """
    if draws <= 0:
        raise ValueError(f"draws must be positive, got {draws}")
    generator = Random(seed)
    minutes_cumulative = _cumulative(components.minutes)
    goals_cumulative = _cumulative(components.goals)
    assists_cumulative = _cumulative(components.assists)
    conceded_cumulative = _cumulative(components.team_goals_conceded)

    counts = [0] * (max_points + 1)
    for _ in range(draws):
        # Fixed draw order, always four uniforms per iteration (even on the appearance gate) so the
        # stream is a deterministic function of (seed, draws) alone.
        u_minutes = generator.random()
        u_goals = generator.random()
        u_assists = generator.random()
        u_conceded = generator.random()

        bin_index = _sample_index(minutes_cumulative, u_minutes)
        if bin_index == 0:
            points = 0
        else:
            goals = _sample_index(goals_cumulative, u_goals)
            assists = _sample_index(assists_cumulative, u_assists)
            conceded = _sample_index(conceded_cumulative, u_conceded)
            points = lookup.points(components.position, bin_index, goals, assists, conceded)

        index = points if points > 0 else 0
        if index > max_points:
            index = max_points
        counts[index] += 1

    return tuple(count / draws for count in counts)
