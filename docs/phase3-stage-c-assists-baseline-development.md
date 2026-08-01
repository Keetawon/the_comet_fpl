# Phase 3 Stage C (Player Attacking Assists) Baseline Development Record

This document records the single baseline-only development evaluation of the Stage C player
attacking assists component. It follows the pre-registration contract frozen in
[`config/phase3_stage_c_assists_evaluation.yaml`](file:///d:/Personal/workspace/the_comet_fpl/config/phase3_stage_c_assists_evaluation.yaml)
(contract version `1.0`) -- a SEPARATE frozen contract from the Stage C goals contract, with its
own version counter, so it never perturbs the goals contract.

> [!NOTE]
> **Development Record Only — Not a Promotion Result.**
> The historical target roster and first-kickoff deadline cutoff are unversioned archive proxies,
> so real-deadline knowledge-time validity is unproven. This run evaluates baseline performance
> only; no candidate is evaluated or promoted here.

---

## 1. Provenance and Governance

- **Contract Version:** `1.0` (Stage C attacking assists, separate file from the goals contract).
- **Evaluation Date:** `2026-08-01`
- **Reconciliation Record (verbatim):** [`docs/evidence/phase3-stage-c-assists-baseline-2026-08-01.json`](file:///d:/Personal/workspace/the_comet_fpl/docs/evidence/phase3-stage-c-assists-baseline-2026-08-01.json)
- **Harness:** `src/fpl/validate/attacking_assists_harness.py` (mirrors the goals harness; reuses
  the same fold/population machinery and the generic count-distribution scorer).
- **Leakage Failures:** `0`
- **Exclusions:** `0`

The assists label is FPL assists (the FPL definition, not Opta). The grain is
`(season, code, fixture)`. The model target is the assist-count DISTRIBUTION (Poisson over
`0..10`), not the mean.

---

## 2. Evaluation Population and Walk-Forward Split

Identical to the Stage C goals component (the same registered population, folds, and warmup):

- **Population Grain:** `(season, code, fixture)` for all registered player fixtures with non-null
  minutes (`mart_fact_player_fixture`).
- **Expanding Folds:** 181 observed gameweek folds across 5 seasons (8-gameweek warmup in 2021-22):
  - **2021-22:** 30 folds (GW9–GW38)
  - **2022-23:** 37 folds (GW1–GW38, excluding unplayed GW7)
  - **2023-24:** 38 folds (GW1–GW38)
  - **2024-25:** 38 folds (GW1–GW38)
  - **2025-26:** 38 folds (GW1–GW38)
- **Total Eligible Predictions:** `133,964` player-fixture rows (20704 / 26505 / 29725 / 27283 /
  29747 by season) -- the same eligible rows the goals component scores.
- **Cold Starts:** `1,207` player-fixture rows (first appearance of player identity `code` in fold
  history; fallback distribution assigned).

---

## 3. Overall Baseline Results

| Metric | `positional_assist_rate_poisson` | `trailing_player_assist_rate_poisson` | Best Baseline Value | Dominant Baseline |
| :--- | :---: | :---: | :---: | :---: |
| **Mean Log Score** (Primary, ↓) | 0.148409 | **0.142730** | **0.142730** | `trailing_player_assist_rate_poisson` |
| **Ranked Probability Score** (↓) | 0.033550 | **0.033145** | **0.033145** | `trailing_player_assist_rate_poisson` |
| **Brier Score ($P(\text{assists} \ge 1)$)** (↓) | 0.030927 | **0.030522** | **0.030522** | `trailing_player_assist_rate_poisson` |
| **PIT 80% Coverage Error** ($\le 0.05$) | 0.003611 | **0.001409** | **0.001409** | `trailing_player_assist_rate_poisson` |

`trailing_player_assist_rate_poisson` **dominates across all four metrics overall.** It is the
comparator for any future Stage C assists candidate.

---

## 4. Per-Season Breakdown

### Mean Log Score (Primary Metric, ↓)

| Season | Folds | Predictions | `positional_assist_rate_poisson` | `trailing_player_assist_rate_poisson` | Leader |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **2021-22** | 30 | 20,704 | 0.152430 | **0.147536** | `trailing…` |
| **2022-23** | 37 | 26,505 | 0.148101 | **0.143119** | `trailing…` |
| **2023-24** | 38 | 29,725 | 0.152611 | **0.145182** | `trailing…` |
| **2024-25** | 38 | 27,283 | 0.152066 | **0.144603** | `trailing…` |
| **2025-26** | 38 | 29,747 | 0.138331 | **0.134871** | `trailing…` |

`trailing_player_assist_rate_poisson` leads on mean log score in all five seasons.

### Ranked Probability Score (↓)

| Season | `positional_assist_rate_poisson` | `trailing_player_assist_rate_poisson` | Leader |
| :--- | :---: | :---: | :---: |
| **2021-22** | 0.034622 | **0.034391** | `trailing…` |
| **2022-23** | 0.033650 | **0.033373** | `trailing…` |
| **2023-24** | 0.034748 | **0.034023** | `trailing…` |
| **2024-25** | 0.034495 | **0.033906** | `trailing…` |
| **2025-26** | 0.030652 | **0.030497** | `trailing…` |

### Brier Score on $P(\text{assists} \ge 1)$ (↓)

| Season | `positional_assist_rate_poisson` | `trailing_player_assist_rate_poisson` | Leader |
| :--- | :---: | :---: | :---: |
| **2021-22** | 0.031681 | **0.031455** | `trailing…` |
| **2022-23** | 0.031164 | **0.030873** | `trailing…` |
| **2023-24** | 0.031390 | **0.030664** | `trailing…` |
| **2024-25** | 0.031860 | **0.031275** | `trailing…` |
| **2025-26** | 0.028874 | **0.028728** | `trailing…` |

---

## 5. By-Position Baseline Results (mean log score, ↓)

Assists concentrate at MID and FWD; GK almost never assists. Reported for the by-position slice
the candidate design will emphasise (esp. DEF, where the attacking signal is xA not xG per
`docs/research-adaptation.md` §2.1).

| Position | Predictions | `positional…` log | `trailing…` log | `trailing…` RPS | `positional…` RPS |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **GK** | 14,890 | **0.012083** | 0.012956 | 0.001670 | **0.001610** |
| **DEF** | 44,678 | 0.111707 | **0.109760** | 0.022891 | **0.022813** |
| **MID** | 58,386 | 0.202377 | **0.192437** | **0.046817** | 0.047775 |
| **FWD** | 16,010 | 0.180807 | **0.174159** | **0.041168** | 0.041346 |

**No baseline dominates by position.** `trailing…` leads on mean log score at DEF, MID, and FWD,
but `positional…` leads at GK (where almost no player ever assists, so a player's own sparse
trailing history is noisier than the positional mean) and edges `trailing…` on RPS at GK and DEF.
This mirrors the goals component's "no baseline dominates" finding and is diagnostic context for
a future candidate, not a promotion signal.

---

## 6. Authoritative Label / Signal Coverage (asserted, not re-derived)

`tests/test_attacking_assists_archive.py` asserts these against the built database:

- **`assists` (label):** 100% measured every season. Count distribution over minutes-not-null
  rows: `0 → 134228, 1 → 4139, 2 → 314, 3 → 24, 4 → 2` (max 4).
- **`expected_assists` (xA):** SAME measured-coverage profile as `expected_goals` -- 2021-22 0%,
  2022-23 partial (NULL GW1–15, measured GW16+), 2023-24 / 2024-25 / 2025-26 100%.
- **`creativity`:** 100% measured every season (the FPL-native creative signal; the xA fallback,
  exactly as `threat` is the goals fallback).

The xA-vs-creativity signal question, like xG-vs-goals, must be judged WITHIN xA-covered seasons
(2023-24+); 2021-22 has no xA.

---

## 7. Supporting measurement: assists-minus-xA within-position persistence

Measured here against `data/fpl.duckdb` to support pinning the future candidate's assist-residual
shrinkage. Methodology mirrors `docs/research-adaptation.md` §2.1: season-to-season Pearson `r`
of `(assists - expected_assists) / 90`, players with $\ge 900$ minutes in both seasons, within
modal position, over the xA-covered consecutive season pairs (2022-23↔2023-24, 2023-24↔2024-25,
2024-25↔2025-26).

| Position | n player-season-pairs | r[(assists − xA)/90] |
| :--- | :---: | :---: |
| GK | 47 | −0.073 |
| DEF | 209 | +0.012 |
| MID | 248 | +0.161 |
| FWD | 49 | +0.192 |
| **ALL** | **553** | **+0.225** |

For comparison, the goals finishing residual `(goals − xG)/90` persistence measured in §2.1 was
FWD 0.138 / MID 0.060 / DEF −0.103 (at the noise floor). The assist residual is modestly MORE
persistent for MID/FWD (0.16–0.19) but still small, and is ≈0 for DEF. A trailing-5-match residual
captures far less than this full-season figure, so the persistence available to the candidate is
small. This supports pinning the assist-residual shrinkage **almost fully to the positional mean**
(`finishing_keep` small): the candidate keeps only a small fraction of a player's own trailing
residual. The exact constant is pinned in the candidate pre-registration BEFORE its run and is not
tuned to this number.

---

## 8. Promotion Thresholds for Future Candidates

Under pre-registration contract `1.0`, any candidate proposed for Stage C attacking assists must
beat the best baseline (`trailing_player_assist_rate_poisson`) under the following gates:

1. **Primary Metric Gate:** Overall Mean Log Score $\le$ **0.141302** ($\ge 1.0\%$ relative lift
   over baseline `0.142730`).
2. **Guardrail Metric Gates:** No aggregate regression on RPS or Brier ($P(\text{assists} \ge 1)$)
   vs the best baseline value of each metric.
3. **Calibration Gate:** PIT 80% Coverage Error $\le$ **0.0500** (both baselines pass with error
   $\le 0.0037$).
4. **Consistency & Safety Gates:** No season log-score regression; zero leakage failures across
   all 181 folds; 100% prediction coverage; $\ge 181$ folds.
