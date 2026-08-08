"""CLI for recording a prospective-points artifact into the append-only prediction ledger.

Thin orchestration: it reads and validates the frozen JSONL artifact, then calls the ledger domain
functions. Re-recording a byte-identical artifact is an idempotent no-op (the ledger refuses the
duplicate internally, and this CLI reports it and exits 0), so a pipeline that runs twice does not
fail and never duplicates a vintage.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from fpl.artifacts.prospective_points import artifact_bytes, read_artifact
from fpl.storage.db import initialise
from fpl.storage.ledger import DuplicateRunError, derive_run_id, record_forecast


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record a prospective-points artifact into the append-only prediction ledger."
    )
    parser.add_argument(
        "artifact", type=Path, help="Path to the prospective-points JSONL artifact."
    )
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)

    artifact = read_artifact(args.artifact)
    manifest = artifact.manifest
    con = initialise(args.db)
    try:
        run_id = record_forecast(con, artifact)
        horizon = f"GW{manifest.gw_from}-{manifest.gw_to}"
        print(
            f"recorded run {run_id}: {manifest.season} {horizon}, "
            f"{manifest.row_count} predictions, as_of {manifest.as_of.isoformat()}"
        )
    except DuplicateRunError:
        # Nothing was written; recompute the id only for the message. Idempotent no-op, exit 0.
        artifact_sha256 = hashlib.sha256(artifact_bytes(artifact)).hexdigest()
        run_id = derive_run_id(manifest, artifact_sha256)
        print(f"run {run_id} already recorded; ledger unchanged (idempotent no-op)")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
