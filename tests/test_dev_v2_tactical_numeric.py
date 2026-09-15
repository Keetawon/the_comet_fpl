"""Synthetic orchestration only; no tactical real-data fitting or formal claim."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import polars as pl
import pytest
import yaml

from fpl.config import repo_root
from fpl.validate import dev_v2_tactical_numeric as runner
from fpl.validate.tactical_numeric_solver import PoissonSolverError


def _contract_files(tmp_path):
    root = repo_root()
    for name in (runner.CONFIG, runner.legacy.CONFIG, runner.legacy.RESULT):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / name).read_bytes())
    return tmp_path


def test_parent_statistics_and_failure_remain_hash_pinned():
    amendment, parent = runner.load_contract(repo_root())
    assert amendment.candidate != parent.candidate
    assert amendment.parent_preregistration_sha == runner.PARENT_SHA
    assert parent.eligible_seasons == ("2023-24", "2025-26")
    assert (parent.expected_rows, parent.expected_folds, parent.seed) == (1520, 76, 20260904)
    assert parent.minimum_log_lift == parent.minimum_cs_brier_lift == 0.01
    assert parent.goal_penalties == (None, 10.0, 1.0, 0.1)


def test_frozen_numerical_policy_matches_actual_solver_constants():
    from fpl.validate import tactical_numeric_solver as solver

    amendment, _ = runner.load_contract(repo_root())
    for field, constant in (
        ("solver", solver.SOLVER_ID),
        ("maximum_iterations", solver.MAX_ITERATIONS),
        ("maximum_backtracks", solver.MAX_BACKTRACKS),
        ("armijo", solver.ARMIJO),
        ("tolerance", solver.TOLERANCE),
        ("roundoff_multiplier", solver.ROUNDOFF_MULTIPLIER),
        ("small_increment", solver.SMALL_INCREMENT),
    ):
        assert getattr(amendment, field) == constant


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("candidate", runner.legacy.CANDIDATE),
        ("parent_config_sha256", "changed"),
        ("parent_failure_sha256", "changed"),
        ("solver", "other"),
        ("maximum_iterations", 80),
        ("maximum_backtracks", 60),
        ("armijo", 0.1),
        ("tolerance", 1e-6),
        ("roundoff_multiplier", 128),
        ("small_increment", 0.1),
        ("formal_runs", 2),
        ("require_clean_worktree", False),
        ("promotion_permitted", True),
        ("goal_penalties", [0.001]),
        ("minimum_log_lift", 0.0),
    ],
)
def test_no_numerical_or_statistical_policy_override(tmp_path, field, value):
    _contract_files(tmp_path)
    path = tmp_path / runner.CONFIG
    config = yaml.safe_load(path.read_bytes())
    config[field] = value
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError, match=field):
        runner.load_contract(tmp_path)


@pytest.mark.parametrize("path", [runner.legacy.CONFIG, runner.legacy.RESULT])
def test_modified_parent_evidence_refused(tmp_path, path):
    _contract_files(tmp_path)
    (tmp_path / path).write_text("changed", encoding="utf-8")
    with pytest.raises(RuntimeError, match="frozen parent"):
        runner.load_contract(tmp_path)


def test_dirty_refusal_precedes_data_or_incumbent_fitting(tmp_path, monkeypatch):
    def dirty(*args):
        raise RuntimeError("dirty worktree")

    def forbidden(*args, **kwargs):
        pytest.fail("dirty run reached data/fitting")

    monkeypatch.setattr(runner.legacy.scoring, "require_clean_worktree", dirty)
    monkeypatch.setattr(runner, "connect", forbidden)
    monkeypatch.setattr(runner.legacy, "reproduce_incumbent", forbidden)
    with pytest.raises(RuntimeError, match="dirty"):
        runner.run_formal(tmp_path, tmp_path / "absent.duckdb")
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize("artifact", ["result", "claim", "checkpoint"])
def test_consumed_new_identity_refuses_before_database(tmp_path, monkeypatch, artifact):
    monkeypatch.setattr(runner.legacy.scoring, "require_clean_worktree", lambda root: None)
    path = {
        "result": tmp_path / runner.RESULT,
        "claim": runner._claim_path(tmp_path),
        "checkpoint": runner._checkpoint_path(tmp_path),
    }[artifact]
    path.parent.mkdir(parents=True, exist_ok=True)
    if artifact == "checkpoint":
        path.mkdir()
    else:
        path.write_bytes(b"retained")
    with pytest.raises(FileExistsError, match="no second run"):
        runner.run_formal(tmp_path, tmp_path / "absent.duckdb")
    if artifact != "checkpoint":
        assert path.read_bytes() == b"retained"


def test_claim_and_checkpoints_exclusive_and_provenance_bound(tmp_path):
    snapshot = {"git_head": "sha", "config_sha256": "config", "database_sha256": "db"}
    claim = runner.reserve_claim(tmp_path, snapshot)
    claim_bytes = claim.read_bytes()
    with pytest.raises(FileExistsError):
        runner.reserve_claim(tmp_path, snapshot)
    assert claim.read_bytes() == claim_bytes
    checkpoints = runner.Checkpoints(tmp_path, snapshot)
    batch = {"fold": {"season": "2023-24", "gw": 1}, "rows": [{"key": "synthetic"}]}
    checkpoints.write(batch)
    path = checkpoints.directory / "batch-001.json"
    retained = json.loads(path.read_bytes())
    assert retained["candidate"] == runner.CANDIDATE
    assert retained["provenance"] == snapshot
    assert retained["formal_evaluation_completed"] is False
    assert retained["resume_permitted"] is False
    assert checkpoints.manifest[0]["sha256"] == runner.legacy.scoring.file_sha256(path)
    with pytest.raises(FileExistsError):
        runner.Checkpoints(tmp_path, snapshot)
    checkpoints.write({"fold": {"season": "2023-24", "gw": 2}, "rows": []})
    assert len(checkpoints.manifest) == 2
    assert json.loads(path.read_bytes()) == retained


def test_checkpoint_publication_failure_does_not_claim_completed_batch(tmp_path, monkeypatch):
    snapshot = {"git_head": "sha", "config_sha256": "config", "database_sha256": "db"}
    checkpoints = runner.Checkpoints(tmp_path, snapshot)

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(runner, "_publish_result", fail)
    with pytest.raises(OSError, match="disk full"):
        checkpoints.write({"fold": {"season": "2023-24", "gw": 1}, "rows": []})
    assert checkpoints.manifest == []


def test_failure_record_retains_diagnostics_without_false_success(tmp_path):
    @dataclass
    class Diagnostic:
        gradient: float

    snapshot = {"git_head": "sha", "config_sha256": "config", "database_sha256": "db"}
    claim = runner.reserve_claim(tmp_path, snapshot)
    exc = PoissonSolverError("synthetic", {"gradient": float("inf"), "trace": [Diagnostic(1.0)]})
    exc.add_note("2024-25 GW10 kind=goal_x penalty=0.1 input_sha=synthetic")
    report = runner.failure_report(
        exc,
        snapshot=snapshot,
        reproduction={"rows": 1520},
        claim=claim,
        checkpoints=None,
        started="start",
        postflight={"snapshot_unchanged": True},
    )
    json.dumps(report, allow_nan=False)
    assert report["completed"] is False
    assert report["candidate_metrics"] is None
    assert report["restart_permitted"] is False
    assert report["failure"]["notes"] == exc.__notes__
    assert report["failure"]["numerical_state"]["gradient"] == {"nonfinite_diagnostic": "inf"}
    assert report["failure"]["numerical_state"]["trace"] == [{"gradient": 1.0}]


def _mock_formal(tmp_path, monkeypatch):
    amendment, parent = runner.load_contract(repo_root())
    db = tmp_path / "research.duckdb"
    db.write_bytes(b"synthetic placeholder never opened as DuckDB")
    audit = {
        "manifest_sha256": "synthetic-captures",
        "season_eligibility_decision": {"selected_seasons": list(parent.eligible_seasons)},
    }
    for path, content in ((parent.coverage_report, audit), (parent.reference, {})):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(content), encoding="utf-8")
    snapshot = {
        "git_head": "synthetic-clean",
        "config_sha256": "synthetic-config",
        "database_sha256": parent.database_sha256,
    }
    monkeypatch.setattr(runner.legacy.scoring, "require_clean_worktree", lambda root: None)
    monkeypatch.setattr(runner, "load_contract", lambda root: (amendment, parent))
    monkeypatch.setattr(runner, "_snapshot", lambda *args: snapshot)
    original_hash = runner.legacy.scoring.file_sha256
    monkeypatch.setattr(
        runner.legacy.scoring,
        "file_sha256",
        lambda path: (
            parent.coverage_sha256
            if path.as_posix().endswith(parent.coverage_report)
            else parent.reference_sha256
            if path.as_posix().endswith(parent.reference)
            else original_hash(path)
        ),
    )

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(runner, "connect", lambda *args, **kwargs: Connection())
    monkeypatch.setattr(runner, "build_audit", lambda con: audit)
    monkeypatch.setattr(runner.legacy, "reproduce_incumbent", lambda *args: ({}, {"rows": 1520}))
    monkeypatch.setattr(
        runner,
        "load_team_frame",
        lambda *args, **kwargs: pl.DataFrame({"kickoff_time": [datetime(2026, 5, 1, tzinfo=UTC)]}),
    )
    from fpl.validate import tactical_state

    monkeypatch.setattr(tactical_state, "load_observations", lambda *args: ())
    return db


def test_after_claim_failure_auto_publishes_and_refuses_restart(tmp_path, monkeypatch):
    from fpl.validate import tactical_matchup

    db = _mock_formal(tmp_path, monkeypatch)

    def fail(observations, incumbent, seasons, *, goal_fitter, checkpoint):
        assert runner._claim_path(tmp_path).is_file()
        assert goal_fitter.__name__ == "fit_poisson_offset_stable"
        checkpoint({"fold": {"season": "2021-22", "gw": 1}, "rows": []})
        exc = PoissonSolverError("synthetic numerical stop", {"iteration": 40, "penalty": 0.1})
        exc.add_note("synthetic GW2 fit failure")
        raise exc

    monkeypatch.setattr(tactical_matchup, "run_tactical_walk_forward", fail)
    with pytest.raises(PoissonSolverError, match="synthetic numerical stop"):
        runner.run_formal(tmp_path, db)
    report = json.loads((tmp_path / runner.RESULT).read_bytes())
    assert report["artifact_kind"] == "execution_failure"
    assert report["completed"] is False
    assert report["failure"]["numerical_state"]["iteration"] == 40
    assert len(report["complete_batch_checkpoints"]) == 1
    assert report["provenance"]["postflight"]["snapshot_unchanged"] is True
    with pytest.raises(FileExistsError, match="no second run"):
        runner.run_formal(tmp_path, db)


def test_incumbent_reproduction_failure_does_not_claim_candidate(tmp_path, monkeypatch):
    db = _mock_formal(tmp_path, monkeypatch)

    def fail(*args):
        raise ValueError("incumbent PMF differs")

    monkeypatch.setattr(runner.legacy, "reproduce_incumbent", fail)
    with pytest.raises(ValueError, match="incumbent PMF"):
        runner.run_formal(tmp_path, db)
    assert not runner._claim_path(tmp_path).exists()
    assert not (tmp_path / runner.RESULT).exists()


def test_new_report_identity_leaves_parent_scorer_default_unchanged():
    from .test_dev_v2_tactical_matchup import _run, _tiny_contract

    old = runner.legacy.score_experiment(_run(), _tiny_contract())
    new = runner.legacy.score_experiment(_run(), _tiny_contract(), candidate=runner.CANDIDATE)
    assert old["candidate"] == runner.legacy.CANDIDATE
    assert new["candidate"] == runner.CANDIDATE
    assert new["paired_log_uncertainty"]["negative_favours"] == runner.CANDIDATE
    assert new["overall"]["candidate"]["model"] == runner.CANDIDATE
    assert new["relative_goal_log_lift"] == old["relative_goal_log_lift"]
    assert new["relative_clean_sheet_brier_lift"] == old["relative_clean_sheet_brier_lift"]


def test_exact_population_not_only_equal_counts():
    incumbent = {"2023-24:1:1": None, "2023-24:1:2": None, "2024-25:2:1": None}
    rows = [{"key": "2023-24:1:1"}, {"key": "2023-24:1:2"}]
    runner.verify_candidate_population(rows, incumbent, ("2023-24",))
    for changed in ([rows[0], {"key": "2023-24:99:2"}], [rows[0], rows[0]]):
        with pytest.raises(RuntimeError, match="fixture identities"):
            runner.verify_candidate_population(changed, incumbent, ("2023-24",))
