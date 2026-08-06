"""Tests for Phase 4 EV Backtest contract loading and validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from fpl.config import Phase4EVBacktestConfig, load_phase4_ev_backtest_evaluation
from fpl.models import defensive_contribution_v1, gk_saves_v1
from fpl.validate.metrics import PROBABILITY_FLOOR
from fpl.validate.points_harness import default_component_suite


def test_phase4_ev_backtest_contract_loads() -> None:
    load_phase4_ev_backtest_evaluation.cache_clear()
    contract = load_phase4_ev_backtest_evaluation()
    assert contract.phase == 4
    assert contract.contract_version == "1.1"
    assert contract.horizon.season == "2025-26"
    assert contract.horizon.start_gw == 29
    assert contract.horizon.end_gw == 38
    assert contract.horizon.expected_selected_gws == 10
    assert contract.horizon.expected_fixtures == 99
    assert contract.horizon.expected_player_fixture_rows == 8224
    assert contract.horizon.expected_gws == (29, 30, 31, 32, 33, 34, 35, 36, 37, 38)
    assert contract.support.max_fixture_points == 34
    assert contract.components.stage_a == "trailing_goals_attack_defence"
    assert contract.components.minutes == "concentration_adaptive_shrinkage_player_minutes_v3"
    assert contract.components.saves == "gk_saves_poisson_from_team_conceded_v1"
    assert contract.components.defensive_contribution == "trailing_dc_threshold_hit_bernoulli_v1"
    assert contract.components.bps_residual == "trailing_ict_ridge_residual_v1"
    assert contract.primary_architecture.name == "prospective_v3_coupled_seasonal_bonus"
    assert contract.primary_architecture.seasonal_appearance_min_rows == 3
    assert contract.primary_architecture.prior_season_blend_weight == 0.0
    assert contract.primary_architecture.historical_availability_multiplier == 1.0
    assert contract.diagnostic_comparator.name == "prospective_v1_independent_seasonal_bonus"
    assert contract.monte_carlo.draws == 2000
    assert contract.monte_carlo.seed == 202627


@pytest.mark.parametrize(
    ("path_keys", "wrong_val"),
    [
        (("contract_version",), "2.0"),
        (("phase",), 5),
        (("horizon", "season"), "2024-25"),
        (("horizon", "start_gw"), 28),
        (("horizon", "end_gw"), 37),
        (("horizon", "expected_selected_gws"), 9),
        (("horizon", "expected_fixtures"), 100),
        (("horizon", "expected_player_fixture_rows"), 8000),
        (("horizon", "split_unit"), "wrong_unit"),
        (("horizon", "cutoff_proxy"), "wrong_proxy"),
        (("support", "max_fixture_points"), 30),
        (("components", "stage_a"), "wrong_stage_a"),
        (("components", "minutes"), "wrong_minutes"),
        (("components", "saves"), "wrong_saves"),
        (("components", "defensive_contribution"), "wrong_dc"),
        (("components", "bps_residual"), "wrong_bps"),
        (("primary_architecture", "name"), "wrong_primary"),
        (("primary_architecture", "attacking"), "wrong_attacking"),
        (("primary_architecture", "assists"), "wrong_assists"),
        (("primary_architecture", "appearance"), "wrong_appearance"),
        (("primary_architecture", "seasonal_appearance_min_rows"), 5),
        (("primary_architecture", "prior_season_blend_weight"), 0.5),
        (("primary_architecture", "historical_availability_multiplier"), 0.9),
        (("primary_architecture", "scoring_rules"), "wrong_rules"),
        (("primary_architecture", "bonus_simulation"), "wrong_bonus"),
        (("diagnostic_comparator", "name"), "wrong_comp"),
        (("diagnostic_comparator", "attacking"), "wrong_comp_attacking"),
        (("diagnostic_comparator", "assists"), "wrong_comp_assists"),
        (("diagnostic_comparator", "role"), "wrong_role"),
        (("monte_carlo", "draws"), 1000),
        (("monte_carlo", "seed"), 12345),
        (("target_population", "eligible"), "all_players"),
        (("target_population", "include_zero_minutes"), False),
        (("target_population", "scoring_ruleset"), "wrong_ruleset"),
        (("metrics", "ranking"), ("wrong_metric",)),
        (("metrics", "calibration"), ("wrong_metric",)),
        (("metrics", "proper_distribution"), ("wrong_metric",)),
        (("scoring_calibration", "log_probability_floor"), 1e-6),
        (("scoring_calibration", "randomized_pit_band"), [0.2, 0.8]),
        (("scoring_calibration", "randomized_pit_seed"), 12345),
        (("components", "assists_architecture"), "wrong_assists_architecture"),
        (("components", "bps_simulation"), "wrong_bps_simulation"),
    ],
)
def test_phase4_ev_backtest_contract_valid_but_wrong_mutations_rejected(
    path_keys: tuple[str, ...], wrong_val: object
) -> None:
    doc = load_phase4_ev_backtest_evaluation().model_dump()
    target = doc
    for key in path_keys[:-1]:
        target = target[key]
    target[path_keys[-1]] = wrong_val

    with pytest.raises(ValidationError):
        Phase4EVBacktestConfig.model_validate(doc)


# --------------------------------------------------------------------------------------
# The contract must name what actually runs
# --------------------------------------------------------------------------------------
#
# Contract 1.0 froze `league_constant_save_rate_v1` and `team_rescaled_dc_v1`. Neither string
# existed anywhere in the repository, and both misdescribed the model they claimed to pin: the
# saves component is fitted fold-locally, and the DC component applies no destination-team
# rescaling at all. Every test passed, because they only checked the YAML against itself. These
# tests close that gap by comparing the frozen identity to the implementation constant.


def test_frozen_component_identities_equal_the_implementation_constants() -> None:
    contract = load_phase4_ev_backtest_evaluation()
    assert contract.components.saves == gk_saves_v1.NAME
    assert contract.components.defensive_contribution == defensive_contribution_v1.NAME


def test_frozen_identities_equal_what_the_executed_suite_installs() -> None:
    """The suite is what actually runs, so it is the authority the contract must match."""
    contract = load_phase4_ev_backtest_evaluation()
    suite = default_component_suite()

    assert contract.components.minutes == suite.minutes_name
    assert contract.components.saves == suite.saves_name
    assert contract.components.defensive_contribution == suite.dc_name
    # The comparator architecture is the suite's own goals/assists models, unmodified.
    assert contract.diagnostic_comparator.attacking == suite.goals_name
    assert contract.diagnostic_comparator.assists == suite.assists_name


def test_frozen_log_probability_floor_equals_the_scoring_constant() -> None:
    contract = load_phase4_ev_backtest_evaluation()
    assert contract.scoring_calibration.log_probability_floor == PROBABILITY_FLOOR


def test_version_bump_without_an_amendment_record_is_rejected() -> None:
    """A pre-registered contract may not change invisibly."""
    doc = load_phase4_ev_backtest_evaluation().model_dump()
    doc["amendments"] = []
    with pytest.raises(ValidationError, match="no amendment record"):
        Phase4EVBacktestConfig.model_validate(doc)


def test_amendment_history_is_pinned() -> None:
    """Rewriting a recorded amendment's evaluation count fails to load."""
    doc = load_phase4_ev_backtest_evaluation().model_dump()
    doc["amendments"][0]["candidates_evaluated_before_amendment"] = 3
    with pytest.raises(ValidationError, match="not the frozen record"):
        Phase4EVBacktestConfig.model_validate(doc)


def test_amendment_1_1_records_zero_prior_evaluations() -> None:
    """The correction was made before first execution; the record must say so."""
    contract = load_phase4_ev_backtest_evaluation()
    assert len(contract.amendments) == 1
    amendment = contract.amendments[0]
    assert amendment.version == "1.1"
    assert amendment.candidates_evaluated_before_amendment == 0
