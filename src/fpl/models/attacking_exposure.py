"""Shared PURE exposure-weighting helpers for Stage C attacking candidates.

Candidate V4 (goals) and Candidate V2 (assists) both form a player's attacking expectation as

    per-minute productivity  x  predicted exposure

and allocate a frozen team scale by those weights. The math is identical for goals (xG/min) and
assists (xA/min); only the signal column and the team scale differ. This module holds the
signal-agnostic, database-free pieces so the two candidates share one tested implementation and
neither imports the other.

It is deliberately PURE: no DuckDB, no SQL, no Polars, no config read, no ``threat``/``creativity``
fallback (the xG-only / xA-only candidates never read a fallback signal). Each function is
hand-computable and unit-tested directly.

Conventions
-----------
* ``signal`` is a per-appearance measured value (``expected_goals`` for goals, ``expected_assists``
  for assists). ``NULL`` means unmeasured and is NEVER zero-filled: a NULL-signal row contributes
  neither to the signal sum nor to the minutes sum (R data contract).
* "minutes" are always actual played minutes on appeared rows (``minutes > 0``).
* ``prior_minutes`` is the fixed development shrinkage strength (one full-match equivalent = 90),
  locked in the contract and never tuned after a result.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

# Fixed development shrinkage: one full-match equivalent of prior exposure. A player's own measured
# rate reaches equal weight with the position prior at 90 measured minutes, ~80% at 360 (four
# matches), ~89% at 720. This is a FIXED development choice, locked in the contract before any
# evaluation; it is never tuned or changed after a result.
PRIOR_MINUTES: float = 90.0

# Deterministic empty-bin fallbacks for fold-local bin means (bin midpoints / cap). Used only when a
# fold's training history contains no row in a bin (essentially the first pre-xG folds). Bin 0 is
# always exactly zero by construction; its fallback is never reached but kept for symmetry.
BIN_MEAN_FALLBACKS: tuple[float, float, float, float] = (0.0, 30.0, 75.0, 90.0)

# A four-bin minutes distribution (matches ``fpl.validate.minutes_baselines.MinutesDistribution``
# without importing it; this module stays model-only / validate-free).
type FourBinDistribution = tuple[float, float, float, float]


def shrunk_rate_per_min(
    signal_sum: float,
    minutes_sum: float,
    position_rate_per_min: float,
    *,
    prior_minutes: float = PRIOR_MINUTES,
) -> float:
    """Exposure-based shrinkage of a per-minute signal rate toward the position prior.

        shrunk = (signal_sum + prior_minutes * position_rate_per_min)
                 / (minutes_sum + prior_minutes)

    Units: signal-per-minute (xG/min or xA/min). A cold start (``minutes_sum == 0``) reduces
    EXACTLY to ``position_rate_per_min``. ``prior_minutes`` is the fixed development choice
    (90); it is the minutes-equivalent of position-average play the prior is trusted as, never
    a tuned knob.
    """
    return (signal_sum + prior_minutes * position_rate_per_min) / (minutes_sum + prior_minutes)


def trailing_signal_minutes(
    rows: Sequence[tuple[float, int, float | None]],
    *,
    window: int,
) -> tuple[float, float]:
    """Option-A trailing window: last ``window`` appeared rows, summed over measured-signal rows.

    ``rows`` are ``(kickoff_epoch, minutes, signal)`` in chronological order (the history query is
    ``ORDER BY kickoff_time, season, fixture, code``, so arrival order is chronological; the last
    ``window`` entries are the most recent). Among those ``window`` rows, a NULL signal contributes
    NEITHER signal NOR minutes (NULL means unmeasured, never zero). Returns ``(signal_sum,
    minutes_sum)``; both are 0.0 when no measured-signal row is in the window (a cold start).
    """
    signal_sum = 0.0
    minutes_sum = 0.0
    for _epoch, minutes, signal in list(rows)[-window:]:
        if signal is not None:
            signal_sum += signal
            minutes_sum += float(minutes)
    return signal_sum, minutes_sum


def trailing_signal_per_appearance(
    rows: Sequence[tuple[float, int, float | None]],
    *,
    window: int,
) -> tuple[float, int]:
    """Option-A trailing window MEAN signal per APPEARANCE (the raw per-appearance aggregation).

    The controlled-comparator counterpart to :func:`trailing_signal_minutes`: over the last
    ``window`` appeared rows it takes the MEAN of the measured-signal values (NULL-signal rows are
    excluded from both numerator and denominator, so a 15-min cameo counts as much as a 90-min
    match -- exactly the property the exposure candidate is tested against). Returns
    ``(mean_signal_per_appearance, measured_count)``; the mean is 0.0 and the count 0 when no
    measured-signal row is in the window (a cold start). ``math.fsum`` keeps the mean reproducible.
    """
    measured = [sig for _epoch, _minutes, sig in list(rows)[-window:] if sig is not None]
    if not measured:
        return 0.0, 0
    return math.fsum(measured) / len(measured), len(measured)


def expected_minutes(bin_probs: FourBinDistribution, bin_means: FourBinDistribution) -> float:
    """E[minutes] = sum_b P(bin = b) * bin_mean_b.

    Unconditional by construction: bin 0 (no appearance) contributes ``bin_means[0]`` which is
    exactly 0, so availability is folded in once (the zero-minute mass contributes nothing). This is
    the quantity the exposure weight multiplies; the candidate must NOT also multiply by an
    appearance probability (that would double-count availability).
    """
    return sum(prob * mean for prob, mean in zip(bin_probs, bin_means, strict=True))


def allocate_team_scale(weights: Mapping[int, float], team_scale: float) -> dict[int, float]:
    """Normalise per-player weights so the rates sum to ``team_scale``.

    Underlying Poisson-rate conservation: ``sum_i rate_i == team_scale``. An empty input returns an
    empty dict; a roster whose weights sum to <= 0 takes equal shares (``team_scale / n`` each), so
    the team total is still conserved. Returns ``{code: rate}``.
    """
    if not weights:
        return {}
    total = math.fsum(weights.values())
    if total <= 0.0:
        share = team_scale / len(weights)
        return dict.fromkeys(weights, share)
    return {code: team_scale * weight / total for code, weight in weights.items()}
