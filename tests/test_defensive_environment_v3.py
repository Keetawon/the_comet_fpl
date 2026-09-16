"""Synthetic-only hand calculations; no archive forecasting or model evaluation."""

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from fpl.models.attacking_baselines import poisson_pmf
from fpl.models.defensive_environment_v3 import (
    EVIDENCE_CLASS,
    DcMeanPrediction,
    DcOosObservation,
    DcPlayerObservation,
    DcTarget,
    DcTeamObservation,
    DispersionEstimate,
    PredictedDefensiveEnvironment,
    fit_dispersion,
    gamma_poisson_pmf,
    predict_threshold,
)
from fpl.types import Position

NOW = datetime(2025, 9, 12, tzinfo=UTC)
PAST = NOW - timedelta(days=7)


def player(**changes):
    return replace(
        DcPlayerObservation("2025-26", 2, 1, PAST, 100, 10, Position.DEF, 45, 5), **changes
    )


def team(**changes):
    return replace(DcTeamObservation("2025-26", 2, 1, PAST, 10, 100), **changes)


def target(**changes):
    return replace(DcTarget("2025-26", 3, 2, NOW, 100, 10, Position.DEF, (0, 0, 0, 1)), **changes)


def fitted(players=None, teams=None):
    return PredictedDefensiveEnvironment().fit(
        [player()] if players is None else players,
        [team()] if teams is None else teams,
        as_of=NOW,
        excluded_target_gw=("2025-26", 3),
    )


def dispersion(alpha=0):
    return DispersionEstimate(alpha, 0, 0, 0, 0, None, False, NOW, ("2025-26", 3))


def test_hand_calculation_exposure_normalised_intensity_is_not_thinned_twice():
    prediction = fitted().predict_mean(target())
    assert prediction.team_environment == 100
    assert prediction.intensity_ratio == 0.1  # 5/(100*.5), pooled toward same position ratio
    assert prediction.full_match_mean == 10
    assert prediction.means_by_minutes_bin == (0, 5, 10 * 89 / 90, 10)
    assert prediction.evidence_class == EVIDENCE_CLASS


def test_team_environment_uses_last_five_and_shrinks_to_prior_only_league():
    teams = [
        team(fixture=i + 1, kickoff=PAST - timedelta(days=7 * (5 - i)), defensive_actions=v)
        for i, v in enumerate((1000, 10, 20, 30, 40, 50))
    ]
    prediction = fitted(players=[], teams=teams).predict_mean(target())
    assert prediction.team_history_matches == 5
    assert prediction.team_environment == (150 + 5 * (1150 / 6)) / 10
    assert prediction.intensity_ratio is None
    assert prediction.full_match_mean is None


def test_opportunity_pooling_and_position_prior_are_fold_local():
    players = [
        player(),
        player(fixture=5, code=200, team_code=20, minutes=90, defensive_contribution=20),
    ]
    teams = [team(), team(fixture=5, team_code=20, defensive_actions=200)]
    model = fitted(players, teams)
    prediction = model.predict_mean(target())
    assert prediction.team_environment == (100 + 5 * 150) / 6
    assert model.position_ratios[Position.DEF] == 25 / 250
    assert prediction.intensity_ratio == (5 + 750 * 0.1) / (50 + 750)


def test_player_last_five_cap_uses_event_order_not_input_order():
    players = [
        player(
            fixture=i + 1,
            kickoff=PAST - timedelta(days=7 * (5 - i)),
            minutes=90,
            defensive_contribution=v,
        )
        for i, v in enumerate((80, 1, 2, 3, 4, 5))
    ]
    teams = [team(fixture=p.fixture, kickoff=p.kickoff) for p in players]
    first = fitted(players, teams).predict_mean(target())
    second = fitted(list(reversed(players)), list(reversed(teams))).predict_mean(target())
    assert first == second
    assert first.player_history_appearances == 5
    assert first.intensity_ratio == (15 + 500 * (95 / 600)) / (500 + 500)


def test_future_same_gw_dgw_postponed_and_six_hour_truncation_equivalence():
    before = fitted().predict_mean(target())
    unavailable = [
        player(fixture=10, gw=3, kickoff=NOW - timedelta(days=2), defensive_contribution=80),
        player(fixture=11, gw=3, kickoff=NOW + timedelta(days=1), defensive_contribution=80),
        player(fixture=12, gw=1, kickoff=NOW + timedelta(days=2), defensive_contribution=80),
        player(fixture=13, gw=1, kickoff=NOW - timedelta(hours=6), defensive_contribution=80),
    ]
    future_teams = [team(fixture=p.fixture, gw=p.gw, kickoff=p.kickoff) for p in unavailable]
    extended = fitted([player(), *unavailable], [team(), *future_teams]).predict_mean(target())
    assert extended == before  # includes exact historical-source SHA equivalence


def test_prior_measured_zero_and_missing_are_not_equivalent():
    missing = fitted([player(defensive_contribution=None)]).predict_mean(target())
    zero = fitted([player(defensive_contribution=0)]).predict_mean(target())
    assert missing.means_by_minutes_bin is None
    assert zero.means_by_minutes_bin == (0, 0, 0, 0)
    result = predict_threshold(zero, dispersion(0.5), 10, 0.2)
    assert result.conditional_count_pmf == (1,) + (0,) * 60
    assert result.conditional_hit_probability == 0


def test_promoted_or_new_club_uses_prior_league_environment_and_position_ratio():
    predicted = fitted().predict_mean(target(code=999, team_code=99))
    assert predicted.team_environment == 100
    assert predicted.team_history_matches == 0
    assert predicted.player_history_appearances == 0
    assert predicted.intensity_ratio == 0.1
    assert predicted.past_witnessed_transfer is False


def test_transfer_persists_after_current_club_witness_and_never_uses_future_stints():
    old = player(team_code=20, minutes=0, defensive_contribution=0)
    current = player(fixture=5, kickoff=PAST + timedelta(days=1))
    model = fitted([old, current], [team(fixture=5, kickoff=current.kickoff)])
    predicted = model.predict_mean(target())
    assert predicted.past_witnessed_transfer is True
    assert predicted.intensity_ratio == 0.1
    future = player(team_code=20, kickoff=NOW + timedelta(days=1))
    assert fitted([player(), future]).predict_mean(target()).past_witnessed_transfer is False
    previous_season = replace(old, season="2024-25")
    assert (
        fitted([previous_season, player()]).predict_mean(target()).past_witnessed_transfer is False
    )


def test_changed_target_actual_minutes_or_dc_are_unrepresentable_in_target():
    assert "minutes" not in DcTarget.__dataclass_fields__
    assert "defensive_contribution" not in DcTarget.__dataclass_fields__
    assert "team_defensive_actions" not in DcTarget.__dataclass_fields__


def test_team_crosswalk_or_complete_opportunity_contradiction_fails():
    with pytest.raises(ValueError, match="metadata contradict"):
        fitted(teams=[team(kickoff=PAST - timedelta(hours=1))])
    with pytest.raises(ValueError, match="exceeds"):
        fitted([player(defensive_contribution=101)])
    with pytest.raises(ValueError, match="duplicate"):
        fitted(teams=[team(), team()])
    with pytest.raises(ValueError, match="duplicate"):
        fitted(players=[player(), player()])


@pytest.mark.parametrize("mean", [0, 0.01, 2, 10, 50, 1000])
def test_alpha_zero_is_bit_exact_existing_poisson_and_zero_mean_exact(mean):
    assert gamma_poisson_pmf(mean, 0) == poisson_pmf(mean, max_goals=60)
    assert gamma_poisson_pmf(0, 2) == (1,) + (0,) * 60


def test_gamma_poisson_hand_computable_geometric_and_integer_shape():
    assert gamma_poisson_pmf(1, 1, 3) == pytest.approx((0.5, 0.25, 0.125, 0.125), abs=1e-15)
    assert gamma_poisson_pmf(2, 0.5, 3) == pytest.approx((0.25, 0.25, 0.1875, 0.3125), abs=1e-15)


@pytest.mark.parametrize("alpha", [1e-12, 0.1, 1, 1000, 1e100])
def test_wide_and_poisson_limit_distributions_remain_proper(alpha):
    pmf = gamma_poisson_pmf(8, alpha)
    assert math.fsum(pmf) == pytest.approx(1, abs=1e-15)
    assert all(math.isfinite(p) and p >= 0 for p in pmf)
    if alpha == 1e-12:
        assert pmf == pytest.approx(poisson_pmf(8, max_goals=60), abs=1e-11)
    if alpha == 1e100:
        assert pmf[-1] > 0  # do not lose tiny nonzero overflow to 1-CDF cancellation


@pytest.mark.parametrize(
    ("mean", "alpha"), [(math.inf, 1), (-1, 0), (1, math.nan), (1, -1), (True, 0), (1e308, 1e308)]
)
def test_invalid_or_nonrepresentable_count_parameters_fail_closed(mean, alpha):
    with pytest.raises(ValueError, match=r"finite|overflow"):
        gamma_poisson_pmf(mean, alpha)


def _oos(i, observed=5):
    past = NOW - timedelta(days=14)
    t = target(fixture=100 + i, gw=1, kickoff=past, minutes_pmf=(0, 0.5, 0, 0.5))
    prediction = DcMeanPrediction(
        t,
        past,
        past - timedelta(days=7),
        "a" * 64,
        100,
        0.04,
        4,
        (0, 0, 3, 4),
        (0, 0, 67.5, 90),
        1,
        1,
        False,
    )
    return DcOosObservation(prediction, observed, 90)


def test_dispersion_hand_computation_subtracts_predicted_minutes_mixture_variance():
    # Predicted bins mean0 or4 equally => mean2, bin variance4, E(mu²)=8.
    # Observed5 gives excess (5-2)²-2-4=3, raw alpha3/8, shrink200/300.
    estimate = fit_dispersion(
        [_oos(i) for i in range(200)], as_of=NOW, excluded_target_gw=("2025-26", 3)
    )
    assert estimate.rows == 200
    assert estimate.residual_excess_sum == 600
    assert estimate.conditional_squared_mean_sum == 1600
    assert estimate.alpha == 0.25
    assert estimate.shrinkage == 2 / 3


def test_dispersion_minimum_oos_rows_null_zero_and_underdispersion():
    short = fit_dispersion(
        [_oos(i) for i in range(199)], as_of=NOW, excluded_target_gw=("2025-26", 3)
    )
    assert short.alpha == 0
    assert not short.used_dispersion
    low = fit_dispersion(
        [_oos(i, observed=2) for i in range(200)], as_of=NOW, excluded_target_gw=("2025-26", 3)
    )
    assert low.alpha == 0
    assert low.used_dispersion
    missing = replace(_oos(300), observed_count=None)
    absent = replace(_oos(301), observed_minutes=0)
    assert fit_dispersion([missing, absent], as_of=NOW, excluded_target_gw=("2025-26", 3)).rows == 0
    zero = replace(_oos(302), observed_count=0)
    assert fit_dispersion([zero], as_of=NOW, excluded_target_gw=("2025-26", 3)).rows == 1


def test_oos_dispersion_never_uses_future_or_current_gw_target_counts():
    prior = [_oos(i) for i in range(200)]
    same = replace(
        _oos(999),
        prediction=replace(_oos(999).prediction, target=replace(_oos(999).prediction.target, gw=3)),
        observed_count=1000,
    )
    future = replace(
        _oos(998),
        prediction=replace(
            _oos(998).prediction,
            target=replace(_oos(998).prediction.target, kickoff=NOW + timedelta(days=1)),
        ),
        observed_count=1000,
    )
    expected = fit_dispersion(prior, as_of=NOW, excluded_target_gw=("2025-26", 3))
    assert (
        fit_dispersion([*prior, same, future], as_of=NOW, excluded_target_gw=("2025-26", 3))
        == expected
    )
    assert (
        fit_dispersion(list(reversed(prior)), as_of=NOW, excluded_target_gw=("2025-26", 3))
        == expected
    )


def test_invalid_oos_source_and_later_fitted_dispersion_cannot_reach_earlier_prediction():
    observation = _oos(1)
    with pytest.raises(ValueError, match="source event reaches"):
        replace(observation.prediction, maximum_source_kickoff=observation.prediction.as_of)
    with pytest.raises(ValueError, match="duplicate"):
        fit_dispersion([observation, observation], as_of=NOW, excluded_target_gw=("2025-26", 3))
    future = replace(dispersion(), as_of=NOW + timedelta(days=7))
    with pytest.raises(ValueError, match="same pre-GW"):
        predict_threshold(fitted().predict_mean(target()), future, 10, 0.1)


def test_conditional_and_unconditional_counts_apply_predicted_minutes_once():
    prediction = fitted().predict_mean(target(minutes_pmf=(0.5, 0, 0, 0.5)))
    forecast = predict_threshold(prediction, dispersion(0.5), 10, 0.1)
    assert forecast.conditional_count_pmf == gamma_poisson_pmf(10, 0.5)
    assert forecast.marginal_hit_probability == 0.5 * forecast.conditional_hit_probability
    assert forecast.marginal_count_pmf[0] == 0.5 + 0.5 * forecast.conditional_count_pmf[0]
    assert math.fsum(forecast.marginal_count_pmf) == pytest.approx(1)


def test_no_history_or_zero_predicted_appearance_keeps_incumbent_fallback_without_deleting_rows():
    unavailable = fitted(players=[], teams=[]).predict_mean(target())
    result = predict_threshold(unavailable, dispersion(0.5), 10, 0.123)
    assert result.conditional_hit_probability == 0.123
    assert result.marginal_hit_probability == 0.123
    assert result.conditional_count_pmf is None
    assert result.fallback == "unavailable_prior_opportunity"
    absent = fitted().predict_mean(target(minutes_pmf=(1, 0, 0, 0)))
    result = predict_threshold(absent, dispersion(0.5), 10, 0.123)
    assert result.conditional_hit_probability == 0.123
    assert result.marginal_hit_probability == 0
    assert result.fallback == "no_predicted_appearance"


def test_failed_refit_cannot_expose_stale_state_and_wrong_target_gw_fails():
    model = fitted()
    with pytest.raises(ValueError, match="duplicate"):
        model.fit([player(), player()], [team()], as_of=NOW, excluded_target_gw=("2025-26", 3))
    with pytest.raises(ValueError, match="fit a prior-only"):
        model.predict_mean(target())
    with pytest.raises(ValueError, match="whole target GW"):
        fitted().predict_mean(target(gw=5))


@pytest.mark.parametrize("bad", [True, -1, 1.2])
def test_labels_are_not_coerced_to_integer_or_missing_to_zero(bad):
    with pytest.raises(ValueError, match="nullable nonnegative integer"):
        player(defensive_contribution=bad)
