# Role / exposure opportunity: two separate development candidates

Fixed algorithm before any real opportunity fit or scoring:

- `retrospective_role_exposure_player_goals_v1`: archive `expected_goals`, scored on recorded player goals.
- `retrospective_role_exposure_player_assists_v1`: archive `expected_assists`, scored on recorded FPL assists.

They share pure mechanics, not a candidate identity, claim, outcome or formal run.
Evidence class: `retrospective_role_and_archive_price_proxy_development`.
This is neither a production replacement nor historical deadline-known evidence.
Final config, population/provenance pins and the separate once-only runners must be
committed cleanly before scoring. No result or next-stage license is implied here.

## Research question and exact control

Does a small league-to-soft-role-to-player opportunity hierarchy, multiplied once by
predicted exposure, improve the CURRENT coupled goals or assists marginal on the same
player-fixture population?

Control is `retrospective_current_component_proxy_v1`, with minutes from the retained
`retrospective_current_minutes_proxy_v1` cache. Never substitute old Stage C V4/V2
result numbers: they used different minutes and comparators. Never substitute the
Phase D minutes challenger unless that separate full gate has passed. The unchanged
team PMFs/goal scale come from the current `TrailingGoalsAttackDefence` path. Assists
retain the exact current fold-local `league_assist_rate`; not a constant 0.75.

No team strength, goal distribution family, current minutes probability, price rule,
optimizer input or prospective default changes. No tactical feature, player identity
coefficient, venue correction, finishing parameter, new dependency or grid is added.

## Fixed formulas

For each component separately, pool appeared, measured prior archive signal/exposure.
`s` is xG or xA, and `m` is observed FPL minutes; no provider nominal-duration
reconstruction replaces those minutes. NULL signal contributes neither `s` nor `m`.

`league_rate = sum(s) / sum(m)`.

Preserve the exact existing `_trailing_row_eligible` rule: a row qualifies when it is
in the latest observed archive season (at any club), OR is an older row at the current
stable club. It is **not** silently narrowed to current-club-only history. The frontier
is computed from prior events only. The same appeared eligible population supplies the
league prior; all prior measured minutes supply fold-local bin means.

For each of four broad role covariates `r`, use only earlier sequentially OOS role
forecasts `p_j[r]` made at historical row `j`'s own pre-GW cutoff:

`soft_role_rate[r] = (sum_j(p_j[r] * s_j) + 900 * league_rate)`

`                    / (sum_j(p_j[r] * m_j) + 900)`.

The fixed 900-minute prior is ten nominal full-match equivalents of strong shrinkage
to the league rate. It is a model prior, not ten fabricated observations. No prior
OOS-role measured support anywhere means exact incumbent fallback, not a fitted role
effect. An unsupported individual role dimension shrinks to the measured league prior.

For a current player, take the last five **appeared eligible** rows, THEN select
measured signal rows among those five. Do not search farther back to fill a NULL slot.
Let their sums be `S_i` and `M_i`. Their context prior is:

`context_rate_i = sum_r(current_OOS_role_probability_i[r] * soft_role_rate[r])`.

`player_rate_i = (S_i + 90 * context_rate_i) / (M_i + 90)`.

The player prior is fixed at 90 minutes, matching one full-match-equivalent shrinkage
already used by the repository's exposure helper. There is no outer-result tuning.

`expected_minutes_i = sum_b(current_minutes_PMF_i[b] * prior_fold_bin_mean[b])`.

Bin zero is exactly zero. Other bin means use prior observed minutes, with the existing
fixed `(0,30,75,90)` fallback only for a genuinely empty training bin. These are not the
composer's scoring-threshold representative minutes. No second `P(play)` multiplier:

`weight_i = player_rate_i * expected_minutes_i`.

## Role meaning and out-of-sample boundary

The role forecast is `P(GK, DEF, MID, FWD | hypothetical start)`. Here those values are
**pre-match soft covariates**, not probabilities of starting, actual substitute roles,
physical role-minute exposure or permanent player roles. Weighted signal/minute sums
are predictive-context statistics; they must not be described as observed minutes
played in each role. No actual target role, lineup, minutes, xG/xA or scoring outcome
enters a predictor. No unapproved positional/formation translation is introduced.

Each historical row's context retains the original role prediction, source SHA,
capture/interpretation identities and late known times. Its maximum training event and
retained event must be strictly before its own cutoff. Recent sources must satisfy
the unchanged whole-GW exclusion and completion guard: known event/end before cutoff;
otherwise kickoff plus six hours strictly before cutoff. Capture timestamps are never
rewritten to resemble historical knowledge.

## Allocation and exact fallback

For each fixture side, retain every declared player. Players are ineligible for a new
allocation when current-control cold, role evidence unavailable/cold, recent signal
unmeasured, expected exposure zero, or incumbent team scale unavailable. Their original
unconditional rate and exact conditional PMF stay unchanged, including price-sensitive
cold starts. Source NULL is never filled with zero or a made-up average.

Let `E` contain only eligible players, and `B = sum_i_in_E(incumbent_rate_i)`. Reallocate
only this existing budget:

`candidate_rate_i = B * weight_i / sum_j_in_E(weight_j)`.

Require at least two eligible players and positive total weight/budget; otherwise the
whole pool keeps its incumbent. This is an identifiability condition, not a selected
row-count tuning parameter. Explicit zero or unchanged allocation returns the original
PMF object. Missing players remain in all scoring denominators. Preserving their rates
avoids an apparent "fallback" whose value secretly changes through team normalization.

The complete incumbent side's raw rate sum must match its retained team scale; every
eligible pool must conserve its own original budget. Conditional-on-appearance rates
still use the exact existing `conditional_rate(rate, P(play), cap=team_scale)` helper
and its original Poisson support 0..10. Retain whether the cap binds. This guarantees
**pre-cap rate-budget conservation only**: caps/tail-folding can change post-cap means,
and no per-draw realised total conservation is claimed.

The component marginal scored against all recorded outcomes is the current appearance
mixture, not an independent Poisson regenerated from the unconditional rate:

`P(Y=0) = P(DNP) + P(play)*conditional_PMF[0]`;

`P(Y=k>0) = P(play)*conditional_PMF[k]`.

## Temporal fitting and safeguards

Expanding history retains the existing eight-prior-GW minimum. There is no new Phase D
eight-GW/200-row threshold. Future targets and every target season/GW row are excluded;
historical observed labels require kickoff plus six hours strictly before the outer
cutoff. Same-GW upstream cutoffs and stable club codes must agree. Every target fixture,
including DGW legs, uses one immutable pre-GW fit. No random split, future normalization,
future season frontier, in-sample learned upstream prediction or target value is used.

Retain fold-local bin means, pooled/soft-role rates and sufficient statistics, player
measured window counts/exposure, exact source hash, maximum prior event, original and
candidate allocations/PMFs, cap diagnostics and per-row OOS role source identity.

Current-control price is never a new predictor. Preserve the same direct 821-row proxy
lineage on the full cached population and propagate same-club dependence through the
allocation. Any later points experiment must additionally propagate fixture-wide joint
bonus dependence. Non-proxy and proxy-excluded diagnostics cannot replace all-row results.

## Coverage and unchanged full gate

Read-only audit of the preserved archive found complete goals, assists, xG and xA labels:

| Season | Player-fixture rows | Appeared rows | xG/xA measured | GWs / fixtures |
|---|---:|---:|---:|---:|
| 2023-24 | 29,725 | 11,384 | 100% / 100% | 38 / 380 |
| 2024-25 | 27,283 | 11,566 | 100% / 100% | 38 / 380 |
| 2025-26 | 29,747 | 11,492 | 100% / 100% | 38 / 380 |

This is signal/target coverage, not proof of historical capture-time or role coverage.
The original control universe remains 86,755 rows / 114 folds, including all 821 direct
price-proxy rows. OOS competitive role evidence is scoped only to 2025-26; earlier seasons
retain exact incumbent outputs, not invented role forecasts.

**Both existing Stage C contracts require at least 181 folds**, 100% prediction coverage,
1% primary lift, no RPS/Brier regression, acceptable PIT, no seasonal regression and zero
leakage. Those requirements remain unchanged. A 114-fold / one-role-season experiment is
full-gate **INELIGIBLE**, whatever its numeric result, and cannot enter the passed-successor
synthesis or replace a default. Final runner configs must state this before scoring.

Offline synthetic tests establish formulas, invariants and exact control fallback only.
They do not supply a real-data result, model promotion, or an exception to the full gate.
