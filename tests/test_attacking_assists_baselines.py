"""Offline tests for Stage C attacking assists baselines.

No database, no network. Uses tiny synthetic fixtures. Mirrors the goals baseline tests.
"""

from __future__ import annotations

from fpl.models.attacking_assists_baselines import (
    AssistHistoryRow,
    PositionalAssistRateBaseline,
    TrailingPlayerAssistRateBaseline,
)
from fpl.models.attacking_baselines import TargetRowProjection, poisson_pmf
from fpl.types import Position
from fpl.validate.attacking_metrics import score_attacking_predictions


def test_positional_assist_rate_baseline() -> None:
    history = [
        AssistHistoryRow("2021-22", 1, 1, "2021-08-13T19:00:00Z", 101, Position.FWD, 2),
        AssistHistoryRow("2021-22", 1, 1, "2021-08-13T19:00:00Z", 102, Position.FWD, 0),
        AssistHistoryRow("2021-22", 1, 2, "2021-08-14T14:00:00Z", 201, Position.MID, 1),
        AssistHistoryRow("2021-22", 1, 2, "2021-08-14T14:00:00Z", 301, Position.DEF, 0),
    ]

    base = PositionalAssistRateBaseline()
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


def test_trailing_player_assist_rate_baseline_shrunk() -> None:
    history = [
        # FWD positional total: 1 assist across 4 app rows = 0.25 rate
        AssistHistoryRow("2021-22", 1, 1, "2021-08-13T19:00:00Z", 101, Position.FWD, 1),
        AssistHistoryRow("2021-22", 1, 1, "2021-08-13T19:00:00Z", 102, Position.FWD, 0),
        AssistHistoryRow("2021-22", 2, 2, "2021-08-20T19:00:00Z", 102, Position.FWD, 0),
        AssistHistoryRow("2021-22", 3, 3, "2021-08-27T19:00:00Z", 102, Position.FWD, 0),
    ]

    base = TrailingPlayerAssistRateBaseline(alpha=5.0)
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


def test_baseline_history_row_carries_xa_and_creativity() -> None:
    """The history row preserves xA / creativity for Candidate V1; v1.0 baselines ignore them."""
    row = AssistHistoryRow("2023-24", 1, 1, "2023-08-11T19:00:00Z", 101, Position.FWD, 1, 0.4, 12.5)
    assert row.assists == 1
    assert row.expected_assists == 0.4
    assert row.creativity == 12.5
    # NULL means unmeasured and is preserved (never zero-filled).
    row_null = AssistHistoryRow("2021-22", 1, 1, "2021-08-13T19:00:00Z", 101, Position.FWD, 0)
    assert row_null.expected_assists is None
    assert row_null.creativity is None


def test_score_assists_predictions_reuses_generic_scorer() -> None:
    preds = [poisson_pmf(0.05), poisson_pmf(0.4)]
    targets = [0, 1]

    report = score_attacking_predictions(preds, targets, seed=202627)
    assert report.predictions == 2
    assert report.exclusions == 0
    assert report.mean_log_score > 0
    assert report.mean_ranked_probability_score >= 0
    # The reused report's brier field is the generic P(count >= 1) Brier.
    assert 0.0 <= report.mean_brier_at_least_one_goal <= 1.0
    assert 0.0 <= report.pit_interval_80_coverage <= 1.0
    assert len(report.reliability_at_least_one_goal.buckets) == 10
