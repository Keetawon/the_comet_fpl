"""Phase 0b live capture, loading, and bitemporal point-in-time guards."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

from fpl.features.pit import AsOf, FeatureSource, PointInTimeView
from fpl.ingest.live_snapshot import capture_payload, load_capture, write_capture
from fpl.ingest.snapshot_files import load_directory
from fpl.storage.db import initialise


def _bootstrap() -> dict[str, object]:
    return {
        "events": [
            {
                "id": 1,
                "name": "Gameweek 1",
                "deadline_time": "2026-08-21T17:30:00Z",
                "finished": True,
            }
        ],
        "teams": [
            {"id": 1, "name": "Home", "short_name": "HOM"},
            {"id": 2, "name": "Away", "short_name": "AWY"},
        ],
        "elements": [
            {
                "id": 10,
                "code": 10010,
                "web_name": "Tester",
                "element_type": 3,
                "team": 1,
                "now_cost": 75,
                "status": "a",
            }
        ],
    }


def _fixtures(*, kickoff: str = "2026-08-22T14:00:00Z") -> list[dict[str, object]]:
    return [
        {
            "id": 501,
            "code": 9001,
            "event": 1,
            "finished": True,
            "kickoff_time": kickoff,
            "team_h": 1,
            "team_a": 2,
            "team_h_difficulty": 2,
            "team_a_difficulty": 4,
            "pulse_id": 7001,
        }
    ]


def _summary(*, minutes: int, bonus: int) -> dict[str, object]:
    return {
        "fixtures": [],
        "history": [
            {
                "element": 10,
                "fixture": 501,
                "opponent_team": 2,
                "total_points": 5 + bonus,
                "was_home": True,
                "kickoff_time": "2026-08-22T14:00:00Z",
                "round": 1,
                "minutes": minutes,
                "starts": 1,
                "goals_scored": 0,
                "assists": 1,
                "clean_sheets": 1,
                "goals_conceded": 0,
                "bonus": bonus,
                "bps": 24,
                "value": 75,
                "selected": 1000,
                "transfers_in": 5,
                "transfers_out": 1,
            }
        ],
        "history_past": [],
    }


def _capture(*, minutes: int = 90, bonus: int = 1) -> list[object]:
    return [
        capture_payload("bootstrap-static", _bootstrap()),
        capture_payload("fixtures", _fixtures()),
        capture_payload("event-live", {"elements": []}, parameter="1"),
        capture_payload("element-summary", _summary(minutes=minutes, bonus=bonus), parameter="10"),
    ]


def test_capture_manifest_and_live_loader_are_atomic() -> None:
    con = initialise(":memory:")
    try:
        result = write_capture(
            con,
            _capture(),  # type: ignore[arg-type]
            season="2026-27",
            gw=1,
            mode="player-history",
            captured_at=datetime(2026, 8, 23, 12, tzinfo=UTC),
            capture_id="capture-one",
        )
        assert result.payload_count == 4
        assert result.loaded.player_versions == 1
        assert result.loaded.fixture_versions == 1
        assert result.loaded.player_fixture_versions == 1
        header = con.execute(
            "SELECT payload_count, length(manifest_sha256) FROM snapshot_capture"
        ).fetchone()
        assert header == (4, 64)
        assert con.execute("SELECT count(*) FROM snapshot_payload").fetchone() == (4,)
        assert con.execute("SELECT count(*) FROM mart_fact_player_fixture_live").fetchone() == (1,)
        columns = {
            row[0]
            for row in con.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'mart_fact_player_fixture_live'
                """
            ).fetchall()
        }
        assert "total_points" not in columns
    finally:
        con.close()


def test_mid_write_failure_rolls_back_header_payloads_and_legacy_rows() -> None:
    con = initialise(":memory:")
    duplicate = capture_payload("bootstrap-static", _bootstrap())
    try:
        with pytest.raises(duckdb.ConstraintException):
            write_capture(
                con,
                [duplicate, duplicate],
                season="2026-27",
                gw=1,
                mode="daily",
                capture_id="must-rollback",
            )
        for table in ("snapshot_capture", "snapshot_payload", "snapshot_bootstrap"):
            assert con.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)
    finally:
        con.close()


def test_checksum_tampering_is_detected_before_loading() -> None:
    con = initialise(":memory:")
    try:
        result = write_capture(
            con,
            _capture(),  # type: ignore[arg-type]
            season="2026-27",
            gw=1,
            mode="player-history",
        )
        con.execute(
            """
            UPDATE snapshot_payload SET payload = '{"elements": [1]}'
            WHERE capture_id = ? AND endpoint = 'event-live'
            """,
            [result.capture_id],
        )
        with pytest.raises(ValueError, match="checksum mismatch"):
            load_capture(con, result.capture_id)
    finally:
        con.close()


def test_point_in_time_uses_latest_version_known_at_as_of() -> None:
    con = initialise(":memory:")
    try:
        write_capture(
            con,
            _capture(minutes=60, bonus=0),  # type: ignore[arg-type]
            season="2026-27",
            gw=1,
            mode="player-history",
            captured_at=datetime(2026, 8, 23, 12, tzinfo=UTC),
            capture_id="early",
        )
        write_capture(
            con,
            _capture(minutes=90, bonus=3),  # type: ignore[arg-type]
            season="2026-27",
            gw=1,
            mode="player-history",
            captured_at=datetime(2026, 8, 24, 12, tzinfo=UTC),
            capture_id="late",
        )
        source = FeatureSource(con)
        before_known = PointInTimeView(
            source, AsOf(datetime(2026, 8, 23, 11, tzinfo=UTC))
        ).observed_player_fixtures(seasons=["2026-27"])
        early = PointInTimeView(
            source, AsOf(datetime(2026, 8, 23, 13, tzinfo=UTC))
        ).observed_player_fixtures(seasons=["2026-27"])
        late = PointInTimeView(
            source, AsOf(datetime(2026, 8, 24, 13, tzinfo=UTC))
        ).observed_player_fixtures(seasons=["2026-27"])
        assert before_known.is_empty()
        assert early["minutes"].to_list() == [60]
        assert late["minutes"].to_list() == [90]
    finally:
        con.close()


def test_schedule_versions_do_not_rewrite_the_past() -> None:
    con = initialise(":memory:")
    try:
        initial = [
            capture_payload("bootstrap-static", _bootstrap()),
            capture_payload("fixtures", _fixtures(kickoff="2026-08-25T14:00:00Z")),
        ]
        delayed = [
            capture_payload("bootstrap-static", _bootstrap()),
            capture_payload("fixtures", _fixtures(kickoff="2026-08-27T14:00:00Z")),
        ]
        write_capture(
            con,
            initial,
            season="2026-27",
            gw=1,
            mode="daily",
            captured_at=datetime(2026, 8, 23, 12, tzinfo=UTC),
            capture_id="schedule-early",
        )
        write_capture(
            con,
            delayed,
            season="2026-27",
            gw=1,
            mode="daily",
            captured_at=datetime(2026, 8, 24, 12, tzinfo=UTC),
            capture_id="schedule-late",
        )
        source = FeatureSource(con)
        early = PointInTimeView(source, AsOf(datetime(2026, 8, 23, 13, tzinfo=UTC))).schedule(
            seasons=["2026-27"]
        )
        late = PointInTimeView(source, AsOf(datetime(2026, 8, 24, 13, tzinfo=UTC))).schedule(
            seasons=["2026-27"]
        )
        assert early["kickoff_time"].dt.day().unique().to_list() == [25]
        assert late["kickoff_time"].dt.day().unique().to_list() == [27]
    finally:
        con.close()


def test_previous_season_fixture_ids_are_quarantined() -> None:
    con = initialise(":memory:")
    stale = _fixtures(kickoff="2025-08-22T14:00:00Z")
    try:
        result = write_capture(
            con,
            [
                capture_payload("bootstrap-static", _bootstrap()),
                capture_payload("fixtures", stale),
            ],
            season="2026-27",
            gw=1,
            mode="daily",
        )
        assert result.loaded.fixture_versions == 0
        assert result.loaded.skipped_rows == 1
        assert con.execute("SELECT count(*) FROM snapshot_payload").fetchone() == (2,)
        assert con.execute("SELECT count(*) FROM stg_live_fixture_version").fetchone() == (0,)
        assert con.execute("SELECT count(*) FROM ingest_anomaly").fetchone() == (1,)
    finally:
        con.close()


def test_committed_player_history_package_is_verified_loadable_and_idempotent(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "gw-1"
    directory.mkdir()
    bootstrap_path = directory / "bootstrap-static.json.gz"
    fixtures_path = directory / "fixtures.json.gz"
    archive_path = directory / "element-summary.tar.gz"
    with gzip.open(bootstrap_path, "wt", encoding="utf-8") as stream:
        json.dump(_bootstrap(), stream)
    with gzip.open(fixtures_path, "wt", encoding="utf-8") as stream:
        json.dump(_fixtures(), stream)
    summary_bytes = json.dumps(_summary(minutes=90, bonus=2)).encode()
    with tarfile.open(archive_path, "w:gz") as archive:
        member = tarfile.TarInfo("10.json")
        member.size = len(summary_bytes)
        archive.addfile(member, io.BytesIO(summary_bytes))
    payload_paths = (bootstrap_path, fixtures_path, archive_path)
    checksums = "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in payload_paths
    )
    (directory / "SHA256SUMS").write_text(checksums, "utf-8")
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "captured_at": "2026-08-23T12:00:00Z",
                "season": "2026-27",
                "history_through_gw": 1,
                "element_payloads": 1,
                "player_fixture_rows": 1,
            }
        ),
        "utf-8",
    )

    con = initialise(":memory:")
    try:
        result = load_directory(con, directory)
        assert result is not None and result.loaded.player_fixture_versions == 1
        assert load_directory(con, directory) is None
        assert con.execute("SELECT count(*) FROM snapshot_capture").fetchone() == (1,)
    finally:
        con.close()


def test_committed_snapshot_checksum_failure_writes_nothing(tmp_path: Path) -> None:
    directory = tmp_path / "daily"
    directory.mkdir()
    for filename, payload in (
        ("bootstrap-static.json.gz", _bootstrap()),
        ("fixtures.json.gz", _fixtures()),
    ):
        with gzip.open(directory / filename, "wt", encoding="utf-8") as stream:
            json.dump(payload, stream)
    (directory / "SHA256SUMS").write_text("0" * 64 + "  bootstrap-static.json.gz\n", "utf-8")
    (directory / "manifest.json").write_text(
        json.dumps({"schema_version": "1", "captured_at": "2026-08-23T12:00:00Z"}),
        "utf-8",
    )
    con = initialise(":memory:")
    try:
        with pytest.raises(ValueError, match="checksum mismatch"):
            load_directory(con, directory)
        assert con.execute("SELECT count(*) FROM snapshot_capture").fetchone() == (0,)
    finally:
        con.close()
