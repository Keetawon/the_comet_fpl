"""The V2 evaluation contracts, enforced as data rather than trusted as prose.

`config/phase1_evaluation.yaml` established the discipline these follow: a contract written
before any candidate exists, whose loader refuses the shapes that would let a result be chosen
after the fact. The additions specific to V2 are the nested-ladder rule -- an ablation whose
rungs are not nested cannot attribute a lift to a signal -- and the standing requirement that
no historical result may promote anything.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from fpl.config import (
    SdpMetricDictionary,
    V2GkSavesContract,
    V2TeamEnvironmentContract,
    load_sdp_metrics,
    load_v2_gk_saves_evaluation,
    load_v2_team_environment_evaluation,
)
from fpl.models.football_engine_v2 import BLENDABLE_SIGNALS, DEFAULT_SIGNALS


def test_both_contracts_load_and_declare_themselves_development_only() -> None:
    team = load_v2_team_environment_evaluation()
    saves = load_v2_gk_saves_evaluation()
    assert team.status == "development_only"
    assert saves.status == "development_only"


def test_no_historical_result_can_promote_anything() -> None:
    """The standing caveat: the target roster and kickoff cutoff are unversioned proxies."""
    for contract in (load_v2_team_environment_evaluation(), load_v2_gk_saves_evaluation()):
        assert contract.promotion.promotion_requires_prospective_window is True


def test_the_ablation_ladder_is_nested() -> None:
    """Rungs that merely differ cannot attribute a lift to a signal."""
    contract = load_v2_team_environment_evaluation()
    previous: set[str] = set()
    for candidate in contract.ablation.candidates:
        signals = set(candidate.signals)
        assert previous <= signals, f"{candidate.name} dropped {sorted(previous - signals)}"
        previous = signals


def test_a_non_nested_ladder_is_refused(tmp_path: Path) -> None:
    """The guard is real, not decorative."""
    source = yaml.safe_load(
        (Path("config") / "v2_team_environment_evaluation.yaml").read_text(encoding="utf-8")
    )
    source["ablation"]["candidates"] = [
        {"name": "a", "signals": ["goals"], "rationale": "x"},
        {"name": "b", "signals": ["expected_goals"], "rationale": "y"},
    ]
    with pytest.raises(ValidationError, match="does not extend"):
        V2TeamEnvironmentContract.model_validate(source)


def test_a_version_bump_without_an_amendment_record_is_refused() -> None:
    """Amending a pre-registered contract is legitimate only with the reason recorded."""
    source = yaml.safe_load(
        (Path("config") / "v2_team_environment_evaluation.yaml").read_text(encoding="utf-8")
    )
    source["contract_version"] = "1.1"
    with pytest.raises(ValidationError, match="no matching amendment record"):
        V2TeamEnvironmentContract.model_validate(source)


def test_the_saves_contract_declares_exactly_one_incumbent() -> None:
    """A comparison without a declared baseline has no bar."""
    source = yaml.safe_load(
        (Path("config") / "v2_gk_saves_evaluation.yaml").read_text(encoding="utf-8")
    )
    for candidate in source["candidates"]:
        candidate["is_baseline"] = True
    with pytest.raises(ValidationError, match="exactly one baseline"):
        V2GkSavesContract.model_validate(source)


def test_a_contiguous_gameweek_policy_is_not_expressible() -> None:
    """2022-23 has no GW7; assuming contiguity misaligns that whole season's split."""
    source = yaml.safe_load(
        (Path("config") / "v2_team_environment_evaluation.yaml").read_text(encoding="utf-8")
    )
    source["population"]["gameweeks"] = "1_to_38"
    with pytest.raises(ValidationError):
        V2TeamEnvironmentContract.model_validate(source)


def test_random_splits_cannot_be_permitted() -> None:
    source = yaml.safe_load(
        (Path("config") / "v2_team_environment_evaluation.yaml").read_text(encoding="utf-8")
    )
    source["walk_forward"]["forbid_random_split"] = False
    with pytest.raises(ValidationError):
        V2TeamEnvironmentContract.model_validate(source)


def test_calibration_is_the_randomised_pit_not_a_raw_interval() -> None:
    """Phase 1 amendment 1.1 measured that a raw central interval PREFERS biased models."""
    assert load_v2_team_environment_evaluation().metrics.calibration == "randomised_pit"
    assert load_v2_gk_saves_evaluation().metrics.calibration == "randomised_pit"


def test_every_contract_signal_is_known_to_the_engine() -> None:
    """A contract naming a signal the engine cannot fit would silently score a lesser model."""
    known = {spec.name for spec in DEFAULT_SIGNALS}
    for candidate in load_v2_team_environment_evaluation().ablation.candidates:
        for signal in candidate.signals:
            assert signal in known, signal
            assert signal in BLENDABLE_SIGNALS, f"{signal} cannot enter a goal-rate blend"


def test_results_must_be_split_before_they_are_discussed() -> None:
    """A pooled figure has misled this repository three times; season is mandatory."""
    assert "season" in load_v2_team_environment_evaluation().splits
    assert "season" in load_v2_gk_saves_evaluation().splits


# -- the metric dictionary ---------------------------------------------------------------


def test_every_provider_field_name_is_declared_unverified() -> None:
    """No SDP payload was observable when this dictionary was written.

    Promoting `verified_semantics` requires an observed payload AND a reconciliation, so a
    provider field silently marked verified would be an unbacked claim.
    """
    for metric in load_sdp_metrics().metrics:
        assert metric.verified_semantics is False, metric.local_field


def test_derived_metrics_may_be_verified_because_this_repository_computes_them() -> None:
    derived = {metric.local_field for metric in load_sdp_metrics().derived_metrics}
    assert "shots_on_target_allowed_proxy" in derived


def test_one_provider_key_cannot_feed_two_metrics() -> None:
    source = yaml.safe_load((Path("config") / "pl_sdp_metrics.yaml").read_text(encoding="utf-8"))
    source["metrics"].append(
        {
            "local_field": "duplicate_claimant",
            "provider_fields": ["goals"],
            "type": "int",
            "group": "result",
            "description": "x",
            "verified_semantics": False,
        }
    )
    with pytest.raises(ValidationError, match="cannot feed two metrics"):
        SdpMetricDictionary.model_validate(source)


def test_a_mirror_cannot_collide_with_a_sourced_metric() -> None:
    """A mirror column is derived; letting it share a name would make one column mean two."""
    source = yaml.safe_load((Path("config") / "pl_sdp_metrics.yaml").read_text(encoding="utf-8"))
    source["metrics"][0]["mirror"] = "expected_goals"
    with pytest.raises(ValidationError, match="collides with a declared metric"):
        SdpMetricDictionary.model_validate(source)


def test_a_metric_with_no_alias_is_refused() -> None:
    source = yaml.safe_load((Path("config") / "pl_sdp_metrics.yaml").read_text(encoding="utf-8"))
    source["metrics"][0]["provider_fields"] = []
    with pytest.raises(ValidationError, match="at least one candidate provider key"):
        SdpMetricDictionary.model_validate(source)


def test_possession_is_declared_as_a_percent_not_a_fraction() -> None:
    """Both sides must sum to ~100 for the consistency check to mean anything."""
    possession = load_sdp_metrics().by_local_field()["possession"]
    assert str(possession.type) == "percent"
