"""Live API client and snapshot job, tested entirely offline.

Every test here runs against a local stub server or a vendored payload. None touches the
network: a test that needs egress is a test that fails in CI for reasons unrelated to the
code, and R5 is the one job that must be provably correct before it ever runs for real.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import httpx
import pytest
import yaml

from fpl.config import LiveApiSource, config_dir, load_sources
from fpl.ingest.fpl_api import (
    ApiFixture,
    ApiResponseError,
    BootstrapStatic,
    EgressBlockedError,
    FplApiClient,
    assert_same_season,
    detect_season_skew,
)
from fpl.ingest.stub_server import StubFplApi, StubRoute
from fpl.jobs import daily_snapshot, verify_rules

FAST_CONFIG = LiveApiSource(
    base_url="http://127.0.0.1:1",
    endpoints={"bootstrap_static": "bootstrap-static/", "fixtures": "fixtures/"},
    # Keep the throttle measurable but the suite quick.
    min_request_interval_seconds=0.05,
    timeout_seconds=5.0,
    max_retries=2,
    retry_backoff_base_seconds=0.01,
)


# --------------------------------------------------------------------------------------
# Response models
# --------------------------------------------------------------------------------------


def test_bootstrap_model_parses_the_vendored_payload(bootstrap_payload_path: Path) -> None:
    payload = json.loads(bootstrap_payload_path.read_text("utf-8"))
    bootstrap = BootstrapStatic.model_validate(payload)
    assert len(bootstrap.teams) == 20
    assert len(bootstrap.events) == 38
    assert bootstrap.elements

    # Every element maps to a real position, and codes are the stable identity.
    for element in bootstrap.elements:
        assert element.element_type in {1, 2, 3, 4, 5}
        assert element.code > 0


def test_bootstrap_model_ignores_unknown_fields() -> None:
    """FPL adds and removes fields between seasons; a new one must not break a snapshot."""
    bootstrap = BootstrapStatic.model_validate(
        {"teams": [], "events": [], "elements": [], "some_new_2027_field": {"a": 1}}
    )
    assert bootstrap.teams == []


def test_element_model_tolerates_placeholder_nulls() -> None:
    """`"None"` as a string appears in mirrored payloads; it must not abort a capture."""
    bootstrap = BootstrapStatic.model_validate(
        {
            "elements": [
                {
                    "id": 1,
                    "code": 123,
                    "web_name": "X",
                    "element_type": 3,
                    "team": 1,
                    "news_added": "None",
                    "status": "",
                }
            ]
        }
    )
    assert bootstrap.elements[0].news_added is None
    assert bootstrap.elements[0].status is None


def test_gw1_deadline_matches_the_specification(bootstrap_payload_path: Path) -> None:
    bootstrap = BootstrapStatic.model_validate(json.loads(bootstrap_payload_path.read_text()))
    first = min(e.deadline_time for e in bootstrap.events if e.deadline_time)
    assert first == datetime(2026, 8, 21, 17, 30, tzinfo=UTC)


def test_next_event_is_identified(bootstrap_payload_path: Path) -> None:
    bootstrap = BootstrapStatic.model_validate(json.loads(bootstrap_payload_path.read_text()))
    event = bootstrap.next_event()
    assert event is not None and event.id == 1


def test_scoring_block_is_extracted(bootstrap_payload_path: Path) -> None:
    bootstrap = BootstrapStatic.model_validate(json.loads(bootstrap_payload_path.read_text()))
    scoring = bootstrap.scoring_block()
    assert scoring, "no scoring block found"
    assert "goals_scored" in scoring


def test_scoring_block_falls_back_to_flat_game_settings() -> None:
    """Older payloads carried the constants as flat `scoring_*` keys on game_settings."""
    bootstrap = BootstrapStatic.model_validate(
        {"game_settings": {"scoring_assists": 3, "scoring_long_play": 2, "squad_squadsize": 15}}
    )
    scoring = bootstrap.scoring_block()
    assert scoring == {"assists": 3, "long_play": 2}


# --------------------------------------------------------------------------------------
# Gotcha 14: season skew between fixtures and bootstrap-static
# --------------------------------------------------------------------------------------


def test_season_skew_is_detected(bootstrap_payload_path: Path, fixtures_payload_path: Path) -> None:
    """The real 2026-07-26 state: bootstrap on 2026/27, fixtures still on 2025-26.

    Team ids are reassigned every season, so joining across this boundary attributes matches
    to the wrong clubs -- silently, because the ids are all valid.
    """
    bootstrap = BootstrapStatic.model_validate(json.loads(bootstrap_payload_path.read_text()))
    fixtures = [
        ApiFixture.model_validate(item) for item in json.loads(fixtures_payload_path.read_text())
    ]
    skew = detect_season_skew(bootstrap, fixtures)
    assert not skew.is_consistent
    assert "previous season" in skew.detail
    assert skew.fixtures_all_finished
    assert skew.fixtures_first_kickoff is not None
    assert skew.bootstrap_first_deadline is not None
    assert skew.fixtures_first_kickoff < skew.bootstrap_first_deadline


def test_joining_across_a_season_boundary_is_refused(
    bootstrap_payload_path: Path, fixtures_payload_path: Path
) -> None:
    bootstrap = BootstrapStatic.model_validate(json.loads(bootstrap_payload_path.read_text()))
    fixtures = [
        ApiFixture.model_validate(item) for item in json.loads(fixtures_payload_path.read_text())
    ]
    with pytest.raises(ApiResponseError, match="season skew"):
        assert_same_season(bootstrap, fixtures)


def test_consistent_season_passes_the_guard() -> None:
    bootstrap = BootstrapStatic.model_validate(
        {"events": [{"id": 1, "name": "GW1", "deadline_time": "2026-08-21T17:30:00Z"}]}
    )
    fixtures = [
        ApiFixture.model_validate(
            {"id": 1, "team_h": 1, "team_a": 2, "kickoff_time": "2026-08-22T14:00:00Z"}
        )
    ]
    assert detect_season_skew(bootstrap, fixtures).is_consistent
    assert_same_season(bootstrap, fixtures)  # must not raise


# --------------------------------------------------------------------------------------
# Client behaviour: throttling, retries, and blocked egress
# --------------------------------------------------------------------------------------


def test_client_fetches_from_a_stub(
    bootstrap_payload_path: Path, fixtures_payload_path: Path
) -> None:
    with (
        StubFplApi.from_fixtures(
            bootstrap_path=bootstrap_payload_path, fixtures_path=fixtures_payload_path
        ) as stub,
        FplApiClient(base_url=stub.base_url, config=FAST_CONFIG) as client,
    ):
        bootstrap = client.bootstrap_static()
        fixtures = client.fixtures()
    assert len(bootstrap.teams) == 20
    assert len(fixtures) == 380


def test_client_retries_transient_failures() -> None:
    """Two 503s then success, within `max_retries`."""
    route = StubRoute(body={"events": [], "teams": [], "elements": []}, fail_times=2)
    with (
        StubFplApi({"/bootstrap-static": route}) as stub,
        FplApiClient(base_url=stub.base_url, config=FAST_CONFIG) as client,
    ):
        client.bootstrap_static()
    assert route.served == 3


def test_client_gives_up_after_max_retries() -> None:
    route = StubRoute(body={}, fail_times=99)
    with (
        StubFplApi({"/bootstrap-static": route}) as stub,
        FplApiClient(base_url=stub.base_url, config=FAST_CONFIG) as client,
    ):
        with pytest.raises(ApiResponseError):
            client.bootstrap_static()
    assert route.served == FAST_CONFIG.max_retries + 1


@pytest.mark.parametrize("status", [403, 407])
def test_proxy_denial_raises_egress_blocked_and_does_not_retry(status: int) -> None:
    """403/407 is a policy denial, not a server error. Retrying hides the real cause."""
    route = StubRoute(body={}, status=status)
    with (
        StubFplApi({"/bootstrap-static": route}) as stub,
        FplApiClient(base_url=stub.base_url, config=FAST_CONFIG) as client,
    ):
        with pytest.raises(EgressBlockedError, match="egress blocked"):
            client.bootstrap_static()
    assert route.served == 1, "a policy denial must not be retried"


def test_client_does_not_retry_client_errors() -> None:
    route = StubRoute(body={}, status=404)
    with (
        StubFplApi({"/bootstrap-static": route}) as stub,
        FplApiClient(base_url=stub.base_url, config=FAST_CONFIG) as client,
    ):
        with pytest.raises(ApiResponseError, match="404"):
            client.bootstrap_static()
    assert route.served == 1


def test_proxy_error_is_reported_as_blocked_egress() -> None:
    """A transport-level proxy refusal is the same diagnosis as an HTTP 403."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ProxyError("CONNECT tunnel failed, response 403")

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as http:
        client = FplApiClient(base_url="https://example.invalid", config=FAST_CONFIG, client=http)
        with pytest.raises(EgressBlockedError, match="egress blocked"):
            client.bootstrap_static()


def test_rate_limit_is_enforced_between_requests() -> None:
    """Roughly 1 req/sec in production; the interval is honoured, whatever it is set to."""
    route = StubRoute(body={"events": [], "teams": [], "elements": []})
    interval = 0.25
    config = FAST_CONFIG.model_copy(update={"min_request_interval_seconds": interval})
    import time

    with (
        StubFplApi({"/bootstrap-static": route}) as stub,
        FplApiClient(base_url=stub.base_url, config=config) as client,
    ):
        started = time.monotonic()
        for _ in range(3):
            client.bootstrap_static()
        elapsed = time.monotonic() - started
    # Three requests means at least two enforced gaps.
    assert elapsed >= 2 * interval, f"took only {elapsed:.3f}s; throttle not applied"


def test_production_config_is_polite() -> None:
    live = load_sources().live_api
    assert live.min_request_interval_seconds >= 1.0
    assert live.max_retries >= 3
    assert live.retry_backoff_base_seconds >= 2.0


def test_invalid_json_is_reported() -> None:
    class BadRoute(StubRoute):
        def next_response(self) -> tuple[int, bytes]:
            return 200, b"<html>not json</html>"

    with (
        StubFplApi({"/bootstrap-static": BadRoute()}) as stub,
        FplApiClient(base_url=stub.base_url, config=FAST_CONFIG) as client,
    ):
        with pytest.raises(ApiResponseError, match="invalid JSON"):
            client.bootstrap_static()


# --------------------------------------------------------------------------------------
# The snapshot job
# --------------------------------------------------------------------------------------


def test_dry_run_exercises_the_full_path_with_no_network() -> None:
    """`--dry-run` must be a real exercise, not a mock: stub server, parse, write."""
    assert daily_snapshot.run(dry_run=True) == daily_snapshot.EXIT_OK


def test_dry_run_writes_nothing_to_the_real_database(tmp_path: Path) -> None:
    """A dry run must be provably non-destructive, so it writes to an in-memory database."""
    target = tmp_path / "should_not_appear.duckdb"
    assert daily_snapshot.run(dry_run=True, db_path=target) == daily_snapshot.EXIT_OK
    assert not target.exists()


def test_snapshot_writes_an_immutable_timestamped_row(
    tmp_path: Path, bootstrap_payload_path: Path, fixtures_payload_path: Path
) -> None:
    db_path = tmp_path / "snap.duckdb"
    sources = load_sources()
    with StubFplApi.from_fixtures(
        bootstrap_path=bootstrap_payload_path,
        fixtures_path=fixtures_payload_path,
        bootstrap_route="/" + sources.live_api.endpoints["bootstrap_static"].rstrip("/"),
        fixtures_route="/" + sources.live_api.endpoints["fixtures"].rstrip("/"),
    ) as stub:
        assert daily_snapshot.run(db_path=db_path, base_url=stub.base_url) == daily_snapshot.EXIT_OK

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = con.execute(
            "SELECT endpoint, gw, sha256, length(payload) FROM snapshot_bootstrap ORDER BY endpoint"
        ).fetchall()
        assert [row[0] for row in rows] == ["bootstrap-static", "event-live/1", "fixtures"]
        for endpoint, gw, sha, size in rows:
            assert gw == 1  # from the payload's is_next event
            assert len(sha) == 64
            assert size > (10 if endpoint.startswith("event-live") else 1000)
        # A single captured_at ties the endpoints into one capture.
        stamps = con.execute(
            "SELECT count(DISTINCT captured_at) FROM snapshot_bootstrap"
        ).fetchone()
        assert stamps is not None and stamps[0] == 1
    finally:
        con.close()


def test_snapshot_is_append_only_across_runs(
    tmp_path: Path, bootstrap_payload_path: Path, fixtures_payload_path: Path
) -> None:
    """R5: the table only ever grows. A missed week is unrecoverable, so nothing is replaced."""
    db_path = tmp_path / "snap.duckdb"
    sources = load_sources()
    with StubFplApi.from_fixtures(
        bootstrap_path=bootstrap_payload_path,
        fixtures_path=fixtures_payload_path,
        bootstrap_route="/" + sources.live_api.endpoints["bootstrap_static"].rstrip("/"),
        fixtures_route="/" + sources.live_api.endpoints["fixtures"].rstrip("/"),
    ) as stub:
        for _ in range(2):
            assert (
                daily_snapshot.run(db_path=db_path, base_url=stub.base_url)
                == daily_snapshot.EXIT_OK
            )

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        total = con.execute("SELECT count(*) FROM snapshot_bootstrap").fetchone()
        assert total is not None and total[0] == 6
    finally:
        con.close()


def test_blocked_egress_exits_non_zero_and_writes_nothing(tmp_path: Path) -> None:
    """Fail loud. A partial or empty snapshot is worse than none, because it looks like data."""
    db_path = tmp_path / "snap.duckdb"
    route = StubRoute(body={}, status=403)
    with StubFplApi({"/bootstrap-static": route}) as stub:
        code = daily_snapshot.run(db_path=db_path, base_url=stub.base_url)
    assert code == daily_snapshot.EXIT_EGRESS_BLOCKED
    assert not db_path.exists(), "no database should be created when the capture failed"


def test_partial_failure_writes_no_snapshot(tmp_path: Path, bootstrap_payload_path: Path) -> None:
    """bootstrap-static succeeds, fixtures 500s -- the whole capture is abandoned."""
    db_path = tmp_path / "snap.duckdb"
    sources = load_sources()
    routes = {
        "/" + sources.live_api.endpoints["bootstrap_static"].rstrip("/"): StubRoute(
            body=json.loads(bootstrap_payload_path.read_text("utf-8"))
        ),
        "/" + sources.live_api.endpoints["fixtures"].rstrip("/"): StubRoute(body=[], fail_times=99),
    }
    with StubFplApi(routes) as stub:
        code = daily_snapshot.run(db_path=db_path, base_url=stub.base_url)
    assert code == daily_snapshot.EXIT_API_ERROR
    assert not db_path.exists()


def test_rollover_signal_logs_the_first_kickoff(
    caplog: pytest.LogCaptureFixture, bootstrap_payload_path: Path, fixtures_payload_path: Path
) -> None:
    """The snapshot history must pin the exact day the fixtures endpoint rolls over."""
    captured = [
        daily_snapshot._capture(
            "bootstrap-static", json.loads(bootstrap_payload_path.read_text("utf-8"))
        ),
        daily_snapshot._capture("fixtures", json.loads(fixtures_payload_path.read_text("utf-8"))),
    ]
    with caplog.at_level("INFO", logger="fpl.daily_snapshot"):
        first_kickoff = daily_snapshot.log_rollover_signal(captured)
    assert first_kickoff == "2025-08-15T19:00:00Z"
    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "2025-08-15T19:00:00Z" in messages
    assert "STALE" in messages


# --------------------------------------------------------------------------------------
# Rules verification
# --------------------------------------------------------------------------------------


def test_verify_rules_resolves_every_field(bootstrap_payload_path: Path) -> None:
    code, checks = verify_rules.verify("2026_27", bootstrap_payload_path, write=False)
    assert code == verify_rules.EXIT_OK
    unconfirmed = [check.path for check in checks if check.status == "unconfirmed"]
    assert unconfirmed == [], f"could not locate: {unconfirmed}"
    assert not [check for check in checks if check.status == "MISMATCH"]


def test_verify_rules_refuses_to_rewrite_from_a_placeholder(
    bootstrap_payload_path: Path,
) -> None:
    """The vendored payload is synthetic, so nothing may be marked confirmed from it."""
    payload = json.loads(bootstrap_payload_path.read_text("utf-8"))
    assert "_PLACEHOLDER" in payload

    path = config_dir() / "scoring_2026_27.yaml"
    before = path.read_bytes()
    code, _ = verify_rules.verify("2026_27", bootstrap_payload_path, write=True)
    assert code == verify_rules.EXIT_OK
    assert path.read_bytes() == before


def test_real_2026_27_scoring_extract_has_no_false_map_mismatches() -> None:
    payload = Path(__file__).parent / "fixtures" / "bootstrap_scoring_2026_27_real.json"
    code, checks = verify_rules.verify("2026_27", payload, write=False)
    assert code == verify_rules.EXIT_OK
    assert not [check for check in checks if check.status == "MISMATCH"]
    unconfirmed = {check.path for check in checks if check.status == "unconfirmed"}
    assert unconfirmed == {
        "appearance.long_play_minutes",
        "clean_sheets.minimum_minutes",
        "goals_conceded.unit",
        "saves.unit",
        "defensive_contribution.thresholds.DEF",
        "defensive_contribution.thresholds.MID",
        "defensive_contribution.thresholds.FWD",
    }
    from fpl.config import load_scoring_rules

    verification = load_scoring_rules("2026_27").verification
    expected_confirmed = {
        check.path
        for check in checks
        if check.status == "confirmed"
        and check.path not in {"goals_scored.GK", "clean_sheets.points.FWD"}
    }
    assert set(verification.payload_confirmed) == expected_confirmed
    assert verification.payload_sha256 == verify_rules._canonical_text_sha256(payload)


def test_payload_rewrite_preserves_authoritatively_resolved_omissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refreshing bootstrap evidence must not reopen fields resolved from official rules."""
    config_path = config_dir() / "scoring_2026_27.yaml"
    temporary_config = tmp_path / config_path.name
    temporary_config.write_bytes(config_path.read_bytes())
    payload = Path(__file__).parent / "fixtures" / "bootstrap_scoring_2026_27_real.json"
    omitted = [
        "appearance.long_play_minutes",
        "clean_sheets.minimum_minutes",
        "goals_conceded.unit",
        "saves.unit",
        "defensive_contribution.thresholds.DEF",
        "defensive_contribution.thresholds.MID",
        "defensive_contribution.thresholds.FWD",
    ]
    unconfirmed = [
        verify_rules.FieldCheck(path=path, expected=None, observed=None, matched_key=None)
        for path in omitted
    ]

    monkeypatch.setattr(verify_rules, "config_dir", lambda: tmp_path)
    verify_rules._rewrite_verification("2026_27", payload, [], unconfirmed)

    rewritten = yaml.safe_load(temporary_config.read_text("utf-8"))
    assert set(rewritten["verification"]["unverified"]) == {
        "goals_scored.GK",
        "clean_sheets.points.FWD",
    }


def test_verify_rules_reports_a_mismatch_and_does_not_write(tmp_path: Path) -> None:
    """An upstream rule change needs a human decision, never a silent config overwrite."""
    payload = {
        "game_config": {
            "scoring": {
                "long_play": 2,
                "short_play": 1,
                "long_play_limit": 60,
                "assists": 4,  # FPL "changed" the assist value
                "goals_scored": {"1": 10, "2": 6, "3": 5, "4": 4},
            }
        }
    }
    path = tmp_path / "changed.json"
    path.write_text(json.dumps(payload), "utf-8")

    code, checks = verify_rules.verify("2026_27", path, write=True)
    assert code == verify_rules.EXIT_MISMATCH
    assert any(check.path == "assists" and check.status == "MISMATCH" for check in checks)
    # The config still says 3.
    from fpl.config import load_scoring_rules

    load_scoring_rules.cache_clear()
    assert load_scoring_rules("2026_27").assists == 3


def test_verify_rules_handles_the_flat_legacy_layout(tmp_path: Path) -> None:
    """Key layout has moved between releases; the tool must not depend on one shape."""
    payload = {
        "game_settings": {
            "scoring_long_play": 2,
            "scoring_short_play": 1,
            "scoring_long_play_limit": 60,
            "scoring_assists": 3,
            "scoring_yellow_cards": -1,
        }
    }
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(payload), "utf-8")
    code, checks = verify_rules.verify("2026_27", path, write=False)
    assert code == verify_rules.EXIT_OK
    resolved = {check.path: check.status for check in checks}
    assert resolved["assists"] == "confirmed"
    assert resolved["yellow_cards"] == "confirmed"
    # Fields absent from this minimal payload are unconfirmed, never guessed.
    assert resolved["saves.unit"] == "unconfirmed"
