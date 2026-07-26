"""DuckDB connection management and schema application.

Five seasons is ~139k rows and a few MB. A database server is unjustified operational
cost, so this is a single file on disk.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import duckdb

from fpl.config import load_sources, repo_root
from fpl.types import RulesetId

_SCHEMA_PATH: Final[Path] = Path(__file__).with_name("schema.sql")

# Table-role boundaries. The feature builder may read exactly these tables; everything
# else -- and in particular every mart_target_* table -- is out of reach. Enforced at
# runtime by features.pit.FeatureSource and statically by tests/test_point_in_time.py.
FEATURE_READABLE_TABLES: Final[frozenset[str]] = frozenset(
    {
        "mart_fact_player_fixture",
        "mart_fact_team_match",
        "mart_dim_player",
        "mart_dim_team",
    }
)

# Read only by the validation harness and the dashboard.
TARGET_TABLE_PREFIX: Final[str] = "mart_target_"

# Any column in a feature-readable table matching this is a bug: components only.
FORBIDDEN_FEATURE_COLUMN_SUBSTRING: Final[str] = "points"


def default_db_path() -> Path:
    return repo_root() / load_sources().paths.database


def connect(
    db_path: Path | str | None = None, *, read_only: bool = False
) -> duckdb.DuckDBPyConnection:
    """Open a connection, creating the parent directory when writing."""
    resolved = Path(db_path) if db_path is not None else default_db_path()
    if str(resolved) != ":memory:":
        resolved.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(resolved), read_only=read_only)


def apply_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Apply the static DDL. Idempotent -- every statement is CREATE ... IF NOT EXISTS."""
    con.execute(_SCHEMA_PATH.read_text(encoding="utf-8"))


def table_exists(con: duckdb.DuckDBPyConnection, table: str) -> bool:
    row = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [table]
    ).fetchone()
    return bool(row and row[0])


def table_columns(con: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    return [
        str(name)
        for (name,) in con.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = ? ORDER BY ordinal_position
            """,
            [table],
        ).fetchall()
    ]


def points_column_for(ruleset_id: RulesetId) -> str:
    """The recomputed-points column name for a ruleset. "2026_27" -> the R1-safe target."""
    return f"points_under_rules_{ruleset_id}"


def ensure_ruleset_columns(
    con: duckdb.DuckDBPyConnection, ruleset_ids: list[RulesetId]
) -> list[str]:
    """Add a `points_under_rules_<ruleset>` column per configured ruleset. Idempotent.

    The column set is a function of configuration (R2), so it cannot live in static DDL:
    adding 2027/28 must be a config change, and that must include its target column.
    """
    existing = set(table_columns(con, "mart_target_player_fixture"))
    added: list[str] = []
    for ruleset_id in ruleset_ids:
        column = points_column_for(ruleset_id)
        if column not in existing:
            # Identifier is derived from a config filename and validated below, not
            # from user input.
            if not column.replace("_", "").isalnum():
                raise ValueError(f"refusing to create unsafe column name: {column!r}")
            con.execute(f'ALTER TABLE mart_target_player_fixture ADD COLUMN "{column}" INTEGER')
            added.append(column)
    return added


def record_build_metadata(con: duckdb.DuckDBPyConnection, key: str, value: str) -> None:
    con.execute(
        """
        INSERT OR REPLACE INTO build_metadata (key, value, written_at)
        VALUES (?, ?, ?)
        """,
        [key, value, datetime.now(UTC)],
    )


def initialise(db_path: Path | str | None = None) -> duckdb.DuckDBPyConnection:
    """Open a connection with the schema applied and ruleset columns present."""
    from fpl.config import available_rulesets

    con = connect(db_path)
    apply_schema(con)
    ensure_ruleset_columns(con, available_rulesets())
    return con
