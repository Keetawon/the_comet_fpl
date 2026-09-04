"""The SDP client: schema tolerance where it is safe, loud failure where it is not.

Every test is offline. The client's `base_url` is injectable and `httpx.MockTransport` serves
the vendored payload shapes in `tests/fixtures/pl_sdp/`, so no test reaches the network -- which
is also the only way these could run at all, since the provider is unreachable from CI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from fpl.config import load_sdp_metrics, load_sources
from fpl.ingest.fpl_api import ApiResponseError, EgressBlockedError
from fpl.ingest.pl_sdp import (
    PlSdpClient,
    SdpSchemaError,
    extract_items,
    parse_match_summary,
    parse_team_stats,
)

FIXTURES = Path(__file__).parent / "fixtures" / "pl_sdp"


def _fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _client(handler: Any, **overrides: Any) -> PlSdpClient:
    """A client whose transport is a local handler and whose throttle is disabled."""
    config = load_sources().pl_sdp
    assert config is not None
    config = config.model_copy(update={"min_request_interval_seconds": 0.0, **overrides})
    return PlSdpClient(
        base_url="https://sdp.test",
        config=config,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


# -- envelope tolerance ----------------------------------------------------------------


def test_paged_envelope_and_bare_list_yield_the_same_records() -> None:
    """The same information in two renderings must parse identically.

    The provider's envelope shape is undocumented, so the parser is written against several
    plausible shapes rather than one assumed one.
    """
    paged = [parse_match_summary(record) for record in extract_items(_fixture("matches_page"))]
    bare = [parse_match_summary(record) for record in extract_items(_fixture("matches_bare_list"))]
    assert paged[0].match_id == bare[0].match_id == 116001
    assert paged[0].home_team_name == bare[0].home_team_name == "Arsenal"
    assert paged[0].home_score == bare[0].home_score == 2
    assert paged[0].kickoff == bare[0].kickoff


def test_epoch_millis_and_iso_kickoffs_agree() -> None:
    """A kickoff sent as epoch millis and as ISO text must land on the same instant."""
    paged = parse_match_summary(extract_items(_fixture("matches_page"))[0])
    bare = parse_match_summary(extract_items(_fixture("matches_bare_list"))[0])
    assert paged.kickoff == bare.kickoff
    assert paged.kickoff is not None
    assert paged.kickoff.tzinfo is not None, "a naive kickoff would defeat the as_of boundary"


def test_unknown_envelope_raises_rather_than_returning_empty() -> None:
    """'No matches' and 'the envelope changed' must not look the same.

    The first is a fact worth recording; the second is a bug worth failing on. Returning an
    empty list for both would let a provider redesign look like a quiet season.
    """
    with pytest.raises(SdpSchemaError, match="no recognised list container"):
        extract_items(_fixture("matches_unknown_envelope"))


def test_match_record_without_an_id_is_refused() -> None:
    with pytest.raises(SdpSchemaError, match="no integer id"):
        parse_match_summary({"matchweek": 3, "homeTeam": {"id": 1}})


# -- stats payloads --------------------------------------------------------------------


def test_object_and_list_stat_shapes_parse_identically() -> None:
    object_form = parse_team_stats(_fixture("match_stats"), match_id=116001)
    list_form = parse_team_stats(_fixture("match_stats_list_form"), match_id=116002)
    assert [side.side for side in object_form] == ["home", "away"]
    assert [side.side for side in list_form] == ["home", "away"]
    assert object_form[0].stats["goals"] == 2
    assert list_form[0].stats["goals"] == 3
    assert list_form[0].stats["expected_goals"] == 2.41


def test_one_sided_stats_payload_is_refused() -> None:
    """A partial capture must not become a team-match fact with no opponent mirror."""
    with pytest.raises(SdpSchemaError, match=r"expected exactly.*away.*home"):
        parse_team_stats(_fixture("match_stats_one_sided"), match_id=116001)


def test_duplicate_stat_names_with_conflicting_values_fail_closed() -> None:
    """Letting the last one win would make a wrong number a permanent record."""
    payload = [
        {"side": "Home", "stats": [{"name": "goals", "value": 2}, {"name": "goals", "value": 3}]},
        {"side": "Away", "stats": [{"name": "goals", "value": 1}]},
    ]
    with pytest.raises(SdpSchemaError, match="appears twice with different values"):
        parse_team_stats(payload, match_id=1)


def test_unknown_provider_fields_survive_parsing() -> None:
    """An unmapped field must reach the caller so the tall store can retain it."""
    sides = parse_team_stats(_fixture("match_stats_unknown_fields"), match_id=116001)
    assert sides[0].stats["brand_new_upstream_metric"] == 42
    assert "brand_new_upstream_metric" not in load_sdp_metrics().alias_index()


def test_unrecognised_side_label_is_refused() -> None:
    payload = [{"side": "Neutral", "stats": {"goals": 1}}]
    with pytest.raises(SdpSchemaError, match="unrecognised side label"):
        parse_team_stats(payload, match_id=1)


# -- transport behaviour ---------------------------------------------------------------


def test_raw_payload_records_bytes_hash_and_request_identity() -> None:
    """Raw bytes are the record; the parse is a convenience."""
    body = json.dumps(_fixture("match_stats"))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    with _client(handler) as client:
        raw = client.fetch_match_stats(116001)
    assert raw.text == body
    assert raw.byte_count == len(body.encode("utf-8"))
    assert raw.sha256 == __import__("hashlib").sha256(body.encode("utf-8")).hexdigest()
    assert json.loads(raw.params_json()) == {"match_id": "116001"}
    assert raw.fetched_at.tzinfo is not None


def test_429_is_retried_and_retry_after_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr("fpl.ingest.pl_sdp.time.sleep", slept.append)
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(429, headers={"Retry-After": "7"}, text="slow down")
        return httpx.Response(200, text=json.dumps(_fixture("match_stats")))

    with _client(handler) as client:
        raw = client.fetch_match_stats(1)
    assert attempts["count"] == 2
    assert 7.0 in slept, "the provider's Retry-After must be honoured, not overridden"
    assert raw.status_code == 200


def test_retry_after_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hostile or buggy header must not stall a backfill indefinitely."""
    slept: list[float] = []
    monkeypatch.setattr("fpl.ingest.pl_sdp.time.sleep", slept.append)
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(429, headers={"Retry-After": "999999"}, text="no")
        return httpx.Response(200, text=json.dumps(_fixture("match_stats")))

    with _client(handler) as client:
        client.fetch_match_stats(1)
    assert max(slept) <= 120.0


def test_5xx_is_retried_then_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fpl.ingest.pl_sdp.time.sleep", lambda _: None)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    with _client(handler, max_retries=2) as client, pytest.raises(ApiResponseError, match="503"):
        client.fetch_match_stats(1)


def test_4xx_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retrying a 404 wastes the provider's capacity and hides the real cause."""
    monkeypatch.setattr("fpl.ingest.pl_sdp.time.sleep", lambda _: None)
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(404, text="not found")

    with _client(handler) as client, pytest.raises(ApiResponseError, match="404"):
        client.fetch_match_stats(1)
    assert attempts["count"] == 1


def test_policy_denial_is_distinguished_from_a_server_error() -> None:
    """403/407 mean 'this host is refused', which no amount of retrying fixes."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    with _client(handler) as client, pytest.raises(EgressBlockedError, match="policy denial"):
        client.fetch_match_stats(1)


def test_implausibly_small_body_is_a_failure_not_empty_data() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="[]")

    with _client(handler) as client, pytest.raises(ApiResponseError, match="byte floor"):
        client.fetch_match_stats(1)


def test_invalid_json_is_reported_not_swallowed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>an error page that is definitely not json</html>")

    with _client(handler) as client, pytest.raises(ApiResponseError, match="invalid JSON"):
        client.fetch_match_stats(1)


# -- pagination ------------------------------------------------------------------------


def test_pagination_stops_when_a_page_adds_no_new_match() -> None:
    """An endpoint that ignores `page` returns the same records forever.

    Terminating on 'no unseen ids' rather than on 'empty page' is what stops that becoming an
    infinite backfill against someone else's website.
    """
    calls = {"count": 0}
    # Deliberately WITHOUT a declared total: this test pins the fallback termination rule,
    # which is the one that has to work when the provider declares nothing.
    payload = _fixture("matches_page")
    payload.pop("pageInfo")

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, text=json.dumps(payload))

    with _client(handler, page_size=2, maximum_pages=10) as client:
        pages = list(client.iter_matches(season_id=719))
    assert calls["count"] == 2, "one page of new ids, then one that repeats them"
    assert {summary.match_id for _, summaries in pages for summary in summaries} == {
        116001,
        116002,
    }


def test_pagination_respects_a_declared_total() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=json.dumps(_fixture("matches_page")))

    with _client(handler, page_size=2) as client:
        pages = list(client.iter_matches(season_id=719))
    # totalElements is 2 and the first page carries both, so no second request is needed.
    assert len(pages) == 1


def test_runaway_pagination_is_bounded() -> None:
    """A provider that ignores paging AND returns fresh ids must still terminate."""
    counter = {"next": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        counter["next"] += 1
        return httpx.Response(
            200,
            text=json.dumps(
                [
                    {
                        "id": 900000 + counter["next"],
                        "season": {"id": 719},
                        "kickoff": "2025-11-25T15:00:00Z",
                        "homeTeam": {"id": 1, "name": "Arsenal"},
                        "awayTeam": {"id": 4, "name": "Chelsea"},
                    }
                ]
                * 2
            ),
        )

    with _client(handler, page_size=2, maximum_pages=3) as client:
        with pytest.raises(ApiResponseError, match="did not terminate"):
            list(client.iter_matches(season_id=719))


# -- configuration refusals -------------------------------------------------------------


def test_unmapped_season_label_is_refused_rather_than_guessed() -> None:
    """Fetching the wrong year under a correct-looking label is worse than fetching nothing."""
    config = load_sources().pl_sdp
    assert config is not None
    with pytest.raises(KeyError, match="no pl_sdp season id mapped"):
        config.season_id("2025-26")
