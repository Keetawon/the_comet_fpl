"""Coverage eligibility is decided without predictions or score inspection."""

from datetime import UTC, datetime
from typing import Any

import pytest

from fpl.validate.chance_coverage import coverage, eligible_seasons


def rows() -> list[dict[str, Any]]:
    return [
        {
            "key": f"{season}:{fixture}:{team}",
            "season": season,
            "fixture": fixture,
            "team_code": team,
            "opponent_team_code": other,
            "was_home": home,
            "gw": (fixture - 1) // 10 + 1,
            "kickoff_time": datetime(2024, 1, 1, tzinfo=UTC),
            "sdp_match_id": fixture,
            "capture_id": f"{season}-{fixture}",
            "goals": 1,
            "goals_allowed": 1,
            "expected_goals": 1.1,
            "shots": 10,
        }
        for season in ("2023-24", "2024-25")
        for fixture in range(1, 381)
        for team, other, home in ((3, 8, True), (8, 3, False))
    ]


def test_complete_paired_coverage_only_rule() -> None:
    data = rows()
    assert eligible_seasons(data) == ["2024-25"]
    assert coverage(data)["2024-25"]["paired_joint_sides"] == 760
    for row in data:
        if row["season"] == "2024-25" and row["fixture"] <= 19 and row["was_home"]:
            row["expected_goals"] = None
    assert coverage(data)["2024-25"]["paired_joint_sides"] == 722
    assert eligible_seasons(data) == ["2024-25"]
    data[-1]["expected_goals"] = None
    assert eligible_seasons(data) == []


def test_missing_and_zero_distinct_and_incomplete_season_not_eligible() -> None:
    data = rows()
    data[0]["shots"] = 0
    data[1]["shots"] = None
    counts = coverage(data)["2023-24"]["targets"]["shots"]
    assert counts == {"measured": 759, "explicit_zero": 1, "missing": 1}
    assert eligible_seasons(data[:-2]) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("opponent_team_code", 99),
        ("was_home", False),
        ("gw", 99),
        ("sdp_match_id", 99),
        ("capture_id", "other"),
        ("goals_allowed", 2),
    ],
)
def test_identity_contradictions_fail_closed(field: str, value: object) -> None:
    data = rows()
    data[0][field] = value
    with pytest.raises(ValueError, match="reciprocal"):
        coverage(data)


@pytest.mark.parametrize("threshold", [0, -1, 1.01, float("nan")])
def test_invalid_coverage_threshold(threshold: float) -> None:
    with pytest.raises(ValueError, match="threshold"):
        eligible_seasons(rows(), threshold)


def test_duplicate_identity_refuses() -> None:
    data = rows()
    with pytest.raises(ValueError, match="duplicate"):
        coverage([*data, data[0]])
