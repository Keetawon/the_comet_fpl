"""P1.6 player-form mart at player-gameweek/window grain.

The unit tests build only the two source marts in a temporary DuckDB.  They intentionally include a
double gameweek, an absent observed gameweek, and incomplete measurement coverage; no archive or
network is required for those cases.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import duckdb
import pytest

from fpl.publish.contract import SEMANTIC_CONTRACT_V1
from fpl.storage.db import initialise, table_columns
from fpl.transform.facts import PlayerFormSourceError, build_player_form

SEASON = "2025-26"
KICKOFF = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _con() -> duckdb.DuckDBPyConnection:
    return initialise(":memory:")


def _insert_rostered(
    con: duckdb.DuckDBPyConnection,
    *,
    fixture: int,
    gw: int,
    offset_days: int,
    code: int = 10,
    season: str = SEASON,
    minutes: int | None,
    starts: int | None,
    goals: int = 0,
    assists: int = 0,
    clean_sheets: int = 0,
    goals_conceded: int = 0,
    saves: int = 0,
    bonus: int = 0,
    bps: int = 0,
    defensive_contribution: int | None = None,
    expected_goals: float | None = None,
    expected_assists: float | None = None,
    expected_goals_conceded: float | None = None,
    points: int | None = 0,
) -> None:
    kickoff_time = KICKOFF + timedelta(days=offset_days)
    con.execute(
        """
        INSERT INTO mart_fact_player_fixture (
            season, gw, fixture, kickoff_time, code, position, team_id, opponent_team_id,
            was_home, minutes, starts, goals_scored, assists, clean_sheets, goals_conceded,
            saves, bonus, bps, defensive_contribution, expected_goals, expected_assists,
            expected_goals_conceded
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            season,
            gw,
            fixture,
            kickoff_time,
            code,
            "MID",
            1,
            2,
            True,
            minutes,
            starts,
            goals,
            assists,
            clean_sheets,
            goals_conceded,
            saves,
            bonus,
            bps,
            defensive_contribution,
            expected_goals,
            expected_assists,
            expected_goals_conceded,
        ],
    )
    con.execute(
        """
        INSERT INTO mart_target_player_fixture (
            season, gw, fixture, kickoff_time, code, position, points_under_rules_2026_27
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [season, gw, fixture, kickoff_time, code, "MID", points],
    )


def _seed_player_with_double_gameweek(con: duckdb.DuckDBPyConnection) -> None:
    _insert_rostered(
        con,
        fixture=101,
        gw=1,
        offset_days=0,
        minutes=90,
        starts=1,
        goals=1,
        clean_sheets=1,
        saves=3,
        bonus=3,
        bps=30,
        defensive_contribution=4,
        expected_goals=0.6,
        expected_assists=0.2,
        expected_goals_conceded=0.7,
        points=8,
    )
    # The first leg is a DNP.  Its nine replayed points intentionally prove that productivity
    # uses appeared rows rather than all rostered rows.
    _insert_rostered(
        con,
        fixture=102,
        gw=2,
        offset_days=7,
        minutes=0,
        starts=0,
        clean_sheets=1,
        goals_conceded=2,
        saves=4,
        expected_goals_conceded=1.2,
        points=9,
    )
    _insert_rostered(
        con,
        fixture=103,
        gw=2,
        offset_days=9,
        minutes=60,
        starts=1,
        assists=1,
        goals_conceded=1,
        bonus=1,
        bps=20,
        defensive_contribution=2,
        expected_goals=0.4,
        points=5,
    )
    # This appeared fixture has no xG but has xA.  It makes the matching-minutes denominator
    # differ from total appeared minutes.
    _insert_rostered(
        con,
        fixture=104,
        gw=3,
        offset_days=16,
        minutes=30,
        starts=1,
        goals_conceded=1,
        bps=10,
        defensive_contribution=1,
        expected_assists=0.3,
        expected_goals_conceded=0.4,
        points=2,
    )
    _insert_rostered(
        con,
        fixture=105,
        gw=4,
        offset_days=23,
        minutes=0,
        starts=0,
        points=7,
    )
    _insert_rostered(
        con,
        fixture=106,
        gw=5,
        offset_days=30,
        minutes=90,
        starts=1,
        goals=1,
        assists=1,
        bonus=2,
        bps=25,
        defensive_contribution=0,
        expected_goals=0.5,
        expected_assists=0.5,
        points=10,
    )
    _insert_rostered(
        con,
        fixture=107,
        gw=6,
        offset_days=37,
        minutes=90,
        starts=1,
        bps=22,
        defensive_contribution=3,
        expected_goals=0.2,
        expected_assists=0.1,
        points=3,
    )
    # GW7 is deliberately absent.  Iteration must use observed gameweeks, not range(1, 39).
    _insert_rostered(
        con,
        fixture=108,
        gw=8,
        offset_days=51,
        minutes=45,
        starts=1,
        bps=15,
        defensive_contribution=1,
        expected_goals=0.1,
        expected_assists=0.2,
        points=2,
    )


def _form_row(
    con: duckdb.DuckDBPyConnection, *, season: str = SEASON, gw: int, code: int, window: str
) -> tuple[object, ...]:
    row = con.execute(
        """
        SELECT rostered_fixtures, appearances, starts, did_not_play, minutes,
               goals_scored, assists, bonus, bps, defensive_contribution,
               expected_goals, expected_assists, expected_goals_per_90,
               expected_assists_per_90, points_under_rules_2026_27,
               clean_sheets, goals_conceded, saves, expected_goals_conceded
        FROM mart_fact_player_form
        WHERE season = ? AND gw = ? AND code = ? AND "window" = ?
        """,
        [season, gw, code, window],
    ).fetchone()
    assert row is not None
    return row


def test_availability_and_productivity_use_different_populations_in_a_double_gameweek() -> None:
    con = _con()
    try:
        _seed_player_with_double_gameweek(con)

        assert build_player_form(con) == 28  # seven observed player-gameweeks x four windows

        row = _form_row(con, gw=2, code=10, window="last_3")
        assert row[:10] == (3, 2, 2, 1, 150, 1, 1, 4, 50, 6)
        assert row[10] == pytest.approx(1.0)
        assert row[11] == pytest.approx(0.2)
        assert row[12] == pytest.approx(0.6)
        assert row[13] == pytest.approx(0.2)
        # The zero-minute leg's nine points are not a productivity contribution.
        assert row[14] == 13
        # Defensive form uses the same appeared population; the deliberately non-zero DNP
        # components are excluded, while measured xGC keeps its partial-coverage semantics.
        assert row[15:18] == (1, 1, 3)
        assert row[18] == pytest.approx(0.7)
    finally:
        con.close()


def test_per_90_uses_matching_measured_minutes_and_zero_appearance_rates_are_null() -> None:
    con = _con()
    try:
        _seed_player_with_double_gameweek(con)
        _insert_rostered(
            con,
            fixture=201,
            gw=1,
            offset_days=0,
            code=20,
            minutes=0,
            starts=0,
            expected_goals=0.0,
            expected_assists=0.0,
        )

        build_player_form(con)

        row = _form_row(con, gw=3, code=10, window="season_to_date")
        # xG = 1.0, but its matching minutes are 90 + 60, not all 180 appeared minutes.
        assert row[10] == pytest.approx(1.0)
        assert row[12] == pytest.approx(0.6)
        # xA = 0.2 + 0.3 over 90 + 30 matching minutes, not the 60-minute no-xA row.
        assert row[11] == pytest.approx(0.5)
        assert row[13] == pytest.approx(0.375)

        no_appearance = _form_row(con, gw=1, code=20, window="season_to_date")
        assert no_appearance[5:19] == (None,) * 14
    finally:
        con.close()


def test_unmeasured_signals_and_starts_remain_null_not_zero() -> None:
    con = _con()
    try:
        _insert_rostered(
            con,
            season="2021-22",
            fixture=301,
            gw=1,
            offset_days=0,
            code=30,
            minutes=90,
            starts=None,
            goals=1,
            points=6,
        )

        build_player_form(con)

        row = _form_row(con, season="2021-22", gw=1, code=30, window="season_to_date")
        assert row[:10] == (1, 1, None, 0, 90, 1, 0, 0, 0, None)
        assert row[10:14] == (None, None, None, None)
        assert row[14] == 6
        assert row[15:18] == (0, 0, 0)
        assert row[18] is None
    finally:
        con.close()


def test_long_windows_use_fixture_history_and_only_observed_gameweeks() -> None:
    con = _con()
    try:
        _seed_player_with_double_gameweek(con)

        build_player_form(con)

        last_three = _form_row(con, gw=8, code=10, window="last_3")
        last_five = _form_row(con, gw=8, code=10, window="last_5")
        last_ten = _form_row(con, gw=8, code=10, window="last_10")
        season_to_date = _form_row(con, gw=8, code=10, window="season_to_date")
        assert last_three[0] == 3
        assert last_five[0] == 5
        assert last_ten[0] == 8
        assert season_to_date[0] == 8
        assert last_three[4] == 225
        assert season_to_date[4] == 405

        observed = con.execute(
            """
            SELECT DISTINCT gw FROM mart_fact_player_form
            WHERE season = ? AND code = ?
            ORDER BY gw
            """,
            [SEASON, 10],
        ).fetchall()
        assert observed == [(1,), (2,), (3,), (4,), (5,), (6,), (8,)]
        assert con.execute(
            """
            SELECT count(*) FROM mart_fact_player_form
            WHERE season = ? AND code = ? AND gw = 7
            """,
            [SEASON, 10],
        ).fetchone() == (0,)
    finally:
        con.close()


def test_duplicate_player_fixture_source_key_fails_closed() -> None:
    con = _con()
    try:
        con.execute("DROP TABLE mart_fact_player_fixture")
        con.execute(
            """
            CREATE TABLE mart_fact_player_fixture (
                season VARCHAR,
                gw INTEGER,
                fixture INTEGER,
                kickoff_time TIMESTAMPTZ,
                code INTEGER,
                minutes INTEGER,
                starts INTEGER,
                goals_scored INTEGER,
                assists INTEGER,
                bonus INTEGER,
                bps INTEGER,
                defensive_contribution INTEGER,
                expected_goals DOUBLE,
                expected_assists DOUBLE
            )
            """
        )
        con.execute(
            """
            INSERT INTO mart_fact_player_fixture VALUES
                (?, 1, 101, ?, 10, 90, 1, 0, 0, 0, 0, NULL, NULL, NULL),
                (?, 1, 101, ?, 10, 90, 1, 0, 0, 0, 0, NULL, NULL, NULL)
            """,
            [SEASON, KICKOFF, SEASON, KICKOFF],
        )

        with pytest.raises(PlayerFormSourceError, match="duplicate player-fixture"):
            build_player_form(con)
    finally:
        con.close()


def test_appeared_fixture_with_missing_basic_defensive_count_fails_closed() -> None:
    con = _con()
    try:
        _insert_rostered(
            con,
            fixture=401,
            gw=1,
            offset_days=0,
            minutes=90,
            starts=1,
        )
        con.execute(
            """
            UPDATE mart_fact_player_fixture
            SET saves = NULL
            WHERE season = ? AND fixture = ? AND code = ?
            """,
            [SEASON, 401, 10],
        )

        with pytest.raises(PlayerFormSourceError, match="NULL clean_sheets"):
            build_player_form(con)
    finally:
        con.close()


@pytest.mark.archive
def test_archive_player_form_mart_has_the_contract_shape_and_grain(
    db: duckdb.DuckDBPyConnection,
) -> None:
    """A rebuilt archive supplies every contract column and exactly four windows per anchor."""
    form = SEMANTIC_CONTRACT_V1.table("fact_player_form")
    assert set(table_columns(db, "mart_fact_player_form")) == form.column_names

    duplicate_keys = db.execute(
        """
        SELECT count(*) FROM (
            SELECT season, gw, code, "window", count(*) AS rows_at_key
            FROM mart_fact_player_form
            GROUP BY season, gw, code, "window"
            HAVING count(*) <> 1
        )
        """
    ).fetchone()
    assert duplicate_keys == (0,)

    windows = {
        row[0]
        for row in db.execute('SELECT DISTINCT "window" FROM mart_fact_player_form').fetchall()
    }
    assert windows == {"last_3", "last_5", "last_10", "season_to_date"}

    anchors = db.execute(
        "SELECT count(*) FROM (SELECT DISTINCT season, gw, code FROM mart_fact_player_fixture)"
    ).fetchone()
    rows = db.execute("SELECT count(*) FROM mart_fact_player_form").fetchone()
    assert anchors is not None and rows is not None
    assert rows[0] == 4 * anchors[0]
