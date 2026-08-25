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

| | MAE | log score | CRPS | EV/actual |
|---|---|---|---|---|
| before | 1.772 | 1.777 | 1.180 | 0.964 |
| after | **1.729** | **1.732** | **1.144** | **0.969** |

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
