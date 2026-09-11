"""The additive real-SOT retrospective preregistration, before outer scoring."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from fpl.config import (
    V2RealSotRetrospectiveContract,
    load_v2_real_sot_retrospective_evaluation,
    load_v2_team_environment_evaluation,
)


def _document() -> dict[str, object]:
    loaded = yaml.safe_load(
        (Path("config") / "v2_real_sot_retrospective_evaluation.yaml").read_text(encoding="utf-8")
    )
    assert isinstance(loaded, dict)
    return loaded


def test_real_sot_contract_is_separate_and_retrospective_only() -> None:
    contract = load_v2_real_sot_retrospective_evaluation()
    assert contract.status == "development_only"
    assert contract.evidence_class == "retrospective_backfill_development"
    assert contract.source.preserve_original_known_at is True
    assert contract.source.later_capture_known_at_permitted is True
    assert contract.development_gate.promotion_requires_strict_prospective_confirmation is True


def test_real_sot_contract_licenses_exactly_one_new_field() -> None:
    contract = load_v2_real_sot_retrospective_evaluation()
    assert contract.source.target_provider == "fpl_archive"
    assert contract.source.xg_provider == "fpl_archive"
    assert contract.source.sot_provider == "pl_sdp"
    assert contract.source.sot_provider_field == "ontargetScoringAtt"
    assert contract.source.metric_whitelist == ("shots_on_target",)
    assert (
        contract.source.version_selection
        == "earliest_successful_complete_match_stats_payload_by_fetched_at_then_payload_id"
    )
    assert contract.source.version_order == "fetched_at_ascending_then_payload_id"


def test_real_sot_candidate_is_the_control_plus_only_sot() -> None:
    contract = load_v2_real_sot_retrospective_evaluation()
    assert contract.baseline == "trailing_goals_attack_defence"
    assert contract.control.signals == ("goals", "expected_goals")
    assert contract.candidate.name == "retrospective_real_sot_team_environment_v1"
    assert contract.candidate.signals == (*contract.control.signals, "shots_on_target")


def test_coverage_rule_selects_three_complete_xg_seasons() -> None:
    population = load_v2_real_sot_retrospective_evaluation().population
    assert population.minimum_joint_season_coverage == 0.95
    assert population.eligible_seasons == ("2023-24", "2024-25", "2025-26")
    assert population.training_seasons == "all_prior_archive_seasons_before_as_of"


def test_seed_and_walk_forward_settings_are_frozen() -> None:
    contract = load_v2_real_sot_retrospective_evaluation()
    assert contract.random_seed == 20260904
    assert contract.walk_forward.minimum_training_observed_gameweeks == 8
    assert contract.walk_forward.minimum_team_matches == 3
    assert contract.walk_forward.inner_holdout_observed_gameweeks == 6
    assert contract.walk_forward.minimum_inner_training_observed_gameweeks == 10


def test_fewer_than_two_eligible_seasons_is_refused() -> None:
    document = _document()
    population = document["population"]
    assert isinstance(population, dict)
    population["eligible_seasons"] = ["2025-26"]
    with pytest.raises(ValidationError, match=r"at least 2|fewer than two"):
        V2RealSotRetrospectiveContract.model_validate(document)


def test_any_extra_metric_is_refused() -> None:
    document = _document()
    source = document["source"]
    assert isinstance(source, dict)
    source["metric_whitelist"] = ["shots_on_target", "possession"]
    with pytest.raises(ValidationError, match="shots_on_target only"):
        V2RealSotRetrospectiveContract.model_validate(document)


def test_candidate_cannot_change_a_second_signal() -> None:
    document = _document()
    candidate = document["candidate"]
    assert isinstance(candidate, dict)
    candidate["signals"] = ["goals", "expected_goals", "shots_on_target", "possession"]
    with pytest.raises(ValidationError, match="only by shots_on_target"):
        V2RealSotRetrospectiveContract.model_validate(document)


def test_capture_time_cannot_be_rewritten_or_hidden() -> None:
    document = _document()
    source = document["source"]
    assert isinstance(source, dict)
    source["preserve_original_known_at"] = False
    with pytest.raises(ValidationError):
        V2RealSotRetrospectiveContract.model_validate(document)


def test_development_gate_compares_sot_to_the_exact_control() -> None:
    gate = load_v2_real_sot_retrospective_evaluation().development_gate
    assert gate.compare_against == "retrospective_goals_xg_control_v1"
    assert gate.minimum_relative_log_lift == 0.01
    assert gate.maximum_crps_relative_regression == 0.0
    assert gate.require_no_season_log_score_regression is True


def test_frozen_v2_contract_is_not_reused_or_changed() -> None:
    old = load_v2_team_environment_evaluation()
    new = load_v2_real_sot_retrospective_evaluation()
    assert old.contract_version == "1.0"
    assert old.population.provider == "fpl_archive"
    assert new.candidate.name not in {candidate.name for candidate in old.ablation.candidates}
