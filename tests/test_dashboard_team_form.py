from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from fpl.publish.team_form import refresh_team_forms


def row(fixture: int, **patch: Any) -> dict[str, Any]:
    return {
        "fixture": fixture,
        "gw": fixture,
        "kickoff_time": f"2026-09-{fixture:02}T14:00:00+00:00",
        "opponent_team_code": 2,
        "was_home": True,
        "goals_for": 2,
        "goals_against": 0,
        "team_xg": 1.5,
        "team_xgc": 0.5,
        **patch,
    }


def record(*rows: dict[str, Any], season: str = "2026-27") -> dict[str, Any]:
    return {"season": season, "team_code": 88, "actuals": list(rows)}


def test_current_promoted_club_form_replaces_archive_and_keeps_short_season() -> None:
    teams = [
        {"season": "2026-27", "team_code": 88, "form": None, "fixtures": [{"lambda_for": 1.23}]},
        {"season": "2026-27", "team_code": 9, "form": {"season": "2024-25"}},
    ]
    final = [
        record(row(1), row(2), row(3)),
        record(row(38, kickoff_time="2025-05-25T14:00:00+00:00"), season="2024-25"),
    ]
    provisional = [record(row(4))]
    before = copy.deepcopy((teams, final, provisional))
    result = refresh_team_forms(teams, final, provisional)
    f = result[0]["form"]
    assert f["season"] == "2026-27"
    assert f["as_at_gw"] == 4
    assert f["windows"]["last_5"]["matches_played"] == 4
    assert f["windows"]["last_5"]["wins"] == 4
    assert f["windows"]["last_5"]["observations"]["fixture_ids"] == [4, 3, 2, 1]
    assert f["windows"]["last_5"]["observations"]["provisional_matches"] == 1
    assert f["windows"]["last_3"]["matches_played"] == 3
    assert result[1]["form"] is None  # No current evidence: never silently use a stale season.
    assert result[0]["fixtures"] == teams[0]["fixtures"]
    assert (teams, final, provisional) == before
    assert json.dumps(result, sort_keys=True) == json.dumps(
        refresh_team_forms(teams, list(reversed(final)), provisional), sort_keys=True
    )


def test_measured_denominators_zero_null_and_finalized_precedence() -> None:
    teams = [{"season": "2026-27", "team_code": 88}]
    final = [record(row(1, team_xg=None, team_xgc=None), row(2, team_xg=0, team_xgc=None))]
    provisional = [record(row(2, team_xg=99), row(3, team_xg=2, team_xgc=None))]
    f = refresh_team_forms(teams, final, provisional)[0]["form"]["windows"]["last_5"]
    assert f["matches_played"] == 3
    assert f["team_xg_per_match"] == 1  # 2 / 2 measured fixtures, not 2 / 3.
    assert f["team_xgc_per_match"] is None
    assert f["observations"]["team_xg_matches"] == 2
    assert f["observations"]["team_xgc_matches"] == 0
    assert f["observations"]["provisional_matches"] == 1
    with pytest.raises(ValueError, match="duplicate"):
        refresh_team_forms(teams, [record(row(1), row(1))], [])
    with pytest.raises(ValueError, match="identity mismatch"):
        refresh_team_forms(teams, final, [record(row(2, opponent_team_code=99))])


def test_match_order_counts_dgw_legs_and_late_rescheduled_fixture() -> None:
    teams = [{"season": "2026-27", "team_code": 88}]
    final = [record(row(1), row(2), row(3), row(4), row(5, gw=2), row(6, gw=3))]
    form = refresh_team_forms(teams, final, [])[0]["form"]
    assert form["windows"]["last_3"]["observations"]["fixture_ids"] == [6, 5, 4]
    assert form["windows"]["last_5"]["matches_played"] == 5
    assert form["windows"]["season_to_date"]["matches_played"] == 6
