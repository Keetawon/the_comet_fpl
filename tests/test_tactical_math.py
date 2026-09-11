"""Hand-computable, offline numerical checks; no historical fitting or scoring."""

from __future__ import annotations

import math
from dataclasses import asdict

import pytest

from fpl.validate.metrics import poisson_pmf
from fpl.validate.tactical_math import adjusted_pmf, fit_poisson_offset, fit_ridge, fit_scaler


def test_scaler_hand_calculation_and_constant_column() -> None:
    scaler = fit_scaler([[0.0, 7.0], [2.0, 7.0]])
    assert scaler.means == (1.0, 7.0)
    assert scaler.scales == (1.0, 1.0)
    assert scaler.transform([0.0, 7.0]) == (-1.0, 0.0)


def test_prediction_does_not_refit_scaler_from_future_values() -> None:
    scaler = fit_scaler([[0.0], [2.0]])
    before = asdict(scaler)
    assert scaler.transform([100.0]) == (99.0,)
    assert asdict(scaler) == before


def test_ridge_hand_computable_penalised_intercept_and_slope() -> None:
    # X'X/n = identity, X'y/n = (2, 1): penalty 1 halves both.
    model = fit_ridge([[-1.0], [1.0]], [[1.0, 2.0], [3.0, 6.0]], 1.0)
    assert model.coefficients[0] == pytest.approx((1.0, 0.5))
    assert model.coefficients[1] == pytest.approx((2.0, 1.0))
    assert model.predict([-1.0]) == pytest.approx((0.5, 1.0))
    assert model.predict([1.0]) == pytest.approx((1.5, 3.0))
    assert model.training_rows == 2


def test_ridge_constant_predictor_is_not_a_second_intercept() -> None:
    model = fit_ridge([[7.0], [7.0]], [[2.0], [2.0]], 1.0)
    assert model.coefficients[0] == pytest.approx((1.0, 0.0))
    assert model.predict([7.0]) == pytest.approx((1.0,))


def test_ridge_supports_intercept_only() -> None:
    assert fit_ridge([[], []], [[2.0], [2.0]], 1.0).predict([]) == pytest.approx((1.0,))


def test_ridge_duplicate_rows_preserve_mean_objective() -> None:
    x, y = [[-1.0], [1.0]], [[1.0], [3.0]]
    assert fit_ridge(x, y, 1.0).coefficients == fit_ridge(x * 2, y * 2, 1.0).coefficients


def test_poisson_intercept_hand_solution() -> None:
    # offset=e^-1, goals=2, penalty=1: derivative exp(-1+b)-2+b=0 at b=1.
    model = fit_poisson_offset([[], []], [2, 2], [math.exp(-1)] * 2, 1.0)
    assert model.coefficients == pytest.approx((1.0,), abs=1e-9)
    assert model.converged
    assert model.iterations <= 40
    assert model.raw_correction([]) == pytest.approx(1.0)
    assert model.correction([]) == 0.5


def test_poisson_zero_adjustment_optimum_preserves_offset() -> None:
    model = fit_poisson_offset([[-1.0], [1.0]], [1, 2], [1.0, 2.0], 0.1)
    assert model.coefficients == (0.0, 0.0)
    assert model.correction([9.0]) == 0.0
    assert model.converged


def test_poisson_uses_no_full_population_normalisation() -> None:
    model = fit_poisson_offset([[0.0], [2.0]], [1, 2], [1.0, 2.0], 1.0)
    assert model.scaler.means == (1.0,)
    assert model.scaler.scales == (1.0,)
    model.correction([1e6])
    assert model.scaler.means == (1.0,)


def test_poisson_constant_predictor_and_repeat_determinism() -> None:
    args = ([[3.0], [3.0], [3.0]], [0, 2, 4], [1.0, 1.0, 1.0], 1.0)
    first = fit_poisson_offset(*args)
    second = fit_poisson_offset(*args)
    assert first == second
    assert first.coefficients[1] == 0.0
    assert first.converged
    assert math.isfinite(first.objective)


def test_poisson_training_correction_is_not_prediction_clipped() -> None:
    model = fit_poisson_offset([[], []], [20, 20], [1.0, 1.0], 0.1)
    assert model.raw_correction([]) > 0.5
    assert model.correction([]) == 0.5
    assert model.converged


def test_zero_correction_returns_exact_incumbent_tuple() -> None:
    rate = 4.5  # folded tail makes mean differ from generating lambda.
    original = poisson_pmf(rate)
    assert sum(i * mass for i, mass in enumerate(original)) != rate
    assert adjusted_pmf(rate, original, 0.0) is original


def test_nonzero_correction_preserves_family_floor_and_mass() -> None:
    pmf = adjusted_pmf(0.05, poisson_pmf(0.05), -0.5)
    assert pmf == poisson_pmf(0.05)
    assert len(pmf) == 11
    assert sum(pmf) == pytest.approx(1.0)
    assert adjusted_pmf(2.0, poisson_pmf(2.0), 99.0) == poisson_pmf(2 * math.exp(0.5))


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_predictors_and_targets_are_rejected(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        fit_scaler([[value]])
    with pytest.raises(ValueError, match="finite"):
        fit_ridge([[0.0]], [[value]], 1.0)
    with pytest.raises(ValueError, match="finite"):
        fit_poisson_offset([[0.0]], [1], [value], 1.0)
    with pytest.raises(ValueError, match="finite"):
        fit_scaler([[0.0]]).transform([value])


@pytest.mark.parametrize("penalty", [0.0, -1.0, math.nan, math.inf])
def test_nonpositive_or_nonfinite_penalties_rejected(penalty: float) -> None:
    with pytest.raises(ValueError, match="penalty"):
        fit_ridge([[0.0]], [[1.0]], penalty)
    with pytest.raises(ValueError, match="penalty"):
        fit_poisson_offset([[0.0]], [1], [1.0], penalty)


def test_bad_shapes_empty_data_and_targets_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        fit_scaler([])
    with pytest.raises(ValueError, match="width"):
        fit_scaler([[0.0], [0.0, 1.0]])
    with pytest.raises(ValueError, match="width"):
        fit_scaler([[0.0]]).transform([])
    with pytest.raises(ValueError, match="row count"):
        fit_ridge([[0.0]], [[1.0], [2.0]], 1.0)
    with pytest.raises(ValueError, match="nonzero width"):
        fit_ridge([[]], [[]], 1.0)
    with pytest.raises(ValueError, match="row count"):
        fit_poisson_offset([[0.0]], [1, 2], [1.0], 1.0)


@pytest.mark.parametrize("goal", [-1, True, 1.2])
def test_poisson_invalid_goal_rejected(goal: int) -> None:
    with pytest.raises(ValueError, match="nonnegative integers"):
        fit_poisson_offset([[]], [goal], [1.0], 1.0)


@pytest.mark.parametrize("offset", [0.0, -1.0, math.exp(21), math.exp(-21)])
def test_poisson_invalid_offset_rejected(offset: float) -> None:
    with pytest.raises(ValueError, match="offset"):
        fit_poisson_offset([[]], [1], [offset], 1.0)


def test_invalid_incumbent_distribution_rejected() -> None:
    with pytest.raises(ValueError, match=r"0\.\.10"):
        adjusted_pmf(1.0, (1.0,), 0.0)
    with pytest.raises(ValueError, match="sum to one"):
        adjusted_pmf(1.0, (0.0,) * 11, 0.0)
