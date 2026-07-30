"""Deterministic offline tests for the Stage B four-bin minutes scoring slice.

No database, no network. Every distribution and observation is synthetic. These tests pin the
frozen contract (``config/phase2_evaluation.yaml`` 1.0): the log floor, the RPS as ordered-CATEGORY
CDF errors, the two Brier binary margins, a reproducible randomised PIT, the two ten-bucket
reliability curves (always all ten buckets; empty buckets carry ``None``, never fabricated zero),
the within-group Spearman ranking of the 60-plus margin, and the frozen counts/cold-start/
coverage/uncertainty accounting. Policy values (floor, seed, band, edges) are read from the
loaded contract, never hardcoded here.
"""

from __future__ import annotations

import math
import random

import pytest

from fpl.config import load_phase2_evaluation
from fpl.validate.metrics import log_score as phase1_log_score
from fpl.validate.minutes_metrics import (
    MinutesDistribution,
    ReliabilityBucket,
    brier_60_plus,
    brier_any_minutes,
    minutes_log_score,
    minutes_ranked_probability_score,
    probability_60_plus,
    probability_any_minutes,
    score_minutes_predictions,
)

CONFIG = load_phase2_evaluation()
FLOOR = CONFIG.scoring_calibration.log_probability_floor
SEED = CONFIG.scoring_calibration.randomized_pit_seed
BAND = CONFIG.scoring_calibration.randomized_pit_band
EDGES = CONFIG.scoring_calibration.reliability_edges

UNIFORM: MinutesDistribution = (0.25, 0.25, 0.25, 0.25)


# --------------------------------------------------------------------------------------
# Single-row metric primitives, hand-computed
# --------------------------------------------------------------------------------------


def test_log_score_matches_negative_log_of_observed_bin() -> None:
    # -ln(0.25) = ln(4)
    assert minutes_log_score(UNIFORM, 0, floor=FLOOR) == pytest.approx(math.log(4.0))


def test_log_score_floor_binds_on_a_one_hot_zero() -> None:
    # Observed bin has probability 0 -> floored to 1e-12 -> -ln(1e-12).
    one_hot_zero: MinutesDistribution = (0.0, 0.0, 0.0, 1.0)
    assert minutes_log_score(one_hot_zero, 0, floor=FLOOR) == pytest.approx(-math.log(FLOOR))


def test_minutes_log_score_is_consistent_with_phase1_when_floor_does_not_bind() -> None:
    # Phase 1's floor is also 1e-12; where the probability is well above it both must agree.
    dist = (0.4, 0.3, 0.2, 0.1)
    for observed in range(4):
        assert minutes_log_score(dist, observed, floor=FLOOR) == pytest.approx(
            phase1_log_score(dist, observed)
        )


def test_ranked_probability_score_is_ordered_category_cdf_errors() -> None:
    # cdf = (0.25, 0.5, 0.75, 1.0); observed = 0 -> every category's indicator is 1.
    # (0.25-1)^2 + (0.5-1)^2 + (0.75-1)^2 + (1-1)^2 = 0.5625 + 0.25 + 0.0625 + 0
    assert minutes_ranked_probability_score(UNIFORM, 0) == pytest.approx(0.875)


def test_ranked_probability_score_does_not_measure_physical_minute_distance() -> None:
    # A one-hot at the observed bin is a perfect RPS (0) regardless of which bin.
    for bin_index in range(4):
        one_hot: MinutesDistribution = tuple(  # type: ignore[misc]
            1.0 if i == bin_index else 0.0 for i in range(4)
        )
        assert minutes_ranked_probability_score(one_hot, bin_index) == pytest.approx(0.0)


def test_ranked_probability_score_for_a_two_bin_away_miss() -> None:
    # cdf = (0, 0, 1, 1); observed = 0. Indicators all 1.
    # (0-1)^2 + (0-1)^2 + (1-1)^2 + (1-1)^2 = 1 + 1 + 0 + 0 = 2.0
    dist: MinutesDistribution = (0.0, 0.0, 1.0, 0.0)
    assert minutes_ranked_probability_score(dist, 0) == pytest.approx(2.0)


def test_brier_any_minutes_uses_one_minus_p0() -> None:
    # p = 1 - 0.25 = 0.75; observed bin 0 -> y = 0. (0.75)^2 = 0.5625
    assert brier_any_minutes(UNIFORM, 0) == pytest.approx(0.5625)
    # observed bin 1 -> y = 1. (0.75 - 1)^2 = 0.0625
    assert brier_any_minutes(UNIFORM, 1) == pytest.approx(0.0625)


def test_brier_60_plus_uses_p2_plus_p3() -> None:
    # p = 0.25 + 0.25 = 0.5; observed bin 0 -> y = 0. (0.5)^2 = 0.25
    assert brier_60_plus(UNIFORM, 0) == pytest.approx(0.25)
    # observed bin 2 -> y = 1. (0.5 - 1)^2 = 0.25
    assert brier_60_plus(UNIFORM, 2) == pytest.approx(0.25)


def test_probability_margins() -> None:
    assert probability_any_minutes(UNIFORM) == pytest.approx(0.75)
    assert probability_60_plus(UNIFORM) == pytest.approx(0.5)


# --------------------------------------------------------------------------------------
# Distribution / observation validation
# --------------------------------------------------------------------------------------


def test_scoring_rejects_wrong_bin_count() -> None:
    with pytest.raises(ValueError, match="exactly 4"):
        score_minutes_predictions(
            [(0.5, 0.5)],
            [0],
            config=CONFIG,  # type: ignore[list-item]
        )


def test_scoring_rejects_negative_probability() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        score_minutes_predictions(
            [(1.2, -0.2, 0.0, 0.0)],
            [0],
            config=CONFIG,  # type: ignore[list-item]
        )


def test_scoring_rejects_non_finite_probability() -> None:
    with pytest.raises(ValueError, match="finite"):
        score_minutes_predictions(
            [(float("nan"), 0.0, 0.0, 1.0)],
            [0],
            config=CONFIG,  # type: ignore[list-item]
        )


def test_scoring_rejects_bool_probability() -> None:
    with pytest.raises(TypeError, match="non-bool float"):
        score_minutes_predictions(
            [(True, 0.0, 0.0, 0.0)],
            [0],
            config=CONFIG,  # type: ignore[list-item]
        )


def test_scoring_rejects_a_distribution_that_does_not_sum_to_one() -> None:
    with pytest.raises(ValueError, match=r"sum to 1\.0"):
        score_minutes_predictions(
            [(0.3, 0.3, 0.3, 0.3)],
            [0],
            config=CONFIG,  # type: ignore[list-item]
        )


def test_scoring_rejects_observation_out_of_range() -> None:
    with pytest.raises(ValueError, match=r"0\.\.3"):
        score_minutes_predictions([UNIFORM], [4], config=CONFIG)


def test_scoring_rejects_bool_observation() -> None:
    with pytest.raises(TypeError, match="non-bool int"):
        score_minutes_predictions([UNIFORM], [True], config=CONFIG)  # type: ignore[list-item]


def test_scoring_rejects_misaligned_lengths() -> None:
    with pytest.raises(ValueError, match="distributions against"):
        score_minutes_predictions([UNIFORM, UNIFORM], [0], config=CONFIG)


def test_scoring_rejects_empty_inputs() -> None:
    with pytest.raises(ValueError, match="no predictions"):
        score_minutes_predictions([], [], config=CONFIG)


def test_scoring_rejects_eligible_below_scored() -> None:
    with pytest.raises(ValueError, match="eligible prediction count"):
        score_minutes_predictions([UNIFORM, UNIFORM], [0, 1], config=CONFIG, eligible_predictions=1)


def test_scoring_rejects_misaligned_cold_starts() -> None:
    with pytest.raises(ValueError, match="cold-start flags must align"):
        score_minutes_predictions([UNIFORM, UNIFORM], [0, 1], config=CONFIG, cold_starts=[False])


def test_scoring_rejects_misaligned_rank_groups() -> None:
    with pytest.raises(ValueError, match="ranking groups must align"):
        score_minutes_predictions(
            [UNIFORM, UNIFORM], [0, 1], config=CONFIG, rank_groups=["only_one"]
        )


# --------------------------------------------------------------------------------------
# Reproducible randomised PIT (contract seed, fixed row order)
# --------------------------------------------------------------------------------------


def test_pit_is_reproducible_for_fixed_order_and_seed() -> None:
    distributions: list[MinutesDistribution] = [
        (0.1, 0.2, 0.3, 0.4),
        (0.5, 0.2, 0.2, 0.1),
        (0.0, 0.0, 0.0, 1.0),
        UNIFORM,
    ]
    observations = [0, 1, 3, 2]

    # Re-derive the expected PIT values from the same seed advanced row-by-row in order.
    expected_generator = random.Random(SEED)
    from fpl.validate.metrics import randomised_pit

    expected = [
        randomised_pit(dist, obs, expected_generator)
        for dist, obs in zip(distributions, observations, strict=True)
    ]

    report = score_minutes_predictions(distributions, observations, config=CONFIG)
    assert report.pit_values == pytest.approx(expected, rel=1e-12)


def test_pit_band_coverage_fraction_is_correct() -> None:
    # Build many rows; coverage is the fraction of PIT values inside the [0.1, 0.9] band.
    distributions = [UNIFORM] * 50
    observations = [i % 4 for i in range(50)]
    report = score_minutes_predictions(distributions, observations, config=CONFIG)
    expected = sum(1 for v in report.pit_values if BAND[0] <= v <= BAND[1]) / 50
    assert report.pit_interval_80_coverage == pytest.approx(expected)


# --------------------------------------------------------------------------------------
# Reliability: ten buckets, edges, accounting, empty buckets, final right-closed bucket
# --------------------------------------------------------------------------------------


def _all_buckets_present(curve) -> None:
    assert len(curve.buckets) == 10
    for i, bucket in enumerate(curve.buckets):
        assert bucket.lower == pytest.approx(EDGES[i])
        assert bucket.upper == pytest.approx(EDGES[i + 1])


def test_reliability_always_emits_all_ten_buckets() -> None:
    report = score_minutes_predictions([UNIFORM], [0], config=CONFIG)
    _all_buckets_present(report.reliability_any_minutes)
    _all_buckets_present(report.reliability_60_plus)


def test_reliability_empty_buckets_carry_none_not_zero() -> None:
    # Single uniform row: p_any = 0.75 -> bucket [0.7, 0.8). All other buckets empty.
    report = score_minutes_predictions([UNIFORM], [0], config=CONFIG)
    curve = report.reliability_any_minutes
    assert sum(bucket.n for bucket in curve.buckets) == 1
    occupied = [b for b in curve.buckets if b.n > 0]
    assert len(occupied) == 1
    assert occupied[0].lower == pytest.approx(0.7)
    assert occupied[0].mean_predicted == pytest.approx(0.75)
    assert occupied[0].observed_rate == pytest.approx(0.0)  # observed bin 0 -> no minutes
    for bucket in curve.buckets:
        if bucket.n == 0:
            assert bucket.mean_predicted is None
            assert bucket.observed_rate is None


def test_reliability_final_bucket_is_right_closed_for_probability_one() -> None:
    # One-hot at bin 3 -> p_60 = 1.0 must land in the final bucket [0.9, 1.0] (right-closed).
    one_hot_90: MinutesDistribution = (0.0, 0.0, 0.0, 1.0)
    report = score_minutes_predictions([one_hot_90], [3], config=CONFIG)
    curve = report.reliability_60_plus
    occupied = [b for b in curve.buckets if b.n > 0]
    assert len(occupied) == 1
    assert occupied[0].lower == pytest.approx(0.9)
    assert occupied[0].upper == pytest.approx(1.0)
    assert occupied[0].observed_rate == pytest.approx(1.0)


def test_reliability_left_closed_right_open_at_internal_edge() -> None:
    # A predicted probability of exactly 0.3 belongs to the bucket STARTING at 0.3 (left-closed),
    # not the one ending at 0.3.
    # p_any = 0.3 -> p0 = 0.7: (0.7, 0.1, 0.1, 0.1).
    dist: MinutesDistribution = (0.7, 0.1, 0.1, 0.1)
    report = score_minutes_predictions([dist], [0], config=CONFIG)
    occupied = [b for b in report.reliability_any_minutes.buckets if b.n > 0]
    assert occupied[0].lower == pytest.approx(0.3)
    assert occupied[0].upper == pytest.approx(0.4)


def test_reliability_bucket_n_accounts_for_every_prediction() -> None:
    distributions = [
        (0.8, 0.1, 0.05, 0.05),  # p_any=0.2,  p_60=0.1
        (0.4, 0.3, 0.2, 0.1),  # p_any=0.6,  p_60=0.3
        (0.1, 0.1, 0.3, 0.5),  # p_any=0.9,  p_60=0.8
        (0.0, 0.0, 0.0, 1.0),  # p_any=1.0,  p_60=1.0
    ]
    observations = [0, 1, 2, 3]
    report = score_minutes_predictions(distributions, observations, config=CONFIG)
    assert report.reliability_any_minutes.total_n() == 4
    assert report.reliability_60_plus.total_n() == 4


def test_reliability_mean_and_rate_over_a_populated_bucket() -> None:
    # Two rows in the same any-minutes bucket [0.7, 0.8): p_any = 0.75 and 0.75, observed 0 and 1.
    dist: MinutesDistribution = (0.25, 0.25, 0.25, 0.25)
    report = score_minutes_predictions([dist, dist], [0, 1], config=CONFIG)
    bucket = next(b for b in report.reliability_any_minutes.buckets if b.n > 0)
    assert bucket.n == 2
    assert bucket.mean_predicted == pytest.approx(0.75)
    assert bucket.observed_rate == pytest.approx(0.5)


def test_reliability_edges_read_from_contract() -> None:
    assert tuple(round(i / 10, 1) for i in range(11)) == EDGES


# --------------------------------------------------------------------------------------
# Within-group Spearman ranking of the 60-plus margin
# --------------------------------------------------------------------------------------


def test_spearman_is_perfect_for_a_monotone_group() -> None:
    # Two rows, one group: predicted p_60 and observed 60-plus binary both rise -> rank corr 1.0.
    distributions = [
        (0.9, 0.05, 0.03, 0.02),  # p_60 = 0.05, obs bin 0 -> observed_60 = 0
        (0.1, 0.1, 0.4, 0.4),  # p_60 = 0.80, obs bin 2 -> observed_60 = 1
    ]
    report = score_minutes_predictions(
        distributions, [0, 2], config=CONFIG, rank_groups=["gw", "gw"]
    )
    assert report.spearman_p60_within_position_gameweek == pytest.approx(1.0)


def test_spearman_ties_are_averaged_not_broken() -> None:
    # Two identical predicted p_60 values share an average rank (1.5, 1.5); observed_60 ties in
    # the same place ([0, 0, 1] -> ranks 1.5, 1.5, 3). Aligned average ranks -> correlation 1.0.
    distributions = [
        (0.5, 0.2, 0.2, 0.1),  # p_60 = 0.30
        (0.5, 0.2, 0.2, 0.1),  # p_60 = 0.30 (tie)
        (0.1, 0.1, 0.4, 0.4),  # p_60 = 0.80
    ]
    report = score_minutes_predictions(
        distributions, [0, 1, 2], config=CONFIG, rank_groups=["g", "g", "g"]
    )
    assert report.spearman_p60_within_position_gameweek == pytest.approx(1.0)


def test_spearman_averages_only_scoreable_groups() -> None:
    # Group "a" is scoreable (>= 2 rows, non-constant); group "b" has a single row (skipped);
    # group "c" has constant observed (Pearson None, skipped).
    distributions = [
        (0.9, 0.05, 0.03, 0.02),  # a: p_60=0.05, obs bin 0 -> observed_60 = 0
        (0.1, 0.1, 0.4, 0.4),  # a: p_60=0.80, obs bin 2 -> observed_60 = 1
        (0.2, 0.2, 0.3, 0.3),  # b: single row (skipped: too few)
        (0.5, 0.2, 0.2, 0.1),  # c: p_60=0.30, obs bin 0 -> observed_60 = 0
        (0.5, 0.2, 0.2, 0.1),  # c: p_60=0.30, obs bin 0 -> observed_60 = 0 (constant observed)
    ]
    report = score_minutes_predictions(
        distributions,
        [0, 2, 0, 0, 0],
        config=CONFIG,
        rank_groups=["a", "a", "b", "c", "c"],
    )
    # Only group "a" contributes, and it is perfectly monotone -> 1.0.
    assert report.spearman_p60_within_position_gameweek == pytest.approx(1.0)


def test_spearman_is_nan_when_no_group_is_scoreable() -> None:
    # Every group has a single row; nothing is scoreable.
    report = score_minutes_predictions(
        [UNIFORM, UNIFORM],
        [0, 1],
        config=CONFIG,
        rank_groups=["a", "b"],
    )
    assert math.isnan(report.spearman_p60_within_position_gameweek)


# --------------------------------------------------------------------------------------
# Counts, cold starts, uncertainty, coverage
# --------------------------------------------------------------------------------------


def test_counts_and_coverage_accounting() -> None:
    distributions = [UNIFORM] * 5
    observations = [0, 1, 2, 3, 0]
    report = score_minutes_predictions(
        distributions,
        observations,
        config=CONFIG,
        eligible_predictions=8,
        cold_starts=[True, False, True, False, False],
    )
    assert report.predictions == 5
    assert report.eligible_predictions == 8
    assert report.exclusions == 3
    assert report.cold_starts == 2
    assert report.prediction_coverage == pytest.approx(5 / 8)


def test_prediction_coverage_is_one_when_every_eligible_row_scored() -> None:
    report = score_minutes_predictions([UNIFORM], [0], config=CONFIG)
    assert report.prediction_coverage == pytest.approx(1.0)


def test_mean_log_score_standard_error_matches_row_log_scores() -> None:
    distributions = [
        (0.5, 0.2, 0.2, 0.1),
        (0.1, 0.1, 0.4, 0.4),
        (0.25, 0.25, 0.25, 0.25),
    ]
    observations = [0, 2, 1]
    report = score_minutes_predictions(distributions, observations, config=CONFIG)
    row_scores = [
        minutes_log_score(dist, obs, floor=FLOOR)
        for dist, obs in zip(distributions, observations, strict=True)
    ]
    average = sum(row_scores) / len(row_scores)
    variance = sum((s - average) ** 2 for s in row_scores) / (len(row_scores) - 1)
    expected_se = math.sqrt(variance / len(row_scores))
    assert report.mean_log_score == pytest.approx(average)
    assert report.mean_log_score_standard_error == pytest.approx(expected_se)


def test_aggregate_metrics_are_means_of_row_metrics() -> None:
    distributions = [
        (0.5, 0.2, 0.2, 0.1),
        (0.1, 0.1, 0.4, 0.4),
        (0.0, 0.0, 0.0, 1.0),
    ]
    observations = [0, 2, 0]
    report = score_minutes_predictions(distributions, observations, config=CONFIG)
    assert report.mean_ranked_probability_score == pytest.approx(
        sum(
            minutes_ranked_probability_score(d, o)
            for d, o in zip(distributions, observations, strict=True)
        )
        / 3
    )
    assert report.mean_brier_any_minutes == pytest.approx(
        sum(brier_any_minutes(d, o) for d, o in zip(distributions, observations, strict=True)) / 3
    )
    assert report.mean_brier_60_plus == pytest.approx(
        sum(brier_60_plus(d, o) for d, o in zip(distributions, observations, strict=True)) / 3
    )


def test_pit_interval_absolute_error_property() -> None:
    report = score_minutes_predictions([UNIFORM] * 100, [i % 4 for i in range(100)], config=CONFIG)
    assert report.pit_interval_80_absolute_error == pytest.approx(
        abs(report.pit_interval_80_coverage - 0.80)
    )


def test_report_is_frozen() -> None:
    report = score_minutes_predictions([UNIFORM], [0], config=CONFIG, name="test")
    with pytest.raises((AttributeError, Exception)):
        report.cold_starts = 5  # type: ignore[misc]
    assert report.name == "test"


def test_reliability_bucket_is_frozen() -> None:
    bucket = ReliabilityBucket(0.0, 0.1, 0, None, None)
    with pytest.raises((AttributeError, Exception)):
        bucket.n = 1  # type: ignore[misc]
