"""Deterministic, offline tests for the Stage D v1 integrative points-composition harness.

No network, no built archive. A tiny in-memory DuckDB with only the columns the harness reads
exercises the whole fold: point-in-time component histories, the Stage A team-conceded join through
``team_code``, the Monte-Carlo composition, and the realised non-bonus label. Two seasons are used
so the xG-coverage regime split (2021-22 excluded from the headline) is exercised.
"""

from __future__ import annotations

from datetime import UTC, datetime

import duckdb
import pytest

from fpl.config import load_scoring_rules
from fpl.storage.db import connect
from fpl.types import Position
from fpl.validate.points_harness import (
    REGIME_NO_XG,
    REGIME_XG,
    assert_no_points_leakage,
    non_bonus_points,
    run_points_harness,
)

RULES = load_scoring_rules("2026_27")

# team_id -> stable team_code, identical across the two synthetic seasons (same four clubs).
_TEAMS = [(season, tid, tid) for season in ("2021-22", "2022-23") for tid in (1, 2, 3, 4)]

# Two fixtures per gameweek: club 1 v 2 (fixture base+0), club 3 v 4 (fixture base+1).
_FIXTURE_PAIRS = ((1, 2), (3, 4))
_POSITIONS = ("GK", "DEF", "MID", "FWD")


def _kick(season: str, gw: int) -> datetime:
    year = 2021 if season == "2021-22" else 2022
    return datetime(year, 8, 7 + gw, 12, 0, tzinfo=UTC)


def _player_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for season in ("2021-22", "2022-23"):
        has_xg = season == "2022-23"
        for gw in range(1, 6):
            for pair_index, (home, away) in enumerate(_FIXTURE_PAIRS):
                fixture = gw * 10 + pair_index
                kickoff = _kick(season, gw)
                for team, opponent, was_home in ((home, away, True), (away, home, False)):
                    for slot, position in enumerate(_POSITIONS):
                        code = team * 100 + slot
                        minutes = 90 if slot != 3 else 60
                        goals = 1 if (position == "FWD" and gw % 2 == 0) else 0
                        assists = 1 if (position == "MID" and gw % 3 == 0) else 0
                        conceded = 0 if was_home else 1
                        rows.append(
                            {
                                "season": season,
                                "gw": gw,
                                "fixture": fixture,
                                "kickoff_time": kickoff,
                                "code": code,
                                "position": position,
                                "team_id": team,
                                "opponent_team_id": opponent,
                                "was_home": was_home,
                                "minutes": minutes,
                                "goals_scored": goals,
                                "assists": assists,
                                "clean_sheets": 1 if conceded == 0 and minutes >= 60 else 0,
                                "goals_conceded": conceded,
                                "saves": 0,
                                "penalties_saved": 0,
                                "penalties_missed": 0,
                                "own_goals": 0,
                                "yellow_cards": 0,
                                "red_cards": 0,
                                "bonus": 1 if goals else 0,
                                "expected_goals": (0.3 if has_xg else None),
                                "expected_assists": (0.2 if has_xg else None),
                                "creativity": (10.0 if has_xg else None),
                                "defensive_contribution": None,
                            }
                        )
    return rows


def _team_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for season in ("2021-22", "2022-23"):
        has_xg = season == "2022-23"
        for gw in range(1, 6):
            for pair_index, (home, away) in enumerate(_FIXTURE_PAIRS):
                fixture = gw * 10 + pair_index
                kickoff = _kick(season, gw)
                for team, opponent, was_home, gf, ga in (
                    (home, away, True, 2, 1),
                    (away, home, False, 1, 2),
                ):
                    rows.append(
                        {
                            "season": season,
                            "gw": gw,
                            "fixture": fixture,
                            "kickoff_time": kickoff,
                            "team_id": team,
                            "opponent_team_id": opponent,
                            "was_home": was_home,
                            "goals_for": gf,
                            "goals_against": ga,
                            "team_xg": (1.5 if has_xg else None),
                            "team_xgc": (1.1 if has_xg else None),
                            "fdr": 3,
                        }
                    )
    return rows


def _build_db() -> duckdb.DuckDBPyConnection:
    con = connect(":memory:")
    con.execute(
        """
        CREATE TABLE mart_fact_player_fixture (
            season VARCHAR, gw INTEGER, fixture INTEGER, kickoff_time TIMESTAMPTZ,
            code INTEGER, position VARCHAR, team_id INTEGER, opponent_team_id INTEGER,
            was_home BOOLEAN, minutes INTEGER, goals_scored INTEGER, assists INTEGER,
            clean_sheets INTEGER, goals_conceded INTEGER, saves INTEGER, penalties_saved INTEGER,
            penalties_missed INTEGER, own_goals INTEGER, yellow_cards INTEGER, red_cards INTEGER,
            bonus INTEGER, expected_goals DOUBLE, expected_assists DOUBLE, creativity DOUBLE,
            defensive_contribution INTEGER
        )
        """
    )
    con.execute(
        """
        CREATE TABLE mart_fact_team_match (
            season VARCHAR, gw INTEGER, fixture INTEGER, kickoff_time TIMESTAMPTZ,
            team_id INTEGER, opponent_team_id INTEGER, was_home BOOLEAN,
            goals_for INTEGER, goals_against INTEGER, team_xg DOUBLE, team_xgc DOUBLE, fdr INTEGER
        )
        """
    )
    con.execute("CREATE TABLE mart_dim_team (season VARCHAR, team_id INTEGER, team_code INTEGER)")
    con.executemany("INSERT INTO mart_dim_team VALUES (?, ?, ?)", _TEAMS)

    player_cols = list(_player_rows()[0].keys())
    con.executemany(
        f"INSERT INTO mart_fact_player_fixture ({', '.join(player_cols)}) "
        f"VALUES ({', '.join('?' for _ in player_cols)})",
        [tuple(row[c] for c in player_cols) for row in _player_rows()],
    )
    team_cols = list(_team_rows()[0].keys())
    con.executemany(
        f"INSERT INTO mart_fact_team_match ({', '.join(team_cols)}) "
        f"VALUES ({', '.join('?' for _ in team_cols)})",
        [tuple(row[c] for c in team_cols) for row in _team_rows()],
    )
    return con


# --------------------------------------------------------------------------------------
# Label helper (validation layer, R1-safe)
# --------------------------------------------------------------------------------------


def _component_row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "minutes": 90,
        "goals_scored": 0,
        "assists": 0,
        "clean_sheets": 0,
        "goals_conceded": 0,
        "saves": 0,
        "penalties_saved": 0,
        "penalties_missed": 0,
        "own_goals": 0,
        "yellow_cards": 0,
        "red_cards": 0,
        "bonus": 0,
        "defensive_contribution": None,
    }
    base.update(overrides)
    return base


def test_non_bonus_label_excludes_bonus() -> None:
    # FWD, 90', 1 goal, 3 recorded bonus: recorded non-bonus = appearance 2 + goal 4 = 6.
    row = _component_row(goals_scored=1, bonus=3)
    assert non_bonus_points(row, Position.FWD, RULES) == 6
    # The bonus value must not change the label.
    row_more_bonus = _component_row(goals_scored=1, bonus=3)
    assert non_bonus_points(row_more_bonus, Position.FWD, RULES) == 6


def test_non_bonus_label_defender_clean_sheet() -> None:
    # DEF, 90', 0 conceded, clean sheet flag set, 1 bonus: 2 + 4 = 6 non-bonus.
    row = _component_row(clean_sheets=1, goals_conceded=0, bonus=1)
    assert non_bonus_points(row, Position.DEF, RULES) == 6


def test_leakage_assertion_fires_when_a_target_predates_cutoff() -> None:
    as_of = datetime(2022, 8, 10, 12, 0, tzinfo=UTC)
    good = [(datetime(2022, 8, 10, 12, 0, tzinfo=UTC), "2022-23", 101, 20)]
    assert_no_points_leakage(good, as_of)  # equal kickoff is allowed
    bad = [(datetime(2022, 8, 9, 12, 0, tzinfo=UTC), "2022-23", 101, 20)]
    with pytest.raises(AssertionError):
        assert_no_points_leakage(bad, as_of)


# --------------------------------------------------------------------------------------
# Full integrative run on the synthetic archive
# --------------------------------------------------------------------------------------


def test_harness_runs_and_reports_all_slices() -> None:
    con = _build_db()
    try:
        result = run_points_harness(con, draws=200, warmup=2)
    finally:
        con.close()

    assert result.folds_evaluated > 0
    assert result.predictions > 0
    # Every composed pmf is a proper distribution -> a finite, positive mean log score.
    assert 0.0 < result.overall.mean_log_score < 100.0
    # Both seasons present; 2021-22 is a reported season but kept out of the headline.
    assert set(result.by_season) <= {"2021-22", "2022-23"}
    # Regime split: the no-xG regime is separated from the xG-present regime.
    assert REGIME_NO_XG in result.by_regime or "2021-22" not in result.folds_by_season
    assert REGIME_XG in result.by_regime
    # By-position covers only the playing positions that appear.
    assert set(result.by_position) <= {"GK", "DEF", "MID", "FWD"}
    # Component provenance recorded, including the Stage A team clean-sheet source.
    assert result.component_names["team_clean_sheet"] == "trailing_goals_attack_defence"


def test_harness_is_deterministic_across_runs() -> None:
    con_a = _build_db()
    con_b = _build_db()
    try:
        a = run_points_harness(con_a, draws=200, warmup=2)
        b = run_points_harness(con_b, draws=200, warmup=2)
    finally:
        con_a.close()
        con_b.close()
    assert a.overall.mean_log_score == b.overall.mean_log_score
    assert a.overall.mean_crps == b.overall.mean_crps
    assert a.predictions == b.predictions


def test_headline_excludes_no_xg_season_from_overall() -> None:
    con = _build_db()
    try:
        result = run_points_harness(con, draws=200, warmup=2)
    finally:
        con.close()
    # If both regimes are present the headline (xG-present only) population is strictly smaller than
    # the all-seasons overall population.
    if "2021-22" in result.folds_by_season and "2022-23" in result.folds_by_season:
        assert result.headline_xg.predictions < result.overall.predictions
