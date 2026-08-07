"""Contract tests for the trailing-window minute-bin shrinkage estimator.

The estimator exists because a raw ``counts / n`` over five rows is over-confident at both
ends, and because the composer's entire full-points distribution is drawn through it. These
tests pin the three properties that make it safe to put in that position: it never returns a
degenerate probability where the raw estimate did, it never re-orders players within a
position, and its two regimes stay separate.
"""

from __future__ import annotations

import pytest

from fpl.models.minutes_shrinkage import (
    MINUTES_SHRINKAGE_ALPHA,
    shrink_minute_bins,
)

IN_SQUAD = (0.304, 0.197, 0.142, 0.357)
OUT_OF_SIDE = (0.963, 0.026, 0.004, 0.007)


def estimate(counts: tuple[float, ...], n: int, **kw: float) -> tuple[float, ...]:
    return shrink_minute_bins(
        counts, n, in_squad_prior=IN_SQUAD, out_of_side_profile=OUT_OF_SIDE, **kw
    )


def test_a_full_window_no_longer_asserts_certainty() -> None:
    """5/5 appearances must not produce P(play) = 1.

    This is the defect the estimator exists for: the composer scores a bin-0 draw as exactly
    zero points, so P(play) = 1 gives a nailed starter a distribution with no lower tail, and
    an actual blank then falls outside the support entirely.
    """
    raw = estimate((0.0, 0.0, 0.0, 5.0), 5, alpha=0.0)
    shrunk = estimate((0.0, 0.0, 0.0, 5.0), 5)
    assert raw[0] == 0.0
    assert 0.0 < shrunk[0] < 0.15
    assert sum(shrunk[1:]) < 1.0
    assert abs(sum(shrunk) - 1.0) < 1e-12


def test_an_empty_window_is_not_shrunk_toward_the_in_squad_prior() -> None:
    """Zero appearances in five is a different state, not a low draw.

    Extrapolating the in-squad posterior to k = 0 gives P(play) near 0.16; the measured value
    over 43,139 archive rows is 0.039. Shrinking these rows toward the in-squad prior would be
    a four-fold over-statement on the single largest group of rows in the population.
    """
    shrunk = estimate((5.0, 0.0, 0.0, 0.0), 5)
    assert shrunk == OUT_OF_SIDE
    in_squad_path = estimate((4.0, 1.0, 0.0, 0.0), 5)
    assert sum(shrunk[1:]) < sum(in_squad_path[1:]) / 2


def test_a_single_appearance_separates_from_pure_absence() -> None:
    """The resolution gain, and the reason this is not the Stage B shrinkage failure.

    The raw estimator ties a substitute-only window and a pure-absence window together at
    P(60+) = 0. Measured over 2025-26 those groups go on to play 60+ minutes 13.4% and 0.9%
    of the time. Collapsing a fifteen-fold difference into one tie is lost resolution, and
    separating them recovers it.
    """
    absent = estimate((5.0, 0.0, 0.0, 0.0), 5)
    cameo = estimate((4.0, 1.0, 0.0, 0.0), 5)
    assert cameo[2] + cameo[3] > absent[2] + absent[3]
    assert cameo[0] < absent[0]


@pytest.mark.parametrize("n", [3, 4, 5])
def test_shrinkage_is_order_preserving_within_a_window_size(n: int) -> None:
    """Strictly increasing in the observed count, so it cannot cost within-position ranking.

    Stage B Candidates V1, V2 and V3 each improved every proper score and each failed the
    starter-ranking gate. That is the standing risk with any shrinkage, so it is pinned here:
    for a fixed window size the posterior mean is a strictly increasing function of the
    observed count, and monotone maps do not reorder.
    """
    values = []
    for k in range(1, n + 1):
        counts = (float(n - k), 0.0, 0.0, float(k))
        dist = estimate(counts, n)
        values.append(dist[3])
    assert values == sorted(values)
    assert len(set(values)) == len(values)


def test_alpha_zero_reproduces_the_raw_estimate_exactly() -> None:
    """The reproducibility escape hatch, including the out-of-side regime."""
    cases = (((5.0, 0.0, 0.0, 0.0), 5), ((1.0, 1.0, 1.0, 2.0), 5), ((2.0, 1.0, 0.0, 0.0), 3))
    for counts, n in cases:
        assert estimate(counts, n, alpha=0.0) == tuple(c / n for c in counts)


def test_a_shorter_window_is_shrunk_harder() -> None:
    """Three rows of evidence must move the estimate less than five do."""
    short = estimate((0.0, 0.0, 0.0, 3.0), 3)
    long = estimate((0.0, 0.0, 0.0, 5.0), 5)
    assert short[3] < long[3]
    assert short[0] > long[0]


def test_the_estimate_is_a_distribution_for_every_reachable_count_vector() -> None:
    for n in (3, 4, 5):
        for c0 in range(n + 1):
            for c1 in range(n - c0 + 1):
                for c2 in range(n - c0 - c1 + 1):
                    c3 = n - c0 - c1 - c2
                    dist = estimate((float(c0), float(c1), float(c2), float(c3)), n)
                    assert abs(sum(dist) - 1.0) < 1e-12
                    assert all(0.0 <= p <= 1.0 for p in dist)


def test_invalid_inputs_are_rejected_rather_than_silently_absorbed() -> None:
    with pytest.raises(ValueError, match="n must be positive"):
        estimate((0.0, 0.0, 0.0, 0.0), 0)
    with pytest.raises(ValueError, match="alpha must be non-negative"):
        estimate((1.0, 1.0, 1.0, 2.0), 5, alpha=-1.0)
    with pytest.raises(ValueError, match="prior has 3 bins"):
        shrink_minute_bins(
            (1.0, 1.0, 1.0, 2.0),
            5,
            in_squad_prior=(0.3, 0.3, 0.4),
            out_of_side_profile=OUT_OF_SIDE,
        )


def test_the_frozen_alpha_is_the_value_the_holdout_was_measured_at() -> None:
    """A silent change to alpha would invalidate every figure recorded for this estimator."""
    assert MINUTES_SHRINKAGE_ALPHA == 3.5
