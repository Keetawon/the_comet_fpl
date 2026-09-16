from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from fpl.features.attacking_role_premium_v1 import UsageObservation, UsageTarget, predict_batch
from fpl.validate.attacking_role_premium_v1_metrics import (
    ScoredUsage,
    blocked_bootstrap,
    comparison,
    diagnostics,
    history_bucket,
    percentile,
    positive_shift,
    relative_lift,
    spearman,
    verdict,
)


def example():
    cutoff = datetime(2023, 9, 1, tzinfo=UTC)
    history = [
        UsageObservation(
            "2023-24",
            1,
            1,
            cutoff - timedelta(days=5),
            100,
            "DEF",
            90,
            1,
            0.2,
            0.1,
            cutoff - timedelta(days=4),
            cutoff - timedelta(days=4),
            "ARCHIVED_AS_OF",
            "a" * 40,
            "b" * 64,
        )
    ]
    target = UsageTarget("2023-24", 2, 2, cutoff + timedelta(days=2), 100, "DEF", 1, 2, "HOME")
    return predict_batch(history, [target], as_of=cutoff)[0]


def test_conditional_targets_xgi_and_null_rank_semantics():
    prediction = example()
    row = ScoredUsage(prediction, 45, 0.3, 0.2)
    assert row.observed("xgi") == 1.0
    report = comparison([row])
    assert report["control"]["xgi"]["mae"] == pytest.approx(0.7)
    assert report["control"]["xgi"]["mean_error"] == pytest.approx(-0.7)
    assert report["control"]["xgi"]["spearman"] is None
    with pytest.raises(ValueError, match="zero-minute"):
        ScoredUsage(prediction, 0, 0, 0).observed("xgi")
    assert comparison([])["candidate"]["xg"]["mae"] is None
    assert relative_lift(0.0, 0.0) is None
    assert spearman([1, 1], [2, 3]) is None
    assert spearman([1, 2, 2, 4], [1, 3, 3, 9]) == pytest.approx(1)


def test_fixed_shift_and_exposure_slices():
    p = replace(
        example(),
        candidate_xgi90=0.5,
        control_xgi90=0.3,
        recent_shift_xgi90=0.2,
        recent_window_minutes=180,
    )
    assert positive_shift(p)
    assert not positive_shift(replace(p, recent_window_minutes=179))
    rows = [ScoredUsage(p, 45, 0.3, 0.1), ScoredUsage(p, 44, 0.1, 0.1), ScoredUsage(p, 0, 0.0, 0.0)]
    report = diagnostics(rows, primary_minutes=45)
    assert report["regime_shift"]["positive"]["rows"] == 1
    assert report["regime_shift"]["persistence_rate"] == 1.0
    assert report["all_playing_time"]["rows"] == 2
    assert report["short_appearances_1_44"]["rows"] == 1
    assert report["zero_minute_targets"] == 1
    assert [history_bucket(n) for n in (0, 1, 89, 90, 269, 270, 449, 450, 899, 900)] == [
        "0",
        "1-89",
        "1-89",
        "90-269",
        "90-269",
        "270-449",
        "270-449",
        "450-899",
        "450-899",
        "900+",
    ]


def test_blocked_bootstrap_paired_and_deterministic():
    p = replace(example(), control_xgi90=0.3, candidate_xgi90=0.4)
    rows = [
        ScoredUsage(replace(p, target=replace(p.target, gameweek=gw)), 90, 0.4, 0.0)
        for gw in (2, 2, 3)
    ]
    result = blocked_bootstrap(rows, draws=100, seed=20260908)
    assert result == blocked_bootstrap(list(reversed(rows)), draws=100, seed=20260908)
    assert result["relative_mae_improvement_ci95"] == [1.0, 1.0]
    assert result["gw_blocks"] == 2
    assert percentile([1, 2, 3], 0.5) == 2


def test_materiality_and_uncertainty_cannot_be_replaced_by_examples():
    base = {
        "rows": 200,
        "relative_mae_lift": {"xg": 0.02, "xa": 0.02, "xgi": 0.02},
        "control": {"xgi": {"mean_error": -0.01}},
        "candidate": {"xgi": {"mean_error": -0.01}},
    }
    positions = dict.fromkeys(("DEF", "MID", "FWD"), base)
    gates = {
        "minimum_xgi_mae_lift": 0.01,
        "maximum_component_regression": 0.005,
        "minimum_guardrail_position_rows": 100,
        "maximum_absolute_bias_increase": 0.05,
        "maximum_position_mae_regression": 0.05,
    }
    assert (
        verdict(
            base,
            positions,
            {
                "draws": 100,
                "defined_relative_draws": 100,
                "relative_mae_improvement_ci95": [0.001, 0.04],
            },
            gates,
            pit_valid=True,
        )["verdict"]
        == "SUPPORTED"
    )
    assert (
        verdict(
            base,
            positions,
            {
                "draws": 100,
                "defined_relative_draws": 100,
                "relative_mae_improvement_ci95": [-0.01, 0.04],
            },
            gates,
            pit_valid=True,
        )["verdict"]
        == "INCONCLUSIVE"
    )
    weak = {**base, "relative_mae_lift": {"xg": 0.003, "xa": 0.003, "xgi": 0.003}}
    assert (
        verdict(
            weak,
            positions,
            {
                "draws": 100,
                "defined_relative_draws": 100,
                "relative_mae_improvement_ci95": [0.001, 0.005],
            },
            gates,
            pit_valid=True,
        )["verdict"]
        == "INCONCLUSIVE"
    )
    assert (
        verdict(
            base,
            positions,
            {
                "draws": 100,
                "defined_relative_draws": 100,
                "relative_mae_improvement_ci95": [0.001, 0.04],
            },
            gates,
            pit_valid=False,
        )["verdict"]
        == "INVALID"
    )
    bad = {**base, "relative_mae_lift": {"xg": -0.02, "xa": -0.02, "xgi": -0.02}}
    assert (
        verdict(
            bad,
            positions,
            {
                "draws": 100,
                "defined_relative_draws": 100,
                "relative_mae_improvement_ci95": [-0.04, -0.01],
            },
            gates,
            pit_valid=True,
        )["verdict"]
        == "REFUTED"
    )
