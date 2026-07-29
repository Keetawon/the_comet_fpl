# Phase 2 Stage B baseline development result

> **PROVISIONAL / HEADLINE DEVELOPMENT BASELINE — NOT A CALIBRATION RECORD, NOT A PROMOTION
> VERDICT.** This is the **baseline-only** full-archive run under contract version `1.0`: the four
> frozen Stage B baselines fitted and predicted inside every observed-gameweek fold, with **no
> candidate** fitted and **no promotion gate** executed. It records the headline development bar a
> future Stage B candidate would be measured against, and it is **provisional**: a post-processing
> defect (below) means the full calibration bucket counts and an explicit assertion block were not
> captured, so this is a headline/provisional baseline, not a complete calibration record. No rerun
> was authorized as part of this slice. The historical archive (2021-22 through 2025-26) is
> **development evidence**, not a fresh holdout; the first historical baseline number is a
> development number, **not an upper bound** of any kind.

The harness (`src/fpl/validate/minutes_harness.py`) and the four frozen baselines
(`src/fpl/validate/minutes_baselines.py`) are unchanged from the implementation slice recorded in
[`phase2-stage-b-implementation.md`](phase2-stage-b-implementation.md); the frozen contract is
[`config/phase2_evaluation.yaml`](../config/phase2_evaluation.yaml) at version `1.0`. This document
records the result of the first full-archive baseline run; it does **not** change the contract,
baselines, metrics, or gate.

## Identity

| Field | Value |
|---|---|
| Run type | Baselines-only development run (no candidate, no gate) |
| Contract | `config/phase2_evaluation.yaml`, version `1.0` (no amendments; zero candidates precede it) |
| Baselines | `position_minutes_frequency`, `last_observed_player_minutes`, `trailing_5_player_minutes`, `trailing_5_team_position_minutes` |
| Harness commit | `057330db1f4bfc9a9ced21b54533ad1f6b9fd0a8` (HEAD of `agent/phase2-minutes-contract`; worktree clean) |
| Archive fingerprint (SHA-256) | `c37aa58c41bc68b89656547eb1ee790d917c57a7497713d6b02d0f02f1414418` (`data/fpl.duckdb`) |
| Seed | `202627` (contract `training.seed`) |
| Capture date (UTC) | `2026-07-29` |
| Seasons | 2021-22, 2022-23, 2023-24, 2024-25, 2025-26 (complete archive) |

## Population

| Count | Value |
|---|---|
| Observed gameweek folds | **181** (one per observed gameweek; 2022-23 has no GW7) |
| Folds by season | 2021-22 = **30**, 2022-23 = **37**, 2023-24 = **38**, 2024-25 = **38**, 2025-26 = **38** |
| Eligible predictions | **133,964** player-fixtures (`(season, code, fixture)` grain) |
| Exclusions | **0** (every eligible row received a prediction; coverage 1.000) |
| Leakage failures | **0** (`assert_no_minutes_leakage` held in every fold) |
| Baseline population | all four frozen baselines on the **same** eligible rows |
| Wall time | **569.069 s** |

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
1.03867** (from the unrounded 1.04916 baseline) to clear the 1% aggregate lift. **No candidate and no
gate were run in this slice**, so 1.03867 is a forward-looking reference figure, not a judgement.

`position_minutes_frequency` is best on mean log score **only**: it is the **worst** of the four on
RPS (0.59531), Brier-any (0.23766), and Brier-60 (0.20115). `trailing_5_player_minutes` is the
mirror image — best (lowest) RPS (0.31901) and both Brier margins (0.11552 / 0.10885) but the
second-highest mean log score (3.12642). Mean log score and RPS/Brier therefore rank these baselines
differently, and no baseline dominates across the scores. This is a divergence between the
scoring rules rather than a data mechanism that this run diagnoses: mean log score is unbounded as
the realized-bin probability falls to the 1e-12 floor, whereas RPS and each Brier margin are bounded,
so the same misprediction can be modest under RPS/Brier yet severe under log score. The player-level
baselines' higher `rho` is reported here, not gated.

What a future promotion gate would require (**none of this was exercised by this baseline-only
slice**): against the best eligible baseline on the same eligible predictions, a candidate must clear
**≥ 1% aggregate mean-log-score lift** (≤ about 1.03867) with **no aggregate regression** on RPS, on
Brier-any, or on Brier-60 (each `maximum_*_relative_regression = 0.0`), keep **PIT-80 band coverage
within 0.05 of nominal** (`|0.80 − PIT80| ≤ 0.05`), achieve **full prediction coverage (1.0)** over
**≥ 181 folds** with **zero leakage failures**, and show **no mean-log-score regression in any
reported season**. `spearman_p60_within_position_gameweek` and the reliability curves stay
**report-only**.

## The post-processing defect (why this is provisional)

`run_minutes_harness` returned successfully with 181 folds, 133,964/133,964 predictions, and zero
leakage; `format_minutes_report` and the headline metrics then printed. After those steps, the same
outer process exited with code 1 during transcript post-processing because it read calibration
bucket definitions from the wrong contract field:

- It read `contract.calibration` instead of `contract.scoring_calibration`. In this contract the
  bucket edges, band, and seed live under `scoring_calibration:` (the typed loader's calibration
  definitions); `metrics.calibration:` is only the ordered list of metric *names*. Reading the wrong
  field meant the reliability bucket **counts were not emitted** from the frozen definitions, and the
  explicit reliability/assertion block was not captured for this record.
- The rendered transcript was also **truncated for the 2024-25 and 2025-26 per-season metric rows**.

This is a **post-processing/rendering defect, not a harness or contract defect**: it does not touch
the scored predictions, the proper scores above, the fold count, the population, or the leakage
result, all of which came straight from the harness. It only means the **calibration detail**
(reliability bucket counts for `reliability_any_minutes` / `reliability_60_plus`, and the two
truncated per-season rows) was not captured here. Per the contract, reliability curves are
**report-only in v1.0** and gate nothing, so this gap does not change any number above or any gate;
it only means this record is **not a complete calibration record** and therefore not a basis for a
calibration verdict. **No rerun was authorized** as part of this slice. The frozen contract and
thresholds are unchanged.

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
signal would be expected to beat.

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
- **Development evidence, overfit by construction.** The archive has shaped every Stage A candidate
  and now the Stage B baselines; a historical baseline bar is necessary context, not a ceiling.
- **Provisional calibration.** The post-processing defect above means the reliability bucket counts
  and two per-season rows are absent from this record; it is a headline/provisional baseline, not a
  complete calibration record.
- **No candidate exists.** No Stage B candidate has been pre-registered, fitted, or judged.

## Verdict and next step

**Headline/provisional development baseline. Do not promote, and do not fit a candidate against
this number yet.** The position prior (`position_minutes_frequency`, mean log score 1.04916) is the
headline development bar; a future aggregate 1% lift would require mean log score ≤ about 1.03867.
The result is provisional because the post-processing defect left the reliability bucket counts and
two per-season rows uncaptured, so the calibration record is incomplete.

The next Stage B step is **one explicitly authorized corrected run** that re-renders the full
calibration output (reliability bucket counts from `scoring_calibration`, the explicit assertion
block, and the 2024-25 / 2025-26 per-season rows) against the same frozen contract and the same
archive fingerprint, **before** any candidate is pre-registered or fitted. The frozen contract,
baselines, metrics, scoring/calibration definitions, and promotion gate are unchanged and must not
be altered; a gate may never be amended after a candidate is judged. **No Stage B candidate exists.**
