"""Offline prospective competitive exposure; no retrospective evidence is relabelled."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta

import pytest

from fpl.features.sdp_workload import workload_features
from fpl.jobs.capture_sdp_workload import COMPETITIONS, normalize_bundle
from fpl.transform.competitive_participation import exact_crosswalk

from .test_competitive_participation_v2 import KICKOFF, sample
from .test_pl_sdp_revision_pit import _raw


def normalized(competition=8):
    match, lineups, events = sample()
    match["competitionId"] = str(competition)
    capture = KICKOFF + timedelta(hours=3)
    sources = {
        name: (name, _raw(name, body, capture))
        for name, body in (("metadata", match), ("lineups", lineups), ("events", events))
    }
    registry = [
        {"season": "2025-26", "opta_code": f"p{i}", "code": 10000 + i} for i in range(1, 114)
    ]
    return normalize_bundle(
        metadata=match,
        sources=sources,
        season="2025-26",
        registry=registry,
        team_codes={3, 31},
        identity_known_at=KICKOFF,
        interpreted_at=capture + timedelta(seconds=1),
    )


@pytest.mark.parametrize("competition", COMPETITIONS)
def test_all_six_competitions_supply_positive_witnessed_minutes_only(competition):
    value = normalized(competition)
    assert value["valid"], value["errors"]
    report = workload_features([value], code=10001, team_code=3, cutoff=KICKOFF + timedelta(days=1))
    assert report["witnessed_minutes_last_72h_lower_bound"] == 90
    assert report["minutes_last_72h"] is None
    assert report["player_rest_hours"] is None
    assert report["team_rest_hours"] is None
    assert report["played90"] is True
    assert report["played120"] is False


def test_missing_and_future_capture_never_mean_zero_workload():
    value = normalized(1)
    cutoff = KICKOFF + timedelta(hours=2)
    for versions in ([], [value]):
        result = workload_features(versions, code=10001, team_code=3, cutoff=cutoff)
        assert result["minutes_last_72h"] is None
        assert result["witnessed_minutes_last_72h_lower_bound"] is None
        assert result["started_midweek"] is None
        assert result["played120"] is None


def test_unresolved_revision_fails_window_without_rewriting_old_cutoff():
    value = normalized(5)
    revision = deepcopy(value)
    revision.update(
        valid=False, version_id="revision", known_at=(KICKOFF + timedelta(days=2)).isoformat()
    )
    old = workload_features(
        [value, revision], code=10001, team_code=3, cutoff=KICKOFF + timedelta(days=1)
    )
    assert old["witnessed_minutes_last_72h_lower_bound"] == 90
    new = workload_features(
        [value, revision], code=10001, team_code=3, cutoff=KICKOFF + timedelta(days=2, hours=1)
    )
    assert new["witnessed_minutes_last_72h_lower_bound"] is None


def test_exact_provider_identity_does_not_fuzzy_match_names_or_reused_ids():
    registry = [
        {"season": "2024-25", "opta_code": "p1", "code": 10001},
        {"season": "2025-26", "web_name": "Identical Name", "code": 1},
    ]
    mapping, errors = exact_crosswalk([1], registry, season="2025-26")
    assert mapping[1] is None and errors
