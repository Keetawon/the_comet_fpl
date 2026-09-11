"""Historical Premier League SDP backfill.

    python -m fpl.jobs.backfill_pl_sdp --season 2024-25
    python -m fpl.jobs.backfill_pl_sdp --all-seasons
    python -m fpl.jobs.backfill_pl_sdp --season 2026-27 --limit-matches 2
    python -m fpl.jobs.backfill_pl_sdp --season 2026-27 --refresh-stats

Requires network egress to the provider. Every host in the Pulselive / premierleague.com /
fantasy.premierleague.com family is refused by some sandboxes' egress policy, in which case
this exits with a diagnostic naming the block rather than a generic timeout -- run it where
the provider is reachable and commit the resulting database or raw export.

Landing is append-only and content-addressed, so re-running is cheap and safe: an unchanged
payload is recognised and not stored twice, while a provider restatement lands beside the
original rather than replacing it.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fpl.config import load_sources
from fpl.ingest.fpl_api import EgressBlockedError
from fpl.ingest.pl_sdp import PlSdpClient, SdpMatchSummary, is_completed_scored_match
from fpl.storage.db import initialise
from fpl.transform import pl_sdp as sdp_transform

logger = logging.getLogger("fpl.backfill_pl_sdp")


@dataclass
class BackfillReport:
    seasons: tuple[str, ...] = ()
    match_pages: int = 0
    matches_seen: int = 0
    stats_fetched: int = 0
    stats_skipped: int = 0
    payloads_new: int = 0
    payloads_duplicate: int = 0
    requests: int = 0
    stats_failures: tuple[str, ...] = ()


def backfill(
    *,
    seasons: list[str],
    db_path: Path | None = None,
    fetch_stats: bool = True,
    client: PlSdpClient | None = None,
    limit_matches: int | None = None,
    refresh_stats: bool = False,
) -> BackfillReport:
    """Fetch a season's matches, then optionally each match's team stats."""
    if limit_matches is not None and limit_matches <= 0:
        raise ValueError("limit_matches must be positive")
    sources = load_sources()
    if sources.pl_sdp is None:
        raise RuntimeError("config/sources.yaml carries no `pl_sdp` block")

    owned = client is None
    sdp = client or PlSdpClient(config=sources.pl_sdp)
    report = BackfillReport(seasons=tuple(seasons))
    failures: list[str] = []
    moment = datetime.now(UTC)
    try:
        con = initialise(db_path)
        try:
            for season in seasons:
                # Refuses rather than guesses: an unmapped label would otherwise ingest an
                # arbitrary season's matches under the wrong name.
                season_id = sources.pl_sdp.season_id(season)
                logger.info("season %s -> provider season id %d", season, season_id)
                matches: list[SdpMatchSummary] = []
                for raw, summaries in sdp.iter_matches(season_id=season_id):
                    _, is_new = sdp_transform.land_payload(con, raw, season=season)
                    report.match_pages += 1
                    report.payloads_new += int(is_new)
                    report.payloads_duplicate += int(not is_new)
                    matches.extend(summaries)
                unique_ids = sorted({summary.match_id for summary in matches})
                report.matches_seen += len(unique_ids)
                logger.info("season %s: %d matches", season, len(unique_ids))

                if not fetch_stats:
                    continue
                completed_ids = sorted(
                    {
                        summary.match_id
                        for summary in matches
                        if is_completed_scored_match(summary, now=moment)
                    }
                )
                retained_ids = (
                    set()
                    if refresh_stats
                    else sdp_transform.retained_complete_stats_ids(con, season=season)
                )
                report.stats_skipped += len(set(completed_ids) & retained_ids)
                pending_ids = [
                    match_id for match_id in completed_ids if match_id not in retained_ids
                ]
                selected = pending_ids[:limit_matches] if limit_matches else pending_ids
                for index, match_id in enumerate(selected, start=1):
                    try:
                        raw = sdp.fetch_match_stats(match_id)
                    except EgressBlockedError:
                        raise
                    except Exception as error:
                        # One unavailable match must not abandon a season's backfill; the
                        # coverage report is where a gap becomes visible.
                        failures.append(f"{season} match {match_id}: {error}")
                        continue
                    _, is_new = sdp_transform.land_payload(
                        con, raw, season=season, sdp_match_id=match_id
                    )
                    report.stats_fetched += 1
                    report.payloads_new += int(is_new)
                    report.payloads_duplicate += int(not is_new)
                    if index % 25 == 0:
                        logger.info("  %s: %d/%d stats", season, index, len(selected))
        finally:
            con.close()
    finally:
        report.requests = sdp.request_count
        if owned:
            sdp.close()
    report.stats_failures = tuple(failures)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill Premier League SDP match data.")
    parser.add_argument("--season", action="append", default=None, help="season label, repeatable")
    parser.add_argument("--all-seasons", action="store_true", help="every configured season id")
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--no-stats", action="store_true", help="fetch match lists only")
    parser.add_argument(
        "--limit-matches", type=int, default=None, help="cap stats fetches per season (smoke runs)"
    )
    parser.add_argument(
        "--refresh-stats",
        action="store_true",
        help="refetch completed-match stats so provider restatements can be retained",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    sources = load_sources()
    if sources.pl_sdp is None:
        logger.error("config/sources.yaml carries no `pl_sdp` block")
        return 2
    seasons = sorted(sources.pl_sdp.season_ids) if args.all_seasons else list(args.season or [])
    if not seasons:
        logger.error(
            "no seasons selected. Pass --season, or record `pl_sdp.season_ids` in "
            "config/sources.yaml (see `python -m fpl.jobs.audit_pl_sdp --probe`) and use "
            "--all-seasons."
        )
        return 2

    try:
        report = backfill(
            seasons=seasons,
            db_path=args.db,
            fetch_stats=not args.no_stats,
            limit_matches=args.limit_matches,
            refresh_stats=args.refresh_stats,
        )
    except EgressBlockedError as error:
        logger.error("%s", error)
        logger.error(
            "the provider is unreachable from this environment. Run this job where "
            "premierleague.com is reachable; nothing was written."
        )
        return 3
    except (KeyError, ValueError) as error:
        logger.error("%s", error)
        return 2

    logger.info(
        "seasons=%s matches=%d stats=%d skipped=%d payloads new=%d duplicate=%d requests=%d",
        ",".join(report.seasons),
        report.matches_seen,
        report.stats_fetched,
        report.stats_skipped,
        report.payloads_new,
        report.payloads_duplicate,
        report.requests,
    )
    for failure in report.stats_failures:
        logger.warning("stats gap %s", failure)
    return 0


if __name__ == "__main__":
    sys.exit(main())
