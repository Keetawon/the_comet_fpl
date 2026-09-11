"""CLI for recording an SDP primary/shadow evidence pair from two published artifacts.

The parent calls this AFTER both immutable artifacts are published. This job OWNS the
``daily_pl_sdp.writer_lock``: it takes the explicit existing operational database, fails
closed on overlap, stale locks, unresolved WALs, or a database that does not already
exist (no schema-only fallback, no default path), then binds the pair on the yielded
write connection. Schema initialization happens inside ``record_pair`` before its
transaction; both ledger vintages and the pair commit or roll back together, so a failure
leaves zero partial new predictions. The record entry instant is always the actual
``datetime.now(UTC)``; there is no caller-supplied recording stamp.

Exit codes: ``0`` recorded (or identical repeat: same id, original stamp kept); ``1``
refused (reason on stderr, nothing written).
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import duckdb

from fpl.artifacts.prospective_points import read_artifact_bytes
from fpl.jobs.daily_pl_sdp import writer_lock
from fpl.storage.sdp_evidence import SdpEvidenceError, record_pair


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bind a published SDP primary artifact and its incumbent shadow artifact as one "
            "pre-deadline evidence pair, inserting both ledger vintages atomically under the "
            "operational writer lock."
        )
    )
    parser.add_argument(
        "--primary",
        required=True,
        type=Path,
        help="path to the published primary prospective-points JSONL artifact",
    )
    parser.add_argument(
        "--shadow",
        required=True,
        type=Path,
        help="path to the published incumbent-shadow (environment disabled) artifact",
    )
    parser.add_argument(
        "--db",
        required=True,
        type=Path,
        help="explicit EXISTING operational database path; never created or defaulted",
    )
    args = parser.parse_args(argv)

    if not args.db.is_file():
        print(
            f"refused: operational database {args.db} does not exist; this job never creates "
            "or defaults a database",
            file=sys.stderr,
        )
        return 1

    artifacts: list[bytes] = []
    try:
        for path in (args.primary, args.shadow):
            artifacts.append(path.read_bytes())
        primary = read_artifact_bytes(artifacts[0])
        shadow = read_artifact_bytes(artifacts[1])
    except (OSError, ValueError) as error:
        print(f"refused: unreadable artifact: {error}", file=sys.stderr)
        return 1

    try:
        with writer_lock(args.db) as con:
            prediction_id = record_pair(
                con,
                primary=primary,
                primary_sha256=hashlib.sha256(artifacts[0]).hexdigest(),
                shadow=shadow,
                shadow_sha256=hashlib.sha256(artifacts[1]).hexdigest(),
            )
    except (SdpEvidenceError, OSError, RuntimeError, duckdb.Error) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    print(f"recorded pair {prediction_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
