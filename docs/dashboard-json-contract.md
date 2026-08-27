# Dashboard read-model JSON contract, version 7

Status: implemented development-only by DEV-ROADMAP P1.7a and extended through P2.5. This
document is the authoritative prose counterpart of `src/fpl/publish/dashboard_json.py`. The
static app renders these files and nothing else. Version 2 adds `summary.json`,
`next_gw.json`, `forecast_vs_actual.json`, and `optimizer_audit.json` to the version-1 file
set; the version-1 record shapes are unchanged.

Version 3 adds explicit optimizer-plan classification and owner-policy fields. It does not
infer plan ownership from run-id, hash, input, or row order.

Version 4 adds `player_horizons.json`: cumulative player xP and inclusive points-threshold
probabilities for every endpoint in a forecast run. The static emitter computes these values by
convolving the already-published player-gameweek distributions. The browser selects an exact
endpoint and may filter/sort player records; it never conditions a distribution, sums
probabilities, parses a PMF, or derives a tail.

## Version 5 monitoring amendment (implemented 2026-08-26)

Version 5 retains all version-4 files/fields and implements the exact monitoring repair in
`docs/prediction-vs-actual-dashboard.md`. It replaces the ambiguous
`forecast_vs_actual.json` with `player_forecast_vs_actual.json` and
`team_forecast_vs_actual.json`, backed by append-only finalized outcomes and exact stored PMFs.

Player observations are emitted only after complete-gameweek finality; one completed double-
gameweek leg never scores a full convolved gameweek forecast. Team observations stay at directed
team-fixture grain and use the opponent's exact goal PMF for defensive scoring. Both files publish
coverage, scalar chart/table observations, score blocks, slices, and calibration; neither exposes a
PMF to JavaScript. Version-4 consumers are not permitted to treat the old aggregate as version-5
evidence. The executable emitter, strict frontend loaders, public-package allowlist, manifest, and
tests moved together to version 5.

## Version 6 current-season player actuals amendment (implemented 2026-08-26)

Version 6 retains every version-5 file and adds `actuals` to each `players.json` player record.
The rows come from the published `fact_player_fixture_actual` table, never DuckDB, and match the
player record on exactly `(season, code)`. Only rows whose `(season, gw)` resolves to
`dim_gameweek.finished = true` are included. There is no prior-season fallback: at the start of a
season, an empty current-season range is an empty array rather than last season's form.

Actuals stay at fixture grain, so both legs of a completed double gameweek remain separate and are
ordered by gameweek, kickoff, then fixture. A duplicate `(season, fixture, code)` fails the build.
The browser may select a current-season gameweek range and sum these already-published observed
values; it does not query DuckDB or derive model quantities. Source `null` values remain JSON
`null` and are never rewritten as zero.

## Version 7 normalized player history and forecast provenance amendment (implemented 2026-08-26)

Version 7 retains every version-6 metric but removes the repeated `actuals` array from each
forecast-vintage row in `players.json`. It adds `player_actuals.json`, normalized once at
`(season, code)` grain. Each record contains the same finalized fixture rows and preserves the
version-6 complete-gameweek, double-gameweek, ordering, duplicate-identity, and NULL rules. The
file is bounded to each published forecast season and its immediate predecessor for player codes
present in the published forecast population; a predecessor is emitted only when finalized
observations exist, and older archive seasons are absent. For a selected run, the Players page
offers only its forecast season and its published immediate predecessor, and never mixes seasons
in one aggregate.

Version 7 also transports `cold_start_player` on every `players.json` row. This is the selected
forecast vintage's own no-usable-history provenance flag from
`fact_forecast_player_gameweek`; it is never inferred from form, ownership, or later actuals. A
within-player/vintage disagreement fails publication. Player analytics may exclude those rows as
an explicit reporting filter and recompute its Pareto geometry over the selected population, but
it may not alter the stored xP or probabilities.

## Boundary and provenance chain

```text
production DuckDB ──(fpl.jobs.export_bi)──► Parquet export ──(fpl.jobs.export_dashboard_json)──► read-model JSON
```

`fpl.jobs.export_dashboard_json --input data/bi-export --output data/dashboard-json` reads a
**published P1.4 Parquet export only**. It never opens the production DuckDB, never opens any
DuckDB at all (the emitter is pure Polars over Parquet files), and never mutates the export.
Before deriving anything it verifies the source export's manifest self-hash and the SHA-256 of
every Parquet file it reads, so a tampered or half-replaced export fails closed.

The read-model manifest carries the full provenance chain: the source export's schema version,
`content_sha256`, `created_at`, and `database_sha256`; the exported `run_id`s with their
`as_of`; and the ease formula version found in the data.

## Publication

Mirrors P1.4 exactly: a unique sibling staging directory is built, fsynced, and fully
validated (strict JSON, per-file hashes, row counts, manifest self-hash), then atomically
swapped into the endpoint via the same generation-symlink machinery. An exclusive sibling lock
rejects a concurrent writer; an unmanaged target directory is never replaced; any failure
removes the staging tree and leaves the previous endpoint byte-identical.

`generated_at` is the only field excluded from the read-model manifest's `content_sha256`, so
identical inputs produce byte-identical read-model JSON (including `player_horizons.json`) and an
identical content hash.

## Layout

Version 7 publishes nine read-model files plus the manifest.

```text
data/
├── dashboard-json -> .dashboard-json.generation.9b4…/
└── .dashboard-json.generation.9b4…/
    ├── manifest.json
    ├── fixture_matrix.json
    ├── players.json
    ├── player_actuals.json
    ├── player_horizons.json
    ├── next_gw.json
    ├── summary.json
    ├── player_forecast_vs_actual.json
    ├── team_forecast_vs_actual.json
    └── optimizer_audit.json
```

## Null semantics (hard)

A JSON `null` means unmeasured or unavailable — never `0`, never `""`. Ease indices with a
rejected denominator, a zero `lambda_against`, a missing official FDR, pre-coverage xG/xA, and
the ledger's not-yet-persisted fixture-level player probabilities are all passed through as
`null`. `allow_nan=False` is used everywhere; a non-finite float fails the export.

## Identity rules

- Every object keys on `run_id` + `season` + the cross-season identity (`team_code`, `code`).
  No season-scoped id (`team_id`, `opponent_team_id`, `element_id`) appears as a key anywhere.
- Club labels resolve through `dim_team_season` on `(season, team_id)`; a player's club comes
  from the forecast row's `team_code` with that season-qualified fallback — never
  `dim_player` (which carries no club by contract).
- Opponents appear as `opponent_team_code` + `opponent_short_name`.

## fixture_matrix.json — one object per (run_id, season, team_code)

The population is every club with rows in `fact_forecast_team_fixture` for that vintage; a
legacy schema-1 vintage with no fixture transport contributes zero team objects.

- `form` is the `fact_team_form` windows at the team's **latest observed (season, gw) anchor**
  across seasons (`team_code` is cross-season-safe). At a GW1 deadline this is the prior
  season's closing gameweek; a promoted club falls back to its last completed PL season; a
  club with no observed form has `form: null`. The anchor `season` and `as_at_gw` are carried
  so the UI can label how old the form is. The emitter attaches that same latest-at-export
  snapshot to every forecast-run record; it is not reconstructed as of each run's `as_of` and
  may therefore post-date an older selected vintage. It is reporting context only. All four
  windows (`last_3`, `last_5`, `last_10`, `season_to_date`) carry every measure including
  per-match rates, NULLs preserved.
- `fixtures` is every team-fixture row of that vintage, ordered by `gw`, then kickoff, then
  fixture id — both legs of a double gameweek are separate entries. `kickoff_time` may be
  `null` for an unscheduled fixture and orders last, never first.

The file also carries a separately versioned `schedule` object
(`schedule.schema_version: 2`). It is a **current-at-BI-export official schedule overlay**,
not part of any selected forecast vintage:

- `semantics` is exactly `current_at_export_not_forecast_vintage`;
- `export_created_at` and `database_sha256` bind the overlay to the source BI export;
- `schedule.teams` is one object per `(season, team_code)`, with directed fixture rows
  containing gameweek, fixture id, kickoff, opponent identity, home/away, and nullable current
  `official_fdr`;
- schedule rows never carry lambdas, clean-sheet probabilities, or ease indices. Schema v1 remains
  readable as a legacy overlay with no `official_fdr`.

The Fixture Matrix keeps the model horizon unchanged and offers 5/10/15-GW display windows.
Rows after the forecast horizon are schedule-only chips. **Official FDR** uses the current
schedule-owned `official_fdr`. **Opponent strength** may reuse the selected vintage's display-time
club-strength proxy. **Club ease** uses display proxy `fixture-ease-proxy-v1`, composed from the
selected vintage's average club lambdas:

```text
lambda_for_proxy     = own_avg_for * opponent_avg_against / league_average
lambda_against_proxy = own_avg_against * opponent_avg_for / league_average
attack_ease_proxy    = 100 * lambda_for_proxy / league_average
defence_ease_proxy   = 100 * league_average / lambda_against_proxy
overall_ease_proxy   = sqrt(attack_ease_proxy * defence_ease_proxy)
clean_sheet_proxy    = exp(-lambda_against_proxy)
```

The proxy has no later fixture model, venue adjustment, or new forecast input. Every later chip
identifies whether its colour is current FDR or a selected-vintage proxy. Later rows never enter
model-ease averages or sorting and remain current schedule context that may post-date an older
selected vintage. A moved fixture may therefore appear once in the recorded vintage and again at
its current schedule gameweek; that is explicit vintage-versus-current context, not a duplicate
forecast.

Sample record (abbreviated):

```json
{
  "run_id": "f9bbd862…",
  "as_of": "2026-08-21T17:30:00+00:00",
  "season": "2026-27",
  "team_code": 101,
  "team_name": "Alpha",
  "short_name": "ALP",
  "form": {
    "season": "2025-26",
    "as_at_gw": 38,
    "windows": {
      "last_3": {"matches_played": 3, "goals_for": 5, "goals_against": 3, "clean_sheets": 1,
                  "wins": 1, "draws": 1, "losses": 1, "team_xg": 3.6, "team_xgc": 2.9,
                  "goals_for_per_match": 1.7, "goals_against_per_match": 1.0,
                  "team_xg_per_match": 1.2, "team_xgc_per_match": 0.97},
      "last_5": {"…": "…"}, "last_10": {"…": "…"}, "season_to_date": {"…": "…"}
    }
  },
  "fixtures": [
    {"gw": 1, "fixture": 100, "kickoff_time": "2026-08-22T14:00:00+00:00",
     "opponent_team_code": 102, "opponent_short_name": "BET", "was_home": true,
     "lambda_for": 2.0, "lambda_against": 1.0, "probability_clean_sheet": 0.4,
     "attack_ease_index": 120.0, "defence_ease_index": 120.0, "overall_ease_index": 120.0,
     "ease_index_formula_version": "fixture-ease-v1", "official_fdr": 2,
     "stage_a_league_average_team": false}
  ]
}
```

Ease indices stay **directed and versioned** (`ease_index_formula_version` per fixture):
higher means easier for the named team, 100 is league average. The raw `lambda_for` /
`lambda_against` primitives sit beside them and must stay visible in any UI. `official_fdr`
is a separate field and is never blended into an ease value.

## players.json — one object per (run_id, season, code)

The population is every player with rows in `fact_forecast_player_gameweek` for that vintage.

- Identity (`web_name` via `dim_player_season`, `position`, club, `now_cost`,
  `selected_by_percent`, availability) comes from the player's **first forecast gameweek**
  row — the deadline-known state of the vintage. Availability is a reported overlay valid for
  the first forecast gameweek; the ledger repeats it for later gameweeks, and it is passed
  through, never folded into any distribution or EV.
- `form` follows the same latest-anchor rule as teams, at `code` grain; `avg_minutes_last_5`
  is `minutes / rostered_fixtures` from the `last_5` window — a per-rostered-match average
  with DNPs included, `null` when there is no window. Each form window carries the observed
  `clean_sheets`, on-pitch `goals_conceded`, `saves`, and `expected_goals_conceded` fields in
  addition to the existing availability, attack, bonus/BPS, DC, and points measures. The first
  three are `null` when the player did not appear; xGC is `null` when no appeared row measured it
  and otherwise sums the measured appeared rows, including a partially measured window. As with
  team form, this is the latest snapshot at static export attached across forecast runs, not a
  point-in-time snapshot at the selected run's `as_of`; the per-row `season` and `as_at_gw`
  anchors must remain visible wherever an older forecast is compared with form.
- `cold_start_player` is copied from the first forecast gameweek after verifying it is constant
  for the player/vintage. It identifies the forecast's own cold-start path and is not an outcome
  or a browser-derived newcomer guess.
- `fixtures` is every player-fixture row of that vintage (double gameweek = two entries),
  each carrying the player's own xP/probabilities **plus the player's club fixture fields for
  that fixture** (`team_attack_ease_index`, `team_defence_ease_index`,
  `team_overall_ease_index`, `team_official_fdr`, `team_lambda_for`, `team_lambda_against`,
  `team_probability_clean_sheet`), joined from
  `fact_forecast_team_fixture` on the season-qualified `(run_id, season, fixture, team_id)`
  key so the UI can colour the chip and show the raw primitives behind the colour without a
  client-side join. `team_probability_clean_sheet` is the CLUB's clean-sheet probability and
  is a different measure from the player's own `probability_clean_sheet`. A missing team row
  for a player fixture fails closed rather than rendering an unlabelled chip; legitimately
  null ease/FDR values stay `null`.

Sample record (abbreviated):

```json
{
  "run_id": "f9bbd862…",
  "as_of": "2026-08-21T17:30:00+00:00",
  "season": "2026-27",
  "code": 1,
  "web_name": "Vicario",
  "position": "GK",
  "team_code": 101,
  "team_short_name": "ALP",
  "now_cost": 55,
  "selected_by_percent": null,
  "availability_status": "a",
  "chance_of_playing": null,
  "availability_multiplier": 1.0,
  "cold_start_player": false,
  "form": {"season": "2025-26", "as_at_gw": 38, "windows": {"…": "…"}},
  "avg_minutes_last_5": 52.0,
  "fixtures": [
    {"gw": 1, "fixture": 100, "kickoff_time": "2026-08-22T14:00:00+00:00",
     "opponent_team_code": 102, "opponent_short_name": "BET", "was_home": true,
     "expected_points": 5.5, "probability_appears": null, "probability_sixty_minutes": null,
     "expected_goals": null, "expected_assists": null, "probability_clean_sheet": null,
     "team_attack_ease_index": 120.0, "team_defence_ease_index": 120.0,
     "team_overall_ease_index": 120.0, "team_official_fdr": 2,
     "team_lambda_for": 2.0, "team_lambda_against": 1.0, "team_probability_clean_sheet": 0.4}
  ]
}
```

The player-fixture probability/expected-minute fields are `null` until the ledger persists
them (P1.2 exports them as typed NULLs); they are never reconstructed from a convolved
gameweek distribution.

The observed form fields above do **not** add future player-level defensive forecasts. Expected
saves, defensive contributions, goals conceded, or xGC per future player-fixture remain absent;
the UI may show the already transported player/club clean-sheet probabilities and club lambda
against, but must not convert those club primitives into fabricated player forecasts.

P1.8 is implemented in the schema, form builder, semantic export, static emitter, and focused
tests. An existing DuckDB gains the four additive columns as NULL, so code or migration alone does
not populate `players.json`. The failure-atomic local development database rebuild and atomic
BI/static publication completed successfully on 2026-08-19, and that local generation now contains
the populated values. The final deadline vintage must still repeat rebuild/export/republish through
P0; the refreshed development generation does not replace the deadline artifact.

## player_actuals.json — one object per (season, code)

This normalized file carries finalized observed history without repeating it once per forecast
vintage. Each row has `season`, `code`, and a non-empty `actuals` array. Each actual contains
`gw`, `fixture`, `kickoff_time`, `minutes`, `starts`, `goals_scored`, `assists`, `clean_sheets`,
on-pitch `goals_conceded`, `saves`, `bonus`, `bps`, `defensive_contribution`, `expected_goals`,
`expected_assists`, `expected_goals_conceded`, and `points_under_rules_2026_27`.

Publication is limited to the union of every published run's forecast season and its immediate
predecessor. A predecessor enters the file only when finalized observed rows exist for an eligible
forecast-population player; no earlier observed season is transported.

Only officially complete gameweeks enter the file. Rows sort by gameweek, kickoff, then fixture;
both double-gameweek legs remain separate. Identities sort by season then code, duplicate fixture
identities fail closed, and source NULLs remain NULL. JavaScript may select one explicit season and
gameweek range and aggregate these observations; it may not treat them as forecast inputs or query
DuckDB for missing history.

## player_horizons.json — cumulative outcomes per player

Each player object contains one cumulative entry for every `gw_to` from its forecast run's
`gw_from` through `gw_to`. Its logical grain is `(run_id, season, code, gw_to)`, and the manifest
`row_count` counts those nested horizon entries rather than only the outer player objects.

The emitter starts with a point mass at zero and convolves the complete, already-DGW-convolved
player-gameweek distributions in ascending gameweek order. It validates the calculation at full
precision, then quantizes the seven published model values to six decimal places. xP has maximum
absolute serialization error `0.0000005`; a probability has error below `0.000001` because exact
zero and one are reserved for source probabilities at those exact boundaries. Each endpoint
carries:

- `xp`;
- `p_le_2`, meaning inclusive `P(total points <= 2)`;
- `p_ge_2`, `p_ge_4`, `p_ge_6`, `p_ge_10`, and `p_ge_15`, each inclusive.

Score 2 therefore belongs to both `p_le_2` and `p_ge_2`; the fields are not complements. A blank
gameweek's `[1.0]` point mass leaves the cumulative distribution unchanged. Missing player-week
rows, a duplicate week, malformed/non-finite/negative/non-normalised mass, or disagreement between
the PMF mean and stored xP fails publication. The source run's `row_count` and `roster_size` are
also reconciled so an entirely omitted player or run cannot disappear silently.

```json
{
  "schema": "fpl.dashboard-player-horizons",
  "json_schema_version": 7,
  "semantics": {
    "grain": ["run_id", "season", "code", "gw_to"],
    "cumulative_from": "dim_forecast_run.gw_from",
    "distribution_combination": "independent-gameweek-convolution-v1",
    "availability": "raw-model-distribution-unadjusted",
    "value_decimal_places": 6,
    "probability_boundary_policy": "preserve-exact-zero-one-v1",
    "thresholds": {"p_le": [2], "p_ge": [2, 4, 6, 10, 15]}
  },
  "horizon_fields": [
    "gw_to", "xp", "p_le_2", "p_ge_2", "p_ge_4", "p_ge_6", "p_ge_10", "p_ge_15"
  ],
  "players": [{
    "run_id": "f9bbd862…", "season": "2026-27", "code": 118748,
    "horizons": [[1, 6.41, 0.200, 0.852, 0.681, 0.512, 0.371, 0.126]]
  }]
}
```

`horizon_fields` is a fixed positional dictionary for the compact wire rows. The frontend checks
that exact order and maps each row to named values; that decoding is serialization work, not model
arithmetic. Unknown fields, the wrong order, excess precision, or a row of the wrong length fails
closed.

The semantics are deliberately explicit. The stored PMFs are raw model distributions: the
first-gameweek reported availability overlay is not mixed into xP or any probability and is never
repeated over later weeks. Only marginal player-gameweek PMFs are stored, so the cumulative
operation is versioned as an independent-across-gameweek convolution rather than claimed to be a
joint forecast.

Every endpoint always covers **all fixtures** from the run's fixed `gw_from` through its `gw_to`.
It cannot answer a shifted-start or Home/Away-only question. The dense Players table intentionally
omits the six overlapping threshold columns; Player analytics selects the exact fixed-start
endpoint for its blank/haul view. Arbitrary fixture filtering may still sum published xP, but it
never subtracts, rescales, or relabels a cumulative probability.

Expected points are summable; probabilities are not. A measured three-gameweek example gives
`P(total >= 6) = 0.9033` after convolution, while adding its three per-gameweek values gives
`1.0585` (invalid and above one). The same player's xP sums exactly to `13.3475`. Consequently:

- JavaScript may sum already-published xP, perform set operations, sort/filter rows, and compute
  presentation geometry such as hulls or quadrant boundaries;
- JavaScript may not add probability fields, convolve PMFs, derive a CCDF, or manufacture a model
  quantity from reporting primitives.

The design budget measured for 599 players over five endpoints was about 305 KB JSON / 76 KB
gzipped per vintage. The compact implementation's current 609-player/five-endpoint development
vintage measures 259,421 / 75,155 bytes; these are empirical sizes, not schema invariants. The
current file contains every published vintage, so its total size scales with the number of
recorded runs; the per-vintage comparison is the relevant raw-PMF comparison. Raw PMFs are absent
from this bulk payload. A future CCDF drill-down must publish precomputed CCDF points in
deterministic, lazy-loaded player shards (and cap the UI to a small comparison set); React may draw
those points but may not turn a PMF into a CCDF. That shard/shortlist policy is not introduced by
version 4.

## next_gw.json — one object per optimizer plan (P1.7d)

The population is every plan in the source export's `fact_optimizer_plan` (the export is
built with explicit `--optimizer-plan` artifact inputs; no plans in, no plans out — the UI
shows a "no plans" state, never a fabricated squad). Each plan object carries:

- identity and provenance: `optimizer_run_id`, `decision_sha256`, `forecast_run_id`, `as_of`,
  `season`, `gw_from`, `gw_to`;
- `component_modes` parsed from that plan's forecast run in `dim_forecast_run`, so the UI can
  show which architecture produced the plan;
- `plan_kind` and `display_label`, derived first from explicit
  `search_policy.plan_origin`, then (only for platform plans) from `component_modes`:
  `platform_default` for v3 goals/coupled assists, `platform_diagnostic` for any other
  platform architecture, and `user_custom` for every owner-built plan regardless of model;
  Their display prefixes are exactly "Platform default", "Diagnostic sensitivity", and
  "Your plan";
- compact `policy` with sorted `locked_codes`, sorted `excluded_codes`, and
  `min_bench_appearance`, so the user-plan result can explain its generating constraints
  without loading the full audit record;
- `weeks[]`, one per optimizer gameweek: `hit_points`, `squad_cost` (sum of `now_cost`, the
  deadline's static prices), `captain_code` / `vice_captain_code`, and `players[]` with role
  (`starting_xi` / `bench_goalkeeper` / `bench_outfield`), `bench_order_index`,
  transfer flags, price, and that gameweek's `expected_points` joined from the plan's own
  forecast run;
- `player_xp`: per `code`, the full-horizon per-gameweek EV map (`{"1": 7.4, …}`), so the
  UI's 1/3/5-GW selector sums inside one model. A missing/unmeasured gameweek is `null` and
  **makes the summed horizon EV null, never a partial sum**;
- `squad_context`: ownership/availability overlay and all five fallback/cold-start flags per
  code, taken from that forecast run's first gameweek (the same deadline-known rule as
  players.json identity). Availability is a reported overlay valid for the first forecast
  gameweek only.

The emitter fails closed when a plan references a forecast run absent from
`dim_forecast_run`, spans weeks outside its forecast horizon, mixes decisions, names a player
the forecast never rated, or lacks exactly one captain and one vice-captain in the XI.
A `fact_optimizer_plan` row without its matching `dim_optimizer_run` row also fails closed:
architecture alone is never accepted as a substitute for the search policy.
It also fails closed on an unknown `plan_origin` or malformed lock/exclusion policy.
For old optimizer artifacts, missing code lists mean empty lists and a missing
`min_bench_appearance` means `0.0`. A missing `plan_origin` is classified
`user_custom` when locks, exclusions, or a positive bench threshold are present; otherwise
it is `platform`. JSON `null` has the same legacy meaning as a missing field. An explicit
origin always wins over that compatibility inference, and the emitted audit `search_policy`
normalises the inferred value to `platform` or `user_custom`.

**The default-vs-diagnostic diff is not precomputed.** Both plans ship complete, and the UI
derives squad/XI overlap and captaincy agreement as set operations. Cross-plan EV is never
compared anywhere: absolute EV differences between architectures measure the two models'
calibration against each other, not squad quality (the P0.3 lesson).

## Historical `forecast_vs_actual.json` (version 2-4; removed in version 5)

One object per recorded vintage that has at least one scored player-gameweek, plus a
top-level `has_outcomes` flag. The join is **read-time only**: forecast rows keep their
`run_id`, outcome rows carry none, and they meet on `(season, gw, code)` — gameweek actuals
are the sum of `points_under_rules_2026_27` over that gameweek's finalised player-fixture
rows. Unfinalised (NULL-points) rows are excluded from every sum, never read as zero.

Each run block reports `rows`, `mean_ev`, `mean_actual`, `bias` (actual − EV; positive = the
model under-predicted), `mae`, and `crps` (mean discrete CRPS computed from the stored
full-points distribution by the double-sum identity; a malformed pmf scores `crps: null` for
that row rather than inventing a number), split `by_position` and `by_gw`, plus a
`calibration` table bucketing predicted `P(points >= 2)` (from the stored distribution)
against the observed rate. **With no finalised outcomes inside any vintage's horizon — the
2026-27 GW1 state — `has_outcomes` is false, `runs` is empty, and the UI shows the framework
with an explicit explanation instead of zero-filled numbers.** Cross-vintage EV differences
measure calibration, not squad quality; a run is compared only against its own outcomes.

This section preserves the historical P1.7e contract only. Version 5 does not emit or public-package
this file, and the frontend never accepts it as current monitoring evidence.

## `player_forecast_vs_actual.json` — complete-gameweek player monitoring (P2.3)

One run block per recorded vintage, with explicit coverage/finality, scalar observations, overall
scores, position/gameweek/team slices, and threshold calibration. Observation grain is
`(run_id, season, gw, code)`. Forecasts retain `run_id`; ledger outcomes carry none and join only at
read time. A player-gameweek is scored only when the official gameweek is complete and every
forecast fixture leg has an immutable replayed-points outcome. One final leg of a double gameweek
and one pending leg produces no observation. Missing outcomes increment coverage and never become
zero.

The Python emitter computes signed residual `actual - forecast`, absolute error, RMSE inputs, exact
discrete CRPS, and inclusive calibration probabilities from the stored gameweek PMF. The JSON
contains those scalar results, not the PMF. Positive residual means the model under-predicted.

## `team_forecast_vs_actual.json` — directed team-fixture monitoring (P2.3)

Observation grain is `(run_id, season, fixture, team_code)`. Each observation carries the directed
team/opponent identity, gameweek, kickoff, venue, forecast lambdas, official finalized goals,
signed attack/defence residuals, clean-sheet probability/outcome, attack CRPS, defence CRPS,
clean-sheet Brier, and Stage-A fallback status. Attack CRPS uses the named team's exact stored
`goals_for_distribution`; defence CRPS uses the opponent side's exact distribution for the same
fixture. Neither distribution is regenerated from a lambda or exposed to JavaScript.

Positive attack residual means more goals scored than forecast. Positive defence residual means
more goals conceded than forecast and is therefore worse. Each run publishes coverage plus attack,
defence, and clean-sheet score blocks and slices. A team fixture is eligible only after the two
official-score outcome sides have been attached reciprocally.

## summary.json — the landing snapshot (P1.7d)

A single object: the latest recorded run (`max created_at`) with its parsed component modes,
roster coverage (players/clubs with forecast rows), the next gameweek's `first_kickoff` /
`last_kickoff` / `fixture_count` from `dim_gameweek` (**deadlines are not sourced — the
export's `deadline_time` is a typed NULL and none is ever fabricated**), top-5 lists for
next-GW xP, horizon xP, and flagged-availability xP (the availability overlay is labelled as
such), the three easiest and hardest next-GW fixtures by directed ease with official FDR
beside (never blended), the optimizer plans present, and the ease formula version. With no
recorded runs the summary is an explicit null-run object, not an error.

## optimizer_audit.json — one object per optimizer plan (P1.7e)

The population is every row of the source export's `dim_optimizer_run` (itself sourced only
from optimizer decision artifacts passed explicitly to the export). Each plan object carries
the run's full provenance — both Git commits with the clean-worktree guarantee, forecast
artifact SHA-256, squad-rule path/contract version/SHA-256 — the solver identity (name,
package + binary versions, deterministic options, seed, status), the parsed bounded-search
`search_policy`, the parsed `rules_snapshot` (the constraints the plan obeyed), the explicit
`assumptions` list, and the development-only `status`. `component_modes` from the plan's
forecast run labels which architecture produced it. The same `plan_kind` and
`display_label` used by `next_gw.json` are repeated here so audit navigation cannot
silently reclassify a plan.

The three JSON columns are parsed at emit time and fail closed on malformed content. **The
squad, XI, and transfer path are not duplicated here** — `next_gw.json` already carries them,
and the audit page reads both files.

## Read-model manifest

```json
{
  "schema": "fpl.dashboard-read-models",
  "json_schema_version": 7,
  "generated_at": "2026-08-15T00:00:00+00:00",
  "source": {
    "export_schema": "fpl.bi-semantic-export",
    "export_schema_version": 1,
    "semantic_contract_version": 4,
    "export_content_sha256": "…",
    "export_created_at": "…",
    "database_sha256": "…"
  },
  "runs": [
    {"run_id": "…", "as_of": "…", "season": "2026-27", "gw_from": 1, "gw_to": 5,
     "horizon_gameweeks": 5}
  ],
  "run_ids": ["…"],
  "ease_index_formula_version": "fixture-ease-v1",
  "files": {
    "fixture_matrix.json": {"row_count": 20, "sha256": "…"},
    "players.json": {"row_count": 599, "sha256": "…"},
    "player_actuals.json": {"row_count": 1078, "sha256": "…"},
    "player_horizons.json": {"row_count": 2995, "sha256": "…"},
    "next_gw.json": {"row_count": 2, "sha256": "…"},
    "summary.json": {"row_count": 1, "sha256": "…"},
    "player_forecast_vs_actual.json": {"row_count": 0, "sha256": "…"},
    "team_forecast_vs_actual.json": {"row_count": 0, "sha256": "…"},
    "optimizer_audit.json": {"row_count": 2, "sha256": "…"}
  },
  "content_sha256": "…"
}
```

`row_count` is the number of objects in the file's top-level array (`plans` for
next_gw.json and optimizer_audit.json, `runs` for both forecast-monitoring files, and normalized
season/player records for `player_actuals.json`), except that
`player_horizons.json` counts its nested cumulative endpoint rows. `summary.json` is a single
object, so its row count is 1. `runs` is sorted by `run_id` and validated against
both the source manifest's `exported_run_ids` and the `dim_forecast_run` rows read from the
export. Every fixture row must fall inside its run's `gw_from..gw_to` horizon and season;
anything outside fails closed. A source export that mixes ease formula versions also fails
closed.

## Consumers

The static app, any notebook, and any external tool read only these files (or the Parquet export).
Nothing downstream of the BI boundary queries DuckDB. All nine read-only dashboard routes have
read models; later pages require an explicit schema bump under the same manifest policy. Version-6
consumers must republish before loading version 7. Version-7 consumers load cumulative outcomes
through the strict `player_horizons.json` boundary and look up an exact
`(run_id, season, code, gw_to)` endpoint;
they never interpolate or substitute another vintage. The Players route uses the exact xP endpoint
when applicable and delegates probability comparison to Player analytics.
