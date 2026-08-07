"""Shrinkage for the trailing-five minute-bin estimate used by the prospective composer.

A raw ``counts / n`` over a five-match window is a maximum-likelihood estimate from five
Bernoulli trials, so it can only take the six values ``0, 0.2, 0.4, 0.6, 0.8, 1.0`` and it is
badly over-confident at both ends. Measured on 101,306 archive rows from 2021-22 to 2024-25,
what a raw trailing-five appearance count actually predicts is:

===========  ===========  ==========
raw ``k/5``  ``P(play)``  ``P(60+)``
===========  ===========  ==========
0.0          0.039        0.036
0.2          0.310        0.279
0.4          0.459        0.419
0.6          0.588        0.543
0.8          0.736        0.695
1.0          0.897        0.869
===========  ===========  ==========

The composer's whole full-points distribution hangs off this draw, so an estimate that says
1.000 where the truth is 0.897 gives a nailed starter no lower tail at all, and one that says
0.000 where the truth is 0.039 gives a fringe player no upper tail. That is the dominant source
of the composer's measured under-dispersion (PIT-80 coverage 0.7454 against a nominal 0.80).

Two regimes, because the data says two regimes
----------------------------------------------

For ``k >= 1`` the realised rate is very close to linear in ``k`` -- a textbook
Dirichlet-multinomial posterior mean. Extrapolating that line to ``k = 0`` predicts about
0.16, but the measured value is 0.039, over four times smaller, on 43,139 rows. A player who
has appeared in *none* of his last five is not a low draw from the same distribution: he is
injured, suspended, or out of the side, and that state persists. So ``k = 0`` gets its own
measured profile rather than being shrunk toward the in-squad prior.

This also buys resolution rather than costing it, which is the opposite of what shrinkage did
to Stage B Candidates V1/V2/V3. The raw estimator ties every non-appearance and every
substitute-only window together at exactly zero, and those two groups are not alike: measured
over 2025-26, a window of pure absence goes on to play 60+ minutes 0.9% of the time and a
substitute-only window 13.4% of the time, a fifteen-fold difference collapsed into one tie.
"""

from __future__ import annotations

from collections.abc import Sequence

__all__ = [
    "MINUTES_SHRINKAGE_ALPHA",
    "MINUTES_SHRINKAGE_MIN_PRIOR_ROWS",
    "shrink_minute_bins",
]

MINUTES_SHRINKAGE_ALPHA = 3.5
"""Dirichlet concentration for the in-squad regime.

Selected by four-bin log loss on 2021-22..2024-25 (104,354 point-in-time rows) over a grid of
0.25 to 12.0 in steps of 0.25, with 2025-26 held out and not consulted during selection. The
optimum is interior and the neighbourhood is flat (3.00: 0.70328, 3.25: 0.70298, 3.50: 0.70294,
3.75: 0.70311, 4.00: 0.70345), so the value is not knife-edge.

Held out on 2025-26 at this frozen value, against the raw estimator: Brier on P(play) +4.00%,
Brier on P(60+) +5.34%, AUC on P(60+) +2.18%, and per-gameweek within-position AUC on P(60+)
+1.02% -- better in 123 of 152 gameweek-position groups. Every one of the five seasons improves
on both log loss and AUC.
"""

MINUTES_SHRINKAGE_MIN_PRIOR_ROWS = 500
"""Rows a position's own prior needs before it is preferred to the all-position prior.

Goalkeepers are the reason this exists: their bin profile is nothing like an outfielder's (they
almost never play a partial match), so a pooled prior is wrong for them -- but early in the
archive a single position can be too thin to estimate, and then pooling is the lesser error.
"""


def shrink_minute_bins(
    counts: Sequence[float],
    n: int,
    *,
    in_squad_prior: Sequence[float],
    out_of_side_profile: Sequence[float],
    alpha: float = MINUTES_SHRINKAGE_ALPHA,
) -> tuple[float, ...]:
    """Shrink a trailing-window minute-bin count vector to a calibrated distribution.

    ``counts`` are the observed per-bin counts over the ``n`` most recent rows, bin 0 being
    "did not play". ``in_squad_prior`` is the population bin frequency among rows whose own
    trailing window contained at least one appearance, and ``out_of_side_profile`` the same
    among rows whose window contained none. Both must be point-in-time.

    The in-squad prior is deliberately *not* the pooled population frequency. Once the
    zero-appearance windows are given their own regime, the remaining population is a
    different one -- measured over the archive, pooled bin-0 frequency is 0.594 against an
    in-squad 0.304. Shrinking in-squad players toward the pooled figure drags them toward
    absences that have already been removed, and it measurably over-shrinks: it under-predicts
    appearance in every reliability bucket (by 6 to 10 percentage points) where the in-squad
    prior lands within 3.5.

    ``alpha = 0.0`` disables the estimator entirely and returns the raw ``counts / n``, both
    regimes included. It is the reproducibility escape hatch, not a tuning value.
    """
    if n <= 0:
        raise ValueError("n must be positive to form a trailing-window estimate")
    if alpha < 0.0:
        raise ValueError(f"alpha must be non-negative, got {alpha}")
    if alpha == 0.0:
        return tuple(c / n for c in counts)
    if counts[0] >= n:
        return tuple(out_of_side_profile)
    if len(in_squad_prior) != len(counts):
        raise ValueError(f"prior has {len(in_squad_prior)} bins, counts have {len(counts)}")
    denominator = n + alpha
    return tuple((counts[j] + alpha * in_squad_prior[j]) / denominator for j in range(len(counts)))
