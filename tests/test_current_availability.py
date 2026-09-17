from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import duckdb
import pytest

from fpl.ingest.live_snapshot import _manifest, capture_payload
from fpl.publish.current_availability import (
    current_availability,
    current_reporting,
    validate_current_availability,
    validate_current_price,
)

STAMP = datetime(2026, 9, 17, 4, tzinfo=UTC)


@pytest.fixture
def availability_db() -> Iterator[duckdb.DuckDBPyConnection]:
    with duckdb.connect() as con:
        con.execute("""CREATE TABLE snapshot_capture(capture_id VARCHAR, captured_at TIMESTAMPTZ,
                    season VARCHAR, payload_count INTEGER, manifest VARCHAR,
                    manifest_sha256 VARCHAR);
                    CREATE TABLE snapshot_payload(capture_id VARCHAR, endpoint VARCHAR,
                    parameter VARCHAR, payload VARCHAR, sha256 VARCHAR, byte_count BIGINT,
                    row_count BIGINT)""")
        yield con


def add_capture(
    con: duckdb.DuckDBPyConnection,
    players: list[dict[str, Any]],
    *,
    identity: str = "current",
    at: str = "2026-09-17T03:00:00Z",
    season: str = "2026-27",
) -> None:
    payload = capture_payload(
        "bootstrap-static",
        {
            "elements": players,
            "events": [{"id": 5, "is_next": True}],
        },
    )
    body, sha = _manifest([payload])
    con.execute(
        "INSERT INTO snapshot_capture VALUES (?, ?, ?, ?, ?, ?)",
        [identity, at, season, 1, body, sha],
    )
    con.execute(
        "INSERT INTO snapshot_payload VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            identity,
            payload.endpoint,
            "",
            payload.payload_json,
            payload.sha256,
            payload.byte_count,
            payload.row_count,
        ],
    )


def test_whole_latest_capture_exact_identity_nulls_and_real_cutoff(
    availability_db: duckdb.DuckDBPyConnection,
) -> None:
    con = availability_db
    player = {"id": 165, "code": 475168, "status": "a", "now_cost": 50}
    add_capture(con, [player, {"id": 2, "code": 2}], identity="old", at="2026-09-14T03:00:00Z")
    add_capture(
        con,
        [
            {
                **player,
                "status": "d",
                "chance_of_playing_next_round": 75,
                "news": "Unspecified injury - 75% chance of playing",
                "news_added": "2026-09-16T19:00:09Z",
                "now_cost": 49,
            },
            {"id": 3, "code": 3},
        ],
    )
    add_capture(
        con,
        [{**player, "status": "i", "now_cost": 48}],
        identity="future",
        at="2026-09-18T03:00:00Z",
    )
    add_capture(con, [{**player, "status": "s"}], identity="previous-season", season="2025-26")
    result = current_availability(con, as_of=STAMP)
    assert ("2026-27", 2) not in result  # No per-player stale backfill.
    assert result[("2026-27", 475168)]["status"] == "d"
    assert result[("2026-27", 475168)]["chance_of_playing_next_round"] == 75
    assert result[("2026-27", 475168)]["capture_id"] == "current"
    assert result[("2025-26", 475168)]["status"] == "s"
    unknown = result[("2026-27", 3)]
    assert all(
        unknown[k] is None for k in ("status", "chance_of_playing_next_round", "news", "news_added")
    )
    assert current_availability(con, as_of=STAMP) == result
    reporting = current_reporting(con, as_of=STAMP)
    price = reporting[("2026-27", 475168)]["current_price"]
    assert price["now_cost"] == 49
    assert reporting[("2025-26", 475168)]["current_price"]["now_cost"] == 50
    assert reporting[("2026-27", 3)]["current_price"]["now_cost"] is None
    assert ("2026-27", 2) not in reporting
    assert {key: value for key, value in price.items() if key != "now_cost"} == {
        key: result[("2026-27", 475168)][key] for key in price if key != "now_cost"
    }
    earlier = current_reporting(con, as_of=datetime(2026, 9, 15, tzinfo=UTC))
    assert earlier[("2026-27", 475168)]["current_price"]["now_cost"] == 50


@pytest.mark.parametrize(
    "players",
    [
        [{"id": 1, "code": 1}, {"id": 2, "code": 1}],
        [{"id": 1, "code": 1}, {"id": 1, "code": 2}],
        [{"id": 1, "code": None}],
    ],
)
def test_ambiguous_source_identity_fails_closed(
    availability_db: duckdb.DuckDBPyConnection,
    players: list[dict[str, Any]],
) -> None:
    add_capture(availability_db, players)
    with pytest.raises(ValueError, match="player identity"):
        current_availability(availability_db, as_of=STAMP)


@pytest.mark.parametrize("corruption", ["payload", "manifest", "count"])
def test_incomplete_or_changed_source_fails_closed(
    availability_db: duckdb.DuckDBPyConnection,
    corruption: str,
) -> None:
    con = availability_db
    add_capture(con, [{"id": 1, "code": 1}])
    statements = {
        "payload": "UPDATE snapshot_payload SET payload = '{}'",
        "manifest": "UPDATE snapshot_capture SET manifest_sha256 = 'wrong'",
        "count": "UPDATE snapshot_capture SET payload_count = 2",
    }
    con.execute(statements[corruption])
    with pytest.raises(ValueError, match=r"checksum|manifest"):
        current_availability(con, as_of=STAMP)


def test_no_capture_is_unknown_and_bad_overlay_cannot_pass_validation(
    availability_db: duckdb.DuckDBPyConnection,
) -> None:
    con = availability_db
    assert current_availability(con, as_of=STAMP) == {}
    assert current_reporting(con, as_of=STAMP) == {}
    add_capture(con, [{"id": 1, "code": 1, "status": "d"}])
    original = current_availability(con, as_of=STAMP)[("2026-27", 1)]
    for key, value in [
        ("code", 2),
        ("chance_of_playing_next_round", True),
        ("status", "healthy"),
        ("status", []),
        ("source_sha256", "bad"),
        ("captured_at", "2026-09-19T00:00:00Z"),
        ("news_added", "2026-09-19T00:00:00Z"),
    ]:
        player = {"season": "2026-27", "code": 1, "current_availability": {**original, key: value}}
        with pytest.raises(ValueError, match="current availability"):
            validate_current_availability(player, exported_at=STAMP.isoformat())
    validate_current_availability({"season": "2026-27", "code": 1}, exported_at=STAMP.isoformat())
    assert json.loads(json.dumps(original))["chance_of_playing_next_round"] is None
    validate_current_availability(
        {"season": "2026-27", "code": 1, "current_availability": {**original, "status": "x"}},
        exported_at=STAMP.isoformat(),
    )


@pytest.mark.parametrize("price", [True, 49.0, "49", 0, -1])
def test_invalid_current_price_fails_without_using_older_price(
    availability_db: duckdb.DuckDBPyConnection, price: object
) -> None:
    player = {"id": 1, "code": 1, "now_cost": 50}
    add_capture(availability_db, [player], identity="old", at="2026-09-16T03:00:00Z")
    add_capture(availability_db, [{**player, "now_cost": price}])
    with pytest.raises(ValueError, match="current price"):
        current_reporting(availability_db, as_of=STAMP)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("code", 2),
        ("code", True),
        ("season", "2025-26"),
        ("source", "other"),
        ("unexpected", 49),
        ("semantics", "forecast"),
        ("source_sha256", "bad"),
        ("capture_id", ""),
        ("captured_at", "2026-09-19T00:00:00Z"),
        ("captured_at", "2026-09-17T00:00:00"),
    ],
)
def test_current_price_identity_provenance_and_time_are_validated(
    availability_db: duckdb.DuckDBPyConnection, field: str, value: object
) -> None:
    add_capture(availability_db, [{"id": 1, "code": 1, "now_cost": 49}])
    original = current_reporting(availability_db, as_of=STAMP)[("2026-27", 1)]["current_price"]
    with pytest.raises(ValueError, match="current price"):
        validate_current_price(
            {"season": "2026-27", "code": 1, "current_price": {**original, field: value}},
            exported_at=STAMP.isoformat(),
        )


def test_price_requires_same_capture_as_availability_and_supports_legacy_and_null(
    availability_db: duckdb.DuckDBPyConnection,
) -> None:
    add_capture(
        availability_db,
        [{"id": 1, "code": 1, "now_cost": 50}],
        identity="old",
        at="2026-09-16T03:00:00Z",
    )
    add_capture(availability_db, [{"id": 1, "code": 1, "now_cost": None}])
    report = current_reporting(availability_db, as_of=STAMP)[("2026-27", 1)]
    player = {"season": "2026-27", "code": 1, **report}
    validate_current_price(player, exported_at=STAMP.isoformat())
    assert report["current_price"]["now_cost"] is None
    for legacy in (
        {"season": "2026-27", "code": 1},
        {"season": "2026-27", "code": 1, "current_price": None},
    ):
        validate_current_price(legacy, exported_at=STAMP.isoformat())
    with pytest.raises(ValueError, match="source mismatch"):
        validate_current_price(
            {**player, "current_price": {**report["current_price"], "capture_id": "another"}},
            exported_at=STAMP.isoformat(),
        )
