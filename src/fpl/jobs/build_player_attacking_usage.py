"""Build a descriptive current-player JSON/CSV scouting export, without inference."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from fpl.publish.player_attacking_usage import METHOD_NOTE, SORT_FIELDS, build_usage_export
from fpl.storage.db import default_db_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=METHOD_NOTE)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument(
        "--output-dir", type=Path, required=True, help="New immutable export directory."
    )
    parser.add_argument(
        "--as-of",
        type=datetime.fromisoformat,
        default=None,
        help="Aware cutoff; default actual UTC now.",
    )
    parser.add_argument(
        "--position", choices=("DEF", "MID", "FWD"), default=None, help="CSV filter only."
    )
    parser.add_argument("--sort", choices=SORT_FIELDS, default="recent_usage_percentile")
    parser.add_argument(
        "--min-minutes",
        type=int,
        default=180,
        help="CSV/list exposure; 0 includes unranked players.",
    )
    args = parser.parse_args(argv)
    try:
        result = build_usage_export(
            args.db or default_db_path(),
            args.output_dir,
            as_of=args.as_of or datetime.now(UTC),
            position=args.position,
            sort=args.sort,
            minimum_minutes=args.min_minutes,
        )
    except (ValueError, OSError, duckdb.Error) as exc:
        print(f"Scouting export not published: {exc}", file=sys.stderr)
        return 1
    print(METHOD_NOTE)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
