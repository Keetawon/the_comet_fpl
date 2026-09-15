"""Synthetic equivalence/causality proofs; no retained data or model evaluation."""

from dataclasses import replace
from datetime import timedelta

import pytest

from fpl.validate.competitive_workload_view import (
    ObservedPlayerIdentity,
    RetrospectiveCompetitiveWorkloadView,
    WorkloadObservation,
)
from fpl.validate.player_workload_cache import _BatchView, observe_workload_batch
from tests import test_competitive_workload_view as fixture

IDENTITIES = tuple(
    ObservedPlayerIdentity(code, code, "exact-synthetic-opta", fixture.KNOWN)
    for code in (1001, 1002, 1003)
)
SCOPE = frozenset({101, 102})


def ordinary(view, identities=IDENTITIES, *, as_of=fixture.AS_OF, excluded=frozenset()):
    return tuple(
        view.observed_participation_snapshot(
            identity=identity,
            scope_team_codes=SCOPE,
            as_of=as_of,
            excluded_target_gw_fixtures=excluded,
        )
        for identity in identities
    )


def cached(view, identities=IDENTITIES, *, as_of=fixture.AS_OF, excluded=frozenset()):
    return observe_workload_batch(
        view,
        identities,
        scope_team_codes=SCOPE,
        as_of=as_of,
        excluded_target_gw_fixtures=excluded,
    )


def test_exact_original_outputs_with_independent_player_specific_errors():
    first = fixture._version()
    first = replace(
        first,
        observations=(
            replace(first.observations[0], nominal_minutes=None),
            WorkloadObservation(1002, 1002, 101, 90, True, True),
            WorkloadObservation(1003, 1003, 101, 0, False, False),
        ),
    )
    view = fixture._view(versions=(first,), memberships=())
    before = (view.fixtures, view.catalogue, view.memberships, dict(view._versions))
    result = cached(view)
    assert result == ordinary(view)
    assert result[0].windows[0].nominal_minutes_lower_bound is None
    assert result[0].windows[0].appearances_lower_bound == 1
    assert result[1].windows[0].nominal_minutes_lower_bound == 90
    assert not any("duration_unknown" in issue for issue in result[1].windows[0].unknown_reasons)
    assert result[2].windows[0].nominal_minutes_lower_bound is None
    assert result[2].windows[0].appearances_lower_bound is None
    assert (view.fixtures, view.catalogue, view.memberships, view._versions) == before
    assert cached(view, tuple(reversed(IDENTITIES))) == tuple(reversed(result))


def test_only_three_resolver_scans_for_many_players(monkeypatch):
    calls = []
    original = RetrospectiveCompetitiveWorkloadView._resolve

    def spy(self, segments, cutoff, excluded):
        calls.append((tuple(segments), cutoff, excluded))
        return original(self, segments, cutoff, excluded)

    view = fixture._view()
    identities = tuple(replace(IDENTITIES[0], code=n, provider_player_id=n) for n in range(1, 801))
    expected = ordinary(view, identities)
    monkeypatch.setattr(RetrospectiveCompetitiveWorkloadView, "_resolve", spy)
    assert cached(view, identities) == expected
    assert len(calls) == 3
    assert len(set(calls)) == 3


def test_same_gw_excludes_all_dgw_legs_and_future_truncation_is_exact():
    earlier = fixture._version(fixture._fixture(24, 1))
    postponed = fixture._version(fixture._fixture(48, 2))
    future = fixture._version(fixture._fixture(-24, 3))
    all_view = fixture._view(
        fixtures=(earlier.fixture, postponed.fixture, future.fixture),
        versions=(earlier, postponed, future),
        memberships=(),
    )
    short_view = fixture._view(fixtures=(earlier.fixture,), versions=(earlier,), memberships=())
    excluded = frozenset({postponed.fixture.key, future.fixture.key})
    result = cached(all_view, excluded=excluded)
    assert result == ordinary(all_view, excluded=excluded)
    assert result == cached(short_view, excluded=excluded)
    assert result[0].windows[0].witnessed_fixtures == (earlier.fixture.key,)


@pytest.mark.parametrize("hours", [1, 6, 7])
def test_completion_proxy_same_as_original_at_six_hour_boundary(hours):
    match = fixture._fixture(hours)
    version = replace(fixture._version(match), maximum_retained_event_timestamp=None)
    view = fixture._view(fixtures=(match,), versions=(version,))
    result = cached(view)
    assert result == ordinary(view)
    assert result[0].windows[0].nominal_minutes_lower_bound == (90 if hours > 6 else None)


def test_future_end_remains_unknown_even_when_kickoff_is_old():
    version = replace(fixture._version(), verified_end_at=fixture.AS_OF)
    view = fixture._view(versions=(version,))
    assert cached(view) == ordinary(view)
    assert cached(view)[0].windows[0].nominal_minutes_lower_bound is None


def test_null_and_explicit_zero_positive_cameos_are_not_conflated():
    first = fixture._version()
    versions = replace(
        first,
        observations=(
            replace(first.observations[0], nominal_minutes=0, started=False),
            WorkloadObservation(1002, 1002, 101, None, False, True),
        ),
    )
    view = fixture._view(versions=(versions,))
    result = cached(view)
    assert result == ordinary(view)
    assert result[0].windows[0].nominal_minutes_lower_bound == 0
    assert result[1].windows[0].nominal_minutes_lower_bound is None
    assert result[0].windows[0].appearances_lower_bound == 1
    assert result[1].windows[0].appearances_lower_bound == 1


def test_transfer_scope_earliest_revision_and_original_late_provenance_survive():
    first = fixture._version()
    old_club = fixture._version(fixture._fixture(96, 2, 102))
    later = replace(
        first,
        capture_id="later",
        capture_known_at=fixture.KNOWN + timedelta(minutes=1),
        observations=(replace(first.observations[0], nominal_minutes=1),),
    )
    view = fixture._view(
        fixtures=(first.fixture, old_club.fixture),
        versions=(later, old_club, first),
        memberships=(),
    )
    result = cached(view)
    assert result == ordinary(view)
    assert result[0].windows[1].nominal_minutes_lower_bound == 180
    assert result[0].selected_versions == (first, old_club)
    assert all(v.capture_known_at > fixture.AS_OF for v in result[0].selected_versions)
    assert result[0].exact_player_rest_hours is None
    assert "continuous_player_membership_unproved" in result[0].windows[1].unknown_reasons


def test_cache_does_not_survive_a_different_batch_source_or_cutoff():
    first = fixture._version()
    view = fixture._view(versions=(first,))
    before = cached(view)
    changed = replace(first, observations=(replace(first.observations[0], nominal_minutes=1),))
    assert cached(fixture._view(versions=(changed,)))[0].windows[0].nominal_minutes_lower_bound == 1
    later = fixture.AS_OF + timedelta(days=4)
    assert cached(view, as_of=later) == ordinary(view, as_of=later)
    assert cached(view) == before


def test_cached_containers_are_fresh_and_private_scope_is_bounded():
    view = _BatchView(fixture._view())
    segments = [(101, fixture.START, fixture.AS_OF)]
    selected, expected, issues = view._resolve(segments, fixture.AS_OF, frozenset())
    selected.clear()
    issues.append("injected_player_specific_error")
    again = view._resolve(segments, fixture.AS_OF, frozenset())
    assert len(again[0]) == 1 and again[1] == expected and not again[2]
    for hours in (1, 2):
        view._resolve(
            [(101, fixture.AS_OF - timedelta(hours=hours), fixture.AS_OF)],
            fixture.AS_OF,
            frozenset(),
        )
    with pytest.raises(ValueError, match="bounded"):
        view._resolve(
            [(101, fixture.AS_OF - timedelta(hours=3), fixture.AS_OF)], fixture.AS_OF, frozenset()
        )


@pytest.mark.parametrize("conflict", ["code", "provider", "exact"])
def test_duplicate_or_ambiguous_identity_is_not_a_second_player(conflict):
    first = IDENTITIES[0]
    second = (
        replace(first, provider_player_id=999)
        if conflict == "code"
        else (replace(first, code=999) if conflict == "provider" else first)
    )
    with pytest.raises(ValueError, match="duplicates or ambiguity"):
        cached(fixture._view(), (first, second))


def test_original_identity_conflict_still_fails_closed():
    version = replace(
        fixture._version(), observations=(WorkloadObservation(1001, 999, 101, 90, True, True),)
    )
    view = fixture._view(versions=(version,))
    with pytest.raises(ValueError, match="identity witness"):
        cached(view)


def test_no_identity_is_not_fabricated_as_zero_or_sent_to_resolver(monkeypatch):
    def forbidden(*_args):
        raise AssertionError("no exact identities should not resolve any fixture")

    monkeypatch.setattr(RetrospectiveCompetitiveWorkloadView, "_resolve", forbidden)
    assert cached(fixture._view(), ()) == ()


def test_prospective_or_other_capability_is_not_accepted():
    with pytest.raises(ValueError, match="separately retrospective"):
        cached(object())
