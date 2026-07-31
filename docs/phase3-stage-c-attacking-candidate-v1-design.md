# Stage C Candidate V1 design: xG-informed trailing player goals

**Status: frozen pre-registration record, written before any evaluation.**
Candidate V1 is named `xg_informed_trailing_player_goals_v1` in
`config/phase3_evaluation.yaml` amendment 1.1 (contract version `1.1`). The exact estimator is
pinned in the contract's `stage_c_candidate_v1` block and implemented in
`src/fpl/models/attacking_v1.py`, covered by deterministic offline tests. A separately named,
provenance-guarded development runner lives in `src/fpl/validate/dev_attacking_candidate_v1.py`. It
has now been run **once** as a clean historical development run (2026-07-31); the result is recorded
in [`phase3-stage-c-attacking-candidate-v1-development.md`](phase3-stage-c-attacking-candidate-v1-development.md)
and is **development-only — not a promotion verdict**, because the historical target roster and
first-kickoff cutoff remain unversioned proxies. The pre-registered formula and policy below remain
unchanged.

Candidate V1 is **development-only**. The archive already shaped the hypothesis (the xG-beats-goals
and finishing-does-not-persist measurements in [`docs/research-adaptation.md`](research-adaptation.md)),
and the historical target roster and first-kickoff cutoff remain unversioned proxies (the same reason
every Stage B candidate is development-only). A later historical number can diagnose the model under
those proxies; it cannot establish real-deadline knowledge-time validity or promote a production model.

Amendment 1.1 adds this candidate policy only. The complete version 1.0 population, target-roster
policy, two baselines and their definitions, metrics, scoring/calibration definitions, promotion
gate, reporting, seed, and Monte Carlo exclusion remain unchanged.

## Hypothesis

The Stage C baseline record showed `trailing_player_goal_rate_poisson` leading
`positional_goal_rate_poisson` on every proper distribution metric overall and in every season (mean
log score 0.143547 vs 0.154512). The trailing baseline estimates a player's goal rate from his own
recent **recorded goals**. Candidate V1 tests one hypothesis only, drawn from the measured constants:

- **xG beats recorded goals as the attacking signal where xG is measured.** Recorded goals are a
  noisy realisation of chance quality; `expected_goals` is the less noisy underlying signal. The
  candidate replaces the recent-goals signal with recent-xG wherever xG is measured.
- **Finishing (goals − xG) does not persist within position.** Measured season-to-season persistence
  is at the noise floor — FWD 0.138, MID 0.060, DEF −0.103 — so a player's own over-/under-performance
  of his xG is shrunk almost fully to the positional mean. The candidate keeps 5% of the player's own
  trailing finishing and 95% of the positional mean finishing.

Where xG is unmeasured, the candidate does nothing new: it falls back to the exact v1.0
trailing-player baseline. It therefore reduces to that baseline bit-for-bit in 2021-22 (no xG at all)
and partially in 2022-23 (xG measured only from GW16 onward).

## Exact estimator

For a target prediction at player `code`, position `p`, inside one walk-forward fold whose training
history is every prior eligible row with `kickoff_time < as_of`:

**Fold-local positional means** (recomputed inside each fold from the same prior history the v1.0
baselines use):

- `pos_g[p]` — mean goals per appearance at position `p` over all prior eligible rows at `p`. This is
  *exactly* the v1.0 `positional_goal_rate_poisson` rate (the same `PositionalGoalRateBaseline`).
- `pos_x[p]` — mean `expected_goals` per appearance at position `p`, computed only over prior
  eligible rows at `p` whose `expected_goals` is non-NULL. `pos_x[p]` is undefined when no prior row
  at `p` carries a measured xG.

**Per-target rate.** Take the up to five most recent prior player-fixture rows for `code` (same
recency order and window as the v1.0 trailing baseline: `kickoff_time`, then `season`, then
`fixture`, including zero-goal rows). Let `n` be their count (0–5).

- **Cold start** (`n = 0`): `rate = pos_g[p]`. Identical to the v1.0 trailing baseline's fallback.
- **xG-informed path**, used iff at least one of the trailing rows carries a measured xG **and**
  `pos_x[p]` is defined. Let `measured` be the trailing rows with non-NULL `expected_goals`, `m` their
  count, `S_x = Σ expected_goals` over them, and `S_gm = Σ goals` over them:

  ```text
  shrunk_xg   = (S_x + alpha * pos_x[p]) / (m + alpha)
  player_fin  = (S_gm - S_x) / m
  pos_fin     = pos_g[p] - pos_x[p]
  finish_term = finishing_keep * player_fin + (1 - finishing_keep) * pos_fin
  rate        = max(0.0, shrunk_xg + finish_term)
  ```

- **Fallback path** (no measured xG among the trailing rows, or `pos_x[p]` undefined):

  ```text
  rate = (S_g + alpha * pos_g[p]) / (n + alpha)
  ```

  where `S_g = Σ goals` over all `n` trailing rows. This is **exactly** the v1.0
  `trailing_player_goal_rate_poisson` shrunk rate, bit-for-bit.

The prediction is the Poisson goal-count distribution over `0..10` (tail folded into 10) at `rate`,
via the existing `poisson_pmf`.

**Frozen constants** (pinned in the contract; changing either fails to load):

- `alpha = 5.0` — the shrinkage of trailing xG toward `pos_x`. This mirrors the v1.0 trailing
  baseline's goals shrinkage exactly, so the only structural change is goals → xG.
- `finishing_keep = 0.05` — finishing is shrunk 95% to the positional mean. Within-position finishing
  persistence is measured at the noise floor, so a candidate reporting a gain from keeping more
  finishing is reporting noise.

There is **no parameter grid and no inner walk-forward selection**: `selected_parameter` is pinned to
`none`. This candidate is a fixed closed-form estimator. "Fold-local" means the positional means and
player histories are recomputed inside each fold (point-in-time safe), not that any parameter is
tuned per fold. This is the material difference from the Stage B candidates, each of which selected a
parameter on a nested walk-forward; V1 has nothing to select and therefore nothing to overfit to the
outer holdout.

## Frozen history and identity policy

- Prediction grain remains `(season, code, fixture)`; double-gameweek fixtures are never collapsed.
- Stable `code` is the only cross-season player identity. A bare `element_id` or archive `element` is
  never used.
- History is the up to five most recent prior player-fixture rows, ordered by `kickoff_time`, then
  `season`, then `fixture`, including zero-goal rows.
- Every history outcome satisfies the strict cutoff `kickoff_time < as_of`. The predicted gameweek is
  isolated as a batch; no row in a gameweek trains another prediction in that gameweek.
- The target label (`goals_scored`) stays outside model inputs. Candidate inputs are prior
  `expected_goals`, prior `goals`, the target's stable `code`, and its current position from the
  existing historical roster proxy. The target row's own `expected_goals` is never read — it is an
  in-match outcome and would be leakage.
- NULL `expected_goals` means unmeasured and is never zero-filled. This is the per-row signal the
  candidate keys on; it matches `xg_signal_policy.use_when_measured_within_covered_seasons` and the
  archive's measured coverage (2021-22 0%, 2022-23 68% / NULL GW1–15, 2023-24+ 100%).
- Zero-goal and zero-minute rows remain in history (an appearance is an appearance). Assistant
  Manager elements (`element_type == 5`) remain excluded upstream.

The target current position is still an unversioned historical proxy; amendment 1.1 does not upgrade
that field to known-at-deadline evidence. Live use requires the existing versioned player-registry
policy with `known_at <= as_of` before entity, position, or club reaches the model.

## xG coverage and the "reduces to baseline" guarantee

`expected_goals` is NULL where unmeasured. Measured coverage on the archive:

| Season | rows (min not null) | xG not-null | xG coverage |
|---|---:|---:|---:|
| 2021-22 | 25,447 | 0 | 0.0% |
| 2022-23 | 26,505 | 18,014 | 67.96% (NULL GW1–15, measured GW16+) |
| 2023-24 | 29,725 | 29,725 | 100.0% |
| 2024-25 | 27,283 | 27,283 | 100.0% |
| 2025-26 | 29,747 | 29,747 | 100.0% |

Because `pos_x[p]` is undefined whenever no prior row at `p` carries xG, every prediction in a 2021-22
fold (and the GW1–15 portion of 2022-23 folds, before any xG has been observed) takes the fallback
path and is bit-identical to the v1.0 trailing baseline. The xG signal only begins to act once a
position has accumulated measured-xG prior rows. The offline test suite asserts this bit-identity on
a fixture where all `expected_goals` are NULL.

## Double-gameweek behavior

Every `(season, code, fixture)` target remains a separate prediction and scored row. All fixtures in
one target gameweek use the same pre-gameweek history; no result is absorbed until the whole gameweek
has been predicted. Because Candidate V1 has no fixture-specific feature, the same `code` and
current-position pair may receive the same distribution for both fixtures of a double gameweek. That
is intentional, must be reported honestly, and is never permission to collapse the two fixture rows.

## Point-in-time argument

- **Target leakage:** target `goals_scored`, `expected_goals`, `mart_target_*`, and recorded points
  are not model inputs. The validation layer alone retains labels for scoring.
- **Event-time leakage:** all candidate history uses only rows with `kickoff_time < as_of`; the
  predicted gameweek is isolated as a batch.
- **Knowledge-time limitation:** the archive roster and first-kickoff cutoff are unversioned proxies.
  Availability is excluded. This is why the candidate is development-only.
- **Identity leakage:** player history uses stable `code`; fixture rows keep season-qualified grain.
  Candidate V1 performs no cross-season team join.

## Evaluation and unchanged gate

The implemented development runner scores Candidate V1 and the two frozen v1.0 baselines on the same
eligible rows (the candidate is fitted on the identical fold history the baselines use and predicts
the identical targets, enforced structurally by the harness). The frozen version 1.0 gate remains the
reference without any change:

- at least 1% aggregate mean-log-score lift over the best eligible required baseline
  (`trailing_player_goal_rate_poisson`, 0.143547 → must reach 0.142111 or better);
- no aggregate regression on RPS or Brier (`P(goals >= 1)`);
- PIT-80 absolute error at most 0.05;
- full prediction coverage over at least 181 folds;
- zero leakage failures; and
- no per-season mean-log-score regression.

Each condition is reported as its own labelled development diagnostic and is never combined into a
production promotion verdict. Reliability curves remain report-only.

**xG judging.** Per `xg_signal_policy.xg_covered_seasons_judging`, the xG effect is judged *within*
the xG-covered seasons (2023-24, 2024-25, 2025-26). The candidate reduces to the baseline in 2021-22
and partially in 2022-23, so those seasons cannot credit or blame xG; the per-season log scores are
still reported for all five seasons, but the xG signal's value is read from 2023-24 onward.

## Implemented runner provenance

The runner is implemented and offline-reviewed before use. It mirrors the Stage B candidate runners
and must continue to:

- refuse a dirty worktree at preflight and require it to remain clean at postflight;
- record and recheck Git HEAD, Git status, the evaluation-config SHA-256, the Candidate V1
  model-source SHA-256, and the database SHA-256 before publishing a result;
- suppress the result or mark it invalid if any recheck detects a time-of-check/time-of-use change;
- open the database read-only and confirm its hash is unchanged;
- record the fixed seed and UTC start/end timestamps; and
- emit the full folds, seasons, positions, venues, coverage, calibration, xG/fallback path split, and
  assertion record needed for independent reconciliation.

## Next step

The development runner, unchanged-baseline comparison, provenance rechecks, strict-JSON reconciliation
record, and deterministic offline tests are implemented and reviewed. The next step is one explicitly
authorized clean historical development run using the committed provenance-ready runner. Any formula,
constant, window, fallback, feature, or selection-policy change after a V1 number exists is a new
named candidate under a new amendment, never a V1 retune.
