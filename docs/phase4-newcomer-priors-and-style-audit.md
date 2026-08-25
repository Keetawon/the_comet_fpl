# Newcomer priors, multi-season blending, and an opponent-style audit

Status: **development measurement**. Record:
`results/newcomer_priors_and_style_audit_development.json`. One of the four investigations
shipped (the price prior); the other three are **negative results, recorded so they are not
re-opened without new evidence**. No frozen evaluation was re-run and no component default
changed.

Throughout, a *newcomer* is a player with no archive row in either of the two seasons preceding
the one being predicted, and the target is his appearance rate over a season's first five
observed gameweeks. Identity is `code`; club is resolved from fact rows through `team_code`.

## 1. A season t-2 term does not help appearance — but it does help rates

The proposal was `0.2 * stat(t-2) + 0.3 * stat(t-1) + 0.5 * last-5`. Measured within position,
the partial correlation of t-2 given t-1 for the appearance rate is:

| position | n | partial |
|---|---|---|
| GK | 114 | **+0.268** |
| MID | 486 | +0.083 |
| DEF | 369 | −0.020 |
| FWD | 103 | −0.083 |

Out of sample, rotating the held-out season triple, the proposal loses to the shipped blend in
every position group:

| scheme | MAE |
|---|---|
| shipped `0 / 0.7 / 0.3` | **0.2503** |
| `0.1 / 0.5 / 0.4` | 0.2519 |
| proposed `0.2 / 0.3 / 0.5` | 0.2560 |
| t-1 only | 0.2591 |
| last-5 only | 0.2628 |
| OLS, weights fitted out of sample | 0.2780 |

Two things are worth keeping. **The larger error is the 0.5 on the last-five window, not the 0.2
on t-2** — fitted last-five weights run 0.148 to 0.432, and the repository already measures
0.7 long / 0.3 recent as optimal at a season boundary. And **a fitted four-parameter model is the
worst of the six in every group**, so these weights should not be fitted at all; a principled
fixed prior generalises better than a regression on three season-triples.

For per-90 **rates** the answer flips. On the single triple where xG is complete
(2023-24 → 2025-26), the partial correlation of t-2 given t-1 is +0.268 (DEF) and +0.411 (MID)
for xG/90, and +0.233 / +0.205 for xA/90, and `0.2 * t-2 + 0.8 * t-1` beats t-1 alone
(xG/90 0.0492 → 0.0468; xA/90 0.0342 → 0.0336). This is one triple and in-sample, so it is
indicative only — but it points at the right split: **blend across seasons for the rate, keep
the minutes estimate on recent evidence**, which is what the repository's own rule about keeping
the minutes model separate from per-minute rate models already asks for.

Do not read the pooled `ALL` row of that table: it reads 0.864, reproducing the documented
pooled-across-position artefact of 0.871.

### The injury-return cohort: the instinct is right, the fix is not

Defining the cohort as appearance ≥ 0.70 in t-2 and ≤ 0.30 in t-1 gives **32 players, about 11
per season, 3.0% of the population**; 26 of the 32 stayed at the same club, so the trailing-
eligibility rule does not block them.

**The current model does under-rate them, significantly**: signed bias −0.149 (se 0.050,
t = −2.98). But what they actually do next is a mixture:

| outcome in season t | n | share |
|---|---|---|
| barely played (< 0.1) | 15 | **46.9%** |
| some (0.1–0.5) | 9 | 28.1% |
| regular (0.5–0.8) | 5 | 15.6% |
| nailed (≥ 0.8) | 3 | **9.4%** |

and on this cohort more t-2 weight is monotonically **worse**: last-5 alone 0.2172, shipped
0.2306, proposed 0.2412, a heavier `0.35/0.45/0.20` 0.2718. Two-season-old statistics cannot say
which branch a given player is on; current availability can, and that belongs in the overlay.

## 2. A club's positional median adds nothing for newcomers

| base | ALL | GK | DEF | MID | FWD |
|---|---|---|---|---|---|
| league mean, all players | 0.3877 | 0.3161 | **0.3918** | 0.4067 | 0.3905 |
| newcomer base by position | 0.3823 | 0.2675 | 0.3978 | **0.4046** | 0.3898 |
| club positional median | **0.3808** | **0.2480** | 0.3968 | 0.4074 | 0.3910 |

Paired where a club median exists (254 of 473 newcomers — **only 54% coverage**), club median
minus newcomer base is −0.0029 (se 0.0108, **t = −0.27**). The apparent goalkeeper gain is a
level correction, not club information: a position-level newcomer base rate captures nearly all
of it. Publishing a club-median *share* would also dilute every teammate, because the composer
conserves the team rate.

## 3. Launch price is the real newcomer signal — shipped

Measured on the live GW1 run, 120 of 599 roster players were cold starts and their within-club,
within-position ordering was **Monte-Carlo noise**: twelve zero-history midfielders at one club
spanned 1.349 to 1.508 expected points with prices 4.5m and 5.0m interleaved through the
ordering. Expected points *do* vary by opponent (zero-history defenders span 0.822 to 1.868
across clubs, because Stage A is opponent-aware); it is only the ordering among a club's own
newcomers that carries no information.

Price does carry information — correlation with appearance is 0.619 (GK), 0.508 (MID), 0.473
(FWD), 0.250 (DEF) — and the band table is monotone from 0.180 at 4.0-4.5m to 0.787 at
6.0-6.5m. **All 35 newcomer goalkeepers priced at or below 4.0m appeared 0.000 of the time**,
against 0.393 above 4.0m.

Held out on 181 unseen 2025-26 newcomers, against the constants it replaces: MAE
0.3835 → 0.3086 (−19.5%), paired difference −0.0749 (se 0.0134, **t = −5.57**). Implementation,
fitted coefficients and the defender weakness are documented in
`src/fpl/models/price_starter_prior.py`.

## 4. Opponent style adds nothing beyond opponent strength — do not build it

The setup was made deliberately generous: style indices were built from the **full season**
(hindsight) and scored **in-sample**. A signal that cannot survive that cannot survive a
point-in-time build.

At team grain, over 3,040 team-match rows, the residual of a multiplicative strength model
against every style variable:

| variable | r | t |
|---|---|---|
| opponent control | +0.0132 | +0.73 |
| opponent directness | +0.0043 | +0.24 |
| own control | −0.0148 | −0.82 |
| style × style interaction | +0.0124 | +0.68 |
| directness × control | −0.0113 | −0.63 |

Nothing is distinguishable from zero, and this table shows why:

| opponent tercile | actual goals | residual |
|---|---|---|
| lets you shoot (absorbing) | **1.808** | −0.0252 |
| middle | 1.469 | +0.0039 |
| controls the game | **1.154** | +0.0111 |

The raw spread is enormous and **the strength model already absorbs all of it**. Style and
strength are collinear — good teams control, weak teams absorb — so once you know how good a
defence is, knowing *how* it is good adds nothing.

At player grain, split-half reliability of "this player suits that style of opponent" (his
xG+xA per 90 against absorbing minus controlling opponents, odd matches versus even):

| position | n | split-half r |
|---|---|---|
| DEF | 377 | 0.016 |
| MID | 457 | 0.053 |
| FWD | 95 | 0.198 |

against benchmarks of 0.44 for card-proneness and 0.784 for defender xA across seasons. The
pooled `ALL` row reads 0.134 and **must be ignored** — it is the same pooled-across-position
artefact again.

If this is ever re-opened, the data is not in the archive: `mart_fact_team_match` carries goals,
`team_xg`, `team_xgc`, `team_bps` and `fdr` only, with no possession, passes or shot counts.
FBref through the existing operator-pull recipe (`docs/phase3-stage-c-fbref-recipe.md`) is the
established route, and its column mapping is unverified until the 2025-26 overlap gate passes.
Run the kill-test above on the new feed **before** wiring anything into the model.

## 5. What the price prior did to GW1

Both forecasts were generated at `as_of 2026-08-21T17:30:00Z` on the same database; the
pre-change run came from checking out the parent commit.

Accuracy on the 359 rows of the six completed fixtures improves on every metric:

| | EV/actual | MAE | log score | CRPS |
|---|---|---|---|---|
| before | 0.964 | 1.7720 | 1.7767 | 1.1796 |
| after | **0.969** | **1.7294** | **1.7318** | **1.1440** |

(Same rows, same column order and same precision as the table in section 6, which adds the cap
on top of this "after".)

On the 73 zero-history rows MAE falls 1.894 → 1.815 (−4.2%). Ranking is stable where it should
be: Spearman 0.9444 overall, top-10 9/10, top-20 18/20, top-50 47/50. Players with eligible
history move only slightly (379 of 479, median 0.0085, at most 0.2685) through share
normalisation and the joint per-fixture bonus simulation.

**The optimizer's squad changes: 2 of 15.** Out go Donnarumma (5.5m GK, 8.6% owned) and Thiaw
(5.0m DEF); in come Rulli (5.0m GK, **0.0% owned, no PL history**) and Pedro Porro. GW1 expected
points 64.827 → 64.979; horizon 322.950 → 321.092.

### The risk that change exposes

**The prior is absolute, not club-relative.** Rulli at 5.0m reaches the 0.85 cap and outscores
his own club's 5.5m incumbent (4.83 against 3.82) despite 0.0% ownership — a mid-priced newcomer
sitting behind a dearer first choice is over-rated, and this inversion is what drove the squad
change. Counted systematically, 47 cheaper cold starts now outrank a dearer teammate in the same
position; **38 of those already did before the change, so 9 are new**.

Rulli's GW1 outcome cannot be checked here: Manchester City play in fixture 8, which had not
kicked off when the last committed snapshot was captured.

Ownership (`selected_by_percent`) is loaded and unused, and would rank two keepers at one club.
That is a modelling change needing its own validation window, so it is recorded here rather than
patched in on the strength of one squad diff.

## 6. Closing the club-relative blind spot without fitting anything

An absolute price is read on its own scale, so it cannot see who is already at the club.
Splitting the same 473 newcomers by whether their club fields an established same-position
incumbent (prior-season appearance ≥ 0.70), and whether the newcomer is priced above or below
him:

| newcomer vs incumbent | n | appears | prior said |
|---|---|---|---|
| priced above him | 25 | 0.863 | 0.699 |
| priced the same | 75 | 0.508 | 0.513 |
| **priced below him** | 201 | **0.284** | 0.382 |

The middle row is nearly exact and the outer two are compressed toward it. The bottom row is
the damaging one, and it is not noise: **0.284** over 201 historical rows and **0.283** over the
98 of them in 2025-26, two windows agreeing to a thousandth.

`BEHIND_INCUMBENT_CAP` caps exactly that group at the rate it was measured at. It only ever
lowers a value, adds no fitted parameter, and consumes no validation window.

### What it did

The motivating case is resolved: Rulli (5.0m goalkeeper, 0.0% owned, no PL history) read 1.380
before any prior, **4.825** under the price prior, and **1.587** with the cap — now below his own
club's incumbent Donnarumma at 3.822. Club-internal inversions fall from 47 to 29, and of the
**9 newly created by the price prior only 1 survives**. 84 of 120 cold starts are lowered.

| | EV/actual | MAE | log score | CRPS |
|---|---|---|---|---|
| no prior | 0.964 | 1.7720 | 1.7767 | 1.1796 |
| price prior | 0.969 | 1.7294 | **1.7318** | **1.1440** |
| price + cap | 0.952 | **1.7236** | 1.7451 | 1.1536 |

**This is a trade, not a clean win.** The cap wins MAE overall and on the 90-row cold-start
subset (1.8096 → 1.7764), and loses slightly on mean log score and CRPS. Capping at a group
*mean* truncates the upper half of that group, which also deepens the existing under-prediction
of cold starts (EV 109.48 → 96.84 against an actual 151). Both variants beat no prior on every
metric. On 359 rows over six fixtures none of these differences is individually significant —
the actual total alone carries an 8.9% standard error — so this is a **decision-safety choice,
not a measured accuracy win**: what it removes is a squad selection driven by a 0%-owned
newcomer, which matters more here than a third decimal of log score.

## 7. Ownership: measured, deliberately not built

The sharper fix is ownership, and the evidence for the mechanism is strong. Splitting expensive
newcomers by whether the crowd picks them:

| | historical | live 2026/27 GW1 |
|---|---|---|
| expensive, widely selected | 0.760 (n=89) | 0.846 (n=13) |
| expensive, ignored | 0.438 (n=101) | 0.316 (n=19) |
| difference | **+0.322** (t=5.93) | **+0.530** (t=3.63) |

Prices are near-identical between the two high-price groups (5.75m against 5.22m), so this is
not price in disguise, and ownership separates at the cheap end too (0.354 against 0.138).

It is not built, for three reasons:

1. **The live window has been spent.** Three encodings were tried against 2026/27 GW1 —
   log-odds floored at 0.001% (+18.0%, t = −4.97, but a cliff at the 0.0/0.1% rounding
   boundary), floored at 0.05% (+14.9%, t = −3.85, but the goalkeeper correction vanishes), and
   a within-position percentile (+10.8%, t = −4.77, stable). Iterating like that biases all
   three figures upward.
2. **Goalkeepers cannot express it.** On 39 training rows where price already separates almost
   perfectly, the ownership term is inert in every encoding — so the case that motivated the
   work is the one it cannot fix.
3. **The additive three-feature form failed the strict test**: t = −1.59 on the 2025-26 holdout,
   regressing in three of four positions.

The confirmation window is **2026/27 GW2 onward**, untouched by any fit or holdout here. Fit
once on history, score once there, and do not iterate on the encoding again.

## 8. Consuming a distribution downstream: two facts worth having before anyone builds

These came out of designing a player-selection view and are recorded because they constrain any
consumer of the forecast artifact, not just that view.

**Expected points are summable across gameweeks. Probabilities are not.** A gameweek row is
already the convolution over that gameweek's fixtures — a double gameweek convolves both, a blank
is the exact point mass `(1.0,)` — so summing `expected_points` over any horizon is exact and
needs no special case. Summing a probability is not. Measured on one player over GW1-3:

| | value |
|---|---|
| `P(>= 6 points)`, convolved correctly | **0.9033** |
| the same by adding the three per-gameweek values | **1.0585** |
| `xP`, summed directly | 13.3475 (correct) |

The naive figure is 17% high **and above 1.0**, which a probability cannot be. The existing
`player_xp` per-gameweek map (P1.7d) lets a consumer sum for a 1/3/5-gameweek selector; that
pattern does not extend to any probability, which must be precomputed from the convolved
distribution per horizon.

**There is no performance problem here, so do not design around one.** Convolving all 599 players
over five cumulative horizons takes **0.16 s** in pure Python; `numpy` is not a dependency of this
project and adding one for this would not be justified. The effective support is smaller than it
looks — 171 slots at a five-gameweek horizon, but 99.999% of the mass sits below 86 — so the work
could be halved by truncating, and it is not worth doing at 0.16 s. A precomputed payload of 599
players × 5 horizons × 7 values is 305 KB of JSON, about 76 KB gzipped, against 819 KB for
shipping the raw distributions. The real cost in this pipeline is the Monte-Carlo forecast itself
(~2 minutes for a GW1-5 vintage), which runs once per vintage.
