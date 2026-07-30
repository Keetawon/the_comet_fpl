# Stage B Candidate V2 design: recency-weighted trailing player minutes

**Status: frozen pre-registration record, written before any evaluation; now executed once (2026-07-30) — see [`phase2-stage-b-candidate-v2-development.md`](phase2-stage-b-candidate-v2-development.md).** Candidate V2 is named
`recency_weighted_trailing_player_minutes_v2` in `config/phase2_evaluation.yaml` amendment 1.3.
The exact estimator and joint nested selector are implemented in
`src/fpl/models/minutes_v2.py` and covered by deterministic offline tests. There is a separately
named, offline-tested development runner in `src/fpl/validate/dev_minutes_candidate_v2.py` that
reuses the V1 runner's provenance machinery and the shared best-per-metric + starter-ranking gate.
**The single historical development evaluation has now been run once** (2026-07-30, mean log score
0.72625; V2 improves on every baseline on all four bounded scored metrics and on Candidate V1 on
all five, but **fails the v1.2 starter-ranking gate**, aggregate Spearman-p60 0.70071 vs the best
baseline 0.70851, −1.10%; nine of ten diagnostics pass). V2 is judged by the contract version 1.2
gate unchanged (this amendment adds a candidate policy only).

Candidate V2 is **development-only**. The archive already shaped the hypothesis, and the historical
target roster and first-kickoff cutoff remain unversioned proxies. A later historical number can
diagnose the model under those proxies; it cannot establish real-deadline knowledge-time validity
or promote a production model. Like V1, V2 **cannot be promoted on historical data** because of the
unversioned roster/cutoff proxies — a historical run can only diagnose whether recency-weighting
improves starter ranking.

Amendment 1.3 adds this candidate policy only. The complete version 1.0 population,
target-roster policy, four bins, four baselines and their definitions, metrics,
scoring/calibration definitions, the version 1.2 promotion gate, reporting, seed, and Monte Carlo
exclusion remain unchanged.

## Hypothesis

Candidate V1 counts the trailing-5 window with equal weight, so it cannot distinguish a player
losing his place from one winning it:

```text
A: 90, 90, 90, 0, 0   (starter being dropped)   -> counts {90:3, 0:2}
B:  0,  0, 90, 90, 90  (substitute breaking in)  -> counts {90:3, 0:2}   identical prediction
```

That discarded ordering is exactly the starter-ranking signal amendment 1.2 now gates, and V1
regresses it (aggregate `spearman_p60_within_position_gameweek` 0.69090 vs the best baseline
`last_observed_player_minutes` at 0.70851, −2.49%). Candidate V2 tests **one** hypothesis: a
geometric recency weight on the same trailing-5 window improves starter ranking without regressing
the proper scores. The window stays pinned at 5 and every other V1 choice is unchanged, so any
effect is attributable to recency alone.

## Exact distribution and the nesting property

For the `i`-th most-recent row in the trailing window (`i = 0` newest), the weight is `decay ** i`.
The weighted bin mass `w_k` is the sum of `decay ** i` over the trailing rows in bin `k`;
`W = sum_k w_k`; and

```text
p_k(decay, alpha) = (w_k + alpha * q_k) / (W + alpha)
```

`q_k` is the same fold-local raw `position_minutes_frequency` prior V1 uses (including its
all-position fallback). At `decay = 1.0` every weight is `1`, so `w_k = c_k` (V1's bin count) and
`W = n`, and the formula collapses to V1's `p_k(alpha) = (c_k + alpha * q_k) / (n + alpha)`
**bit-identically**. V2 is therefore a strict generalisation of V1, and the comparison is honest:
the nesting is asserted directly in the offline tests (`tests/test_minutes_v2.py`).

When `W == 0` (no prior history for the player) the prediction is exactly `q`, identical to V1's
`n == 0` branch. No epsilon is added in the model; the contract's `1e-12` log-probability floor
stays a scoring-only operation.

## Frozen parameter selection

`decay` and `alpha` are selected **jointly** by the *same* nested six-observed-gameweek inner
walk-forward V1 uses (predict each holdout gameweek from the pre-gameweek state, score by pooled
mean log score, then absorb). Grids:

- `decay ∈ {1.0, 0.9, 0.7, 0.5, 0.3}` (`1.0` is V1 exactly),
- `alpha ∈ {1.0, 2.0, 5.0, 10.0, 20.0}` (V1's grid, unchanged).

Tie-break, biased toward the null (V1): on equal inner pooled mean log score, pick the **largest**
`decay` first (closest to no-decay), then the **smallest** `alpha`. When fewer than 14 prior
observed gameweeks exist, fall back to the frozen `(decay = 1.0, alpha = 5.0)` (i.e. V1's fallback);
these folds are flagged as fallback, not boundary hits.

The development runner records fold-local `(decay, alpha)` selections with counts and flags
`decay == 0.3` (floor), `decay == 1.0` (ceiling, i.e. V1), and `alpha == 1.0` / `alpha == 20.0`
boundary hits.

## What V2 inherits unchanged from V1 and the contract

Population (registered FPL player population, zero-minute rows included), grain
`(season, code, fixture)`, four ordered bins, stable-`code` identity, strict cutoff
`kickoff_time < as_of`, NULL-not-zero, assistant-manager exclusion, double-gameweek batch isolation
(separate fixture rows, same pre-gameweek state, no within-gameweek absorption), the fold-local raw
position prior, and the scoring/calibration definitions. Availability / `status` /
chance-of-playing is **not** a feature (a separately named prospective candidate, untouched here).
Monte Carlo is out of scope; the minutes model stays a closed-form marginal (R6).

Every prior, transform, and grid score is fitted strictly within the applicable inner/outer fold.
Observed gameweeks only; 2022-23 GW7 stays absent.

## Reuse, not duplication

`src/fpl/models/minutes_v2.py` subclasses V1 to reuse its leakage-safe history/target validation
and prediction dispatch, and the shared position-prior / per-code history / inner-holdout machinery
factored into `minutes_v1.py` (`_fit_state`, `_build_inner_holdout_plan`). The only deltas are the
weighted distribution (`_distribution_weighted`) and the joint `(decay, alpha)` selection
(`_select_params`). The development runner
(`src/fpl/validate/dev_minutes_candidate_v2.py`) reuses the V1 runner's provenance lifecycle
(preflight → verify → finalize), the shared `compute_development_diagnostics` gate (best-per-metric
guardrails + starter-ranking Spearman gate from amendment 1.2), and `build_reconciliation_record`;
it supplies only the V2 candidate factory, the V2 model-source path, the V2 banner, and the V2
reconciliation schema (`stage_b_candidate_v2_development/v1`). There is no second copy of the gate
or the provenance machinery.

## The one-shot historical development run (executed once, 2026-07-30)

V2 has now been evaluated **once** as the owner's authorized action (exactly as V1 was handled),
against a pristine rebuilt archive; the result is recorded in
[`phase2-stage-b-candidate-v2-development.md`](phase2-stage-b-candidate-v2-development.md). Per the
pre-registration it is run **exactly once** and is not retuned afterwards. The exact command was:

```powershell
python -m fpl.validate.dev_minutes_candidate_v2
```

**Precondition — a pristine historical archive.** The run must execute against a **pristine
historical archive**, rebuilt via the `build_db` job, on a clean worktree, exactly once. The working
database currently carries the Step-2 live-row load (its fingerprint is `828740040b…`, no longer the
V1-era `c37aa58c…`), so it must be rebuilt before any V2 historical number is trustworthy. The
runner refuses a dirty worktree, fingerprints the exact parsed config bytes, the V2 candidate-source
bytes, and the archive, re-checks them after the database is closed, and suppresses the result as
INVALID/UNPUBLISHABLE if anything moved during the run.

V2 will be judged by the unchanged 1.2 gate. As with V1, the gate's role here is diagnostic, not
promotional: because the target roster and cutoff are unversioned proxies, no historical number can
promote V2 — the run can only show whether recency-weighting improves the starter-ranking signal
that motivated the candidate.
