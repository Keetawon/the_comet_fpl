"""Incremental current-season Premier League SDP capture.

    python -m fpl.jobs.capture_pl_sdp
    python -m fpl.jobs.capture_pl_sdp --season 2026-27 --lookback-days 5

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
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fpl.config import load_sources
from fpl.ingest.fpl_api import EgressBlockedError
from fpl.ingest.pl_sdp import PlSdpClient, SdpMatchSummary
from fpl.storage.db import initialise
from fpl.transform import pl_sdp as sdp_transform

logger = logging.getLogger("fpl.capture_pl_sdp")

# Status labels that mean "this match is over and its stats are final enough to capture".
# Matched case-insensitively against whatever the provider sends; an unrecognised status is
# treated as NOT complete, so an unknown vocabulary under-captures rather than storing
# in-progress numbers as if they were final.
COMPLETED_STATUSES: frozenset[str] = frozenset(
    {"c", "complete", "completed", "finished", "fulltime", "full_time", "ft", "played"}
)


@dataclass
class CaptureReport:
    season: str = ""
    matches_seen: int = 0
    completed: int = 0
    already_captured: int = 0
    stats_fetched: int = 0
    payloads_new: int = 0
    requests: int = 0
    failures: tuple[str, ...] = ()


def _is_complete(summary: SdpMatchSummary, *, now: datetime) -> bool:
    """Whether a match is finished, by status where given and by kickoff age otherwise."""
    if summary.status is not None:
        return summary.status.strip().casefold().replace(" ", "") in COMPLETED_STATUSES
    if summary.home_score is not None and summary.away_score is not None:
        return True
    if summary.kickoff is None:
        return False
    # No status and no score: a match whose kickoff is comfortably past is over. Three hours
    # covers stoppage time and a delayed restart without treating a live match as final.
    return summary.kickoff + timedelta(hours=3) <= now


def capture(
    *,
    season: str | None = None,
    db_path: Path | None = None,
    lookback_days: int | None = None,
    client: PlSdpClient | None = None,
    now: datetime | None = None,
) -> CaptureReport:
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
    try:
        con = initialise(db_path)
        try:
            captured = {
                int(row[0])
                for row in con.execute(
                    """
                    SELECT DISTINCT sdp_match_id FROM raw_pl_sdp_payload
                    WHERE endpoint = 'match_stats' AND sdp_match_id IS NOT NULL
                    """
                ).fetchall()
            }
            summaries: list[SdpMatchSummary] = []
            for raw, page in sdp.iter_matches(season_id=season_id):
                _, is_new = sdp_transform.land_payload(con, raw, season=resolved_season)
                report.payloads_new += int(is_new)
                summaries.extend(page)
            report.matches_seen = len({summary.match_id for summary in summaries})

            wanted: list[int] = []
            for summary in sorted(summaries, key=lambda item: item.match_id):
                if not _is_complete(summary, now=moment):
                    continue
                report.completed += 1
                if horizon is not None and summary.kickoff is not None:
                    if summary.kickoff < horizon:
                        continue
                if summary.match_id in captured:
                    report.already_captured += 1
                    continue
                wanted.append(summary.match_id)

            for match_id in wanted:
                try:
                    raw = sdp.fetch_match_stats(match_id)
                except EgressBlockedError:
                    raise
                except Exception as error:
                    failures.append(f"match {match_id}: {error}")
                    continue
                _, is_new = sdp_transform.land_payload(
                    con, raw, season=resolved_season, sdp_match_id=match_id
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
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        report = capture(season=args.season, db_path=args.db, lookback_days=args.lookback_days)
    except EgressBlockedError as error:
        logger.error("%s", error)
        return 3
    except KeyError as error:
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
