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

# Every connection runs at UTC. A point-in-time system whose stored values depend on the
# builder's local timezone is not reproducible, and R4's whole premise is that a value
# computed for a given instant is fixed.
SESSION_TIMEZONE: Final[str] = "UTC"

# Table-role boundaries. The feature builder may read exactly these tables; everything
# else -- and in particular every mart_target_* table -- is out of reach. Enforced at
# runtime by features.pit.FeatureSource and statically by tests/test_point_in_time.py.
FEATURE_READABLE_TABLES: Final[frozenset[str]] = frozenset(
    {
        "mart_fact_player_fixture",
        "mart_fact_team_match",
        "mart_dim_player",
        "mart_dim_team",
        "mart_fact_player_fixture_live",
        "mart_team_fixture_live",
        # The versioned live player registry: identity/registration metadata only (code,
        # position, team_id, status, ...) with NO outcome column. This is the contract's
        # `live_prospective_registry` -- the only point-in-time-safe way to select WHICH
        # players to predict in a live/prospective run (known_at <= as_of). Unlike the
        # outcome-carrying staging tables (e.g. stg_player_fixture, which holds total_points),
        # this stg_ table is safe for the feature layer, and fpl.features.pit guards its
        # projection with assert_no_outcome_columns.
        "stg_live_player_version",
        # V2 football data layer. Both are component/observation tables carrying no points
        # column of any kind; every post-match metric column on them is registered in
        # features.pit.OUTCOME_COLUMNS, so PointInTimeView hard-filters them on
        # `kickoff_time < as_of` and `schedule()` cannot project them.
        "mart_fact_team_match_stats_v2",
        "mart_fact_team_tactical_form_v2",
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
    """Open a connection, creating the parent directory when writing.

    The session timezone is pinned to UTC. This is not cosmetic -- DuckDB evaluates
    date/time functions on TIMESTAMPTZ in the *session* timezone, so without it the
    contents of the fact tables depend on the machine that built them. Measured: the same
    pair of kickoff times yields a rest-day gap of 2 under UTC and 1 under Asia/Bangkok,
    because `date_diff('day', ...)` counts calendar boundaries in local time.

    Pinning it also makes timestamps come back tagged UTC rather than a named local zone,
    which avoids resolving the IANA database at all -- on Windows `zoneinfo` cannot resolve
    a named zone unless the `tzdata` package is installed.
    """
    resolved = Path(db_path) if db_path is not None else default_db_path()
    if str(resolved) != ":memory:":
        resolved.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(resolved), read_only=read_only)
    con.execute(f"SET TimeZone='{SESSION_TIMEZONE}'")
    return con


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


# --------------------------------------------------------------------------------------
# V2 football metric columns
# --------------------------------------------------------------------------------------

# The three tables whose metric columns are a function of the metric dictionary rather than
# of static DDL, and the suffix each uses. `None` means the metric's own name is the column.
_SDP_METRIC_TABLES: Final[tuple[tuple[str, str | None, bool], ...]] = (
    # (table, column suffix, include derived opponent mirrors)
    ("stg_pl_sdp_team_match_stats", None, False),
    ("mart_fact_team_match_stats_v2", None, True),
    ("mart_fact_team_tactical_form_v2", "_per_match", True),
)

# Column type per declared metric type. A percent is a DOUBLE on a 0-100 scale, never a
# fraction: the two sides of a match must sum to ~100 for the consistency check to mean
# anything, and silently normalising to 0-1 in one place and not another is how that check
# starts passing on wrong data.
_SDP_COLUMN_TYPES: Final[dict[str, str]] = {
    "int": "INTEGER",
    "float": "DOUBLE",
    "percent": "DOUBLE",
}

# A rolling mean of an integer count is not an integer.
_SDP_AGGREGATE_TYPE: Final[str] = "DOUBLE"


def _validate_identifier(name: str) -> str:
    """Reject anything that is not a plain identifier before it reaches DDL.

    The names come from a repository config file rather than from user input, but a column
    name is interpolated into SQL and there is no bind parameter for an identifier, so this
    is checked rather than trusted.
    """
    if not name or not name.replace("_", "").isalnum() or name[0].isdigit():
        raise ValueError(f"refusing to create unsafe column name: {name!r}")
    return name


def sdp_metric_columns(
    *, suffix: str | None = None, include_mirrors: bool = True
) -> dict[str, str]:
    """Column name -> SQL type for every metric (and mirror) in the dictionary."""
    from fpl.config import load_sdp_metrics

    dictionary = load_sdp_metrics()
    columns: dict[str, str] = {}
    for metric in dictionary.all_fields():
        base = _SDP_COLUMN_TYPES[str(metric.type)]
        column_type = _SDP_AGGREGATE_TYPE if suffix else base
        columns[_validate_identifier(f"{metric.local_field}{suffix or ''}")] = column_type
        if include_mirrors and metric.mirror is not None:
            columns[_validate_identifier(f"{metric.mirror}{suffix or ''}")] = column_type
    return columns


def ensure_sdp_metric_columns(con: duckdb.DuckDBPyConnection) -> dict[str, list[str]]:
    """Add every dictionary-declared metric column to the V2 tables. Idempotent.

    The column set is a function of `config/pl_sdp_metrics.yaml` (R2's principle applied to a
    second config), so it cannot live in static DDL: adding a metric must be a config change,
    and that change must bring its columns. Existing rows receive NULL, which is correct --
    the metric was not measured for them, and NULL is not zero.
    """
    added: dict[str, list[str]] = {}
    for table, suffix, mirrors in _SDP_METRIC_TABLES:
        if not table_exists(con, table):
            continue
        existing = set(table_columns(con, table))
        new_columns: list[str] = []
        for column, column_type in sdp_metric_columns(
            suffix=suffix, include_mirrors=mirrors
        ).items():
            if column not in existing:
                con.execute(f'ALTER TABLE {table} ADD COLUMN "{column}" {column_type}')
                new_columns.append(column)
        if new_columns:
            added[table] = new_columns
    return added


def initialise(db_path: Path | str | None = None) -> duckdb.DuckDBPyConnection:
    """Open a connection with the schema applied and ruleset columns present."""
    from fpl.config import available_rulesets

    con = connect(db_path)
    apply_schema(con)
    ensure_ruleset_columns(con, available_rulesets())
    ensure_sdp_metric_columns(con)
    return con
