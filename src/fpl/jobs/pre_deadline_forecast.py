"""Refresh FPL + SDP, then generate a primary forecast with an incumbent safety path.

Example:
    python -m fpl.jobs.pre_deadline_forecast --db D:/FPL/operational.duckdb \
        --runs D:/FPL/runs --gw-from 4 --gw-to 8 --output D:/FPL/predictions/gw4.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from fpl.config import load_sources, repo_root
from fpl.football_configuration import load_football_environment
from fpl.jobs import daily_pl_sdp, prospective_points_v1, record_sdp_evidence
from fpl.jobs.build_db import _sha256
from fpl.validate.points_harness_v3 import DEFAULT_DRAWS


def _snapshot_source(database: Path, destination: Path) -> None:
    """Keep the exact forecast input independently of later captures or ledger writes."""
    if not database.is_file():
        raise FileNotFoundError(database)
    if destination.exists():
        raise FileExistsError("forecast replay inputs are immutable")
    with daily_pl_sdp.writer_lock(database, backup=destination):
        pass


def _refresh_receipt(receipt_root: Path, status: int) -> tuple[Path, int]:
    """Bind every capture/failure receipt, including a failure after a job wrote its own."""
    reports: list[dict[str, object]] = []
    for path in sorted(receipt_root.glob("*/report.json")):
        entry: dict[str, object] = {"path": path.relative_to(receipt_root).as_posix()}
        try:
            body = path.read_bytes()
            entry["sha256"] = _sha256(path)
            report = json.loads(body)
            if not isinstance(report, dict):
                raise ValueError("refresh receipt must be an object")
            json.dumps(report, allow_nan=False)
            entry["report"] = report
            if report.get("healthy") is not True:
                status = status or 1
        except (OSError, ValueError) as error:
            entry["failure"] = f"{type(error).__name__}: {error}"
            status = status or 1
        reports.append(entry)
    if not reports:
        status = status or 1
    destination = receipt_root / "refresh-report.json"
    daily_pl_sdp._write(
        destination,
        {"schema_version": 1, "healthy": status == 0, "exit_code": status, "receipts": reports},
    )
    return destination, status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--runs", required=True, type=Path)
    parser.add_argument("--gw-from", required=True, type=int)
    parser.add_argument("--gw-to", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--draws", type=int, default=DEFAULT_DRAWS)
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--skip-player-history", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    started_at = datetime.now(UTC)
    explicit_cutoff = datetime.fromisoformat(args.as_of) if args.as_of else None
    if explicit_cutoff is not None and (
        explicit_cutoff.tzinfo is None or explicit_cutoff > started_at
    ):
        raise ValueError("prediction cutoff must be timezone-aware and cannot be in the future")
    if not prospective_points_v1._git_worktree_clean(repo_root()):
        raise ValueError("commit verified implementation before a pre-deadline production run")
    if args.output.exists():
        raise FileExistsError("prediction vintages are immutable; choose a new output path")
    shadow_path = args.output.with_name(args.output.stem + ".shadow-incumbent.jsonl")
    if shadow_path.exists():
        raise FileExistsError("shadow vintages are immutable; choose a new output path")
    config = load_football_environment()
    # Dedicated receipt directory isolates this refresh from concurrently scheduled receipts.
    receipt_root = args.runs / ("pre-deadline-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ"))
    receipt_root.mkdir(parents=True, exist_ok=False)
    try:
        status = daily_pl_sdp.run(
            database=args.db,
            runs=receipt_root,
            include_workload=True,
            lookback_days=config.lookback_days,
            player_history=not args.skip_player_history,
        )
    except Exception as error:
        # A refresh cannot suppress the incumbent's own independent FPL readiness check.
        failed = receipt_root / "failed"
        failed.mkdir()
        (failed / "report.json").write_text(
            json.dumps(
                {
                    "healthy": False,
                    "consumer_ready": False,
                    "exit_code": 1,
                    "database": str(args.db.resolve()),
                    "started_at": started_at.isoformat(),
                    "finished_at": datetime.now(UTC).isoformat(),
                    "failure": f"{type(error).__name__}: {error}",
                }
            ),
            encoding="utf-8",
        )
        status = 1
    refresh_report, status = _refresh_receipt(receipt_root, status)
    source_database = receipt_root / "forecast-source.duckdb"
    build_report: dict[str, object] = {
        "started_at": started_at,
        "prediction_cutoff": None,
        "refresh_exit_code": status,
        "refresh_report": str(refresh_report),
        "refresh_report_sha256": _sha256(refresh_report),
        "source_database": str(source_database),
        "source_database_sha256": None,
        "forecast_exit_code": None,
        "evidence_exit_code": None,
    }
    try:
        _snapshot_source(args.db, source_database)
    except Exception as error:
        build_report.update(
            finished_at=datetime.now(UTC),
            snapshot_failure=f"{type(error).__name__}: {error}",
        )
        daily_pl_sdp._write(receipt_root / "forecast.json", build_report)
        return 1
    cutoff = explicit_cutoff or datetime.now(UTC)
    command = [
        "--db",
        str(source_database),
        "--as-of",
        cutoff.isoformat(),
        "--season",
        load_sources().current_season.season,
        "--gw-from",
        str(args.gw_from),
        "--gw-to",
        str(args.gw_to),
        "--draws",
        str(args.draws),
        "--output",
        str(args.output),
        "--refresh-report",
        str(refresh_report),
    ]
    if status:
        command.extend(
            ["--sdp-refresh-failure", f"SDP refresh exit {status}; receipts: {receipt_root}"]
        )
    # FPL freshness and artifact legality still fail closed inside the incumbent job.
    forecast_failure: str | None = None
    try:
        forecast_status = prospective_points_v1.main(command)
    except Exception as error:
        forecast_status = 1
        forecast_failure = f"{type(error).__name__}: {error}"
    evidence_status: int | None = None
    evidence_failure: str | None = None
    if (
        forecast_status == 0
        and config.football_environment_primary == "sdp_v2"
        and config.shadow_incumbent
    ):
        try:
            evidence_status = record_sdp_evidence.main(
                [
                    "--db",
                    str(args.db),
                    "--primary",
                    str(args.output),
                    "--shadow",
                    str(shadow_path),
                ]
            )
        except Exception as error:
            # Retain the completed forecast and replay image even if evidence storage fails.
            evidence_status = 1
            evidence_failure = f"{type(error).__name__}: {error}"
    daily_pl_sdp._write(
        receipt_root / "forecast.json",
        {
            **build_report,
            "finished_at": datetime.now(UTC),
            "prediction_cutoff": cutoff,
            "refresh_exit_code": status,
            "forecast_exit_code": forecast_status,
            "forecast_failure": forecast_failure,
            "evidence_exit_code": evidence_status,
            "evidence_failure": evidence_failure,
            "source_database": str(source_database),
            "source_database_sha256": _sha256(source_database),
            "primary_artifact": str(args.output),
            "primary_artifact_sha256": _sha256(args.output) if args.output.is_file() else None,
            "shadow_artifact": str(shadow_path),
            "shadow_artifact_sha256": _sha256(shadow_path) if shadow_path.is_file() else None,
        },
    )
    return forecast_status or evidence_status or 0


if __name__ == "__main__":
    raise SystemExit(main())
