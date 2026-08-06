"""Tests for Phase 4 EV Backtest contract loading and validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from fpl.config import Phase4EVBacktestConfig, load_phase4_ev_backtest_evaluation


def test_phase4_ev_backtest_contract_loads() -> None:
    load_phase4_ev_backtest_evaluation.cache_clear()
    contract = load_phase4_ev_backtest_evaluation()
    assert contract.phase == 4
    assert contract.contract_version == "1.0"
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
    assert contract.components.saves == "league_constant_save_rate_v1"
    assert contract.components.defensive_contribution == "team_rescaled_dc_v1"
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
