# Stage C attacking assists — Candidate V1 design: xA-informed trailing player assists

**Status: frozen pre-registration record, written before any Candidate V1 evaluation.**

Candidate V1 is named `xa_informed_trailing_player_assists_v1` in
`config/phase3_stage_c_assists_evaluation.yaml` **amendment 1.1** (contract version `1.1`,
additive over the unchanged v1.0 population, target roster, baselines, metrics, and gate). The
exact estimator is pinned in the contract's `stage_c_assists_candidate_v1` block and will be
implemented in `src/fpl/models/attacking_assists_v1.py`, covered by deterministic offline tests.
A separately named, provenance-guarded development runner will live in
`src/fpl/validate/dev_assists_candidate_v1.py`. The single authorized historical development run
records its number in
[`phase3-stage-c-assists-candidate-v1-development.md`](phase3-stage-c-assists-candidate-v1-development.md)
and is **development-only — not a promotion verdict**. Any formula, constant, window, fallback,
feature, or selection-policy change after a V1 number exists is a new named candidate under a new
amendment, never a V1 retune.

Candidate V1 is **development-only**. The archive already shaped the hypothesis (the xA-beats-goals
analogue and the assists-minus-xA persistence measurement in
[`phase3-stage-c-assists-baseline-development.md`](phase3-stage-c-assists-baseline-development.md)
§7), and the historical target roster and first-kickoff cutoff remain unversioned proxies (the same
reason every Stage B/C candidate is development-only).

Amendment 1.1 adds this candidate policy only. The complete version 1.0 population, target-roster
policy, two baselines and their definitions, metrics, scoring/calibration definitions, promotion
gate, reporting, seed, and Monte Carlo exclusion remain unchanged.

## Hypothesis

The Stage C assists baseline record showed `trailing_player_assist_rate_poisson` leading
`positional_assist_rate_poisson` on every metric overall and on mean log score in every season (mean
log score 0.142730 vs 0.148409). The trailing baseline estimates a player's assist rate from his own
recent **recorded assists**. Candidate V1 tests one hypothesis only, drawn from the measured
constants:

- **xA (expected_assists) beats recorded assists as the per-appearance signal where xA is measured.**
  Recorded assists are a noisy realisation of chance-creation quality; `expected_assists` is the less
  noisy underlying signal. The candidate replaces the recent-assists signal with recent-xA wherever
  xA is measured (per row), and fills xA-unmeasured rows with `creativity` rescaled to the assist-rate
  scale (creativity is the FPL-native creative index, measured 100% every season — the xA analogue of
  `threat`).
- **The assist residual (assists − xA) is shrunk almost fully to the positional mean.** The
  supporting measurement (`phase3-stage-c-assists-baseline-development.md` §7) found assists-minus-xA
  season-to-season within-position persistence of DEF +0.01 / MID +0.16 / FWD +0.19 / GK −0.07 — modest
  (a trailing-5 residual captures far less than the full-season figure), so a player's own
  over-/under-performance of his xA is shrunk 95% to the positional mean. The candidate keeps 5% of the
  player's own trailing residual and 95% of the positional residual.
- **R6 appearance fix (learned from the Stage C goals V2/V3 work).** The per-appearance signal is
  computed over **appeared** prior rows only (`minutes > 0`), so a did-not-play prior row cannot dilute
  a per-appearance rate; availability is separated from rate.

Where xA is unmeasured on a player's trailing appeared rows, the candidate does nothing new: it falls
back to the exact v1.0 trailing-assist baseline. It therefore reduces to that baseline bit-for-bit in
2021-22 (no xA at all) and partially in 2022-23 (xA measured only from GW16 onward).

## Exact estimator

For a target prediction at player `code`, position `p`, inside one walk-forward fold whose training
history is every prior eligible row with `kickoff_time < as_of`:

**Fold-local positional means** (recomputed inside each fold from the same prior history the v1.0
baselines use):

- `pos_a[p]` — mean assists per appearance at position `p` over ALL prior eligible rows at `p`. This
  is *exactly* the v1.0 `positional_assist_rate_poisson` rate (the same
  `PositionalAssistRateBaseline`), so the fallback path is bit-identical to the baseline.
- `pos_xa[p]` — mean `expected_assists` per appearance at position `p`, computed only over prior
  **appeared** rows (`minutes > 0`) at `p` whose `expected_assists` is non-NULL. `pos_xa[p]` is
  undefined when no prior appeared row at `p` carries a measured xA.
- `mean_creativity[p]` — mean `creativity` over prior **appeared** rows at `p` (creativity is 100%
  covered, so always defined when any appeared row at `p` exists).
- `creativity_factor[p] = pos_a[p] / mean_creativity[p]` — the fold-local positional creativity→assist
  rescale (0 if `mean_creativity[p]` is 0). This is the **pinned rescale rule**: a fixed positional
  factor that maps creativity onto the assist-rate scale, calibrated fold-locally.

**Per-target rate.** Two windows are kept, mirroring the two requirements (R6 appeared-only signal;
bit-identical fallback):

- `recent_all` — the up to five most recent prior rows for `code` over ALL rows (including zero-minute),
  the SAME window and order the v1.0 trailing baseline uses (`kickoff_time`, then `season`, then
  `fixture`). Used only by the fallback path so it is bit-identical to the baseline.
- `recent_appeared` — the up to five most recent prior **appeared** rows for `code` (`minutes > 0`).
  Used by the xA signal (R6: availability never dilutes the per-appearance rate).

Decision:

- **Cold start** (`recent_all` empty, i.e. no prior row at all): `rate = pos_a[p]`. Identical to the
  v1.0 trailing baseline's fallback. Path `cold_start`.
- **Fallback** (`recent_appeared` empty, OR no row in `recent_appeared` carries a measured xA, OR
  `pos_xa[p]` undefined):

  ```text
  rate = (S_a_all + alpha * pos_a[p]) / (n_all + alpha)
  ```

  where `S_a_all = Σ assists` and `n_all = len(recent_all)`. This is **exactly** the v1.0
  `trailing_player_assist_rate_poisson` shrunk rate over the all-rows window, bit-for-bit. Path
  `fallback_v1`.
- **xA-informed path**, used iff `recent_appeared` is non-empty AND at least one of its rows carries a
  measured xA AND `pos_xa[p]` is defined. Per-row expected-assist signal over `recent_appeared`:

  ```text
  xa_i = expected_assists_i            if expected_assists_i is not NULL
       = creativity_factor[p] * creativity_i   otherwise
  ```

  (NULL xA is filled by rescaled creativity, not dropped — creativity is the xA fallback signal.) Let
  `n = len(recent_appeared)`, `S_xa = Σ xa_i`, `S_a = Σ assists` over `recent_appeared`:

  ```text
  shrunk_xa       = (S_xa + alpha * pos_xa[p]) / (n + alpha)
  player_residual = (S_a - S_xa) / n
  pos_residual    = pos_a[p] - pos_xa[p]
  residual_term   = finishing_keep * player_residual + (1 - finishing_keep) * pos_residual
  rate            = max(0.0, shrunk_xa + residual_term)
  ```

  Path `xa_informed`.

The prediction is the Poisson assist-count distribution over `0..10` (tail folded into 10) at `rate`,
via the existing `poisson_pmf`.

**Frozen constants** (pinned in the contract; changing either fails to load):

- `alpha = 5.0` — the shrinkage of trailing xA toward `pos_x`. This mirrors the v1.0 trailing baseline's
  assists shrinkage exactly, so the only structural change is assists → xA.
- `finishing_keep = 0.05` — the assist residual is shrunk 95% to the positional mean. The measured
  within-position persistence is modest (§7 of the baseline record); a candidate reporting a gain from
  keeping more residual is reporting noise.

There is **no parameter grid and no inner walk-forward selection**: `selected_parameter` is pinned to
`none`. This candidate is a fixed closed-form estimator. "Fold-local" means the positional means and
player histories are recomputed inside each fold (point-in-time safe), not that any parameter is tuned
per fold.

## Frozen history and identity policy

- Prediction grain remains `(season, code, fixture)`; double-gameweek fixtures are never collapsed.
- Stable `code` is the only cross-season player identity. A bare `element_id` or archive `element` is
  never used.
- The xA signal window is the up to five most recent prior **appeared** player-fixture rows
  (`minutes > 0`), ordered by `kickoff_time`, then `season`, then `fixture` (R6 appearance fix). The
  fallback window is the up to five most recent prior rows over ALL rows (matching the baseline, so the
  fallback is bit-identical).
- Every history outcome satisfies the strict cutoff `kickoff_time < as_of`. The predicted gameweek is
  isolated as a batch.
- The target label (`assists`) stays outside model inputs. Candidate inputs are prior
  `expected_assists`, prior `creativity`, prior `assists`, the target's stable `code`, and its current
  position from the existing historical roster proxy. The target row's own `expected_assists` /
  `creativity` are never read — they are in-match outcomes and would be leakage.
- NULL `expected_assists` means unmeasured and is never zero-filled; a NULL-xA row on the xA path is
  filled by rescaled `creativity` (which is measured). NULL `creativity` does not occur (100% coverage).
- Zero-minute prior rows are excluded from the appeared signal window (R6) but a zero-minute TARGET row
  remains scored (it is part of the eligible population). Assistant Manager elements
  (`element_type == 5`) remain excluded upstream.

The target current position is still an unversioned historical proxy; amendment 1.1 does not upgrade
that field to known-at-deadline evidence.

## xA coverage and the "reduces to baseline" guarantee

`expected_assists` is NULL where unmeasured, with the SAME coverage profile as `expected_goals`:
2021-22 0%, 2022-23 partial (NULL GW1–15, measured GW16+), 2023-24 / 2024-25 / 2025-26 100%
(asserted in `tests/test_attacking_assists_archive.py`).

Because `pos_xa[p]` is undefined whenever no prior appeared row at `p` carries xA, every prediction in
a 2021-22 fold (and the GW1–15 portion of 2022-23 folds, before any xA has been observed) takes the
fallback / cold-start path and is bit-identical to the v1.0 trailing baseline. The xA signal only
begins to act once a position has accumulated measured-xA appeared prior rows. The offline test suite
asserts this bit-identity on a fixture where all `expected_assists` are NULL.

## Creativity rescale (pinned rule)

`creativity` is on a different unit than `expected_assists` (an Opta index in the tens–hundreds vs an
assist expectation around 0.05–0.2 per appearance), so it must be rescaled onto the assist-rate scale
before it can fill a NULL-xA row. The pinned rule is a **fixed fold-local positional factor**:

```text
creativity_factor[p] = pos_a[p] / mean_creativity[p]
rescaled_creativity_i = creativity_factor[p] * creativity_i
```

so that, position by position, the mean rescaled creativity equals the positional assist mean. This is
calibrated fold-locally (per fold, per position, over appeared prior rows) and pinned before the run; it
is not tuned to the result. The alternative (regressing appeared assists on appeared creativity within
the training window) is recorded as not adopted: a single positional factor is the simpler, pinned,
interpretable mapping and avoids fitting a slope on a small fold-local sample.

## Defender emphasis

`docs/research-adaptation.md` §2.1 establishes that for DEF the attacking signal is **xA, not xG** (xA
persists at 0.784 vs xG 0.319 for defenders). Candidate V1 uses xA directly, so the hypothesis is that
it helps DEF. The development record reports a by-position slice (esp. DEF) alongside the primary lift.

## Double-gameweek behavior

Every `(season, code, fixture)` target remains a separate prediction and scored row. All fixtures in
one target gameweek use the same pre-gameweek history. Because Candidate V1 has no fixture-specific
feature, the same `code` and current-position pair may receive the same distribution for both fixtures
of a double gameweek. That is intentional, must be reported honestly, and is never permission to
collapse the two fixture rows.

## Point-in-time argument

- **Target leakage:** target `assists`, `expected_assists`, `creativity`, `mart_target_*`, and recorded
  points are not model inputs. The validation layer alone retains labels for scoring.
- **Event-time leakage:** all candidate history uses only rows with `kickoff_time < as_of`; the
  predicted gameweek is isolated as a batch.
- **Knowledge-time limitation:** the archive roster and first-kickoff cutoff are unversioned proxies.
  Availability is excluded. This is why the candidate is development-only.
- **Identity leakage:** player history uses stable `code`; fixture rows keep season-qualified grain.
  Candidate V1 performs no cross-season team join.

## Evaluation and unchanged gate

The implemented development runner will score Candidate V1 and the two frozen v1.0 baselines on the
same eligible rows (the candidate is fitted on the identical fold history the baselines use and
predicts the identical targets, enforced structurally by the harness). The frozen version 1.0 gate
remains the reference without any change:

- at least 1% aggregate mean-log-score lift over the best eligible required baseline
  (`trailing_player_assist_rate_poisson`, 0.142730 → must reach 0.141302 or better);
- no aggregate regression on RPS or Brier (`P(assists >= 1)`) vs the best baseline value of each metric;
- PIT-80 absolute error at most 0.05;
- full prediction coverage over at least 181 folds;
- zero leakage failures; and
- no per-season mean-log-score regression.

Each condition is reported as its own labelled development diagnostic and is never combined into a
production promotion verdict.

**xA judging.** Per `xa_signal_policy.xa_covered_seasons_judging`, the xA effect is judged *within* the
xA-covered seasons (2023-24, 2024-25, 2025-26). The candidate reduces to the baseline in 2021-22 and
partially in 2022-23, so those seasons cannot credit or blame xA; the per-season log scores are still
reported for all five seasons, but the xA signal's value is read from 2023-24 onward.

## Implemented runner provenance

The runner will mirror the Stage C goals Candidate V1 runner and must:

- refuse a dirty worktree at preflight and require it to remain clean at postflight;
- record and recheck Git HEAD, Git status, the evaluation-config SHA-256, the Candidate V1
  model-source SHA-256, and the database SHA-256 before publishing a result;
- suppress the result as INVALID/UNPUBLISHABLE if any recheck detects a time-of-check/time-of-use
  change;
- open the database read-only and confirm its hash is unchanged;
- record the fixed seed and UTC start/end timestamps; and
- emit the full folds, seasons, positions, venues, coverage, calibration, xA/fallback path split, and
  assertion record needed for independent reconciliation.

## Next step

Implement the development runner, unchanged-baseline comparison, provenance rechecks, strict-JSON
reconciliation record, and deterministic offline tests, then run **once** as a clean historical
development run. The verdict is **DEVELOPMENT-ONLY — NOT PROMOTED** regardless of the number: the
historical target roster and first-kickoff cutoff are unversioned archive proxies, so real-deadline
knowledge-time validity is unproven. A second historical evaluation is not permitted, and nothing here
is retuned.
