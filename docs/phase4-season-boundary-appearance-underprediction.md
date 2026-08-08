# The season boundary under-predicts rested-nailed starters, and the degenerate zero is gone

Read-only investigation, measured on the first live 2026/27 GW1-5 prospective run (`as_of` =
2026-08-21T17:30:00Z, the real GW1 deadline). No contract loaded, no gate metric scored, nothing
promoted, nothing written to `results/`. The minutes-shrinkage estimator
(`models/minutes_shrinkage.py`) and the composer are untouched; this records what they do on the
one regime they were never fitted against -- a cross-summer season boundary.

## Why this window is the first real test

`models/minutes_shrinkage.py` was fitted on 2021-22..2024-25, which contains **no** cross-summer
boundary: every trailing-five window in the fit sits inside a season. The shrinkage `alpha = 3.5`
and the `k = 0` out-of-side profile were both selected there. 2026/27 GW1 is the first time the
composer draws minutes for players whose trailing-five Premier League window straddles the summer
break, so the interaction between the shrinkage floor and the `seasonal` appearance blend had never
been exercised until now.

The mechanism under test: `shrink_minute_bins` routes a window that is **all** zero-minute rows
(`counts[0] >= n`) to the measured out-of-side profile, whose `P(play)` is **0.0369** in August
here (matching the ~0.038 recorded in the fix doc). The prospective `seasonal` path then blends that
base distribution with the prior-season appearance rate as `p_play = 0.7 * prior + 0.3 * recent`
(August long-weight 0.7).

## Result 1: the degenerate zero is eliminated on live data

Over the 570-player 2026/27 roster, **zero** players are predicted a final `P(play)` of exactly
0.0. On the raw `counts / n` estimator the equivalent run produced exactly one. The shrinkage floor
plus the seasonal blend removes the degenerate zero on live cross-summer data, which is the whole
point of the fix. 75 players sit below 0.05, correctly -- they are backup/fringe profiles (e.g.
backup goalkeepers with a prior-season rate near zero blend to ~0.005).

## Result 2: zero-history players route to the position prior, not to "will not play"

The 78 cold-start players (no prior Premier League rows at all) fall back to the Stage B position
prior, constant within a position:

| position | n | final `P(play)` |
|---|---:|---:|
| GK | 9 | 0.2496 |
| DEF | 25 | 0.4089 |
| MID | 33 | 0.4387 |
| FWD | 11 | 0.4216 |

None is 0.0. But the goalkeeper value is a **known under-prediction of a genuine first-choice
keeper**: the GK position prior is dominated by reserves (each club carries two keepers and one
starts), so a promoted-club or newly-signed **#1** with no PL history reads 0.25 when his true
appearance is near-certain. No live field corrects this -- price, ownership and availability are
overlay-only and do not enter the distribution.

## Result 3: the blend rescues rested-nailed starters from the floor, but caps them below true

Of the 147 roster players whose trailing-five window is all zero-minute rows (`counts[0] >= n`),
146 carry a trusted prior-season rate (`prior_n >= 10`). The blend does its job in the gross sense:
it lifts returners well clear of the out-of-side floor (trusted-prior all-zero mean base 0.0367 ->
final 0.1259) while correctly keeping true non-starters low. **No player leaks through
under-predicted at ~0.04 or 0.0** -- the catastrophic form of the trap does not occur.

But it systematically under-predicts the **rested-nailed** subset, because the 0.3 weight lands on
a *contaminated* recent estimate. A player rested through the May dead rubbers has an all-zero
window, so `recent` is the out-of-side floor (~0.037), not his true form. The ceiling for any
all-zero player is therefore `0.7 * prior + 0.3 * 0.037 ≈ 0.7 * prior`:

| player | pos | status | prior rate | base (recent) | final `P(play)` | gap vs prior |
|---|---|---|---:|---:|---:|---:|
| Vicario | GK | a (available) | 0.816 | 0.0179 | 0.576 | −0.24 |
| J. Timber | DEF | a | 0.789 | ~0.037 | 0.567 | −0.22 |
| Hudson-Odoi | MID | a | 0.789 | ~0.037 | 0.564 | −0.22 |
| Ekitike | FWD | a | 0.737 | ~0.037 | 0.526 | −0.21 |
| Murillo / Henry | DEF | a | 0.658 | ~0.037 | 0.475 | −0.18 |

A truly nailed player (prior ~1.0) can reach at most **~0.71** (goalkeepers ~0.635, since the GK
out-of-side recent is lower at 0.018). That is not just below the player's own prior; it is below
the **measured cross-season average** for a nailed-last-season player, which `AGENTS.md` records at
**~0.78** (a player nailed last season at 0.913 appears only 0.776 early next season). So Vicario at
0.576 is ~0.14 below even the honest cross-season expectation, not merely below an over-optimistic
0.9.

The subset is narrow: exactly **one** player clears a `prior >= 0.8` bar (Vicario), plus roughly
six high-appearance returners one tier down. Vicario's live status is `a` (available), so this is a
minutes-model under-prediction, not an injury downgrade -- whether his GW1 start is genuinely at
risk (return from a late-season absence) is exactly what the separate availability overlay exists to
express, and is not decidable from minutes alone.

## Why this is not fixed before GW1

1. **It is bounded and conservative.** The gap is ~0.24 in `P(play)`, it under-predicts rather than
   over-predicts (a returning nailed starter is discounted, not inflated), and it touches ~1-7
   players out of 570 at this deadline.
2. **The 0.7/0.3 blend is measured-optimal on average.** `AGENTS.md` records that cross-season
   appearance is genuinely hard (MAE ~0.22 for every method) and that `0.7 * long + 0.3 * recent`
   is the best measured trade-off. The rested-nailed case is the minority where that average is
   suboptimal; re-weighting it is a modelling change to a fitted blend and needs its own
   validation window, not a pre-deadline tweak.
3. **The overlay is the designated place.** Return-from-rest and return-from-injury signals belong
   in the availability overlay, which is already reported separately and never folded into the
   distribution.

## What this licenses

A named, separately designed change to the season-boundary appearance path: when a trailing window
is all-zero at a boundary, the `recent` term is an *actively wrong* signal (out-of-side) rather than
a merely noisy one, so the blend should either recognise the boundary-rest case or route it through
the availability overlay. That is a future design item with a measured target (lift the rested-nailed
ceiling from ~0.71 toward the ~0.78 cross-season average without inflating genuine non-starters). It
does **not** license re-tuning the shrinkage `alpha` or the 0.7/0.3 blend on this window.
