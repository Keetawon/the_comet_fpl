"""Deterministic, offline tests for the Stage D v1 points composer.

No network, no database. Uses the real 2026/27 scoring config (a local YAML read) and hand-built
component distributions.
"""

from __future__ import annotations

from fpl.config import load_phase2_evaluation, load_scoring_rules
from fpl.models.attacking_baselines import poisson_pmf as count_poisson_pmf
from fpl.models.points_composition import (
    ComponentDistributions,
    PointsLookup,
    compose_points_distribution,
    representative_minutes,
)
from fpl.types import Position

RULES = load_scoring_rules("2026_27")
BINS = load_phase2_evaluation().output
BIN_RANGES = tuple((b.minutes_min, b.minutes_max) for b in BINS.bins)
BIN_MINUTES = representative_minutes(BIN_RANGES)
LOOKUP = PointsLookup(RULES, bin_minutes=BIN_MINUTES)

# Bin indices for the frozen four-bin minutes shape.
BIN_ZERO = 0
BIN_1_59 = 1
BIN_90 = 3


def _minutes_one_hot(index: int) -> tuple[float, float, float, float]:
    masses = [0.0, 0.0, 0.0, 0.0]
    masses[index] = 1.0
    return (masses[0], masses[1], masses[2], masses[3])


def _count_one_hot(value: int) -> tuple[float, ...]:
    masses = [0.0] * 11
    masses[value] = 1.0
    return tuple(masses)


def _components(
    position: Position,
    minutes_bin: int,
    goals: int,
    assists: int,
    conceded: int,
) -> ComponentDistributions:
    return ComponentDistributions(
        position=position,
        minutes=_minutes_one_hot(minutes_bin),
        goals=_count_one_hot(goals),
        assists=_count_one_hot(assists),
        team_goals_conceded=_count_one_hot(conceded),
    )


def test_representative_minutes_from_frozen_bins() -> None:
    # (0,0),(1,59),(60,89),(90,None) -> 0, 59, 89, 90; on the correct side of the 60' threshold.
    assert BIN_MINUTES == (0, 59, 89, 90)


def test_determinism_bit_for_bit_under_fixed_seed() -> None:
    # Spread (non-degenerate) components so the empirical pmf genuinely depends on the draws.
    components = ComponentDistributions(
        position=Position.MID,
        minutes=(0.1, 0.2, 0.3, 0.4),
        goals=count_poisson_pmf(0.5),
        assists=count_poisson_pmf(0.4),
        team_goals_conceded=count_poisson_pmf(1.3),
    )
    first = compose_points_distribution(components, LOOKUP, seed=202627, draws=1000)
    second = compose_points_distribution(components, LOOKUP, seed=202627, draws=1000)
    assert first == second
    # A different seed produces a different empirical pmf, confirming it is genuinely seed-driven.
    third = compose_points_distribution(components, LOOKUP, seed=1, draws=1000)
    assert first != third


def test_appearance_gate_zero_minutes_scores_exactly_zero() -> None:
    # Bin 0 always: every draw is the appearance gate -> exactly 0 points, goals/assists ignored.
    components = ComponentDistributions(
        position=Position.FWD,
        minutes=_minutes_one_hot(BIN_ZERO),
        goals=count_poisson_pmf(2.0),
        assists=count_poisson_pmf(1.0),
        team_goals_conceded=count_poisson_pmf(1.5),
    )
    pmf = compose_points_distribution(components, LOOKUP, seed=7, draws=500)
    assert pmf[0] == 1.0
    assert sum(pmf) == 1.0


def test_sub_sixty_appearance_no_returns_scores_exactly_one_point() -> None:
    # 1-59 minutes, no goals/assists, no clean sheet (sub-60) -> exactly the short-appearance point.
    components = _components(Position.MID, BIN_1_59, goals=0, assists=0, conceded=0)
    pmf = compose_points_distribution(components, LOOKUP, seed=3, draws=400)
    assert pmf[1] == 1.0


def test_sixty_plus_appearance_no_returns_scores_two_points() -> None:
    # 60+ minutes forward, no goals/assists, 0 conceded: appearance 2 + FWD clean sheet 0 = 2.
    components = _components(Position.FWD, BIN_90, goals=0, assists=0, conceded=0)
    pmf = compose_points_distribution(components, LOOKUP, seed=11, draws=400)
    assert pmf[2] == 1.0


def test_clean_sheet_requires_both_zero_conceded_and_sixty_minutes() -> None:
    # DEF, 60+, 0 conceded -> clean sheet: appearance 2 + CS 4 = 6.
    kept = _components(Position.DEF, BIN_90, goals=0, assists=0, conceded=0)
    assert compose_points_distribution(kept, LOOKUP, seed=1, draws=200)[6] == 1.0
    # DEF, sub-60, 0 conceded -> NO clean sheet (minutes gate): appearance 1.
    short = _components(Position.DEF, BIN_1_59, goals=0, assists=0, conceded=0)
    assert compose_points_distribution(short, LOOKUP, seed=1, draws=200)[1] == 1.0
    # DEF, 60+, 1 conceded -> NO clean sheet (conceded gate): appearance 2, no penalty (1 // 2 = 0).
    conceded = _components(Position.DEF, BIN_90, goals=0, assists=0, conceded=1)
    assert compose_points_distribution(conceded, LOOKUP, seed=1, draws=200)[2] == 1.0


def test_position_dependent_goal_points() -> None:
    # Difference of one goal with conceded=1 (no clean sheet either way) isolates the goal value.
    def goal_value(position: Position) -> int:
        with_goal = LOOKUP.points(position, BIN_90, 1, 0, 1)
        without = LOOKUP.points(position, BIN_90, 0, 0, 1)
        return with_goal - without

    assert goal_value(Position.DEF) == 6
    assert goal_value(Position.MID) == 5
    assert goal_value(Position.FWD) == 4
    assert goal_value(Position.GK) == 10


def test_position_dependent_clean_sheet_points() -> None:
    # Difference between 0 conceded (clean sheet) and 1 conceded (no CS, no penalty) at 60+ minutes.
    def clean_sheet_value(position: Position) -> int:
        with_cs = LOOKUP.points(position, BIN_90, 0, 0, 0)
        without = LOOKUP.points(position, BIN_90, 0, 0, 1)
        return with_cs - without

    assert clean_sheet_value(Position.DEF) == 4
    assert clean_sheet_value(Position.GK) == 4
    assert clean_sheet_value(Position.MID) == 1
    assert clean_sheet_value(Position.FWD) == 0


def test_degenerate_zero_rate_components_compose_to_a_valid_pmf() -> None:
    # The no-xG fallback can yield a rate-0 Poisson (point mass on zero). Composition must still
    # produce a proper pmf and route the mass through the appearance / no-goal paths.
    components = ComponentDistributions(
        position=Position.MID,
        minutes=(0.0, 0.0, 0.0, 1.0),
        goals=count_poisson_pmf(0.0),
        assists=count_poisson_pmf(0.0),
        team_goals_conceded=count_poisson_pmf(0.0),
    )
    pmf = compose_points_distribution(components, LOOKUP, seed=5, draws=300)
    assert abs(sum(pmf) - 1.0) < 1e-9
    # 90', 0 goals, 0 assists, 0 conceded, MID -> appearance 2 + MID clean sheet 1 = 3.
    assert pmf[3] == 1.0


def test_negative_concede_points_fold_into_zero_bin() -> None:
    # DEF, sub-60 (appearance 1), 6 conceded -> 1 + (6 // 2) * -1 = -2, folded to the 0 bin.
    components = _components(Position.DEF, BIN_1_59, goals=0, assists=0, conceded=6)
    pmf = compose_points_distribution(components, LOOKUP, seed=1, draws=200)
    assert pmf[0] == 1.0
