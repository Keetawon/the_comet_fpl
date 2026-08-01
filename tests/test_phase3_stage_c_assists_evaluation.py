"""Tests for the Phase 3 Stage C (player attacking assists) evaluation contract.

A separate frozen contract from the goals contract. Offline: no database, no network.
"""

from __future__ import annotations

import copy

import pytest
import yaml
from pydantic import ValidationError

from fpl.config import (
    PHASE3_STAGE_C_ASSISTS_TARGET_ROSTER_FORBIDDEN_COLUMNS,
    PHASE3_TARGET_ROSTER_PROXY_COLUMNS,
    Phase3StageCAssistsEvaluationConfig,
    config_dir,
    load_phase3_stage_c_assists_evaluation,
)
from fpl.features.pit import OUTCOME_COLUMNS


def _document() -> dict[str, object]:
    loaded = yaml.safe_load(
        (config_dir() / "phase3_stage_c_assists_evaluation.yaml").read_text("utf-8")
    )
    assert isinstance(loaded, dict)
    return loaded


def test_assists_contract_loads_with_point_in_time_cutoffs() -> None:
    load_phase3_stage_c_assists_evaluation.cache_clear()
    contract = load_phase3_stage_c_assists_evaluation()
    assert contract.phase == 3
    assert contract.contract_version == "1.1"
    assert contract.target.entity == "player"
    assert contract.target.grain == "season_player_code_fixture"
    assert contract.target.outcome == "assists_distribution"
    assert contract.target.downstream_points_ruleset == "2026_27"
    assert contract.target.identity_policy == "code_is_cross_season_player_key"
    assert contract.cutoff.split_unit == "observed_gameweek"
    assert contract.cutoff.prediction_time == "archive_first_kickoff_proxy_for_gameweek_deadline"
    assert contract.cutoff.observed_results == "kickoff_time < as_of"
    assert contract.cutoff.snapshot_versions == "known_at <= as_of"
    assert contract.training.fit_transforms_within_fold is True
    assert contract.training.preserve_nulls is True
    assert contract.training.seed == 202627


def test_assists_population_retains_zero_minutes() -> None:
    contract = load_phase3_stage_c_assists_evaluation()
    assert contract.population.include_zero_minutes is True
    assert contract.population.eligible_outcome == "minutes_not_null"
    assert contract.population.registered_population == "mart_fact_player_fixture_minutes_not_null"
    assert contract.training.no_minimum_player_history_exclusion is True
    assert (
        contract.training.cold_start_policy == "every_eligible_row_receives_fallback_distribution"
    )


def test_assists_target_roster_proxy_columns() -> None:
    contract = load_phase3_stage_c_assists_evaluation()
    assert contract.target_roster.proxy_columns == PHASE3_TARGET_ROSTER_PROXY_COLUMNS
    assert PHASE3_TARGET_ROSTER_PROXY_COLUMNS.isdisjoint(
        PHASE3_STAGE_C_ASSISTS_TARGET_ROSTER_FORBIDDEN_COLUMNS
    )
    # The assist label column is forbidden (label stays outside the model projection).
    assert "assists" in PHASE3_STAGE_C_ASSISTS_TARGET_ROSTER_FORBIDDEN_COLUMNS
    assert PHASE3_TARGET_ROSTER_PROXY_COLUMNS.isdisjoint(OUTCOME_COLUMNS)


def test_assists_baselines_exact_set() -> None:
    contract = load_phase3_stage_c_assists_evaluation()
    names = {defn.name for defn in contract.baselines.definitions}
    assert names == {"positional_assist_rate_poisson", "trailing_player_assist_rate_poisson"}
    assert contract.baselines.stage_c_attacking_assists == names


def test_assists_xa_signal_policy() -> None:
    contract = load_phase3_stage_c_assists_evaluation()
    assert contract.xa_signal_policy.xa_handling == "use_when_measured_within_covered_seasons"
    assert contract.xa_signal_policy.xa_covered_seasons_judging is True
    # Same covered-seasons profile as the goals xG policy.
    assert contract.xa_signal_policy.xa_covered_seasons == ("2023-24", "2024-25", "2025-26")
    assert contract.xa_signal_policy.fallback_signal == "creativity"


def test_assists_metrics_and_promotion_gates() -> None:
    contract = load_phase3_stage_c_assists_evaluation()
    assert contract.metrics.primary == "mean_log_score"
    assert contract.promotion.minimum_primary_relative_lift == 0.01
    assert contract.promotion.maximum_ranked_probability_score_relative_regression == 0.0
    assert contract.promotion.maximum_brier_relative_regression_at_least_one_assist == 0.0
    assert contract.promotion.pit_interval_80_maximum_absolute_error == 0.05
    assert contract.promotion.minimum_fold_count == 181
    assert contract.promotion.minimum_prediction_coverage == 1.0
    assert contract.promotion.require_no_season_mean_log_score_regression is True
    assert contract.promotion.require_zero_leakage_failures is True


def test_assists_candidate_v1_policy_is_frozen_and_additive() -> None:
    contract = load_phase3_stage_c_assists_evaluation()
    cand = contract.stage_c_assists_candidate_v1
    assert cand is not None
    assert cand.name == "xa_informed_trailing_player_assists_v1"
    assert cand.development_only is True
    assert cand.alpha == 5.0
    assert cand.finishing_keep == 0.05
    assert cand.history_window == 5
    assert cand.creativity_rescale == (
        "fold_local_positional_factor_pos_assist_mean_over_mean_creativity_per_appearance"
    )
    assert (
        cand.selected_parameter == "none_fixed_closed_form_estimator_no_grid_no_inner_walk_forward"
    )
    assert cand.reduces_to_v1_baseline == (
        "when_all_trailing_xa_unmeasured_candidate_equals_v1_trailing_assist_baseline_bit_for_bit"
    )


def test_assists_candidate_v1_constants_are_pinned() -> None:
    """alpha and finishing_keep cannot be changed without failing to load."""
    document = copy.deepcopy(_document())
    document["stage_c_assists_candidate_v1"]["alpha"] = 7.0
    with pytest.raises(ValidationError, match=r"alpha is pinned to 5\.0"):
        Phase3StageCAssistsEvaluationConfig.model_validate(document)
    document2 = copy.deepcopy(_document())
    document2["stage_c_assists_candidate_v1"]["finishing_keep"] = 0.2
    with pytest.raises(ValidationError, match=r"finishing_keep is pinned to 0\.05"):
        Phase3StageCAssistsEvaluationConfig.model_validate(document2)


def test_assists_amendment_1_1_record_is_frozen() -> None:
    """The 1.1 amendment record (candidates_evaluated_before_amendment: 0) is pinned."""
    document = copy.deepcopy(_document())
    document["amendments"][0]["candidates_evaluated_before_amendment"] = 1
    with pytest.raises(ValidationError, match="not the frozen record"):
        Phase3StageCAssistsEvaluationConfig.model_validate(document)


def test_assists_v1_1_is_additive_to_v1_0_comparison_rules() -> None:
    """Amendment 1.1 changes no v1.0 baseline/metric/gate field."""
    contract = load_phase3_stage_c_assists_evaluation()
    assert {defn.name for defn in contract.baselines.definitions} == {
        "positional_assist_rate_poisson",
        "trailing_player_assist_rate_poisson",
    }
    assert contract.metrics.primary == "mean_log_score"
    assert contract.promotion.minimum_primary_relative_lift == 0.01
    assert contract.promotion.maximum_ranked_probability_score_relative_regression == 0.0
    assert contract.promotion.maximum_brier_relative_regression_at_least_one_assist == 0.0
    assert contract.promotion.pit_interval_80_maximum_absolute_error == 0.05
    assert contract.promotion.minimum_fold_count == 181
    assert contract.promotion.require_no_season_mean_log_score_regression is True


def test_assists_v1_0_document_is_baseline_only() -> None:
    """A v1.0 document (no candidate block) loads as baseline-only (candidate None)."""
    document = copy.deepcopy(_document())
    document["contract_version"] = "1.0"
    document["amendments"] = []
    document.pop("stage_c_assists_candidate_v1", None)
    contract = Phase3StageCAssistsEvaluationConfig.model_validate(document)
    assert contract.contract_version == "1.0"
    assert contract.stage_c_assists_candidate_v1 is None


def test_assists_v1_0_document_rejects_a_candidate_block() -> None:
    """v1.0 is baseline-only; carrying a candidate block at v1.0 fails to load."""
    document = copy.deepcopy(_document())
    document["contract_version"] = "1.0"
    document["amendments"] = []
    with pytest.raises(ValidationError, match="baseline-only"):
        Phase3StageCAssistsEvaluationConfig.model_validate(document)


def test_assists_version_bump_without_amendment_is_rejected() -> None:
    document = copy.deepcopy(_document())
    document["contract_version"] = "1.2"
    with pytest.raises(ValidationError, match="no amendment record"):
        Phase3StageCAssistsEvaluationConfig.model_validate(document)


def test_assists_baseline_field_regression_is_rejected() -> None:
    """The goals-only brier gate field name is not the assists one; a goals field name fails."""
    document = copy.deepcopy(_document())
    document["promotion"]["maximum_brier_relative_regression_at_least_one_goal"] = 0.0
    with pytest.raises(ValidationError):
        Phase3StageCAssistsEvaluationConfig.model_validate(document)


def test_assists_brier_regression_gate_field_is_pinned() -> None:
    document = copy.deepcopy(_document())
    document["promotion"]["maximum_brier_relative_regression_at_least_one_assist"] = 0.1
    with pytest.raises(ValidationError, match=r"pinned to 0\.0"):
        Phase3StageCAssistsEvaluationConfig.model_validate(document)


def test_assists_does_not_perturb_goals_contract() -> None:
    """The assists contract is a separate file; the goals contract still loads at 1.3."""
    from fpl.config import load_phase3_evaluation

    load_phase3_evaluation.cache_clear()
    goals = load_phase3_evaluation()
    assert goals.contract_version == "1.3"
    assert {defn.name for defn in goals.baselines.definitions} == {
        "positional_goal_rate_poisson",
        "trailing_player_goal_rate_poisson",
    }
