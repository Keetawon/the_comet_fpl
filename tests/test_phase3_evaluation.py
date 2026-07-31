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
    assert contract.contract_version == "1.0"
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
    document["contract_version"] = "1.1"
    with pytest.raises(ValidationError, match="no amendment record"):
        Phase3EvaluationConfig.model_validate(document)
