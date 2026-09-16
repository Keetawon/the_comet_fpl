"""Numerical-only Poisson offset amendment; the frozen tactical solver is unchanged.

The objective, zero start, scaling, penalty and prediction methods are inherited
from Tactical V1. Only convergence checks and objective-difference arithmetic
change. This module has no data access or production caller.
"""

from __future__ import annotations

import math
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from typing import Any

from fpl.validate.tactical_math import (
    PoissonOffsetModel,
    _cholesky_solve,
    _design,
    _dot,
    _finite,
    _penalty,
    fit_scaler,
)

SOLVER_ID = "poisson_offset_stable_difference_v1"
MAX_ITERATIONS = 40
MAX_BACKTRACKS = 30
ARMIJO = 1e-4
TOLERANCE = 1e-9
ROUNDOFF_MULTIPLIER = 64
SMALL_INCREMENT = 1e-3


@dataclass(frozen=True, slots=True)
class NewtonDiagnostic:
    iteration: int
    objective: float
    gradient_infinity_norm: float
    gradient_roundoff_allowance: float
    gradient_tolerance: float
    newton_step_infinity_norm: float
    step_tolerance: float
    newton_decrement_squared: float
    eta_minimum: float
    eta_maximum: float
    accepted_fraction: float | None
    backtracking_trials: int
    objective_difference: float | None
    armijo_bound: float | None


@dataclass(frozen=True, slots=True)
class StablePoissonOffsetModel(PoissonOffsetModel):
    solver: str
    convergence_reason: str
    final_gradient: tuple[float, ...]
    final_newton_step: tuple[float, ...]
    diagnostics: tuple[NewtonDiagnostic, ...]


class PoissonSolverError(ValueError):
    """Fail closed with the exact numerical state; no silent model fallback."""

    def __init__(self, reason: str, state: dict[str, Any]) -> None:
        self.state = {"solver": SOLVER_ID, "reason": reason, **state}
        super().__init__(f"{SOLVER_ID}: {reason}")


def _expm1_remainder(value: float) -> float:
    """Evaluate exp(value)-1-value without cancellation at a tiny step.

    The fixed sixth-degree series has remainder <2e-25 for |value|<=1e-3,
    below binary64 roundoff at the resulting second-order term's scale.
    """
    if abs(value) <= SMALL_INCREMENT:
        return (
            value
            * value
            * (0.5 + value * (1 / 6 + value * (1 / 24 + value * (1 / 120 + value / 720))))
        )
    return math.expm1(value) - value


def _objective_difference(
    design: Sequence[Sequence[float]],
    rates: Sequence[float],
    gradient: Sequence[float],
    delta: Sequence[float],
    penalty: float,
) -> float:
    """Algebraic objective increment, never a subtraction of large objectives."""
    return math.fsum(
        (
            _dot(gradient, delta),
            math.fsum(
                rate * _expm1_remainder(_dot(row, delta))
                for row, rate in zip(design, rates, strict=True)
            )
            / len(design),
            penalty * _dot(delta, delta) / 2,
        )
    )


def fit_poisson_offset_stable(
    x: list[list[float]], goals: list[int], offsets: list[float], penalty: float
) -> StablePoissonOffsetModel:
    """Fit the identical V1 objective with bounded, cancellation-safe Newton.

    Convergence requires a small final gradient AND a small undamped Newton
    step. A small accepted/damped step alone never counts as convergence.
    The numerical tolerances are fixed constants, not selected from match scores.
    """
    _penalty(penalty)
    if len(goals) != len(x) or len(offsets) != len(x):
        raise ValueError("goals and offsets must match predictor row count")
    if any(isinstance(goal, bool) or not isinstance(goal, int) or goal < 0 for goal in goals):
        raise ValueError("goals must be nonnegative integers")
    _finite(offsets)
    if any(rate <= 0 for rate in offsets):
        raise ValueError("offset rates must be strictly positive")
    log_offsets = [math.log(rate) for rate in offsets]
    if any(abs(value) > 20 for value in log_offsets):
        raise ValueError("offset log rate outside fitting safety bounds")
    scaler = fit_scaler(x)
    design = [_design(scaler, row) for row in x]
    size, count = len(design[0]), len(design)
    beta = (0.0,) * size
    trace: list[NewtonDiagnostic] = []

    def levels(coefficients: Sequence[float]) -> list[float]:
        return [
            offset + _dot(row, coefficients)
            for offset, row in zip(log_offsets, design, strict=True)
        ]

    for iteration in range(MAX_ITERATIONS + 1):
        eta = levels(beta)
        state: dict[str, Any] = {
            "penalty": penalty,
            "iteration": iteration,
            "training_rows": count,
            "design_width": size,
            "coefficients": beta,
            "eta_minimum": min(eta),
            "eta_maximum": max(eta),
            "trace": [asdict(item) for item in trace],
        }
        if any(not math.isfinite(value) or abs(value) > 20 for value in eta):
            raise PoissonSolverError("current eta is outside fitting safety bounds", state)
        rates = [math.exp(value) for value in eta]
        objective = (
            math.fsum(
                rate - goal * level for rate, goal, level in zip(rates, goals, eta, strict=True)
            )
            / count
            + penalty * _dot(beta, beta) / 2
        )
        gradient = tuple(
            math.fsum(
                row[j] * (rate - goal) for row, rate, goal in zip(design, rates, goals, strict=True)
            )
            / count
            + penalty * beta[j]
            for j in range(size)
        )
        hessian = [
            [
                math.fsum(rate * row[i] * row[j] for row, rate in zip(design, rates, strict=True))
                / count
                + (penalty if i == j else 0)
                for j in range(size)
            ]
            for i in range(size)
        ]
        roundoff = (
            ROUNDOFF_MULTIPLIER
            * sys.float_info.epsilon
            * max(
                math.fsum(
                    abs(row[j]) * (rate + goal)
                    for row, rate, goal in zip(design, rates, goals, strict=True)
                )
                / count
                + penalty * abs(beta[j])
                for j in range(size)
            )
        )
        gradient_norm = max(abs(value) for value in gradient)
        gradient_tolerance = TOLERANCE + roundoff
        step_tolerance = TOLERANCE * (1 + max(abs(value) for value in beta))
        state.update(
            objective=objective,
            gradient=gradient,
            gradient_infinity_norm=gradient_norm,
            gradient_roundoff_allowance=roundoff,
            gradient_tolerance=gradient_tolerance,
            step_tolerance=step_tolerance,
            hessian_diagonal=tuple(hessian[j][j] for j in range(size)),
        )
        try:
            step = _cholesky_solve(hessian, gradient)
        except ValueError as exc:
            raise PoissonSolverError("Newton system solve failed", state) from exc
        step_norm = max(abs(value) for value in step)
        decrement = _dot(gradient, step)
        state.update(newton_step=step, newton_step_infinity_norm=step_norm)
        state["newton_decrement_squared"] = decrement
        if not math.isfinite(decrement) or decrement < 0:
            raise PoissonSolverError("Newton direction is not a finite descent direction", state)

        diagnostic = NewtonDiagnostic(
            iteration,
            objective,
            gradient_norm,
            roundoff,
            gradient_tolerance,
            step_norm,
            step_tolerance,
            decrement,
            min(eta),
            max(eta),
            None,
            0,
            None,
            None,
        )

        if gradient_norm <= gradient_tolerance and step_norm <= step_tolerance:
            trace.append(diagnostic)
            return StablePoissonOffsetModel(
                scaler,
                beta,
                penalty,
                count,
                iteration,
                True,
                objective,
                SOLVER_ID,
                "final_gradient_and_undamped_newton_step",
                gradient,
                step,
                tuple(trace),
            )
        if iteration == MAX_ITERATIONS:
            raise PoissonSolverError("bounded Newton iteration limit exhausted", state)
        if decrement == 0:
            raise PoissonSolverError("zero Newton descent outside convergence tolerances", state)

        trials: list[dict[str, Any]] = []
        for backtrack in range(MAX_BACKTRACKS):
            fraction = 0.5**backtrack
            proposed = tuple(
                coefficient - fraction * change
                for coefficient, change in zip(beta, step, strict=True)
            )
            # Use the ACTUAL representable coefficient change, not its idealized
            # fraction*step, so Armijo and delta-L describe the same proposal.
            delta = tuple(new - old for new, old in zip(proposed, beta, strict=True))
            proposed_eta = levels(proposed)
            safe = all(math.isfinite(value) and abs(value) <= 20 for value in proposed_eta)
            bound = ARMIJO * _dot(gradient, delta)
            difference = (
                _objective_difference(design, rates, gradient, delta, penalty) if safe else None
            )
            trials.append(
                {
                    "fraction": fraction,
                    "safe_eta": safe,
                    "eta_minimum": min(proposed_eta),
                    "eta_maximum": max(proposed_eta),
                    "objective_difference": difference,
                    "armijo_bound": bound,
                }
            )
            if (
                safe
                and proposed != beta
                and bound < 0
                and difference is not None
                and math.isfinite(difference)
                and difference <= bound
            ):
                trace.append(
                    replace(
                        diagnostic,
                        accepted_fraction=fraction,
                        backtracking_trials=backtrack + 1,
                        objective_difference=difference,
                        armijo_bound=bound,
                    )
                )
                beta = proposed
                break
        else:
            state["backtracking"] = trials
            raise PoissonSolverError("bounded backtracking found no safe descent step", state)
    raise AssertionError("bounded Newton loop must return or fail")
