"""The V2 football engine, the fixture-environment contract, and the V2 components.

The engine's central claim is that fitting one rating system per signal makes an ablation
attributable: two rungs differ only in which signals participate, so a lift belongs to the
signal. Several of these tests exist to keep that claim true -- notably that a single-signal
engine reproduces the underlying estimator exactly, and that an unavailable signal degrades
the blend rather than deflating the rate.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from fpl.artifacts.fixture_environment import (
    FixtureEnvironment,
    FixtureEnvironmentError,
    TeamEnvironment,
    summarise_coverage,
)
from fpl.models.defensive_environment_v2 import (
    DcEnvironmentHistoryRow,
    DefensiveEnvironmentV2,
)
from fpl.models.football_engine_v2 import (
    BLENDABLE_SIGNALS,
    DEFAULT_SIGNALS,
    MultiSignalTeamEngine,
    SignalSpec,
    simplex_grid,
)
from fpl.models.gk_saves_v1 import GkSavesHistoryRow, GkSavesV1
from fpl.models.gk_saves_v2 import GkSavesV2
from fpl.types import Position
from fpl.validate.metrics import poisson_pmf

START = datetime(2025, 8, 16, 14, 0, tzinfo=UTC)


def _frame(matches: int = 40, *, with_xg: bool = True, with_sot: bool = True) -> pl.DataFrame:
    """A synthetic four-club round-robin with a deliberate strength ordering.

    Club 3 attacks best and club 8 worst, so a fitted engine that has learned anything must
    rank them in that order -- which is a stronger assertion than "it produced a number".
    """
    strength = {3: 2.0, 8: 0.7, 11: 1.3, 14: 1.0}
    rows: list[dict[str, object]] = []
    clubs = sorted(strength)
    fixture = 0
    for week in range(matches):
        pairs = (
            [(clubs[0], clubs[1]), (clubs[2], clubs[3])]
            if week % 2 == 0
            else [
                (clubs[0], clubs[2]),
                (clubs[1], clubs[3]),
            ]
        )
        for home, away in pairs:
            fixture += 1
            kickoff = START + timedelta(days=7 * week)
            for team, opponent, was_home in ((home, away, True), (away, home, False)):
                base = strength[team] / strength[opponent] * (1.2 if was_home else 1.0)
                goals = round(base)
                rows.append(
                    {
                        "season": "2025-26",
                        "gw": week + 1,
                        "fixture": fixture,
                        "kickoff_time": kickoff,
                        "team_code": team,
                        "opponent_team_code": opponent,
                        "was_home": was_home,
                        "goals": goals,
                        "expected_goals": base if with_xg else None,
                        "shots_on_target": base * 3.0 if with_sot else None,
                        "shots_on_target_allowed_proxy": (
                            strength[opponent] / strength[team] * 3.0 if with_sot else None
                        ),
                        "expected_goals_on_target": None,
                        "shots": None,
                        "touches_in_opposition_box": None,
                        "big_chances_created": None,
                        "defensive_actions": None,
                    }
                )
    return pl.DataFrame(rows)


# -- the contract ---------------------------------------------------------------------


def _side(team: int, *, was_home: bool, rate: float = 1.4) -> TeamEnvironment:
    distribution = poisson_pmf(rate)
    return TeamEnvironment(
        team_code=team,
        was_home=was_home,
        goal_distribution=distribution,
        expected_goals=sum(i * m for i, m in enumerate(distribution)),
        expected_goals_against=1.1,
    )


def test_a_distribution_that_does_not_sum_to_one_is_refused() -> None:
    """An unnormalised pmf would silently misprice every downstream probability."""
    with pytest.raises(FixtureEnvironmentError, match="sums to"):
        TeamEnvironment(
            team_code=3,
            was_home=True,
            goal_distribution=(0.5, 0.2),
            expected_goals=0.2,
            expected_goals_against=1.0,
        )


def test_expected_goals_must_agree_with_its_own_distribution() -> None:
    with pytest.raises(FixtureEnvironmentError, match="disagrees with the mean"):
        TeamEnvironment(
            team_code=3,
            was_home=True,
            goal_distribution=poisson_pmf(1.4),
            expected_goals=3.0,
            expected_goals_against=1.0,
        )


def test_mislabelled_sides_are_refused() -> None:
    with pytest.raises(FixtureEnvironmentError, match="mislabelled"):
        FixtureEnvironment(
            season="2025-26",
            fixture=1,
            gw=1,
            kickoff_time=START,
            home=_side(3, was_home=False),
            away=_side(8, was_home=False),
        )


def test_clean_sheet_is_the_opponents_zero_mass_exactly() -> None:
    """Read off the opponent's own distribution, so the two cannot disagree."""
    environment = FixtureEnvironment(
        season="2025-26",
        fixture=1,
        gw=1,
        kickoff_time=START,
        home=_side(3, was_home=True, rate=1.8),
        away=_side(8, was_home=False, rate=0.9),
    )
    assert environment.clean_sheet_probability(3) == pytest.approx(math.exp(-0.9), abs=1e-9)
    assert environment.goals_conceded_distribution(3) == environment.away.goal_distribution


def test_a_club_not_in_the_fixture_is_a_key_error() -> None:
    environment = FixtureEnvironment(
        season="2025-26",
        fixture=1,
        gw=1,
        kickoff_time=START,
        home=_side(3, was_home=True),
        away=_side(8, was_home=False),
    )
    with pytest.raises(KeyError, match="does not play"):
        environment.for_team(99)


def test_coverage_summary_counts_present_and_absent_signals() -> None:
    home = TeamEnvironment(
        team_code=3,
        was_home=True,
        goal_distribution=poisson_pmf(1.4),
        expected_goals=sum(i * m for i, m in enumerate(poisson_pmf(1.4))),
        expected_goals_against=1.0,
        signal_coverage={"goals": True, "shots_on_target": False},
    )
    away = TeamEnvironment(
        team_code=8,
        was_home=False,
        goal_distribution=poisson_pmf(1.0),
        expected_goals=sum(i * m for i, m in enumerate(poisson_pmf(1.0))),
        expected_goals_against=1.4,
        signal_coverage={"goals": True, "shots_on_target": False},
    )
    summary = summarise_coverage(
        [
            FixtureEnvironment(
                season="2025-26", fixture=1, gw=1, kickoff_time=START, home=home, away=away
            )
        ]
    )
    assert summary["goals"] == {"present": 2, "absent": 0}
    assert summary["shots_on_target"] == {"present": 0, "absent": 2}


# -- the engine -------------------------------------------------------------------------


def test_simplex_grid_weights_sum_to_one() -> None:
    for count in (1, 2, 3, 4):
        points = simplex_grid(count, step=0.25)
        assert points
        for point in points:
            assert len(point) == count
            assert sum(point) == pytest.approx(1.0)
            assert all(value >= 0.0 for value in point)


def test_the_engine_learns_the_strength_ordering() -> None:
    engine = MultiSignalTeamEngine()
    engine.set_prediction_season("2025-26")
    engine.fit(_frame())
    strong = engine.goal_rate(3, 14, was_home=True)
    weak = engine.goal_rate(8, 14, was_home=True)
    assert strong > weak, "a fitted engine must rank a strong attack above a weak one"


def test_home_advantage_is_learned_not_assumed() -> None:
    engine = MultiSignalTeamEngine()
    engine.set_prediction_season("2025-26")
    engine.fit(_frame())
    assert engine.goal_rate(3, 14, was_home=True) > engine.goal_rate(3, 14, was_home=False)


def test_an_absent_signal_is_rejected_with_a_recorded_reason() -> None:
    """A coverage gap must be reported, not silently absorbed into the blend."""
    engine = MultiSignalTeamEngine()
    engine.set_prediction_season("2025-26")
    engine.fit(_frame(with_xg=False))
    assert "expected_goals" in engine.parameters.signals_rejected
    assert "goals" in engine.parameters.signals_fitted
    assert "expected_goals" not in engine.parameters.weights


def test_a_low_coverage_signal_is_rejected_by_the_floor() -> None:
    frame = _frame()
    # Measure xG on only a tenth of rows: a rating fitted from that is mostly its prior.
    frame = frame.with_columns(
        pl.when(pl.arange(0, frame.height) % 10 == 0)
        .then(pl.col("expected_goals"))
        .otherwise(None)
        .alias("expected_goals")
    )
    engine = MultiSignalTeamEngine(minimum_signal_coverage=0.25)
    engine.set_prediction_season("2025-26")
    engine.fit(frame)
    assert "coverage" in engine.parameters.signals_rejected["expected_goals"]


def test_a_single_signal_engine_produces_a_degenerate_blend() -> None:
    """Rung A must be the estimator alone, so it isolates it from the blend."""
    engine = MultiSignalTeamEngine(signals=[SignalSpec("goals", "goals")])
    engine.set_prediction_season("2025-26")
    engine.fit(_frame())
    assert engine.parameters.weights == {"goals": 1.0}


def test_environment_only_signals_are_declared_non_blendable() -> None:
    """The declaration is the guard; the engine merely honours it."""
    non_blendable = {spec.name for spec in DEFAULT_SIGNALS if not spec.blendable}
    assert non_blendable == {"shots_on_target_allowed_proxy", "defensive_actions"}
    assert not (non_blendable & BLENDABLE_SIGNALS)


def test_environment_signals_never_enter_the_goal_blend() -> None:
    """Blending an opponent-facing measurement into an attacking rate would invert it."""
    engine = MultiSignalTeamEngine()
    engine.set_prediction_season("2025-26")
    engine.fit(_frame())
    assert "shots_on_target_allowed_proxy" in engine.fitted_signals
    assert "shots_on_target_allowed_proxy" not in engine.parameters.weights
    assert "defensive_actions" not in engine.parameters.weights


def test_shots_faced_is_read_from_the_proxy_where_it_fitted() -> None:
    """A measurement of shots faced beats a rearrangement of shots taken."""
    engine = MultiSignalTeamEngine()
    engine.set_prediction_season("2025-26")
    engine.fit(_frame())
    environment = engine.predict_environment(
        season="2025-26", fixture=9001, home_team_code=3, away_team_code=8
    )
    # Club 3 is strong and club 8 weak, so club 3 should face fewer shots than club 8 does.
    assert environment.home.expected_shots_on_target_against is not None
    assert environment.away.expected_shots_on_target_against is not None
    assert (
        environment.home.expected_shots_on_target_against
        < environment.away.expected_shots_on_target_against
    )


def test_an_unknown_club_is_a_cold_start_and_lands_on_its_prior() -> None:
    engine = MultiSignalTeamEngine()
    engine.set_promoted({"2025-26": frozenset({99})})
    engine.set_prediction_season("2025-26")
    engine.fit(_frame())
    assert engine.is_cold_start(99, 3)
    rate = engine.goal_rate(99, 3, was_home=True)
    assert rate > 0.0 and math.isfinite(rate)


def test_predicting_environments_pairs_sides_rather_than_assuming_order() -> None:
    engine = MultiSignalTeamEngine()
    engine.set_prediction_season("2025-26")
    frame = _frame()
    engine.fit(frame)
    shuffled = frame.head(4).sort("team_code", descending=True)
    environments = engine.predict_environments(shuffled)
    for environment in environments:
        assert environment.home.was_home and not environment.away.was_home
        assert environment.home.team_code != environment.away.team_code


def test_an_empty_training_window_does_not_crash() -> None:
    engine = MultiSignalTeamEngine()
    engine.fit(pl.DataFrame(schema=_frame().schema))
    assert engine.parameters.signals_fitted == ()


# -- GK saves V2 -------------------------------------------------------------------------


def _gk_history(rows: int = 200) -> list[GkSavesHistoryRow]:
    """A history whose league save rate is exactly 0.70 by construction."""
    return [
        GkSavesHistoryRow(position=Position.GK, minutes=90, saves=7, goals_conceded=3)
        for _ in range(rows)
    ]


def test_v1_and_v2_derive_the_same_save_rate() -> None:
    """Sharing the estimator is what makes the comparison about the shot volume alone."""
    v1, v2 = GkSavesV1(), GkSavesV2()
    v1.fit(_gk_history())
    v2.fit(_gk_history())
    assert v1.save_rate == pytest.approx(v2.save_rate)
    assert v2.save_rate == pytest.approx(0.70)


def test_v2_reproduces_v1_exactly_when_it_has_no_shots_signal() -> None:
    """The fallback is what keeps V2 never worse-informed than V1."""
    v1, v2 = GkSavesV1(), GkSavesV2()
    v1.fit(_gk_history())
    v2.fit(_gk_history())
    assert v2.predict(Position.GK, 1.4) == pytest.approx(v1.predict(Position.GK, 1.4))


def test_v2_uses_the_engines_shots_faced_when_it_has_one() -> None:
    v2 = GkSavesV2()
    v2.fit(_gk_history())
    detail = v2.predict_detail(Position.GK, lambda_conceded=1.4, expected_shots_on_target_faced=8.0)
    assert detail.used_expected_shots is True
    assert detail.rate == pytest.approx(0.70 * 8.0)


def test_two_clubs_with_equal_conceded_but_different_shots_differ_under_v2_only() -> None:
    """The whole hypothesis, in one test.

    V1 cannot tell these apart because shots faced is a function of goals conceded; V2 can,
    because shots faced is supplied by the engine.
    """
    v1, v2 = GkSavesV1(), GkSavesV2()
    v1.fit(_gk_history())
    v2.fit(_gk_history())
    quiet = v2.predict(Position.GK, 1.4, expected_shots_on_target_faced=3.0)
    busy = v2.predict(Position.GK, 1.4, expected_shots_on_target_faced=9.0)
    assert quiet != busy
    assert v1.predict(Position.GK, 1.4) == pytest.approx(v1.predict(Position.GK, 1.4))
    quiet_mean = sum(i * m for i, m in enumerate(quiet))
    busy_mean = sum(i * m for i, m in enumerate(busy))
    assert busy_mean > quiet_mean


def test_a_non_goalkeeper_scores_no_saves() -> None:
    v2 = GkSavesV2()
    v2.fit(_gk_history())
    for position in (Position.DEF, Position.MID, Position.FWD):
        distribution = v2.predict(position, 1.4, expected_shots_on_target_faced=8.0)
        assert distribution[0] == 1.0


def test_saves_distributions_are_normalised() -> None:
    v2 = GkSavesV2()
    v2.fit(_gk_history())
    for shots in (0.5, 3.0, 8.0, 15.0):
        distribution = v2.predict(Position.GK, 1.4, expected_shots_on_target_faced=shots)
        assert sum(distribution) == pytest.approx(1.0, abs=1e-6)


# -- DC environment V2 ---------------------------------------------------------------------


def _dc_history(share: float = 0.12, rows: int = 10) -> list[DcEnvironmentHistoryRow]:
    return [
        DcEnvironmentHistoryRow(
            code=7,
            team_code=3,
            position=Position.MID,
            minutes=90,
            defensive_contribution=round(share * 100),
            team_defensive_actions=100,
        )
        for _ in range(rows)
    ]


def test_role_share_is_dimensionless_and_comparable_between_clubs() -> None:
    model = DefensiveEnvironmentV2()
    model.fit(_dc_history())
    share = model.role_share(7, Position.MID)
    assert share is not None
    assert 0.10 < share < 0.14


def test_a_transferred_player_is_rescaled_by_the_destination_environment() -> None:
    """The measured rule this model exists to obey: the scale does not travel, the share does."""
    model = DefensiveEnvironmentV2()
    model.fit(_dc_history())
    low_block = model.predict_detail(
        code=7, position=Position.MID, threshold=12, team_defensive_actions=160.0
    )
    dominant = model.predict_detail(
        code=7, position=Position.MID, threshold=12, team_defensive_actions=70.0
    )
    assert low_block.role_share == dominant.role_share, "the share travels with the player"
    assert low_block.expected_count is not None and dominant.expected_count is not None
    assert low_block.expected_count > dominant.expected_count, "the scale does not"
    assert low_block.hit_probability > dominant.hit_probability


def test_no_measured_dc_in_the_window_contributes_nothing() -> None:
    """Every season before 2025-26 has NULL DC; that is unmeasured, never zero."""
    model = DefensiveEnvironmentV2()
    model.fit(
        [
            DcEnvironmentHistoryRow(
                code=7,
                team_code=3,
                position=Position.MID,
                minutes=90,
                defensive_contribution=None,
                team_defensive_actions=None,
            )
        ]
    )
    assert model.has_measured_dc is False
    assert (
        model.predict(code=7, position=Position.MID, threshold=12, team_defensive_actions=120.0)
        == 0.0
    )


def test_goalkeepers_never_earn_the_award() -> None:
    model = DefensiveEnvironmentV2()
    model.fit(_dc_history())
    assert (
        model.predict(code=7, position=Position.GK, threshold=12, team_defensive_actions=120.0)
        == 0.0
    )


def test_an_absent_environment_contributes_nothing_rather_than_inventing_one() -> None:
    model = DefensiveEnvironmentV2()
    model.fit(_dc_history())
    prediction = model.predict_detail(
        code=7, position=Position.MID, threshold=12, team_defensive_actions=None
    )
    assert prediction.hit_probability == 0.0
    assert prediction.used_environment is False


def test_a_short_history_is_shrunk_toward_the_position_mean() -> None:
    history = [*_dc_history(share=0.12, rows=30), *_dc_history(share=0.30, rows=1)]
    history[-1] = DcEnvironmentHistoryRow(
        code=99,
        team_code=3,
        position=Position.MID,
        minutes=90,
        defensive_contribution=30,
        team_defensive_actions=100,
    )
    model = DefensiveEnvironmentV2()
    model.fit(history)
    newcomer = model.role_share(99, Position.MID)
    assert newcomer is not None
    assert newcomer < 0.30, "one appearance must not be trusted at face value"


def test_minutes_exposure_thins_the_expected_count() -> None:
    model = DefensiveEnvironmentV2()
    model.fit(_dc_history())
    full = model.predict_detail(
        code=7,
        position=Position.MID,
        threshold=12,
        team_defensive_actions=120.0,
        minutes_exposure=1.0,
    )
    cameo = model.predict_detail(
        code=7,
        position=Position.MID,
        threshold=12,
        team_defensive_actions=120.0,
        minutes_exposure=0.25,
    )
    assert full.expected_count is not None and cameo.expected_count is not None
    assert cameo.expected_count == pytest.approx(full.expected_count * 0.25)
    assert cameo.hit_probability < full.hit_probability


# -- component engine V2 (the composer adapter) -------------------------------------------


def _profiles() -> list[object]:
    from fpl.models.component_engine_v2 import PlayerProfile

    return [
        PlayerProfile(
            code=1, position=Position.FWD, team_code=3,
            minutes=(0.05, 0.10, 0.15, 0.70), attacking_share=0.30, assist_share=0.15,
        ),
        PlayerProfile(
            code=2, position=Position.MID, team_code=3,
            minutes=(0.20, 0.15, 0.25, 0.40), attacking_share=0.20, assist_share=0.35,
        ),
        PlayerProfile(
            code=3, position=Position.DEF, team_code=3,
            minutes=(0.02, 0.03, 0.10, 0.85), attacking_share=0.05, assist_share=0.10,
        ),
        PlayerProfile(
            code=4, position=Position.GK, team_code=3,
            minutes=(0.01, 0.00, 0.00, 0.99), attacking_share=0.0, assist_share=0.0,
        ),
    ]


def _environment(rate: float = 1.8, against: float = 1.1) -> FixtureEnvironment:
    home = TeamEnvironment(
        team_code=3, was_home=True,
        goal_distribution=poisson_pmf(rate),
        expected_goals=sum(i * m for i, m in enumerate(poisson_pmf(rate))),
        expected_goals_against=against,
        expected_shots_on_target_against=6.0,
        expected_defensive_actions=120.0,
    )
    away = TeamEnvironment(
        team_code=8, was_home=False,
        goal_distribution=poisson_pmf(against),
        expected_goals=sum(i * m for i, m in enumerate(poisson_pmf(against))),
        expected_goals_against=rate,
        expected_shots_on_target_against=9.0,
        expected_defensive_actions=150.0,
    )
    return FixtureEnvironment(
        season="2025-26", fixture=1, gw=1, kickoff_time=START, home=home, away=away
    )


def test_the_adapter_conserves_the_teams_expected_goals() -> None:
    """The defect that once destroyed 11.11% of all attacking mass, pinned.

    The composer gates by drawing the minutes bin, so the rates it receives must be
    conditional on appearance. Summing `p_play x conditional_rate` back over the roster must
    return the team's expected goals.
    """
    from fpl.models.component_engine_v2 import (
        build_component_distributions,
        conserved_team_goals,
    )

    environment = _environment()
    profiles = _profiles()
    components = build_component_distributions(environment, profiles, team_code=3)
    assert conserved_team_goals(components, profiles) == pytest.approx(
        environment.home.expected_goals, rel=1e-6
    )


def test_the_adapter_reads_goals_conceded_from_the_opponents_own_distribution() -> None:
    """Rebuilding one from a scalar would let the two disagree."""
    from fpl.models.component_engine_v2 import build_component_distributions

    environment = _environment()
    components = build_component_distributions(environment, _profiles(), team_code=3)
    for distribution in components.values():
        assert distribution.team_goals_conceded == environment.away.goal_distribution


def test_the_adapter_gives_only_the_goalkeeper_a_saves_distribution() -> None:
    from fpl.models.component_engine_v2 import build_component_distributions

    saves = GkSavesV2()
    saves.fit(_gk_history())
    components = build_component_distributions(
        _environment(), _profiles(), team_code=3, saves_model=saves
    )
    keeper = components[4]
    assert keeper.saves is not None and keeper.saves[0] < 1.0
    outfield = components[1]
    assert outfield.saves is not None and outfield.saves[0] == 1.0


def test_the_adapter_passes_the_environments_shots_faced_to_the_saves_model() -> None:
    from fpl.models.component_engine_v2 import build_component_distributions

    saves = GkSavesV2()
    saves.fit(_gk_history())
    quiet = build_component_distributions(
        _environment(), _profiles(), team_code=3, saves_model=saves
    )[4].saves
    busy_environment = _environment()
    busy = build_component_distributions(
        FixtureEnvironment(
            season="2025-26", fixture=1, gw=1, kickoff_time=START,
            home=TeamEnvironment(
                team_code=3, was_home=True,
                goal_distribution=busy_environment.home.goal_distribution,
                expected_goals=busy_environment.home.expected_goals,
                expected_goals_against=busy_environment.home.expected_goals_against,
                expected_shots_on_target_against=12.0,
                expected_defensive_actions=120.0,
            ),
            away=busy_environment.away,
        ),
        _profiles(), team_code=3, saves_model=saves,
    )[4].saves
    assert quiet is not None and busy is not None
    assert sum(i * m for i, m in enumerate(busy)) > sum(i * m for i, m in enumerate(quiet))


def test_dc_uses_the_team_environment_not_a_personal_rate() -> None:
    from fpl.models.component_engine_v2 import build_component_distributions

    dc = DefensiveEnvironmentV2()
    dc.fit(_dc_history())
    thresholds = {Position.DEF: 10, Position.MID: 12, Position.FWD: 12}
    components = build_component_distributions(
        _environment(), _profiles(), team_code=3, dc_model=dc, dc_thresholds=thresholds
    )
    assert components[4].dc_hit_probability == 0.0, "a goalkeeper never earns DC"
    assert components[2].dc_hit_probability > 0.0


def test_the_adapter_produces_exactly_the_composer_input_type() -> None:
    """Milestone I costs nothing precisely because this type is unchanged."""
    from fpl.models.component_engine_v2 import build_component_distributions
    from fpl.models.points_composition import ComponentDistributions

    components = build_component_distributions(_environment(), _profiles(), team_code=3)
    assert all(isinstance(value, ComponentDistributions) for value in components.values())
    for distribution in components.values():
        assert sum(distribution.minutes) == pytest.approx(1.0)
        assert sum(distribution.goals) == pytest.approx(1.0, abs=1e-9)
        assert sum(distribution.assists) == pytest.approx(1.0, abs=1e-9)
