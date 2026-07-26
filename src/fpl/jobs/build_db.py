"""Full database rebuild: archive -> raw_ -> stg_ -> mart_.

    python -m fpl.jobs.build_db            # build, using the cached archive if present
    python -m fpl.jobs.build_db --refresh  # re-download the archive first

Idempotent: every layer is rebuilt from the one below it, so running twice produces the
same database.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from fpl.config import available_rulesets, load_data_quality, load_sources
from fpl.ingest.archive import download_archive, land_raw
from fpl.storage.db import initialise, record_build_metadata
from fpl.transform import crosswalk, facts, quality

logger = logging.getLogger("fpl.build_db")


def build(
    *, db_path: Path | None = None, refresh_archive: bool = False, strict: bool = True
) -> int:
    """Rebuild the database. Returns a process exit code."""
    sources = load_sources()
    data_quality = load_data_quality()

    logger.info("downloading archive (%d seasons)", len(sources.archive.seasons))
    files = download_archive(sources=sources, force=refresh_archive)

    con = initialise(db_path)
    try:
        logger.info("landing raw layer")
        land_raw(con, files)

        logger.info("building stg dimensions")
        crosswalk.build_dimensions(con)

        logger.info("building stg_player_fixture")
        report = crosswalk.build_player_fixture(
            con, nullify_predicates=quality.nullify_predicates(data_quality)
        )
        logger.info(
            "staged %d rows (raw %d, %d duplicate, %d manager row(s) excluded, %d unmatched)",
            report.staged_rows,
            report.raw_rows,
            report.duplicate_rows_removed,
            report.manager_rows_excluded,
            report.unmatched_element_rows,
        )
        if report.unmatched_element_rows:
            # Measured match rate is 100.000%; anything else means the crosswalk broke.
            logger.error("%d row(s) failed the element->code join", report.unmatched_element_rows)
            if strict:
                return 1

        logger.info("validating declared data-quality repairs")
        quality.assert_nullify_expectations(con, data_quality)

        anomalies = quality.validate(con, data_quality)
        for anomaly in anomalies:
            logger.warning("anomaly %s: %s", anomaly.check_id, anomaly.detail)

        logger.info("building mart layer")
        counts = facts.build_all(con)
        logger.info(
            "mart_fact_player_fixture=%d mart_fact_team_match=%d mart_target_player_fixture=%d",
            counts.player_fixture_rows,
            counts.team_match_rows,
            counts.target_rows,
        )

        record_build_metadata(con, "seasons", ",".join(sources.archive.seasons))
        record_build_metadata(con, "rulesets", ",".join(available_rulesets()))
        record_build_metadata(con, "player_fixture_rows", str(counts.player_fixture_rows))
        record_build_metadata(con, "team_match_rows", str(counts.team_match_rows))
        record_build_metadata(con, "anomaly_checks_triggered", str(len(anomalies)))
    finally:
        con.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild the FPL model database.")
    parser.add_argument("--db", type=Path, default=None, help="database path")
    parser.add_argument(
        "--refresh", action="store_true", help="re-download the archive before building"
    )
    parser.add_argument(
        "--no-strict", action="store_true", help="warn instead of failing on join misses"
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return build(db_path=args.db, refresh_archive=args.refresh, strict=not args.no_strict)


if __name__ == "__main__":
    sys.exit(main())
