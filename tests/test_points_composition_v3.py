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
from fpl.models.attacking_v2 import _RosterEntry
from fpl.models.attacking_v3 import allocate_minutes_gated_rates
from fpl.models.bps_bonus import PlayerRow, award_bonus, exact_bps
from fpl.models.points_composition import (
    MEASURED_CONCEDED_EXPOSURE,
    BpsExactLookup,
    ComponentDistributions,
    ExtraScoring,
    FixturePlayer,
    PointsLookup,
    compose_fixture_full_points,
    compose_points_distribution,
    conditional_rate,
    representative_minutes,
    thin_count_distribution,
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


# --------------------------------------------------------------------------------------
# P(play) is applied exactly once: the composer conserves the Stage A team goal total
# --------------------------------------------------------------------------------------
#
# `allocate_minutes_gated_rates` returns rates that already carry p_play and sum to lambda_team.
# The composer gates AGAIN on the minutes draw, so feeding those rates in unchanged realises only
# `p_play * rate` per player and the roster silently loses attacking mass -- measured at 11.11% of
# all goal and assist mass over the GW29-38 horizon. `conditional_rate` divides p_play back out.


def test_conditional_rate_inverts_the_composer_appearance_gate() -> None:
    # The composer realises p_play * conditional_rate; that must equal the unconditional rate.
    for unconditional, p_play in ((0.42, 0.8), (0.11, 0.35), (1.7, 0.99)):
        restored = p_play * conditional_rate(unconditional, p_play, cap=10.0)
        assert restored == pytest.approx(unconditional)


def test_conditional_rate_leaves_a_never_playing_roster_alone() -> None:
    # p_play == 0 is only reachable on the all-absent fallback, where the composer scores every
    # draw as zero anyway. Returning the input beats dividing by zero.
    assert conditional_rate(0.5, 0.0, cap=2.0) == 0.5
    assert conditional_rate(0.0, 0.0, cap=2.0) == 0.0


def test_one_rotation_risk_among_nailed_team_mates_does_not_inflate_the_rate() -> None:
    """An individual p_play cancels: it is in the numerator and in the roster denominator."""
    roster = [_RosterEntry(code=i, signal=1.0, cold_start=False) for i in range(1, 5)]
    lambda_team = 1.6
    p_play = {1: 0.02, 2: 1.0, 3: 1.0, 4: 1.0}  # player 1 is a near-certain absentee
    allocated = allocate_minutes_gated_rates(roster, p_play, lambda_team, minutes_gating=True)
    rate, _path = allocated[1]
    # Equal shares, so the conditional rate is lambda_team * 0.25 / 0.755 -- bounded and well
    # under lambda_team. The 0.02 does NOT reappear as a 50x multiplier.
    assert conditional_rate(rate, p_play[1], cap=lambda_team) == pytest.approx(
        lambda_team * 0.25 / 0.755
    )


def test_a_whole_roster_of_absentees_is_capped_at_the_team_rate() -> None:
    """The denominator collapses when NOBODY is likely to play, so the cap has to be real.

    Without it a uniform p_play of 1e-6 over three equal shares turns a lambda_team of 1.6 into
    533,333 -- a single player expected to outscore their own team 300,000 times over.
    """
    roster = [_RosterEntry(code=i, signal=1.0, cold_start=False) for i in range(1, 4)]
    lambda_team = 1.6
    tiny = dict.fromkeys((1, 2, 3), 1e-6)
    allocated = allocate_minutes_gated_rates(roster, tiny, lambda_team, minutes_gating=True)
    for code in (1, 2, 3):
        rate, _path = allocated[code]
        assert rate / tiny[code] > 500_000  # the uncapped division really does diverge
        assert conditional_rate(rate, tiny[code], cap=lambda_team) == lambda_team


def test_the_cap_is_inert_on_a_realistic_roster() -> None:
    """It must not quietly truncate ordinary predictions -- only the degenerate ones."""
    roster = [
        _RosterEntry(code=1, signal=0.55, cold_start=False),
        _RosterEntry(code=2, signal=0.30, cold_start=False),
        _RosterEntry(code=3, signal=0.10, cold_start=False),
        _RosterEntry(code=4, signal=0.05, cold_start=True),
    ]
    p_play = {1: 0.95, 2: 0.60, 3: 0.25, 4: 0.40}
    lambda_team = 1.72
    allocated = allocate_minutes_gated_rates(roster, p_play, lambda_team, minutes_gating=True)
    for code, p in p_play.items():
        rate, _path = allocated[code]
        assert conditional_rate(rate, p, cap=lambda_team) < lambda_team


def test_corrected_roster_conserves_the_stage_a_team_goal_total() -> None:
    """sum_i P(play_i) * conditional_rate_i == lambda_team, which is the conservation property.

    Fails against the uncorrected wiring: passing the allocated rate straight through realises
    sum_i p_play_i * rate_i, which is strictly below lambda_team whenever anyone may be absent.
    """
    roster = [
        _RosterEntry(code=1, signal=0.55, cold_start=False),  # nailed striker
        _RosterEntry(code=2, signal=0.30, cold_start=False),  # rotated winger
        _RosterEntry(code=3, signal=0.10, cold_start=False),  # squad player
        _RosterEntry(code=4, signal=0.05, cold_start=True),  # cold start
    ]
    p_play = {1: 0.95, 2: 0.60, 3: 0.25, 4: 0.40}
    lambda_team = 1.72
    allocated = allocate_minutes_gated_rates(roster, p_play, lambda_team, minutes_gating=True)

    realised_corrected = sum(
        p_play[code] * conditional_rate(allocated[code][0], p_play[code], cap=lambda_team)
        for code in p_play
    )
    assert realised_corrected == pytest.approx(lambda_team)

    realised_uncorrected = sum(p_play[code] * allocated[code][0] for code in p_play)
    assert realised_uncorrected < lambda_team * 0.85  # the defect loses a sixth of the mass here


def test_the_composer_realises_the_unconditional_rate_end_to_end() -> None:
    """Drive the real composer and read the realised goal rate back out of the points pmf.

    A 90-minute midfielder who concedes exactly one goal scores ``appearance + 5 * goals`` and
    nothing else, so ``E[points] = p_play * appearance + goal_points * E[realised goals]`` inverts
    to the goal mass the composer actually delivered.
    """
    p_play = 0.7
    unconditional = 0.40
    appearance_points = RULES.appearance.long_play_points
    goal_points = RULES.goals_scored[Position.MID]
    draws = 400_000

    def realised_goal_mass(rate: float) -> float:
        components = ComponentDistributions(
            position=Position.MID,
            minutes=(1.0 - p_play, 0.0, 0.0, p_play),
            goals=count_poisson_pmf(rate),
            assists=_count_one_hot(0),
            team_goals_conceded=_count_one_hot(1),  # one conceded: no clean sheet, no MID penalty
        )
        pmf = compose_points_distribution(components, LOOKUP, seed=202627, draws=draws)
        expected_points = sum(index * mass for index, mass in enumerate(pmf))
        return (expected_points - p_play * appearance_points) / goal_points

    corrected = realised_goal_mass(conditional_rate(unconditional, p_play, cap=3.0))
    assert corrected == pytest.approx(unconditional, rel=0.02)

    # The uncorrected wiring delivers only p_play of the mass it was asked to allocate.
    uncorrected = realised_goal_mass(unconditional)
    assert uncorrected == pytest.approx(unconditional * p_play, rel=0.02)


# --------------------------------------------------------------------------------------
# Goals conceded are charged only for the part of the match the player was on the pitch
# --------------------------------------------------------------------------------------
#
# FPL charges the goals-conceded penalty, and awards the clean sheet, on goals conceded WHILE THE
# PLAYER WAS ON THE PITCH. The composer handed every appearing player the full-match team conceded
# distribution, which over-charged substitutes 4.2x (measured mean penalty 0.559 against an actual
# 0.133 for the 1-59 bin).


def test_thinning_is_the_identity_at_full_exposure() -> None:
    """Bin 3 must not move: a player who lasted the match saw all of it."""
    team = count_poisson_pmf(1.43)
    assert thin_count_distribution(team, 1.0) == team


def test_thinning_moves_mass_toward_zero_and_stays_a_proper_distribution() -> None:
    team = count_poisson_pmf(1.6)
    thinned = thin_count_distribution(team, 0.344)
    assert sum(thinned) == pytest.approx(sum(team))
    assert thinned[0] > team[0]  # more chance of seeing none of them
    mean_team = sum(i * m for i, m in enumerate(team))
    mean_thinned = sum(i * m for i, m in enumerate(thinned))
    assert mean_thinned == pytest.approx(0.344 * mean_team, rel=1e-6)


def test_thinning_a_known_count_is_the_binomial() -> None:
    """A point mass at 3 conceded, thinned at 0.5, is Binomial(3, 0.5) exactly."""
    thinned = thin_count_distribution(_count_one_hot(3), 0.5)
    assert thinned[:4] == pytest.approx((0.125, 0.375, 0.375, 0.125))
    assert sum(thinned[4:]) == pytest.approx(0.0)


def test_measured_exposure_matches_the_archive_penalty_rates() -> None:
    """The constant is only worth having if it reproduces the observed penalty per bin.

    Archive means (GK/DEF): bin 1 0.133, bin 2 0.412, bin 3 0.485, against a team conceded rate of
    about 1.5. The un-thinned composer charges every one of them the bin-3 figure.
    """
    team = count_poisson_pmf(1.5)

    def mean_penalty(exposure: float) -> float:
        thinned = thin_count_distribution(team, exposure)
        return sum((n // 2) * mass for n, mass in enumerate(thinned))

    assert mean_penalty(MEASURED_CONCEDED_EXPOSURE[1]) == pytest.approx(0.11, abs=0.03)
    assert mean_penalty(MEASURED_CONCEDED_EXPOSURE[2]) == pytest.approx(0.41, abs=0.03)
    assert mean_penalty(MEASURED_CONCEDED_EXPOSURE[3]) == pytest.approx(0.49, abs=0.03)
    # The defect: without thinning a substitute is charged the full-match rate, 4x the truth.
    assert mean_penalty(1.0) / mean_penalty(MEASURED_CONCEDED_EXPOSURE[1]) > 3.5


def test_omitting_exposure_reproduces_the_unthinned_composer_bit_for_bit() -> None:
    """The new parameter must be inert when absent, on both composer entry points."""
    players = [
        FixturePlayer(
            code=code,
            components=ComponentDistributions(
                position=position,
                minutes=(0.1, 0.2, 0.3, 0.4),
                goals=count_poisson_pmf(0.3),
                assists=count_poisson_pmf(0.2),
                team_goals_conceded=count_poisson_pmf(1.4),
            ),
            residual_mean=0.0,
            residual_sigma=3.0,
        )
        for code, position in ((11, Position.DEF), (12, Position.MID))
    ]
    absent = compose_fixture_full_points(
        players, LOOKUP, BPS_LOOKUP, EXTRA, fixture_seed=5, draws=800
    )
    explicit_identity = compose_fixture_full_points(
        players,
        LOOKUP,
        BPS_LOOKUP,
        EXTRA,
        fixture_seed=5,
        draws=800,
        conceded_exposure=(0.0, 1.0, 1.0, 1.0),
    )
    assert [p.distribution for p in absent] == [p.distribution for p in explicit_identity]

    thinned = compose_fixture_full_points(
        players,
        LOOKUP,
        BPS_LOOKUP,
        EXTRA,
        fixture_seed=5,
        draws=800,
        conceded_exposure=MEASURED_CONCEDED_EXPOSURE,
    )
    assert [p.distribution for p in thinned] != [p.distribution for p in absent]


def _defender_expected_points(minutes_bin: int, exposure: tuple[float, ...] | None) -> float:
    """A defender facing a leaky opponent, scored end to end through the real composer."""
    components = ComponentDistributions(
        position=Position.DEF,
        minutes=_minutes_one_hot(minutes_bin),
        goals=_count_one_hot(0),
        assists=_count_one_hot(0),
        team_goals_conceded=count_poisson_pmf(2.4),
    )
    pmf = compose_points_distribution(
        components, LOOKUP, seed=202627, draws=200_000, conceded_exposure=exposure
    )
    return sum(index * mass for index, mass in enumerate(pmf))


def test_thinning_raises_a_defenders_points_at_every_appearing_bin() -> None:
    """Isolates exposure: identical bin, identical everything, only the charge changes."""
    for minutes_bin in (BIN_1_59, 2, BIN_90):
        thinned = _defender_expected_points(minutes_bin, MEASURED_CONCEDED_EXPOSURE)
        unthinned = _defender_expected_points(minutes_bin, None)
        if minutes_bin == BIN_90:
            assert thinned == unthinned  # exposure 1.0 -> nothing to thin
        else:
            assert thinned > unthinned


def test_a_sixty_minute_defender_outscores_an_ever_present_one_against_a_leaky_team() -> None:
    """Both bank 2 appearance points and both are clean-sheet eligible, so exposure is the only
    difference between them -- and coming off on 75 minutes really is worth points when the team
    is shipping goals."""
    sixty = _defender_expected_points(2, MEASURED_CONCEDED_EXPOSURE)
    ever_present = _defender_expected_points(BIN_90, MEASURED_CONCEDED_EXPOSURE)
    assert sixty > ever_present


def test_a_substituted_defender_can_keep_a_clean_sheet_his_team_did_not() -> None:
    """FPL awards the clean sheet on goals conceded while ON THE PITCH.

    A 60-89 player whose team conceded once, after he was withdrawn, keeps his clean sheet. The
    un-thinned composer could never represent that: it required the whole team to keep one.
    """
    components = ComponentDistributions(
        position=Position.DEF,
        minutes=_minutes_one_hot(2),
        goals=_count_one_hot(0),
        assists=_count_one_hot(0),
        team_goals_conceded=_count_one_hot(1),  # the team concedes exactly one, every world
    )
    clean_sheet_points = RULES.clean_sheets.points[Position.DEF]
    scored = RULES.appearance.long_play_points + clean_sheet_points

    unthinned = compose_points_distribution(components, LOOKUP, seed=11, draws=50_000)
    assert unthinned[scored] == 0.0  # team conceded, so nobody ever keeps one

    thinned = compose_points_distribution(
        components, LOOKUP, seed=11, draws=50_000, conceded_exposure=MEASURED_CONCEDED_EXPOSURE
    )
    # He is on the pitch for 0.813 of the conceded goals, so he keeps it about 18.7% of the time.
    assert thinned[scored] == pytest.approx(1.0 - MEASURED_CONCEDED_EXPOSURE[2], abs=0.01)
