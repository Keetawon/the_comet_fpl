"""Offline orchestration: reproduce first, one claim, no fits or silent retry."""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from fpl.models.points_composition import ComposedPlayer
from fpl.validate import dev_player_points_synthesis as runner
from tests.test_player_points_synthesis import synthetic_reference


def policy():
    return {
        "expected_folds": 1,
        "expected_rows": 8,
        "expected_fixtures": 1,
        "expected_direct_proxy_rows": 0,
        "external_inputs": {"component_manifest": "a"},
        "seed": 202627,
        "minimum_log_lift": 0.01,
        "maximum_pit80_error": 0.05,
        "maximum_position_log_regression": 0.01,
        "maximum_ranking_regression": 0.01,
        "refutation_relative_regression": 0.01,
    }


@pytest.fixture
def setup(monkeypatch, tmp_path):
    reference = synthetic_reference()
    keys = [(r.target.season, r.target.fixture, r.target.code) for r in reference.rows]
    config = policy()
    calls = []
    monkeypatch.setattr(runner, "load_contract", lambda _: config)
    monkeypatch.setattr(runner, "snapshot", lambda *a: {"git_head": "a" * 40})
    monkeypatch.setattr(runner, "load_component_reference_cache", lambda *a, **k: (reference,))
    monkeypatch.setattr(
        runner,
        "target_labels",
        lambda *a: (
            {key: {"signed_target": i % 2, "scored_target": i % 2} for i, key in enumerate(keys)},
            set(),
        ),
    )
    roles = SimpleNamespace(
        predictions=tuple(
            SimpleNamespace(
                target=SimpleNamespace(
                    season=key[0], fixture=key[1], code=key[2], as_of=reference.as_of
                ),
                recent_measured_starts=1,
                probabilities=(0.25,) * 4,
            )
            for key in keys
        )
    )
    monkeypatch.setattr(runner, "load_role_cache", lambda *a, **k: {("2025-26", 1): roles})
    workload = [
        {
            "season": k[0],
            "fixture": k[1],
            "code": k[2],
            "as_of": reference.as_of.isoformat(),
            "feature_evidence": {"witnessed_nominal_minutes_lower_bound": None},
        }
        for k in keys
    ]
    monkeypatch.setattr(runner, "retained_folds", lambda *a: ({"rows": workload},))
    monkeypatch.setattr(
        runner,
        "load_saves_projection",
        lambda *a: SimpleNamespace(
            source_files={},
            provenance={},
            reproduction={},
            project=lambda *a: {k[2]: (1.0,) + (0.0,) * 10 for k in keys},
        ),
    )
    monkeypatch.setattr(runner, "build_composer_context", lambda: None)
    old = tuple(ComposedPlayer(k[2], (0.5, 0.5) + (0.0,) * 33, 0.0, 0.0) for k in keys)

    def original(*args):
        calls.append("original")
        return old

    def compose(*args, saves_replacements=None):
        calls.append("candidate" if saves_replacements else "zero")
        if saves_replacements:
            assert "claim" in calls
        return old

    def claim(*args):
        calls.append("claim")
        path = tmp_path / "shared-claim.json"
        runner.publish_json(path, {"candidate": runner.NAME})
        return path

    monkeypatch.setattr(runner, "compose_reference_fixture", original)
    monkeypatch.setattr(runner, "compose_synthesis_fixture", compose)
    monkeypatch.setattr(runner, "reserve_program_claim", claim)
    args = {
        "root": tmp_path / "repo",
        "db": tmp_path / "database",
        "output": tmp_path / "run",
        "inputs": {
            k: tmp_path / k
            for k in (
                "component_manifest",
                "minutes_manifest",
                "roles",
                "workload",
                "saves",
                "chance",
            )
        },
    }
    return args, calls, old


def test_complete_run_reproduces_before_claim_and_scores_one_candidate(setup):
    args, calls, _ = setup
    result = runner.run(**args)
    assert calls == ["original", "zero", "claim", "candidate"]
    assert result["completed"] and result["component_fits"] == 0
    assert result["comparator_reproduction"]["maximum_pmf_difference"] == 0
    assert len(result["folds"]) == len(result["control_folds"]) == 1
    assert result["relative_log_lift"] == 0
    assert result["promotion_permitted"] is False
    assert len(result["paired_vs_incumbent"]["row_losses"]) == 8


def test_existing_output_refused_before_source_or_draw(setup, monkeypatch):
    args, calls, _ = setup
    args["output"].mkdir()
    monkeypatch.setattr(runner, "load_contract", lambda *a: pytest.fail("source touched"))
    with pytest.raises(FileExistsError, match="write-once"):
        runner.run(**args)
    assert not calls


def test_dirty_refused_before_loading_reference(setup, monkeypatch):
    args, calls, _ = setup

    def dirty(*args):
        raise ValueError("dirty worktree")

    monkeypatch.setattr(runner, "snapshot", dirty)
    with pytest.raises(ValueError, match="dirty"):
        runner.run(**args)
    assert not calls and not args["output"].exists()


def test_comparator_mismatch_never_reserves_candidate(setup, monkeypatch):
    args, calls, old = setup
    monkeypatch.setattr(
        runner,
        "compose_reference_fixture",
        lambda *a: (replace(old[0], expected_bonus=1.0), *old[1:]),
    )
    with pytest.raises(ValueError, match="reproduction failed"):
        runner.run(**args)
    assert "claim" not in calls and "candidate" not in calls
    assert not (args["root"] / "shared-claim.json").exists()


def test_failure_preserves_single_claim_and_control(setup, monkeypatch):
    args, calls, old = setup

    def fail(*a, saves_replacements=None):
        if saves_replacements:
            raise ArithmeticError("synthetic failure")
        return old

    monkeypatch.setattr(runner, "compose_synthesis_fixture", fail)
    with pytest.raises(ArithmeticError, match="synthetic"):
        runner.run(**args)
    failure = runner.read_json(args["output"] / "failure.json")
    assert failure["retry_permitted"] is False
    assert Path(failure["claim"]).is_file()
    assert (args["output"] / "comparator_reproduction.json").is_file()
    with pytest.raises(FileExistsError, match="write-once"):
        runner.run(**args)
    assert calls.count("claim") == 1


@pytest.mark.parametrize("when", [2, 3])
def test_source_drift_preclaim_or_postflight_never_publishes_success(setup, monkeypatch, when):
    args, calls, _ = setup
    snapshots = []

    def snapshot(*a):
        snapshots.append(1)
        return {"head": "a" if len(snapshots) < when else "b"}

    monkeypatch.setattr(runner, "snapshot", snapshot)
    with pytest.raises(ValueError, match="drift"):
        runner.run(**args)
    assert not (args["output"] / "result.json").exists()
    assert ("claim" in calls) is (when == 3)


@pytest.mark.parametrize("corrupt", ["control", "candidate"])
def test_output_hash_drift_refused(setup, monkeypatch, corrupt):
    args, _, _ = setup
    original = runner.summarize_points

    def scores(rows, **kwargs):
        name = "control-2025-26-gw01.json" if corrupt == "control" else "2025-26-gw01.json"
        (args["output"] / name).write_text("changed", encoding="utf8")
        return original(rows, **kwargs)

    monkeypatch.setattr(runner, "summarize_points", scores)
    with pytest.raises(ValueError, match="output changed"):
        runner.run(**args)
    assert not (args["output"] / "result.json").exists()


def test_retained_upstream_fold_missing_changed_or_escaping_fails(tmp_path):
    result = tmp_path / "result.json"
    result.write_text(
        json.dumps({"completed": True, "folds": [{"file": "../outside.json", "sha256": "a" * 64}]}),
        encoding="utf8",
    )
    with pytest.raises(ValueError, match="path/identity"):
        runner.retained_folds(result)


def test_real_registered_policy_loads_and_freezes_population():
    root = Path(__file__).resolve().parents[1]
    config = runner.load_contract(root)
    assert config["expected_rows"] == 29747
    assert config["expected_folds"] == 38
    assert config["accepted_replacements"] == ["saves"]
    assert config["minimum_log_lift"] == 0.01


@pytest.mark.parametrize(
    ("verdict", "eligible", "accepted"),
    [
        ("SUPPORTED", True, True),
        ("INCONCLUSIVE", False, False),
        ("INELIGIBLE", False, False),
        ("REFUTED", False, False),
        ("SUPPORTED", False, False),
    ],
)
def test_mechanical_acceptance_never_uses_numerical_only_pass(
    tmp_path, verdict, eligible, accepted
):
    path = tmp_path / "result.json"
    runner.publish_json(
        path,
        {
            "completed": True,
            "verdict": verdict,
            "development_synthesis_eligible": eligible,
            "gate": {"threshold": True},
        },
    )
    config = {
        "component_results": {
            "saves": {
                "file": "result.json",
                "sha256": runner.file_sha256(path),
                "candidate": "new",
                "incumbent": "old",
            }
        },
        "accepted_replacements": ["saves"] if accepted else [],
    }
    result = runner.acceptance(tmp_path, config)
    assert result["saves"]["accepted"] is accepted
    assert result["saves"]["used"] == ("new" if accepted else "old")


def test_acceptance_rejects_result_hash_drift(tmp_path):
    path = tmp_path / "result.json"
    runner.publish_json(path, {"completed": True})
    config = {"component_results": {"saves": {"file": "result.json", "sha256": "0" * 64}}}
    with pytest.raises(ValueError, match="decision evidence changed"):
        runner.acceptance(tmp_path, config)
