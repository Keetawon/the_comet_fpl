"""Offline unit tests for the prediction ledger storage, CLI, and contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

from fpl.artifacts.prospective_points import (
    ContractIdentity,
    ForecastArtifactManifest,
    ForecastArtifactRow,
    LiveInputProvenance,
    ProspectivePointsArtifact,
    write_artifact_atomic,
)
from fpl.jobs.record_forecast import main as record_forecast_main
from fpl.storage.db import connect
from fpl.storage.ledger import (
    DuplicateRunError,
    attach_fixture_outcomes,
    compute_run_id,
    ensure_ledger_tables,
    record_forecast_artifact,
)


def _make_sample_manifest(*, base_seed: int = 42, as_of_hour: int = 17) -> ForecastArtifactManifest:
    return ForecastArtifactManifest(
        as_of=datetime(2026, 8, 21, as_of_hour, 30, tzinfo=UTC),
        season="2026-27",
        gw_from=1,
        gw_to=1,
        row_count=2,
        roster_size=2,
        fixture_count=1,
        monte_carlo_draws=1000,
        base_seed=base_seed,
        fixture_points_support_max=50,
        freshness_cold_start=True,
        worktree_clean=True,
        commit_sha="a" * 40,
        database_sha256="b" * 64,
        contracts={
            "scoring": ContractIdentity(name="scoring_2026_27", version="1.0", sha256="c" * 64)
        },
        component_modes={"attacking": "coupled_v3"},
        live_inputs=LiveInputProvenance(
            bootstrap_capture_id="boot_1",
            bootstrap_known_at=datetime(2026, 8, 21, 10, 0, tzinfo=UTC),
            bootstrap_payload_sha256="d" * 64,
            schedule_capture_ids=("sched_1",),
        ),
    )


def _make_sample_artifact(*, base_seed: int = 42) -> ProspectivePointsArtifact:
    manifest = _make_sample_manifest(base_seed=base_seed)
    row1 = ForecastArtifactRow(
        season="2026-27",
        gw=1,
        code=101,
        web_name="Player A",
        position="FWD",
        team_id=1,
        team_code=10,
        now_cost=80,
        selected_by_percent=15.5,
        availability_status="a",
        chance_of_playing=100.0,
        availability_multiplier=1.0,
        fixture_ids=(1001,),
        kickoff_times=(datetime(2026, 8, 22, 14, 0, tzinfo=UTC),),
        expected_points=1.7,
        availability_adjusted_expected_points=1.7,
        expected_bonus=0.5,
        distribution=(0.1, 0.1, 0.8),  # 0*0.1 + 1*0.1 + 2*0.8 = 1.7
        cold_start_player=False,
        stage_a_league_average_team=False,
        attacking_signal_cold_start=False,
        assist_signal_cold_start=False,
        transferred_no_rescale=False,
    )
    row2 = ForecastArtifactRow(
        season="2026-27",
        gw=1,
        code=102,
        web_name=None,
        position="DEF",
        team_id=2,
        team_code=None,
        now_cost=None,
        selected_by_percent=None,
        availability_status="d",
        chance_of_playing=None,
        availability_multiplier=0.75,
        fixture_ids=(1002,),
        kickoff_times=(datetime(2026, 8, 22, 16, 30, tzinfo=UTC),),
        expected_points=2.0,
        availability_adjusted_expected_points=1.5,  # 0.75 * 2.0 = 1.5
        expected_bonus=0.0,
        distribution=(0.0, 0.0, 1.0),  # 0*0 + 1*0 + 2*1.0 = 2.0
        cold_start_player=True,
        stage_a_league_average_team=False,
        attacking_signal_cold_start=True,
        assist_signal_cold_start=True,
        transferred_no_rescale=False,
    )
    return ProspectivePointsArtifact(manifest=manifest, rows=(row1, row2))


def test_roundtrip_record_forecast() -> None:
    con = connect(":memory:")
    artifact = _make_sample_artifact()
    artifact_sha256 = "e" * 64

    run_id = record_forecast_artifact(con, artifact, artifact_sha256)
    assert run_id == compute_run_id(artifact.manifest)

    run_row = con.execute(
        "SELECT season, gw_from, gw_to, commit_sha, database_sha256, artifact_sha256, "
        "base_seed, row_count FROM ledger_forecast_run WHERE run_id = ?",
        [run_id],
    ).fetchone()
    assert run_row is not None
    assert run_row == ("2026-27", 1, 1, "a" * 40, "b" * 64, artifact_sha256, 42, 2)

    pred_count = con.execute(
        "SELECT count(*) FROM ledger_prediction_player_gameweek WHERE run_id = ?", [run_id]
    ).fetchone()
    assert pred_count is not None and pred_count[0] == 2

    # Verify player 101 distribution float array round-trips exactly
    p1 = con.execute(
        "SELECT web_name, expected_points, distribution FROM ledger_prediction_player_gameweek "
        "WHERE run_id = ? AND code = 101",
        [run_id],
    ).fetchone()
    assert p1 is not None
    assert p1[0] == "Player A"
    assert pytest.approx(p1[1]) == 1.7
    assert p1[2] == [0.1, 0.1, 0.8]


def test_duplicate_run_refusal() -> None:
    con = connect(":memory:")
    artifact = _make_sample_artifact()
    artifact_sha256 = "e" * 64

    record_forecast_artifact(con, artifact, artifact_sha256)

    with pytest.raises(DuplicateRunError, match="already exists"):
        record_forecast_artifact(con, artifact, artifact_sha256)

    runs = con.execute("SELECT count(*) FROM ledger_forecast_run").fetchone()
    preds = con.execute("SELECT count(*) FROM ledger_prediction_player_gameweek").fetchone()
    assert runs is not None and runs[0] == 1
    assert preds is not None and preds[0] == 2


def test_multi_vintage_retention() -> None:
    con = connect(":memory:")
    art1 = _make_sample_artifact(base_seed=42)
    art2 = _make_sample_artifact(base_seed=99)

    run1 = record_forecast_artifact(con, art1, "1" * 64)
    run2 = record_forecast_artifact(con, art2, "2" * 64)

    assert run1 != run2

    runs = con.execute("SELECT count(*) FROM ledger_forecast_run").fetchone()
    preds = con.execute("SELECT count(*) FROM ledger_prediction_player_gameweek").fetchone()
    assert runs is not None and runs[0] == 2
    assert preds is not None and preds[0] == 4

    p101_v1 = con.execute(
        "SELECT expected_points FROM ledger_prediction_player_gameweek "
        "WHERE run_id = ? AND code = 101",
        [run1],
    ).fetchone()
    p101_v2 = con.execute(
        "SELECT expected_points FROM ledger_prediction_player_gameweek "
        "WHERE run_id = ? AND code = 101",
        [run2],
    ).fetchone()

    assert p101_v1 is not None and p101_v2 is not None
    assert p101_v1[0] == p101_v2[0]


def test_null_preservation() -> None:
    con = connect(":memory:")
    artifact = _make_sample_artifact()
    run_id = record_forecast_artifact(con, artifact, "e" * 64)

    p102 = con.execute(
        "SELECT web_name, team_code, now_cost, selected_by_percent, chance_of_playing "
        "FROM ledger_prediction_player_gameweek WHERE run_id = ? AND code = 102",
        [run_id],
    ).fetchone()

    assert p102 is not None
    assert p102[0] is None
    assert p102[1] is None
    assert p102[2] is None
    assert p102[3] is None
    assert p102[4] is None


def test_failure_atomicity() -> None:
    con = connect(":memory:")
    ensure_ledger_tables(con)
    sample = _make_sample_artifact()
    # Inject a duplicate row to trigger a primary key constraint error during batch insert
    corrupted_artifact = ProspectivePointsArtifact(
        manifest=sample.manifest,
        rows=(sample.rows[0], sample.rows[0]),  # Duplicate PK (season, gw, code)
    )

    with pytest.raises(duckdb.ConstraintException):
        record_forecast_artifact(con, corrupted_artifact, "f" * 64)

    runs = con.execute("SELECT count(*) FROM ledger_forecast_run").fetchone()
    preds = con.execute("SELECT count(*) FROM ledger_prediction_player_gameweek").fetchone()
    assert runs is not None and runs[0] == 0
    assert preds is not None and preds[0] == 0


def test_separate_outcome_attachment() -> None:
    con = connect(":memory:")
    outcomes = [
        {
            "code": 101,
            "fixture": 1001,
            "total_points_as_recorded": 8,
            "points_under_rules_2026_27": 8,
        }
    ]

    count = attach_fixture_outcomes(con, "2026-27", outcomes)
    assert count == 1

    row = con.execute(
        "SELECT season, code, fixture, total_points_as_recorded, points_under_rules_2026_27 "
        "FROM ledger_outcome_player_fixture WHERE code = 101"
    ).fetchone()
    assert row is not None
    assert row == ("2026-27", 101, 1001, 8, 8)


def test_run_id_stability_and_sensitivity() -> None:
    m1 = _make_sample_manifest(base_seed=42, as_of_hour=17)
    m2 = _make_sample_manifest(base_seed=42, as_of_hour=17)
    m3 = _make_sample_manifest(base_seed=99, as_of_hour=17)
    m4 = _make_sample_manifest(base_seed=42, as_of_hour=18)

    h1 = compute_run_id(m1)
    h2 = compute_run_id(m2)
    h3 = compute_run_id(m3)
    h4 = compute_run_id(m4)

    assert h1 == h2
    assert h1 != h3
    assert h1 != h4


def test_cli_record_forecast(tmp_path: Path) -> None:
    artifact = _make_sample_artifact()
    artifact_file = tmp_path / "prospective_points.jsonl"
    write_artifact_atomic(artifact_file, artifact)

    db_path = tmp_path / "test_fpl.duckdb"

    # First run succeeds
    rc1 = record_forecast_main([str(artifact_file), "--db", str(db_path)])
    assert rc1 == 0

    # Second run with same artifact is refused
    rc2 = record_forecast_main([str(artifact_file), "--db", str(db_path)])
    assert rc2 == 1
