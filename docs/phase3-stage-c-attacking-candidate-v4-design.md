# Stage C attacking Candidate V4 — design (exposure-weighted xG team share)

**Status: pre-registration, development-only.** Candidate V4
(`exposure_weighted_xg_team_share_attacking_goals_v4`) is pre-registered under
`config/phase3_evaluation.yaml` amendment 1.4 (contract v1.4) **before any V4 evaluation**. It is
additive: it changes no v1.0/1.1/1.2/1.3 population, target roster, baseline, metric, gate, seed, or
calibration field, and is judged by the unchanged v1.0 promotion gate. No V4 historical run is
authorized by this document; the development runner (`fpl.validate.dev_attacking_candidate_v4`)
exists and is provenance-ready but is the single explicitly authorized clean run, never a test.

V4 is the controlled test of the hypothesis:

> **Separating per-minute attacking productivity from predicted exposure improves point-in-time
> proper scores over raw per-appearance xG shares.**

It keeps V3's team-coupling / conservation skeleton and changes THREE things at once: the share
signal (per-minute productivity × predicted exposure vs mean per appearance), the cold-start prior
(pooled → position-specific), and the signal fallback (threat → none, xG-only).

## What changes vs V3

| | V3 (`minutes_gated_coupled_team_share_attacking_goals_v3`) | V4 |
|---|---|---|
| share signal | mean trailing xG per **appearance** (a 15-min cameo counts as much as a 90-min match) | **exposure-weighted** `shrunk_xg_per_min * E[minutes]` |
| appearance handling | separate `share * p_play` factor, renormalised | availability folded once into `E[minutes]`; **no** `p_play` factor (no double-count) |
| cold-start prior | pooled all-position signal mean (see audit below) | **position-specific** fold-local xG/min prior |
| minutes model | frozen `trailing_5_player_minutes` (for `p_play`) | frozen `trailing_5_player_minutes` (for `E[minutes]`) — **same baseline, not Stage B Candidate V3** |
| signal fallback | `threat` where xG unmeasured | **none** — xG-only |
| conservation | `sum_i rate_i == lambda_team` (renormalised) | `sum_i rate_i == lambda_team` (same, in expectation) |

The only structural difference is the share construction; the team-coupling, conservation, and
Stage A reuse are identical.

## Exact formulas and units

For a club with Stage A expected goals `lambda_team` (the frozen `trailing_goals_attack_defence`
baseline, refit fold-local on `kickoff_time < as_of`), and a fixture roster of players `i`:

```
# per-minute productivity (xG-only, Option-A window: last 5 appeared rows, measured-xG rows among them)
player_xg_per_min_i = sum(xG over window measured rows) / sum(minutes over the same rows)
position_xg_per_min[pos] = sum(xG over appeared measured rows at pos) / sum(minutes)   # fold-local, position-specific

# FIXED shrinkage toward the position prior (prior_minutes = 90, one full-match equivalent)
shrunk_xg_per_min_i = (sum(xG) + 90 * position_xg_per_min[pos_i]) / (sum(minutes) + 90)

# expected exposure from the frozen Stage B baseline distribution (UNCONDITIONAL)
bin_mean_b(fold) = mean(minutes in bin b over minutes-not-null training rows, kickoff_time < as_of)  # bin 0 == 0
E[minutes_i] = sum_b P_i(bin=b) * bin_mean_b        # P_i is the trailing_5_player_minutes distribution

# weight, then team-scale allocation (underlying Poisson-rate conservation)
goal_weight_i = shrunk_xg_per_min_i * E[minutes_i]   # NO p_play factor
goal_lambda_i = lambda_team * goal_weight_i / sum_j(goal_weight_j)
=> sum_i goal_lambda_i == lambda_team   (in expectation)
```

Units: `xg_per_min` is xG per minute; `goal_weight` is xG-equivalent exposure; `goal_lambda` is
expected goals. The prediction is `Poisson(goal_lambda_i)` over `0..10`.

### Conservation guarantee

**Underlying Poisson-rate conservation in expectation**: `sum_i goal_lambda_i == lambda_team` by
construction (weights normalise to the team total). This is **not** per-draw realised-count
conservation (independent Poisson draws do not sum to a fixed total) and V4 is never fed to the
full-points composer in this slice (see the composer defect note below).

## Locked choices (all stated before any V4 evaluation)

- **xG-only, no fallback.** The signal is `expected_goals` only; there is no `threat` fallback.
  NULL xG is unmeasured and never zero-filled; it contributes to neither the signal sum nor the
  minutes sum.
- **Option-A window.** Select the last five appeared rows (`minutes > 0`), then use the
  measured-xG rows among them. This is the same five rows V3 selects, so the only difference is the
  aggregation.
- **prior_minutes = 90 (fixed).** One full-match equivalent of prior exposure. Derivation: at
  `prior_minutes = 90` the player's own measured rate and the position prior reach **equal weight at
  90 measured minutes** (one full match) — `shrunk = (Σ + 90·prior)/(Σmin + 90)` gives 50% own-rate
  at 90 min, ~80% at 360 min (four matches), ~89% at 720 min. This tames cameo-rate explosion (a
  10-min cameo with 0.3 xG is pulled from a naive 2.7 xG/90 to ~0.7) **without** collapsing
  moderate-minute players (a 125-minute sub keeps ~58% own-rate weight). It is a FIXED development
  choice, never tuned after a result. The naive `5 × 90 = 450` translation of V1/V2/V3's `alpha = 5`
  appearances was rejected: it would give a 90-minute player only ~17% own-rate weight and
  over-shrink substitutes.
- **E[minutes] from fold-local GLOBAL bin means.** `bin_mean_b` is the empirical mean minutes in bin
  b over `minutes IS NOT NULL AND kickoff_time < as_of` rows (bin 0 exactly 0; deterministic
  empty-bin fallbacks `30 / 75 / 90`). Bin means are GLOBAL (all positions): minutes-within-a-bin is
  a playing-time property, not a position property; the position effect is already in `P_i(bin)`
  and the position-specific rate prior. `E[minutes]` is unconditional (bin 0 contributes 0), so the
  weight must NOT also multiply by `P(play)` (that would double-count availability). It is NOT
  `points_composition.representative_minutes` (whose values `(0, 59, 89, 90)` are scoring-threshold
  edges, not conditional means — `59` badly overstates a typical 1–59-minute appearance).
- **Minutes model: frozen `trailing_5_player_minutes`** baseline (the same one V3 uses), NOT Stage B
  Candidate V3 — so productivity and minutes are not changed simultaneously.
- **alpha = 5.0** mirrors the v1.0 trailing baseline, used only by the stage-A-uninformative fallback.

## V3 cold-start implementation-vs-contract audit

V4 does not modify or reinterpret frozen V3; it explicitly chooses differently. The audit:

- **Committed V3 behaviour** (`attacking_v2._appeared_history`, inherited unchanged by V3's
  `_fold_player_history` and `_build_roster`): the cold-start fill is accumulated over **all appeared
  prior rows regardless of position** (`position` is selected but never used in the accumulation);
  the variable is named `positional_mean` / `pos_signal_mean` but it is the fold-local **pooled**
  all-position signal mean. Every cold-start player in a fixture (GK/DEF/MID/FWD alike) receives the
  same pooled fill.
- **Contract wording** (V2/V3 `cold_start_share`): `...fold_local_positional_goal_mean_equal_to_v1_baseline`.
- **They disagree** on two axes: (a) pooled vs positional (the concrete divergence); (b) it is the
  signal mean (xG/threat), not the V1 goal-rate baseline the contract names.

V4's cold-start prior is **position-specific** (`position_xg_per_min[pos]`), so a cold-start GK
prior is ~0 and a cold-start FWD prior is large. This is an additional, deliberate change beyond
per-minute normalization, called out here and in the candidate docstring.

## Minutes integration without double-counting

`E[minutes]` already includes the zero-minute mass (bin 0 → 0 minutes), so availability is folded in
exactly once. The candidate never multiplies by `P(play)`. This makes V4's rate an unconditional
marginal — exactly what the Stage C harness needs (it scores zero-minute target rows as `goals = 0`).

## File boundary (additive; no frozen file modified)

Created:
- `src/fpl/models/attacking_exposure.py` — shared PURE exposure helpers (`shrunk_rate_per_min`,
  `trailing_signal_minutes`, `expected_minutes`, `allocate_team_scale`, `PRIOR_MINUTES`,
  `BIN_MEAN_FALLBACKS`).
- `src/fpl/models/attacking_v4.py` — the candidate (subclasses V2 for Stage A coupling + trailing
  fallback; overrides `prepare`).
- `src/fpl/validate/dev_attacking_candidate_v4.py` — provenance-ready development runner (co-scores
  V3 live as the comparator; clean-worktree gate; sha256 of phase3 config, phase2 minutes contract,
  candidate source, exposure source, V3 source, database; UTC start/end; seed; DEVELOPMENT-ONLY
  banner + fenced reconciliation JSON; suppresses INVALID/UNPUBLISHABLE on provenance drift).
- `tests/test_attacking_exposure.py`, `tests/test_attacking_v4.py`,
  `tests/test_dev_attacking_candidate_v4.py`.
- This document.

Modified (additive amendments / schema only — no frozen gate, baseline, metric, or result):
- `config/phase3_evaluation.yaml` (`1.3 → 1.4`, amendment 1.4, `stage_c_candidate_v4` block).
- `src/fpl/config.py` (`Phase3StageCCandidateV4Policy`, the required field, the `1.4` amendment
  history entry).
- `tests/test_phase3_evaluation.py` (version pin `1.4`; V4 contract tests).

Not touched (frozen): `points_composition.py`, `prospective_points_v1.py`, `attacking_v2.py`,
`attacking_v3.py`, `attacking_v1.py`, `attacking_assists_v1.py`, `minutes_v3.py`, every existing
dev runner, all gate/baseline/metric config, all recorded numbers, the prospective default.

## Composer defect (recorded, not fixed here)

A separate audit found the frozen composer applies a minutes-zero gate **after** rates were already
appearance-adjusted, applying non-appearance more than once in the composed distribution
(`sum_i E_composer[goals] = lambda_team * weighted_mean(P(play)) < lambda_team`). This is a
pre-existing, development-only defect in the prospective wiring; it is not caused by V4 and is not
fixed here. V4 scores **component-level goals only** and is never fed to the composer in this slice.
The relative-V4-vs-V3 "cancels" claim is withdrawn: V3 and V4 depend on `p_play` / `E[minutes]`
differently, so the second gate is candidate-dependent. Fixing the composer's event/minutes
conditionality is a separate proposed corrective slice (Phase C) with its own offline regression
test and explicit conditional/unconditional component contract.

## Measurement plan (Phase B, only after authorization)

Leakage-safe, mirroring `dev_attacking_candidate_v3` provenance. The harness scores **every
eligible row** (full population, including 2021-22 and partial 2022-23) and reports full-population
and covered-season metrics **separately**; the **verdict uses only the xG-covered subset
(2023-24, 2024-25, 2025-26)**. 2021-22 is excluded only from covered-season judging, not from
execution. Candidate and all comparators (frozen V3 live co-score; the two v1.0 baselines) score
identical eligible rows.

Metrics: mean log score, RPS, Brier P(≥1 goal), randomised-PIT, reliability — overall, per-season,
per-position, home/away. Slices: starter/rotation/sub by `E[minutes]` (the hypothesis-critical
slice), cold starts, transferred players, low-history-minute cohorts. Conservation diagnostic:
per fixture `sum_i goal_lambda_i` vs `lambda_team`. No combined full-points score. No promotion
verdict.

## Scope sequencing

- **Phase A (this slice):** pre-register + implement + offline-test + provenance-ready runner +
  design docs. No archive run, no composer change, no prospective change.
- **Phase B (after code review + explicit authorization):** one clean goals development run;
  reconcile independently; no promotion verdict.
- **Phase C (only if evidence supports V4):** separately fix/version the composer's
  event/minutes conditionality, then test prospective integration under the new composer contract.
