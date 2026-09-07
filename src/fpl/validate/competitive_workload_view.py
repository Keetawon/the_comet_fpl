"""Pure, retrospective-only competitive workload snapshot capability.

Catalogue completeness and trusted membership intervals are explicit inputs.
Missing coverage is never inferred from observed matches, and never becomes zero.
No database, provider requests, model fitting or prospective interface lives here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

EVIDENCE_CLASS: Final = "retrospective_competitive_workload_development"
VERSION_POLICY: Final = "earliest_complete_capture_then_id_then_sha_under_pinned_interpretation"
COMPETITIONS: Final = frozenset({8, 1, 2, 5, 6, 1125})
WINDOW_HOURS: Final = (72, 168, 336)


@dataclass(frozen=True, slots=True, order=True)
class CompetitiveFixtureKey:
    provider: str
    competition_id: int
    season: str
    match_id: int


@dataclass(frozen=True, slots=True)
class CompetitiveFixture:
    key: CompetitiveFixtureKey
    kickoff: datetime
    # Exact stable codes resolved for the scoped clubs; foreign opponents may lack one.
    team_codes: frozenset[int]
    completed: bool | None
    provider_team_ids: frozenset[int] = frozenset()
    provider_to_team_code: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True, slots=True)
class WorkloadObservation:
    provider_player_id: int
    code: int | None
    team_code: int | None
    nominal_minutes: float | None
    started: bool | None
    appeared: bool | None
    errors: tuple[str, ...] = ()
    provider_team_id: int | None = None


@dataclass(frozen=True, slots=True)
class CompetitiveMatchVersion:
    """Whole fixture/lineup/event interpretation, never independent player revisions."""

    fixture: CompetitiveFixture
    capture_id: str
    capture_known_at: datetime
    interpretation_id: str
    interpretation_known_at: datetime
    payload_sha256: str
    capture_complete: bool
    observations: tuple[WorkloadObservation, ...]
    extra_time: bool | None
    maximum_retained_event_timestamp: datetime | None = None
    verified_end_at: datetime | None = None
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CatalogueCoverage:
    """A complete/failed discovery statement, including proved empty inventories."""

    provider: str
    competition_id: int
    team_code: int
    kickoff_from: datetime
    kickoff_before: datetime
    known_at: datetime
    source_identity: str
    complete: bool
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TrustedMembershipInterval:
    code: int
    team_code: int
    valid_from: datetime
    valid_before: datetime
    known_at: datetime
    source_identity: str
    verified_interval: bool


@dataclass(frozen=True, slots=True)
class WindowWorkload:
    hours: int
    nominal_minutes: float | None
    starts: int | None
    appearances: int | None
    midweek_utc_nominal_minutes: float | None
    midweek_utc_appearances: int | None
    extra_time_appearances: int | None
    expected_fixtures: tuple[CompetitiveFixtureKey, ...]
    unknown_reasons: tuple[str, ...]
    completion_time_proxy: bool


@dataclass(frozen=True, slots=True)
class CompetitiveWorkloadSnapshot:
    code: int
    current_team_code: int
    as_of: datetime
    windows: tuple[WindowWorkload, ...]
    player_kickoff_rest_hours_proxy: float | None
    team_kickoff_rest_hours_proxy: float | None
    player_verified_whistle_rest_hours: float | None
    team_verified_whistle_rest_hours: float | None
    rest_unknown_reasons: tuple[str, ...]
    selected_versions: tuple[CompetitiveMatchVersion, ...]
    membership_sources: tuple[TrustedMembershipInterval, ...]
    catalogue_sources: tuple[CatalogueCoverage, ...]
    excluded_target_gw_fixtures: frozenset[CompetitiveFixtureKey]
    evidence_class: str = EVIDENCE_CLASS
    version_policy: str = VERSION_POLICY
    promotion_permitted: bool = False


def _aware(value: datetime) -> None:
    if value.utcoffset() is None:
        raise ValueError("workload instants must be timezone aware")


def _interval(start: datetime, before: datetime) -> None:
    _aware(start)
    _aware(before)
    if start >= before:
        raise ValueError("coverage and membership intervals must be nonempty half-open intervals")


def _covers(intervals: list[tuple[datetime, datetime]], start: datetime, before: datetime) -> bool:
    frontier = start
    for left, right in sorted(intervals):
        if left > frontier:
            return False
        frontier = max(frontier, right)
        if frontier >= before:
            return True
    return False


class RetrospectiveCompetitiveWorkloadView:
    """Separate capability; historical final status is NOT deadline completion proof."""

    def __init__(
        self,
        *,
        interpretation_id: str,
        fixtures: tuple[CompetitiveFixture, ...],
        versions: tuple[CompetitiveMatchVersion, ...],
        catalogue_coverage: tuple[CatalogueCoverage, ...],
        memberships: tuple[TrustedMembershipInterval, ...],
        competitions: frozenset[int] = COMPETITIONS,
    ) -> None:
        if not interpretation_id or not competitions or not competitions <= COMPETITIONS:
            raise ValueError("explicit interpretation and verified competitive-only scope required")
        if len({f.key for f in fixtures}) != len(fixtures):
            raise ValueError("catalogue fixture identities must be unique, never silently merged")
        self.fixtures = fixtures
        self.catalogue = catalogue_coverage
        self.memberships = memberships
        self.competitions = competitions
        self._versions: dict[CompetitiveFixtureKey, CompetitiveMatchVersion] = {}
        for fixture in fixtures:
            _aware(fixture.kickoff)
            if fixture.key.provider != "pl_sdp" or fixture.key.competition_id not in COMPETITIONS:
                raise ValueError("unverified provider/competition or friendly fixture is forbidden")
            crosswalk = dict(fixture.provider_to_team_code)
            if (
                len(crosswalk) != len(fixture.provider_to_team_code)
                or len(set(crosswalk.values())) != len(crosswalk)
                or not set(crosswalk) <= fixture.provider_team_ids
                or not set(crosswalk.values()) <= fixture.team_codes
            ):
                raise ValueError("provider club crosswalk must be exact and one-to-one")
        for coverage in catalogue_coverage:
            _interval(coverage.kickoff_from, coverage.kickoff_before)
            _aware(coverage.known_at)
            if coverage.provider != "pl_sdp" or coverage.competition_id not in COMPETITIONS:
                raise ValueError("catalogue coverage cannot license a friendly or unknown provider")
            if not isinstance(coverage.complete, bool):
                raise ValueError("catalogue completeness must be explicitly boolean")
        for membership in memberships:
            _interval(membership.valid_from, membership.valid_before)
            _aware(membership.known_at)
            if not isinstance(membership.verified_interval, bool):
                raise ValueError("membership interval trust must be explicitly boolean")
        capture_keys: set[tuple[CompetitiveFixtureKey, str, str]] = set()
        for version in sorted(
            versions, key=lambda v: (v.capture_known_at, v.capture_id, v.payload_sha256)
        ):
            for instant in (version.capture_known_at, version.interpretation_known_at):
                _aware(instant)
            if version.interpretation_known_at < version.capture_known_at:
                raise ValueError("interpretation cannot precede its retained capture")
            if not isinstance(version.capture_complete, bool) or (
                version.extra_time is not None and not isinstance(version.extra_time, bool)
            ):
                raise ValueError("capture completeness and measured extra-time flags must be typed")
            _aware(version.fixture.kickoff)
            if (
                version.fixture.key.provider != "pl_sdp"
                or version.fixture.key.competition_id not in COMPETITIONS
            ):
                raise ValueError("capture contains an unverified provider or friendly competition")
            for optional_instant in (
                version.maximum_retained_event_timestamp,
                version.verified_end_at,
            ):
                if optional_instant is not None:
                    _aware(optional_instant)
                    if (
                        optional_instant < version.fixture.kickoff
                        or optional_instant > version.capture_known_at
                    ):
                        raise ValueError(
                            "retained event/end lies outside kickoff-through-capture bounds"
                        )
            identity = (version.fixture.key, version.capture_id, version.interpretation_id)
            if identity in capture_keys:
                raise ValueError("duplicate capture interpretation identity")
            capture_keys.add(identity)
            if not version.capture_id or len(version.payload_sha256) != 64:
                raise ValueError("capture id and content SHA256 required")
            if len({r.provider_player_id for r in version.observations}) != len(
                version.observations
            ):
                raise ValueError("duplicate provider-player observation in a whole match version")
            codes = [r.code for r in version.observations if r.code is not None]
            if len(codes) != len(set(codes)):
                raise ValueError("duplicate stable player identity across fixture sides")
            for row in version.observations:
                if (
                    row.provider_team_id is not None
                    and row.provider_team_id not in version.fixture.provider_team_ids
                ):
                    raise ValueError("participant provider team is outside the exact fixture sides")
                resolved_team = (
                    dict(version.fixture.provider_to_team_code).get(row.provider_team_id)
                    if row.provider_team_id is not None
                    else None
                )
                if (
                    resolved_team is not None
                    and row.team_code is not None
                    and row.team_code != resolved_team
                ):
                    raise ValueError(
                        "participant stable club contradicts the provider-side crosswalk"
                    )
                if row.nominal_minutes is not None and (
                    isinstance(row.nominal_minutes, bool)
                    or not math.isfinite(row.nominal_minutes)
                    or not 0 <= row.nominal_minutes <= 120
                ):
                    raise ValueError("nominal duration must be measured in [0,120], not fabricated")
                if row.started is not None and not isinstance(row.started, bool):
                    raise ValueError("started must be boolean or unknown")
                if row.appeared is not None and not isinstance(row.appeared, bool):
                    raise ValueError("appeared must be boolean or unknown")
                if row.appeared is False and (
                    row.started is True or (row.nominal_minutes or 0) > 0
                ):
                    raise ValueError("nonappearance contradicts starts or positive duration")
            if (
                version.interpretation_id == interpretation_id
                and version.capture_complete
                and version.fixture.completed is True
            ):
                self._versions.setdefault(version.fixture.key, version)

    def _resolve(
        self,
        segments: list[tuple[int, datetime, datetime]],
        cutoff: datetime,
        excluded: frozenset[CompetitiveFixtureKey],
    ) -> tuple[list[CompetitiveMatchVersion], tuple[CompetitiveFixtureKey, ...], list[str]]:
        issues: list[str] = []
        expected: dict[CompetitiveFixtureKey, CompetitiveFixture] = {}
        for team, left, right in segments:
            for competition in sorted(self.competitions):
                proofs = [
                    (c.kickoff_from, c.kickoff_before)
                    for c in self.catalogue
                    if c.team_code == team
                    and c.competition_id == competition
                    and c.complete
                    and not c.errors
                    and c.source_identity
                ]
                if not _covers(proofs, left, right):
                    issues.append(
                        f"catalogue_scope_incomplete:team={team}:competition={competition}"
                    )
                for c in self.catalogue:
                    if (
                        c.team_code == team
                        and c.competition_id == competition
                        and c.kickoff_from < right
                        and c.kickoff_before > left
                    ):
                        issues.extend(f"catalogue_error:{e}" for e in c.errors)
            for fixture in self.fixtures:
                if (
                    team in fixture.team_codes
                    and left <= fixture.kickoff < right
                    and fixture.key.competition_id in self.competitions
                    and fixture.key not in excluded
                ):
                    expected[fixture.key] = fixture
        selected: list[CompetitiveMatchVersion] = []
        for key, fixture in sorted(expected.items()):
            version = self._versions.get(key)
            if fixture.completed is not True:
                issues.append(f"fixture_completion_unknown:{key.match_id}")
                continue
            if version is None:
                issues.append(f"complete_capture_missing:{key.match_id}")
                continue
            if version.fixture != fixture or version.fixture.completed is not True:
                issues.append(f"capture_catalogue_identity_contradiction:{key.match_id}")
                continue
            if any(
                t is not None and t >= cutoff
                for t in (version.maximum_retained_event_timestamp, version.verified_end_at)
            ):
                issues.append(f"fixture_has_event_or_end_at_or_after_cutoff:{key.match_id}")
                continue
            if version.errors:
                issues.extend(f"fixture_error:{key.match_id}:{e}" for e in version.errors)
                continue
            selected.append(version)
        return selected, tuple(sorted(expected)), issues

    def snapshot(
        self,
        *,
        code: int,
        current_team_code: int,
        as_of: datetime,
        excluded_target_gw_fixtures: frozenset[CompetitiveFixtureKey],
    ) -> CompetitiveWorkloadSnapshot:
        _aware(as_of)
        if any(
            isinstance(v, bool) or not isinstance(v, int) or v <= 0
            for v in (code, current_team_code)
        ):
            raise ValueError("workload player and club identities must be positive stable codes")
        if any(type(key) is not CompetitiveFixtureKey for key in excluded_target_gw_fixtures):
            raise ValueError(
                "excluded gameweek fixtures need exact provider/competition/season identities"
            )
        windows: list[WindowWorkload] = []
        used: dict[CompetitiveFixtureKey, CompetitiveMatchVersion] = {}
        player_rest = player_whistle = None
        rest_issues: list[str] = []
        for hours in WINDOW_HOURS:
            start = as_of - timedelta(hours=hours)
            memberships = [
                m
                for m in self.memberships
                if m.code == code and m.valid_from < as_of and m.valid_before > start
            ]
            segments = [
                (m.team_code, max(start, m.valid_from), min(as_of, m.valid_before))
                for m in memberships
                if m.verified_interval and m.source_identity
            ]
            membership_issues: list[str] = []
            if not _covers([(left, right) for _, left, right in segments], start, as_of):
                membership_issues.append("trusted_player_membership_interval_incomplete")
            if any(
                a[0] != b[0] and max(a[1], b[1]) < min(a[2], b[2])
                for i, a in enumerate(segments)
                for b in segments[i + 1 :]
            ):
                membership_issues.append("contradictory_overlapping_club_memberships")
            selected, expected, issues = self._resolve(segments, as_of, excluded_target_gw_fixtures)
            issues = [*membership_issues, *issues]
            minutes: list[float | None] = []
            starts: list[int | None] = []
            apps: list[int | None] = []
            mid_minutes: list[float | None] = []
            mid_apps: list[int | None] = []
            extra_apps: list[int | None] = []
            played: list[CompetitiveMatchVersion] = []
            for version in selected:
                used[version.fixture.key] = version
                members = [
                    team
                    for team, left, right in segments
                    if left <= version.fixture.kickoff < right
                ]
                scoped_provider_ids = {
                    provider_id
                    for provider_id, stable_code in version.fixture.provider_to_team_code
                    if stable_code in members
                }
                relevant = [
                    r
                    for r in version.observations
                    if r.team_code in members
                    or (
                        r.team_code is None
                        and (
                            r.provider_team_id is None
                            or r.provider_team_id in scoped_provider_ids
                            or not scoped_provider_ids
                        )
                    )
                ]
                if any(r.code is None or r.errors for r in relevant):
                    issues.append(
                        f"unresolved_player_identity_or_participation:{version.fixture.key.match_id}"
                    )
                row = next((r for r in version.observations if r.code == code), None)
                if row is not None and row.team_code not in members:
                    issues.append(
                        f"participant_membership_contradiction:{version.fixture.key.match_id}"
                    )
                # Complete, valid lineup absence PLUS trusted registration proves no appearance.
                nominal = row.nominal_minutes if row is not None else 0.0
                started = (None if row.started is None else int(row.started)) if row else 0
                appeared = (None if row.appeared is None else int(row.appeared)) if row else 0
                minutes.append(nominal)
                starts.append(started)
                apps.append(appeared)
                if version.fixture.kickoff.astimezone(UTC).weekday() <= 3:
                    mid_minutes.append(nominal)
                    mid_apps.append(appeared)
                extra_apps.append(
                    0
                    if appeared == 0
                    else None
                    if appeared is None or version.extra_time is None
                    else int(version.extra_time)
                )
                if appeared == 1:
                    played.append(version)
            incomplete = bool(issues)

            def total(values: list[float | None], failed: bool = incomplete) -> float | None:
                return (
                    None
                    if failed or any(v is None for v in values)
                    else math.fsum(v for v in values if v is not None)
                )

            def count(values: list[int | None]) -> int | None:
                value = total([None if v is None else float(v) for v in values])
                return None if value is None else int(value)

            missing = [
                name
                for name, values in (
                    ("nominal_minutes", minutes),
                    ("starts", starts),
                    ("appearances", apps),
                    ("extra_time", extra_apps),
                )
                if any(v is None for v in values)
            ]
            windows.append(
                WindowWorkload(
                    hours,
                    total(minutes),
                    count(starts),
                    count(apps),
                    total(mid_minutes),
                    count(mid_apps),
                    count(extra_apps),
                    expected,
                    tuple(sorted({*issues, *[f"unmeasured_{name}" for name in missing]})),
                    any(v.verified_end_at is None for v in selected),
                )
            )
            if hours == 336:
                if not incomplete and all(v is not None for v in apps) and played:
                    last = max(played, key=lambda v: v.fixture.kickoff)
                    player_rest = (as_of - last.fixture.kickoff).total_seconds() / 3600
                    if last.verified_end_at is not None:
                        player_whistle = (as_of - last.verified_end_at).total_seconds() / 3600
                else:
                    rest_issues.extend(
                        issues or ["player_last_appearance_unknown_or_outside_14d_scope"]
                    )
        team_selected, _, team_issues = self._resolve(
            [(current_team_code, as_of - timedelta(days=14), as_of)],
            as_of,
            excluded_target_gw_fixtures,
        )
        team_rest = team_whistle = None
        if not team_issues and team_selected:
            last = max(team_selected, key=lambda v: v.fixture.kickoff)
            team_rest = (as_of - last.fixture.kickoff).total_seconds() / 3600
            if last.verified_end_at is not None:
                team_whistle = (as_of - last.verified_end_at).total_seconds() / 3600
            for version in team_selected:
                used[version.fixture.key] = version
        else:
            rest_issues.extend(team_issues or ["team_last_match_unknown_or_outside_14d_scope"])
        return CompetitiveWorkloadSnapshot(
            code,
            current_team_code,
            as_of,
            tuple(windows),
            player_rest,
            team_rest,
            player_whistle,
            team_whistle,
            tuple(sorted(set(rest_issues))),
            tuple(used[key] for key in sorted(used)),
            tuple(m for m in self.memberships if m.code == code),
            self.catalogue,
            excluded_target_gw_fixtures,
        )
