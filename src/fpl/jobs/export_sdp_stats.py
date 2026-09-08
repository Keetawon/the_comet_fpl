"""Write one immutable observed SDP dashboard sidecar from a read-only database."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from fpl.publish.sdp_stats import export_sdp_stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--as-of", required=True, type=datetime.fromisoformat)
    args = parser.parse_args(argv)
    receipt = export_sdp_stats(args.db, args.output, as_of=args.as_of)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
