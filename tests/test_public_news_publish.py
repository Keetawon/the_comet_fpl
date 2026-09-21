"""Public news trust boundary, separate from forecast/owner-note publication."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fpl.publish.public_news import empty_news_feed, export_news_feed, validate_news_feed
from fpl.storage.public_news import (
    BilingualSummary,
    CaptureStatus,
    NewsStore,
    SourceObservation,
    SummaryRecord,
)

AS_OF = datetime(2026, 9, 19, 12, tzinfo=UTC)


def example() -> dict:
    feed = empty_news_feed(as_of=AS_OF)
    feed["sources"][0].update(
        status="ok", last_checked_at=AS_OF.isoformat(), last_success_at=AS_OF.isoformat()
    )
    feed["stories"] = [
        {
            "id": "a" * 64,
            "source_id": "news",
            "source_name": "News collection",
            "source_kind": "fpl",
            "source_url": "https://fantasy.premierleague.com/",
            "source_record_id": "2026-27:123",
            "published_at": None,
            "known_at": "2026-09-19T11:00:00Z",
            "source_sha256": "b" * 64,
            "season": "2026-27",
            "team_code": 3,
            "team_name": "Example Club",
            "player_code": 123,
            "player_name": "Example Player",
            "category": "other",
            "title": {"en": "Example FPL update", "th": None},
            "summary": {"en": "Synthetic test: awaiting a training update.", "th": None},
            "rendering": "source_text",
            "ai_model": None,
            "summarized_at": None,
        }
    ]
    return feed


def test_missing_store_is_not_created(tmp_path: Path) -> None:
    path = tmp_path / "missing.sqlite3"
    first = export_news_feed(path, as_of=AS_OF)
    assert first == export_news_feed(path, as_of=AS_OF)
    assert not path.exists()
    assert first["stories"] == []
    assert first["sources"][0]["status"] == "not_configured"


def test_original_news_has_no_fabricated_translation_or_forecast() -> None:
    feed = example()
    validate_news_feed(feed)
    assert feed["stories"][0]["summary"]["th"] is None
    assert "xp" not in feed["stories"][0]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("known_at", "2026-09-20T00:00:00Z"),
        ("published_at", "2026-09-19T11:30:00Z"),
        ("source_sha256", "invalid"),
        ("source_id", "unlisted"),
        ("player_code", True),
        ("player_code", None),
        ("team_code", None),
        ("xp", 4.5),
        ("manager_id", 123),
        ("source_url", "http://example.com/news"),
        ("source_url", "https://localhost/news"),
        ("source_url", "https://127.0.0.1/news"),
        ("source_url", "https://10.0.0.1/news"),
        ("source_url", "https://user:password@example.com/news"),
        ("source_url", "https://example.com:8765/news"),
        ("source_url", "https://example.com/news?api_key=private"),
        ("source_url", "https://example.com/news?manager_id=123"),
        ("source_url", "https://example.com/news#private"),
    ],
)
def test_invalid_public_evidence_rejected(field: str, value: object) -> None:
    feed = example()
    feed["stories"][0][field] = value
    with pytest.raises(ValueError, match="validation error"):
        validate_news_feed(feed)


def test_duplicate_logical_record_rejected_even_with_different_version() -> None:
    feed = example()
    second = deepcopy(feed["stories"][0])
    second["id"] = "c" * 64
    feed["stories"].append(second)
    with pytest.raises(ValueError, match="duplicate"):
        validate_news_feed(feed)


def test_ai_requires_translation_and_provenance() -> None:
    feed = example()
    story = feed["stories"][0]
    story.update(
        rendering="ai_summary",
        ai_model="gpt-4o-mini-2024-07-18",
        summarized_at="2026-09-19T11:15:00Z",
    )
    with pytest.raises(ValueError, match="both languages"):
        validate_news_feed(feed)
    story["title"]["th"] = "ข่าวตัวอย่าง"
    story["summary"]["th"] = "ข้อมูลจำลองสำหรับทดสอบเท่านั้น"
    validate_news_feed(feed)


def test_x_names_never_resolve_to_a_player_code() -> None:
    feed = example()
    feed["sources"][0]["source_kind"] = "x"
    feed["stories"][0].update(source_kind="x", source_url="https://x.com/example/status/123")
    with pytest.raises(ValueError, match="identity resolution"):
        validate_news_feed(feed)


def test_source_article_may_be_club_link_but_still_fpl_origin() -> None:
    feed = example()
    feed["stories"][0]["source_url"] = "https://www.arsenal.com/news/example"
    validate_news_feed(feed)
    assert feed["stories"][0]["source_kind"] == "fpl"


def observe(store: NewsStore, text: str, hour: int) -> SourceObservation:
    raw = json.dumps({"text": text}, sort_keys=True).encode()
    stamp = AS_OF.replace(hour=hour)
    return store.append(
        SourceObservation(
            source_id="fpl",
            source_name="Official FPL",
            source_kind="fpl",
            source_record_id="2026-27:123",
            source_url="https://fantasy.premierleague.com/",
            source_published_at=None,
            captured_at=stamp,
            known_at=stamp,
            content_sha256=hashlib.sha256(raw).hexdigest(),
            text=text,
            team_code=3,
            team_name="Example club",
            player_code=123,
            player_name="Example player",
            season="2026-27",
            active=bool(text),
        ),
        raw,
    )


def test_retained_export_is_read_only_and_future_invariant(tmp_path: Path) -> None:
    path = tmp_path / "news.sqlite3"
    store = NewsStore(path)
    observe(store, "Synthetic source A", 10)
    store.record_status(
        CaptureStatus(
            source_id="fpl",
            source_name="Official FPL",
            source_kind="fpl",
            checked_at=AS_OF.replace(hour=10),
            status="ok",
            reason="retained FPL update",
            summary_status="missing_key",
        )
    )
    before = path.read_bytes()
    first = export_news_feed(path, as_of=AS_OF.replace(hour=11))
    assert path.read_bytes() == before
    assert first["stories"][0]["summary"] == {"en": "Synthetic source A", "th": None}
    observe(store, "Synthetic source B", 12)
    assert export_news_feed(path, as_of=AS_OF.replace(hour=11)) == first
    assert (
        export_news_feed(path, as_of=AS_OF)["stories"][0]["summary"]["en"] == "Synthetic source B"
    )


def test_cleared_news_is_tombstone_not_zero_or_stale_article(tmp_path: Path) -> None:
    path = tmp_path / "news.sqlite3"
    store = NewsStore(path)
    observe(store, "Synthetic source A", 10)
    observe(store, "", 11)
    assert export_news_feed(path, as_of=AS_OF)["stories"] == []
    assert len(export_news_feed(path, as_of=AS_OF.replace(hour=10))["stories"]) == 1


def test_aba_reuses_summary_without_inventing_new_generation_time(tmp_path: Path) -> None:
    path = tmp_path / "news.sqlite3"
    store = NewsStore(path)
    first = observe(store, "Synthetic source A", 9)
    store.save_summary(
        SummaryRecord(
            content_sha256=first.content_sha256,
            model="gpt-4o-mini-2024-07-18",
            prompt_sha256="c" * 64,
            summarized_at=AS_OF.replace(hour=10),
            summary=BilingualSummary(
                title_en="Synthetic A",
                title_th="ตัวอย่าง A",
                summary_en="Synthetic summary A",
                summary_th="สรุปตัวอย่าง A",
                category="other",
            ),
        )
    )
    observe(store, "Synthetic source B", 11)
    latest = observe(store, "Synthetic source A", 12)
    result = export_news_feed(path, as_of=AS_OF)["stories"][0]
    assert result["id"] == latest.version_id != first.version_id
    assert result["known_at"] == AS_OF.isoformat()
    assert result["summarized_at"] == AS_OF.replace(hour=10).isoformat()
    assert result["summary"]["th"] == "สรุปตัวอย่าง A"


def test_corrupt_optional_store_does_not_leak_error_details(tmp_path: Path) -> None:
    path = tmp_path / "private.sqlite3"
    path.write_text("secret-not-a-database")
    result = export_news_feed(path, as_of=AS_OF)
    assert result["stories"] == []
    assert result["sources"][0]["status"] == "error"
    assert "private.sqlite3" not in str(result) and "secret" not in str(result)


def test_unsafe_source_text_is_not_exported_or_allowed_to_block_core(tmp_path: Path) -> None:
    path = tmp_path / "news.sqlite3"
    observe(NewsStore(path), "Unexpected contact: private@example.com", 10)
    result = export_news_feed(path, as_of=AS_OF)
    assert result["stories"] == []
    assert result["sources"][0]["status"] == "error"
    assert "private@example.com" not in str(result)


@pytest.mark.parametrize("substantive", [True, False, None])
def test_withdrawn_x_permission_hides_retained_digest(
    tmp_path: Path, substantive: bool | None
) -> None:
    path = tmp_path / "news.sqlite3"
    store = NewsStore(path)
    original = observe(store, "Synthetic source", 9)
    raw = json.dumps({"text": "Synthetic X"}).encode()
    post = original.model_copy(
        update={
            "source_id": "club",
            "source_name": "Example club",
            "source_kind": "x",
            "source_url": "https://x.com/example/status/123",
            "source_record_id": "123",
            "player_code": None,
            "player_name": None,
            "text": "Synthetic X",
            "content_sha256": hashlib.sha256(raw).hexdigest(),
        }
    )
    store.append(post, raw)
    record = SummaryRecord(
        content_sha256=post.content_sha256,
        model="gpt-4o-mini-2024-07-18",
        prompt_sha256="c" * 64,
        summarized_at=AS_OF.replace(hour=10),
        summary=BilingualSummary(
            title_en="Example",
            title_th="ตัวอย่าง",
            summary_en="Synthetic digest",
            summary_th="ข่าวสมมติ",
            category="other",
            has_substantive_update=bool(substantive),
        ),
    )
    if substantive is None:
        # Simulate the pre-review contract's immutable serialized record.
        legacy = record.model_dump(mode="json")
        del legacy["summary"]["has_substantive_update"]
        with sqlite3.connect(path) as db:
            db.execute(
                "INSERT INTO summaries VALUES(?,?,?,?)",
                (record.content_sha256, record.model, record.prompt_sha256, json.dumps(legacy)),
            )
    else:
        store.save_summary(record)
    # A raw observation alone does not establish publication permission.
    assert all(s["source_kind"] != "x" for s in export_news_feed(path, as_of=AS_OF)["stories"])
    state = CaptureStatus(
        source_id="club",
        source_name="Example club",
        source_kind="x",
        checked_at=AS_OF.replace(hour=10),
        status="ok",
        reason="approved selected source",
        summary_status="ok",
    )
    store.record_status(state)
    earlier = export_news_feed(path, as_of=AS_OF.replace(hour=10))
    assert any(s["source_kind"] == "x" for s in earlier["stories"]) is bool(substantive)
    store.record_status(
        state.model_copy(
            update={
                "checked_at": AS_OF.replace(hour=11),
                "status": "unapproved",
                "reason": "source reuse approval withdrawn",
            }
        )
    )
    assert all(s["source_kind"] != "x" for s in export_news_feed(path, as_of=AS_OF)["stories"])
    assert export_news_feed(path, as_of=AS_OF.replace(hour=10)) == earlier
