"""Last-ten-appearance conversion experiment; never imported by production jobs."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from fpl.models.attacking_baselines import poisson_pmf
from fpl.models.component_followup import (
    DEFAULT_POLICY,
    AttackPrediction,
    Component,
    Observation,
    Target,
    appearance_mixture,
)
from fpl.models.points_composition import conditional_rate
from fpl.types import Position


@dataclass(frozen=True)
class ConversionPolicy:
    window: int = 10
    prior_exposure: float = 5.0
    ridge: float = 10.0
    coefficient_bound: float = 1.0

    def __post_init__(self) -> None:
        if self.window != 10:
            raise ValueError("owner-selected window is ten appearances")
        for value in (self.prior_exposure, self.ridge, self.coefficient_bound):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("policy values must be finite and positive")


DEFAULT_CONVERSION = ConversionPolicy()


@dataclass(frozen=True)
class ConversionFeature:
    selected_keys: tuple[tuple[str, int, int], ...]
    paired_keys: tuple[tuple[str, int, int], ...]
    selected_minutes: int
    paired_minutes: int
    first_kickoff: str | None
    last_kickoff: str | None
    actual_sum: int | None
    expected_sum: float | None
    raw_ratio: float | None
    shrunk_ratio: float
    log_ratio: float

    @property
    def coverage(self) -> float | None:
        return len(self.paired_keys) / len(self.selected_keys) if self.selected_keys else None


def conversion_feature(
    history: Sequence[Observation],
    *,
    code: int,
    component: Component,
    cutoff: datetime,
    policy: ConversionPolicy = DEFAULT_CONVERSION,
) -> ConversionFeature:
    """Select ten earlier appearances, then match actual and expected on identical rows."""
    if cutoff.tzinfo is None:
        raise ValueError("timezone-aware cutoff required")
    selected = sorted(
        (r for r in history if r.code == code and r.minutes > 0 and r.kickoff < cutoff),
        key=lambda r: (r.kickoff, r.season, r.fixture),
    )[-policy.window :]
    keys = tuple((r.season, r.fixture, r.code) for r in selected)
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate selected fixture")
    pairs = []
    for r in selected:
        actual = r.goals if component == "goals" else r.assists
        expected = r.xg if component == "goals" else r.xa
        if actual is not None and expected is not None:
            if not math.isfinite(expected) or expected < 0 or actual < 0:
                raise ValueError("invalid matched conversion measurement")
            pairs.append((r, actual, expected))
    actual_sum = sum(a for _, a, _ in pairs) if pairs else None
    expected_sum = math.fsum(x for _, _, x in pairs) if pairs else None
    smoothed = (
        (actual_sum + policy.prior_exposure) / (expected_sum + policy.prior_exposure)
        if actual_sum is not None and expected_sum is not None
        else 1.0
    )
    return ConversionFeature(
        keys,
        tuple((r.season, r.fixture, r.code) for r, _, _ in pairs),
        sum(r.minutes for r in selected),
        sum(r.minutes for r, _, _ in pairs),
        selected[0].kickoff.isoformat() if selected else None,
        selected[-1].kickoff.isoformat() if selected else None,
        actual_sum,
        expected_sum,
        actual_sum / expected_sum
        if actual_sum is not None and expected_sum is not None and expected_sum > 0
        else None,
        smoothed,
        math.log(smoothed),
    )


@dataclass(frozen=True)
class TrainingExample:
    season: str
    gw: int
    fixture: int
    code: int
    position: Position
    cutoff: str
    history_before: str
    component: Component
    actual: int
    offset: float
    feature: ConversionFeature


def training_examples(
    history: Sequence[Observation],
    *,
    seasons: Sequence[str],
    component: Component,
    policy: ConversionPolicy = DEFAULT_CONVERSION,
) -> tuple[list[TrainingExample], dict[str, int]]:
    """Historical first-kickoff proxy, with a fixed three-hour completion lag.

    Target xG/xA never supplies an offset or feature. Target appearances define a
    conditional-on-appearance development population, not a historical live roster.
    """
    groups: dict[tuple[str, int], list[Observation]] = defaultdict(list)
    for r in history:
        if r.season in seasons:
            groups[r.season, r.gw].append(r)
    result = []
    counts: dict[str, int] = defaultdict(int)
    for (season, gw), targets in sorted(
        groups.items(), key=lambda item: min(r.kickoff for r in item[1])
    ):
        cutoff = min(r.kickoff for r in targets)
        history_before = cutoff - timedelta(hours=3)
        past = [
            r
            for r in history
            if r.kickoff < history_before and (r.season, r.gw) != (season, gw) and r.minutes > 0
        ]
        frontier = f"{int(season[:4]) - 1}-{int(season[5:]) - 1:02d}"
        pooled: dict[Position, list[float]] = defaultdict(list)
        by_code: dict[int, list[Observation]] = defaultdict(list)
        for r in past:
            by_code[r.code].append(r)
            value = r.xg if component == "goals" else r.xa
            if r.season >= frontier and value is not None:
                pooled[r.position].append(value)
        for rows in by_code.values():
            rows.sort(key=lambda r: (r.kickoff, r.season, r.fixture))
        all_values = [v for values in pooled.values() for v in values]
        league = math.fsum(all_values) / len(all_values) if all_values else None
        for target in sorted(targets, key=lambda r: (r.kickoff, r.fixture, r.code)):
            if target.minutes <= 0:
                counts["dnp_excluded"] += 1
                continue
            actual = target.goals if component == "goals" else target.assists
            if actual is None:
                counts["missing_target"] += 1
                continue
            if league is None:
                counts["unmeasured_prior"] += 1
                continue
            pos = pooled[target.position]
            prior = (math.fsum(pos) + DEFAULT_POLICY.attack_position_strength * league) / (
                len(pos) + DEFAULT_POLICY.attack_position_strength
            )
            recent = [
                r
                for r in by_code[target.code]
                if r.season >= frontier or r.team_code == target.team_code
            ][-DEFAULT_POLICY.window :]
            values = [
                value
                for r in recent
                if (value := r.xg if component == "goals" else r.xa) is not None
            ]
            offset = (math.fsum(values) + DEFAULT_POLICY.attack_player_strength * prior) / (
                len(values) + DEFAULT_POLICY.attack_player_strength
            )
            if offset <= 0:
                counts["zero_offset_excluded"] += 1
                counts["zero_offset_events"] += actual
                continue
            feature = conversion_feature(
                by_code[target.code],
                code=target.code,
                component=component,
                cutoff=history_before,
                policy=policy,
            )
            result.append(
                TrainingExample(
                    season,
                    gw,
                    target.fixture,
                    target.code,
                    target.position,
                    cutoff.isoformat(),
                    history_before.isoformat(),
                    component,
                    actual,
                    offset,
                    feature,
                )
            )
            counts["included"] += 1
    return result, dict(counts)


@dataclass(frozen=True)
class ConversionFit:
    beta: float
    position_intercepts: dict[str, float | None]
    rows: int
    events: int
    derivative: float
    boundary: bool
    penalized_log_likelihood_gain: float


def fit_conversion(
    rows: Sequence[TrainingExample], policy: ConversionPolicy = DEFAULT_CONVERSION
) -> ConversionFit:
    """Concave Poisson profile likelihood; position intercepts are fitting nuisances only."""
    if not rows:
        raise ValueError("training rows required")
    groups: dict[Position, list[TrainingExample]] = defaultdict(list)
    for r in rows:
        if (
            not math.isfinite(r.offset)
            or r.offset <= 0
            or r.actual < 0
            or not math.isfinite(r.feature.log_ratio)
        ):
            raise ValueError("invalid training row")
        groups[r.position].append(r)
    events = {p: sum(r.actual for r in group) for p, group in groups.items()}
    yz = math.fsum(r.actual * r.feature.log_ratio for r in rows)

    def profile(beta: float) -> tuple[float, float, dict[str, float | None]]:
        derivative = yz - policy.ridge * beta
        objective = beta * yz - 0.5 * policy.ridge * beta * beta
        intercepts: dict[str, float | None] = {}
        for p, group in groups.items():
            weights = [r.offset * math.exp(beta * r.feature.log_ratio) for r in group]
            total = math.fsum(weights)
            y = events[p]
            intercepts[p.value] = math.log(y / total) if y else None
            if y:
                derivative -= (
                    y
                    * math.fsum(
                        w * r.feature.log_ratio for w, r in zip(weights, group, strict=True)
                    )
                    / total
                )
                # Constants independent of beta omitted.
                objective -= y * math.log(total)
        return derivative, objective, intercepts

    lo, hi = -policy.coefficient_bound, policy.coefficient_bound
    if profile(lo)[0] <= 0:
        beta = lo
    elif profile(hi)[0] >= 0:
        beta = hi
    else:
        for _ in range(60):
            mid = (lo + hi) / 2
            if profile(mid)[0] > 0:
                lo = mid
            else:
                hi = mid
        beta = (lo + hi) / 2
    derivative, objective, intercepts = profile(beta)
    return ConversionFit(
        beta,
        intercepts,
        len(rows),
        sum(events.values()),
        derivative,
        abs(beta) == policy.coefficient_bound,
        objective - profile(0.0)[1],
    )


def apply_conversion(
    baseline: Mapping[int, AttackPrediction],
    roster: Sequence[Target],
    features: Mapping[int, ConversionFeature],
    *,
    beta: float,
    team_budget: float,
) -> dict[int, AttackPrediction]:
    """Tilt frozen player shares and renormalize to the frozen team budget."""
    if not math.isfinite(beta) or abs(beta) > DEFAULT_CONVERSION.coefficient_bound:
        raise ValueError("invalid conversion coefficient")
    if not math.isfinite(team_budget) or team_budget < 0:
        raise ValueError("invalid team budget")
    codes = {t.code for t in roster}
    if len(codes) != len(roster) or codes != set(baseline) or codes != set(features):
        raise ValueError("exact unique roster required")
    if len({t.team_code for t in roster}) > 1:
        raise ValueError("one stable club required")
    if beta == 0 or team_budget == 0 or any(b.allocated_rate is None for b in baseline.values()):
        return dict(baseline)
    weighted = {
        code: (baseline[code].allocated_rate or 0) * math.exp(beta * features[code].log_ratio)
        for code in codes
    }
    total = math.fsum(weighted.values())
    if total <= 0:
        return dict(baseline)
    result = {}
    for t in roster:
        old = baseline[t.code]
        allocated = team_budget * weighted[t.code] / total
        rate = conditional_rate(allocated, t.p_play, cap=team_budget)
        pmf = tuple(poisson_pmf(rate))
        result[t.code] = AttackPrediction(
            pmf,
            appearance_mixture(t.p_play, pmf),
            old.signal * math.exp(beta * features[t.code].log_ratio)
            if old.signal is not None
            else None,
            old.measured_recent,
            allocated,
            rate,
            old.fallback,
        )
    return result
