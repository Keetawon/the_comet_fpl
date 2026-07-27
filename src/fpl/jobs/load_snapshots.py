"""CLI for checksum-verifying and loading committed snapshot packages."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fpl.ingest.snapshot_files import load_directory
from fpl.storage.db import initialise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load committed FPL snapshot directories.")
    parser.add_argument("directories", nargs="+", type=Path)
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    con = initialise(args.db)
    loaded = 0
    try:
        for directory in args.directories:
            if load_directory(con, directory) is not None:
                loaded += 1
    finally:
        con.close()
    print(f"loaded {loaded} snapshot(s); {len(args.directories) - loaded} already present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
