# BI semantic contract, version 1

Status: **frozen** (DEV-ROADMAP P1.1). Development-only data, like everything upstream of it.

This is the authoritative description of what the BI export publishes. Its executable counterpart is
`src/fpl/publish/contract.py`, which declares the same schema as typed data and validates it; the two
must be changed together. P1.2-P1.4 were built against this contract rather than discovering a
schema by writing an exporter. The atomic publication and manifest rules are in
`docs/bi-export-contract.md`.

Nothing downstream of the publish boundary queries the mutable production DuckDB. BI, dashboards and
notebooks read only the atomic read-only export that P1.4 produces.

## Why the contract is executable

Every expensive defect in this repository has been join-shaped, and prose cannot stop a join.

`element_id` and `team_id` are **reassigned every season**. Measured: `element_id = 308` resolves to
Almiron, Aké, Salah, Ward and Heath across five seasons, so joining on it merges five different
players into one history. Club id 10 is Leeds, Leicester, Fulham, Ipswich, then Fulham again -- the
failure mode is not that ids move but that they *return*, so the join looks like it works and yields
a Fulham history with Ipswich in the middle. Compressing 26 clubs into 20 id slots already cost
**0.022 of mean log score** inside the Stage A baselines before anyone noticed.

So `SemanticContract.validate_contract()` mechanically rejects any declared join that touches a
season-scoped id without binding `season`, and `tests/test_bi_semantic_contract.py` proves it does by
constructing the violation and asserting the rejection.

## Keys

| Purpose | Key | Never |
| --- | --- | --- |
| Player across seasons | `code` | `element_id`, `web_name` |
| Player within a season | `(season, code)` | bare `element_id` |
| Club across seasons | `team_code` | `team_id` |
| Club within a season | `(season, team_id)` | bare `team_id` |
| Player-fixture facts | `(season, code, fixture)` | player-gameweek |
| Team-fixture facts | `(season, team_id, fixture)` | bare `team_id` |
| Forecast facts | prefixed by `run_id` | any un-versioned forecast row |

`web_name` drifts between seasons (`Salah` → `M.Salah`). It is a display attribute, never a key and
never a join column.

## Meta-rules the validator enforces

1. **Every forecast fact carries `run_id` and `as_of`, and keys on `run_id`.** Without `run_id` in
   the grain a later vintage would collide with an earlier one, and the ledger is append-only by
   contract.
2. **No outcome fact carries `run_id`.** Predictions and outcomes stay separate until finalisation
   and are joined only at read time.
3. **A season-scoped id may only be joined with `season` bound in the same join.**
4. **A `many_to_one` join must bind its target's full grain**, or it is not many-to-one and will fan
   out.
5. **Grain columns are non-nullable.**
6. **Every nullable column declares what its NULL means** — one of `unmeasured`, `not_applicable`,
   `unknown_until_finalised`, `optional_attribute`. There is deliberately **no `zero` option**: an
   unmeasured xG and a measured xG of `0.0` are different facts, and zero-filling destroys the
   distinction.
7. Join targets and columns must resolve, and table names must be unique.

## Dimensions

### `dim_forecast_run` — grain `run_id`

One immutable prediction vintage from the append-only ledger. Source: `ledger_forecast_run`.

`as_of` is **knowledge time** and is the most important column in the schema. Comparing two vintages
without slicing by it compares different knowledge states. `component_modes` is what distinguishes a
default vintage from a diagnostic one.

### `dim_player` — grain `code`

A player's permanent identity, and the only player dimension safe to join across seasons without
fanning out. It carries **no club and no position**: both are season-scoped, and club is time-scoped
even within a season. `latest_web_name` is display-only.

### `dim_player_season` — grain `(season, code)`

Season-scoped attributes: `element_id`, `web_name`, `position`.

`season_end_team_id` is present for reporting and is **documented as unreliable**: it records only
the club a player finished the season at, and matched the true club in **120 of 242** measured
transfer stints. Never resolve club membership from it.

### `dim_player_stint` — grain `(season, code, stint_index)`

A continuous spell at one club within one season, with both `team_id` and `team_code`. This is the
answer to "which club was this player at", because that question has a time in it. A player may have
more than two stints; **three clubs in one season occurs**.

When a player moves, his attacking *share* travels with him and the team *scale* does not, and
defensive contribution is a property of the team system (measured team hit rates 0.333 to 0.146), so
expectations are not portable across stints.

### `dim_team` — grain `team_code`

The club's permanent identity: 27 codes over five seasons, 1:1 with the club. The only club key
allowed to join across seasons.

### `dim_team_season` — grain `(season, team_id)`

The season-scoped club id and the `team_code` it resolves to in that season. Every fact joins clubs
through here, season-qualified.

### `dim_fixture` — grain `(season, fixture)`

One match. `gw` and `kickoff_time` are nullable because a fixture may be unscheduled or postponed.
`kickoff_time` is **event time** and governs which outcomes were observable; it is not knowledge
time, and schedules are themselves versioned by `known_at` upstream.

### `dim_gameweek` — grain `(season, gw)`

One gameweek. **Never assume 1..38** — 2022-23 has no GW7. Iterate observed gameweeks.

### `dim_optimizer_run` — grain `(optimizer_run_id)` (P1.7e)

One row per optimizer decision artifact explicitly passed to the export (`--optimizer-plan`;
a database alone contributes no rows — no plans in, no rows published). Carries the run-level
provenance `fact_optimizer_plan` deliberately does not repeat at player grain: both Git
commits (optimizer and forecast) with the clean-worktree guarantee, the forecast artifact
SHA-256, the squad-rule path/contract version/SHA-256, the full solver identity (name,
package + binary versions, deterministic options, seed, status), the search method and
declared optimality scope, risk lambda, and three deterministic JSON columns — the complete
bounded-search `search_policy`, the verified `rules_snapshot` (the constraints), and the
`assumptions` list. Joins many-to-one to `dim_forecast_run` on `forecast_run_id`: one vintage
can back several plans (default and diagnostic architectures), never the reverse. Sourced and
declared in the same change, so it was never in `NOT_YET_SOURCED`; the contract stays at v1
(an additive table, exactly as `fact_team_form` was added).

## Facts

### `fact_forecast_player_gameweek` — grain `(run_id, season, gw, code)`

A player's forecast full-points distribution for a gameweek, from
`ledger_prediction_player_gameweek`. Where a club has two fixtures in a gameweek, this is the
convolution of that player's fixture distributions.

`distribution` is a JSON probability vector indexed by whole points. It is the reason this project
models distributions at all: quantiles, `P(points >= threshold)` and downside risk all come from it,
and a mean alone cannot answer a captaincy or differential question.

**Availability is a reported overlay, never folded into the stored distribution.** To apply it,
*mix*: `m * distribution + (1 - m) * point mass at zero`. Never multiply a quantile by the
multiplier. The overlay is valid for the **first forecast gameweek only**; reusing it across later
gameweeks is an explicit scenario assumption, never a measured per-gameweek policy.

Degradation flags travel with the row: `cold_start_player`, `stage_a_league_average_team`,
`attacking_signal_cold_start`, `assist_signal_cold_start`, `transferred_no_rescale`.

### `fact_forecast_player_fixture` — grain `(run_id, season, fixture, code)`

**Sourced by P1.2** from `ledger_prediction_player_fixture`. This is the natural forecast grain:
double gameweeks are real, and the gameweek row is *derived* from these by convolution. Do **not**
reverse-engineer fixture values out of a convolved gameweek distribution; the convolution is not
invertible. Each row maps to exactly one gameweek row via `(run_id, season, gw, code)`, and that
mapping is part of the transport contract.

### `fact_forecast_team_fixture` — grain `(run_id, season, fixture, team_id)`

**Sourced by P1.2** from `ledger_prediction_team_fixture`. Two rows per fixture, one per club.
These are the fixture-difficulty **primitives**: `lambda_for`, `lambda_against`,
`probability_clean_sheet`, plus the official FDR as a separate measure. P1.5 publishes the raw
lambdas beside four nullable derived values and a non-null formula identity:

```text
league_average_team_lambda = mean(lambda_for) over (run_id, season)
attack_ease_index           = 100 * lambda_for / league_average_team_lambda
defence_ease_index          = 100 * league_average_team_lambda / lambda_against
overall_ease_index          = sqrt(attack_ease_index * defence_ease_index)
ease_index_formula_version  = "fixture-ease-v1"
```

These are **ease** indices: `100` is league average and **higher means easier/better for the named
team**. The denominator uses all team-fixture rows in the same forecast vintage and season. At least
two rows must support it and its mean must be positive; otherwise the denominator and all three
indices are NULL, never zero. `lambda_against = 0` makes the defence and overall indices NULL rather
than infinite. Because each club's `lambda_for` for one fixture equals the other club's
`lambda_against`, the same per-season mean serves both attack and defence directions.

The formula is a publish-layer derivation: the immutable forecast artifact and ledger keep only the
primitives, so the composite remains re-derivable and re-versionable. The table stays at
per-team-fixture grain. Rolling 3/5-GW views are dashboard aggregations in P1.7, not pre-aggregated
facts here.

`official_fdr` is an official schedule property, not forecast-derived: historical rows come from
`mart_fact_team_match.fdr`; a live season uses the latest `mart_team_fixture_live.fdr` capture per
`(season, fixture, team_id)`. It remains NULL where unavailable. Never display an undirected
"difficulty" number, and **never blend official FDR into any model ease index**.

Read the lambdas and ease indices as a **relative** signal. Stage A predicts about 2.86 goals per fixture regardless
of the season it is in, while actual season rates range 2.645 to 3.147, so the absolute level is not
calibrated to the current season.

### `fact_player_fixture_actual` — grain `(season, fixture, code)`

What a player actually did, from `mart_fact_player_fixture` + `mart_target_player_fixture`. Carries
**no `run_id`**.

`total_points_as_recorded` and `points_under_rules_2026_27` are **different measures** and are never
conflated or summed together. Recorded points are never a model feature or a cross-season target.

`expected_goals` / `expected_assists` are **NULL where unmeasured, never zero**: 2021-22 carries no
xG at all and 2022-23 only 64% coverage. Zero-filling produces a pooled figure that measures xG's
absence rather than its value.

`goals_conceded` is already an **on-pitch** figure. A substitute sees about **35% more** of his
club's conceded goals than his share of the minutes implies (measured exposure 0.344 / 0.813 / 0.999
by minutes bin against 0.254 / 0.837 / 1.000 by minutes), so never derive on-pitch exposure from
minutes.

### `fact_player_form` — grain `(season, gw, code, window)`

**Sourced by P1.6** as `mart_fact_player_form`, built from `mart_fact_player_fixture` and the
separately owned `points_under_rules_2026_27` target in `mart_target_player_fixture`. Long format,
one row per window (`last_3`, `last_5`, `last_10`, `season_to_date`), so a pivot can put window on
an axis.

**Availability and productivity have different denominators and must not be mixed.** Availability
counts *rostered* fixtures (appearances, starts, minutes, DNPs); productivity counts *appeared*
fixtures (goals, assists, bonus, BPS, DC, xG, xA). Here **rostered means that a
`mart_fact_player_fixture` row exists** -- the registered player-fixture population, not an inferred
matchday squad. A zero-minute row is therefore rostered and is counted as a DNP, but contributes no
productivity measure.

Each anchor is an observed `(season, gw, code)` with a player-fixture row. The rolling windows take
that player's most recent rostered fixtures ordered by kickoff, with the anchor gameweek's latest
kickoff as the point-in-time cutoff; double-gameweek legs are retained as two fixture rows, while a
missing published gameweek creates no synthetic form row. `season_to_date` remains within the same
season.

`starts` is NULL when any rostered source row in the window has unmeasured starts. In particular,
the 2021-22 archive did not measure starts at all, so reporting zero there would create a false
availability fact.

Per-90 rates use only the matching measured rows:

```text
xG_per_90 = 90 * sum(expected_goals) / sum(minutes on those same measured-xG rows)
xA_per_90 = 90 * sum(expected_assists) / sum(minutes on those same measured-xA rows)
```

NULL when that denominator is zero. A per-90 is a **display** measure: never multiply it by expected
minutes in the reporting layer to synthesise a forecast.

### `fact_team_form` — grain `(season, gw, team_code, window)`

**Sourced by P1.6b** (owner-approved addition) as `mart_fact_team_form`, built from
`mart_fact_team_match` with `team_code` resolved through `mart_dim_team` inside each match's own
season. Long format, one row per window (`last_3`, `last_5`, `last_10`, `season_to_date`). It is
the data behind the P1.7 fixture-matrix **Team** page's recent-form block, and the club-level
counterpart of `fact_player_form` with the same anchoring: observed gameweeks only, the window ends
at the anchor gameweek inclusive, the anchor gameweek's latest kickoff is the point-in-time
boundary, both legs of a double gameweek count as two matches, and a blank gameweek creates no row
and never a synthetic match.

Keyed on `team_code`, **never `team_id`** — club ids are reassigned every season. It is
backward-looking observed form from the historical marts and carries no `run_id`; a live season with
no finished matches contributes zero rows.

`team_xg` / `team_xgc` are NULL where unmeasured — the whole of 2021-22 measured no xG — and their
per-match rates are additionally NULL then, never `0.0`. Goal aggregates (`goals_for`,
`goals_against`, `clean_sheets`, `wins`, `draws`, `losses`) are NULL when any match in the window
has an unmeasured score rather than silently undercounting. The goal per-match rates are
`measure / matches_played`, but the `team_xg` / `team_xgc` per-match rates divide by the count of
**measured**-xG/xGC matches, not `matches_played`, so partial coverage (2022-23 measured only 64% of
matches) does not understate them — mirroring `fact_player_form`, whose per-90 denominator is minutes
on measured-xG rows only. All per-match rates are NULL on a zero denominator; they are display
measures and must never be multiplied by a fixture count to synthesise a forecast.

### `fact_optimizer_plan` — grain `(optimizer_run_id, gw, code)`

One player's role in one planned gameweek, from `fpl.artifacts.optimizer_plan`. It carries
`forecast_run_id`, not `run_id`: a plan is not a forecast vintage, it is a decision derived from one.

Every gameweek after the first uses the deadline's static price, so later-gameweek affordability is a
**frozen-price scenario**, not a price forecast. The initial squad is exact; the transfer path is
optimal only within the configured bounded search.

## Additions to the roadmap's original table list

P1.1 is the design step, so identifying that the listed five dimensions were insufficient is part of
the work. Three were added, each forced by a documented invariant rather than by taste:

| Added | Because |
| --- | --- |
| `dim_player_season` | `web_name`, `position` and `element_id` are all season-scoped, so a single `code`-grain player dimension carrying them would either misreport them or fan a cross-season query out by season. |
| `dim_player_stint` | Club membership is time-scoped within a season. `AGENTS.md` forbids resolving club from a player dimension; without a stint table there is nowhere correct to resolve it. |
| `dim_team_season` | The season-scoped `team_id` on every fact needs somewhere to resolve to a cross-season `team_code`. Without it, cross-season club analysis has to join on `team_id` — the exact defect that cost 0.022 of log score. |

`dim_player` and `dim_team` remain as the roadmap named them, narrowed to permanent identity only.

## Source completeness

Every v1 table now has a concrete source owner: P1.2 supplies the two fixture-grain forecast facts,
P1.6 supplies `fact_player_form`, and P1.6b adds `fact_team_form` (declared and sourced in the same
change, so it is never in `NOT_YET_SOURCED`). Consequently `contract.NOT_YET_SOURCED` is empty; P1.4
can require the complete v1 contract rather than silently emitting an apparently complete partial
export.
