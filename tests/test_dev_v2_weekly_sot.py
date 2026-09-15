"""Synthetic-only guards for incremental SOT on the frozen weekly-inner control."""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta

import polars as pl
import pytest
from pydantic import ValidationError

from fpl.config import config_dir, repo_root
from fpl.features.pit import AsOf, FeatureSource, PointInTimeView
from fpl.models.football_engine_v2 import MultiSignalTeamEngine
from fpl.storage.db import initialise
from fpl.transform.pl_sdp import SdpIdentityError
from fpl.validate import dev_v2_real_sot as prior
from fpl.validate import dev_v2_weekly_inner as weekly
from fpl.validate import dev_v2_weekly_sot as runner
from fpl.validate.metrics import log_score
from fpl.validate.retrospective_sdp import EVIDENCE_CLASS, VERSION_SELECTION_POLICY
from fpl.validate.sot_zero_audit import CorroboratedSotBackfillView
from fpl.validate.weekly_inner_selection import WeeklyRefitTeamEngine

from .test_dev_v2_corroborated_sot import _audit
from .test_dev_v2_real_sot import CAPTURED, START, _add_second_target_fixture, _seed_season
from .test_weekly_inner_selection import START as ENGINE_START
from .test_weekly_inner_selection import _frame


@pytest.fixture
def con():
    connection = initialise(":memory:")
    _seed_season(connection)
    yield connection
    connection.close()


def _base():
    return prior._load_contract(config_dir() / prior.CONFIG_FILE)[0]


def _contract():
    return runner.load_contract(config_dir() / runner.CONFIG_FILE, root=repo_root())[0]


def _engine(**overrides):
    base = _base()
    return runner.WeeklySotTeamEngine(
        base.model_copy(
            update={
                "engine": base.engine.model_copy(
                    update={
                        "half_life_days": (40.0, None),
                        "prior_matches": (2.0, 8.0),
                        **overrides,
                    }
                ),
                "walk_forward": base.walk_forward.model_copy(
                    update={
                        "inner_holdout_observed_gameweeks": 3,
                        "minimum_inner_training_observed_gameweeks": 2,
                        "minimum_team_matches": 0,
                    }
                ),
            }
        )
    )


def _sot_frame(weeks=8):
    return _frame(weeks).with_columns(
        (pl.col("goals") + 3).cast(pl.Float64).alias("shots_on_target_corroborated")
    )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("candidate", "retrospective_real_sot_team_environment_v1"),
        ("control", "retrospective_goals_xg_control_v1"),
        ("evidence_class", "strict_prospective"),
        ("signals", ["goals", "expected_goals", "possession"]),
        ("signals", ["goals", "expected_goals", "shots_on_target_corroborated", "shots"]),
        ("formal_outer_runs", 2),
        ("require_clean_worktree", False),
        ("promotion_permitted", True),
        ("retain_fixture_distributions", False),
        ("expected_rows", 2000),
        ("expected_folds", 100),
        ("allow_dirty", True),
    ],
)
def test_contract_rejects_scope_or_evidence_expansion(key, value):
    data = _contract().model_dump()
    data[key] = value
    with pytest.raises(ValidationError):
        runner.WeeklySotEvaluationContract.model_validate(data)


def test_separate_identity_reuses_exact_frozen_weekly_procedure_and_grid():
    candidate, control = runner.WeeklySotTeamEngine(_base()), WeeklyRefitTeamEngine()
    assert candidate.name == runner.CANDIDATE
    assert candidate.evidence_class == EVIDENCE_CLASS
    assert tuple(spec.column for spec in candidate._signals) == (
        "goals",
        "expected_goals",
        "shots_on_target_corroborated",
    )
    assert tuple(spec.name for spec in candidate._signals) == (
        "goals",
        "expected_goals",
        "shots_on_target",
    )
    for name in (
        "fit",
        "fit_as_of",
        "_inner_batches",
        "_select_decay_and_prior",
        "_select_weights",
    ):
        assert getattr(type(candidate), name) is getattr(type(control), name)
    assert candidate.fit.__func__ is MultiSignalTeamEngine.fit
    for name in (
        "_half_lives",
        "_prior_matches",
        "_minimum_team_matches",
        "_inner_holdout_gameweeks",
        "_minimum_inner_training_gameweeks",
        "_weight_step",
        "_minimum_signal_coverage",
        "_promoted_attack_prior",
        "_promoted_defence_prior",
        "_rate_floor",
        "_maximum_goals",
    ):
        assert getattr(candidate, name) == getattr(control, name)
    with pytest.raises(TypeError, match="signals"):
        runner.WeeklySotTeamEngine(_base(), signals=())
    assert _base().development_gate.minimum_relative_log_lift == 0.01


def test_frozen_weekly_source_and_prior_results_remain_byte_identical():
    root = repo_root()
    contract = _contract()
    assert prior.file_sha256(root / contract.control_reference) == contract.control_reference_sha256
    assert prior.file_sha256(root / contract.base_contract) == contract.base_contract_sha256
    expected = {
        "src/fpl/validate/weekly_inner_selection.py": (
            "c5570d61300dc3cc0051aca9590591e79b0e21efb24eb1f6259ca0a60d234985"
        ),
        "src/fpl/models/football_engine_v2.py": (
            "ace9c6a0f0e90dfe7834533a4b6a731703b11ddbe7299e42af85a683632eeb19"
        ),
    }
    for relative, digest in expected.items():
        assert (
            hashlib.sha256((root / relative).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            == digest
        )
    for relative, digest in {
        "results/v2_real_sot_development.json": (
            "32a3332dd92e30b160a632d6ad68ee268cbfd3367a27340e365583c2e9ca7e7d"
        ),
        "results/v2_corroborated_zero_sot_development.json": (
            "e8d1a5c0fcce42946d3bf8e798f52e208ac79168c2453e4c0840c1be65c009c5"
        ),
        "results/v2_weekly_inner_selection_development.json": (
            "79f3a0815271a95cd0e39874aaa20fa89d3b1df0875a5e780c0317a961424d35"
        ),
    }.items():
        assert prior.file_sha256(root / relative) == digest


def test_absent_or_null_sot_reduces_exactly_to_weekly_control(con):
    base = _base()
    control = runner.run_control_walk_forward(con, base)
    assert control == weekly.run_candidate_walk_forward(con, base)
    con.execute(
        "UPDATE stg_pl_sdp_team_match_metric SET value_numeric=NULL "
        "WHERE provider_field='ontargetScoringAtt'"
    )
    candidate = runner.run_candidate_walk_forward(con, base, _audit())
    assert [p.distribution for p in candidate.predictions] == [
        p.distribution for p in control.predictions
    ]
    assert candidate.folds[0]["parameters"]["rejected_shots_on_target"] == "no measured rows"
    assert runner.run_control_walk_forward(con, base) == control


def test_zero_sot_weight_reduces_to_exact_control_and_extra_metrics_are_unused():
    candidate = _engine()
    control = WeeklyRefitTeamEngine(
        half_life_days=(40.0, None),
        prior_matches=(2.0, 8.0),
        inner_holdout_gameweeks=3,
        minimum_inner_training_gameweeks=2,
        minimum_team_matches=0,
    )
    frame = _sot_frame()
    candidate.fit(
        frame.with_columns(
            pl.lit(999999.0).alias("possession"), pl.lit(-999.0).alias("shots_on_target")
        )
    )
    control.fit(frame)
    assert candidate.parameters.half_life_days == control.parameters.half_life_days
    assert candidate.parameters.prior_matches == control.parameters.prior_matches
    candidate.parameters.weights = {**control.parameters.weights, "shots_on_target": 0.0}
    assert candidate.goal_rate(3, 8, True) == control.goal_rate(3, 8, True)
    assert candidate.goal_rate(8, 3, False) == control.goal_rate(8, 3, False)
    assert set(candidate.fitted_signals) == {"goals", "expected_goals", "shots_on_target"}


def test_inner_sot_scales_are_fold_local_and_dgw_legs_never_update_same_batch():
    frame = _sot_frame().with_columns(
        pl.when(pl.col("gw") == 6)
        .then(1000.0)
        .otherwise(pl.col("shots_on_target_corroborated"))
        .alias("shots_on_target_corroborated")
    )
    delayed = frame.filter(pl.col("gw") == 6).with_columns(
        pl.lit(106, dtype=pl.Int64).alias("fixture"), pl.col("kickoff_time") + timedelta(days=9)
    )
    frame = pl.concat([frame, delayed]).sort("kickoff_time")
    candidate = _engine()
    batches = candidate._inner_batches(frame)
    assert set(batches[0].target["fixture"]) == {6, 106}
    assert 106 not in batches[1].training["fixture"]
    assert 106 in batches[2].training["fixture"]
    candidate.fit(frame)
    for batch in candidate.selector_diagnostics["weights"]["batches"]:
        history = frame.filter(pl.col("kickoff_time") < datetime.fromisoformat(batch["as_of"]))
        scale = history["goals"].mean() / history["shots_on_target_corroborated"].mean()
        assert batch["signal_scales"]["shots_on_target"] == pytest.approx(scale)
        assert batch["event_time_violations"] == batch["target_gameweek_overlap"] == 0


def test_candidate_output_is_deterministic_unit_mass_and_event_truncation_equivalent():
    frame, cutoff = _sot_frame(12), AsOf(ENGINE_START + timedelta(days=63))
    left, right = _engine(), _engine()
    left.fit_as_of(frame, cutoff)
    right.fit_as_of(frame.filter(pl.col("kickoff_time") < cutoff.ts).reverse(), cutoff)
    assert left.parameters == right.parameters
    assert left.selector_diagnostics == right.selector_diagnostics
    options = {
        "season": "2025-26",
        "fixture": 99,
        "home_team_code": 3,
        "away_team_code": 8,
        "gw": 9,
    }
    environment = left.predict_environment(**options)
    assert environment == right.predict_environment(**options)
    for side in (environment.home, environment.away):
        assert math.fsum(side.goal_distribution) == pytest.approx(1.0, abs=1e-14)
        assert all(math.isfinite(p) and p >= 0 for p in side.goal_distribution)


def test_whole_outer_target_batch_cannot_observe_its_own_goals_xg_or_sot(con):
    _add_second_target_fixture(con)
    before = runner.run_candidate_walk_forward(con, _base(), _audit())
    con.execute("UPDATE mart_fact_team_match_stats_v2 SET goals=90, expected_goals=80 WHERE gw=9")
    con.execute(
        "UPDATE stg_pl_sdp_team_match_metric SET value_numeric=9999 "
        "WHERE sdp_match_id=9009 AND provider_field='ontargetScoringAtt'"
    )
    after = runner.run_candidate_walk_forward(con, _base(), _audit())
    assert len(before.predictions) == 4
    assert [p.distribution for p in before.predictions] == [
        p.distribution for p in after.predictions
    ]
    assert before.folds == after.folds


def test_outer_future_truncation_preserves_predictions_parameters_and_scaling(con):
    later = initialise(":memory:")
    try:
        _seed_season(later, weeks=10)
        later.execute(
            "UPDATE mart_fact_team_match_stats_v2 SET goals=90, expected_goals=70 WHERE gw=10"
        )
        later.execute(
            "UPDATE stg_pl_sdp_team_match_metric SET value_numeric=9999 "
            "WHERE sdp_match_id=9010 AND provider_field='ontargetScoringAtt'"
        )
        before = runner.run_candidate_walk_forward(con, _base(), _audit())
        after = runner.run_candidate_walk_forward(later, _base(), _audit())
        assert before.predictions == [p for p in after.predictions if p.gw == 9]
        assert before.folds[0] == after.folds[0]
    finally:
        later.close()


def test_source_retains_original_time_identity_nulls_and_earliest_complete_version(con):
    cutoff = AsOf(START + timedelta(days=56))
    before = CorroboratedSotBackfillView(con, cutoff, _audit()).observed_corroborated_sot()
    con.execute(
        "INSERT INTO raw_pl_sdp_payload SELECT * REPLACE ('later' AS payload_id, "
        "fetched_at + INTERVAL '1 day' AS fetched_at, 'later-hash' AS sha256) "
        "FROM raw_pl_sdp_payload WHERE payload_id='capture-01'"
    )
    con.execute(
        "INSERT INTO stg_pl_sdp_team_match_stats SELECT * REPLACE ('later' AS payload_id, "
        "known_at + INTERVAL '1 day' AS known_at) "
        "FROM stg_pl_sdp_team_match_stats WHERE payload_id='capture-01'"
    )
    con.execute(
        "INSERT INTO stg_pl_sdp_team_match_metric SELECT * REPLACE ('later' AS payload_id, "
        "9999 AS value_numeric) FROM stg_pl_sdp_team_match_metric WHERE payload_id='capture-01'"
    )
    after = CorroboratedSotBackfillView(con, cutoff, _audit()).observed_corroborated_sot()
    assert before.equals(after)
    assert set(after["team_code"]) == {101, 202}
    assert all(
        pulse != match for pulse, match in after.select("pulse_id", "sdp_match_id").iter_rows()
    )
    assert after["source_known_at"].min() > cutoff.ts
    assert set(after["version_selection_policy"]) == {VERSION_SELECTION_POLICY}
    con.execute(
        "UPDATE stg_pl_sdp_team_match_metric SET value_numeric=NULL "
        "WHERE payload_id='capture-01' AND side='home' AND provider_field='ontargetScoringAtt'"
    )
    missing = CorroboratedSotBackfillView(con, cutoff, _audit()).observed_corroborated_sot()
    assert missing["shots_on_target"].null_count() == 1
    assert missing["shots_on_target_corroborated"].null_count() == 1


def test_candidate_rejects_uncorroborated_crosswalk_instead_of_fuzzy_matching(con):
    con.execute(
        "UPDATE stg_pl_sdp_fixture_crosswalk SET corroborated_teams=FALSE WHERE fixture=1001"
    )
    with pytest.raises(SdpIdentityError, match="not fully corroborated"):
        runner.run_candidate_walk_forward(con, _base(), _audit())


def test_later_known_sot_never_becomes_strict_prospective_evidence(con):
    con.execute(
        """
        INSERT INTO mart_fact_team_match_stats_v2_version (
            season, gw, fixture, pulse_id, sdp_match_id, kickoff_time, team_id, team_code,
            opponent_team_id, opponent_team_code, was_home, provider, known_at, capture_id,
            payload_sha256, source_known_at, metadata_capture_id, metadata_known_at,
            shots_on_target
        ) SELECT season, gw, fixture, pulse_id, 9001, kickoff_time, team_id, team_code,
                 opponent_team_id, opponent_team_code, was_home, 'pl_sdp', ?, 'capture-01',
                 'retained-hash', ?, 'archive', kickoff_time, 3
          FROM mart_fact_team_match_stats_v2 WHERE fixture=1001
    """,
        [CAPTURED, CAPTURED],
    )
    cutoff = AsOf(START + timedelta(days=56))
    assert (
        PointInTimeView(FeatureSource(con), cutoff)
        .observed_team_football(providers=["pl_sdp"])
        .is_empty()
    )
    assert (
        PointInTimeView(FeatureSource(con), AsOf(CAPTURED))
        .observed_team_football(providers=["pl_sdp"])
        .height
        == 2
    )
    assert (
        CorroboratedSotBackfillView(con, cutoff, _audit()).observed_corroborated_sot().height == 16
    )
    assert not issubclass(CorroboratedSotBackfillView, PointInTimeView)
    for path in (repo_root() / "src/fpl").rglob("*.py"):
        if "validate" not in path.relative_to(repo_root() / "src/fpl").parts:
            assert "dev_v2_weekly_sot" not in path.read_text(encoding="utf-8")


def test_control_reproduction_accepts_weekly_reference_without_changing_it(con):
    base = _base()
    control = runner.run_control_walk_forward(con, base)
    reference = deepcopy(weekly.score_run(control, control, base))
    original = deepcopy(reference)
    assert runner.verify_control_reproduction(
        control, reference, base, expected_rows=2, expected_folds=1
    )["pass"]
    assert original == reference


@pytest.mark.parametrize(
    "changed",
    ["identity", "outcome", "pmf", "parameter", "scale", "cutoff", "log", "crps", "season"],
)
def test_control_reproduction_rejects_any_changed_weekly_evidence(con, changed):
    base = _base()
    control = runner.run_control_walk_forward(con, base)
    reference = deepcopy(weekly.score_run(control, control, base))
    row, fold = reference["fixture_predictions"][0], reference["fold_parameters"][0]
    if changed == "identity":
        row["key"] += "-wrong"
    elif changed == "outcome":
        row["observed_goals"] += 1
    elif changed == "pmf":
        row["distributions"][runner.CONTROL] = list(row["distributions"][runner.CONTROL])
        row["distributions"][runner.CONTROL][0] += 1e-6
    elif changed == "parameter":
        fold["candidate_parameters"]["prior_matches"] = 999
    elif changed == "scale":
        fold["candidate_signal_fit"]["expected_goals"]["goal_scale"] += 1
    elif changed == "cutoff":
        row["as_of"] = "2099-01-01T00:00:00+00:00"
    elif changed in {"log", "crps"}:
        reference["overall"][runner.CONTROL]["mean_log_score" if changed == "log" else "crps"] += (
            1e-6
        )
    else:
        reference["by_slice"]["season:2023-24"][runner.CONTROL]["mean_log_score"] += 1e-6
    with pytest.raises(prior.RetrospectiveEvaluationError):
        runner.verify_control_reproduction(
            control, reference, base, expected_rows=2, expected_folds=1
        )


def test_report_keeps_all_pmfs_and_reconciles_proper_scores(con):
    base = _base()
    control = runner.run_control_walk_forward(con, base)
    candidate = runner.run_candidate_walk_forward(con, base, _audit())
    report = runner.score_run(control, candidate, base)
    assert report["evidence_class"] == EVIDENCE_CLASS
    assert report["promotion_permitted"] is False
    assert report["rows_scored"] == len(report["fixture_predictions"]) == 2
    assert report["folds"] == 1
    for name in (runner.CONTROL, runner.CANDIDATE):
        losses = []
        for row in report["fixture_predictions"]:
            pmf = row["distributions"][name]
            assert math.fsum(pmf) == pytest.approx(1.0, abs=1e-12)
            losses.append(log_score(pmf, row["observed_goals"]))
        assert sum(losses) / len(losses) == pytest.approx(report["overall"][name]["mean_log_score"])
    assert prior._json_bytes(report)
    assert report == runner.score_run(control, candidate, base)


@pytest.mark.parametrize("changed", ["identity", "outcome", "training_input"])
def test_scoring_refuses_changed_candidate_population(con, changed):
    base = _base()
    control = runner.run_control_walk_forward(con, base)
    candidate = runner.run_candidate_walk_forward(con, base, _audit())
    if changed == "training_input":
        candidate.folds[0]["training_input_sha256"] = "f" * 64
    else:
        first = candidate.predictions[0]
        candidate.predictions[0] = replace(
            first,
            **({"key": "other"} if changed == "identity" else {"observed": first.observed + 1}),
        )
    with pytest.raises(prior.RetrospectiveEvaluationError):
        runner.score_run(control, candidate, base)


def test_dirty_worktree_refused_before_database_or_any_fitting(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail("dirty worktree reached fitting")

    monkeypatch.setattr(prior, "_git", lambda *_args: " M uncommitted.py")
    monkeypatch.setattr(runner, "run_control_walk_forward", forbidden)
    monkeypatch.setattr(runner, "run_candidate_walk_forward", forbidden)
    with pytest.raises(prior.RetrospectiveEvaluationError, match="dirty worktree"):
        runner.run(
            root=tmp_path,
            db_path=tmp_path / "missing.db",
            config_path=tmp_path / "missing.yaml",
            output_path=tmp_path / "result.json",
        )
    assert not (tmp_path / "result.json").exists()


def test_execution_claim_is_exclusive_and_survives_interruption(tmp_path):
    claim = runner.reserve_execution_claim(tmp_path, {"git_head": "first"})
    before = claim.read_bytes()
    with pytest.raises(prior.RetrospectiveEvaluationError, match="already claimed"):
        runner.reserve_execution_claim(tmp_path, {"git_head": "second"})
    assert claim.read_bytes() == before
    assert json.loads(before)["candidate"] == runner.CANDIDATE


def test_existing_formal_result_is_not_overwritten(monkeypatch, tmp_path):
    output = tmp_path / "result.json"
    output.write_text("frozen", encoding="utf-8")
    monkeypatch.setattr(prior, "require_clean_worktree", lambda _root: None)
    with pytest.raises(prior.RetrospectiveEvaluationError, match=r"write-once|already exists"):
        runner.run(
            root=tmp_path,
            db_path=tmp_path / "missing.db",
            config_path=tmp_path / "missing.yaml",
            output_path=output,
        )
    assert output.read_text(encoding="utf-8") == "frozen"


def test_reproduction_keeps_frozen_cold_start_population_and_model_label_separate(con):
    base = _base()
    control = runner.run_control_walk_forward(con, base)
    prior_labels = deepcopy(control)
    for index, prediction in enumerate(prior_labels.predictions):
        prior_labels.predictions[index] = replace(prediction, cold_start=not prediction.cold_start)
        prior_labels.contexts[prediction.key]["cold_start"] = not prediction.cold_start
    reference = deepcopy(weekly.score_run(prior_labels, control, base))
    original = deepcopy(reference)
    result = runner.verify_control_reproduction(
        control, reference, base, expected_rows=2, expected_folds=1
    )
    assert result["model_vs_reference_cold_start_disagreements"] == 2
    for prediction in control.predictions:
        context = control.contexts[prediction.key]
        assert prediction.cold_start == context["cold_start"]
        assert prediction.cold_start != context["model_cold_start"]
    assert reference == original


@pytest.fixture
def formal_stub(con, monkeypatch, tmp_path):
    """Formal ordering exercised only on tiny synthetic predictions and temporary evidence."""
    root = repo_root()
    contract, base, sot = runner.load_contract(config_dir() / runner.CONFIG_FILE, root=root)
    contract = contract.model_copy(update={"expected_rows": 2, "expected_folds": 1})
    control = runner.run_control_walk_forward(con, base)
    candidate = runner.run_candidate_walk_forward(con, base, _audit())
    reference = deepcopy(weekly.score_run(control, control, base))
    reference["provenance"] = {"source_sha256": {}}
    for relative, content in (
        (contract.control_reference, reference),
        (base.population.coverage_report, {}),
        ("results/" + prior.CAPTURE_MANIFEST_FILE, []),
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(prior._json_bytes(content))
    db_path = tmp_path / "synthetic.db"
    db_path.touch()
    snapshot = prior.ProvenanceSnapshot(
        head="synthetic-clean-head",
        config_sha256="a" * 64,
        database_sha256=runner.DATABASE_SHA256,
        coverage_report_sha256=runner.COVERAGE_SHA256,
        capture_manifest_sha256=runner.MANIFEST_SHA256,
        source_sha256={},
        frozen_v2_result_sha256=prior.FROZEN_V2_RESULT_SHA256,
        started_at_utc="2026-09-07T00:00:00+00:00",
    )
    real_hash = prior.file_sha256
    monkeypatch.setattr(
        prior,
        "file_sha256",
        lambda p: real_hash(p if p.is_file() else root / p.relative_to(tmp_path)),
    )
    monkeypatch.setattr(prior, "require_clean_worktree", lambda _root: None)
    monkeypatch.setattr(prior, "_snapshot", lambda **_kwargs: snapshot)
    monkeypatch.setattr(prior, "_verify_snapshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(prior, "build_coverage_evidence", lambda *_args: ({}, []))
    monkeypatch.setattr(runner, "load_contract", lambda *_args, **_kwargs: (contract, base, sot))
    monkeypatch.setattr(runner, "connect", lambda *_args, **_kwargs: con)
    monkeypatch.setattr(runner, "run_control_walk_forward", lambda *_args: control)
    monkeypatch.setattr(runner, "run_candidate_walk_forward", lambda *_args: candidate)
    monkeypatch.setattr(
        runner.corroborated,
        "validate_audit",
        lambda *_args: {
            **_audit(),
            "database_sha256": runner.DATABASE_SHA256,
            "canonical_capture_manifest_sha256": runner.MANIFEST_SHA256,
        },
    )
    return {
        "root": tmp_path,
        "db_path": db_path,
        "config_path": tmp_path / "config/weekly.yaml",
        "output_path": tmp_path / "result.json",
    }


@pytest.mark.parametrize("failure", ["reproduction", "preflight", "candidate", "postflight"])
def test_formal_failure_order_claims_only_after_reproduction_and_never_restarts(
    formal_stub, monkeypatch, failure
):
    calls = []
    claim = formal_stub["root"] / "data/evaluation-claims" / f"{runner.CANDIDATE}.json"

    def rejected(*args, **kwargs):
        raise prior.RetrospectiveEvaluationError("synthetic failure")

    original_candidate = runner.run_candidate_walk_forward

    def candidate(*args):
        calls.append("candidate")
        assert claim.exists()
        if failure == "candidate":
            rejected()
        return original_candidate(*args)

    def verify(*args, **kwargs):
        calls.append("snapshot")
        if failure == "preflight" or (failure == "postflight" and calls.count("snapshot") == 2):
            rejected()

    monkeypatch.setattr(runner, "run_candidate_walk_forward", candidate)
    monkeypatch.setattr(prior, "_verify_snapshot", verify)
    if failure == "reproduction":
        monkeypatch.setattr(runner, "verify_control_reproduction", rejected)
    with pytest.raises(prior.RetrospectiveEvaluationError, match="synthetic failure"):
        runner.run(**formal_stub)
    assert claim.exists() == (failure in {"candidate", "postflight"})
    assert not formal_stub["output_path"].exists()
    if claim.exists():
        before = list(calls)
        with pytest.raises(prior.RetrospectiveEvaluationError, match="no second run"):
            runner.run(**formal_stub)
        assert calls == before


def test_formal_synthetic_run_retains_clean_provenance_and_write_once_result(formal_stub):
    report = runner.run(**formal_stub)
    stored = json.loads(formal_stub["output_path"].read_bytes())
    assert report["rows_scored"] == stored["rows_scored"] == 2
    assert stored["provenance"]["clean_worktree"] is True
    assert stored["provenance"]["git_head"] == "synthetic-clean-head"
    assert stored["provenance"]["evidence_class"] == EVIDENCE_CLASS
    assert stored["provenance"]["original_capture_known_at_preserved"] is True
    assert stored["promotion_permitted"] is False
