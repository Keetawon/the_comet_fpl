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
    assert contract.cutoff.prediction_time == "archive_first_kickoff_proxy_for_gameweek_deadline"
    assert contract.cutoff.observed_results == "kickoff_time < as_of"
    assert contract.cutoff.snapshot_versions == "known_at <= as_of"
    assert contract.training.fit_transforms_within_fold is True
    assert contract.training.preserve_nulls is True


def test_candidate_v2_search_is_pre_registered() -> None:
    candidate = load_phase1_evaluation().stage_a_candidate
    assert candidate.name == "dixon_coles_team_goals_v2"
    assert candidate.inner_holdout_observed_gameweeks == 6
    assert candidate.minimum_inner_training_observed_gameweeks == 12
    assert candidate.half_life_days == (40.0, 80.0, 160.0, 320.0, 640.0)
    assert candidate.include_no_decay is True
    assert candidate.prior_matches == (2.0, 4.0, 8.0, 16.0, 32.0)
    assert candidate.fallback_half_life_days is None
    assert candidate.fallback_prior_matches == 8.0


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
    assert {
        "randomized_pit",
        "interval_80_coverage",
        "pit_interval_80_coverage",
    } <= contract.metrics.calibration
    assert "spearman_within_gameweek" in contract.metrics.ranking


def test_phase1_promotion_gate_is_measurable() -> None:
    gate = load_phase1_evaluation().promotion
    assert gate.compare_against == "best_eligible_required_stage_a_baseline"
    assert gate.comparison_population == "same_eligible_predictions"
    assert gate.relative_lift_formula == "(baseline - candidate) / abs(baseline)"
    assert gate.minimum_primary_relative_lift == 0.01
    assert gate.maximum_crps_relative_regression == 0.0
    assert gate.pit_interval_80_maximum_absolute_error == 0.05
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


# --------------------------------------------------------------------------------------
# Amendment 1.1: the calibration gate names its metric
# --------------------------------------------------------------------------------------


def test_the_calibration_gate_names_the_metric_it_measures() -> None:
    """The superseded key said `interval_80` without saying which interval.

    That ambiguity is the whole defect: the harness built the raw central interval, which for
    a count distribution is governed by the discreteness of the pmf rather than by the model.
    `extra="forbid"` means a config still carrying the old key cannot load at all, so the
    change cannot be half-applied.
    """
    document = copy.deepcopy(_document())
    promotion = document["promotion"]
    assert isinstance(promotion, dict)
    assert "interval_80_maximum_absolute_error" not in promotion
    assert promotion["pit_interval_80_maximum_absolute_error"] == 0.05

    promotion["interval_80_maximum_absolute_error"] = 0.05
    with pytest.raises(ValidationError, match=r"[Ee]xtra"):
        Phase1EvaluationConfig.model_validate(document)


def test_the_amendment_is_recorded_with_its_reason_and_evidence() -> None:
    contract = load_phase1_evaluation()
    assert contract.contract_version == "1.4"
    amendment = next(a for a in contract.amendments if a.version == "1.1")
    assert amendment.candidates_evaluated_before_amendment == 0, (
        "amending a pre-registered gate is only legitimate before a candidate could bias it"
    )
    assert "pit_interval_80_maximum_absolute_error" in amendment.changed
    assert amendment.reason and amendment.evidence


def test_a_version_bump_without_an_amendment_record_is_rejected() -> None:
    """Otherwise a gate could be rewritten between two commits and read as always having said so."""
    document = copy.deepcopy(_document())
    document["amendments"] = []

    with pytest.raises(ValueError, match="no amendment record"):
        Phase1EvaluationConfig.model_validate(document)


def test_an_amendment_cannot_be_recorded_without_a_date() -> None:
    document = copy.deepcopy(_document())
    amendments = document["amendments"]
    assert isinstance(amendments, list)
    amendments[0]["date"] = "soon"

    with pytest.raises(ValidationError, match="pattern"):
        Phase1EvaluationConfig.model_validate(document)


def test_the_baseline_identity_fix_is_recorded_and_made_the_bar_harder() -> None:
    """Amendment 1.2 changed no field here, only what the baselines compute.

    A baseline change moves the number a candidate is judged against, so it belongs in the
    amendment log even though the YAML gates are untouched. The direction is what makes it
    legitimate: the score a candidate must reach fell from 1.5075 to 1.4853.
    """
    amendment = next(a for a in load_phase1_evaluation().amendments if a.version == "1.2")
    assert amendment.candidates_evaluated_before_amendment == 0
    assert "team_code" in amendment.changed


def test_candidate_v2_fixes_are_recorded_without_moving_the_gate() -> None:
    contract = load_phase1_evaluation()
    amendment = next(a for a in contract.amendments if a.version == "1.3")
    assert amendment.candidates_evaluated_before_amendment == 1
    assert "No baseline, gate, tolerance" in amendment.changed
    assert "17 to 22 observed gameweeks" in amendment.reason
    assert contract.promotion.minimum_primary_relative_lift == 0.01
    assert contract.promotion.maximum_crps_relative_regression == 0.0
    assert contract.promotion.pit_interval_80_maximum_absolute_error == 0.05


def test_candidate_search_grids_must_be_ordered_and_unique() -> None:
    document = copy.deepcopy(_document())
    candidate = document["stage_a_candidate"]
    assert isinstance(candidate, dict)
    candidate["half_life_days"] = [80.0, 40.0, 80.0]

    with pytest.raises(ValueError, match="unique and increasing"):
        Phase1EvaluationConfig.model_validate(document)


# --------------------------------------------------------------------------------------
# Amendment 1.4: Candidate V3 development pre-registration
# --------------------------------------------------------------------------------------


def test_candidate_v3_search_is_pre_registered() -> None:
    candidate = load_phase1_evaluation().stage_a_candidate_v3
    assert candidate is not None
    assert candidate.name == "dynamic_team_goals_v3"
    assert candidate.development_only is True
    assert candidate.learning_rate == (0.05, 0.10, 0.20)
    assert candidate.retention == (0.985, 0.995, 1.0)
    assert candidate.season_retention == (0.5, 0.75, 1.0)
    assert candidate.fallback_learning_rate == 0.10
    assert candidate.fallback_retention == 0.995
    assert candidate.fallback_season_retention == 0.75
    assert candidate.inner_holdout_observed_gameweeks == 6
    assert candidate.minimum_inner_training_observed_gameweeks == 12


def test_amendment_1_4_records_the_v3_pre_registration_additively() -> None:
    contract = load_phase1_evaluation()
    amendment = next(a for a in contract.amendments if a.version == "1.4")
    assert amendment.candidates_evaluated_before_amendment == 2
    assert amendment.date == "2026-07-28"
    assert "additive" in amendment.changed
    assert "No existing baseline" in amendment.changed
    # The V2 policy and every promotion gate are untouched.
    assert contract.stage_a_candidate.name == "dixon_coles_team_goals_v2"
    gate = contract.promotion
    assert gate.minimum_primary_relative_lift == 0.01
    assert gate.maximum_crps_relative_regression == 0.0
    assert gate.pit_interval_80_maximum_absolute_error == 0.05


def test_v3_grid_values_must_be_ordered_unique_and_bounded() -> None:
    document = copy.deepcopy(_document())
    candidate = document["stage_a_candidate_v3"]
    assert isinstance(candidate, dict)
    candidate["retention"] = [1.0, 0.995, 0.985]  # decreasing

    with pytest.raises(ValueError, match="unique and increasing"):
        Phase1EvaluationConfig.model_validate(document)


def test_v3_retention_above_one_is_rejected() -> None:
    document = copy.deepcopy(_document())
    candidate = document["stage_a_candidate_v3"]
    assert isinstance(candidate, dict)
    candidate["season_retention"] = [0.5, 0.75, 1.5]  # > 1.0 is not a retention factor

    with pytest.raises(ValueError, match="season_retention"):
        Phase1EvaluationConfig.model_validate(document)


def test_v3_fallback_outside_the_grid_is_rejected() -> None:
    document = copy.deepcopy(_document())
    candidate = document["stage_a_candidate_v3"]
    assert isinstance(candidate, dict)
    candidate["fallback_learning_rate"] = 0.13  # not in the declared grid

    with pytest.raises(ValueError, match="fallback learning rate"):
        Phase1EvaluationConfig.model_validate(document)


def test_v3_must_stay_development_only() -> None:
    """A config that silently promoted V3 to a promotion candidate must fail to load."""
    document = copy.deepcopy(_document())
    candidate = document["stage_a_candidate_v3"]
    assert isinstance(candidate, dict)
    candidate["development_only"] = False

    with pytest.raises(ValidationError, match=r"[Ee]xtra|development_only|Literal"):
        Phase1EvaluationConfig.model_validate(document)


def test_v3_is_optional_and_does_not_touch_v1_v2_results() -> None:
    """Removing the V3 block still loads the contract, with V2 exactly as before."""
    document = copy.deepcopy(_document())
    document.pop("stage_a_candidate_v3")
    contract = Phase1EvaluationConfig.model_validate(document)
    assert contract.stage_a_candidate_v3 is None
    assert contract.stage_a_candidate.name == "dixon_coles_team_goals_v2"
