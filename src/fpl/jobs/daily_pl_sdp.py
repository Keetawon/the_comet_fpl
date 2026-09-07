"""Locked, backed-up local SDP capture; never switches the default database.

Run from a persistent checkout/environment with an explicit operational database:
    python -m fpl.jobs.daily_pl_sdp --db D:/FPL/operational.duckdb --runs D:/FPL/runs

``--raw-only`` retains provider versions without rebuilding feature marts. Client retries
remain the bounded, paced policy in sources.yaml; this wrapper adds no request retry loop.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from fpl.config import load_sources, repo_root
from fpl.ingest.pl_sdp import (
    SdpMatchSummary,
    extract_items,
    is_completed_scored_match,
    parse_match_summary,
    parse_team_stats,
)
from fpl.jobs import capture_pl_sdp, daily_snapshot
from fpl.jobs.build_db import _prepare_temporary_database, _sha256, _wal_path
from fpl.storage.db import connect, default_db_path
from fpl.transform.pl_sdp import (
    KICKOFF_TOLERANCE_SECONDS,
    _fixture_identities,
    retained_complete_stats_ids,
)

logger = logging.getLogger("fpl.daily_pl_sdp")


def _write(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, default=str, allow_nan=False)
        handle.write("\n")


@contextmanager
def writer_lock(
    database: Path, *, backup: Path | None = None
) -> Iterator[duckdb.DuckDBPyConnection]:
    """Fail closed on overlap, stale locks, unresolved WALs, or external DB writers.

    The sidecar covers cooperating jobs; the held DuckDB write connection excludes other
    processes, including callers that ignore the sidecar. The backup is made first under a
    DuckDB read lease (Windows cannot copy a writer-open file), then the write lease covers
    every ingestion/staging operation. A crash leaves the sidecar for explicit diagnosis.
    """
    lock = database.with_name(database.name + ".daily-sdp.lock")
    with lock.open("x", encoding="utf-8") as handle:
        json.dump({"pid": os.getpid(), "started_at": datetime.now(UTC)}, handle, default=str)
    try:
        if _wal_path(database).exists():
            raise RuntimeError("unresolved WAL: close writers and inspect recovery before retrying")
        if backup is not None:
            with connect(database, read_only=True):
                _prepare_temporary_database(database, backup)
        with connect(database) as con:
            yield con
    finally:
        lock.unlink()


def inventory(con: duckdb.DuckDBPyConnection, *, season: str, now: datetime) -> dict[str, Any]:
    """Read raw captures plus current official identities, including in raw-only mode.

    Only exact permanent club identities and the established kickoff tolerance match sources;
    pulse_id is not presumed to equal matchId. No staging or metric repair happens here.
    """
    config = load_sources().pl_sdp
    assert config is not None
    matches: dict[int, SdpMatchSummary] = {}
    for (body,) in con.execute(
        """SELECT CAST(payload AS VARCHAR) FROM raw_pl_sdp_payload
           WHERE provider = 'pl_sdp' AND season = ? AND endpoint = 'matches'
           ORDER BY fetched_at, payload_id""",
        [season],
    ).fetchall():
        for item in extract_items(json.loads(body)):
            match = parse_match_summary(item)
            if match.season_id != config.season_id(season):
                raise ValueError(f"provider season contradicts configured season: {match.match_id}")
            matches[match.match_id] = match

    complete = retained_complete_stats_ids(con, season=season)
    latest_bodies = con.execute(
        """SELECT sdp_match_id, CAST(payload AS VARCHAR) FROM raw_pl_sdp_payload
           WHERE provider = 'pl_sdp' AND season = ? AND endpoint = 'match_stats'
           QUALIFY row_number() OVER (
               PARTITION BY sdp_match_id ORDER BY fetched_at DESC, payload_id DESC
           ) = 1""",
        [season],
    ).fetchall()
    contradictions: list[str] = []
    retained = {int(identifier) for identifier, _ in latest_bodies}
    for identifier, body in latest_bodies:
        if identifier not in complete or identifier not in matches:
            continue
        match = matches[identifier]
        sides = {
            side.side: side for side in parse_team_stats(json.loads(body), match_id=identifier)
        }
        if (sides["home"].team_id, sides["away"].team_id) != (
            match.home_team_id,
            match.away_team_id,
        ):
            contradictions.append(f"match {identifier}: stats teams contradict match metadata")
            complete.remove(identifier)

    official_rows = con.execute(
        """SELECT fixture, finished, finished_provisional, team_h_score, team_a_score
           FROM stg_live_fixture_version WHERE season = ?
           QUALIFY row_number() OVER (
               PARTITION BY fixture ORDER BY known_at DESC, capture_id DESC
           ) = 1""",
        [season],
    ).fetchall()
    ended = {
        int(identifier)
        for identifier, final, provisional, home, away in official_rows
        if (final or provisional) and home is not None and away is not None
    }
    finalized = {
        int(row[0]) for row in official_rows if row[1] and row[3] is not None and row[4] is not None
    }
    resolved: dict[int, int] = {}
    for fixture in _fixture_identities(con, [season]):
        candidates = [
            match
            for match in matches.values()
            if fixture.kickoff_time is not None
            and match.kickoff is not None
            and abs((fixture.kickoff_time - match.kickoff).total_seconds())
            <= KICKOFF_TOLERANCE_SECONDS
            and fixture.home_team_code is not None
            and fixture.away_team_code is not None
            and (fixture.home_team_code, fixture.away_team_code)
            == (match.home_team_id, match.away_team_id)
        ]
        if len(candidates) != 1:
            continue
        match = candidates[0]
        if fixture.fixture in ended and (fixture.home_score, fixture.away_score) != (
            match.home_score,
            match.away_score,
        ):
            contradictions.append(
                f"fixture {fixture.fixture} / match {match.match_id}: scores differ"
            )
            continue
        if match.match_id in resolved.values():
            contradictions.append(f"match {match.match_id}: more than one official fixture")
            continue
        resolved[fixture.fixture] = match.match_id

    completed = {
        identifier
        for identifier, match in matches.items()
        if is_completed_scored_match(match, now=now)
    }
    expected = completed | {resolved[fixture] for fixture in ended if fixture in resolved}
    missing = expected - complete
    unresolved = sorted(ended - resolved.keys())
    unresolved_provider = sorted(completed - set(resolved.values()))
    issues = []
    if not official_rows:
        issues.append("no official current-season fixtures retained")
    if not matches:
        issues.append("no provider current-season matches retained")
    latest = con.execute(
        """SELECT CAST(max(fetched_at) AS VARCHAR),
                  date_diff('second', max(fetched_at), ?)
           FROM raw_pl_sdp_payload WHERE provider = 'pl_sdp' AND season = ?""",
        [now, season],
    ).fetchone()
    return {
        "season": season,
        "checked_at": now,
        "official_fixture_count": len(official_rows),
        "official_finalized": len(finalized),
        "official_provisional_ended": len(ended - finalized),
        "provider_completed": len(completed),
        "expected_completed": len(expected),
        "retained_complete": len(expected & complete),
        "retained_complete_match_ids": sorted(expected & complete),
        "missing_match_ids": sorted(missing),
        "incomplete_match_ids": sorted(missing & retained),
        "awaiting_stats_match_ids": sorted(missing - retained),
        "awaiting_provider_completion_match_ids": sorted(expected - completed),
        "unresolved_fixture_ids": unresolved,
        "unresolved_provider_match_ids": unresolved_provider,
        "contradictions": contradictions,
        "issues": issues,
        "latest_retained_payload_fetched_at": latest[0] if latest else None,
        "latest_retained_payload_age_seconds": latest[1] if latest else None,
        "timestamp_note": "unchanged responses retain known_at; request checks are in run report",
        "healthy": not (missing or unresolved or unresolved_provider or contradictions or issues),
    }


def _verify_staging(
    con: duckdb.DuckDBPyConnection,
    *,
    season: str,
    expected: list[int],
    as_of: datetime,
) -> dict[str, Any]:
    """A successful audit exit is insufficient: exercise the real strict PIT capability."""
    from fpl.features.pit import AsOf, FeatureSource, PointInTimeView

    view = PointInTimeView(FeatureSource(con), AsOf(as_of))
    rows = view.observed_team_football(seasons=[season], providers=["pl_sdp"]).to_dicts()
    by_match: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        by_match.setdefault(int(row["sdp_match_id"]), []).append(row)
    invalid: list[int] = []
    for identifier in expected:
        sides = by_match.get(identifier, [])
        if (
            len(sides) != 2
            or {side["was_home"] for side in sides} != {True, False}
            or sides[0]["team_code"] is None
            or sides[1]["team_code"] is None
            or sides[0]["team_code"] == sides[1]["team_code"]
            or sides[0]["team_code"] != sides[1]["opponent_team_code"]
            or sides[1]["team_code"] != sides[0]["opponent_team_code"]
        ):
            invalid.append(identifier)
    tactical = view.observed_team_tactical_form(seasons=[season], providers=["pl_sdp"])
    return {
        "as_of": as_of,
        "reader": "PointInTimeView.observed_team_football / observed_team_tactical_form",
        "expected_matches": len(expected),
        "football_rows": len(rows),
        "tactical_rows": tactical.height,
        "missing_or_invalid_match_ids": invalid,
        "healthy": not invalid and (not expected or tactical.height > 0),
    }


def run(
    *,
    database: Path,
    runs: Path,
    raw_only: bool = False,
    include_workload: bool = False,
    lookback_days: int = 7,
    player_history: bool = False,
) -> int:
    """One local cycle. Partial raw successes survive a later network or staging failure."""
    database = database.resolve(strict=True)
    if not database.is_file() or database == default_db_path().resolve():
        raise ValueError("use a separate existing operational database, never the default database")
    season = load_sources().current_season.season
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid.uuid4().hex[:8]
    destination = runs.resolve() / run_id
    destination.mkdir(parents=True, exist_ok=False)
    report: dict[str, Any] = {
        "run_id": run_id,
        "started_at": datetime.now(UTC),
        "database": str(database),
        "python": sys.executable,
        "season": season,
        "mode": "raw_only" if raw_only else "capture_and_stage",
        "staging_status": "deferred" if raw_only else "pending",
        "consumer_ready": False,
        "failures": [],
        "retry_policy": "existing bounded client retries only; no wrapper retries",
    }
    handler = logging.FileHandler(destination / "run.log", encoding="utf-8", mode="x")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    try:
        report["git_head"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root(),
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).strip()
        report["source_sha256"] = {
            name: _sha256(repo_root() / name)
            for name in (
                "config/sources.yaml",
                "src/fpl/jobs/daily_pl_sdp.py",
                "src/fpl/jobs/capture_pl_sdp.py",
                "src/fpl/jobs/audit_pl_sdp.py",
                "src/fpl/ingest/pl_sdp.py",
                "src/fpl/transform/pl_sdp.py",
                "src/fpl/features/pit.py",
                "src/fpl/transform/football_v2.py",
                "src/fpl/transform/football_versions.py",
                "src/fpl/storage/schema.sql",
            )
        }
        backup = destination / "before.duckdb"
        with writer_lock(database, backup=backup) as con:
            report["backup"] = {
                "path": str(backup),
                "sha256": _sha256(backup),
                "policy": "read lease; no WAL; source/copy SHA256 equality; then write lease",
            }
            _write(
                destination / "before.json", inventory(con, season=season, now=datetime.now(UTC))
            )
            snapshot_status = (
                daily_snapshot.run(db_path=database, include_player_history=True)
                if player_history
                else daily_snapshot.run(db_path=database)
            )
            report["snapshot_exit_code"] = snapshot_status
            if snapshot_status:
                report["failures"].append(f"official snapshot failed: exit {snapshot_status}")
            for name, refresh in (("missing", False), ("revision", True)):
                captured = capture_pl_sdp.capture(
                    db_path=database,
                    season=season,
                    refresh_stats=refresh,
                    lookback_days=lookback_days if refresh else None,
                )
                report[name] = asdict(captured)
                report[name]["provider_listing_checked_at"] = datetime.now(UTC)
                report["failures"].extend(captured.failures)
                logger.info("%s capture: %s", name, asdict(captured))
            report["freshness"] = inventory(con, season=season, now=datetime.now(UTC))
            _write(destination / "after.json", report["freshness"])
            if not raw_only:
                # Lazy import lets raw-only capture survive a feature/staging import defect.
                from fpl.jobs import audit_pl_sdp

                report["staging_status"] = "running"
                status = audit_pl_sdp.main(
                    ["--db", str(database), "--stage", "--results", str(destination / "staging")]
                )
                report["staging_exit_code"] = status
                if status:
                    report["staging_status"] = "failed"
                    report["failures"].append(f"staging failed: exit {status}")
                else:
                    report["staging_verification"] = _verify_staging(
                        con,
                        season=season,
                        expected=report["freshness"]["retained_complete_match_ids"],
                        as_of=datetime.now(UTC),
                    )
                    report["staging_status"] = (
                        "verified" if report["staging_verification"]["healthy"] else "failed"
                    )
                    if not report["staging_verification"]["healthy"]:
                        report["failures"].append(
                            "staged data failed strict PIT completeness check"
                        )
                from fpl.storage.sdp_runtime import load_sdp_state

                state = load_sdp_state(con, cutoff=datetime.now(UTC), season=season)
                current_rows = [r for r in state.rows if r.season == season]
                report["production_health"] = {
                    "matches_valid": len(current_rows) // 2,
                    "latest_completed_match": max(state.expected.values(), default=None),
                    "latest_valid_sdp_known_at": max(
                        (r.provenance["known_at"] for r in current_rows), default=None
                    ),
                    "global_failure": state.global_failure,
                    "schema_validation_failures": sum(
                        reason == "SDP_SCHEMA_FALLBACK" for reason in state.failures.values()
                    )
                    + int(state.global_failure == "SDP_SCHEMA_FALLBACK"),
                    "identity_failures": sum(
                        reason == "SDP_IDENTITY_FALLBACK" for reason in state.failures.values()
                    )
                    + int(state.global_failure == "SDP_IDENTITY_FALLBACK"),
                    "failures": {str(key): value for key, value in state.failures.items()},
                    "diagnostics": state.diagnostics,
                }
            if include_workload:
                from fpl.jobs.capture_sdp_workload import capture as capture_workload

                report["workload"] = capture_workload(
                    database=database, lookback_days=lookback_days
                )
            con.execute("CHECKPOINT")
        # Windows prevents hashing a writer-open file. No default/source DB is touched.
        with connect(database, read_only=True):
            report["database_sha256_after"] = _sha256(database)
    except Exception as error:
        logger.exception("daily SDP cycle failed; retained raw successes are not rolled back")
        report["failures"].append(f"{type(error).__name__}: {error}")
        if report["staging_status"] == "running":
            report["staging_status"] = "failed"
    finally:
        report["finished_at"] = datetime.now(UTC)
        report["healthy"] = not report["failures"] and report.get("freshness", {}).get(
            "healthy", False
        )
        report["exit_code"] = 0 if report["healthy"] else 1
        report["consumer_ready"] = report["healthy"] and report["staging_status"] == "verified"
        requests = sum(report.get(k, {}).get("stats_requested", 0) for k in ("missing", "revision"))
        captured = sum(report.get(k, {}).get("stats_fetched", 0) for k in ("missing", "revision"))
        previous_success = None
        for path in sorted(runs.resolve().glob("*/report.json"), reverse=True):
            try:
                previous = json.loads(path.read_text(encoding="utf-8"))
                if previous.get("healthy") and previous.get("database") == str(database):
                    previous_success = datetime.fromisoformat(previous["finished_at"])
                    break
            except (OSError, ValueError, KeyError):
                continue
        last_success = report["finished_at"] if report["healthy"] else previous_success
        report["operational_metrics"] = {
            "capture_success_rate": captured / requests if requests else None,
            "matches_expected": report.get("freshness", {}).get("expected_completed"),
            "matches_captured": report.get("freshness", {}).get("retained_complete"),
            "matches_valid": report.get("production_health", {}).get("matches_valid"),
            "hours_since_last_successful_capture": (
                report["finished_at"] - last_success
            ).total_seconds()
            / 3600
            if last_success
            else None,
            "latest_sdp_known_at": report.get("freshness", {}).get(
                "latest_retained_payload_fetched_at"
            ),
            "latest_completed_match": report.get("production_health", {}).get(
                "latest_completed_match"
            ),
            "identity_failures": report.get("production_health", {}).get("identity_failures"),
            "schema_validation_failures": report.get("production_health", {}).get(
                "schema_validation_failures"
            ),
        }
        _write(destination / "report.json", report)
        logging.getLogger().removeHandler(handler)
        handler.close()
    logger.info("daily SDP report: %s (healthy=%s)", destination / "report.json", report["healthy"])
    return int(report["exit_code"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--runs", required=True, type=Path)
    parser.add_argument("--raw-only", action="store_true")
    parser.add_argument("--workload", action="store_true")
    parser.add_argument("--player-history", action="store_true")
    parser.add_argument("--lookback-days", type=int, default=5)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return run(
        database=args.db,
        runs=args.runs,
        raw_only=args.raw_only,
        include_workload=args.workload,
        lookback_days=args.lookback_days,
        player_history=args.player_history,
    )


if __name__ == "__main__":
    sys.exit(main())
