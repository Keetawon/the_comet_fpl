"""Append one corroborated card-enum interpretation to a NEW copy of retained workload data."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import traceback
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import duckdb
import yaml

from fpl.config import repo_root
from fpl.jobs import capture_competitive_workload as capture
from fpl.jobs import stage_competitive_workload as staging
from fpl.jobs.build_db import _sha256, _wal_path
from fpl.jobs.competitive_participation_pilot import file_sha256, publish_json, reference_data
from fpl.jobs.daily_pl_sdp import writer_lock
from fpl.storage.competitive_workload import (
    TABLES,
    append_match,
    append_report,
    identity,
    semantic_identity,
)
from fpl.transform.competitive_participation import ParticipationError, exact_crosswalk
from fpl.transform.competitive_participation_v3 import INTERPRETATION_ID, parse_participation_v3

CONFIG = "config/competitive_participation_v3.yaml"
SOURCE_FILES = tuple(
    sorted(
        {
            *staging.SOURCE_FILES,
            CONFIG,
            "src/fpl/jobs/restage_competitive_participation_v3.py",
            "src/fpl/transform/competitive_participation_v3.py",
            "docs/competitive-participation-v3.md",
            "results/competitive_straight_red_source_audit.json",
            "tests/test_competitive_participation_v3.py",
        }
    )
)


def source_rows(con: duckdb.DuckDBPyConnection, interpretation_id: str) -> list[dict[str, Any]]:
    return [
        json.loads(row[0])
        for row in con.execute(
            "SELECT CAST(record_json AS VARCHAR) FROM dev_competitive_match_version "
            "WHERE interpretation_id=? ORDER BY match_id,version_id",
            [interpretation_id],
        ).fetchall()
    ]


def endpoint_payloads(con: duckdb.DuckDBPyConnection, record: dict[str, Any]) -> dict[str, Any]:
    payloads = {}
    for rid in record["receipt_ids"]:
        row = con.execute(
            "SELECT request_url,sha256,body FROM dev_competitive_raw_receipt WHERE receipt_id=?",
            [rid],
        ).fetchone()
        if row is None or hashlib.sha256(row[2]).hexdigest() != row[1]:
            raise ValueError("retained raw receipt missing or byte hash differs")
        path = urlparse(row[0]).path
        for endpoint in ("lineups", "events"):
            if path.endswith(f"/matches/{record['match_id']}/{endpoint}"):
                if endpoint in payloads:
                    raise ValueError("whole version has duplicate endpoint receipts")
                if record["source_versions"][endpoint]["sha256"] != row[1]:
                    raise ValueError("endpoint SHA contradicts whole source version")
                payloads[endpoint] = json.loads(row[2])
    if set(payloads) != {"lineups", "events"}:
        raise ValueError("complete retained source endpoints required")
    return payloads


def reinterpret(
    old: dict[str, Any],
    payloads: dict[str, Any],
    reference: dict[str, Any],
    clubs: dict[int, int],
    *,
    interpreted_at: datetime,
    parser_sha256: str,
) -> dict[str, Any]:
    result = deepcopy(old)
    result.update(
        {
            "interpretation_id": INTERPRETATION_ID,
            "interpretation_known_at": interpreted_at.isoformat(),
            "rows": [],
            "errors": [],
            "side_summaries": [],
            "source_enum_alias_log": [],
            "parent_version_id": old["version_id"],
        }
    )
    result["identity_source"]["observed_at"] = reference["identity_observed_at_utc"]
    if interpreted_at < max(
        datetime.fromisoformat(old["capture_known_at"]),
        datetime.fromisoformat(reference["identity_observed_at_utc"]),
    ):
        raise ValueError("interpretation precedes source or identity evidence")
    # Retain attempted aliases even if another unchanged guard rejects the whole interpretation.
    result["attempted_source_enum_alias_log"] = [
        {
            "source_field": f"{node}.cards[{index}].type",
            "provider_value": "StraightRed",
            "private_state_transition": "Red",
            "raw_event": deepcopy(card),
        }
        for node in ("homeTeam", "awayTeam")
        for index, card in enumerate(payloads["events"][node]["cards"])
        if card.get("type") == "StraightRed"
    ]
    try:
        parsed = parse_participation_v3(
            old["raw_match"],
            payloads["lineups"],
            payloads["events"],
            known_at=datetime.fromisoformat(old["capture_known_at"]),
            event_known_at=datetime.fromisoformat(old["source_versions"]["events"]["known_at"]),
            interpretation_known_at=interpreted_at,
        )
        result["source_enum_alias_log"] = parsed["source_enum_alias_log"]
        result["raw_events"] = parsed["raw_events"]
        for side in parsed["sides"]:
            team = side["provider_team_id"]
            codes, identity_errors = exact_crosswalk(
                [r["provider_player_id"] for r in side["rows"]],
                reference["registry"],
                season=reference["season"],
            )
            result["errors"].extend(f"side={team}:{e}" for e in side["errors"])
            result["side_summaries"].append(
                {
                    **{k: deepcopy(v) for k, v in side.items() if k != "rows"},
                    "team_code": clubs.get(team),
                    "identity_errors": identity_errors,
                }
            )
            result["rows"].extend(
                {
                    **deepcopy(row),
                    "code": codes[row["provider_player_id"]],
                    "provider_team_id": team,
                    "team_code": clubs.get(team),
                }
                for row in side["rows"]
            )
        nominal = [s["nominal_match_minutes"] for s in parsed["sides"]]
        result["extra_time"] = (
            any(n == 120 for n in nominal) if all(n is not None for n in nominal) else None
        )
        stamp = staging.maximum_event_time(payloads["events"])
        result["maximum_retained_event_timestamp"] = stamp.isoformat() if stamp else None
    except (ParticipationError, ValueError, KeyError, TypeError) as error:
        result["errors"].append(f"{type(error).__name__}:{error}")
    result["interpretation_valid"] = result["capture_complete"] and not result["errors"]
    result["version_id"] = identity((old["version_id"], INTERPRETATION_ID, parser_sha256))
    result["semantic_sha256"] = semantic_identity(result)
    return result


def run(*, root: Path, source_db: Path, database: Path, results: Path) -> dict[str, Any]:
    if any(p.is_symlink() for p in (source_db, database, results)) or results.exists():
        raise ValueError("new nonsymlink operational paths required")
    root, source_db, database, results = (p.resolve() for p in (root, source_db, database, results))
    if (
        results.is_relative_to(root)
        or database.is_relative_to(root)
        or results in {source_db, database}
    ):
        raise ValueError("new external operational DB/report paths required")
    results.mkdir(parents=True, exist_ok=False)
    try:
        contract: dict[str, Any] = yaml.safe_load((root / CONFIG).read_bytes())
        head = capture._head(root, contract)
        fingerprints = {name: file_sha256(root / name) for name in SOURCE_FILES}
        if file_sha256(root / contract["source_audit"]) != contract["source_audit_sha256"]:
            raise ValueError("preregistered card-semantics source audit changed")
        if (
            file_sha256(root / "src/fpl/transform/competitive_participation_v2.py")
            != contract["original_v2_parser_sha256"]
        ):
            raise ValueError("original V2 parser changed")
        database.parent.mkdir(parents=True, exist_ok=True)
        staging.consistent_copy(source_db, database, contract["source_database_sha256"])
        reference = reference_data(source_db, contract["season"])
        parser_sha = fingerprints["src/fpl/transform/competitive_participation_v3.py"]
        with writer_lock(database) as con:
            old = source_rows(con, contract["source_interpretation_id"])
            if len(old) != contract["expected_source_versions"] or len(
                {r["match_id"] for r in old}
            ) != len(old):
                raise ValueError("exact source V2 population required")
            old_digest = identity(old)
            prior_raw_count = con.execute(
                "SELECT count(*) FROM dev_competitive_raw_receipt"
            ).fetchone()
            ingestion = con.execute(
                "SELECT CAST(record_json AS VARCHAR) FROM dev_competitive_ingestion"
            ).fetchall()
            maps = [json.loads(row[0]).get("provider_to_team_code") for row in ingestion]
            maps = [m for m in maps if m is not None]
            if len(maps) != 1:
                raise ValueError("one retained verified PL club crosswalk required")
            clubs = {int(k): v for k, v in maps[0].items()}
            con.execute("BEGIN TRANSACTION")
            try:
                new = []
                for old_record in old:
                    record = reinterpret(
                        old_record,
                        endpoint_payloads(con, old_record),
                        reference,
                        clubs,
                        interpreted_at=datetime.now(UTC),
                        parser_sha256=parser_sha,
                    )
                    append_match(con, record)
                    new.append(record)
                audit = staging.participation_audit(new, reference, clubs)
                provenance = {
                    "run_id": results.name,
                    "git_head": head,
                    "clean_worktree": True,
                    "source_database": str(source_db),
                    "source_database_sha256": contract["source_database_sha256"],
                    "operational_database": str(database),
                    "config": contract,
                    "source_sha256": fingerprints,
                    "source_v2_records_sha256": old_digest,
                    "provider_to_team_code": clubs,
                    "model_fitting": False,
                    "network_requests": False,
                    "defaults_changed": False,
                }
                append_report(con, "dev_competitive_ingestion", results.name, provenance)
                append_report(con, "dev_competitive_coverage_version", results.name, audit)
                if identity(source_rows(con, contract["source_interpretation_id"])) != old_digest:
                    raise ValueError("original V2 versions changed")
                if (
                    con.execute("SELECT count(*) FROM dev_competitive_raw_receipt").fetchone()
                    != prior_raw_count
                ):
                    raise ValueError(
                        "V3 interpretation unexpectedly changed retained raw population"
                    )
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise
            con.execute("CHECKPOINT")
            counts = {}
            for table in sorted(TABLES):
                count = con.execute(f"SELECT count(*) FROM {table}").fetchone()
                assert count is not None
                counts[table] = count[0]
        if capture._head(root, contract) != head or any(
            file_sha256(root / n) != sha for n, sha in fingerprints.items()
        ):
            raise ValueError("restaging source provenance changed")
        if (
            _wal_path(source_db).exists()
            or _sha256(source_db) != contract["source_database_sha256"]
        ):
            raise ValueError("original operational source DB changed")
        report = {
            "completed": True,
            "provenance": provenance,
            "counts": counts,
            "audit": audit,
            "previous_valid_matches": sum(r["interpretation_valid"] for r in old),
            "new_valid_matches": sum(r["interpretation_valid"] for r in new),
            "newly_valid_match_ids": [
                r["match_id"]
                for r, o in zip(new, old, strict=True)
                if r["interpretation_valid"] and not o["interpretation_valid"]
            ],
            "regressed_match_ids": [
                r["match_id"]
                for r, o in zip(new, old, strict=True)
                if o["interpretation_valid"] and not r["interpretation_valid"]
            ],
            "source_database_preserved": True,
            "original_v2_versions_preserved": True,
            "operational_database_sha256": _sha256(database),
            "operational_no_wal": not _wal_path(database).exists(),
            "finished_at_utc": datetime.now(UTC).isoformat(),
            "model_fitting": False,
            "network_requests": False,
        }
        serializable: dict[str, Any] = json.loads(json.dumps(report, allow_nan=False))
        publish_json(results / "result.json", serializable)
        return serializable
    except Exception as error:
        publish_json(
            results / "failure.json",
            {
                "completed": False,
                "failure_class": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
                "source_database": str(source_db),
                "operational_database": str(database),
                "operational_database_exists": database.exists(),
                "model_fitting": False,
                "network_requests": False,
            },
        )
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-db", "db", "results"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run(root=repo_root(), source_db=args.source_db, database=args.db, results=args.results)
    logging.getLogger(__name__).warning(
        "V3 interpretation: %s valid, old V2 preserved", result["new_valid_matches"]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
