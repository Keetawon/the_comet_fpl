"""Audit/reproduce the CURRENT default minutes selectors, never fit a candidate.

The caller supplies already fitted V3 outputs and fold-prior summaries produced
by the unmodified prospective helpers WITH current-club filtering. This module
does not fit V3, infer a registry, substitute historical prices, or compose points.
An archive roster proxy can establish selector arithmetic, not deadline validity.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from fpl.jobs.prospective_points_v1 import (
    _MIN_TRAILING5_ROWS,
    _trailing_row_eligible,
    season_boundary_minutes,
)
from fpl.models.price_starter_prior import apply_price_starter_prior
from fpl.validate.minutes_baselines import (
    HistoryRow,
    MinutesDistribution,
    TargetRow,
    TeamCodeMap,
)

NAME = "current_prospective_seasonal_minutes_selector_reproduction_v1"
V3_NAME = "concentration_adaptive_shrinkage_player_minutes_v3"
HISTORICAL_CAVEAT = "archive_roster_current_club_proxy_not_deadline_known_registry"
FIXED_CODE_CAVEAT = (
    "current_fixed_selector_constants_were_developed_on_historical_data_not_unseen_validation"
)


@dataclass(frozen=True, slots=True)
class NullablePriceEvidence:
    """Known nullable API price differs from missing historical capture evidence.

    For ``established_price`` this is the maximum price among established
    same-position current-club registry teammates, as selected by the main job.
    A known None there means the complete registry proved there was no price.
    """

    value: int | None
    known_at: datetime | None
    source_identity: str | None

    def known_by(self, cutoff: datetime) -> bool:
        return bool(self.source_identity) and self.known_at is not None and self.known_at <= cutoff


@dataclass(frozen=True, slots=True)
class RegistryEvidence:
    mode: Literal["deadline_known", "archive_roster_proxy"]
    source_identity: str
    known_at: datetime | None
    complete_current_registry: bool


@dataclass(frozen=True, slots=True)
class DefaultMinutesInputs:
    target: TargetRow  # exactly the existing safe nine-column projection
    as_of: datetime
    raw_v3: MinutesDistribution
    raw_v3_as_of: datetime
    raw_v3_model_name: str
    current_team_code: int | None
    eligible_history_present: bool | None
    # These MUST come from the current prospective helpers, not the EV adapter.
    trailing5: tuple[MinutesDistribution, int] | None
    prior_appearance: tuple[float | None, int]
    maximum_prior_event: datetime | None
    prior_source_identity: str
    registry: RegistryEvidence
    price: NullablePriceEvidence
    established_price: NullablePriceEvidence


@dataclass(frozen=True, slots=True)
class MinutesSelectorReproduction:
    distribution: MinutesDistribution | None
    route: str
    blockers: tuple[str, ...]
    caveats: tuple[str, ...]
    selector_arithmetic_reproduced: bool
    historical_deadline_validity_established: bool
    behind_established_incumbent: bool | None
    price_dependency: bool
    reproduction_scope: str = "minutes_selector_only_not_full_prospective_or_player_points"


def _aware(value: datetime, label: str) -> None:
    if value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone aware")


def _distribution(value: MinutesDistribution) -> None:
    if len(value) != 4 or any(not math.isfinite(v) or v < 0 for v in value):
        raise ValueError("minutes must retain four finite nonnegative bins")
    if not math.isclose(math.fsum(value), 1, rel_tol=0, abs_tol=1e-9):
        raise ValueError("minutes distribution must sum to one")


def eligible_trailing_history(
    history: Sequence[HistoryRow],
    *,
    current_club: Mapping[int, int],
    team_codes: TeamCodeMap,
    as_of: datetime,
    target_season: str,
    target_gw: int,
) -> tuple[HistoryRow, ...]:
    """Audit the same club/frontier rule without copying its implementation.

    Input is ALL already-cut-off non-NULL archive minutes rows; this filtered
    result is for trailing summaries only. V3 itself still fits unfiltered prior
    rows in the current prospective job. Never pass this result to V3 instead.
    """
    _aware(as_of, "as_of")
    keys: set[tuple[str, int, int]] = set()
    for row in history:
        _aware(row.kickoff_time, "history kickoff")
        key = (row.season, row.fixture, row.code)
        if key in keys:
            raise ValueError("duplicate prior player-fixture identity")
        keys.add(key)
        if row.kickoff_time >= as_of or (row.season, row.gw) == (target_season, target_gw):
            raise ValueError("same-GW or future history cannot enter minutes summaries")
        if isinstance(row.minutes, bool) or not isinstance(row.minutes, int) or row.minutes < 0:
            raise ValueError("prior minutes must be measured nonnegative integers, not NULL")
    frontier = max((row.season for row in history), default=None)
    return tuple(
        row
        for row in history
        if _trailing_row_eligible(
            season=row.season,
            row_team_code=team_codes.code(row.season, row.team_id),
            code=row.code,
            frontier_season=frontier,
            current_club=current_club,
        )
    )


def reproduce_default_minutes(inputs: DefaultMinutesInputs) -> MinutesSelectorReproduction:
    """Invoke identical default selectors; unavailable evidence never becomes None-price.

    This reproduces numerical selection, not the upstream fit or live registry.
    The ordinary established-player path is independent of price. An unknown
    price cannot be skipped on the cold/sparse path, where it affects the answer.
    All-zero trailing windows still use the supplied out-of-side shrunk profile;
    neither a constant prior nor the V3 distribution is silently substituted.
    """
    target = inputs.target
    if type(target) is not TargetRow:
        raise ValueError("minutes target must be the exact outcome-free TargetRow projection")
    if inputs.eligible_history_present is not None and not isinstance(
        inputs.eligible_history_present, bool
    ):
        raise ValueError("eligible history status must be explicitly true, false or unknown")
    for name, timestamp in (
        ("as_of", inputs.as_of),
        ("target kickoff", target.kickoff_time),
        ("V3 as_of", inputs.raw_v3_as_of),
    ):
        _aware(timestamp, name)
    if target.kickoff_time < inputs.as_of or inputs.raw_v3_as_of != inputs.as_of:
        raise ValueError("target or V3 prediction does not match the fold cutoff")
    if inputs.raw_v3_model_name != V3_NAME:
        raise ValueError("the current default requires the exact fitted V3 output")
    if inputs.maximum_prior_event is not None:
        _aware(inputs.maximum_prior_event, "maximum prior event")
        if inputs.maximum_prior_event >= inputs.as_of:
            raise ValueError("prior minutes summaries contain same-match or future events")
    _distribution(inputs.raw_v3)
    if inputs.trailing5 is not None:
        dist, n = inputs.trailing5
        _distribution(dist)
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 5:
            raise ValueError("the current default trailing window contains one to five rows")
    rate, n_prior = inputs.prior_appearance
    if isinstance(n_prior, bool) or not isinstance(n_prior, int) or n_prior < 0:
        raise ValueError("prior appearance count must be nonnegative")
    if (rate is None) != (n_prior == 0) or (
        rate is not None and (not math.isfinite(rate) or not 0 <= rate <= 1)
    ):
        raise ValueError("prior appearance rate and count are inconsistent")
    if inputs.registry.mode not in ("deadline_known", "archive_roster_proxy"):
        raise ValueError("registry evidence mode must be explicit")
    for evidence in (inputs.price, inputs.established_price):
        if evidence.value is not None and (
            isinstance(evidence.value, bool)
            or not isinstance(evidence.value, int)
            or evidence.value < 0
        ):
            raise ValueError("price must be nullable nonnegative integer FPL tenths")
        if evidence.known_at is not None:
            _aware(evidence.known_at, "price known_at")
            if evidence.known_at > inputs.as_of:
                raise ValueError("later-known price cannot enter the historical comparator")
    if inputs.registry.known_at is not None:
        _aware(inputs.registry.known_at, "registry known_at")
        if inputs.registry.known_at > inputs.as_of:
            raise ValueError("later-known registry cannot enter the historical comparator")

    blockers: list[str] = []
    caveats = [FIXED_CODE_CAVEAT]
    if inputs.registry.mode == "archive_roster_proxy":
        caveats.append(HISTORICAL_CAVEAT)
    elif inputs.registry.known_at is None or not inputs.registry.complete_current_registry:
        blockers.append("deadline_registry_evidence_incomplete")
    if not inputs.registry.source_identity:
        blockers.append("missing_target_roster_source_identity")
    if inputs.current_team_code is None:
        blockers.append("unresolved_season_qualified_current_team_code")
    if inputs.eligible_history_present is None:
        blockers.append("current_club_filtered_history_eligibility_unproven")
    if not inputs.prior_source_identity or inputs.maximum_prior_event is None:
        blockers.append("missing_fold_prior_provenance")

    recent_selected = inputs.trailing5 is not None and inputs.trailing5[1] >= _MIN_TRAILING5_ROWS
    cold = inputs.eligible_history_present is False
    price_dependency = cold and not recent_selected
    behind: bool | None = None
    if price_dependency:
        if not inputs.price.known_by(inputs.as_of):
            blockers.append("cold_start_deadline_now_cost_unavailable")
        elif inputs.price.value is not None and inputs.price.value > 0:
            if not inputs.registry.complete_current_registry:
                blockers.append("cold_start_complete_teammate_registry_unavailable")
            if not inputs.established_price.known_by(inputs.as_of):
                blockers.append("cold_start_established_teammate_price_unproven")
        # A proven null/zero own price makes the existing helper a no-op regardless
        # of teammate price; do not require irrelevant information for that case.
    if blockers:
        return MinutesSelectorReproduction(
            None,
            "blocked_missing_comparator_evidence",
            tuple(blockers),
            tuple(caveats),
            False,
            False,
            None,
            price_dependency,
        )

    minutes = inputs.raw_v3
    route = "raw_v3_sparse_history"
    if price_dependency:
        behind = (
            inputs.established_price.value is not None
            and inputs.price.value is not None
            and inputs.established_price.value > inputs.price.value
        )
        minutes = apply_price_starter_prior(
            minutes,
            price=inputs.price.value,
            position=target.position,
            behind_established_incumbent=behind,
        )
        route = "raw_v3_cold_start_price_prior"
    if recent_selected:
        assert inputs.trailing5 is not None
        minutes = inputs.trailing5[0]
        route = "current_club_filtered_shrunk_equal_weight_trailing5"
    minutes = season_boundary_minutes(
        minutes, prior_rate=rate, prior_n=n_prior, target_month=target.kickoff_time.month
    )
    _distribution(minutes)
    return MinutesSelectorReproduction(
        minutes,
        route,
        (),
        tuple(caveats),
        True,
        False,
        behind,
        price_dependency,
    )
