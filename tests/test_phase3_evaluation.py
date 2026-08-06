"""Tests for Phase 3 Stage C (player attacking goals) evaluation contract.

These tests are offline: no database, no network.
"""

from __future__ import annotations

import copy

import pytest
import yaml
from pydantic import ValidationError

from fpl.config import (
    PHASE3_TARGET_ROSTER_FORBIDDEN_COLUMNS,
    PHASE3_TARGET_ROSTER_PROXY_COLUMNS,
    Phase3EvaluationConfig,
    config_dir,
    load_phase3_evaluation,
)
from fpl.features.pit import OUTCOME_COLUMNS


def _document() -> dict[str, object]:
    loaded = yaml.safe_load((config_dir() / "phase3_evaluation.yaml").read_text("utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_phase3_contract_loads_with_point_in_time_cutoffs() -> None:
    load_phase3_evaluation.cache_clear()
    contract = load_phase3_evaluation()
    assert contract.phase == 3
    assert contract.contract_version == "1.4"
    assert contract.target.entity == "player"
    assert contract.target.grain == "season_player_code_fixture"
    assert contract.target.outcome == "goals_distribution"
    assert contract.target.downstream_points_ruleset == "2026_27"
    assert contract.target.identity_policy == "code_is_cross_season_player_key"
    assert contract.cutoff.split_unit == "observed_gameweek"
    assert contract.cutoff.prediction_time == "archive_first_kickoff_proxy_for_gameweek_deadline"
    assert contract.cutoff.observed_results == "kickoff_time < as_of"
    assert contract.cutoff.snapshot_versions == "known_at <= as_of"
    assert contract.training.fit_transforms_within_fold is True
    assert contract.training.preserve_nulls is True
    assert contract.training.seed == 202627


def test_phase3_population_retains_zero_minutes() -> None:
    contract = load_phase3_evaluation()
    assert contract.population.include_zero_minutes is True
    assert contract.population.eligible_outcome == "minutes_not_null"
    assert contract.population.registered_population == "mart_fact_player_fixture_minutes_not_null"
    assert contract.training.no_minimum_player_history_exclusion is True
    assert (
        contract.training.cold_start_policy == "every_eligible_row_receives_fallback_distribution"
    )


def test_phase3_target_roster_proxy_columns() -> None:
    contract = load_phase3_evaluation()
    assert contract.target_roster.proxy_columns == PHASE3_TARGET_ROSTER_PROXY_COLUMNS
    assert PHASE3_TARGET_ROSTER_PROXY_COLUMNS.isdisjoint(PHASE3_TARGET_ROSTER_FORBIDDEN_COLUMNS)
    assert PHASE3_TARGET_ROSTER_PROXY_COLUMNS.isdisjoint(OUTCOME_COLUMNS)


def test_phase3_baselines_exact_set() -> None:
    contract = load_phase3_evaluation()
    names = {defn.name for defn in contract.baselines.definitions}
    assert names == {"positional_goal_rate_poisson", "trailing_player_goal_rate_poisson"}
    assert contract.baselines.stage_c_attacking == names


def test_phase3_metrics_and_promotion_gates() -> None:
    contract = load_phase3_evaluation()
    assert contract.metrics.primary == "mean_log_score"
    assert contract.promotion.minimum_primary_relative_lift == 0.01
    assert contract.promotion.maximum_ranked_probability_score_relative_regression == 0.0
    assert contract.promotion.maximum_brier_relative_regression_at_least_one_goal == 0.0
    assert contract.promotion.pit_interval_80_maximum_absolute_error == 0.05
    assert contract.promotion.minimum_fold_count == 181
    assert contract.promotion.minimum_prediction_coverage == 1.0
    assert contract.promotion.require_no_season_mean_log_score_regression is True
    assert contract.promotion.require_zero_leakage_failures is True


def test_version_bump_without_amendment_is_rejected() -> None:
    document = copy.deepcopy(_document())
    document["contract_version"] = "1.5"
    with pytest.raises(ValidationError, match="no amendment record"):
        Phase3EvaluationConfig.model_validate(document)


def test_phase3_candidate_v1_policy_is_frozen_and_additive() -> None:
    contract = load_phase3_evaluation()
    cand = contract.stage_c_candidate_v1
    assert cand.name == "xg_informed_trailing_player_goals_v1"
    assert cand.development_only is True
    assert cand.alpha == 5.0
    assert cand.finishing_keep == 0.05
    assert cand.history_window == 5
    assert (
        cand.selected_parameter == "none_fixed_closed_form_estimator_no_grid_no_inner_walk_forward"
    )
    assert cand.reduces_to_v1_baseline == (
        "when_all_trailing_xg_unmeasured_candidate_equals_v1_trailing_baseline_bit_for_bit"
    )


def test_phase3_candidate_v1_constants_are_pinned() -> None:
    """alpha and finishing_keep cannot be changed without failing to load."""
    document = copy.deepcopy(_document())
    document["stage_c_candidate_v1"]["alpha"] = 7.0
    with pytest.raises(ValidationError, match=r"alpha is pinned to 5\.0"):
        Phase3EvaluationConfig.model_validate(document)
    document2 = copy.deepcopy(_document())
    document2["stage_c_candidate_v1"]["finishing_keep"] = 0.2
    with pytest.raises(ValidationError, match=r"finishing_keep is pinned to 0\.05"):
        Phase3EvaluationConfig.model_validate(document2)


def test_phase3_amendment_history_is_frozen() -> None:
    """The 1.1 amendment record may not be reordered, dropped, duplicated, or count-altered."""
    document = copy.deepcopy(_document())
    # Altering the candidates-evaluated count fails to load.
    document["amendments"][0]["candidates_evaluated_before_amendment"] = 1
    with pytest.raises(ValidationError, match="not the frozen record"):
        Phase3EvaluationConfig.model_validate(document)


def test_phase3_v1_0_baselines_metrics_and_gate_unchanged() -> None:
    """Amendment 1.1 is additive: no v1.0 baseline/metric/gate field moved."""
    contract = load_phase3_evaluation()
    assert {defn.name for defn in contract.baselines.definitions} == {
        "positional_goal_rate_poisson",
        "trailing_player_goal_rate_poisson",
    }
    assert contract.promotion.minimum_primary_relative_lift == 0.01
    assert contract.promotion.minimum_fold_count == 181
    assert contract.promotion.require_no_season_mean_log_score_regression is True


def test_phase3_candidate_v2_policy_is_frozen_and_additive() -> None:
    contract = load_phase3_evaluation()
    cand = contract.stage_c_candidate_v2
    assert cand.name == "coupled_team_share_attacking_goals_v2"
    assert cand.development_only is True
    assert cand.alpha == 5.0
    assert cand.history_window == 5
    assert cand.stage_a_model == "frozen_trailing_goals_attack_defence_reused_not_reimplemented"
    assert cand.appeared_rows_filter == (
        "prior_rows_with_minutes_gt_0_only_did_not_play_prior_rows_excluded_from_rate"
    )
    assert cand.rate == "rate_i_equals_lambda_team_times_share_i"
    assert (
        cand.selected_parameter == "none_fixed_closed_form_estimator_no_grid_no_inner_walk_forward"
    )
    assert cand.reduces_to_baseline == (
        "where_stage_a_is_uninformative_candidate_equals_v1_trailing_player_goal_rate_poisson_bit_for_bit"
    )


def test_phase3_candidate_v2_alpha_is_pinned() -> None:
    """alpha cannot be changed without failing to load."""
    document = copy.deepcopy(_document())
    document["stage_c_candidate_v2"]["alpha"] = 7.0
    with pytest.raises(ValidationError, match=r"alpha is pinned to 5\.0"):
        Phase3EvaluationConfig.model_validate(document)


def test_phase3_amendment_1_2_record_is_frozen() -> None:
    """The 1.2 amendment record (candidates_evaluated_before_amendment: 1) is pinned."""
    document = copy.deepcopy(_document())
    document["amendments"][1]["candidates_evaluated_before_amendment"] = 0
    with pytest.raises(ValidationError, match="not the frozen record"):
        Phase3EvaluationConfig.model_validate(document)


def test_phase3_v2_is_additive_to_v1_0_comparison_rules() -> None:
    """Amendment 1.2 changes no v1.0/1.1 baseline/metric/gate field."""
    contract = load_phase3_evaluation()
    assert {defn.name for defn in contract.baselines.definitions} == {
        "positional_goal_rate_poisson",
        "trailing_player_goal_rate_poisson",
    }
    assert contract.metrics.primary == "mean_log_score"
    assert contract.promotion.minimum_primary_relative_lift == 0.01
    assert contract.promotion.maximum_ranked_probability_score_relative_regression == 0.0
    assert contract.promotion.maximum_brier_relative_regression_at_least_one_goal == 0.0
    assert contract.promotion.pit_interval_80_maximum_absolute_error == 0.05
    assert contract.promotion.minimum_fold_count == 181
    assert contract.promotion.require_no_season_mean_log_score_regression is True


def test_phase3_candidate_v3_policy_is_frozen_and_additive() -> None:
    contract = load_phase3_evaluation()
    cand = contract.stage_c_candidate_v3
    assert cand.name == "minutes_gated_coupled_team_share_attacking_goals_v3"
    assert cand.development_only is True
    assert cand.alpha == 5.0
    assert cand.history_window == 5
    assert cand.minutes_baseline == "trailing_5_player_minutes"
    assert cand.appearance_probability == (
        "p_play_equals_one_minus_trailing5_minutes_distribution_bin_zero"
    )
    assert cand.conservation == (
        "renormalise_share_i_times_p_play_i_to_sum_to_one_so_sum_i_rate_i_equals_lambda_team"
    )
    assert cand.reduces_to_v2_when_gating_off is True
    assert (
        cand.selected_parameter == "none_fixed_closed_form_estimator_no_grid_no_inner_walk_forward"
    )


def test_phase3_candidate_v3_alpha_is_pinned() -> None:
    document = copy.deepcopy(_document())
    document["stage_c_candidate_v3"]["alpha"] = 7.0
    with pytest.raises(ValidationError, match=r"alpha is pinned to 5\.0"):
        Phase3EvaluationConfig.model_validate(document)


def test_phase3_amendment_1_3_record_is_frozen() -> None:
    """The 1.3 amendment record (candidates_evaluated_before_amendment: 2) is pinned."""
    document = copy.deepcopy(_document())
    document["amendments"][2]["candidates_evaluated_before_amendment"] = 1
    with pytest.raises(ValidationError, match="not the frozen record"):
        Phase3EvaluationConfig.model_validate(document)


def test_phase3_v3_is_additive_to_v1_0_comparison_rules() -> None:
    """Amendment 1.3 changes no v1.0/1.1/1.2 baseline/metric/gate field."""
    contract = load_phase3_evaluation()
    assert {defn.name for defn in contract.baselines.definitions} == {
        "positional_goal_rate_poisson",
        "trailing_player_goal_rate_poisson",
    }
    assert contract.promotion.minimum_primary_relative_lift == 0.01
    assert contract.promotion.minimum_fold_count == 181
    assert contract.promotion.require_no_season_mean_log_score_regression is True


def test_phase3_candidate_v4_policy_is_frozen_and_additive() -> None:
    contract = load_phase3_evaluation()
    cand = contract.stage_c_candidate_v4
    assert cand.name == "exposure_weighted_xg_team_share_attacking_goals_v4"
    assert cand.development_only is True
    assert cand.alpha == 5.0
    assert cand.prior_minutes == 90.0
    assert cand.history_window == 5
    assert cand.signal == "expected_goals_only_no_fallback"
    assert cand.minutes_baseline == "trailing_5_player_minutes"
    assert cand.window == "option_a_last_five_appeared_rows_then_measured_signal_rows_among_them"
    expected_selected = (
        "none_fixed_closed_form_estimator_no_grid_no_inner_walk_forward_"
        "prior_minutes_is_fixed_not_selected"
    )
    assert cand.selected_parameter == expected_selected
    assert cand.null_policy == (
        "preserve_nulls_xg_null_means_unmeasured_never_zero_filled_excluded_from_signal_and_minutes_sums"
    )


def test_phase3_candidate_v4_constants_are_pinned() -> None:
    """alpha and prior_minutes cannot be changed without failing to load."""
    document = copy.deepcopy(_document())
    document["stage_c_candidate_v4"]["alpha"] = 7.0
    with pytest.raises(ValidationError, match=r"alpha is pinned to 5\.0"):
        Phase3EvaluationConfig.model_validate(document)
    document2 = copy.deepcopy(_document())
    document2["stage_c_candidate_v4"]["prior_minutes"] = 270.0
    with pytest.raises(ValidationError, match=r"prior_minutes is pinned to 90\.0"):
        Phase3EvaluationConfig.model_validate(document2)


def test_phase3_amendment_1_4_record_is_frozen() -> None:
    """The 1.4 amendment record (candidates_evaluated_before_amendment: 3) is pinned."""
    document = copy.deepcopy(_document())
    document["amendments"][3]["candidates_evaluated_before_amendment"] = 2
    with pytest.raises(ValidationError, match="not the frozen record"):
        Phase3EvaluationConfig.model_validate(document)


def test_phase3_v4_is_additive_to_v1_0_comparison_rules() -> None:
    """Amendment 1.4 changes no v1.0/1.1/1.2/1.3 baseline/metric/gate field."""
    contract = load_phase3_evaluation()
    assert {defn.name for defn in contract.baselines.definitions} == {
        "positional_goal_rate_poisson",
        "trailing_player_goal_rate_poisson",
    }
    assert contract.promotion.minimum_primary_relative_lift == 0.01
    assert contract.promotion.minimum_fold_count == 181
    assert contract.promotion.require_no_season_mean_log_score_regression is True


def test_phase3_v4_block_is_required_at_1_4() -> None:
    """A 1.4 config that drops the V4 block fails to load rather than scoring a different model."""
    document = copy.deepcopy(_document())
    document.pop("stage_c_candidate_v4", None)
    with pytest.raises(ValidationError):
        Phase3EvaluationConfig.model_validate(document)
