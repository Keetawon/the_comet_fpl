"""One existing-host flow: capture, final outcomes, current plan, dashboard publication.

No inference or forecast replacement. A new forecast must first be registered by
pre_deadline_forecast. A missing current artifact fails before replacing the preview.
"""

from __future__ import annotations

import argparse
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
from fpl.jobs.build_sdp_dashboard import build
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
) -> dict[str, Any]:
    forecast, season, run_id = latest_primary(database, forecasts)
    forecast_hash = digest(forecast)
    # Outcome attachment is the existing append-only authoritative path.
    with daily_pl_sdp.writer_lock(database, backup=destination / "before-outcomes.duckdb") as con:
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
        "forecast_regenerated": False,
        "preview_updated": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--runs", required=True, type=Path)
    parser.add_argument("--forecast-dir", required=True, type=Path)
    parser.add_argument("--preview-public", required=True, type=Path)
    parser.add_argument("--plan-store", required=True, type=Path)
    parser.add_argument("--optimizer-plan", type=Path, help="Already verified initial plan")
    parser.add_argument("--skip-capture", action="store_true", help="Republish retained data only")
    args = parser.parse_args(argv)
    if not args.db.is_file() or args.db.resolve() == default_db_path().resolve():
        raise ValueError("explicit existing non-default operational database required")
    args.runs.mkdir(parents=True, exist_ok=True)
    lock = args.runs / ".dashboard-refresh.lock"
    # Exclusive cycle lock complements the existing DB writer locks/backup leases.
    with lock.open("x", encoding="utf-8") as handle:
        json.dump({"pid": os.getpid(), "started_at": datetime.now(UTC).isoformat()}, handle)
    started = datetime.now(UTC)
    destination = args.runs / f"dashboard-{started.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    destination.mkdir()
    report: dict[str, Any] = {"started_at": started.isoformat(), "status": "FAILED"}
    logging.basicConfig(level=logging.INFO)
    try:
        if not args.skip_capture:
            report["capture_exit_code"] = daily_pl_sdp.run(
                database=args.db, runs=args.runs, include_workload=True, player_history=True
            )
            # Provider gaps do not imply that FPL refresh failed. Require a fresh
            # complete player-history capture independently before continuing.
            with connect(args.db, read_only=True) as con:
                fresh = con.execute(
                    """SELECT count(*) FROM snapshot_capture
                    WHERE mode = 'player-history' AND captured_at >= ?""",
                    [started],
                ).fetchone()
            if not fresh or not fresh[0]:
                raise ValueError("no fresh complete FPL player history; preview kept unchanged")
        report.update(
            complete(
                args.db,
                destination,
                args.forecast_dir,
                args.preview_public,
                args.plan_store,
                initial_plan=args.optimizer_plan,
            )
        )
        report["status"] = "COMPLETE"
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        logging.exception("Dashboard refresh failed; inspect retained receipt")
    finally:
        report["finished_at"] = datetime.now(UTC).isoformat()
        (destination / "receipt.json").write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
        )
        lock.unlink()
    print(json.dumps({"receipt": str(destination / "receipt.json"), **report}, sort_keys=True))
    return 0 if report["status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
