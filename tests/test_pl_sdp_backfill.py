"""Offline coverage for resumable Premier League SDP backfills."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from fpl.config import load_sources
from fpl.ingest.pl_sdp import PlSdpClient
from fpl.jobs.backfill_pl_sdp import BackfillReport, backfill


def test_backfill_limit_applies_after_retained_stats_are_skipped(tmp_path: Path) -> None:
    matches = {
        "pagination": {"_limit": 2, "_prev": None, "_next": None},
        "data": [
            {
                "matchId": "2645195",
                "season": "2026",
                "matchWeek": 1,
                "kickoff": "2026-08-21 20:00:00",
                "resultType": "NormalResult",
                "homeTeam": {"id": "3", "name": "Arsenal", "score": 3},
                "awayTeam": {"id": "9", "name": "Coventry City", "score": 0},
            },
            {
                "matchId": "2645198",
                "season": "2026",
                "matchWeek": 1,
                "kickoff": "2026-08-22 12:30:00",
                "resultType": "NormalResult",
                "homeTeam": {"id": "7", "name": "Burnley", "score": 1},
                "awayTeam": {"id": "14", "name": "Sunderland", "score": 2},
            },
        ],
    }
    stats = [
        {"side": "Home", "teamId": "3", "stats": {"goals": 3, "totalScoringAtt": 12}},
        {"side": "Away", "teamId": "9", "stats": {"goals": 0, "totalScoringAtt": 7}},
    ]
    fetched_stats: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/matches":
            return httpx.Response(200, text=json.dumps(matches))
        match_id = int(request.url.path.split("/")[-2])
        fetched_stats.append(match_id)
        return httpx.Response(200, text=json.dumps(stats))

    config = load_sources().pl_sdp
    assert config is not None
    config = config.model_copy(update={"min_request_interval_seconds": 0.0})
    database = tmp_path / "fpl.duckdb"

    def run_once() -> BackfillReport:
        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            client = PlSdpClient(base_url="https://sdp.test", config=config, client=http)
            return backfill(seasons=["2026-27"], db_path=database, client=client, limit_matches=1)

    first = run_once()
    assert fetched_stats == [2645195]
    assert (first.stats_fetched, first.stats_skipped) == (1, 0)

    second = run_once()
    assert fetched_stats == [2645195, 2645198]
    assert (second.stats_fetched, second.stats_skipped) == (1, 1)

    third = run_once()
    assert fetched_stats == [2645195, 2645198]
    assert (third.stats_fetched, third.stats_skipped) == (0, 2)


def test_backfill_retries_a_retained_but_incomplete_stats_body(tmp_path: Path) -> None:
    matches = {
        "pagination": {"_limit": 1, "_prev": None, "_next": None},
        "data": [
            {
                "matchId": "2645195",
                "season": "2026",
                "matchWeek": 1,
                "kickoff": "2026-08-21 20:00:00",
                "resultType": "NormalResult",
                "homeTeam": {"id": "3", "name": "Arsenal", "score": 3},
                "awayTeam": {"id": "9", "name": "Coventry City", "score": 0},
            }
        ],
    }
    incomplete = [
        {"side": "Home", "teamId": "3", "stats": {"totalScoringAtt": 12}},
        {"side": "Away", "stats": {"totalScoringAtt": 7}},
    ]
    complete = [
        {"side": "Home", "teamId": "3", "stats": {"totalScoringAtt": 12}},
        {"side": "Away", "teamId": "9", "stats": {"totalScoringAtt": 7}},
    ]
    stats_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal stats_requests
        if request.url.path == "/api/v2/matches":
            return httpx.Response(200, text=json.dumps(matches))
        stats_requests += 1
        body = incomplete if stats_requests == 1 else complete
        return httpx.Response(200, text=json.dumps(body))

    config = load_sources().pl_sdp
    assert config is not None
    config = config.model_copy(update={"min_request_interval_seconds": 0.0})
    database = tmp_path / "fpl.duckdb"

    def run_once(*, refresh_stats: bool = False) -> BackfillReport:
        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            client = PlSdpClient(base_url="https://sdp.test", config=config, client=http)
            return backfill(
                seasons=["2026-27"],
                db_path=database,
                client=client,
                refresh_stats=refresh_stats,
            )

    first = run_once()
    second = run_once()
    third = run_once()
    refreshed = run_once(refresh_stats=True)

    assert (first.stats_fetched, first.stats_skipped) == (1, 0)
    assert (second.stats_fetched, second.stats_skipped) == (1, 0)
    assert (third.stats_fetched, third.stats_skipped) == (0, 1)
    assert (refreshed.stats_fetched, refreshed.stats_skipped) == (1, 0)
    assert stats_requests == 3
