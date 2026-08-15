# BI export contract, version 1

Status: implemented by DEV-ROADMAP P1.4. This document describes the durable, read-only BI
boundary; `src/fpl/publish/contract.py` remains the frozen semantic schema authority.

## Boundary

`fpl.publish.export` is upstream of every dashboard, notebook, and external BI tool. It reads the
production DuckDB and explicit optimizer decision artifacts, materialises the complete contract,
validates it, and publishes the result atomically. **Nothing downstream may query the production
DuckDB.** Consumers read only this export.

The job is deliberately thin:

```text
python -m fpl.jobs.export_bi --output data/bi-export [--db data/fpl.duckdb]
    [--optimizer-plan data/optimizer-plan.json ...]
    [--max-source-age-hours 24]
```

## Layout and atomic publication

The stable output path is an atomic symlink to a private sibling generation directory. Readers of
`data/bi-export/` therefore see either the complete previous generation or the complete new one,
never a directory containing a mixture of both.

```text
data/
├── bi-export -> .bi-export.generation.9b4…/
└── .bi-export.generation.9b4…/
    ├── manifest.json
    ├── dim_forecast_run.parquet
    ├── dim_player.parquet
    ├── dim_player_season.parquet
    ├── dim_player_stint.parquet
    ├── dim_team.parquet
    ├── dim_team_season.parquet
    ├── dim_fixture.parquet
    ├── dim_gameweek.parquet
    ├── fact_forecast_player_gameweek.parquet
    ├── fact_forecast_player_fixture.parquet
    ├── fact_forecast_team_fixture.parquet
    ├── fact_player_fixture_actual.parquet
    ├── fact_player_form.parquet
    ├── fact_team_form.parquet
    └── fact_optimizer_plan.parquet
```

The exporter builds in a unique sibling `.tmp` directory, validates every file and the manifest,
renames it to a private generation, then swaps the endpoint symlink with `os.replace`. An exclusive
sibling lock rejects a concurrent publisher; an unmanaged target path is never replaced. Any
failure removes the temporary generation and leaves the old endpoint unchanged.

## Selection decisions

### Forecast runs

The export contains **all recorded ledger forecast vintages**. `dim_forecast_run` enumerates every
run and each forecast fact carries its `run_id` and `as_of`.

A database freshly built by `fpl.jobs.build_db` has no ledger schema until the first
`record_forecast` invocation. That is a complete zero-vintage export: `dim_forecast_run` and all
three forecast facts contain zero rows, not a partial contract and not an error. A partial ledger
schema, or a populated required source table missing a required column, fails closed.

A recorded schema-version-1 forecast vintage can likewise have zero fixture-grain transport rows;
its player-gameweek rows remain exported and its two fixture facts are empty for that vintage. The
exporter does not manufacture fixture forecasts from a convolved gameweek distribution.

### Live-season dimensions

A real deadline forecast is for the **upcoming** season, which the archive marts
(`mart_dim_player`, `mart_dim_team`, `stg_fixture`) never cover — they are built from completed
seasons only. Without a source for that season's players, clubs, fixtures and gameweeks, a recorded
live-season forecast would fail referential integrity (its `code`, `team_id`/`team_code`, `fixture`
and `gw` resolve to no dimension row) and could not be published.

The six affected dimensions (`dim_player`, `dim_player_season`, `dim_team`, `dim_team_season`,
`dim_fixture`, `dim_gameweek`) therefore **union the archive marts with the versioned live staging**
(`stg_live_player_version`, `stg_live_team_version`, `stg_live_fixture_version`) for any season the
marts do not carry. `stg_live_team_version` is flattened from the bootstrap-static `teams` payload
at snapshot-load time; it is the only source of the live season's season-scoped `team_id → team_code`
map and club names. A fresh build with no snapshots loaded leaves the live staging empty, so the
export is historical-only — unchanged from before.

**Point-in-time policy.** A live-season dimension row is the **latest committed snapshot per entity**
(the most recent capture by `known_at`) — the current registry. This introduces no leakage: the
dimension is descriptive current attributes, while every forecast fact keeps its own `as_of` and
`bootstrap_known_at`; no forecast input is derived from it. Per-vintage (slowly-changing) dimension
history is out of scope for v1. Season-scoped ids (`element_id`, `team_id`) are never joined across
seasons; live rows are unioned only for seasons the marts omit, so no `(season, id)` grain collides.

### Optimizer plans

Optimizer decision artifacts are never discovered implicitly. Pass zero or more
`--optimizer-plan` paths; no paths produces an empty `fact_optimizer_plan`. Each artifact's
forecast SHA and declared forecast provenance must resolve to exactly one row in the exported
`dim_forecast_run`; otherwise the entire export is rejected.

`fact_optimizer_plan` is at post-transfer squad-member grain. Version-1 decision artifacts do not
emit outgoing players as post-transfer squad members, so valid rows have `transferred_out = false`;
the artifact's transfer list remains the source of any separate outgoing-player analysis. The
exporter does not invent an artificial role or row to make that field appear populated.

### Actuals and unmeasured values

`fact_player_fixture_actual` comes only from `mart_fact_player_fixture` joined to
`mart_target_player_fixture`. It carries no `run_id`, and preserves
`total_points_as_recorded` and `points_under_rules_2026_27` as separate measures.

No source NULL is zero-filled. Nullable floats remain Parquet NULLs—not `NaN` and not `0.0`—and
non-finite floats are refused. The P1.2 ledger does not persist fixture-level player minutes/rates,
so those player-fixture fields are explicit typed NULLs rather than reconstructed values.

### Team form

`fact_team_form` is a direct projection of `mart_fact_team_form` — backward-looking observed form at
`(season, gw, team_code, window)` grain, keyed on the cross-season `team_code`. It carries no
timestamps and no `run_id`. A live season with no finished matches contributes zero rows, exactly as
for `fact_player_form`. Its NULL discipline is re-asserted after the Parquet round trip like every
other table: unmeasured `team_xg`/`team_xgc` (all of 2021-22) stay NULL, never `0.0`, and their
per-match rates are NULL whenever their numerator is.

### Fixture ease and official FDR

The team-fixture ease columns are derived only in this publish layer from the immutable stored
`lambda_for` / `lambda_against` primitives. Formula version `fixture-ease-v1` uses one denominator
per `(run_id, season)`: the mean `lambda_for` over every team-fixture row in that group. At least two
rows and a positive mean are required. When either check fails,
`league_average_team_lambda`, `attack_ease_index`, `defence_ease_index`, and
`overall_ease_index` are Parquet NULLs. A zero `lambda_against` also makes defence and overall NULL,
never infinity. The formula identity remains non-null even on a row whose indices are unavailable.

`official_fdr` is joined separately on the complete season-qualified fixture-team key. Historical
seasons use `mart_fact_team_match.fdr`. A season absent from that archive mart uses
`mart_team_fixture_live.fdr`, selecting the latest `(known_at, capture_id)` per
`(season, fixture, team_id)`, consistent with the live-dimension current-registry policy. Missing FDR
stays NULL. It is never an input to the denominator or any ease index.

## Validation

Before publication, the exporter verifies:

- exact declared columns, deterministic contract order, and declared Arrow-compatible dtypes;
- non-null, unique and explicitly grain-ordered rows for every table;
- child-to-parent referential integrity for every declared `Join`, including `season` for every
  `element_id`, `team_id`, or `opponent_team_id` relationship;
- Parquet round-trip row counts and NULL counts, plus the absence of non-finite floats;
- a strict JSON manifest (`allow_nan=False`), per-file SHA-256 values, and row accounting; and
- a stable source database SHA-256 before and after reading, so a changing source database cannot
  produce a mixed export.

Parquet uses a fixed writer configuration and every table is sorted by its declared grain. Identical
inputs therefore produce byte-identical Parquet files. `created_at` is intentionally excluded from
the manifest's `content_sha256` so it does not change the content identity.

## Freshness and manifest

`bootstrap_known_at` is the available live-input knowledge time in the ledger. Every run must have
`known_at <= as_of`; an optional `--max-source-age-hours` adds an operator-selected age ceiling.
Without that option, the exporter records age and cold-start state without imposing an arbitrary
pre-season expiry policy.

An abbreviated zero-vintage manifest looks like this (real SHA-256 values are 64 hexadecimal
characters):

```json
{
  "schema": "fpl.bi-semantic-export",
  "schema_version": 1,
  "semantic_contract_version": 1,
  "created_at": "2026-08-14T00:00:00+00:00",
  "database_sha256": "…",
  "exported_run_ids": [],
  "source_known_at": {"minimum": null, "maximum": null},
  "freshness": {
    "status": "complete_no_recorded_forecast_runs",
    "all_known_at_at_or_before_as_of": true,
    "cold_start_run_ids": [],
    "source_age_seconds": {"minimum": null, "maximum": null},
    "maximum_source_age_seconds": null
  },
  "tables": {
    "dim_forecast_run": {
      "file": "dim_forecast_run.parquet",
      "row_count": 0,
      "sha256": "…"
    }
  },
  "content_sha256": "…"
}
```

The real `tables` object always contains all fifteen contract tables. `created_at`, exported
`run_id`s, source min/max `known_at`, freshness, database hash, per-table row counts, and per-file
hashes are all required and validated on read.
