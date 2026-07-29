# Phase 2 Stage B baseline development result

> **COMPLETE BASELINE-ONLY DEVELOPMENT AND CALIBRATION RECORD — NOT A CANDIDATE EVALUATION, NOT
> A PROMOTION GATE, NOT A PROMOTION VERDICT, NOT A REAL-DEADLINE POINT-IN-TIME VALIDATION, AND
> NOT A FRESH HOLDOUT.** This is the **baseline-only** full-archive run under the frozen contract
> version `1.0`: the four frozen Stage B baselines fitted and predicted inside every
> observed-gameweek fold, with **no candidate** fitted, **no promotion gate** executed, **no
> Monte Carlo** (Stage B is a closed-form four-bin marginal), and **no parameter tuning**. It
> records the development bar a future Stage B candidate would be measured against, plus the full
> calibration (reliability) record for those baselines. The historical archive (2021-22 through
> 2025-26) is **development evidence**, not a fresh holdout; the headline number is a development
> number, **not an upper bound** of any kind.

The harness (`src/fpl/validate/minutes_harness.py`) and the four frozen baselines
(`src/fpl/validate/minutes_baselines.py`) are unchanged from the implementation slice recorded in
[`phase2-stage-b-implementation.md`](phase2-stage-b-implementation.md); the frozen contract is
[`config/phase2_evaluation.yaml`](../config/phase2_evaluation.yaml) at version `1.0`. This document
records the result of the corrected full-archive baseline run; it does **not** change the contract,
baselines, metrics, or gate.

The unrounded machine-readable source for every number below is the committed evidence record
[`evidence/phase2-stage-b-baseline-2026-07-29.json`](evidence/phase2-stage-b-baseline-2026-07-29.json)
(schema `stage_b_corrected_evidence/v1`; SHA-256 recorded in the Identity table). Values in the
tables here are rounded for readability (log/SE/RPS/Brier to 5 d.p., PIT-80/rho/reliability means
and observed rates to 4 d.p.); the evidence JSON holds the unrounded values. Empty reliability
buckets carry `null` in the JSON and are shown here as `—` (unavailable), never as a fabricated zero.

## Identity

| Field | Value |
|---|---|
| Run type | Baselines-only development run (no candidate, no gate, no Monte Carlo, no tuning) |
| Contract | `config/phase2_evaluation.yaml`, version `1.0` (frozen; no amendments; zero candidates precede it) |
| Baselines | `position_minutes_frequency`, `last_observed_player_minutes`, `trailing_5_player_minutes`, `trailing_5_team_position_minutes` |
| Run repository HEAD | `ce83e36e3ebdee8ea6e8df3b969ec9eb97da53b2` (branch `agent/phase2-minutes-contract`; worktree clean before and after) |
| Harness implementation commit | `057330db1f4bfc9a9ced21b54533ad1f6b9fd0a8` (the Stage B minutes-harness implementation commit; an ancestor of the run HEAD) |
| Evidence record (committed) | [`evidence/phase2-stage-b-baseline-2026-07-29.json`](evidence/phase2-stage-b-baseline-2026-07-29.json) — SHA-256 `9a3185487635a35b4932b1ff69781486859d9ecb858e7ab5e0809dd4deec3011` |
| Runner script | `D:\tmp\stage_b_corrected_runner.py` (one-shot, read-only; not committed; execution provenance only — not the durable evidence source) |
| Archive fingerprint (SHA-256) | `c37aa58c41bc68b89656547eb1ee790d917c57a7497713d6b02d0f02f1414418` (`data/fpl.duckdb`) — unchanged before, after, and as currently measured |
| Config fingerprint (SHA-256) | `e43e32016f40f4aa5c39482bfad6a5df07effc75033beac8f278def84d81f9f9` (`config/phase2_evaluation.yaml`) — unchanged before and after |
| Seed | `202627` (contract `training.seed`; also the randomised-PIT seed) |
| Run window (UTC) | `2026-07-29T10:26:58Z` → `2026-07-29T10:28:51Z` |
| Wall time | `113.354 s` |
| Seasons | 2021-22, 2022-23, 2023-24, 2024-25, 2025-26 (complete archive) |

The run HEAD and the harness implementation commit are deliberately recorded separately: the run
HEAD pins the exact repository state the scores were produced against (it includes the prior
provisional-baseline documentation commit), while the harness implementation commit pins the code
that performs the scoring. The runner opened the database read-only; the DB and config SHA-256 are
identical before, after, and as currently measured, and the worktree was clean both before and
after.

## Population

| Count | Value |
|---|---|
| Observed gameweek folds | **181** (one per observed gameweek; 2022-23 has no GW7) |
| Folds by season | 2021-22 = **30**, 2022-23 = **37**, 2023-24 = **38**, 2024-25 = **38**, 2025-26 = **38** |
| Eligible predictions | **133,964** player-fixtures (`(season, code, fixture)` grain) |
| Exclusions | **0** for every baseline (every eligible row received a prediction) |
| Prediction coverage | **1.000** for every baseline |
| Leakage failures | **0** (`assert_no_minutes_leakage` held in every fold) |
| Cold starts | **27,971** (combined `no_prior_player_fixture` + `prior_player_fixtures_no_positive_minutes` cohorts; identical across baselines) |
| Baseline population | all four frozen baselines on the **same** eligible rows |

The fold accounting matches the contract's expectation: 189 observed gameweeks minus the 8
cross-season warmup (`minimum_observed_gameweeks`) = 181 folds, with only the earliest season
(2021-22) losing gameweeks (38 → 30). The eligible population equals the registered FPL player
population on the 181 predicted folds (every `mart_fact_player_fixture` row with non-NULL `minutes`,
including zero-minute rows); the warmup gameweeks of 2021-22 account for the difference between the
138,707 archive-wide eligible keys and the 133,964 scored predictions.

## Baselines (overall)

Lower `log`, `RPS`, `bAny`, and `b60` are better; the best (lowest) value in each of those columns
is bolded. `PIT80` is the randomised-PIT band coverage
(contract `pit_interval_80_maximum_absolute_error` guards `|0.80 − PIT80| ≤ 0.05`); nominal is
0.80. `rho` is `spearman_p60_within_position_gameweek` (report-only, see below). `SE` is the
standard error of the row log scores (`mean_log_score_standard_error`).

| baseline | log | SE | RPS | bAny | b60 | PIT80 | rho |
|---|---:|---:|---:|---:|---:|---:|---:|
| position_minutes_frequency | **1.04916** | 0.00196 | 0.59531 | 0.23766 | 0.20115 | 0.8101 | NaN |
| trailing_5_team_position_minutes | 1.12715 | 0.00501 | 0.58225 | 0.23134 | 0.19734 | 0.7981 | 0.1285 |
| trailing_5_player_minutes | 3.12642 | 0.02248 | **0.31901** | **0.11552** | **0.10885** | 0.7342 | 0.7022 |
| last_observed_player_minutes | 7.02586 | 0.03285 | 0.38054 | 0.13365 | 0.12650 | 0.5990 | 0.7085 |

`position_minutes_frequency` has the lowest mean log score (1.04916) and is therefore the **headline
development bar** — the baseline a future Stage B candidate's aggregate 1% lift would be measured
against (the contract ranks on its primary metric, mean log score). The lift formula is
`(baseline − candidate) / |baseline|`, so a future candidate would need mean log score **≤ about
1.03867** (from the unrounded 1.04916 baseline) to clear the 1% aggregate lift. **No candidate and
no gate were run in this slice**, so 1.03867 is a forward-looking reference figure, not a judgement.

`position_minutes_frequency` is best on mean log score **only**: it is the **worst** of the four on
RPS (0.59531), Brier-any (0.23766), and Brier-60 (0.20115). `trailing_5_player_minutes` is the
mirror image — best (lowest) RPS (0.31901) and both Brier margins (0.11552 / 0.10885) but the
second-highest mean log score (3.12642). Mean log score and RPS/Brier therefore rank these baselines
differently, and **no baseline dominates** across the scores (a baseline is dominant only if it is
best on every relevant score). This is a divergence between the scoring rules rather than a data
mechanism that this run diagnoses: mean log score is unbounded as the realized-bin probability falls
to the 1e-12 floor, whereas RPS and each Brier margin are bounded, so the same misprediction can be
modest under RPS/Brier yet severe under log score. The player-level baselines' higher `rho` is
reported here, not gated.

What a future promotion gate would require (**none of this was exercised by this baseline-only
slice**): against the best eligible baseline on the same eligible predictions, a candidate must clear
**≥ 1% aggregate mean-log-score lift** (≤ about 1.03867) with **no aggregate regression** on RPS, on
Brier-any, or on Brier-60 (each `maximum_*_relative_regression = 0.0`), keep **PIT-80 band coverage
within 0.05 of nominal** (`|0.80 − PIT80| ≤ 0.05`), achieve **full prediction coverage (1.0)** over
**≥ 181 folds** with **zero leakage failures**, and show **no mean-log-score regression in any
reported season**. `spearman_p60_within_position_gameweek` and the reliability curves stay
**report-only**.

## All-season metric record

These are the full per-season reports, including 2024-25 and 2025-26. Within each season all four
baselines run on the **same** `n` and the **same** cold-start cohort. `log`/`SE`/`RPS`/`bAny`/`b60`
to 5 d.p.; `PIT80`/`rho` to 4 d.p.; `rho` shown as `NaN` where the metric is structurally undefined
(see below). The JSON holds the unrounded values.

### 2021-22 — n = 20,704; cold starts = 5,957; 30 folds

| baseline | log | SE | RPS | bAny | b60 | PIT80 | rho |
|---|---:|---:|---:|---:|---:|---:|---:|
| position_minutes_frequency | 1.01102 | 0.00490 | 0.62857 | 0.23771 | 0.21072 | 0.8007 | NaN |
| trailing_5_team_position_minutes | 1.10453 | 0.01344 | 0.61468 | 0.23108 | 0.20649 | 0.7979 | 0.1350 |
| trailing_5_player_minutes | 3.30517 | 0.05883 | 0.35868 | 0.12589 | 0.12068 | 0.7360 | 0.6938 |
| last_observed_player_minutes | 7.33691 | 0.08477 | 0.44822 | 0.15533 | 0.14713 | 0.5916 | 0.6808 |

### 2022-23 — n = 26,505; cold starts = 5,005; 37 folds (no GW7)

| baseline | log | SE | RPS | bAny | b60 | PIT80 | rho |
|---|---:|---:|---:|---:|---:|---:|---:|
| position_minutes_frequency | 1.08768 | 0.00457 | 0.61208 | 0.24174 | 0.20798 | 0.8126 | NaN |
| trailing_5_team_position_minutes | 1.18429 | 0.01221 | 0.60147 | 0.23642 | 0.20548 | 0.7944 | 0.1107 |
| trailing_5_player_minutes | 3.19619 | 0.05092 | 0.32592 | 0.11831 | 0.11091 | 0.7342 | 0.6977 |
| last_observed_player_minutes | 7.34771 | 0.07490 | 0.39508 | 0.13731 | 0.13249 | 0.5885 | 0.6980 |

### 2023-24 — n = 29,725; cold starts = 6,472; 38 folds

| baseline | log | SE | RPS | bAny | b60 | PIT80 | rho |
|---|---:|---:|---:|---:|---:|---:|---:|
| position_minutes_frequency | 1.02841 | 0.00413 | 0.57682 | 0.23411 | 0.19399 | 0.8136 | NaN |
| trailing_5_team_position_minutes | 1.10292 | 0.01069 | 0.55908 | 0.22592 | 0.18848 | 0.7989 | 0.1466 |
| trailing_5_player_minutes | 3.05391 | 0.04731 | 0.30510 | 0.11295 | 0.10261 | 0.7333 | 0.7006 |
| last_observed_player_minutes | 6.66629 | 0.06851 | 0.35335 | 0.12841 | 0.11372 | 0.6074 | 0.7211 |

### 2024-25 — n = 27,283; cold starts = 4,197; 38 folds

| baseline | log | SE | RPS | bAny | b60 | PIT80 | rho |
|---|---:|---:|---:|---:|---:|---:|---:|
| position_minutes_frequency | 1.08412 | 0.00437 | 0.59805 | 0.24101 | 0.20379 | 0.8074 | NaN |
| trailing_5_team_position_minutes | 1.15751 | 0.01078 | 0.58645 | 0.23514 | 0.20033 | 0.7940 | 0.1351 |
| trailing_5_player_minutes | 3.19382 | 0.05015 | 0.32112 | 0.11691 | 0.10989 | 0.7300 | 0.7093 |
| last_observed_player_minutes | 7.38299 | 0.07398 | 0.38772 | 0.13470 | 0.13153 | 0.5878 | 0.7120 |

### 2025-26 — n = 29,747; cold starts = 6,340; 38 folds

| baseline | log | SE | RPS | bAny | b60 | PIT80 | rho |
|---|---:|---:|---:|---:|---:|---:|---:|
| position_minutes_frequency | 1.03003 | 0.00409 | 0.57320 | 0.23446 | 0.19313 | 0.8095 | NaN |
| trailing_5_team_position_minutes | 1.08833 | 0.00956 | 0.56184 | 0.22891 | 0.18980 | 0.7990 | 0.1159 |
| trailing_5_player_minutes | 2.95048 | 0.04653 | 0.29721 | 0.10713 | 0.10406 | 0.7324 | 0.7077 |
| last_observed_player_minutes | 6.55435 | 0.06810 | 0.34108 | 0.11955 | 0.11494 | 0.6110 | 0.7246 |

Per-season `n` sum to 133,964 and per-season cold starts sum to 27,971, matching the overall
counts. `position_minutes_frequency` is the lowest-log baseline in every season individually as well
as overall; `trailing_5_player_minutes` is the lowest-RPS and lowest-Brier baseline in every season.
No baseline is dominant in any season either.

## Why `position_minutes_frequency` reports `rho = NaN`

`spearman_p60_within_position_gameweek` ranks the predicted `P(minutes >= 60)` margin against the
binary observation `minutes >= 60` **within each `(season, gw, position)` group**. The position
prior emits an **identical** four-bin prediction for every player in the same group (it keys on
target position only), so the predicted margin is **constant within the group**: all ranks are tied,
the rank variance is zero, and the Spearman correlation is structurally undefined (`NaN`). The other
three baselines vary their prediction by player (`code`) or by club within the group, so their `rho`
is finite. This is the correct, expected behaviour for a within-group rank metric applied to a
group-constant prediction; it is **report-only and not gated** by any contract threshold. The NaN is
not missing data and not a failure — it records that the position baseline carries no
within-gameweek ordering information, which is exactly the limitation a candidate's player-level
signal would be expected to beat. (The runner serializes this structural `NaN` as JSON `null` for
strict JSON validity; the non-finite-floats coercion is recorded in the evidence.)

## Calibration (overall reliability curves)

Reliability is read from `contract.scoring_calibration` (the typed loader's calibration
definitions; `metrics.calibration` is only the ordered list of metric **names**). The contract
fixes ten buckets on the edges `[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]`, left-closed
and right-open except the final bucket `[0.9, 1.0]` which is right-closed. Each bucket reports `n`,
`mean_predicted`, and `observed_rate` for the two report-only margins `reliability_any_minutes`
(predicted `P(any minutes)` vs observed `minutes > 0`) and `reliability_60_plus` (predicted
`P(minutes >= 60)` vs observed `minutes >= 60`). Reliability curves gate nothing in v1.0; they are
reported for context.

Below are the **overall** curves for all four baselines over all ten buckets (means/rates to 4 d.p.).
`n_any`/`pred_any`/`obs_any` are the any-minutes margin; `n_60`/`pred_60`/`obs_60` are the 60-plus
margin. Empty buckets show `—` for the mean and observed rate. Each baseline's `n_any` buckets sum
to 133,964 and its `n_60` buckets sum to 133,964.

### position_minutes_frequency

| bucket | n_any | pred_any | obs_any | n_60 | pred_60 | obs_60 |
|---|---:|---:|---:|---:|---:|---:|
| [0.0, 0.1) | 0 | — | — | 0 | — | — |
| [0.1, 0.2) | 0 | — | — | 0 | — | — |
| [0.2, 0.3) | 14676 | 0.2633 | 0.2471 | 68542 | 0.2723 | 0.2499 |
| [0.3, 0.4) | 214 | 0.3049 | 0.2804 | 65212 | 0.3344 | 0.3128 |
| [0.4, 0.5) | 117813 | 0.4376 | 0.4224 | 210 | 0.4012 | 0.3857 |
| [0.5, 0.6) | 1261 | 0.5033 | 0.4869 | 0 | — | — |
| [0.6, 0.7) | 0 | — | — | 0 | — | — |
| [0.7, 0.8) | 0 | — | — | 0 | — | — |
| [0.8, 0.9) | 0 | — | — | 0 | — | — |
| [0.9, 1.0] | 0 | — | — | 0 | — | — |

### last_observed_player_minutes

| bucket | n_any | pred_any | obs_any | n_60 | pred_60 | obs_60 |
|---|---:|---:|---:|---:|---:|---:|
| [0.0, 0.1) | 78887 | 0.0000 | 0.1107 | 95236 | 0.0000 | 0.0876 |
| [0.1, 0.2) | 0 | — | — | 0 | — | — |
| [0.2, 0.3) | 135 | 0.2651 | 0.1556 | 611 | 0.2728 | 0.1358 |
| [0.3, 0.4) | 2 | 0.3051 | 0.0000 | 595 | 0.3333 | 0.1630 |
| [0.4, 0.5) | 1063 | 0.4379 | 0.3217 | 1 | 0.4012 | 0.0000 |
| [0.5, 0.6) | 7 | 0.5017 | 0.2857 | 0 | — | — |
| [0.6, 0.7) | 0 | — | — | 0 | — | — |
| [0.7, 0.8) | 0 | — | — | 0 | — | — |
| [0.8, 0.9) | 0 | — | — | 0 | — | — |
| [0.9, 1.0] | 53870 | 1.0000 | 0.8348 | 37521 | 1.0000 | 0.7754 |

`last_observed_player_minutes` is one-hot at the last observed bin when a player has prior
fixtures; rows with no prior fixture fall back to the position prior. Its exact `0.0000` /
`1.0000` predicted margins come from that one-hot last-observed distribution (a player whose last
observed bin had zero minutes is a hard zero, and a hard-one 60-plus prediction specifically means
the last observed bin was ≥ 60 minutes), so its mass concentrates in the edge buckets. The
`0.0000` observed rates on buckets `[0.3, 0.4)` are a tiny-sample artifact (n = 2 and n = 1), not a
model claim.

### trailing_5_player_minutes

| bucket | n_any | pred_any | obs_any | n_60 | pred_60 | obs_60 |
|---|---:|---:|---:|---:|---:|---:|
| [0.0, 0.1) | 58902 | 0.0000 | 0.0378 | 74853 | 0.0000 | 0.0362 |
| [0.1, 0.2) | 9198 | 0.2000 | 0.3193 | 0 | — | — |
| [0.2, 0.3) | 228 | 0.2589 | 0.2018 | 11624 | 0.2042 | 0.2767 |
| [0.3, 0.4) | 117 | 0.3329 | 0.3333 | 672 | 0.3333 | 0.1845 |
| [0.4, 0.5) | 9795 | 0.4041 | 0.4470 | 9152 | 0.4000 | 0.4199 |
| [0.5, 0.6) | 248 | 0.5000 | 0.4395 | 175 | 0.5000 | 0.5486 |
| [0.6, 0.7) | 10068 | 0.6007 | 0.5900 | 9032 | 0.6006 | 0.5384 |
| [0.7, 0.8) | 107 | 0.7500 | 0.6542 | 69 | 0.7500 | 0.6957 |
| [0.8, 0.9) | 13695 | 0.8000 | 0.7355 | 10591 | 0.8000 | 0.6909 |
| [0.9, 1.0] | 31606 | 1.0000 | 0.8938 | 17796 | 1.0000 | 0.8653 |

### trailing_5_team_position_minutes

| bucket | n_any | pred_any | obs_any | n_60 | pred_60 | obs_60 |
|---|---:|---:|---:|---:|---:|---:|
| [0.0, 0.1) | 127 | 0.0690 | 0.2362 | 1419 | 0.0541 | 0.1191 |
| [0.1, 0.2) | 6565 | 0.1845 | 0.1942 | 14553 | 0.1642 | 0.1746 |
| [0.2, 0.3) | 14249 | 0.2599 | 0.2711 | 62339 | 0.2495 | 0.2526 |
| [0.3, 0.4) | 39389 | 0.3513 | 0.3582 | 45087 | 0.3378 | 0.3275 |
| [0.4, 0.5) | 47516 | 0.4424 | 0.4383 | 9008 | 0.4265 | 0.4010 |
| [0.5, 0.6) | 20318 | 0.5310 | 0.5103 | 1286 | 0.5131 | 0.4666 |
| [0.6, 0.7) | 4652 | 0.6284 | 0.5918 | 119 | 0.6081 | 0.5546 |
| [0.7, 0.8) | 564 | 0.7269 | 0.6596 | 51 | 0.7069 | 0.6078 |
| [0.8, 0.9) | 258 | 0.8154 | 0.7674 | 47 | 0.8221 | 0.7234 |
| [0.9, 1.0] | 326 | 0.9690 | 0.8528 | 55 | 0.9709 | 0.8364 |

The JSON also carries both reliability curves for **every season** (all five seasons, both margins,
all four baselines): 48 curves and 480 buckets in total. An independent reconciliation (below)
validated every season curve and confirmed each curve's bucket `n` sums to that report's prediction
count, so the overall and per-season reliability records reconcile.

## Validation and assertions

The runner checked **27/27 required assertions; all passed** (`assertions_all_passed = true`). They
do **not** exercise a candidate gate — there is no candidate and no gate in this slice; they assert
read-only integrity, contract identity, population, and calibration shape. The assertions were:

- **Read-only integrity:** DB SHA-256 matches the expected fingerprint before and after and is
  unchanged; DB size unchanged; config SHA-256 unchanged; git HEAD unchanged; worktree clean before
  and after.
- **Contract identity:** contract version is `1.0`; required baseline names and required baseline
  order are exact; all four overall baselines present.
- **Population:** 181 folds evaluated; folds-by-season exact (30/37/38/38/38); 133,964 predictions;
  133,964 eligible predictions; predictions equal eligible; leakage failures zero; exclusions zero
  for every baseline; coverage 1.0 for every baseline; identical prediction and eligible counts
  across baselines; season keys exact (all five).
- **Calibration shape:** all curves have ten buckets on the contract edges; every curve's `total_n`
  equals its report's prediction count; empty buckets have null means; non-empty buckets have
  non-null means.

In addition, an **independent reconciliation** parsed and re-checked the evidence after completion.
It reconciled all four overall reports, all 20 season-baseline rows (five seasons × four baselines),
and all 48 reliability curves (overall plus five seasons, two margins, four baselines) covering 480
buckets. Per-season prediction and cold-start sums, the prediction-weighted mean log score, RPS,
Brier-any, and Brier-60, and the per-season reliability bucket aggregates all reconcile to the
overall figures, and the DB and config SHA-256 as currently measured still match the recorded
fingerprints. **Zero independent validation failures.**

## Execution note (infrastructure launch retry)

This is an execution/infrastructure note, not model evidence and not a second evaluation. An initial
Claude-managed launch at `2026-07-29T10:24:24Z` was terminated by the one-shot agent lifecycle about
42 seconds later, before any terminal result or scored artifact was produced; the repository and
database were unchanged by that attempt. The same unchanged runner was then relaunched detached at
`2026-07-29T10:26:58Z` and produced the successful single record above (`status = success`,
`assertions_all_passed = true`). There is exactly one successful scored run in this record; the
terminated attempt produced no scores and is noted only for provenance transparency.

## Caveats

- **Unversioned historical target roster.** The historical target roster is the archive proxy
  projected from the target rows (`target_roster.historical_roster_status:
  archive_proxy_unversioned_at_real_deadline`). The archive does not version player registration,
  position, or club at the real FPL deadline, so this run makes **no claim** that membership,
  position, or club were known at the real deadline. No live or versioned player registry was
  consulted; live/prospective Stage B work must select entities from a versioned registry whose
  `known_at <= as_of` before the model sees them, and may not reuse this proxy to claim historical
  lift.
- **First-kickoff cutoff is an unversioned proxy.** Each fold's `as_of` is the first kickoff across
  every player row in the predicted gameweek — the latest proxy that still excludes every outcome in
  that gameweek under `kickoff_time < as_of`. It is not evidence that schedule, postponement, or
  availability fields were known at the real deadline. No live registry validation occurred.
- **Real-deadline point-in-time validity is unproven.** This is a development run on the frozen
  historical archive with the two proxies above; it is **not** a real-deadline knowledge-time
  validation and does not establish that the procedure would be point-in-time correct against a live,
  versioned registry at the real deadline.
- **Development evidence, overfit by construction.** The archive has shaped every Stage A candidate
  and now the Stage B baselines; a historical baseline bar is necessary context, not a ceiling. The
  headline number is a development number, not an upper bound.
- **No candidate was part of this run; no model is promoted.** The run predates Candidate V1's
  additive design-only pre-registration and contains no candidate prediction, fit, or gate
  execution. Candidate V1 is now pre-registered under amendment 1.1 but still has no model code,
  fit, evaluation, result, or verdict. Calibration completeness concerns only these frozen
  baselines under this frozen historical proxy contract.

## Verdict and next step

**Complete baseline-only development and calibration record for the frozen v1.0 historical proxy
contract. Do not promote.** The position prior
(`position_minutes_frequency`, mean log score 1.04916) is the headline development bar; a future
aggregate 1% lift would require mean log score ≤ about 1.03867. No baseline dominates: the position
prior leads only on mean log score, while `trailing_5_player_minutes` leads on RPS and both Brier
margins, overall and in every season.

The baseline/calibration record is complete for this frozen historical proxy contract, while
real-deadline knowledge-time validity remains unproven and no model is promoted. The next Stage B
step is the **separate reviewed Candidate V1 implementation and deterministic-test slice** recorded
in [`phase2-stage-b-candidate-v1-design.md`](phase2-stage-b-candidate-v1-design.md). That slice must
not run the archive, fit a model, or execute a gate. The frozen v1.0 population, target-roster
knowledge-time policy, bin shape, baseline definitions, metrics, scoring/calibration definitions,
and promotion gate remain unchanged under additive amendment 1.1, and a gate may never be amended
after a candidate is judged. Candidate V1 currently has design policy only.
