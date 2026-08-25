"""Create the public-safe dashboard read-model directory and release asset."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fpl.publish.dashboard_json import DashboardJsonError
from fpl.publish.export import BiExportError
from fpl.publish.public_dashboard import (
    PublicDashboardPackageError,
    package_public_dashboard,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate an internal dashboard JSON generation, remove user-custom plans, "
            "normalize public provenance, and emit a deterministic ZIP release asset."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Validated internal dashboard JSON generation (read-only).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New directory for the validated public-safe generation.",
    )
    parser.add_argument(
        "--archive",
        type=Path,
        required=True,
        help="New deterministic .zip asset; its eight files are stored at archive root.",
    )
    args = parser.parse_args(argv)

    try:
        result = package_public_dashboard(args.input, args.output, args.archive)
    except (
        PublicDashboardPackageError,
        DashboardJsonError,
        BiExportError,
        OSError,
        ValueError,
    ) as exc:
        print(f"public dashboard package not created: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result.metadata(), allow_nan=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
