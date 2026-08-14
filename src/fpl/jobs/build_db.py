"""Full database rebuild: archive -> raw_ -> stg_ -> mart_.

    python -m fpl.jobs.build_db            # build, using the cached archive if present
    python -m fpl.jobs.build_db --refresh  # re-download the archive first

Idempotent: every layer is rebuilt from the one below it, so running twice produces the
same database. Failure-atomic: work happens in a sibling DuckDB file and is promoted with
one `os.replace` only after every layer succeeds. Existing live snapshots are cloned into
the work file, and a concurrent target change aborts promotion instead of losing new data.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import shutil
import sys
import uuid
from pathlib import Path

from fpl.config import available_rulesets, load_data_quality, load_sources
from fpl.ingest.archive import download_archive, land_raw
from fpl.storage.db import default_db_path, initialise, record_build_metadata
from fpl.transform import crosswalk, facts, quality

logger = logging.getLogger("fpl.build_db")


def build(
    *, db_path: Path | None = None, refresh_archive: bool = False, strict: bool = True
) -> int:
    """Rebuild into a sibling file and atomically promote it on complete success."""
    sources = load_sources()
    data_quality = load_data_quality()
    target_path = (db_path or default_db_path()).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = _temporary_database_path(target_path)

    try:
        original_sha256 = _prepare_temporary_database(target_path, temporary_path)

        logger.info("downloading archive (%d seasons)", len(sources.archive.seasons))
        files = download_archive(sources=sources, force=refresh_archive)

        con = initialise(temporary_path)
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
                logger.error(
                    "%d row(s) failed the element->code join", report.unmatched_element_rows
                )
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
                "mart_fact_player_fixture=%d mart_fact_team_match=%d mart_target_player_fixture=%d "
                "mart_fact_player_form=%d",
                counts.player_fixture_rows,
                counts.team_match_rows,
                counts.target_rows,
                counts.player_form_rows,
            )

            record_build_metadata(con, "seasons", ",".join(sources.archive.seasons))
            record_build_metadata(con, "rulesets", ",".join(available_rulesets()))
            record_build_metadata(con, "player_fixture_rows", str(counts.player_fixture_rows))
            record_build_metadata(con, "team_match_rows", str(counts.team_match_rows))
            record_build_metadata(con, "player_form_rows", str(counts.player_form_rows))
            record_build_metadata(con, "anomaly_checks_triggered", str(len(anomalies)))
        finally:
            con.close()

        _promote_database(temporary_path, target_path, original_sha256)
    finally:
        _discard_database(temporary_path)
    return 0


def _temporary_database_path(target_path: Path) -> Path:
    """A unique sibling keeps the final `os.replace` on one filesystem."""
    return target_path.with_name(f".{target_path.name}.{uuid.uuid4().hex}.tmp")


def _wal_path(database_path: Path) -> Path:
    return Path(f"{database_path}.wal")


def _sha256(database_path: Path) -> str:
    digest = hashlib.sha256()
    with database_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prepare_temporary_database(target_path: Path, temporary_path: Path) -> str | None:
    """Clone existing state so irreplaceable live snapshots survive an archive rebuild."""
    if not target_path.exists():
        return None
    target_wal = _wal_path(target_path)
    if target_wal.exists():
        raise RuntimeError(
            f"refusing to copy {target_path}: {target_wal.name} exists; "
            "close active writers or recover the existing database first"
        )
    shutil.copy2(target_path, temporary_path)
    source_sha256 = _sha256(target_path)
    if _sha256(temporary_path) != source_sha256:
        raise RuntimeError(f"{target_path} changed while its rebuild image was being copied")
    return source_sha256


def _promote_database(temporary_path: Path, target_path: Path, original_sha256: str | None) -> None:
    """Atomically replace only if the target is unchanged since the rebuild started."""
    target_wal = _wal_path(target_path)
    if target_wal.exists():
        raise RuntimeError(
            f"refusing to replace {target_path}: {target_wal.name} exists; "
            "close active writers or recover the existing database first"
        )
    if original_sha256 is None:
        if target_path.exists():
            raise RuntimeError(f"refusing to replace {target_path}: it was created during rebuild")
    else:
        changed = not target_path.exists() or _sha256(target_path) != original_sha256
        if target_wal.exists() or changed:
            raise RuntimeError(
                f"refusing to replace {target_path}: it changed during rebuild; "
                "the newer database was preserved"
            )
    os.replace(temporary_path, target_path)


def _discard_database(database_path: Path) -> None:
    """Best-effort cleanup for an unpromoted DuckDB file and its WAL sidecar."""
    for candidate in (_wal_path(database_path), database_path):
        try:
            candidate.unlink(missing_ok=True)
        except OSError as error:
            logger.warning("could not remove failed-build file %s: %s", candidate, error)


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
