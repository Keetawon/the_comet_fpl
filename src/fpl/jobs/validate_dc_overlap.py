"""Lock the DC rebuild formula against FPL's own 2025-26 data.

    python -m fpl.jobs.validate_dc_overlap

2025-26 is the one season carrying both FPL's recorded `defensive_contribution` and the raw
actions it is built from. Feeding FPL's own raw inputs through
`reconstruct_defensive_contribution` and requiring exact agreement on every scoring position
proves the rebuild formula is FPL's definition, not an approximation. It exits non-zero if any
scoring row fails to reconcile, so it is a runnable contract, not just a report.

The same check, fed an external source's actions on 2025-26 instead of FPL's own, becomes the
definition-match test for that source before any 2021-22..2024-25 backfill is trusted. That
step needs a chosen external source; this job needs only the database already built.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from fpl.storage.db import connect
from fpl.transform.defensive_actions import (
    DcObservation,
    check_dc_reconstruction,
)
from fpl.types import Position

logger = logging.getLogger("fpl.validate_dc_overlap")

_OVERLAP_SEASON = "2025-26"


def _load_observations(db_path: Path | None, season: str) -> list[DcObservation]:
    """Read one season's raw actions and recorded DC from `mart_fact_player_fixture`.

    NULL means unmeasured, never zero: rows missing any input or the recorded DC are skipped
    rather than coerced. In the overlap season all four are 100% non-null, so nothing is
    skipped, but the filter keeps the check honest if run on a partial season.
    """
    con = connect(db_path, read_only=True)
    try:
        rows = con.execute(
            """
            SELECT position, tackles, clearances_blocks_interceptions, recoveries,
                   defensive_contribution
            FROM mart_fact_player_fixture
            WHERE season = ?
              AND tackles IS NOT NULL
              AND clearances_blocks_interceptions IS NOT NULL
              AND recoveries IS NOT NULL
              AND defensive_contribution IS NOT NULL
            """,
            [season],
        ).fetchall()
    finally:
        con.close()

    observations: list[DcObservation] = []
    for position, tackles, cbi, recoveries, recorded_dc in rows:
        observations.append(
            DcObservation(
                position=Position(position),
                tackles=int(tackles),
                cbi=int(cbi),
                recoveries=int(recoveries),
                recorded_dc=int(recorded_dc),
            )
        )
    return observations


def validate(db_path: Path | None = None, *, season: str = _OVERLAP_SEASON) -> int:
    """Return 0 when the rebuild reconciles on every scoring row, 1 otherwise."""
    observations = _load_observations(db_path, season)
    report = check_dc_reconstruction(observations)

    logger.info(
        "DC rebuild on %s: %d rows, %d scoring rows, %d exact, %d mismatch (rate %.6f)",
        season,
        report.total_rows,
        report.scoring_rows,
        report.exact_matches,
        report.mismatches,
        report.agreement_rate,
    )
    for position in (Position.DEF, Position.MID, Position.FWD):
        seen, matched = report.by_position.get(position, (0, 0))
        logger.info("  %s: %d/%d exact", position.value, matched, seen)

    if not report.reconciles:
        logger.error(
            "DC rebuild did NOT reconcile: %d mismatch(es), max abs error %d, examples %r",
            report.mismatches,
            report.max_abs_error,
            report.mismatch_examples,
        )
        return 1

    logger.info("DC rebuild reconciles exactly on all %d scoring rows.", report.scoring_rows)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the DC rebuild against FPL 2025-26.")
    parser.add_argument("--database", type=Path, default=None, help="Path to the DuckDB file.")
    parser.add_argument("--season", default=_OVERLAP_SEASON, help="Overlap season to check.")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    return validate(args.database, season=args.season)


if __name__ == "__main__":
    sys.exit(main())
