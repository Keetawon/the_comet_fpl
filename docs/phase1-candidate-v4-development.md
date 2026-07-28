# Candidate V4 development result

> **DEVELOPMENT ONLY — NOT A PROMOTION RESULT.** This is the single historical development
> evaluation pre-registered for Candidate V4 (`dynamic_team_goals_v4`), the leakage-safe
> successor to the **invalidated** Candidate V3. It is not a promotion evaluation, V4 is judged
> by no promotion gate, and no number here is a promotion verdict. The historical archive
> (2021-22 through 2025-26) is **development evidence** — it has already shaped Candidates V1,
> V2, and V3 — not a fresh holdout. Prospective 2026/27 data is reserved as the untouched
> confirmation set and was not consumed. The required Stage A baseline remains
> `trailing_goals_attack_defence`.

Unlike V3's development number, this one is leakage-safe: the runner refused to start on a
dirty worktree, snapshotted the contract bytes before fingerprinting, and revalidated the
(code, config, data) triple immediately before printing. Exit code 0 and the provenance lines
below are therefore a trustworthy record of what was scored. The design and pre-registered grid
are fixed in [`phase1-candidate-v4-design.md`](phase1-candidate-v4-design.md); the policy is the
additive `stage_a_candidate_v4` block (contract amendment 1.5). The model is
`src/fpl/models/dynamic_team_goals_v4.py`; the development runner is
`src/fpl/validate/dev_candidate_v4.py`. V3's void result and its four defects are documented in
[`phase1-candidate-v3-invalidation.md`](phase1-candidate-v3-invalidation.md).

## Identity

| Field | Value |
|---|---|
| Model | `dynamic_team_goals_v4` (development-only) |
| Config | `stage_a_candidate_v4`, contract version `1.5` |
| Evaluated under commit | `1319dce719fe6db9303754ef7b12610f9d17d347` (frozen before this run; worktree clean, revalidated before print) |
| Contract fingerprint | `afd79d3f82dbb00f3d9d13bb370db1beece4fcb65f3c9e21aedda9eccb67649d` |
| Archive fingerprint | `c37aa58c41bc68b89656547eb1ee790d917c57a7497713d6b02d0f02f1414418` |
| Seed | `202627` |
| Capture timestamp (UTC) | `2026-07-28T17:41:29Z` (runner `captured_at`, verbatim) |
| Seasons | 2021-22, 2022-23, 2023-24, 2024-25, 2025-26 (complete archive) |
| Command | `python -m fpl.validate.dev_candidate_v4` (exit code 0) |

## Population

| Count | Value |
|---|---|
| Folds evaluated | 181 (one per observed gameweek; 2022-23 has no GW7) |
| Eligible predictions | 3,640 team-fixtures (3,800 less the eight warm-up gameweeks of 2021-22) |
| Scored predictions | 3,640 (fixture coverage 100.00%; exclusions 0) |
| Cold starts | 140 |
| Leakage failures | 0 |
| Mean log-score SE | 0.0111 (reported uncertainty) |

The development runner reuses the Stage A harness unchanged, so V4 is scored on exactly the
same eligible rows as every baseline (`comparison_population: same_eligible_predictions`).

## Required baselines and V4 (overall)

Lower log score, CRPS, deviance, and MAE are better. `Spearman` is within-gameweek rank
(higher is better). `raw80` is the reported-but-not-gated central interval; `PIT80` is the
calibration quantity. `cover` is fixture coverage; `n`/`excl`/`cold` are prediction, exclusion,
and cold-start counts.

| model | log | SE | CRPS | deviance | MAE | pred. var. | raw80 | PIT80 | Spearman | cover | n | excl | cold |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **dynamic_team_goals_v4** | **1.4945** | 0.0111 | **0.6363** | 1.1245 | 0.944 | 1.456 | 0.937 | **0.800** | 0.320 | 1.000 | 3,640 | 0 | 140 |
| trailing_goals_attack_defence | 1.5003 | 0.0115 | 0.6393 | 1.1361 | 0.943 | 1.436 | 0.930 | 0.798 | 0.306 | 1.000 | 3,640 | 0 | 0 |
| trailing_xg_attack_defence | 1.5107 | 0.0111 | 0.6460 | 1.1570 | 0.966 | 1.507 | 0.944 | 0.803 | 0.261 | 1.000 | 3,640 | 0 | 0 |
| naive_fdr | 1.5262 | 0.0121 | 0.6580 | 1.1879 | 0.976 | 1.425 | 0.929 | 0.799 | 0.238 | 1.000 | 3,640 | 0 | 0 |
| promoted_team_pooled_prior | 1.5481 | 0.0120 | 0.6739 | 1.2317 | 1.012 | 1.446 | 0.929 | 0.794 | 0.127 | 1.000 | 3,640 | 0 | 140 |
| league_home_away_goals | 1.5522 | 0.0122 | 0.6764 | 1.2399 | 1.016 | 1.445 | 0.929 | 0.794 | 0.109 | 1.000 | 3,640 | 0 | 0 |

## Comparison against the unchanged baseline (development diagnostics, NOT a gate)

The comparator is the best required baseline by overall mean log score:
`trailing_goals_attack_defence` (1.5003) — the same baseline V2 is measured against, and the bar
a promotion candidate would need to beat by 1% (i.e. reach 1.4853).

| Metric | Candidate V4 | Best baseline | Development comparison |
|---|---:|---:|---|
| Mean log score | 1.4945 | 1.5003 | +0.3888% lift |
| Mean log-score SE | 0.0111 | 0.0115 | diagnostic |
| Mean CRPS | 0.6363 | 0.6393 | +0.4588% (improves) |
| Poisson deviance | 1.1245 | 1.1361 | diagnostic |
| PIT 80% coverage | 0.800 | 0.798 | error 0.000 |
| Raw 80% coverage | 0.937 | 0.930 | reported, not gated |
| Within-gameweek Spearman | 0.320 | 0.306 | diagnostic |
| Cold starts | 140 | 0 | reported |

For complete candidate-history context on the same population, Candidate V1 scored **1.4886**
(+0.7828% lift, PIT-80 0.800) but failed the aggregate and per-season 1% gates and had documented
mechanics defects that made it unsuitable for silent modification; its non-promotion remains
valid. Corrected Candidate V2 scored **1.4939** (+0.4284% lift, CRPS 0.6355, PIT-80 0.803), and
the invalidated V3 printed 1.4956 (void — see
[`phase1-candidate-v3-invalidation.md`](phase1-candidate-v3-invalidation.md)). V4 (1.4945) is
therefore fractionally behind V2 on the primary metric and on CRPS, with the cleanest
calibration among the corrected candidates (PIT-80 exactly 0.800) and tied with V1 on that
diagnostic. **None clears the 1% promotion lift, and none is promoted.** V4's 140 cold starts
match the `promoted_team_pooled_prior`
baseline's cohort rather than V2/V3's 84: fix 3 (returning-promoted count reset) makes a club
relegated and promoted back cold again, which is the intended behaviour and the reason the count
moved.

## Slices

### By season (mean log score; lift is V4 vs `trailing_goals_attack_defence`)

| season | V4 | baseline | lift |
|---|---:|---:|---:|
| 2021-22 | 1.5022 | 1.4900 | **−0.8187%** (regresses) |
| 2022-23 | 1.5105 | 1.5186 | +0.5316% |
| 2023-24 | 1.5344 | 1.5484 | +0.8992% |
| 2024-25 | 1.4753 | 1.4955 | **+1.3482%** (only season clearing 1%) |
| 2025-26 | 1.4515 | 1.4469 | **−0.3172%** (regresses) |

V4 clears a 1% season lift only in 2024-25, and regresses in 2021-22 and 2025-26 — the same
regime signature as V1, V2, and the invalidated V3. 2021-22 has no preceding season and no xG,
so a model that relies on cross-season retention and the xG signal has little to work with
there, exactly as the design doc predicted. The 2025-26 regression (and the 2021-22 one) is the
honest weak spot, not something to retune against.

### By promoted status (mean log score)

| slice | V4 | baseline |
|---|---:|---:|
| established | 1.5219 | 1.5287 |
| promoted | 1.3032 | 1.3020 |

V4 improves on established clubs (+0.44%) and is essentially tied with — a touch behind — the
trailing-goals baseline on promoted clubs (1.3032 vs 1.3020). The fold-local prior and the
six-match cold-start rule (now applied in the fitting residual) behave as intended, and the
dynamic strength yields to observed matches within a few gameweeks; the slight drag on the
promoted slice is consistent with fix 3 making returning promoted clubs cold again rather than
carrying a stale, optimistic count.

### By home/away (mean log score)

| slice | V4 | baseline |
|---|---:|---:|
| home | 1.5366 | 1.5403 |
| away | 1.4523 | 1.4603 |

V4 improves on both venues, slightly more away (+0.55%) than home (+0.24%).

## Fold-local parameter selections

The three dynamic knobs were selected on the six-observed-gameweek **walk-forward** inner
holdout inside each fold (fix 1). The exact holdout ran in 171 folds; the declared fallback
(learning rate 0.10, retention 0.995, season retention 0.75) ran in the first 10, which lack
enough inner history.

| Parameter | Selection counts (of 181 folds) |
|---|---|
| `learning_rate` | **0.05 = 164**, 0.10 = 17 (never 0.20) |
| `retention` | 0.985 = 84, 0.995 = 27, 1.0 = 70 |
| `season_retention` | **0.5 = 83**, 0.75 = 20, **1.0 = 78** |
| `used_inner_holdout` | True = 171, False = 10 |
| `inner_holdout_observed_gameweeks` | 6 = 171, 0 = 10 (fallback) |

The three pinned procedure fields fired in **all 181 folds**, as the pre-registration requires:
`holdout_walk_forward = True` (181), `cold_start_in_fitting = True` (181),
`returning_promoted_count_reset = True` (181), `promoted_prior_source =
fold_local_earlier_cohorts` (181).

### Fold-local promoted prior (fix 4, the leakage fix)

The prior is estimated per prediction season from earlier promoted cohorts inside the fold; it
carries no full-archive constant. It took three distinct non-neutral values, each in 38 folds,
and fell back to the declared neutral `1.0 / 1.0` in 67 folds where no eligible earlier cohort
reached the per-component minimum:

| Side | Non-neutral values (×38 folds each) | Neutral fallback |
|---|---|---:|
| attack | 0.7272, 0.7773, 0.8268 | 1.0 (×67) |
| defence | 1.1562, 1.2631, 1.3144 | 1.0 (×67) |

Every non-neutral attack prior is below 1.0 (promoted teams score less than the league) and
every defence prior above 1.0 (promoted teams concede more) — the same direction as the measured
`0.719 / 1.309` constants V2/V3 hardcoded, but now estimated from earlier cohorts only, varying
with the eligible seasons, and less extreme. That is exactly what the leakage-safe estimator is
meant to produce. The neutral fallback firing in 67 folds is the earliest folds' honest
behaviour, not a defect: when no earlier promoted cohort is eligible, V4 declares neutrality
rather than smuggling in a future-estimated constant.

**Boundary selections (diagnostics, not authorisation to widen the grid).** Recorded as evidence
for a future structural hypothesis, not as permission to change V4 after seeing this result:

- **`learning_rate = 0.05` in 164 of 181 folds** (the grid floor, slowest adaptation; more
  dominant than V3's 153). The inner walk-forward almost always prefers the smallest step size,
  which says team strength moves slowly. A candidate wanting slower-than-0.05 adaptation would
  need a separately named, committed policy.
- **`season_retention` is bimodal**: `0.5` (floor, strongest summer shrinkage) in 83 folds and
  `1.0` (ceiling, no shrinkage) in 78, with the middle value rarely chosen. The model usually
  wants either aggressive summer regression or none — consistent with squad churn being a real
  but uneven structural break.
- **`retention` is also bimodal** between 0.985 (strong within-season forgetting, 84 folds) and
  1.0 (no forgetting, 70 folds).

## Caveats

- **First-kickoff cutoff.** The archive carries no authoritative FPL deadline or
  schedule-version history, so each fold's cutoff is the first kickoff of its predicted
  gameweek — the latest proxy that excludes every outcome in it. This is not evidence that
  schedule, postponement, or availability fields were known at the real deadline. No live or
  versioned fact is consumed.
- **Development evidence.** The archive has shaped V1, V2, V3, and now V4, so a historical
  improvement is necessary but not sufficient. It is overfit-by-construction to a fixed,
  already-seen set of seasons.
- **Leakage-safe provenance.** The runner recorded a clean commit SHA, snapshotted and hashed
  the exact contract bytes, hashed the scored database, and revalidated all three immediately
  before printing; it refused to start on a dirty worktree. This closes the four V3 defects.
- **Promoted-prior provenance.** Unlike V2/V3, V4's promoted prior carries no full-archive
  constant: it is estimated fold-locally from earlier cohorts, with a declared neutral fallback.
  No 2026/27 outcome is read or predicted by V4.

## Verdict

**DEVELOPMENT ONLY. Do not promote.** Candidate V4 improves on the trailing-goals baseline by
+0.3888% on mean log score (1.4945 vs 1.5003) and by +0.4588% on CRPS, with the best calibration
among the corrected candidates (PIT-80 exactly 0.800, error 0.000; tied with V1), full fixture
coverage (3,640/3,640), and zero leakage failures. It does not approach the 1% promotion lift
(it would need 1.4853), and regresses in 2021-22 (−0.82%) and 2025-26 (−0.32%).

**Did the structural hypothesis improve historically?** Only marginally, and not over the
existing structural candidate. The leakage-safe sequential dynamic filter beats the simple
trailing-goals baseline (+0.39% aggregate) but lands fractionally behind V2's batch
Dixon-Coles on both proper scores (1.4945 vs 1.4939 log; 0.6363 vs 0.6355 CRPS). The sequential,
mean-reverting adaptation is therefore competitive with — not better than — the existing
structural candidate, and it shares the same regime signature (loses where cross-season history
and xG are thinnest). Relative to V2, its one clean win is calibration; it ties V1 on that
diagnostic while trailing V1's historical primary score. The boundary selections (slowest
learning rate in 164/181, bimodal summer retention) point at where a different structural
hypothesis would have to go.

**The value of this run is trustworthiness, not lift.** For the first time the dynamic-model
development number is leakage-safe: the procedure pins fired in all 181 folds, the promoted
prior carries no future-estimated constant, and the provenance is bound to one frozen (code,
config, data) triple. This number may finally be compared — and the comparison says the
hypothesis is competitive but not a step-change.

Per the pre-registration, V4 is left as committed and is not tuned again after this result. The
grid, priors, estimator, fallback, and thresholds are unchanged. The trailing-goals baseline
remains the Stage A model. A genuine promotion attempt would be a separately pre-registered
candidate evaluated against prospective 2026/27 data as it accrues, under the unchanged
promotion gate — that confirmation set was not consumed here and remains the only honest path to
promotion.
