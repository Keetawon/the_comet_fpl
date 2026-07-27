"""R5: snapshot the live API every day, forever.

    python -m fpl.jobs.daily_snapshot            # real run
    python -m fpl.jobs.daily_snapshot --dry-run  # full code path against a local stub

The FPL API retains only the current season at per-gameweek granularity; `history_past`
gives season totals only. At season rollover the per-gameweek data is destroyed
permanently, so **missing a week is unrecoverable**. That asymmetry drives two decisions:

  * The snapshot table is append-only. Nothing here updates or deletes a prior capture.
  * A partial snapshot is worse than no snapshot, because it looks like data. Every
    endpoint must succeed or the whole capture is abandoned and the process exits
    non-zero with a diagnostic naming the cause.

`--dry-run` proves the local code path without depending on egress. The GitHub workflows
remain the durable execution path because an irreplaceable capture must not depend on a
developer machine being online.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb

from fpl.config import load_sources, repo_root
from fpl.ingest.fpl_api import (
    ApiResponseError,
    BootstrapStatic,
    EgressBlockedError,
    FplApiClient,
    detect_season_skew,
)
from fpl.ingest.live_snapshot import (
    CapturedPayload,
    capture_payload,
    write_capture,
)
from fpl.ingest.stub_server import StubFplApi
from fpl.storage.db import initialise

logger = logging.getLogger("fpl.daily_snapshot")

EXIT_OK = 0
EXIT_EGRESS_BLOCKED = 2
EXIT_API_ERROR = 3

# Vendored payloads used by --dry-run. Replaced by a real capture when one is available;
# see tests/fixtures/README.md.
_FIXTURE_DIR = repo_root() / "tests" / "fixtures"


CapturedEndpoint = CapturedPayload


def _capture(endpoint: str, payload: object, *, parameter: str = "") -> CapturedEndpoint:
    return capture_payload(endpoint, payload, parameter=parameter)


def fetch_all(
    client: FplApiClient, *, include_player_history: bool = False
) -> list[CapturedEndpoint]:
    """Fetch every endpoint the snapshot covers.

    Ordered so bootstrap-static -- the payload that carries the rules and the gameweek
    calendar -- is fetched first. If anything raises, the caller writes nothing.
    """
    bootstrap = client.raw_bootstrap_static()
    fixtures = client.raw_fixtures()
    captured = [_capture("bootstrap-static", bootstrap), _capture("fixtures", fixtures)]
    parsed = BootstrapStatic.model_validate(bootstrap)
    event = parsed.current_event() or parsed.next_event()
    if event is None:
        finished = [item for item in parsed.events if item.finished]
        event = max(finished, key=lambda item: item.id, default=None)
    if event is not None:
        captured.append(
            _capture("event-live", client.raw_event_live(event.id), parameter=str(event.id))
        )
    if include_player_history:
        for player in parsed.elements:
            if player.element_type not in {1, 2, 3, 4}:
                continue
            captured.append(
                _capture(
                    "element-summary",
                    client.raw_element_summary(player.id),
                    parameter=str(player.id),
                )
            )
    return captured


def log_rollover_signal(captured: list[CapturedEndpoint]) -> str:
    """Log the first kickoff in the fixtures payload, and whether it is stale.

    As of 2026-07-26 `/api/fixtures/` still returned the completed 2025-26 fixtures while
    bootstrap-static had rolled over to 2026/27. Recording the first kickoff on every run
    means the snapshot history pins the exact day the fixtures endpoint rolls over, rather
    than us noticing weeks later.
    """
    by_endpoint = {capture.endpoint: capture.payload for capture in captured}
    fixtures = by_endpoint.get("fixtures") or []
    bootstrap_payload = by_endpoint.get("bootstrap-static") or {}

    kickoffs = sorted(
        fixture["kickoff_time"]
        for fixture in fixtures
        if isinstance(fixture, dict) and fixture.get("kickoff_time")
    )
    first_kickoff = kickoffs[0] if kickoffs else None
    logger.info(
        "fixtures payload: %d fixture(s), first kickoff_time=%s, last=%s",
        len(fixtures),
        first_kickoff,
        kickoffs[-1] if kickoffs else None,
    )

    try:
        bootstrap = BootstrapStatic.model_validate(bootstrap_payload)
    except Exception:
        logger.warning("could not parse bootstrap-static for the skew check")
        return str(first_kickoff)

    skew = detect_season_skew(bootstrap, [])
    logger.info("bootstrap-static first deadline=%s", skew.bootstrap_first_deadline)
    if first_kickoff and skew.bootstrap_first_deadline is not None:
        stale = first_kickoff < skew.bootstrap_first_deadline.isoformat()
        logger.info(
            "fixtures endpoint appears %s relative to bootstrap-static",
            "STALE (previous season)" if stale else "rolled over to the current season",
        )
    return str(first_kickoff)


def write_snapshot(
    con: duckdb.DuckDBPyConnection, captured: list[CapturedEndpoint], *, gw: int | None
) -> int:
    """Append every captured endpoint under a single `captured_at`. All or nothing."""
    sources = load_sources()
    result = write_capture(
        con,
        captured,
        season=sources.current_season.season,
        gw=gw,
        mode=(
            "player-history" if any(c.endpoint == "element-summary" for c in captured) else "daily"
        ),
    )
    return result.payload_count


def _next_gw(captured: list[CapturedEndpoint]) -> int | None:
    for capture in captured:
        if capture.endpoint != "bootstrap-static":
            continue
        try:
            bootstrap = BootstrapStatic.model_validate(capture.payload)
        except Exception:
            return None
        event = bootstrap.next_event() or bootstrap.current_event()
        return event.id if event else None
    return None


def run(
    *,
    db_path: Path | None = None,
    dry_run: bool = False,
    base_url: str | None = None,
    include_player_history: bool = False,
) -> int:
    """Capture a snapshot. Returns a process exit code."""
    sources = load_sources()

    if dry_run:
        bootstrap_fixture = _FIXTURE_DIR / "bootstrap_static_sample.json"
        fixtures_fixture = _FIXTURE_DIR / "fixtures_sample.json"
        missing = [path for path in (bootstrap_fixture, fixtures_fixture) if not path.is_file()]
        if missing:
            logger.error("missing vendored payload(s): %s", ", ".join(str(p) for p in missing))
            return EXIT_API_ERROR
        logger.info("dry run: serving vendored payloads from a local stub server")
        with StubFplApi.from_fixtures(
            bootstrap_path=bootstrap_fixture,
            fixtures_path=fixtures_fixture,
            bootstrap_route="/" + sources.live_api.endpoints["bootstrap_static"].rstrip("/"),
            fixtures_route="/" + sources.live_api.endpoints["fixtures"].rstrip("/"),
            event_live_route="/"
            + sources.live_api.endpoints["event_live"].format(gw=1).rstrip("/"),
        ) as stub:
            # A dry run must not touch the real database: it writes to an in-memory one so
            # the full write path is still exercised.
            return _capture_and_write(
                base_url=stub.base_url,
                db_path=":memory:",
                label="dry-run",
                include_player_history=False,
            )

    return _capture_and_write(
        base_url=base_url,
        db_path=db_path,
        label="snapshot",
        include_player_history=include_player_history,
    )


def _capture_and_write(
    *,
    base_url: str | None,
    db_path: Path | str | None,
    label: str,
    include_player_history: bool,
) -> int:
    try:
        with FplApiClient(base_url=base_url) as client:
            captured = fetch_all(client, include_player_history=include_player_history)
    except EgressBlockedError as error:
        # Deliberately loud and specific. A silent empty snapshot would be indistinguishable
        # from a day on which nothing happened, and R5 data cannot be recovered later.
        logger.error("EGRESS BLOCKED -- no snapshot written. %s", error)
        logger.error(
            "R5 requires a daily capture and this data is unrecoverable once the season "
            "rolls over. Run this job where fantasy.premierleague.com is reachable, or rely "
            "on .github/workflows/snapshot.yml, which is the durable execution path."
        )
        return EXIT_EGRESS_BLOCKED
    except ApiResponseError as error:
        logger.error("API error -- no snapshot written. %s", error)
        return EXIT_API_ERROR

    if not captured:
        logger.error("no endpoints captured -- refusing to write an empty snapshot")
        return EXIT_API_ERROR

    log_rollover_signal(captured)
    gw = _next_gw(captured)

    con = initialise(db_path)
    try:
        written = write_snapshot(con, captured, gw=gw)
        total = con.execute("SELECT count(*) FROM snapshot_bootstrap").fetchone()
    finally:
        con.close()
    logger.info(
        "%s: wrote %d endpoint(s) for gw=%s; snapshot table now holds %s row(s)",
        label,
        written,
        gw,
        total[0] if total else "?",
    )
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture a daily FPL API snapshot (R5).")
    parser.add_argument("--db", type=Path, default=None, help="database path")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="exercise the full code path against a local stub server; writes to an "
        "in-memory database and requires no network",
    )
    parser.add_argument(
        "--base-url", default=None, help="override the API base URL (for a local mirror)"
    )
    parser.add_argument(
        "--player-history",
        action="store_true",
        help="also capture every element-summary payload; run after a gameweek finalises",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return run(
        db_path=args.db,
        dry_run=args.dry_run,
        base_url=args.base_url,
        include_player_history=args.player_history,
    )


if __name__ == "__main__":
    sys.exit(main())
