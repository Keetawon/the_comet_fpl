# Phase 3 Stage C (Player Attacking Goals) Baseline Development Record

This document records the single baseline-only development evaluation of the Stage C player attacking goals component. It follows the pre-registration contract frozen in [`config/phase3_evaluation.yaml`](file:///d:/Personal/workspace/the_comet_fpl/config/phase3_evaluation.yaml) (contract version `1.0`).

> [!NOTE]
> **Development Record Only — Not a Promotion Result.**
> The historical target roster and first-kickoff deadline cutoff are unversioned archive proxies, so real-deadline knowledge-time validity is unproven. This run evaluates baseline performance only; no candidate is evaluated or promoted here.

---

## 1. Provenance and Governance

- **Contract Version:** `1.0`
- **Evaluation Date:** `2026-07-31`
- **Reconciliation Record:** [`docs/evidence/phase3-stage-c-attacking-baseline-2026-07-31.json`](file:///d:/Personal/workspace/the_comet_fpl/docs/evidence/phase3-stage-c-attacking-baseline-2026-07-31.json)
- **Leakage Failures:** `0`
- **Exclusions:** `0`

---

## 2. Evaluation Population and Walk-Forward Split

- **Population Grain:** `(season, code, fixture)` for all registered player fixtures with non-null minutes (`mart_fact_player_fixture`).
- **Expanding Folds:** 181 observed gameweek folds across 5 seasons (8-gameweek warmup in 2021-22):
  - **2021-22:** 30 folds (GW9–GW38)
  - **2022-23:** 37 folds (GW1–GW38, excluding unplayed GW7)
  - **2023-24:** 38 folds (GW1–GW38)
  - **2024-25:** 38 folds (GW1–GW38)
  - **2025-26:** 38 folds (GW1–GW38)
- **Total Eligible Predictions:** `133,964` player-fixture rows.
- **Cold Starts:** `1,207` player-fixture rows (first appearance of player identity `code` in fold history; fallback distribution assigned).

---

## 3. Overall Baseline Results

| Metric | `positional_goal_rate_poisson` | `trailing_player_goal_rate_poisson` | Best Baseline Value | Dominant Baseline |
| :--- | :---: | :---: | :---: | :---: |
| **Mean Log Score** (Primary, $\downarrow$) | 0.154512 | **0.143547** | **0.143547** | `trailing_player_goal_rate_poisson` |
| **Ranked Probability Score** ($\downarrow$) | 0.036650 | **0.035129** | **0.035129** | `trailing_player_goal_rate_poisson` |
| **Brier Score ($P(\text{goals} \ge 1)$)** ($\downarrow$) | 0.032843 | **0.031384** | **0.031384** | `trailing_player_goal_rate_poisson` |
| **PIT 80% Coverage Error** ($\le 0.05$) | 0.004373 | **0.001977** | **0.001977** | `trailing_player_goal_rate_poisson` |

`trailing_player_goal_rate_poisson` **dominates across all proper distribution metrics and calibration error overall.**

---

## 4. Per-Season Breakdown

### Mean Log Score (Primary Metric, $\downarrow$)

| Season | Folds | Predictions | `positional_goal_rate_poisson` | `trailing_player_goal_rate_poisson` | Leader |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **2021-22** | 30 | 22,233 | 0.162451 | **0.152725** | `trailing_player_goal_rate_poisson` |
| **2022-23** | 37 | 27,249 | 0.155079 | **0.143548** | `trailing_player_goal_rate_poisson` |
| **2023-24** | 38 | 28,154 | 0.161035 | **0.148799** | `trailing_player_goal_rate_poisson` |
| **2024-25** | 38 | 28,160 | 0.157072 | **0.144386** | `trailing_player_goal_rate_poisson` |
| **2025-26** | 38 | 28,168 | 0.139614 | **0.131139** | `trailing_player_goal_rate_poisson` |

### Ranked Probability Score (CRPS, $\downarrow$)

| Season | `positional_goal_rate_poisson` | `trailing_player_goal_rate_poisson` | Leader |
| :--- | :---: | :---: | :---: |
| **2021-22** | 0.038490 | **0.037273** | `trailing_player_goal_rate_poisson` |
| **2022-23** | 0.037199 | **0.035415** | `trailing_player_goal_rate_poisson` |
| **2023-24** | 0.038376 | **0.036695** | `trailing_player_goal_rate_poisson` |
| **2024-25** | 0.037551 | **0.035722** | `trailing_player_goal_rate_poisson` |
| **2025-26** | 0.032329 | **0.031273** | `trailing_player_goal_rate_poisson` |

### Brier Score on $P(\text{goals} \ge 1)$ ($\downarrow$)

| Season | `positional_goal_rate_poisson` | `trailing_player_goal_rate_poisson` | Leader |
| :--- | :---: | :---: | :---: |
| **2021-22** | 0.034301 | **0.033106** | `trailing_player_goal_rate_poisson` |
| **2022-23** | 0.033068 | **0.031361** | `trailing_player_goal_rate_poisson` |
| **2023-24** | 0.034086 | **0.032486** | `trailing_player_goal_rate_poisson` |
| **2024-25** | 0.034118 | **0.032366** | `trailing_player_goal_rate_poisson` |
| **2025-26** | 0.029217 | **0.028204** | `trailing_player_goal_rate_poisson` |

---

## 5. Promotion Thresholds for Future Candidates

Under pre-registration contract `1.0`, any candidate proposed for Stage C attacking goals must beat the best baseline (`trailing_player_goal_rate_poisson`) under the following gates:

1. **Primary Metric Gate:**
   - Overall Mean Log Score $\le$ **0.142111** ($\ge 1.0\%$ relative lift over baseline `0.143547`).
2. **Guardrail Metric Gates:**
   - Overall Ranked Probability Score $\le$ **0.035129** (no relative regression over baseline `0.035129`).
   - Overall Brier Score ($P(\text{goals} \ge 1)$) $\le$ **0.031384** (no relative regression over baseline `0.031384`).
3. **Calibration Gate:**
   - PIT 80% Coverage Error $\le$ **0.0500** (both baselines easily pass with error $\le 0.0044$).
4. **Consistency & Safety Gates:**
   - No season log score regression (must not regress against `trailing_player_goal_rate_poisson` in any of the 5 seasons).
   - Zero leakage failures across all 181 folds.
   - 100% prediction coverage (no excluded or skipped predictions).
