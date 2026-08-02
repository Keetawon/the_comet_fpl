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
| attacking goals | Stage C Candidate V1 `xg_informed_trailing_player_goals_v1` |
| assists | Stage C assists Candidate V1 `xa_informed_trailing_player_assists_v1` |
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
- **The attacking side is fixture-blind.** Goals/assists are per-player Poisson rates with no
  opponent coupling (a documented Stage C V1 limitation), so within the horizon only the conceded /
  clean-sheet side varies by opponent. A striker against a weak defence in GW3 and a strong one in
  GW1 gets the same attacking distribution. Team-coupled Stage C is a separate, unbuilt candidate.
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

### Horizon leaderboard (raw expected points, GW1-5)

| player | pos | team | fixtures | xP | xP (avail.) | status | flags |
|---|---|---|---|---|---|---|---|
| Virgil | DEF | LIV | 5 | 23.0 | 23.0 | a | |
| B.Fernandes | MID | MUN | 5 | 22.6 | 22.6 | a | |
| Mbeumo | MID | MUN | 5 | 21.1 | 21.1 | a | |
| Tarkowski | DEF | EVE | 5 | 20.6 | 20.6 | a | |
| Szoboszlai | MID | LIV | 5 | 19.9 | 19.9 | a | |
| Pedro Porro | DEF | TOT | 5 | 19.9 | 19.9 | a | |
| E.Le Fée | MID | SUN | 5 | 19.7 | 19.7 | a | |
| Botman | DEF | NEW | 5 | 19.0 | 19.0 | a | |
| Fernandes | MID | TOT | 5 | 18.2 | 18.2 | a | transfer |
| Senesi | DEF | TOT | 5 | 18.2 | 18.2 | a | transfer |

Position leaders: **GK** Leno 17.1 · **DEF** Virgil 23.0 · **MID** B.Fernandes 22.6 ·
**FWD** Watkins 17.9.

## Reading — development-only

- **The pipeline runs forward end to end.** A point-in-time-safe, availability-aware xP distribution
  is produced for every player across a five-gameweek planning horizon from a real 2026/27 roster and
  schedule. That is the deliverable.
- **The leaderboard tilts toward defenders**, and the recognised attacking premiums (e.g. the top
  strikers) do not top it. This is the known Stage C V1 limitation surfacing, not a bug: attacking
  goals/assists are independent Poisson rates with no team-goal coupling, no opponent modulation, and
  no set-piece / penalty weighting, while defenders additionally bank the 2026/27 defensive-
  contribution points and clean-sheet points that *are* opponent-coupled. Per-fixture mean expected
  points: DEF 1.40 > MID 1.36 > FWD 1.26 > GK 1.09. Closing this needs the team-coupled Stage C
  candidate, not a change to the composer.
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
