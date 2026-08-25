"""Price-informed appearance prior for players with no eligible Premier League history.

A player the trailing-history rule cannot see gets a constant per position -- GK 0.2496,
DEF 0.4089, MID 0.4387, FWD 0.4216 -- so every newcomer at a club reads the same. Measured on
the first live 2026/27 GW1 run that is exactly what happens: 100 of 599 roster players had no
archive row at all, and the twelve zero-history midfielders of one club came out at 1.349 to
1.508 expected points with **no relation to anything**, prices 4.5m and 5.0m interleaved
through the ordering. That spread is Monte-Carlo noise from each player's own draw stream, not
information, so sorting newcomers by expected points sorts noise.

The launch price is not noise. Measured over 473 newcomers in 2023-24..2025-26 -- a newcomer
being a player with no archive row in either of the two preceding seasons -- the correlation
between launch price and the appearance rate over his first five gameweeks is:

==========  =============
position    correlation
==========  =============
GK          0.619
MID         0.508
FWD         0.473
DEF         0.250
==========  =============

and the pooled ladder is monotone: 4.0-4.5m appears 0.180 of the time (n=115), 4.5-5.0m 0.301
(n=168), 5.0-5.5m 0.488 (n=99), 5.5-6.0m 0.654 (n=52), 6.0-6.5m 0.787 (n=16). This is the
"price-informed starter prior" the roadmap has carried as measured-but-not-built.

Goalkeepers are the sharpest case and the reason the documented reserve-dominated GK prior is
wrong in both directions at once. Of 35 newcomer goalkeepers priced at or below 4.0m, **every
single one** finished with an appearance rate of 0.000; above 4.0m the mean is 0.393. A single
constant of 0.2496 is far too high for the backup who will never play and far too low for the
signed first choice, and no live field separates them. Price does.

Why a capped logistic rather than a line
----------------------------------------

The relationship is bounded at both ends, so a linear fit leaves the support. It also separates
perfectly for goalkeepers, and an unpenalised logistic answers that by driving the slope to a
step function -- fitted without a penalty the GK slope reaches 3.87, predicting 0.000 at 4.0m
and 1.000 at 5.0m. That is precisely the over-confidence :mod:`fpl.models.minutes_shrinkage`
exists to remove; a probability of 1.000 is not supported by 39 training rows any more than it
is by five Bernoulli trials.

So the slope carries an L2 penalty and the output is capped. Both ends of the cap are anchored
on constants already measured in this repository: a proven ever-present with a full trailing-five
window predicts appearance 0.897, so a newcomer nobody has seen in this league may not be given
more confidence than 0.85; and a player out of the side entirely measures 0.039, which the lower
cap rounds to 0.04.

Fitting and what was held out
-----------------------------

Coefficients are fitted on 2023-24 and 2024-25 newcomers only, with 2025-26 never consulted
during fitting or selection -- the same discipline used for the minutes-shrinkage concentration.
The penalty was chosen by leave-one-season-out cross-validation *inside* the training seasons,
where 0.0 and 0.5 tie at 0.3280 mean absolute error and 0.5 cuts the largest fitted slope from
3.905 to 0.967; the tie is broken on stability.

Scored once against the 181 held-out 2025-26 newcomers, versus the constant position priors
this replaces:

=========  ====  ==============  ==========  ========
position   n     MAE (constant)  MAE (price) change
=========  ====  ==============  ==========  ========
GK         23    0.2932          0.1699      -42.1%
DEF        60    0.3763          0.3755       -0.2%
MID        70    0.4105          0.2956      -28.0%
FWD        28    0.4056          0.3120      -23.1%
ALL        181   0.3835          0.3086      -19.5%
=========  ====  ==============  ==========  ========

Paired over the 181 rows the difference is -0.0749 (se 0.0134, t = -5.57).

**Defenders are the honest weak case and are shipped unchanged anyway.** They gain 0.2%, which
is nothing, and their signed bias worsens from +0.075 to +0.130 -- price over-predicts how much
a newcomer defender plays. Defender launch prices are compressed near the floor, so price
carries least information exactly where the position is most crowded. Dropping defenders after
seeing that number would be selecting a rule on its own test set, so all four positions ship on
the same rule and the weakness is recorded here instead.

The one thing an absolute price cannot see
-----------------------------------------

Price is read on its own scale, so it does not know who else is already at the club. Measured
on the same 473 newcomers, splitting those whose club fields an established same-position
incumbent (prior-season appearance >= 0.70) by whether the newcomer is priced above or below
him:

=========================  ====  =============  ==========
newcomer versus incumbent  n     appearance     prior says
=========================  ====  =============  ==========
priced above him           25    0.863          0.699
priced the same            75    0.508          0.513
priced below him           201   **0.284**      0.382
=========================  ====  =============  ==========

The middle row is almost exact and the outer two are compressed toward it. The bottom row is
the damaging one, and it is not a rounding error: a newcomer behind a dearer established
incumbent appears **0.284** of the time historically and **0.283** on the 2025-26 rows alone --
two windows agreeing to a thousandth -- while the price curve alone hands out up to the 0.85
cap. The live consequence was a 5.0m goalkeeper with no Premier League history and 0.0%
ownership outscoring his own club's 5.5m incumbent, which changed the optimizer's squad.

:data:`BEHIND_INCUMBENT_CAP` therefore caps, and only caps, a cold start in exactly that
position. It never raises anyone, and it is a measured ceiling rather than a fitted parameter,
so it introduces no new degrees of freedom and consumes no validation window.

Ownership would resolve the same case more finely -- an expensive newcomer nobody selects is a
different animal from an expensive newcomer everybody selects, and the gap between those two
groups measures +0.322 historically and +0.530 on live 2026/27 GW1. It is deliberately NOT
built here: three candidate encodings were tried against the live window, which spends it, and
goalkeepers cannot express it at all on 39 training rows where price already separates almost
perfectly. The confirmation window for that work is 2026/27 GW2 onward, untouched.

Scope
-----

This applies only where there is no eligible history at all. A player with any trailing window
keeps the existing estimator untouched, so no frozen evaluation and no validated path changes.
Launch price is a deadline-known bootstrap field, so the prior is point-in-time safe.
"""

from __future__ import annotations

import math

from fpl.types import Position

__all__ = [
    "BEHIND_INCUMBENT_CAP",
    "INCUMBENT_APPEARANCE_THRESHOLD",
    "PRICE_PRIOR_CAP",
    "PRICE_PRIOR_COEFFICIENTS",
    "PRICE_PRIOR_PIVOT",
    "PRICE_PRIOR_RIDGE_LAMBDA",
    "apply_price_starter_prior",
    "price_starter_probability",
]

PRICE_PRIOR_PIVOT = 47.0
"""Price the logistic is centred on, in FPL tenths of a million (4.7m).

The mean newcomer launch price over the 473 measured rows. Centring keeps the intercept
interpretable as "the appearance rate of an average-priced newcomer" and keeps the Newton step
well conditioned. Newcomer prices do not drift across the archive -- the median launch price is
exactly 45 in each of 2023-24, 2024-25 and 2025-26, and the 10th percentile is 40 in all three
-- so a raw price is comparable between seasons and needs no per-season normalisation.
"""

PRICE_PRIOR_RIDGE_LAMBDA = 0.5
"""L2 penalty applied to the slope only, never to the intercept.

Selected by leave-one-season-out cross-validation within the training seasons; see the module
docstring for the tie with 0.0 and why stability breaks it.
"""

PRICE_PRIOR_CAP = (0.04, 0.85)
"""Floor and ceiling on the returned probability.

0.85 sits below the 0.897 that a full trailing-five window is measured to predict, because a
newcomer carries strictly less evidence than a proven ever-present. 0.04 is the measured
out-of-the-side rate of 0.039.
"""

BEHIND_INCUMBENT_CAP = 0.284
"""Ceiling for a cold start priced below an established same-position team-mate.

The measured appearance rate of exactly that group: 0.284 over 201 historical newcomers and
0.283 over the 98 of them in 2025-26. It is a cap, never a floor, so a newcomer the price curve
already rates below it keeps his own lower value.
"""

INCUMBENT_APPEARANCE_THRESHOLD = 0.70
"""Prior-season appearance rate at which a team-mate counts as an established incumbent.

The threshold the group above was measured under. Below it the "incumbent" is not established
enough for his price to say anything about who starts.
"""

PRICE_PRIOR_COEFFICIENTS: dict[Position, tuple[float, float]] = {
    Position.GK: (1.36703, 0.99990),
    Position.DEF: (0.61236, 0.19870),
    Position.MID: (-0.89655, 0.17736),
    Position.FWD: (-0.64023, 0.07122),
}
"""``position -> (intercept, slope)`` for ``sigmoid(a + b * (price - PRICE_PRIOR_PIVOT))``.

Price stays in FPL tenths throughout, so the slope is per 0.1m. Fitted on 2023-24 and
2024-25 newcomers under :data:`PRICE_PRIOR_RIDGE_LAMBDA`; 2025-26 was held out.
"""


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, value))))


def price_starter_probability(
    price: int | None,
    position: Position,
    *,
    behind_established_incumbent: bool = False,
) -> float | None:
    """Appearance probability for a no-history player at ``price`` (FPL tenths of a million).

    ``behind_established_incumbent`` marks a cold start whose club fields a same-position
    team-mate with eligible history, a prior-season appearance rate of at least
    :data:`INCUMBENT_APPEARANCE_THRESHOLD`, and a strictly higher price. Such a player is capped
    at :data:`BEHIND_INCUMBENT_CAP`; the cap only ever lowers the answer.

    Returns ``None`` when the price is missing or not positive, which is the caller's signal to
    keep the existing constant position prior rather than invent one.
    """
    if price is None or price <= 0:
        return None
    coefficients = PRICE_PRIOR_COEFFICIENTS.get(position)
    if coefficients is None:
        return None
    intercept, slope = coefficients
    probability = _sigmoid(intercept + slope * (float(price) - PRICE_PRIOR_PIVOT))
    low, high = PRICE_PRIOR_CAP
    if behind_established_incumbent:
        high = min(high, BEHIND_INCUMBENT_CAP)
    return max(low, min(high, probability))


def apply_price_starter_prior(
    minutes: tuple[float, float, float, float],
    *,
    price: int | None,
    position: Position,
    behind_established_incumbent: bool = False,
) -> tuple[float, float, float, float]:
    """Reshape a four-bin minutes distribution to the price-implied appearance probability.

    The conditional (when-playing) minute shape is preserved: only the split between "did not
    play" and "played" moves, and the freed or added mass is redistributed across the playing
    bins in their own proportions. This mirrors :func:`season_boundary_minutes`, so the two
    corrections compose without either inventing a minute shape.

    Availability is not applied here. It stays the separate reported overlay and is never folded
    into a stored distribution.
    """
    probability = price_starter_probability(
        price, position, behind_established_incumbent=behind_established_incumbent
    )
    if probability is None:
        return minutes
    _, bin1, bin2, bin3 = minutes
    playing = bin1 + bin2 + bin3
    if playing <= 1e-12:
        # No when-playing shape to preserve. Fall back to the same 15/85 split
        # `season_boundary_minutes` uses when it faces the identical situation.
        return (1.0 - probability, 0.0, probability * 0.15, probability * 0.85)
    scale = probability / playing
    return (1.0 - probability, bin1 * scale, bin2 * scale, bin3 * scale)
