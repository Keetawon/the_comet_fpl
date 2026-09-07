"""Synthetic coverage, version and event-time proofs; no provider/database writes."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from fpl.validate.competitive_workload_view import (
    COMPETITIONS,
    EVIDENCE_CLASS,
    CatalogueCoverage,
    CompetitiveFixture,
    CompetitiveFixtureKey,
    CompetitiveMatchVersion,
    RetrospectiveCompetitiveWorkloadView,
    TrustedMembershipInterval,
    WorkloadObservation,
)

AS_OF = datetime(2025, 10, 6, 12, tzinfo=UTC)
START = AS_OF - timedelta(days=14)
KNOWN = datetime(2026, 9, 7, tzinfo=UTC)
INTERPRETATION = "synthetic_frozen_nominal_clock_v2"


def _fixture(hours: int = 24, match_id: int = 1, team: int = 101) -> CompetitiveFixture:
    return CompetitiveFixture(
        CompetitiveFixtureKey("pl_sdp", 8, "2025-26", match_id),
        AS_OF - timedelta(hours=hours),
        frozenset({team}),
        True,
    )


def _version(fixture: CompetitiveFixture | None = None) -> CompetitiveMatchVersion:
    fixture = fixture or _fixture()
    return CompetitiveMatchVersion(
        fixture,
        "first",
        KNOWN,
        INTERPRETATION,
        KNOWN + timedelta(hours=1),
        "a" * 64,
        True,
        (WorkloadObservation(1001, 1001, next(iter(fixture.team_codes)), 90.0, True, True),),
        False,
        fixture.kickoff + timedelta(hours=2),
    )


def _coverage(team: int = 101, start: datetime = START) -> tuple[CatalogueCoverage, ...]:
    return tuple(
        CatalogueCoverage(
            "pl_sdp", competition, team, start, AS_OF, KNOWN, "complete-discovery", True
        )
        for competition in COMPETITIONS
    )


def _membership(team: int = 101) -> TrustedMembershipInterval:
    return TrustedMembershipInterval(1001, team, START, AS_OF, KNOWN, "verified-registration", True)


def _view(
    *,
    fixtures: tuple[CompetitiveFixture, ...] | None = None,
    versions: tuple[CompetitiveMatchVersion, ...] | None = None,
    coverage: tuple[CatalogueCoverage, ...] | None = None,
    memberships: tuple[TrustedMembershipInterval, ...] | None = None,
) -> RetrospectiveCompetitiveWorkloadView:
    return RetrospectiveCompetitiveWorkloadView(
        interpretation_id=INTERPRETATION,
        fixtures=fixtures if fixtures is not None else (_fixture(),),
        versions=versions if versions is not None else (_version(),),
        catalogue_coverage=coverage if coverage is not None else _coverage(),
        memberships=memberships if memberships is not None else (_membership(),),
    )


def _snapshot(view: RetrospectiveCompetitiveWorkloadView):  # type: ignore[no-untyped-def]
    return view.snapshot(
        code=1001, current_team_code=101, as_of=AS_OF, excluded_target_gw_fixtures=frozenset()
    )


def test_hand_computable_windows_midweek_and_rest_are_separate() -> None:
    fixtures = (_fixture(24, 1), _fixture(96, 2), _fixture(240, 3))
    versions = tuple(_version(f) for f in fixtures)
    result = _snapshot(_view(fixtures=fixtures, versions=versions))
    assert [w.nominal_minutes for w in result.windows] == [90, 180, 270]
    assert [w.appearances for w in result.windows] == [1, 2, 3]
    assert [w.starts for w in result.windows] == [1, 2, 3]
    # Sunday, Thursday, Friday: only the 96h fixture is Monday-Thursday UTC.
    assert [w.midweek_utc_nominal_minutes for w in result.windows] == [0, 90, 90]
    assert result.player_kickoff_rest_hours_proxy == result.team_kickoff_rest_hours_proxy == 24
    assert result.player_verified_whistle_rest_hours is None
    assert result.team_verified_whistle_rest_hours is None
    assert all(w.completion_time_proxy for w in result.windows)
    assert result.evidence_class == EVIDENCE_CLASS and not result.promotion_permitted
    assert result.selected_versions[0].capture_known_at == KNOWN > AS_OF


def test_verified_whistle_does_not_use_nominal_duration_as_rest() -> None:
    version = replace(_version(), verified_end_at=_fixture().kickoff + timedelta(minutes=110))
    result = _snapshot(_view(versions=(version,)))
    assert result.player_verified_whistle_rest_hours == pytest.approx(24 - 110 / 60)
    assert result.team_verified_whistle_rest_hours == pytest.approx(24 - 110 / 60)
    assert not result.windows[0].completion_time_proxy


def test_earliest_complete_revision_retained_without_double_counting() -> None:
    first = _version()
    later = replace(
        first,
        capture_id="later",
        capture_known_at=KNOWN + timedelta(minutes=1),
        observations=(replace(first.observations[0], nominal_minutes=30),),
    )
    result = _snapshot(_view(versions=(later, first)))
    assert result.windows[0].nominal_minutes == 90
    assert len(result.selected_versions) == 1
    assert result.selected_versions[0].capture_id == "first"


def test_incomplete_capture_does_not_win_but_complete_interpretation_error_is_not_skipped() -> None:
    valid = _version()
    incomplete = replace(
        valid,
        capture_id="earlier",
        capture_known_at=KNOWN - timedelta(minutes=1),
        capture_complete=False,
    )
    assert _snapshot(_view(versions=(incomplete, valid))).windows[0].nominal_minutes == 90
    failed = replace(incomplete, capture_complete=True, errors=("contradictory_starters",))
    result = _snapshot(_view(versions=(failed, valid)))
    assert result.windows[0].nominal_minutes is None
    assert "fixture_error:1:contradictory_starters" in result.windows[0].unknown_reasons


def test_interpretation_identity_and_capture_tie_breaking_are_explicit() -> None:
    first = _version()
    old = replace(
        first, interpretation_id="old-unlicensed", capture_known_at=KNOWN - timedelta(days=1)
    )
    tied = replace(
        first, capture_id="zzz", observations=(replace(first.observations[0], nominal_minutes=20),)
    )
    result = _snapshot(_view(versions=(tied, old, first)))
    assert result.windows[0].nominal_minutes == 90
    assert result.selected_versions[0].interpretation_id == INTERPRETATION


def test_future_fixture_truncation_equivalence() -> None:
    future = _fixture(-24, 2)
    future_version = _version(future)
    short = _snapshot(_view())
    full = _snapshot(_view(fixtures=(_fixture(), future), versions=(_version(), future_version)))
    assert short == full


def test_explicit_same_gw_exclusion_does_not_absorb_earlier_leg() -> None:
    view = _view()
    result = view.snapshot(
        code=1001,
        current_team_code=101,
        as_of=AS_OF,
        excluded_target_gw_fixtures=frozenset({_fixture().key}),
    )
    assert all(w.nominal_minutes == 0 and w.appearances == 0 for w in result.windows)
    assert not result.selected_versions


@pytest.mark.parametrize("source", ["event", "whistle"])
def test_past_kickoff_with_future_event_or_whistle_is_unknown_not_filtered_to_zero(
    source: str,
) -> None:
    version = _version()
    version = replace(
        version,
        **(
            {"maximum_retained_event_timestamp": AS_OF}
            if source == "event"
            else {"verified_end_at": AS_OF}
        ),
    )
    result = _snapshot(_view(versions=(version,)))
    assert all(w.nominal_minutes is None for w in result.windows)
    assert all(w.expected_fixtures == (_fixture().key,) for w in result.windows)
    assert result.player_kickoff_rest_hours_proxy is None


def test_null_duration_remains_null_while_known_appearance_survives() -> None:
    version = _version()
    version = replace(
        version, observations=(replace(version.observations[0], nominal_minutes=None),)
    )
    result = _snapshot(_view(versions=(version,)))
    assert result.windows[0].nominal_minutes is None
    assert result.windows[0].appearances == 1
    assert "unmeasured_nominal_minutes" in result.windows[0].unknown_reasons


def test_zero_nominal_stoppage_entry_is_an_appearance_and_extra_time_is_measured() -> None:
    version = replace(
        _version(),
        observations=(WorkloadObservation(1001, 1001, 101, 0.0, False, True),),
        extra_time=True,
    )
    result = _snapshot(_view(versions=(version,)))
    assert (
        result.windows[0].nominal_minutes,
        result.windows[0].starts,
        result.windows[0].appearances,
    ) == (0, 0, 1)
    assert result.windows[0].extra_time_appearances == 1


def test_complete_roster_absence_can_prove_dnp_only_with_membership_and_catalogue() -> None:
    version = replace(_version(), observations=())
    result = _snapshot(_view(versions=(version,)))
    assert result.windows[0].nominal_minutes == result.windows[0].appearances == 0
    unknown = _snapshot(_view(versions=(version,), memberships=()))
    assert unknown.windows[0].nominal_minutes is None
    assert unknown.player_kickoff_rest_hours_proxy is None


def test_empty_proved_inventory_is_zero_workload_not_zero_rest() -> None:
    result = _snapshot(_view(fixtures=(), versions=()))
    assert all(w.nominal_minutes == 0 for w in result.windows)
    assert result.player_kickoff_rest_hours_proxy is None
    assert result.team_kickoff_rest_hours_proxy is None


@pytest.mark.parametrize("gap", ["catalogue", "member", "capture", "status", "scope_error"])
def test_required_scope_gap_propagates_unknown(gap: str) -> None:
    coverage = _coverage()
    memberships = (_membership(),)
    versions = (_version(),)
    fixture = _fixture()
    if gap == "catalogue":
        coverage = coverage[:-1]
    elif gap == "member":
        memberships = (replace(_membership(), verified_interval=False),)
    elif gap == "capture":
        versions = ()
    elif gap == "status":
        fixture = replace(fixture, completed=None)
    else:
        coverage = (replace(coverage[0], errors=("pagination_incomplete",)), *coverage[1:])
    result = _snapshot(
        _view(fixtures=(fixture,), versions=versions, coverage=coverage, memberships=memberships)
    )
    assert all(w.nominal_minutes is None for w in result.windows)
    assert result.player_kickoff_rest_hours_proxy is None


def test_partial_window_coverage_does_not_poison_shorter_proved_window() -> None:
    result = _snapshot(_view(coverage=_coverage(start=AS_OF - timedelta(hours=72))))
    assert result.windows[0].nominal_minutes == 90
    assert result.windows[1].nominal_minutes is None
    assert result.windows[2].nominal_minutes is None


def test_transfers_keep_code_global_history_and_require_old_club_coverage() -> None:
    old = _fixture(240, 2, 102)
    memberships = (
        replace(_membership(102), valid_before=AS_OF - timedelta(days=5)),
        replace(_membership(), valid_from=AS_OF - timedelta(days=5)),
    )
    kwargs = {
        "fixtures": (_fixture(), old),
        "versions": (_version(), _version(old)),
        "memberships": memberships,
    }
    valid = _snapshot(_view(**kwargs, coverage=(*_coverage(), *_coverage(102))))
    assert valid.windows[2].nominal_minutes == 180
    missing = _snapshot(_view(**kwargs))
    assert missing.windows[0].nominal_minutes == 90
    assert missing.windows[2].nominal_minutes is None


def test_conflicting_membership_is_not_a_transfer_inference() -> None:
    result = _snapshot(
        _view(
            memberships=(_membership(), _membership(102)), coverage=(*_coverage(), *_coverage(102))
        )
    )
    assert result.windows[0].nominal_minutes is None
    assert "contradictory_overlapping_club_memberships" in result.windows[0].unknown_reasons


def test_foreign_opponent_null_fpl_identity_is_separated_by_exact_provider_side() -> None:
    fixture = replace(
        _fixture(), provider_team_ids=frozenset({1, 2}), provider_to_team_code=((1, 101),)
    )
    own = replace(_version().observations[0], provider_team_id=1)
    foreign = WorkloadObservation(2002, None, None, 90.0, True, True, provider_team_id=2)
    version = replace(_version(fixture), observations=(own, foreign))
    result = _snapshot(_view(fixtures=(fixture,), versions=(version,)))
    assert result.windows[0].nominal_minutes == 90
    unresolved_own = replace(foreign, provider_team_id=1)
    blocked = _snapshot(
        _view(fixtures=(fixture,), versions=(replace(version, observations=(own, unresolved_own)),))
    )
    assert blocked.windows[0].nominal_minutes is None


def test_midweek_uses_utc_not_local_day() -> None:
    # Friday 02:00 Bangkok is Thursday19:00 UTC.
    kickoff = datetime(2025, 10, 3, 2, tzinfo=timezone(timedelta(hours=7)))
    fixture = replace(_fixture(96), kickoff=kickoff)
    result = _snapshot(_view(fixtures=(fixture,), versions=(_version(fixture),)))
    assert result.windows[1].midweek_utc_appearances == 1


@pytest.mark.parametrize("bad", ["friendly", "duplicate", "negative", "unknown_provider", "naive"])
def test_invalid_input_is_rejected(bad: str) -> None:
    fixture = _fixture()
    version = _version()
    if bad == "friendly":
        fixture = replace(fixture, key=replace(fixture.key, competition_id=999))
    elif bad == "unknown_provider":
        fixture = replace(fixture, key=replace(fixture.key, provider="unverified"))
    elif bad == "duplicate":
        version = replace(version, observations=(*version.observations, *version.observations))
    elif bad == "negative":
        version = replace(
            version, observations=(replace(version.observations[0], nominal_minutes=-1),)
        )
    else:
        fixture = replace(fixture, kickoff=fixture.kickoff.replace(tzinfo=None))
    with pytest.raises(ValueError, match=r"friendly|provider|duplicate|nominal|aware"):
        _view(fixtures=(fixture,), versions=(version,))


def test_earliest_complete_completed_capture_not_an_in_progress_predecessor() -> None:
    final = _version()
    ongoing = replace(
        final,
        capture_id="ongoing",
        capture_known_at=KNOWN - timedelta(days=1),
        fixture=replace(final.fixture, completed=False),
    )
    result = _snapshot(_view(versions=(ongoing, final)))
    assert result.windows[0].nominal_minutes == 90
    assert result.selected_versions[0].capture_id == "first"


def test_bare_excluded_match_id_is_rejected_not_silently_unmatched() -> None:
    with pytest.raises(ValueError, match="exact provider"):
        _view().snapshot(
            code=1001,
            current_team_code=101,
            as_of=AS_OF,
            excluded_target_gw_fixtures=frozenset({1}),  # type: ignore[arg-type]
        )


def test_workload_view_is_not_imported_by_prospective_paths() -> None:
    root = Path(__file__).resolve().parents[1] / "src/fpl"
    for directory in ("jobs", "features", "models", "optimize"):
        for path in (root / directory).rglob("*.py"):
            assert "competitive_workload_view" not in path.read_text(encoding="utf-8")
