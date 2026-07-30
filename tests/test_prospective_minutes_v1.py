"""Offline tests for the prospective Stage B Candidate V1 minutes job.

In-memory database, synthetic 2026/27 roster (via the live loader) and synthetic prior history.
No network. The candidate is development-only; these tests check the job mechanics, the
double-gameweek-no-collapse rule, and provenance -- never a promotion.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fpl.config import repo_root
from fpl.ingest.live_snapshot import capture_payload, write_capture
from fpl.jobs.prospective_minutes_v1 import GW1_2026_27_DEADLINE, predict_prospective_minutes
from fpl.storage.db import initialise

AS_OF = GW1_2026_27_DEADLINE
CAPTURE_ID = "cap-2026-08-01"
CAPTURED_AT = datetime(2026, 8, 1, 12, tzinfo=UTC)
_HISTORY_BASE = datetime(2025, 8, 1, tzinfo=UTC)
ALPHA_GRID = {1.0, 2.0, 5.0, 10.0, 20.0}


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


def _fixture(fid: int, team_h: int, team_a: int, *, event: int = 1) -> dict[str, object]:
    return {
        "id": fid,
        "code": 9000 + fid,
        "event": event,
        "finished": False,
        "kickoff_time": "2026-08-22T14:00:00Z",
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
                "finished": False,
            }
        ],
        "teams": teams,
        "elements": players,
    }


def _seed_history(
    con, *, codes_positions: list[tuple[int, str, int, int, bool]], n_gw: int = 16
) -> None:
    """Insert `n_gw` observed gameweeks of prior history (>=14 exercises the nested holdout)."""
    rows: list[tuple[object, ...]] = []
    for gw in range(1, n_gw + 1):
        kickoff = _HISTORY_BASE + timedelta(
            days=7 * gw
        )  # all 2025, strictly before AS_OF (2026-08)
        for code, position, team, opponent, was_home in codes_positions:
            minutes = 90 if gw % 2 == 0 else 0  # alternate full/none -> a learnable trailing signal
            rows.append(
                (
                    "2025-26",
                    gw,
                    900 + gw,
                    kickoff,
                    code,
                    position,
                    team,
                    opponent,
                    was_home,
                    minutes,
                )
            )
    con.executemany(
        """
        INSERT INTO mart_fact_player_fixture
            (season, gw, fixture, kickoff_time, code, position, team_id,
             opponent_team_id, was_home, minutes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _load_registry(con, teams, players, fixtures) -> None:
    write_capture(
        con,
        [
            capture_payload("bootstrap-static", _bootstrap(teams, players)),
            capture_payload("fixtures", fixtures),
        ],  # type: ignore[arg-type]
        season="2026-27",
        gw=1,
        mode="daily",
        captured_at=CAPTURED_AT,
        capture_id=CAPTURE_ID,
    )


def test_prospective_gw1_emits_one_distribution_per_player_fixture() -> None:
    con = initialise(":memory:")
    try:
        _load_registry(
            con,
            _teams(1, 2),
            [_player(11, 1001, 3, 1), _player(12, 1002, 4, 2)],  # MID team 1, FWD team 2
            [_fixture(501, 1, 2)],
        )
        _seed_history(con, codes_positions=[(1001, "MID", 1, 2, True), (1002, "FWD", 2, 1, False)])

        result = predict_prospective_minutes(
            con, as_of=AS_OF, season="2026-27", gw=1, db_path=None, repo=repo_root()
        )
        prov = result.provenance

        # Roster + fixture + row accounting.
        assert prov.candidate == "shrunk_trailing_5_player_minutes_v1"
        assert prov.registry_capture_ids == (CAPTURE_ID,)
        assert prov.roster_size == 2
        assert prov.fixture_count == 1
        assert prov.row_count == 2
        assert {p.code for p in result.predictions} == {1001, 1002}

        # alpha comes from the registered nested procedure, not a frozen value.
        assert "registered nested inner walk-forward" in prov.alpha_source
        assert prov.selected_alpha in ALPHA_GRID
        assert prov.used_inner_holdout is True  # 16 history gameweeks >= 14

        # Each row is a proper four-bin distribution.
        for pred in result.predictions:
            assert abs(pred.p_0 + pred.p_1_59 + pred.p_60_89 + pred.p_90 - 1.0) < 1e-12
        means = result.bin_means
        assert abs(sum(means) - 1.0) < 1e-12

        # Provenance fingerprints: git HEAD + config are real; archive is None (in-memory db).
        expected_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root(),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert prov.commit_sha == expected_head
        assert prov.config_sha256 is not None and len(prov.config_sha256) == 64
        assert prov.archive_sha256 is None
        assert "DEVELOPMENT-ONLY" in prov.label
    finally:
        con.close()


def test_prospective_double_gameweek_fixtures_are_not_collapsed() -> None:
    """Two GW1 fixtures for one club -> two rows, same distribution, not collapsed."""
    con = initialise(":memory:")
    try:
        # Team 1 plays twice in GW1 (a double gameweek); team 2 plays once.
        _load_registry(
            con,
            _teams(1, 2, 3),
            [_player(11, 1001, 3, 1), _player(12, 1002, 4, 2)],
            [_fixture(501, 1, 2), _fixture(502, 1, 3)],
        )
        _seed_history(con, codes_positions=[(1001, "MID", 1, 2, True), (1002, "FWD", 2, 1, False)])

        result = predict_prospective_minutes(
            con, as_of=AS_OF, season="2026-27", gw=1, db_path=None, repo=None
        )
        prov = result.provenance
        assert prov.fixture_count == 2
        # 1001 (team 1, two fixtures) -> 2 rows; 1002 (team 2, one fixture) -> 1 row. Not collapsed.
        assert prov.row_count == 3
        by_code: dict[int, list] = {}
        for pred in result.predictions:
            by_code.setdefault(pred.code, []).append(pred)
        assert {pred.fixture for pred in by_code[1001]} == {501, 502}
        assert len(by_code[1002]) == 1
        # Identical distribution across the two fixtures
        # (contract: double_gameweek_same_distribution).
        a, b = by_code[1001]
        assert (a.p_0, a.p_1_59, a.p_60_89, a.p_90) == (b.p_0, b.p_1_59, b.p_60_89, b.p_90)
        assert a.fixture != b.fixture  # but they are distinct (code, fixture) rows
    finally:
        con.close()


def test_prospective_archive_fingerprint_when_db_path_is_a_file(tmp_path: Path) -> None:
    """A real file db_path is fingerprinted (read-only open still allows hashing the file)."""
    db_path = tmp_path / "prospective.duckdb"
    con = initialise(str(db_path))
    try:
        _load_registry(
            con,
            _teams(1, 2),
            [_player(11, 1001, 3, 1), _player(12, 1002, 4, 2)],
            [_fixture(501, 1, 2)],
        )
        _seed_history(con, codes_positions=[(1001, "MID", 1, 2, True), (1002, "FWD", 2, 1, False)])
    finally:
        con.close()

    # Re-open read-only, as the job's caller does, and fingerprint the file.
    import duckdb

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        result = predict_prospective_minutes(
            con, as_of=AS_OF, season="2026-27", gw=1, db_path=db_path, repo=None
        )
    finally:
        con.close()
    assert result.provenance.archive_sha256 is not None
    assert len(result.provenance.archive_sha256) == 64
    assert result.provenance.row_count == 2
