# Stage C Attacking Goals — Candidate V3 (minutes-gated coupled share) — design record

> **Status: frozen pre-registration record, written before any V3 evaluation.** Candidate V3 is
> pre-registered under `config/phase3_evaluation.yaml` **amendment 1.3** (contract version `1.3`,
> additive over the unchanged v1.0/1.1/1.2 population, target roster, baselines, metrics, and gate).
> The single authorized historical development run records its number in
> `docs/phase3-stage-c-attacking-candidate-v3-development.md` and is **development-only — not a
> promotion verdict**. Any formula, constant, window, fallback, feature, or selection-policy
> change after a V3 number exists is a new named candidate under a new amendment, never a V3 retune.

## 1. Hypothesis

Candidate V2 (`coupled_team_share_attacking_goals_v2`) allocated the Stage A team-goal expectation
among a club's players by a trailing attacking share, but treated every roster player as if certain
to appear. Candidate V3 tests whether **explicitly gating each player's rate by an appearance
probability** helps: a player unlikely to play should contribute proportionally less expected
attacking output, with appearance probability and per-appearance attacking rate kept as separate
components (R6). V3 is V2 with one change:

    weighted_i = share_i * p_play_i
    rate_i     = lambda_team * weighted_i / sum_j(weighted_j)   =>   sum_i rate_i = lambda_team.

`share_i` is V2's trailing attacking share (unchanged). `p_play_i = P(minutes >= 1)` comes from the
frozen Stage B BASELINE `trailing_5_player_minutes` (a deterministic baseline, not an unpromoted
candidate), refit fold-local on player-fixture history with `kickoff_time < as_of`.

## 2. Exact estimator

For each Stage C fold `(season, gw)` at `as_of` = first kickoff of the predicted gameweek:

1. **`lambda_team` (Stage A, reused).** As V2: the frozen `trailing_goals_attack_defence` baseline
   refit fold-local on team-match history (`kickoff_time < as_of`), keyed by stable `team_code`.
2. **`share_i` (V2 share machinery, reused).** As V2: each roster player's trailing attacking signal
   (`expected_goals` in xG-covered seasons 2023-24+, `threat` otherwise) over the trailing 5
   **appeared** prior rows (`minutes > 0`), normalised so the club's eligible roster in the fixture
   sums to 1; cold-start players take the positional mean of the same signal type; a zero-signal
   roster takes equal shares.
3. **`p_play_i` (Stage B baseline, reused not reimplemented).** The frozen `trailing_5_player_minutes`
   baseline is refit fold-local on player-fixture history (`kickoff_time < as_of`) and
   `p_play_i = P(minutes >= 1) = 1 - dist[0]` from its four-bin distribution. This is a frozen
   BASELINE, so it introduces no unpromoted-candidate dependency.
4. **Rate.** `weighted_i = share_i * p_play_i`; renormalise so the weighted shares sum to 1;
   `rate_i = lambda_team * weighted_i / sum_j(weighted_j)`. Predict `Poisson(rate_i)` over `0..10`.

This is a **fixed closed-form estimator**: no parameter grid, no inner walk-forward
(`selected_parameter` pinned to `none`); `alpha` mirrors the v1.0 trailing baseline (5.0) and is
used only by the stage-A-uninformative fallback.

### Conservation rule (documented)

V3 renormalises `share_i * p_play_i` to sum to 1 **before** multiplying by `lambda_team`, so the
coupled path still conserves the team total (`sum_i rate_i = lambda_team`). The alternative (a
sub-`lambda_team` total accepting that benched mass is unaccounted for) is rejected: it would drop
the team's expected goals whenever any roster player is uncertain to appear, which conflates
appearance uncertainty with team scoring strength. Renormalisation instead redistributes the mass of
low-`p_play` players to those more likely to appear.

### Fallbacks (every target receives a prediction)

- **Stage A uninformative** (empty team-match window): every player on that club takes the exact v1.0
  `trailing_player_goal_rate_poisson` rate (uncoupled, ungated) — the bit-for-bit
  `reduces_to_baseline` guarantee inherited from V2.
- **All `p_play` zero** (a roster everyone is predicted not to appear): fall back to the unweighted
  V2 allocation, keeping the team total at `lambda_team`.
- **Cold-start player** (no appeared prior row): V2's positional-mean share (then gated by their
  `p_play`, which for a cold-start player is the positional appearance rate from the Stage B
  fallback).

## 3. Reduces-to-V2 guarantee

With `minutes_gating` disabled, V3 is bit-for-bit V2: the allocation function takes the V2 code path
(`allocate_coupled_rates`) unchanged. With gating on and every `p_play == 1`, the renormalisation is
the identity, so V3 also reduces to V2 numerically. The R6 separation (minutes and per-appearance
attacking rate are distinct multiplied components, never a single joint fit) is structural.

## 4. Leakage guards (V2's surfaces carry over, plus a Stage B surface)

- Stage A is fit on team-match history with `kickoff_time < as_of`; `lambda_team` never reads the
  predicted gameweek's goals.
- Player shares use appeared prior rows only; the target fixture's minutes/goals/xG/threat never
  enter the rate.
- Club identity is `team_code` end-to-end (Stage A and Stage B both resolve `team_id` to `team_code`
  via `mart_dim_team`); no bare cross-season `team_id` join.
- **Stage B** is fit on player-fixture history with `kickoff_time < as_of`; the target fixture's
  minutes never enter `p_play`. Minutes and attacking rate are separate components (R6).
- The share denominator and the Stage B history are the existing unversioned `target_roster` /
  archive proxies the contract already declares — not new leakage, and stated reasons the verdict is
  development-only.

## 5. Evaluation and unchanged gate

Same population, grain, folds, metrics, and gate as v1.0/1.1/1.2. The comparator is the best
required Stage C attacking baseline (`trailing_player_goal_rate_poisson` at **0.143547**). The frozen
gate is unchanged: ≥ 1% aggregate mean-log lift, no aggregate RPS/Brier(≥1) regression vs the
best-per-metric baseline, PIT-80 absolute error ≤ 0.05, ≥ 181 folds, coverage 1.0, no per-season
mean-log regression, zero leakage. V3-vs-V2 and V3-vs-V1 are reported as diagnostics (never a gate).

## 6. Implemented runner provenance

`src/fpl/validate/dev_attacking_candidate_v3.py` mirrors V2's provenance-guarded runner and adds the
Stage B bins (read from the frozen Phase 2 contract). It fingerprints `attacking_v3.py` (the
candidate) plus `attacking_v2.py` and `attacking_v1.py` (the V3-vs-V2 live co-score and the V3-vs-V1
cited diagnostic), refuses a dirty worktree, runs read-only, and re-checks all fingerprints at
postflight. V3 is fixture-coupled, so it uses the same optional `prepare(targets, con, as_of)` hook
as V2.

## 7. Next step

Run the runner **once** as a clean historical development run; record
`docs/phase3-stage-c-attacking-candidate-v3-development.md` plus verbatim evidence JSON under
`docs/evidence/`. The verdict is **DEVELOPMENT-ONLY — NOT PROMOTED** regardless of the number: the
historical target roster and first-kickoff cutoff are unversioned archive proxies AND the Stage B
minutes input is itself a development proxy, so real-deadline knowledge-time validity is unproven. A
second historical evaluation is not permitted, and nothing here is retuned.
