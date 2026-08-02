# Phase 4 — Prospective full-points xP over a GW1-5 horizon: development record

> **DEVELOPMENT ONLY — NOT A VALIDATED PRODUCTION FORECAST.**
> This is the first *forward-looking* end-to-end reading of the composed points pipeline: a real
> 2026/27 roster and schedule instead of a historical fold. It promotes nothing and changes no
> frozen Stage A/B/C/D contract. Every component is an unpromoted development-stage estimator, and
> the composition carries every unversioned historical proxy the earlier stages carry plus the
> Stage-D component-independence limitation. Its point-in-time safety is real; its accuracy is
> unproven and is established only as 2026/27 accrues.

## What it does

`fpl.jobs.prospective_points_v1` is the **prospective sibling** of the Stage D v3 walk-forward
(`fpl.validate.points_harness_v3`). It fits the identical best-development component suite on the
archive under the strict cutoff `kickoff_time < as_of`, then composes a per-player-fixture **full
points** distribution (including bonus) for every fixture in a *future* gameweek window and reports
each player's expected points and an aggregate expected-points total across the horizon. It scores
nothing — those gameweeks have not been played.

The multi-gameweek horizon is the point. In FPL an extra transfer beyond the free one costs a −4
hit, so a squad is planned several gameweeks ahead against a single *current-form* information set,
not re-optimised every week. GW1-5 is that planning window.

| stage | component (best development candidate) |
|---|---|
| team goals / clean sheet | promoted Stage A `trailing_goals_attack_defence`, predicted over the scheduled fixtures |
| minutes (xMin) | Stage B Candidate V3 `concentration_adaptive_shrinkage_player_minutes_v3` |
| attacking goals | Stage C Candidate V3 `minutes_gated_coupled_team_share_attacking_goals_v3` (**team-coupled, default**); `--attacking v1` reverts to the independent V1 `xg_informed_trailing_player_goals_v1` |
| assists | Stage C assists Candidate V1 `xa_informed_trailing_player_assists_v1` (independent, not yet team-coupled) |
| GK saves | `gk_saves_v1` (Poisson on the fold-local point-in-time save rate) |
| defensive contribution | `defensive_contribution_v1` (prospective P(≥ threshold)) |
| bonus | hybrid BPS match simulator (`exact_bps` + fold-local point-in-time residual), joint per fixture |

## How it is prospective (and point-in-time safe)

1. **Roster** comes from the versioned live player registry (`PointInTimeView.player_registry`,
   `known_at <= as_of`) — the model never chooses who to score.
2. **Schedule** (opponent, venue, kickoff for each future gameweek) comes from the versioned live
   schedule (`PointInTimeView.schedule`, `known_at <= as_of`).
3. **Season-boundary team identity.** The live season's `team_id -> team_code` map is read from the
   captured `bootstrap-static` payload (the loader does not populate `stg_team` for the live
   season); Stage A keys attack/defence on the permanent `team_code`, so a club's cross-season
   history is followed correctly.
4. **Every trailing history obeys `kickoff_time < as_of`.** The BPS residual's `influence` /
   `creativity` proxies are each player's *trailing* mean under the cutoff (0 when the player has no
   history), never a realised target value — a future fixture has no realised ICT to leak.
5. **Freshness gate.** `require_prospective_freshness` runs before any model work. A pre-season /
   GW1 deadline is a legitimate cold start and passes.

## Documented prospective limitations

- **Current-form / frozen horizon.** All trailing windows are frozen at `as_of`; GW2..N reuse the
  GW1 information set (no in-season update). This is the correct forecast at one deadline, but it
  does not chase form within the window.
- **Goals are team-coupled and opponent-aware (default); assists are not.** By default goals use
  Stage C Candidate V3: the Stage A team-goal expectation `lambda_team` (opponent/venue-modulated)
  is allocated among a club's players by a minutes-gated trailing attacking share, conserving the
  team total, so a striker's goal distribution responds to the opponent across the horizon.
  **Assists remain the independent Candidate V1** (fixture-blind), and `--attacking v1` reverts
  goals to the independent V1 too.
- **Appearance at the season boundary is the dominant remaining ceiling.** Appearance probability
  comes from the trailing-minutes model, whose window at the GW1 deadline is the *end of the prior
  season*. A nailed starter rested in dead-rubber final fixtures reads as a rotation risk, which
  suppresses both his appearance points and — through the minutes gate on the coupled goal share —
  his goals. The live `status` / `chance_of_playing` signal is only the reported availability
  overlay here, not yet an input to appearance, so it cannot rescue an available-but-rested starter.
- **Promoted clubs get league-average team strength.** `trailing_goals_attack_defence` returns the
  league-average multiplier (1.0) for a `team_code` with no archive history, not the measured
  promoted prior. Flagged per record (`stage_a_league_average_team`).
- **No transfer rescaling.** A transferred player keeps his own trailing attacking rate at his new
  club (a documented Stage C V1 limitation). Flagged per record (`transferred_no_rescale`).
- **Availability is a reported overlay, never a model input.** The raw distribution ignores
  availability; a transparent post-model overlay (`status` / `chance_of_playing_next_round` from the
  deadline bootstrap) scales the expected points alongside the raw figure. `i`/`s`/`u`/`n` → 0,
  `a` → 1, an explicit chance → chance/100, doubtful without a percentage → 0.5.

## First run

Run at `as_of = 2026-08-21T17:30Z` (GW1 deadline), season `2026-27`, gameweeks 1–5, Monte-Carlo
2000 draws per fixture, points support 0..34, base seed 202627, against the rebuilt archive
(five seasons through 2025-26) and the committed daily snapshots through 2026-08-02.

- **564** roster players, **50** scheduled fixtures (10 per gameweek), **2820** player-fixture rows.
- Freshness: cold start (season start) — passed.
- **73** cold-start players (no archive history → position priors), **48** transferred (no rescale),
  **36** players zeroed by the availability overlay (injured / suspended / unavailable).
- **0** Stage A league-average fallbacks — every scheduled club resolved to a `team_code` the Stage
  A fit had ratings for, except the two genuine promotions (Coventry, Hull) which by construction
  take the league-average multiplier.

### Horizon leaderboard (raw expected points, GW1-5, team-coupled V3 default)

| player | pos | team | fixtures | xP | xP (avail.) | status | V1 rank |
|---|---|---|---|---|---|---|---|
| Virgil | DEF | LIV | 5 | 27.0 | 27.0 | a | 1 |
| Szoboszlai | MID | LIV | 5 | 26.0 | 26.0 | a | 5 |
| B.Fernandes | MID | MUN | 5 | 25.3 | 25.3 | a | 2 |
| Tarkowski | DEF | EVE | 5 | 25.2 | 25.2 | a | 4 |
| E.Le Fée | MID | SUN | 5 | 21.8 | 21.8 | a | 7 |
| Mac Allister | MID | LIV | 5 | 21.1 | 21.1 | a | 23 |
| Maguire | DEF | MUN | 5 | 20.8 | 20.8 | a | 11 |
| Watkins | FWD | AVL | 5 | 20.7 | 20.7 | a | 14 |
| Pedro Porro | DEF | TOT | 5 | 20.7 | 20.7 | a | 6 |
| Danso | DEF | TOT | 5 | 20.6 | 20.6 | a | 18 |

The `V1 rank` column shows where the independent-goals V1 placed each player; the coupled path lifts
LIV/MUN attackers on strong sides. `--attacking v1` reproduces the earlier independent-goals board
(Virgil 23.0, B.Fernandes 22.6, Mbeumo 21.1, …).

## Reading — development-only

- **The pipeline runs forward end to end.** A point-in-time-safe, availability-aware xP distribution
  is produced for every player across a five-gameweek planning horizon from a real 2026/27 roster and
  schedule. That is the deliverable.
- **Team-coupling (default V3) re-ranks mid-tier attackers correctly.** Switching goals from the
  independent V1 to the team-coupled, opponent-aware V3 lifts nailed attackers in strong sides and
  favourable fixtures — e.g. Szoboszlai (LIV) 19.9 → 26.0 (rank 5 → 2), Semenyo +75 places,
  Mac Allister +17, Watkins 17.9 → 20.7 — because their goal share now scales with an
  opponent-modulated `lambda_team`. The leaderboard still leans defensive, which is partly the
  genuine 2026/27 rules (defensive-contribution + clean-sheet points are large and opponent-coupled)
  and partly that assists remain uncoupled and the share signal for a not-yet-covered future season
  is `threat`, not xG.
- **The elite-striker suppression is an appearance defect, not an attacking one.** Haaland (8.8 xP
  over five gameweeks, ~1.8/gw — below the 2-pt appearance floor) and Isak (3.1) sit far too low.
  The cause is the trailing-minutes window at the deadline: Haaland's last six 2025-26 appearances
  were `[0, 90, 0, 90, 90, 90]` (rested in dead rubbers) → the minutes model reads a 0.55 chance he
  does *not* play, halving his appearance and gating his goal share; Isak's injury-hit tail gives
  0.32. Nailed ever-presents (Virgil, Szoboszlai: `[90 × 6]`) score 0.91 and dominate. The fix is
  to let the live availability signal inform appearance probability at the season boundary, rather
  than reading it purely from end-of-prior-season minutes — a separate change from the goals
  coupling, and the next ceiling to address.
- **It is not a production forecast.** The historical proxies are unversioned, the components are
  unpromoted, and accuracy is established only as 2026/27 results accrue.

## How to reproduce

```bash
# 1. Rebuild the archive (single-writer; run DuckDB jobs sequentially). Populates influence/xG.
uv run python -m fpl.jobs.build_db

# 2. Load the committed daily snapshots (roster + schedule + availability) into the database.
uv run python -m fpl.jobs.load_snapshots snapshots/daily/*/*

# 3. Prospective full-points xP over the GW1-5 horizon (read-only).
uv run python -m fpl.jobs.prospective_points_v1 --gw-from 1 --gw-to 5 \
  --output docs/results/phase4-prospective-points-gw1-5-development.json
```
