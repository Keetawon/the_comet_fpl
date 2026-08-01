"""Deterministic OFFLINE tests for the Phase 0b P1 read-time freshness gate.

No network, no built archive. Every database is a tiny in-memory DuckDB. These tests pin the
gate's three pass cases (season-start cold start, prior-archived-season cold start, and a covered
current-season capture) and its one fail case (a current-season completed gameweek whose
player-history capture is missing or only exists with ``known_at > as_of``), plus the
``predict_prospective_minutes`` integration: refuse (non-zero exit) when stale, emit with
freshness provenance when fresh.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

from fpl.ingest.live_snapshot import capture_payload, write_capture
from fpl.jobs.prospective_minutes_v1 import predict_prospective_minutes
from fpl.storage.db import initialise
from fpl.validate.freshness import (
    FreshnessError,
    assess_prospective_freshness,
    require_prospective_freshness,
)

# --------------------------------------------------------------------------------------
# Unit tests: the gate logic against minimal tables
# --------------------------------------------------------------------------------------


def _con() -> duckdb.DuckDBPyConnection:
    """Three minimal tables with only the columns the gate reads."""
    con = duckdb.connect(":memory:")
    con.execute("SET TimeZone='UTC'")
    con.execute(
        """
        CREATE TABLE stg_live_fixture_version (
            season       VARCHAR,
            fixture      INTEGER,
            known_at     TIMESTAMPTZ,
            capture_id   VARCHAR,
            gw           INTEGER,
            kickoff_time TIMESTAMPTZ,
            finished     BOOLEAN
        )
        """
    )
    con.execute(
        """
        CREATE TABLE mart_fact_player_fixture_live (
            season       VARCHAR,
            gw           INTEGER,
            fixture      INTEGER,
            kickoff_time TIMESTAMPTZ,
            code         INTEGER,
            minutes      INTEGER,
            known_at     TIMESTAMPTZ,
            capture_id   VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE mart_fact_player_fixture (
            season       VARCHAR,
            gw           INTEGER,
            fixture      INTEGER,
            kickoff_time TIMESTAMPTZ,
            code         INTEGER,
            minutes      INTEGER
        )
        """
    )
    return con


def _fx(
    *, fixture: int, gw: int, kickoff: datetime, finished: bool, known_at: datetime
) -> tuple[object, ...]:
    return ("2026-27", fixture, known_at, "fx", gw, kickoff, finished)


def _live(
    *, gw: int, fixture: int, kickoff: datetime, known_at: datetime, capture_id: str = "ph"
) -> tuple[object, ...]:
    return ("2026-27", gw, fixture, kickoff, 118748, 90, known_at, capture_id)


def test_preseason_cold_start_passes_with_empty_live_table() -> None:
    # GW1 of 2026-27 is upcoming (finished=False). There is no completed current-season fixture,
    # so the most recent completed gameweek is a prior-season one that lives in the archive. The
    # gate must pass (cold start) even though the live per-fixture table is empty.
    con = _con()
    con.execute(
        "INSERT INTO stg_live_fixture_version VALUES (?, ?, ?, ?, ?, ?, ?)",
        _fx(
            fixture=1,
            gw=1,
            kickoff=datetime(2026, 8, 22, 14, tzinfo=UTC),
            finished=False,
            known_at=datetime(2026, 8, 1, 6, tzinfo=UTC),
        ),
    )
    con.execute(
        "INSERT INTO mart_fact_player_fixture VALUES (?, ?, ?, ?, ?, ?)",
        ("2025-26", 38, 999, datetime(2026, 5, 25, tzinfo=UTC), 118748, 90),
    )
    as_of = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)  # the GW1 deadline, before kickoff

    assessment = assess_prospective_freshness(con, as_of=as_of)
    assert assessment.covered is True
    assert assessment.cold_start is True
    assert assessment.uncovered_season is None
    # No current-season completed GW was found, so nothing is reported as covered either.
    assert assessment.most_recent_completed_season is None


def test_prior_archived_season_completed_gw_is_a_cold_start_not_a_failure() -> None:
    # Rollover edge case: the versioned schedule still shows a finished prior-season fixture
    # (2025-26 GW38), but that season is fully in the archive. Its history is archived, not live,
    # so the gate must pass without requiring a live capture for it -- even though the live
    # per-fixture table holds no 2025-26 row.
    con = _con()
    con.execute(
        "INSERT INTO stg_live_fixture_version VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "2025-26",
            760,
            datetime(2026, 5, 26, 6, tzinfo=UTC),
            "fx",
            38,
            datetime(2026, 5, 25, 15, tzinfo=UTC),
            True,
        ),
    )
    con.execute(
        "INSERT INTO mart_fact_player_fixture VALUES (?, ?, ?, ?, ?, ?)",
        ("2025-26", 38, 760, datetime(2026, 5, 25, 15, tzinfo=UTC), 118748, 90),
    )
    as_of = datetime(2026, 7, 15, 12, tzinfo=UTC)

    assessment = assess_prospective_freshness(con, as_of=as_of)
    assert assessment.covered is True
    assert assessment.cold_start is True
    assert assessment.most_recent_completed_season == "2025-26"
    assert assessment.most_recent_completed_gw == 38


def test_current_season_completed_gw_covered_passes() -> None:
    con = _con()
    con.execute(
        "INSERT INTO stg_live_fixture_version VALUES (?, ?, ?, ?, ?, ?, ?)",
        _fx(
            fixture=1,
            gw=1,
            kickoff=datetime(2026, 8, 15, 14, tzinfo=UTC),
            finished=True,
            known_at=datetime(2026, 8, 16, 6, tzinfo=UTC),
        ),
    )
    captured_at = datetime(2026, 8, 16, 7, 30, tzinfo=UTC)
    con.execute(
        "INSERT INTO mart_fact_player_fixture_live VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        _live(gw=1, fixture=1, kickoff=datetime(2026, 8, 15, 14, tzinfo=UTC), known_at=captured_at),
    )
    as_of = datetime(2026, 8, 20, 12, tzinfo=UTC)

    assessment = assess_prospective_freshness(con, as_of=as_of)
    assert assessment.covered is True
    assert assessment.cold_start is False
    assert assessment.most_recent_completed_season == "2026-27"
    assert assessment.most_recent_completed_gw == 1
    assert assessment.capture_known_at == captured_at


def test_current_season_completed_gw_missing_capture_raises() -> None:
    con = _con()
    con.execute(
        "INSERT INTO stg_live_fixture_version VALUES (?, ?, ?, ?, ?, ?, ?)",
        _fx(
            fixture=1,
            gw=1,
            kickoff=datetime(2026, 8, 15, 14, tzinfo=UTC),
            finished=True,
            known_at=datetime(2026, 8, 16, 6, tzinfo=UTC),
        ),
    )
    # No player-history live rows at all.
    as_of = datetime(2026, 8, 20, 12, tzinfo=UTC)

    with pytest.raises(FreshnessError, match=r"2026-27 GW1") as exc_info:
        require_prospective_freshness(con, as_of=as_of)
    assessment = exc_info.value.assessment
    assert assessment.covered is False
    assert assessment.uncovered_season == "2026-27"
    assert assessment.uncovered_gw == 1
    assert assessment.capture_known_at is None  # live table empty -> nothing seen


def test_future_only_capture_is_not_credited() -> None:
    # A completed GW whose only player-history capture has known_at > as_of is UNCOVERED: the
    # gate never grants future-knowledge credit. The capture is also absent from the "newest
    # seen" staleness figure because it is not known at the deadline.
    con = _con()
    con.execute(
        "INSERT INTO stg_live_fixture_version VALUES (?, ?, ?, ?, ?, ?, ?)",
        _fx(
            fixture=1,
            gw=1,
            kickoff=datetime(2026, 8, 15, 14, tzinfo=UTC),
            finished=True,
            known_at=datetime(2026, 8, 16, 6, tzinfo=UTC),
        ),
    )
    con.execute(
        "INSERT INTO mart_fact_player_fixture_live VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        _live(
            gw=1,
            fixture=1,
            kickoff=datetime(2026, 8, 15, 14, tzinfo=UTC),
            known_at=datetime(2026, 8, 25, 7, tzinfo=UTC),  # captured AFTER as_of
            capture_id="ph_future",
        ),
    )
    as_of = datetime(2026, 8, 20, 12, tzinfo=UTC)

    with pytest.raises(FreshnessError, match=r"2026-27 GW1") as exc_info:
        require_prospective_freshness(con, as_of=as_of)
    assessment = exc_info.value.assessment
    assert assessment.covered is False
    assert assessment.capture_known_at is None  # the only capture is future -> not "seen"


# --------------------------------------------------------------------------------------
# Integration: predict_prospective_minutes refuses when stale, records provenance when fresh
# --------------------------------------------------------------------------------------

_AS_OF = datetime(2026, 8, 29, 17, 30, tzinfo=UTC)  # the GW2 deadline
_POST = datetime(2026, 8, 23, 6, tzinfo=UTC)  # a daily capture taken after GW1 completed
_GW1_KICKOFF = datetime(2026, 8, 22, 14, tzinfo=UTC)
_GW1_CAPTURE = datetime(2026, 8, 23, 7, tzinfo=UTC)  # player-history capture covering GW1


def _teams(*ids: int) -> list[dict[str, object]]:
    return [{"id": i, "name": f"T{i}", "short_name": f"T{i}"} for i in ids]


def _player(pid: int, code: int, element_type: int, team: int) -> dict[str, object]:
    return {
        "id": pid,
        "code": code,
        "web_name": f"P{code}",
        "element_type": element_type,
        "team": team,
        "now_cost": 55,
        "status": "a",
    }


def _fx_payload(
    fid: int, team_h: int, team_a: int, *, event: int, finished: bool, kickoff_iso: str
) -> dict[str, object]:
    return {
        "id": fid,
        "code": 9000 + fid,
        "event": event,
        "finished": finished,
        "kickoff_time": kickoff_iso,
        "team_h": team_h,
        "team_a": team_a,
        "team_h_difficulty": 3,
        "team_a_difficulty": 3,
        "pulse_id": 7000 + fid,
    }


def _bootstrap(
    teams: list[dict[str, object]], players: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "events": [
            {
                "id": 1,
                "name": "Gameweek 1",
                "deadline_time": "2026-08-21T17:30:00Z",
                "finished": True,
            },
            {
                "id": 2,
                "name": "Gameweek 2",
                "deadline_time": "2026-08-29T17:30:00Z",
                "finished": False,
            },
        ],
        "teams": teams,
        "elements": players,
    }


def _populate_prospective_db(con: duckdb.DuckDBPyConnection, *, with_live_capture: bool) -> None:
    """A 2026-27 DB where GW1 has completed (schedule finished) and GW2 is the predicted GW.

    GW1 finished=True is captured in the versioned schedule; prior-season (2025-26) history lives
    in the archive, so 2026-27 is the current/live season. ``with_live_capture`` controls whether
    a player-history capture covering GW1 exists with ``known_at <= as_of``.
    """
    teams = _teams(1, 2)
    players = [_player(11, 1001, 3, 1), _player(12, 1002, 4, 2)]  # MID team 1, FWD team 2
    fixtures = [
        _fx_payload(501, 1, 2, event=1, finished=True, kickoff_iso="2026-08-22T14:00:00Z"),
        _fx_payload(502, 1, 2, event=2, finished=False, kickoff_iso="2026-09-05T14:00:00Z"),
    ]
    write_capture(
        con,
        [
            capture_payload("bootstrap-static", _bootstrap(teams, players)),
            capture_payload("fixtures", fixtures),
        ],  # type: ignore[arg-type]
        season="2026-27",
        gw=1,
        mode="daily",
        captured_at=_POST,
        capture_id="cap-post",
    )

    # Prior-season archive history so 2026-27 is the current season and the model has a window.
    archive_rows = [
        (
            "2025-26",
            gw,
            900 + gw,
            datetime(2025, 8, 1, tzinfo=UTC) + _weeks(gw),
            code,
            position,
            team,
            opponent,
            True,
            90 if gw % 2 else 0,
        )
        for gw in range(1, 16)
        for code, position, team, opponent in [(1001, "MID", 1, 2), (1002, "FWD", 2, 1)]
    ]
    con.executemany(
        """
        INSERT INTO mart_fact_player_fixture (
            season, gw, fixture, kickoff_time, code, position, team_id,
            opponent_team_id, was_home, minutes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        archive_rows,
    )

    if with_live_capture:
        con.executemany(
            """
            INSERT INTO mart_fact_player_fixture_live (
                season, gw, fixture, kickoff_time, code, position, team_id,
                opponent_team_id, was_home, minutes, known_at, capture_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "2026-27",
                    1,
                    501,
                    _GW1_KICKOFF,
                    code,
                    position,
                    team,
                    opponent,
                    True,
                    90,
                    _GW1_CAPTURE,
                    "ph-gw1",
                )
                for code, position, team, opponent in [(1001, "MID", 1, 2), (1002, "FWD", 2, 1)]
            ],
        )


def _weeks(n: int) -> object:
    from datetime import timedelta

    return timedelta(days=7 * n)


def test_predict_prospective_refuses_when_current_season_gw_is_stale() -> None:
    con = initialise(":memory:")
    try:
        _populate_prospective_db(con, with_live_capture=False)
        # GW1 completed in the schedule but no player-history capture -> the job must refuse
        # before emitting, naming the uncovered current-season gameweek.
        with pytest.raises(FreshnessError, match=r"2026-27 GW1"):
            predict_prospective_minutes(
                con, as_of=_AS_OF, season="2026-27", gw=2, db_path=None, repo=None
            )
    finally:
        con.close()


def test_predict_prospective_records_freshness_provenance_when_fresh() -> None:
    con = initialise(":memory:")
    try:
        _populate_prospective_db(con, with_live_capture=True)
        result = predict_prospective_minutes(
            con, as_of=_AS_OF, season="2026-27", gw=2, db_path=None, repo=None
        )
        prov = result.provenance
        assert prov.freshness_cold_start is False
        assert prov.freshness_most_recent_completed_season == "2026-27"
        assert prov.freshness_most_recent_completed_gw == 1
        assert prov.freshness_capture_known_at == _GW1_CAPTURE
        assert prov.row_count == 2  # the job still emitted the GW2 predictions
    finally:
        con.close()


def test_main_exits_nonzero_on_a_stale_current_season_db(tmp_path: Path) -> None:
    # The CLI must surface the freshness failure as a non-zero exit, not a silent forecast.
    import fpl.jobs.prospective_minutes_v1 as job

    db_path = tmp_path / "stale.duckdb"
    con = initialise(str(db_path))
    try:
        _populate_prospective_db(con, with_live_capture=False)
    finally:
        con.close()

    rc = job.main(
        ["--db", str(db_path), "--as-of", _AS_OF.isoformat(), "--season", "2026-27", "--gw", "2"]
    )
    assert rc == 1
