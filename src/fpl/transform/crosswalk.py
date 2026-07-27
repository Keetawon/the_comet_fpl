"""raw_ -> stg_: typing, deduplication, and the season-scoped crosswalks.

Three identifier hazards make this layer mandatory rather than cosmetic:

  * `element` id is reassigned every season (gotcha 1). Salah is 233, 283, 308, 328, 381
    across 2021-22..2025-26. The stable key is `code` (118748). `merged_gw.csv` carries
    only `element`, so joining to that season's `players_raw.csv` is the only way to get
    a stable identity. Measured match rate: 100.000%.
  * Team ids are reassigned every season (gotcha 2). Id 3 is Brentford in 2021-22,
    Bournemouth in 2022-23, Burnley in 2025-26, so `opponent_team` is meaningless without
    a per-season crosswalk.
  * The archive's `position` label vocabulary drifts, so position comes from
    `element_type` (gotcha 10).
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from fpl.types import MANAGER_ELEMENT_TYPE, Season

# merged_gw carries `team` as a NAME and `opponent_team` as an ID, in the same row.
# Both need the per-season crosswalk, in opposite directions. Measured: 100% of team
# names resolve and every opponent id is valid, in all five seasons.
_POSITION_FROM_ELEMENT_TYPE = """
    CASE element_type
        WHEN 1 THEN 'GK' WHEN 2 THEN 'DEF' WHEN 3 THEN 'MID' WHEN 4 THEN 'FWD'
    END
"""


@dataclass(frozen=True, slots=True)
class CrosswalkReport:
    """Row accounting for one build. Every number here is asserted by the test suite."""

    raw_rows: int
    duplicate_rows_removed: int
    manager_rows_excluded: int
    unmatched_element_rows: int
    staged_rows: int


def build_dimensions(con: duckdb.DuckDBPyConnection) -> None:
    """Build stg_team, stg_player and stg_fixture."""
    con.execute("DELETE FROM stg_team")
    con.execute(
        """
        INSERT INTO stg_team (season, team_id, team_name, short_name, team_code, pulse_id)
        SELECT season,
               CAST(id AS INTEGER),
               name,
               short_name,
               TRY_CAST(code AS INTEGER),
               TRY_CAST(pulse_id AS INTEGER)
        FROM raw_teams
        """
    )

    con.execute("DELETE FROM stg_player")
    con.execute(
        f"""
        INSERT INTO stg_player
            (season, element, code, opta_code, web_name, element_type, position, team_id)
        SELECT season,
               CAST(id AS INTEGER),
               CAST(code AS INTEGER),
               opta_code,
               web_name,
               CAST(element_type AS INTEGER),
               {_POSITION_FROM_ELEMENT_TYPE},
               TRY_CAST(team AS INTEGER)
        FROM raw_players
        WHERE CAST(element_type AS INTEGER) <> {MANAGER_ELEMENT_TYPE}
        """
    )

    con.execute("DELETE FROM stg_fixture")
    con.execute(
        """
        INSERT INTO stg_fixture (
            season, fixture, pulse_id, gw, kickoff_time, team_h, team_a,
            team_h_score, team_a_score, team_h_difficulty, team_a_difficulty, finished
        )
        SELECT season,
               CAST(id AS INTEGER),
               TRY_CAST(pulse_id AS INTEGER),
               TRY_CAST(event AS INTEGER),
               TRY_CAST(kickoff_time AS TIMESTAMPTZ),
               CAST(team_h AS INTEGER),
               CAST(team_a AS INTEGER),
               TRY_CAST(team_h_score AS INTEGER),
               TRY_CAST(team_a_score AS INTEGER),
               TRY_CAST(team_h_difficulty AS INTEGER),
               TRY_CAST(team_a_difficulty AS INTEGER),
               lower(CAST(finished AS VARCHAR)) IN ('true', '1')
        FROM raw_fixtures
        """
    )


def _nullify_expression(
    column: str, nullify_predicates: dict[str, list[str]], alias: str = "d"
) -> str:
    """Wrap a cast in the declared data-quality repairs for that column.

    Repairs only ever widen NULL coverage -- they never write a value.
    """
    predicates = nullify_predicates.get(column, [])
    target = f'{alias}."{column}"'
    cast = (
        f"TRY_CAST({target} AS DOUBLE)"
        if column.startswith("expected_") or column in {"threat", "creativity"}
        else f"TRY_CAST({target} AS INTEGER)"
    )
    if not predicates:
        return cast
    joined = " OR ".join(f"({predicate})" for predicate in predicates)
    return f"CASE WHEN {joined} THEN NULL ELSE {cast} END"


def build_player_fixture(
    con: duckdb.DuckDBPyConnection,
    *,
    nullify_predicates: dict[str, list[str]] | None = None,
) -> CrosswalkReport:
    """Build stg_player_fixture: deduped, crosswalked, typed, `xP` dropped.

    Deduplication is on `(season, element, fixture)`, not `(season, element, gw)`. The
    grain really is per-fixture: double gameweeks are genuine (2,217 duplicated
    player-gameweek cells in 2021-22, 409 in 2025-26) and collapsing them would destroy
    real matches. Separately, 2025-26 contains 10 exactly-duplicated rows -- same player,
    same fixture, twice -- which the `(element, fixture)` key removes. Verified: all 10
    are byte-identical across every column, so `keep first` cannot lose information.
    """
    repairs = nullify_predicates or {}
    raw_rows = _scalar(con, "SELECT count(*) FROM raw_merged_gw")

    # `expected_goal_involvements` is xG + xA and derivable, so it is not staged.
    numeric_columns = [
        "minutes",
        "starts",
        "goals_scored",
        "assists",
        "clean_sheets",
        "goals_conceded",
        "saves",
        "penalties_saved",
        "penalties_missed",
        "own_goals",
        "yellow_cards",
        "red_cards",
        "bonus",
        "bps",
        "expected_goals",
        "expected_assists",
        "expected_goals_conceded",
        "threat",
        "creativity",
        "defensive_contribution",
        "tackles",
        "recoveries",
        "clearances_blocks_interceptions",
        "value",
        "selected",
        "transfers_in",
        "transfers_out",
        "total_points",
    ]
    projections = ",\n               ".join(
        f"{_nullify_expression(column, repairs)} AS {column}" for column in numeric_columns
    )

    con.execute("DELETE FROM stg_player_fixture")
    con.execute(
        f"""
        INSERT INTO stg_player_fixture (
            season, element, code, fixture, gw, kickoff_time, position,
            team_id, opponent_team_id, was_home,
            {", ".join(numeric_columns)}
        )
        WITH deduped AS (
            SELECT *,
                   row_number() OVER (
                       PARTITION BY season, CAST(element AS INTEGER), CAST(fixture AS INTEGER)
                       ORDER BY TRY_CAST("GW" AS INTEGER)
                   ) AS _row_in_group
            FROM raw_merged_gw
        )
        SELECT d.season,
               CAST(d.element AS INTEGER),
               p.code,
               CAST(d.fixture AS INTEGER),
               TRY_CAST(d."GW" AS INTEGER),
               TRY_CAST(d.kickoff_time AS TIMESTAMPTZ),
               p.position,
               own.team_id,
               CAST(d.opponent_team AS INTEGER),
               lower(CAST(d.was_home AS VARCHAR)) IN ('true', '1'),
               {projections}
        FROM deduped AS d
        -- Season-scoped element -> code. INNER JOIN drops the manager elements, which
        -- stg_player already excluded; the count is reported, never silent.
        JOIN stg_player AS p
          ON p.season = d.season AND p.element = CAST(d.element AS INTEGER)
        -- `team` is a NAME in merged_gw, so this resolves name -> season team_id.
        JOIN stg_team AS own
          ON own.season = d.season AND own.team_name = d.team
        WHERE d._row_in_group = 1
        """
    )

    staged_rows = _scalar(con, "SELECT count(*) FROM stg_player_fixture")
    distinct_keys = _scalar(
        con,
        "SELECT count(*) FROM (SELECT DISTINCT season, element, fixture FROM raw_merged_gw)",
    )
    manager_rows = _scalar(
        con,
        f"""
        SELECT count(*) FROM raw_merged_gw AS d
        JOIN raw_players AS p ON p.season = d.season AND p.id = d.element
        WHERE CAST(p.element_type AS INTEGER) = {MANAGER_ELEMENT_TYPE}
        """,
    )
    return CrosswalkReport(
        raw_rows=raw_rows,
        duplicate_rows_removed=raw_rows - distinct_keys,
        manager_rows_excluded=manager_rows,
        unmatched_element_rows=distinct_keys - manager_rows - staged_rows,
        staged_rows=staged_rows,
    )


def _scalar(con: duckdb.DuckDBPyConnection, sql: str) -> int:
    row = con.execute(sql).fetchone()
    return int(row[0]) if row else 0


def element_to_code(con: duckdb.DuckDBPyConnection, season: Season, element: int) -> int | None:
    row = con.execute(
        "SELECT code FROM stg_player WHERE season = ? AND element = ?", [season, element]
    ).fetchone()
    return int(row[0]) if row else None


def team_id_for_name(con: duckdb.DuckDBPyConnection, season: Season, team_name: str) -> int | None:
    row = con.execute(
        "SELECT team_id FROM stg_team WHERE season = ? AND team_name = ?", [season, team_name]
    ).fetchone()
    return int(row[0]) if row else None
