"""The Phase 2 Stage B (player minutes) population, bin shape, baselines, metrics, and lift
gate are fixed before any model is fitted.

These tests are offline: no database, no network. A mismatched scoring threshold is injected
through the loader's ``scoring_path`` seam (a temporary scoring YAML), exercising the
fail-closed boundary cross-check without touching the real config.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from fpl.config import (
    PHASE2_TARGET_ROSTER_FORBIDDEN_COLUMNS,
    PHASE2_TARGET_ROSTER_PROXY_COLUMNS,
    Phase2EvaluationConfig,
    config_dir,
    load_phase1_evaluation,
    load_phase2_evaluation,
    load_scoring_rules,
)
from fpl.features.pit import OUTCOME_COLUMNS


def _document() -> dict[str, object]:
    loaded = yaml.safe_load((config_dir() / "phase2_evaluation.yaml").read_text("utf-8"))
    assert isinstance(loaded, dict)
    return loaded


# --------------------------------------------------------------------------------------
# The contract loads with its point-in-time cutoffs and frozen identity policy
# --------------------------------------------------------------------------------------


def test_phase2_contract_loads_with_point_in_time_cutoffs() -> None:
    load_phase2_evaluation.cache_clear()
    contract = load_phase2_evaluation()
    assert contract.phase == 2
    assert contract.contract_version == "1.2"
    assert contract.target.entity == "player"
    assert contract.target.grain == "season_player_code_fixture"
    assert contract.target.outcome == "minutes_distribution"
    assert contract.target.downstream_points_ruleset == "2026_27"
    assert contract.target.identity_policy == "code_is_cross_season_player_key"
    assert contract.cutoff.split_unit == "observed_gameweek"
    assert contract.cutoff.prediction_time == "archive_first_kickoff_proxy_for_gameweek_deadline"
    assert contract.cutoff.observed_results == "kickoff_time < as_of"
    assert contract.cutoff.snapshot_versions == "known_at <= as_of"
    assert contract.training.fit_transforms_within_fold is True
    assert contract.training.preserve_nulls is True
    assert contract.training.seed == 202627


def test_phase2_population_includes_zero_minutes_registered_population() -> None:
    contract = load_phase2_evaluation()
    assert contract.population.include_zero_minutes is True
    assert contract.population.eligible_outcome == "minutes_not_null"
    assert contract.population.registered_population == "mart_fact_player_fixture_minutes_not_null"
    # No player-history exclusion: every eligible row receives a fallback distribution.
    assert contract.training.no_minimum_player_history_exclusion is True
    assert (
        contract.training.cold_start_policy == "every_eligible_row_receives_fallback_distribution"
    )


# --------------------------------------------------------------------------------------
# The four ordered minute bins and the boundary cross-check
# --------------------------------------------------------------------------------------


def test_the_four_ordered_bin_keys_are_frozen() -> None:
    contract = load_phase2_evaluation()
    keys = tuple(bin_.key for bin_ in contract.output.bins)
    assert keys == ("0", "1_59", "60_89", "90")
    assert contract.output.long_bin_lower_boundary() == 60


def test_bin_boundaries_are_contiguous_and_open_ended_at_full_match() -> None:
    contract = load_phase2_evaluation()
    bins = contract.output.bins
    assert (bins[0].minutes_min, bins[0].minutes_max) == (0, 0)
    assert (bins[1].minutes_min, bins[1].minutes_max) == (1, 59)
    assert (bins[2].minutes_min, bins[2].minutes_max) == (60, 89)
    assert (bins[3].minutes_min, bins[3].minutes_max) == (90, None)


def test_a_dropped_bin_is_rejected() -> None:
    document = copy.deepcopy(_document())
    bins = document["output"]["bins"]
    assert isinstance(bins, list)
    bins.pop()  # only three bins remain

    with pytest.raises(ValueError, match="exactly four minute bins"):
        Phase2EvaluationConfig.model_validate(document)


def test_reordered_bin_keys_are_rejected() -> None:
    document = copy.deepcopy(_document())
    bins = document["output"]["bins"]
    assert isinstance(bins, list)
    bins[0], bins[1] = bins[1], bins[0]  # swap "0" and "1_59"

    with pytest.raises(ValueError, match="bin keys must be exactly"):
        Phase2EvaluationConfig.model_validate(document)


def test_a_non_contiguous_bin_boundary_is_rejected() -> None:
    document = copy.deepcopy(_document())
    bins = document["output"]["bins"]
    assert isinstance(bins, list)
    # Break the key-derived range: "60_89" must start at the key-derived 60, not 61.
    assert isinstance(bins[2], dict)
    bins[2]["minutes_min"] = 61

    with pytest.raises(ValueError, match="key-derived"):
        Phase2EvaluationConfig.model_validate(document)


def test_a_closed_full_match_bin_is_rejected() -> None:
    document = copy.deepcopy(_document())
    bins = document["output"]["bins"]
    assert isinstance(bins, list)
    assert isinstance(bins[3], dict)
    bins[3]["minutes_max"] = 95  # the "90" bin must be open-ended above (key-derived None)

    with pytest.raises(ValueError, match="key-derived"):
        Phase2EvaluationConfig.model_validate(document)


def test_changing_the_90_bin_minutes_min_is_rejected() -> None:
    """The "90" bin's minutes_min is derived from its key text (90), never hardcoded."""
    document = copy.deepcopy(_document())
    bins = document["output"]["bins"]
    assert isinstance(bins, list)
    assert isinstance(bins[3], dict)
    bins[3]["minutes_min"] = 89  # key-derived expectation is 90

    with pytest.raises(ValueError, match="key-derived"):
        Phase2EvaluationConfig.model_validate(document)


def test_changing_a_labeled_bin_range_is_rejected() -> None:
    """A labeled bin's max is derived by splitting the key on "_": "1_59" => 59, not 60."""
    document = copy.deepcopy(_document())
    bins = document["output"]["bins"]
    assert isinstance(bins, list)
    assert isinstance(bins[1], dict)
    bins[1]["minutes_max"] = 60  # key-derived expectation is 59

    with pytest.raises(ValueError, match="key-derived"):
        Phase2EvaluationConfig.model_validate(document)


def test_a_mismatched_scoring_threshold_fails_closed(tmp_path: Path) -> None:
    """The 60-minute boundary is read from the contract and cross-checked against BOTH
    appearance.long_play_minutes and clean_sheets.minimum_minutes of the configured ruleset.
    Both thresholds are shifted to 61 so they agree with each other but disagree with the
    contract's 60 boundary, exercising the fail-closed loader seam."""
    real = (config_dir() / "scoring_2026_27.yaml").read_text("utf-8")
    tampered = real.replace("long_play_minutes: 60", "long_play_minutes: 61", 1).replace(
        "minimum_minutes: 60", "minimum_minutes: 61", 1
    )
    scoring_path = tmp_path / "scoring_2026_27.yaml"
    scoring_path.write_text(tampered, encoding="utf-8")

    load_phase2_evaluation.cache_clear()
    with pytest.raises(ValueError, match="long-bin lower boundary"):
        load_phase2_evaluation(scoring_path=scoring_path)


def test_disagreeing_scoring_thresholds_fail_closed(tmp_path: Path) -> None:
    """If the two scoring thresholds disagree with each other, the cross-check fails even
    though the contract boundary is 60."""
    real = (config_dir() / "scoring_2026_27.yaml").read_text("utf-8")
    tampered = real.replace("minimum_minutes: 60", "minimum_minutes: 61", 1)
    scoring_path = tmp_path / "scoring_2026_27.yaml"
    scoring_path.write_text(tampered, encoding="utf-8")

    load_phase2_evaluation.cache_clear()
    with pytest.raises(ValueError, match="internally inconsistent"):
        load_phase2_evaluation(scoring_path=scoring_path)


def test_the_boundary_cross_check_is_satisfied_by_the_real_ruleset() -> None:
    contract = load_phase2_evaluation()
    scoring = load_scoring_rules("2026_27")
    assert scoring.appearance.long_play_minutes == 60
    assert scoring.clean_sheets.minimum_minutes == 60
    # Must not raise.
    contract.verify_minutes_boundary(scoring)


# --------------------------------------------------------------------------------------
# Baselines, metrics, gate, and reporting are pre-registered
# --------------------------------------------------------------------------------------


def test_stage_b_baselines_are_pre_registered_and_ep_next_is_excluded() -> None:
    contract = load_phase2_evaluation()
    expected_stage_b = {
        "position_minutes_frequency",
        "last_observed_player_minutes",
        "trailing_5_player_minutes",
        "trailing_5_team_position_minutes",
    }
    # EXACT set: the four names are required AND no extra may be present.
    assert contract.baselines.stage_b == expected_stage_b
    assert contract.baselines.excluded == {"fpl_ep_next_recorded_rules"}
    # The frozen definitions cover exactly the stage_b set, one definition each.
    definition_names = [definition.name for definition in contract.baselines.definitions]
    assert len(definition_names) == len(set(definition_names))  # no duplicates
    assert set(definition_names) == expected_stage_b


def test_metrics_are_pre_registered() -> None:
    contract = load_phase2_evaluation()
    assert contract.metrics.primary == "mean_log_score"
    assert contract.metrics.primary_direction == "lower_is_better"
    assert contract.metrics.proper_distribution == {
        "mean_log_score",
        "mean_ranked_probability_score",
    }
    assert contract.metrics.binary_guardrails == {
        "mean_brier_any_minutes",
        "mean_brier_60_plus",
    }
    assert contract.metrics.calibration == {
        "randomized_pit",
        "pit_interval_80_coverage",
        "reliability_any_minutes",
        "reliability_60_plus",
    }
    assert contract.metrics.reliability_buckets_carry_n is True
    assert contract.metrics.ranking == {"spearman_p60_within_position_gameweek"}


def test_promotion_gate_is_measurable_and_cannot_relax_coverage() -> None:
    gate = load_phase2_evaluation().promotion
    assert gate.compare_against == "best_eligible_required_stage_b_baseline"
    assert gate.comparison_population == "same_eligible_predictions"
    assert gate.relative_lift_formula == "(baseline - candidate) / abs(baseline)"
    # Amendment 1.2: bounded guardrails measured best-per-metric; new starter-ranking gate.
    assert gate.guardrail_comparison == "best_baseline_per_metric"
    assert gate.minimum_primary_relative_lift == 0.01
    assert gate.maximum_ranked_probability_score_relative_regression == 0.0
    assert gate.maximum_brier_relative_regression_any_minutes == 0.0
    assert gate.maximum_brier_relative_regression_60_plus == 0.0
    assert gate.maximum_spearman_p60_relative_regression == 0.0
    assert gate.pit_interval_80_maximum_absolute_error == 0.05
    assert gate.minimum_prediction_coverage == 1.0
    assert gate.minimum_fold_count == 181
    assert gate.require_no_season_mean_log_score_regression is True
    assert gate.require_zero_leakage_failures is True


def test_minimum_prediction_coverage_cannot_be_set_below_one() -> None:
    document = copy.deepcopy(_document())
    promotion = document["promotion"]
    assert isinstance(promotion, dict)
    promotion["minimum_prediction_coverage"] = 0.98

    with pytest.raises(ValueError, match=r"pinned to 1\.0"):
        Phase2EvaluationConfig.model_validate(document)


def test_reporting_dimensions_and_counts_are_pre_registered() -> None:
    contract = load_phase2_evaluation()
    assert contract.reporting.dimensions == {
        "fold",
        "season",
        "position",
        "home_away",
        "transfer_status",
        "player_history_cohort",
    }
    assert contract.reporting.counts == {
        "predictions",
        "exclusions",
        "cold_starts",
        "uncertainty",
    }
    assert contract.reporting.starts_reporting == "measured_only"


def test_historical_features_exclude_availability_and_disclaim_an_upper_bound() -> None:
    features = load_phase2_evaluation().historical_features
    assert features.availability_status == "excluded_unavailable_in_archive"
    assert features.point_in_time_only == "reconstructable_fields_only"
    assert features.live_availability_prospective_candidate == "separately_named_prospective_only"
    assert features.historical_score_is == "development_number_not_upper_bound"


def test_monte_carlo_is_out_of_scope() -> None:
    assert load_phase2_evaluation().monte_carlo.scope == "out_of_scope_closed_form_marginal"


# --------------------------------------------------------------------------------------
# Required policy/baseline/metric omissions are rejected
# --------------------------------------------------------------------------------------


def test_missing_required_baseline_is_rejected() -> None:
    document = copy.deepcopy(_document())
    stage_b = document["baselines"]["stage_b"]
    assert isinstance(stage_b, list)
    stage_b.remove("trailing_5_team_position_minutes")
    # Remove from the frozen definitions too, so the rejection comes from the exact-set check
    # on stage_b (the path whose wording this test pins).
    definitions = document["baselines"]["definitions"]
    assert isinstance(definitions, list)
    definitions[:] = [d for d in definitions if d.get("name") != "trailing_5_team_position_minutes"]

    with pytest.raises(ValueError, match="missing required Stage B baselines"):
        Phase2EvaluationConfig.model_validate(document)


def test_missing_required_metric_is_rejected() -> None:
    document = copy.deepcopy(_document())
    proper = document["metrics"]["proper_distribution"]
    assert isinstance(proper, list)
    proper.remove("mean_ranked_probability_score")

    with pytest.raises(ValueError, match="missing required proper distribution metrics"):
        Phase2EvaluationConfig.model_validate(document)


def test_missing_required_calibration_output_is_rejected() -> None:
    document = copy.deepcopy(_document())
    calibration = document["metrics"]["calibration"]
    assert isinstance(calibration, list)
    calibration.remove("reliability_60_plus")

    with pytest.raises(ValueError, match="missing required calibration outputs"):
        Phase2EvaluationConfig.model_validate(document)


def test_missing_required_dimension_is_rejected() -> None:
    document = copy.deepcopy(_document())
    dimensions = document["reporting"]["dimensions"]
    assert isinstance(dimensions, list)
    dimensions.remove("player_history_cohort")

    with pytest.raises(ValueError, match="missing required report dimensions"):
        Phase2EvaluationConfig.model_validate(document)


def test_extra_field_is_rejected() -> None:
    """extra='forbid' throughout: a typo or an unrecognised key surfaces as an error."""
    document = copy.deepcopy(_document())
    document["output"]["unexpected_key"] = True

    with pytest.raises(ValidationError, match=r"[Ee]xtra"):
        Phase2EvaluationConfig.model_validate(document)


# --------------------------------------------------------------------------------------
# Amendment 1.1 and Candidate V1 are exact, required pre-registration records
# --------------------------------------------------------------------------------------


def test_phase2_amendment_history_is_exactly_frozen() -> None:
    contract = load_phase2_evaluation()
    assert contract.contract_version == "1.2"
    assert tuple(
        (amendment.version, amendment.candidates_evaluated_before_amendment)
        for amendment in contract.amendments
    ) == (("1.1", 0), ("1.2", 1))


@pytest.mark.parametrize("version", ["1.0", "1.1", "2.0"])
def test_only_phase2_contract_version_1_2_is_accepted(version: str) -> None:
    document = copy.deepcopy(_document())
    document["contract_version"] = version
    with pytest.raises((ValidationError, ValueError)):
        Phase2EvaluationConfig.model_validate(document)


def test_phase2_current_amendment_record_is_required() -> None:
    document = copy.deepcopy(_document())
    document["amendments"] = []
    with pytest.raises((ValidationError, ValueError), match=r"amendment record|amendment history"):
        Phase2EvaluationConfig.model_validate(document)


def test_phase2_amendment_count_is_frozen() -> None:
    document = copy.deepcopy(_document())
    document["amendments"][0]["candidates_evaluated_before_amendment"] = 1
    with pytest.raises((ValidationError, ValueError), match="amendment history"):
        Phase2EvaluationConfig.model_validate(document)


def test_phase2_duplicate_amendment_is_rejected() -> None:
    document = copy.deepcopy(_document())
    document["amendments"].append(copy.deepcopy(document["amendments"][0]))
    with pytest.raises((ValidationError, ValueError), match="amendment history"):
        Phase2EvaluationConfig.model_validate(document)


def test_phase2_extra_or_reordered_amendment_is_rejected() -> None:
    document = copy.deepcopy(_document())
    extra = copy.deepcopy(document["amendments"][0])
    extra["version"] = "1.0"
    document["amendments"].insert(0, extra)
    with pytest.raises((ValidationError, ValueError), match="amendment history"):
        Phase2EvaluationConfig.model_validate(document)


def test_stage_b_candidate_v1_block_is_required() -> None:
    document = copy.deepcopy(_document())
    del document["stage_b_candidate_v1"]
    with pytest.raises(ValidationError, match="stage_b_candidate_v1"):
        Phase2EvaluationConfig.model_validate(document)


def test_stage_b_candidate_v1_is_exactly_pre_registered() -> None:
    candidate = load_phase2_evaluation().stage_b_candidate_v1
    assert candidate.name == "shrunk_trailing_5_player_minutes_v1"
    assert candidate.development_only is True
    assert candidate.development_only_reason == (
        "archive_target_roster_and_first_kickoff_cutoff_are_unversioned_proxies_"
        "and_archive_evidence_shaped_the_design"
    )
    assert candidate.grain == "season_player_code_fixture"
    assert candidate.identity == "stable_code"
    assert candidate.history_population == (
        "up_to_5_most_recent_prior_player_fixture_rows_including_zero_minutes"
    )
    assert candidate.history_order == "kickoff_time_then_season_then_fixture"
    assert candidate.history_window == 5
    assert candidate.history_observed_results == "kickoff_time < as_of"
    assert candidate.position_prior == (
        "fold_local_raw_position_minutes_frequency_for_target_current_position"
    )
    assert candidate.position_prior_fallback == "existing_unsmoothed_all_position_prior_rows"
    assert candidate.player_bin_counts == ("c_k_is_history_count_in_bin_k_and_n_equals_sum_k_c_k")
    assert candidate.estimator == "p_k(alpha)=(c_k+alpha*q_k)/(n+alpha)"
    assert candidate.additional_smoothing == "none"
    assert candidate.scoring_floor_role == (
        "existing_1e-12_floor_is_scoring_only_not_model_smoothing"
    )
    assert candidate.cold_start_fallback == "when_n_equals_0_distribution_is_exactly_q"
    assert candidate.prior_strength_grid == (1.0, 2.0, 5.0, 10.0, 20.0)
    assert candidate.selected_parameter == "alpha_only_history_window_remains_5"
    assert candidate.inner_holdout_observed_gameweeks == 6
    assert candidate.minimum_earlier_observed_gameweeks == 8
    assert candidate.inner_walk_forward == (
        "most_recent_6_observed_gameweeks_true_per_gameweek_predict_whole_gameweek_"
        "from_pre_gameweek_history_then_score_then_absorb"
    )
    assert candidate.inner_objective == "pooled_mean_log_score"
    assert candidate.tie_break == "smallest_alpha"
    assert candidate.insufficient_inner_history_fallback_alpha == 5.0
    assert candidate.fit_scope == "all_transforms_priors_and_grid_selection_are_fold_local"
    assert candidate.target_label_policy == "target_labels_never_enter_model_inputs"
    assert candidate.target_position_source == (
        "existing_unversioned_target_roster_proxy_current_position"
    )
    assert candidate.null_policy == "preserve_nulls"
    assert candidate.zero_minutes_policy == "include_in_history_and_training"
    assert candidate.assistant_manager_policy == "excluded_upstream_element_type_5"
    assert candidate.double_gameweek_policy == (
        "fixture_rows_remain_separate_same_pre_gameweek_state_no_within_gameweek_absorption"
    )
    assert candidate.double_gameweek_same_distribution == (
        "same_code_current_position_may_share_distribution_across_target_gameweek_fixtures_"
        "intentional_reportable_not_collapsed"
    )
    assert candidate.excluded_features == (
        "availability_status_team_opponent_and_home_away_are_not_features"
    )
    assert candidate.monte_carlo == "out_of_scope_closed_form"


@pytest.mark.parametrize(
    ("field", "mutated"),
    [
        ("name", "renamed_candidate"),
        ("development_only", False),
        ("development_only_reason", "historical_data_is_fully_point_in_time"),
        ("identity", "season_scoped_element"),
        ("grain", "player_gameweek"),
        ("history_population", "all_player_history"),
        ("history_order", "fixture_only"),
        ("history_window", 4),
        ("history_observed_results", "kickoff_time <= as_of"),
        ("position_prior", "full_archive_position_prior"),
        ("position_prior_fallback", "uniform"),
        ("player_bin_counts", "zero_minutes_are_not_counted"),
        ("estimator", "raw_player_frequency"),
        ("additional_smoothing", "laplace"),
        ("scoring_floor_role", "candidate_probability_floor"),
        ("cold_start_fallback", "uniform"),
        ("selected_parameter", "alpha_and_window"),
        ("inner_holdout_observed_gameweeks", 5),
        ("minimum_earlier_observed_gameweeks", 7),
        ("inner_walk_forward", "one_frozen_state_for_all_holdout_gameweeks"),
        ("inner_objective", "mean_ranked_probability_score"),
        ("tie_break", "largest_alpha"),
        ("fit_scope", "full_archive"),
        ("target_label_policy", "target_labels_are_features"),
        ("target_position_source", "end_of_season_dimension"),
        ("null_policy", "fill_zero"),
        ("zero_minutes_policy", "exclude"),
        ("assistant_manager_policy", "include"),
        ("double_gameweek_policy", "collapse_to_player_gameweek"),
        ("double_gameweek_same_distribution", "collapse_identical_rows"),
        ("excluded_features", "availability_is_allowed"),
        ("monte_carlo", "required"),
    ],
)
def test_stage_b_candidate_v1_literal_policy_cannot_be_weakened(
    field: str, mutated: object
) -> None:
    document = copy.deepcopy(_document())
    document["stage_b_candidate_v1"][field] = mutated
    with pytest.raises((ValidationError, ValueError)):
        Phase2EvaluationConfig.model_validate(document)


@pytest.mark.parametrize(
    "grid",
    [
        [1.0, 2.0, 5.0, 10.0],
        [1.0, 2.0, 5.0, 10.0, 20.0, 40.0],
        [2.0, 1.0, 5.0, 10.0, 20.0],
        [1.0, 2.0, 4.0, 10.0, 20.0],
    ],
)
def test_stage_b_candidate_v1_prior_strength_grid_is_exact(grid: list[float]) -> None:
    document = copy.deepcopy(_document())
    document["stage_b_candidate_v1"]["prior_strength_grid"] = grid
    with pytest.raises((ValidationError, ValueError), match="prior_strength_grid"):
        Phase2EvaluationConfig.model_validate(document)


def test_stage_b_candidate_v1_fallback_alpha_is_exact() -> None:
    document = copy.deepcopy(_document())
    document["stage_b_candidate_v1"]["insufficient_inner_history_fallback_alpha"] = 10.0
    with pytest.raises((ValidationError, ValueError), match="fallback_alpha"):
        Phase2EvaluationConfig.model_validate(document)


# --------------------------------------------------------------------------------------
# Phase 1 behaviour is preserved
# --------------------------------------------------------------------------------------


def test_phase1_contract_still_loads() -> None:
    contract = load_phase1_evaluation()
    assert contract.phase == 1
    assert contract.contract_version == "1.5"
    assert contract.target.grain == "season_team_fixture"


# --------------------------------------------------------------------------------------
# Target roster knowledge-time policy (Finding 2)
# --------------------------------------------------------------------------------------


def test_target_roster_proxy_columns_are_exact_and_disjoint_from_outcomes() -> None:
    contract = load_phase2_evaluation()
    expected = {
        "season",
        "gw",
        "fixture",
        "kickoff_time",
        "code",
        "position",
        "team_id",
        "opponent_team_id",
        "was_home",
    }
    # The proxy set equals the module constant exactly.
    assert contract.target_roster.proxy_columns == expected
    assert contract.target_roster.proxy_columns == PHASE2_TARGET_ROSTER_PROXY_COLUMNS
    # Identity/schedule only: disjoint from the authoritative OUTCOME_COLUMNS from features.pit.
    assert not (contract.target_roster.proxy_columns & OUTCOME_COLUMNS)
    # `code` is the stable cross-season key; the season-scoped aliases and the label are absent.
    assert "code" in contract.target_roster.proxy_columns
    for forbidden in ("element_id", "element", "minutes", "starts"):
        assert forbidden not in contract.target_roster.proxy_columns
    assert {"element_id", "element", "minutes", "starts"} == PHASE2_TARGET_ROSTER_FORBIDDEN_COLUMNS
    assert not (PHASE2_TARGET_ROSTER_PROXY_COLUMNS & PHASE2_TARGET_ROSTER_FORBIDDEN_COLUMNS)


def test_target_roster_status_records_unversioned_archive_proxy() -> None:
    roster = load_phase2_evaluation().target_roster
    assert roster.historical_roster_status == "archive_proxy_unversioned_at_real_deadline"
    assert roster.historical_source == (
        "archive_player_fixture_identity_schedule_proxy_projected_from_target_rows"
    )
    assert roster.minutes_role == "label_outside_model_facing_projection"
    assert roster.point_in_time_disclaimer == "not_fully_reconstructable_pit_at_real_deadline"
    assert roster.live_prospective_registry == (
        "versioned_player_registry_selected_known_at_le_as_of_"
        "before_model_sees_entity_team_position"
    )
    assert roster.cross_season_team_identity == (
        "season_qualified_team_id_resolved_to_stable_team_code"
    )


def test_missing_target_roster_section_is_rejected() -> None:
    document = copy.deepcopy(_document())
    del document["target_roster"]
    with pytest.raises(ValidationError, match="target_roster"):
        Phase2EvaluationConfig.model_validate(document)


def test_weakening_target_roster_policy_is_rejected() -> None:
    document = copy.deepcopy(_document())
    document["target_roster"]["historical_roster_status"] = "versioned_at_real_deadline"
    with pytest.raises((ValidationError, ValueError)):
        Phase2EvaluationConfig.model_validate(document)

    document = copy.deepcopy(_document())
    document["target_roster"]["minutes_role"] = "feature_inside_projection"
    with pytest.raises((ValidationError, ValueError)):
        Phase2EvaluationConfig.model_validate(document)


def test_target_roster_proxy_column_addition_is_rejected() -> None:
    document = copy.deepcopy(_document())
    document["target_roster"]["proxy_columns"].append("minutes")
    with pytest.raises((ValidationError, ValueError), match="proxy columns"):
        Phase2EvaluationConfig.model_validate(document)


def test_target_roster_proxy_column_deletion_is_rejected() -> None:
    document = copy.deepcopy(_document())
    document["target_roster"]["proxy_columns"].remove("code")
    with pytest.raises((ValidationError, ValueError), match="proxy columns"):
        Phase2EvaluationConfig.model_validate(document)


# --------------------------------------------------------------------------------------
# Baseline definitions are exactly frozen (Finding 3)
# --------------------------------------------------------------------------------------


def _baseline_def(document: dict[str, object], name: str) -> dict[str, object]:
    definitions = document["baselines"]["definitions"]
    assert isinstance(definitions, list)
    for entry in definitions:
        assert isinstance(entry, dict)
        if entry.get("name") == name:
            return entry
    raise AssertionError(f"baseline definition {name!r} not found")


def test_baseline_definition_window_is_frozen() -> None:
    document = copy.deepcopy(_document())
    _baseline_def(document, "trailing_5_player_minutes")["window"] = 7  # pinned to 5
    with pytest.raises((ValidationError, ValueError), match="frozen definition"):
        Phase2EvaluationConfig.model_validate(document)


def test_baseline_definition_smoothing_is_frozen() -> None:
    document = copy.deepcopy(_document())
    _baseline_def(document, "position_minutes_frequency")["additive_smoothing"] = "laplace"
    with pytest.raises((ValidationError, ValueError)):
        Phase2EvaluationConfig.model_validate(document)


def test_baseline_definition_fallback_is_frozen() -> None:
    document = copy.deepcopy(_document())
    _baseline_def(document, "last_observed_player_minutes")["fallback"] = (
        "unsmoothed_all_position_prior_rows"
    )
    with pytest.raises((ValidationError, ValueError), match="frozen definition"):
        Phase2EvaluationConfig.model_validate(document)


def test_baseline_definition_order_is_frozen() -> None:
    document = copy.deepcopy(_document())
    _baseline_def(document, "trailing_5_player_minutes")["order"] = "none_applicable_all_rows"
    with pytest.raises((ValidationError, ValueError), match="frozen definition"):
        Phase2EvaluationConfig.model_validate(document)


def test_baseline_definition_identity_is_frozen() -> None:
    document = copy.deepcopy(_document())
    _baseline_def(document, "trailing_5_team_position_minutes")["identity"] = "stable_code"
    with pytest.raises((ValidationError, ValueError), match="frozen definition"):
        Phase2EvaluationConfig.model_validate(document)


def test_baseline_definition_population_is_frozen() -> None:
    document = copy.deepcopy(_document())
    _baseline_def(document, "position_minutes_frequency")["population"] = (
        "up_to_5_most_recent_prior_player_fixture_rows_including_zero"
    )
    with pytest.raises((ValidationError, ValueError), match="frozen definition"):
        Phase2EvaluationConfig.model_validate(document)


def test_baseline_definitions_pin_raw_empirical_bin_frequency_estimator() -> None:
    """Every baseline definition carries the frozen probability estimator field."""
    contract = load_phase2_evaluation()
    expected_estimator = "raw_empirical_bin_frequency_count_divided_by_n"
    assert {
        definition.name: definition.estimator for definition in contract.baselines.definitions
    } == {
        "position_minutes_frequency": expected_estimator,
        "last_observed_player_minutes": expected_estimator,
        "trailing_5_player_minutes": expected_estimator,
        "trailing_5_team_position_minutes": expected_estimator,
    }


def test_baseline_definition_estimator_is_frozen() -> None:
    """Changing the estimator on any baseline is rejected. The field is a single-value Literal
    pinned per-name in ``_PHASE2_BASELINE_PINS``, mirroring ``additive_smoothing``: any other
    value fails to load (via the Literal validator, and via the per-name pin if the Literal is
    ever widened)."""
    document = copy.deepcopy(_document())
    _baseline_def(document, "trailing_5_player_minutes")["estimator"] = (
        "additive_smoothed_bin_frequency"
    )
    with pytest.raises((ValidationError, ValueError)):
        Phase2EvaluationConfig.model_validate(document)


def test_adding_a_fifth_baseline_name_is_rejected() -> None:
    document = copy.deepcopy(_document())
    document["baselines"]["stage_b"].append("extra_baseline")
    # A name not backed by a frozen definition is rejected before the exact-set check.
    with pytest.raises((ValidationError, ValueError), match="must match the stage_b set"):
        Phase2EvaluationConfig.model_validate(document)


def test_removing_a_baseline_name_is_rejected() -> None:
    document = copy.deepcopy(_document())
    document["baselines"]["stage_b"].remove("trailing_5_player_minutes")
    definitions = document["baselines"]["definitions"]
    assert isinstance(definitions, list)
    definitions[:] = [d for d in definitions if d.get("name") != "trailing_5_player_minutes"]
    with pytest.raises((ValidationError, ValueError), match="missing required Stage B baselines"):
        Phase2EvaluationConfig.model_validate(document)


# --------------------------------------------------------------------------------------
# Frozen numeric / boundary policy (Finding 4)
# --------------------------------------------------------------------------------------


def test_training_minimum_observed_gameweeks_is_frozen() -> None:
    document = copy.deepcopy(_document())
    document["training"]["minimum_observed_gameweeks"] = 9  # pinned to 8
    with pytest.raises((ValidationError, ValueError)):
        Phase2EvaluationConfig.model_validate(document)


def test_training_seed_is_frozen() -> None:
    document = copy.deepcopy(_document())
    document["training"]["seed"] = 12345  # pinned to 202627
    with pytest.raises((ValidationError, ValueError)):
        Phase2EvaluationConfig.model_validate(document)


def test_target_downstream_points_ruleset_is_frozen() -> None:
    document = copy.deepcopy(_document())
    document["target"]["downstream_points_ruleset"] = "2025_26"  # pinned to "2026_27"
    with pytest.raises((ValidationError, ValueError)):
        Phase2EvaluationConfig.model_validate(document)


def test_promotion_minimum_fold_count_is_frozen() -> None:
    document = copy.deepcopy(_document())
    document["promotion"]["minimum_fold_count"] = 180  # pinned to 181
    with pytest.raises((ValidationError, ValueError)):
        Phase2EvaluationConfig.model_validate(document)


def test_promotion_minimum_primary_relative_lift_is_frozen() -> None:
    document = copy.deepcopy(_document())
    document["promotion"]["minimum_primary_relative_lift"] = 0.02  # pinned to 0.01
    with pytest.raises((ValidationError, ValueError), match=r"pinned to 0\.01"):
        Phase2EvaluationConfig.model_validate(document)


def test_promotion_rps_regression_is_frozen() -> None:
    document = copy.deepcopy(_document())
    document["promotion"]["maximum_ranked_probability_score_relative_regression"] = (
        0.01  # pinned to 0.0
    )
    with pytest.raises((ValidationError, ValueError), match="aggregate guardrail"):
        Phase2EvaluationConfig.model_validate(document)


def test_promotion_brier_regressions_are_frozen() -> None:
    for field in (
        "maximum_brier_relative_regression_any_minutes",
        "maximum_brier_relative_regression_60_plus",
    ):
        document = copy.deepcopy(_document())
        document["promotion"][field] = 0.01  # pinned to 0.0
        with pytest.raises((ValidationError, ValueError), match="aggregate guardrail"):
            Phase2EvaluationConfig.model_validate(document)


def test_promotion_pit_interval_error_is_frozen() -> None:
    document = copy.deepcopy(_document())
    document["promotion"]["pit_interval_80_maximum_absolute_error"] = 0.06  # pinned to 0.05
    with pytest.raises((ValidationError, ValueError), match=r"pinned to 0\.05"):
        Phase2EvaluationConfig.model_validate(document)


# --------------------------------------------------------------------------------------
# Amendment 1.2: best-per-metric guardrails + starter-ranking gate (additive, harder only)
# --------------------------------------------------------------------------------------


def test_amendment_1_2_spearman_regression_is_pinned_to_zero() -> None:
    """The new starter-ranking gate may not be relaxed away."""
    document = copy.deepcopy(_document())
    document["promotion"]["maximum_spearman_p60_relative_regression"] = 0.01
    with pytest.raises((ValidationError, ValueError), match="spearman_p60_relative_regression"):
        Phase2EvaluationConfig.model_validate(document)


def test_amendment_1_2_guardrail_comparison_is_pinned() -> None:
    """The best-per-metric comparison is part of the contract, not implicit in code."""
    contract = load_phase2_evaluation()
    assert contract.promotion.guardrail_comparison == "best_baseline_per_metric"
    document = copy.deepcopy(_document())
    document["promotion"]["guardrail_comparison"] = "single_log_score_comparator"
    with pytest.raises((ValidationError, ValueError)):
        Phase2EvaluationConfig.model_validate(document)


def test_amendment_1_2_missing_spearman_gate_is_rejected() -> None:
    """extra='forbid' on the gate means a 1.2 file that drops the new key fails to load."""
    document = copy.deepcopy(_document())
    del document["promotion"]["maximum_spearman_p60_relative_regression"]
    with pytest.raises(
        (ValidationError, ValueError), match="maximum_spearman_p60_relative_regression"
    ):
        Phase2EvaluationConfig.model_validate(document)


def test_amendment_1_2_count_is_frozen_at_one_candidate_evaluated() -> None:
    """The amendment honestly records that one candidate (V1) had been evaluated before it."""
    document = copy.deepcopy(_document())
    for amendment in document["amendments"]:
        if amendment["version"] == "1.2":
            amendment["candidates_evaluated_before_amendment"] = 0  # wrong: V1 was evaluated
    with pytest.raises((ValidationError, ValueError), match="amendment history"):
        Phase2EvaluationConfig.model_validate(document)


# --------------------------------------------------------------------------------------
# Scoring / calibration definitions are frozen (Finding 5)
# --------------------------------------------------------------------------------------


def test_scoring_calibration_values_are_frozen() -> None:
    cal = load_phase2_evaluation().scoring_calibration
    assert cal.log_probability_floor == 1e-12
    assert cal.ranked_probability_score == (
        "sum_of_squared_ordered_category_cdf_errors_not_physical_minute_distance"
    )
    assert cal.brier == "squared_binary_probability_error"
    assert cal.randomized_pit_band == (0.1, 0.9)
    assert cal.randomized_pit_seed == 202627
    assert cal.reliability_edges == tuple(round(i / 10, 1) for i in range(11))
    assert cal.reliability_buckets == "left_closed_right_open_except_final_bucket_right_closed"
    assert cal.reliability_bucket_n is True


def test_missing_scoring_calibration_section_is_rejected() -> None:
    document = copy.deepcopy(_document())
    del document["scoring_calibration"]
    with pytest.raises(ValidationError, match="scoring_calibration"):
        Phase2EvaluationConfig.model_validate(document)


def test_log_probability_floor_is_frozen() -> None:
    document = copy.deepcopy(_document())
    document["scoring_calibration"]["log_probability_floor"] = 1e-11
    with pytest.raises((ValidationError, ValueError), match=r"pinned to 1e-12"):
        Phase2EvaluationConfig.model_validate(document)


def test_randomized_pit_band_is_frozen() -> None:
    document = copy.deepcopy(_document())
    document["scoring_calibration"]["randomized_pit_band"] = [0.05, 0.95]
    with pytest.raises((ValidationError, ValueError), match=r"pinned to \(0\.1, 0\.9\)"):
        Phase2EvaluationConfig.model_validate(document)


def test_reliability_edges_are_frozen() -> None:
    document = copy.deepcopy(_document())
    document["scoring_calibration"]["reliability_edges"] = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    with pytest.raises((ValidationError, ValueError), match="reliability_edges"):
        Phase2EvaluationConfig.model_validate(document)


def test_ranked_probability_score_definition_is_frozen() -> None:
    document = copy.deepcopy(_document())
    document["scoring_calibration"]["ranked_probability_score"] = "physical_minute_distance"
    with pytest.raises((ValidationError, ValueError)):
        Phase2EvaluationConfig.model_validate(document)


def test_brier_definition_is_frozen() -> None:
    document = copy.deepcopy(_document())
    document["scoring_calibration"]["brier"] = "spherical_score"
    with pytest.raises((ValidationError, ValueError)):
        Phase2EvaluationConfig.model_validate(document)


def test_randomized_pit_seed_is_frozen() -> None:
    document = copy.deepcopy(_document())
    document["scoring_calibration"]["randomized_pit_seed"] = 1
    with pytest.raises((ValidationError, ValueError)):
        Phase2EvaluationConfig.model_validate(document)


def test_reliability_buckets_definition_is_frozen() -> None:
    document = copy.deepcopy(_document())
    document["scoring_calibration"]["reliability_buckets"] = "right_closed_left_open"
    with pytest.raises((ValidationError, ValueError)):
        Phase2EvaluationConfig.model_validate(document)


def test_reliability_bucket_n_is_frozen() -> None:
    document = copy.deepcopy(_document())
    document["scoring_calibration"]["reliability_bucket_n"] = False
    with pytest.raises((ValidationError, ValueError)):
        Phase2EvaluationConfig.model_validate(document)


# --------------------------------------------------------------------------------------
# Frozen sets reject additions as well as deletions (Finding 6)
# --------------------------------------------------------------------------------------


def test_adding_an_extra_excluded_baseline_is_rejected() -> None:
    document = copy.deepcopy(_document())
    document["baselines"]["excluded"].append("extra_excluded")
    with pytest.raises((ValidationError, ValueError), match="unexpected excluded baselines"):
        Phase2EvaluationConfig.model_validate(document)


def test_adding_an_extra_proper_distribution_metric_is_rejected() -> None:
    document = copy.deepcopy(_document())
    document["metrics"]["proper_distribution"].append("extra_proper")
    with pytest.raises(
        (ValidationError, ValueError), match="unexpected proper distribution metrics"
    ):
        Phase2EvaluationConfig.model_validate(document)


def test_adding_an_extra_binary_guardrail_is_rejected() -> None:
    document = copy.deepcopy(_document())
    document["metrics"]["binary_guardrails"].append("extra_binary")
    with pytest.raises((ValidationError, ValueError), match="unexpected binary guardrail metrics"):
        Phase2EvaluationConfig.model_validate(document)


def test_adding_an_extra_calibration_output_is_rejected() -> None:
    document = copy.deepcopy(_document())
    document["metrics"]["calibration"].append("extra_cal")
    with pytest.raises((ValidationError, ValueError), match="unexpected calibration outputs"):
        Phase2EvaluationConfig.model_validate(document)


def test_adding_an_extra_ranking_output_is_rejected() -> None:
    document = copy.deepcopy(_document())
    document["metrics"]["ranking"].append("extra_ranking")
    with pytest.raises((ValidationError, ValueError), match="unexpected ranking outputs"):
        Phase2EvaluationConfig.model_validate(document)


def test_adding_an_extra_report_dimension_is_rejected() -> None:
    document = copy.deepcopy(_document())
    document["reporting"]["dimensions"].append("extra_dim")
    with pytest.raises((ValidationError, ValueError), match="unexpected report dimensions"):
        Phase2EvaluationConfig.model_validate(document)


def test_adding_an_extra_report_count_is_rejected() -> None:
    document = copy.deepcopy(_document())
    document["reporting"]["counts"].append("extra_count")
    with pytest.raises((ValidationError, ValueError), match="unexpected report counts"):
        Phase2EvaluationConfig.model_validate(document)
