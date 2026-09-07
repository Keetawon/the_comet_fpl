"""Synthetic source-precedence and duration tests; no real pilot replay."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from fpl.config import repo_root
from fpl.transform.competitive_participation import ParticipationError, parse_participation
from fpl.transform.competitive_participation_v2 import (
    INTERPRETATION_ID,
    RESULT_TYPES,
    parse_participation_v2,
)

KICKOFF = datetime(2025, 9, 14, 15, tzinfo=UTC)
CAPTURE = datetime(2026, 9, 7, tzinfo=UTC)
INTERPRETED = CAPTURE + timedelta(hours=8)


def sample() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    match = {
        "matchId": "1",
        "season": "2025",
        "competitionId": "8",
        "kickoff": KICKOFF.isoformat(),
        "period": "FullTime",
        "resultType": "NormalResult",
        "clock": "96",
        "homeTeam": {"id": "3", "score": 1},
        "awayTeam": {"id": "31", "score": 0},
    }
    lineups: dict[str, Any] = {}
    events: dict[str, Any] = {}
    for label, node, team, shift in (("home", "homeTeam", 3, 0), ("away", "awayTeam", 31, 100)):
        lineups[f"{label}_team"] = {
            "teamId": str(team),
            "formation": {
                "teamId": str(team),
                "lineup": [[str(i + shift) for i in range(1, 12)]],
                "subs": [str(12 + shift), str(13 + shift)],
            },
            "players": [
                {
                    "id": str(i + shift),
                    "position": "Midfielder" if i <= 11 else "Substitute",
                    "subPosition": "Midfielder",
                }
                for i in range(1, 14)
            ],
        }
        events[node] = {"id": str(team), "subs": [], "cards": [], "goals": []}
    return match, lineups, events


def event(minute: int, *, period: str = "SecondHalf", **fields: Any) -> dict[str, Any]:
    stamp = KICKOFF + timedelta(minutes=minute + 15)
    return {"period": period, "time": str(minute), "timestamp": stamp.isoformat(), **fields}


def parsed(data: tuple[dict[str, Any], dict[str, Any], dict[str, Any]]) -> dict[str, Any]:
    return parse_participation_v2(*data, known_at=CAPTURE, interpretation_known_at=INTERPRETED)


def row(result: dict[str, Any], pid: int = 1) -> dict[str, Any]:
    return next(item for item in result["sides"][0]["rows"] if item["provider_player_id"] == pid)


def extra_roster(data: tuple[dict[str, Any], dict[str, Any], dict[str, Any]]) -> None:
    data[1]["home_team"]["players"].append({"id": "14", "position": "Goalkeeper"})


def test_observed_formation_precedence_preserves_every_original_byte_object() -> None:
    data = sample()
    extra_roster(data)
    original = deepcopy(data)
    with pytest.raises(ParticipationError, match="observed 12"):
        parse_participation(*data, known_at=CAPTURE)
    result = parsed(data)
    assert data == original
    assert result["raw_match"] == data[0]
    assert result["raw_lineups"] == data[1]
    assert result["raw_events"] == data[2]
    assert result["sides"][0]["unassigned_roster_ids"] == [14]
    assert row(result, 14)["raw_player"] == data[1]["home_team"]["players"][-1]
    assert all(
        row(result, 14)[key] is None
        for key in ("started", "on_bench", "appeared", "nominal_minutes")
    )
    assert row(result)["nominal_minutes"] == 90


@pytest.mark.parametrize("formation", [None, {}])
def test_absent_formation_uses_original_validated_fallback(formation: Any) -> None:
    data = sample()
    data[1]["home_team"]["formation"] = formation
    legacy = parse_participation(*data, known_at=CAPTURE)
    current = parsed(data)
    for before, after in zip(legacy["sides"][0]["rows"], current["sides"][0]["rows"], strict=True):
        assert all(after[key] == value for key, value in before.items())
    assert current["sides"][0]["membership_policy"].startswith("validated_v1")


@pytest.mark.parametrize(
    "change",
    [
        {"lineup": [["1"] * 11]},
        {"lineup": [[str(i) for i in range(1, 11)]]},
        {"lineup": [[str(i) for i in range(1, 11)] + ["999"]]},
        {"subs": ["12", "12"]},
        {"subs": ["1", "12"]},
        {"teamId": "31"},
        {"lineup": None},
        {"subs": None},
    ],
)
def test_invalid_present_formation_never_falls_back(change: dict[str, Any]) -> None:
    data = sample()
    data[1]["home_team"]["formation"].update(change)
    with pytest.raises(ParticipationError):
        parsed(data)


def test_duplicate_raw_ids_and_cross_side_ids_rejected_before_exclusion() -> None:
    data = sample()
    extra_roster(data)
    data[1]["away_team"]["players"].append({"id": "14", "position": "Goalkeeper"})
    with pytest.raises(ParticipationError, match="both fixture sides"):
        parsed(data)
    data = sample()
    data[1]["home_team"]["players"].append(deepcopy(data[1]["home_team"]["players"][0]))
    with pytest.raises(ParticipationError, match="duplicate raw"):
        parsed(data)


@pytest.mark.parametrize("kind", ["sub", "goal", "assist"])
def test_unassigned_player_cannot_have_participation_event(kind: str) -> None:
    data = sample()
    extra_roster(data)
    if kind == "sub":
        data[2]["homeTeam"]["subs"] = [event(60, playerOnId="14", playerOffId="1")]
    else:
        data[2]["homeTeam"]["goals"] = [
            event(
                60,
                playerId="14" if kind == "goal" else "1",
                assistPlayerId="14" if kind == "assist" else None,
            )
        ]
    with pytest.raises(ParticipationError):
        parsed(data)


@pytest.mark.parametrize("card_type", ["Yellow", "Red", "SecondYellow"])
def test_unassigned_roster_cards_are_retained_without_fabricated_exposure(card_type: str) -> None:
    data = sample()
    extra_roster(data)
    data[2]["homeTeam"]["cards"] = [event(60, playerId="14", type=card_type)]
    result = parsed(data)
    assert row(result, 14)["appeared"] is None
    assert row(result, 14)["nominal_minutes"] is None
    assert result["sides"][0]["discipline"][0]["context"] == "unassigned_roster"
    assert row(result)["nominal_minutes"] == 90


def test_actual_bench_card_and_active_second_yellow_keep_legacy_semantics() -> None:
    data = sample()
    data[2]["homeTeam"]["cards"] = [
        event(60, playerId="12", type="SecondYellow"),
        event(70, playerId="1", type="SecondYellow"),
    ]
    result = parsed(data)
    assert row(result, 12)["nominal_minutes"] == 0
    assert row(result, 12)["appeared"] is False
    assert row(result)["nominal_minutes"] == 70


def test_membership_adapter_never_publishes_changed_provider_position() -> None:
    data = sample()
    data[1]["home_team"]["formation"]["lineup"][0][-1] = "12"
    data[1]["home_team"]["formation"]["subs"] = ["11", "13"]
    result = parsed(data)
    assert row(result, 12)["started"] is True
    assert row(result, 12)["provider_position"] == "Substitute"
    assert row(result, 11)["on_bench"] is True
    assert row(result, 11)["provider_position"] == "Midfielder"


def test_capture_time_unchanged_and_interpretation_has_separate_availability() -> None:
    result = parsed(sample())
    assert result["known_at"] == CAPTURE.isoformat()
    assert result["interpretation_known_at"] == INTERPRETED.isoformat()
    assert result["available_at"] == INTERPRETED.isoformat()
    assert result["interpretation_id"] == INTERPRETATION_ID
    assert result["exact_match_end_timestamp"] is None
    assert result["exact_rest_hours"] is None


@pytest.mark.parametrize("result_type", ["Aggregate", "AfterExtraTime", "PenaltyShootout"])
def test_120_minutes_requires_clock_and_explicit_extra_period(result_type: str) -> None:
    data = sample()
    data[0].update(resultType=result_type, clock="122")
    assert row(parsed(data))["nominal_minutes"] is None
    data[2]["homeTeam"]["goals"] = [
        event(98, period="ExtraFirstHalf", playerId="1", assistPlayerId=None)
    ]
    result = parsed(data)
    assert row(result)["nominal_minutes"] == 120
    assert result["raw_result_type"] == result_type
    assert result["raw_match"]["resultType"] == result_type


def test_aggregate_can_mean_regulation_but_afterextratime_cannot() -> None:
    data = sample()
    data[0]["resultType"] = "Aggregate"
    assert row(parsed(data))["nominal_minutes"] == 90
    data[0]["resultType"] = "AfterExtraTime"
    result = parsed(data)
    assert row(result)["nominal_minutes"] is None
    assert result["sides"][0]["errors"]


@pytest.mark.parametrize("result_type", [None, "Unknown", "Live"])
def test_unknown_result_not_assumed_regulation(result_type: Any) -> None:
    data = sample()
    data[0]["resultType"] = result_type
    with pytest.raises(ParticipationError):
        parsed(data)


def test_late_substitution_preserves_appearance_without_rounding_to_fpl_one() -> None:
    data = sample()
    data[2]["homeTeam"]["subs"] = [event(91, playerOnId="12", playerOffId="1")]
    result = parsed(data)
    assert row(result, 12)["nominal_minutes"] == 0
    assert row(result, 12)["appeared"] is True


def test_unknown_future_goal_evidence_is_rejected() -> None:
    data = sample()
    data[2]["homeTeam"]["goals"] = [
        event(60, playerId="1", timestamp=(CAPTURE + timedelta(days=1)).isoformat())
    ]
    with pytest.raises(ParticipationError, match="capture bounds"):
        parsed(data)


def test_v2_contract_and_frozen_parser_hash() -> None:
    root = repo_root()
    config = yaml.safe_load((root / "config/competitive_participation_v2.yaml").read_text())
    assert config["interpretation_id"] == INTERPRETATION_ID
    assert set(config["allowed_completed_result_types"]) == RESULT_TYPES
    assert config["rewrite_raw_payloads"] is False
    source = Path(root / "src/fpl/transform/competitive_participation.py")
    assert hashlib.sha256(source.read_bytes()).hexdigest() == config["frozen_v1_parser_sha256"]
