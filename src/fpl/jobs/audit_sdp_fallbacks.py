"""Read-only SDP fallback attribution audit over a saved primary artifact.

    python -m fpl.jobs.audit_sdp_fallbacks --db DB --artifact ARTIFACT.jsonl --output REPORT.json

Opens the database strictly read-only (the operational copy may have a scheduled writer),
parses the saved prospective-points artifact, re-derives the selector's fallback
attribution at the artifact's own cutoff, and writes one JSON report. The output path is
never clobbered, the artifact and database are never modified, and no capture, forecast,
or model fit is performed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from fpl.artifacts.prospective_points import read_artifact_bytes
from fpl.storage.db import connect
from fpl.storage.sdp_diagnostics import (
    FIXABLE_NOW,
    LEGITIMATE_FAIL_CLOSED,
    audit_fallbacks,
)


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    content = (
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False, default=str) + "\n"
    ).encode()
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="database to audit (opened read-only)")
    parser.add_argument("--artifact", required=True, help="saved primary JSONL artifact")
    parser.add_argument("--output", required=True, help="report path; refused if it exists")
    parser.add_argument("--repo", default=None, help="repository root for the frozen model")
    args = parser.parse_args(argv)

    artifact_path = Path(args.artifact)
    output_path = Path(args.output)
    if output_path.exists():
        print(f"refusing to clobber existing output: {output_path}", file=sys.stderr)
        return 2
    payload = artifact_path.read_bytes()
    artifact_sha256 = hashlib.sha256(payload).hexdigest()
    artifact = read_artifact_bytes(payload)
    con = connect(args.db, read_only=True)
    try:
        report = audit_fallbacks(
            con,
            artifact,
            artifact_path=str(artifact_path),
            artifact_sha256=artifact_sha256,
            db_path=str(Path(args.db)),
            repo=Path(args.repo) if args.repo else None,
        )
    finally:
        con.close()
    _write_atomic(output_path, report)
    summary = report["summary"]
    print(
        f"cutoff={report['cutoff']} horizon_fixtures={summary['horizon_fixtures']} "
        f"fallback={summary['fallback_fixtures']} "
        f"primary_saved={summary['primary_saved_fixtures']} "
        f"categories={summary['fallback_categories']} "
        f"fixable={summary['fixture_classification'][FIXABLE_NOW]} "
        f"legitimate={summary['fixture_classification'][LEGITIMATE_FAIL_CLOSED]}"
    )
    print(f"report written: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
