"""P1.6b team-form mart at (season, gw, team_code, window) grain.

The unit tests build only the two source marts in a temporary DuckDB.  They intentionally include a
double gameweek, an absent observed gameweek, a cross-season team_id reuse, and an unmeasured-xG
season; no archive or network is required for those cases.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import duckdb
import pytest

from fpl.publish.contract import SEMANTIC_CONTRACT_V1
from fpl.storage.db import initialise, table_columns
from fpl.transform.facts import TeamFormSourceError, build_team_form

SEASON = "2025-26"
KICKOFF = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _con() -> duckdb.DuckDBPyConnection:
    return initialise(":memory:")


def _seed_team_codes(con: duckdb.DuckDBPyConnection) -> None:
    con.executemany(
        """
        INSERT INTO mart_dim_team (season, team_id, team_code, team_name, short_name, pulse_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (SEASON, 1, 101, "Alpha", "ALP", None),
            (SEASON, 2, 102, "Beta", "BET", None),
            ("2021-22", 1, 201, "Gamma", "GAM", None),
        ],
    )


def _insert_match(
    con: duckdb.DuckDBPyConnection,
    *,
    fixture: int,
    gw: int,
    offset_days: int,
    team_id: int = 1,
    opponent_team_id: int = 2,
    season: str = SEASON,
    goals_for: int | None = 0,
    goals_against: int | None = 0,
    team_xg: float | None = None,
    team_xgc: float | None = None,
) -> None:
    con.execute(
        """
        INSERT INTO mart_fact_team_match (
            season, gw, fixture, kickoff_time, team_id, opponent_team_id, was_home,
            goals_for, goals_against, team_xg, team_xgc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            season,
            gw,
            fixture,
            KICKOFF + timedelta(days=offset_days),
            team_id,
            opponent_team_id,
            True,
            goals_for,
            goals_against,
            team_xg,
            team_xgc,
        ],
    )


def _seed_season(con: duckdb.DuckDBPyConnection) -> None:
    """GW2 is a double gameweek; GW7 is absent (blank)."""
    _insert_match(
        con,
        fixture=101,
        gw=1,
        offset_days=0,
        goals_for=2,
        goals_against=1,
        team_xg=1.8,
        team_xgc=0.9,
    )
    _insert_match(
        con,
        fixture=102,
        gw=2,
        offset_days=7,
        goals_for=0,
        goals_against=0,
        team_xg=0.7,
        team_xgc=0.4,
    )
    _insert_match(
        con,
        fixture=103,
        gw=2,
        offset_days=9,
        goals_for=1,
        goals_against=2,
        team_xg=1.1,
        team_xgc=1.6,
    )
    _insert_match(
        con,
        fixture=104,
        gw=3,
        offset_days=16,
        goals_for=3,
        goals_against=0,
        team_xg=2.4,
        team_xgc=0.5,
    )
    _insert_match(
        con,
        fixture=105,
        gw=4,
        offset_days=23,
        goals_for=0,
        goals_against=1,
        team_xg=0.5,
        team_xgc=1.2,
    )
    _insert_match(
        con,
        fixture=106,
        gw=5,
        offset_days=30,
        goals_for=1,
        goals_against=1,
        team_xg=1.0,
        team_xgc=1.0,
    )
    _insert_match(
        con,
        fixture=107,
        gw=6,
        offset_days=37,
        goals_for=2,
        goals_against=2,
        team_xg=1.5,
        team_xgc=1.9,
    )
    _insert_match(
        con,
        fixture=108,
        gw=8,
        offset_days=51,
        goals_for=1,
        goals_against=0,
        team_xg=0.9,
        team_xgc=0.6,
    )


def _form_row(
    con: duckdb.DuckDBPyConnection,
    *,
    season: str = SEASON,
    gw: int,
    team_code: int,
    window: str,
) -> tuple[object, ...]:
    row = con.execute(
        """
        SELECT matches_played, goals_for, goals_against, clean_sheets, wins, draws, losses,
               team_xg, team_xgc, goals_for_per_match, goals_against_per_match,
               team_xg_per_match, team_xgc_per_match
        FROM mart_fact_team_form
        WHERE season = ? AND gw = ? AND team_code = ? AND "window" = ?
        """,
        [season, gw, team_code, window],
    ).fetchone()
    assert row is not None
    return row


def test_double_gameweek_counts_both_legs_and_windows_end_inclusive() -> None:
    con = _con()
    try:
        _seed_team_codes(con)
        _seed_season(con)

        assert build_team_form(con) == 28  # seven observed team-gameweeks x four windows

        row = _form_row(con, gw=2, team_code=101, window="last_3")
        assert row[:7] == (3, 3, 3, 1, 1, 1, 1)
        assert row[7] == pytest.approx(3.6)
        assert row[8] == pytest.approx(2.9)
        assert row[9] == pytest.approx(1.0)
        assert row[10] == pytest.approx(1.0)
        assert row[11] == pytest.approx(1.2)
        assert row[12] == pytest.approx(2.9 / 3)

        season_to_date = _form_row(con, gw=8, team_code=101, window="season_to_date")
        assert season_to_date[0] == 8
        last_five = _form_row(con, gw=8, team_code=101, window="last_5")
        assert last_five[0] == 5
    finally:
        con.close()


def test_blank_gameweek_never_fabricates_a_match() -> None:
    con = _con()
    try:
        _seed_team_codes(con)
        _seed_season(con)

        build_team_form(con)

        observed = con.execute("SELECT DISTINCT gw FROM mart_fact_team_form ORDER BY gw").fetchall()
        assert observed == [(1,), (2,), (3,), (4,), (5,), (6,), (8,)]
    finally:
        con.close()


def test_point_in_time_boundary_excludes_a_postponed_later_kickoff() -> None:
    con = _con()
    try:
        _seed_team_codes(con)
        _seed_season(con)
        # A postponed GW1 match actually played AFTER GW2's last kickoff. Its gw qualifies
        # (1 <= 2) but its kickoff does not (10 > 9), so it must not enter the GW2 window.
        _insert_match(
            con,
            fixture=109,
            gw=1,
            offset_days=10,
            goals_for=4,
            goals_against=0,
            team_xg=3.0,
            team_xgc=0.1,
        )

        build_team_form(con)

        row = _form_row(con, gw=2, team_code=101, window="season_to_date")
        assert row[:2] == (3, 3)  # GW1's played match plus both GW2 legs, not the postponement
    finally:
        con.close()


def test_unmeasured_xg_stays_null_never_zero() -> None:
    con = _con()
    try:
        _seed_team_codes(con)
        _insert_match(
            con,
            season="2021-22",
            fixture=201,
            gw=1,
            offset_days=0,
            team_id=1,
            opponent_team_id=2,
            goals_for=1,
            goals_against=0,
        )

        build_team_form(con)

        row = _form_row(con, season="2021-22", gw=1, team_code=201, window="season_to_date")
        assert row[:7] == (1, 1, 0, 1, 1, 0, 0)
        assert row[7:13] == (None, None, 1.0, 0.0, None, None)
    finally:
        con.close()


def test_team_code_is_season_scoped_no_cross_season_bleed() -> None:
    """team_id 1 is club 101 in 2025-26 and club 201 in 2021-22; histories must not mix."""
    con = _con()
    try:
        _seed_team_codes(con)
        _seed_season(con)
        _insert_match(
            con,
            season="2021-22",
            fixture=201,
            gw=1,
            offset_days=-700,
            team_id=1,
            opponent_team_id=2,
            goals_for=5,
            goals_against=5,
        )

        build_team_form(con)

        # The 2021-22 club's five goals appear only under its own team_code and season.
        row_2021 = _form_row(con, season="2021-22", gw=1, team_code=201, window="season_to_date")
        assert row_2021[:2] == (1, 5)
        row_2025 = _form_row(con, gw=1, team_code=101, window="season_to_date")
        assert row_2025[:2] == (1, 2)
        # And the anchor population is per season: no 2021-22 rows exist for team_code 101.
        bleed = con.execute(
            """
            SELECT count(*) FROM mart_fact_team_form
            WHERE team_code = 101 AND season <> ?
            """,
            [SEASON],
        ).fetchone()
        assert bleed == (0,)
    finally:
        con.close()


def test_duplicate_team_fixture_source_key_fails_closed() -> None:
    con = _con()
    try:
        # Drop and rebuild without the PRIMARY KEY: the real table's constraint would reject the
        # duplicate at insert, so the fail-closed path needs a hand-built or migrated source.
        con.execute("DROP TABLE mart_fact_team_match")
        con.execute(
            """
            CREATE TABLE mart_fact_team_match (
                season VARCHAR,
                gw INTEGER,
                fixture INTEGER,
                kickoff_time TIMESTAMPTZ,
                team_id INTEGER,
                opponent_team_id INTEGER,
                was_home BOOLEAN,
                goals_for INTEGER,
                goals_against INTEGER,
                team_xg DOUBLE,
                team_xgc DOUBLE
            )
            """
        )
        _seed_team_codes(con)
        _insert_match(con, fixture=101, gw=1, offset_days=0)
        _insert_match(con, fixture=101, gw=1, offset_days=0)

        with pytest.raises(TeamFormSourceError, match="duplicate team-fixture"):
            build_team_form(con)
    finally:
        con.close()


def test_unresolvable_team_code_fails_closed() -> None:
    con = _con()
    try:
        _insert_match(con, fixture=101, gw=1, offset_days=0, team_id=99, opponent_team_id=2)

        with pytest.raises(TeamFormSourceError, match="resolves to no"):
            build_team_form(con)
    finally:
        con.close()


@pytest.mark.archive
def test_archive_team_form_mart_has_the_contract_shape_and_grain(
    db: duckdb.DuckDBPyConnection,
) -> None:
    """A rebuilt archive supplies every contract column and exactly four windows per anchor."""
    form = SEMANTIC_CONTRACT_V1.table("fact_team_form")
    assert set(table_columns(db, "mart_fact_team_form")) == form.column_names

    duplicate_keys = db.execute(
        """
        SELECT count(*) FROM (
            SELECT season, gw, team_code, "window", count(*) AS rows_at_key
            FROM mart_fact_team_form
            GROUP BY season, gw, team_code, "window"
            HAVING count(*) <> 1
        )
        """
    ).fetchone()
    assert duplicate_keys == (0,)

    windows = {
        row[0] for row in db.execute('SELECT DISTINCT "window" FROM mart_fact_team_form').fetchall()
    }
    assert windows == {"last_3", "last_5", "last_10", "season_to_date"}

    anchors = db.execute(
        """
        SELECT count(*)
        FROM (
            SELECT DISTINCT m.season, m.gw, t.team_code
            FROM mart_fact_team_match AS m
            JOIN mart_dim_team AS t
              ON t.season = m.season AND t.team_id = m.team_id
        )
        """
    ).fetchone()
    rows = db.execute("SELECT count(*) FROM mart_fact_team_form").fetchone()
    assert anchors is not None and rows is not None
    assert rows[0] == 4 * anchors[0]

    # Rates are NULL exactly when their numerator is NULL; never one without the other.
    mismatched = db.execute(
        """
        SELECT count(*) FROM mart_fact_team_form
        WHERE (team_xg IS NULL) <> (team_xg_per_match IS NULL)
           OR (team_xgc IS NULL) <> (team_xgc_per_match IS NULL)
        """
    ).fetchone()
    assert mismatched == (0,)
