"""The Phase 1 split, baselines, metrics, and lift gate are fixed before fitting."""

from __future__ import annotations

import copy

import pytest
import yaml
from pydantic import ValidationError

from fpl.config import Phase1EvaluationConfig, config_dir, load_phase1_evaluation


def _document() -> dict[str, object]:
    loaded = yaml.safe_load((config_dir() / "phase1_evaluation.yaml").read_text("utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_phase1_contract_loads_with_point_in_time_cutoffs() -> None:
    contract = load_phase1_evaluation()
    assert contract.phase == 1
    assert contract.target.grain == "season_team_fixture"
    assert contract.target.outcome == "goals_distribution"
    assert contract.target.downstream_points_ruleset == "2026_27"
    assert contract.cutoff.split_unit == "observed_gameweek"
    assert contract.cutoff.observed_results == "kickoff_time < as_of"
    assert contract.cutoff.snapshot_versions == "known_at <= as_of"
    assert contract.training.fit_transforms_within_fold is True
    assert contract.training.preserve_nulls is True


def test_phase1_contract_pins_honest_baselines() -> None:
    contract = load_phase1_evaluation()
    assert {
        "league_home_away_goals",
        "trailing_goals_attack_defence",
        "trailing_xg_attack_defence",
        "naive_fdr",
        "promoted_team_pooled_prior",
    } <= contract.baselines.stage_a
    assert {
        "fpl_ep_next_recorded_rules",
        "trailing_5_recorded_points",
        "naive_fdr",
    } <= contract.baselines.downstream_player_points


def test_phase1_contract_requires_distribution_and_calibration_metrics() -> None:
    contract = load_phase1_evaluation()
    assert contract.metrics.primary == "mean_log_score"
    assert contract.metrics.primary_direction == "lower_is_better"
    assert {"mean_log_score", "mean_crps"} <= contract.metrics.proper_distribution
    assert {"randomized_pit", "interval_80_coverage"} <= contract.metrics.calibration
    assert "spearman_within_gameweek" in contract.metrics.ranking


def test_phase1_promotion_gate_is_measurable() -> None:
    gate = load_phase1_evaluation().promotion
    assert gate.compare_against == "best_eligible_required_stage_a_baseline"
    assert gate.comparison_population == "same_eligible_predictions"
    assert gate.relative_lift_formula == "(baseline - candidate) / abs(baseline)"
    assert gate.minimum_primary_relative_lift == 0.01
    assert gate.maximum_crps_relative_regression == 0.0
    assert gate.interval_80_maximum_absolute_error == 0.05
    assert gate.minimum_fixture_coverage == 0.98
    assert gate.minimum_fold_count == 20
    assert gate.require_each_reported_season_to_pass is True
    assert gate.require_zero_leakage_failures is True


def test_missing_required_baseline_is_rejected() -> None:
    document = copy.deepcopy(_document())
    baselines = document["baselines"]
    assert isinstance(baselines, dict)
    stage_a = baselines["stage_a"]
    assert isinstance(stage_a, list)
    stage_a.remove("naive_fdr")

    with pytest.raises(ValueError, match="missing required Stage A baselines"):
        Phase1EvaluationConfig.model_validate(document)


def test_contiguous_gameweek_policy_is_rejected() -> None:
    document = copy.deepcopy(_document())
    cutoff = document["cutoff"]
    assert isinstance(cutoff, dict)
    cutoff["split_unit"] = "range_1_38"

    with pytest.raises(ValidationError, match="observed_gameweek"):
        Phase1EvaluationConfig.model_validate(document)


def test_report_cannot_hide_exclusions_or_cold_starts() -> None:
    document = copy.deepcopy(_document())
    reporting = document["reporting"]
    assert isinstance(reporting, dict)
    reporting["counts"] = ["predictions", "exclusions"]

    with pytest.raises(ValueError, match="missing report counts"):
        Phase1EvaluationConfig.model_validate(document)
