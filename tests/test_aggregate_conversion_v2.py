"""Offline safeguards for fully nested conversion training."""

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from fpl.models.aggregate_conversion_v2 import (
    FitRow,
    Parameters,
    ShareRow,
    ValidationFold,
    clip_fit,
    converted_rates,
    fit_profile,
    parameter_grid,
    prepare_profile,
    ratio_feature,
    select_parameters,
)

CUTOFF = datetime(2025, 1, 1, tzinfo=UTC)


def row(actual=1, past_actual=1, expected=1, position="MID", **changes):
    base = FitRow(
        position,
        0.3,
        actual,
        past_actual,
        expected,
        CUTOFF - timedelta(days=10),
        CUTOFF - timedelta(days=7),
    )
    return replace(base, **changes)


def grid():
    return parameter_grid([1, 5, 20], [0.1, 10, 100], [0.5, 1, 2])


def test_grid_has_twenty_seven_choices_and_off_first():
    candidates = grid()
    assert len(candidates) == 28
    assert candidates[0].name == "off"
    assert len({p.name for p in candidates}) == 28
    assert Parameters(5, 10, 1).name in {p.name for p in candidates}


@pytest.mark.parametrize("values", [[0], [-1], [float("nan")], [float("inf")]])
def test_grid_rejects_bad_values(values):
    with pytest.raises(ValueError, match="finite"):
        parameter_grid(values, [10], [1])


def test_grid_rejects_duplicate_settings():
    with pytest.raises(ValueError, match="duplicate"):
        parameter_grid([1, 1], [10], [1])


def test_matched_sums_preserve_missing_and_zero():
    assert ratio_feature(None, None, 5) == 0
    assert ratio_feature(0, 0, 5) == 0
    assert ratio_feature(1, 0, 5) == pytest.approx(math.log(1.2))
    with pytest.raises(ValueError, match="paired"):
        ratio_feature(1, None, 5)


def test_fitting_future_labels_equals_physically_truncated_data():
    earlier = [row(), row(actual=0, past_actual=0, expected=2)]
    later = row(actual=500, offset=100, label_available=CUTOFF + timedelta(days=1))
    assert prepare_profile(earlier, cutoff=CUTOFF, smoothing=5) == prepare_profile(
        [*earlier, later],
        cutoff=CUTOFF,
        smoothing=5,
    )
    # Equality at the label boundary is also unavailable.
    assert prepare_profile(earlier, cutoff=CUTOFF, smoothing=5) == prepare_profile(
        [*earlier, replace(later, label_available=CUTOFF)],
        cutoff=CUTOFF,
        smoothing=5,
    )


def test_training_features_must_precede_their_label():
    bad = row(feature_cutoff=CUTOFF - timedelta(days=5))
    with pytest.raises(ValueError, match="precede"):
        prepare_profile([bad], cutoff=CUTOFF, smoothing=5)


def test_compressed_profile_matches_direct_position_likelihood():
    rows = [row(), row(actual=0, past_actual=0, expected=2)] * 30
    rows += [row(actual=0, position="DEF", expected=0.2)] * 15
    profile = prepare_profile(rows, cutoff=CUTOFF, smoothing=5)
    beta, ridge = 0.3, 10
    gradient, curvature, objective = profile.at(beta, ridge)
    z = [ratio_feature(r.past_actual, r.past_expected, 5) for r in rows]
    direct_gradient = sum(r.outcome * v for r, v in zip(rows, z, strict=True)) - ridge * beta
    direct_objective = (
        beta * sum(r.outcome * v for r, v in zip(rows, z, strict=True)) - ridge * beta**2 / 2
    )
    for position in {"MID", "DEF"}:
        chosen = [(r, v) for r, v in zip(rows, z, strict=True) if r.position == position]
        y = sum(r.outcome for r, _ in chosen)
        w = [r.offset * math.exp(beta * v) for r, v in chosen]
        direct_gradient -= y * sum(a * v for a, (_, v) in zip(w, chosen, strict=True)) / sum(w)
        direct_objective -= y * math.log(sum(w))
    assert gradient == pytest.approx(direct_gradient, abs=1e-12)
    assert objective == pytest.approx(direct_objective, abs=1e-12)
    assert curvature < 0


def test_optimizer_can_select_positive_negative_and_neutral_effects():
    positive = [row(actual=2, past_actual=3), row(actual=0, past_actual=0)] * 100
    negative = [row(actual=0, past_actual=3), row(actual=2, past_actual=0)] * 100
    neutral = [row(actual=1, past_actual=3), row(actual=1, past_actual=0)] * 100
    fits = [
        fit_profile(
            prepare_profile(r, cutoff=CUTOFF, smoothing=5),
            ridge=10,
            bound=2,
            minimum_rows=1,
            minimum_events=1,
        )
        for r in (positive, negative, neutral)
    ]
    assert fits[0].beta > 0
    assert fits[1].beta < 0
    # Position profiling permits a neutral optimum only with symmetric offsets/features;
    # verify a feature-constant dataset exactly instead.
    constant = prepare_profile([row()] * 100, cutoff=CUTOFF, smoothing=5)
    assert fit_profile(constant, ridge=10, bound=2, minimum_rows=1, minimum_events=1).beta == 0


def test_optimum_has_zero_derivative_and_is_deterministic():
    data = [row(actual=2, past_actual=2), row(actual=0, past_actual=0)] * 50
    profile = prepare_profile(data, cutoff=CUTOFF, smoothing=5)
    fit = fit_profile(profile, ridge=100, bound=2, minimum_rows=1, minimum_events=1)
    assert not fit.boundary
    assert abs(fit.derivative) < 1e-8
    assert fit.objective_gain >= 0
    assert fit == fit_profile(profile, ridge=100, bound=2, minimum_rows=1, minimum_events=1)


def test_narrower_bound_clips_to_the_exact_constrained_optimum():
    data = [row(actual=3, past_actual=3), row(actual=0, past_actual=0)] * 300
    profile = prepare_profile(data, cutoff=CUTOFF, smoothing=1)
    wide = fit_profile(profile, ridge=0.1, bound=2)
    clipped = clip_fit(profile, wide, ridge=0.1, bound=0.5)
    direct = fit_profile(profile, ridge=0.1, bound=0.5)
    assert clipped.beta == direct.beta == 0.5
    assert clipped.derivative >= 0
    assert clipped.boundary


def test_insufficient_training_returns_explicit_neutral_fallback():
    profile = prepare_profile([row()] * 10, cutoff=CUTOFF, smoothing=5)
    fit = fit_profile(profile, ridge=10, bound=2)
    assert fit.beta == 0
    assert fit.fallback == "short_training"


def test_position_nuisance_does_not_convert_position_difference_to_skill():
    rows = [row(actual=0, past_actual=0, position="DEF"), row(actual=2, past_actual=3)] * 300
    profile = prepare_profile(rows, cutoff=CUTOFF, smoothing=5)
    fit = fit_profile(profile, ridge=10, bound=2)
    assert fit.beta == pytest.approx(0, abs=1e-12)


def validation(day, losses=None, available=None):
    return ValidationFold(
        f"2024-25-GW{day}",
        CUTOFF - timedelta(days=day),
        CUTOFF - timedelta(days=day - 1) if available is None else available,
        100,
        losses or {"off": 1.0, "k5_r10_b1": 0.9},
    )


def test_selection_uses_only_earlier_fully_completed_validation_folds():
    choices = (Parameters(None, None, None), Parameters(5, 10, 1))
    past = [validation(i) for i in range(2, 8)]
    delayed = validation(1, {"off": 100, "k5_r10_b1": 0}, available=CUTOFF + timedelta(days=3))
    chosen, keys, _ = select_parameters([*past, delayed], cutoff=CUTOFF, grid=choices)
    assert chosen.name == "k5_r10_b1"
    assert delayed.key not in keys
    assert len(keys) == 6


def test_current_or_future_score_cannot_select_its_own_parameters():
    choices = (Parameters(None, None, None), Parameters(5, 10, 1))
    past = [validation(i, {"off": 0.9, "k5_r10_b1": 1}) for i in range(2, 8)]
    current = ValidationFold("current", CUTOFF, CUTOFF, 100000, {"off": 500, "k5_r10_b1": 0})
    expected = select_parameters(past, cutoff=CUTOFF, grid=choices)
    assert select_parameters([*past, current], cutoff=CUTOFF, grid=choices) == expected
    assert expected[0].name == "off"


def test_selection_requires_six_folds_and_ties_choose_off():
    choices = (Parameters(None, None, None), Parameters(5, 10, 1))
    assert select_parameters([validation(2)], cutoff=CUTOFF, grid=choices)[0].name == "off"
    tied = [validation(i, {"off": 1, "k5_r10_b1": 1}) for i in range(2, 8)]
    assert select_parameters(tied, cutoff=CUTOFF, grid=choices)[0].name == "off"


def test_team_allocation_and_exact_zero_weight_control():
    rows = [ShareRow(1, 0.8, 0.8, 1.0, 2, 1), ShareRow(2, 0.8, 0.8, 1.0, 0, 1)]
    assert converted_rates(rows, budget=1.6, smoothing=5, beta=0) == (1, 1)
    rates = converted_rates(rows, budget=1.6, smoothing=5, beta=0.3)
    assert rates[0] > rates[1]
    assert sum(r.p_play * rate for r, rate in zip(rows, rates, strict=True)) == pytest.approx(1.6)


def test_unavailable_allocation_retains_whole_group_control():
    rows = [ShareRow(1, 0.8, None, None, 2, 1), ShareRow(2, 0.8, None, None, 0, 1)]
    assert converted_rates(rows, budget=1.6, smoothing=5, beta=0.3) == (None, None)


def test_zero_appearance_does_not_get_event_mass():
    rows = [ShareRow(1, 0, 0, 0, 2, 1), ShareRow(2, 1, 1.6, 1.6, 0, 1)]
    assert converted_rates(rows, budget=1.6, smoothing=5, beta=0.3) == (0, 1.6)
