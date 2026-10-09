"""Independent news publication must never move the model pointer or publish demos."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import timedelta
from typing import Any

import pytest

from fpl.jobs.publish_public_news import CURRENT_KEY, add_roundup, publish
from fpl.publish.public_news import empty_news_feed

from .test_r2_dashboard import FakeS3
from .test_refresh_official_fpl import STAMP, official_payloads


def test_schedule_is_exactly_five_hours_before_next_future_official_deadline() -> None:
    bootstrap, _ = official_payloads()
    bootstrap["events"][5]["deadline_time"] = (STAMP + timedelta(days=1)).isoformat()
    doc = add_roundup(empty_news_feed(as_of=STAMP), bootstrap, captured_at=STAMP)
    assert doc["roundup"]["gw"] == 6
    assert doc["roundup"]["opens_at"] == (STAMP + timedelta(hours=19)).isoformat()
    assert "complete" not in str(doc["roundup"])
    with pytest.raises(ValueError, match="no upcoming"):
        add_roundup(empty_news_feed(as_of=STAMP), official_payloads()[0], captured_at=STAMP)


def test_news_cas_idempotence_and_readback_failures_preserve_current() -> None:
    client = FakeS3()
    doc = empty_news_feed(as_of=STAMP)
    digest = publish(client, "bucket", doc)
    assert publish(client, "bucket", doc) == digest
    assert set(client.objects) == {CURRENT_KEY, f"news/editions/{digest}.json"}
    original = client.objects[CURRENT_KEY]["Body"]
    later = empty_news_feed(as_of=STAMP + timedelta(hours=1))
    read = client.get_object

    def corrupt(**kwargs: Any) -> dict[str, Any]:
        client.failure = "verify" if kwargs["Key"].startswith("news/editions/") else None
        return read(**kwargs)

    client.get_object = corrupt  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="readback"):
        publish(client, "bucket", later)
    assert client.objects[CURRENT_KEY]["Body"] == original
    client.get_object = read  # type: ignore[method-assign]
    client.failure = None
    publish(client, "bucket", later)
    with pytest.raises(ValueError, match="rollback"):
        publish(client, "bucket", doc)
    invalid = deepcopy(later) | {"demo": True}
    with pytest.raises(ValueError, match="demo"):
        publish(client, "bucket", invalid)


def test_concurrent_news_writer_cannot_overwrite_newer_reviewed_edition() -> None:
    client = FakeS3()
    publish(client, "bucket", empty_news_feed(as_of=STAMP))
    put = client.put_object
    newer = json.dumps(empty_news_feed(as_of=STAMP + timedelta(hours=2))).encode()

    def race(**kwargs: Any) -> None:
        if kwargs["Key"] == CURRENT_KEY:
            client.objects[CURRENT_KEY].update(Body=newer, ETag="another-writer")
        put(**kwargs)

    client.put_object = race  # type: ignore[method-assign]
    with pytest.raises(Exception, match="credential-secret"):
        publish(client, "bucket", empty_news_feed(as_of=STAMP + timedelta(hours=1)))
    assert client.objects[CURRENT_KEY]["Body"] == newer
