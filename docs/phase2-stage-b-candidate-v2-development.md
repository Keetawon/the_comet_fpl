# Candidate V2 development result (Stage B player minutes)

> **DEVELOPMENT ONLY — NOT A PROMOTION RESULT.** This is the single historical development
> evaluation pre-registered for Stage B Candidate V2
> (`recency_weighted_trailing_player_minutes_v2`), pre-registered under contract amendment 1.3 and
> judged by the unchanged version 1.2 gate. It is not a promotion evaluation, and no number here is a
> promotion verdict. The historical archive (2021-22 through 2025-26) is **development evidence** — it
> shaped the recency hypothesis (via the V1 run and the 1.2 starter-ranking regression it exposed) —
> not a fresh holdout. Prospective 2026/27 data is reserved as the untouched confirmation set and was
> not consumed. The required Stage B baselines remain the Stage B model.

The number is leakage-safe and provenance-bound. The runner refused to start on a dirty worktree,
loaded the contract from one snapshotted read of the config bytes and fingerprinted exactly those
bytes, recorded the candidate-source and archive fingerprints, and re-checked the worktree, HEAD,
config, candidate-source, and database fingerprints after the database was closed and before
printing. Exit code 0 and the provenance below are therefore a trustworthy record of what was
scored. The design and pre-registered frozen grids/tie-break/fallback are fixed in
[`phase2-stage-b-candidate-v2-design.md`](phase2-stage-b-candidate-v2-design.md); the policy is the
additive `stage_b_candidate_v2` block (contract amendment 1.3, which changes none of the version
1.0 population, bins, baselines, metrics, or the version 1.2 gate). The model is
`src/fpl/models/minutes_v2.py`; the development runner is `src/fpl/validate/dev_minutes_candidate_v2.py`.

The run was executed against a **pristine rebuilt archive** (`build_db`, atomic promotion). The
runner recomputed the four frozen baselines on the same eligible rows as V1's run, and an
independent reconciliation diffed V2's baseline records against V1's frozen
[`evidence/phase2-stage-b-candidate-v1-2026-07-30.json`](evidence/phase2-stage-b-candidate-v1-2026-07-30.json)
**bit-for-bit**: every baseline value matched at every grain (overall, per-season, all four
slices, all 181 folds), and the population counts matched exactly (181 folds by season
30/37/38/38/38, 133,964 eligible predictions, zero exclusions, zero leakage). The only difference
between the two records is the candidate (V2 vs V1), which is the whole point. The whole-file
archive hash differs from V1's recorded `c37aa58c…` for the expected reason — the rebuilt DB now
contains the live-registry rows (`stg_live_player_version`, 1,684 rows) the V1-era DB did not — and
the bit-for-bit baseline match is the comparability check, not the whole-file hash.

The unrounded machine-readable source for every number below is
[`evidence/phase2-stage-b-candidate-v2-2026-07-30.json`](evidence/phase2-stage-b-candidate-v2-2026-07-30.json)
(schema `stage_b_candidate_v2_development/v1`). Values here are rounded for readability (log/SE/
RPS/Brier to 5 d.p.; PIT-80 and reliability means/rates to 4 d.p.); the JSON holds the unrounded
values. Empty reliability buckets carry `null` and are shown as `—`, never as a fabricated zero.

## Identity

| Field | Value |
|---|---|
| Model | `recency_weighted_trailing_player_minutes_v2` (development-only) |
| Config | `stage_b_candidate_v2`, contract version `1.3` (additive amendment; v1.0 / 1.2 frozen) |
| Evaluated under commit | `eb9b6a570f9606e67f9b97632f9215d35a16b486` (frozen before the run; worktree clean, revalidated before print) |
| Config fingerprint | `2e30ea31a02d4639417b6d879b8ebcc93133d8cfff8ad7f5b876afd6848665e6` |
| Candidate-source fingerprint | `0cd8956dc00e2be7518ad0ad549f51509e272731454adae6a10db8976200902c` (`src/fpl/models/minutes_v2.py`) |
| Archive fingerprint | `ac704f0728105af8ba5a7ac9f4d5287746f11133be7a6ccfc5c099fbf5836495` (`data/fpl.duckdb`, pristine rebuild) |
| Seed | `202627` (contract `training.seed`; also the randomised-PIT seed) |
| Run window (UTC) | `2026-07-30T09:50:59Z` → `2026-07-30T09:56:41Z` |
| Seasons | 2021-22, 2022-23, 2023-24, 2024-25, 2025-26 (complete archive) |
| Command | `python -m fpl.validate.dev_minutes_candidate_v2 --db data\fpl.duckdb` (exit code 0) |

## Population

| Count | Value |
|---|---|
| Observed gameweek folds | **181** (one per observed gameweek; 2022-23 has no GW7) |
| Folds by season | 2021-22 = 30, 2022-23 = 37, 2023-24 = 38, 2024-25 = 38, 2025-26 = 38 |
| Eligible predictions | **133,964** player-fixtures (`(season, code, fixture)` grain) |
| Scored predictions | 133,964 (exclusions 0; prediction coverage 1.000) |
| Cold starts | 27,971 (identical across all five models; `no_prior` + `no_positive` cohorts) |
| Leakage failures | 0 (`assert_no_minutes_leakage` held in every fold) |

The development runner reuses the Stage B harness unchanged and fits Candidate V2 inside every
fold on the **same validated history** the baselines use, so V2 is scored on exactly the same
eligible rows as every baseline (`comparison_population: same_eligible_predictions`). The harness
raises if any model's prediction count drifts from the eligible population, so identical rows is
structural, not aspirational.

## Required baselines and Candidate V2 (overall)

Lower log, RPS, Brier-any, and Brier-60+ are better. `Spearman` is within-`(season, gw,
position)` rank of the 60-plus margin (higher is better; report-only). `PIT80` is the
randomised-PIT band coverage (nominal 0.80); `|err|` is `|0.80 − PIT80|`. `n`/`excl`/`cold` are
prediction, exclusion, and cold-start counts. The best (lowest) value in each scored column is
bolded; the best (highest) Spearman is bolded separately.

| model | log | SE | RPS | bAny | b60+ | PIT80 | \|err\| | Spearman | cover | n | excl | cold |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **recency_weighted_trailing_player_minutes_v2** | **0.72625** | 0.00262 | **0.29568** | **0.10791** | **0.10005** | 0.8273 | 0.0273 | 0.7007 | 1.000 | 133,964 | 0 | 27,971 |
| position_minutes_frequency | 1.04916 | 0.00196 | 0.59531 | 0.23766 | 0.20115 | 0.8101 | 0.0101 | — | 1.000 | 133,964 | 0 | 27,971 |
| trailing_5_team_position_minutes | 1.12715 | 0.00501 | 0.58225 | 0.23134 | 0.19734 | 0.7981 | 0.0019 | 0.1285 | 1.000 | 133,964 | 0 | 27,971 |
| trailing_5_player_minutes | 3.12642 | 0.02248 | 0.31901 | 0.11552 | 0.10885 | 0.7342 | 0.0658 | 0.7022 | 1.000 | 133,964 | 0 | 27,971 |
| last_observed_player_minutes | 7.02586 | 0.03285 | 0.38054 | 0.13365 | 0.12650 | 0.5990 | 0.2010 | **0.7085** | 1.000 | 133,964 | 0 | 27,971 |

Candidate V2 is the best of the five models on all four bounded scored metrics (mean log score,
RPS, Brier-any, Brier-60+) and improves on V1 on **all five** metrics (see the V2-vs-V1 diagnostic
below). It is the **second-best** starter ranker behind `last_observed_player_minutes`, just ahead
of `trailing_5_player_minutes`.

## Comparison against the baselines (development diagnostics, NOT a gate)

The contract ranks on the primary metric, mean log score, so the registered comparator is the
best required baseline by log score: `position_minutes_frequency` (1.04916). A promotion
candidate would need mean log score **≤ about 1.03867** to clear the 1% aggregate lift gate.
Candidate V2 reaches **0.72625**, a **+30.7774%** lift over that comparator. **That figure is
not a verdict: V2 is judged by no promotion gate, and the reason it is not promoted is the
unversioned historical proxies, not the score (see Verdict).**

The honest test under amendment 1.2 is each bounded guardrail against the **best** baseline value
of its own metric, plus the new starter-ranking gate:

| Guardrail | Candidate V2 | Best baseline (which) | Lift vs best |
|---|---:|---:|---:|
| Mean RPS (lower) | 0.2956794 | 0.3190106 (`trailing_5_player_minutes`) | **+7.3136%** |
| Brier any-minutes (lower) | 0.1079116 | 0.1155240 (`trailing_5_player_minutes`) | **+6.5895%** |
| Brier 60-plus (lower) | 0.1000459 | 0.1088506 (`trailing_5_player_minutes`) | **+8.0888%** |
| Spearman-p60 starter ranking (higher) | 0.7007144 | 0.7085065 (`last_observed_player_minutes`) | **−1.0998%** |
| Mean log score (lower) | 0.7262534 | 1.0491567 (`position_minutes_frequency`) | +30.7774% |

Candidate V2 improves on the best baseline value of every bounded scored metric (RPS and both
Brier margins by +6.6% to +8.1%, a larger move than V1's +0.13% to +1.87% on the same bars), and
on the primary log score by +30.78%. The recency reweighting therefore sharpens the
ordered-distribution prediction beyond V1's shrinkage. **It fails exactly one criterion — the
starter-ranking gate.** V2's aggregate `spearman_p60_within_position_gameweek` (0.70071) regresses
1.10% against the best baseline `last_observed_player_minutes` (0.70851), so a candidate that
ranks starters slightly worse than the best baseline cannot clear the gate whose whole purpose is
to protect starter ranking. As under the 1.1 gate for V1, a material share of the log lift is the
removal of zero-probability mass (the shrinkage still mixes in the never-zero position prior); the
bounded guardrails, not the headline log lift, are what make the result meaningful, and on those
V2 is the strongest model in the set.

## Gate criteria (each a development diagnostic; never combined into a verdict)

Each frozen version 1.2 gate condition is reported as its own labelled check against the
thresholds read from the unchanged `promotion` block. The bounded guardrails are each measured
against the best baseline value of their own metric (`guardrail_comparison:
best_baseline_per_metric`); the starter-ranking gate is `maximum_spearman_p60_relative_regression:
0.0`.

| Gate criterion | Threshold | Observed | Result |
|---|---|---|---|
| `minimum_primary_relative_lift` | ≥ 0.01 | log lift +30.7774% (0.72625 vs 1.04916) | PASS |
| `maximum_ranked_probability_score_relative_regression` | ≤ 0.0 | RPS +7.3136% vs `trailing_5_player_minutes` (regression 0.0%) | PASS |
| `maximum_brier_relative_regression_any_minutes` | ≤ 0.0 | Brier-any +6.5895% vs `trailing_5_player_minutes` (regression 0.0%) | PASS |
| `maximum_brier_relative_regression_60_plus` | ≤ 0.0 | Brier-60+ +8.0888% vs `trailing_5_player_minutes` (regression 0.0%) | PASS |
| `maximum_spearman_p60_relative_regression` | ≤ 0.0 | Spearman −1.0998% vs `last_observed_player_minutes` (regression 1.0998%) | **FAIL** |
| `pit_interval_80_maximum_absolute_error` | ≤ 0.05 | 0.0273 | PASS |
| `minimum_prediction_coverage` | ≥ 1.0 | 1.0000 | PASS |
| `minimum_fold_count` | ≥ 181 | 181 | PASS |
| `require_no_season_mean_log_score_regression` | true | 0 of 5 seasons regress | PASS |
| `require_zero_leakage_failures` | true | 0 leakage failures | PASS |

**Nine of the ten development diagnostics pass; the starter-ranking gate fails.** As a development
diagnostic under the tightened 1.2 gate, V2 does **not** clear it. `combined_promotion_verdict`
is **null** in the evidence record: these checks are never combined into a production promotion
verdict, and the verdict is fixed in advance as development-only (see Verdict). The gate's role
here is diagnostic, not promotional — it shows that recency-weighting improves V1's starter ranking
but does not close the gap to the best baseline.

## The two questions this run exists to answer

### 1. Did recency-weighting lift starter ranking?

**Partly.** Candidate V2's aggregate `spearman_p60_within_position_gameweek` is **0.70071**, up
from V1's **0.69090** — a **+1.4205%** relative lift, so recency-weighting did recover a meaningful
share of the ordering signal V1's equal-weight count discarded (the dropped starter vs the
substitute breaking in now get different predictions). It also moves V2 above
`trailing_5_player_minutes` (0.70219 → V2 0.70071, marginally below) and well above
`trailing_5_team_position_minutes` (0.12846). **But it still falls 1.0998% short of the best
baseline, `last_observed_player_minutes` (0.70851), so it fails the starter-ranking gate.** The
one-hot last-observed prediction carries a sharper within-group ordering than any
trailing-window candidate has yet matched, and recency weighting narrows that gap from V1's
−2.49% to V2's −1.10% without closing it. So the hypothesis "recency improves starter ranking" is
supported relative to V1 and rejected against the gate bar.

### 2. How often did the inner selection actually use recency?

The joint `(decay, alpha)` inner-holdout selections, from the frozen grids `decay ∈ {1.0, 0.9,
0.7, 0.5, 0.3}` and `alpha ∈ {1.0, 2.0, 5.0, 10.0, 20.0}` (tie-break: largest decay, then smallest
alpha; fallback `(1.0, 5.0)` when fewer than 14 prior observed gameweeks):

| decay | alpha | folds | note |
|---|---|---:|---|
| 1.0 | 5.0 | 6 | **fallback** (<14 prior observed GWs; not a genuine selection) |
| 0.9 | 1.0 | 1 | |
| 0.7 | 1.0 | 162 | **modal** |
| 0.7 | 2.0 | 2 | |
| 0.5 | 1.0 | 10 | |

`used_inner_holdout`: True = 175, False = 6 (the fallback folds). **Recency (`decay < 1.0`) was
genuinely selected in all 175 folds where the inner holdout could run — 100% of selectable folds.**
When the six-observed-gameweek inner walk-forward could compare decay values, it never preferred
`decay = 1.0` (V1). The dominant choice is **`decay = 0.7, alpha = 1.0`** (162 of 175 genuine
selections): discount the trailing window at 0.7 per step toward the present and trust the player
history with near-minimal position-prior shrinkage. That weighting puts recent form in charge and
uses the prior only to stay finite, which is exactly what sharpens both the proper scores and the
starter ordering.

**Boundary selections (diagnostics, not authorisation to widen the grid).** Recorded as evidence,
not permission to change V2 after seeing this result:

- **`decay = 1.0` ceiling (recency did not help / V2 collapsed to V1): 0 genuine hits.** The six
  `decay = 1.0` folds are the declared `< 14`-history fallback, not a ceiling selection. Whenever
  the inner holdout could choose, it always preferred some decay.
- **`decay = 0.3` floor: 0 folds.** No floor hit — the grid never bottomed out; `0.7` was preferred
  to heavier discounting, so a true optimum below `0.3` is not indicated here.
- **`alpha = 1.0` floor: 173 folds (heavy hit).** The inner selection wanted minimal shrinkage in
  173 of 181 folds. Because `1.0` is the floor, a true optimum below `1.0` (even less prior) could
  not be expressed and would need a separately named, committed policy to probe. This is far more
  aggressive than V1, which selected `alpha = 1.0` in only 21 folds: once recency concentrates mass
  on the recent rows, less prior is needed to avoid zeros, so the selected `alpha` collapses toward
  its floor.
- **`alpha = 20.0` ceiling: 0 folds.** No upper-boundary hit.
- **6 fallback folds** (`decay = 1.0, alpha = 5.0`) are the earliest gameweeks with fewer than 14
  prior observed gameweeks and are flagged as fallback, not boundary hits.

## Slices (all six registered reporting dimensions)

Lift is Candidate V2 vs `position_minutes_frequency` (the log-score comparator) on mean log
score, unless noted. `V2-vs-V1` is V2's log lift over V1's frozen per-slice value. `n` is the
slice prediction count.

### By fold

181 folds (30/37/38/38/38 by season). Per-fold scores for all five models are in the evidence
JSON (`harness.by_fold`); candidate predictions sum to 133,964 across the 181 folds.

### By season (mean log score)

| season | Candidate V2 | baseline | lift | V2-vs-V1 | n |
|---|---:|---:|---:|---:|---:|
| 2021-22 | 0.74736 | 1.01102 | +26.0787% | +1.0631% | 20,704 |
| 2022-23 | 0.75403 | 1.08768 | +30.6753% | +2.0080% | 26,505 |
| 2023-24 | 0.70393 | 1.02841 | +31.5519% | +2.5626% | 29,725 |
| 2024-25 | 0.75111 | 1.08412 | +30.7171% | +2.0708% | 27,283 |
| 2025-26 | 0.68632 | 1.03003 | +33.3689% | +2.6090% | 29,747 |

No season regresses. V2 beats V1 in every season on mean log score, with the largest gains in the
later, data-richer seasons (2023-24, 2025-26), where the recency-weighted trailing window has more
history to weight.

### By position (mean log score)

| position | Candidate V2 | baseline | lift | V2-vs-V1 | n |
|---|---:|---:|---:|---:|---:|
| GK | 0.25583 | 0.59556 | +57.0442% | +5.1083% | 14,890 |
| DEF | 0.74454 | 1.02538 | +27.3895% | +2.2921% | 44,678 |
| FWD | 0.77686 | 1.13216 | +31.3827% | +1.9193% | 16,010 |
| MID | 0.81836 | 1.16027 | +29.4681% | +1.8035% | 58,386 |

The candidate improves on the position prior in every position. The V2-over-V1 gain is largest for
goalkeepers (+5.11%): their minutes are the most stable, so a recency-weighted trailing window
identifies the established starter most cleanly.

### By home/away (mean log score)

| venue | Candidate V2 | baseline | lift | V2-vs-V1 | n |
|---|---:|---:|---:|---:|---:|
| home | 0.72147 | 1.04688 | +31.0843% | +2.1676% | 66,979 |
| away | 0.73104 | 1.05143 | +30.4719% | +2.0713% | 66,985 |

### By transfer status (mean log score)

| transfer status | Candidate V2 | baseline | lift | V2-vs-V1 | n |
|---|---:|---:|---:|---:|---:|
| same_team_code_as_last_observed_fixture | 0.72216 | 1.04948 | +31.1883% | +2.1557% | 132,390 |
| no_prior_player_fixture | 0.95280 | 0.95280 | +0.0000% | +0.0000% | 1,207 |
| changed_team_code_since_last_observed_fixture | 1.45709 | 1.25096 | **−16.4779%** | −0.0040% | 367 |

**The transferred-player slice still regresses, and recency does not fix it.** For the 367
predictions (0.27% of the population) where a player changed club since his last observed fixture,
Candidate V2 (1.45709) is **worse than the position prior** (1.25096) by −16.48%, essentially
identical to V1 (the V2-over-V1 lift is −0.004%). This is expected and diagnostic: the trailing-5
history is from the **old** club, and recency-weighting merely re-emphasises the most recent of
those stale rows — it does not rescale minutes to the destination club, so the un-rescaled
stale-history problem V1 had persists unchanged. Recency and rescaling attack orthogonal failures;
recency helps the same-club majority and is silent on the transfer minority. (On the tiny
transferred cohort V2 does slightly better at *ranking* starters — Spearman +4.07%, 0.33171 →
0.34522 — but it is 367 rows and moves nothing aggregate.) This remains the single clearest target
for a separately named future candidate and the minutes-model analogue of the contract's rule that
a transferred player's expectation must be rescaled to the destination club. There is no
per-transfer-status gate, so this does not change the aggregate diagnostic outcome. The
`no_prior_player_fixture` slice ties the comparator exactly (+0.0000%) by construction: with no
history the estimator returns exactly the position prior `q`, which **is** the comparator.

### By player-history cohort (mean log score)

| cohort | Candidate V2 | baseline | lift | V2-vs-V1 | n |
|---|---:|---:|---:|---:|---:|
| prior_player_fixtures_no_positive_minutes | 0.17560 | 0.53520 | +67.1897% | +1.6277% | 26,764 |
| prior_positive_minutes | 0.86272 | 1.18003 | +26.8903% | +2.1703% | 105,993 |
| no_prior_player_fixture | 0.95280 | 0.95280 | +0.0000% | +0.0000% | 1,207 |

The candidate helps most where a player has prior fixtures but no positive minutes (the bench
regulars): their zero-heavy recent history, weighted toward the present and shrunk toward the
position prior, predicts non-appearance far better than the position prior alone. `no_prior` ties
by construction.

## V2-vs-V1 diagnostic (the whole point of the candidate)

Recency-weighting moves **every** metric in the right direction over V1. The bounded proper-score
gains (+5.82% to +6.47%) are larger than the log gain (+2.12%), because concentrating mass on the
recent, most-informative rows sharpens the ordered distribution rather than merely removing zeros.

| metric (direction) | V1 | V2 | V2-vs-V1 lift |
|---|---:|---:|---:|
| Mean log score (lower) | 0.7419767 | 0.7262534 | **+2.1191%** |
| Mean RPS (lower) | 0.3139589 | 0.2956794 | **+5.8222%** |
| Brier any-minutes (lower) | 0.1153706 | 0.1079116 | **+6.4653%** |
| Brier 60-plus (lower) | 0.1068164 | 0.1000459 | **+6.3384%** |
| Spearman-p60 (higher) | 0.6908998 | 0.7007144 | **+1.4205%** |

So V2 is a genuine, all-metric improvement over V1, and the starter-ranking regression V1 showed
is partially recovered (−2.49% → −1.10% vs the best baseline). It is simply not recovered far
enough to clear the gate. This is diagnostic evidence for the next structural step, not a verdict.

## Reliability (overall; report-only, gates nothing)

Reliability is read from `contract.scoring_calibration`. The contract fixes ten buckets on the
edges `[0.0 … 1.0]` in 0.1 steps, left-closed/right-open except the final bucket right-closed.
Each bucket carries a count `n`. `pred` is the mean predicted probability in the bucket; `obs` is
the observed rate. **Reliability curves are report-only in this contract; there is no post-hoc
tolerance on them and they gate nothing.** The calibration error is stated, not glossed as
"calibrated."

### Candidate V2 — any-minutes margin (`reliability_any_minutes`; total_n = 133,964)

| bucket | n | pred | obs |
|---|---:|---:|---:|
| [0.0, 0.1) | 9,846 | 0.0712 | 0.0180 |
| [0.1, 0.2) | 50,027 | 0.1219 | 0.0484 |
| [0.2, 0.3) | 7,297 | 0.2465 | 0.1923 |
| [0.3, 0.4) | 6,477 | 0.3596 | 0.4155 |
| [0.4, 0.5) | 5,816 | 0.4419 | 0.4347 |
| [0.5, 0.6) | 8,637 | 0.5604 | 0.5920 |
| [0.6, 0.7) | 6,255 | 0.6605 | 0.7786 |
| [0.7, 0.8) | 10,166 | 0.7564 | 0.8355 |
| [0.8, 0.9) | 29,443 | 0.8454 | 0.8958 |
| [0.9, 1.0] | 0 | — | — |

### Candidate V2 — 60-plus margin (`reliability_60_plus`; total_n = 133,964)

| bucket | n | pred | obs |
|---|---:|---:|---:|
| [0.0, 0.1) | 68,024 | 0.0789 | 0.0347 |
| [0.1, 0.2) | 11,656 | 0.1437 | 0.0964 |
| [0.2, 0.3) | 7,070 | 0.2494 | 0.2150 |
| [0.3, 0.4) | 7,510 | 0.3519 | 0.3909 |
| [0.4, 0.5) | 4,806 | 0.4515 | 0.5060 |
| [0.5, 0.6) | 6,781 | 0.5470 | 0.5860 |
| [0.6, 0.7) | 6,706 | 0.6543 | 0.7554 |
| [0.7, 0.8) | 6,445 | 0.7507 | 0.8065 |
| [0.8, 0.9) | 14,966 | 0.8166 | 0.8687 |
| [0.9, 1.0] | 0 | — | — |

**Calibration error (state it, do not call the model calibrated).** Across the non-empty buckets,
the mean absolute `pred − obs` gap is **0.0581** (any-minutes, 9 buckets — the top bucket is empty
because V2 never predicts P(any) ≥ 0.9) and **0.0519** (60-plus, 9 buckets). The largest
single-bucket gap is **0.1181** (any-minutes, `[0.6, 0.7)`: predicts 0.6605, observed 0.7786, an
under-prediction). The pattern is the same shape as V1 and the position prior — **over-prediction
in the low-probability buckets** (`[0.1, 0.2)` gap +0.0735; the cold-start and bench cohorts are
assigned too much playing probability) combined with under-prediction in the mid-high buckets.
This is not corrected by recency (recency moves mass by recency, not toward calibration), and it
gates nothing. The mean absolute gap is slightly larger than V1's (0.0443 any / 0.0463 60+ over 10
and 9 buckets respectively); the two are not directly comparable because V2 empties the top
any-minutes bucket, but the calibration is in the same weak band and is reported here as such.

## Reporting notes

This run reports the six registered dimensions (fold, season, position, home_away,
transfer_status, player_history_cohort) and the counts predictions, exclusions, cold_starts. It
reports **no `starts`-based slice**. The contract requires that any `starts`-based slice exclude
2021-22, whose `starts` column is entirely NULL — treating that NULL as zero is forbidden. That
rule is respected by omission here.

## Caveats

- **Unversioned historical target roster.** The historical target roster is the archive proxy
  projected from the target rows (`target_roster.historical_roster_status:
  archive_proxy_unversioned_at_real_deadline`). The archive does not version player registration,
  position, or club at the real FPL deadline, so this run makes **no claim** that membership,
  position, or club were known at the real deadline. Live/prospective Stage B work must select
  entities from a versioned registry whose `known_at <= as_of` before the model sees them, and may
  not reuse this proxy to claim historical lift.
- **First-kickoff cutoff is an unversioned proxy.** Each fold's `as_of` is the first kickoff
  across every player row in the predicted gameweek. It excludes every outcome in that gameweek
  under `kickoff_time < as_of` but is not evidence that schedule, postponement, or availability
  were known at the real deadline.
- **Real-deadline knowledge-time validity is unproven.** This is a development run on the frozen
  historical archive under the two proxies above; it is **not** a real-deadline validation.
- **Development evidence, overfit by construction.** The archive shaped the recency hypothesis (the
  V1 run and the 1.2 regression motivated it), so a historical improvement is necessary but not
  sufficient. The headline number is a development number, not an upper bound.
- **A material share of the log lift is zero-mass removal**, not new signal (see Comparison). The
  bounded guardrails, not the log lift, are what make the result meaningful.
- **The starter-ranking gate is failed on this archive.** Recency narrows V1's gap to the best
  baseline but does not close it, and that is a valid, reportable diagnostic result — not something
  the grid/prior/tie-break was adjusted to fix.
- **No model is promoted.** `combined_promotion_verdict` is null. V2 is judged by no promotion
  gate.

## Verdict

**DEVELOPMENT ONLY. Do not promote.** On this historical archive Candidate V2 is the best of the
five models on all four bounded scored metrics — mean log score 0.72625 (best baseline 1.04916,
+30.78%), RPS 0.29568 (best baseline 0.31901, +7.31%), Brier-any 0.10791 (best baseline 0.11552,
+6.59%), Brier-60+ 0.10005 (best baseline 0.10885, +8.09%) — and improves on Candidate V1 on **all
five** metrics including starter ranking (Spearman 0.70071 vs V1's 0.69090, +1.42%). It is leakage-
safe (0 failures), full coverage (133,964/133,964), and shows no per-season mean-log-score
regression. Recency-weighting is therefore supported as a development diagnostic: it sharpens V1's
ordered-distribution prediction and recovers part of the starter-ordering signal V1 discarded.

**It does not clear the version 1.2 gate, because of the starter-ranking criterion.** V2's
aggregate `spearman_p60_within_position_gameweek` (0.70071) regresses 1.0998% against the best
baseline `last_observed_player_minutes` (0.70851), so it fails
`maximum_spearman_p60_relative_regression: 0.0`. Nine of ten development diagnostics pass; this one
fails. The one-hot last-observed prediction still ranks who starts and plays 60+ slightly better
than any trailing-window candidate has yet matched.

**The reason it is not promoted is not the failed gate alone — it is the unversioned proxies,
stated even though four of five scored criteria pass.** The historical target roster is
`archive_proxy_unversioned_at_real_deadline` and the cutoff is the first-kickoff proxy, so no
historical number — however large the lift — can establish real-deadline knowledge-time validity.
The verdict is fixed in advance: development-only, no promotion, regardless of the numbers. This
is stated explicitly even though V2 dominates every baseline on the bounded scores.

Per the pre-registration, V2 is left as committed and is **not** retuned after this result: the
`(decay, alpha)` grids, the window-5, the fallback `(1.0, 5.0)`, the tie-break, the priors, the
estimator, and the 1.2 gate are all frozen. Candidate V1's frozen evidence
([`evidence/phase2-stage-b-candidate-v1-2026-07-30.json`](evidence/phase2-stage-b-candidate-v1-2026-07-30.json))
is byte-identical and was not re-run, re-scored, or re-judged. The honest forward signal from this
run is twofold: recency is a real improvement over equal-weight shrinkage (selected in 100% of
selectable folds), and the remaining starter-ranking gap — plus the un-rescaled transferred-player
slice — name the next structural hypotheses for separately pre-registered candidates evaluated
against prospective 2026/27 data from a versioned registry, the only honest path to promotion.
