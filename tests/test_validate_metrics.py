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
    central_interval,
    crps,
    expected_goals,
    interval_covers,
    log_score,
    normalise,
    poisson_pmf,
    randomised_pit,
    relative_lift,
    score_predictions,
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
    """The measured defect behind `ScoreReport.interval_80_absolute_error`.

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
    assert report.interval_80_absolute_error == pytest.approx(
        abs(report.pit_interval_80_coverage - 0.80)
    )
    assert len(report.pit_values) == len(observations)


def test_score_predictions_is_reproducible_for_a_fixed_seed() -> None:
    masses = poisson_pmf(1.4)
    observations = [0, 1, 2, 1, 3, 0]
    first = score_predictions("a", [masses] * 6, observations, seed=202627)
    second = score_predictions("a", [masses] * 6, observations, seed=202627)
    assert first.pit_values == second.pit_values


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
        "mean_log_score",
        "mean_crps",
        "interval_80_coverage",
        "pit_interval_80_coverage",
        "mae_goals",
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
