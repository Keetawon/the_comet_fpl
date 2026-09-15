"""Append-only development workload storage, intentionally outside the production schema."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import duckdb

TABLES = frozenset(
    {
        "dev_competitive_ingestion",
        "dev_competitive_raw_receipt",
        "dev_competitive_match_version",
        "dev_competitive_participation_version",
        "dev_competitive_coverage_version",
    }
)

DDL = """
CREATE TABLE IF NOT EXISTS dev_competitive_ingestion (
    run_id VARCHAR PRIMARY KEY, record_json JSON NOT NULL
);
CREATE TABLE IF NOT EXISTS dev_competitive_raw_receipt (
    receipt_id VARCHAR PRIMARY KEY, request_url VARCHAR NOT NULL,
    source_known_at TIMESTAMPTZ NOT NULL, captured_at TIMESTAMPTZ NOT NULL,
    source_path VARCHAR NOT NULL, sha256 VARCHAR NOT NULL, status INTEGER NOT NULL,
    body BLOB NOT NULL, record_json JSON NOT NULL
);
CREATE TABLE IF NOT EXISTS dev_competitive_match_version (
    version_id VARCHAR PRIMARY KEY, provider VARCHAR NOT NULL,
    competition_id INTEGER NOT NULL, season VARCHAR NOT NULL, match_id BIGINT NOT NULL,
    kickoff TIMESTAMPTZ NOT NULL, capture_known_at TIMESTAMPTZ NOT NULL,
    interpretation_known_at TIMESTAMPTZ NOT NULL, interpretation_id VARCHAR NOT NULL,
    capture_complete BOOLEAN NOT NULL, interpretation_valid BOOLEAN NOT NULL,
    semantic_sha256 VARCHAR NOT NULL, record_json JSON NOT NULL
);
CREATE TABLE IF NOT EXISTS dev_competitive_participation_version (
    version_id VARCHAR NOT NULL, provider_player_id BIGINT NOT NULL,
    code BIGINT, provider_team_id BIGINT NOT NULL, team_code BIGINT,
    started BOOLEAN, appeared BOOLEAN, nominal_minutes DOUBLE,
    provider_position VARCHAR, formation_membership VARCHAR,
    record_json JSON NOT NULL, PRIMARY KEY(version_id, provider_player_id)
);
CREATE TABLE IF NOT EXISTS dev_competitive_coverage_version (
    run_id VARCHAR PRIMARY KEY, record_json JSON NOT NULL
);
"""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def identity(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def apply_workload_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(DDL)


def semantic_identity(record: dict[str, Any]) -> str:
    """Hash interpreted meaning, not repeat-run bookkeeping or physical source-copy paths."""
    return identity(
        {
            k: v
            for k, v in record.items()
            if k
            not in {
                "interpretation_known_at",
                "identity_source",
                "source_versions",
                "version_id",
                "semantic_sha256",
            }
        }
    )


def append_report(con: duckdb.DuckDBPyConnection, table: str, run_id: str, report: Any) -> None:
    if table not in {"dev_competitive_ingestion", "dev_competitive_coverage_version"}:
        raise ValueError("only explicitly development report tables are writable")
    body = canonical(report)
    prior = con.execute(
        f"SELECT CAST(record_json AS VARCHAR) FROM {table} WHERE run_id=?", [run_id]
    ).fetchone()
    if prior:
        if prior[0] != body:
            raise ValueError("append-only report identity collision")
        return
    con.execute(f"INSERT INTO {table} VALUES (?, ?)", [run_id, body])


def append_receipt(
    con: duckdb.DuckDBPyConnection, *, receipt: dict[str, Any], body: bytes, source_path: str
) -> str:
    if hashlib.sha256(body).hexdigest() != receipt["sha256"] or len(body) != receipt["bytes"]:
        raise ValueError("raw receipt byte identity mismatch")
    rid = identity((receipt["url"], receipt["sha256"], receipt["captured_at_utc"]))
    prior = con.execute(
        "SELECT sha256,body FROM dev_competitive_raw_receipt WHERE receipt_id=?", [rid]
    ).fetchone()
    if prior:
        if prior != (receipt["sha256"], body):
            raise ValueError("append-only raw receipt identity collision")
        return rid
    con.execute(
        "INSERT INTO dev_competitive_raw_receipt VALUES (?,?,?,?,?,?,?,?,?)",
        [
            rid,
            receipt["url"],
            receipt.get("source_known_at", receipt["captured_at_utc"]),
            receipt["captured_at_utc"],
            source_path,
            receipt["sha256"],
            receipt["status"],
            body,
            canonical(receipt),
        ],
    )
    return rid


def append_match(con: duckdb.DuckDBPyConnection, record: dict[str, Any]) -> bool:
    """One whole capture+interpretation version; repeats retain first interpretation time."""
    if semantic_identity(record) != record["semantic_sha256"]:
        raise ValueError("caller semantic hash differs from actual interpreted record")
    prior = con.execute(
        "SELECT semantic_sha256 FROM dev_competitive_match_version WHERE version_id=?",
        [record["version_id"]],
    ).fetchone()
    if prior:
        if prior[0] != record["semantic_sha256"]:
            raise ValueError("same source/interpretation identity produced different semantics")
        return False
    con.execute(
        "INSERT INTO dev_competitive_match_version VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            record["version_id"],
            "pl_sdp",
            record["competition_id"],
            record["season"],
            record["match_id"],
            record["kickoff"],
            record["capture_known_at"],
            record["interpretation_known_at"],
            record["interpretation_id"],
            record["capture_complete"],
            record["interpretation_valid"],
            record["semantic_sha256"],
            canonical(record),
        ],
    )
    for row in record["rows"]:
        con.execute(
            "INSERT INTO dev_competitive_participation_version VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                record["version_id"],
                row["provider_player_id"],
                row["code"],
                row["provider_team_id"],
                row["team_code"],
                row["started"],
                row["appeared"],
                row["nominal_minutes"],
                row["provider_position"],
                row["membership"],
                canonical(row),
            ],
        )
    return True
