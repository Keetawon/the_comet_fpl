"""Offline news capture contracts; no evaluation outcomes or external API calls."""

from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from fpl.ingest.public_news import (
    MAX_RESPONSE_BYTES,
    OPENAI_MODEL,
    PROMPT_SHA256,
    CaptureError,
    NewsCaptureConfig,
    XSource,
    capture_fpl_snapshot,
    run_capture,
    summarize_observation,
)
from fpl.jobs.capture_public_news import main
from fpl.storage.public_news import NewsStore, SourceObservation, canonical

NOW = datetime(2026, 9, 19, 12, tzinfo=UTC)
SUMMARY = {
    "title_en": "Manager hopes for a return",
    "title_th": "ผู้จัดการหวังว่านักเตะจะกลับมา",
    "summary_en": "The manager hopes the player returns next week; no return was confirmed.",
    "summary_th": "ผู้จัดการหวังว่านักเตะจะกลับมาสัปดาห์หน้า แต่ยังไม่ได้ยืนยัน",
    "category": "injury",
    "has_substantive_update": True,
}


def source(**values: Any) -> XSource:
    return XSource(
        source_id="club", name="Club", handle="ClubOfficial", reuse_approved=True, **values
    )


def config(**values: Any) -> NewsCaptureConfig:
    return NewsCaptureConfig(enabled=True, x_sources=[source()], **values)


def observation(
    text: str = "A", when: datetime = NOW, record_id: str = "100"
) -> tuple[SourceObservation, bytes]:
    raw = canonical({"text": text, "id": record_id})
    return SourceObservation(
        source_id="club",
        source_name="Club",
        source_record_id=record_id,
        source_url=f"https://x.com/ClubOfficial/status/{record_id}",
        source_published_at=NOW - timedelta(days=1),
        captured_at=when,
        known_at=when,
        content_sha256=hashlib.sha256(raw).hexdigest(),
        text=text,
        source_kind="x",
        active=bool(text),
    ), raw


def x_response(*, data: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    posts = (
        data
        if data is not None
        else [
            {
                "id": "100",
                "text": "Manager hopes to have him back.",
                "created_at": "2026-09-18T09:00:00Z",
            }
        ]
    )
    return {"data": posts, "meta": {"result_count": len(posts)}}


def ai_response() -> dict[str, Any]:
    return {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": json.dumps(SUMMARY)}],
            }
        ],
    }


def fpl_snapshot(
    path: Path,
    *,
    news: str | None = "Knock - being assessed",
    captured: datetime = NOW,
    code: int = 10,
) -> Path:
    path.mkdir()
    payload = {
        "teams": [{"id": 1, "code": 99, "name": "Club"}],
        "elements": [
            {
                "id": 9,
                "code": code,
                "element_type": 3,
                "team": 1,
                "web_name": "Exact player",
                "news": news,
                "news_added": "2026-09-17T12:00:00Z",
                "scout_news_link": "http://127.0.0.1/private-not-fetched",
            },
            {"element_type": 5},
        ],
    }
    raw = gzip.compress(canonical(payload), mtime=0)
    (path / "bootstrap-static.json.gz").write_bytes(raw)
    (path / "SHA256SUMS").write_text(
        hashlib.sha256(raw).hexdigest() + "  bootstrap-static.json.gz\n", encoding="utf-8"
    )
    (path / "manifest.json").write_text(
        json.dumps({"season": "2026-27", "captured_at": captured.isoformat()})
    )
    return path


def test_no_keys_disabled_or_unapproved_never_network(tmp_path: Path) -> None:
    calls: list[str] = []
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: calls.append(str(request.url)))
    ) as client:  # type: ignore[arg-type, return-value]
        store = NewsStore(tmp_path / "news.sqlite")
        assert (
            run_capture(
                NewsCaptureConfig(x_sources=[source()]),
                store,
                client=client,
                env={},
                clock=lambda: NOW,
            )[0].status
            == "disabled"
        )
        assert (
            run_capture(config(), store, client=client, env={}, clock=lambda: NOW)[0].status
            == "missing_key"
        )
        unapproved = NewsCaptureConfig(
            enabled=True, x_sources=[XSource(source_id="club", name="Club", handle="ClubOfficial")]
        )
        assert (
            run_capture(
                unapproved,
                store,
                client=client,
                env={"X_BEARER_TOKEN": "secret"},
                clock=lambda: NOW,
            )[0].status
            == "unapproved"
        )
        assert calls == []


def test_x_incremental_ids_summary_cache_and_secret_boundary(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert "secret" not in str(request.url)
        return httpx.Response(
            200, json=x_response() if request.url.host == "api.x.com" else ai_response()
        )

    store = NewsStore(tmp_path / "news.sqlite")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        for day in (0, 1):
            states = run_capture(
                config(),
                store,
                client=client,
                env={"X_BEARER_TOKEN": "x-secret", "OPENAI_API_KEY": "ai-secret"},
                clock=lambda day=day: NOW + timedelta(days=day),
            )
            assert states[0].status == "ok"
            assert states[0].summary_status == "ok"
    assert [r.url.host for r in requests] == ["api.x.com", "api.openai.com", "api.x.com"]
    assert [r.extensions["timeout"]["read"] for r in requests] == [5.0, 20.0, 5.0]
    assert requests[2].url.params["since_id"] == "100"
    assert "expansions" not in requests[0].url.params
    body = json.loads(requests[1].content)
    assert body["store"] is False
    assert body["model"] == OPENAI_MODEL
    assert "tools" not in body
    assert body["text"]["format"]["strict"] is True
    assert body["text"]["format"]["schema"]["additionalProperties"] is False
    schema = body["text"]["format"]["schema"]
    assert set(schema["required"]) == set(schema["properties"])
    assert all("default" not in prop for prop in schema["properties"].values())
    assert store.recent_observations()[0].known_at == NOW
    assert store.recent_observations()[0].player_code is None
    assert b"x-secret" not in store.path.read_bytes()
    assert b"ai-secret" not in store.path.read_bytes()


def test_summary_retry_uses_remaining_shared_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    elapsed = 0.0
    read_timeouts: list[float] = []
    monkeypatch.setattr("fpl.ingest.public_news.time.monotonic", lambda: elapsed)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal elapsed
        read_timeouts.append(request.extensions["timeout"]["read"])
        if len(read_timeouts) == 1:
            elapsed = 21.0
            raise httpx.ReadTimeout("synthetic delayed generation")
        return httpx.Response(200, json=ai_response())

    store = NewsStore(tmp_path / "news.sqlite")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = summarize_observation(
            observation()[0],
            store,
            config(),
            client,
            key="secret",
            clock=lambda: NOW,
            sleep=lambda _: None,
        )
    assert result.summary.title_en == SUMMARY["title_en"]
    assert read_timeouts == [20.0, 9.0]
    with closing(sqlite3.connect(store.path)) as db:
        costs = db.execute("SELECT microusd FROM reservations WHERE provider='openai'").fetchall()
    assert len(costs) == 2 and costs[0] == costs[1]


@pytest.mark.parametrize("handle", ["FFScout", "Account12345678"])
def test_team_news_profile_is_bounded_private_and_preserves_fpl(
    tmp_path: Path, handle: str
) -> None:
    store = NewsStore(tmp_path / "news.sqlite")
    fpl_status = capture_fpl_snapshot(
        fpl_snapshot(tmp_path / "fpl"), store, season="2026-27", clock=lambda: NOW
    )
    fpl_rows = store.recent_observations(source_id="fpl")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.x.com"
        requests.append(request)
        return httpx.Response(200, json=x_response())

    original_source = {
        "source_id": "ffscout",
        "name": "Fantasy Football Scout",
        "handle": handle,
        "team_code": None,
        "team_name": None,
        "season": None,
        "reuse_approved": True,
    }
    scoped_source = {
        **original_source,
        "source_id": "ffscout_team_news_v1",
        "topic": "team_news",
    }
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        for settings in (original_source, scoped_source):
            statuses = run_capture(
                NewsCaptureConfig(
                    enabled=True,
                    summarize=False,
                    x_sources=[XSource.model_validate(settings)],
                    x_max_results=10,
                    x_monthly_budget_usd=0.10,
                    openai_monthly_budget_usd=0,
                ),
                store,
                client=client,
                env={"X_BEARER_TOKEN": "x-test", "OPENAI_API_KEY": "ai-test"},
                clock=lambda: NOW,
            )
            assert len(statuses) == 1
            assert statuses[0].status == "ok"
            assert statuses[0].summary_status == "disabled"
            assert statuses[0].summarized == 0
    assert len(requests) == 2
    base_query = f"from:{handle} -is:retweet -is:reply"
    assert requests[0].url.params["query"] == base_query
    query = requests[1].url.params["query"]
    assert query.startswith(base_query + " (") and query.endswith(")")
    assert query.count("from:") == 1
    assert len(query) <= 512
    for term in (
        '"team news"',
        '"press conference"',
        "injury",
        "training",
        "suspension",
        '"starting XI"',
        "lineup",
        "rotation",
        "transfer",
        "signing",
    ):
        assert term in query
    assert all(request.url.params["max_results"] == "10" for request in requests)
    assert "since_id" not in requests[1].url.params
    with closing(sqlite3.connect(store.path)) as db:
        for settings in (original_source, scoped_source):
            row = db.execute(
                "SELECT raw FROM observations WHERE source_id=?", (settings["source_id"],)
            ).fetchone()
            assert row and row[0] == canonical(
                {"post": x_response()["data"][0], "source": settings}
            )
        assert db.execute("SELECT COUNT(*) FROM summaries").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM observations WHERE source_id='fpl'").fetchone()[
            0
        ] == len(fpl_rows)
    assert store.reserved_microusd("openai", "2026-09") == 0
    assert store.reserved_microusd("x", "2026-09") == 100_000
    assert store.recent_observations(source_id="fpl") == fpl_rows
    assert (
        next(state for state in store.latest_statuses() if state.source_id == "fpl") == fpl_status
    )


def test_unsupported_x_topic_is_rejected() -> None:
    with pytest.raises(ValidationError, match="topic"):
        XSource.model_validate(
            {
                "source_id": "ffscout_team_news_v1",
                "name": "Scout",
                "handle": "FFScout",
                "topic": "injury OR from:any",
            }
        )


def test_append_only_aba_missing_and_cutoff(tmp_path: Path) -> None:
    store = NewsStore(tmp_path / "news.sqlite")
    first = store.append(*observation())
    unchanged = store.append(*observation(when=NOW + timedelta(hours=1)))
    assert first == unchanged
    second = store.append(*observation("B", NOW + timedelta(hours=2)))
    third = store.append(*observation("A", NOW + timedelta(hours=3)))
    assert third.content_sha256 == first.content_sha256
    assert third.version_id != first.version_id
    assert store.recent_observations(as_of=NOW + timedelta(hours=2))[0] == second
    assert store.recent_observations(as_of=NOW)[0] == first
    assert store.recent_observations(as_of=NOW - timedelta(seconds=1)) == []
    with closing(sqlite3.connect(store.path)) as db:
        assert db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 3
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("DELETE FROM observations")
    readonly = NewsStore(store.path, read_only=True)
    assert readonly.recent_observations() == store.recent_observations()
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        readonly.append(*observation("C", NOW + timedelta(hours=4)))
    store.path.rename(tmp_path / "closed-connections.sqlite")


def test_atomic_capture_and_hash_guard(tmp_path: Path) -> None:
    store = NewsStore(tmp_path / "news.sqlite")
    with pytest.raises(ValueError, match="hash mismatch"):
        store.append_batch([observation(record_id="1"), (observation(record_id="2")[0], b"bad")])
    assert store.recent_observations() == []
    earlier = observation()[0].model_copy(update={"known_at": NOW - timedelta(days=1)})
    with pytest.raises(ValueError, match="actual capture"):
        store.append(earlier, observation()[1])


def test_budget_reserved_before_call_and_retry_persists(tmp_path: Path) -> None:
    store = NewsStore(tmp_path / "news.sqlite")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert store.reserved_microusd("x", "2026-09") == 50000
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        status = run_capture(
            config(x_monthly_budget_usd=0.05),
            store,
            client=client,
            env={"X_BEARER_TOKEN": "secret"},
            clock=lambda: NOW,
            sleep=lambda _: None,
        )[0]
        assert status.status == "budget_exhausted"
        assert len(calls) == 1
        reopened = NewsStore(store.path)
        run_capture(
            config(x_monthly_budget_usd=0.05),
            reopened,
            client=client,
            env={"X_BEARER_TOKEN": "secret"},
            clock=lambda: NOW,
        )
        assert len(calls) == 1
    assert store.reserve("x", 50000, cap_microusd=50000, now=NOW + timedelta(days=30))


@pytest.mark.parametrize(
    "response",
    [
        {
            "data": [{"id": "100", "text": "A", "created_at": "2026-09-18T09:00:00Z"}],
            "meta": {"result_count": 2},
        },
        {"data": [], "meta": {"result_count": 0}, "errors": [{"detail": "secret"}]},
        x_response(data=[{"id": "100", "text": "A", "created_at": "2026-09-20T09:00:00Z"}]),
    ],
)
def test_malformed_x_is_safe_status_and_keeps_previous(tmp_path: Path, response: object) -> None:
    store = NewsStore(tmp_path / "news.sqlite")
    previous = store.append(*observation())
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response))
    ) as client:
        status = run_capture(
            config(), store, client=client, env={"X_BEARER_TOKEN": "secret"}, clock=lambda: NOW
        )[0]
    assert status.status == "error"
    assert "secret" not in status.model_dump_json()
    assert store.recent_observations() == [previous]


@pytest.mark.parametrize("bad", ["refusal", "tool", "incomplete", "extra", "oversize"])
def test_openai_rejects_invalid_and_refusal_outputs(tmp_path: Path, bad: str) -> None:
    reply = ai_response()
    if bad == "refusal":
        reply["output"][0]["content"].append({"type": "refusal", "refusal": "No"})
    elif bad == "tool":
        reply["output"].append({"type": "function_call"})
    elif bad == "incomplete":
        reply["status"] = "incomplete"
    elif bad == "extra":
        reply["output"][0]["content"][0]["text"] = json.dumps({**SUMMARY, "xp": 5})
    store = NewsStore(tmp_path / "news.sqlite")
    response = (
        httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1))
        if bad == "oversize"
        else httpx.Response(200, json=reply)
    )
    with httpx.Client(transport=httpx.MockTransport(lambda _: response)) as client:
        with pytest.raises(CaptureError):
            summarize_observation(
                observation()[0], store, config(), client, key="secret", clock=lambda: NOW
            )
    assert store.latest_summary(observation()[0].content_sha256, as_of=NOW) is None


def test_fpl_retained_identity_tombstone_and_independent_gpt(tmp_path: Path) -> None:
    store = NewsStore(tmp_path / "news.sqlite")
    captured = NOW - timedelta(hours=1)
    capture_fpl_snapshot(
        fpl_snapshot(tmp_path / "first", captured=captured),
        store,
        season="2026-27",
        clock=lambda: NOW,
    )
    row = store.recent_observations()[0]
    assert row.player_code == 10
    assert row.team_code == 99
    assert row.known_at == captured
    assert row.source_published_at == NOW - timedelta(days=2)
    assert row.source_snapshot_id is not None
    assert row.source_url == "https://fantasy.premierleague.com/"
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=ai_response()))
    ) as client:
        result = run_capture(
            NewsCaptureConfig(enabled=True),
            store,
            client=client,
            env={"OPENAI_API_KEY": "secret"},
            clock=lambda: NOW,
        )
        assert result[-1].source_id == "fpl"
        assert result[-1].summary_status == "ok"
    assert store.last_successes(as_of=NOW)["fpl"] == captured
    capture_fpl_snapshot(
        fpl_snapshot(tmp_path / "clear", news=""), store, season="2026-27", clock=lambda: NOW
    )
    assert store.recent_observations()[0].active is False
    assert store.recent_observations(as_of=captured)[0].active is True
    summary = store.summary_for(row.content_sha256, OPENAI_MODEL, PROMPT_SHA256)
    assert summary and summary.summary.summary_th


def test_fpl_missing_is_not_tombstone_and_checksum_rejected(tmp_path: Path) -> None:
    store = NewsStore(tmp_path / "news.sqlite")
    with pytest.raises(ValueError, match="absent"):
        capture_fpl_snapshot(
            fpl_snapshot(tmp_path / "missing", news=None),
            store,
            season="2026-27",
            clock=lambda: NOW,
        )
    snapshot = fpl_snapshot(tmp_path / "broken")
    (snapshot / "bootstrap-static.json.gz").write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum mismatch"):
        capture_fpl_snapshot(snapshot, store, season="2026-27", clock=lambda: NOW)
    assert store.recent_observations() == []


@pytest.mark.parametrize(
    "changes",
    [
        {"source_id": "fpl"},
        {"handle": "bad) OR from:any"},
        {"team_code": 1},
        {"reuse_approved": "yes"},
    ],
)
def test_config_trust_boundary(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        XSource.model_validate({"source_id": "club", "name": "Club", "handle": "Club", **changes})


def test_cli_disabled_receipt_write_once_and_private_store(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("enabled: false\n")
    args = [
        "--config",
        str(config_path),
        "--store",
        str(tmp_path / "news.sqlite"),
        "--output",
        str(tmp_path / "receipt.json"),
    ]
    assert main(args) == 0
    assert json.loads((tmp_path / "receipt.json").read_text())["sources"][0]["status"] == "disabled"
    with pytest.raises(SystemExit):
        main(args)
    with pytest.raises(SystemExit):
        main(
            [
                "--config",
                str(config_path),
                "--store",
                str(tmp_path / "public" / "news.sqlite"),
                "--output",
                str(tmp_path / "private.json"),
            ]
        )


def test_source_filtered_before_summary_limit(tmp_path: Path) -> None:
    store = NewsStore(tmp_path / "news.sqlite")
    original = store.append(*observation("The manager hopes he returns next week."))
    unrelated = []
    for number in range(201):
        row, raw = observation(when=NOW + timedelta(hours=1), record_id=str(number + 1000))
        unrelated.append((row.model_copy(update={"source_id": "unrelated"}), raw))
    store.append_batch(unrelated)
    assert all(row.source_id == "unrelated" for row in store.recent_observations(limit=200))
    assert store.recent_observations(limit=200, source_id="club") == [original]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.x.com":
            return httpx.Response(200, json=x_response(data=[]))
        return httpx.Response(200, json=ai_response())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = run_capture(
            config(),
            store,
            client=client,
            env={"X_BEARER_TOKEN": "secret", "OPENAI_API_KEY": "secret"},
            clock=lambda: NOW + timedelta(hours=2),
        )
    assert result[0].summarized == 1
    assert store.latest_summary(original.content_sha256, as_of=NOW + timedelta(hours=2))


def test_withdrawn_approval_blocks_calls_even_when_disabled(tmp_path: Path) -> None:
    store = NewsStore(tmp_path / "news.sqlite")
    store.append(*observation())
    withdrawn = NewsCaptureConfig(x_sources=[source().model_copy(update={"reuse_approved": False})])

    def no_request(_: httpx.Request) -> httpx.Response:
        pytest.fail("withdrawn source must not make a provider request")

    with httpx.Client(transport=httpx.MockTransport(no_request)) as client:
        result = run_capture(
            withdrawn,
            store,
            client=client,
            env={"X_BEARER_TOKEN": "secret", "OPENAI_API_KEY": "secret"},
            clock=lambda: NOW,
        )
    assert result[0].status == "unapproved"
    assert result[0].summary_status == "disabled"
    assert store.latest_statuses(as_of=NOW)[0].status == "unapproved"


def test_capture_status_time_is_completion_not_request_start(tmp_path: Path) -> None:
    store = NewsStore(tmp_path / "news.sqlite")
    stamps = iter(NOW + timedelta(seconds=n) for n in range(4))
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=x_response()))
    ) as client:
        result = run_capture(
            config(),
            store,
            client=client,
            env={"X_BEARER_TOKEN": "secret"},
            clock=lambda: next(stamps),
        )
    assert result[0].source_checked_at == NOW + timedelta(seconds=2)
    assert result[0].checked_at == NOW + timedelta(seconds=3)
    assert store.latest_statuses(as_of=NOW) == []
    assert store.recent_observations(as_of=NOW) == []


def test_same_raw_cannot_relabel_player_or_club(tmp_path: Path) -> None:
    store = NewsStore(tmp_path / "news.sqlite")
    row, raw = observation()
    store.append(row, raw)
    with pytest.raises(ValueError, match="conflicting news metadata"):
        store.append(row.model_copy(update={"team_code": 999}), raw)


def test_cli_never_echoes_misplaced_credential(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = tmp_path / "bad.yaml"
    settings.write_text("enabled: false\napi_key: DO-NOT-LOG-THIS-KEY\n")
    with pytest.raises(SystemExit):
        main(
            [
                "--config",
                str(settings),
                "--store",
                str(tmp_path / "news.sqlite"),
                "--output",
                str(tmp_path / "receipt.json"),
            ]
        )
    captured = capsys.readouterr()
    assert "DO-NOT-LOG-THIS-KEY" not in captured.err + captured.out
