"""Gameweek P(goals + FPL assists >= 2), with a separately trained event calibrator.

The component baseline shares ONE appearance gate between goals and assists.
Fixture legs are combined before calibration. The event classifier does not modify
the full-points distribution or claim to be a joint generative count model.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

POSITIONS = ("GK", "DEF", "MID", "FWD")


def fixture_low_counts(
    minutes: Sequence[float], goals: Sequence[float], assists: Sequence[float]
) -> tuple[float, float]:
    """Return unconditional P(G+A=0), P(G+A=1) from conditional count PMFs."""
    if len(minutes) != 4 or len(goals) < 2 or len(assists) < 2:
        raise ValueError("four minutes bins and count PMFs required")
    for pmf in (minutes, goals, assists):
        if any(not math.isfinite(v) or v < 0 for v in pmf) or not math.isclose(
            math.fsum(pmf), 1, abs_tol=1e-9, rel_tol=0
        ):
            raise ValueError("invalid probability distribution")
    play = 1 - minutes[0]
    return (
        minutes[0] + play * goals[0] * assists[0],
        play * (goals[1] * assists[0] + goals[0] * assists[1]),
    )


def gameweek_probability(legs: Sequence[tuple[float, float]]) -> float:
    """An explicitly empty scheduled GW is zero; absent evidence is handled by callers."""
    zero, one = 1.0, 0.0
    for p0, p1 in legs:
        if any(not math.isfinite(v) or v < 0 for v in (p0, p1)) or p0 + p1 > 1 + 1e-9:
            raise ValueError("invalid fixture low-count probabilities")
        zero, one = zero * p0, one * p0 + zero * p1
    return max(0.0, min(1.0, 1 - zero - one))


def _logit_feature(probability: float) -> float:
    if not math.isfinite(probability) or not 0 <= probability <= 1:
        raise ValueError("invalid event probability")
    p = min(1 - 1e-6, max(1e-6, probability))
    # Registered fixed discretization, not a transform fitted on the full archive.
    return round(max(-12.0, min(6.0, math.log(p / (1 - p)))) * 10) / 10


def _sigmoid(value: float) -> float:
    return 1 / (1 + math.exp(-value)) if value >= 0 else math.exp(value) / (1 + math.exp(value))


@dataclass(frozen=True)
class EventRow:
    position: str
    baseline: float
    outcome: int

    def __post_init__(self) -> None:
        if self.position not in POSITIONS or self.outcome not in (0, 1):
            raise ValueError("invalid binary event row")
        _logit_feature(self.baseline)


@dataclass(frozen=True)
class EventFit:
    intercepts: tuple[float, ...]
    slope_delta: float
    ridge: float
    fit_slope: bool
    rows: int
    events: int
    iterations: int
    gradient_max: float

    def predict(self, position: str, baseline: float) -> float:
        x = _logit_feature(baseline)
        return _sigmoid(self.intercepts[POSITIONS.index(position)] + (1 + self.slope_delta) * x)


def fit_event_model(rows: Sequence[EventRow], *, ridge: float, fit_slope: bool) -> EventFit:
    """Penalized binomial logistic regression around the component-model identity.

    Exact sufficient statistics of the registered discretized feature make the
    full nested search inexpensive without subsampling or class reweighting.
    Position intercepts and the optional shared slope are fitted jointly.
    """
    if not math.isfinite(ridge) or ridge <= 0 or not rows:
        raise ValueError("nonempty training and positive finite ridge required")
    groups: dict[tuple[int, float], list[int]] = defaultdict(lambda: [0, 0])
    for row in rows:
        key = POSITIONS.index(row.position), _logit_feature(row.baseline)
        groups[key][0] += 1
        groups[key][1] += row.outcome
    compressed = [(pos, x, n, y) for (pos, x), (n, y) in sorted(groups.items())]

    def evaluate(values: list[float]) -> tuple[float, list[float], list[float], list[float], float]:
        objective = ridge * math.fsum(v * v for v in values) / 2
        gradient = [ridge * v for v in values]
        diagonal = [ridge] * 4
        cross = [0.0] * 4
        slope_curvature = ridge
        for pos, x, n, y in compressed:
            eta = values[pos] + (1 + values[4]) * x
            p = _sigmoid(eta)
            objective += n * (max(eta, 0) + math.log1p(math.exp(-abs(eta)))) - y * eta
            residual = n * p - y
            weight = n * p * (1 - p)
            gradient[pos] += residual
            diagonal[pos] += weight
            if fit_slope:
                gradient[4] += residual * x
                cross[pos] += weight * x
                slope_curvature += weight * x * x
        return objective, gradient, diagonal, cross, slope_curvature

    values = [0.0] * 5
    for iteration in range(1, 81):
        iterations = iteration
        objective, gradient, diagonal, cross, curvature = evaluate(values)
        if max(abs(v) for v in gradient) < 1e-7:
            break
        slope_step = (
            (
                gradient[4]
                - sum(c * g / d for c, g, d in zip(cross, gradient[:4], diagonal, strict=True))
            )
            / (curvature - sum(c * c / d for c, d in zip(cross, diagonal, strict=True)))
            if fit_slope
            else 0.0
        )
        step = [
            (g - c * slope_step) / d for g, c, d in zip(gradient[:4], cross, diagonal, strict=True)
        ]
        step.append(slope_step)
        scale = 1.0
        for _ in range(40):
            proposed = [v - scale * s for v, s in zip(values, step, strict=True)]
            if evaluate(proposed)[0] <= objective + 1e-9:
                values = proposed
                break
            scale /= 2
        else:
            raise ArithmeticError("event fit line search failed")
    else:
        raise ArithmeticError("event model did not converge")
    gradient_max = max(abs(v) for v in evaluate(values)[1])
    if gradient_max > 1e-6 or any(not math.isfinite(v) for v in values):
        raise ArithmeticError("event model optimum failed verification")
    return EventFit(
        tuple(values[:4]),
        values[4],
        ridge,
        fit_slope,
        len(rows),
        sum(r.outcome for r in rows),
        iterations,
        gradient_max,
    )


def binary_log_loss(probability: float, outcome: int) -> float:
    if outcome not in (0, 1) or not math.isfinite(probability) or not 0 <= probability <= 1:
        raise ValueError("invalid binary score")
    p = min(1 - 1e-12, max(1e-12, probability))
    return -math.log(p) if outcome else -math.log1p(-p)
