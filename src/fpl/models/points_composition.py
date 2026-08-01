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
* **Only the main scoring drivers are drawn.** Appearance, goals, assists, team clean sheet, and
  goals conceded are always composed. Stage D **v2** additionally draws two independent components
  when they are supplied: goalkeeper **saves** and a **defensive-contribution** threshold hit (see
  :class:`ComponentDistributions` and :class:`ExtraScoring`). Penalties, own goals, and cards remain
  held at zero (their own future components); the realised label still includes them, a documented
  gap. FPL scoring is additive across independent components, so v2 adds saves and DC as two extra
  draws on top of the unchanged five-dimensional base rather than enlarging the lookup table.
* **v1 is reproduced bit-for-bit when saves and DC are absent.** When ``components.saves is None``
  and ``components.dc_hit_probability == 0.0`` the composer draws the same four uniforms in the same
  order and returns the identical pmf; the two extra uniforms are drawn only when a component is on.
* **Negative composed points are folded to 0, on the TOTAL.** The negative source is the GK/DEF
  goals-conceded penalty. v2 folds negatives only AFTER adding saves and DC, so a goalkeeper's
  ``-1`` concede penalty nets against its save points rather than being folded prematurely. The
  count-distribution metrics clamp a negative observation to 0, matching this non-negative support.

The composer is pure: no database, SQL, Polars, or config-file read. It receives already-fitted
component distributions, a prebuilt :class:`PointsLookup`, and (for v2) an :class:`ExtraScoring`
carrying the saves / DC scoring constants resolved from the rules; it takes an explicit integer
``seed`` and draw count and draws in a fixed order, so the same inputs reproduce the same pmf
bit-for-bit.
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
class ExtraScoring:
    """The saves / defensive-contribution scoring constants the v2 composer needs.

    Resolved from the loaded :class:`~fpl.config.ScoringRules` by the caller (the composer stays
    config-free). ``saves_positions`` and ``dc_positions`` are the position sets each award applies
    to -- for 2026/27, saves are goalkeeper-only and DC is DEF/MID/FWD (goalkeepers are absent from
    the rules' DC threshold map, gotcha 7). ``saves_unit`` is the saves-per-point divisor and
    ``dc_points`` the flat DC award.
    """

    saves_unit: int
    dc_points: int
    saves_positions: frozenset[Position]
    dc_positions: frozenset[Position]


@dataclass(frozen=True, slots=True)
class ComponentDistributions:
    """The component distributions the composer draws for one player-fixture.

    ``minutes`` is the four-bin Stage B distribution over ``(0, 1-59, 60-89, 90)``. ``goals`` and
    ``assists`` are the player's own Stage C Poisson count distributions. ``team_goals_conceded`` is
    the Poisson distribution over goals the player's team concedes in the fixture -- the OPPONENT's
    Stage A scored-goals distribution -- used both to derive the clean sheet and to score the
    goals-conceded penalty.

    ``saves`` and ``dc_hit_probability`` are the Stage D **v2** additions. ``saves`` is the
    goalkeeper's saves count distribution (a point mass on zero for non-goalkeepers, or ``None`` to
    disable the whole saves draw); ``dc_hit_probability`` is ``P(defensive_contribution >=
    threshold)`` for the player-fixture (``0.0`` disables the DC draw). Both default so that a
    v1-style construction (neither supplied) reproduces v1 bit-for-bit.
    """

    position: Position
    minutes: tuple[float, float, float, float]
    goals: Distribution
    assists: Distribution
    team_goals_conceded: Distribution
    saves: Distribution | None = None
    dc_hit_probability: float = 0.0


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
    extra: ExtraScoring | None = None,
) -> Distribution:
    """Monte-Carlo compose one player-fixture's components into a non-bonus points distribution.

    For each of ``draws`` iterations, in a fixed draw order, four uniforms are drawn -- minutes bin,
    goals, assists, team goals conceded -- and mapped through their inverse CDFs. A minutes bin of 0
    is the appearance gate: the draw scores exactly 0 (everything else zeroed), while the remaining
    uniforms are still consumed so the random stream length is fixed and the pmf is reproducible
    bit-for-bit for the same inputs. Otherwise the drawn counts index the prebuilt
    :class:`PointsLookup` for the base points.

    **Stage D v2 additions (additive).** When ``components.saves`` is not ``None`` or
    ``components.dc_hit_probability`` is non-zero, two MORE uniforms are drawn per iteration in a
    fixed appended order (saves, DC), and ``extra`` (an :class:`ExtraScoring`) is required. A drawn
    saves count adds ``saves // extra.saves_unit`` points for a position in
    ``extra.saves_positions``; a DC hit (``u_dc < dc_hit_probability``) adds ``extra.dc_points`` for
    a position in ``extra.dc_positions``. Both are summed onto the base BEFORE negatives are folded,
    so a goalkeeper's concede penalty nets against its save points on the total. When neither v2
    component is present the two extra uniforms are NOT drawn, so the four-uniform v1 stream -- and
    the pmf -- is reproduced bit-for-bit.

    Returns the empirical pmf over ``0..max_points`` (length ``max_points + 1``) as
    ``count / draws`` per bin, with the tail folded into the final bin.
    """
    if draws <= 0:
        raise ValueError(f"draws must be positive, got {draws}")
    extended = components.saves is not None or components.dc_hit_probability != 0.0
    if extended and extra is None:
        raise ValueError(
            "saves / defensive-contribution components require an ExtraScoring; got extra=None"
        )
    generator = Random(seed)
    minutes_cumulative = _cumulative(components.minutes)
    goals_cumulative = _cumulative(components.goals)
    assists_cumulative = _cumulative(components.assists)
    conceded_cumulative = _cumulative(components.team_goals_conceded)
    saves_cumulative = _cumulative(components.saves) if components.saves is not None else None

    position = components.position
    dc_probability = components.dc_hit_probability

    counts = [0] * (max_points + 1)
    for _ in range(draws):
        # Fixed draw order, always the same uniform count per iteration (even on the appearance
        # gate) so the stream is a deterministic function of (seed, draws). v1 draws four; v2 draws
        # two more ONLY when a v2 component is present, keeping the v1 stream bit-for-bit unchanged.
        u_minutes = generator.random()
        u_goals = generator.random()
        u_assists = generator.random()
        u_conceded = generator.random()
        if extended:
            u_saves = generator.random()
            u_dc = generator.random()

        bin_index = _sample_index(minutes_cumulative, u_minutes)
        if bin_index == 0:
            total = 0
        else:
            goals = _sample_index(goals_cumulative, u_goals)
            assists = _sample_index(assists_cumulative, u_assists)
            conceded = _sample_index(conceded_cumulative, u_conceded)
            total = lookup.points(position, bin_index, goals, assists, conceded)
            if extended:
                assert extra is not None  # guaranteed above when `extended`
                if saves_cumulative is not None and position in extra.saves_positions:
                    saves = _sample_index(saves_cumulative, u_saves)
                    total += saves // extra.saves_unit
                if position in extra.dc_positions and u_dc < dc_probability:
                    total += extra.dc_points

        index = total if total > 0 else 0
        if index > max_points:
            index = max_points
        counts[index] += 1

    return tuple(count / draws for count in counts)
