"""Small deterministic, training-only estimators for tactical development.

No database access or production integration. Every coefficient, including the
intercept, is penalised toward zero. Scaling is fitted solely on supplied rows.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from fpl.validate.metrics import Distribution, poisson_pmf


def _finite(values: Sequence[float]) -> None:
    if any(not math.isfinite(value) for value in values):
        raise ValueError("values must be finite")


def _matrix(rows: Sequence[Sequence[float]]) -> int:
    if not rows:
        raise ValueError("training rows must not be empty")
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise ValueError("inconsistent row width")
    for row in rows:
        _finite(row)
    return width


def _penalty(value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError("penalty must be finite and strictly positive")


@dataclass(frozen=True, slots=True)
class Scaler:
    means: tuple[float, ...]
    scales: tuple[float, ...]

    def transform(self, row: Sequence[float]) -> tuple[float, ...]:
        if len(row) != len(self.means):
            raise ValueError("predictor row width differs from training")
        _finite(row)
        return tuple(
            (value - mean) / scale
            for value, mean, scale in zip(row, self.means, self.scales, strict=True)
        )


def fit_scaler(x: list[list[float]]) -> Scaler:
    width = _matrix(x)
    means = tuple(math.fsum(row[j] for row in x) / len(x) for j in range(width))
    scales = tuple(
        math.sqrt(math.fsum((row[j] - means[j]) ** 2 for row in x) / len(x)) or 1.0
        for j in range(width)
    )
    _finite((*means, *scales))
    return Scaler(means, scales)


def _design(scaler: Scaler, row: Sequence[float]) -> tuple[float, ...]:
    return (1.0, *scaler.transform(row))


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return math.fsum(a * b for a, b in zip(left, right, strict=True))


def _cholesky_solve(matrix: list[list[float]], rhs: Sequence[float]) -> tuple[float, ...]:
    """Solve the small strictly positive-definite penalised normal equations."""
    size = len(rhs)
    lower = [[0.0] * size for _ in range(size)]
    for i in range(size):
        for j in range(i + 1):
            value = matrix[i][j] - math.fsum(lower[i][k] * lower[j][k] for k in range(j))
            if i == j:
                if not math.isfinite(value) or value <= 0:
                    raise ValueError("normal equations are not positive definite")
                lower[i][j] = math.sqrt(value)
            else:
                lower[i][j] = value / lower[j][j]
    forward = [0.0] * size
    for i in range(size):
        forward[i] = (rhs[i] - math.fsum(lower[i][j] * forward[j] for j in range(i))) / lower[i][i]
    answer = [0.0] * size
    for i in reversed(range(size)):
        answer[i] = (
            forward[i] - math.fsum(lower[j][i] * answer[j] for j in range(i + 1, size))
        ) / lower[i][i]
    _finite(answer)
    return tuple(answer)


@dataclass(frozen=True, slots=True)
class RidgeModel:
    scaler: Scaler
    coefficients: tuple[tuple[float, ...], ...]  # output-major; intercept first
    penalty: float
    training_rows: int

    def predict(self, row: Sequence[float]) -> tuple[float, ...]:
        predictors = _design(self.scaler, row)
        return tuple(_dot(predictors, coefficients) for coefficients in self.coefficients)


def fit_ridge(x: list[list[float]], y: list[list[float]], penalty: float) -> RidgeModel:
    """Minimise mean squared residual plus penalty * squared coefficient norm."""
    _penalty(penalty)
    outputs = _matrix(y)
    if not outputs or len(x) != len(y):
        raise ValueError("targets must have nonzero width and match predictor row count")
    scaler = fit_scaler(x)
    design = [_design(scaler, row) for row in x]
    width = len(design[0])
    normal = [
        [
            math.fsum(row[i] * row[j] for row in design) / len(x) + (penalty if i == j else 0)
            for j in range(width)
        ]
        for i in range(width)
    ]
    coefficients = tuple(
        _cholesky_solve(
            normal,
            [
                math.fsum(row[i] * target[k] for row, target in zip(design, y, strict=True))
                / len(x)
                for i in range(width)
            ],
        )
        for k in range(outputs)
    )
    return RidgeModel(scaler, coefficients, penalty, len(x))


@dataclass(frozen=True, slots=True)
class PoissonOffsetModel:
    scaler: Scaler
    coefficients: tuple[float, ...]
    penalty: float
    training_rows: int
    iterations: int
    converged: bool
    objective: float

    def raw_correction(self, row: Sequence[float]) -> float:
        return _dot(_design(self.scaler, row), self.coefficients)

    def correction(self, row: Sequence[float]) -> float:
        return max(-0.5, min(0.5, self.raw_correction(row)))


def fit_poisson_offset(
    x: list[list[float]], goals: list[int], offsets: list[float], penalty: float
) -> PoissonOffsetModel:
    """Penalised Poisson offset MLE; deterministic Newton with bounded backtracking.

    Training eta is constrained to [-20, 20] by rejecting unsafe steps, not by
    silently clipping the likelihood or its derivative. Prediction alone clips
    the tactical correction to [-0.5, 0.5].
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
    size = len(design[0])
    coefficients = (0.0,) * size

    def likelihood(beta: Sequence[float]) -> tuple[float, list[float]]:
        eta = [offset + _dot(row, beta) for offset, row in zip(log_offsets, design, strict=True)]
        if any(not math.isfinite(value) or abs(value) > 20 for value in eta):
            return math.inf, []
        rates = [math.exp(value) for value in eta]
        value = math.fsum(
            rate - goal * level for rate, goal, level in zip(rates, goals, eta, strict=True)
        )
        return value / len(x) + penalty * _dot(beta, beta) / 2, rates

    objective, rates = likelihood(coefficients)
    converged = False
    iteration = 0
    for _ in range(40):
        iteration += 1
        gradient = [
            math.fsum(
                row[j] * (rate - goal) for row, rate, goal in zip(design, rates, goals, strict=True)
            )
            / len(x)
            + penalty * coefficients[j]
            for j in range(size)
        ]
        if max(abs(value) for value in gradient) <= 1e-9:
            converged = True
            break
        hessian = [
            [
                math.fsum(rate * row[i] * row[j] for row, rate in zip(design, rates, strict=True))
                / len(x)
                + (penalty if i == j else 0)
                for j in range(size)
            ]
            for i in range(size)
        ]
        step = _cholesky_solve(hessian, gradient)
        directional = _dot(gradient, step)
        fraction = 1.0
        for _ in range(30):
            proposed = tuple(
                beta - fraction * change for beta, change in zip(coefficients, step, strict=True)
            )
            next_objective, next_rates = likelihood(proposed)
            if next_objective <= objective - 1e-4 * fraction * directional:
                break
            fraction *= 0.5
        else:
            raise ValueError("Poisson Newton backtracking failed to find a safe descent step")
        coefficients, objective, rates = proposed, next_objective, next_rates
        if max(abs(fraction * value) for value in step) <= 1e-9:
            converged = True
            break
    return PoissonOffsetModel(
        scaler, coefficients, penalty, len(x), iteration, converged, objective
    )


def adjusted_pmf(rate: float, pmf: Distribution, correction: float) -> Distribution:
    """Preserve the exact incumbent tuple at zero; preserve its family otherwise."""
    _finite((rate, correction, *pmf))
    if rate <= 0 or len(pmf) != 11 or any(value < 0 for value in pmf):
        raise ValueError("expected a positive incumbent rate and 0..10 goal PMF")
    if not math.isclose(math.fsum(pmf), 1.0, rel_tol=0, abs_tol=1e-9):
        raise ValueError("incumbent PMF must sum to one")
    if correction == 0.0:
        return pmf
    bounded = max(-0.5, min(0.5, correction))
    return poisson_pmf(max(0.05, rate * math.exp(bounded)), max_goals=10)
