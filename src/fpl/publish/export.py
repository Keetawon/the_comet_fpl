"""Atomic, versioned Parquet export for the frozen BI semantic contract.

This is the read-only boundary between the mutable modelling DuckDB and every downstream BI
consumer.  It deliberately reads the database and optimizer decision artifacts, materialises the
complete semantic contract into one Parquet file per table, validates the result, and only then
publishes it.  Dashboards, notebooks, and external BI tools must read this export; they never get a
DuckDB connection.

The export endpoint is a directory symlink to a private sibling generation directory.  Replacing a
symlink is atomic on the supported filesystems, while replacing a non-empty directory is not.  A
reader therefore resolves either the complete old generation or the complete new generation, never
a half-written mix.  A short-lived exclusive lock plus an identity check rejects competing writers
rather than silently clobbering one another.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import tempfile
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, NoReturn

import duckdb
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from fpl.artifacts.optimizer_plan import OptimizerPlanArtifact, read_optimizer_artifact
from fpl.publish.contract import SEMANTIC_CONTRACT_V1, Column, Table
from fpl.storage.db import connect, table_columns, table_exists

BI_EXPORT_SCHEMA: Final[str] = "fpl.bi-semantic-export"
BI_EXPORT_SCHEMA_VERSION: Final[int] = 1
MANIFEST_FILENAME: Final[str] = "manifest.json"
EASE_INDEX_FORMULA_VERSION: Final[str] = "fixture-ease-v1"
_MIN_EASE_INDEX_ROWS: Final[int] = 2

_LEDGER_TABLES: Final[tuple[str, ...]] = (
    "ledger_forecast_run",
    "ledger_prediction_player_gameweek",
    "ledger_prediction_player_fixture",
    "ledger_prediction_team_fixture",
)
_FORECAST_TABLE_NAMES: Final[frozenset[str]] = frozenset(
    {
        "dim_forecast_run",
        "fact_forecast_player_gameweek",
        "fact_forecast_player_fixture",
        "fact_forecast_team_fixture",
    }
)
_SQL_TYPES: Final[dict[str, str]] = {
    "string": "VARCHAR",
    "int": "INTEGER",
    "float": "DOUBLE",
    "bool": "BOOLEAN",
    "timestamp": "TIMESTAMPTZ",
}

# Every source column named below is physically required for a populated source.  Values which the
# ledger intentionally does not persist (fixture-level expected minutes/rates) are represented by
# explicit typed NULL expressions in the projection rather than being guessed or reconstructed
# from another grain. Official FDR is schedule-owned and is sourced separately below.
_SOURCE_COLUMNS: Final[dict[str, tuple[str, ...]]] = {
    "mart_dim_player": (
        "code",
        "season",
        "element_id",
        "web_name",
        "position",
        "team_id",
        "opta_code",
    ),
    "mart_dim_team": ("season", "team_id", "team_code", "team_name", "short_name", "pulse_id"),
    "mart_dim_player_stint": (
        "season",
        "code",
        "team_id",
        "stint_index",
        "first_gw",
        "last_gw",
        "first_kickoff",
        "last_kickoff",
        "appearances",
        "minutes",
    ),
    "stg_fixture": (
        "season",
        "fixture",
        "gw",
        "kickoff_time",
        "team_h",
        "team_a",
        "pulse_id",
        "finished",
    ),
    "mart_fact_player_fixture": (
        "season",
        "fixture",
        "code",
        "gw",
        "kickoff_time",
        "position",
        "team_id",
        "opponent_team_id",
        "was_home",
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
        "defensive_contribution",
        "threat",
        "creativity",
        "influence",
    ),
    "mart_target_player_fixture": (
        "season",
        "fixture",
        "code",
        "total_points_as_recorded",
        "points_under_rules_2026_27",
    ),
    "stg_live_player_version": (
        "season",
        "code",
        "element",
        "known_at",
        "capture_id",
        "web_name",
        "position",
        "team_id",
    ),
    "stg_live_team_version": (
        "season",
        "team_id",
        "team_code",
        "known_at",
        "capture_id",
        "team_name",
        "short_name",
        "pulse_id",
    ),
    "stg_live_fixture_version": (
        "season",
        "fixture",
        "known_at",
        "capture_id",
        "gw",
        "kickoff_time",
        "team_h",
        "team_a",
        "finished",
    ),
    "mart_team_fixture_live": (
        "season",
        "fixture",
        "team_id",
        "fdr",
        "known_at",
        "capture_id",
    ),
    "mart_fact_team_match": ("season", "fixture", "team_id", "fdr"),
    "mart_fact_team_form": (
        "season",
        "gw",
        "team_code",
        "window",
        "matches_played",
        "goals_for",
        "goals_against",
        "clean_sheets",
        "wins",
        "draws",
        "losses",
        "team_xg",
        "team_xgc",
        "goals_for_per_match",
        "goals_against_per_match",
        "team_xg_per_match",
        "team_xgc_per_match",
    ),
    "mart_fact_player_form": (
        "season",
        "gw",
        "code",
        "window",
        "rostered_fixtures",
        "appearances",
        "starts",
        "did_not_play",
        "minutes",
        "goals_scored",
        "assists",
        "bonus",
        "bps",
        "defensive_contribution",
        "expected_goals",
        "expected_assists",
        "expected_goals_per_90",
        "expected_assists_per_90",
        "points_under_rules_2026_27",
        "clean_sheets",
        "goals_conceded",
        "saves",
        "expected_goals_conceded",
    ),
    "ledger_forecast_run": (
        "run_id",
        "created_at",
        "as_of",
        "season",
        "gw_from",
        "gw_to",
        "artifact_schema",
        "schema_version",
        "status",
        "commit_sha",
        "database_sha256",
        "artifact_sha256",
        "base_seed",
        "monte_carlo_draws",
        "row_count",
        "roster_size",
        "contract_identities",
        "component_modes",
        "bootstrap_known_at",
        "freshness_cold_start",
    ),
    "ledger_prediction_player_gameweek": (
        "run_id",
        "season",
        "gw",
        "code",
        "position",
        "team_id",
        "team_code",
        "now_cost",
        "selected_by_percent",
        "availability_status",
        "chance_of_playing",
        "availability_multiplier",
        "expected_points",
        "availability_adjusted_expected_points",
        "expected_bonus",
        "distribution",
        "cold_start_player",
        "stage_a_league_average_team",
        "attacking_signal_cold_start",
        "assist_signal_cold_start",
        "transferred_no_rescale",
    ),
    "ledger_prediction_player_fixture": (
        "run_id",
        "season",
        "gw",
        "fixture",
        "code",
        "kickoff_time",
        "position",
        "team_id",
        "team_code",
        "opponent_team_id",
        "was_home",
        "expected_points",
        "distribution",
        "stage_a_league_average_team",
    ),
    "ledger_prediction_team_fixture": (
        "run_id",
        "season",
        "gw",
        "fixture",
        "team_id",
        "team_code",
        "opponent_team_id",
        "was_home",
        "lambda_for",
        "lambda_against",
        "probability_clean_sheet",
        "goals_for_distribution",
        "stage_a_league_average_team",
    ),
}


class BiExportError(RuntimeError):
    """The BI export cannot truthfully be built or published."""


class BiExportSourceError(BiExportError):
    """A required source table, column, or source value is missing or invalid."""


class BiExportValidationError(BiExportError):
    """The staged Parquet export does not satisfy the frozen semantic contract."""


class BiExportFreshnessError(BiExportError):
    """A recorded forecast's live knowledge provenance is invalid or exceeds an opt-in age bound."""


class BiExportConcurrentWriterError(BiExportError):
    """Another writer owns or changed the export endpoint; no clobber was attempted."""


class OptimizerPlanResolutionError(BiExportError):
    """An optimizer artifact does not resolve to exactly one exported ledger forecast vintage."""


@dataclass(frozen=True, slots=True)
class TableExport:
    """One table's content-addressed entry in the manifest."""

    file: str
    row_count: int
    sha256: str

    def as_dict(self) -> dict[str, object]:
        return {"file": self.file, "row_count": self.row_count, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class BiExportResult:
    """The published endpoint and immutable facts recorded in its manifest."""

    output_dir: Path
    manifest_path: Path
    content_sha256: str
    exported_run_ids: tuple[str, ...]
    tables: Mapping[str, TableExport]


@dataclass(frozen=True, slots=True)
class _ForecastFreshness:
    run_id: str
    as_of: datetime
    known_at: datetime
    cold_start: bool


@dataclass(frozen=True, slots=True)
class _PublishedSnapshot:
    link_target: str
    digest: str


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _canonical_json_bytes(value: object, *, indent: int | None = None) -> bytes:
    text = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        indent=indent,
        separators=None if indent is not None else (",", ":"),
        sort_keys=True,
    )
    return (text + "\n").encode("utf-8")


def _reject_json_constant(value: str) -> NoReturn:
    raise ValueError(f"strict JSON does not permit {value}")


def _strict_json_loads(payload: str) -> dict[str, Any]:
    parsed = json.loads(payload, parse_constant=_reject_json_constant)
    if not isinstance(parsed, dict):
        raise BiExportValidationError("manifest must be a JSON object")
    return parsed


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _database_sha256(path: Path) -> str:
    if not path.is_file():
        raise BiExportSourceError(f"database does not exist or is not a file: {path}")
    return _sha256_file(path)


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise BiExportSourceError("timestamps in the BI boundary must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _utc_from_epoch_us(microseconds: int) -> datetime:
    """Rebuild a UTC instant from a DuckDB ``epoch_us`` value.

    The provenance reads below select ``epoch_us(...)`` instead of the raw ``TIMESTAMPTZ`` so that
    DuckDB never converts a stored timestamp into a Python ``datetime``.  That conversion imports
    ``pytz``, which this project deliberately does not depend on (it pins ``tzdata`` for
    ``zoneinfo``); microseconds since the epoch are exact and carry no timezone name to resolve.
    """
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=microseconds)


def _contract_columns(table: Table) -> tuple[str, ...]:
    return tuple(column.name for column in table.columns)


def _arrow_type(column: Column) -> pa.DataType:
    if column.dtype == "string":
        return pa.string()
    if column.dtype == "int":
        return pa.int32()
    if column.dtype == "float":
        return pa.float64()
    if column.dtype == "bool":
        return pa.bool_()
    if column.dtype == "timestamp":
        return pa.timestamp("us", tz="UTC")
    raise AssertionError(f"unknown semantic dtype {column.dtype!r}")


def _empty_table(table: Table) -> pa.Table:
    schema = pa.schema([pa.field(column.name, _arrow_type(column)) for column in table.columns])
    return pa.Table.from_pylist([], schema=schema)


def _empty_source_sql(table: Table) -> str:
    projections = ", ".join(
        f"CAST(NULL AS {_SQL_TYPES[column.dtype]}) AS {_quote_identifier(column.name)}"
        for column in table.columns
    )
    return f"SELECT {projections} WHERE FALSE"


def _contract_query(table: Table, source_sql: str) -> str:
    projections = ",\n       ".join(
        f"CAST(source.{_quote_identifier(column.name)} AS {_SQL_TYPES[column.dtype]}) "
        f"AS {_quote_identifier(column.name)}"
        for column in table.columns
    )
    order_by = ", ".join(_quote_identifier(column) for column in table.grain)
    return f"""
        SELECT {projections}
        FROM ({source_sql}) AS source
        ORDER BY {order_by}
    """


def _require_source_columns(
    con: duckdb.DuckDBPyConnection, table: str, required: Sequence[str]
) -> None:
    if not table_exists(con, table):
        raise BiExportSourceError(f"required source table {table!r} is missing")
    actual = set(table_columns(con, table))
    missing = sorted(set(required) - actual)
    if missing:
        raise BiExportSourceError(
            f"required source table {table!r} is missing column(s) {missing}; refusing a "
            "partial semantic export"
        )


def _ledger_is_present(con: duckdb.DuckDBPyConnection) -> bool:
    present = {table for table in _LEDGER_TABLES if table_exists(con, table)}
    if not present:
        # `build_db` intentionally does not create ledger tables before the first recorded
        # forecast.  That pristine state is a complete zero-vintage export, not source drift.
        return False
    missing = sorted(set(_LEDGER_TABLES) - present)
    if missing:
        raise BiExportSourceError(
            "ledger schema is partial: present tables cannot be combined with missing table(s) "
            f"{missing}"
        )
    return True


def _validate_source_schema(con: duckdb.DuckDBPyConnection) -> bool:
    ledger_present = _ledger_is_present(con)
    for source_table, columns in _SOURCE_COLUMNS.items():
        if source_table.startswith("ledger_") and not ledger_present:
            continue
        _require_source_columns(con, source_table, columns)
    if ledger_present:
        non_integer_chance = con.execute(
            """
            SELECT count(*)
            FROM ledger_prediction_player_gameweek
            WHERE chance_of_playing IS NOT NULL
              AND chance_of_playing <> floor(chance_of_playing)
            """
        ).fetchone()
        if non_integer_chance is not None and int(non_integer_chance[0]) != 0:
            raise BiExportSourceError(
                "ledger_prediction_player_gameweek.chance_of_playing contains non-integer "
                "values but the semantic contract declares an integer percentage"
            )
    return ledger_present


# Live-season registry, latest committed snapshot per entity. The archive marts cover completed
# seasons only, so a live-season forecast's players, clubs, fixtures and gameweeks are sourced from
# the versioned live staging and unioned into the dimensions for seasons the marts do not carry.
# Point-in-time policy: the dimension shows the current registry (the latest capture per entity);
# forecast facts keep their own as_of/bootstrap_known_at, so no forecast input is affected and no
# leakage is introduced. See docs/bi-export-contract.md.
_LIVE_PLAYER_LATEST: Final[str] = """
    SELECT season, code, element, web_name, position, team_id
    FROM stg_live_player_version
    QUALIFY row_number() OVER (
        PARTITION BY season, code ORDER BY known_at DESC, capture_id DESC
    ) = 1
"""
_LIVE_TEAM_LATEST: Final[str] = """
    SELECT season, team_id, team_code, team_name, short_name, pulse_id
    FROM stg_live_team_version
    WHERE team_code IS NOT NULL
    QUALIFY row_number() OVER (
        PARTITION BY season, team_id ORDER BY known_at DESC, capture_id DESC
    ) = 1
"""
_LIVE_FIXTURE_LATEST: Final[str] = """
    SELECT season, fixture, gw, kickoff_time, team_h, team_a, finished
    FROM stg_live_fixture_version
    QUALIFY row_number() OVER (
        PARTITION BY season, fixture ORDER BY known_at DESC, capture_id DESC
    ) = 1
"""
_LIVE_FDR_LATEST: Final[str] = """
    SELECT season, fixture, team_id, fdr
    FROM mart_team_fixture_live
    QUALIFY row_number() OVER (
        PARTITION BY season, fixture, team_id ORDER BY known_at DESC, capture_id DESC
    ) = 1
"""
_OFFICIAL_FDR: Final[str] = f"""
    SELECT season, fixture, team_id, fdr
    FROM mart_fact_team_match
    UNION ALL
    SELECT live.season, live.fixture, live.team_id, live.fdr
    FROM ({_LIVE_FDR_LATEST}) AS live
    WHERE live.season NOT IN (SELECT DISTINCT season FROM mart_fact_team_match)
"""


def _source_queries(ledger_present: bool) -> dict[str, str]:
    queries: dict[str, str] = {
        "dim_player": f"""
            WITH unified AS (
                SELECT season, element_id AS sort_id, code, web_name, opta_code
                FROM mart_dim_player
                UNION ALL
                SELECT season, element AS sort_id, code, web_name,
                       CAST(NULL AS VARCHAR) AS opta_code
                FROM ({_LIVE_PLAYER_LATEST})
            ),
            opta AS (SELECT code, max(opta_code) AS opta_code FROM unified GROUP BY code),
            ranked AS (
                SELECT code, web_name AS latest_web_name,
                       row_number() OVER (
                           PARTITION BY code ORDER BY season DESC, sort_id DESC
                       ) AS rank_within_code
                FROM unified
            )
            SELECT ranked.code, opta.opta_code, ranked.latest_web_name
            FROM ranked JOIN opta ON opta.code = ranked.code
            WHERE ranked.rank_within_code = 1
        """,
        "dim_player_season": f"""
            SELECT season, code, element_id, web_name, position,
                   team_id AS season_end_team_id
            FROM mart_dim_player
            UNION ALL
            SELECT season, code, element AS element_id, web_name, position,
                   team_id AS season_end_team_id
            FROM ({_LIVE_PLAYER_LATEST})
            WHERE season NOT IN (SELECT DISTINCT season FROM mart_dim_player)
        """,
        "dim_player_stint": """
            SELECT stint.season, stint.code, stint.stint_index, stint.team_id,
                   team.team_code, stint.first_gw, stint.last_gw,
                   stint.first_kickoff, stint.last_kickoff, stint.appearances, stint.minutes
            FROM mart_dim_player_stint AS stint
            LEFT JOIN mart_dim_team AS team
              ON team.season = stint.season
             AND team.team_id = stint.team_id
        """,
        "dim_team": f"""
            WITH unified AS (
                SELECT season, team_id AS sort_id, team_code, team_name, short_name
                FROM mart_dim_team
                UNION ALL
                SELECT season, team_id AS sort_id, team_code, team_name, short_name
                FROM ({_LIVE_TEAM_LATEST})
            ),
            ranked AS (
                SELECT team_code, team_name, short_name,
                       row_number() OVER (
                           PARTITION BY team_code ORDER BY season DESC, sort_id DESC
                       ) AS rank_within_team
                FROM unified
                WHERE team_code IS NOT NULL
            )
            SELECT team_code, team_name, short_name
            FROM ranked
            WHERE rank_within_team = 1
        """,
        "dim_team_season": f"""
            SELECT season, team_id, team_code, team_name, short_name, pulse_id
            FROM mart_dim_team
            UNION ALL
            SELECT season, team_id, team_code, team_name, short_name, pulse_id
            FROM ({_LIVE_TEAM_LATEST})
            WHERE season NOT IN (SELECT DISTINCT season FROM mart_dim_team)
        """,
        "dim_fixture": f"""
            SELECT fixture.season, fixture.fixture, fixture.gw, fixture.kickoff_time,
                   fixture.team_h AS home_team_id, fixture.team_a AS away_team_id,
                   home.team_code AS home_team_code, away.team_code AS away_team_code,
                   fixture.pulse_id, fixture.finished
            FROM stg_fixture AS fixture
            LEFT JOIN mart_dim_team AS home
              ON home.season = fixture.season
             AND home.team_id = fixture.team_h
            LEFT JOIN mart_dim_team AS away
              ON away.season = fixture.season
             AND away.team_id = fixture.team_a
            UNION ALL
            SELECT lf.season, lf.fixture, lf.gw, lf.kickoff_time,
                   lf.team_h AS home_team_id, lf.team_a AS away_team_id,
                   home.team_code AS home_team_code, away.team_code AS away_team_code,
                   CAST(NULL AS INTEGER) AS pulse_id, lf.finished
            FROM ({_LIVE_FIXTURE_LATEST}) AS lf
            LEFT JOIN ({_LIVE_TEAM_LATEST}) AS home
              ON home.season = lf.season AND home.team_id = lf.team_h
            LEFT JOIN ({_LIVE_TEAM_LATEST}) AS away
              ON away.season = lf.season AND away.team_id = lf.team_a
            WHERE lf.season NOT IN (SELECT DISTINCT season FROM stg_fixture)
        """,
        "dim_gameweek": f"""
            SELECT season, gw,
                   CAST(NULL AS TIMESTAMPTZ) AS deadline_time,
                   min(kickoff_time) AS first_kickoff,
                   max(kickoff_time) AS last_kickoff,
                   CAST(count(*) AS INTEGER) AS fixture_count,
                   CASE
                       WHEN count(finished) = count(*) THEN bool_and(finished)
                   END AS finished
            FROM stg_fixture
            WHERE gw IS NOT NULL
            GROUP BY season, gw
            UNION ALL
            SELECT season, gw,
                   CAST(NULL AS TIMESTAMPTZ) AS deadline_time,
                   min(kickoff_time) AS first_kickoff,
                   max(kickoff_time) AS last_kickoff,
                   CAST(count(*) AS INTEGER) AS fixture_count,
                   CASE
                       WHEN count(finished) = count(*) THEN bool_and(finished)
                   END AS finished
            FROM ({_LIVE_FIXTURE_LATEST})
            WHERE gw IS NOT NULL AND season NOT IN (SELECT DISTINCT season FROM stg_fixture)
            GROUP BY season, gw
        """,
        "fact_player_fixture_actual": """
            SELECT fact.season, fact.fixture, fact.code, fact.gw, fact.kickoff_time,
                   fact.position, fact.team_id, team.team_code, fact.opponent_team_id,
                   fact.was_home, fact.minutes, fact.starts, fact.goals_scored, fact.assists,
                   fact.clean_sheets, fact.goals_conceded, fact.saves, fact.penalties_saved,
                   fact.penalties_missed, fact.own_goals, fact.yellow_cards, fact.red_cards,
                   fact.bonus, fact.bps, fact.expected_goals, fact.expected_assists,
                   fact.expected_goals_conceded, fact.defensive_contribution, fact.threat,
                   fact.creativity, fact.influence, target.total_points_as_recorded,
                   target.points_under_rules_2026_27
            FROM mart_fact_player_fixture AS fact
            LEFT JOIN mart_dim_team AS team
              ON team.season = fact.season
             AND team.team_id = fact.team_id
            LEFT JOIN mart_target_player_fixture AS target
              ON target.season = fact.season
             AND target.fixture = fact.fixture
             AND target.code = fact.code
        """,
        "fact_player_form": """
            SELECT season, gw, code, "window", rostered_fixtures, appearances, starts,
                   did_not_play, minutes, goals_scored, assists, bonus, bps,
                   defensive_contribution, expected_goals, expected_assists,
                   expected_goals_per_90, expected_assists_per_90,
                   points_under_rules_2026_27, clean_sheets, goals_conceded, saves,
                   expected_goals_conceded
            FROM mart_fact_player_form
        """,
        "fact_team_form": """
            SELECT season, gw, team_code, "window", matches_played, goals_for, goals_against,
                   clean_sheets, wins, draws, losses, team_xg, team_xgc,
                   goals_for_per_match, goals_against_per_match, team_xg_per_match,
                   team_xgc_per_match
            FROM mart_fact_team_form
        """,
    }
    if not ledger_present:
        for table_name in _FORECAST_TABLE_NAMES:
            queries[table_name] = _empty_source_sql(SEMANTIC_CONTRACT_V1.table(table_name))
        return queries

    queries.update(
        {
            "dim_forecast_run": """
                SELECT run_id, as_of, created_at, season, gw_from, gw_to, status, commit_sha,
                       database_sha256, artifact_sha256, base_seed, monte_carlo_draws, row_count,
                       roster_size, component_modes, contract_identities, bootstrap_known_at
                FROM ledger_forecast_run
            """,
            "fact_forecast_player_gameweek": """
                SELECT prediction.run_id, run.as_of, prediction.season, prediction.gw,
                       prediction.code, prediction.position, prediction.team_id,
                       prediction.team_code, prediction.now_cost, prediction.selected_by_percent,
                       prediction.availability_status,
                       CAST(prediction.chance_of_playing AS INTEGER) AS chance_of_playing,
                       prediction.availability_multiplier, prediction.expected_points,
                       prediction.availability_adjusted_expected_points,
                       prediction.expected_bonus,
                       CAST(to_json(prediction.distribution) AS VARCHAR) AS distribution,
                       prediction.cold_start_player, prediction.stage_a_league_average_team,
                       prediction.attacking_signal_cold_start,
                       prediction.assist_signal_cold_start,
                       prediction.transferred_no_rescale
                FROM ledger_prediction_player_gameweek AS prediction
                LEFT JOIN ledger_forecast_run AS run ON run.run_id = prediction.run_id
            """,
            "fact_forecast_player_fixture": """
                SELECT prediction.run_id, run.as_of, prediction.season, prediction.fixture,
                       prediction.code, prediction.gw, prediction.team_id,
                       prediction.opponent_team_id, prediction.was_home,
                       prediction.expected_points,
                       CAST(to_json(prediction.distribution) AS VARCHAR) AS distribution,
                       CAST(NULL AS DOUBLE) AS expected_minutes,
                       CAST(NULL AS DOUBLE) AS probability_appears,
                       CAST(NULL AS DOUBLE) AS probability_sixty_minutes,
                       CAST(NULL AS DOUBLE) AS expected_goals,
                       CAST(NULL AS DOUBLE) AS expected_assists,
                       CAST(NULL AS DOUBLE) AS probability_clean_sheet
                FROM ledger_prediction_player_fixture AS prediction
                LEFT JOIN ledger_forecast_run AS run ON run.run_id = prediction.run_id
            """,
            "fact_forecast_team_fixture": f"""
                WITH rates AS (
                    SELECT prediction.run_id, run.as_of, prediction.season,
                           prediction.fixture, prediction.team_id, prediction.team_code,
                           prediction.opponent_team_id, prediction.gw, prediction.was_home,
                           prediction.lambda_for, prediction.lambda_against,
                           count(*) OVER (
                               PARTITION BY prediction.run_id, prediction.season
                           ) AS denominator_row_count,
                           avg(prediction.lambda_for) OVER (
                               PARTITION BY prediction.run_id, prediction.season
                           ) AS raw_league_average_team_lambda,
                           prediction.probability_clean_sheet,
                           prediction.stage_a_league_average_team
                    FROM ledger_prediction_team_fixture AS prediction
                    LEFT JOIN ledger_forecast_run AS run ON run.run_id = prediction.run_id
                ),
                denominators AS (
                    SELECT *,
                           CASE
                               WHEN denominator_row_count >= {_MIN_EASE_INDEX_ROWS}
                                AND raw_league_average_team_lambda > 0
                               THEN raw_league_average_team_lambda
                           END AS league_average_team_lambda
                    FROM rates
                ),
                directed AS (
                    SELECT *,
                           CASE WHEN league_average_team_lambda IS NOT NULL
                               THEN 100.0 * lambda_for / league_average_team_lambda
                           END AS attack_ease_index,
                           CASE WHEN league_average_team_lambda IS NOT NULL
                                      AND lambda_against > 0
                               THEN 100.0 * league_average_team_lambda / lambda_against
                           END AS defence_ease_index
                    FROM denominators
                )
                SELECT directed.run_id, directed.as_of, directed.season, directed.fixture,
                       directed.team_id, directed.team_code, directed.opponent_team_id,
                       directed.gw, directed.was_home, directed.lambda_for,
                       directed.lambda_against, directed.league_average_team_lambda,
                       directed.attack_ease_index, directed.defence_ease_index,
                       CASE WHEN directed.attack_ease_index IS NOT NULL
                                  AND directed.defence_ease_index IS NOT NULL
                            THEN sqrt(
                                directed.attack_ease_index * directed.defence_ease_index
                            )
                       END AS overall_ease_index,
                       '{EASE_INDEX_FORMULA_VERSION}' AS ease_index_formula_version,
                       directed.probability_clean_sheet, fdr.fdr AS official_fdr,
                       directed.stage_a_league_average_team
                FROM directed
                LEFT JOIN ({_OFFICIAL_FDR}) AS fdr
                  ON fdr.season = directed.season
                 AND fdr.fixture = directed.fixture
                 AND fdr.team_id = directed.team_id
            """,
        }
    )
    return queries


def _fetch_arrow_table(con: duckdb.DuckDBPyConnection, query: str) -> pa.Table:
    return con.execute(query).to_arrow_table().replace_schema_metadata(None)


def _type_matches(column: Column, actual: pa.DataType) -> bool:
    if column.dtype == "string":
        return bool(pa.types.is_string(actual) or pa.types.is_large_string(actual))
    if column.dtype == "int":
        return bool(pa.types.is_integer(actual))
    if column.dtype == "float":
        return bool(pa.types.is_floating(actual))
    if column.dtype == "bool":
        return bool(pa.types.is_boolean(actual))
    if column.dtype == "timestamp":
        return bool(pa.types.is_timestamp(actual) and actual.tz == "UTC")
    raise AssertionError(f"unknown semantic dtype {column.dtype!r}")


def _null_counts(frame: pa.Table) -> dict[str, int]:
    return {name: int(frame.column(name).null_count) for name in frame.column_names}


def _validate_table_frame(
    table: Table,
    frame: pa.Table,
    *,
    expected_null_counts: Mapping[str, int] | None = None,
) -> None:
    expected_columns = _contract_columns(table)
    if tuple(frame.column_names) != expected_columns:
        raise BiExportValidationError(
            f"{table.name}: columns {tuple(frame.column_names)!r} do not equal the frozen "
            f"contract order {expected_columns!r}"
        )
    for column in table.columns:
        actual = frame.schema.field(column.name).type
        if not _type_matches(column, actual):
            raise BiExportValidationError(
                f"{table.name}.{column.name}: expected {column.dtype}, found {actual}"
            )
        if column.dtype == "float":
            for value in frame.column(column.name).to_pylist():
                if value is not None and not math.isfinite(float(value)):
                    raise BiExportValidationError(
                        f"{table.name}.{column.name}: non-finite float cannot cross the BI boundary"
                    )

    if expected_null_counts is not None:
        actual_null_counts = _null_counts(frame)
        if actual_null_counts != dict(expected_null_counts):
            raise BiExportValidationError(
                f"{table.name}: NULL counts changed between source and Parquet; NULLs must be "
                "preserved rather than zero-filled or converted to NaN"
            )

    grain_columns = [frame.column(name).to_pylist() for name in table.grain]
    keys = list(zip(*grain_columns, strict=True))
    if any(any(value is None for value in key) for key in keys):
        raise BiExportValidationError(f"{table.name}: a grain key is NULL")
    if len(keys) != len(set(keys)):
        raise BiExportValidationError(f"{table.name}: duplicate row(s) at grain {table.grain}")
    if keys != sorted(keys):
        raise BiExportValidationError(
            f"{table.name}: Parquet rows are not in deterministic grain order {table.grain}"
        )


def _validate_referential_integrity(tables: Mapping[str, pa.Table]) -> None:
    con = duckdb.connect(":memory:")
    try:
        for table in SEMANTIC_CONTRACT_V1.tables:
            con.register(table.name, tables[table.name])
        for child in SEMANTIC_CONTRACT_V1.tables:
            for join in child.joins:
                parent = SEMANTIC_CONTRACT_V1.table(join.to_table)
                on = " AND ".join(
                    f"child.{_quote_identifier(local)} = parent.{_quote_identifier(remote)}"
                    for local, remote in join.on
                )
                non_null = " AND ".join(
                    f"child.{_quote_identifier(local)} IS NOT NULL" for local, _ in join.on
                )
                parent_key = _quote_identifier(parent.grain[0])
                violation = con.execute(
                    f"""
                    SELECT 1
                    FROM {_quote_identifier(child.name)} AS child
                    LEFT JOIN {_quote_identifier(parent.name)} AS parent ON {on}
                    WHERE {non_null}
                      AND parent.{parent_key} IS NULL
                    LIMIT 1
                    """
                ).fetchone()
                if violation is not None:
                    raise BiExportValidationError(
                        f"{child.name}: referential-integrity violation joining {parent.name} "
                        f"on {join.on}; season-scoped ids must resolve within their season"
                    )
    finally:
        con.close()


def _write_parquet(path: Path, frame: pa.Table) -> None:
    pq.write_table(
        frame.replace_schema_metadata(None),
        path,
        compression="zstd",
        data_page_version="1.0",
        row_group_size=65_536,
        use_dictionary=False,
        version="2.6",
        write_statistics=True,
    )
    _fsync_file(path)


def _fsync_file(path: Path) -> None:
    # Append mode opens a writable descriptor without truncating: os.fsync needs one on
    # Windows (a read-only handle raises EBADF) and nothing is appended.
    with path.open("ab") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    """Best-effort directory fsync.  Windows does not expose directory descriptors."""
    if os.name == "nt":
        return
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        # The atomic swap already provides reader consistency; a filesystem that rejects a
        # directory fsync should not turn a successfully published export into a false failure.
        pass
    finally:
        os.close(descriptor)


def _strict_manifest_content_sha256(manifest: Mapping[str, Any]) -> str:
    content = dict(manifest)
    content.pop("created_at", None)
    content.pop("content_sha256", None)
    return _sha256_bytes(_canonical_json_bytes(content))


def _assess_freshness(
    con: duckdb.DuckDBPyConnection,
    *,
    ledger_present: bool,
    maximum_source_age: timedelta | None,
) -> tuple[tuple[str, ...], dict[str, object], dict[str, str | None]]:
    if maximum_source_age is not None and maximum_source_age < timedelta(0):
        raise ValueError("maximum_source_age must be non-negative")
    if not ledger_present:
        freshness: dict[str, object] = {
            "status": "complete_no_recorded_forecast_runs",
            "all_known_at_at_or_before_as_of": True,
            "cold_start_run_ids": [],
            "source_age_seconds": {"minimum": None, "maximum": None},
            "maximum_source_age_seconds": (
                None if maximum_source_age is None else maximum_source_age.total_seconds()
            ),
        }
        return (), freshness, {"minimum": None, "maximum": None}

    raw_rows = con.execute(
        """
        SELECT run_id, epoch_us(as_of) AS as_of_us,
               epoch_us(bootstrap_known_at) AS known_at_us, freshness_cold_start
        FROM ledger_forecast_run
        ORDER BY run_id
        """
    ).fetchall()
    records: list[_ForecastFreshness] = []
    for raw in raw_rows:
        run_id, as_of_us, known_at_us, cold_start = raw
        if (
            not isinstance(run_id, str)
            or not isinstance(as_of_us, int)
            or isinstance(as_of_us, bool)
            or not isinstance(known_at_us, int)
            or isinstance(known_at_us, bool)
        ):
            raise BiExportSourceError(
                "ledger forecast provenance has an invalid timestamp or run id"
            )
        as_of = _utc_from_epoch_us(as_of_us)
        known_at = _utc_from_epoch_us(known_at_us)
        if known_at > as_of:
            raise BiExportFreshnessError(
                f"run {run_id} has bootstrap_known_at after as_of; future knowledge cannot be "
                "published as a forecast vintage"
            )
        age = as_of - known_at
        if maximum_source_age is not None and age > maximum_source_age:
            raise BiExportFreshnessError(
                f"run {run_id} source knowledge is {age.total_seconds():.0f}s old, exceeding "
                f"the requested maximum of {maximum_source_age.total_seconds():.0f}s"
            )
        records.append(
            _ForecastFreshness(
                run_id=run_id,
                as_of=as_of,
                known_at=known_at,
                cold_start=bool(cold_start),
            )
        )

    ages = [record.as_of - record.known_at for record in records]
    known_values = [record.known_at for record in records]
    run_ids = tuple(record.run_id for record in records)
    freshness = {
        "status": "known_at_valid" if records else "complete_no_recorded_forecast_runs",
        "all_known_at_at_or_before_as_of": True,
        "cold_start_run_ids": [record.run_id for record in records if record.cold_start],
        "source_age_seconds": {
            "minimum": min((age.total_seconds() for age in ages), default=None),
            "maximum": max((age.total_seconds() for age in ages), default=None),
        },
        "maximum_source_age_seconds": (
            None if maximum_source_age is None else maximum_source_age.total_seconds()
        ),
    }
    known_at_bounds = {
        "minimum": _isoformat(min(known_values, default=None)),
        "maximum": _isoformat(max(known_values, default=None)),
    }
    return run_ids, freshness, known_at_bounds


def _forecast_run_for_plan(
    con: duckdb.DuckDBPyConnection, artifact: OptimizerPlanArtifact, path: Path
) -> tuple[str, datetime]:
    forecast = artifact.provenance.forecast
    rows = con.execute(
        """
        SELECT run_id, epoch_us(as_of) AS as_of_us, season, gw_from, gw_to, commit_sha,
               artifact_schema, schema_version
        FROM ledger_forecast_run
        WHERE artifact_sha256 = ?
        """,
        [forecast.sha256],
    ).fetchall()
    if len(rows) != 1:
        raise OptimizerPlanResolutionError(
            f"optimizer plan {path} refers to forecast SHA {forecast.sha256}, which resolves to "
            f"{len(rows)} exported ledger run(s), expected exactly one"
        )
    run_id, as_of_us, season, gw_from, gw_to, commit_sha, schema, schema_version = rows[0]
    if not isinstance(run_id, str) or not isinstance(as_of_us, int) or isinstance(as_of_us, bool):
        raise OptimizerPlanResolutionError(
            f"optimizer plan {path} resolved malformed ledger provenance"
        )
    as_of = _utc_from_epoch_us(as_of_us)
    expected = (
        forecast.as_of,
        forecast.season,
        forecast.gw_from,
        forecast.gw_to,
        forecast.commit_sha,
        forecast.forecast_schema,
        forecast.forecast_schema_version,
    )
    observed = (as_of, season, gw_from, gw_to, commit_sha, schema, schema_version)
    if observed != expected:
        raise OptimizerPlanResolutionError(
            f"optimizer plan {path} forecast provenance disagrees with ledger run {run_id}"
        )
    return run_id, as_of


def _load_optimizer_artifacts(
    con: duckdb.DuckDBPyConnection, paths: Sequence[Path]
) -> list[tuple[OptimizerPlanArtifact, Path, str, datetime]]:
    artifacts: list[tuple[OptimizerPlanArtifact, Path, str, datetime]] = []
    seen_run_ids: set[str] = set()
    for raw_path in paths:
        path = Path(raw_path)
        try:
            artifact = read_optimizer_artifact(path)
        except (OSError, ValueError) as exc:
            raise OptimizerPlanResolutionError(f"cannot read optimizer plan {path}: {exc}") from exc
        if artifact.run_id in seen_run_ids:
            raise OptimizerPlanResolutionError(
                f"optimizer input paths include duplicate optimizer run {artifact.run_id}"
            )
        seen_run_ids.add(artifact.run_id)
        forecast_run_id, as_of = _forecast_run_for_plan(con, artifact, path)
        artifacts.append((artifact, path, forecast_run_id, as_of))
    return sorted(artifacts, key=lambda item: item[0].run_id)


def _optimizer_run_records(
    artifacts: Sequence[tuple[OptimizerPlanArtifact, Path, str, datetime]],
) -> tuple[dict[str, object], ...]:
    """Run-level provenance for dim_optimizer_run: one row per decision artifact, carrying
    the solver identity, search policy, rules snapshot, and assumptions verbatim (the JSON
    columns deterministic with sorted keys)."""
    records: list[dict[str, object]] = []
    for artifact, _, forecast_run_id, as_of in artifacts:
        provenance = artifact.provenance
        records.append(
            {
                "optimizer_run_id": artifact.run_id,
                "decision_sha256": artifact.decision_sha256,
                "forecast_run_id": forecast_run_id,
                "as_of": as_of,
                "season": provenance.forecast.season,
                "gw_from": provenance.forecast.gw_from,
                "gw_to": provenance.forecast.gw_to,
                "optimizer_commit_sha": provenance.optimizer_commit_sha,
                "optimizer_worktree_clean": provenance.optimizer_worktree_clean,
                "forecast_artifact_sha256": provenance.forecast.sha256,
                "forecast_commit_sha": provenance.forecast.commit_sha,
                "squad_rules_path": provenance.squad_rules.path,
                "squad_rules_contract_version": provenance.squad_rules.contract_version,
                "squad_rules_sha256": provenance.squad_rules.sha256,
                "solver_name": artifact.solver.name,
                "solver_package": artifact.solver.package,
                "solver_package_version": artifact.solver.package_version,
                "solver_binary_version": artifact.solver.binary_version,
                "solver_options": _canonical_json_bytes(list(artifact.solver.options)).decode(
                    "utf-8"
                ),
                "solver_seed": artifact.solver.seed,
                "solver_status": artifact.solver.status,
                "search_method": artifact.search_policy.search_method,
                "optimality_scope": artifact.search_policy.optimality_scope,
                "risk_lambda": artifact.search_policy.risk_lambda,
                "search_policy": _canonical_json_bytes(artifact.search_policy.model_dump()).decode(
                    "utf-8"
                ),
                "rules_snapshot": _canonical_json_bytes(artifact.rules.model_dump()).decode(
                    "utf-8"
                ),
                "assumptions": _canonical_json_bytes(list(artifact.assumptions)).decode("utf-8"),
                "status": artifact.status,
            }
        )
    return tuple(records)


def _optimizer_plan_records(
    artifacts: Sequence[tuple[OptimizerPlanArtifact, Path, str, datetime]],
) -> tuple[dict[str, object], ...]:
    records: list[dict[str, object]] = []
    for artifact, _, forecast_run_id, as_of in artifacts:
        for week in artifact.plan.weeks:
            starter_codes = {player.code for player in week.starting_xi}
            bench_order = {
                player.code: index for index, player in enumerate(week.bench_order, start=1)
            }
            transferred_in = {player.code for player in week.transfers_in}
            transferred_out = {player.code for player in week.transfers_out}
            for member in week.squad_after_transfers:
                if member.code in starter_codes:
                    role = "starting_xi"
                    bench_order_index: int | None = None
                elif member.code == week.bench_goalkeeper.code:
                    role = "bench_goalkeeper"
                    bench_order_index = None
                else:
                    role = "bench_outfield"
                    bench_order_index = bench_order.get(member.code)
                    if bench_order_index is None:
                        raise OptimizerPlanResolutionError(
                            f"optimizer run {artifact.run_id} has no role for code {member.code} "
                            f"in GW{week.gw}"
                        )
                records.append(
                    {
                        "optimizer_run_id": artifact.run_id,
                        "decision_sha256": artifact.decision_sha256,
                        "forecast_run_id": forecast_run_id,
                        "as_of": as_of,
                        "season": artifact.provenance.forecast.season,
                        "gw": week.gw,
                        "code": member.code,
                        "role": role,
                        "bench_order_index": bench_order_index,
                        "is_captain": member.code == week.captain.code,
                        "is_vice_captain": member.code == week.vice_captain.code,
                        "now_cost": member.now_cost,
                        "transferred_in": member.code in transferred_in,
                        # A v1 decision row is the *post-transfer* squad.  An outgoing player
                        # has no role in that gameweek and therefore no row at this grain; this
                        # expression is intentionally false for valid v1 artifacts rather than
                        # inventing a role for a player who has left the squad.
                        "transferred_out": member.code in transferred_out,
                        "hit_points_this_gw": week.hit_points,
                    }
                )
    return tuple(sorted(records, key=_optimizer_record_sort_key))


def _optimizer_record_sort_key(row: Mapping[str, object]) -> tuple[str, int, int]:
    gw = row["gw"]
    code = row["code"]
    if not isinstance(gw, int) or not isinstance(code, int):
        raise AssertionError("optimizer record has non-integer semantic grain")
    return str(row["optimizer_run_id"]), gw, code


def _manifest(
    *,
    created_at: datetime,
    database_sha256: str,
    exported_run_ids: Sequence[str],
    source_known_at: Mapping[str, str | None],
    freshness: Mapping[str, object],
    tables: Mapping[str, TableExport],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": BI_EXPORT_SCHEMA,
        "schema_version": BI_EXPORT_SCHEMA_VERSION,
        "semantic_contract_version": SEMANTIC_CONTRACT_V1.version,
        "created_at": _isoformat(created_at),
        "database_sha256": database_sha256,
        "exported_run_ids": list(exported_run_ids),
        "source_known_at": dict(source_known_at),
        "freshness": dict(freshness),
        "tables": {name: entry.as_dict() for name, entry in sorted(tables.items())},
    }
    payload["content_sha256"] = _strict_manifest_content_sha256(payload)
    return payload


def _parse_manifest(output_dir: Path) -> dict[str, Any]:
    manifest_path = output_dir / MANIFEST_FILENAME
    try:
        return _strict_json_loads(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BiExportValidationError(f"manifest is unreadable at {manifest_path}: {exc}") from exc
    except (TypeError, ValueError) as exc:
        raise BiExportValidationError(f"manifest is not strict JSON: {exc}") from exc


def _manifest_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise BiExportValidationError(f"manifest {field} must be an ISO timestamp string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise BiExportValidationError(f"manifest {field} is not ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BiExportValidationError(f"manifest {field} must be timezone-aware")
    return parsed


def _manifest_optional_timestamp(value: object, field: str) -> datetime | None:
    return None if value is None else _manifest_timestamp(value, field)


def _manifest_non_negative_seconds(value: object, field: str) -> None:
    if value is None:
        return
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value < 0
    ):
        raise BiExportValidationError(
            f"manifest {field} must be a finite non-negative number or null"
        )


def _assert_manifest_shape(manifest: Mapping[str, Any]) -> None:
    expected_keys = {
        "schema",
        "schema_version",
        "semantic_contract_version",
        "created_at",
        "database_sha256",
        "exported_run_ids",
        "source_known_at",
        "freshness",
        "tables",
        "content_sha256",
    }
    if set(manifest) != expected_keys:
        raise BiExportValidationError(
            f"manifest fields drifted: expected {sorted(expected_keys)}, found {sorted(manifest)}"
        )
    if (
        manifest["schema"] != BI_EXPORT_SCHEMA
        or manifest["schema_version"] != BI_EXPORT_SCHEMA_VERSION
    ):
        raise BiExportValidationError("manifest export schema/version does not match this exporter")
    if manifest["semantic_contract_version"] != SEMANTIC_CONTRACT_V1.version:
        raise BiExportValidationError("manifest semantic contract version does not match v1")
    _manifest_timestamp(manifest["created_at"], "created_at")
    if not _is_sha256(manifest["database_sha256"]):
        raise BiExportValidationError("manifest database_sha256 must be a SHA-256 string")
    run_ids = manifest["exported_run_ids"]
    if not isinstance(run_ids, list) or any(not isinstance(run_id, str) for run_id in run_ids):
        raise BiExportValidationError("manifest exported_run_ids must be a list of strings")
    known_at = manifest["source_known_at"]
    if not isinstance(known_at, dict) or set(known_at) != {"minimum", "maximum"}:
        raise BiExportValidationError("manifest source_known_at is malformed")
    minimum_known_at = _manifest_optional_timestamp(known_at["minimum"], "source_known_at.minimum")
    maximum_known_at = _manifest_optional_timestamp(known_at["maximum"], "source_known_at.maximum")
    if (minimum_known_at is None) != (maximum_known_at is None) or (
        minimum_known_at is not None
        and maximum_known_at is not None
        and minimum_known_at > maximum_known_at
    ):
        raise BiExportValidationError("manifest source_known_at minimum/maximum are inconsistent")
    freshness = manifest["freshness"]
    expected_freshness_keys = {
        "status",
        "all_known_at_at_or_before_as_of",
        "cold_start_run_ids",
        "source_age_seconds",
        "maximum_source_age_seconds",
    }
    if not isinstance(freshness, dict) or set(freshness) != expected_freshness_keys:
        raise BiExportValidationError("manifest freshness is malformed")
    if not isinstance(freshness["status"], str) or not isinstance(
        freshness["all_known_at_at_or_before_as_of"], bool
    ):
        raise BiExportValidationError("manifest freshness status/known-at flag are malformed")
    cold_start_run_ids = freshness["cold_start_run_ids"]
    if not isinstance(cold_start_run_ids, list) or any(
        not isinstance(run_id, str) for run_id in cold_start_run_ids
    ):
        raise BiExportValidationError("manifest freshness cold_start_run_ids are malformed")
    source_age = freshness["source_age_seconds"]
    if not isinstance(source_age, dict) or set(source_age) != {"minimum", "maximum"}:
        raise BiExportValidationError("manifest freshness source_age_seconds is malformed")
    _manifest_non_negative_seconds(source_age["minimum"], "freshness.source_age_seconds.minimum")
    _manifest_non_negative_seconds(source_age["maximum"], "freshness.source_age_seconds.maximum")
    _manifest_non_negative_seconds(
        freshness["maximum_source_age_seconds"], "freshness.maximum_source_age_seconds"
    )
    if not _is_sha256(manifest["content_sha256"]):
        raise BiExportValidationError("manifest content_sha256 must be a SHA-256 string")
    expected_content = _strict_manifest_content_sha256(manifest)
    if manifest["content_sha256"] != expected_content:
        raise BiExportValidationError(
            "manifest content_sha256 does not match content excluding created_at"
        )


def _validate_export_directory(
    output_dir: Path,
    *,
    expected_null_counts: Mapping[str, Mapping[str, int]] | None,
) -> dict[str, Any]:
    manifest = _parse_manifest(output_dir)
    _assert_manifest_shape(manifest)
    table_metadata = manifest["tables"]
    if not isinstance(table_metadata, dict):
        raise BiExportValidationError("manifest tables must be an object")
    expected_table_names = {table.name for table in SEMANTIC_CONTRACT_V1.tables}
    if set(table_metadata) != expected_table_names:
        raise BiExportValidationError(
            "manifest does not enumerate exactly the semantic contract tables"
        )
    expected_files = {MANIFEST_FILENAME}
    frames: dict[str, pa.Table] = {}
    for table in SEMANTIC_CONTRACT_V1.tables:
        entry = table_metadata[table.name]
        if not isinstance(entry, dict) or set(entry) != {"file", "row_count", "sha256"}:
            raise BiExportValidationError(f"manifest entry for {table.name} is malformed")
        filename = entry["file"]
        if filename != f"{table.name}.parquet":
            raise BiExportValidationError(f"manifest file for {table.name} is not canonical")
        if not isinstance(entry["row_count"], int) or entry["row_count"] < 0:
            raise BiExportValidationError(f"manifest row count for {table.name} is invalid")
        if not isinstance(entry["sha256"], str) or len(entry["sha256"]) != 64:
            raise BiExportValidationError(f"manifest SHA-256 for {table.name} is invalid")
        path = output_dir / filename
        if not path.is_file():
            raise BiExportValidationError(f"missing Parquet file for {table.name}")
        if _sha256_file(path) != entry["sha256"]:
            raise BiExportValidationError(f"Parquet SHA-256 mismatch for {table.name}")
        frame = pq.read_table(path).replace_schema_metadata(None)
        if frame.num_rows != entry["row_count"]:
            raise BiExportValidationError(
                f"manifest row count does not match Parquet for {table.name}"
            )
        null_counts = None if expected_null_counts is None else expected_null_counts[table.name]
        _validate_table_frame(table, frame, expected_null_counts=null_counts)
        frames[table.name] = frame
        expected_files.add(filename)

    actual_files = {path.name for path in output_dir.iterdir()}
    if actual_files != expected_files:
        raise BiExportValidationError(
            f"export directory must contain exactly manifest plus one Parquet per table; found "
            f"{sorted(actual_files)}"
        )
    _validate_referential_integrity(frames)

    run_ids = tuple(frames["dim_forecast_run"].column("run_id").to_pylist())
    manifest_run_ids = manifest["exported_run_ids"]
    if not isinstance(manifest_run_ids, list) or tuple(manifest_run_ids) != run_ids:
        raise BiExportValidationError("manifest exported_run_ids do not equal dim_forecast_run")
    if list(run_ids) != sorted(run_ids):
        raise BiExportValidationError("manifest run ids are not deterministically ordered")
    return manifest


def validate_bi_export(output_dir: Path) -> dict[str, Any]:
    """Re-open and validate a published export without touching the production DuckDB."""
    return _validate_export_directory(Path(output_dir), expected_null_counts=None)


def _tree_digest(root: Path) -> str:
    if not root.is_dir() or root.is_symlink():
        raise BiExportConcurrentWriterError(
            f"managed export generation is not a real directory: {root}"
        )
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        if path.is_symlink():
            raise BiExportConcurrentWriterError("managed export generation contains a symlink")
        if path.is_dir():
            digest.update(b"D\0" + relative + b"\0")
        elif path.is_file():
            digest.update(b"F\0" + relative + b"\0" + _sha256_file(path).encode("ascii") + b"\0")
        else:
            raise BiExportConcurrentWriterError(
                f"managed export generation has unsupported path {path}"
            )
    return digest.hexdigest()


def _managed_generation(output_dir: Path) -> tuple[str, Path]:
    if not output_dir.is_symlink():
        raise BiExportConcurrentWriterError(
            f"{output_dir} exists but is not a managed atomic-export symlink; refusing to "
            "replace an unmanaged directory"
        )
    link_target = os.readlink(output_dir)
    candidate = output_dir.parent / link_target
    required_prefix = f".{output_dir.name}.generation."
    if (
        Path(link_target).is_absolute()
        or candidate.parent != output_dir.parent
        or not candidate.name.startswith(required_prefix)
        or not candidate.exists()
    ):
        raise BiExportConcurrentWriterError(
            f"{output_dir} does not point at a managed sibling generation; refusing to clobber it"
        )
    return link_target, candidate


def _published_snapshot(output_dir: Path) -> _PublishedSnapshot | None:
    if not output_dir.exists() and not output_dir.is_symlink():
        return None
    link_target, generation = _managed_generation(output_dir)
    return _PublishedSnapshot(link_target=link_target, digest=_tree_digest(generation))


@contextmanager
def _export_lock(output_dir: Path) -> Iterator[None]:
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    lock = output_dir.parent / f".{output_dir.name}.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise BiExportConcurrentWriterError(
            f"another writer is already publishing {output_dir}; no clobber was attempted"
        ) from exc
    try:
        os.write(descriptor, b"fpl-bi-export\n")
        os.fsync(descriptor)
        yield
    finally:
        os.close(descriptor)
        lock.unlink(missing_ok=True)


def _resolve_output_dir(output_dir: Path) -> Path:
    # Resolve only the parent.  Resolving ``output_dir`` itself would follow the current
    # generation symlink and turn a subsequent publish into an attempt to replace that immutable
    # generation directory rather than the stable endpoint name.
    parent = output_dir.parent.resolve()
    resolved = parent / output_dir.name
    if resolved == resolved.parent or not resolved.name:
        raise ValueError("output_dir must name a concrete child directory")
    return resolved


def _publish_generation(
    *,
    output_dir: Path,
    temporary_dir: Path,
    original: _PublishedSnapshot | None,
) -> None:
    if _published_snapshot(output_dir) != original:
        raise BiExportConcurrentWriterError(
            f"{output_dir} changed while this export was being built; previous content was left "
            "intact"
        )
    generation = output_dir.parent / f".{output_dir.name}.generation.{uuid.uuid4().hex}"
    pointer = output_dir.parent / f".{output_dir.name}.pointer.{uuid.uuid4().hex}.tmp"
    moved_generation = False
    promoted = False
    old_generation: Path | None = None
    try:
        if original is not None:
            _, old_generation = _managed_generation(output_dir)
        os.replace(temporary_dir, generation)
        moved_generation = True
        os.symlink(generation.name, pointer, target_is_directory=True)
        os.replace(pointer, output_dir)
        promoted = True
        _fsync_directory(output_dir.parent)
    finally:
        pointer.unlink(missing_ok=True)
        if moved_generation and not promoted:
            shutil.rmtree(generation, ignore_errors=True)
    if old_generation is not None:
        # It is private and has already ceased to be visible through the published endpoint.
        shutil.rmtree(old_generation, ignore_errors=True)


def export_bi(
    db_path: Path,
    output_dir: Path,
    *,
    optimizer_plan_paths: Sequence[Path] = (),
    created_at: datetime | None = None,
    maximum_source_age: timedelta | None = None,
    before_publish: Callable[[], None] | None = None,
) -> BiExportResult:
    """Materialise and atomically publish the complete v1 semantic contract.

    ``optimizer_plan_paths`` is an explicit 0..N input.  Each parsed optimizer artifact must map
    through its forecast SHA to exactly one recorded ledger run; passing no paths publishes an empty
    optimizer-plan fact.  A database with no ledger tables at all is the supported fresh-build case:
    all forecast facts and ``dim_forecast_run`` are empty, while the contract remains complete.
    """
    source_path = Path(db_path).resolve()
    target = _resolve_output_dir(Path(output_dir))
    stamp = created_at or datetime.now(UTC)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("created_at must be timezone-aware")
    stamp = stamp.astimezone(UTC)

    with _export_lock(target):
        original = _published_snapshot(target)
        temporary_dir = Path(
            tempfile.mkdtemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        )
        try:
            database_sha256 = _database_sha256(source_path)
            con = connect(source_path, read_only=True)
            try:
                ledger_present = _validate_source_schema(con)
                exported_run_ids, freshness, source_known_at = _assess_freshness(
                    con,
                    ledger_present=ledger_present,
                    maximum_source_age=maximum_source_age,
                )
                if optimizer_plan_paths and not ledger_present:
                    raise OptimizerPlanResolutionError(
                        "optimizer plans require a recorded forecast ledger run, but this "
                        "database has no ledger schema or recorded runs"
                    )
                optimizer_artifacts = _load_optimizer_artifacts(con, optimizer_plan_paths)
                optimizer_records = _optimizer_plan_records(optimizer_artifacts)
                optimizer_runs = _optimizer_run_records(optimizer_artifacts)
                queries = _source_queries(ledger_present)

                injected: Mapping[str, tuple[dict[str, object], ...]] = {
                    "fact_optimizer_plan": optimizer_records,
                    "dim_optimizer_run": optimizer_runs,
                }
                table_exports: dict[str, TableExport] = {}
                expected_null_counts: dict[str, dict[str, int]] = {}
                for table in SEMANTIC_CONTRACT_V1.tables:
                    if table.name in injected:
                        rows = injected[table.name]
                        frame = (
                            pa.Table.from_pylist(
                                list(rows),
                                schema=pa.schema(
                                    [
                                        pa.field(column.name, _arrow_type(column))
                                        for column in table.columns
                                    ]
                                ),
                            )
                            if rows
                            else _empty_table(table)
                        )
                    else:
                        source_sql = queries[table.name]
                        frame = _fetch_arrow_table(con, _contract_query(table, source_sql))
                    expected_null_counts[table.name] = _null_counts(frame)
                    _validate_table_frame(
                        table,
                        frame,
                        expected_null_counts=expected_null_counts[table.name],
                    )
                    path = temporary_dir / f"{table.name}.parquet"
                    _write_parquet(path, frame)
                    table_exports[table.name] = TableExport(
                        file=path.name,
                        row_count=frame.num_rows,
                        sha256=_sha256_file(path),
                    )
            finally:
                con.close()

            if _database_sha256(source_path) != database_sha256:
                raise BiExportSourceError(
                    "source database changed while the BI export was being built; refusing to "
                    "publish an unverifiable mixed snapshot"
                )

            manifest = _manifest(
                created_at=stamp,
                database_sha256=database_sha256,
                exported_run_ids=exported_run_ids,
                source_known_at=source_known_at,
                freshness=freshness,
                tables=table_exports,
            )
            manifest_path = temporary_dir / MANIFEST_FILENAME
            manifest_path.write_bytes(_canonical_json_bytes(manifest, indent=2))
            _fsync_file(manifest_path)
            _fsync_directory(temporary_dir)
            _validate_export_directory(temporary_dir, expected_null_counts=expected_null_counts)
            if before_publish is not None:
                before_publish()
            _publish_generation(output_dir=target, temporary_dir=temporary_dir, original=original)
        finally:
            # After a successful os.replace the old staging pathname no longer exists, so this is
            # harmless; on every error it removes the sibling temporary tree.
            shutil.rmtree(temporary_dir, ignore_errors=True)

    return BiExportResult(
        output_dir=target,
        manifest_path=target / MANIFEST_FILENAME,
        content_sha256=str(manifest["content_sha256"]),
        exported_run_ids=tuple(exported_run_ids),
        tables=table_exports,
    )


__all__ = [
    "BI_EXPORT_SCHEMA",
    "BI_EXPORT_SCHEMA_VERSION",
    "EASE_INDEX_FORMULA_VERSION",
    "BiExportConcurrentWriterError",
    "BiExportError",
    "BiExportFreshnessError",
    "BiExportResult",
    "BiExportSourceError",
    "BiExportValidationError",
    "OptimizerPlanResolutionError",
    "TableExport",
    "export_bi",
    "validate_bi_export",
]
