"""Capture optional public news privately; no forecasts or operational databases touched."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx
import yaml
from pydantic import ValidationError

from fpl.ingest.public_news import NewsCaptureConfig, capture_fpl_snapshot, run_capture
from fpl.storage.public_news import NewsStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, required=True, help="New private capture receipt; write once"
    )
    parser.add_argument("--fpl-snapshot", type=Path)
    parser.add_argument("--season")
    args = parser.parse_args(argv)
    if args.store.suffix.lower() not in {".sqlite", ".sqlite3"}:
        parser.error("--store must be a separate private .sqlite or .sqlite3 file")
    if any(part.lower() in {"public", "dist", "dashboard"} for part in args.store.resolve().parts):
        parser.error("private news store must be outside dashboard/publication directories")
    if args.fpl_snapshot and not args.season:
        parser.error("--fpl-snapshot requires its explicit --season")
    if args.output.exists():
        parser.error("capture receipt already exists; use a new output identity")
    try:
        config = NewsCaptureConfig.model_validate(
            yaml.safe_load(args.config.read_text(encoding="utf-8"))
        )
    except (ValidationError, yaml.YAMLError):
        parser.error("invalid news configuration; credentials belong only in process environment")
    store = NewsStore(args.store)
    statuses = []
    if args.fpl_snapshot:
        statuses.append(capture_fpl_snapshot(args.fpl_snapshot, store, season=args.season))
    with httpx.Client(trust_env=False) as client:
        statuses.extend(run_capture(config, store, client=client))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(
            {"schema_version": 1, "sources": [s.model_dump(mode="json") for s in statuses]},
            handle,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        handle.write("\n")
    print(
        json.dumps(
            {
                "sources": len(statuses),
                "network_enabled": config.enabled,
                "statuses": {s.source_id: s.status for s in statuses},
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
