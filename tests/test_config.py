"""R2: scoring rules are configuration, not code.

The test that matters most here is the last one: it greps the calculator for scoring
constants, because R2 is only true if it is impossible to satisfy the unit tests by
hard-coding.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

from fpl.config import (
    ScoringRules,
    available_rulesets,
    config_dir,
    load_data_quality,
    load_scoring_rules,
    load_sources,
    repo_root,
)
from fpl.models.scoring import _UNEXERCISED_RULES, components_required_by
from fpl.types import Position, ruleset_id_for_season


def test_both_rulesets_load() -> None:
    assert available_rulesets() == ["2025_26", "2026_27"]
    for ruleset_id in available_rulesets():
        rules = load_scoring_rules(ruleset_id)
        assert rules.ruleset_id == ruleset_id


def test_ruleset_id_derivation() -> None:
    assert ruleset_id_for_season("2026-27") == "2026_27"


def test_every_position_has_a_goal_value() -> None:
    for ruleset_id in available_rulesets():
        rules = load_scoring_rules(ruleset_id)
        assert set(rules.goals_scored) == set(Position)


def test_goalkeepers_cannot_be_given_a_dc_threshold() -> None:
    """The config schema refuses to express a rule that contradicts measured data.

    Goalkeeper defensive_contribution is always 0 (measured max 0), so a GK threshold is
    always a mistake. Rejecting it in the schema is better than a comment.
    """
    document = yaml.safe_load((config_dir() / "scoring_2026_27.yaml").read_text("utf-8"))
    document["defensive_contribution"]["thresholds"]["GK"] = 10
    with pytest.raises(ValueError, match="goalkeepers never earn"):
        ScoringRules.model_validate(document)


def test_unknown_config_keys_are_rejected() -> None:
    """`extra="forbid"`, so an upstream rule change cannot be silently ignored."""
    document = yaml.safe_load((config_dir() / "scoring_2026_27.yaml").read_text("utf-8"))
    document["scoring_for_corner_kicks"] = 1
    with pytest.raises(ValueError, match=r"extra_forbidden|Extra inputs"):
        ScoringRules.model_validate(document)


def test_bonus_mode_is_passthrough_in_phase_0() -> None:
    for ruleset_id in available_rulesets():
        assert load_scoring_rules(ruleset_id).bonus.mode == "passthrough"
        assert load_scoring_rules(ruleset_id).bonus.ranked_points == (3, 2, 1)


def test_2026_27_matches_2025_26_on_every_scoring_component() -> None:
    """They are identical in every component, and that is asserted rather than assumed.

    It is why the 2025-26 replay is meaningful evidence for the live ruleset. It is also why
    both files ship: hard-coding the equivalence would violate R2, and the day FPL changes a
    rule this test is the thing that notices.
    """
    old = load_scoring_rules("2025_26")
    new = load_scoring_rules("2026_27")
    for field in (
        "appearance",
        "goals_scored",
        "assists",
        "clean_sheets",
        "goals_conceded",
        "saves",
        "penalties_saved",
        "penalties_missed",
        "own_goals",
        "yellow_cards",
        "red_cards",
        "defensive_contribution",
    ):
        assert getattr(old, field) == getattr(new, field), f"{field} differs between rulesets"


def test_forwards_earn_defensive_contribution_in_both_rulesets() -> None:
    """Forwards already earned DC in 2025-26; it is not new in 2026-27."""
    for ruleset_id in available_rulesets():
        thresholds = load_scoring_rules(ruleset_id).defensive_contribution.thresholds
        assert thresholds[Position.FWD] == 12
        assert thresholds[Position.MID] == 12
        assert thresholds[Position.DEF] == 10


def test_unexercised_rules_are_declared_unverified_in_config() -> None:
    """Code and config must agree about what cannot be validated.

    `goals_scored.GK` is the case that matters: a payload can confirm the published value,
    but no replay can exercise it because no goalkeeper scored in the data.
    """
    for ruleset_id in available_rulesets():
        rules = load_scoring_rules(ruleset_id)
        for path in _UNEXERCISED_RULES:
            assert path in rules.verification.unverified, (
                f"{ruleset_id}: {path} cannot be exercised by any replay but is not listed "
                "in the config's `unverified` block"
            )


def test_2026_27_claims_no_unearned_verification() -> None:
    """The live ruleset must not claim confirmation it has not obtained.

    No real payload has been supplied, so `payload_confirmed` must be empty and nothing may
    be listed as replay-exercised for a season that has not been played.
    """
    rules = load_scoring_rules("2026_27")
    assert rules.verification.payload_confirmed == []
    assert rules.verification.replay_exercised == []
    assert not rules.verification.is_confirmed("goals_scored.GK")


def test_2025_26_records_what_the_replay_exercised() -> None:
    rules = load_scoring_rules("2025_26")
    exercised = set(rules.verification.replay_exercised)
    assert "defensive_contribution" in exercised
    assert "goals_scored.DEF" in exercised
    # And it does not claim to have exercised the unexercisable.
    assert not exercised & _UNEXERCISED_RULES


def test_components_required_by_includes_dc_when_rules_pay_for_it() -> None:
    required = components_required_by(load_scoring_rules("2026_27"))
    assert "defensive_contribution" in required
    assert "minutes" in required
    assert "total_points" not in required


def test_sources_and_data_quality_load() -> None:
    sources = load_sources()
    assert len(sources.archive.seasons) == 5
    assert sources.live_api.min_request_interval_seconds >= 1.0
    assert sources.current_season.season == "2026-27"
    assert sources.current_season.gw1_deadline.isoformat() == "2026-08-21T17:30:00+00:00"

    quality = load_data_quality()
    assert any(rule.season == "2022-23" for rule in quality.nullify)
    assert "defensive_contribution" in quality.ranges


def test_archive_urls_are_well_formed() -> None:
    sources = load_sources()
    url = sources.archive.url("2025-26", "merged_gw")
    assert url.endswith("/2025-26/gws/merged_gw.csv")


# --------------------------------------------------------------------------------------
# The R2 test with teeth
# --------------------------------------------------------------------------------------

_SCORING_MODULE = repo_root() / "src" / "fpl" / "models" / "scoring.py"

# Values that may legitimately appear in the calculator: 0 and 1 as arithmetic identities,
# and 2/3 only inside the bonus-rank tuple. Anything else would be a scoring constant.
_ALLOWED_NUMERIC_LITERALS = frozenset({0, 1})


def test_calculator_contains_no_scoring_constants() -> None:
    """Grep the calculator for magic numbers.

    Without this, every scoring unit test could be satisfied by hard-coding, and R2 would be
    a comment rather than a property. The point of R2 is that adding 2027/28 is a config
    change; that is only true if no value lives here.
    """
    tree = ast.parse(_SCORING_MODULE.read_text("utf-8"), filename=str(_SCORING_MODULE))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            if isinstance(node.value, bool):
                continue
            if node.value not in _ALLOWED_NUMERIC_LITERALS:
                offenders.append(f"line {node.lineno}: {node.value}")
    assert offenders == [], (
        "scoring.py contains numeric literals that look like scoring constants; they belong "
        "in config/scoring_<ruleset>.yaml (R2): " + ", ".join(offenders)
    )


def test_no_position_name_is_special_cased_with_a_value() -> None:
    """Position-specific values must come from the rules mapping, not from branches."""
    source = _SCORING_MODULE.read_text("utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        # Reject `if position == Position.GK: points += <literal>` shapes.
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name):
            if node.left.id == "position":
                for comparator in node.comparators:
                    assert not isinstance(comparator, ast.Constant), (
                        f"line {node.lineno}: position compared against a literal; use the "
                        "rules mapping"
                    )


def test_config_files_are_valid_yaml_and_documented() -> None:
    """Each ruleset file should explain itself; these are the project's rule of record."""
    for path in sorted(config_dir().glob("scoring_*.yaml")):
        text = path.read_text("utf-8")
        assert yaml.safe_load(text)
        assert text.lstrip().startswith("#"), f"{path.name} has no explanatory header"


def test_repo_root_discovery_is_stable() -> None:
    assert (repo_root() / "config" / "sources.yaml").is_file()
    assert Path(repo_root() / "pyproject.toml").is_file()
