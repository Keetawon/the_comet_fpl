"""CLI entry point for recording prospective prediction JSONL artifacts into the ledger.

Thin orchestration job coordinating domain functions. Consumes a provenance-bearing
prospective points JSONL artifact and records it into the DuckDB ledger.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from fpl.artifacts.prospective_points import read_artifact
from fpl.storage.db import connect
from fpl.storage.ledger import DuplicateRunError, record_forecast_artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record a prospective points JSONL artifact into the prediction ledger."
    )
    parser.add_argument("artifact", type=Path, help="Path to prospective points JSONL artifact.")
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Path to DuckDB database (defaults to data/fpl.duckdb).",
    )
    args = parser.parse_args(argv)

    artifact_path: Path = args.artifact
    if not artifact_path.exists():
        print(f"Error: artifact file not found: {artifact_path}", file=sys.stderr)
        return 1

    try:
        raw_bytes = artifact_path.read_bytes()
        artifact_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        artifact = read_artifact(artifact_path)
    except Exception as exc:
        print(f"Error: failed to read/validate artifact: {exc}", file=sys.stderr)
        return 1

    con = connect(args.db)
    try:
        run_id = record_forecast_artifact(con, artifact, artifact_sha256)
    except DuplicateRunError as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: failed to record forecast artifact: {exc}", file=sys.stderr)
        return 1
    finally:
        con.close()

    print(
        f"Successfully recorded forecast run {run_id} ({len(artifact.rows)} predictions) "
        f"into ledger."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
