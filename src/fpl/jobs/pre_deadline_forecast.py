"""Refresh FPL + SDP, then generate a primary forecast with an incumbent safety path.

Example:
    python -m fpl.jobs.pre_deadline_forecast --db D:/FPL/operational.duckdb \
        --runs D:/FPL/runs --gw-from 4 --gw-to 8 --output D:/FPL/predictions/gw4.jsonl
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from fpl.config import load_sources, repo_root
from fpl.football_configuration import load_football_environment
from fpl.jobs import daily_pl_sdp, prospective_points_v1
from fpl.validate.points_harness_v3 import DEFAULT_DRAWS


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
    if not prospective_points_v1._git_worktree_clean(repo_root()):
        raise ValueError("commit verified implementation before a pre-deadline production run")
    if args.output.exists():
        raise FileExistsError("prediction vintages are immutable; choose a new output path")
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
            json.dumps({"healthy": False, "failure": f"{type(error).__name__}: {error}"}),
            encoding="utf-8",
        )
        status = 1
    command = [
        "--db",
        str(args.db),
        "--as-of",
        args.as_of or datetime.now(UTC).isoformat(),
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
    ]
    reports = list(receipt_root.glob("*/report.json"))
    if len(reports) == 1:
        command.extend(["--refresh-report", str(reports[0])])
    if status:
        command.extend(
            ["--sdp-refresh-failure", f"SDP refresh exit {status}; receipts: {receipt_root}"]
        )
    # FPL freshness and artifact legality still fail closed inside the incumbent job.
    return prospective_points_v1.main(command)


if __name__ == "__main__":
    raise SystemExit(main())
