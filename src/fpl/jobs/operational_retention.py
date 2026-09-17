"""Bound full operational copies; retain source evidence and health receipts."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import stat
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

import duckdb

from fpl.config import repo_root
from fpl.jobs.build_db import _prepare_temporary_database
from fpl.jobs.sdp_capture_health import parse_receipt_instant
from fpl.storage.db import connect

_CAPTURE = re.compile(r"^\d{8}T\d{6}\.\d{6}Z-[0-9a-f]{8}$")
_DASHBOARD = re.compile(r"^dashboard-\d{8}T\d{6}Z-[0-9a-f]{8}$")
_SHA = re.compile(rb"[0-9a-f]{64}")
_RUN = re.compile(rb"(?:dashboard-)?\d{8}T\d{6}(?:\.\d{6})?Z-[0-9a-f]{8}")
_MUTABLE = {
    "build_metadata",
    "mart_dim_player",
    "mart_dim_player_stint",
    "mart_dim_team",
    "mart_fact_player_fixture",
    "mart_fact_player_fixture_live",
    "mart_fact_player_form",
    "mart_fact_team_form",
    "mart_fact_team_match",
    "mart_fact_team_match_stats_v2",
    "mart_fact_team_tactical_form_v2",
    "mart_target_completeness",
    "mart_target_player_fixture",
    "mart_team_fixture_live",
    "stg_fixture",
    "stg_pl_sdp_fixture_crosswalk",
    "stg_pl_sdp_match",
    "stg_pl_sdp_team_match_metric",
    "stg_pl_sdp_team_match_stats",
    "stg_player",
    "stg_player_fixture",
    "stg_team",
}


def _hash(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _safe_tree(path: Path, root: Path) -> None:
    """Reject links before resolving/traversing or deleting anything."""
    if not path.absolute().is_relative_to(root.absolute()) or path.absolute() == root.absolute():
        raise ValueError("retention target outside its run root")
    for ancestor in (path, *path.parents):
        info = ancestor.lstat()
        if (
            ancestor.is_symlink()
            or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ValueError("retention refuses symlink/reparse paths")
    if path.is_dir():
        for child in path.iterdir():
            _safe_tree(child, root)


def _references() -> tuple[set[str], set[str]]:
    hashes: set[str] = set()
    runs: set[str] = set()
    for folder in ("config", "results", "docs"):
        for path in (repo_root() / folder).rglob("*"):
            if path.suffix not in (".json", ".yaml", ".yml", ".md") or not path.is_file():
                continue
            with path.open("rb") as handle:
                tail = b""
                while block := handle.read(128 * 1024):
                    data = tail + block
                    hashes.update(match.decode() for match in _SHA.findall(data))
                    runs.update(match.decode() for match in _RUN.findall(data))
                    tail = data[-128:]
    return hashes, runs


def _protected_hashes(forecasts: Path) -> set[str]:
    if not forecasts.is_dir():
        raise ValueError("retention requires the retained forecast directory")
    hashes: set[str] = set()
    for path in forecasts.rglob("*.jsonl"):
        with path.open(encoding="utf-8") as handle:
            line = handle.readline(16 * 1024 * 1024 + 1)
        if len(line) > 16 * 1024 * 1024:
            raise ValueError("forecast header exceeds retention safety bound")
        header = json.loads(line)
        value = header.get("database_sha256")
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("unrecognized forecast pin; retention stopped")
        # Serialized component provenance also pins source DBs distinct from the
        # top-level replay DB. All SHA references conservatively protect copies.
        hashes.update(match.decode() for match in _SHA.findall(line.encode("utf-8")))
    return hashes


def _verify_backup(database: Path, backup: Path) -> dict[str, Any]:
    """Exact old immutable row occurrences must remain in the active database."""
    for path in (database, backup):
        if Path(str(path) + ".wal").exists() or Path(str(path) + ".daily-sdp.lock").exists():
            raise ValueError("unresolved database lock/WAL; retention stopped")
    checks = []
    with TemporaryDirectory(prefix="comet-retention-") as temporary, duckdb.connect() as con:
        con.execute("SET memory_limit='1GB'")
        con.execute("SET threads=2")
        con.execute("SET preserve_insertion_order=false")
        con.execute("SET temp_directory=?", [temporary])
        for alias, path in (("current_db", database), ("old_db", backup)):
            escaped = str(path.resolve()).replace("'", "''")
            con.execute(f"ATTACH '{escaped}' AS {alias} (READ_ONLY)")
        tables = con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_catalog='old_db' AND table_schema='main' AND table_type='BASE TABLE' "
            "ORDER BY table_name"
        ).fetchall()
        for (table,) in tables:
            if table in _MUTABLE:
                continue
            if not (
                table.startswith(("raw_", "snapshot_", "ledger_", "dev_competitive_"))
                or table
                in (
                    "ingest_anomaly",
                    "mart_fact_team_match_stats_v2_version",
                    "sdp_competitive_match_version",
                )
                or table
                in (
                    "stg_live_fixture_version",
                    "stg_live_player_fixture_version",
                    "stg_live_player_version",
                    "stg_live_team_version",
                )
            ):
                raise ValueError(f"unclassified table requires manual retention review: {table}")
            columns = (
                "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                "WHERE table_catalog=? AND table_schema='main' AND table_name=? "
                "ORDER BY ordinal_position"
            )
            old = con.execute(columns, ["old_db", table]).fetchall()
            current = con.execute(columns, ["current_db", table]).fetchall()
            if old != current or not old:
                raise ValueError(f"retention schema mismatch: {table}")
            quoted = '"' + table.replace('"', '""') + '"'
            missing = con.execute(
                f"SELECT count(*) FROM (SELECT * FROM old_db.main.{quoted} EXCEPT ALL "
                f"SELECT * FROM current_db.main.{quoted})"
            ).fetchone()
            if missing is None or missing[0] != 0:
                raise ValueError(f"immutable rows missing or changed: {table}")
            count = con.execute(f"SELECT count(*) FROM old_db.main.{quoted}").fetchone()
            assert count is not None
            checks.append({"table": table, "retained_rows": count[0], "missing_rows": 0})
        if not checks:
            raise ValueError("no immutable tables proved; retain backup")
        return {
            "backup_sha256": _hash(backup),
            "retained_database_sha256": _hash(database),
            "tables": checks,
        }


def create_recovery(database: Path, destination: Path) -> dict[str, str]:
    """Freeze one complete post-success recovery copy before retiring older copies."""
    target = destination / "recovery.duckdb"
    if target.exists():
        raise FileExistsError(target)
    if Path(str(database) + ".daily-sdp.lock").exists() or Path(str(database) + ".wal").exists():
        raise ValueError("database writer lock/WAL; recovery deferred")
    with connect(database, read_only=True):
        digest = _prepare_temporary_database(database, target)
    if digest is None:
        raise ValueError("missing operational database")
    return {
        "path": str(target.resolve()),
        "sha256": digest,
        "created_at": datetime.now(UTC).isoformat(),
    }


def prune_runs(
    database: Path,
    runs: Path,
    forecasts: Path,
    *,
    keep: int = 2,
    recovery: Path | None = None,
) -> dict[str, Any]:
    """Keep two full refreshes/captures; old diagnostic skeletons stay discoverable.

    Legacy dashboard generations lack DB attribution and require manual review.
    Scientific/forecast source pins take precedence over the full-copy limit.
    """
    if keep < 2:
        raise ValueError("automatic retention requires at least two complete copies")
    if Path(str(database) + ".wal").exists() or Path(str(database) + ".daily-sdp.lock").exists():
        raise ValueError("unresolved database lock/WAL; retention stopped")
    root = runs.absolute()
    if (
        not root.is_dir()
        or root == root.parent
        or database.resolve().is_relative_to(root.resolve())
    ):
        raise ValueError("retention requires an isolated operational runs root")
    references, protected_names = _references()
    references.update(_protected_hashes(forecasts))
    now = datetime.now(UTC)
    if recovery is not None:
        recovery = recovery.absolute()
        _safe_tree(recovery, root)
        if (
            recovery.name not in ("recovery.duckdb", "before-outcomes.duckdb")
            or not recovery.is_file()
        ):
            raise ValueError("invalid recovery snapshot")
        with connect(database, read_only=True):
            if _hash(recovery) != _hash(database):
                raise ValueError("recovery snapshot differs from active database")
    groups: dict[str, list[tuple[datetime, Path, dict[str, Any]]]] = {
        "capture": [],
        "dashboard": [],
    }
    for child in root.iterdir():
        kind = (
            "capture"
            if _CAPTURE.fullmatch(child.name)
            else "dashboard"
            if _DASHBOARD.fullmatch(child.name)
            else None
        )
        if kind is None or not child.is_dir():
            continue
        _safe_tree(child, root)
        receipt = child / ("report.json" if kind == "capture" else "receipt.json")
        if not receipt.is_file():
            continue
        try:
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            finished = parse_receipt_instant(payload.get("finished_at"), now)
        except (ValueError, AttributeError):
            continue
        if finished is None:
            continue
        if kind == "capture":
            if (
                not isinstance(payload.get("healthy"), bool)
                or Path(payload.get("database", "")).resolve() != database.resolve()
            ):
                continue
            backup = child / "before.duckdb"
            pin = payload.get("backup")
            if (
                not backup.is_file()
                or not isinstance(pin, dict)
                or not isinstance(pin.get("path"), str)
                or Path(pin["path"]).resolve() != backup.resolve()
                or pin.get("sha256") != _hash(backup)
            ):
                # Failed copy attempts are diagnostics, not recovery generations.
                continue
        elif (
            payload.get("status") != "COMPLETE"
            or payload.get("public_publication", {}).get("status", "COMPLETE") != "COMPLETE"
            or (
                payload.get("database") is not None
                and Path(payload["database"]).resolve() != database.resolve()
            )
        ):
            continue
        groups[kind].append((finished, child, payload))
    candidates: list[Path] = []
    skipped: list[dict[str, str]] = []
    for kind, group in groups.items():
        ordered = sorted(group, reverse=True)
        retained_generations = {child for _, child, _ in ordered[:keep]}
        selected = ordered if recovery is not None else ordered[keep:]
        for _, child, payload in selected:
            if (
                child.name in protected_names
                or (child / "forecast-source.duckdb").exists()
                or (child / "forecast.json").exists()
            ):
                skipped.append(
                    {"path": str(child), "reason": "retained scientific/forecast reference"}
                )
                continue
            if kind == "dashboard" and (
                payload.get("retention_policy_version") != 1
                or Path(payload.get("database", "")).resolve() != database.resolve()
            ):
                skipped.append(
                    {"path": str(child), "reason": "legacy dashboard requires manual review"}
                )
                continue
            names = (
                ("before.duckdb",)
                if kind == "capture"
                else ("before-outcomes.duckdb", "recovery.duckdb")
                + (() if child in retained_generations else ("generation",))
            )
            if (
                recovery is None
                and kind == "dashboard"
                and not (child / "before-outcomes.duckdb").is_file()
            ):
                skipped.append(
                    {
                        "path": str(child),
                        "reason": "retention blocked: source backup proof unavailable",
                    }
                )
                continue
            candidates.extend(
                child / name
                for name in names
                if (child / name).exists() and (child / name).absolute() != recovery
            )
    # Validate every destructive boundary before the first removal.
    for candidate in candidates:
        _safe_tree(candidate, root)
        if candidate.is_dir() and any(
            p.suffix in (".duckdb", ".wal", ".jsonl") for p in candidate.rglob("*")
        ):
            raise ValueError("unexpected evidence inside disposable generation")
    report: dict[str, Any] = {
        "schema": "fpl.operational-retention",
        "schema_version": 1,
        "status": "RUNNING",
        "started_at": now.isoformat(),
        "database": str(database.resolve()),
        "keep_full_runs_per_kind": keep,
        "recovery_policy": "one_verified_post_success_copy"
        if recovery is not None
        else "two_verified_full_copies_per_kind",
        "retained_recovery": str(recovery) if recovery is not None else None,
        "deleted": [],
        "skipped": skipped,
        "health_receipts_preserved": True,
    }
    receipt_path = root / f"retention-{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}.json"

    def save() -> None:
        receipt_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    save()
    blocked_directories: dict[Path, str] = {}
    for candidate in candidates:
        proof: dict[str, Any] | None = None
        try:
            if candidate.is_dir() and candidate.parent in blocked_directories:
                skipped.append(
                    {
                        "path": str(candidate),
                        "reason": blocked_directories[candidate.parent],
                    }
                )
                continue
            if candidate.is_file():
                if _hash(candidate) in references:
                    blocked_directories[candidate.parent] = "immutable source hash pin"
                    skipped.append({"path": str(candidate), "reason": "immutable source hash pin"})
                    continue
                # Bind retirement to the surviving copy, even if an independent
                # capture has appended to the live database since it was frozen.
                proof = _verify_backup(recovery if recovery is not None else database, candidate)
            size = (
                sum(p.stat().st_size for p in candidate.rglob("*") if p.is_file())
                if candidate.is_dir()
                else candidate.stat().st_size
            )
            report["pending_deletion"] = {
                "path": str(candidate),
                "bytes": size,
                "retention_proof": proof,
            }
            save()
            if candidate.is_dir():
                for relative, archive_name in (
                    ("receipt.json", "generation-retired-receipt.json"),
                    ("public/data/manifest.json", "generation-retired-manifest.json"),
                ):
                    source = candidate / relative
                    if source.is_file():
                        archive = candidate.parent / archive_name
                        content = source.read_bytes()
                        if archive.exists():
                            if archive.read_bytes() != content:
                                raise ValueError("retired generation receipt collision")
                        else:
                            with archive.open("xb") as handle:
                                handle.write(content)
                shutil.rmtree(candidate)
            else:
                candidate.unlink()
            report["deleted"].append(
                {"path": str(candidate), "bytes": size, "retention_proof": proof}
            )
            report.pop("pending_deletion", None)
        except (OSError, ValueError, duckdb.Error) as exc:
            blocked_directories[candidate.parent] = (
                "retention blocked: source backup was not certified"
            )
            skipped.append({"path": str(candidate), "reason": f"retention blocked: {exc}"})
        save()
    report["status"] = (
        "PARTIAL"
        if any(s["reason"].startswith("retention blocked:") for s in skipped)
        else "COMPLETE"
    )
    report["finished_at"] = datetime.now(UTC).isoformat()
    report["deleted_bytes"] = sum(row["bytes"] for row in report["deleted"])
    save()
    return {"receipt": str(receipt_path), **report}
