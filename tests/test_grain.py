"""Table grain and role boundaries: gotchas 3 and 4, plus the components/targets split."""

from __future__ import annotations

import re

import duckdb
import pytest

from fpl.storage.db import FEATURE_READABLE_TABLES, table_columns

pytestmark = pytest.mark.archive

# Measured row counts after a correct build.
PLAYER_FIXTURE_ROWS = 138_707  # 139,039 landed - 10 duplicates - 322 manager rows
TEAM_MATCH_ROWS = 3_800  # 380 fixtures x 2 sides x 5 seasons

# Genuine double-gameweek cells per season: one player, one gameweek, two fixtures.
DUPLICATE_PLAYER_GAMEWEEKS = {
    "2021-22": 2217,
    "2022-23": 1548,
    "2023-24": 983,
    "2024-25": 364,
    "2025-26": 409,
}


def test_player_fixture_row_count(db: duckdb.DuckDBPyConnection) -> None:
    row = db.execute("SELECT count(*) FROM mart_fact_player_fixture").fetchone()
    assert row is not None and row[0] == PLAYER_FIXTURE_ROWS


def test_team_match_row_count_is_exact(db: duckdb.DuckDBPyConnection) -> None:
    """Exactly 3,800: two sides per fixture, 380 fixtures, five seasons.

    Built from `stg_fixture` rather than by grouping player rows, so the grain holds even
    for a match with no player rows on one side.
    """
    row = db.execute("SELECT count(*) FROM mart_fact_team_match").fetchone()
    assert row is not None and row[0] == TEAM_MATCH_ROWS

    per_season = db.execute(
        "SELECT season, count(*) FROM mart_fact_team_match GROUP BY season ORDER BY season"
    ).fetchall()
    assert [row[1] for row in per_season] == [760] * 5


@pytest.mark.parametrize(
    ("table", "key"),
    [
        ("mart_fact_player_fixture", ("season", "code", "fixture")),
        ("mart_fact_team_match", ("season", "team_id", "fixture")),
        ("mart_target_player_fixture", ("season", "code", "fixture")),
        ("mart_dim_player", ("code", "season")),
        ("mart_dim_team", ("season", "team_id")),
    ],
)
def test_declared_grain_is_unique(
    db: duckdb.DuckDBPyConnection, table: str, key: tuple[str, ...]
) -> None:
    columns = ", ".join(key)
    row = db.execute(f"SELECT count(*), count(DISTINCT ({columns})) FROM {table}").fetchone()
    assert row is not None
    total, distinct = row
    assert total == distinct, f"{table} has {total - distinct} duplicate {key} row(s)"


def test_grain_is_fixture_not_gameweek(db: duckdb.DuckDBPyConnection) -> None:
    """Gotcha 3. Double gameweeks are real, so `(code, gameweek)` is NOT unique.

    Collapsing to gameweek would silently destroy a real match for 409 player-gameweeks in
    2025-26 alone. This asserts the duplicates are still there.
    """
    rows = dict(
        db.execute(
            """
            SELECT season, count(*) - count(DISTINCT (code, gw))
            FROM mart_fact_player_fixture GROUP BY season ORDER BY season
            """
        ).fetchall()
    )
    assert rows == DUPLICATE_PLAYER_GAMEWEEKS


def test_2025_26_exact_duplicate_rows_were_removed(db: duckdb.DuckDBPyConnection) -> None:
    """Gotcha 4. 10 rows appeared twice -- same player, same fixture.

    All 10 were byte-identical across every column, which is why `keep first` cannot lose
    information. 29,757 landed rows become 29,747.
    """
    landed = db.execute("SELECT count(*) FROM raw_merged_gw WHERE season = '2025-26'").fetchone()
    staged = db.execute(
        "SELECT count(*) FROM stg_player_fixture WHERE season = '2025-26'"
    ).fetchone()
    assert landed is not None and staged is not None
    assert landed[0] == 29_757
    assert staged[0] == 29_747
    assert landed[0] - staged[0] == 10


def test_duplicate_source_rows_were_identical(db: duckdb.DuckDBPyConnection) -> None:
    """Dedup is only safe because the duplicates carry no distinct information."""
    groups = db.execute(
        """
        SELECT element, fixture, count(*) AS n,
               count(DISTINCT (minutes, total_points, bps, bonus, goals_scored,
                               assists)) AS variants
        FROM raw_merged_gw WHERE season = '2025-26'
        GROUP BY element, fixture HAVING count(*) > 1
        """
    ).fetchall()
    assert len(groups) == 10
    for _, _, _, variants in groups:
        assert variants == 1


# --------------------------------------------------------------------------------------
# Table roles: components vs targets
# --------------------------------------------------------------------------------------


def test_fact_table_has_no_points_column_of_any_kind(db: duckdb.DuckDBPyConnection) -> None:
    """`mart_fact_player_fixture` is components only.

    The feature builder reads this table, so any points column here is a leakage vector:
    both `total_points` (the label) and `points_under_rules_*` (the model target) would be
    directly readable as features.
    """
    offending = [
        column
        for column in table_columns(db, "mart_fact_player_fixture")
        if re.search(r"points", column, re.IGNORECASE)
    ]
    assert offending == [], f"component table carries points column(s): {offending}"


def test_no_feature_readable_table_exposes_points(db: duckdb.DuckDBPyConnection) -> None:
    """Extend the rule to every table the feature builder may read."""
    for table in sorted(FEATURE_READABLE_TABLES):
        offending = [
            column
            for column in table_columns(db, table)
            if re.search(r"points", column, re.IGNORECASE)
        ]
        assert offending == [], f"{table} carries points column(s): {offending}"


def test_recorded_points_live_only_in_staging(db: duckdb.DuckDBPyConnection) -> None:
    """`total_points` as recorded reaches `stg_` and stops there.

    `raw_*` tables carry it because they are the source as landed -- `players_raw.csv` has a
    season-total `total_points` and `merged_gw.csv` a per-match one. The rule being asserted
    is that no `mart_` table has a column by that name; the target table renames it to
    `total_points_as_recorded` precisely so a careless `SELECT *` cannot mistake it for a
    modelling column.
    """
    locations = [
        row[0]
        for row in db.execute(
            """
            SELECT table_name FROM information_schema.columns
            WHERE column_name = 'total_points' ORDER BY table_name
            """
        ).fetchall()
    ]
    assert locations == ["raw_merged_gw", "raw_players", "stg_player_fixture"]
    assert not [name for name in locations if name.startswith("mart_")]


def test_target_table_carries_recorded_and_recomputed_points(
    db: duckdb.DuckDBPyConnection,
) -> None:
    columns = set(table_columns(db, "mart_target_player_fixture"))
    assert "total_points_as_recorded" in columns
    # One recomputed column per configured ruleset (R2: the column set follows config).
    assert {"points_under_rules_2025_26", "points_under_rules_2026_27"} <= columns


def test_target_and_fact_tables_align_row_for_row(db: duckdb.DuckDBPyConnection) -> None:
    """Same grain, same population -- so a join for validation cannot silently drop rows."""
    row = db.execute(
        """
        SELECT
          (SELECT count(*) FROM mart_fact_player_fixture),
          (SELECT count(*) FROM mart_target_player_fixture),
          (SELECT count(*) FROM mart_fact_player_fixture AS f
             FULL OUTER JOIN mart_target_player_fixture AS t
               ON t.season = f.season AND t.code = f.code AND t.fixture = f.fixture
           WHERE f.code IS NULL OR t.code IS NULL)
        """
    ).fetchone()
    assert row is not None
    facts, targets, unmatched = row
    assert facts == targets == PLAYER_FIXTURE_ROWS
    assert unmatched == 0
