"""Synthetic V3 read-only adapter boundaries; no fits or network."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from fpl.validate.player_workload_inputs import INTERPRETATION_ID, _guard, version_view


def source() -> dict[str, Any]:
    return {
        "interpretation_id": INTERPRETATION_ID,
        "competition_id": 1,
        "season": "2025-26",
        "match_id": 123,
        "kickoff": "2025-08-01T12:00:00+00:00",
        "raw_match": {
            "matchId": 123,
            "kickoff": "2025-08-01T12:00:00+00:00",
            "period": "FullTime",
            "resultType": "AfterExtraTime",
            "homeTeam": {"id": 3, "score": 1},
            "awayTeam": {"id": 77, "score": 0},
        },
        "capture_known_at": "2026-09-07T08:00:00+00:00",
        "interpretation_known_at": "2026-09-07T09:00:00+00:00",
        "receipt_ids": ["a" * 64],
        "version_id": "version1",
        "capture_complete": True,
        "extra_time": True,
        "maximum_retained_event_timestamp": None,
        "verified_end_at": None,
        "errors": [],
        "rows": [
            {
                "provider_player_id": 101,
                "code": 1,
                "team_code": 3,
                "provider_team_id": 3,
                "nominal_minutes": None,
                "started": None,
                "appeared": None,
            }
        ],
    }


def build(record: dict[str, Any]):
    return version_view(
        [record],
        {3: 3},
        catalogue_identity="retained-catalogue",
        catalogue_known_at=datetime(2026, 9, 7, tzinfo=UTC),
    )


def test_v3_original_times_and_nulls_survive_with_all_competition_catalogues() -> None:
    record = source()
    view = build(record)
    version = next(iter(view._versions.values()))
    assert version.interpretation_id == INTERPRETATION_ID
    assert version.capture_known_at.isoformat() == record["capture_known_at"]
    assert version.verified_end_at is None
    assert version.observations[0].nominal_minutes is None
    assert version.observations[0].appeared is None
    assert version.extra_time is True
    assert len(view.catalogue) == 6
    assert view.memberships == ()
    assert view.fixtures[0].provider_to_team_code == ((3, 3),)


@pytest.mark.parametrize(
    ("field", "value"),
    [("interpretation_id", "v2"), ("capture_complete", False), ("match_id", 456)],
)
def test_adapter_rejects_wrong_version_incomplete_or_identity(field: str, value: Any) -> None:
    record = source()
    record[field] = value
    with pytest.raises(ValueError, match=r"V3|complete|identity"):
        build(record)


@pytest.mark.parametrize(
    "result_type", ["AfterExtraTime", "AfterPenalties", "AggregateResult", "NormalResult"]
)
def test_competitive_result_labels_are_not_pl_only(result_type: str) -> None:
    record = source()
    record["raw_match"]["resultType"] = result_type
    # Exact enums only; an unknown plausible spelling remains unsupported.
    from fpl.transform.competitive_participation_v2 import RESULT_TYPES

    if result_type not in RESULT_TYPES:
        with pytest.raises(ValueError, match="complete"):
            build(record)
    else:
        assert build(record).fixtures[0].completed is True


def test_unknown_whole_match_retained_but_not_usable_in_reader() -> None:
    record = source()
    record["errors"] = ["unknown dismissal actor"]
    view = build(record)
    assert next(iter(view._versions.values())).errors == ("unknown dismissal actor",)


def test_explicit_database_rejects_wrong_hash_and_wal(tmp_path: Path) -> None:
    database = tmp_path / "test.duckdb"
    database.write_bytes(b"not the pinned source")
    with pytest.raises(ValueError, match="hash/WAL"):
        _guard(database)
    Path(str(database) + ".wal").write_bytes(b"active")
    with pytest.raises(ValueError, match="hash/WAL"):
        _guard(database)
