"""Shared test fixtures.

No test in this suite requires network access. Tests needing the built database are marked
`archive` and skip with an actionable message if `build_db` has not been run.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import duckdb
import pytest

from fpl.config import repo_root
from fpl.storage.db import connect, default_db_path

FEATURE_TABLES: tuple[str, ...] = (
    "mart_fact_player_fixture",
    "mart_fact_team_match",
    "mart_dim_player",
    "mart_dim_team",
)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip `archive` tests when the database has not been built."""
    if default_db_path().is_file():
        return
    skip = pytest.mark.skip(
        reason=f"no database at {default_db_path()}; run `python -m fpl.jobs.build_db` first"
    )
    for item in items:
        if "archive" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def db() -> Iterator[duckdb.DuckDBPyConnection]:
    """Read-only connection to the built database."""
    path = default_db_path()
    if not path.is_file():
        pytest.skip(f"no database at {path}")
    # `connect`, not `duckdb.connect`: tests must see the same session settings production
    # does, or they cannot detect a setting that production depends on.
    con = connect(path, read_only=True)
    try:
        yield con
    finally:
        con.close()


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return repo_root() / "tests" / "fixtures"


@pytest.fixture(scope="session")
def bootstrap_payload_path(fixtures_dir: Path) -> Path:
    path = fixtures_dir / "bootstrap_static_sample.json"
    if not path.is_file():
        pytest.skip(f"missing vendored payload {path}")
    return path


@pytest.fixture(scope="session")
def fixtures_payload_path(fixtures_dir: Path) -> Path:
    path = fixtures_dir / "fixtures_sample.json"
    if not path.is_file():
        pytest.skip(f"missing vendored payload {path}")
    return path


def make_truncated_db(
    as_of: datetime, *, truncate_future_season_dimensions: bool = False
) -> duckdb.DuckDBPyConnection:
    """An in-memory database holding only rows with `kickoff_time < as_of`.

    The other half of the truncation-equivalence test: querying this with a point-in-time
    view must give the same answer as querying the full database with the same `as_of`. If
    an accessor forgets its filter, the full database returns extra rows and the two
    disagree.

    Dimension tables carry no ``kickoff_time``, so by default they are copied unchanged. With
    ``truncate_future_season_dimensions`` a stricter physical truncation also drops dimension
    rows whose season has no observed fact yet (seasons later than the latest one with a
    pre-``as_of`` kickoff): a model that secretly read a future-season dimension row would then
    diverge from the full-database-with-filter result. The point-in-time layer's own truncation
    test keeps the default, so it is unaffected.
    """
    # Via the project's own `connect`, not duckdb directly, so this session is pinned to
    # UTC like every other. Otherwise DuckDB tags timestamps with the local zone and the
    # comparison below fails on dtype -- Datetime('us','Asia/Bangkok') is not
    # Datetime('us','UTC') to Polars, even when the instants are identical.
    con = connect(":memory:")
    con.execute(f"ATTACH '{default_db_path()}' AS full_db (READ_ONLY)")
    for table in FEATURE_TABLES:
        # `information_schema` is not qualified per attached database; duckdb_columns() is.
        columns = [
            str(name)
            for (name,) in con.execute(
                """
                SELECT column_name FROM duckdb_columns()
                WHERE database_name = 'full_db' AND table_name = ?
                ORDER BY column_index
                """,
                [table],
            ).fetchall()
        ]
        if "kickoff_time" in columns:
            con.execute(
                f"CREATE TABLE {table} AS SELECT * FROM full_db.{table} WHERE kickoff_time < ?",
                [as_of],
            )
        elif truncate_future_season_dimensions and "season" in columns:
            # Keep dimension rows only for seasons that have started by as_of (first kickoff
            # <= as_of), resolved against the full DB. A season-opener fold still keeps the
            # upcoming season's known club roster (its first kickoff is as_of itself) while
            # dropping genuinely future seasons, so a model that read a future-season dimension
            # row would diverge.
            con.execute(
                f"CREATE TABLE {table} AS SELECT d.* FROM full_db.{table} d "
                "WHERE d.season IN ("
                "  SELECT season FROM full_db.mart_fact_team_match"
                "  GROUP BY season HAVING min(kickoff_time) <= ?"
                ")",
                [as_of],
            )
        else:
            con.execute(f"CREATE TABLE {table} AS SELECT * FROM full_db.{table}")
    con.execute("DETACH full_db")
    return con
