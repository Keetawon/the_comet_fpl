# Stage C Attacking Goals — Candidate V2 (coupled team share) — design record

> **Status: frozen pre-registration record, written before any V2 evaluation.** Candidate V2 is
> pre-registered under `config/phase3_evaluation.yaml` **amendment 1.2** (contract version `1.2`,
> additive over the unchanged v1.0/1.1 population, target roster, baselines, metrics, and gate).
> The single authorized historical development run records its number in
> `docs/phase3-stage-c-attacking-candidate-v2-development.md` and is **development-only — not a
> promotion verdict**. Any formula, constant, window, fallback, feature, or selection-policy
> change after a V2 number exists is a new named candidate under a new amendment, never a V2 retune.

## 1. Hypothesis

The two v1.0 Stage C attacking baselines predict each player's goals *independently* from that
player's own trailing history. Candidate V1 (`xg_informed_trailing_player_goals_v1`) kept that
independent structure and improved the per-player signal (xG where measured, finishing shrunk to
the positional mean), reaching **mean log score 0.137813 (+3.99% over the best baseline
`trailing_player_goal_rate_poisson` at 0.143547)** as a development number.

Candidate V2 tests a **structural** hypothesis instead: a player's goals are not independent of his
team's scoring. The team is expected to score `lambda_team` goals (Stage A), and the players
*share* that total. So V2 predicts player `i`'s goals as a Poisson thinning of the team expectation:

    rate_i = lambda_team * share_i ,  with  sum_i share_i = 1  =>  sum_i rate_i = lambda_team.

Conservation is structural, not fitted: the per-player marginals are exact independent Poissons
that add up to the Stage A team total. The evidence this is drawn from (`docs/research-adaptation.md`):
team strength combines **multiplicatively** (`attack x opponent defence` correlates 0.439 with goals
scored; the subtractive form manages 0.070), so a team-goal expectation is the right scale to
allocate; xG and `threat` both persist within position, and `threat` is measured for every season
including 2021-22 which carries no xG.

V2's second change is the **R6 appearance-vs-rate correction** (V1's history included zero-minute
rows in the rate). A did-not-play prior row carries no attacking information, so it must not dilute
a per-appearance rate: V2 computes each player's trailing attacking signal over **appeared** prior
rows only (`minutes > 0`), separating availability from per-appearance productivity.

## 2. Exact estimator

For each Stage C fold `(season, gw)` at `as_of` = first kickoff of the predicted gameweek:

1. **`lambda_team` (Stage A, reused not reimplemented).** The frozen
   `trailing_goals_attack_defence` baseline is refit fold-local on team-match history with
   `kickoff_time < as_of`, then `rate_for({team_code, opponent_team_code, was_home})` gives each
   club's expected goals for its fixture in this gameweek. Club identity is the stable `team_code`
   resolved from the season-qualified `team_id` via `mart_dim_team`; a bare `team_id` is never
   joined across seasons (it is reassigned every summer and recurs — id 10 is Leeds, Leicester,
   Fulham, Ipswich, then Fulham again).

2. **Per-player trailing attacking signal (appeared rows only).** For player `i`, take the trailing
   5 prior player-fixture rows with `minutes > 0`, ordered `kickoff_time, season, fixture`. The
   signal for a row is `expected_goals` where measured, else `threat`; `NULL` is unmeasured and
   never zero-filled. The player's signal is the **mean** of those appeared rows (a per-appearance
   attacking rate).

3. **Share normalisation.** The share denominator is the club's **eligible roster in the fixture**
   — the same unversioned `target_roster` proxy the v1.0 baselines already declare (the scored
   population; zero-minute target rows stay in it). For each roster player the unnormalised share
   `s_i` is the per-appearance signal from step 2; `share_i = s_i / sum_j s_j`.

4. **Rate and prediction.** `rate_i = lambda_team * share_i`; predict `Poisson(rate_i)` over
   `0..10` (tail folded into 10), via the existing `poisson_pmf`.

This is a **fixed closed-form estimator**: no parameter grid, no inner walk-forward
(`selected_parameter` pinned to `none`). The single constant `alpha` mirrors the v1.0 trailing
baseline (5.0) and is used only by the stage-A-uninformative fallback.

### Fallbacks (every target receives a prediction; each path is tallied)

- **Cold-start player** (no appeared prior row): `s_i` = the fold-local positional goal mean —
  identical to the v1.0 `positional_goal_rate_poisson` baseline — so a new player is not zeroed but
  gets the average positional share.
- **Equal share**: if a club's roster signal sums to zero (e.g. every roster player has zero
  trailing attacking output), `share_i = 1 / |roster|` for every roster player.
- **Stage A uninformative**: if the Stage A training window is empty (no team-match history before
  `as_of`), the candidate cannot couple, so every player on that club takes the **exact v1.0
  `trailing_player_goal_rate_poisson` rate** (their own shrunk-goals rate, or the positional mean if
  the player is cold-start). This is the bit-for-bit `reduces_to_baseline` guarantee.

## 3. Frozen history and identity policy

- Grain `(season, code, fixture)`; stable `code` is the only cross-season player key; double
  gameweeks keep separate fixture rows.
- History window 5, ordered `kickoff_time, season, fixture`, strict `kickoff_time < as_of`.
- The appeared-rows filter uses `minutes > 0` on **prior** rows only; target rows' `minutes`,
  `goals_scored`, `expected_goals`, `threat` never enter the rate. `NULL` xG/threat = unmeasured.
- Target current position is the unversioned historical proxy (not known-at-deadline) — a reason
  the verdict is development-only, unchanged from V1.
- Assistant Manager elements (`element_type == 5`) are excluded upstream.

## 4. Stage A coupling and the "reduces to baseline" guarantee

V2 imports the frozen Stage A baseline class and calls it; it does **not** reimplement Stage A. The
coupling is one-directional: Stage A produces `lambda_team` from team-match history, V2 allocates
it. Where Stage A is uninformative (empty training window) V2 falls back to the exact v1.0
trailing-player rate per player, so on those rows V2 is the baseline bit-for-bit. On the coupled
path the per-player rates sum to `lambda_team` by construction.

## 5. Double-gameweek behaviour

Fixture rows remain separate. A club with two fixtures in a gameweek has two `lambda_team` values
and two roster-normalised share allocations; a player in both fixtures gets a separate rate per
fixture. No within-gameweek absorption.

## 6. Point-in-time argument

V2 has more leakage surfaces than V1, each addressed:

- **Stage A** is fit on team-match history with `kickoff_time < as_of`; `lambda_team` never reads
  the predicted gameweek's goals. The harness already asserts no target fixture kicked off before
  `as_of`.
- **Player shares** use appeared prior rows only; the target fixture's minutes/goals/xG/threat
  never enter the rate.
- **Club identity** is `team_code` end-to-end; the candidate asserts it never joins a bare
  cross-season `team_id` (the relegated-and-returning-club failure mode).
- **Share denominator** is the existing unversioned `target_roster` proxy the contract already
  declares, routed through that mechanism — not new leakage. It is a stated reason the verdict is
  development-only.

## 7. Evaluation and unchanged gate

Same population, grain, folds, metrics, and gate as v1.0/1.1. The comparator is the best required
Stage C attacking baseline by mean log score (`trailing_player_goal_rate_poisson` at **0.143547**;
`positional_goal_rate_poisson` at 0.154512). The frozen gate (unchanged): ≥ 1% aggregate mean-log
lift, no aggregate RPS regression vs the best baseline RPS, no aggregate Brier(≥1) regression vs
the best baseline Brier, PIT-80 absolute error ≤ 0.05, ≥ 181 folds, coverage 1.0, no per-season
mean-log regression, zero leakage. As for V1, the xG/threat effect is judged within the xG-covered
seasons (2023-24, 2024-25, 2025-26); per-season log scores are reported for all five.

## 8. Implemented runner provenance

`src/fpl/validate/dev_attacking_candidate_v2.py` mirrors V1's provenance-guarded runner: it refuses
a dirty worktree, snapshots (commit SHA, config fingerprint, candidate-source fingerprint, archive
fingerprint, seed, UTC timestamps) at preflight, runs read-only, and re-checks all fingerprints at
postflight — suppressing the result as INVALID/UNPUBLISHABLE if anything moved during the run. It
scores V2 against the two v1.0 baselines on **identical eligible rows** and reports V2-vs-V1 as a
diagnostic (never a gate).

The candidate is fixture-coupled (it needs the full fold roster to normalise shares and a Stage A
`lambda_team` per fixture), which the one-target `predict(target)` protocol cannot supply. The
harness therefore calls an **optional `prepare(targets, con, as_of)` hook** when the candidate
defines one; V1 defines none, so V1's path and the baselines-only path are unchanged, and the scored
population is unchanged (the hook only reads the already-scored targets).

## 9. Next step

Run the runner **once** as a clean historical development run; record
`docs/phase3-stage-c-attacking-candidate-v2-development.md` plus verbatim evidence JSON under
`docs/evidence/`. The verdict is **DEVELOPMENT-ONLY — NOT PROMOTED** regardless of the number: the
historical target roster and first-kickoff cutoff are unversioned archive proxies, so real-deadline
knowledge-time validity is unproven, and the Stage A coupling adds no new leakage surface but
depends on the same proxy. A second historical evaluation is not permitted, and nothing here is
retuned. The best required Stage C attacking baseline (`trailing_player_goal_rate_poisson`) remains
the Stage C attacking model until a separately pre-registered candidate clears the unchanged
promotion gate against prospective data.
