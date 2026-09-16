from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pytest

from fpl.publish import competitive_schedule as publisher
from fpl.publish.competitive_schedule import build_catalogues

STAMP = datetime(2026, 9, 15, tzinfo=UTC)


def match(identifier: int = 100, *, kickoff: str | None = "2026-09-16 20:00:00") -> dict[str, Any]:
    return {
        "matchId": str(identifier),
        "competitionId": "2",
        "season": "2026",
        "homeTeam": {"id": "500", "name": "Home FC", "abbr": "HOM"},
        "awayTeam": {"id": "600", "name": "Cup opposition", "abbr": "CUP"},
        "kickoff": kickoff,
        "kickoffTimezoneString": "Europe/London",
        "period": "PreMatch",
    }


def page(
    items: list[dict[str, Any]],
    *,
    cursor: str | None = None,
    next_cursor: str | None = None,
    stamp: datetime = STAMP,
) -> dict[str, Any]:
    body = json.dumps({"data": items, "pagination": {"_next": next_cursor}})
    sha = hashlib.sha256(body.encode()).hexdigest()
    params = {"competition": "2", "season": "2026", "_limit": "100"}
    if cursor is not None:
        params["_next"] = cursor
    return {
        "body": body,
        "byte_count": len(body.encode()),
        "sha256": sha,
        "payload_id": sha,
        "fetched_at": stamp,
        "status_code": 200,
        "endpoint": "competitive_matches",
        "season": "2026-27",
        "params_json": json.dumps(params),
    }


def catalogue(raw: list[dict[str, Any]]) -> Any:
    return build_catalogues(raw, season="2026-27", as_of=STAMP, team_map={500: 3})[1]


def test_exact_identity_future_schedule_and_uk_timezone() -> None:
    result = catalogue([page([match()])])
    assert result.status == "AVAILABLE"
    row = result.matches[0]
    assert row.home_team_code == 3  # Provider 500 is explicitly mapped, not FPL id equality.
    assert row.away_team_code is None
    assert row.kickoff_time.isoformat() == "2026-09-16T19:00:00+00:00"
    assert row.status == "PreMatch"


def test_never_fuzzy_join_a_named_club_or_invent_an_undated_kickoff() -> None:
    unknown = match(101)
    unknown["homeTeam"]["id"] = "999"
    result = catalogue([page([match(kickoff=None), unknown])])
    assert len(result.matches) == 1
    assert result.matches[0].kickoff_time is None


def test_latest_root_follows_exact_chain_ignoring_orphaned_old_pages() -> None:
    raw = [
        page([match(1)], next_cursor="old", stamp=STAMP - timedelta(days=1)),
        page([match(2)], cursor="old"),
        page([match(3)]),
    ]
    assert [m.provider_match_id for m in catalogue(raw).matches] == [3]


def test_missing_page_and_empty_catalogue_are_not_no_competition() -> None:
    assert catalogue([]).status == "UNAVAILABLE"
    assert catalogue([page([])]).status == "NOT_PUBLISHED"
    partial = catalogue([page([match()], next_cursor="missing")])
    assert partial.status == "PARTIAL"
    assert partial.issues == ["missing_catalogue_page"]
    assert len(partial.matches) == 1


@pytest.mark.parametrize("problem", ["hash", "http", "identity", "duplicate", "loop"])
def test_invalid_revision_fails_closed_without_reviving_old_matches(problem: str) -> None:
    old = page([match(1)], stamp=STAMP - timedelta(days=1))
    new = page([match(2)])
    if problem == "hash":
        new["sha256"] = "0" * 64
    elif problem == "http":
        new["status_code"] = 503
    elif problem == "identity":
        m = match(2)
        m["competitionId"] = "5"
        new = page([m])
    elif problem == "duplicate":
        new = page([match(2), match(2)])
    else:
        new = page([match(2)], next_cursor="repeat")
    raw = [old, new]
    if problem == "loop":
        raw.append(page([match(3)], cursor="repeat", next_cursor="repeat"))
    result = catalogue(raw)
    assert result.status == "UNAVAILABLE"
    assert result.matches == []


def test_replay_future_truncation_and_raw_immutability() -> None:
    raw = [page([match()])]
    before = deepcopy(raw)
    result = catalogue(raw).model_dump_json()
    assert (
        result
        == catalogue([*raw, page([match(2)], stamp=STAMP + timedelta(days=1))]).model_dump_json()
    )
    assert raw == before
    assert result == catalogue(list(reversed(raw))).model_dump_json()


def test_public_write_once_replay_and_provenance_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = publisher.CompetitiveSchedule(
        season="2026-27",
        as_of=STAMP,
        verified_team_codes=[3],
        identity_sources=[],
        competitions=build_catalogues(
            [page([match()])], season="2026-27", as_of=STAMP, team_map={500: 3}
        ),
    )
    db = tmp_path / "empty.duckdb"
    duckdb.connect(str(db)).close()
    monkeypatch.setattr(publisher, "build_competitive_schedule", lambda *a, **k: doc)
    first, replay = tmp_path / "first.json", tmp_path / "replay.json"
    assert publisher.export_competitive_schedule(
        db, first, as_of=STAMP
    ) == publisher.export_competitive_schedule(db, replay, as_of=STAMP)
    assert first.read_bytes() == replay.read_bytes()
    with pytest.raises(FileExistsError):
        publisher.export_competitive_schedule(db, first, as_of=STAMP)
    value = doc.model_dump(mode="json")
    value["competitions"][1]["sources"][0]["known_at"] = (STAMP + timedelta(days=1)).isoformat()
    with pytest.raises(ValueError, match="future source"):
        publisher.validate_competitive_schedule(value)
    value = doc.model_dump(mode="json")
    value["competitions"][1]["matches"][0]["source_payload_id"] = "0" * 64
    with pytest.raises(ValueError, match="provenance"):
        publisher.validate_competitive_schedule(value)
