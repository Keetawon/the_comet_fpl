"""Synthetic structural labels: source order never becomes a tactical role claim."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from fpl.transform.competitive_participation import ParticipationError
from fpl.transform.competitive_participation_v2 import parse_participation_v2
from fpl.transform.player_role_source import available_before, parse_role_structure
from tests.test_competitive_participation_v2 import CAPTURE, INTERPRETED, KICKOFF, event, sample


def structural_sample() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    data = sample()
    for label, shift in (("home", 0), ("away", 100)):
        side = data[1][f"{label}_team"]
        side["formation"]["formation"] = "4-2-3-1"
        side["formation"]["lineup"] = [
            [str(1 + shift)],
            [str(i + shift) for i in range(2, 6)],
            [str(i + shift) for i in range(6, 8)],
            [str(i + shift) for i in range(8, 11)],
            [str(11 + shift)],
        ]
        side["players"][0]["position"] = "Goalkeeper"
    return data


def registry() -> list[dict[str, Any]]:
    return [
        {"season": "2025-26", "code": pid + 500, "opta_code": f"p{pid}", "position": "MID"}
        for pid in [*range(1, 14), *range(101, 114)]
    ]


def parsed(
    data: tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None = None, **kwargs: Any
) -> dict[str, Any]:
    options = {
        "season": "2025-26",
        "fixture": 9,
        "registry": registry(),
        "source_known_at": None,
        "capture_known_at": CAPTURE,
        "interpretation_known_at": INTERPRETED,
        "identity_known_at": CAPTURE,
        "provenance": {"lineups_sha256": "a" * 64, "events_sha256": "b" * 64},
        **kwargs,
    }
    return parse_role_structure(*(data or structural_sample()), **options)


def row(result: dict[str, Any], pid: int = 1) -> dict[str, Any]:
    return next(item for item in result["sides"][0]["rows"] if item["provider_player_id"] == pid)


def test_exact_eleven_ordered_lines_preserved_without_spatial_claim() -> None:
    data = structural_sample()
    data[1]["home_team"]["formation"]["lineup"][1].reverse()
    result = parsed(data)
    side = result["sides"][0]
    assert side["formation_lineup"] == data[1]["home_team"]["formation"]["lineup"]
    assert side["formation_line_sizes"] == [1, 4, 2, 3, 1]
    assert side["formation_annotation_matches"] is True
    assert sum(item["started"] is True for item in side["rows"]) == 11
    assert row(result, 5)["formation_member_index"] == 0
    assert row(result, 5)["formation_line_index"] == 1
    assert row(result, 5)["formation_band"] == "defensive_line"
    assert row(result, 8)["formation_band"] == "interior_line_2"
    assert row(result, 11)["formation_band"] == "forward_line"
    assert side["within_line_semantics_validated"] is False
    for item in side["rows"]:
        assert "observed_role_family" not in item
        assert "tactical_side" not in item
        assert item["oop_diagnostic"] == "UNKNOWN"


@pytest.mark.parametrize(
    "change",
    [
        {"lineup": [["1"] * 11]},
        {"lineup": [[str(i) for i in range(1, 11)]]},
        {"lineup": [[str(i) for i in range(1, 11)] + ["999"]]},
        {"lineup": [[str(i) for i in range(1, 12)], []]},
        {"subs": ["1", "12"]},
        {"subs": ["12", "12"]},
        {"teamId": "31"},
        {"lineup": None},
    ],
)
def test_malformed_formation_fails_closed(change: dict[str, Any]) -> None:
    data = structural_sample()
    data[1]["home_team"]["formation"].update(change)
    with pytest.raises(ParticipationError):
        parsed(data)


@pytest.mark.parametrize("formation", [None, {}])
def test_missing_formation_retains_membership_with_null_indices(formation: Any) -> None:
    data = structural_sample()
    data[1]["home_team"]["formation"] = formation
    result = parsed(data)
    assert sum(item["started"] is True for item in result["sides"][0]["rows"]) == 11
    assert row(result)["formation_line_index"] is None
    assert row(result)["formation_member_index"] is None
    assert row(result)["formation_band"] is None
    assert row(result)["evidence_level"] == 1


@pytest.mark.parametrize("annotation", [None, "4-3-3", 4231, "4--2-3-1"])
def test_annotation_disagreement_quarantines_bands_but_keeps_source_grouping(
    annotation: Any,
) -> None:
    data = structural_sample()
    data[1]["home_team"]["formation"]["formation"] = annotation
    result = parsed(data)
    assert result["sides"][0]["formation_band_errors"]
    assert row(result, 2)["formation_line_index"] == 1
    assert row(result, 2)["formation_band"] is None
    assert row(result, 2)["started"] is True


def test_initial_goalkeeper_requires_source_corroboration() -> None:
    data = structural_sample()
    data[1]["home_team"]["players"][0]["position"] = "Midfielder"
    result = parsed(data)
    assert row(result)["formation_band"] is None
    assert result["sides"][0]["formation_band_errors"]


def test_raw_payload_objects_are_immutable_and_result_is_detached() -> None:
    data = structural_sample()
    before = json.dumps(data, sort_keys=True).encode()
    result = parsed(data)
    row(result)["raw_player"]["position"] = "Changed"
    result["sides"][0]["formation_lineup"][0][0] = "Changed"
    assert json.dumps(data, sort_keys=True).encode() == before


def test_unassigned_roster_retains_null_exposure_and_position() -> None:
    data = structural_sample()
    data[1]["home_team"]["players"].append({"id": "14", "position": "Defender"})
    unknown = row(parsed(data), 14)
    for key in ("started", "on_bench", "appeared", "nominal_minutes", "fpl_code", "fpl_position"):
        assert unknown[key] is None
    assert unknown["formation_line_index"] is None
    assert unknown["provider_sub_position"] is None


def test_only_exact_season_qualified_opta_identity_can_map() -> None:
    anchors = registry()
    anchors[0]["opta_code"] = "p0001"
    anchors[0]["name"] = "Identical name"
    anchors[1]["season"] = "2024-25"
    result = parsed(registry=anchors)
    assert row(result)["fpl_code"] is None
    assert row(result, 2)["fpl_code"] is None
    assert row(result, 3)["fpl_code"] == 503
    assert row(result, 3)["fpl_position"] == "MID"


@pytest.mark.parametrize("collision", ["duplicate_anchor", "contradictory_anchor", "shared_code"])
def test_identity_collision_only_quarantines_affected_players(collision: str) -> None:
    anchors = registry()
    if collision == "duplicate_anchor":
        anchors.append(deepcopy(anchors[0]))
    elif collision == "contradictory_anchor":
        anchors.append({**anchors[0], "code": 999})
    else:
        anchors[1]["code"] = anchors[0]["code"]
    result = parsed(registry=anchors)
    assert row(result)["fpl_code"] is None
    assert row(result)["identity_errors"]
    assert row(result, 3)["fpl_code"] == 503
    assert row(result, 2)["fpl_code"] == (None if collision == "shared_code" else 502)


def test_actual_observation_cannot_be_target_match_predeadline_feature() -> None:
    observed = row(parsed())
    assert not available_before(observed, KICKOFF - timedelta(hours=1))
    assert not available_before(observed, CAPTURE)
    assert available_before(observed, INTERPRETED)
    assert observed["source_known_at"] is None
    assert observed["available_at"] == INTERPRETED.isoformat()


def test_source_identity_and_interpretation_times_all_bound_availability() -> None:
    publication = CAPTURE - timedelta(hours=1)
    identity = CAPTURE + timedelta(hours=2)
    observed = row(parsed(source_known_at=publication, identity_known_at=identity))
    assert observed["source_known_at"] == publication.isoformat()
    assert observed["capture_known_at"] == CAPTURE.isoformat()
    assert observed["identity_known_at"] == identity.isoformat()
    assert not available_before(observed, INTERPRETED - timedelta(microseconds=1))
    observed["available_at"] = CAPTURE.isoformat()
    assert not available_before(observed, INTERPRETED)


@pytest.mark.parametrize("field", ["source_known_at", "capture_known_at", "identity_known_at"])
def test_interpretation_cannot_predate_needed_evidence(field: str) -> None:
    with pytest.raises(ParticipationError, match="predates"):
        parsed(**{field: INTERPRETED + timedelta(seconds=1)})


def test_knowledge_times_require_aware_instants() -> None:
    with pytest.raises(ParticipationError, match="timezone-aware"):
        parsed(capture_known_at=datetime(2026, 9, 7))
    with pytest.raises(ParticipationError, match="timezone-aware"):
        available_before(row(parsed()), datetime(2026, 9, 8))


def test_substitution_preserves_raw_timing_and_never_inherits_off_player_band() -> None:
    data = structural_sample()
    substitution = event(91, playerOnId="12", playerOffId="2")
    data[2]["homeTeam"]["subs"] = [substitution]
    result = parsed(data)
    observed = result["sides"][0]["substitutions"][0]
    assert observed["raw"] == substitution
    assert all(observed[key] == value for key, value in substitution.items())
    assert row(result, 12)["appeared"] is True
    assert row(result, 12)["nominal_minutes"] == 0
    assert row(result, 12)["formation_band"] is None
    assert row(result, 12)["formation_line_index"] is None


@pytest.mark.parametrize(("on", "off"), [("999", "2"), ("2", "3"), ("12", "13")])
def test_substitution_unknown_or_impossible_identity_is_rejected(on: str, off: str) -> None:
    data = structural_sample()
    data[2]["homeTeam"]["subs"] = [event(60, playerOnId=on, playerOffId=off)]
    with pytest.raises(ParticipationError):
        parsed(data)


def test_substitution_later_than_capture_is_rejected() -> None:
    data = structural_sample()
    data[2]["homeTeam"]["subs"] = [
        event(
            60,
            playerOnId="12",
            playerOffId="2",
            timestamp=(CAPTURE + timedelta(days=1)).isoformat(),
        )
    ]
    with pytest.raises(ParticipationError):
        parsed(data)


def test_event_time_must_not_hide_behind_later_metadata_capture() -> None:
    data = structural_sample()
    data[2]["homeTeam"]["subs"] = [event(60, playerOnId="12", playerOffId="2")]
    with pytest.raises(ParticipationError, match="follows actual capture"):
        parsed(data, event_capture_known_at=KICKOFF + timedelta(minutes=30))


def test_registry_contradiction_outside_match_also_quarantines_identity() -> None:
    anchors = registry()
    anchors.append({**anchors[0], "opta_code": "p9999"})
    result = parsed(registry=anchors)
    assert row(result)["fpl_code"] is None
    assert row(result, 2)["fpl_code"] == 502


@pytest.mark.parametrize("field", ["match", "lineup_team", "event_team", "formation_team"])
def test_reciprocal_match_and_team_identity_rejected(field: str) -> None:
    data = structural_sample()
    if field == "match":
        data[1]["matchId"] = "99"
    elif field == "lineup_team":
        data[1]["home_team"]["teamId"] = "99"
    elif field == "event_team":
        data[2]["homeTeam"]["id"] = "99"
    else:
        data[1]["home_team"]["formation"]["teamId"] = "99"
    with pytest.raises(ParticipationError):
        parsed(data)


def test_provider_season_and_incomplete_match_fail_closed() -> None:
    data = structural_sample()
    with pytest.raises(ParticipationError, match="season identity"):
        parsed(data, season="2024-25")
    data[0]["period"] = "FirstHalf"
    with pytest.raises(ParticipationError, match="completed match"):
        parsed(data)


def test_duration_unknown_does_not_erase_validated_formation_structure() -> None:
    data = structural_sample()
    data[0]["clock"] = None
    result = parsed(data)
    assert row(result)["nominal_minutes"] is None
    assert row(result)["formation_band"] == "goalkeeper_line"
    assert result["sides"][0]["participation_errors"]


def test_name_changes_cannot_change_identity_or_classification() -> None:
    data = structural_sample()
    before = parsed(data)
    for side in data[1].values():
        for player in side["players"]:
            player.update(name="arbitrary renamed player", firstName="other", lastName="other")
    after = parsed(data)
    for first, second in zip(before["sides"][0]["rows"], after["sides"][0]["rows"], strict=True):
        for key in (
            "fpl_code",
            "fpl_position",
            "formation_band",
            "evidence_level",
            "oop_diagnostic",
        ):
            assert first[key] == second[key]


def test_repeat_run_is_deterministic_and_v2_remains_unchanged() -> None:
    data = structural_sample()
    before = parse_participation_v2(*data, known_at=CAPTURE, interpretation_known_at=INTERPRETED)
    first, second = parsed(data), parsed(data)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    after = parse_participation_v2(*data, known_at=CAPTURE, interpretation_known_at=INTERPRETED)
    assert before == after
    source = Path("src/fpl/transform/competitive_participation_v2.py")
    assert hashlib.sha256(source.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == (
        "cf7adc6edea9d07bfc7883186fcab0f5933b777168211a36ef1c443864994492"
    )
