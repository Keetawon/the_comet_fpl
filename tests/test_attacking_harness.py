"""Offline tests for Stage C attacking baselines and metrics.

No database, no network. Uses tiny synthetic fixtures.
"""

from __future__ import annotations

from fpl.models.attacking_baselines import (
    PlayerHistoryRow,
    PositionalGoalRateBaseline,
    TargetRowProjection,
    TrailingPlayerGoalRateBaseline,
    poisson_pmf,
)
from fpl.types import Position
from fpl.validate.attacking_metrics import score_attacking_predictions


def test_poisson_pmf_properties() -> None:
    dist = poisson_pmf(0.5)
    assert len(dist) == 11
    assert abs(sum(dist) - 1.0) < 1e-9
    assert all(p >= 0 for p in dist)


def test_positional_goal_rate_baseline() -> None:
    history = [
        PlayerHistoryRow("2021-22", 1, 1, "2021-08-13T19:00:00Z", 101, Position.FWD, 2),
        PlayerHistoryRow("2021-22", 1, 1, "2021-08-13T19:00:00Z", 102, Position.FWD, 0),
        PlayerHistoryRow("2021-22", 1, 2, "2021-08-14T14:00:00Z", 201, Position.MID, 1),
        PlayerHistoryRow("2021-22", 1, 2, "2021-08-14T14:00:00Z", 301, Position.DEF, 0),
    ]

    base = PositionalGoalRateBaseline()
    base.fit(history)

    # FWD rate = (2 + 0) / 2 = 1.0
    assert abs(base.get_rate(Position.FWD) - 1.0) < 1e-6
    # MID rate = 1.0 / 1 = 1.0
    assert abs(base.get_rate(Position.MID) - 1.0) < 1e-6
    # DEF rate = 0.0 / 1 = 0.0
    assert abs(base.get_rate(Position.DEF) - 0.0) < 1e-6

    target = TargetRowProjection(
        "2021-22", 2, 3, "2021-08-21T14:00:00Z", 101, Position.FWD, 1, 2, True
    )
    pred = base.predict(target)
    assert len(pred) == 11
    assert abs(sum(pred) - 1.0) < 1e-6


def test_trailing_player_goal_rate_baseline_shrunk() -> None:
    history = [
        # FWD positional total: 1 goal across 4 app rows = 0.25 rate
        PlayerHistoryRow("2021-22", 1, 1, "2021-08-13T19:00:00Z", 101, Position.FWD, 1),
        PlayerHistoryRow("2021-22", 1, 1, "2021-08-13T19:00:00Z", 102, Position.FWD, 0),
        PlayerHistoryRow("2021-22", 2, 2, "2021-08-20T19:00:00Z", 102, Position.FWD, 0),
        PlayerHistoryRow("2021-22", 3, 3, "2021-08-27T19:00:00Z", 102, Position.FWD, 0),
        # Player 101 has 1 app, 1 goal -> player rate = 1.0.
        # Shrunk with alpha=5.0 and pos_rate=0.25: rate = (1 + 5 * 0.25) / (1 + 5) = 0.375
    ]

    base = TrailingPlayerGoalRateBaseline(alpha=5.0)
    base.fit(history)

    target_101 = TargetRowProjection(
        "2021-22", 4, 4, "2021-09-04T14:00:00Z", 101, Position.FWD, 1, 2, True
    )
    pred_101 = base.predict(target_101)
    assert len(pred_101) == 11

    # Cold start player 999 -> returns positional rate
    target_cold = TargetRowProjection(
        "2021-22", 4, 4, "2021-09-04T14:00:00Z", 999, Position.FWD, 1, 2, True
    )
    pred_cold = base.predict(target_cold)
    assert len(pred_cold) == 11


def test_score_attacking_predictions() -> None:
    preds = [poisson_pmf(0.2), poisson_pmf(1.5)]
    targets = [0, 2]

    report = score_attacking_predictions(preds, targets, seed=202627)
    assert report.predictions == 2
    assert report.exclusions == 0
    assert report.mean_log_score > 0
    assert report.mean_ranked_probability_score >= 0
    assert 0.0 <= report.mean_brier_at_least_one_goal <= 1.0
    assert 0.0 <= report.pit_interval_80_coverage <= 1.0
    assert len(report.reliability_at_least_one_goal.buckets) == 10
