# Stage B Candidate V1 design: shrunk trailing-five player minutes

**Status: frozen pre-registration record, written before implementation or evaluation.**
Candidate V1 is named `shrunk_trailing_5_player_minutes_v1` in
`config/phase2_evaluation.yaml` amendment 1.1. The exact estimator and nested selector are now
implemented in `src/fpl/models/minutes_v1.py` and covered by deterministic offline tests. There
is now a separately named, offline-tested development runner in
`src/fpl/validate/dev_minutes_candidate_v1.py`. It has now been run **once** as a clean historical
development run; the result is recorded in
[`phase2-stage-b-candidate-v1-development.md`](phase2-stage-b-candidate-v1-development.md) and is
**development-only — not a promotion verdict**, because the historical target roster and
first-kickoff cutoff remain unversioned proxies. The pre-registered formula and policy below
remain unchanged.

Candidate V1 is **development-only**. The archive already shaped the hypothesis, and the
historical target roster and first-kickoff cutoff remain unversioned proxies. A later
historical number can diagnose the model under those proxies; it cannot establish
real-deadline knowledge-time validity or promote a production model.

Amendment 1.1 adds this candidate policy only. The complete version 1.0 population,
target-roster policy, four bins, four baselines and their definitions, metrics,
scoring/calibration definitions, promotion gate, reporting, seed, and Monte Carlo exclusion
remain unchanged.

## Hypothesis and exact distribution

The baseline-only record showed complementary failure modes:

- `position_minutes_frequency` had the best mean log score (1.04916) but the worst RPS and
  both Brier margins;
- `trailing_5_player_minutes` had the best RPS and both Brier margins but a poor mean log
  score (3.12642), driven by raw empirical zero probabilities.

Candidate V1 tests one hypothesis only: shrink the player distribution toward the current
position prior so recent player information remains visible without relying on a five-row raw
distribution alone.

For target player `i` and minute bin `k`:

- `q_k` is the fold-local raw `position_minutes_frequency` distribution at the target's
  **current position**, including that baseline's existing all-position fallback;
- `c_k` is the number of the player's up to five most recent prior player-fixture rows in bin
  `k`, including zero-minute rows;
- `n = sum_k c_k`; and
- `alpha` is the fold-selected prior strength.

The closed-form prediction is:

```text
p_k(alpha) = (c_k + alpha * q_k) / (n + alpha)
```

If `n = 0`, the prediction is exactly `q`. There is no uniform or Laplace smoothing and no
candidate-specific epsilon. The contract's `1e-12` probability floor remains a scoring-only
operation. A bin where both `c_k` and `q_k` are zero therefore remains zero in the candidate
distribution and is handled only by the existing scorer.

## Frozen history and identity policy

- Prediction grain remains `(season, code, fixture)`; double-gameweek fixtures are never
  collapsed.
- Stable `code` is the only cross-season player identity. A bare `element_id` or archive
  `element` is never used.
- History is the up to five most recent prior player-fixture rows, ordered by
  `kickoff_time`, then `season`, then `fixture` (most recent first), including minutes = 0.
- Every history outcome satisfies the strict cutoff `kickoff_time < as_of`.
- The target label stays outside model inputs. Candidate inputs are prior minutes plus the
  target's stable `code` and current position from the existing historical roster proxy.
- NULL remains unavailable and is never zero-filled. Eligible training outcomes follow the
  existing minutes-not-NULL population. Assistant Manager elements remain excluded upstream.
- Availability/status, team, opponent, and home/away are not Candidate V1 features.

The target current position is still an unversioned historical proxy; amendment 1.1 does not
upgrade that field to known-at-deadline evidence. Live use requires the existing versioned
player-registry policy with `known_at <= as_of` before entity, position, or club reaches the
model.

## Nested prior-strength selection

Only `alpha` is selected. The player-history window remains fixed at five. The exact grid is:

```text
1.0, 2.0, 5.0, 10.0, 20.0
```

Inside each outer fold:

1. Take the most recent six observed gameweeks before the outer cutoff as the inner holdout,
   but only when at least eight earlier observed gameweeks remain for inner training. This
   requires at least 14 prior observed gameweeks in total.
2. For each `alpha`, walk the six holdout gameweeks chronologically. For one holdout
   gameweek, compute all distributions from the pre-gameweek history, score the complete
   gameweek, and only then absorb the entire gameweek before advancing. No row in a gameweek
   can train another prediction in that same gameweek.
3. Select the `alpha` with the lowest pooled inner mean log score. An exact tie selects the
   smallest `alpha`.
4. Recompute the position priors and player histories from the complete outer training window
   and predict the outer gameweek with the selected `alpha`.

When fewer than 14 prior observed gameweeks exist, `alpha = 5.0` is the frozen fallback. This
is deterministic nested parameter selection, not Monte Carlo. The candidate remains a
closed-form four-bin marginal.

Gameweeks are observed values from the facts, never `range(1, 39)`; the missing 2022-23 GW7
stays absent. Every prior, transform, and grid score is fitted within the applicable inner or
outer fold.

## Double-gameweek behavior

Every `(season, code, fixture)` target remains a separate prediction and scored row. All
fixtures in one target gameweek use the same pre-gameweek history; no result is absorbed until
the whole gameweek has been predicted. Because Candidate V1 has no fixture-specific feature,
the same `code` and current-position pair may receive the same distribution for both fixtures
of a double gameweek. That is intentional, must be reported honestly, and is never permission
to collapse the two fixture rows.

## Point-in-time argument

- **Target leakage:** target minutes, `mart_target_*`, and recorded points are not model
  inputs. The validation layer alone retains labels for scoring.
- **Event-time leakage:** all candidate history and every inner transform use only rows with
  `kickoff_time < as_of`; the predicted gameweek is isolated as a batch.
- **Knowledge-time limitation:** the archive roster and first-kickoff cutoff are unversioned
  proxies. Availability is excluded. This is why the candidate is development-only.
- **Identity leakage:** player history uses stable `code`; fixture rows keep season-qualified
  grain. Candidate V1 does not perform a cross-season team join.

Implementation tests must cover full-database versus physically truncated equivalence for
candidate predictions, timezone-aware cutoffs, target-label separation, stable-code history,
input-order invariance, zero-minute inclusion, NULL behavior, cold starts, missing GW7, and
double-gameweek batch isolation.

## Evaluation and unchanged gate

The implemented development runner scores Candidate V1 and all four frozen baselines on the
same eligible rows. The frozen version 1.0 gate remains the reference without any change:

- at least 1% aggregate mean-log-score lift over the best eligible required baseline;
- no aggregate regression on RPS, Brier-any, or Brier-60-plus;
- PIT-80 absolute error at most 0.05;
- full prediction coverage over at least 181 folds;
- zero leakage failures; and
- no per-season mean-log-score regression.

Reliability curves and within-position/gameweek Spearman remain report-only. Because V1 is
development-only, mechanically comparing these conditions is diagnostic, not a production
promotion verdict.

## Implemented runner provenance

The runner is implemented and offline-reviewed before use. It must continue to:

- refuse a dirty worktree at preflight and require it to remain clean at postflight;
- record and recheck Git HEAD, Git status, the evaluation-config SHA-256, the Candidate V1
  model-source SHA-256, and the database SHA-256 before publishing a result;
- suppress the result or mark it invalid if any recheck detects a time-of-check/time-of-use
  change;
- open the database read-only and confirm its hash is unchanged;
- record the fixed seed and UTC start/end timestamps; and
- emit the full folds, seasons, cohorts, coverage, calibration, parameter selections, and
  assertion record needed for independent reconciliation.

## Next step

The development runner, unchanged-baseline comparison, provenance rechecks, strict-JSON
reconciliation record, and deterministic offline failure-path tests are implemented and reviewed.
No archive run, gate execution, or result document occurred in that slice. The next step may be one
explicitly authorized clean historical development run using the committed provenance-ready runner.
Any formula, grid, window, fallback, feature, or selection-policy change after a V1 number exists is
a new named candidate under a new amendment, never a V1 retune.
