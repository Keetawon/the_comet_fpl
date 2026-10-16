"""Fixed-policy components, operationally adopted by the owner on 2026-10-16."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from fpl.models.attacking_baselines import poisson_pmf
from fpl.models.points_composition import conditional_rate
from fpl.types import Position

Component = Literal["goals", "assists"]


@dataclass(frozen=True)
class Policy:
    """Policy constants are registered assumptions, never selected on GW4-6 outcomes."""

    attack_player_strength: float = 1.0
    attack_position_strength: float = 5.0
    dc_team_strength: float = 20.0
    dc_player_strength: float = 5.0
    dc_beta_half: float = 0.5
    window: int = 5

    def __post_init__(self) -> None:
        for value in (
            self.attack_player_strength,
            self.attack_position_strength,
            self.dc_team_strength,
            self.dc_player_strength,
            self.dc_beta_half,
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("prior strengths must be finite and positive")
        if self.window < 1:
            raise ValueError("window must be positive")


DEFAULT_POLICY = Policy()


@dataclass(frozen=True)
class Observation:
    """Whole rows already selected by PointInTimeView; NULL measurements stay NULL."""

    season: str
    gw: int
    fixture: int
    code: int
    team_code: int | None
    position: Position
    kickoff: datetime
    minutes: int
    goals: int | None
    assists: int | None
    xg: float | None
    xa: float | None
    dc: int | None


@dataclass(frozen=True)
class Target:
    code: int
    team_code: int
    position: Position
    minutes: tuple[float, ...]
    incumbent_goals: tuple[float, ...]
    incumbent_assists: tuple[float, ...]
    incumbent_dc: float

    def __post_init__(self) -> None:
        if len(self.minutes) != 4:
            raise ValueError("four minutes bins required")
        for pmf in (self.minutes, self.incumbent_goals, self.incumbent_assists):
            if any(not math.isfinite(x) or x < 0 for x in pmf):
                raise ValueError("invalid PMF")
            if not math.isclose(math.fsum(pmf), 1, abs_tol=1e-12):
                raise ValueError("PMF must sum to one")
        if not 0 <= self.incumbent_dc <= 1:
            raise ValueError("invalid incumbent DC probability")

    @property
    def p_play(self) -> float:
        return 1 - self.minutes[0]


@dataclass(frozen=True)
class AttackPrediction:
    conditional: tuple[float, ...]
    unconditional: tuple[float, ...]
    signal: float | None
    measured_recent: int
    allocated_rate: float | None
    conditional_rate: float | None
    fallback: str | None


@dataclass(frozen=True)
class DcPrediction:
    by_minutes: tuple[float, ...] | None
    unconditional: tuple[float, ...] | None
    fallback: str | None


def checked_history(
    rows: Sequence[Observation], cutoff: datetime, season: str, gw: int
) -> tuple[Observation, ...]:
    """Defence in depth after the reader's event/knowledge-time whole-row selection."""
    if cutoff.tzinfo is None:
        raise ValueError("timezone-aware cutoff required")
    seen: set[tuple[str, int, int]] = set()
    out = []
    for row in rows:
        if row.kickoff.tzinfo is None:
            raise ValueError("timezone-aware observation required")
        if row.kickoff >= cutoff or (row.season, row.gw) == (season, gw):
            raise ValueError("target/future observation in selected history")
        identity = row.season, row.code, row.fixture
        if identity in seen:
            raise ValueError("duplicate player-fixture history")
        seen.add(identity)
        if row.minutes < 0:
            raise ValueError("negative minutes")
        for value in (row.goals, row.assists, row.xg, row.xa, row.dc):
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError("invalid measured component")
        out.append(row)
    return tuple(sorted(out, key=lambda r: (r.kickoff, r.season, r.fixture, r.code)))


def appearance_mixture(p_play: float, pmf: Sequence[float]) -> tuple[float, ...]:
    if not math.isfinite(p_play) or not 0 <= p_play <= 1:
        raise ValueError("invalid appearance probability")
    return (1 - p_play + p_play * pmf[0], *(p_play * p for p in pmf[1:]))


def minute_bin(minutes: int) -> int:
    return 0 if minutes == 0 else 1 if minutes < 60 else 2 if minutes < 90 else 3


def shrunk_attack(
    history: Sequence[Observation],
    roster: Sequence[Target],
    *,
    component: Component,
    frontier_season: str,
    team_budget: float,
    policy: Policy = DEFAULT_POLICY,
) -> dict[int, AttackPrediction]:
    """Position-prior smoothing of appearance-based shares; minutes and team scale unchanged."""
    if not math.isfinite(team_budget) or team_budget < 0:
        raise ValueError("invalid team budget")
    if len({t.code for t in roster}) != len(roster):
        raise ValueError("duplicate roster code")
    if len({t.team_code for t in roster}) > 1:
        raise ValueError("one stable club per allocation")
    current = {t.code: t.team_code for t in roster}
    # Global position priors use the frontier season onwards; old same-club rows are
    # eligible only for the individual trailing signal, not an unbounded population prior.
    pooled: dict[Position, list[float]] = defaultdict(list)
    recent: dict[int, list[Observation]] = defaultdict(list)
    for r in history:
        if r.minutes <= 0:
            continue
        value = r.xg if component == "goals" else r.xa
        if r.season >= frontier_season and value is not None:
            pooled[r.position].append(value)
        if r.code in current and (r.season >= frontier_season or r.team_code == current[r.code]):
            recent[r.code].append(r)
    all_values = [v for values in pooled.values() for v in values]
    league = math.fsum(all_values) / len(all_values) if all_values else None
    signals: dict[int, tuple[float | None, int]] = {}
    for t in roster:
        # Select the last five appearances BEFORE dropping missing measurements.
        selected = recent[t.code][-policy.window :]
        values = [
            value
            for r in selected
            if (value := (r.xg if component == "goals" else r.xa)) is not None
        ]
        if league is None:
            signals[t.code] = None, len(values)
            continue
        pos = pooled[t.position]
        prior = (math.fsum(pos) + policy.attack_position_strength * league) / (
            len(pos) + policy.attack_position_strength
        )
        smoothed_signal = (math.fsum(values) + policy.attack_player_strength * prior) / (
            len(values) + policy.attack_player_strength
        )
        signals[t.code] = smoothed_signal, len(values)
    denominator = math.fsum((signals[t.code][0] or 0) * t.p_play for t in roster)
    output = {}
    for t in roster:
        signal, n = signals[t.code]
        old = t.incumbent_goals if component == "goals" else t.incumbent_assists
        if signal is None or denominator <= 0:
            output[t.code] = AttackPrediction(
                old,
                appearance_mixture(t.p_play, old),
                signal,
                n,
                None,
                None,
                "unmeasured_prior" if signal is None else "zero_roster_weight",
            )
            continue
        allocated = team_budget * signal * t.p_play / denominator
        rate = conditional_rate(allocated, t.p_play, cap=team_budget)
        pmf = tuple(poisson_pmf(rate))
        output[t.code] = AttackPrediction(
            pmf, appearance_mixture(t.p_play, pmf), signal, n, allocated, rate, None
        )
    return output


def duration_dc(
    history: Sequence[Observation],
    target: Target,
    thresholds: Mapping[Position, int],
    policy: Policy = DEFAULT_POLICY,
) -> DcPrediction:
    """Position/bin -> destination-team/bin -> same-club player/bin Bernoulli hierarchy."""
    threshold = thresholds.get(target.position)
    if threshold is None:
        return DcPrediction(None, None, "position_not_applicable")
    measured = [
        r for r in history if r.position == target.position and r.minutes > 0 and r.dc is not None
    ]
    if not measured:
        q = target.incumbent_dc
        return DcPrediction(
            (0, q, q, q), (1 - target.p_play * q, target.p_play * q), "unmeasured_position"
        )
    club = [r for r in measured if r.team_code == target.team_code]
    # Latest witnessed fixtures at this position, with measured DC, ordered by event time.
    fixture_order = sorted({(r.kickoff, r.season, r.fixture) for r in club})
    latest = set(fixture_order[-policy.window :])
    club = [r for r in club if (r.kickoff, r.season, r.fixture) in latest]
    # Prior-club DC never travels with the player; destination-team evidence supplies the prior.
    player = [r for r in measured if r.code == target.code and r.team_code == target.team_code]
    player = player[-policy.window :]
    probabilities = [0.0]
    for b in (1, 2, 3):
        population = [r for r in measured if minute_bin(r.minutes) == b]
        team_rows = [r for r in club if minute_bin(r.minutes) == b]
        player_rows = [r for r in player if minute_bin(r.minutes) == b]

        def hits(rows: Sequence[Observation]) -> int:
            return sum(r.dc is not None and r.dc >= threshold for r in rows)

        # Missing bin support falls back to the measured position's all-duration rate,
        # rather than assigning a 50% rate to an empty rare-event bin.
        anchor = population if population else measured
        position_rate = (hits(anchor) + policy.dc_beta_half) / (
            len(anchor) + 2 * policy.dc_beta_half
        )
        team_rate = (hits(team_rows) + policy.dc_team_strength * position_rate) / (
            len(team_rows) + policy.dc_team_strength
        )
        player_rate = (hits(player_rows) + policy.dc_player_strength * team_rate) / (
            len(player_rows) + policy.dc_player_strength
        )
        probabilities.append(player_rate)
    q = math.fsum(m * p for m, p in zip(target.minutes, probabilities, strict=True))
    return DcPrediction(tuple(probabilities), (1 - q, q), None)
