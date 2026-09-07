"""Source-label audit never runs a model or rewrites rare bench outcomes."""

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from fpl.jobs.audit_disciplinary_targets import summarise
from fpl.models.disciplinary_development import NAME, DisciplinaryParameters


def test_source_audit_retains_zero_minute_and_missing_labels() -> None:
    rows = [
        {"season": "2025-26", "yellow_cards": 1, "red_cards": 0, "minutes": 0},
        {"season": "2025-26", "yellow_cards": 0, "red_cards": 1, "minutes": 90},
        {"season": "2025-26", "yellow_cards": None, "red_cards": 0, "minutes": 90},
    ]
    before = deepcopy(rows)
    result = summarise(rows)
    assert rows == before
    assert result["counts"]["rows"] == 3
    assert result["counts"]["yellow"] == 1
    assert result["counts"]["red"] == 1
    assert result["counts"]["unmeasured"] == 1
    assert result["zero_minute_card_rows"] == [rows[0]]


def test_new_joint_source_target_fails_before_model_scoring() -> None:
    with pytest.raises(ValueError, match="re-audit"):
        summarise([{"season": "2025-26", "yellow_cards": 1, "red_cards": 1, "minutes": 90}])


def test_frozen_card_parameters_and_shared_proxy_population() -> None:
    root = Path(__file__).resolve().parents[1]
    contract = yaml.safe_load((root / "config/player_disciplinary_evaluation.yaml").read_bytes())
    reference = yaml.safe_load(
        (root / "config/retrospective_minutes_control_cache.yaml").read_bytes()
    )
    params = DisciplinaryParameters()
    assert contract["candidate"] == NAME
    assert contract["expected_rows"] == reference["expected_rows"] == 86755
    assert contract["expected_direct_price_proxy_rows"] == 821
    assert contract["expected_folds"] == 114
    assert contract["database_sha256"] == reference["database_sha256"]
    assert contract["position_prior_minutes"] == params.position_prior_minutes
    assert contract["player_yellow_prior_minutes"] == params.player_yellow_prior_minutes
    assert contract["player_red_prior_minutes"] == params.player_red_prior_minutes
    assert contract["global_pseudocount_per_cause"] == params.global_pseudocount
    assert contract["global_prior_minutes"] == params.global_prior_minutes
    assert contract["promotion_permitted"] is False
    assert contract["formal_runs"] == 1
