"""Publish a write-once GW4-8 checkpoint from retained prospective ledger pairs."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from fpl.jobs.competitive_participation_pilot import publish_bytes
from fpl.jobs.daily_pl_sdp import writer_lock
from fpl.storage.db import connect
from fpl.storage.outcomes import attach_finalized_outcomes
from fpl.validate.sdp_checkpoint import build_checkpoint, canonical_bytes, load_checkpoint_pair


def write_report(path: Path, report: dict[str, Any]) -> bool:
    """Create only; identical repeated evidence is idempotent, revisions need a new path."""
    data = canonical_bytes(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        publish_bytes(path, data)
    except FileExistsError:
        if path.read_bytes() != data:
            raise ValueError(
                "checkpoint output already exists with different evidence; use a new version path"
            ) from None
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attach-outcomes", action="store_true")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args(argv)
    data = args.contract.read_bytes()
    contract = yaml.safe_load(data)
    if not isinstance(contract, dict):
        raise ValueError("checkpoint contract must be a mapping")
    contract_hash = hashlib.sha256(data).hexdigest()
    attachment = None
    if args.attach_outcomes:
        if args.backup is None:
            parser.error("--attach-outcomes requires --backup NEW_PATH")
        if args.backup.exists() or args.backup.resolve() == args.db.resolve():
            raise ValueError("outcome attachment requires a new backup path")
        with connect(args.db, read_only=True) as con:
            load_checkpoint_pair(con, contract=contract, contract_sha256=contract_hash)
        actual_now = datetime.now(UTC)
        with writer_lock(args.db, backup=args.backup) as con:
            result = attach_finalized_outcomes(con, as_of=actual_now, season=contract["season"])
        attachment = {
            "as_of": actual_now.isoformat(),
            "backup": str(args.backup),
            "result": asdict(result),
        }
    elif args.backup is not None:
        parser.error("--backup is used only with --attach-outcomes")
    with connect(args.db, read_only=True) as con:
        report = build_checkpoint(con, contract=contract, contract_sha256=contract_hash)
    created = write_report(args.output, report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "report_version": report["report_version"],
                "output": str(args.output),
                "created": created,
                "operations": report["operations"],
                "attachment": attachment,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
