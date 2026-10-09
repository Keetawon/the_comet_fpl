"""Publish reviewed public news independently of the immutable forecast generation."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fpl.ingest.fpl_api import BootstrapStatic, FplApiClient
from fpl.ingest.live_snapshot import capture_payload
from fpl.publish.public_news import export_news_feed, validate_news_feed
from fpl.publish.r2_dashboard import _read, load_config, s3_client
from fpl.storage.public_news import canonical

CURRENT_KEY = "news/current.json"
MAX_BYTES = 1_000_000


def add_roundup(
    document: dict[str, Any], bootstrap: Any, *, captured_at: datetime
) -> dict[str, Any]:
    """Use the next actual future official deadline, not an inferred fixture kickoff."""
    parsed = BootstrapStatic.model_validate(bootstrap)
    if (
        captured_at.tzinfo is None
        or len(parsed.events) != 38
        or {e.id for e in parsed.events} != set(range(1, 39))
    ):
        raise ValueError("complete official calendar and aware capture time required")
    deadlines = [e for e in parsed.events if e.deadline_time is not None]
    future = [e for e in deadlines if e.deadline_time and e.deadline_time > captured_at]
    if not future:
        raise ValueError("no upcoming official deadline")
    event = min(future, key=lambda e: e.deadline_time or captured_at)
    first = min(e.deadline_time for e in deadlines if e.deadline_time)
    year = first.year if first.month >= 7 else first.year - 1
    assert event.deadline_time is not None
    result = document | {
        "schema_version": 2,
        "roundup": {
            "season": f"{year}-{str(year + 1)[-2:]}",
            "gw": event.id,
            "deadline_at": event.deadline_time.isoformat(),
            "opens_at": (event.deadline_time - timedelta(hours=5)).isoformat(),
            "schedule_captured_at": captured_at.isoformat(),
            "schedule_sha256": capture_payload("bootstrap-static", bootstrap).sha256,
        },
    }
    validate_news_feed(result)
    return result


def publish(client: Any, bucket: str, document: dict[str, Any]) -> str:
    """Read back a content-addressed public digest before advancing latest with CAS."""
    validate_news_feed(document)
    if document["demo"]:
        raise ValueError("demo news cannot be published")
    body = canonical(document)
    if len(body) > MAX_BYTES:
        raise ValueError("news exceeds size bound")
    previous = _read(client, bucket, CURRENT_KEY, MAX_BYTES)
    if previous:
        if previous[0] == body:
            return hashlib.sha256(body).hexdigest()
        if datetime.fromisoformat(
            json.loads(previous[0])["generated_at"]
        ) >= datetime.fromisoformat(document["generated_at"]):
            raise ValueError("refuse news timestamp rollback")
        if not isinstance(previous[1].get("ETag"), str):
            raise ValueError("previous news has no concurrency token")
    digest = hashlib.sha256(body).hexdigest()
    key = f"news/editions/{digest}.json"
    retained = _read(client, bucket, key, MAX_BYTES)
    if retained is None:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            IfNoneMatch="*",
            ContentType="application/json",
            CacheControl="public, max-age=31536000, immutable",
        )
        retained = _read(client, bucket, key, MAX_BYTES)
    if retained is None or retained[0] != body:
        raise ValueError("news edition readback failed")
    condition = {"IfMatch": previous[1]["ETag"]} if previous else {"IfNoneMatch": "*"}
    client.put_object(
        Bucket=bucket,
        Key=CURRENT_KEY,
        Body=body,
        ContentType="application/json",
        CacheControl="no-store",
        **condition,
    )
    retained = _read(client, bucket, CURRENT_KEY, MAX_BYTES)
    if retained is None or retained[0] != body:
        raise ValueError("current news readback failed")
    return digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--r2-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--allow-empty", action="store_true", help="Explicitly withdraw all stories"
    )
    args = parser.parse_args()
    try:
        with FplApiClient() as client:
            bootstrap = client.raw_bootstrap_static()
        captured = datetime.now(UTC)
        document = add_roundup(
            export_news_feed(args.store, as_of=captured), bootstrap, captured_at=captured
        )
        if not document["stories"] and not args.allow_empty:
            raise ValueError(
                "no reviewed current stories; use --allow-empty for explicit withdrawal"
            )
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output / "news.json").write_bytes(canonical(document))
        # Official schedule replay stays local. Raw X text and keys are never uploaded.
        (args.output / "bootstrap-static.json").write_bytes(canonical(bootstrap))
        config = load_config(args.r2_config)
        digest = publish(s3_client(config), config.bucket, document)
        print(
            json.dumps(
                {"status": "COMPLETE", "sha256": digest, "stories": len(document["stories"])}
            )
        )
        return 0
    except Exception as exc:
        print(json.dumps({"status": "FAILED", "error_type": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
