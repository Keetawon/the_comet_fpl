"""Schema drift and NULL-vs-zero: gotchas 5, 6, 7, 11, plus the 2022-23 defect.

The governing rule: zero means "measured as zero", NULL means "not measured". Zero-filling
biases every rate, so these tests assert the difference survives ingest.
"""

from __future__ import annotations

import duckdb
import pytest

pytestmark = pytest.mark.archive

# Columns absent from a season's source file must be NULL for every row of that season,
# never 0 or 0.0.
EXPECTED_ABSENT = {
    "2021-22": (
        "expected_goals",
        "expected_assists",
        "expected_goals_conceded",
        "starts",
        "defensive_contribution",
        "tackles",
        "recoveries",
        "clearances_blocks_interceptions",
    ),
    "2022-23": (
        "defensive_contribution",
        "tackles",
        "recoveries",
        "clearances_blocks_interceptions",
    ),
    "2023-24": (
        "defensive_contribution",
        "tackles",
        "recoveries",
        "clearances_blocks_interceptions",
    ),
    "2024-25": (
        "defensive_contribution",
        "tackles",
        "recoveries",
        "clearances_blocks_interceptions",
    ),
}

EXPECTED_PRESENT = {
    "2022-23": ("starts",),
    "2023-24": ("expected_goals", "expected_assists", "expected_goals_conceded", "starts"),
    "2024-25": ("expected_goals", "expected_assists", "expected_goals_conceded", "starts"),
    "2025-26": (
        "expected_goals",
        "expected_assists",
        "expected_goals_conceded",
        "starts",
        "defensive_contribution",
        "tackles",
        "recoveries",
        "clearances_blocks_interceptions",
    ),
}


@pytest.mark.parametrize(("season", "columns"), sorted(EXPECTED_ABSENT.items()))
def test_unmeasured_columns_are_null_not_zero(
    db: duckdb.DuckDBPyConnection, season: str, columns: tuple[str, ...]
) -> None:
    """Gotcha 5. The single most consequential ingest rule in the project."""
    for column in columns:
        row = db.execute(
            f"""
            SELECT count(*), count({column})
            FROM mart_fact_player_fixture WHERE season = ?
            """,
            [season],
        ).fetchone()
        assert row is not None
        total, non_null = row
        assert total > 0
        assert non_null == 0, f"{season}.{column} has {non_null} non-NULL value(s); expected none"


@pytest.mark.parametrize(("season", "columns"), sorted(EXPECTED_PRESENT.items()))
def test_measured_columns_have_values(
    db: duckdb.DuckDBPyConnection, season: str, columns: tuple[str, ...]
) -> None:
    """The converse: a column the source did carry must not be wholesale NULL.

    Without this, an over-broad repair or a failed cast would look like correct
    schema-drift handling.
    """
    for column in columns:
        row = db.execute(
            f"SELECT count({column}) FROM mart_fact_player_fixture WHERE season = ?",
            [season],
        ).fetchone()
        assert row is not None and row[0] > 0, f"{season}.{column} is entirely NULL"


def test_source_column_presence_is_recorded(db: duckdb.DuckDBPyConnection) -> None:
    """`raw_source_columns` is how stg_ tells "absent from source" from "empty value"."""
    row = db.execute(
        """
        SELECT count(*) FROM raw_source_columns
        WHERE source_table = 'raw_merged_gw' AND column_name = 'defensive_contribution'
        """
    ).fetchone()
    assert row is not None and row[0] == 1  # 2025-26 only

    row = db.execute(
        """
        SELECT count(*) FROM raw_source_columns
        WHERE source_table = 'raw_merged_gw' AND column_name = 'expected_goals'
        """
    ).fetchone()
    assert row is not None and row[0] == 4  # 2022-23 onwards

    # `mng_*` existed only in 2024-25.
    row = db.execute(
        """
        SELECT season FROM raw_source_columns
        WHERE source_table = 'raw_merged_gw' AND column_name = 'mng_win'
        """
    ).fetchall()
    assert [r[0] for r in row] == ["2024-25"]


# --------------------------------------------------------------------------------------
# The 2022-23 present-but-zero defect
# --------------------------------------------------------------------------------------


def test_2022_23_expected_columns_repaired_to_null_through_gw15(
    db: duckdb.DuckDBPyConnection,
) -> None:
    """The archive records `expected_*` as literal 0.0 for 2022-23 GW1-15.

    Team xG sums to exactly zero across those 14 gameweeks while 344 goals were actually
    scored; real values start at GW16. This is gotcha 5 occurring *inside* a season, so a
    column-presence check cannot catch it. Repaired declaratively in
    `config/data_quality.yaml`.
    """
    for column in ("expected_goals", "expected_assists", "expected_goals_conceded"):
        row = db.execute(
            f"""
            SELECT
              count({column}) FILTER (WHERE gw <= 15),
              count({column}) FILTER (WHERE gw >= 16)
            FROM mart_fact_player_fixture WHERE season = '2022-23'
            """,
            [],
        ).fetchone()
        assert row is not None
        early, late = row
        assert early == 0, f"2022-23 {column} should be NULL through GW15, found {early} values"
        assert late > 0, f"2022-23 {column} should have values from GW16, found none"


def test_2022_23_team_xg_is_plausible_after_repair(db: duckdb.DuckDBPyConnection) -> None:
    """The repair's point: an xG mean near actual goals rather than 32% below it.

    Before the repair, 2022-23 team_xg averaged 0.963 against actual goals of 1.426, and
    corr(team_xg, goals) was 0.332 against 0.50-0.59 for later seasons. Feeding that into an
    xG-trained team model is the most likely cause of an xG model losing to a goals model.
    """
    row = db.execute(
        """
        SELECT avg(team_xg), avg(goals_for)
        FROM mart_fact_team_match WHERE season = '2022-23' AND team_xg IS NOT NULL
        """
    ).fetchone()
    assert row is not None
    mean_xg, mean_goals = row
    # Post-repair the surviving rows are GW16+, where xG tracks goals closely.
    assert abs(mean_xg - mean_goals) < 0.25, f"team_xg {mean_xg:.3f} vs goals {mean_goals:.3f}"


def test_null_guarded_aggregates_do_not_become_zero(db: duckdb.DuckDBPyConnection) -> None:
    """2021-22 has no xG columns at all, so its team aggregates must be NULL, not 0.0.

    A Polars `sum()` over an all-null group returns 0.0, which silently reintroduces
    gotcha 5 at the aggregate level -- it dragged an early audit's pooled team_xg mean to
    1.08 against a true 1.41. SQL SUM returns NULL, which is why these are built in SQL.
    """
    row = db.execute(
        """
        SELECT count(*), count(team_xg), count(team_xgc)
        FROM mart_fact_team_match WHERE season = '2021-22'
        """
    ).fetchone()
    assert row is not None
    total, xg, xgc = row
    assert total == 760
    assert xg == 0, f"2021-22 team_xg should be entirely NULL, found {xg} value(s)"
    assert xgc == 0, f"2021-22 team_xgc should be entirely NULL, found {xgc} value(s)"


# --------------------------------------------------------------------------------------
# Defensive contribution shape
# --------------------------------------------------------------------------------------


def test_defensive_contribution_is_a_count_not_points(db: duckdb.DuckDBPyConnection) -> None:
    """Gotcha 6. Observed range 0-29 across the data; it is an action count."""
    row = db.execute(
        """
        SELECT min(defensive_contribution), max(defensive_contribution)
        FROM mart_fact_player_fixture WHERE defensive_contribution IS NOT NULL
        """
    ).fetchone()
    assert row is not None
    low, high = row
    assert low == 0
    assert high >= 21, f"expected a count reaching at least 21, saw max {high}"


def test_goalkeeper_defensive_contribution_is_always_zero(
    db: duckdb.DuckDBPyConnection,
) -> None:
    """Gotcha 7. A non-zero value would mean a position crosswalk error."""
    row = db.execute(
        """
        SELECT count(*), coalesce(max(defensive_contribution), 0)
        FROM mart_fact_player_fixture
        WHERE position = 'GK' AND defensive_contribution IS NOT NULL
        """
    ).fetchone()
    assert row is not None
    measured, highest = row
    assert measured > 0, "expected measured GK rows in 2025-26"
    assert highest == 0


def test_defensive_contribution_hit_rates(db: duckdb.DuckDBPyConnection) -> None:
    """Measured 2025-26: DEF 20.8% at 10, MID 11.0% at 12, FWD 0.6% at 12.

    Sizing matters for Phase 3: forwards reaching 12 in 0.6% of appearances is worth about
    0.012 points per game, so it is not worth modelling.
    """
    rows = dict(
        db.execute(
            """
            SELECT position,
                   round(100.0 * sum(CASE WHEN defensive_contribution >=
                        CASE WHEN position = 'DEF' THEN 10 ELSE 12 END THEN 1 ELSE 0 END)
                        / count(*), 1)
            FROM mart_fact_player_fixture
            WHERE season = '2025-26' AND minutes > 0 AND position <> 'GK'
            GROUP BY position
            """
        ).fetchall()
    )
    assert rows == {"DEF": 20.8, "MID": 11.0, "FWD": 0.6}


# --------------------------------------------------------------------------------------
# xP contamination
# --------------------------------------------------------------------------------------


def test_xp_never_reaches_a_typed_table(db: duckdb.DuckDBPyConnection) -> None:
    """Gotcha 11. `xP` is derived from `ep_this` scraped after the gameweek finished.

    Measured contamination: xP rolling-3 correlates 0.31 with same-gameweek points, far too
    high for a pre-match feature. It is dropped at the stg_ boundary. Matched by exact
    column name -- a substring match would false-positive on "e-x-p-ected_goals".
    """
    leaked = db.execute(
        """
        SELECT table_name, column_name FROM information_schema.columns
        WHERE (table_name LIKE 'stg_%' OR table_name LIKE 'mart_%')
          AND lower(column_name) = 'xp'
        """
    ).fetchall()
    assert leaked == [], f"xP leaked into: {leaked}"


def test_xp_is_present_in_raw_so_the_drop_is_deliberate(
    db: duckdb.DuckDBPyConnection,
) -> None:
    """Proves the previous test is meaningful rather than vacuous.

    `xP` really is in the source; it is dropped on purpose, not simply missing.
    """
    row = db.execute(
        """
        SELECT count(*) FROM information_schema.columns
        WHERE table_name = 'raw_merged_gw' AND lower(column_name) = 'xp'
        """
    ).fetchone()
    assert row is not None and row[0] == 1

    seasons = db.execute(
        """
        SELECT count(DISTINCT season) FROM raw_source_columns
        WHERE source_table = 'raw_merged_gw' AND column_name = 'xP'
        """
    ).fetchone()
    assert seasons is not None and seasons[0] == 5
