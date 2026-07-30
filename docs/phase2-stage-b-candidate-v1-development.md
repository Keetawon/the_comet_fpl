# Candidate V1 development result (Stage B player minutes)

> **DEVELOPMENT ONLY — NOT A PROMOTION RESULT.** This is the single historical development
> evaluation pre-registered for Stage B Candidate V1 (`shrunk_trailing_5_player_minutes_v1`).
> It is not a promotion evaluation, V1 is judged by no promotion gate, and no number here is a
> promotion verdict. The historical archive (2021-22 through 2025-26) is **development
> evidence** — it shaped the shrinkage hypothesis via the baseline-only run — not a fresh
> holdout. Prospective 2026/27 data is reserved as the untouched confirmation set and was not
> consumed. The required Stage B baselines remain the Stage B model.

The number is leakage-safe and provenance-bound. The runner refused to start on a dirty
worktree, loaded the contract from one snapshotted read of the config bytes and fingerprinted
exactly those bytes, recorded the candidate-source and archive fingerprints, and re-checked
the worktree, HEAD, config, candidate-source, and database fingerprints after the database was
closed and before printing. Exit code 0 and the provenance below are therefore a trustworthy
record of what was scored. The design and pre-registered frozen grid are fixed in
[`phase2-stage-b-candidate-v1-design.md`](phase2-stage-b-candidate-v1-design.md); the policy is
the additive `stage_b_candidate_v1` block (contract amendment 1.1, which changes none of the
version 1.0 population, bins, baselines, metrics, or gate). The model is
`src/fpl/models/minutes_v1.py`; the development runner is
`src/fpl/validate/dev_minutes_candidate_v1.py`. The baseline-only bar it is measured against is
recorded in [`phase2-stage-b-baseline-development.md`](phase2-stage-b-baseline-development.md).

The unrounded machine-readable source for every number below is
[`evidence/phase2-stage-b-candidate-v1-2026-07-30.json`](evidence/phase2-stage-b-candidate-v1-2026-07-30.json)
(schema `stage_b_candidate_v1_development/v1`). Values here are rounded for readability (log/SE/
RPS/Brier to 5 d.p.; PIT-80 and reliability means/rates to 4 d.p.); the JSON holds the unrounded
values. Empty reliability buckets carry `null` and are shown as `—`, never as a fabricated zero.

## Identity

| Field | Value |
|---|---|
| Model | `shrunk_trailing_5_player_minutes_v1` (development-only) |
| Config | `stage_b_candidate_v1`, contract version `1.1` (additive amendment; v1.0 frozen) |
| Evaluated under commit | `b8e354fd5a0d706d9e350b5c002a1fde0b921f76` (frozen before the run; worktree clean, revalidated before print) |
| Config fingerprint | `bd0a4b0d910c94eb05ab2b7f52474ae5499c11202e515af8b88a90b1bd148438` |
| Candidate-source fingerprint | `4b793097736aa3fadc8fa08458d0642f5ed872530a5bc588e47ca408168a5116` (`src/fpl/models/minutes_v1.py`) |
| Archive fingerprint | `c37aa58c41bc68b89656547eb1ee790d917c57a7497713d6b02d0f02f1414418` (`data/fpl.duckdb`) |
| Seed | `202627` (contract `training.seed`; also the randomised-PIT seed) |
| Run window (UTC) | `2026-07-30T01:17:39Z` → `2026-07-30T01:21:36Z` |
| Seasons | 2021-22, 2022-23, 2023-24, 2024-25, 2025-26 (complete archive) |
| Command | `python -m fpl.validate.dev_minutes_candidate_v1` (exit code 0) |

## Population

| Count | Value |
|---|---|
| Observed gameweek folds | **181** (one per observed gameweek; 2022-23 has no GW7) |
| Folds by season | 2021-22 = 30, 2022-23 = 37, 2023-24 = 38, 2024-25 = 38, 2025-26 = 38 |
| Eligible predictions | **133,964** player-fixtures (`(season, code, fixture)` grain) |
| Scored predictions | 133,964 (exclusions 0; prediction coverage 1.000) |
| Cold starts | 27,971 (identical across all five models; `no_prior` + `no_positive` cohorts) |
| Leakage failures | 0 (`assert_no_minutes_leakage` held in every fold) |

The development runner reuses the Stage B harness unchanged and fits Candidate V1 inside every
fold on the **same validated history** the baselines use, so V1 is scored on exactly the same
eligible rows as every baseline (`comparison_population: same_eligible_predictions`). The
harness raises if any model's prediction count drifts from the eligible population, so identical
rows is structural, not aspirational.

## Required baselines and Candidate V1 (overall)

Lower log, RPS, Brier-any, and Brier-60+ are better. `Spearman` is within-`(season, gw,
position)` rank of the 60-plus margin (higher is better; report-only). `PIT80` is the
randomised-PIT band coverage (nominal 0.80); `|err|` is `|0.80 − PIT80|`. `n`/`excl`/`cold` are
prediction, exclusion, and cold-start counts. The best (lowest) value in each scored column is
bolded.

| model | log | SE | RPS | bAny | b60+ | PIT80 | \|err\| | Spearman | cover | n | excl | cold |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **shrunk_trailing_5_player_minutes_v1** | **0.74198** | 0.00259 | **0.31396** | **0.11537** | **0.10682** | 0.8249 | 0.0249 | 0.6909 | 1.000 | 133,964 | 0 | 27,971 |
| position_minutes_frequency | 1.04916 | 0.00196 | 0.59531 | 0.23766 | 0.20115 | 0.8101 | 0.0101 | — | 1.000 | 133,964 | 0 | 27,971 |
| trailing_5_team_position_minutes | 1.12715 | 0.00501 | 0.58225 | 0.23134 | 0.19734 | 0.7981 | 0.0019 | 0.1285 | 1.000 | 133,964 | 0 | 27,971 |
| trailing_5_player_minutes | 3.12642 | 0.02248 | 0.31901 | 0.11552 | 0.10885 | 0.7342 | 0.0658 | 0.7022 | 1.000 | 133,964 | 0 | 27,971 |
| last_observed_player_minutes | 7.02586 | 0.03285 | 0.38054 | 0.13365 | 0.12650 | 0.5990 | 0.2010 | 0.7085 | 1.000 | 133,964 | 0 | 27,971 |

## Comparison against the baselines (development diagnostics, NOT a gate)

The contract ranks on the primary metric, mean log score, so the registered comparator is the
best required baseline by log score: `position_minutes_frequency` (1.04916). A promotion
candidate would need mean log score **≤ about 1.03867** to clear the 1% aggregate lift gate.
Candidate V1 reaches **0.74198**, a **+29.2787%** lift over that comparator. **That figure is
not a verdict: V1 is judged by no gate, and the reason it is not promoted is the unversioned
historical proxies, not the score (see Verdict).**

The four baselines have **complementary failure modes**, which is why a single headline lift
against the log-score comparator misrepresents the result. The full four-baselines ×
four-metrics picture is:

| baseline | mean log score | RPS | Brier any | Brier 60+ | Spearman p60 |
|---|---:|---:|---:|---:|---:|
| `position_minutes_frequency` | **1.0491566551300036** | 0.5953141730482708 | 0.2376592347949081 | 0.2011472062545267 | null (group-constant) |
| `trailing_5_team_position_minutes` | 1.1271469209895286 | 0.5822460261372097 | 0.2313357493730081 | 0.1973358755799989 | 0.128457864583993 |
| `trailing_5_player_minutes` | 3.1264177104931354 | **0.3190106444147852** | **0.1155239635780142** | **0.1088506158124824** | 0.7021940329513104 |
| `last_observed_player_minutes` | 7.0258624391112665 | 0.3805442840493138 | 0.1336469501846979 | 0.1264973467750296 | **0.7085065087471287** |

`position_minutes_frequency`, the log-score comparator, is the **worst** of the four on RPS
(0.59531), on Brier-any (0.23766), and on Brier-60+ (0.20115), and its Spearman is structurally
**undefined** (`null`) because it emits an identical four-bin prediction for every player in a
`(season, gw, position)` group — it carries no within-group ordering information at all. The
player-level baselines (`trailing_5_player`, `last_observed`) already carried the strong
ordered-distribution signal — `trailing_5_player` is best on RPS and both Brier margins — and
they lost on mean log score **only** because raw empirical frequencies emit literal zero
probabilities that hit the contract's `1e-12` log floor. Each such miss costs `−log(1e-12) ≈
27.6`, which is why `last_observed_player_minutes` scores 7.03 despite being the best within-group
ranker: a single missed one-hot prediction dominates its average.

**A material share of Candidate V1's log-score lift is therefore the removal of zero-probability
mass, not newly discovered signal.** The shrinkage estimator `p_k = (c_k + alpha·q_k)/(n + alpha)`
mixes in the position prior `q`, which is never zero, so V1 emits no literal zeros — and a
finite distribution beats a `1e-12`-floored one on log score almost by construction. Quoting the
+29% log lift against the position prior without this caveat would overstate the result.

**The guardrails are what make the result meaningful.** RPS and the two Brier margins are
bounded proper scores that are *not* distorted by the floor, so they measure real
ordered-distribution accuracy. The honest test is therefore the candidate against the baselines'
**best** value on each guardrail, not against the log-score comparator:

| Guardrail (lower better) | Candidate V1 | Best baseline (which) | Lift vs best |
|---|---:|---:|---:|
| Mean RPS | 0.3139588604416710 | 0.3190106444147852 (`trailing_5_player_minutes`) | **+1.5836%** |
| Brier any-minutes | 0.1153705728215893 | 0.1155239635780142 (`trailing_5_player_minutes`) | **+0.1328%** |
| Brier 60-plus | 0.1068163524088986 | 0.1088506158124824 (`trailing_5_player_minutes`) | **+1.8689%** |
| Mean log score | 0.7419767497490626 | 1.0491566551300036 (`position_minutes_frequency`) | +29.2787% |

Candidate V1 improves on the **best** baseline value of every metric **except the
within-position Spearman-p60 starter ranking, where it regresses (0.69090 vs 0.70851 best
baseline, −2.49%)**, including the three bounded guardrails. The improvement over the strongest
player-history baseline (`trailing_5_player`) is small on RPS/Brier (+0.13% to +1.87%) but real
and in the same direction on all three: the shrinkage retains the player signal while removing the
log-score catastrophe. Against the position prior it improves on all four metrics simultaneously.
So V1 is not merely a numerically-finite `trailing_5_player`; it is a genuine, if modest,
improvement on the strongest ordered-distribution baseline, and the shrinkage hypothesis is
supported on this development archive — **as a development diagnostic, not a promotion verdict.**
The Spearman regression is the one place V1 gives back signal: it ranks who starts and plays 60+
slightly worse than `last_observed_player_minutes`, and that is exactly the dimension a later
amendment (1.2) makes into a gate.

## Gate criteria (each a development diagnostic; never combined into a verdict)

Each frozen gate condition is reported as its own labelled check against the registered
thresholds read from the unchanged `promotion` block. The aggregate RPS/Brier non-regression
guardrails compare against the log-score comparator (`position_minutes_frequency`), as the
runner computes them; the harder best-per-metric comparison is the table above.

| Gate criterion | Threshold | Observed | Result |
|---|---|---|---|
| `minimum_primary_relative_lift` | ≥ 0.01 | log lift +29.2787% (0.74198 vs 1.04916) | PASS |
| `maximum_ranked_probability_score_relative_regression` | ≤ 0.0 | RPS lift +47.2617% (0.31396 vs 0.59531; regression 0.0%) | PASS |
| `maximum_brier_relative_regression_any_minutes` | ≤ 0.0 | Brier-any lift +51.4555% (0.11537 vs 0.23766; regression 0.0%) | PASS |
| `maximum_brier_relative_regression_60_plus` | ≤ 0.0 | Brier-60+ lift +46.8964% (0.10682 vs 0.20115; regression 0.0%) | PASS |
| `pit_interval_80_maximum_absolute_error` | ≤ 0.05 | 0.0249 | PASS |
| `minimum_prediction_coverage` | ≥ 1.0 | 1.0000 | PASS |
| `minimum_fold_count` | ≥ 181 | 181 | PASS |
| `require_no_season_mean_log_score_regression` | true | 0 of 5 seasons regress | PASS |
| `require_zero_leakage_failures` | true | 0 leakage failures | PASS |

All nine development diagnostics pass on this historical archive. `combined_promotion_verdict`
is **null** in the evidence record: these checks are never combined into a production promotion
verdict, and the verdict is fixed in advance as development-only (see Verdict).

## Slices (all six registered reporting dimensions)

Lift is Candidate V1 vs `position_minutes_frequency` (the log-score comparator) on mean log
score, unless noted. `n` is the slice prediction count.

### By fold

181 folds (30/37/38/38/38 by season). Per-fold scores for all five models are in the evidence
JSON (`harness.by_fold`); candidate predictions sum to 133,964 across the 181 folds.

### By season (mean log score)

| season | Candidate V1 | baseline | lift | n |
|---|---:|---:|---:|---:|
| 2021-22 | 0.75539 | 1.01102 | +25.2844% | 20,704 |
| 2022-23 | 0.76948 | 1.08768 | +29.2548% | 26,505 |
| 2023-24 | 0.72244 | 1.02841 | +29.7517% | 29,725 |
| 2024-25 | 0.76700 | 1.08412 | +29.2521% | 27,283 |
| 2025-26 | 0.70471 | 1.03003 | +31.5840% | 29,747 |

No season regresses. The candidate's per-season RPS and Brier also improve on the comparator in
every season (e.g. 2025-26: RPS 0.29065 vs 0.57320; Brier-any 0.10656 vs 0.23446).

### By position (mean log score)

| position | Candidate V1 | baseline | lift | n |
|---|---:|---:|---:|---:|
| GK | 0.26960 | 0.59556 | +54.7318% | 14,890 |
| FWD | 0.79206 | 1.13216 | +30.0400% | 16,010 |
| MID | 0.83339 | 1.16027 | +28.1727% | 58,386 |
| DEF | 0.76200 | 1.02538 | +25.6862% | 44,678 |

The candidate improves on the position prior in every position; the gain is largest for
goalkeepers, whose minutes are the most stable (so player history is most informative).

### By home/away (mean log score)

| venue | Candidate V1 | baseline | lift | n |
|---|---:|---:|---:|---:|
| home | 0.73745 | 1.04688 | +29.5574% | 66,979 |
| away | 0.74650 | 1.05143 | +29.0013% | 66,985 |

### By transfer status (mean log score)

| transfer status | Candidate V1 | baseline | lift | n |
|---|---:|---:|---:|---:|
| same_team_code_as_last_observed_fixture | 0.73807 | 1.04948 | +29.6723% | 132,390 |
| no_prior_player_fixture | 0.95281 | 0.95281 | +0.0000% | 1,207 |
| changed_team_code_since_last_observed_fixture | 1.45704 | 1.25096 | **−16.4733%** | 367 |

**The transferred-player slice regresses, and it is reported plainly, not buried.** For the 367
predictions (0.27% of the population) where a player changed club since his last observed
fixture, Candidate V1 (1.45704) is **worse than the position prior** (1.25096) by −16.47%. The
candidate shrinks the player's trailing-five history toward the position prior; for a transferred
player that trailing history is from the **old** club, and V1 does not rescale minutes to the
destination club. The result says that for transferred players, ignoring the stale history
entirely (the pure position prior) is better than shrinking it in. This is the one regime where
the shrinkage hypothesis hurts. There is no per-transfer-status gate (the gate is aggregate plus
per-season only), so this does not change the aggregate diagnostic outcome — but it is the
single clearest target for a separately named future candidate, and it is the minutes-model
analogue of the contract's rule that a transferred player's expectation must be rescaled to the
destination club. The `no_prior_player_fixture` slice ties the comparator exactly (+0.0000%) by
construction: with `n = 0` the estimator returns exactly the position prior `q`, which **is**
the comparator.

### By player-history cohort (mean log score)

| cohort | Candidate V1 | baseline | lift | n |
|---|---:|---:|---:|---:|
| prior_player_fixtures_no_positive_minutes | 0.17851 | 0.53520 | +66.6468% | 26,764 |
| prior_positive_minutes | 0.88186 | 1.18003 | +25.2684% | 105,993 |
| no_prior_player_fixture | 0.95281 | 0.95281 | +0.0000% | 1,207 |

The candidate helps most where a player has prior fixtures but no positive minutes (the bench
regulars): their zero-heavy history, shrunk toward the position prior, predicts non-appearance
far better than the position prior alone. `no_prior_player_fixture` ties by construction (n = 0).

## Reliability (overall; report-only, gates nothing)

Reliability is read from `contract.scoring_calibration`. The contract fixes ten buckets on the
edges `[0.0 … 1.0]` in 0.1 steps, left-closed/right-open except the final bucket right-closed.
Each bucket carries a count `n`. `pred` is the mean predicted probability in the bucket; `obs` is
the observed rate. **Reliability curves are report-only in this contract; there is no
post-hoc tolerance on them and they gate nothing.** The calibration error is stated, not glossed
as "calibrated."

### Candidate V1 — any-minutes margin (`reliability_any_minutes`; total_n = 133,964)

| bucket | n | pred | obs |
|---|---:|---:|---:|
| [0.0, 0.1) | 16,450 | 0.0712 | 0.0261 |
| [0.1, 0.2) | 40,080 | 0.1262 | 0.0408 |
| [0.2, 0.3) | 11,202 | 0.2577 | 0.2681 |
| [0.3, 0.4) | 1,089 | 0.3436 | 0.3067 |
| [0.4, 0.5) | 9,666 | 0.4156 | 0.4483 |
| [0.5, 0.6) | 10,117 | 0.5537 | 0.5910 |
| [0.6, 0.7) | 9,349 | 0.6862 | 0.7393 |
| [0.7, 0.8) | 8,513 | 0.7396 | 0.8132 |
| [0.8, 0.9) | 23,845 | 0.8400 | 0.8921 |
| [0.9, 1.0] | 3,653 | 0.9053 | 0.8886 |

### Candidate V1 — 60-plus margin (`reliability_60_plus`; total_n = 133,964)

| bucket | n | pred | obs |
|---|---:|---:|---:|
| [0.0, 0.1) | 65,051 | 0.0782 | 0.0343 |
| [0.1, 0.2) | 9,192 | 0.1266 | 0.0465 |
| [0.2, 0.3) | 12,218 | 0.2320 | 0.2668 |
| [0.3, 0.4) | 9,864 | 0.3718 | 0.4040 |
| [0.4, 0.5) | 836 | 0.4771 | 0.5311 |
| [0.5, 0.6) | 8,851 | 0.5240 | 0.5490 |
| [0.6, 0.7) | 9,802 | 0.6602 | 0.7054 |
| [0.7, 0.8) | 8,138 | 0.7784 | 0.8435 |
| [0.8, 0.9) | 10,012 | 0.8255 | 0.8618 |
| [0.9, 1.0] | 0 | — | — |

**Calibration error (state it, do not call the model calibrated).** Across the non-empty
buckets, the mean absolute `pred − obs` gap is **0.0443** (any-minutes, 10 buckets) and **0.0463**
(60-plus, 9 buckets; the top bucket is empty because V1 never predicts P(60+) ≥ 0.9). The largest
single-bucket gap is **0.0853** (any-minutes, `[0.1, 0.2)`: predicts 0.1262, observed 0.0408). The
consistent pattern is **over-prediction in the low-probability buckets**: the candidate (like the
position prior it shrinks toward) assigns too much playing probability to the players it considers
least likely to appear — the cold-start and bench cohorts. This is the same shape as the position
prior's reliability and is not corrected by the shrinkage. It is a real calibration weakness,
reported here, and it gates nothing.

## Fold-local parameter selections

`alpha` is the only selected parameter, from the frozen grid `[1.0, 2.0, 5.0, 10.0, 20.0]`, by
the six-observed-gameweek inner walk-forward with at least eight earlier observed gameweeks.

| Parameter | Selection (of 181 folds) |
|---|---|
| `selected_alpha` | **2.0 = 154**, 1.0 = 21, 5.0 = 6 |
| `used_inner_holdout` | True = 175, False = 6 |
| `inner_holdout_observed_gameweeks` | 6 = 175, 0 = 6 (fallback) |
| `inner_training_observed_gameweeks` | range 2 … 182 (one per fold; grows with the expanding window) |

The inner holdout ran in 175 folds; the 6 folds without it are the earliest (fewer than 14
observed gameweeks of history), which take the declared fallback `alpha = 5.0`. The modal choice
is **alpha = 2.0** (85% of folds): light shrinkage toward the position prior, retaining most
player signal while mixing in enough prior mass to avoid literal zeros.

**Boundary selections (diagnostics, not authorisation to widen the grid).** Recorded as evidence
for a future structural hypothesis, not as permission to change V1 after seeing this result:

- **`alpha = 1.0` (the grid floor) in 21 of 181 folds.** The inner walk-forward selected the
  smallest grid value in those folds, i.e. it wanted the player history to dominate with minimal
  prior. Because 1.0 is the floor, a true optimum below 1.0 (even less shrinkage) could not be
  expressed and would need a separately named, committed policy to probe. This is a flagged
  lower-boundary hit.
- **`alpha = 20.0` (the grid ceiling) was selected in 0 folds.** No upper-boundary hit; the inner
  objective never wanted shrinkage that strong.
- The 6 fallback folds (`alpha = 5.0`) are mid-grid by construction and are not boundary hits.

The frozen grid, prior, estimator, fallback, and thresholds are unchanged; V1 is not tuned again
after this result.

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
- **Development evidence, overfit by construction.** The archive shaped the shrinkage hypothesis
  (the baseline run motivated it), so a historical improvement is necessary but not sufficient.
  The headline number is a development number, not an upper bound.
- **A material share of the log lift is zero-mass removal**, not new signal (see Comparison). The
  bounded guardrails, not the log lift, are what make the result meaningful.
- **No model is promoted.** `combined_promotion_verdict` is null. V1 is judged by no promotion
  gate.

## Verdict

**DEVELOPMENT ONLY. Do not promote.** On this historical archive Candidate V1 improves on the
best required baseline value of every metric **except the within-position Spearman-p60 starter
ranking, where it regresses (0.69090 vs 0.70851 best baseline, −2.49%)**: mean log score 0.74198
(best baseline 1.04916, +29.28%), RPS 0.31396 (best baseline 0.31901, +1.58%), Brier-any 0.11537
(best baseline 0.11552, +0.13%), Brier-60+ 0.10682 (best baseline 0.10885, +1.87%), with PIT-80
band coverage 0.8249 (|error| 0.0249), full prediction coverage (133,964/133,964), zero leakage
failures, and no per-season mean-log-score regression. All nine development diagnostics pass under
the contract version (1.1) this run was scored against.

**The reason it is not promoted is not the score — it is the unversioned proxies.** The
historical target roster is `archive_proxy_unversioned_at_real_deadline` and the cutoff is the
first-kickoff proxy, so no historical number — however large the lift — can establish
real-deadline knowledge-time validity. The verdict is fixed in advance: development-only, no
promotion, regardless of the numbers. This is stated explicitly even though every gate criterion
is satisfied on this archive.

The shrinkage hypothesis is supported as a development diagnostic: it retains the player
ordered-distribution signal while removing the log-score catastrophe of raw empirical
frequencies, and it strictly improves on the strongest bounded-score baseline. Its honest weak
spot is the transferred-player slice (−16.47%), where un-rescaled stale history hurts. A genuine
promotion attempt would be a separately pre-registered candidate evaluated against prospective
2026/27 data as it accrues under the unchanged promotion gate, selected from a versioned player
registry — that confirmation set was not consumed here and remains the only honest path to
promotion. Per the pre-registration, V1 is left as committed and is not tuned again.

## Note added under amendment 1.2 (not a re-run)

> This note records how a later contract amendment would view V1's frozen numbers. It does **not**
> re-run, re-score, or re-judge Candidate V1. V1 was scored once, under contract version 1.1, and
> its evidence
> ([`evidence/phase2-stage-b-candidate-v1-2026-07-30.json`](evidence/phase2-stage-b-candidate-v1-2026-07-30.json))
> is byte-identical. V1's verdict — development-only, not promoted — is unchanged, and its reason
> is still the unversioned proxies, not any score.

Amendment 1.2 (contract version 1.2) tightens the Stage B guardrails for **future** candidates
only. Two changes are relevant to how V1's frozen numbers would be read under the later gate:

1. **Each bounded guardrail is now measured against the best baseline value of its own metric.**
   Under 1.1 the RPS/Brier guardrails were measured against the single best-by-log-score baseline
   (`position_minutes_frequency`), which is the *worst* baseline on RPS and both Brier margins.
   Under 1.2 V1's still-passing RPS/Brier guardrails would be measured against the harder
   `trailing_5_player_minutes` bar — RPS +1.58%, Brier-any +0.13%, Brier-60+ +1.87% — and they
   remain improvements, so those three would still pass.
2. **A new starter-ranking gate (`maximum_spearman_p60_relative_regression: 0.0`) exists.** V1's
   aggregate Spearman-p60 is 0.69090 against the best baseline 0.70851 (`last_observed_player_minutes`;
   `position_minutes_frequency` is group-constant and excluded), a −2.49% regression. Under 1.2 V1
   would **additionally fail** this one new gate.

This changes nothing about V1: it was never a promotion (the block is the unversioned proxies, not
any score), it is not re-evaluated, and `candidates_evaluated_before_amendment` for 1.2 is honestly
recorded as 1. The annotation exists so the frozen 1.1 record is not misread as "V1 would pass a
later, harder gate" — on starter ranking it would not, and that regression is the diagnostic
motivation for the recency-weighted successor.
