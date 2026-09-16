"""Offline equivalence and provenance guards for the separately named SOT successor."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from fpl.config import config_dir, repo_root
from fpl.features.pit import AsOf, PointInTimeView
from fpl.storage.db import initialise
from fpl.validate import dev_v2_corroborated_sot as runner
from fpl.validate import dev_v2_real_sot as prior
from fpl.validate.metrics import log_score
from fpl.validate.retrospective_sdp import EVIDENCE_CLASS, RetrospectiveBackfillView
from fpl.validate.sot_zero_audit import POLICY, CorroboratedSotBackfillView

from .test_dev_v2_real_sot import START, _add_second_target_fixture, _seed_season


def _contract():
    return runner.load_contract(config_dir() / runner.CONFIG_FILE)


def _audit():
    return {"policy": POLICY, "evidence_class": EVIDENCE_CLASS, "missing_sot_decisions": []}


def _decision(row):
    return {
        **{
            k: row[k]
            for k in (
                "season",
                "fixture",
                "team_code",
                "sdp_match_id",
                "was_home",
                "opponent_team_code",
                "capture_id",
                "payload_sha256",
            )
        },
        "source_known_at": row["source_known_at"].isoformat(),
        "kickoff_time": row["kickoff_time"].isoformat(),
        "raw_field_present": False,
        "interpreted_sot": 0,
        "reason": "shot_accounting_and_fpl_proxy_zero",
    }


@pytest.fixture
def con():
    connection = initialise(":memory:")
    _seed_season(connection)
    yield connection
    connection.close()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("candidate", "retrospective_real_sot_team_environment_v1"),
        ("evidence_class", "strict_prospective"),
        ("promotion_permitted", True),
        ("signals", ["goals", "expected_goals", "touches_in_opposition_box"]),
        ("signals", ["goals", "expected_goals", "shots_on_target_corroborated", "possession"]),
        ("formal_outer_runs", 2),
        ("retain_fixture_distributions", False),
        ("allow_dirty", True),
    ],
)
def test_contract_forbids_scope_expansion(key, value):
    contract, _ = _contract()
    data = contract.model_dump()
    data[key] = value
    with pytest.raises(ValidationError):
        runner.SotZeroEvaluationContract.model_validate(data)


def test_frozen_inputs_and_all_original_estimator_sources_remain_identical():
    contract, base = _contract()
    root = repo_root()
    original = root / "results/v2_real_sot_development.json"
    assert prior.file_sha256(original) == runner.FROZEN_REAL_SOT_SHA
    assert prior.file_sha256(root / "results" / prior.FROZEN_V2_RESULT) == (
        prior.FROZEN_V2_RESULT_SHA256
    )
    for path, digest in json.loads(original.read_bytes())["provenance"]["source_sha256"].items():
        assert prior.file_sha256(root / path) == digest, path
    assert prior.file_sha256(root / contract.policy) == contract.policy_sha256
    assert prior.file_sha256(root / contract.coverage_audit) == contract.coverage_audit_sha256
    assert base.population.eligible_seasons == ("2023-24", "2024-25", "2025-26")
    assert base.development_gate.minimum_relative_log_lift == 0.01


def test_unchanged_inputs_reproduce_control_baseline_and_original_sot_on_toy_only(con):
    contract, base = _contract()
    blocks, slices, folds = runner.run_walk_forward(con, contract, base, _audit())
    old_blocks, old_slices, old_folds, _ = prior.run_walk_forward(con, base)
    assert blocks[base.baseline] == old_blocks[base.baseline]
    assert blocks[base.control.name] == old_blocks[base.control.name]
    assert blocks[contract.candidate] == old_blocks[base.candidate.name]
    assert slices == old_slices
    for field in (
        "control_parameters",
        "candidate_parameters",
        "control_signal_fit",
        "candidate_signal_fit",
    ):
        assert folds[0][field] == old_folds[0][field]
    assert runner.run_walk_forward(con, contract, base, _audit()) == (blocks, slices, folds)


def test_interpreted_zero_changes_only_candidate_history_and_fold_local_scale(con):
    con.execute("""
        UPDATE stg_pl_sdp_team_match_metric SET value_numeric=NULL
        WHERE sdp_match_id=9001 AND side='home' AND provider_field='ontargetScoringAtt'
    """)
    contract, base = _contract()
    original, _, original_folds = runner.run_walk_forward(con, contract, base, _audit())
    history = RetrospectiveBackfillView(con, AsOf(START + timedelta(days=56))).observed_real_sot()
    row = next(r for r in history.iter_rows(named=True) if r["fixture"] == 1001 and r["was_home"])
    audit = _audit()
    audit["missing_sot_decisions"] = [_decision(row)]
    blocks, _, folds = runner.run_walk_forward(con, contract, base, audit)
    assert blocks[base.control.name] == original[base.control.name]
    assert blocks[base.baseline] == original[base.baseline]
    assert folds[0]["retrospective_sot_non_null"] == 16
    assert original_folds[0]["retrospective_sot_non_null"] == 15
    fit = folds[0]["candidate_signal_fit"]["shots_on_target"]
    assert fit["goal_scale"] == pytest.approx(24 / 93)
    assert folds[0]["sot_interpretation_counts"]["shot_accounting_and_fpl_proxy_zero"] == 1
    assert any(
        a.distribution != b.distribution
        for a, b in zip(blocks[contract.candidate], original[contract.candidate], strict=True)
    )
    assert con.execute("""
        SELECT value_numeric FROM stg_pl_sdp_team_match_metric
        WHERE sdp_match_id=9001 AND side='home' AND provider_field='ontargetScoringAtt'
    """).fetchone() == (None,)


def test_null_sot_fallback_is_exact_control(con):
    con.execute("""
        UPDATE stg_pl_sdp_team_match_metric SET value_numeric=NULL
        WHERE provider_field='ontargetScoringAtt'
    """)
    contract, base = _contract()
    blocks, _, folds = runner.run_walk_forward(con, contract, base, _audit())
    assert [r.distribution for r in blocks[contract.candidate]] == [
        r.distribution for r in blocks[base.control.name]
    ]
    assert folds[0]["candidate_parameters"]["rejected_shots_on_target"] == "no measured rows"


def test_target_batch_outcomes_and_sot_do_not_change_same_gw_predictions(con):
    full = RetrospectiveBackfillView(con, AsOf(START + timedelta(days=60))).observed_real_sot()
    _add_second_target_fixture(con)
    contract, base = _contract()
    blocks, _, folds = runner.run_walk_forward(con, contract, base, _audit())
    con.execute("""
        UPDATE mart_fact_team_match_stats_v2
        SET goals=50, goals_allowed=40, expected_goals=30 WHERE gw=9
    """)
    con.execute("""
        UPDATE stg_pl_sdp_team_match_metric SET value_numeric=NULL
        WHERE sdp_match_id=9009 AND provider_field='ontargetScoringAtt'
    """)
    audit = _audit()
    audit["missing_sot_decisions"] = [
        _decision(r) for r in full.iter_rows(named=True) if r["fixture"] == 1009
    ]
    changed, _, changed_folds = runner.run_walk_forward(con, contract, base, audit)
    for name, rows in blocks.items():
        assert len(rows) == 4
        assert [p.distribution for p in rows] == [p.distribution for p in changed[name]]
    assert folds == changed_folds
    assert folds[0]["retrospective_rows"] == 16
    assert folds[0]["same_gameweek_overlap"] == 0


def test_future_truncation_equivalence_for_scaling_and_predictions(con):
    later = initialise(":memory:")
    try:
        _seed_season(later, weeks=10)
        later.execute("""
            UPDATE mart_fact_team_match_stats_v2
            SET goals=70, expected_goals=60, goals_allowed=50 WHERE gw=10
        """)
        later.execute("""
            UPDATE stg_pl_sdp_team_match_metric SET value_numeric=9999
            WHERE sdp_match_id=9010 AND provider_field='ontargetScoringAtt'
        """)
        contract, base = _contract()
        before, _, folds = runner.run_walk_forward(con, contract, base, _audit())
        after, _, later_folds = runner.run_walk_forward(later, contract, base, _audit())
        assert folds[0] == later_folds[0]
        for name, rows in before.items():
            assert rows == [p for p in after[name] if p.gw == 9]
    finally:
        later.close()


def test_stored_pmfs_reconcile_scores_without_refitting(con):
    contract, base = _contract()
    base = base.model_copy(
        update={"population": base.population.model_copy(update={"eligible_seasons": ("2023-24",)})}
    )
    blocks, slices, folds = runner.run_walk_forward(con, contract, base, _audit())
    report = runner.score_run(blocks, slices, folds, contract, base)
    assert report["evidence_class"] == EVIDENCE_CLASS
    assert report["promotion_permitted"] is False
    assert report["rows_scored"] == 2
    assert report["folds"] == 1
    for name in blocks:
        losses = []
        for row in report["fixture_predictions"]:
            pmf = row["distributions"][name]
            assert sum(pmf) == pytest.approx(1, abs=1e-9)
            assert min(pmf) >= 0
            losses.append(log_score(pmf, row["observed_goals"]))
            assert row["as_of"] == folds[0]["as_of"]
        assert sum(losses) / len(losses) == pytest.approx(report["overall"][name]["mean_log_score"])
    assert prior._json_bytes(report)  # No nonfinite values or unserialisable metadata.
    assert report == runner.score_run(blocks, slices, folds, contract, base)


def test_dirty_worktree_refused_before_database_or_scoring(monkeypatch, tmp_path):
    monkeypatch.setattr(prior, "_git", lambda *_args: " M uncommitted.py")
    with pytest.raises(prior.RetrospectiveEvaluationError, match="dirty worktree"):
        runner.run_formal_evaluation(
            db_path=tmp_path / "missing.db",
            results_dir=tmp_path,
            contract_path=tmp_path / "missing.yaml",
        )
    assert not (tmp_path / runner.RESULT_FILE).exists()


def test_new_formal_result_is_write_once(tmp_path):
    path = tmp_path / runner.RESULT_FILE
    path.write_text("already scored", encoding="utf-8")
    with pytest.raises(prior.RetrospectiveEvaluationError, match="write-once"):
        runner.run_formal_evaluation(
            db_path=tmp_path / "missing.db",
            results_dir=tmp_path,
            contract_path=tmp_path / "missing.yaml",
        )
    assert path.read_text(encoding="utf-8") == "already scored"


def test_changed_audit_input_refused_before_scoring(monkeypatch, con):
    contract, base = _contract()
    monkeypatch.setattr(prior, "file_sha256", lambda _path: "0" * 64)
    with pytest.raises(prior.RetrospectiveEvaluationError, match="preregistered input changed"):
        runner.validate_audit(con, contract, base)


def test_changed_live_audit_rejected_even_with_same_frozen_files(monkeypatch, con):
    contract, base = _contract()
    monkeypatch.setattr(runner, "build_audit", lambda *_args: {"raw_values_changed": True})
    with pytest.raises(prior.RetrospectiveEvaluationError, match="raw evidence/interpretation"):
        runner.validate_audit(con, contract, base)


def test_coverage_season_selection_is_fail_closed(monkeypatch, con):
    contract, base = _contract()
    frozen = json.loads((repo_root() / contract.coverage_audit).read_bytes())
    monkeypatch.setattr(runner, "build_audit", lambda *_args: deepcopy(frozen))
    wrong = base.model_copy(
        update={
            "population": base.population.model_copy(
                update={"eligible_seasons": ("2022-23", "2023-24", "2024-25", "2025-26")}
            )
        }
    )
    with pytest.raises(prior.RetrospectiveEvaluationError, match="coverage-selected seasons"):
        runner.validate_audit(con, contract, wrong)


def test_new_capability_has_no_production_import_or_pit_mode():
    assert not issubclass(CorroboratedSotBackfillView, PointInTimeView)
    production = repo_root() / "src/fpl"
    offenders: list[Path] = []
    for path in production.rglob("*.py"):
        if "validate" in path.relative_to(production).parts:
            continue
        text = path.read_text(encoding="utf-8")
        if any(
            token in text
            for token in (
                "sot_zero_audit",
                "shots_on_target_corroborated",
                "dev_v2_corroborated_sot",
            )
        ):
            offenders.append(path)
    assert offenders == []
