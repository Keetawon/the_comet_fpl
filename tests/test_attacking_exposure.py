"""Offline tests for the shared PURE exposure helpers (``fpl.models.attacking_exposure``).

No network, no database. Each function is hand-computable; these pin the exact invariants the
goals V4 and assists V2 candidates rely on: exposure-weighted per-min rate, Option-A window
with NULL exclusion, unconditional E[minutes] (bin 0 contributes 0), underlying Poisson-rate
conservation, the no-double-counted-availability property, starter-vs-substitute exposure, and
low-minute shrinkage toward the position prior.
"""

from __future__ import annotations

import math

from fpl.models.attacking_exposure import (
    BIN_MEAN_FALLBACKS,
    PRIOR_MINUTES,
    allocate_team_scale,
    expected_minutes,
    shrunk_rate_per_min,
    trailing_signal_minutes,
    trailing_signal_per_appearance,
)

# --------------------------------------------------------------------------------------
# Fixed development constants
# --------------------------------------------------------------------------------------


def test_prior_minutes_is_locked_at_one_full_match() -> None:
    """prior_minutes is fixed (90, one full-match equivalent); never tuned after a result."""
    assert PRIOR_MINUTES == 90.0
    assert BIN_MEAN_FALLBACKS == (0.0, 30.0, 75.0, 90.0)


# --------------------------------------------------------------------------------------
# Exposure-weighted per-minute rate + shrinkage
# --------------------------------------------------------------------------------------


def test_shrunk_rate_cold_start_equals_position_prior() -> None:
    """A cold start (no measured minutes) reduces exactly to the position prior."""
    assert shrunk_rate_per_min(0.0, 0.0, 0.0042) == 0.0042


def test_shrunk_rate_parity_at_one_full_match() -> None:
    """At 90 measured minutes with the player's own rate == prior, the rate is unchanged."""
    prior = 0.005  # xG/min (~0.45 xG/90)
    # 90 minutes at the prior rate => signal_sum = 90 * prior.
    assert math.isclose(shrunk_rate_per_min(90.0 * prior, 90.0, prior), prior, rel_tol=1e-12)
    # At 360 minutes (four matches) the player dominates: ~80% own weight.
    shrunk = shrunk_rate_per_min(360.0 * prior, 360.0, prior)
    assert math.isclose(shrunk, prior, rel_tol=1e-12)  # own rate == prior => unchanged regardless


def test_shrunk_rate_tames_a_cameo_explosion() -> None:
    """A 10-min cameo with a lucky 0.3 xG (naive 2.7 xG/90) is pulled toward the position prior."""
    prior = 0.005  # ~0.45 xG/90
    shrunk_per_min = shrunk_rate_per_min(0.3, 10.0, prior)
    shrunk_per_90 = 90.0 * shrunk_per_min
    raw_per_90 = 90.0 * (0.3 / 10.0)
    assert math.isclose(raw_per_90, 2.7)  # the absurd naive rate
    # Shrunk rate sits between the prior-only (0.45) and the naive (2.7), closer to the prior.
    assert 0.45 < shrunk_per_90 < 0.8


def test_shrunk_rate_does_not_collapse_a_moderate_sub() -> None:
    """A sub with ~125 measured minutes retains majority own-rate weight (not over-shrunk)."""
    prior = 0.005
    # 125 minutes at twice the prior rate.
    player_rate = 2.0 * prior
    shrunk_per_min = shrunk_rate_per_min(125.0 * player_rate, 125.0, prior)
    # own-weight share = 125 / (125 + 90) ~ 0.58 -> shrunk sits 58% of the way prior->player_rate.
    expected = (125.0 * player_rate + 90.0 * prior) / (125.0 + 90.0)
    assert math.isclose(shrunk_per_min, expected, rel_tol=1e-12)
    assert shrunk_per_min > prior  # not collapsed to the prior


# --------------------------------------------------------------------------------------
# Option-A trailing window: NULL excluded from BOTH signal and minutes
# --------------------------------------------------------------------------------------


def test_trailing_signal_minutes_excludes_null_signal_rows() -> None:
    """A NULL-signal row contributes neither signal nor minutes (NULL means unmeasured, never 0)."""
    rows = [
        (1.0, 90, 0.3),  # measured
        (2.0, 15, None),  # NULL xG -> excluded (minutes 15 NOT counted)
        (3.0, 90, 0.2),  # measured
    ]
    signal_sum, minutes_sum = trailing_signal_minutes(rows, window=5)
    assert math.isclose(signal_sum, 0.5)  # 0.3 + 0.2
    assert math.isclose(minutes_sum, 180.0)  # 90 + 90 (the 15-min cameo's minutes excluded)


def test_trailing_signal_minutes_keeps_only_last_window_rows() -> None:
    rows = [(float(i), 90, 0.1 * i) for i in range(1, 8)]  # 7 chronological rows
    signal_sum, minutes_sum = trailing_signal_minutes(rows, window=5)
    # last 5 rows: i = 3..7 -> signals 0.3..0.7 sum 2.5; minutes 5*90 = 450.
    assert math.isclose(signal_sum, 0.3 + 0.4 + 0.5 + 0.6 + 0.7)
    assert math.isclose(minutes_sum, 450.0)


def test_trailing_signal_minutes_empty_window_is_cold_start() -> None:
    assert trailing_signal_minutes([], window=5) == (0.0, 0.0)
    # All-NULL window is also a cold start.
    assert trailing_signal_minutes([(1.0, 90, None), (2.0, 15, None)], window=5) == (0.0, 0.0)


def test_trailing_signal_per_appearance_treats_cameo_as_full_match() -> None:
    """The raw per-appearance aggregation: a 15-min cameo counts as much as a 90-min match."""
    rows = [
        (1.0, 90, 0.3),  # measured appearance
        (2.0, 15, 0.3),  # 15-min cameo counts the SAME as the 90-min match (mean per appearance)
        (3.0, 90, None),  # NULL -> excluded from numerator and denominator
    ]
    mean_sig, count = trailing_signal_per_appearance(rows, window=5)
    assert math.isclose(mean_sig, 0.3)  # (0.3 + 0.3) / 2
    assert count == 2


def test_trailing_signal_per_appearance_keeps_only_last_window_rows() -> None:
    rows = [(float(i), 90, 0.1 * i) for i in range(1, 8)]  # 7 chronological rows
    mean_sig, count = trailing_signal_per_appearance(rows, window=5)
    # last 5 rows: i = 3..7 -> mean of 0.3..0.7 = 0.5; 5 measured rows.
    assert math.isclose(mean_sig, 0.5)
    assert count == 5


def test_trailing_signal_per_appearance_empty_window_is_cold_start() -> None:
    assert trailing_signal_per_appearance([], window=5) == (0.0, 0)
    assert trailing_signal_per_appearance([(1.0, 90, None), (2.0, 15, None)], window=5) == (0.0, 0)


# --------------------------------------------------------------------------------------
# E[minutes]: unconditional (bin 0 contributes exactly 0)
# --------------------------------------------------------------------------------------


def test_expected_minutes_is_probability_weighted_bin_means() -> None:
    probs = (0.2, 0.3, 0.4, 0.1)
    means = (0.0, 30.0, 75.0, 90.0)
    assert math.isclose(
        expected_minutes(probs, means), 0.2 * 0.0 + 0.3 * 30.0 + 0.4 * 75.0 + 0.1 * 90.0
    )


def test_expected_minutes_bin_zero_contributes_nothing() -> None:
    """Availability is folded in once via the zero bin mean: doubling p0 only removes minutes."""
    full = (0.0, 0.3, 0.4, 0.3)
    half = (0.5, 0.15, 0.2, 0.15)  # same conditional shape, half the appearance probability
    means = (0.0, 30.0, 75.0, 90.0)
    assert math.isclose(expected_minutes(half, means), 0.5 * expected_minutes(full, means))


# --------------------------------------------------------------------------------------
# Starter vs substitute exposure: equal xG/90, weight proportional to E[minutes]
# --------------------------------------------------------------------------------------


def test_starter_and_sub_equal_rate_weight_proportional_to_expected_minutes() -> None:
    """A 90-min starter and a 15-min sub with the SAME xG/90 get weights proportional to
    E[minutes]; a per-appearance mean (V3-style) would tie them. Hypothesis in one line."""
    prior = 0.005
    rate_per_min = prior  # identical per-minute productivity
    starter_e = expected_minutes((0.0, 0.0, 0.1, 0.9), (0.0, 30.0, 75.0, 90.0))
    sub_e = expected_minutes((0.6, 0.4, 0.0, 0.0), (0.0, 30.0, 75.0, 90.0))
    starter_weight = rate_per_min * starter_e
    sub_weight = rate_per_min * sub_e
    assert starter_weight > 0.0 and sub_weight >= 0.0
    if sub_weight > 0.0:
        assert math.isclose(starter_weight / sub_weight, starter_e / sub_e, rel_tol=1e-12)
    assert starter_weight > sub_weight  # the starter dominates despite equal xG/90


# --------------------------------------------------------------------------------------
# Underlying Poisson-rate conservation
# --------------------------------------------------------------------------------------


def test_allocate_team_scale_conserves_team_total() -> None:
    weights = {1: 0.5, 2: 0.25, 3: 0.0}  # player 3 has zero exposure weight
    lam = 1.4
    rates = allocate_team_scale(weights, lam)
    assert math.isclose(sum(rates.values()), lam, rel_tol=1e-12)
    # Proportional to the weights (player 3 gets 0).
    total = 0.75
    assert math.isclose(rates[1], lam * 0.5 / total, rel_tol=1e-12)
    assert rates[3] == 0.0


def test_allocate_team_scale_equal_share_when_total_zero() -> None:
    """All-zero weights -> deterministic equal shares, still conserving the team total."""
    rates = allocate_team_scale({1: 0.0, 2: 0.0, 3: 0.0}, 0.9)
    assert math.isclose(sum(rates.values()), 0.9, rel_tol=1e-12)
    assert math.isclose(rates[1], 0.3, rel_tol=1e-12)


def test_allocate_team_scale_empty_roster_is_empty() -> None:
    assert allocate_team_scale({}, 1.0) == {}
