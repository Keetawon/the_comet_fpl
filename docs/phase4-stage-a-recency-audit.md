# Stage A recency / time-decay audit: measured, and the answer is no

Read-only audit. No contract loaded, no gate metric scored, nothing promoted, nothing written to
`results/`. `trailing_goals_attack_defence` is untouched and remains the promoted Stage A model.
This closes an item that had been carried as "measured-but-not-yet-built"; it is closed with a
**negative** result, which is worth recording precisely so it is not re-opened on the same
reasoning.

## The question

The promoted Stage A baseline predicts

```
lambda = mu_venue * attack_team * defence_opponent
```

where `mu_venue` comes from `_venue_means` over the *entire* training window with equal weight.
The Candidate V2 docstring states the property outright: "the baselines weight a match from 2021
exactly like last week's."

`docs/phase4-composer-out-of-window-validation.md` measured the consequence: Stage A expects
about 2.86 goals per fixture in both 2025-26 windows while the season delivers 2.645 over its
full 380 fixtures, roughly 2.5 standard errors below. The question this audit had to answer was
narrow: **given N observed team-matches of the current season, how much weight should the league
scoring level put on them against the pooled prior?**

## What was measured

The fitted model is used unchanged and every rate is rescaled after the fact:

```
w     = N / (N + k)                              N = current-season team-matches already played
scale = ((1 - w) * pooled_level + w * season_to_date_level) / pooled_level
```

Attack/defence ratios, the venue split, and the measured pooled home advantage are all untouched,
so this isolates the level and nothing else. `k -> infinity` reproduces today's model exactly.
`k` was selected on 2021-22..2024-25 by team-match mean log score with 2025-26 held out;
`k = 120` team-matches won, worth **+0.10%** on the training seasons.

## Result 1: at the Stage A grain it is worth nothing

Holdout 2025-26, 760 team-match predictions, `k = 120` frozen:

| | log score | `E[goals]` per fixture | actual |
|---|---:|---:|---:|
| today (no recency) | 1.44686 | 2.868 | 2.750 |
| blended level | 1.44702 | **2.733** | 2.750 |
| | **−0.01%** | | |

**The blend fixes the level almost exactly and the log score does not improve.** The sensitivity
sweep across the whole grid is flat -- from `k = 10` (−0.11%) to `k = 760` (+0.03%) -- so there is
no value of `k` that matters and none that is knife-edge.

This is arithmetic rather than a surprise. A Poisson log score charges roughly `(Δλ)² / 2λ` for a
level error; at `λ ≈ 1.4` per team-match a 4% error costs about 0.001 nats against a score of
1.447, which is the ~0.1% observed. **A level bias is nearly invisible to a proper score at this
grain**, which is also why five seasons of Stage A work never surfaced it.

Per season, same frozen `k`, all five:

| season | n | today | blended | lift | pred today | pred new | actual |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2021-22 | 560 | 1.46969 | 1.46969 | +0.00% | 2.789 | 2.789 | 2.818 |
| 2022-23 | 760 | 1.51859 | 1.51980 | −0.08% | 2.854 | 2.857 | 2.853 |
| 2023-24 | 760 | 1.54835 | 1.54015 | **+0.53%** | 2.886 | 3.054 | 3.279 |
| 2024-25 | 760 | 1.49547 | 1.49657 | −0.07% | 2.947 | 2.924 | 2.934 |
| 2025-26 | 760 | 1.44686 | 1.44702 | −0.01% | 2.868 | 2.733 | 2.750 |

Only 2023-24 gains, and it is the archive's extreme season (3.147 goals per fixture). Four of
five seasons are flat or slightly negative.

## Result 2: at the composer grain it is also worth nothing, and it is not free

The composer's error is a *bias* rather than a likelihood miss, so it was measured there too --
2025-26 GW10-28, 14,959 rows, identical seeds, only the rescaling toggled. Applied scale ranged
0.9422 to 0.9745 (mean 0.9562).

| | today | blended | change |
|---|---:|---:|---:|
| mean log score | 1.06623 | 1.06955 | −0.31% |
| CRPS | 0.66626 | 0.66624 | +0.00% |
| MAE | 1.06892 | 1.06836 | +0.05% |
| PIT-80 | 0.79878 | 0.79865 | −0.00013 |
| EV / actual | 1.07975 | 1.07990 | +0.00015 |

Decisions barely move either: mean per-gameweek top-20 overlap between the two arms is
**19.21 / 20**, and the captain pick is identical in 18 of 19 gameweeks.

The component decomposition shows why the total does not move -- **it is a zero-sum shuffle**:

| component | today | blended | actual |
|---|---:|---:|---:|
| goals | +7.2% | **+2.5%** | 2498.0 |
| assists | +2.3% | −2.2% | 1449.0 |
| clean sheet | +5.7% | **+11.5%** | 2446.0 |
| goals-conceded penalty | +4.9% | −1.5% | −920.0 |
| saves | +13.1% | +5.9% | 224.0 |
| **total (modelled)** | **+2.9%** | **+3.0%** | 18091.0 |

Lowering the team goal level improves goals, the conceded penalty and saves, and breaks the clean
sheet by the same amount, because fewer predicted goals mean more predicted clean sheets. **The
league scoring level is not a free parameter the composer can be tuned on.**

## Conclusion

Do not build a recency or time-decay correction for the Stage A league level. It is measurably
worth nothing on three independent measurements -- team-grain log score, composer distribution
metrics, and composer decisions -- and it actively worsens the clean-sheet component.

The finding that Stage A does not track the season's scoring level stands and stays recorded; what
this audit removes is the inference that acting on it would help.

## What the audit surfaced instead

**The composer's bias is positional, not global.** EV against actual over the same window, with
the unmodelled negative components added back so the comparison is like for like (cards, own
goals and missed penalties are held at zero by design, and they fall unevenly: DEF −376, MID −381,
FWD −79, GK +1 over this window):

| position | model EV | actual | actual + unmodelled negatives | bias |
|---|---:|---:|---:|---:|
| GK | 1342.4 | 1267 | 1266 | **+6.0%** |
| DEF | 6693.2 | 5981 | 6357 | **+5.3%** |
| MID | 8490.9 | 7916 | 8297 | +2.3% |
| FWD | 2105.6 | 2092 | 2171 | **−3.0%** |

The composer over-values goalkeepers and defenders by 5-6% and slightly under-values forwards.
That tilts every squad the optimiser builds toward defenders, and unlike the aggregate total it is
not something offsetting errors can hide. The level correction makes it **worse** (DEF +5.3% to
+7.1%), which is the same zero-sum shuffle seen above.

GK and DEF are precisely the positions whose points come from clean sheets, and the clean sheet is
the component over-predicting by +5.7%. The positional bias and the clean-sheet over-prediction
are one finding, not two.

### A measured directional defect in the clean-sheet path

Archive semantics were verified exact first: over 2025-26 GK/DEF rows, `clean_sheets = 1` holds
for 1,015 rows and coincides with `minutes >= 60 AND goals_conceded = 0` with **zero** mismatches
in either direction, so the archive already records the on-pitch rule FPL applies.

Realised clean-sheet rates by minutes bin, 2025-26 GK/DEF appearances:

| bin | rows | realised `P(clean sheet)` | mean goals conceded |
|---|---:|---:|---:|
| 60-89 | 521 | **0.2495** | 1.215 |
| 90 | 3,262 | **0.2713** | 1.336 |

**Reality gives a 60-89 minute player a *lower* clean-sheet probability than a 90-minute one.**
The composer awards the clean sheet from `thinned[0]`, the probability of conceding nothing during
the player's own exposure, and binomial thinning at an exposure of 0.813 necessarily produces the
**opposite** ordering. The direction is wrong, on 14% of GK/DEF appearing rows.

This is not a contradiction of the conceded-exposure repair, which remains correct on the quantity
it was measured against: predicted mean penalty 0.417 against an actual 0.412 for bin 2, 0.479
against 0.485 for bin 3. Thinning gets the conceded *mean* right and the probability of *zero*
wrong, which is a distributional-shape problem, and the population is selected -- a player
withdrawn between 60 and 89 minutes is disproportionately one whose match was going badly.

That is the next accuracy item on evidence. It is bounded, it is decision-relevant through the
positional bias, and it has a measured target to hit.
