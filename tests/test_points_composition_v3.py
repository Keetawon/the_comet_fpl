"""Deterministic, offline tests for the Stage D v3 match-level JOINT full-points composer.

No network, no database. Uses the real 2026/27 scoring + BPS config (a local YAML read) and
hand-built component distributions. Covers: joint determinism under a fixed seed; the top-BPS
player receiving +3 bonus in the composed total; the own-scoring<->own-bonus coupling (a high-goal
draw carries the bonus); the full-points label = recomputed non-bonus + realised bonus; the BPS
exact lookup reusing ``exact_bps``; the award matching ``bps_bonus.award_bonus``; and the v2
per-player path being untouched.
"""

from __future__ import annotations

import pytest

from fpl.config import load_phase2_evaluation, load_scoring_rules
from fpl.models.attacking_baselines import poisson_pmf as count_poisson_pmf
from fpl.models.bps_bonus import PlayerRow, award_bonus, exact_bps
from fpl.models.points_composition import (
    BpsExactLookup,
    ComponentDistributions,
    ExtraScoring,
    FixturePlayer,
    PointsLookup,
    compose_fixture_full_points,
    compose_points_distribution,
    representative_minutes,
)
from fpl.models.scoring import calculate_points
from fpl.types import PlayerMatchStats, Position
from fpl.validate.points_harness_v3 import full_points

RULES = load_scoring_rules("2026_27")
assert RULES.bps is not None
BPS = RULES.bps
BINS = load_phase2_evaluation().output
BIN_RANGES = tuple((b.minutes_min, b.minutes_max) for b in BINS.bins)
BIN_MINUTES = representative_minutes(BIN_RANGES)
LOOKUP = PointsLookup(RULES, bin_minutes=BIN_MINUTES)
BPS_LOOKUP = BpsExactLookup(
    BPS, bin_minutes=BIN_MINUTES, clean_sheet_minimum_minutes=RULES.clean_sheets.minimum_minutes
)
EXTRA = ExtraScoring(
    saves_unit=RULES.saves.unit,
    dc_points=RULES.defensive_contribution.points,
    saves_positions=RULES.saves.positions,
    dc_positions=frozenset(RULES.defensive_contribution.thresholds),
)

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


def _deterministic_player(
    code: int,
    position: Position,
    goals: int,
    assists: int,
    conceded: int,
    *,
    minutes_bin: int = BIN_90,
    residual_mean: float = 0.0,
) -> FixturePlayer:
    """A player whose draw is fully deterministic (one-hot components, zero residual sigma)."""
    return FixturePlayer(
        code=code,
        components=ComponentDistributions(
            position=position,
            minutes=_minutes_one_hot(minutes_bin),
            goals=_count_one_hot(goals),
            assists=_count_one_hot(assists),
            team_goals_conceded=_count_one_hot(conceded),
        ),
        residual_mean=residual_mean,
        residual_sigma=0.0,
    )


# --------------------------------------------------------------------------------------
# BPS exact lookup reuses exact_bps
# --------------------------------------------------------------------------------------


def test_bps_exact_lookup_reuses_exact_bps() -> None:
    # MID, 90', 2 goals, 1 assist, 0 conceded. The lookup cell must equal exact_bps on the
    # equivalent hand-built PlayerRow (goals 2*18 + assists 1*9 = 45; MID earns no clean-sheet BPS).
    minutes = BIN_MINUTES[BIN_90]
    row = PlayerRow(
        code=0,
        position="MID",
        minutes=minutes,
        goals_scored=2,
        assists=1,
        clean_sheets=1,  # MID clean-sheet BPS is not awarded, so this is inert here.
        penalties_saved=0,
        clearances_blocks_interceptions=None,
        influence=0.0,
        creativity=0.0,
        bps=0,
        bonus=0,
    )
    assert BPS_LOOKUP.exact(Position.MID, BIN_90, 2, 1, 0) == exact_bps(row, BPS)
    assert BPS_LOOKUP.exact(Position.MID, BIN_90, 2, 1, 0) == pytest.approx(45.0)
    # DEF, 90', clean sheet (0 conceded) -> 12 BPS for the clean sheet.
    assert BPS_LOOKUP.exact(Position.DEF, BIN_90, 0, 0, 0) == pytest.approx(12.0)


# --------------------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------------------


def test_joint_determinism_bit_for_bit_under_fixed_seed() -> None:
    players = [
        FixturePlayer(
            code=101,
            components=ComponentDistributions(
                position=Position.MID,
                minutes=(0.1, 0.2, 0.3, 0.4),
                goals=count_poisson_pmf(0.6),
                assists=count_poisson_pmf(0.3),
                team_goals_conceded=count_poisson_pmf(1.2),
            ),
            residual_mean=1.5,
            residual_sigma=4.0,
        ),
        FixturePlayer(
            code=102,
            components=ComponentDistributions(
                position=Position.DEF,
                minutes=(0.05, 0.05, 0.2, 0.7),
                goals=count_poisson_pmf(0.1),
                assists=count_poisson_pmf(0.15),
                team_goals_conceded=count_poisson_pmf(1.2),
            ),
            residual_mean=-2.0,
            residual_sigma=5.0,
        ),
    ]
    first = compose_fixture_full_points(
        players, LOOKUP, BPS_LOOKUP, EXTRA, fixture_seed=202627, draws=1500
    )
    second = compose_fixture_full_points(
        players, LOOKUP, BPS_LOOKUP, EXTRA, fixture_seed=202627, draws=1500
    )
    assert [p.distribution for p in first] == [p.distribution for p in second]
    # A different seed yields a different empirical pmf, confirming it is genuinely seed-driven.
    third = compose_fixture_full_points(
        players, LOOKUP, BPS_LOOKUP, EXTRA, fixture_seed=7, draws=1500
    )
    assert [p.distribution for p in first] != [p.distribution for p in third]
    # Each pmf is proper.
    for player in first:
        assert abs(sum(player.distribution) - 1.0) < 1e-9


# --------------------------------------------------------------------------------------
# Top-BPS player gets +3 bonus in the composed total
# --------------------------------------------------------------------------------------


def test_top_bps_player_gets_three_bonus_in_the_total() -> None:
    # A fully deterministic fixture: A (MID, 2 goals) has the highest BPS, C (DEF, clean sheet)
    # second, B (FWD, nothing) third. So bonus is A=3, C=2, B=1 in every world.
    a = _deterministic_player(1, Position.MID, goals=2, assists=0, conceded=0)  # BPS 36
    b = _deterministic_player(2, Position.FWD, goals=0, assists=0, conceded=1)  # BPS 0
    c = _deterministic_player(3, Position.DEF, goals=0, assists=0, conceded=0)  # BPS 12 (CS)
    composed = compose_fixture_full_points(
        [a, b, c], LOOKUP, BPS_LOOKUP, EXTRA, fixture_seed=1, draws=200
    )
    by_code = {p.code: p for p in composed}
    # A: appearance 2 + 2 goals*5 + MID clean sheet 1 = 13; + bonus 3 = 16.
    assert by_code[1].distribution[16] == 1.0
    assert by_code[1].expected_bonus == pytest.approx(3.0)
    # C: appearance 2 + DEF clean sheet 4 = 6; + bonus 2 = 8.
    assert by_code[3].distribution[8] == 1.0
    assert by_code[3].expected_bonus == pytest.approx(2.0)
    # B: appearance 2 + FWD clean sheet 0 = 2; + bonus 1 = 3.
    assert by_code[2].distribution[3] == 1.0
    assert by_code[2].expected_bonus == pytest.approx(1.0)


def test_composed_award_matches_award_bonus() -> None:
    # For a deterministic fixture, each player's composed expected bonus must equal the award
    # award_bonus assigns to the deterministic BPS vector (order-aligned by code).
    players = [
        _deterministic_player(10, Position.MID, goals=1, assists=1, conceded=0),
        _deterministic_player(20, Position.FWD, goals=1, assists=0, conceded=1),
        _deterministic_player(30, Position.DEF, goals=0, assists=0, conceded=0),
        _deterministic_player(40, Position.GK, goals=0, assists=0, conceded=2, residual_mean=5.0),
    ]
    composed = compose_fixture_full_points(
        players, LOOKUP, BPS_LOOKUP, EXTRA, fixture_seed=3, draws=100
    )
    # The deterministic BPS each player draws every world (exact part + residual_mean, sigma 0).
    bps_values = [
        exact_bps(
            PlayerRow(
                code=p.code,
                position=p.components.position.value,
                minutes=BIN_MINUTES[BIN_90],
                goals_scored=next(i for i, m in enumerate(p.components.goals) if m == 1.0),
                assists=next(i for i, m in enumerate(p.components.assists) if m == 1.0),
                clean_sheets=1
                if next(i for i, m in enumerate(p.components.team_goals_conceded) if m == 1.0) == 0
                else 0,
                penalties_saved=0,
                clearances_blocks_interceptions=None,
                influence=0.0,
                creativity=0.0,
                bps=0,
                bonus=0,
            ),
            BPS,
        )
        + p.residual_mean
        for p in players
    ]
    expected_awards = award_bonus([round(v) for v in bps_values])
    by_code = {p.code: p for p in composed}
    for player, award in zip(players, expected_awards, strict=True):
        assert by_code[player.code].expected_bonus == pytest.approx(float(award))


# --------------------------------------------------------------------------------------
# Own-scoring <-> own-bonus coupling
# --------------------------------------------------------------------------------------


def test_own_scoring_and_own_bonus_are_coupled_in_the_same_draw() -> None:
    # Player X scores either 0 or 2 goals (50/50). Three filler players sit at a deterministic
    # BPS of 10. When X scores 2 (BPS 36) X is top and takes +3; when X scores 0 (BPS 0) X is
    # below all three fillers and gets 0. So X's bonus rides on X's OWN goals within each world:
    # the 2-goal outcome ALWAYS carries the +3, and no probability mass lands on "2 goals, no
    # bonus" (total 12). That absence is the coupling a v2-style independent bonus could not model.
    x = FixturePlayer(
        code=1,
        components=ComponentDistributions(
            position=Position.MID,
            minutes=_minutes_one_hot(BIN_90),
            goals=(0.5, 0.0, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            assists=_count_one_hot(0),
            team_goals_conceded=_count_one_hot(1),  # 1 conceded -> no clean sheet for X
        ),
        residual_mean=0.0,
        residual_sigma=0.0,
    )
    fillers = [
        FixturePlayer(
            code=code,
            components=ComponentDistributions(
                position=Position.MID,
                minutes=_minutes_one_hot(BIN_90),
                goals=_count_one_hot(0),
                assists=_count_one_hot(0),
                team_goals_conceded=_count_one_hot(1),
            ),
            residual_mean=10.0,
            residual_sigma=0.0,
        )
        for code in (2, 3, 4)
    ]
    composed = compose_fixture_full_points(
        [x, *fillers], LOOKUP, BPS_LOOKUP, EXTRA, fixture_seed=99, draws=6000
    )
    result = next(p for p in composed if p.code == 1)
    # X non-bonus: 2 goals -> 2 + 10 = 12; 0 goals -> 2. With coupling, 2-goal worlds carry +3.
    assert result.distribution[15] == pytest.approx(0.5, abs=0.03)  # 12 + 3 bonus
    assert result.distribution[2] == pytest.approx(0.5, abs=0.03)  # 2, no bonus
    # The decoupled outcome (2 goals but no bonus -> 12) must carry essentially no mass.
    assert result.distribution[12] < 0.01
    # And E[bonus] tracks E[goals>0]: ~0.5 * 3 = 1.5.
    assert result.expected_bonus == pytest.approx(1.5, abs=0.1)


# --------------------------------------------------------------------------------------
# Full-points label = recomputed non-bonus + realised bonus (R1-safe)
# --------------------------------------------------------------------------------------


def test_full_points_label_is_non_bonus_plus_realised_bonus() -> None:
    row: dict[str, object] = {
        "minutes": 90,
        "goals_scored": 1,
        "assists": 1,
        "clean_sheets": 1,
        "goals_conceded": 0,
        "saves": 0,
        "penalties_saved": 0,
        "penalties_missed": 0,
        "own_goals": 0,
        "yellow_cards": 0,
        "red_cards": 0,
        "bonus": 3,
        "defensive_contribution": 0,
    }
    label, realised_bonus = full_points(row, Position.MID, RULES)
    stats = PlayerMatchStats.from_row(row)
    # The full label equals the full recomputed total under the rules (which passes bonus through),
    # and realised bonus is the recorded bonus component -- never total_points (R1).
    assert label == calculate_points(stats, RULES, Position.MID)
    assert realised_bonus == 3
    # MID: appearance 2 + goal 5 + assist 3 + clean sheet 1 = 11 non-bonus; + 3 bonus = 14.
    assert label == 14


# --------------------------------------------------------------------------------------
# v2 per-player path is untouched
# --------------------------------------------------------------------------------------


def test_v2_per_player_path_unchanged() -> None:
    # The v2 composer must still behave exactly as before the v3 additions: a deterministic
    # sub-60 no-returns appearance scores exactly the short-appearance point, and the draw is
    # bit-for-bit reproducible for a fixed seed.
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
    short = ComponentDistributions(
        position=Position.MID,
        minutes=_minutes_one_hot(BIN_1_59),
        goals=_count_one_hot(0),
        assists=_count_one_hot(0),
        team_goals_conceded=_count_one_hot(0),
    )
    assert compose_points_distribution(short, LOOKUP, seed=3, draws=400)[1] == 1.0
