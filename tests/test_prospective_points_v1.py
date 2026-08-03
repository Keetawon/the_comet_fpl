"""Offline tests for the prospective full-points xP job.

In-memory database, a synthetic 2026/27 roster (via the live loader), synthetic prior history, and
synthetic team-match history for the prospective Stage A prediction. No network. The job is
development-only; these tests check mechanics -- row accounting, valid distributions, the
availability overlay, reproducibility, multi-gameweek totals, and provenance -- never a promotion.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta

from fpl.config import repo_root
from fpl.ingest.live_snapshot import capture_payload, write_capture
from fpl.jobs.prospective_points_v1 import (
    GW1_2026_27_DEADLINE,
    _expected_points,
    availability_multiplier,
    predict_prospective_points,
    resolve_assist_signal_kind,
    resolve_share_signal_kind,
    season_boundary_minutes,
)
from fpl.storage.db import initialise

_XG_COVERED = frozenset({"2023-24", "2024-25", "2025-26"})

AS_OF = GW1_2026_27_DEADLINE
CAPTURE_ID = "cap-2026-08-02"
CAPTURED_AT = datetime(2026, 8, 2, 8, tzinfo=UTC)
_HISTORY_BASE = datetime(2025, 8, 1, tzinfo=UTC)

# team_id -> team_code, shared by the bootstrap payload and the seeded archive dimension so the
# prospective Stage A prediction keys line up across the season boundary.
TEAM_CODE = {1: 101, 2: 102, 3: 103}


def _teams(*ids: int) -> list[dict[str, object]]:
    return [{"id": i, "code": TEAM_CODE[i], "name": f"T{i}", "short_name": f"T{i}"} for i in ids]


def _player(
    pid: int,
    code: int,
    element_type: int,
    team: int,
    *,
    status: str = "a",
    chance: int | None = None,
) -> dict[str, object]:
    return {
        "id": pid,
        "code": code,
        "web_name": f"P{code}",
        "element_type": element_type,
        "team": team,
        "now_cost": 55,
        "status": status,
        "chance_of_playing_next_round": chance,
    }


def _fixture(fid: int, team_h: int, team_a: int, *, event: int = 1) -> dict[str, object]:
    return {
        "id": fid,
        "code": 9000 + fid,
        "event": event,
        "finished": False,
        "kickoff_time": f"2026-08-{21 + event}T14:00:00Z",
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
            },
            {
                "id": 2,
                "name": "Gameweek 2",
                "deadline_time": "2026-08-28T17:30:00Z",
                "finished": False,
            },
        ],
        "teams": teams,
        "elements": players,
    }


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


def _seed_dim_team(con) -> None:
    rows = [
        ("2025-26", tid, code, f"T{tid}", f"T{tid}", 1000 + tid) for tid, code in TEAM_CODE.items()
    ]
    con.executemany(
        "INSERT INTO mart_dim_team (season, team_id, team_code, team_name, short_name, pulse_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )


def _seed_history(con, *, players: list[tuple[int, str, int, int, bool]], n_gw: int = 14) -> None:
    """`n_gw` observed 2025-26 gameweeks (>=14 exercises nested selection), strictly before AS_OF.

    Each `players` entry is (code, position, team_id, opponent_team_id, was_home). Rows carry goals,
    assists, bps, bonus, influence and creativity so every component (and the BPS residual) has real
    training signal; team-match history for the same fixtures feeds the prospective Stage A fit.
    """
    pf_rows: list[tuple[object, ...]] = []
    tm_rows: list[tuple[object, ...]] = []
    seen_team_fixture: set[tuple[int, int]] = set()
    for gw in range(1, n_gw + 1):
        kickoff = _HISTORY_BASE + timedelta(days=7 * gw)
        fixture = 900 + gw
        for code, position, team, opponent, was_home in players:
            minutes = 90 if gw % 2 == 0 else 60
            goals = 1 if (position in {"MID", "FWD"} and gw % 3 == 0) else 0
            assists = 1 if (position == "MID" and gw % 4 == 0) else 0
            xa = {"MID": 0.30, "FWD": 0.10, "DEF": 0.15, "GK": 0.0}[position]
            pf_rows.append(
                (
                    "2025-26",
                    gw,
                    fixture,
                    kickoff,
                    code,
                    position,
                    team,
                    opponent,
                    was_home,
                    minutes,
                    goals,
                    assists,
                    0,
                    1,
                    2 if position == "GK" else 0,
                    0,
                    18 + goals * 6,
                    gw % 3,
                    20.0 + gw,
                    15.0 + gw,
                    10.0 + gw,
                    xa,
                )
            )
            key = (team, fixture)
            if key not in seen_team_fixture:
                seen_team_fixture.add(key)
                tm_rows.append(
                    ("2025-26", gw, fixture, kickoff, team, opponent, was_home, 1, 1, 1.2, 1.1, 3)
                )
    con.executemany(
        """
        INSERT INTO mart_fact_player_fixture
            (season, gw, fixture, kickoff_time, code, position, team_id, opponent_team_id,
             was_home, minutes, goals_scored, assists, clean_sheets, goals_conceded, saves,
             penalties_saved, bps, bonus, influence, creativity, threat, expected_assists)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        pf_rows,
    )
    con.executemany(
        """
        INSERT INTO mart_fact_team_match
            (season, gw, fixture, kickoff_time, team_id, opponent_team_id, was_home,
             goals_for, goals_against, team_xg, team_xgc, fdr)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        tm_rows,
    )


def _basic_db(players, fixtures, history):
    con = initialise(":memory:")
    team_ids = sorted({t for f in fixtures for t in (f["team_h"], f["team_a"])})
    _load_registry(con, _teams(*team_ids), players, fixtures)
    _seed_dim_team(con)
    _seed_history(con, players=history)
    return con


def test_emits_full_distribution_per_player_fixture() -> None:
    con = _basic_db(
        players=[_player(11, 1001, 3, 1), _player(12, 1002, 4, 2)],
        fixtures=[_fixture(501, 1, 2)],
        history=[(1001, "MID", 1, 2, True), (1002, "FWD", 2, 1, False)],
    )
    try:
        result = predict_prospective_points(
            con, as_of=AS_OF, season="2026-27", gw_from=1, gw_to=1, db_path=None, repo=repo_root()
        )
        assert result.roster_size == 2
        assert result.fixture_count == 1
        assert len(result.records) == 2
        assert {r.code for r in result.records} == {1001, 1002}
        for r in result.records:
            assert abs(sum(r.distribution) - 1.0) < 1e-9
            assert r.expected_points > 0.0
            assert abs(r.expected_points - _expected_points(r.distribution)) < 1e-12
            assert r.expected_bonus >= 0.0
            # both scheduled teams have archive history -> Stage A predicted, not league fallback
            assert r.stage_a_league_average_team is False
        assert set(result.component_names) == {
            "minutes",
            "goals",
            "assists",
            "team_clean_sheet",
            "saves",
            "defensive_contribution",
            "bonus",
        }
        # Per-player totals reconcile with the per-record expected points.
        totals = {t.code: t for t in result.player_totals}
        assert totals[1001].fixtures == 1
        assert (
            abs(
                totals[1001].expected_points
                - _expected_points(next(r for r in result.records if r.code == 1001).distribution)
            )
            < 1e-12
        )
        expected_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root(),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert result.commit_sha == expected_head
        assert result.config_sha256 is not None and len(result.config_sha256) == 64
        assert result.archive_sha256 is None
    finally:
        con.close()


def test_availability_overlay_scales_expected_points_only() -> None:
    con = _basic_db(
        players=[
            _player(11, 1001, 3, 1, status="a"),
            _player(12, 1002, 4, 2, status="i"),
            _player(13, 1003, 3, 2, status="d", chance=25),
        ],
        fixtures=[_fixture(501, 1, 2)],
        history=[
            (1001, "MID", 1, 2, True),
            (1002, "FWD", 2, 1, False),
            (1003, "MID", 2, 1, False),
        ],
    )
    try:
        result = predict_prospective_points(
            con, as_of=AS_OF, season="2026-27", gw_from=1, gw_to=1, db_path=None, repo=None
        )
        by_code = {r.code: r for r in result.records}
        # Available: overlay is a no-op.
        assert by_code[1001].availability_multiplier == 1.0
        assert by_code[1001].availability_adjusted_points == by_code[1001].expected_points
        # Injured: overlay zeroes the adjusted total but leaves the raw distribution/expectation.
        assert by_code[1002].availability_multiplier == 0.0
        assert by_code[1002].expected_points > 0.0
        assert by_code[1002].availability_adjusted_points == 0.0
        # Doubtful with a published chance: scaled by chance/100.
        assert by_code[1003].availability_multiplier == 0.25
        assert (
            abs(by_code[1003].availability_adjusted_points - 0.25 * by_code[1003].expected_points)
            < 1e-12
        )
    finally:
        con.close()


def test_reproducible_bit_for_bit() -> None:
    def run():
        con = _basic_db(
            players=[_player(11, 1001, 3, 1), _player(12, 1002, 4, 2)],
            fixtures=[_fixture(501, 1, 2)],
            history=[(1001, "MID", 1, 2, True), (1002, "FWD", 2, 1, False)],
        )
        try:
            return predict_prospective_points(
                con, as_of=AS_OF, season="2026-27", gw_from=1, gw_to=1, db_path=None, repo=None
            )
        finally:
            con.close()

    a = {r.code: r.distribution for r in run().records}
    b = {r.code: r.distribution for r in run().records}
    assert a.keys() == b.keys()
    for code in a:
        assert a[code] == b[code]


def test_multi_gameweek_horizon_totals() -> None:
    # Team 1 plays GW1 and GW2; team 2 plays only GW1. The horizon total sums a player's fixtures.
    con = _basic_db(
        players=[_player(11, 1001, 3, 1), _player(12, 1002, 4, 2)],
        fixtures=[_fixture(501, 1, 2, event=1), _fixture(502, 1, 3, event=2)],
        history=[(1001, "MID", 1, 2, True), (1002, "FWD", 2, 1, False)],
    )
    try:
        result = predict_prospective_points(
            con, as_of=AS_OF, season="2026-27", gw_from=1, gw_to=2, db_path=None, repo=None
        )
        totals = {t.code: t for t in result.player_totals}
        assert totals[1001].fixtures == 2
        assert totals[1002].fixtures == 1
        per_player_records = [r.expected_points for r in result.records if r.code == 1001]
        assert len(per_player_records) == 2
        assert abs(totals[1001].expected_points - sum(per_player_records)) < 1e-12
        # Totals are ranked descending by raw expected points.
        ordered = [t.expected_points for t in result.player_totals]
        assert ordered == sorted(ordered, reverse=True)
    finally:
        con.close()


def test_team_coupled_v3_is_default_and_differs_from_independent_v1() -> None:
    # A club with two attackers: the team-coupled path (V3, default) allocates the Stage A team
    # total between them, so at least one player's distribution differs from the independent V1.
    def run(attacking: str):
        con = _basic_db(
            players=[_player(11, 1001, 3, 1), _player(12, 1002, 4, 1), _player(13, 1003, 4, 2)],
            fixtures=[_fixture(501, 1, 2)],
            history=[
                (1001, "MID", 1, 2, True),
                (1002, "FWD", 1, 2, True),
                (1003, "FWD", 2, 1, False),
            ],
        )
        try:
            return predict_prospective_points(
                con,
                as_of=AS_OF,
                season="2026-27",
                gw_from=1,
                gw_to=1,
                attacking=attacking,
                db_path=None,
                repo=None,
            )
        finally:
            con.close()

    v3 = run("v3")
    v1 = run("v1")
    assert v3.attacking_mode == "v3"
    assert v1.attacking_mode == "v1"
    # Default is the team-coupled path.
    default = run("v3")
    assert default.attacking_mode == "v3"
    v3_pts = {r.code: r.expected_points for r in v3.records}
    v1_pts = {r.code: r.expected_points for r in v1.records}
    assert v3_pts.keys() == v1_pts.keys()
    assert any(abs(v3_pts[c] - v1_pts[c]) > 1e-9 for c in v3_pts)
    # Both modes still produce valid distributions.
    for r in list(v3.records) + list(v1.records):
        assert abs(sum(r.distribution) - 1.0) < 1e-9


def test_rejects_unknown_attacking_mode() -> None:
    con = _basic_db(
        players=[_player(11, 1001, 3, 1), _player(12, 1002, 4, 2)],
        fixtures=[_fixture(501, 1, 2)],
        history=[(1001, "MID", 1, 2, True), (1002, "FWD", 2, 1, False)],
    )
    try:
        import pytest

        with pytest.raises(ValueError, match="attacking must be"):
            predict_prospective_points(
                con, as_of=AS_OF, season="2026-27", attacking="v2", db_path=None, repo=None
            )
    finally:
        con.close()


def test_season_boundary_minutes_lifts_rested_nailed_starter() -> None:
    # Model says a 0.55 chance of not playing (rested in dead rubbers), but the player was nailed
    # last season (0.92). At an August target the correction blends 0.7*long + 0.3*recent.
    dist = (0.55, 0.05, 0.10, 0.30)
    out = season_boundary_minutes(dist, prior_rate=0.92, prior_n=38, target_month=8)
    assert abs(sum(out) - 1.0) < 1e-12
    p_play = 1.0 - out[0]
    assert abs(p_play - (0.7 * 0.92 + 0.3 * 0.45)) < 1e-9
    # The when-playing minute shape (ratios among the playing bins) is preserved.
    assert abs(out[3] / out[2] - dist[3] / dist[2]) < 1e-9
    assert abs(out[2] / out[1] - dist[2] / dist[1]) < 1e-9


def test_season_boundary_minutes_is_a_noop_off_boundary_or_without_history() -> None:
    dist = (0.55, 0.05, 0.10, 0.30)
    # In-season month: weight is zero, distribution unchanged.
    assert season_boundary_minutes(dist, prior_rate=0.92, prior_n=38, target_month=1) == dist
    # Too few prior-season rows to trust the long rate.
    assert season_boundary_minutes(dist, prior_rate=0.92, prior_n=3, target_month=8) == dist
    # No prior-season rate at all.
    assert season_boundary_minutes(dist, prior_rate=None, prior_n=0, target_month=8) == dist


def test_appearance_seasonal_is_default_and_mode_is_validated() -> None:
    con = _basic_db(
        players=[_player(11, 1001, 3, 1), _player(12, 1002, 4, 2)],
        fixtures=[_fixture(501, 1, 2)],
        history=[(1001, "MID", 1, 2, True), (1002, "FWD", 2, 1, False)],
    )
    try:
        default = predict_prospective_points(
            con, as_of=AS_OF, season="2026-27", gw_from=1, gw_to=1, db_path=None, repo=None
        )
        assert default.appearance_mode == "seasonal"
        model = predict_prospective_points(
            con,
            as_of=AS_OF,
            season="2026-27",
            gw_from=1,
            gw_to=1,
            appearance="model",
            db_path=None,
            repo=None,
        )
        assert model.appearance_mode == "model"
        for r in list(default.records) + list(model.records):
            assert abs(sum(r.distribution) - 1.0) < 1e-9

        import pytest

        with pytest.raises(ValueError, match="appearance must be"):
            predict_prospective_points(
                con, as_of=AS_OF, season="2026-27", appearance="nope", db_path=None, repo=None
            )
    finally:
        con.close()


def test_resolve_share_signal_kind() -> None:
    # auto: a future season (after the latest covered) uses xG, as does a covered season.
    assert resolve_share_signal_kind("2026-27", _XG_COVERED, "auto") == "expected_goals"
    assert resolve_share_signal_kind("2024-25", _XG_COVERED, "auto") == "expected_goals"
    # auto: a genuinely pre-xG season falls back to threat.
    assert resolve_share_signal_kind("2021-22", _XG_COVERED, "auto") == "threat"
    # forced modes ignore the season.
    assert resolve_share_signal_kind("2026-27", _XG_COVERED, "threat") == "threat"
    assert resolve_share_signal_kind("2021-22", _XG_COVERED, "xg") == "expected_goals"
    # empty covered set: auto cannot claim an xG era, falls back to threat.
    assert resolve_share_signal_kind("2026-27", frozenset(), "auto") == "threat"


def test_share_signal_mode_is_validated_and_recorded() -> None:
    con = _basic_db(
        players=[_player(11, 1001, 3, 1), _player(12, 1002, 4, 2)],
        fixtures=[_fixture(501, 1, 2)],
        history=[(1001, "MID", 1, 2, True), (1002, "FWD", 2, 1, False)],
    )
    try:
        # Default auto on a future season resolves to xG and is recorded.
        default = predict_prospective_points(
            con, as_of=AS_OF, season="2026-27", gw_from=1, gw_to=1, db_path=None, repo=None
        )
        assert default.share_signal_kind == "expected_goals"
        threat = predict_prospective_points(
            con,
            as_of=AS_OF,
            season="2026-27",
            gw_from=1,
            gw_to=1,
            share_signal="threat",
            db_path=None,
            repo=None,
        )
        assert threat.share_signal_kind == "threat"

        import pytest

        with pytest.raises(ValueError, match="share_signal must be"):
            predict_prospective_points(
                con, as_of=AS_OF, season="2026-27", share_signal="bad", db_path=None, repo=None
            )
    finally:
        con.close()


def test_resolve_assist_signal_kind() -> None:
    assert resolve_assist_signal_kind("2026-27", _XG_COVERED, "auto") == "expected_assists"
    assert resolve_assist_signal_kind("2024-25", _XG_COVERED, "auto") == "expected_assists"
    assert resolve_assist_signal_kind("2021-22", _XG_COVERED, "auto") == "creativity"
    assert resolve_assist_signal_kind("2026-27", _XG_COVERED, "threat") == "creativity"
    assert resolve_assist_signal_kind("2021-22", _XG_COVERED, "xg") == "expected_assists"
    assert resolve_assist_signal_kind("2026-27", frozenset(), "auto") == "creativity"


def test_assists_coupled_is_default_and_differs_from_v1() -> None:
    # Two players of different xA on one club: the coupled path allocates the club's assisted-goal
    # total by xA-share, so at least one player's distribution differs from independent V1.
    def run(mode: str):
        con = _basic_db(
            players=[_player(11, 1001, 3, 1), _player(12, 1002, 4, 1), _player(13, 1003, 4, 2)],
            fixtures=[_fixture(501, 1, 2)],
            history=[
                (1001, "MID", 1, 2, True),
                (1002, "FWD", 1, 2, True),
                (1003, "FWD", 2, 1, False),
            ],
        )
        try:
            return predict_prospective_points(
                con,
                as_of=AS_OF,
                season="2026-27",
                gw_from=1,
                gw_to=1,
                assists=mode,
                db_path=None,
                repo=None,
            )
        finally:
            con.close()

    coupled = run("coupled")
    v1 = run("v1")
    assert coupled.assists_mode == "coupled"
    assert v1.assists_mode == "v1"
    default = run("coupled")
    assert default.assists_mode == "coupled"
    c_pts = {r.code: r.expected_points for r in coupled.records}
    v_pts = {r.code: r.expected_points for r in v1.records}
    assert c_pts.keys() == v_pts.keys()
    assert any(abs(c_pts[c] - v_pts[c]) > 1e-9 for c in c_pts)
    for r in list(coupled.records) + list(v1.records):
        assert abs(sum(r.distribution) - 1.0) < 1e-9

    import pytest

    con = _basic_db(
        players=[_player(11, 1001, 3, 1)],
        fixtures=[_fixture(501, 1, 2)],
        history=[(1001, "MID", 1, 2, True)],
    )
    try:
        with pytest.raises(ValueError, match="assists must be"):
            predict_prospective_points(
                con, as_of=AS_OF, season="2026-27", assists="nope", db_path=None, repo=None
            )
    finally:
        con.close()


def test_availability_multiplier_rules() -> None:
    assert availability_multiplier("a", None) == 1.0
    assert availability_multiplier("i", None) == 0.0
    assert availability_multiplier("s", None) == 0.0
    assert availability_multiplier("u", None) == 0.0
    assert availability_multiplier("n", None) == 0.0
    assert availability_multiplier("d", None) == 0.5  # doubtful, no published percentage
    assert availability_multiplier("d", 75.0) == 0.75  # an explicit chance always wins
    assert availability_multiplier("a", 0.0) == 0.0
    assert availability_multiplier("i", 100.0) == 1.0
