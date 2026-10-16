"""Nested, historical conversion training. Isolated from every production consumer."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Parameters:
    smoothing: float | None
    ridge: float | None
    bound: float | None

    @property
    def name(self) -> str:
        if self.smoothing is None:
            return "off"
        return f"k{self.smoothing:g}_r{self.ridge:g}_b{self.bound:g}"


def parameter_grid(
    smoothing: Sequence[float], ridge: Sequence[float], bounds: Sequence[float]
) -> tuple[Parameters, ...]:
    values = [*smoothing, *ridge, *bounds]
    if not values or any(not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError("positive finite search values required")
    active = [Parameters(k, r, b) for k in smoothing for r in ridge for b in bounds]
    active.sort(key=lambda p: (-(p.ridge or 0), -(p.smoothing or 0), p.bound or 0))
    result = (Parameters(None, None, None), *active)
    if len({p.name for p in result}) != len(result):
        raise ValueError("duplicate search settings")
    return result


def ratio_feature(actual: int | None, expected: float | None, smoothing: float) -> float:
    if not math.isfinite(smoothing) or smoothing <= 0:
        raise ValueError("positive finite smoothing required")
    if actual is None or expected is None:
        if actual is not None or expected is not None:
            raise ValueError("paired sums must both be available or missing")
        return 0.0
    if actual < 0 or expected < 0 or not math.isfinite(expected):
        raise ValueError("invalid conversion sums")
    return math.log((actual + smoothing) / (expected + smoothing))


@dataclass(frozen=True)
class FitRow:
    position: str
    offset: float
    outcome: int
    past_actual: int | None
    past_expected: float | None
    feature_cutoff: datetime
    label_available: datetime


@dataclass(frozen=True)
class Profile:
    # Exact sufficient statistics, compressed by equal position/feature value.
    groups: tuple[tuple[str, int, tuple[tuple[float, float], ...]], ...]
    yz: float
    rows: int
    events: int

    def at(self, beta: float, ridge: float) -> tuple[float, float, float]:
        derivative = self.yz - ridge * beta
        curvature = -ridge
        objective = beta * self.yz - ridge * beta * beta / 2
        for _, events, values in self.groups:
            if events == 0:
                continue
            weights = [offset * math.exp(beta * z) for z, offset in values]
            total = math.fsum(weights)
            mean = (
                math.fsum(weight * value[0] for weight, value in zip(weights, values, strict=True))
                / total
            )
            variance = (
                math.fsum(
                    weight * (value[0] - mean) ** 2
                    for weight, value in zip(weights, values, strict=True)
                )
                / total
            )
            derivative -= events * mean
            curvature -= events * variance
            objective -= events * math.log(total)
        return derivative, curvature, objective


def prepare_profile(rows: Sequence[FitRow], *, cutoff: datetime, smoothing: float) -> Profile:
    if cutoff.tzinfo is None:
        raise ValueError("timezone-aware fitting cutoff required")
    eligible = [r for r in rows if r.label_available < cutoff and r.feature_cutoff < cutoff]
    grouped: dict[str, dict[float, list[float]]] = defaultdict(lambda: defaultdict(list))
    events: dict[str, int] = defaultdict(int)
    yz = []
    for r in eligible:
        if r.feature_cutoff >= r.label_available:
            raise ValueError("training feature does not precede label availability")
        if r.offset <= 0 or not math.isfinite(r.offset) or r.outcome < 0:
            raise ValueError("invalid training example")
        z = ratio_feature(r.past_actual, r.past_expected, smoothing)
        grouped[r.position][z].append(r.offset)
        events[r.position] += r.outcome
        yz.append(r.outcome * z)
    groups = tuple(
        (
            position,
            events[position],
            tuple((z, math.fsum(offsets)) for z, offsets in sorted(values.items())),
        )
        for position, values in sorted(grouped.items())
    )
    return Profile(groups, math.fsum(yz), len(eligible), sum(events.values()))


@dataclass(frozen=True)
class Fitted:
    beta: float
    rows: int
    events: int
    derivative: float
    curvature: float
    objective_gain: float
    boundary: bool
    iterations: int
    fallback: str | None


def fit_profile(
    profile: Profile,
    *,
    ridge: float,
    bound: float,
    minimum_rows: int = 500,
    minimum_events: int = 20,
) -> Fitted:
    if any(not math.isfinite(v) or v <= 0 for v in (ridge, bound)):
        raise ValueError("positive finite ridge and bound required")
    if profile.rows < minimum_rows or profile.events < minimum_events:
        return Fitted(0, profile.rows, profile.events, 0, -ridge, 0, False, 0, "short_training")
    lo, hi = -bound, bound
    iterations = 0
    if profile.at(lo, ridge)[0] <= 0:
        beta = lo
    elif profile.at(hi, ridge)[0] >= 0:
        beta = hi
    else:
        beta = 0.0
        for _ in range(80):
            iterations += 1
            gradient, curvature, _ = profile.at(beta, ridge)
            if abs(gradient) < 1e-9 or hi - lo < 1e-12:
                break
            if gradient > 0:
                lo = beta
            else:
                hi = beta
            proposal = beta - gradient / curvature
            beta = proposal if lo < proposal < hi else (lo + hi) / 2
        else:
            raise ArithmeticError("profile solver did not converge")
    gradient, curvature, objective = profile.at(beta, ridge)
    if abs(beta) < bound and abs(gradient) > 1e-7:
        raise ArithmeticError("profile optimum not verified")
    return Fitted(
        beta,
        profile.rows,
        profile.events,
        gradient,
        curvature,
        objective - profile.at(0, ridge)[2],
        abs(beta) == bound,
        iterations,
        None,
    )


def clip_fit(profile: Profile, fitted: Fitted, *, ridge: float, bound: float) -> Fitted:
    """Strict concavity makes clipping the wider optimum exact for a narrower bound."""
    if fitted.fallback:
        return fitted
    beta = max(-bound, min(bound, fitted.beta))
    gradient, curvature, objective = profile.at(beta, ridge)
    return Fitted(
        beta,
        fitted.rows,
        fitted.events,
        gradient,
        curvature,
        objective - profile.at(0, ridge)[2],
        abs(beta) == bound,
        fitted.iterations,
        None,
    )


@dataclass(frozen=True)
class ShareRow:
    code: int
    p_play: float
    allocated: float | None
    conditional_rate: float | None
    past_actual: int | None
    past_expected: float | None


def converted_rates(
    rows: Sequence[ShareRow], *, budget: float, smoothing: float | None, beta: float
) -> tuple[float | None, ...]:
    if not math.isfinite(beta) or not math.isfinite(budget) or budget < 0:
        raise ValueError("invalid allocation inputs")
    if len({r.code for r in rows}) != len(rows):
        raise ValueError("unique roster codes required")
    if beta == 0 or smoothing is None or any(r.allocated is None for r in rows):
        return tuple(r.conditional_rate for r in rows)
    weights = [
        (r.allocated or 0)
        * math.exp(beta * ratio_feature(r.past_actual, r.past_expected, smoothing))
        for r in rows
    ]
    total = math.fsum(weights)
    if total <= 0:
        return tuple(r.conditional_rate for r in rows)
    return tuple(
        min(budget * weight / total / r.p_play, budget) if r.p_play > 0 else 0.0
        for r, weight in zip(rows, weights, strict=True)
    )


@dataclass(frozen=True)
class ValidationFold:
    key: str
    cutoff: datetime
    labels_available: datetime
    rows: int
    losses: Mapping[str, float]


def select_parameters(
    folds: Sequence[ValidationFold],
    *,
    cutoff: datetime,
    grid: Sequence[Parameters],
    window: int = 6,
) -> tuple[Parameters, tuple[str, ...], dict[str, float]]:
    if cutoff.tzinfo is None:
        raise ValueError("timezone-aware selection cutoff required")
    eligible = sorted(
        (f for f in folds if f.cutoff < cutoff and f.labels_available < cutoff),
        key=lambda f: (f.cutoff, f.key),
    )[-window:]
    if len(eligible) < window:
        return grid[0], tuple(f.key for f in eligible), {}
    denominator = sum(f.rows for f in eligible)
    if denominator <= 0:
        raise ValueError("empty inner validation population")
    scores = {
        p.name: math.fsum(f.rows * f.losses[p.name] for f in eligible) / denominator for p in grid
    }
    selected = grid[0]
    for candidate in grid[1:]:
        if scores[candidate.name] < scores[selected.name] - 1e-12:
            selected = candidate
    return selected, tuple(f.key for f in eligible), scores
