"""Historical backfill from the vaastav/Fantasy-Premier-League archive.

Seasons 2021-22 through 2025-26. This is a backfill source only: the repository stopped
weekly updates after 2024-25 and now refreshes roughly three times per season, so it
must never be relied on in-season. That is what the daily snapshot (R5) is for.

Landing rules:
  * Every raw column is VARCHAR. `""` and `"0.0"` must stay distinguishable, because
    "not measured" and "measured as zero" are different facts (gotcha 5) and casting at
    landing time is an irreversible interpretation.
  * The raw table's column set is the union of the headers actually observed, so a
    column the archive adds later lands instead of being dropped. Per-season presence is
    recorded in `raw_source_columns`, which is how the stg_ layer distinguishes "column
    absent from this season's file" from "column present but empty".
"""

from __future__ import annotations

import csv
import hashlib
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import httpx

from fpl.config import SourcesConfig, load_sources, repo_root
from fpl.types import Season

# raw table name per archive file key.
RAW_TABLES: dict[str, str] = {
    "merged_gw": "raw_merged_gw",
    "fixtures": "raw_fixtures",
    "teams": "raw_teams",
    "players_raw": "raw_players",
}


@dataclass(frozen=True, slots=True)
class ArchiveFile:
    season: Season
    file_key: str
    url: str
    path: Path
    sha256: str
    header: list[str]
    row_count: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        try:
            return next(reader)
        except StopIteration:
            raise ValueError(f"{path} is empty") from None


def _count_rows(path: Path) -> int:
    """Row count excluding the header. Quoted newlines make a plain line count wrong."""
    with path.open("r", encoding="utf-8", newline="") as handle:
        return max(sum(1 for _ in csv.reader(handle)) - 1, 0)


def download_archive(
    *,
    sources: SourcesConfig | None = None,
    dest_dir: Path | None = None,
    force: bool = False,
    client: httpx.Client | None = None,
) -> list[ArchiveFile]:
    """Fetch every archive file, caching to disk. Returns one record per file."""
    config = sources or load_sources()
    root = dest_dir or repo_root() / config.paths.archive_cache
    owns_client = client is None
    http = client or httpx.Client(timeout=config.live_api.timeout_seconds, follow_redirects=True)
    results: list[ArchiveFile] = []
    try:
        for season in config.archive.seasons:
            for file_key in config.archive.files:
                url = config.archive.url(season, file_key)
                path = root / season / f"{file_key}.csv"
                if force or not path.is_file():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    _fetch_to(http, url, path, config)
                    # Be polite even to a CDN.
                    time.sleep(config.live_api.min_request_interval_seconds / 4)
                results.append(
                    ArchiveFile(
                        season=season,
                        file_key=file_key,
                        url=url,
                        path=path,
                        sha256=_sha256(path),
                        header=_read_header(path),
                        row_count=_count_rows(path),
                    )
                )
    finally:
        if owns_client:
            http.close()
    return results


def _fetch_to(client: httpx.Client, url: str, path: Path, config: SourcesConfig) -> None:
    """GET with exponential backoff on transport errors and 5xx."""
    last_error: Exception | None = None
    for attempt in range(config.live_api.max_retries + 1):
        try:
            response = client.get(url)
            if response.status_code == 200:
                path.write_bytes(response.content)
                return
            if response.status_code < 500:
                raise RuntimeError(f"GET {url} returned {response.status_code}")
            last_error = RuntimeError(f"GET {url} returned {response.status_code}")
        except httpx.HTTPError as error:
            last_error = error
        if attempt < config.live_api.max_retries:
            time.sleep(config.live_api.retry_backoff_base_seconds * (2**attempt))
    raise RuntimeError(f"failed to fetch {url} after {config.live_api.max_retries} retries") from (
        last_error
    )


def land_raw(con: duckdb.DuckDBPyConnection, files: list[ArchiveFile]) -> None:
    """Land archive files into raw_ tables, all columns VARCHAR.

    `union_by_name` gives the union of every season's columns with NULL where a season's
    file lacked one, which is exactly the schema-drift behaviour we want -- and the
    NULL is a true "absent", distinct from an empty string in a season that had the
    column.
    """
    now = datetime.now(UTC)
    for file_key, table in RAW_TABLES.items():
        group = [file for file in files if file.file_key == file_key]
        if not group:
            continue
        paths = [str(file.path) for file in group]
        con.execute(
            f"""
            CREATE OR REPLACE TABLE {table} AS
            SELECT
                regexp_extract(filename, '([0-9]{{4}}-[0-9]{{2}})', 1) AS season,
                ? AS _ingested_at,
                *
            FROM read_csv(
                ?,
                all_varchar = true,
                union_by_name = true,
                filename = true,
                header = true,
                sample_size = -1
            )
            """,
            [now, paths],
        )
        # `filename` has served its purpose; keeping it would leak a machine-local path
        # into every downstream query.
        con.execute(f"ALTER TABLE {table} DROP COLUMN filename")

        for file in group:
            con.execute(
                """
                DELETE FROM raw_source_columns WHERE season = ? AND source_table = ?
                """,
                [file.season, table],
            )
            con.executemany(
                """
                INSERT INTO raw_source_columns (season, source_table, column_name, ordinal)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (file.season, table, column, ordinal)
                    for ordinal, column in enumerate(file.header)
                ],
            )
            con.execute(
                """
                INSERT OR REPLACE INTO raw_ingest_log
                    (ingested_at, season, source_table, source_url, row_count, sha256)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [now, file.season, table, file.url, file.row_count, file.sha256],
            )


def source_has_column(
    con: duckdb.DuckDBPyConnection, season: Season, table: str, column: str
) -> bool:
    """Did this season's source file actually carry `column`?

    The question the stg_ layer must ask before interpreting a NULL. Backs gotcha 5.
    """
    row = con.execute(
        """
        SELECT count(*) FROM raw_source_columns
        WHERE season = ? AND source_table = ? AND column_name = ?
        """,
        [season, table, column],
    ).fetchone()
    return bool(row and row[0])
