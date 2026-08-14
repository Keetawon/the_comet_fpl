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

from fpl.features.pit import OUTCOME_COLUMNS, AsOf, FeatureSource, LeakageError, PointInTimeView
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
                "threat": 55.0,
                "creativity": 12.3,
                "influence": 44.2,
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
        assert result.loaded.team_versions == 2
        assert result.loaded.fixture_versions == 1
        assert result.loaded.player_fixture_versions == 1
        assert con.execute("SELECT count(*) FROM stg_live_team_version").fetchone() == (2,)
        team_row = con.execute(
            """
            SELECT team_id, team_name, short_name
            FROM stg_live_team_version WHERE team_id = 1
            """
        ).fetchone()
        assert team_row == (1, "Home", "HOM")
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


def test_live_projection_carries_influence_and_preserves_null() -> None:
    """`influence` flows through the element-summary projection exactly like threat/creativity.

    When the ICT index is present it must land as its measured value; when the source omits it
    the fact must stay NULL, never a silent zero (gotcha 5). Asserted on both the versioned
    staging row and the live fact.
    """
    con = initialise(":memory:")
    try:
        # Present: `_summary` sets influence = 44.2 for element 10, fixture 501.
        write_capture(
            con,
            _capture(minutes=90, bonus=2),  # type: ignore[arg-type]
            season="2026-27",
            gw=1,
            mode="player-history",
            captured_at=datetime(2026, 8, 23, 12, tzinfo=UTC),
            capture_id="with-influence",
        )
        row = con.execute(
            "SELECT influence FROM mart_fact_player_fixture_live "
            "WHERE code = 10010 AND fixture = 501"
        ).fetchone()
        assert row is not None and row[0] == 44.2
        staged = con.execute(
            "SELECT influence FROM stg_live_player_fixture_version "
            "WHERE fixture = 501 AND capture_id = 'with-influence'"
        ).fetchone()
        assert staged is not None and staged[0] == 44.2

        # Absent: an element-summary history row without an `influence` key must stay NULL.
        # Fixture 502 (player away, opponent = home team 2) must exist in the capture's own
        # fixtures payload or the loader quarantines the history row.
        fixtures_with_502 = [
            {
                "id": 502,
                "code": 9002,
                "event": 2,
                "finished": True,
                "kickoff_time": "2026-08-29T14:00:00Z",
                "team_h": 2,
                "team_a": 1,
                "team_h_difficulty": 3,
                "team_a_difficulty": 3,
                "pulse_id": 7002,
            }
        ]
        summary_without = {
            "fixtures": [],
            "history": [
                {
                    "element": 10,
                    "fixture": 502,
                    "opponent_team": 2,
                    "total_points": 3,
                    "was_home": False,
                    "kickoff_time": "2026-08-29T14:00:00Z",
                    "round": 2,
                    "minutes": 90,
                    "starts": 1,
                    "bonus": 0,
                    "bps": 10,
                    "value": 75,
                }
            ],
            "history_past": [],
        }
        capture_without = [
            capture_payload("bootstrap-static", _bootstrap()),
            capture_payload("fixtures", fixtures_with_502),
            capture_payload("element-summary", summary_without, parameter="10"),
        ]
        write_capture(
            con,
            capture_without,  # type: ignore[arg-type]
            season="2026-27",
            gw=2,
            mode="player-history",
            captured_at=datetime(2026, 8, 30, 12, tzinfo=UTC),
            capture_id="without-influence",
        )
        null_row = con.execute(
            "SELECT count(*), count(influence) FROM mart_fact_player_fixture_live "
            "WHERE code = 10010 AND fixture = 502"
        ).fetchone()
        assert null_row is not None
        total, non_null = null_row
        assert total == 1 and non_null == 0, "absent influence must be NULL, never zero-filled"
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


# --------------------------------------------------------------------------------------
# Versioned player registry (PointInTimeView.player_registry) -- the live/prospective
# roster-selection path. Offline, in-memory; the loader's idempotency and failure-path
# atomicity are covered by the tests above.
# --------------------------------------------------------------------------------------


def _registry_bootstrap(*, team: int, status: str = "a") -> dict[str, object]:
    """A one-player bootstrap whose only variable is the registration club/status."""
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
                "web_name": "Reg",
                "element_type": 3,
                "team": team,
                "now_cost": 55,
                "status": status,
            }
        ],
    }


def _registry_capture(*, team: int, status: str = "a") -> list[object]:
    return [
        capture_payload("bootstrap-static", _registry_bootstrap(team=team, status=status)),
        capture_payload("fixtures", _fixtures()),
    ]


def test_player_registry_picks_newest_capture_at_or_before_as_of() -> None:
    """One row per code: the newest capture with known_at <= as_of; a later capture is hidden."""
    con = initialise(":memory:")
    try:
        write_capture(
            con,
            _registry_capture(team=1),  # type: ignore[arg-type]
            season="2026-27",
            gw=1,
            mode="daily",
            captured_at=datetime(2026, 8, 23, 12, tzinfo=UTC),
            capture_id="early",
        )
        write_capture(
            con,
            _registry_capture(team=2),  # type: ignore[arg-type]
            season="2026-27",
            gw=1,
            mode="daily",
            captured_at=datetime(2026, 8, 24, 12, tzinfo=UTC),
            capture_id="late",
        )
        source = FeatureSource(con)
        before = PointInTimeView(
            source, AsOf(datetime(2026, 8, 23, 11, tzinfo=UTC))
        ).player_registry()
        between = PointInTimeView(
            source, AsOf(datetime(2026, 8, 23, 13, tzinfo=UTC))
        ).player_registry()
        after = PointInTimeView(
            source, AsOf(datetime(2026, 8, 24, 13, tzinfo=UTC))
        ).player_registry()
        assert before.is_empty()
        assert between["team_id"].to_list() == [1]
        assert after["team_id"].to_list() == [2]
        assert after["code"].to_list() == [10010]  # one row per code
    finally:
        con.close()


def test_player_registry_capture_one_second_after_as_of_is_invisible() -> None:
    """known_at <= as_of is strict: a capture one second after as_of is not yet known."""
    con = initialise(":memory:")
    try:
        write_capture(
            con,
            _registry_capture(team=1),  # type: ignore[arg-type]
            season="2026-27",
            gw=1,
            mode="daily",
            captured_at=datetime(2026, 8, 23, 12, 0, 0, tzinfo=UTC),
            capture_id="c",
        )
        source = FeatureSource(con)
        too_early = PointInTimeView(source, AsOf(datetime(2026, 8, 23, 11, 59, 59, tzinfo=UTC)))
        assert too_early.player_registry().is_empty()
        at_instant = PointInTimeView(source, AsOf(datetime(2026, 8, 23, 12, 0, 0, tzinfo=UTC)))
        assert at_instant.player_registry()["code"].to_list() == [10010]
    finally:
        con.close()


def test_player_registry_ties_break_on_capture_id_desc() -> None:
    """Same known_at: the larger capture_id wins, deterministically.

    write_capture cannot itself produce two captures with identical known_at (snapshot_bootstrap
    keys on (captured_at, endpoint)), so this exercises the defensive tiebreak in the registry
    query (`ORDER BY known_at DESC, capture_id DESC`) by inserting tied rows directly.
    """
    con = initialise(":memory:")
    try:
        tied = datetime(2026, 8, 23, 12, tzinfo=UTC)
        con.executemany(
            """
            INSERT INTO stg_live_player_version
                (season, element, code, known_at, capture_id, web_name, element_type,
                 position, team_id, now_cost, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("2026-27", 10, 10010, tied, "aaa", "Reg", 3, "MID", 1, 55, "a"),
                ("2026-27", 10, 10010, tied, "bbb", "Reg", 3, "MID", 2, 55, "a"),
            ],
        )
        source = FeatureSource(con)
        reg = PointInTimeView(source, AsOf(datetime(2026, 8, 23, 13, tzinfo=UTC))).player_registry()
        assert reg["team_id"].to_list() == [2]
        assert reg["capture_id"].to_list() == ["bbb"]
    finally:
        con.close()


def test_player_registry_exposes_no_outcome_and_rejects_outcome_projection() -> None:
    """The registry returns identity/registration metadata only and refuses an outcome column."""
    con = initialise(":memory:")
    try:
        write_capture(
            con,
            _registry_capture(team=1),  # type: ignore[arg-type]
            season="2026-27",
            gw=1,
            mode="daily",
            captured_at=datetime(2026, 8, 23, 12, tzinfo=UTC),
            capture_id="c",
        )
        source = FeatureSource(con)
        view = PointInTimeView(source, AsOf(datetime(2026, 8, 23, 13, tzinfo=UTC)))
        reg = view.player_registry()
        assert set(reg.columns) & OUTCOME_COLUMNS == set()
        with pytest.raises(LeakageError, match="outcome column"):
            view.player_registry(columns=["code", "minutes"])
    finally:
        con.close()
