# Candidate V4 design: the leakage-safe sequential dynamic team-goals model

**Status: pre-registered for development only, not yet evaluated.** Candidate V4
(`dynamic_team_goals_v4`) is the structural successor to the **invalidated** Candidate V3. It
keeps V3's hypothesis -- team strength is a slowly time-varying latent quantity, estimated
*sequentially* by a mean-reverting online Poisson filter in log space with explicit summer
shrinkage -- and fixes the four defects that voided V3's development number
([`phase1-candidate-v3-invalidation.md`](phase1-candidate-v3-invalidation.md)). No V4
historical evaluation has been run; nothing in this document is a result, and V4 is judged by no
promotion gate. The required Stage A baseline remains `trailing_goals_attack_defence`.

**Timeline note.** Commit `cdb1240` invalidated V3 immediately before commit `7aa2dbf`
pre-registered V4; V4 is the leakage-safe successor to that invalidated result. This document is
a follow-up clarification of V4's pre-registration and does not rewrite either commit.

The machine-readable policy lives in `config/phase1_evaluation.yaml` under
`stage_a_candidate_v4` (contract amendment 1.5). The model is implemented in
`src/fpl/models/dynamic_team_goals_v4.py`; the development runner is
`src/fpl/validate/dev_candidate_v4.py`. Nothing about V2, V3, the baselines, the outer rows, the
lift threshold, the CRPS rule, the calibration tolerance, the coverage requirement, the fold
requirement, or the leakage requirement changes.

V4 is pre-registered **before** any evaluation. The grid, the estimator, the fallback, the
shrinkage, and the three procedure pins are frozen here; once a V4 number exists it must not be
tuned again, and a change to any of them is a new named candidate under a further amendment.

## 1. What V4 inherits from V3

The dynamic model itself is unchanged from V3's design (`phase1-candidate-v3-design.md`
sections 1-2): strengths in log space, combined multiplicatively with the pooled venue means,

```
lambda(home, away) = mu_home * exp(alpha_home + beta_away)
lambda(away, home) = mu_away * exp(alpha_away + beta_home)
```

matches processed chronologically with both sides' pre-match rates computed before either side
is updated (no same-match leakage), a Poisson-gradient `(y - lambda)` step after per-appearance
mean reversion, an explicit summer shrinkage at each season boundary, stable `team_code`
identity, season-qualified `(season, fixture)` pairing, xG used where measured and scaled to
goals inside the fold, NULL preserved, an exact Poisson marginal (no Monte Carlo), and the same
three dynamic knobs (learning rate, retention, season retention) selected on an inner
observed-gameweek holdout. What changes is the four places where V3 was not actually that.

## 2. The four fixes

### 2.1 Nested walk-forward inner selection (V3 defect 1)

V3's inner selection replayed the inner training window to one state and scored all six held-out
gameweeks from that single frozen state. V4's inner holdout is a true per-observed-gameweek
walk-forward:

1. Replay the inner training matches chronologically to the pre-holdout state.
2. For each chronological observed holdout gameweek:
   - apply the summer transition if the gameweek crosses a season boundary;
   - predict **every** fixture in the gameweek from the pre-gameweek state (a per-gameweek
     snapshot, so no same-gameweek result leaks into another fixture's prediction and the batch
     is order-invariant);
   - score those predictions; and only then
   - absorb the whole gameweek's results, advancing counts and state before the next gameweek.
3. The grid triple with the lowest total holdout mean log score is selected; the full training
   window is then replayed with it to produce the fold's predictions.

The walk-forward is pinned on by `holdout_walk_forward: true` (a `Literal[True]` field, so a
config that turns it off fails to load rather than being silently ignored).

### 2.2 Cold-start prior in the fitting residual (V3 defect 2)

V3 applied the six-match cold-start prior only at prediction time; the fitting residual was
measured against the raw dynamic rate, so a cold club was trained from its first match against an
under-trained value. V4 uses the cold-start prior in the residual too: a club with fewer than
`minimum_team_matches` (6) eligible matches has its side of the rate taken from the prior --
fold-local promoted ratio if it was promoted in the match's season, otherwise the neutral mean --
on **every** match until six, in fitting as well as prediction. The dynamic strength still
takes the gradient step; what changes is the rate the residual is measured against. Pinned on by
`cold_start_in_fitting: true`.

### 2.3 Returning-promoted count reset (V3 defect 2, count part)

V3 reset a promoted club's attack and defence to the prior at a season boundary but never reset
its `counts`, which only ever incremented. A club relegated and promoted back therefore kept its
old Premier-League match count and was never cold again. V4 resets the eligible count to zero
for **every** club in the new season's promoted set -- never seen before, or relegated and
returned -- while incumbents keep their count and shrink their strength by `season_retention`
(declared summer retention). Pinned on by `returning_promoted_count_reset: true`.

### 2.4 Fold-local promoted priors (V3 defect 3, the leakage)

V3's promoted priors `0.719 / 1.309` were the full-archive measured constants, applied as fixed
priors in every season and fold, including early folds whose `as_of` preceded the seasons those
estimates were drawn from. That is target leakage through a config constant, and it is why V3's
`Leakage failures: 0` is false as a leakage claim. V4 estimates the prior fold-locally and
carries no full-archive constant.

**Estimator (frozen).** For each season `s` strictly before the prediction season whose matches
are inside the fold, and each club `c` newly promoted into `s`, attack and defence ratios are
formed from that club's **measured (non-null) observations of each component** in `s`:

```
mu_s                  = mean goals_for over all team-match rows of season s in the frame
attack_ratio_c        = ((goals_for_c + k * mu_s) / (goals_for_n_c + k)) / mu_s
defence_ratio_c       = ((goals_against_c + k * mu_s) / (goals_against_n_c + k)) / mu_s
```

where `k = promoted_prior_shrinkage_matches` (6.0, frozen; the mean of per-club ratios, not a
ratio of pooled means, exactly as the archive's measured constant was defined). A component ratio
enters only if that component has at least `promoted_prior_min_matches` (6) measured observations,
so the threshold is per-component, not a row count. The prior is the cohort mean of the per-club
ratios, attack and defence separately.

**Eligible cohort (frozen).** Promoted clubs in seasons strictly before the prediction season,
present in the frame. The current promoted cohort (the prediction season's newcomers) is
**excluded** from its own initial prior. Because the frame is the fold's training window
(`kickoff_time < as_of`) and the eligible seasons precede the prediction season, appending later
seasons to the archive cannot move an earlier fold's prior -- those rows are outside the frame.

**Sample behaviour (frozen).** One ratio per cohort club per component, weighted once (not per
match); a component with fewer than `promoted_prior_min_matches` measured observations contributes
nothing and is never zero-filled, so a club whose defence went unmeasured still contributes its
attack ratio and simply omits a defence ratio. The two sides fall back independently when no
eligible component reaches the minimum.

**Fallback (frozen).** With no eligible cohort -- which is the case for the earliest folds, the
first season having no promoted set at all -- the declared neutral `fallback_attack_prior =
fallback_defence_prior = 1.0` applies.

The prior used during inner selection is estimated from the inner training subset only, so the
holdout cannot move it; the prior used for the fold's predictions is estimated from the full
training window. There is no `promoted_attack_prior` / `promoted_defence_prior` field on V4's
policy.

## 3. Point-in-time argument

The filter reads only the fold's training window, which the harness has already restricted to
`kickoff_time < as_of`. The four leakage classes:

- **Target leakage.** No `mart_target_*` table, no `total_points`, no recorded-points column is
  read. The target is goals (and xG where measured), as for V2/V3.
- **Event-time leakage.** Every training match satisfies `kickoff_time < as_of`; the fold's own
  gameweek is invisible (the harness asserts this per fold), and the fold-local prior reads only
  earlier seasons inside that window.
- **Knowledge-time leakage.** The archive carries no authoritative deadline or schedule-version
  history, so the cutoff is the first kickoff of the predicted gameweek -- the latest proxy that
  excludes every outcome in it. No live/versioned fact is consumed.
- **Identity leakage.** Clubs are keyed on stable `team_code`, never season-scoped `team_id`;
  matches are paired by the season-qualified `(season, fixture)` key.

**Truncation equivalence.** V4's prediction at a fold is identical whether the database is full
(with the future filtered by the harness) or physically truncated to `as_of`; this is asserted
on the archive, and it is the check that the fold-local prior has not smuggled in a future row.

Within-fold honesty: the learning rate, retention, season retention, the xG-to-goals scale, and
the fold-local prior are all fitted inside the fold on an inner observed-gameweek holdout, never
on the predicted gameweek and never on pooled outer results. The seed is the contract's
`202627`, used only for the randomized PIT. Behaviour is deterministic: every Polars aggregation
that feeds a number pins `maintain_order=True`.

## 4. Provenance (V3 defect 4)

V3's runner recorded only `git rev-parse HEAD` and would run on a dirty worktree, so the recorded
SHA could name the wrong code. V4's runner (`fpl.validate.dev_candidate_v4`) refuses to start
when `git status --porcelain` is non-empty, and records the exact clean commit SHA, the SHA-256
fingerprint of `config/phase1_evaluation.yaml`, the SHA-256 fingerprint of the scored database,
the fixed seed, and a UTC capture timestamp, so a V4 development number is tied to one frozen
(code, config, data) triple. The runner is pre-registered here; running the full evaluation is
out of scope for the pre-registration change.

## 5. Grid and inner holdout

The grid is V3's, fixed before any V4 score is examined:

| Knob | Grid | Meaning |
|---|---|---|
| `learning_rate` | {0.05, 0.10, 0.20} | how strongly one match moves a club's strength |
| `retention` | {0.985, 0.995, 1.0} | per-appearance within-season memory |
| `season_retention` | {0.5, 0.75, 1.0} | explicit summer shrinkage |

Fallback (insufficient inner history, i.e. the first folds that cannot carve a 6+12 inner split):
learning rate 0.10, retention 0.995, season retention 0.75. The grid is 27 combinations, each a
single chronological replay plus a per-gameweek walk-forward over six holdout gameweeks. Boundary
selections (a fallback, or a grid edge chosen often) are recorded as diagnostics, **not** as
authorisation to widen the grid after seeing a result. Fixed policy: rate floor 0.05; log-strength
cap 2.0; six-match cold start; xG used where measured and scaled to goals inside the fold.

## 6. Development versus prospective confirmation

Like V3, this is historical development only. The archive (2021-22 through 2025-26) is
development evidence -- it has already shaped V1, V2, V3, and now V4's design -- so a good
historical number is necessary but not sufficient. A genuine promotion attempt would be a
separately pre-registered candidate evaluated against prospective 2026/27 data as it accrues,
under the unchanged promotion gate. No 2026/27 outcome is read or predicted by V4.

## 7. Failure conditions and what is frozen

Expected failure modes (recorded honestly, not fixed by widening the grid after the fact):

- No material lift over the trailing-goals baseline: the structural hypothesis remains
  unconfirmed for this archive, and the answer is another documented non-promotion.
- Boundary selections at the grid edges, or the neutral prior fallback firing often: diagnostics
  for a future named hypothesis, not permission to retune V4.
- Worse in 2021-22 / early-season regimes, where cross-season history and xG are thinnest.

Frozen before evaluation: the grid and fallbacks; the estimator (mean of per-club shrunk
ratios), eligible cohort (earlier seasons only, current excluded), sample behaviour
(`promoted_prior_min_matches`), fallback (`1.0 / 1.0`), and shrinkage
(`promoted_prior_shrinkage_matches = 6.0`); and the three procedure pins
(`holdout_walk_forward`, `cold_start_in_fitting`, `returning_promoted_count_reset`). If V4's
development result is poor, the model is left as committed and the verdict is recorded; it is not
tuned again after seeing the full result.
