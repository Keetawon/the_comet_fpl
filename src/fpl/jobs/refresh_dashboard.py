"""One existing-host flow: capture, final outcomes, current plan, dashboard publication.

No inference or forecast replacement. A new forecast must first be registered by
pre_deadline_forecast. A missing current artifact fails before replacing the preview.
"""

from __future__ import annotations

import argparse
import faulthandler
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fpl.artifacts.optimizer_plan import read_optimizer_artifact
from fpl.config import config_dir, repo_root
from fpl.jobs import daily_pl_sdp
from fpl.jobs.build_db import _wal_path
from fpl.jobs.build_sdp_dashboard import build
from fpl.jobs.operational_disk import check_disk_space
from fpl.jobs.operational_lock import operational_lock
from fpl.jobs.operational_retention import create_recovery, prune_runs
from fpl.storage.db import connect, default_db_path
from fpl.storage.outcomes import attach_finalized_outcomes


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def latest_primary(database: Path, forecasts: Path) -> tuple[Path, str, str]:
    """Use the actually registered primary; never select a file by its name or mtime."""
    with connect(database, read_only=True) as con:
        row = con.execute("""SELECT p.primary_artifact_sha256, p.season, p.primary_run_id
            FROM ledger_sdp_evidence_pair p JOIN ledger_forecast_run r
            ON r.run_id = p.primary_run_id AND r.artifact_sha256 = p.primary_artifact_sha256
            ORDER BY p.as_of DESC, p.created_at DESC, p.prediction_id DESC LIMIT 1""").fetchone()
    if row is None:
        raise ValueError("no registered primary forecast; run pre_deadline_forecast first")
    matches = [p for p in sorted(forecasts.glob("*.jsonl")) if digest(p) == row[0]]
    if not matches:
        raise ValueError(
            "latest registered primary artifact unavailable; older forecasts cannot substitute"
        )
    return matches[0], str(row[1]), str(row[2])


def reusable_plan(path: Path, forecast_hash: str) -> bool:
    artifact = read_optimizer_artifact(path)
    policy = artifact.search_policy
    return (
        artifact.provenance.forecast.sha256 == forecast_hash
        and artifact.provenance.squad_rules.sha256 == digest(config_dir() / "squad_2026_27.yaml")
        and policy.plan_origin in (None, "platform")
        and not policy.locked_codes
        and not policy.excluded_codes
        and policy.risk_lambda == 0
        and policy.min_bench_appearance == 0
        and artifact.manager_context is None
    )


def complete(
    database: Path,
    destination: Path,
    forecasts: Path,
    public: Path,
    plan_store: Path,
    *,
    initial_plan: Path | None = None,
    cycle_backup: dict[str, str] | None = None,
) -> dict[str, Any]:
    forecast, season, run_id = latest_primary(database, forecasts)
    forecast_hash = digest(forecast)
    # Outcome attachment is the existing append-only authoritative path.
    with daily_pl_sdp.writer_lock(
        database,
        backup=None if cycle_backup is not None else destination / "before-outcomes.duckdb",
        cycle_backup=cycle_backup,
    ) as con:
        attached = attach_finalized_outcomes(
            con, as_of=datetime.now(UTC), season=season, skip_pending_live=True
        )
        con.execute("CHECKPOINT")
    plan_store.mkdir(parents=True, exist_ok=True)
    candidates = ([initial_plan] if initial_plan else []) + sorted(plan_store.glob("*.json"))
    plan = next((p for p in candidates if reusable_plan(p, forecast_hash)), None)
    reused = plan is not None
    if plan is None:
        plan = plan_store / f"platform-{forecast_hash}-{uuid4().hex[:8]}.json"
        with (destination / "optimizer.log").open("x", encoding="utf-8") as log:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "fpl.jobs.optimize_squad",
                    str(forecast),
                    "--output",
                    str(plan),
                ],
                cwd=repo_root(),
                stdout=log,
                stderr=log,
                check=True,
                timeout=3600,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
    if digest(forecast) != forecast_hash or not reusable_plan(plan, forecast_hash):
        raise ValueError("forecast or optimizer binding changed; refuse publication")
    generation = build(
        database,
        destination / "generation",
        base_dashboard=public / "data",
        optimizer_plans=(plan,),
    )
    status = generation["publication_status"]
    if not status["current_platform_plan"] or status["latest_forecast"]["run_id"] != run_id:
        raise ValueError("current platform plan did not reach the public export")
    # Validate first; keep last working preview on any preceding failure.
    from fpl.jobs.build_sdp_dashboard import install_preview

    install_preview(destination / "generation", public)
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if npm is None:
        raise ValueError("npm unavailable: exports updated but preview build was not completed")
    with (destination / "dashboard-build.log").open("x", encoding="utf-8") as log:
        subprocess.run(
            [npm, "run", "build"],
            cwd=public.resolve().parent,
            stdout=log,
            stderr=log,
            check=True,
            timeout=600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    return {
        "dashboard_built": True,
        "forecast_run_id": run_id,
        "forecast_sha256": forecast_hash,
        "plan_sha256": digest(plan),
        "plan_reused": reused,
        "outcomes": asdict(attached),
        "publication_status": status,
        "current_availability": generation["current_availability"],
        "forecast_regenerated": False,
        "preview_updated": True,
    }


def assert_no_inflight_backup(runs: Path, destination: Path) -> None:
    """A failed/interrupted cycle must be resolved before allocating another recovery copy."""
    for backup in sorted(runs.glob("dashboard-*/recovery.duckdb")):
        if backup.parent == destination:
            continue
        receipt = backup.parent / "receipt.json"
        try:
            previous = json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"unattributed recovery backup requires review: {backup}") from exc
        if previous.get("retention_policy_version", 1) < 2:
            continue
        if not (
            previous.get("status") == "COMPLETE"
            and previous.get("phase") == "finished"
            and previous.get("public_publication", {}).get("status", "COMPLETE") == "COMPLETE"
            and previous.get("retention", {}).get("status") == "COMPLETE"
        ):
            raise ValueError(
                f"incomplete cycle recovery requires review before a new copy: {backup}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--runs", required=True, type=Path)
    parser.add_argument("--forecast-dir", required=True, type=Path)
    parser.add_argument("--preview-public", required=True, type=Path)
    parser.add_argument("--plan-store", required=True, type=Path)
    parser.add_argument("--optimizer-plan", type=Path, help="Already verified initial plan")
    parser.add_argument("--skip-capture", action="store_true", help="Republish retained data only")
    parser.add_argument("--r2-config", type=Path, help="Optional external R2 publication config")
    args = parser.parse_args(argv)
    if not args.db.is_file() or args.db.resolve() == default_db_path().resolve():
        raise ValueError("explicit existing non-default operational database required")
    args.runs.mkdir(parents=True, exist_ok=True)
    lock = args.runs / ".dashboard-refresh.lock"
    started = datetime.now(UTC)
    destination = args.runs / f"dashboard-{started.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    destination.mkdir()
    report: dict[str, Any] = {
        "started_at": started.isoformat(),
        "status": "RUNNING",
        "pid": os.getpid(),
        "phase": "acquire_lock",
        "database": str(args.db.resolve()),
        "retention_policy_version": 2,
        "backup_semantics": "pre_cycle",
    }
    receipt = destination / "receipt.json"

    def save(phase: str | None = None) -> None:
        if phase is not None:
            report["phase"] = phase
        report["updated_at"] = datetime.now(UTC).isoformat()
        temporary = receipt.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(receipt)

    # This exists BEFORE lock acquisition, including under console-less pythonw.
    logging.basicConfig(level=logging.INFO, handlers=[])
    handler = logging.FileHandler(destination / "refresh.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    fatal_enabled = not faulthandler.is_enabled()
    with (destination / "fatal.log").open("x", encoding="utf-8") as fatal_log:
        if fatal_enabled:
            faulthandler.enable(file=fatal_log)
        try:
            save()
            with operational_lock(
                lock,
                wal=_wal_path(args.db),
                validate_recovery=lambda: daily_pl_sdp.validate_idle_database(args.db),
            ) as recovered:
                report["lock_recovery"] = recovered
                save("recovery_backup")
                export_bytes = sum(
                    path.stat().st_size
                    for path in args.preview_public.rglob("*")
                    if path.is_file() and not path.is_symlink()
                )
                report["disk_preflight"] = {
                    "active_database": check_disk_space(args.db, 0),
                    "cycle_allocation": check_disk_space(
                        destination, args.db.stat().st_size + 2 * export_bytes
                    ),
                    "estimate_basis": "database copy + twice current preview bytes; not a quota",
                }
                assert_no_inflight_backup(args.runs, destination)
                report["recovery_backup"] = create_recovery(args.db, destination)
                save()
                if not args.skip_capture:
                    save("capture")
                    report["capture_exit_code"] = daily_pl_sdp.run(
                        database=args.db,
                        runs=args.runs,
                        include_workload=True,
                        player_history=True,
                        cycle_backup=report["recovery_backup"],
                    )
                    # Source gaps may require fallback. FPL history must be fully captured.
                    with connect(args.db, read_only=True) as con:
                        fresh = con.execute(
                            """SELECT count(*) FROM snapshot_capture
                            WHERE mode = 'player-history' AND captured_at >= ?""",
                            [started],
                        ).fetchone()
                    if not fresh or not fresh[0]:
                        raise ValueError(
                            "no fresh complete FPL player history; preview kept unchanged"
                        )
                save("dashboard")
                report.update(
                    complete(
                        args.db,
                        destination,
                        args.forecast_dir,
                        args.preview_public,
                        args.plan_store,
                        initial_plan=args.optimizer_plan,
                        cycle_backup=report["recovery_backup"],
                    )
                )
                report["status"] = "COMPLETE"
                if args.r2_config is not None:
                    from fpl.publish.r2_dashboard import publish_r2_dashboard

                    report["public_publication"] = {"status": "RUNNING"}
                    save("r2_publication")
                    try:
                        report["public_publication"] = publish_r2_dashboard(
                            destination / "generation",
                            args.r2_config,
                            destination / "r2-publication",
                        )
                    except Exception as exc:
                        report["public_publication"] = {
                            "status": "FAILED",
                            "error_type": type(exc).__name__,
                            "error": (
                                "R2 publication could not retain its receipt; "
                                "local refresh completed"
                            ),
                        }
                report["finished_at"] = datetime.now(UTC).isoformat()
                save()
                if report.get("public_publication", {}).get("status", "COMPLETE") == "COMPLETE":
                    try:
                        # Retention stays under the cycle lock and retains its own WAL veto.
                        report["retention"] = {"status": "RUNNING"}
                        save("retention")
                        report["retention"] = prune_runs(
                            args.db,
                            args.runs,
                            args.forecast_dir,
                            recovery=Path(report["recovery_backup"]["path"]),
                            recovery_sha=report["recovery_backup"]["sha256"],
                            archive_pins=True,
                        )
                    except Exception as exc:
                        report["retention"] = {
                            "status": "BLOCKED",
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                        logging.exception("Refresh completed but retention was blocked")
                save("finished")
        except Exception as exc:
            report["status"] = "FAILED"
            report["error"] = f"{type(exc).__name__}: {exc}"
            logging.exception("Dashboard refresh failed; inspect retained receipt")
        finally:
            try:
                report["finished_at"] = datetime.now(UTC).isoformat()
                save()
            finally:
                if fatal_enabled:
                    faulthandler.disable()
                root_logger.removeHandler(handler)
                handler.close()
    if sys.stdout is not None:
        print(json.dumps({"receipt": str(receipt), **report}, sort_keys=True))
    published = report.get("public_publication", {}).get("status", "COMPLETE") == "COMPLETE"
    retained = report.get("retention", {}).get("status", "COMPLETE") == "COMPLETE"
    return 0 if report["status"] == "COMPLETE" and published and retained else 1


if __name__ == "__main__":
    raise SystemExit(main())
