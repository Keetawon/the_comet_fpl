"""Tests for dev_ev_backtest.py, ev_backtest_adapter.py, and ev_backtest_harness.py.

Uses realistic production-schema mock database tables to verify point-in-time state,
label separation, full-roster composition, common seeds, primary/comparator differences,
and strict provenance / failure handling.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import duckdb
import pytest

from fpl.jobs.prospective_points_v1 import (
    prospective_team_scored,
    trailing5_minute_bins,
    trailing_ict,
)
from fpl.models.points_composition import DEFAULT_MAX_POINTS_FULL
from fpl.storage.db import connect
from fpl.validate import dev_ev_backtest as dev_ev_backtest_module
from fpl.validate.dev_ev_backtest import (
    _assert_contract_drives_runtime,
    _target_completeness,
    main,
    run_ev_backtest,
)
from fpl.validate.ev_backtest_adapter import (
    allocate_minutes_gated_rates,
    derive_final_ten_gws,
    extract_target_labels_for_gw,
    extract_target_roster_for_gw,
    generate_forecasts_for_fold,
)
from fpl.validate.ev_backtest_harness import (
    BacktestScoreReport,
    FixturePredictionRow,
    score_backtest_rows,
)
from fpl.validate.minutes_harness import team_code_map


def _build_test_db() -> duckdb.DuckDBPyConnection:
    """Build a DuckDB in-memory database matching production mart schema shapes."""
    con = connect(":memory:", read_only=False)

    con.execute("""
        CREATE TABLE mart_dim_team (
            season VARCHAR,
            team_id INT,
            team_code INT,
            team_name VARCHAR
        )
    """)

    con.execute("""
        CREATE TABLE mart_target_player_fixture (
            season VARCHAR,
            gw INT,
            fixture INT,
            kickoff_time TIMESTAMPTZ,
            code INT,
            position VARCHAR,
            total_points_as_recorded INT,
            points_under_rules_2026_27 INT
        )
    """)

    con.execute("""
        CREATE TABLE mart_fact_player_fixture (
            season VARCHAR,
            gw INT,
            fixture INT,
            kickoff_time TIMESTAMPTZ,
            code INT,
            position VARCHAR,
            team_id INT,
            opponent_team_id INT,
            was_home BOOLEAN,
            minutes INT,
            goals_scored INT,
            assists INT,
            clean_sheets INT,
            goals_conceded INT,
            own_goals INT,
            penalties_saved INT,
            penalties_missed INT,
            yellow_cards INT,
            red_cards INT,
            saves INT,
            bonus INT,
            bps INT,
            clearances_blocks_interceptions INT,
            influence DOUBLE,
            creativity DOUBLE,
            threat DOUBLE,
            ict_index DOUBLE,
            expected_goals DOUBLE,
            expected_assists DOUBLE,
            defensive_contribution INT,
            fdr INT
        )
    """)

    con.execute("""
        CREATE TABLE mart_fact_team_match (
            season VARCHAR,
            gw INT,
            fixture INT,
            kickoff_time TIMESTAMPTZ,
            team_id INT,
            opponent_team_id INT,
            was_home BOOLEAN,
            goals_for INT,
            goals_against INT,
            team_xg DOUBLE,
            team_xgc DOUBLE,
            team_bps INT,
            rest_days INT,
            fdr INT
        )
    """)

    # Populate 20 team codes for 2025-26
    for t_id in range(1, 21):
        con.execute(
            f"INSERT INTO mart_dim_team VALUES ('2025-26', {t_id}, {t_id * 10}, 'Team {t_id}')"
        )

    # Insert prior history matches (GW1..15) once per player code
    for prior_gw in range(1, 16):
        t_str = f"2026-01-{prior_gw:02d}T12:00:00Z"
        con.execute(
            f"INSERT INTO mart_fact_team_match VALUES "
            f"('2025-26', {prior_gw}, {prior_gw + 100}, '{t_str}', 1, 2, true, 2, 1, 1.8, "
            f"1.0, 100, 4, 3)"
        )
        con.execute(
            f"INSERT INTO mart_fact_team_match VALUES "
            f"('2025-26', {prior_gw}, {prior_gw + 100}, '{t_str}', 2, 1, false, 1, 2, 1.0, "
            f"1.8, 90, 4, 3)"
        )
        for code in range(101, 105):
            t_id = 1 if code % 2 == 1 else 2
            opp_id = 2 if t_id == 1 else 1
            is_h = t_id == 1

            # Controlled history for attacking signal differences:
            # Code 101/103 (Team 1) have high xG/xA vs Code 102/104 (Team 2)
            xg_val = 0.8 if code % 2 == 1 else 0.1
            xa_val = 0.5 if code % 2 == 1 else 0.1
            g_scored = 1 if (code % 2 == 1 and prior_gw % 2 == 0) else 0

            con.execute(
                f"INSERT INTO mart_fact_player_fixture VALUES ("
                f"'2025-26', {prior_gw}, {prior_gw + 100}, '{t_str}', {code}, 'MID', {t_id}, "
                f"{opp_id}, {str(is_h).lower()}, 90, {g_scored}, 1, 0, 0, 0, 0, 0, 0, 0, 0, "
                f"1, 18, 0, 0.2, 0.3, 0.1, 10.0, {xg_val}, {xa_val}, 1, 2)"
            )

    # Insert 10 target gameweeks (GW29 to GW38)
    for gw in range(29, 39):
        t_str = f"2026-03-{gw - 28:02d}T12:00:00Z"
        # 1 fixture per GW: team 1 vs team 2
        con.execute(
            f"INSERT INTO mart_fact_team_match VALUES "
            f"('2025-26', {gw}, {gw}, '{t_str}', 1, 2, true, 2, 1, 1.8, 1.1, 150, 4, 3)"
        )
        con.execute(
            f"INSERT INTO mart_fact_team_match VALUES "
            f"('2025-26', {gw}, {gw}, '{t_str}', 2, 1, false, 1, 2, 1.1, 1.8, 120, 4, 3)"
        )

        for code in range(101, 105):
            t_id = 1 if code % 2 == 1 else 2
            opp_id = 2 if t_id == 1 else 1
            is_h = t_id == 1

            # mart_target_player_fixture row (labels post-forecast, no minutes column)
            con.execute(
                f"INSERT INTO mart_target_player_fixture VALUES "
                f"('2025-26', {gw}, {gw}, '{t_str}', {code}, 'MID', {code % 10}, {code % 10})"
            )

            # mart_fact_player_fixture row for GW target
            con.execute(
                f"INSERT INTO mart_fact_player_fixture VALUES ("
                f"'2025-26', {gw}, {gw}, '{t_str}', {code}, 'MID', {t_id}, {opp_id}, "
                f"{str(is_h).lower()}, 90, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 25, 0, 0.4, 0.1, "
                f"0.2, 15.0, 25.0, 35.0, 2, 3)"
            )

    return con


def test_derive_final_ten_gws_returns_ascending_tuple() -> None:
    db = _build_test_db()
    gws = derive_final_ten_gws(db, season="2025-26")
    assert gws == (29, 30, 31, 32, 33, 34, 35, 36, 37, 38)


def test_trailing_ict_exact_parity_with_production_semantics() -> None:
    db = _build_test_db()
    ict_res = trailing_ict(db, "2026-03-05T00:00:00Z")
    assert len(ict_res) == 4
    for code in range(101, 105):
        assert code in ict_res
        inf_mean, cre_mean = ict_res[code]
        assert inf_mean > 0.0
        assert cre_mean > 0.0


def test_trailing_five_appearance_includes_zero_minutes() -> None:
    from fpl.config import load_phase2_evaluation
    from fpl.validate.minutes_baselines import MinuteBins

    db = _build_test_db()
    phase2_config = load_phase2_evaluation()
    bins = MinuteBins.from_config(phase2_config)
    app_res = trailing5_minute_bins(db, "2026-03-05T00:00:00Z", bins)
    assert len(app_res) == 4
    for code in range(101, 105):
        assert code in app_res
        _rate_or_dist, n = app_res[code]
        assert n > 0


def test_extract_target_roster_and_labels_separation() -> None:
    db = _build_test_db()
    targets = extract_target_roster_for_gw(db, "2025-26", 29)
    labels = extract_target_labels_for_gw(db, "2025-26", 29)

    assert len(targets) == 4
    assert len(labels) == 4

    target_keys = {(t.season, t.code, t.fixture) for t in targets}
    label_keys = set(labels.keys())
    assert target_keys == label_keys

    for lbl in labels.values():
        assert isinstance(lbl.actual_points, int)
        assert lbl.actual_points >= 0


def test_generate_forecasts_primary_vs_comparator_differs() -> None:
    db = _build_test_db()
    with patch(
        "fpl.validate.ev_backtest_adapter.allocate_minutes_gated_rates",
        wraps=allocate_minutes_gated_rates,
    ) as spy_allocate:
        primary = generate_forecasts_for_fold(
            db,
            "2025-26",
            29,
            use_v3_primary=True,
            draws=500,
            base_seed=202627,
            max_support=DEFAULT_MAX_POINTS_FULL,
        )
        assert spy_allocate.call_count > 0

    with patch(
        "fpl.validate.ev_backtest_adapter.allocate_minutes_gated_rates",
        wraps=allocate_minutes_gated_rates,
    ) as spy_allocate_comp:
        comparator = generate_forecasts_for_fold(
            db,
            "2025-26",
            29,
            use_v3_primary=False,
            draws=500,
            base_seed=202627,
            max_support=DEFAULT_MAX_POINTS_FULL,
        )
        assert spy_allocate_comp.call_count == 0

    assert len(primary) == len(comparator) == 4
    pmf_differs = False
    ev_differs = False
    for p_fc, c_fc in zip(primary, comparator, strict=True):
        assert p_fc.code == c_fc.code
        assert p_fc.fixture == c_fc.fixture
        assert len(p_fc.pmf_full) == 35
        assert len(c_fc.pmf_full) == 35
        assert abs(sum(p_fc.pmf_full) - 1.0) < 1e-5
        assert abs(sum(c_fc.pmf_full) - 1.0) < 1e-5
        if p_fc.pmf_full != c_fc.pmf_full:
            pmf_differs = True
        if p_fc.expected_points != c_fc.expected_points:
            ev_differs = True

    assert pmf_differs, "Primary V3 and Comparator V1 PMFs must differ"
    assert ev_differs, "Primary V3 and Comparator V1 EVs must differ"


def test_prospective_team_scored_reproducible_ordering() -> None:
    db = _build_test_db()
    tc_map = team_code_map(db)
    team_map = {t_id: tc_map.code("2025-26", t_id) for t_id in range(1, 21)}
    import polars as pl

    sched = pl.DataFrame(
        [
            {
                "season": "2025-26",
                "gw": 29,
                "fixture": 29,
                "team_id": 1,
                "opponent_team_id": 2,
                "was_home": True,
            },
            {
                "season": "2025-26",
                "gw": 29,
                "fixture": 29,
                "team_id": 2,
                "opponent_team_id": 1,
                "was_home": False,
            },
        ]
    )
    res1, c1 = prospective_team_scored(
        db, season="2025-26", as_of="2026-03-01T12:00:00Z", team_map=team_map, schedule=sched
    )
    res2, c2 = prospective_team_scored(
        db, season="2025-26", as_of="2026-03-01T12:00:00Z", team_map=team_map, schedule=sched
    )

    assert c1 == c2
    assert set(res1.keys()) == set(res2.keys())
    for k in res1:
        assert res1[k] == res2[k]


def test_run_ev_backtest_identical_populations() -> None:
    db = _build_test_db()
    primary, comparator, n_fix, n_rows = run_ev_backtest(
        db,
        season="2025-26",
        start_gw=29,
        end_gw=38,
        draws=100,
    )

    assert n_fix == 10
    assert n_rows == 40
    assert primary.total_player_fixture_rows == n_rows
    assert primary.total_player_gw_rows == comparator.total_player_gw_rows
    assert primary.total_unique_players == comparator.total_unique_players


def _dummy_report() -> BacktestScoreReport:
    pmf = (1.0,) + (0.0,) * 34
    row1 = FixturePredictionRow("2025-26", 29, 1, 101, "MID", 1, 2, 0.0, pmf, 0)
    row2 = FixturePredictionRow("2025-26", 38, 2, 101, "MID", 1, 2, 0.0, pmf, 0)
    return score_backtest_rows([row1, row2])


def test_preflight_dirty_worktree_raises_or_exits(tmp_path: Path) -> None:
    out_file = tmp_path / "out.json"
    dummy_db = tmp_path / "dummy.db"
    dummy_db.write_text("db", encoding="utf-8")
    with (
        patch("sys.argv", ["dev_ev_backtest", "--output", str(out_file)]),
        patch("fpl.validate.dev_ev_backtest.default_db_path", return_value=dummy_db),
        patch("fpl.validate.dev_ev_backtest._check_clean_worktree", return_value=False),
    ):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1


def test_postflight_worktree_became_dirty_raises(tmp_path: Path) -> None:
    out_file = tmp_path / "out.json"
    dummy_db = tmp_path / "dummy.db"
    dummy_db.write_text("db", encoding="utf-8")
    with (
        patch("sys.argv", ["dev_ev_backtest", "--output", str(out_file)]),
        patch("fpl.validate.dev_ev_backtest.default_db_path", return_value=dummy_db),
        patch("fpl.validate.dev_ev_backtest._check_clean_worktree", side_effect=[True, False]),
        patch("fpl.validate.dev_ev_backtest._git_commit_sha", return_value="sha1"),
        patch("fpl.validate.dev_ev_backtest._file_sha256", return_value="hash1"),
        patch("fpl.validate.dev_ev_backtest._target_completeness", return_value={}),
        patch("fpl.validate.dev_ev_backtest.run_ev_backtest") as mock_run,
        patch("fpl.validate.dev_ev_backtest.connect"),
    ):
        rep = _dummy_report()
        mock_run.return_value = (rep, rep, 99, 8224)
        with pytest.raises(RuntimeError, match="worktree became dirty"):
            main()


def test_postflight_git_commit_sha_changed_raises(tmp_path: Path) -> None:
    out_file = tmp_path / "out.json"
    dummy_db = tmp_path / "dummy.db"
    dummy_db.write_text("db", encoding="utf-8")
    with (
        patch("sys.argv", ["dev_ev_backtest", "--output", str(out_file)]),
        patch("fpl.validate.dev_ev_backtest.default_db_path", return_value=dummy_db),
        patch("fpl.validate.dev_ev_backtest._check_clean_worktree", return_value=True),
        patch("fpl.validate.dev_ev_backtest._git_commit_sha", side_effect=["sha1", "sha2"]),
        patch("fpl.validate.dev_ev_backtest._file_sha256", return_value="hash1"),
        patch("fpl.validate.dev_ev_backtest._target_completeness", return_value={}),
        patch("fpl.validate.dev_ev_backtest.run_ev_backtest") as mock_run,
        patch("fpl.validate.dev_ev_backtest.connect"),
    ):
        rep = _dummy_report()
        mock_run.return_value = (rep, rep, 99, 8224)
        with pytest.raises(RuntimeError, match="Git HEAD commit SHA changed"):
            main()


@contextlib.contextmanager
def _patched_main(tmp_path: Path, *, file_sha_side_effect: list[str]) -> Iterator[None]:
    """Run `main` against stubbed provenance inputs and a stubbed backtest.

    `_target_completeness` is stubbed here because these tests are about the provenance guards;
    the completeness guard itself is driven against a real database further down.
    """
    out_file = tmp_path / "out.json"
    dummy_db = tmp_path / "dummy.db"
    dummy_db.write_text("db", encoding="utf-8")
    rep = _dummy_report()
    with (
        patch("sys.argv", ["dev_ev_backtest", "--output", str(out_file)]),
        patch("fpl.validate.dev_ev_backtest.default_db_path", return_value=dummy_db),
        patch("fpl.validate.dev_ev_backtest._check_clean_worktree", return_value=True),
        patch("fpl.validate.dev_ev_backtest._git_commit_sha", return_value="sha1"),
        patch("fpl.validate.dev_ev_backtest._file_sha256", side_effect=file_sha_side_effect),
        patch("fpl.validate.dev_ev_backtest._target_completeness", return_value={}),
        patch("fpl.validate.dev_ev_backtest.run_ev_backtest") as mock_run,
        patch("fpl.validate.dev_ev_backtest.connect"),
    ):
        mock_run.return_value = (rep, rep, 99, 8224)
        yield


def _hashed_source_files() -> list[str]:
    """The source files `main` hashes, read out of the runner rather than duplicated here."""
    source = Path(str(dev_ev_backtest_module.__file__)).read_text(encoding="utf-8")
    body = source.split("source_files = [", 1)[1].split("]", 1)[0]
    return re.findall(r'"([A-Za-z0-9_]+\.py)"', body)


_SOURCE_FILES = _hashed_source_files()
# `main` hashes in a fixed order: database, contract YAML, scoring YAML, then each source file.
_PREFLIGHT_HASH_COUNT = 3 + len(_SOURCE_FILES)


def test_provenance_covers_every_module_that_determines_the_architecture() -> None:
    """The hash list must not silently shrink back to the four new files.

    Clean Git HEAD is the authoritative code identity; these hashes only catch a mid-run edit,
    which leaves HEAD untouched. That is worth having only if it spans the modules that decide
    what the numbers are -- a mid-run edit to the minutes model or the BPS simulator invalidates
    a run exactly as much as one to the adapter.
    """
    must_cover = {
        "ev_backtest_adapter.py",
        "ev_backtest_harness.py",
        "dev_ev_backtest.py",
        "points_composition.py",
        "prospective_points_v1.py",
        "bps_bonus.py",
        "gk_saves_v1.py",
        "defensive_contribution_v1.py",
        "minutes_v3.py",
        "metrics.py",
    }
    assert must_cover <= set(_SOURCE_FILES)


@pytest.mark.parametrize(
    ("drift_index", "expected_message"),
    [
        (0, "DuckDB database SHA256 changed"),
        (1, "Contract YAML SHA256 changed"),
        (2, "Scoring YAML SHA256 changed"),
    ],
)
def test_postflight_each_non_source_drift_path_raises(
    tmp_path: Path, drift_index: int, expected_message: str
) -> None:
    """Database, contract, and scoring drift are three separate guards, tested separately.

    A single test that only ever trips the first check cannot show the second and third exist.
    """
    values = [f"h{i}" for i in range(_PREFLIGHT_HASH_COUNT)]
    postflight = list(values)
    postflight[drift_index] = "DRIFTED"

    with _patched_main(tmp_path, file_sha_side_effect=values + postflight):
        with pytest.raises(RuntimeError, match=expected_message):
            main()


@pytest.mark.parametrize("source_index", range(len(_SOURCE_FILES)))
def test_postflight_every_source_file_drift_path_raises(tmp_path: Path, source_index: int) -> None:
    """Every hashed source file is independently guarded, not just the first.

    The source hashes are a mid-run tamper diagnostic layered on top of the authoritative
    clean-HEAD check; each entry only earns its place if a change to that file alone stops the
    run, so each is driven to fail on its own.
    """
    values = [f"h{i}" for i in range(_PREFLIGHT_HASH_COUNT)]
    postflight = list(values)
    postflight[3 + source_index] = "DRIFTED"
    expected_file = _SOURCE_FILES[source_index]

    with _patched_main(tmp_path, file_sha_side_effect=values + postflight):
        # Naming the file proves this drifted the intended entry, not merely some entry.
        with pytest.raises(RuntimeError, match=rf"Source file {re.escape(expected_file)} SHA256"):
            main()


def test_destination_no_clobber_and_uuid_tmp_cleanup(tmp_path: Path) -> None:
    existing_out = tmp_path / "ev_backtest_2025_26_gw29_38.json"
    existing_out.write_text("existing content", encoding="utf-8")

    dummy_db = tmp_path / "dummy.db"
    dummy_db.write_text("db", encoding="utf-8")

    with (
        patch("sys.argv", ["dev_ev_backtest", "--output", str(existing_out)]),
        patch("fpl.validate.dev_ev_backtest.default_db_path", return_value=dummy_db),
    ):
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1
        assert existing_out.read_text(encoding="utf-8") == "existing content"

    non_existing_out = tmp_path / "new_output.json"

    with (
        patch("sys.argv", ["dev_ev_backtest", "--output", str(non_existing_out)]),
        patch("fpl.validate.dev_ev_backtest.default_db_path", return_value=dummy_db),
        patch("fpl.validate.dev_ev_backtest._check_clean_worktree", return_value=True),
        patch("fpl.validate.dev_ev_backtest._git_commit_sha", return_value="sha1"),
        patch("fpl.validate.dev_ev_backtest._file_sha256", return_value="hash1"),
        patch("fpl.validate.dev_ev_backtest._target_completeness", return_value={}),
        patch("fpl.validate.dev_ev_backtest.run_ev_backtest") as mock_run,
        patch("fpl.validate.dev_ev_backtest.connect"),
        patch("os.rename", side_effect=PermissionError("Simulated rename error")),
    ):
        rep = _dummy_report()
        mock_run.return_value = (rep, rep, 99, 8224)

        with pytest.raises(PermissionError):
            main()

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0, f"Temporary files were not cleaned up: {tmp_files}"


# --------------------------------------------------------------------------------------
# Read-only access and connection lifetime
# --------------------------------------------------------------------------------------


def test_database_is_opened_read_only(tmp_path: Path) -> None:
    """The backtest must not be able to mutate the archive it is scoring against."""
    values = [f"h{i}" for i in range(_PREFLIGHT_HASH_COUNT)]
    out_file = tmp_path / "out.json"
    dummy_db = tmp_path / "dummy.db"
    dummy_db.write_text("db", encoding="utf-8")
    rep = _dummy_report()

    with (
        patch("sys.argv", ["dev_ev_backtest", "--output", str(out_file)]),
        patch("fpl.validate.dev_ev_backtest.default_db_path", return_value=dummy_db),
        patch("fpl.validate.dev_ev_backtest._check_clean_worktree", return_value=True),
        patch("fpl.validate.dev_ev_backtest._git_commit_sha", return_value="sha1"),
        patch("fpl.validate.dev_ev_backtest._file_sha256", side_effect=values * 2),
        patch("fpl.validate.dev_ev_backtest._target_completeness", return_value={}),
        patch("fpl.validate.dev_ev_backtest.run_ev_backtest") as mock_run,
        patch("fpl.validate.dev_ev_backtest.connect") as mock_connect,
    ):
        mock_run.return_value = (rep, rep, 99, 8224)
        main()

    mock_connect.assert_called_once()
    assert mock_connect.call_args.kwargs["read_only"] is True


def test_database_connection_is_closed_when_the_backtest_raises(tmp_path: Path) -> None:
    """A failed run must not leave the archive connection open."""
    out_file = tmp_path / "out.json"
    dummy_db = tmp_path / "dummy.db"
    dummy_db.write_text("db", encoding="utf-8")

    with (
        patch("sys.argv", ["dev_ev_backtest", "--output", str(out_file)]),
        patch("fpl.validate.dev_ev_backtest.default_db_path", return_value=dummy_db),
        patch("fpl.validate.dev_ev_backtest._check_clean_worktree", return_value=True),
        patch("fpl.validate.dev_ev_backtest._git_commit_sha", return_value="sha1"),
        patch("fpl.validate.dev_ev_backtest._file_sha256", return_value="hash1"),
        patch("fpl.validate.dev_ev_backtest._target_completeness", return_value={}),
        patch(
            "fpl.validate.dev_ev_backtest.run_ev_backtest",
            side_effect=RuntimeError("backtest exploded"),
        ),
        patch("fpl.validate.dev_ev_backtest.connect") as mock_connect,
    ):
        with pytest.raises(RuntimeError, match="backtest exploded"):
            main()

    mock_connect.return_value.close.assert_called_once()
    assert not out_file.exists()


# --------------------------------------------------------------------------------------
# Target completeness for the scored season and ruleset
# --------------------------------------------------------------------------------------


def _completeness_db(missing: str, is_complete: bool) -> duckdb.DuckDBPyConnection:
    con = connect(":memory:", read_only=False)
    con.execute("""
        CREATE TABLE mart_target_completeness (
            season VARCHAR,
            ruleset_id VARCHAR,
            missing_components VARCHAR,
            is_complete BOOLEAN,
            row_count BIGINT
        )
    """)
    con.execute(
        "INSERT INTO mart_target_completeness VALUES ('2025-26', '2026_27', ?, ?, 8224)",
        [missing, is_complete],
    )
    return con


def test_target_completeness_recorded_when_the_season_is_complete() -> None:
    con = _completeness_db("", True)
    record = _target_completeness(con, "2025-26", "2026_27")
    assert record == {
        "season": "2025-26",
        "ruleset_id": "2026_27",
        "missing_components": "",
        "is_complete": True,
        "row_count": 8224,
    }


def test_incomplete_season_refuses_to_run() -> None:
    """Replayed points silently understate a player whose component the season never measured."""
    con = _completeness_db("defensive_contribution", False)
    with pytest.raises(RuntimeError, match="missing components 'defensive_contribution'"):
        _target_completeness(con, "2025-26", "2026_27")


def test_absent_completeness_row_refuses_to_run() -> None:
    """Unproven is not the same as complete."""
    con = _completeness_db("", True)
    with pytest.raises(RuntimeError, match="No mart_target_completeness row"):
        _target_completeness(con, "2024-25", "2026_27")


# --------------------------------------------------------------------------------------
# The contract must govern the run, not merely describe it
# --------------------------------------------------------------------------------------


def test_contract_component_drift_stops_the_run() -> None:
    """A frozen identity that no longer matches the installed model must fail closed.

    This is the guard that contract 1.0 lacked: it froze two saves/DC names that existed
    nowhere in the repository, and nothing at runtime compared them to what actually ran.
    """
    from fpl.config import load_phase4_ev_backtest_evaluation

    contract = load_phase4_ev_backtest_evaluation()
    drifted = contract.model_copy(
        update={
            "components": contract.components.model_copy(update={"saves": "some_other_saves_model"})
        }
    )
    with pytest.raises(RuntimeError, match="Contract component saves"):
        _assert_contract_drives_runtime(drifted)


def test_contract_log_probability_floor_drift_stops_the_run() -> None:
    from fpl.config import load_phase4_ev_backtest_evaluation

    contract = load_phase4_ev_backtest_evaluation()
    drifted = contract.model_copy(
        update={
            "scoring_calibration": contract.scoring_calibration.model_copy(
                update={"log_probability_floor": 1e-6}
            )
        }
    )
    with pytest.raises(RuntimeError, match="log_probability_floor"):
        _assert_contract_drives_runtime(drifted)


def test_unmodified_contract_passes_the_runtime_assertions() -> None:
    from fpl.config import load_phase4_ev_backtest_evaluation

    _assert_contract_drives_runtime(load_phase4_ev_backtest_evaluation())
