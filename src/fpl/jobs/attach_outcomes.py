"""Attach finalized mart outcomes to the append-only prediction ledger.

The job is intentionally thin.  Source validation, player-fixture grain checks, idempotent exact
repeats, and immutable-conflict detection live in :mod:`fpl.storage.outcomes`; the ledger owns the
transaction that writes new outcome rows.  Re-presenting the same finalized values is a no-op;
re-presenting a key with different values fails rather than updating it.  It never reads or changes
a prediction.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from fpl.storage.db import initialise
from fpl.storage.outcomes import OutcomeAttachmentError, attach_finalized_outcomes

logger = logging.getLogger("fpl.jobs.attach_outcomes")


def _parse_as_of(value: str) -> datetime:
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid ISO 8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("--as-of must include a UTC offset")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Attach finalized player-fixture outcomes from the marts to the ledger."
    )
    parser.add_argument(
        "--as-of",
        required=True,
        type=_parse_as_of,
        help="timezone-aware ISO 8601 cutoff; only kickoff_time strictly before it is eligible",
    )
    parser.add_argument(
        "--season",
        default=None,
        help="optional season filter (default: all seasons with eligible final fixtures)",
    )
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    con = initialise(args.db)
    try:
        result = attach_finalized_outcomes(con, as_of=args.as_of, season=args.season)
    except OutcomeAttachmentError as exc:
        logger.error("%s", exc)
        return 1
    finally:
        con.close()

    print(
        f"selected {result.selected} finalized player-fixture outcomes; "
        f"attached {result.attached}, unchanged {result.already_attached}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
