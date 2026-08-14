"""Publish the validated, read-only BI semantic export.

The domain implementation lives in :mod:`fpl.publish.export`; this module deliberately keeps
argument parsing and process exit handling thin.
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

from fpl.publish.export import BiExportError, export_bi
from fpl.storage.db import default_db_path


def _non_negative_hours(value: str) -> float:
    try:
        hours = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number of hours") from exc
    if hours < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return hours


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Atomically publish the complete, versioned BI semantic-contract export."
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Published export endpoint (an atomically replaced directory symlink).",
    )
    parser.add_argument(
        "--db", type=Path, default=None, help="DuckDB source (default: project DB)."
    )
    parser.add_argument(
        "--optimizer-plan",
        type=Path,
        action="append",
        default=[],
        help="Optimizer decision artifact to include; repeat for multiple immutable plans.",
    )
    parser.add_argument(
        "--max-source-age-hours",
        type=_non_negative_hours,
        default=None,
        help="Optional maximum bootstrap-known-at age relative to each forecast as_of.",
    )
    args = parser.parse_args(argv)

    maximum_source_age = (
        None if args.max_source_age_hours is None else timedelta(hours=args.max_source_age_hours)
    )
    try:
        result = export_bi(
            args.db or default_db_path(),
            args.output,
            optimizer_plan_paths=tuple(args.optimizer_plan),
            maximum_source_age=maximum_source_age,
        )
    except BiExportError as exc:
        print(f"BI export not published: {exc}", file=sys.stderr)
        return 1

    print(
        f"published {len(result.tables)} semantic-contract tables to {result.output_dir} "
        f"({len(result.exported_run_ids)} recorded forecast run(s)); "
        f"content_sha256={result.content_sha256}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
