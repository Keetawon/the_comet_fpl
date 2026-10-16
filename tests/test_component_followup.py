"""Behavioural tests for the isolated component follow-up."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from fpl.models.component_followup import (
    Observation,
    Policy,
    Target,
    appearance_mixture,
    checked_history,
    duration_dc,
    shrunk_attack,
)
from fpl.types import Position

CUTOFF = datetime(2026, 9, 9, tzinfo=UTC)


def observation(code=1, fixture=1, minutes=90, xg=0.0, xa=0.0, dc=10, club=1):
    return Observation(
        "2026-27",
        1,
        fixture,
        code,
        club,
        Position.DEF,
        CUTOFF - timedelta(days=10 - fixture),
        minutes,
        0,
        0,
        xg,
        xa,
        dc,
    )


def target(code=1, club=1, minutes=(0.2, 0.1, 0.1, 0.6), position=Position.DEF):
    return Target(code, club, position, minutes, (1.0, 0.0), (1.0, 0.0), 0.2)


def attack(rows, roster, **kwargs):
    return shrunk_attack(
        rows, roster, component="goals", frontier_season="2025-26", team_budget=1.2, **kwargs
    )


def test_one_measured_zero_gets_positive_share_from_prior():
    predictions = attack([observation(), observation(2, 2, xg=0.5)], [target(), target(2)])
    assert predictions[1].measured_recent == 1
    assert predictions[1].conditional[1] > 0
    assert predictions[1].signal < predictions[2].signal
    assert sum(r.allocated_rate for r in predictions.values()) == pytest.approx(1.2)


def test_goal_and_assist_are_separate_signals():
    rows = [observation(1, 1, xg=0.5, xa=0.0), observation(2, 2, xg=0.0, xa=0.5)]
    goals = attack(rows, [target(), target(2)])
    assists = shrunk_attack(
        rows, [target(), target(2)], component="assists", frontier_season="2025-26", team_budget=1.2
    )
    assert goals[1].allocated_rate > goals[2].allocated_rate
    assert assists[1].allocated_rate < assists[2].allocated_rate


def test_unmeasured_recent_history_is_not_backfilled():
    rows = [observation(fixture=1, xg=9.0)]
    rows += [observation(fixture=i, xg=None) for i in range(2, 7)]
    rows += [observation(2, 8, xg=0.1)]
    result = attack(rows, [target(), target(2)])[1]
    assert result.measured_recent == 0
    assert result.signal is not None


def test_no_measured_attack_retains_exact_incumbent():
    t = replace(target(), incumbent_goals=(0.8, 0.2))
    result = attack([observation(xg=None)], [t])[1]
    assert result.conditional == t.incumbent_goals
    assert result.fallback == "unmeasured_prior"


def test_zero_appearance_and_zero_budget_are_well_defined():
    no_play = target(minutes=(1.0, 0.0, 0.0, 0.0))
    prediction = attack([observation(xg=0.2)], [no_play])[1]
    assert prediction.unconditional == (1.0, 0.0)
    zero_budget = shrunk_attack(
        [observation(xg=0.2)],
        [target()],
        component="goals",
        frontier_season="2025-26",
        team_budget=0,
    )
    assert zero_budget[1].unconditional[0] == 1


def test_appearance_is_applied_once():
    assert appearance_mixture(0.4, (0.7, 0.2, 0.1)) == pytest.approx((0.88, 0.08, 0.04))


def test_old_former_club_attack_is_ineligible():
    old = replace(observation(xg=100.0, club=99), season="2023-24")
    rows = [old, observation(2, 2, xg=0.1)]
    assert attack(rows, [target(), target(2)])[1].measured_recent == 0


def test_dc_distinguishes_short_and_full_appearances():
    rows = [observation(code=i, fixture=i, minutes=10, dc=0) for i in range(1, 5)]
    rows += [observation(code=i, fixture=i, minutes=90, dc=15) for i in range(5, 9)]
    result = duration_dc(rows, target(50), {Position.DEF: 10})
    assert result.by_minutes[1] < result.by_minutes[3]
    assert result.unconditional[1] == pytest.approx(
        sum(p * q for p, q in zip(target(50).minutes, result.by_minutes, strict=True))
    )


def test_dc_transferred_player_does_not_carry_old_club_hits():
    rows = [observation(1, i, dc=20, club=99) for i in range(1, 6)]
    rows += [observation(2, 7, dc=0, club=1)]
    transferred = duration_dc(rows, target(1, 1), {Position.DEF: 10})
    new_player = duration_dc(rows, target(100, 1), {Position.DEF: 10})
    assert transferred == new_player


def test_dc_unknown_position_measurement_falls_back_not_zero():
    result = duration_dc([observation(dc=None)], target(), {Position.DEF: 10})
    assert result.fallback == "unmeasured_position"
    assert result.unconditional[1] == pytest.approx(0.16)


def test_dc_gk_is_unscored():
    assert duration_dc([], target(position=Position.GK), {Position.DEF: 10}).unconditional is None


def test_dc_no_appearance_is_zero_even_with_high_rate():
    result = duration_dc([observation()], target(minutes=(1, 0, 0, 0)), {Position.DEF: 10})
    assert result.unconditional == (1, 0)


def test_dc_threshold_is_inclusive():
    hit = duration_dc([observation(dc=10)], target(99), {Position.DEF: 10})
    miss = duration_dc([observation(dc=9)], target(99), {Position.DEF: 10})
    assert hit.unconditional[1] > miss.unconditional[1]


def test_checked_history_rejects_naive_times():
    with pytest.raises(ValueError, match="timezone-aware"):
        checked_history([], CUTOFF.replace(tzinfo=None), "2026-27", 4)


def test_checked_history_rejects_future_or_target_gw():
    for row in (replace(observation(), kickoff=CUTOFF), replace(observation(), gw=4)):
        with pytest.raises(ValueError, match="target/future"):
            checked_history([row], CUTOFF, "2026-27", 4)


def test_checked_history_uses_season_qualified_identity():
    old = replace(observation(), season="2025-26", kickoff=CUTOFF - timedelta(days=400))
    assert len(checked_history([old, observation()], CUTOFF, "2026-27", 4)) == 2
    with pytest.raises(ValueError, match="duplicate"):
        checked_history([observation(), observation()], CUTOFF, "2026-27", 4)


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
def test_checked_history_rejects_invalid_measured_signal(value):
    with pytest.raises(ValueError, match="invalid measured"):
        checked_history([observation(xg=value)], CUTOFF, "2026-27", 4)


@pytest.mark.parametrize("strength", [0, -1, float("nan")])
def test_prior_strength_is_validated(strength):
    with pytest.raises(ValueError, match="finite and positive"):
        Policy(attack_player_strength=strength)


def test_roster_identity_and_probability_validation():
    with pytest.raises(ValueError, match="duplicate"):
        attack([], [target(), target()])
    with pytest.raises(ValueError, match="one stable club"):
        attack([], [target(), target(2, 99)])
    with pytest.raises(ValueError, match="sum to one"):
        target(minutes=(0.1, 0.1, 0.1, 0.1))
