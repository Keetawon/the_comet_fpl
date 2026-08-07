# Composer validation outside GW29-38, and a corrected reading of the goals residual

Read-only development measurement. No contract was loaded, no gate metric scored, nothing
written to `results/`. It is **not** a re-run of `results/ev_backtest_2025_26_gw29_38.json`,
which covers different gameweeks under a pre-registered contract and stays immutable at its
pinned commit `8af5760`.

## Why this was run

Every composer conclusion recorded during the three repairs came from one 99-fixture window,
2025-26 GW29-38, and that window was also where the defects were diagnosed. Three claims needed
a window that had played no part in producing them:

1. the minutes-shrinkage repair puts PIT-80 at the nominal 0.80
2. appearance carries a residual over-prediction of about 2%
3. **goals over-predicting by 13.5% is a low-scoring regime, not miscalibration**

Fresh window: 2025-26 **GW10-28**, 191 fixtures, 14,959 player-fixture rows -- roughly double the
frozen window, same season so no season boundary is crossed, and disjoint from GW29-38.

## Result

| | GW29-38 (diagnosed on) | GW10-28 (fresh) |
|---|---:|---:|
| fixtures / rows | 99 / 8,224 | 191 / 14,959 |
| **PIT-80 coverage** | 0.79985 | **0.79878** |
| CRPS | 0.61934 | 0.66626 |
| mean log score | 1.00370 | 1.06623 |
| EV / actual | 1.07482 | 1.07975 |

PIT deciles on the fresh window: `[10.9 11.4 10.8 9.9 10.3 9.8 9.8 8.8 9.1 9.2]`.

**Claim 1 holds.** PIT-80 lands at 0.7988 against a nominal 0.80 on a window that played no part
in fitting or diagnosing the shrinkage. The calibration repair generalises.

**Claim 2 holds and is now confirmed persistent.** Appearance over-predicts by **+2.6%** here
against +2.0% on GW29-38. It is a real residual in both windows, not a property of the
end-of-season target roster.

**Claim 3 is wrong as recorded, and this is the reason to read the rest of this document.**

## The goals residual is a season-level miss, not a 99-fixture fluke

The Stage A team-goal expectation was measured directly rather than inferred:

| window | fixtures | Stage A `E[goals]` | actual | ratio |
|---|---:|---:|---:|---:|
| GW10-28 | 191 | 2.869 | 2.712 | **1.058** |
| GW29-38 | 99 | 2.849 | 2.576 | **1.106** |

Archive season scoring rates, all 380 fixtures each: 2021-22 **2.729**, 2022-23 **2.732**,
2023-24 **3.147**, 2024-25 **2.845**, 2025-26 **2.645**. Pooled mean 2.820.

Two things follow, and only the first was in the earlier record.

**Stage A's expectation barely moves between the windows -- 2.869 to 2.849, a change of 0.7% --
while reality moves 2.712 to 2.576, a change of 5.0%.** So the earlier reading was right that
GW29-38 was an unusually low-scoring window, and right that a 99-fixture sample must not be
tuned against. But it was wrong to conclude that nothing is miscalibrated. Stage A predicts
about 2.86 goals per fixture all season long, and 2025-26 delivers **2.645 over its full 380
fixtures**. That is not sampling noise: the standard error of a season mean here is about 0.087
goals, so the gap is roughly 2.5 standard errors, and the observed season-to-season spread
(2.645 to 3.147, a range of 0.50) is far wider than that error.

**The correct statement is that Stage A does not track the current season's scoring level.** It
is anchored near the pooled historical mean, so it is systematically high in a low-scoring
season and would be systematically low in a high one. The goals residual is the same defect seen
at two different window scoring rates, which is exactly why it shrank from +13.5% to +7.2% as
the window rate rose from 2.576 to 2.712.

### What this does and does not license

It does **not** license tuning `lambda` down to match 2025-26. That is still the home-advantage
mistake: per-season rates are genuinely volatile, and fitting the level to the season in progress
after seeing it is the same error in a new place.

It does make the open **Stage A team-goals recency / time-decay audit** the next accuracy item on
evidence rather than on a hunch. The question that audit has to answer is narrow and testable:
given N observed fixtures of the current season, how much weight should the league scoring level
put on them against the pooled prior, and is the answer the same for attack and defence? The
appearance layer is the precedent -- an unexamined weighting assumption there was measurably
wrong, and measuring it fixed a real error.

Note the track distinction. `trailing_goals_attack_defence` is the promoted Stage A model under
a pre-registered contract; changing *it* requires a new named candidate and an amendment, and no
such candidate is pre-registered here. Changing how the **prospective composer** consumes a
league scoring level is prospective-track work with no historical gate. An audit is neither and
is free to proceed.

## Component decomposition on the fresh window

| component | model | actual | diff | rel | GW29-38 rel |
|---|---:|---:|---:|---:|---:|
| appearance | 9913.7 | 9664.0 | +249.7 | **+2.6%** | +2.0% |
| goals | 2678.7 | 2498.0 | +180.7 | **+7.2%** | +13.5% |
| assists | 1482.3 | 1449.0 | +33.3 | +2.3% | +8.1% |
| clean sheet | 2584.9 | 2446.0 | +138.9 | **+5.7%** | −0.4% |
| goals-conceded penalty | −964.9 | −920.0 | −44.9 | +4.9% | +20.6% |
| saves | 253.5 | 224.0 | +29.5 | **+13.1%** | +5.5% |
| defensive contribution | 1456.1 | 1514.0 | −57.9 | −3.8% | +1.3% |
| bonus | 1218.3 | 1216.0 | +2.3 | +0.2% | −0.0% |
| **total (modelled)** | **18622.6** | **18091.0** | **+531.6** | **+2.9%** | +2.6% |

The conceded penalty is far better here (+4.9% against +20.6%), consistent with that component
being dominated by the goals level rather than by the exposure repair.

Two entries are new and are leads rather than findings:

- **Clean sheet +5.7%.** About half is downstream of the appearance over-prediction (deflating
  the model by 2.6% still leaves +3.0%). The residual is worth a look at the clean-sheet
  path specifically: the composer awards it from `thinned[0]`, the probability of conceding
  nothing during the player's own on-pitch exposure, which is the right FPL rule but inherits
  binomial thinning's independent-timing assumption. Note this component moved in the *opposite*
  direction between windows (−0.4% on GW29-38), so it is not yet a stable effect.
- **Saves +13.1%** against +5.5% on GW29-38, on 253.5 points. Small in absolute terms and the
  pooled GK save rate is a measured league constant, so the likely path is the conceded level
  feeding it -- the same Stage A level question.

## Aggregate

`EV / actual` is 1.080 here against 1.075 on GW29-38, so the composer runs consistently about 8%
hot on full points. Of that, the component table accounts for +2.9%; the remainder is the
**unmodelled negative components** (cards, own goals, missed penalties), 835 points in this
window, scaling as expected from the 417 measured over GW29-38. They remain deliberately
unmodelled.
