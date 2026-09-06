"""Offline orchestration and evidence guards for weekly inner-selection development."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from dataclasses import replace

import pytest
from pydantic import ValidationError

from fpl.config import config_dir, repo_root
from fpl.models.football_engine_v2 import MultiSignalTeamEngine
from fpl.storage.db import initialise
from fpl.validate import dev_v2_real_sot as prior
from fpl.validate import dev_v2_weekly_inner as runner
from fpl.validate.metrics import log_score, poisson_pmf
from fpl.validate.v2_environment_harness import Prediction, load_team_frame, observed_folds
from fpl.validate.weekly_inner_selection import NAME, SIGNALS

from .test_dev_v2_real_sot import _add_second_target_fixture, _seed_season


@pytest.fixture
def con():
    connection = initialise(":memory:")
    _seed_season(connection)
    yield connection
    connection.close()


def _base():
    base, _ = prior._load_contract(config_dir() / prior.CONFIG_FILE)
    return base


def _contract():
    import yaml

    path = config_dir() / "v2_weekly_inner_selection_evaluation.yaml"
    return runner.WeeklyInnerEvaluationContract.model_validate(yaml.safe_load(path.read_bytes()))


def _toy_reference(control, base):
    """Old artifact schema over synthetic control predictions; never an archive evaluation."""
    slices = {}
    for prediction in control.predictions:
        context = control.contexts[prediction.key]
        labels = (
            f"season:{prediction.season}",
            "venue:home" if prediction.was_home else "venue:away",
            "promoted:promoted" if context["promoted"] else "promoted:established",
            "season_phase:early" if context["early_season"] else "season_phase:later",
            "cold_start:cold_start" if prediction.cold_start else "cold_start:established",
        )
        for label in labels:
            slices.setdefault(label, []).append(prediction)
    reference = {
        "control": base.control.name,
        "rows_scored": len(control.predictions),
        "folds": len(control.folds),
        "eligible_seasons": list(base.population.eligible_seasons),
        "overall": {
            base.control.name: prior._score_block(
                base.control.name, control.predictions, seed=base.random_seed
            )
        },
        "by_slice": {
            label: {
                base.control.name: prior._score_block(
                    base.control.name, rows, seed=base.random_seed
                )
            }
            for label, rows in slices.items()
        },
        "fixture_predictions": [
            {
                **control.contexts[p.key],
                "key": p.key,
                "observed_goals": p.observed,
                "distributions": {base.control.name: list(p.distribution)},
            }
            for p in control.predictions
        ],
        "fold_parameters": [
            {
                **fold,
                "control_parameters": fold["parameters"],
                "control_signal_fit": fold["signal_fit"],
            }
            for fold in control.folds
        ],
    }
    return deepcopy(reference)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("candidate", "retrospective_real_sot_team_environment_v1"),
        ("control", "other_control"),
        ("evidence_class", "strict_prospective"),
        ("provider", "pl_sdp"),
        ("signals", ["goals", "expected_goals", "shots_on_target"]),
        ("signals", ["goals", "shots_on_target"]),
        ("selection_schedule", "frozen_holdout"),
        ("search_stages", "joint_grid"),
        ("inner_aggregation", "equal_gameweek_weight"),
        ("tie_breaking", "random"),
        ("expected_rows", 2000),
        ("expected_folds", 100),
        ("formal_outer_runs", 2),
        ("retain_fixture_distributions", False),
        ("require_clean_worktree", False),
        ("promotion_permitted", True),
        ("allow_dirty", True),
    ],
)
def test_contract_refuses_second_hypothesis_or_changed_population(field, value):
    data = _contract().model_dump()
    data[field] = value
    with pytest.raises(ValidationError):
        runner.WeeklyInnerEvaluationContract.model_validate(data)


def test_frozen_control_estimator_and_prior_results_remain_byte_identical():
    root = repo_root()
    contract = _contract()
    path = root / contract.control_reference
    assert prior.file_sha256(path) == contract.control_reference_sha256
    assert prior.file_sha256(root / contract.base_contract) == contract.base_contract_sha256
    frozen = json.loads(path.read_bytes())
    for relative, digest in frozen["provenance"]["source_sha256"].items():
        assert prior.file_sha256(root / relative) == digest, relative
    assert frozen["control"] == contract.control
    assert frozen["rows_scored"] == contract.expected_rows == 2280
    assert frozen["folds"] == contract.expected_folds == 114
    assert _base().engine.half_life_days == (40.0, 80.0, 160.0, 320.0, 640.0, None)
    assert _base().engine.prior_matches == (2.0, 4.0, 8.0, 16.0, 32.0)
    assert _base().engine.weight_step == 0.25
    assert _base().development_gate.minimum_relative_log_lift == 0.01
    assert tuple(spec.column for spec in SIGNALS) == ("goals", "expected_goals")


def test_new_control_loop_is_exact_legacy_engine_on_the_same_toy_rows(con):
    import polars as pl

    base = _base()
    result = runner.run_control_walk_forward(con, base)
    frame = load_team_frame(con, provider="fpl_archive")
    folds = observed_folds(frame, minimum_prior_gameweeks=8)
    assert len(result.folds) == len(folds) == 1
    season, gw, cutoff = folds[0]
    training = frame.filter(pl.col("kickoff_time") < cutoff)
    target = frame.filter((pl.col("season") == season) & (pl.col("gw") == gw))
    engine = prior._engine(base, prior._CONTROL_SIGNALS)
    assert type(engine) is MultiSignalTeamEngine
    engine.set_prediction_season(season)
    engine.fit(training)
    expected = [
        poisson_pmf(
            engine.goal_rate(row["team_code"], row["opponent_team_code"], row["was_home"]),
            max_goals=base.engine.maximum_goals,
        )
        for row in target.iter_rows(named=True)
    ]
    assert [p.distribution for p in result.predictions] == expected
    assert result.folds[0]["parameters"] == engine.parameters.as_report()
    assert result == runner.run_control_walk_forward(con, base)


def test_no_sdp_or_extra_metric_can_affect_either_runner(con):
    base = _base()
    control = runner.run_control_walk_forward(con, base)
    candidate = runner.run_candidate_walk_forward(con, base)
    for table in (
        "stg_pl_sdp_fixture_crosswalk",
        "stg_pl_sdp_team_match_metric",
        "stg_pl_sdp_team_match_stats",
        "raw_pl_sdp_payload",
    ):
        con.execute(f"DELETE FROM {table}")
    con.execute("""
        UPDATE mart_fact_team_match_stats_v2 SET shots_on_target=9999,
            touches_in_opposition_box=9999, possession=100, expected_goals_on_target=9999,
            shots=9999, defensive_actions=9999
    """)
    after_control = runner.run_control_walk_forward(con, base)
    after_candidate = runner.run_candidate_walk_forward(con, base)
    assert after_control.predictions == control.predictions
    assert after_candidate.predictions == candidate.predictions
    assert [f["parameters"] for f in after_control.folds] == [
        f["parameters"] for f in control.folds
    ]
    assert [f["parameters"] for f in after_candidate.folds] == [
        f["parameters"] for f in candidate.folds
    ]


@pytest.mark.parametrize("run", ["run_control_walk_forward", "run_candidate_walk_forward"])
def test_complete_outer_gw_is_one_batch_despite_later_fixture_kickoff(con, run):
    _add_second_target_fixture(con)
    execute = getattr(runner, run)
    before = execute(con, _base())
    con.execute("""
        UPDATE mart_fact_team_match_stats_v2
        SET goals=30, goals_allowed=40, expected_goals=50, expected_goals_allowed=60
        WHERE gw=9 AND fixture=1009
    """)
    after = execute(con, _base())
    assert len(before.predictions) == len(after.predictions) == 4
    assert {p.key.split(":")[1] for p in before.predictions} == {"1009", "2009"}
    assert [p.distribution for p in before.predictions] == [
        p.distribution for p in after.predictions
    ]
    assert before.folds == after.folds


def test_future_truncation_leaves_prior_fold_predictions_and_selected_parameters_unchanged(con):
    later = initialise(":memory:")
    try:
        _seed_season(later, weeks=10)
        later.execute("""
            UPDATE mart_fact_team_match_stats_v2
            SET goals=90, goals_allowed=80, expected_goals=70 WHERE gw=10
        """)
        for execute in (runner.run_control_walk_forward, runner.run_candidate_walk_forward):
            before = execute(con, _base())
            after = execute(later, _base())
            assert before.predictions == [p for p in after.predictions if p.gw == 9]
            assert before.folds[0] == after.folds[0]
    finally:
        later.close()


def test_reproduction_accepts_identical_toy_control_and_never_writes_reference(con):
    base = _base()
    control = runner.run_control_walk_forward(con, base)
    frozen = _toy_reference(control, base)
    original = deepcopy(frozen)
    check = runner.verify_control_reproduction(
        control, frozen, base, expected_rows=2, expected_folds=1
    )
    assert check
    assert frozen == original


@pytest.mark.parametrize(
    "changed",
    [
        "row_count",
        "fold_count",
        "control_name",
        "season_population",
        "key",
        "outcome",
        "venue",
        "cutoff",
        "pmf",
        "log",
        "crps",
        "season_log",
        "half_life",
        "scale",
    ],
)
def test_reproduction_rejects_changed_harness_labels_predictions_or_scores(con, changed):
    base = _base()
    control = runner.run_control_walk_forward(con, base)
    frozen = _toy_reference(control, base)
    first = frozen["fixture_predictions"][0]
    if changed == "row_count":
        frozen["rows_scored"] += 1
    elif changed == "fold_count":
        frozen["folds"] += 1
    elif changed == "control_name":
        frozen["control"] = "different_control"
    elif changed == "season_population":
        frozen["eligible_seasons"] = ["2022-23", "2023-24", "2024-25"]
    elif changed == "key":
        first["key"] += "-changed"
    elif changed == "outcome":
        first["observed_goals"] += 1
    elif changed == "venue":
        first["was_home"] = not first["was_home"]
    elif changed == "cutoff":
        first["as_of"] = "2099-01-01T00:00:00+00:00"
    elif changed == "pmf":
        first["distributions"][base.control.name][0] += 1e-6
        first["distributions"][base.control.name][1] -= 1e-6
    elif changed in {"log", "crps"}:
        metric = "mean_log_score" if changed == "log" else "crps"
        frozen["overall"][base.control.name][metric] += 1e-6
    elif changed == "season_log":
        frozen["by_slice"]["season:2023-24"][base.control.name]["mean_log_score"] += 1e-6
    elif changed == "half_life":
        frozen["fold_parameters"][0]["control_parameters"]["half_life_days"] = 40.0
    elif changed == "scale":
        frozen["fold_parameters"][0]["control_signal_fit"]["expected_goals"]["goal_scale"] += 0.01
    with pytest.raises(runner.WeeklyInnerEvaluationError):
        runner.verify_control_reproduction(control, frozen, base, expected_rows=2, expected_folds=1)


def test_fixture_pmfs_are_retained_and_independently_reconcile_the_report(con):
    base = _base()
    control = runner.run_control_walk_forward(con, base)
    candidate = runner.run_candidate_walk_forward(con, base)
    report = runner.score_run(control, candidate, base)
    assert report["evidence_class"] == "retrospective_archive_development"
    assert report["promotion_permitted"] is False
    assert report["rows_scored"] == len(report["fixture_predictions"]) == 2
    assert report["folds"] == 1
    assert report["verdict"] in {"SUPPORTED_FOR_DEVELOPMENT", "INCONCLUSIVE", "REFUTED"}
    for name in (base.control.name, NAME):
        losses = []
        for row in report["fixture_predictions"]:
            pmf = row["distributions"][name]
            assert len(pmf) == base.engine.maximum_goals + 1
            assert sum(pmf) == pytest.approx(1.0, abs=1e-9)
            assert all(math.isfinite(p) and p >= 0 for p in pmf)
            losses.append(log_score(pmf, row["observed_goals"]))
        assert sum(losses) / len(losses) == pytest.approx(report["overall"][name]["mean_log_score"])
    assert prior._json_bytes(report)
    assert report == runner.score_run(control, candidate, base)


def test_cluster_uncertainty_weights_rows_not_unequal_gameweek_means():
    control = [
        Prediction("2023-24", gw, f"{gw}:{i}", poisson_pmf(1.0), observed=1, was_home=True)
        for i, gw in enumerate((1, 1, 1, 2, 3, 3))
    ]
    candidate = [
        replace(p, distribution=poisson_pmf(rate))
        for p, rate in zip(control, (0.2, 0.3, 0.4, 2.5, 1.1, 1.2), strict=True)
    ]
    deltas = [
        log_score(new.distribution, new.observed) - log_score(old.distribution, old.observed)
        for old, new in zip(control, candidate, strict=True)
    ]
    mean = sum(deltas) / 6
    residual_sums = (
        sum(deltas[:3]) - 3 * mean,
        deltas[3] - mean,
        sum(deltas[4:]) - 2 * mean,
    )
    expected = math.sqrt(3 / 2 * sum(value**2 for value in residual_sums)) / 6
    report = runner.clustered_loss_uncertainty(control, candidate)
    assert report["paired_row_weighted_mean_log_loss"] == pytest.approx(mean)
    assert report["paired_gw_cluster_log_loss_standard_error"] == pytest.approx(expected)
    assert report["clusters"] == 3 and report["rows"] == 6
    assert report["normal_95_interval"] == pytest.approx(
        (mean - 1.96 * expected, mean + 1.96 * expected)
    )


@pytest.mark.parametrize(
    "changed", ["event_time_violations", "target_gameweek_overlap", "timestamp"]
)
def test_scoring_refuses_inner_guard_or_timestamp_violations(con, changed):
    base = _base()
    control = runner.run_control_walk_forward(con, base)
    candidate = runner.run_candidate_walk_forward(con, base)
    batch = {
        "as_of": "2023-09-01T00:00:00+00:00",
        "training_latest_kickoff": "2023-08-31T00:00:00+00:00",
        "event_time_violations": 0,
        "target_gameweek_overlap": 0,
    }
    if changed == "timestamp":
        batch["training_latest_kickoff"] = batch["as_of"]
    else:
        batch[changed] = 1
    candidate.folds[0]["inner_diagnostics"] = {"weights": {"batches": [batch]}}
    with pytest.raises(runner.WeeklyInnerEvaluationError, match="inner event-time/batch"):
        runner.score_run(control, candidate, base)


@pytest.mark.parametrize("changed", ["identity", "outcome", "training_input"])
def test_scoring_refuses_changed_candidate_population_or_training_input(con, changed):
    base = _base()
    control = runner.run_control_walk_forward(con, base)
    candidate = runner.run_candidate_walk_forward(con, base)
    if changed == "training_input":
        candidate.folds[0]["training_input_sha256"] = "f" * 64
    else:
        first = candidate.predictions[0]
        candidate.predictions[0] = replace(
            first,
            **({"key": "other"} if changed == "identity" else {"observed": first.observed + 1}),
        )
    with pytest.raises(runner.WeeklyInnerEvaluationError):
        runner.score_run(control, candidate, base)


def test_new_runner_and_selector_are_absent_from_production_import_paths():
    production = repo_root() / "src/fpl"
    offenders = []
    for path in production.rglob("*.py"):
        if "validate" in path.relative_to(production).parts:
            continue
        text = path.read_text(encoding="utf-8")
        if "weekly_inner_selection" in text or "dev_v2_weekly_inner" in text:
            offenders.append(path)
    assert offenders == []


def test_dirty_worktree_refused_before_any_control_or_candidate_fitting(monkeypatch, tmp_path):
    def forbidden(*_args, **_kwargs):
        pytest.fail("dirty worktree reached fitting")

    monkeypatch.setattr(prior, "_git", lambda *_args: " M uncommitted.py")
    monkeypatch.setattr(runner, "run_control_walk_forward", forbidden)
    monkeypatch.setattr(runner, "run_candidate_walk_forward", forbidden)
    with pytest.raises(runner.WeeklyInnerEvaluationError, match="dirty worktree"):
        runner.run(
            root=tmp_path,
            db_path=tmp_path / "missing.db",
            config_path=tmp_path / "missing.yaml",
            output_path=tmp_path / "weekly-result.json",
        )
    assert not (tmp_path / "weekly-result.json").exists()


def test_formal_output_is_write_once_before_database_access(monkeypatch, tmp_path):
    output = tmp_path / "weekly-result.json"
    output.write_text("already scored", encoding="utf-8")
    monkeypatch.setattr(prior, "require_clean_worktree", lambda _root: None)
    with pytest.raises(runner.WeeklyInnerEvaluationError, match=r"write-once|already exists"):
        runner.run(
            root=tmp_path,
            db_path=tmp_path / "missing.db",
            config_path=tmp_path / "missing.yaml",
            output_path=output,
        )
    assert output.read_text(encoding="utf-8") == "already scored"


@pytest.fixture
def formal_stub(con, monkeypatch, tmp_path):
    """Exercise formal orchestration in a throwaway root, with synthetic predictions only."""
    base = _base()
    contract = _contract()
    control = runner.run_control_walk_forward(con, base)
    candidate = runner.run_candidate_walk_forward(con, base)
    real_root = repo_root()
    original = json.loads((real_root / "results/v2_real_sot_development.json").read_bytes())
    for relative in (contract.control_reference, "results/v2_real_sot_development.json"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((real_root / relative).read_bytes())
    evidence = original["provenance"]
    snapshot = prior.ProvenanceSnapshot(
        head="synthetic-clean-head",
        config_sha256=prior.file_sha256(config_dir() / runner.CONFIG_FILE),
        database_sha256=evidence["database_sha256"],
        coverage_report_sha256=evidence["coverage_report_sha256"],
        capture_manifest_sha256=evidence["capture_manifest_sha256"],
        source_sha256=evidence["source_sha256"],
        frozen_v2_result_sha256=evidence["frozen_v2_result_sha256"],
        started_at_utc="2026-09-06T00:00:00+00:00",
    )
    real_hash = prior.file_sha256

    def mapped_hash(path):
        return real_hash(path if path.is_file() else real_root / path.relative_to(tmp_path))

    monkeypatch.setattr(prior, "file_sha256", mapped_hash)
    monkeypatch.setattr(prior, "require_clean_worktree", lambda _root: None)
    monkeypatch.setattr(prior, "_snapshot", lambda **_kwargs: snapshot)
    monkeypatch.setattr(prior, "_verify_snapshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner, "load_contract", lambda *_args, **_kwargs: (contract, base))
    monkeypatch.setattr(runner, "connect", lambda *_args, **_kwargs: con)
    monkeypatch.setattr(runner, "run_control_walk_forward", lambda *_args: control)
    monkeypatch.setattr(runner, "run_candidate_walk_forward", lambda *_args: candidate)
    monkeypatch.setattr(
        runner,
        "verify_control_reproduction",
        lambda *_args, **_kwargs: {
            "pass": True,
            "rows": 2,
            "folds": 1,
            "maximum_pmf_absolute_difference": 0.0,
        },
    )
    return {
        "root": tmp_path,
        "db_path": tmp_path / "synthetic.db",
        "config_path": tmp_path / "config/weekly.yaml",
        "output_path": tmp_path / "weekly-result.json",
    }


@pytest.mark.parametrize(
    ("failure", "claim_expected"),
    [
        ("reproduction", False),
        ("pre_candidate_snapshot", False),
        ("candidate", True),
        ("postflight_snapshot", True),
    ],
)
def test_formal_order_stops_at_failure_without_publishing_or_retrying(
    formal_stub, monkeypatch, failure, claim_expected
):
    calls = []

    def rejected(*_args, **_kwargs):
        calls.append("rejected")
        raise runner.WeeklyInnerEvaluationError("synthetic failure")

    original_candidate = runner.run_candidate_walk_forward

    def candidate(*args):
        calls.append("candidate")
        claim = formal_stub["root"] / "data/evaluation-claims" / f"{NAME}.json"
        assert claim.exists()  # No candidate fit starts without the durable exclusive claim.
        if failure == "candidate":
            rejected()
        return original_candidate(*args)

    monkeypatch.setattr(runner, "run_candidate_walk_forward", candidate)
    if failure == "reproduction":
        monkeypatch.setattr(runner, "verify_control_reproduction", rejected)
    elif "snapshot" in failure:

        def verify(*_args, **_kwargs):
            calls.append("snapshot")
            if failure == "pre_candidate_snapshot" or calls.count("snapshot") == 2:
                rejected()

        monkeypatch.setattr(prior, "_verify_snapshot", verify)
    with pytest.raises(runner.WeeklyInnerEvaluationError, match="synthetic failure"):
        runner.run(**formal_stub)
    claim = formal_stub["root"] / "data/evaluation-claims" / f"{NAME}.json"
    assert claim.exists() is claim_expected
    assert not formal_stub["output_path"].exists()
    assert ("candidate" in calls) is claim_expected
    if claim_expected:
        before = list(calls)
        with pytest.raises(runner.WeeklyInnerEvaluationError, match="already claimed"):
            runner.run(**formal_stub)
        assert calls == before  # A failed/interrupted candidate is not silently started again.


def test_formal_toy_report_keeps_clean_provenance_and_cannot_overwrite(formal_stub):
    report = runner.run(**formal_stub)
    stored = json.loads(formal_stub["output_path"].read_bytes())
    assert stored["provenance"]["clean_worktree"] is True
    assert stored["provenance"]["git_head"] == "synthetic-clean-head"
    assert stored["provenance"]["provider"] == "fpl_archive"
    assert stored["promotion_permitted"] is False
    assert stored["rows_scored"] == report["rows_scored"] == 2
    assert len(stored["provenance"]["execution_claim_sha256"]) == 64
    before = formal_stub["output_path"].read_bytes()
    with pytest.raises(runner.WeeklyInnerEvaluationError, match="write-once"):
        runner.run(**formal_stub)
    assert formal_stub["output_path"].read_bytes() == before


def test_execution_claim_is_exclusive_and_preserves_first_identity(tmp_path):
    path = runner.reserve_execution_claim(tmp_path, {"git_head": "first"})
    first = path.read_bytes()
    with pytest.raises(runner.WeeklyInnerEvaluationError, match="already claimed"):
        runner.reserve_execution_claim(tmp_path, {"git_head": "second"})
    assert path.read_bytes() == first
