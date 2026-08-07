# Stage D composer: the trailing-five minutes estimate was a raw count, and it was over-confident

Status: **fixed forward**. This is a correctness repair to development-only prospective tooling.
It is not a candidate, not a promotion, and not a re-judgement of any frozen evaluation. It is
on the prospective track that `AGENTS.md` describes as carrying no historical gate: measured
first, wired second.

## The defect

`fpl.jobs.prospective_points_v1.trailing5_minute_bins` returned the maximum-likelihood estimate

```
distribution[bin] = count[bin] / n,   n <= 5
```

over a player's five most recent rows. That estimate can take only six values per marginal --
`0, 0.2, 0.4, 0.6, 0.8, 1.0` -- and five Bernoulli trials do not support that confidence.
Measured over 101,306 point-in-time archive rows from 2021-22 to 2024-25:

| raw `k/5` | rows | realised `P(play)` | realised `P(60+)` | realised `P(90)` |
|---|---:|---:|---:|---:|
| 0.0 | 43,139 | 0.039 | 0.036 | 0.031 |
| 0.2 | 7,605 | 0.310 | 0.279 | 0.247 |
| 0.4 | 7,141 | 0.459 | 0.419 | 0.384 |
| 0.6 | 8,069 | 0.588 | 0.543 | 0.516 |
| 0.8 | 11,093 | 0.736 | 0.695 | 0.659 |
| 1.0 | 24,259 | **0.897** | **0.869** | **0.849** |

The composer draws a minutes bin and scores a bin-0 draw as exactly zero points, so this
propagates into every component:

- `P(play) = 1.000` gives a nailed starter a distribution with **no lower tail**. When he blanks
  or is rested -- 10.3% of the time -- the outcome is outside the support the model offered.
- `P(play) = 0.000` gives a fringe player **no upper tail**, on 43,139 rows, 3.9% of which
  featured.

That is the composer's under-dispersion. On the GW29-38 rows, PIT-80 coverage was 0.7454 against
a nominal 0.80, and it split exactly where this predicts: the EV 3-4 bucket put **25.7%** of rows
in the bottom PIT decile against a nominal 10%, and the EV < 1 bucket predicted a mean of 0.096
against an actual 0.187.

## The repair

`fpl.models.minutes_shrinkage.shrink_minute_bins` replaces the raw count with a
Dirichlet-multinomial posterior mean, in two regimes.

### Why two regimes

For `k >= 1` the realised rate is close to linear in `k`, which is what a single Dirichlet
posterior produces. Extrapolating that line to `k = 0` predicts about 0.16. The measured value is
**0.039**, over four times smaller, on the single largest group of rows in the population. A
player who has appeared in none of his last five is not a low draw from the same distribution --
he is injured, suspended, or out of the side, and that state persists. So a zero-appearance
window takes a separately measured `out_of_side_profile` instead of being shrunk toward the
in-squad prior.

### Why the prior is the in-squad population, not the pooled one

This was wrong in the first cut of the repair and the measurement caught it. Once the
zero-appearance windows are given their own regime, the population the shrinkage regime
describes is a different one: pooled bin-0 frequency is **0.594**, in-squad **0.304**. Shrinking
in-squad players toward the pooled figure drags them toward absences that have already been
removed. Measured on the holdout it under-predicted appearance in *every* reliability bucket by
6 to 10 percentage points; with the in-squad prior the worst bucket error is 0.087 and the
largest bucket (6,786 rows) lands at 0.892 predicted against 0.897 realised.

### Point in time

Both priors are built inside the same function from the same `kickoff_time < as_of` history,
per position, with a pooled fallback below `MINUTES_SHRINKAGE_MIN_PRIOR_ROWS = 500` rows.
Goalkeepers are why the prior is positional at all -- their bin profile
(0.741, 0.005, 0.001, 0.253) is nothing like an outfielder's, because they almost never play a
partial match. A player's position is read from his own most recent historical row rather than
from `mart_dim_player`, which records only where a player finished a season.

`alpha = 0.0` returns the raw `counts / n` exactly, both regimes included. It is the
reproducibility escape hatch, not a tuning value.

## Selecting alpha

`MINUTES_SHRINKAGE_ALPHA = 3.5`, selected by four-bin log loss on **2021-22..2024-25 only**
(104,354 point-in-time rows), over a grid of 0.25 to 12.0 in steps of 0.25. **2025-26 was held
out and was not consulted during selection.** The optimum is interior to the grid and the
neighbourhood is flat (3.00: 0.70328, 3.25: 0.70298, **3.50: 0.70294**, 3.75: 0.70311,
4.00: 0.70345), so the value is not knife-edge.

Alpha has not been re-tuned against any figure below. It was fixed before they were measured and
it stays fixed.

## Held out: the estimator alone

2025-26, 29,036 rows, `alpha = 3.5` frozen:

| | raw `counts/n` | shrunk | change |
|---|---:|---:|---:|
| four-bin log loss | 1.62706 | 0.65142 | +59.96% |
| Brier, `P(play)` | 0.10603 | 0.10179 | **+4.00%** |
| Brier, `P(60+)` | 0.10395 | 0.09840 | **+5.34%** |
| AUC, `P(60+)` | 0.90298 | 0.92266 | **+2.18%** |
| AUC, `P(play)` | 0.92020 | 0.92216 | +0.21% |

The log-loss figure is inflated by the floor applied to zero-probability outcomes and should not
be quoted as a magnitude; it is the bounded scores that carry the result.

Every one of the five seasons improves on both log loss and AUC:

| season | rows | raw log | shrunk log | raw AUC | shrunk AUC |
|---|---:|---:|---:|---:|---:|
| 2021-22 | 23,238 | 1.83598 | 0.71450 | 0.89004 | 0.90476 |
| 2022-23 | 25,580 | 1.74383 | 0.71681 | 0.90266 | 0.91691 |
| 2023-24 | 28,852 | 1.67520 | 0.66879 | 0.90475 | 0.92351 |
| 2024-25 | 26,684 | 1.76250 | 0.71651 | 0.90056 | 0.91608 |
| 2025-26 | 29,036 | 1.62706 | 0.65142 | 0.90298 | 0.92266 |

### This is not the Stage B shrinkage failure

Stage B Candidates V1, V2 and V3 each improved every proper score and each failed the
starter-ranking gate. Shrinkage is exactly the move that did it, so it was checked directly.

**Per-gameweek within-position AUC on `P(60+)`: 0.90886 to 0.91815, +1.02%, better in 123 of 152
gameweek-position groups.** Ranking improves rather than degrades, for two structural reasons:

1. For a fixed window size the posterior mean is a **strictly increasing function of the observed
   count**, so it cannot reorder players within a position. `test_shrinkage_is_order_preserving_within_a_window_size`
   pins this.
2. The raw estimator **ties** every pure-absence window and every substitute-only window together
   at `P(60+) = 0`. Those groups are not alike: measured over 2025-26 they go on to play 60+
   minutes **0.9%** and **13.4%** of the time respectively -- a fifteen-fold difference collapsed
   into one tie block of 17,069 rows. Separating them is a resolution gain.

An earlier draft of this measurement reported a 10.9% *loss* using an average-rank Spearman. That
figure was an artifact of tie handling in the diagnostic, not a property of the estimator; AUC is
the appropriate measure for a binary outcome and it rises.

## End to end through the composer

GW29-38, 8,224 identical rows, identical seeds, draws, folds and architecture, only `alpha`
toggled. This is a development measurement of a forward repair, **not** a re-run of
`results/ev_backtest_2025_26_gw29_38.json`, which stays immutable and reproduces only at its
pinned commit `8af5760`.

| | raw (`alpha=0`) | shrunk (3.5) | change |
|---|---:|---:|---:|
| mean log score | 2.07354 | 1.00370 | **+51.59%** |
| CRPS | 0.63496 | 0.61934 | **+2.46%** |
| PIT-80 coverage | 0.74538 | **0.79985** | nominal is 0.80 |
| \|PIT-80 − 0.80\| | 0.0546 | **0.0001** | |
| MAE | 0.95715 | 0.99286 | **−3.73%** |
| EV / actual | 1.06002 | 1.07482 | −0.0148 |

PIT-80 by position moves from 0.735-0.781 to 0.804-0.812, and the decile histogram flattens from
`[14.0 9.4 9.4 8.8 9.2 8.6 9.4 9.6 10.1 11.5]` to
`[11.0 10.7 10.2 9.9 10.4 9.8 9.6 9.9 9.5 9.0]`. The EV 3-4 bucket's bottom decile falls from
25.7% to 8.7% and its mean prediction moves from 3.459-against-3.098 to 3.400-against-3.449.

### MAE gets worse, and that is the expected trade

MAE is a **point**-forecast metric and it rewards exactly the behaviour being removed. On the
5,232 rows where the player did not feature, a raw `P(play) = 0` scores a perfect zero absolute
error, and on the 3.9% where he did feature it is charged only the points he scored. A calibrated
distribution must hedge those rows and pays MAE for it.

CRPS is the distributional generalisation of MAE, it is proper, and it **improves by 2.46%** on
the same rows. For a project whose stated output is a full points distribution, CRPS and PIT are
the metrics that bind and MAE is the one that does not. It is reported here rather than omitted.

### Component decomposition

| component | before | after | actual |
|---|---:|---:|---:|
| appearance | 5033.9 (+0.1%) | 5130.6 (+2.0%) | 5031.0 |
| goals | 1366.6 (+12.8%) | 1375.3 (+13.5%) | 1212.0 |
| assists | 765.0 (+8.1%) | 765.0 (+8.1%) | 708.0 |
| clean sheet | 1309.2 (−2.4%) | **1335.1 (−0.4%)** | 1341.0 |
| goals-conceded penalty | −479.1 (+18.0%) | −489.5 (+20.6%) | −406.0 |
| saves | 128.8 (+0.6%) | 135.1 (+5.5%) | 128.0 |
| defensive contribution | 731.2 (+0.7%) | 735.6 (+1.3%) | 726.0 |
| bonus | 631.7 (−0.0%) | 631.8 (−0.0%) | 632.0 |
| **total (modelled)** | 9487.4 (+1.2%) | 9619.1 (+2.6%) | 9372.0 |

Clean sheets are now accurate to −0.4%. Appearance moves to +2.0%: the shrunk estimator carries a
residual over-prediction of about 3 percentage points on the target-roster population, consistent
with the reliability curve's +0.03 mid-bucket error. It is **not** corrected here, because alpha
was selected on 2021-22..2024-25 and re-tuning it against GW29-38 would be fitting the estimator
to the window it is being judged on -- the mistake `AGENTS.md` records for home advantage.

The aggregate total moves from +1.2% to +2.6%. As with both earlier composer repairs, the
aggregate is not the target: it was near zero only because component errors offset, and the
dominant remaining term is the goals regime effect (GW29-38 ran at 2.576 goals per fixture, the
lowest window in the archive, roughly 1.9 standard errors below the pooled mean on 99 fixtures),
which must not be tuned away.

## What is left, in size order

1. **Unmodelled negative components: 417 points (4.7% of actual full points).** Measured: yellow
   cards 374, red 30, own goals 14, missed penalties 4, penalties saved +5. Cards are 90% of it
   and are not rare -- a booking-prone player picks one up every 2.3 appearances, and the rate
   persists (split-half correlation 0.44 within 2025-26). Deliberately left unmodelled: the mean
   effect is −0.051 points per row, and the spread over a five-gameweek horizon between the most
   and least booked nailed starter is about 1.6 points, small against the residual elsewhere.
2. **Goals +13.5% / assists +8.1%: regime, ~1.9 standard errors on a 99-fixture window.** Do not
   tune. If it needs an answer, the answer is a longer evaluation window, not a smaller `lambda`.
3. **Appearance +2.0% on the target-roster population.** Needs a fresh out-of-sample window to
   act on, not a re-tune of alpha against GW29-38.
4. **Bin-1 conceded exposure understates by 20%** because binomial thinning cannot express a
   substitute arriving into a collapse.
