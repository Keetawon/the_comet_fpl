# Phase 1 evaluation contract

**Status: contract and harness implemented at version 1.3. Candidate V1 was evaluated and did
not promote. Candidate V2 is pre-registered and has not yet been outer-evaluated.** The
machine-readable source is `config/phase1_evaluation.yaml`, validated by
`Phase1EvaluationConfig` and executed by `src/fpl/validate/`. This document explains the
decisions; it does not override that file.

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

### Candidate V2: pre-registered, not yet evaluated

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

The wider search is fixed because V1 selected or defaulted to the 320-day boundary in 73 of 181
folds and selected the 4-match boundary in 74. V2 may be evaluated once without changing this
grid after its outer results are observed.

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

## Exit criterion

Phase 1 exits when one reproducible Stage A configuration passes every promotion gate, its exact
config and seed are committed, and its result contains the required comparisons, metrics,
slices, counts, exclusions, uncertainty, calibration, and leakage evidence. If no candidate
passes, the correct result is another documented non-promotion, never a relaxed post-hoc bar.
