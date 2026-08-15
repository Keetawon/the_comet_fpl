"""Publish the dashboard read-model JSON from a BI Parquet export.

The domain implementation lives in :mod:`fpl.publish.dashboard_json`; this module
deliberately keeps argument parsing and process exit handling thin.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fpl.publish.dashboard_json import DashboardJsonError, export_dashboard_json
from fpl.publish.export import BiExportError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Atomically publish versioned per-page dashboard read models "
            "(fixture_matrix.json, players.json) from a published BI Parquet export."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Published BI Parquet export directory (read-only input; never a DuckDB).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Published read-model endpoint (an atomically replaced directory symlink).",
    )
    args = parser.parse_args(argv)

    try:
        result = export_dashboard_json(args.input, args.output)
    except (DashboardJsonError, BiExportError) as exc:
        print(f"dashboard read models not published: {exc}", file=sys.stderr)
        return 1

    print(
        f"published {result.fixture_matrix_rows} team and {result.players_rows} player "
        f"read-model rows to {result.output_dir}; content_sha256={result.content_sha256}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
