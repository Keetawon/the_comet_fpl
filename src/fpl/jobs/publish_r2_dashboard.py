"""Publish one completed generation using the existing operational refresh lock."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fpl.jobs.operational_lock import operational_lock
from fpl.publish.r2_dashboard import publish_r2_dashboard


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generation", required=True, type=Path)
    parser.add_argument("--r2-config", required=True, type=Path)
    parser.add_argument("--runs", required=True, type=Path)
    args = parser.parse_args(argv)
    args.runs.mkdir(parents=True, exist_ok=True)
    lock = args.runs / ".dashboard-refresh.lock"
    with operational_lock(lock):
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output = args.runs / f"r2-{stamp}-{uuid4().hex[:8]}"
        report = publish_r2_dashboard(args.generation, args.r2_config, output)
        print(json.dumps({"receipt": str(output / "receipt.json"), **report}, sort_keys=True))
        return 0 if report["status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
