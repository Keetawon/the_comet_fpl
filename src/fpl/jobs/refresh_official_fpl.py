"""Hourly public FPL reporting, independent of SDP, forecasts and the desktop database."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fpl.ingest.fpl_api import ApiFixture, BootstrapStatic, FplApiClient, assert_same_season
from fpl.ingest.live_snapshot import capture_payload
from fpl.publish.current_availability import validate_current_availability, validate_current_price
from fpl.publish.r2_dashboard import R2Config, _read, load_config, s3_client

CURRENT_KEY = "live-fpl/current.json"
MAX_BYTES = 4_000_000


def encoded(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def build(bootstrap: Any, fixtures: Any, *, captured_at: datetime) -> dict[str, Any]:
    """Project explicitly public fields; never change or recompute a forecast value."""
    if captured_at.tzinfo is None:
        raise ValueError("capture time must be timezone-aware")
    parsed = BootstrapStatic.model_validate(bootstrap)
    matches = [ApiFixture.model_validate(f) for f in fixtures]
    assert_same_season(parsed, matches)
    # A full EPL publication must have the complete calendar and current player pool.
    if len(parsed.teams) != 20 or len(parsed.events) != 38 or len(matches) != 380:
        raise ValueError("incomplete official season coverage")
    if len(parsed.elements) < 400:
        raise ValueError("incomplete official player coverage")
    teams = {t.id: t.code for t in parsed.teams}
    if (
        len(teams) != 20
        or len(set(teams.values())) != 20
        or any(type(c) is not int or c <= 0 for c in teams.values())
    ):
        raise ValueError("ambiguous permanent club identity")
    deadlines = [e.deadline_time for e in parsed.events if e.deadline_time is not None]
    first = min(deadlines)
    start_year = first.year if first.month >= 7 else first.year - 1
    season = f"{start_year}-{str(start_year + 1)[-2:]}"
    if len({e.id for e in parsed.events}) != 38 or {e.id for e in parsed.events} != set(
        range(1, 39)
    ):
        raise ValueError("ambiguous gameweek identity")
    next_events = [e.id for e in parsed.events if e.is_next]
    if len(next_events) > 1:
        raise ValueError("ambiguous next gameweek")
    stamp = captured_at.astimezone(UTC).isoformat()
    sources = {
        "bootstrap-static": capture_payload("bootstrap-static", bootstrap).sha256,
        "fixtures": capture_payload("fixtures", fixtures).sha256,
    }
    capture_id = hashlib.sha256(encoded([stamp, sources])).hexdigest()
    players = []
    seen_codes: set[int] = set()
    seen_ids: set[int] = set()
    for p in parsed.elements:
        if p.code <= 0 or p.id <= 0 or p.code in seen_codes or p.id in seen_ids:
            raise ValueError("ambiguous permanent player identity")
        seen_codes.add(p.code)
        seen_ids.add(p.id)
        if p.team not in teams:
            raise ValueError("unknown player club")
        if p.element_type not in (1, 2, 3, 4):
            continue
        common = {
            "source": "FPL",
            "season": season,
            "code": p.code,
            "captured_at": stamp,
            "capture_id": capture_id,
            "source_sha256": sources["bootstrap-static"],
            "semantics": "current_reported_not_forecast",
        }
        player = {
            "season": season,
            "code": p.code,
            "current_availability": common
            | {
                "status": p.status,
                "chance_of_playing_next_round": p.chance_of_playing_next_round,
                "news": p.news,
                "news_added": p.news_added.isoformat() if p.news_added else None,
                "next_gw": next_events[0] if next_events else None,
            },
            "current_price": common | {"now_cost": p.now_cost},
        }
        validate_current_availability(player, exported_at=stamp)
        validate_current_price(player, exported_at=stamp)
        players.append(player)
    rows = []
    seen_fixtures: set[int] = set()
    for f in matches:
        if f.id <= 0 or f.id in seen_fixtures or f.team_h == f.team_a:
            raise ValueError("ambiguous fixture identity")
        seen_fixtures.add(f.id)
        if f.team_h not in teams or f.team_a not in teams:
            raise ValueError("unknown fixture club")
        for team, opponent, home, fdr in (
            (f.team_h, f.team_a, True, f.team_h_difficulty),
            (f.team_a, f.team_h, False, f.team_a_difficulty),
        ):
            if fdr is not None and not 1 <= fdr <= 5:
                raise ValueError("invalid official FDR")
            rows.append(
                {
                    "fixture": f.id,
                    "team_code": teams[team],
                    "opponent_team_code": teams[opponent],
                    "was_home": home,
                    "official_fdr": fdr,
                }
            )
    return {
        "schema": "fpl.current-official-reporting",
        "schema_version": 1,
        "season": season,
        "captured_at": stamp,
        "capture_id": capture_id,
        "sources": sources,
        "players": players,
        "fixtures": rows,
    }


def publish(client: Any, bucket: str, document: dict[str, Any], raw: dict[str, Any]) -> None:
    """Retain replay inputs first, read back exact bytes, then conditionally update latest."""
    body = encoded(document)
    if len(body) > MAX_BYTES:
        raise ValueError("official reporting exceeds size bound")
    previous = _read(client, bucket, CURRENT_KEY, MAX_BYTES)
    if previous is not None:
        old = json.loads(previous[0])
        if datetime.fromisoformat(old["captured_at"]) >= datetime.fromisoformat(
            document["captured_at"]
        ):
            raise ValueError("refuse reporting timestamp rollback")
        if not isinstance(previous[1].get("ETag"), str):
            raise ValueError("previous reporting has no concurrency token")
    prefix = f"live-fpl/captures/{document['capture_id']}"
    files = {f"{prefix}/reporting.json": body}
    for endpoint, payload in raw.items():
        checked = capture_payload(endpoint, payload)
        if checked.sha256 != document["sources"][endpoint]:
            raise ValueError("raw source does not match reporting")
        files[f"{prefix}/{endpoint}.json.gz"] = gzip.compress(
            checked.payload_json.encode(), mtime=0
        )
    if set(raw) != {"bootstrap-static", "fixtures"}:
        raise ValueError("complete replay inputs required")
    for key, content in files.items():
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=content,
            IfNoneMatch="*",
            ContentType="application/gzip" if key.endswith(".gz") else "application/json",
            CacheControl="public, max-age=31536000, immutable",
        )
        retained = _read(client, bucket, key, len(content))
        if retained is None or retained[0] != content:
            raise ValueError("immutable official capture readback failed")
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
        raise ValueError("current official reporting readback failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--r2-config", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        # Existing client supplies pacing, bounded request time and retries.
        with FplApiClient() as client:
            bootstrap = client.raw_bootstrap_static()
            fixtures = client.raw_fixtures()
        document = build(bootstrap, fixtures, captured_at=datetime.now(UTC))
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output / "reporting.json").write_bytes(encoded(document))
        raw = {"bootstrap-static": bootstrap, "fixtures": fixtures}
        for endpoint, payload in raw.items():
            (args.output / f"{endpoint}.json.gz").write_bytes(
                gzip.compress(capture_payload(endpoint, payload).payload_json.encode(), mtime=0)
            )
        with TemporaryDirectory(prefix="comet-live-fpl-") as temporary:
            if args.r2_config is not None:
                config = load_config(args.r2_config)
            else:
                # Ephemeral runner profile: no credentials in Git, artifacts or stdout.
                profile = Path(temporary) / "credentials"
                profile.write_text(
                    "[comet-r2]\naws_access_key_id="
                    + os.environ["R2_ACCESS_KEY_ID"]
                    + "\naws_secret_access_key="
                    + os.environ["R2_SECRET_ACCESS_KEY"]
                    + "\n"
                )
                profile.chmod(0o600)
                config = R2Config(
                    os.environ["R2_BUCKET"],
                    os.environ["R2_ENDPOINT_URL"],
                    "https://data.thecometfpl.com",
                    profile,
                )
            publish(s3_client(config), config.bucket, document, raw)
        print(
            json.dumps(
                {
                    "status": "COMPLETE",
                    "captured_at": document["captured_at"],
                    "players": len(document["players"]),
                    "fixture_sides": len(document["fixtures"]),
                }
            )
        )
        return 0
    except Exception as exc:
        # SDK exceptions can include request context. Keep secrets out of job logs.
        print(json.dumps({"status": "FAILED", "error_type": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
