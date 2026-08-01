# Phase 4 — Stage D v1 points composition: development record

> **DEVELOPMENT ONLY — EXPLORATORY. NOT A PROMOTION VERDICT.**
> This is the first end-to-end reading of the composed points pipeline. There is no pre-registered
> Stage D promotion contract; nothing here promotes any model or changes any frozen Stage A/B/C
> contract. The number is a development diagnostic under the same unversioned historical proxies
> (target roster, first-kickoff cutoff) every stage carries, plus the Stage-D-v1 limitations listed
> below. Real-deadline knowledge-time validity is unproven.

## What Stage D v1 does

Stages A (team goals), B (player minutes), and C (player attacking goals + assists) each produce a
*component* distribution for a player-fixture. Nothing before this composed them into a per-player
distribution over fantasy points (xP). Stage D v1 does, by a **seeded Monte-Carlo** draw over the
components followed by the exact scoring calculator, and scores the composed xP against the realised
**non-bonus** points on a `(season, code, fixture)` walk-forward.

Per player-fixture, for each of N draws (fixed order: minutes bin, goals, assists, team goals
conceded):

1. Draw a minutes bin from the Stage B 4-bin `MinutesDistribution` (`0 < 1_59 < 60_89 < 90`).
2. **Appearance gate:** bin `0` → exactly 0 points (everything else zeroed).
3. Otherwise draw goals and assists from the player's own Stage C Poisson pmfs, and draw the team
   goals conceded from the **opponent's Stage A scored-goals distribution** for that fixture.
4. `clean_sheet = (team goals conceded == 0 AND minutes >= 60)`; `goals_conceded` = the drawn team
   total. Assemble a `PlayerMatchStats` and call `calculate_points` under the 2026/27 rules.
5. Tally the draw's points into an empirical points pmf.

### Components (first run)

| component | model | why |
|---|---|---|
| minutes | Stage B Candidate **V3** `concentration_adaptive_shrinkage_player_minutes_v3` | best dev mean log score (0.71205); **caveat: it fails the Stage B starter-ranking gate** and is a development component, not a promoted one |
| attacking goals | Stage C attacking Candidate **V1** `xg_informed_trailing_player_goals_v1` | best dev mean log score of the three attacking candidates (0.137813 vs V3 0.140500, V2 0.153232), and a per-player independent rate |
| assists | Stage C assists Candidate **V1** `xa_informed_trailing_player_assists_v1` | the only assists candidate |
| team clean sheet / goals conceded | promoted Stage A `trailing_goals_attack_defence` | fit fold-locally; the player's team-conceded distribution is the **opponent's** scored-goals distribution in that fixture, resolved through `team_code` |

The harness is component-agnostic (`PointsComponentSuite`): swapping any component is a one-line
change, so a later run can substitute a promoted model without touching the composer or harness.

## The tricky join

A Stage A prediction is per team-fixture; a Stage C row is per player-fixture. In each fold the
promoted Stage A model is fit on the point-in-time team history (`kickoff_time < as_of`) and predicts
both sides of the fold's fixtures, keyed by `(season, team_code, fixture)`. For each target player,
the player's team and opponent are resolved from the fact row's season-scoped `(season, team_id)` /
`(season, opponent_team_id)` to `team_code` via `mart_dim_team`, and the conceded distribution the
composer uses is the **opponent's scored distribution**. A missing / cold-start Stage A fixture
prediction falls back explicitly to the league mean goals conceded (a Poisson), and is counted — never
silently dropped or zeroed.

## Correctness

- **R1:** no component uses `total_points`; the label is recomputed from components under the 2026/27
  rules in the validation layer and the bonus bucket subtracted (`decompose_points(...).total - bonus`).
- **Point-in-time:** every component's history is `kickoff_time < as_of`; the leakage assertion
  confirms no target kicks off before the fold cutoff.
- **Season-scoped identity:** team resolution is `(season, team_id) → team_code`; the player key is
  the stable `code`.
- **Reproducibility:** all Polars aggregations pin order; the composer takes an explicit integer seed
  and draws in a fixed order (4 uniforms per iteration regardless of the appearance gate), so the same
  inputs reproduce the same pmf bit-for-bit. Each player-fixture's seed is a stable hash of the base
  seed and `(season, code, fixture)`, so the run is independent of fold/row ordering. A determinism
  test pins this.

## Documented Stage-D-v1 limitations

- **Component independence / no team-coupling.** The Stage C attacking candidates predict a per-player
  Poisson rate, not a share of a team goal total, so nothing here couples one player's goals to
  another's or conserves a team goal total. Team-coupling / goal-conservation is a Stage-D-v1
  limitation, deliberately not invented here.
- **Bonus excluded** from both prediction and label (scored against `total_points - bonus`).
- **Defensive contribution = 0** in the composer: DC data exists only for 2025-26 and is not
  backtestable across the archive. (Increment 2 adds a prospective DC component.)
- **Unmodelled scoring components.** Saves, penalties, own goals, and cards are held at zero in the
  composer; the realised label still includes them, a small documented support gap.
- **Negative composed points** (the GK/DEF goals-conceded penalty) fold into the 0 bin, matching how
  the count-distribution metrics clamp a negative observation.
- **No-xG season reported separately.** 2021-22 has 0% xG, so the Stage C components degenerate to
  their goals/assists fallbacks there; it is reported as its own season / regime and kept **out of the
  headline**, never averaged into it.

## Result

<!-- RESULTS: filled from the single clean archive dev run; see the reconciliation JSON. -->

_The single clean historical development run is recorded below. The reconciliation JSON is at
`docs/results/phase4-stage-d-points-composition-v1-development.json` (schema
`stage_d_points_composition_v1_development/v1`)._

Headline (xG-present seasons, 2022-23…2025-26), all-seasons overall, per-season, by-position, and
by-xG-regime figures are in the JSON. **Every figure is development-only and exploratory; it is not a
promotion verdict and is not an upper bound.**

## How to reproduce

```bash
# Build/verify the archive first (single-writer; run DuckDB jobs sequentially).
uv run python -m fpl.jobs.build_db

# The single authorized clean development run (refuses a dirty worktree).
uv run python -m fpl.validate.dev_points_composition_v1 \
  --save-json docs/results/phase4-stage-d-points-composition-v1-development.json
```
