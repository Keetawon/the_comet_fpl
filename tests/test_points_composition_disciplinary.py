"""Optional cards preserve frozen draws; only appeared, loaded-rule points change.

Golden hashes were measured before the optional edit at clean 71c11bf29e29ff1b.
Original composer source SHA256:
00106a60ebbfa7e03d52c07bc99a2de76ffbae4a59b1bc64a1e706fbcd140b11.
These are synthetic regression fixtures, never historical model evaluations.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace

import pytest

from fpl.config import load_phase2_evaluation, load_scoring_rules
from fpl.models.attacking_baselines import poisson_pmf
from fpl.models.disciplinary_development import NONE, ConditionalDisciplinary
from fpl.models.points_composition import (
    MEASURED_CONCEDED_EXPOSURE,
    BpsExactLookup,
    ComponentDistributions,
    ComposedPlayer,
    ExtraScoring,
    FixturePlayer,
    PointsLookup,
    compose_fixture_full_points,
    compose_points_distribution,
    representative_minutes,
)
from fpl.types import Position

RULES = load_scoring_rules("2026_27")
assert RULES.bps is not None
BIN_MINUTES = representative_minutes(
    tuple((b.minutes_min, b.minutes_max) for b in load_phase2_evaluation().output.bins)
)
LOOKUP = PointsLookup(RULES, bin_minutes=BIN_MINUTES)
BPS_LOOKUP = BpsExactLookup(
    RULES.bps,
    bin_minutes=BIN_MINUTES,
    clean_sheet_minimum_minutes=RULES.clean_sheets.minimum_minutes,
)
EXTRA = ExtraScoring(
    saves_unit=RULES.saves.unit,
    dc_points=RULES.defensive_contribution.points,
    saves_positions=RULES.saves.positions,
    dc_positions=frozenset(RULES.defensive_contribution.thresholds),
)


def _golden_players() -> list[FixturePlayer]:
    return [
        FixturePlayer(
            100 + i,
            ComponentDistributions(
                position,
                (0.1, 0.2, 0.3, 0.4),
                poisson_pmf(0.15 + i * 0.1),
                poisson_pmf(0.2),
                poisson_pmf(1.3),
                poisson_pmf(2.4) if position is Position.GK else None,
                0.3 if position is not Position.GK else 0,
            ),
            1.5 + i,
            3.0,
        )
        for i, position in enumerate(Position)
    ]


def _full(players: list[FixturePlayer]) -> list[ComposedPlayer]:
    return compose_fixture_full_points(
        players,
        LOOKUP,
        BPS_LOOKUP,
        EXTRA,
        fixture_seed=20260907,
        draws=256,
        max_points=34,
        conceded_exposure=MEASURED_CONCEDED_EXPOSURE,
    )


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _cards(state: int) -> ConditionalDisciplinary:
    row = (float(state == 0), float(state == 1), float(state == 2))
    return ConditionalDisciplinary((NONE, row, row, row))


def test_disabled_component_reproduces_both_pre_edit_golden_hashes() -> None:
    players = _golden_players()
    assert _hash([asdict(p) for p in _full(players)]) == (
        "baf61d806c43a572f629dd843b545250e6bd06793798660231dc8962af5ae689"
    )
    non_bonus = [
        compose_points_distribution(
            p.components,
            LOOKUP,
            seed=20260907,
            draws=256,
            extra=EXTRA,
            conceded_exposure=MEASURED_CONCEDED_EXPOSURE,
        )
        for p in players
    ]
    assert _hash(non_bonus) == ("3934e5687699a6daed52479ebc6a75d1f0b52b7f4f6e1b267609243123e57f7b")


def test_enabled_exact_none_does_not_perturb_any_existing_random_draw() -> None:
    original = _golden_players()
    enabled = [
        replace(p, components=replace(p.components, disciplinary=_cards(0))) for p in original
    ]
    assert _full(original) == _full(enabled)
    for old, new in zip(original, enabled, strict=True):
        assert compose_points_distribution(
            old.components, LOOKUP, seed=7, draws=256, extra=EXTRA
        ) == (compose_points_distribution(new.components, LOOKUP, seed=7, draws=256, extra=EXTRA))


@pytest.mark.parametrize("state", [1, 2])
def test_cards_use_loaded_scoring_rules_not_hardcoded_constants(state: int) -> None:
    changed_rules = RULES.model_copy(update={"yellow_cards": -2, "red_cards": -5})
    changed = PointsLookup(changed_rules, bin_minutes=BIN_MINUTES)
    components = ComponentDistributions(
        Position.MID,
        (0, 0, 0, 1),
        (0, 1),
        (1,),
        (1,),
        disciplinary=_cards(state),
    )
    expected = changed.points(Position.MID, 3, 1, 0, 0) + (
        changed_rules.yellow_cards if state == 1 else changed_rules.red_cards
    )
    pmf = compose_points_distribution(components, changed, seed=9, draws=50)
    assert pmf[expected] == 1
    assert sum(pmf) == 1


def test_nonappearance_and_single_minutes_gate() -> None:
    components = ComponentDistributions(
        Position.MID,
        (0.5, 0, 0, 0.5),
        (0, 1),
        (1,),
        (1,),
        disciplinary=_cards(1),
    )
    pmf = compose_points_distribution(components, LOOKUP, seed=12, draws=20_000)
    appeared_points = LOOKUP.points(Position.MID, 3, 1, 0, 0) + RULES.yellow_cards
    assert pmf[0] == pytest.approx(0.5, abs=0.015)
    assert pmf[appeared_points] == pytest.approx(0.5, abs=0.015)
    assert pmf[LOOKUP.points(Position.MID, 3, 1, 0, 0)] == 0
    absent = replace(components, minutes=(1, 0, 0, 0))
    assert compose_points_distribution(absent, LOOKUP, seed=12, draws=50)[0] == 1


def test_optional_cards_leave_other_players_and_every_bonus_draw_unchanged() -> None:
    original = _golden_players()
    enabled = original.copy()
    enabled[1] = replace(
        original[1], components=replace(original[1].components, disciplinary=_cards(2))
    )
    control, candidate = _full(original), _full(enabled)
    assert candidate == _full(enabled)
    assert any(a.distribution != b.distribution for a, b in zip(control, candidate, strict=True))
    for a, b in zip(control, candidate, strict=True):
        assert a.expected_bonus == b.expected_bonus
        assert a.probability_any_bonus == b.probability_any_bonus
        assert sum(b.distribution) == pytest.approx(1)
        if a.code != original[1].code:
            assert a == b


@pytest.mark.parametrize("invalid", [True, 1.0, -1, 3])
def test_lookup_rejects_unsupported_joint_or_noninteger_state(invalid: int) -> None:
    with pytest.raises(ValueError, match="unsupported"):
        LOOKUP.disciplinary_points(invalid)
