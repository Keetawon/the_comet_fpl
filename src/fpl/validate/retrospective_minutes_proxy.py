"""Explicit development-only archive-price amendment to CURRENT minutes selectors.

No fitting, database reads, production flag or invented knowledge timestamp. The
archive is loaded lazily ONLY when missing evidence blocks a price-sensitive cold
start. All existing selector mathematics and the strict reproduction helper stay
unchanged. Archive metadata is never promoted to deadline-known API evidence.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final, Literal

from fpl.jobs.prospective_points_v1 import _MIN_PRIOR_SEASON_ROWS, season_boundary_minutes
from fpl.models.price_starter_prior import (
    INCUMBENT_APPEARANCE_THRESHOLD,
    apply_price_starter_prior,
)
from fpl.types import Position
from fpl.validate.prospective_incumbent_adapter import (
    DefaultMinutesInputs,
    MinutesSelectorReproduction,
    NullablePriceEvidence,
    _aware,
    _distribution,
    reproduce_default_minutes,
)

NAME = "retrospective_current_minutes_proxy_v1"
EVIDENCE_CLASS: Final = "retrospective_archive_price_proxy_development"
ELIGIBLE_SEASONS = ("2023-24", "2024-25", "2025-26")
PROXY_CAVEAT = "archive_fixture_value_not_proven_deadline_now_cost"
MISSING_PRICE = NullablePriceEvidence(None, None, None)
_PRICE_BLOCKERS = frozenset(
    {
        "cold_start_deadline_now_cost_unavailable",
        "cold_start_complete_teammate_registry_unavailable",
        "cold_start_established_teammate_price_unproven",
    }
)


@dataclass(frozen=True, slots=True)
class ArchiveFixturePrice:
    """Metadata-only source row; NULL is unavailable, measured zero stays zero."""

    season: str
    gw: int
    fixture: int
    code: int
    team_code: int
    position: Position
    kickoff: datetime
    value: int | None
    source_identity: str
    source_known_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class HistoricalRosterMember:
    code: int
    team_code: int
    position: Position
    eligible_history_present: bool | None
    prior_appearance: tuple[float | None, int]
    maximum_prior_event: datetime | None
    known_price: NullablePriceEvidence = MISSING_PRICE


@dataclass(frozen=True, slots=True)
class HistoricalPriceRoster:
    """Complete DECLARED archive target roster, not a complete live registry claim."""

    season: str
    gw: int
    as_of: datetime
    source_identity: str
    database_sha256: str
    complete_for_declared_archive_population: bool
    members: tuple[HistoricalRosterMember, ...]
    prices: tuple[ArchiveFixturePrice, ...]
    evidence_class: Literal["retrospective_archive_price_proxy_development"] = EVIDENCE_CLASS


@dataclass(frozen=True, slots=True)
class ArchivePriceUse:
    role: Literal["cold_own_price", "established_cold_cap_witness"]
    code: int
    value: int
    rows: tuple[ArchiveFixturePrice, ...]


@dataclass(frozen=True, slots=True)
class RetrospectiveMinutesResult:
    selector: MinutesSelectorReproduction
    cold_start: bool
    proxy_dependent: bool
    archive_price_lineage: tuple[ArchivePriceUse, ...]
    roster_source_identity: str | None = None
    database_sha256: str | None = None
    comparator: str = NAME
    evidence_class: str = EVIDENCE_CLASS
    promotion_permitted: bool = False


class _UnavailablePriceError(ValueError):
    pass


def _archive_value(
    roster: HistoricalPriceRoster,
    member: HistoricalRosterMember,
    role: Literal["cold_own_price", "established_cold_cap_witness"],
) -> ArchivePriceUse:
    rows = tuple(
        sorted((r for r in roster.prices if r.code == member.code), key=lambda r: r.fixture)
    )
    if not rows:
        raise _UnavailablePriceError(f"archive_price_rows_missing:{member.code}")
    if len({r.fixture for r in rows}) != len(rows):
        raise ValueError("duplicate archive player-fixture price identity")
    for row in rows:
        _aware(row.kickoff, "archive kickoff")
        if row.source_known_at is not None:
            _aware(row.source_known_at, "original archive known_at")
        if (
            (row.season, row.gw) != (roster.season, roster.gw)
            or row.kickoff < roster.as_of
            or row.team_code != member.team_code
            or row.position != member.position
        ):
            raise _UnavailablePriceError(
                f"archive_price_fixture_or_identity_ambiguity:{member.code}"
            )
        if row.value is None or not row.source_identity:
            raise _UnavailablePriceError(f"archive_price_unmeasured:{member.code}")
        if isinstance(row.value, bool) or not isinstance(row.value, int) or row.value < 0:
            raise ValueError("archive price must be measured nonnegative integer FPL tenths")
    if len({row.value for row in rows}) != 1:
        raise _UnavailablePriceError(f"archive_price_same_gw_revision_ambiguity:{member.code}")
    value = rows[0].value
    assert value is not None
    return ArchivePriceUse(role, member.code, value, rows)


def _validate_roster(roster: HistoricalPriceRoster, inputs: DefaultMinutesInputs) -> None:
    if type(roster) is not HistoricalPriceRoster or roster.evidence_class != EVIDENCE_CLASS:
        raise ValueError("only the separately typed retrospective archive capability is allowed")
    if (
        (roster.season, roster.gw, roster.as_of)
        != (inputs.target.season, inputs.target.gw, inputs.as_of)
        or not roster.source_identity
        or len(roster.database_sha256) != 64
        or any(c not in "0123456789abcdef" for c in roster.database_sha256)
    ):
        raise ValueError("archive roster scope or provenance differs from the target fold")
    if not roster.complete_for_declared_archive_population:
        raise _UnavailablePriceError("incomplete_declared_archive_roster")
    if len({m.code for m in roster.members}) != len(roster.members):
        raise _UnavailablePriceError("archive_roster_same_gw_player_identity_ambiguity")


def reproduce_with_archive_cold_price_proxy(
    inputs: DefaultMinutesInputs,
    *,
    load_archive: Callable[[], HistoricalPriceRoster],
) -> RetrospectiveMinutesResult:
    """Reuse unchanged selectors, relaxing ONLY the explicitly licensed price source.

    ``load_archive`` must expose all legs in the declared target GW. Never pick a
    later DGW leg or another GW's value. Equal-leg agreement permits one GW value
    while retaining EVERY source row. No field here enters a prospective source.
    """
    if inputs.target.season not in ELIGIBLE_SEASONS:
        raise ValueError("this named comparator licenses only its three historical seasons")
    original = reproduce_default_minutes(inputs)
    cold = inputs.eligible_history_present is False
    if not original.blockers or not original.price_dependency:
        return RetrospectiveMinutesResult(original, cold, False, ())
    if set(original.blockers) - _PRICE_BLOCKERS or inputs.registry.mode != "archive_roster_proxy":
        return RetrospectiveMinutesResult(original, cold, False, ())

    roster = load_archive()
    uses: list[ArchivePriceUse] = []
    try:
        _validate_roster(roster, inputs)
        own = next((m for m in roster.members if m.code == inputs.target.code), None)
        if own is None or (
            own.team_code != inputs.current_team_code
            or own.position != inputs.target.position
            or own.eligible_history_present != inputs.eligible_history_present
            or own.prior_appearance != inputs.prior_appearance
        ):
            raise _UnavailablePriceError("archive_target_roster_identity_or_prior_mismatch")
        if inputs.price.known_by(inputs.as_of):
            price = inputs.price.value
        else:
            use = _archive_value(roster, own, "cold_own_price")
            if not any(r.fixture == inputs.target.fixture for r in use.rows):
                raise _UnavailablePriceError("archive_target_fixture_price_missing")
            if any(
                r.fixture == inputs.target.fixture and r.kickoff != inputs.target.kickoff_time
                for r in use.rows
            ):
                raise _UnavailablePriceError("archive_target_fixture_kickoff_mismatch")
            uses.append(use)
            price = use.value

        maximum = inputs.established_price.value
        if price is not None and price > 0 and not inputs.established_price.known_by(inputs.as_of):
            maximum = None
            for member in sorted(roster.members, key=lambda m: m.code):
                if member.team_code != own.team_code or member.position != own.position:
                    continue
                if member.eligible_history_present is None:
                    raise _UnavailablePriceError(
                        f"archive_cap_witness_history_unknown:{member.code}"
                    )
                if not isinstance(member.eligible_history_present, bool):
                    raise ValueError("cap witness history eligibility must be explicitly boolean")
                if not member.eligible_history_present:
                    continue
                rate, count = member.prior_appearance
                if (
                    isinstance(count, bool)
                    or not isinstance(count, int)
                    or (rate is None) != (count == 0)
                    or count < 0
                    or (rate is not None and (not math.isfinite(rate) or not 0 <= rate <= 1))
                ):
                    raise ValueError("cap witness prior appearance evidence is inconsistent")
                if (
                    rate is None
                    or rate < INCUMBENT_APPEARANCE_THRESHOLD
                    or count < _MIN_PRIOR_SEASON_ROWS
                ):
                    continue
                if member.maximum_prior_event is None:
                    raise _UnavailablePriceError(
                        f"archive_cap_witness_prior_provenance_missing:{member.code}"
                    )
                _aware(member.maximum_prior_event, "cap witness maximum prior event")
                if member.maximum_prior_event >= inputs.as_of:
                    raise ValueError("cap witness uses target-GW or future appearance evidence")
                if member.known_price.known_at is not None:
                    _aware(member.known_price.known_at, "cap witness original price known_at")
                if member.known_price.known_by(inputs.as_of):
                    witness_price = member.known_price.value
                else:
                    use = _archive_value(roster, member, "established_cold_cap_witness")
                    uses.append(use)
                    witness_price = use.value
                if witness_price is not None and (
                    isinstance(witness_price, bool)
                    or not isinstance(witness_price, int)
                    or witness_price < 0
                ):
                    raise ValueError("cap witness price must be nullable nonnegative FPL tenths")
                if witness_price is not None and witness_price > (maximum or 0):
                    maximum = witness_price
    except _UnavailablePriceError as error:
        blocked = replace(
            original, blockers=(str(error),), caveats=(*original.caveats, PROXY_CAVEAT)
        )
        return RetrospectiveMinutesResult(
            blocked, cold, bool(uses), tuple(uses), roster.source_identity, roster.database_sha256
        )

    behind = maximum is not None and price is not None and maximum > price
    minutes = apply_price_starter_prior(
        inputs.raw_v3,
        price=price,
        position=inputs.target.position,
        behind_established_incumbent=behind,
    )
    rate, count = inputs.prior_appearance
    minutes = season_boundary_minutes(
        minutes, prior_rate=rate, prior_n=count, target_month=inputs.target.kickoff_time.month
    )
    _distribution(minutes)
    selector = replace(
        original,
        distribution=minutes,
        route="current_cold_price_prior_with_explicit_archive_proxy",
        blockers=(),
        caveats=(*original.caveats, PROXY_CAVEAT),
        selector_arithmetic_reproduced=True,
        behind_established_incumbent=behind,
    )
    return RetrospectiveMinutesResult(
        selector, cold, bool(uses), tuple(uses), roster.source_identity, roster.database_sha256
    )
