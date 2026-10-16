"""Behavioural checks for the separately registered aggregate-conversion experiment."""

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from fpl.models.aggregate_conversion import (
    ConversionPolicy,
    TrainingExample,
    apply_conversion,
    conversion_feature,
    fit_conversion,
    training_examples,
)
from fpl.models.component_followup import Observation, Target, shrunk_attack
from fpl.types import Position

CUTOFF = datetime(2026, 9, 9, tzinfo=UTC)


def obs(fixture=1, code=1, goals=0, xg=0.2, assists=0, xa=0.1, minutes=90, **kwargs):
    row = Observation(
        "2025-26",
        fixture,
        fixture,
        code,
        1,
        Position.MID,
        CUTOFF - timedelta(days=30 - fixture),
        minutes,
        goals,
        assists,
        xg,
        xa,
        None,
    )
    return replace(row, **kwargs)


def feature(rows, component="goals", **kwargs):
    return conversion_feature(rows, code=1, component=component, cutoff=CUTOFF, **kwargs)


def target(code=1, p_play=0.9):
    return Target(code, 1, Position.MID, (1 - p_play, 0, 0, p_play), (1.0, 0.0), (1.0, 0.0), 0)


def test_ratio_of_aggregates_uses_identical_pairs_not_average_of_ratios():
    f = feature([obs(1, goals=1, xg=0.1), obs(2, goals=0, xg=0.9)])
    assert f.raw_ratio == pytest.approx(1)
    assert f.shrunk_ratio == pytest.approx(1)
    assert f.actual_sum == 1
    assert f.expected_sum == pytest.approx(1)


def test_select_ten_appearances_before_missing_measurement_filter():
    rows = [obs(i, goals=1, xg=1) for i in range(1, 12)]
    rows[-1] = replace(rows[-1], xg=None)
    f = feature(rows)
    assert len(f.selected_keys) == 10
    assert len(f.paired_keys) == 9
    assert f.selected_keys[0][1] == 2
    assert f.actual_sum == 9
    assert f.coverage == pytest.approx(0.9)


def test_missing_actual_also_removes_expected_from_matched_sum():
    f = feature([obs(1, goals=None, xg=4), obs(2, goals=1, xg=0.5)])
    assert f.actual_sum == 1
    assert f.expected_sum == 0.5


def test_dnp_does_not_consume_appearance_and_old_club_still_belongs_to_player():
    rows = [obs(i, minutes=0 if i == 11 else 90, team_code=99) for i in range(1, 12)]
    f = feature(rows)
    assert len(f.selected_keys) == 10
    assert f.selected_keys[-1][1] == 10


def test_window_is_chronological_and_stable_code_specific():
    rows = [obs(1), obs(2), obs(3, code=900, goals=50)]
    assert feature(rows) == feature(list(reversed(rows)))
    assert len(feature(rows).selected_keys) == 2


def test_target_and_future_values_cannot_change_feature():
    previous = [obs(1, goals=1)]
    future = obs(2, goals=100, xg=100, kickoff=CUTOFF)
    assert feature(previous) == feature([*previous, future])


def test_missing_is_neutral_and_distinct_from_measured_zero():
    missing = feature([obs(xg=None)])
    zero = feature([obs(goals=0, xg=0)])
    assert missing.expected_sum is None
    assert missing.actual_sum is None
    assert zero.expected_sum == 0
    assert zero.actual_sum == 0
    assert missing.shrunk_ratio == zero.shrunk_ratio == 1
    assert missing.raw_ratio is zero.raw_ratio is None


def test_positive_assist_with_zero_xa_has_finite_smoothed_feature():
    f = feature([obs(assists=1, xa=0)], "assists")
    assert f.raw_ratio is None
    assert f.shrunk_ratio == pytest.approx(1.2)
    assert math.isfinite(f.log_ratio)


def test_goal_and_assist_windows_are_paired_separately():
    rows = [obs(goals=0, xg=1, assists=2, xa=0.5)]
    assert feature(rows).shrunk_ratio < 1
    assert feature(rows, "assists").shrunk_ratio > 1


def test_duplicate_fixture_fails_closed():
    with pytest.raises(ValueError, match="duplicate"):
        feature([obs(), obs()])


@pytest.mark.parametrize(
    "setting",
    [
        {"window": 5},
        {"prior_exposure": 0},
        {"ridge": float("nan")},
        {"coefficient_bound": -1},
    ],
)
def test_policy_rejects_invalid_settings(setting):
    with pytest.raises(ValueError, match=r"appearances|finite"):
        ConversionPolicy(**setting)


def test_beta_zero_is_exact_baseline_and_tilt_preserves_allocated_budget():
    rows = [obs(1, goals=2), obs(2, code=2, goals=0)]
    roster = [target(), target(2)]
    base = shrunk_attack(
        rows,
        roster,
        component="goals",
        frontier_season="2025-26",
        team_budget=1.5,
    )
    features = {
        t.code: conversion_feature(rows, code=t.code, component="goals", cutoff=CUTOFF)
        for t in roster
    }
    assert apply_conversion(base, roster, features, beta=0, team_budget=1.5) == base
    new = apply_conversion(base, roster, features, beta=0.5, team_budget=1.5)
    assert sum(r.allocated_rate for r in new.values()) == pytest.approx(1.5)
    assert new[1].allocated_rate > base[1].allocated_rate
    for t in roster:
        assert new[t.code].unconditional[0] == pytest.approx(
            1 - t.p_play + t.p_play * new[t.code].conditional[0]
        )


def test_zero_appearance_and_unmeasured_fallback_remain_baseline():
    roster = [target(p_play=0)]
    rows = [obs(xg=None)]
    base = shrunk_attack(
        rows,
        roster,
        component="goals",
        frontier_season="2025-26",
        team_budget=1.5,
    )
    new = apply_conversion(base, roster, {1: feature(rows)}, beta=0.5, team_budget=1.5)
    assert new == base
    assert new[1].unconditional[0] == 1


def example(z, actual, fixture=1, position=Position.MID):
    f = replace(feature([]), log_ratio=z, shrunk_ratio=math.exp(z))
    return TrainingExample(
        "2025-26",
        1,
        fixture,
        1,
        position,
        CUTOFF.isoformat(),
        CUTOFF.isoformat(),
        "goals",
        actual,
        0.5,
        f,
    )


def test_fitting_can_learn_positive_negative_or_zero_weight():
    positive = [example(-0.5, 0), example(0.5, 2)] * 30
    negative = [example(-0.5, 2), example(0.5, 0)] * 30
    neutral = [example(-0.5, 1), example(0.5, 1)] * 30
    assert fit_conversion(positive).beta > 0
    assert fit_conversion(negative).beta < 0
    assert fit_conversion(neutral).beta == pytest.approx(0, abs=1e-12)
    assert fit_conversion(positive) == fit_conversion(positive)


def test_position_nuisance_removes_between_position_confounding():
    rows = [example(-0.5, 0, position=Position.DEF), example(0.5, 2)] * 30
    assert fit_conversion(rows).beta == pytest.approx(0, abs=1e-12)


def test_no_events_fit_is_finite_and_neutral():
    fit = fit_conversion([example(-1, 0), example(1, 0)])
    assert fit.beta == pytest.approx(0, abs=1e-12)
    assert fit.position_intercepts == {"MID": None}


def test_historical_features_exclude_target_xg_and_all_same_gw_legs():
    prior = obs(1, season="2022-23", goals=1, xg=0.5)
    first = obs(10, season="2023-24", gw=1, goals=1, xg=0.2)
    late = obs(11, season="2023-24", gw=1, goals=2, xg=5)
    later = obs(20, season="2026-27", gw=1, goals=200, xg=200)
    a, counts = training_examples(
        [prior, first, late, later],
        seasons=["2023-24"],
        component="goals",
    )
    b, _ = training_examples(
        [prior, replace(first, xg=90), replace(late, xg=90), later],
        seasons=["2023-24"],
        component="goals",
    )
    assert len(a) == counts["included"] == 2
    assert a == b
    assert all(r.feature.selected_keys == (("2022-23", 1, 1),) for r in a)
    assert all(r.season == "2023-24" for r in a)


def test_historical_three_hour_lag_excludes_recent_kickoff():
    t = obs(10, season="2023-24", gw=1)
    prior = obs(1, season="2022-23")
    ongoing = obs(9, season="2023-24", gw=2, kickoff=t.kickoff - timedelta(hours=1))
    rows, _ = training_examples([prior, ongoing, t], seasons=["2023-24"], component="goals")
    chosen = next(r for r in rows if r.fixture == 10)
    assert chosen.feature.selected_keys == (("2022-23", 1, 1),)
