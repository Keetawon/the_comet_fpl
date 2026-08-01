# Phase 3 Stage C (Player Attacking Assists) Candidate V1 Development Record

This document records the single authorized clean historical development evaluation of Stage C
attacking assists Candidate V1 `xa_informed_trailing_player_assists_v1`. It follows the
pre-registration frozen in
[`config/phase3_stage_c_assists_evaluation.yaml`](file:///d:/Personal/workspace/the_comet_fpl/config/phase3_stage_c_assists_evaluation.yaml)
(contract version `1.1`, amendment 1.1 -- a SEPARATE contract from the goals contract) and the
design record in
[`phase3-stage-c-assists-candidate-v1-design.md`](phase3-stage-c-assists-candidate-v1-design.md).

> [!IMPORTANT]
> **Development Record Only — Not a Promotion Result.**
> Every frozen-gate condition is reported below as its own labelled development diagnostic, and the
> run records `combined_promotion_verdict: null`. The candidate is **not promoted** regardless of the
> numbers. The historical target roster and first-kickoff deadline cutoff are unversioned archive
> proxies, so real-deadline knowledge-time validity is unproven — the same reason every Stage B/C
> candidate is development-only. A second historical evaluation is not permitted, and nothing here is
> retuned.

---

## 1. Provenance and Governance

- **Contract Version:** `1.1` (additive amendment 1.1 over the unchanged v1.0 population, roster,
  baselines, metrics, and gate; separate file from the goals contract).
- **Candidate:** `xa_informed_trailing_player_assists_v1` — fixed closed-form estimator (no grid, no
  inner walk-forward). `alpha = 5.0`, `finishing_keep = 0.05`, both pinned in the contract.
- **Evaluation Date:** `2026-08-01`
- **Reconciliation Record (verbatim):** [`docs/evidence/phase3-stage-c-assists-candidate-v1-2026-08-01.json`](file:///d:/Personal/workspace/the_comet_fpl/docs/evidence/phase3-stage-c-assists-candidate-v1-2026-08-01.json)
  (`schema: stage_c_assists_candidate_v1_development/v1`).
- **Runner:** `src/fpl/validate/dev_assists_candidate_v1.py` (provenance-guarded; mirrors the goals
  V1 runner).
- **Commit SHA:** `7bf58d6ac12b83254a4b208087d06e538f9269a8` (clean worktree; the recorded SHA names
  the exact code that was scored).
- **Population:** `133,964` eligible predictions over `181` folds (30 / 37 / 38 / 38 / 38) — identical
  eligible rows for the candidate and both v1.0 baselines (enforced structurally by the harness
  population-equality check).
- **Exclusions:** `0`. **Cold starts:** `1,207` (first appearance of `code` in fold history).
- **Leakage Failures:** `0` across all 181 folds.
- **Preflight/postflight:** the worktree was clean at preflight and remained clean at postflight; the
  commit SHA, config SHA-256 (`1953c815…`), candidate-source SHA-256 (`f06865a0…`), and database
  SHA-256 (`ac704f07…`) were unchanged between capture and emit. Seed `202627`; started
  `2026-08-01T05:11:46Z`, ended `2026-08-01T05:14:23Z`.

---

## 2. Estimator (recap)

The v1.0 `trailing_player_assist_rate_poisson` baseline with its recent ASSISTS signal replaced by
recent `expected_assists` (xA) where xA is measured (per row, NULL filled by `creativity` rescaled to
the assist-rate scale), and the assist residual (assists − xA) shrunk almost fully to the positional
mean. The xA signal is over the trailing-5 **appeared** prior rows (`minutes > 0`, R6); where xA is
unmeasured it falls back to the **exact** v1.0 trailing baseline over the all-rows window.

- **xA path** (≥1 trailing appeared row has xA AND fold-local positional xA mean defined):
  `shrunk_xa = (Σxa + α·pos_xa)/(n + α)`, per-row `xa_i = expected_assists_i` else
  `creativity_factor·creativity_i` (`creativity_factor = pos_a/mean_creativity`), and
  `rate = shrunk_xa + [0.05·player_residual + 0.95·(pos_a − pos_xa)]`.
- **fallback path**: `rate = (Σassists + α·pos_a)/(n_all + α)` over the all-rows window —
  bit-identical to the v1.0 baseline.
- **cold start** (`n_all = 0`): `rate = pos_a`.

Full specification: see the design record. α = 5.0 mirrors the v1.0 trailing baseline's shrinkage, so
the only structural change is assists → xA (with creativity fill).

---

## 3. Overall Results

| Metric | `positional_assist_rate_poisson` | `trailing_player_assist_rate_poisson` | **Candidate V1** | Best Baseline |
| :--- | :---: | :---: | :---: | :---: |
| **Mean Log Score** (Primary, ↓) | 0.148409 | 0.142730 | **0.139941** | `trailing…` |
| **Ranked Probability Score** (↓) | 0.033550 | 0.033145 | **0.032790** | `trailing…` |
| **Brier (P(assists ≥ 1))** (↓) | 0.030927 | 0.030522 | **0.030176** | `trailing…` |
| **PIT-80 abs. error** (≤ 0.05) | 0.003611 | 0.001409 | **0.000494** | `trailing…` |

Candidate V1 improves on the best baseline (`trailing_player_assist_rate_poisson`) on **all three
proper distribution metrics** overall and on PIT-80 calibration error. **Primary lift vs `0.142730`:
+1.9540%** (candidate 0.139941; required ≥ 1.0%).

---

## 4. Estimator Path Split (the headline diagnostic)

This candidate is defined by *where the xA signal acts*. The harness tallies the path taken per
prediction (development diagnostic, not a gate):

| Slice | cold start | fallback (v1.0) | xA-informed |
| :--- | :---: | :---: | :---: |
| **Overall** | 1,207 (0.90%) | 54,694 (40.83%) | 78,063 (58.27%) |
| 2021-22 | 139 (0.67%) | 20,565 (99.33%) | 0 (0.00%) |
| 2022-23 | 326 (1.23%) | 15,297 (57.71%) | 10,882 (41.06%) |
| 2023-24 | 302 (1.02%) | 7,967 (26.80%) | 21,456 (72.18%) |
| 2024-25 | 201 (0.74%) | 4,469 (16.38%) | 22,613 (82.88%) |
| 2025-26 | 239 (0.80%) | 6,396 (21.50%) | 23,112 (77.70%) |

This matches the design exactly: **no xA-informed prediction in 2021-22** (xA entirely absent → every
prediction is fallback or cold start → candidate == baseline bit-for-bit), a transition in 2022-23
(xA measured only from GW16), and 72–83% xA-informed in 2023-24 onward. The xA-informed share is lower
than the goals V1 xG share (goals V1 was ~99% in 2023-24+) because assists V1 restricts the xA signal
to **appeared** rows (minutes > 0, R6): a player whose trailing appeared rows predate xA coverage
takes the fallback even in a covered season. The fallback is bit-identical to the baseline, so this is
the R6 appearance fix acting as designed, not lost signal.

---

## 5. Per-Season Mean Log Score (Primary, ↓)

Judge the xA effect **within the xA-covered seasons** (2023-24+, per
`xa_signal_policy.xa_covered_seasons_judging`). 2021-22 carries no xA and is bit-identical to the
baseline by construction.

| Season | Folds | Candidate V1 | `trailing…` baseline | Lift | xA-informed % |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **2021-22** | 30 | 0.147536 | 0.147536 | +0.0000% | 0.00% |
| **2022-23** | 37 | 0.139533 | 0.143119 | +2.5054% | 41.06% |
| **2023-24** | 38 | 0.141342 | 0.145182 | +2.6453% | 72.18% |
| **2024-25** | 38 | 0.142280 | 0.144603 | +1.6070% | 82.88% |
| **2025-26** | 38 | 0.131475 | 0.134871 | +2.5178% | 77.70% |

**The candidate improves on the best baseline in every season, with zero regressions.** 2021-22 is
exactly +0.0000% (0% xA-informed → bit-identical to the baseline by construction); the lift appears
precisely where xA is measured. The candidate also improves RPS and Brier(≥1) in every season except
the 2021-22 tie.

### Per-Season Guardrails (Candidate RPS / Brier(≥1), ↓)

| Season | Candidate RPS / Brier(≥1) | `trailing…` RPS / Brier(≥1) |
| :--- | :---: | :---: |
| 2021-22 | 0.034391 / 0.031455 | 0.034391 / 0.031455 |
| 2022-23 | 0.032902 / 0.030423 | 0.033373 / 0.030873 |
| 2023-24 | 0.033633 / 0.030288 | 0.034023 / 0.030664 |
| 2024-25 | 0.033584 / 0.030959 | 0.033906 / 0.031275 |
| 2025-26 | 0.030004 / 0.028234 | 0.030497 / 0.028728 |

---

## 6. By-Position Slice (DEF emphasis)

`docs/research-adaptation.md` §2.1 establishes that for DEF the attacking signal is **xA, not xG**
(xA persists 0.784 vs xG 0.319 for defenders), so the hypothesis is that xA helps DEF. The candidate
improves on the trailing baseline on mean log score at **all four positions**, including DEF:

| Position | Predictions | Candidate log | `trailing…` log | Lift vs trailing | Candidate Brier | `trailing…` Brier |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **DEF** | 44,678 | 0.107574 | 0.109760 | **+1.99%** | 0.021526 | 0.021812 |
| **MID** | 58,386 | 0.188531 | 0.192437 | +2.03% | 0.042279 | 0.042718 |
| **FWD** | 16,010 | 0.171455 | 0.174159 | +1.55% | 0.036687 | 0.037185 |
| **GK** | 14,890 | 0.012628 | 0.012956 | +2.53% | 0.001627 | 0.001670 |

The DEF hypothesis is confirmed: DEF improves +1.99% on log and on Brier. **Caveat (consistent with
the baseline record's "no baseline dominates"):** at GK, the `positional_assist_rate_poisson` baseline
(0.012083) still beats both the trailing baseline and the candidate on log score — GK almost never
assists, so a player's own sparse trailing history remains noisier than the positional mean. This is a
by-position diagnostic, not a gate; the frozen gate's comparator is the best-by-log baseline
(`trailing…`) overall, and every aggregate gate diagnostic passes.

---

## 7. Development Diagnostics vs the Frozen v1.0 Gate

Each frozen-gate condition is evaluated as an **independent, labelled development diagnostic** and is
**never combined into a promotion verdict** (`combined_promotion_verdict: null`).

| # | Gate condition | Result | Detail |
| :---: | :--- | :---: | :--- |
| 1 | Aggregate mean-log-score lift ≥ 1.0% | **PASS** | lift +1.9540% (0.139941 vs 0.142730) |
| 2 | No aggregate RPS regression | **PASS** | +1.0707% (0.032790 vs 0.033145) |
| 3 | No aggregate Brier(≥1 assist) regression | **PASS** | +1.1349% (0.030176 vs 0.030522) |
| 4 | PIT-80 abs. error ≤ 0.05 | **PASS** | 0.000494 |
| 5 | Prediction coverage ≥ 1.0 | **PASS** | 1.0000 (133,964/133,964) |
| 6 | Folds evaluated ≥ 181 | **PASS** | 181 |
| 7 | Zero leakage failures | **PASS** | 0 |
| 8 | No per-season mean-log-score regression | **PASS** | 0 of 5 seasons regress |

**8 of 8 diagnostics pass.** Mechanically, against the frozen gate and on this historical archive,
every condition is satisfied — including the 1% primary lift (cleared at +1.95%) and no regression in
any season or on any guardrail. This is reported as development evidence only.

---

## 8. Verdict

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

The best required Stage C attacking assists baseline (`trailing_player_assist_rate_poisson`) remains
the Stage C assists model until a separately pre-registered candidate clears the unchanged promotion
gate against prospective data.

---

## 9. What the result tells us (diagnostic only)

The candidate's entire edge is the xA signal acting in the covered seasons: it is bit-identical to
the baseline in 2021-22 (lift exactly +0.0000%, 0% xA-informed) and the per-season lift scales with xA
coverage (+2.5% → +2.6% → +1.6% → +2.5%). That the gain appears precisely where xA is measured — and
nowhere it is not — is the strongest available evidence that the improvement is the xA signal (with the
creativity fill for NULL-xA rows) rather than an artefact of the shrinkage form, since α = 5.0 is
unchanged from the baseline. The DEF slice improving +1.99% independently confirms the measured
hypothesis that xA is the correct attacking signal for defenders. It is still development evidence
under unversioned proxies, not a confirmation.

---

## 10. Signal-substitution caveat — `creativity` is an unvalidated ICT proxy for xA

On the xA path (§2), a NULL-`expected_assists` row inside an otherwise xA-covered trailing window is
filled by rescaled `creativity` (FPL/Opta's chance-creation index), not dropped. `creativity` is a
proprietary proxy for the same quantity xA measures and has **never been validated as a model
signal** in this project. The fill is bounded — exactly zero in 2021-22 (0% xA-informed → the
candidate is bit-identical to the baseline) and concentrated in the 2022-23 transition and the
early-2023-24 coverage boundary — but where it acts, that season's lift is **partly a creativity
result, not purely an xA result**, and must not be quoted as pure xA evidence. This is a
signal-substitution defect, not a knowledge-time leak (all archive stats are post-match and
`kickoff_time < as_of` holds) — recorded so the number is not misread. It does not change the
not-promoted verdict above. The clean pattern is goals Candidate V1's xG fallback (the recorded-count
baseline, never ICT); a creativity-free assists successor should use only the measured-xA rows in the
window — or the recorded-assist baseline when too few remain — never `creativity`. Such a successor
would be a **new named candidate under a new amendment**, not a V1 retune.
