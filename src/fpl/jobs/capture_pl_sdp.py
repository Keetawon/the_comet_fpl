"""Incremental current-season Premier League SDP capture.

    python -m fpl.jobs.capture_pl_sdp
    python -m fpl.jobs.capture_pl_sdp --season 2026-27 --lookback-days 5
    python -m fpl.jobs.capture_pl_sdp --season 2026-27 --refresh-stats

The operational counterpart to `backfill_pl_sdp`: run it after matches complete. It fetches
the current season's match list, then stats for matches that have finished and whose stats are
not already captured, so a daily run costs a handful of requests rather than a season's worth.

Ordering in the wider pipeline, and why it is this way round:

    pre-match    FPL bootstrap / fixtures snapshot   (schedule, prices, availability)
    post-match   SDP match + stats capture           (what actually happened on the pitch)
    finalised    FPL outcome attachment              (official points, append-only)

The V2 model reads only what was known before its own prediction cutoff, so a capture landing
after a prediction cannot contaminate it -- `known_at` on every staged row is the fetch time.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb

from fpl.config import load_sources
from fpl.ingest.fpl_api import EgressBlockedError
from fpl.ingest.pl_sdp import (
    PlSdpClient,
    SdpMatchSummary,
    is_completed_scored_match,
    parse_team_stats,
)
from fpl.storage.db import initialise
from fpl.transform import pl_sdp as sdp_transform

logger = logging.getLogger("fpl.capture_pl_sdp")


@dataclass
class CaptureSource:
    provider_match_id: int
    request_fetched_at: datetime
    payload_id: str
    payload_sha256: str
    known_at: datetime
    new_version: bool


@dataclass
class CaptureReport:
    season: str = ""
    matches_seen: int = 0
    completed: int = 0
    already_captured: int = 0
    stats_fetched: int = 0
    payloads_new: int = 0
    requests: int = 0
    stats_requested: int = 0
    failures: tuple[str, ...] = ()
    required_history_rechecks: tuple[int, ...] = ()
    source_versions: tuple[CaptureSource, ...] = ()


def required_core_rechecks(
    con: duckdb.DuckDBPyConnection, *, season: str, completed: list[SdpMatchSummary]
) -> set[int]:
    """Retry invalid last-five evidence even after it ages out of the revision lookback.

    This only chooses HTTP requests. Normalization and the prediction identity/PIT gates
    still independently validate every response; no missing field is repaired here.
    """
    from fpl.storage.sdp_runtime import checked_metrics

    counts: dict[int, int] = {}
    required: set[int] = set()
    for match in sorted(completed, key=lambda m: (m.kickoff, m.match_id), reverse=True):
        for team in (match.home_team_id, match.away_team_id):
            if team is not None:
                if counts.get(team, 0) < 5:
                    required.add(match.match_id)
                counts[team] = counts.get(team, 0) + 1
    rows = con.execute(
        """SELECT sdp_match_id, CAST(payload AS VARCHAR) AS body
        FROM raw_pl_sdp_payload WHERE provider='pl_sdp' AND season=? AND endpoint='match_stats'
        QUALIFY row_number() OVER(PARTITION BY sdp_match_id
            ORDER BY fetched_at DESC,payload_id DESC)=1""",
        [season],
    ).fetchall()
    invalid = set()
    for identifier, body in rows:
        if identifier not in required:
            continue
        try:
            for side in parse_team_stats(json.loads(body), match_id=identifier):
                checked_metrics(dict(side.stats))
        except (ValueError, TypeError, KeyError, RuntimeError):
            invalid.add(identifier)
    return invalid


def capture(
    *,
    season: str | None = None,
    db_path: Path | None = None,
    lookback_days: int | None = None,
    limit_matches: int | None = None,
    client: PlSdpClient | None = None,
    now: datetime | None = None,
    refresh_stats: bool | None = None,
    recheck_required_history: bool = False,
) -> CaptureReport:
    if limit_matches is not None and limit_matches <= 0:
        raise ValueError("limit_matches must be positive")
    if lookback_days is not None and lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    # A bounded post-match capture also refreshes provider corrections. Callers doing
    # an unbounded missing-only pass can still explicitly set refresh_stats=False.
    refresh_stats = lookback_days is not None if refresh_stats is None else refresh_stats
    sources = load_sources()
    if sources.pl_sdp is None:
        raise RuntimeError("config/sources.yaml carries no `pl_sdp` block")
    resolved_season = season or sources.current_season.season
    season_id = sources.pl_sdp.season_id(resolved_season)
    moment = now or datetime.now(UTC)
    horizon = moment - timedelta(days=lookback_days) if lookback_days else None

    owned = client is None
    sdp = client or PlSdpClient(config=sources.pl_sdp)
    report = CaptureReport(season=resolved_season)
    failures: list[str] = []
    versions: list[CaptureSource] = []
    try:
        con = initialise(db_path)
        try:
            captured = (
                set()
                if refresh_stats
                else sdp_transform.retained_complete_stats_ids(con, season=resolved_season)
            )
            summaries: list[SdpMatchSummary] = []
            for raw, page in sdp.iter_matches(season_id=season_id):
                _, is_new = sdp_transform.land_payload(con, raw, season=resolved_season)
                report.payloads_new += int(is_new)
                summaries.extend(page)
            report.matches_seen = len({summary.match_id for summary in summaries})
            if report.matches_seen != len(summaries):
                raise ValueError("duplicate provider match records in capture catalogue")

            rechecks = (
                required_core_rechecks(
                    con,
                    season=resolved_season,
                    completed=[
                        m
                        for m in summaries
                        if m.kickoff and is_completed_scored_match(m, now=moment)
                    ],
                )
                if recheck_required_history
                else set()
            )
            report.required_history_rechecks = tuple(sorted(rechecks))

            wanted: list[int] = []
            for summary in sorted(summaries, key=lambda item: item.match_id):
                if not is_completed_scored_match(summary, now=moment):
                    continue
                report.completed += 1
                if horizon is not None and summary.kickoff is not None:
                    if summary.kickoff < horizon and summary.match_id not in rechecks:
                        continue
                if summary.match_id in captured and summary.match_id not in rechecks:
                    report.already_captured += 1
                    continue
                wanted.append(summary.match_id)

            if limit_matches is not None:
                wanted = wanted[:limit_matches]
            report.stats_requested = len(wanted)

            for match_id in wanted:
                try:
                    raw = sdp.fetch_match_stats(match_id)
                except EgressBlockedError:
                    raise
                except Exception as error:
                    failures.append(f"match {match_id}: {error}")
                    continue
                identifier, is_new = sdp_transform.land_payload(
                    con, raw, season=resolved_season, sdp_match_id=match_id
                )
                known = con.execute(
                    "SELECT epoch_us(fetched_at) FROM raw_pl_sdp_payload WHERE payload_id=?",
                    [identifier],
                ).fetchone()
                if known is None:
                    raise RuntimeError("landed SDP payload receipt is unavailable")
                versions.append(
                    CaptureSource(
                        match_id,
                        raw.fetched_at,
                        identifier,
                        raw.sha256,
                        sdp_transform._instant(known[0], name="fetched_at"),
                        is_new,
                    )
                )
                report.stats_fetched += 1
                report.payloads_new += int(is_new)
        finally:
            con.close()
    finally:
        report.requests = sdp.request_count
        if owned:
            sdp.close()
    report.failures = tuple(failures)
    report.source_versions = tuple(versions)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture current-season Premier League SDP data.")
    parser.add_argument("--season", default=None, help="defaults to sources.current_season")
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=None,
        help="only fetch stats for matches kicking off within this many days",
    )
    parser.add_argument(
        "--limit-matches", type=int, default=None, help="cap new completed-match stats fetches"
    )
    parser.add_argument(
        "--refresh-stats",
        action="store_true",
        default=None,
        help="refetch completed-match stats so provider restatements can be retained",
    )
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--recheck-required-history",
        action="store_true",
        help="also revisit incomplete last-five club matches outside the lookback",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        report = capture(
            season=args.season,
            db_path=args.db,
            lookback_days=args.lookback_days,
            limit_matches=args.limit_matches,
            refresh_stats=args.refresh_stats,
            recheck_required_history=args.recheck_required_history,
        )
    except EgressBlockedError as error:
        logger.error("%s", error)
        return 3
    except KeyError as error:
        logger.error("%s", error)
        return 2
    except ValueError as error:
        logger.error("%s", error)
        return 2

    logger.info(
        "season=%s matches=%d completed=%d already=%d fetched=%d new_payloads=%d requests=%d",
        report.season,
        report.matches_seen,
        report.completed,
        report.already_captured,
        report.stats_fetched,
        report.payloads_new,
        report.requests,
    )
    for failure in report.failures:
        logger.warning("capture gap %s", failure)
    return 1 if report.failures else 0


if __name__ == "__main__":
    sys.exit(main())
