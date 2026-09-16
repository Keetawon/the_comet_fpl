# Phase 3 Stage C (Player Attacking Goals) Candidate V1 Development Record

This document records the single authorized clean historical development evaluation of Stage C
attacking Candidate V1 `xg_informed_trailing_player_goals_v1`. It follows the pre-registration
frozen in [`config/phase3_evaluation.yaml`](file:///d:/Personal/workspace/the_comet_fpl/config/phase3_evaluation.yaml)
(contract version `1.1`, amendment 1.1) and the design record in
[`phase3-stage-c-attacking-candidate-v1-design.md`](phase3-stage-c-attacking-candidate-v1-design.md).

> [!IMPORTANT]
> **Development Record Only — Not a Promotion Result.**
> Every frozen-gate condition is reported below as its own labelled development diagnostic, and the
> run records `combined_promotion_verdict: null`. The candidate is **not promoted** regardless of the
> numbers. The historical target roster and first-kickoff deadline cutoff are unversioned archive
> proxies, so real-deadline knowledge-time validity is unproven — the same reason every Stage B
> candidate is development-only. A second historical evaluation is not permitted, and nothing here is
> retuned.

---

## 1. Provenance and Governance

- **Contract Version:** `1.1` (additive amendment 1.1 over the unchanged v1.0 population, roster,
  baselines, metrics, and gate).
- **Candidate:** `xg_informed_trailing_player_goals_v1` — fixed closed-form estimator (no grid, no
  inner walk-forward). `alpha = 5.0`, `finishing_keep = 0.05`, both pinned in the contract.
- **Evaluation Date:** `2026-07-31`
- **Reconciliation Record (verbatim):** [`docs/evidence/phase3-stage-c-attacking-candidate-v1-2026-07-31.json`](file:///d:/Personal/workspace/the_comet_fpl/docs/evidence/phase3-stage-c-attacking-candidate-v1-2026-07-31.json)
- **Runner:** `src/fpl/validate/dev_attacking_candidate_v1.py` (provenance-guarded; mirrors the
  Stage B candidate runners).
- **Commit SHA:** `17918ca6263b5a59a6aa82204f4d7030d6ff950b` (clean worktree; the recorded SHA names
  the exact code that was scored).
- **Population:** `133,964` eligible predictions over `181` folds — identical eligible rows for the
  candidate and both v1.0 baselines (enforced structurally by the harness population-equality check).
- **Exclusions:** `0`. **Cold starts:** `1,207` (first appearance of `code` in fold history).
- **Leakage Failures:** `0` across all 181 folds.
- **Preflight/postflight:** the worktree was clean at preflight and remained clean at postflight; the
  commit SHA, config SHA-256, candidate-source SHA-256, and database SHA-256 were unchanged between
  capture and emit.

---

## 2. Estimator (recap)

The v1.0 `trailing_player_goal_rate_poisson` baseline with its recent GOALS signal replaced by recent
`expected_goals` where xG is measured, and finishing shrunk almost fully to the positional mean.
Where xG is unmeasured it falls back to the **exact** v1.0 trailing baseline. With fold-local
positional means `pos_g` (goals/appearance) and `pos_x` (xG/appearance over xG-measured prior rows):

- **xG path** (>=1 trailing row has xG AND `pos_x` defined): `shrunk_xg = (Σx + α·pos_x)/(m + α)`,
  `rate = shrunk_xg + [0.05·player_fin + 0.95·(pos_g − pos_x)]`.
- **fallback path**: `rate = (Σgoals + α·pos_g)/(n + α)` — bit-identical to the v1.0 baseline.
- **cold start** (`n = 0`): `rate = pos_g`.

Full specification: see the design record. α = 5.0 mirrors the v1.0 trailing baseline's shrinkage, so
the only structural change is goals → xG.

---

## 3. Overall Results

| Metric | `positional_goal_rate_poisson` | `trailing_player_goal_rate_poisson` | **Candidate V1** | Best Baseline |
| :--- | :---: | :---: | :---: | :---: |
| **Mean Log Score** (Primary, ↓) | 0.154512 | 0.143547 | **0.137813** | `trailing…` |
| **Ranked Probability Score** (↓) | 0.036650 | 0.035129 | **0.034600** | `trailing…` |
| **Brier (P(goals ≥ 1))** (↓) | 0.032843 | 0.031384 | **0.030862** | `trailing…` |
| **PIT-80 abs. error** (≤ 0.05) | 0.004373 | 0.001977 | 0.003223 | `trailing…` |

Candidate V1 improves on the best baseline (`trailing_player_goal_rate_poisson`) on **all three proper
distribution metrics** overall. Its PIT-80 absolute error (0.0032) is well under the 0.05 gate but
fractionally higher than the trailing baseline's very low 0.0020; PIT-80 is a calibration diagnostic
only, not a proper score, and both are far inside the gate.

**Primary lift vs `0.143547`: +3.9948%** (candidate 0.137813; required ≥ 1.0%).

---

## 4. Estimator Path Split (the headline diagnostic)

This candidate is defined by *where the xG signal acts*. The harness tallies the path taken per
prediction (development diagnostic, not a gate):

| Slice | cold start | fallback (v1.0) | xG-informed |
| :--- | :---: | :---: | :---: |
| **Overall** | 1,207 (0.90%) | 29,590 (22.09%) | 103,167 (77.01%) |
| 2021-22 | 139 (0.67%) | 20,565 (99.33%) | 0 (0.00%) |
| 2022-23 | 326 (1.23%) | 8,959 (33.80%) | 17,220 (64.97%) |
| 2023-24 | 302 (1.02%) | 47 (0.16%) | 29,376 (98.83%) |
| 2024-25 | 201 (0.74%) | 10 (0.04%) | 27,072 (99.23%) |
| 2025-26 | 239 (0.80%) | 9 (0.03%) | 29,499 (99.17%) |

This matches the design exactly: **no xG-informed prediction in 2021-22** (xG entirely absent → every
prediction is fallback or cold start → candidate == baseline bit-for-bit), a transition in 2022-23
(xG measured only from GW16), and ~99% xG-informed in 2023-24 onward. The fallback count in 2023-24+
is the small residue of players whose up-to-five trailing rows all predate xG coverage (e.g. a
returning player whose few prior appearances were in 2021-22).

---

## 5. Per-Season Mean Log Score (Primary, ↓)

Judge the xG effect **within the xG-covered seasons** (2023-24+, per
`xg_signal_policy.xg_covered_seasons_judging`). 2021-22 carries no xG and is bit-identical to the
baseline by construction.

| Season | Folds | Candidate V1 | `trailing…` baseline | Lift | xG-informed % |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **2021-22** | 30 | 0.152725 | 0.152725 | +0.0000% | 0.00% |
| **2022-23** | 37 | 0.140543 | 0.143548 | +2.0925% | 64.97% |
| **2023-24** | 38 | 0.141042 | 0.148799 | +5.2164% | 98.83% |
| **2024-25** | 38 | 0.136164 | 0.144386 | +5.6940% | 99.23% |
| **2025-26** | 38 | 0.123287 | 0.131139 | +5.9860% | 99.17% |

**The candidate improves on the best baseline in every season, with zero regressions**, and the lift
*grows* with xG coverage: +2.1% in the partial 2022-23, +5.2% to +6.0% in the fully-covered 2023-24+.
This is the measured-constants hypothesis (`xG beats recorded goals where xG is measured`) confirmed
on the archive, judged within the covered seasons exactly as the contract requires.

### Per-Season Guardrails (↓)

| Season | Candidate RPS / Brier(≥1) | `trailing…` RPS / Brier(≥1) |
| :--- | :---: | :---: |
| 2021-22 | 0.037273 / 0.033106 | 0.037273 / 0.033106 |
| 2022-23 | 0.035215 / 0.031151 | 0.035415 / 0.031361 |
| 2023-24 | 0.035979 / 0.031780 | 0.036695 / 0.032486 |
| 2024-25 | 0.034942 / 0.031586 | 0.035722 / 0.032366 |
| 2025-26 | 0.030496 / 0.027446 | 0.031273 / 0.028204 |

The candidate improves RPS and Brier in every season except 2021-22 (tie, by construction).

---

## 6. Development Diagnostics vs the Frozen v1.0 Gate

Each frozen-gate condition is evaluated as an **independent, labelled development diagnostic** and is
**never combined into a promotion verdict** (`combined_promotion_verdict: null`).

| # | Gate condition | Result | Detail |
| :---: | :--- | :---: | :--- |
| 1 | Aggregate mean-log-score lift ≥ 1.0% | **PASS** | lift +3.9946% (0.137813 vs 0.143547) |
| 2 | No aggregate RPS regression | **PASS** | +1.5067% (0.034600 vs 0.035129) |
| 3 | No aggregate Brier(≥1) regression | **PASS** | +1.6636% (0.030862 vs 0.031384) |
| 4 | PIT-80 abs. error ≤ 0.05 | **PASS** | 0.003223 |
| 5 | Prediction coverage ≥ 1.0 | **PASS** | 1.0000 (133,964/133,964) |
| 6 | Folds evaluated ≥ 181 | **PASS** | 181 |
| 7 | Zero leakage failures | **PASS** | 0 |
| 8 | No per-season mean-log-score regression | **PASS** | 0 of 5 seasons regress |

**8 of 8 diagnostics pass.** Mechanically, against the frozen gate and on this historical archive,
every condition is satisfied — including the 1% primary lift (cleared at +3.99%) and no regression in
any season or on any guardrail. This is reported as development evidence only.

---

## 7. Verdict

**DEVELOPMENT-ONLY — NOT PROMOTED.** Candidate V1 is not promoted and is judged by no promotion gate.
All eight gate conditions pass on the historical archive, but:

- The historical target roster and first-kickoff cutoff are **unversioned archive proxies**
  (`target_roster.historical_roster_status = archive_proxy_unversioned_at_real_deadline`,
  `cutoff.prediction_time = archive_first_kickoff_proxy_for_gameweek_deadline`), so real-deadline
  knowledge-time validity is **unproven**. Availability is excluded. The historical number is a
  development number, **not an upper bound**.
- Prospective 2026/27 is the untouched confirmation set and was not consumed.
- A second historical evaluation is not permitted, and nothing here is retuned. Any formula,
  constant, window, fallback, or feature change after this result is a **new named candidate under a
  new amendment**, never a V1 retune.

The best required Stage C attacking baseline (`trailing_player_goal_rate_poisson`) remains the Stage C
attacking model until a separately pre-registered candidate clears the unchanged promotion gate
against prospective data.

---

## 8. What the result tells us (diagnostic only)

The candidate's entire edge is the xG signal acting in the covered seasons: it is bit-identical to the
baseline in 2021-22 (lift exactly +0.0000%, 0% xG-informed) and the per-season lift scales with xG
coverage (+2.1% → +5.2% → +5.7% → +6.0%). That the gain appears precisely where xG is measured — and
nowhere it is not — is the strongest available evidence that the improvement is the xG signal rather
than an artefact of the shrinkage form, since α = 5.0 is unchanged from the baseline. It is still
development evidence under unversioned proxies, not a confirmation.
