# Dashboard read-model JSON contract, version 1

Status: implemented by DEV-ROADMAP P1.7a (backend publish layer only; no UI). This document
is the authoritative prose counterpart of `src/fpl/publish/dashboard_json.py`. The P1.7b
static app renders these files and nothing else.

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
identical inputs produce byte-identical `fixture_matrix.json` / `players.json` and an identical
content hash.

## Layout

```text
data/
├── dashboard-json -> .dashboard-json.generation.9b4…/
└── .dashboard-json.generation.9b4…/
    ├── manifest.json
    ├── fixture_matrix.json
    └── players.json
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
  so the UI can label how old the form is. All four windows (`last_3`, `last_5`, `last_10`,
  `season_to_date`) carry every measure including per-match rates, NULLs preserved.
- `fixtures` is every team-fixture row of that vintage, ordered by `gw`, then kickoff, then
  fixture id — both legs of a double gameweek are separate entries. `kickoff_time` may be
  `null` for an unscheduled fixture and orders last, never first.

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
  with DNPs included, `null` when there is no window.
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

## Read-model manifest

```json
{
  "schema": "fpl.dashboard-read-models",
  "json_schema_version": 1,
  "generated_at": "2026-08-15T00:00:00+00:00",
  "source": {
    "export_schema": "fpl.bi-semantic-export",
    "export_schema_version": 1,
    "semantic_contract_version": 1,
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
    "players.json": {"row_count": 581, "sha256": "…"}
  },
  "content_sha256": "…"
}
```

`row_count` is the number of objects in the file's top-level array. `runs` is sorted by
`run_id` and validated against both the source manifest's `exported_run_ids` and the
`dim_forecast_run` rows read from the export. Every fixture row must fall inside its run's
`gw_from..gw_to` horizon and season; anything outside fails closed. A source export that
mixes ease formula versions also fails closed.

## Consumers

The P1.7b static app, any notebook, and any external tool read only these files (or the
Parquet export). Nothing downstream of the BI boundary queries DuckDB. Read models for the
summary / next-GW / forecast-vs-actual / optimizer pages are later additive files under this
same manifest and schema version bump policy.
