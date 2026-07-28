# Candidate V3 development result

> **INVALIDATED — NOT A PROMOTION RESULT AND NOT A COMPARABLE NUMBER.** A review after this
> run found four defects, one of them leakage (the promoted prior was estimated from future
> seasons, so the recorded "zero leakage failures" -- which covers only the harness's per-fold
> checks -- is false as a leakage claim). The other three are specification/fitting and
> provenance defects. Every value below is therefore void for comparison or promotion and is
> retained **only as an audit record** of what the defective procedure printed. See
> [`phase1-candidate-v3-invalidation.md`](phase1-candidate-v3-invalidation.md). The content
> below is unchanged. The leakage-safe successor is the separately pre-registered
> `dynamic_team_goals_v4` (contract amendment 1.5). It had not been evaluated when this
> invalidation banner was written; its later development-only result is recorded in
> [`phase1-candidate-v4-development.md`](phase1-candidate-v4-development.md).

**DEVELOPMENT ONLY — NOT A PROMOTION RESULT.** This is the single historical development
evaluation pre-registered for Candidate V3 (`dynamic_team_goals_v3`). It is not a promotion
evaluation, V3 is judged by no promotion gate, and no number here is a promotion verdict.
The historical archive (2021-22 through 2025-26) is **development evidence** — it has
already shaped Candidates V1 and V2 — not a fresh holdout. Prospective 2026/27 data is
reserved as the untouched confirmation set and was not consumed. The required Stage A
baseline remains `trailing_goals_attack_defence`.

The design and pre-registered grid are fixed in
[`phase1-candidate-v3-design.md`](phase1-candidate-v3-design.md); the policy is the additive
`stage_a_candidate_v3` block (contract amendment 1.4). The model is
`src/fpl/models/dynamic_team_goals.py`; the development runner is
`src/fpl/validate/dev_candidate_v3.py`.

## Identity

| Field | Value |
|---|---|
| Model | `dynamic_team_goals_v3` (development-only) |
| Config | `stage_a_candidate_v3`, contract version `1.4` |
| Evaluated under commit | `f07decc0b752c3d5fd60b87f2a0e06173e00448b` (Commit 1: design + config + model + tests, frozen before this run) |
| Date | 2026-07-28 |
| Seasons | 2021-22, 2022-23, 2023-24, 2024-25, 2025-26 (complete archive) |
| Command | `python -m fpl.validate.dev_candidate_v3` |

## Population

| Count | Value |
|---|---|
| Folds evaluated | 181 (one per observed gameweek; 2022-23 has no GW7) |
| Eligible predictions | 3,640 team-fixtures (3,800 less the eight warm-up gameweeks of 2021-22) |
| Scored predictions | 3,640 (fixture coverage 100.00%; exclusions 0) |
| Cold starts | 84 (matches Candidate V2's cohort) |
| Leakage failures | 0 |

The development runner reuses the Stage A harness unchanged, so V3 is scored on exactly the
same eligible rows as every baseline (`comparison_population: same_eligible_predictions`).

## Required baselines and V3 (overall)

Lower log score, CRPS, deviance, and MAE are better. `rank` is within-gameweek Spearman
(higher is better). `raw80` is the reported-but-not-gated central interval; `PIT80` is the
calibration quantity.

| model | log | SE | CRPS | deviance | MAE | pred. var. | raw80 | PIT80 | Spearman | cold |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **dynamic_team_goals_v3** | **1.4956** | 0.0111 | **0.6373** | 1.1267 | 0.945 | 1.455 | 0.937 | 0.802 | 0.319 | 84 |
| trailing_goals_attack_defence | 1.5003 | 0.0115 | 0.6393 | 1.1361 | 0.943 | 1.436 | 0.930 | 0.798 | 0.306 | 0 |
| trailing_xg_attack_defence | 1.5107 | 0.0111 | 0.6460 | 1.1570 | 0.966 | 1.507 | 0.944 | 0.803 | 0.261 | 0 |
| naive_fdr | 1.5262 | 0.0121 | 0.6580 | 1.1879 | 0.976 | 1.425 | 0.929 | 0.799 | 0.238 | 0 |
| promoted_team_pooled_prior | 1.5481 | 0.0120 | 0.6739 | 1.2317 | 1.012 | 1.446 | 0.929 | 0.794 | 0.127 | 140 |
| league_home_away_goals | 1.5522 | 0.0122 | 0.6764 | 1.2399 | 1.016 | 1.445 | 0.929 | 0.794 | 0.109 | 0 |

## Comparison against the unchanged baseline (development diagnostics, NOT a gate)

The comparator is the best required baseline by overall mean log score:
`trailing_goals_attack_defence` (1.5003) — the same baseline V2 is measured against, and the
bar a promotion candidate would need to beat by 1%.

| Metric | Candidate V3 | Best baseline | Development comparison |
|---|---:|---:|---|
| Mean log score | 1.4956 | 1.5003 | +0.3128% lift |
| Mean log-score SE | 0.0111 | 0.0115 | diagnostic |
| Mean CRPS | 0.6373 | 0.6393 | +0.3016% (improves) |
| Poisson deviance | 1.1267 | 1.1361 | diagnostic |
| PIT 80% coverage | 0.802 | 0.798 | error 0.002 |
| Raw 80% coverage | 0.937 | 0.930 | reported, not gated |
| Within-gameweek Spearman | 0.319 | 0.306 | diagnostic |

For reference, Candidate V2 scored 1.4939 (+0.4284% lift) on the same population. V3
(1.4956) is therefore a touch behind V2 on the primary metric while improving CRPS and
ranking slightly. **Neither clears the 1% promotion lift**, and neither is promoted.

## Slices

### By season (mean log score; lift is V3 vs `trailing_goals_attack_defence`)

| season | V3 | baseline | lift |
|---|---:|---:|---:|
| 2021-22 | 1.5014 | 1.4900 | **−0.7594%** (regresses) |
| 2022-23 | 1.5082 | 1.5186 | +0.6845% |
| 2023-24 | 1.5390 | 1.5484 | +0.6068% |
| 2024-25 | 1.4756 | 1.4955 | **+1.3276%** (only season clearing 1%) |
| 2025-26 | 1.4551 | 1.4469 | **−0.5692%** (regresses) |

V3 clears a 1% season lift only in 2024-25, and regresses in 2021-22 and 2025-26 — the same
regime signature as V1 and V2. 2021-22 has no preceding season and no xG, so a model that
relies on cross-season retention and the xG signal has little to work with there, exactly as
the design doc predicted.

### By promoted status (mean log score)

| slice | V3 | baseline |
|---|---:|---:|
| established | 1.5233 | 1.5287 |
| promoted | 1.3025 | 1.3020 |

V3 is essentially indistinguishable from the trailing-goals baseline on promoted clubs
(1.3025 vs 1.3020): the season-scoped promoted prior and six-match cold-start rule behave
as intended, and the dynamic strength yields to observed matches within a few gameweeks.

### By home/away (mean log score)

| slice | V3 | baseline |
|---|---:|---:|
| home | 1.5397 | 1.5403 |
| away | 1.4516 | 1.4603 |

## Fold-local parameter selections

The three dynamic knobs were selected on the six-observed-gameweek inner holdout inside
each fold. The exact holdout ran in 171 folds; the declared fallback (learning rate 0.10,
retention 0.995, season retention 0.75) ran in the first 10, which lack enough inner
history.

| Parameter | Selection counts (of 181 folds) |
|---|---|
| `learning_rate` | **0.05 = 153**, 0.10 = 25, 0.20 = 3 |
| `retention` | 0.985 = 79, 0.995 = 24, **1.0 = 78** |
| `season_retention` | **0.5 = 92**, 0.75 = 29, 1.0 = 60 |
| `used_inner_holdout` | True = 171, False = 10 |

**Boundary selections (diagnostics, not authorisation to widen the grid).** Two grid edges
dominate and are recorded as evidence for a future structural hypothesis, not as permission
to change V3 after seeing this result:

- **`learning_rate = 0.05` in 153 of 181 folds** (the grid floor, slowest adaptation). The
  inner holdout almost always prefers the smallest step size, which says team strength
  moves slowly and a single match should move it only a little. A new candidate wanting
  slower-than-0.05 adaptation would need a separately named, committed policy.
- **`season_retention = 0.5` in 92 of 181 folds** (the grid floor, strongest summer
  shrinkage). The model usually wants more summer regression than the grid offers,
  consistent with squad churn being a real structural break.
- **`retention` is bimodal** between 0.985 (strong within-season forgetting, 79 folds) and
  1.0 (no forgetting, 78 folds), with the middle value rarely chosen. That bimodality is
  itself a signal worth a named hypothesis later.

## Caveats

- **First-kickoff cutoff.** The archive carries no authoritative FPL deadline or
  schedule-version history, so each fold's cutoff is the first kickoff of its predicted
  gameweek — the latest proxy that excludes every outcome in it. This is not evidence that
  schedule, postponement, or availability fields were known at the real deadline. No live
  or versioned fact is consumed.
- **Development evidence.** The archive has shaped V1, V2, and now V3, so a historical
  improvement is necessary but not sufficient. It is overfit-by-construction to a fixed,
  already-seen set of seasons.
- **Promoted prior provenance.** The promoted-club priors (0.719 / 1.309) are measured
  constants declared in config and used as the cold-start prior for any promoted club in
  any season, as for V2; they are not fold-fitted.

## Verdict

> **SUPERSEDED — this verdict is void.** The run it describes used a leakage-tainted procedure
> (see the invalidation banner above and
> [`phase1-candidate-v3-invalidation.md`](phase1-candidate-v3-invalidation.md)). The
> "competitive with V2" reading below depended on the now-invalid number and must not be
> reused. It is left in place as the audit record of what was written at the time.

**DEVELOPMENT ONLY. Do not promote.** Candidate V3 improves on the trailing-goals baseline
by +0.3128% on mean log score (1.4956 vs 1.5003) and by +0.3016% on CRPS, with good
calibration (PIT-80 error 0.002) and the same 3,640-prediction population and 84 cold
starts as V2. It does not approach the 1% promotion lift, regresses in 2021-22 and 2025-26,
and lands fractionally behind V2 on the primary metric. The structural hypothesis
(sequential, mean-reverting adaptation) is therefore not falsified — it is competitive with
V2 — but it is not a step-change either, and the boundary selections (slowest learning rate,
strongest summer shrinkage) point at where a different structural hypothesis would have to
go. Per the pre-registration, V3 is left as committed and is not tuned again after this
result. The trailing-goals baseline remains the Stage A model.
