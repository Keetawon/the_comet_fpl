# Phase 4 — Prospective full-points xP over a GW1-5 horizon: development record

> **DEVELOPMENT ONLY — NOT A VALIDATED PRODUCTION FORECAST.**
> This is the first *forward-looking* end-to-end reading of the composed points pipeline: a real
> 2026/27 roster and schedule instead of a historical fold. It promotes nothing and changes no
> frozen Stage A/B/C/D contract. Every component is an unpromoted development-stage estimator, and
> the composition carries every unversioned historical proxy the earlier stages carry plus the
> Stage-D component-independence limitation. Its point-in-time safety is real; its accuracy is
> unproven and is established only as 2026/27 accrues.

**As-built follow-up:** the job now defaults to team-coupled goals **and** assists, emits the stable
JSONL contract in `docs/prospective-points-artifact.md`, and feeds the development-only Stage E
optimiser in `docs/stage-e-squad-optimizer.md`. The dated first-run counts and leaderboard below
remain a historical development record rather than a live status page.

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
| attacking goals | Stage C Candidate V3 `minutes_gated_coupled_team_share_attacking_goals_v3` (**team-coupled, default**), share signal xG in the xG era (`--share-signal auto`); `--attacking v1` reverts to the independent V1, `--share-signal threat` reverts the share signal |
| assists | **team-coupled by default**: the club's assisted-goal expectation (`lambda_team * measured assist_rate`, ~0.90) allocated by an xA-share (creativity pre-xG), minutes-gated; `--assists v1` reverts to the independent V1 `xa_informed_trailing_player_assists_v1` |
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
- **Goals and assists are team-coupled and opponent-aware by default.** Goals use
  Stage C Candidate V3: the Stage A team-goal expectation `lambda_team` (opponent/venue-modulated)
  is allocated among a club's players by a minutes-gated trailing attacking share, conserving the
  team total, so a striker's goal distribution responds to the opponent across the horizon. Assists
  allocate `lambda_team * assist_rate` by a minutes-gated xA-share. `--attacking v1` and
  `--assists v1` independently restore the historical per-player candidates.
- **Season-boundary appearance correction (default `--appearance seasonal`).** The trailing-minutes
  window at a GW1 deadline is the *end of the prior season* — its least representative phase: a
  nailed starter rested in dead-rubber final fixtures reads as a rotation risk, suppressing both his
  appearance points and, through the minutes gate on the coupled goal share, his goals. Two measured
  fixes stack here:
  - **Recent appearance is the equal-weighted average of the last five matches, not a
    recency-weighted one.** The fitted minutes model (Stage B V3) is recency-weighted, so it lands
    its *heaviest* weight on the single most recent match — which at a season boundary is the
    dead-rubber final gameweek, exactly where nailed starters are rested. Measured across three
    historical boundaries, the final gameweek collapses nailed starters from a ~0.92–0.97 start rate
    to **0.73 started / 0.21 did-not-play** (goalkeepers 0.97 → 0.75 / 0.25), and the recency weight
    drives an ever-present like Raya (37/38 at a full 90) to a raw p_play of **0.51**. Equal-
    weighting the five predicts next-season GW1-6 appearance strictly better than recency-weighting
    everywhere (overall MAE 0.223 vs 0.234; goalkeepers 0.181 vs 0.195), so `seasonal` builds the
    recent estimate as the plain last-five minute-bin histogram (falling back to the fitted model
    only when there are fewer than three trailing rows to average). The frozen Stage B V3 model
    itself is untouched; this is a Phase-4 composer choice.
  - **Blend that recent estimate with the full prior-season appearance rate** for early-season
    targets (weight 0.7 in Aug-Sep, 0.5 in Oct-Nov, 0 in-season), reshaping the minutes distribution
    while preserving the when-playing minute shape. The prior-season rate is the boundary-robust
    nailed-ness signal (measured: it predicts an opener better than *any* five-match window; for
    nailed players the best-measured scheme overall is equal-5 blended with the prior at 0.7, MAE
    0.215 vs 0.223 for equal-5 alone — pure equal-5 would actually *lower* a nailed keeper below the
    old number). Together these lift Raya from a raw 0.51 (or 0.834 under the old recency-weighted
    blend) to **0.922**.

  **This is not a source of false certainty**: cross-season appearance is genuinely hard (MAE ~0.22;
  nailed-last-season players average ~0.78 early next season, not ~0.88, because of transfers /
  injuries / lost spots), so it lifts rested-but-nailed starters without pretending every
  "available" player starts. Live `status` / `chance_of_playing` stays the separate reported
  overlay, never double-counted. `--appearance model` uses the raw recency-weighted model
  distribution.
- **Promoted clubs get league-average team strength.** `trailing_goals_attack_defence` returns the
  league-average multiplier (1.0) for a `team_code` with no archive history, not the measured
  promoted prior. Flagged per record (`stage_a_league_average_team`).
- **No transfer rescaling.** A transferred player keeps his own trailing attacking rate at his new
  club (a documented Stage C V1 limitation). Flagged per record (`transferred_no_rescale`).
- **Availability is a reported overlay, never a model input.** The raw distribution ignores
  availability; a transparent post-model overlay (`status` / `chance_of_playing_next_round` from the
  deadline bootstrap) scales the expected points alongside the raw figure. `i`/`s`/`u`/`n` → 0,
  `a` → 1, an explicit chance → chance/100, doubtful without a percentage → 0.5.
  The present implementation repeats that next-round multiplier across GW1-5; this is an unresolved
  horizon assumption, not a claim that an injury probability stays constant for five gameweeks.

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

### Horizon leaderboard (raw expected points, GW1-5, team-coupled V3 + seasonal appearance, defaults)

| player | pos | team | xP | rank w/o appearance fix |
|---|---|---|---|---|
| Virgil | DEF | LIV | 28.2 | 1 |
| Tarkowski | DEF | EVE | 26.3 | 4 |
| Szoboszlai | MID | LIV | 25.5 | 2 |
| B.Fernandes | MID | MUN | 24.6 | 3 |
| Watkins | FWD | AVL | 23.3 | 8 |
| Gibbs-White | MID | NFO | 22.1 | 44 |
| E.Le Fée | MID | SUN | 21.8 | 5 |
| O'Reilly | DEF | MCI | 21.8 | 115 |
| Mac Allister | MID | LIV | 21.4 | 6 |
| Groß | MID | BHA | 21.3 | 13 |

The last column is each player's rank under `--appearance model` (V3 goals, no season-boundary
correction). The correction rescues nailed starters whose *trailing-five* window was end-of-season
rotation without inventing certainty for the genuinely uncertain:

| player | model rank / xP | seasonal rank / xP | reading |
|---|---|---|---|
| Haaland | 183 / 8.8 | 21 / 18.5 | rested in dead rubbers (`[0,90,0,90,90,90]`) → restored |
| Ekitiké | 518 / 0.7 | 214 / 8.0 | low recent minutes → restored toward his prior-season level |
| Saka | 126 / 11.4 | 55 / 15.9 | nailed, lifted |
| Isak | 389 / 3.1 | 408 / 3.4 | genuinely injury-hit last season → correctly stays low |

`--attacking v1 --appearance model` reproduces the original independent-goals, raw-minutes board.

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
  and partly the uncertainty in early-season appearance and attacking-share inputs.
- **Assists are team-coupled by default, lifting genuine creators honestly.** An assist requires a
  team goal, so the club's assisted-goal expectation is `lambda_team * assist_rate` (measured
  `sum(assists)/sum(goals)` ~0.90, stable 0.89-0.94 across seasons) allocated by an xA-share
  (creativity pre-xG), minutes-gated and conserving — the exact mirror of the goals coupling.
  Effect on GW1-5: assist-dependent premiums rise on their own merit — B.Fernandes rank 10 → 6
  (MUN's dominant creator: xA 0.36 vs the roster's next 0.17), Szoboszlai 4 → 1, Saka 79 → 50,
  Enzo 30 → 20. This is structural, not a nudge: a player's assist share is his measured xA-share of
  a team total, and the effect on any individual is incidental to getting the structure right.
- **xG-share (default in the xG era) allocates goals to true finishers, embedding the penalty
  premium.** The team-coupled share signal is xG rather than threat for an xG-era target season
  (`--share-signal auto`). Measured on the roster: designated penalty takers (`penalties_order = 1`)
  gain +2.43pp of their club's goal share under xG vs threat (others −0.13pp) because FPL
  `expected_goals` includes penalty xG — and the archive cannot separate penalty goals from
  open-play, so xG-share is the *grounded* way to capture the penalty premium rather than an
  unmeasurable explicit term. Effect on GW1-5: Haaland rank 21 → 5, Watkins → 2, Mbeumo 62 → 3,
  Gyökeres 95 → 39, rebalancing the top toward finishers; Saka / Semenyo fall because their value is
  more assist-led than goal-led. Isak is unmoved (appearance-limited, not share-limited).
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
  --output D:/tmp/prospective-points-2026-27-gw1-5.jsonl
```
