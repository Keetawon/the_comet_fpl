# Phase 1 evaluation contract

**Status: contract and harness implemented at version 1.5. Candidates V1 and V2 were evaluated
and neither promoted. The required trailing-goals baseline remains Stage A. Amendment 1.4
pre-registered a development-only Candidate V3 (`dynamic_team_goals_v3`); its single historical
development result is now **invalidated** (one leakage defect plus specification/fitting and
provenance defects), so its number is void for comparison. Amendment 1.5 pre-registers Candidate V4
(`dynamic_team_goals_v4`), the leakage-safe structural successor to V3; it is development-only,
has not been evaluated, and changes no gate.** The machine-readable source is
`config/phase1_evaluation.yaml`, validated by `Phase1EvaluationConfig` and executed by
`src/fpl/validate/`. This document explains the decisions; it does not override that file.

## Scope and entry gate

Phase 1 predicts a probability distribution for team goals at stable
`(season, fixture, team_code)` grain. Season-scoped `team_id` remains available only for joins
within a season. Stage A does not predict player minutes, player events, bonus, or FPL points.

The four entry contracts are implemented:

1. Phase 0b facts and point-in-time access tests pass.
2. The seven scoring values omitted by `game_config.scoring` have named authoritative evidence.
3. Full archive replacement is failure-atomic, preserves live snapshots, refuses a concurrent
   target change, and has failure and concurrent-update tests.
4. This contract and its executable tests were committed before candidate fitting.

The remaining two rule replay cases under `verification.unverified` still prevent describing
the scoring ruleset as fully validated. They do not alter this team-goals target.

## Walk-forward split and archive cutoff

Each fold predicts one **observed** gameweek. Gameweeks come from the facts rather than `1..38`;
2022/23 has no GW7. The window expands after at least eight observed gameweeks. A team needs six
prior matches for a team-specific estimate; otherwise the candidate uses its declared
season-scoped cold-start prior and reports the prediction as a cold start.

The historical archive does not contain authoritative FPL deadline history or versioned
schedule knowledge. Its cutoff is therefore the first kickoff in the predicted gameweek: the
latest available proxy that excludes every outcome from that gameweek. Observed outcomes must
satisfy `kickoff_time < as_of`. This is not evidence that a postponement, availability field, or
schedule state was known at the real deadline. Any live fact used in a later walk-forward run
must additionally satisfy `known_at <= as_of` or `captured_at <= as_of`.

Every transform, prior, xG scale, and hyperparameter is fitted within the fold. NULL remains
unavailable, never zero. The seed is fixed at `202627`.

## Required comparisons

| Comparator | Purpose |
|---|---|
| League home/away goals | Transparent intercept-only floor |
| Trailing goals attack/defence | Simple observed-goals strength |
| Trailing xG attack/defence | Tests whether xG adds usable signal |
| Naive FPL FDR | Product-facing fixture-difficulty baseline |
| Promoted-team pooled prior | Makes cold-start policy measurable |

All cross-season club ratings use stable `team_code`. Promoted status is season-specific.
Goals-trained and xG-trained candidates must be shown separately. A candidate cannot choose a
more favorable comparator or population after aggregating folds.

The downstream player-points harness is pinned to three minimum comparisons: legitimate FPL
`ep_next`, trailing-five recorded points, and naive FDR. `ep_next` is evaluated only against
`total_points_as_recorded`, because it was generated under the contemporary scoring rules. It
is never a feature and is never compared as if historical points used the 2026/27 ruleset.

## Candidate history

### Candidate V1: documented non-promotion

Candidate V1 scored mean log loss **1.4886** against the unchanged best required baseline at
**1.5003**, a **0.7828%** lift over 181 folds and 3,640 predictions. The gate requires at least
1% on every reported season, with no CRPS regression and all remaining guardrails. V1 therefore
did not promote.

Review also found mechanics that made V1 unsuitable as a base for silent modification:

- its intended six-gameweek inner holdout actually covered 17 to 22 observed gameweeks;
- an unseen promoted club fell back to a neutral rating;
- a club promoted in any historical season kept the promoted prior in later seasons;
- repeated club pairs overwrote matches in the Dixon-Coles rho fit; and
- the compact report omitted contracted slices, diagnostics, counts, and gate checks.

These findings do not invalidate the non-promotion. They define a separately named V2 candidate
under the same outer population and promotion bar.

### Candidate V2: pre-registered, evaluated once, not promoted

| Setting | Pre-registered value |
|---|---|
| Name | `dixon_coles_team_goals_v2` |
| Inner holdout | Last 6 observed gameweeks |
| Minimum inner training history | 12 observed gameweeks |
| Half-life grid | 40, 80, 160, 320, 640 days, plus no decay |
| Prior-match grid | 2, 4, 8, 16, 32 |
| Fallback | No decay, 8 prior matches |
| Team-specific threshold | 6 prior matches |
| Promoted attack/defence priors | 0.719 / 1.309, scoped to prediction season |
| xG policy | Use measured xG, scaled to goals inside the fold |
| Rate floor | 0.05 |
| Fit convergence | 60 sweeps, tolerance `1e-10` |
| Rho grid | -0.20 to 0.20 in steps of 0.01, using every season-fixture match |

The wider search was fixed because V1 selected or defaulted to the 320-day boundary in 73 of
181 folds and selected the 4-match boundary in 74. The policy and implementation were committed
as `c46662f` before V2's single outer evaluation.

| Metric | Candidate V2 | Best required baseline | Result |
|---|---:|---:|---|
| Mean log score | 1.4939 | 1.5003 | +0.4284%; fails required +1% |
| Mean log-score SE | 0.0110 | 0.0115 | diagnostic |
| Mean CRPS | 0.6355 | 0.6393 | +0.5842%; passes |
| Poisson deviance | 1.1233 | 1.1361 | diagnostic |
| PIT 80% coverage | 0.803 | 0.798 | error 0.003; passes |
| Raw 80% coverage | 0.935 | 0.930 | reported, not gated |
| Fixture coverage | 3,640 / 3,640 | 3,640 / 3,640 | passes |
| Cold starts | 84 | 0 | reported |
| Leakage failures | 0 | 0 | passes |

This evaluation ran on 2026-07-28 over the complete 2021-22 through 2025-26 archive. Relative
lifts are computed from the harness's unrounded aggregates; displayed scores are rounded to four
decimals and therefore do not reproduce the final basis-point exactly when recomputed by hand.

The per-season log gate fails in 2021-22 (-0.14%), 2022-23 (+0.15%), 2023-24 (+0.55%), and
2025-26 (+0.02%); only 2024-25 clears 1% (+1.43%). CRPS regresses in 2021-22 (-0.41%),
2022-23 (-0.15%), and 2025-26 (-0.24%). Every season passes calibration, fixture coverage,
fold count, same-population, and leakage checks. The computed verdict is **DO NOT PROMOTE**.

Fold-local selection used the exact six-gameweek holdout in 171 folds and the declared fallback
in the first 10. Half-life counts for 40/80/160/320/640/no-decay were
27/43/42/18/16/35; prior-match counts for 2/4/8/16/32 were 72/20/41/24/24. The lower
prior boundary is evidence for designing a new hypothesis, not for changing V2 after evaluation.

### Candidate V3: pre-registered for historical development only, result now INVALIDATED

> **The V3 development result is invalidated, not merely non-promoted.** Review after the run
> found four defects: one leakage defect (the promoted prior drew on full-archive future
> seasons), two specification/fitting defects (the inner holdout scored all six gameweeks from
> one frozen state; the six-match cold-start prior was prediction-only and returning promoted
> clubs kept old match counts), and one provenance defect (the runner accepted a dirty worktree),
> so V3's development number carries no information and must not be compared against any
> baseline or candidate. The Stage A model and every gate are unchanged. The void values are
> retained as an audit record in
> [`docs/phase1-candidate-v3-invalidation.md`](phase1-candidate-v3-invalidation.md); V3's code
> is left frozen rather than repaired. Amendment 1.5 pre-registers the leakage-safe successor
> `dynamic_team_goals_v4`.

Candidate V3 (`dynamic_team_goals_v3`) is a **development-only** structural probe, not a
promotion candidate. It tests whether a sequential, mean-reverting online Poisson filter in
log space adapts to changing team strength more honestly than V2's batch re-fit, while
retaining useful cross-season information through an explicit retention factor. Its design,
equations, point-in-time argument, cold-start behaviour, and pre-registered grid are fixed in
[`docs/phase1-candidate-v3-design.md`](phase1-candidate-v3-design.md); its policy is the
additive `stage_a_candidate_v3` block. It is evaluated once on the historical archive as
development evidence and judged by no promotion gate. The historical development result is
recorded in [`docs/phase1-candidate-v3-development.md`](phase1-candidate-v3-development.md).
Prospective 2026/27 data is reserved as the untouched confirmation set.

### Candidate V4: pre-registered leakage-safe successor to V3 (not yet evaluated)

Candidate V4 (`dynamic_team_goals_v4`) is the structural successor to the invalidated V3. It
keeps V3's sequential, mean-reverting online Poisson filter and fixes the four defects that
voided V3's number: the inner holdout is a true per-observed-gameweek walk-forward (predict every
fixture in a gameweek from the pre-gameweek state, score, then advance), the six-match cold-start
prior is used in the fitting residual as well as in prediction, returning promoted clubs reset
their eligible count, and the promoted prior is estimated fold-locally from earlier cohorts with
a declared neutral `1.0 / 1.0` fallback (no full-archive constant). Its design, equations,
point-in-time argument, and pre-registered grid are fixed in
[`docs/phase1-candidate-v4-design.md`](phase1-candidate-v4-design.md); its policy is the additive
`stage_a_candidate_v4` block. The three leakage-safety fixes are pinned on as `Literal[True]`
config fields so a silent weakening fails to load. V4 is pre-registered before any evaluation:
no V4 historical score exists, V4 is judged by no gate, and a result would be development
evidence only. Prospective 2026/27 data is reserved as the untouched confirmation set.

## Metrics, reports, and promotion

Mean log score is primary and mean CRPS is the second proper distribution score. Poisson
deviance, goal MAE, predictive variance, randomized PIT, raw 80% interval coverage, PIT-based
80% coverage, and within-gameweek Spearman are diagnostics. Mean log-score standard error is
the reported uncertainty measure. The raw interval is reported but only PIT-band coverage is
gated.

The canonical `HarnessResult` contains overall, fold, season, promoted-status, and home/away
slices. Every score report carries eligible predictions, scored predictions, exclusions, cold
starts, and fixture coverage. Fold-local selected parameters are retained and summarized by the
CLI so a result cannot hide boundary selections or fallbacks.

A Stage A candidate is promoted only if the aggregate and every reported season meet the
machine-readable contract:

- mean log score improves by at least 1% over the best required eligible baseline on the exact
  same prediction rows, using `(baseline - candidate) / abs(baseline)`;
- CRPS does not regress relative to that baseline;
- randomized-PIT 80% band coverage is within five percentage points of 80%;
- at least 98% of eligible team-fixtures receive a prediction;
- at least 20 walk-forward folds are evaluated; and
- point-in-time and truncation-equivalence checks have zero failures.

## Amendments

Every contract version after 1.0 has a machine-readable amendment recording the change, reason,
evidence, and number of candidates already evaluated. A version bump without the matching entry
is rejected by the loader.

### 1.1 -- calibration gate names its metric (2026-07-27, 0 candidates)

The ambiguous raw central-interval gate became
`pit_interval_80_maximum_absolute_error`, at the same 0.05 tolerance. For count distributions,
integer quantiles make raw interval coverage exceed 0.80 by construction. At a true Poisson rate
of 1.80 the correct model covers about 0.964 in the raw interval and would fail, while a model
predicting 2.40 covers about 0.798 and would pass. Randomized PIT is uniform when the model is
calibrated, so its `[0.1, 0.9]` band measures the intended property. A fuller PIT-uniformity test
remains a possible future amendment.

### 1.2 -- stable baseline identity (2026-07-28, 0 candidates)

Stage A baseline ratings changed from bare, reassigned `team_id` to stable `team_code`; promoted
club identification changed with it. The best baseline moved from 1.5227 to 1.5003 over the same
181 folds and 3,640 predictions, making the 1% candidate threshold harder at 1.4853. No gate or
tolerance changed.

### 1.3 -- Candidate V2 and complete executable report (2026-07-28, 1 candidate)

Candidate V2 fixes V1's inner holdout, season-scoped promoted priors, six-match cold-start rule,
season-fixture rho matching, and fold-local xG scaling. The harness now executes every declared
metric, slice, count, same-population check, per-season guardrail, coverage check, fold check, and
leakage check. The outer rows, required baselines, 1% lift, CRPS, calibration, coverage, fold, and
leakage thresholds are unchanged. The archive cutoff is explicitly labeled as a first-kickoff
proxy rather than an authoritative deadline.

### 1.4 -- Candidate V3 development pre-registration (2026-07-28, 2 candidates)

Adds the optional, additive `stage_a_candidate_v3` block pre-registering a development-only
`dynamic_team_goals_v3` and its search grid. No baseline, outer row, lift threshold, CRPS rule,
calibration tolerance, coverage requirement, fold requirement, leakage requirement, or the V2
`stage_a_candidate` policy changes; V3 is never substituted for V2 by any default command. Two
candidates (V1, V2) had been evaluated when this was made. V3 is judged by no promotion gate: it
is reported with V2's metrics, slices, and counts for honest comparison against the unchanged
baseline, and its historical number is explicitly not a promotion verdict. **V3's single
development result was later invalidated (see 1.5).**

### 1.5 -- Candidate V3 invalidation and Candidate V4 pre-registration (2026-07-28, 3 candidates)

Candidate V3's single historical development result is **invalidated**, not merely non-promoted:
review found four defects (one leakage -- the promoted prior drew on full-archive future seasons;
plus specification/fitting defects -- the inner holdout scored all six gameweeks from one frozen
state, the cold-start residual was prediction-only, and returning-promoted clubs kept old match
counts; and a provenance defect -- the runner accepted a dirty worktree). V3's number is
therefore void for comparison and is kept only as an audit record; its code is left frozen rather
than repaired. This amendment adds the additive `stage_a_candidate_v4` block pre-registering
the leakage-safe successor `dynamic_team_goals_v4`, which fixes all four defects with procedure
pins and a fold-local promoted-prior estimator. The block is required at contract version 1.5
(the loader accepts no other version), so it may not be silently dropped. Three candidates (V1,
V2, the invalidated V3) had produced a number before this was made. No baseline, outer row, lift
threshold, CRPS rule, calibration tolerance, coverage requirement, fold requirement, leakage
requirement, the V2 policy, or the frozen V3 policy changes; V4 is never substituted for V2 or V3
by any default command, is judged by no gate, and has not been evaluated.

## Exit criterion

Phase 1 exits when one reproducible Stage A configuration passes every promotion gate, its exact
config and seed are committed, and its result contains the required comparisons, metrics,
slices, counts, exclusions, uncertainty, calibration, and leakage evidence. If no candidate
passes, the correct result is another documented non-promotion, never a relaxed post-hoc bar.
