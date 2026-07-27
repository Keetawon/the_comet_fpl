# The publish contract

**Status: agreed design, not yet implemented.** Phase 4 builds it. Recorded now so Phases
1–3 write towards a fixed boundary rather than being retrofitted.

## Why this exists

The dashboard updates once per gameweek. That is a static-site shaped workload, so the
`publish` job's output is **a set of files, not a database handle**. The specification already
requires "everything served from pre-computed tables, no inference at request time"; this
makes that boundary a file.

The consequence that matters: Streamlit v1 becomes a thin renderer over the same artefact a
React app would consume. Swapping frontends later is a frontend-only change with no
re-plumbing, so the choice stops being one that has to be right today. The export also
doubles as a public read-only API.

**Nothing downstream of `publish` may query DuckDB.** The dashboard reads `public/data/`
only. A dashboard that reaches into the database re-couples the two and reintroduces
request-time inference.

## Layout

```
public/data/
  manifest.json            provenance, target gameweek, model version   (every view)
  players.json             per-gameweek xP for the next 6 GWs            (player table, captaincy)
  fixtures.json            schedule + model lambdas + FPL FDR            (fixture ticker)
  teams.json               attack/defence ratings with uncertainty       (team ratings)
  calibration.json         backtest vs the three baselines               (model transparency)
  players/{code}.json      per-player detail: histogram, decomposition   (player detail)
```

Six files plus one per player. `players.json` stays small enough to load on mobile; the
per-player histograms live in their own files and load on demand.

Rough sizes at ~700 players: `players.json` ≈ 400 KB, each detail file ≈ 4 KB,
`fixtures.json` ≈ 80 KB. All well under a second on a CDN, and trivially gzipped.

## Rules that apply to every file

1. **`code` is the identity.** Never `element`, which is reassigned every season (gotcha 1).
   `element_id` is carried alongside solely for deep-linking to fantasy.premierleague.com,
   and is never used as a join key.
2. **Every number is pre-computed.** The frontend formats and sorts; it never derives a
   statistic. Any quantity a view needs is a field here.
3. **Distributions ship as histograms, not just moments.** `P(≥6)`, `P(≥10)` and `Var` are
   all derivable from the histogram, so shipping the bins means a new threshold is a
   frontend change rather than a re-export. This is the difference between "can we show
   `P(≥15)` for triple-captain week?" being an afternoon or a pipeline change.
4. **`schema_version` is in the manifest** and every consumer asserts on it, so a shape
   change fails loudly instead of rendering wrong numbers.
5. **Nulls are nulls.** An unmodelled or unmeasured quantity is `null`, never `0` — the same
   rule that governs storage (gotcha 5). A frontend showing `0.0 xP` for a player the model
   could not score is lying.
6. **No `total_points`-derived quantity is presented as a prediction.** Recorded points come
   from `mart_target_player_fixture.total_points_as_recorded` and appear only in backtest and
   historical-form contexts, always labelled as actuals.

## manifest.json

The provenance record. Also the data source for the transparency view's caveats.

```json
{
  "schema_version": "1.0.0",
  "generated_at": "2026-08-20T06:12:04Z",
  "target_gw": 1,
  "target_deadline": "2026-08-21T17:30:00Z",
  "season": "2026-27",
  "ruleset_id": "2026_27",
  "ruleset_verified": false,
  "model_version": "0.3.0",
  "simulation_draws": 10000,
  "snapshot_captured_at": "2026-08-20T06:00:11Z",
  "training_seasons": ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26"],
  "excluded_from_training": [
    {"season": "2022-23", "reason": "expected_* unmeasured before GW16"}
  ],
  "target_incomplete_seasons": [
    {"season": "2021-22", "missing": ["defensive_contribution"]}
  ],
  "known_limitations": [
    "Goalkeeper goal value (10) is unvalidated: no goalkeeper scored in the validation data.",
    "Promoted clubs use a pooled cold-start prior and carry wider uncertainty bands."
  ]
}
```

`ruleset_verified` and `target_incomplete_seasons` come straight from
`config/scoring_2026_27.yaml`'s verification block and `mart_target_completeness`. Surfacing
them is the point: the transparency view should state what the model does not know.

## players.json

Drives the player table and the captaincy view. One row per player.

```json
{
  "schema_version": "1.0.0",
  "target_gw": 1,
  "players": [
    {
      "code": 118748, "element_id": 381, "web_name": "M.Salah",
      "position": "MID", "team_id": 12, "team_short": "LIV",
      "price": 145, "selected_by_percent": 41.2, "status": "a",
      "chance_of_playing": 100,
      "xp_next": 6.41, "variance": 21.4,
      "p_returns": 0.512, "p_haul": 0.371, "p_60_plus": 0.883,
      "xp_per_million": 0.442,
      "gameweeks": [
        {"gw": 1, "xp": 6.41, "p_returns": 0.512, "p_haul": 0.371, "variance": 21.4,
         "is_double": false, "is_blank": false,
         "fixtures": [
           {"opponent_short": "BOU", "was_home": true,
            "lambda_for": 2.14, "lambda_against": 0.92, "fpl_fdr": 2}
         ]},
        {"gw": 2, "xp": 11.83, "p_haul": 0.62, "is_double": true,
         "fixtures": [{"opponent_short": "WHU", ...}, {"opponent_short": "EVE", ...}]},
        {"gw": 3, "xp": 0.0, "p_haul": 0.0, "is_blank": true, "fixtures": []}
      ],
      "horizons": {
        "1": {"xp": 6.41,  "p_returns": 0.512, "p_haul": 0.371, "variance": 21.4},
        "4": {"xp": 24.83, "p_returns": 0.938, "p_haul": 0.826, "variance": 74.2},
        "6": {"xp": 36.20, "p_returns": 0.981, "p_haul": 0.914, "variance": 108.7}
      }
    }
  ]
}
```

- `price` in FPL's integer tenths (145 = £14.5m), as the API gives it. Formatting is the
  frontend's job.
- `p_returns` = `P(≥6)`, `p_haul` = `P(≥10)`. Named for what a manager asks, not the maths.
- **`xp_next` and `p_haul` are both first-class.** They rank players differently, and that
  disagreement is the product — the captaincy view sorts by `p_haul` and shows `xp_next`
  beside it.
- `fixtures` carries the model's own `lambda_for`/`lambda_against` **and** `fpl_fdr`, so the
  ticker can show where the model disagrees with FPL rather than replacing one opaque number
  with another.

### The gameweek horizon, and what may be summed

The unit is the **gameweek**, not the fixture, because squad planning happens per gameweek --
you pick a side for GW1, not for "the next six matches". A gameweek holds zero, one or two
fixtures, so the two are genuinely different:

- **Double gameweek** -- `is_double`, and the gameweek's `xp` is the sum over both fixtures.
- **Blank gameweek** -- `is_blank`, `xp` is 0.0 and the entry is still present. A missing
  entry and a zero entry mean different things to a manager, so blanks are never omitted.

This works only because the fact grain is `(code, fixture)` rather than `(code, gameweek)`.
Aggregating to gameweeks is a presentation choice made at publish time; the reverse would
have been impossible.

**Only `xp` may be summed across gameweeks.** Expectation is linear, so a client may add
`gameweeks[].xp` over any subset and be exactly right regardless of how correlated the
fixtures are.

`p_returns`, `p_haul` and `variance` **must not be summed** -- `P(haul in 4 GWs)` is not the
sum of four per-gameweek probabilities, and adding them overstates the result every time. The
simulator holds the joint distribution, so it precomputes those aggregates for N = 1..6 in
`horizons` at no extra cost. A client wanting a horizon the export does not carry must ask
for it to be added rather than deriving it.

## players/{code}.json

The detail view. Histogram plus the decomposition.

```json
{
  "schema_version": "1.0.0", "code": 118748, "target_gw": 1,
  "histogram": {"bin_edges": [0,1,2,3,4,5,6,7,8,9,10,12,14,16,20,25],
                "probabilities": [0.117, 0.031, 0.209, 0.044, 0.062, 0.055, 0.108,
                                  0.039, 0.071, 0.048, 0.089, 0.052, 0.031, 0.028, 0.016]},
  "decomposition": {"appearance": 1.77, "goals": 1.94, "assists": 1.21,
                    "clean_sheet": 0.28, "goals_conceded": 0.0,
                    "defensive_contribution": 0.14, "bonus": 1.07},
  "minutes_distribution": {"0": 0.09, "1_59": 0.08, "60_89": 0.19, "90": 0.64},
  "rolling_form": {
    "gw": [34, 35, 36, 37, 38],
    "minutes": [90, 90, 72, 90, 61],
    "expected_goals": [0.61, 0.22, 0.94, 0.38, 0.55],
    "expected_assists": [0.31, 0.44, 0.12, 0.28, 0.19]
  }
}
```

- `decomposition` keys are exactly `PointsBreakdown`'s fields, so the calculator's structure
  and the dashboard's explanation cannot drift apart.
- Bin edges are irregular above 10 because the tail is sparse; they are explicit rather than
  implied so the frontend never assumes a width.
- **`rolling_form` is underlying stats, never points.** Rolling points would conflate
  per-minute quality with availability, which is R6 — the mistake the whole architecture
  exists to prevent.
- `minutes_distribution` is Stage B's output, shown directly. It is the largest single term
  in `xp_next`, so hiding it would make the decomposition unexplainable.

## fixtures.json, teams.json, calibration.json

```json
// teams.json -- the team ratings view
{"teams": [
  {"team_id": 12, "short_name": "LIV", "attack": 1.34, "defence": 0.79,
   "attack_ci": [1.18, 1.51], "defence_ci": [0.68, 0.92],
   "is_promoted": false, "cold_start_prior": false, "matches_observed": 38}
]}
```

Attack and defence are **ratios to the league mean**, matching how the model multiplies them
(`lambda = mu * A_team * D_opponent * h_venue`). Shipping ratios keeps the frontend from
inventing a subtractive comparison, which is the failure mode the spec measured at 0.062
correlation against 0.260.

`is_promoted` and `cold_start_prior` drive the honesty flag on that view — three promoted
clubs a season is 15% of the league on a pooled prior, and users should see which.

```json
// calibration.json -- the model transparency view
{"backtest": {"window": "2025-26 GW1-38", "method": "walk-forward by gameweek",
              "spearman_within_position_gw": {"model": 0.31, "ep_next": 0.27,
                                              "trailing_5_mean": 0.22, "naive_fdr": 0.11},
              "log_loss_p_returns": {"model": 0.58, "ep_next": 0.63}},
 "reliability": {"p_60_plus": {"predicted": [0.05,0.15,0.25], "observed": [0.06,0.13,0.27],
                               "n": [412, 288, 201]}},
 "season_backtest": {"model_points": 2314, "average_manager": 2085, "n_seasons": 1}}
```

Baselines are named in the file, not assumed by the frontend, so adding a fourth is a
pipeline change only. `n` accompanies every reliability bucket — a calibration curve without
bin counts hides that the tail bins are three observations.

## Implementation notes for Phase 4

- Artefacts are written by `src/fpl/publish/export.py`, with **pydantic models defining every
  payload**. The models are the contract; the JSON is their serialisation.
- Contract tests in `tests/test_publish.py`: every file validates against its model, every
  `schema_version` matches the manifest, every histogram sums to 1.0 within tolerance, every
  `code` in `players.json` resolves in `mart_dim_player`, and no field name matches
  `total_points`.
- Write atomically — build into a temp directory and move, so a partially-written export is
  never served. Same reasoning as the snapshot job's all-or-nothing rule.
- `publish` reads `mart_target_*` and the prediction tables. It is the boundary where target
  data is *allowed*; the feature builder's restriction does not apply here.
- Serve `public/data/` from Pages or any CDN. Streamlit reads the same files from disk, so
  local and deployed rendering are identical.
