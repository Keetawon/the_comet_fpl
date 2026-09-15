"""Separate retrospective xG/xA opportunity research, never a production selector.

Shared fixed hierarchy, two candidate identities. Preserve unavailable players'
incumbent rates and reallocate ONLY the eligible pool's original rate budget.
Soft starting-role forecasts are covariates, not observed role-time exposure.
No I/O, target outcomes, grid search, minutes refit or team-strength fit here.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Final, Literal, cast

from fpl.jobs.prospective_points_v1 import _trailing_row_eligible
from fpl.models.attacking_baselines import poisson_pmf
from fpl.models.attacking_exposure import (
    BIN_MEAN_FALLBACKS,
    allocate_team_scale,
    expected_minutes,
    shrunk_rate_per_min,
    trailing_signal_minutes,
)
from fpl.models.points_composition import conditional_rate
from fpl.validate.minutes_baselines import MinuteBins, MinutesDistribution
from fpl.validate.player_role_history import EVIDENCE_CLASS as ROLE_EVIDENCE
from fpl.validate.player_role_history import NAME as ROLE_NAME
from fpl.validate.player_role_history import RoleBatchForecast, RolePrediction, RoleTarget
from fpl.validate.player_workload_minutes import PrequentialMinutesControl

type Component = Literal["goals", "assists"]
type Four = tuple[float, float, float, float]
type TargetKey = tuple[str, int, int, int, int, datetime, datetime]
NAMES: Final = {
    "goals": "retrospective_role_exposure_player_goals_v1",
    "assists": "retrospective_role_exposure_player_assists_v1",
}
EVIDENCE_CLASS: Final = "retrospective_role_and_archive_price_proxy_development"
ROLE_PRIOR_MINUTES: Final = 900.0
PLAYER_PRIOR_MINUTES: Final = 90.0
WINDOW: Final = 5
MINIMUM_PRIOR_GAMEWEEKS: Final = 8
MINIMUM_GATE_FOLDS: Final = 181
ROLE_CONDITIONALITY: Final = "role_given_hypothetical_start_not_start_probability"


def _target_key(t: RoleTarget) -> TargetKey:
    return t.season, t.gw, t.fixture, t.code, t.team_code, t.kickoff, t.as_of


def _pmf(p: Sequence[float], *, width: int) -> None:
    if len(p) != width or any(isinstance(v, bool) or not math.isfinite(v) or v < 0 for v in p):
        raise ValueError("finite nonnegative PMF with exact support required")
    if not math.isclose(math.fsum(p), 1, rel_tol=0, abs_tol=1e-9):
        raise ValueError("PMF mass must equal one")


def _sha(value: str) -> None:
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("original artifact SHA256 required")


@dataclass(frozen=True, slots=True)
class PrequentialRoleContext:
    prediction: RolePrediction
    batch_source_sha256: str
    batch_source_versions: tuple[tuple[str, str, str, str], ...]


def role_contexts(batch: RoleBatchForecast) -> dict[TargetKey, PrequentialRoleContext]:
    """Project one validated OOS batch once, not repeated roster scans per player."""
    if (
        type(batch) is not RoleBatchForecast
        or batch.name != ROLE_NAME
        or batch.evidence_class != ROLE_EVIDENCE
    ):
        raise ValueError("explicit frozen retrospective role batch required")
    _sha(batch.source_rows_sha256)
    result = {}
    for prediction in batch.predictions:
        t = prediction.target
        if (t.season, t.gw, t.as_of) != (batch.season, batch.gw, batch.as_of):
            raise ValueError("role target is not from the same pre-GW batch")
        key = _target_key(t)
        if key in result:
            raise ValueError("duplicate role prediction target")
        result[key] = PrequentialRoleContext(
            prediction, batch.source_rows_sha256, batch.source_versions
        )
    return result


def _role(context: PrequentialRoleContext | None, target: RoleTarget) -> Four | None:
    if context is None:
        return None
    if (
        type(context) is not PrequentialRoleContext
        or type(context.prediction) is not RolePrediction
    ):
        raise ValueError("typed out-of-sample role evidence required")
    _sha(context.batch_source_sha256)
    p = context.prediction
    if (
        _target_key(p.target) != _target_key(target)
        or p.promotion_permitted
        or p.evidence_class != ROLE_EVIDENCE
        or p.conditionality != ROLE_CONDITIONALITY
    ):
        raise ValueError("role identity/evidence/conditionality contradicts target")
    _pmf(p.probabilities, width=4)
    for instant in (p.maximum_prior_event, p.maximum_retained_event):
        if instant is not None and (instant.utcoffset() is None or instant >= target.as_of):
            raise ValueError("target/future information in historical role forecast")
    for row in p.recent_sources:
        if (
            row.code != target.code
            or row.team_code != target.team_code
            or row.kickoff >= target.as_of
            or row.completed is not True
            or (row.competition_id == 8 and (row.season, row.gw) == (target.season, target.gw))
        ):
            raise ValueError("role source violates stable identity/whole-GW event isolation")
        if any(
            t is not None and t >= target.as_of for t in (row.max_event_at, row.verified_end_at)
        ):
            raise ValueError("role source has future event/end")
        if row.verified_end_at is None and row.kickoff + timedelta(hours=6) >= target.as_of:
            raise ValueError("role source lacks six-hour completion margin")
    if not p.witnessed_current_club_spell or p.recent_measured_starts == 0:
        return None
    if p.maximum_prior_event is None or p.recent_measured_starts != len(p.recent_sources):
        raise ValueError("role history count/time provenance is inconsistent")
    return p.probabilities


@dataclass(frozen=True, slots=True)
class OpportunityHistoryRow:
    """Past observed PL labels/signals, separate from all prediction input objects."""

    target: RoleTarget
    minutes: int
    signal: float | None
    source_field: str
    source_identity: str
    role_context: PrequentialRoleContext | None = None

    def __post_init__(self) -> None:
        if type(self.target) is not RoleTarget or not self.source_identity:
            raise ValueError("exact historical identity and archive provenance required")
        if type(self.minutes) is not int or not 0 <= self.minutes <= 120:
            raise ValueError("measured minutes must be an integer in [0,120]")
        if self.signal is not None and (
            isinstance(self.signal, bool) or not math.isfinite(self.signal) or self.signal < 0
        ):
            raise ValueError("measured xG/xA must be finite nonnegative or missing")


@dataclass(frozen=True, slots=True)
class OpportunityFit:
    component: Component
    season: str
    gw: int
    as_of: datetime
    current_clubs: tuple[tuple[int, int], ...]
    bin_means: Four
    pooled_rate_per_minute: float | None
    soft_role_rates_per_minute: Four | None
    role_signal_sums: Four
    role_exposure_sums: Four
    # Option-A sums retain measured-count exposure; raw NULL never becomes a zero row.
    player_windows: tuple[tuple[int, float, float, int], ...]
    prior_rows: int
    prior_gameweeks: int
    role_prior_rows: int
    maximum_prior_kickoff: datetime | None
    training_source_sha256: str
    role_source_sha256s: tuple[str, ...]
    enabled: bool
    evidence_class: str = EVIDENCE_CLASS
    promotion_permitted: bool = False
    synthesis_eligible: bool = False


def fit_opportunity(
    history: Sequence[OpportunityHistoryRow],
    *,
    component: Component,
    season: str,
    gw: int,
    as_of: datetime,
    bins: MinuteBins,
    current_club: Mapping[int, int],
) -> OpportunityFit:
    """Fixed closed-form hierarchy, fit only prior completed event-time observations."""
    if (
        component not in NAMES
        or as_of.utcoffset() is None
        or not season
        or type(gw) is not int
        or gw <= 0
    ):
        raise ValueError("explicit component/season/GW/aware cutoff required")
    if bins.ranges != ((0, 0), (1, 59), (60, 89), (90, None)):
        raise ValueError("the existing fixed four-bin minutes contract is required")
    if not current_club or any(
        type(v) is not int or v <= 0 for pair in current_club.items() for v in pair
    ):
        raise ValueError("exact positive stable current roster identities required")
    if any(type(row) is not OpportunityHistoryRow for row in history):
        raise ValueError("typed historical opportunity rows required")
    source_field = "expected_goals" if component == "goals" else "expected_assists"
    prior = sorted(
        (
            r
            for r in history
            if r.target.kickoff + timedelta(hours=6) < as_of
            and (r.target.season, r.target.gw) != (season, gw)
        ),
        key=lambda r: (r.target.kickoff, _target_key(r.target)),
    )
    if len({(r.target.season, r.target.fixture, r.target.code) for r in prior}) != len(prior):
        raise ValueError("duplicate historical player-fixture")
    if any(r.source_field != source_field for r in prior):
        raise ValueError("separate component cannot mix xG and xA signal identities")
    frontier = max((r.target.season for r in prior), default=None)
    windows: dict[int, list[tuple[float, int, float | None]]] = defaultdict(list)
    means: list[list[int]] = [[] for _ in range(4)]
    pool: list[OpportunityHistoryRow] = []
    soft: list[tuple[OpportunityHistoryRow, Four]] = []
    role_hashes = set()
    batch_cutoffs: dict[tuple[str, int], datetime] = {}
    batch_clubs: dict[tuple[str, int, int], int] = {}
    for row in prior:
        t = row.target
        batch = t.season, t.gw
        if batch in batch_cutoffs and batch_cutoffs[batch] != t.as_of:
            raise ValueError("historical same-GW predictors have different cutoffs")
        batch_cutoffs[batch] = t.as_of
        identity = t.season, t.gw, t.code
        if identity in batch_clubs and batch_clubs[identity] != t.team_code:
            raise ValueError("historical same-GW stable club contradiction")
        batch_clubs[identity] = t.team_code
        means[bins.index_of(row.minutes)].append(row.minutes)
        if row.minutes == 0 or not _trailing_row_eligible(
            season=t.season,
            row_team_code=t.team_code,
            code=t.code,
            frontier_season=frontier,
            current_club=current_club,
        ):
            continue
        windows[t.code].append((t.kickoff.timestamp(), row.minutes, row.signal))
        if row.signal is None:
            continue
        pool.append(row)
        probabilities = _role(row.role_context, t)
        if probabilities is not None:
            soft.append((row, probabilities))
            assert row.role_context is not None
            role_hashes.add(row.role_context.batch_source_sha256)
    pool_minutes = math.fsum(r.minutes for r in pool)
    pooled = (
        math.fsum(r.signal for r in pool if r.signal is not None) / pool_minutes
        if pool_minutes
        else None
    )
    role_signal = cast(
        Four, tuple(math.fsum(p[j] * cast(float, r.signal) for r, p in soft) for j in range(4))
    )
    role_exposure = cast(
        Four, tuple(math.fsum(p[j] * r.minutes for r, p in soft) for j in range(4))
    )
    rates = (
        None
        if pooled is None or not soft
        else cast(
            Four,
            tuple(
                shrunk_rate_per_min(s, m, pooled, prior_minutes=ROLE_PRIOR_MINUTES)
                for s, m in zip(role_signal, role_exposure, strict=True)
            ),
        )
    )
    bin_means = cast(
        Four,
        tuple(
            0.0 if j == 0 else math.fsum(values) / len(values) if values else BIN_MEAN_FALLBACKS[j]
            for j, values in enumerate(means)
        ),
    )
    player_windows = []
    for code in sorted(current_club):
        rows = windows.get(code, [])[-WINDOW:]
        signal, minutes = trailing_signal_minutes(rows, window=WINDOW)
        player_windows.append((code, signal, minutes, sum(r[2] is not None for r in rows)))
    # Hash original source identities and immutable OOS contexts, not fitted outputs.
    encoded = json.dumps(
        [asdict(r) for r in prior],
        default=str,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return OpportunityFit(
        component,
        season,
        gw,
        as_of,
        tuple(sorted(current_club.items())),
        bin_means,
        pooled,
        rates,
        role_signal,
        role_exposure,
        tuple(player_windows),
        len(prior),
        len(batch_cutoffs),
        len(soft),
        max((r.target.kickoff for r in prior), default=None),
        hashlib.sha256(encoded).hexdigest(),
        tuple(sorted(role_hashes)),
        rates is not None and len(batch_cutoffs) >= MINIMUM_PRIOR_GAMEWEEKS,
    )


@dataclass(frozen=True, slots=True)
class OpportunityInput:
    control: PrequentialMinutesControl
    conditional_incumbent_pmf: tuple[float, ...]
    unconditional_incumbent_rate: float | None
    team_scale: float | None
    role_context: PrequentialRoleContext | None


@dataclass(frozen=True, slots=True)
class OpportunityPrediction:
    target: RoleTarget
    conditional_pmf: tuple[float, ...]
    unconditional_rate: float | None
    conditional_rate: float | None
    incumbent_rate: float | None
    expected_minutes: float
    posterior_rate_per_minute: float | None
    role_probabilities: Four | None
    role_source_sha256: str | None
    correction_applied: bool
    fallback_reason: str | None
    conditional_cap_bound: bool
    pool_incumbent_budget: float
    direct_price_proxy: bool
    team_price_proxy_codes: tuple[int, ...]
    identity: str
    evidence_class: str = EVIDENCE_CLASS
    promotion_permitted: bool = False


def predict_opportunity_batch(
    model: OpportunityFit,
    inputs: Sequence[OpportunityInput],
) -> tuple[OpportunityPrediction, ...]:
    """One immutable GW fit; keep noneligible rates/PMFs EXACT and team scales fixed."""
    if (
        type(model) is not OpportunityFit
        or model.component not in NAMES
        or model.evidence_class != EVIDENCE_CLASS
        or model.promotion_permitted
        or model.synthesis_eligible
    ):
        raise ValueError("explicit unpromoted opportunity fit required")
    if not inputs or min(r.control.target.kickoff for r in inputs) != model.as_of:
        raise ValueError("complete first-kickoff target-GW batch required")
    clubs = dict(model.current_clubs)
    if {(r.control.target.code, r.control.target.team_code) for r in inputs} != set(
        model.current_clubs
    ):
        raise ValueError("target roster differs from the declared fit roster")
    windows = {code: (signal, minutes, n) for code, signal, minutes, n in model.player_windows}
    groups: dict[tuple[int, int], list[OpportunityInput]] = defaultdict(list)
    identities = set()
    evidence = {}
    for row in inputs:
        t, control = row.control.target, row.control
        if type(row) is not OpportunityInput or type(control) is not PrequentialMinutesControl:
            raise ValueError("typed current minutes/component inputs required")
        if (t.season, t.gw, t.as_of) != (model.season, model.gw, model.as_of) or clubs[
            t.code
        ] != t.team_code:
            raise ValueError("target cutoff/identity differs from the frozen GW fit")
        key = t.fixture, t.code
        if key in identities:
            raise ValueError("duplicate target player-fixture")
        identities.add(key)
        _pmf(row.conditional_incumbent_pmf, width=11)
        if any(
            v is not None and (isinstance(v, bool) or not math.isfinite(v) or v < 0)
            for v in (row.unconditional_incumbent_rate, row.team_scale)
        ):
            raise ValueError("incumbent rates/scales must remain finite nonnegative or unavailable")
        if (row.unconditional_incumbent_rate is None) != (row.team_scale is None):
            raise ValueError("incumbent uninformative rate/scale status differs")
        p_play = 1 - control.probabilities[0]
        if row.team_scale is not None and row.unconditional_incumbent_rate is not None:
            expected = poisson_pmf(
                conditional_rate(row.unconditional_incumbent_rate, p_play, cap=row.team_scale)
            )
            if expected != row.conditional_incumbent_pmf:
                raise ValueError(
                    "incumbent PMF does not exactly reproduce the retained current helper"
                )
        reason = None
        role = None
        posterior = None
        exposure = expected_minutes(control.probabilities, model.bin_means)
        if control.cold_start:
            reason = "cold_start_exact_incumbent"
        elif row.team_scale is None:
            reason = "uninformative_team_scale_exact_incumbent"
        elif not model.enabled or model.soft_role_rates_per_minute is None:
            reason = "unsupported_prior_role_history_exact_incumbent"
        else:
            role = _role(row.role_context, t)
            signal, minutes, count = windows[t.code]
            if role is None:
                reason = "unavailable_current_role_exact_incumbent"
            elif not count or minutes <= 0:
                reason = "unmeasured_recent_signal_exact_incumbent"
            elif p_play <= 0 or exposure <= 0:
                reason = "zero_expected_exposure_exact_incumbent"
            else:
                prior = math.fsum(
                    p * rate for p, rate in zip(role, model.soft_role_rates_per_minute, strict=True)
                )
                posterior = shrunk_rate_per_min(
                    signal, minutes, prior, prior_minutes=PLAYER_PRIOR_MINUTES
                )
        evidence[key] = reason, role, posterior, exposure
        groups[(t.fixture, t.team_code)].append(row)
    result = {}
    for roster in groups.values():
        scales = {r.team_scale for r in roster}
        if len(scales) != 1:
            raise ValueError("one fixture side must retain exactly one incumbent scale")
        scale = roster[0].team_scale
        if scale is not None and not math.isclose(
            math.fsum(cast(float, r.unconditional_incumbent_rate) for r in roster),
            scale,
            rel_tol=1e-10,
            abs_tol=1e-12,
        ):
            raise ValueError("declared incumbent roster does not conserve its original team scale")
        eligible = [
            r
            for r in roster
            if evidence[(r.control.target.fixture, r.control.target.code)][0] is None
        ]
        budget = math.fsum(cast(float, r.unconditional_incumbent_rate) for r in eligible)
        weights = {
            r.control.target.code: cast(
                float, evidence[(r.control.target.fixture, r.control.target.code)][2]
            )
            * evidence[(r.control.target.fixture, r.control.target.code)][3]
            for r in eligible
        }
        available = len(eligible) >= 2 and budget > 0 and math.fsum(weights.values()) > 0
        allocated = allocate_team_scale(weights, budget) if available else {}
        if allocated and not math.isclose(
            math.fsum(allocated.values()), budget, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError("eligible-pool incumbent budget is not conserved")
        proxies = tuple(
            sorted(r.control.target.code for r in roster if r.control.price_proxy_dependent)
        )
        for row in roster:
            t = row.control.target
            key = t.fixture, t.code
            reason, role, posterior, exposure = evidence[key]
            if reason is None and not available:
                reason = "insufficient_positive_eligible_pool_exact_incumbent"
            rate = allocated[t.code] if reason is None else row.unconditional_incumbent_rate
            if reason is None and rate == row.unconditional_incumbent_rate:
                reason = "unchanged_allocation_exact_incumbent"
            changed = reason is None
            conditional = (
                None
                if rate is None or row.team_scale is None
                else conditional_rate(rate, 1 - row.control.probabilities[0], cap=row.team_scale)
            )
            pmf = (
                poisson_pmf(cast(float, conditional)) if changed else row.conditional_incumbent_pmf
            )
            p_play = 1 - row.control.probabilities[0]
            cap_bound = (
                rate is not None
                and row.team_scale is not None
                and p_play > 0
                and rate / p_play > row.team_scale
            )
            result[key] = OpportunityPrediction(
                t,
                pmf,
                rate,
                conditional,
                row.unconditional_incumbent_rate,
                exposure,
                posterior,
                role,
                row.role_context.batch_source_sha256
                if role is not None and row.role_context
                else None,
                changed,
                reason,
                cap_bound,
                budget,
                row.control.price_proxy_dependent,
                proxies,
                NAMES[model.component],
            )
    return tuple(result[(r.control.target.fixture, r.control.target.code)] for r in inputs)


def marginal_pmf(conditional: tuple[float, ...], minutes: MinutesDistribution) -> tuple[float, ...]:
    """Exact current appearance gate, once; not an independent unconditional Poisson."""
    _pmf(conditional, width=11)
    _pmf(minutes, width=4)
    p_play = 1 - minutes[0]
    return (minutes[0] + p_play * conditional[0], *(p_play * p for p in conditional[1:]))
