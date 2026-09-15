"""Synthetic numerical amendment tests; never fit or score historical matches."""

from __future__ import annotations

import json
import math
import sys
from dataclasses import asdict
from decimal import Decimal, localcontext

import pytest

from fpl.validate import tactical_numeric_solver as solver
from fpl.validate.metrics import poisson_pmf
from fpl.validate.tactical_math import PoissonOffsetModel, adjusted_pmf, fit_poisson_offset


def _objective(
    beta: tuple[float, ...],
    x: list[list[float]],
    goals: list[int],
    offsets: list[float],
    penalty: float,
) -> float:
    # Independent objective for already-standardized design rows including intercept.
    levels = [
        math.log(offset) + math.fsum(a * b for a, b in zip(row, beta, strict=True))
        for row, offset in zip(x, offsets, strict=True)
    ]
    return (
        math.fsum(math.exp(level) - goal * level for level, goal in zip(levels, goals, strict=True))
        / len(x)
        + penalty * math.fsum(value * value for value in beta) / 2
    )


def test_intercept_optimum_hand_calculation_and_unchanged_prediction_semantics() -> None:
    # exp(-1+beta)-2+beta = 0 at beta=1, curvature=2.
    fit = solver.fit_poisson_offset_stable([[], []], [2, 2], [math.exp(-1)] * 2, 1.0)
    assert isinstance(fit, PoissonOffsetModel)
    assert fit.coefficients == pytest.approx((1.0,), abs=1e-9)
    assert fit.raw_correction([]) == pytest.approx(1.0, abs=1e-9)
    assert fit.correction([]) == 0.5
    assert fit.objective == pytest.approx(1.5)
    assert fit.converged
    assert fit.solver == solver.SOLVER_ID
    assert 0 < fit.iterations <= 40
    json.dumps(asdict(fit), allow_nan=False)


def test_exact_zero_optimum_uses_incumbent_pmf_unchanged() -> None:
    fit = solver.fit_poisson_offset_stable([[-1.0], [1.0]], [1, 2], [1.0, 2.0], 0.1)
    assert fit.coefficients == (0.0, 0.0)
    assert fit.final_gradient == (0.0, 0.0)
    assert fit.final_newton_step == (0.0, 0.0)
    original = poisson_pmf(2.0)
    assert adjusted_pmf(2.0, original, fit.correction([999.0])) is original


def test_constant_predictors_and_repeat_rows_are_deterministic() -> None:
    args = ([[3.0], [3.0], [3.0]], [0, 2, 4], [1.0, 1.0, 1.0], 1.0)
    first = solver.fit_poisson_offset_stable(*args)
    assert first == solver.fit_poisson_offset_stable(*args)
    assert first.coefficients[1] == 0.0
    repeated = solver.fit_poisson_offset_stable(args[0] * 2, args[1] * 2, args[2] * 2, 1.0)
    assert first.coefficients == repeated.coefficients
    assert first.objective == repeated.objective


def test_final_gradient_matches_independent_finite_difference() -> None:
    x = [[-1.0, -1.0], [-1.0, 1.0], [1.0, -1.0], [1.0, 1.0]]
    goals, offsets, penalty = [0, 2, 3, 1], [0.5, 1.2, 1.0, 2.0], 0.1
    fit = solver.fit_poisson_offset_stable(x, goals, offsets, penalty)
    design = [[1.0, *row] for row in x]
    assert fit.scaler.means == (0.0, 0.0)
    assert fit.scaler.scales == (1.0, 1.0)
    for j in range(3):
        plus, minus = list(fit.coefficients), list(fit.coefficients)
        plus[j] += 1e-5
        minus[j] -= 1e-5
        difference = (
            _objective(tuple(plus), design, goals, offsets, penalty)
            - _objective(tuple(minus), design, goals, offsets, penalty)
        ) / 2e-5
        assert difference == pytest.approx(fit.final_gradient[j], abs=1e-9)
        assert _objective(tuple(plus), design, goals, offsets, penalty) > fit.objective
        assert _objective(tuple(minus), design, goals, offsets, penalty) > fit.objective
    final = fit.diagnostics[-1]
    assert final.gradient_infinity_norm <= final.gradient_tolerance
    assert final.newton_step_infinity_norm <= final.step_tolerance
    assert final.accepted_fraction is None


def test_ordinary_fit_matches_legacy_optimum_without_mutating_legacy() -> None:
    args = ([[-1.0], [1.0]], [0, 3], [1.2, 1.0], 1.0)
    old = fit_poisson_offset(*args)
    new = solver.fit_poisson_offset_stable(*args)
    assert new.scaler == old.scaler
    assert new.penalty == old.penalty
    assert new.coefficients == pytest.approx(old.coefficients, abs=1e-8)
    assert new.objective == pytest.approx(old.objective, abs=1e-14)
    assert fit_poisson_offset(*args) == old


def test_synthetic_legacy_small_damped_step_is_not_final_gradient_convergence() -> None:
    # Fixed synthetic intercept-only counterexample, not a historical failure
    # reconstruction: V1 reports convergence while its final gradient is >6e-9.
    # Its whole-objective comparison loses the near-optimal decrease; the stable
    # successor takes a full corrective step and meets its stated tolerance.
    goals = [1, 0, 4, 2, 3, 2, 2, 4, 3, 4, 4, 4, 0, 0, 1]
    offsets = [
        2.3575107973383975,
        1.5674532414324331,
        1.739386361943396,
        2.584928668316833,
        2.0438073022802827,
        0.25103218196676214,
        2.685586873813428,
        2.099943092826725,
        1.0665524841196992,
        0.23667774290094484,
        0.374196051231681,
        2.7350054990048736,
        0.43667164536940234,
        2.7528643961890125,
        1.0036869409146065,
    ]
    old = fit_poisson_offset([[]] * len(goals), goals, offsets, 1.0)
    legacy_gradient = (
        math.fsum(
            math.exp(math.log(offset) + old.coefficients[0]) - goal
            for offset, goal in zip(offsets, goals, strict=True)
        )
        / len(goals)
        + old.coefficients[0]
    )
    assert old.converged
    assert abs(legacy_gradient) > 5e-9
    new = solver.fit_poisson_offset_stable([[]] * len(goals), goals, offsets, 1.0)
    assert abs(new.final_gradient[0]) < 1e-12
    assert new.converged


@pytest.mark.parametrize("value", [-0.001, -1e-8, -1e-12, 0.0, 1e-12, 1e-8, 0.001])
def test_small_exponential_remainder_matches_high_precision(value: float) -> None:
    with localcontext() as context:
        context.prec = 80
        exact_value = Decimal.from_float(value)
        expected = float(exact_value.exp() - 1 - exact_value)
    assert solver._expm1_remainder(value) == pytest.approx(expected, rel=5e-16, abs=1e-90)


def test_stable_difference_resolves_decrease_lost_by_whole_objective_subtraction() -> None:
    rate, goal, penalty = 1.0 + 1e-8, 1, 1.0
    gradient = rate - goal
    delta = -gradient / (rate + penalty)
    stable = solver._objective_difference([[1.0]], [rate], [gradient], [delta], penalty)
    with localcontext() as context:
        context.prec = 80
        mu, g, change = map(Decimal.from_float, (rate, gradient, delta))
        expected = float(g * change + mu * (change.exp() - 1 - change) + change * change / 2)
    assert stable < -2e-17
    assert stable == pytest.approx(expected, rel=5e-16)
    full_difference = _objective((delta,), [[1.0]], [goal], [rate], penalty) - _objective(
        (0.0,), [[1.0]], [goal], [rate], penalty
    )
    assert abs(full_difference - stable) > abs(stable) / 2


def test_objective_difference_matches_direct_evaluation_away_from_roundoff() -> None:
    # beta=0, X=(1,-1)/(1,1), rates=(1,2), goals=(0,3).
    design, rates, gradient, delta = [[1.0, -1.0], [1.0, 1.0]], [1.0, 2.0], [0.0, -1.0], [0.1, 0.2]
    stable = solver._objective_difference(design, rates, gradient, delta, 0.1)
    direct = _objective(tuple(delta), design, [0, 3], rates, 0.1) - _objective(
        (0.0, 0.0), design, [0, 3], rates, 0.1
    )
    assert stable == pytest.approx(direct, abs=1e-15)


def test_every_accepted_step_has_strict_decrease_and_final_both_tolerances() -> None:
    fit = solver.fit_poisson_offset_stable([[], []], [20, 20], [1.0, 1.0], 0.1)
    assert fit.raw_correction([]) > 0.5  # No training correction clipping.
    assert fit.correction([]) == 0.5
    for entry in fit.diagnostics[:-1]:
        assert entry.objective_difference is not None
        assert entry.armijo_bound is not None
        assert entry.objective_difference <= entry.armijo_bound < 0
        assert entry.accepted_fraction is not None
        assert 0 < entry.accepted_fraction <= 1
        assert entry.backtracking_trials <= 30
        assert -20 <= entry.eta_minimum <= entry.eta_maximum <= 20
    final = fit.diagnostics[-1]
    assert final.gradient_infinity_norm <= final.gradient_tolerance
    assert final.newton_step_infinity_norm <= final.step_tolerance


def test_roundoff_allowance_has_preregistered_hand_computable_scale() -> None:
    fit = solver.fit_poisson_offset_stable([[]], [1], [1.0], 1.0)
    diagnostic = fit.diagnostics[0]
    assert diagnostic.gradient_roundoff_allowance == 64 * sys.float_info.epsilon * 2
    assert diagnostic.gradient_tolerance == 1e-9 + diagnostic.gradient_roundoff_allowance
    assert diagnostic.step_tolerance == 1e-9


def test_prediction_cannot_change_fold_local_scaling_or_fit() -> None:
    fit = solver.fit_poisson_offset_stable([[0.0], [2.0]], [0, 3], [1.0, 1.0], 0.1)
    before = asdict(fit)
    fit.correction([1e9])
    assert asdict(fit) == before
    assert fit.scaler.means == (1.0,)
    assert fit.scaler.scales == (1.0,)


def test_bounded_iteration_failure_retains_final_numerical_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(solver, "MAX_ITERATIONS", 0)
    with pytest.raises(solver.PoissonSolverError, match="iteration limit") as caught:
        solver.fit_poisson_offset_stable([[]], [3], [1.0], 0.1)
    state = caught.value.state
    assert state["penalty"] == 0.1
    assert state["iteration"] == 0
    assert state["gradient_infinity_norm"] == 2
    assert state["newton_decrement_squared"] > 0
    assert state["coefficients"] == (0.0,)
    json.dumps(state, allow_nan=False)


def test_bounded_backtracking_failure_retains_every_attempt_and_never_falls_back() -> None:
    # At the lower eta bound, any decrease needed by the true unconstrained
    # optimum would be unsafe. Do not clip the training likelihood and continue.
    with pytest.raises(solver.PoissonSolverError, match="backtracking") as caught:
        solver.fit_poisson_offset_stable([[]], [0], [math.exp(-20)], 0.1)
    state = caught.value.state
    assert len(state["backtracking"]) == 30
    assert all(not trial["safe_eta"] for trial in state["backtracking"])
    assert state["gradient_infinity_norm"] > state["gradient_tolerance"]
    json.dumps(state, allow_nan=False)


@pytest.mark.parametrize("penalty", [0.0, -1.0, math.inf, math.nan])
def test_invalid_penalty_fails_closed(penalty: float) -> None:
    with pytest.raises(ValueError, match="penalty"):
        solver.fit_poisson_offset_stable([[]], [1], [1.0], penalty)


@pytest.mark.parametrize("goal", [-1, True, 1.5])
def test_invalid_goal_fails_closed(goal: int) -> None:
    with pytest.raises(ValueError, match="nonnegative integers"):
        solver.fit_poisson_offset_stable([[]], [goal], [1.0], 1.0)


@pytest.mark.parametrize("offset", [0.0, -1.0, math.nan, math.inf, math.exp(21), math.exp(-21)])
def test_invalid_offsets_fail_closed(offset: float) -> None:
    with pytest.raises(ValueError, match=r"offset|finite"):
        solver.fit_poisson_offset_stable([[]], [1], [offset], 1.0)


@pytest.mark.parametrize("x", [[], [[0.0], [1.0, 2.0]], [[math.nan]], [[math.inf]]])
def test_invalid_predictors_fail_closed(x: list[list[float]]) -> None:
    with pytest.raises(ValueError, match=r"empty|width|finite"):
        solver.fit_poisson_offset_stable(x, [1] * len(x), [1.0] * len(x), 1.0)


def test_mismatched_target_lengths_fail_closed() -> None:
    with pytest.raises(ValueError, match="row count"):
        solver.fit_poisson_offset_stable([[]], [1, 2], [1.0], 1.0)


def test_fixed_numerical_limits_are_not_model_selection_options() -> None:
    assert solver.MAX_ITERATIONS == 40
    assert solver.MAX_BACKTRACKS == 30
    assert solver.ARMIJO == 1e-4
    assert solver.TOLERANCE == 1e-9
    assert solver.ROUNDOFF_MULTIPLIER == 64
    assert solver.SMALL_INCREMENT == 1e-3
