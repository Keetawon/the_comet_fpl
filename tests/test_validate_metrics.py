"""Proper scoring rules, calibration diagnostics, and the promotion-gate arithmetic.

These are pure functions over ten-element tuples, so nothing here needs the database. The
tests that matter most are the ones that pin *why* a metric is shaped the way it is: the
probability floor, the PIT-versus-raw coverage distinction, and the exact lift formula the
contract fixes.
"""

from __future__ import annotations

import math
import random

import pytest

from fpl.validate.metrics import (
    MAX_GOALS,
    Distribution,
    cdf,
    central_interval,
    crps,
    expected_goals,
    interval_covers,
    log_score,
    normalise,
    poisson_deviance,
    poisson_pmf,
    predictive_variance,
    randomised_pit,
    relative_lift,
    score_predictions,
    spearman_within_groups,
)


def _poisson_sample(rate: float, generator: random.Random) -> int:
    """Inverse-CDF draw from the same truncated Poisson the metrics assume."""
    masses = poisson_pmf(rate)
    target = generator.random()
    running = 0.0
    for goals, mass in enumerate(masses):
        running += mass
        if target <= running:
            return goals
    return len(masses) - 1


# --------------------------------------------------------------------------------------
# Distributions
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("rate", [0.0, 0.05, 0.5, 1.35, 2.4, 6.0])
def test_poisson_pmf_is_a_proper_distribution(rate: float) -> None:
    masses = poisson_pmf(rate)
    assert len(masses) == MAX_GOALS + 1
    assert all(mass >= 0.0 for mass in masses)
    assert math.isclose(sum(masses), 1.0, rel_tol=1e-12)


def test_poisson_pmf_matches_closed_form_below_the_truncation() -> None:
    rate = 1.35
    masses = poisson_pmf(rate)
    for goals in range(MAX_GOALS):
        expected = math.exp(-rate) * rate**goals / math.factorial(goals)
        assert math.isclose(masses[goals], expected, rel_tol=1e-12)


def test_poisson_pmf_folds_the_tail_into_the_final_bin() -> None:
    """The last bin is `P(goals >= MAX_GOALS)`, not `P(goals == MAX_GOALS)`.

    Without this a high-rate prediction leaks mass and the log score of a rare high score is
    computed against a distribution that does not sum to one.
    """
    rate = 6.0
    masses = poisson_pmf(rate)
    exact_at_ten = math.exp(-rate) * rate**MAX_GOALS / math.factorial(MAX_GOALS)
    assert masses[MAX_GOALS] > exact_at_ten


def test_poisson_pmf_rejects_a_negative_rate() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        poisson_pmf(-0.1)


def test_zero_rate_is_floored_rather_than_degenerate() -> None:
    """A rate of exactly zero would assign probability 1 to nil and infinite loss to a goal.

    No team ever has literally zero chance, so the floor keeps the log score finite without
    materially moving the prediction.
    """
    masses = poisson_pmf(0.0)
    assert masses[0] > 0.999999
    assert masses[1] > 0.0
    assert math.isfinite(log_score(masses, 3))


def test_normalise_rejects_an_empty_distribution() -> None:
    with pytest.raises(ValueError, match="no mass"):
        normalise([0.0, 0.0, 0.0])


def test_expected_goals_recovers_the_rate() -> None:
    """Exact only up to the folded tail, which at league rates is far below a rounding step."""
    assert math.isclose(expected_goals(poisson_pmf(1.5)), 1.5, abs_tol=1e-5)


def test_distribution_diagnostics_are_finite_and_non_negative() -> None:
    masses = poisson_pmf(1.5)
    assert predictive_variance(masses) == pytest.approx(1.5, abs=1e-4)
    assert poisson_deviance(masses, 0) == pytest.approx(3.0, abs=1e-4)
    assert poisson_deviance(masses, 3) > 0.0


# --------------------------------------------------------------------------------------
# Log score
# --------------------------------------------------------------------------------------


def test_log_score_is_the_negative_log_of_the_observed_bin() -> None:
    masses = poisson_pmf(1.4)
    assert math.isclose(log_score(masses, 2), -math.log(masses[2]), rel_tol=1e-12)


def test_log_score_is_minimised_by_the_truth() -> None:
    """Propriety, checked the only way that matters here: on the archive's own scale.

    Draws come from a rate of 1.35; scoring them under any other rate must be worse on
    average. A metric that failed this would let a deliberately over-dispersed candidate
    beat a correct one.
    """
    generator = random.Random(202627)
    truth = 1.35
    draws = [_poisson_sample(truth, generator) for _ in range(20_000)]
    true_score = sum(log_score(poisson_pmf(truth), goals) for goals in draws) / len(draws)
    for wrong in (0.9, 1.1, 1.6, 2.2):
        wrong_score = sum(log_score(poisson_pmf(wrong), goals) for goals in draws) / len(draws)
        assert wrong_score > true_score, f"rate {wrong} scored no worse than the truth"


def test_log_score_floors_a_zero_probability_outcome() -> None:
    """One impossible outcome must not become an infinite mean that hides every other row."""
    point_mass: Distribution = (1.0,) + (0.0,) * MAX_GOALS
    score = log_score(point_mass, 4)
    assert math.isfinite(score)
    assert score > 25.0, "the floor must still be a severe penalty"


def test_log_score_clamps_an_out_of_range_observation() -> None:
    masses = poisson_pmf(1.4)
    assert log_score(masses, 99) == log_score(masses, MAX_GOALS)
    assert log_score(masses, -1) == log_score(masses, 0)


# --------------------------------------------------------------------------------------
# CRPS
# --------------------------------------------------------------------------------------


def test_crps_of_a_correct_point_mass_is_zero() -> None:
    point_mass: Distribution = (0.0, 0.0, 1.0) + (0.0,) * (MAX_GOALS - 2)
    assert crps(point_mass, 2) == pytest.approx(0.0, abs=1e-12)


def test_crps_penalises_distance_where_log_score_does_not() -> None:
    """The reason both are reported.

    Two predictions can assign identical probability to what happened while differing wildly
    in where the rest of their mass sits. Log score cannot tell them apart; CRPS can.
    """
    near: Distribution = (0.0, 0.5, 0.2, 0.3) + (0.0,) * (MAX_GOALS - 3)
    far: Distribution = (0.5, 0.0, 0.2, 0.0, 0.0, 0.3) + (0.0,) * (MAX_GOALS - 5)
    assert log_score(near, 2) == pytest.approx(log_score(far, 2))
    assert crps(near, 2) < crps(far, 2)


def test_crps_is_minimised_by_the_truth() -> None:
    generator = random.Random(7)
    truth = 1.35
    draws = [_poisson_sample(truth, generator) for _ in range(20_000)]
    true_score = sum(crps(poisson_pmf(truth), goals) for goals in draws) / len(draws)
    for wrong in (0.9, 2.2):
        wrong_score = sum(crps(poisson_pmf(wrong), goals) for goals in draws) / len(draws)
        assert wrong_score > true_score


# --------------------------------------------------------------------------------------
# Calibration
# --------------------------------------------------------------------------------------


def test_randomised_pit_stays_inside_the_observed_bin() -> None:
    masses = poisson_pmf(1.4)
    generator = random.Random(1)
    lower = masses[0]
    upper = masses[0] + masses[1]
    for _ in range(200):
        value = randomised_pit(masses, 1, generator)
        assert lower <= value <= upper


def test_randomised_pit_is_uniform_when_the_model_is_correct() -> None:
    """The property the whole diagnostic rests on.

    Ten equal-width bins over 20,000 draws should each hold about 10% of the mass. The
    tolerance is loose enough not to be flaky and tight enough that a miscalibrated model
    fails it -- see the companion test below.
    """
    generator = random.Random(202627)
    rate = 1.35
    masses = poisson_pmf(rate)
    counts = [0] * 10
    draws = 20_000
    for _ in range(draws):
        goals = _poisson_sample(rate, generator)
        bucket = min(int(randomised_pit(masses, goals, generator) * 10), 9)
        counts[bucket] += 1
    for count in counts:
        assert abs(count / draws - 0.10) < 0.015


def test_randomised_pit_detects_a_miscalibrated_model() -> None:
    """Draws at 1.35 scored under 2.4 must pile the PIT into the low bins."""
    generator = random.Random(11)
    masses = poisson_pmf(2.4)
    low = 0
    draws = 5_000
    for _ in range(draws):
        goals = _poisson_sample(1.35, generator)
        if randomised_pit(masses, goals, generator) < 0.1:
            low += 1
    assert low / draws > 0.2, "a clearly over-confident rate should skew the PIT"


def test_central_interval_holds_at_least_the_requested_mass() -> None:
    for rate in (0.4, 1.35, 2.4, 3.6):
        masses = poisson_pmf(rate)
        low, high = central_interval(masses, 0.8)
        assert sum(masses[low : high + 1]) >= 0.8 - 1e-9


def test_raw_interval_coverage_of_a_correct_model_never_reaches_eighty_percent() -> None:
    """The measured defect behind amendment 1.1.

    A distribution over whole goals cannot be trimmed to an exact quantile, so the narrowest
    central interval holding *at least* 80% almost always holds appreciably more. Swept over
    every rate a Premier League team plausibly gets, a perfectly specified Poisson never
    undershoots and never lands on 0.80. It is the gate's own metric, not the model, that is
    at fault -- which is why the report's gate property uses PIT coverage instead.
    """
    coverages = []
    for step in range(1, 41):
        rate = step * 0.1
        masses = poisson_pmf(rate)
        low, high = central_interval(masses, 0.8)
        coverages.append(sum(masses[low : high + 1]))
    assert min(coverages) > 0.81, "a correct model should never undershoot 80%"
    assert max(coverages) > 0.98


def test_raw_coverage_overshoots_at_team_goal_rates_while_pit_coverage_does_not() -> None:
    """At the rates Stage A actually predicts, the overshoot is far outside the 0.05 gate."""
    generator = random.Random(202627)
    for rate in (0.8, 1.35, 2.0):
        masses = poisson_pmf(rate)
        draws = [_poisson_sample(rate, generator) for _ in range(20_000)]
        raw = sum(interval_covers(masses, goals) for goals in draws) / len(draws)
        pit = sum(0.1 <= randomised_pit(masses, goals, generator) <= 0.9 for goals in draws) / len(
            draws
        )
        assert raw - 0.80 > 0.05, f"rate {rate}: raw coverage {raw:.3f} should breach the gate"
        assert abs(pit - 0.80) < 0.02, f"rate {rate}: PIT coverage {pit:.3f} should sit at 0.80"


# --------------------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------------------


def test_score_predictions_reports_both_coverages_and_gates_on_the_pit_one() -> None:
    generator = random.Random(5)
    rate = 1.35
    masses = poisson_pmf(rate)
    observations = [_poisson_sample(rate, generator) for _ in range(4_000)]
    report = score_predictions("t", [masses] * len(observations), observations, seed=202627)

    assert report.predictions == len(observations)
    assert report.interval_80_coverage > 0.86
    assert abs(report.pit_interval_80_coverage - 0.80) < 0.03
    # The gate property must follow the PIT figure, not the raw one.
    assert report.pit_interval_80_absolute_error == pytest.approx(
        abs(report.pit_interval_80_coverage - 0.80)
    )
    assert len(report.pit_values) == len(observations)


def test_score_predictions_is_reproducible_for_a_fixed_seed() -> None:
    masses = poisson_pmf(1.4)
    observations = [0, 1, 2, 1, 3, 0]
    first = score_predictions("a", [masses] * 6, observations, seed=202627)
    second = score_predictions("a", [masses] * 6, observations, seed=202627)
    assert first.pit_values == second.pit_values


def test_score_predictions_reports_counts_uncertainty_and_within_gameweek_rank() -> None:
    distributions = [poisson_pmf(rate) for rate in (0.5, 1.0, 1.5, 2.0)]
    report = score_predictions(
        "a",
        distributions,
        [0, 1, 2, 3],
        seed=1,
        eligible_predictions=4,
        cold_starts=[True, False, False, True],
        rank_groups=["gw1"] * 4,
    )
    assert report.eligible_predictions == 4
    assert report.exclusions == 0
    assert report.cold_starts == 2
    assert report.fixture_coverage == 1.0
    assert report.mean_log_score_standard_error > 0.0
    assert report.mean_poisson_deviance > 0.0
    assert report.mean_predictive_variance > 0.0
    assert report.spearman_within_gameweek == pytest.approx(1.0)


def test_spearman_is_averaged_within_gameweek_not_across_them() -> None:
    predictions = [1.0, 2.0, 10.0, 9.0]
    observations = [0, 1, 0, 1]
    groups = ["gw1", "gw1", "gw2", "gw2"]
    assert spearman_within_groups(predictions, observations, groups) == pytest.approx(0.0)


def test_score_predictions_rejects_misaligned_populations() -> None:
    masses = poisson_pmf(1.4)
    with pytest.raises(ValueError, match="against"):
        score_predictions("a", [masses, masses], [1], seed=1)
    with pytest.raises(ValueError, match="no predictions"):
        score_predictions("a", [], [], seed=1)


def test_as_row_exposes_every_reported_metric() -> None:
    report = score_predictions("a", [poisson_pmf(1.4)], [1], seed=1)
    row = report.as_row()
    assert set(row) == {
        "baseline",
        "predictions",
        "eligible_predictions",
        "exclusions",
        "cold_starts",
        "fixture_coverage",
        "mean_log_score",
        "mean_log_score_standard_error",
        "mean_crps",
        "poisson_deviance",
        "interval_80_coverage",
        "pit_interval_80_coverage",
        "mae_goals",
        "mean_predictive_variance",
        "spearman_within_gameweek",
    }


# --------------------------------------------------------------------------------------
# Promotion arithmetic
# --------------------------------------------------------------------------------------


def test_relative_lift_matches_the_contract_formula() -> None:
    """`(baseline - candidate) / abs(baseline)`, positive when the candidate is better.

    Log score is lower-is-better, so a candidate scoring 1.50 against a baseline of 1.55 has
    improved; the sign convention must not be inverted anywhere.
    """
    assert relative_lift(1.55, 1.50) == pytest.approx((1.55 - 1.50) / 1.55)
    assert relative_lift(1.55, 1.50) > 0
    assert relative_lift(1.55, 1.60) < 0
    assert relative_lift(1.55, 1.55) == 0.0


def test_relative_lift_rejects_a_zero_baseline() -> None:
    with pytest.raises(ValueError, match="zero"):
        relative_lift(0.0, 1.0)


def _exact_raw_coverage(model_rate: float, true_rate: float) -> float:
    """P(draw from `true_rate` falls in the 80% interval built from `model_rate`)."""
    low, high = central_interval(poisson_pmf(model_rate), 0.8)
    return sum(poisson_pmf(true_rate)[low : high + 1])


def _exact_pit_coverage(model_rate: float, true_rate: float) -> float:
    """P(0.1 <= randomised PIT <= 0.9), integrated rather than sampled.

    Within the observed bin the PIT is uniform on `[F(k-1), F(k)]`, so the probability of
    landing in the band is that segment's overlap with `[0.1, 0.9]` as a fraction of the bin.
    Doing it exactly removes the seed from the argument entirely.
    """
    model = poisson_pmf(model_rate)
    truth = poisson_pmf(true_rate)
    cumulative = cdf(model)
    total = 0.0
    for goals, mass in enumerate(truth):
        if model[goals] <= 0:
            continue
        lower = cumulative[goals - 1] if goals else 0.0
        overlap = max(0.0, min(cumulative[goals], 0.9) - max(lower, 0.1))
        total += mass * (overlap / model[goals])
    return total


TEAM_GOAL_RATES = (1.0, 1.35, 1.6, 1.8, 2.2)
CANDIDATE_RATES = (0.8, 1.0, 1.35, 1.6, 1.8, 2.4, 3.0)


def test_pit_band_coverage_is_exactly_eighty_percent_at_the_truth() -> None:
    """The property that makes it gateable.

    A correctly specified model's randomised PIT is exactly Uniform(0, 1), so the fraction
    landing in `[0.1, 0.9]` is exactly 0.80 -- not approximately, and not dependent on the
    rate. Nothing about the discreteness of goals survives the transform.
    """
    for rate in TEAM_GOAL_RATES:
        assert _exact_pit_coverage(rate, rate) == pytest.approx(0.80, abs=1e-12)


def test_the_superseded_gate_prefers_a_miscalibrated_model_to_a_correct_one() -> None:
    """Amendment 1.1's evidence, and the reason the old gate was not merely strict.

    At a true rate of 1.80 the correct model's raw coverage misses 80% by 0.164 and fails the
    old gate, while a model predicting 2.40 -- 33% too high -- misses by 0.002 and passes it.
    Gating the raw figure would have rejected the right answer in favour of a biased one.
    """
    truth = 1.8
    correct = abs(_exact_raw_coverage(truth, truth) - 0.80)
    biased = abs(_exact_raw_coverage(2.4, truth) - 0.80)
    assert correct > 0.05, "the correct model fails the superseded gate"
    assert biased < 0.05, "the biased model passes it"
    assert biased < correct


def test_only_the_pit_measure_is_minimised_by_the_truth() -> None:
    """Swept across the band where team goals sit, so the finding is not one lucky rate."""
    for truth in TEAM_GOAL_RATES:
        candidates = sorted({*CANDIDATE_RATES, truth})
        raw_errors = {r: abs(_exact_raw_coverage(r, truth) - 0.80) for r in candidates}
        pit_errors = {r: abs(_exact_pit_coverage(r, truth) - 0.80) for r in candidates}
        best_raw = min(candidates, key=lambda r: raw_errors[r])
        best_pit = min(candidates, key=lambda r: pit_errors[r])
        assert best_pit == truth, f"PIT coverage should be closest to nominal at {truth}"
        assert best_raw != truth, (
            f"raw coverage was expected to favour a wrong rate at {truth}, got {best_raw}"
        )
