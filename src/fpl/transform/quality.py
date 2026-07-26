"""Data-quality validation and the declared NULL repairs.

Two jobs, deliberately separate:

  * `nullify_predicates` turns `config/data_quality.yaml` into SQL that the crosswalk
    applies. Repairs only widen NULL coverage; nothing here writes a value.
  * `validate` records range and consistency violations in `ingest_anomaly`. Gotcha 13:
    pre-season payloads contain glitches -- a goalkeeper with 11 goals and 0 minutes --
    so ranges are validated on ingest, anomalies are logged, and nothing fails silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import duckdb

from fpl.config import DataQualityConfig, load_data_quality


@dataclass(frozen=True, slots=True)
class Anomaly:
    check_id: str
    season: str | None
    detail: str
    row_count: int


def nullify_predicates(
    config: DataQualityConfig | None = None, *, alias: str = "d"
) -> dict[str, list[str]]:
    """Column -> SQL predicates that must resolve to NULL, from declared repairs.

    Predicates are written against `raw_merged_gw`, which is all-VARCHAR, so the gameweek
    comparison casts explicitly. Every reference is qualified with `alias` because these
    predicates are spliced into a query that joins three tables sharing a `season` column.
    """
    resolved = config or load_data_quality()
    result: dict[str, list[str]] = {}
    for rule in resolved.nullify:
        clauses = [f"{alias}.season = '{rule.season}'"]
        if rule.gw_max is not None:
            clauses.append(f'TRY_CAST({alias}."GW" AS INTEGER) <= {rule.gw_max}')
        if rule.gw_min is not None:
            clauses.append(f'TRY_CAST({alias}."GW" AS INTEGER) >= {rule.gw_min}')
        predicate = " AND ".join(clauses)
        for column in rule.columns:
            result.setdefault(column, []).append(predicate)
    return result


def validate(
    con: duckdb.DuckDBPyConnection, config: DataQualityConfig | None = None
) -> list[Anomaly]:
    """Record range and consistency violations against stg_player_fixture.

    Returns what was found. Callers decide whether an anomaly count is acceptable; this
    function never drops or mutates a row.
    """
    resolved = config or load_data_quality()
    now = datetime.now(UTC)
    found: list[Anomaly] = []

    staged_columns = {
        str(name)
        for (name,) in con.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'stg_player_fixture'
            """
        ).fetchall()
    }

    for column, bounds in resolved.ranges.items():
        if column not in staged_columns:
            continue
        rows = con.execute(
            f"""
            SELECT season, element, fixture, {column}
            FROM stg_player_fixture
            WHERE {column} IS NOT NULL AND ({column} < ? OR {column} > ?)
            """,
            [bounds.min, bounds.max],
        ).fetchall()
        for season, element, fixture, observed in rows:
            con.execute(
                """
                INSERT INTO ingest_anomaly
                    (detected_at, check_id, season, element, fixture, column_name, observed, detail)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    now,
                    f"range:{column}",
                    season,
                    element,
                    fixture,
                    column,
                    str(observed),
                    f"{column}={observed} outside [{bounds.min}, {bounds.max}]",
                ],
            )
        if rows:
            found.append(
                Anomaly(
                    check_id=f"range:{column}",
                    season=None,
                    detail=f"{len(rows)} row(s) outside [{bounds.min}, {bounds.max}]",
                    row_count=len(rows),
                )
            )

    for rule in resolved.consistency:
        rows = con.execute(
            f"""
            SELECT season, element, fixture FROM stg_player_fixture WHERE {rule.predicate}
            """
        ).fetchall()
        for season, element, fixture in rows:
            con.execute(
                """
                INSERT INTO ingest_anomaly
                    (detected_at, check_id, season, element, fixture, column_name, observed, detail)
                VALUES (?, ?, ?, ?, ?, NULL, NULL, ?)
                """,
                [now, rule.id, season, element, fixture, rule.description.strip()],
            )
        if rows:
            found.append(
                Anomaly(
                    check_id=rule.id,
                    season=None,
                    detail=f"{len(rows)} row(s) matched: {rule.predicate}",
                    row_count=len(rows),
                )
            )

    return found


def assert_nullify_expectations(
    con: duckdb.DuckDBPyConnection, config: DataQualityConfig | None = None
) -> None:
    """Check each declared repair achieved what it claimed.

    A repair that silently stops matching -- because the archive backfilled the data, or
    a column was renamed -- is worse than no repair, because the config still asserts it
    happened.
    """
    resolved = config or load_data_quality()
    for rule in resolved.nullify:
        if rule.expect is None:
            continue
        for column in rule.columns:
            present = con.execute(
                """
                SELECT count(*) FROM information_schema.columns
                WHERE table_name = 'stg_player_fixture' AND column_name = ?
                """,
                [column],
            ).fetchone()
            if not present or not present[0]:
                continue
            non_null_before = con.execute(
                f"""
                SELECT count(*) FROM stg_player_fixture
                WHERE season = ? AND gw <= ? AND {column} IS NOT NULL
                """,
                [rule.season, rule.expect.null_through_gw],
            ).fetchone()
            if non_null_before and non_null_before[0]:
                raise AssertionError(
                    f"data-quality rule {rule.id!r}: {column} should be NULL through GW"
                    f"{rule.expect.null_through_gw} in {rule.season}, found "
                    f"{non_null_before[0]} non-null row(s)"
                )
            non_null_after = con.execute(
                f"""
                SELECT count(*) FROM stg_player_fixture
                WHERE season = ? AND gw >= ? AND {column} IS NOT NULL
                """,
                [rule.season, rule.expect.not_null_from_gw],
            ).fetchone()
            if not non_null_after or not non_null_after[0]:
                raise AssertionError(
                    f"data-quality rule {rule.id!r}: {column} should have values from GW"
                    f"{rule.expect.not_null_from_gw} in {rule.season}, found none -- the "
                    "repair is over-matching or the source changed"
                )
