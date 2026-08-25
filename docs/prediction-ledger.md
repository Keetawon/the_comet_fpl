# Append-only prediction ledger

Status: implemented, development-only tooling. It records, without altering, the forecasts this
repository produces so that a pre-deadline commitment exists on the record.

## Why it exists

Every model result in this repository is caveated "development-only" for one specific reason: the
historical evaluations used unversioned, outcome-derived proxies for the target roster and the
knowledge-time cutoff. No amount of further archive work removes that caveat -- a prediction
reconstructed later, by code written after the outcome was known, is weak evidence. The only thing
that lifts it is a forecast recorded **before** a real deadline, with its knowledge time and inputs
pinned. Daily snapshots protect the inputs; this ledger protects the commitment.

## Input boundary

The ledger consumes the frozen prospective-points JSONL artifact documented in
`docs/prospective-points-artifact.md` and nothing else. It never reaches around that boundary into
the models or the database to re-derive a prediction: the artifact boundary is what makes a recorded
run auditable. `src/fpl/storage/ledger.py` holds the forecast domain logic;
`python -m fpl.jobs.record_forecast <artifact.jsonl> [--db PATH]` is a thin CLI over it.

Finalized actuals have a separate, deliberately narrow mart boundary:
`python -m fpl.jobs.attach_outcomes --as-of <ISO-8601-with-offset> [--season SEASON] [--db PATH]`.
`fpl.storage.outcomes` reads only `mart_target_player_fixture` joined on the season-qualified
fixture key to `stg_fixture`. The latter's `finished = TRUE` is the authoritative official-fixtures
finalization signal retained by the repository; both point columns must be non-NULL and
`kickoff_time < as_of`. The job never reads or changes a prediction.

## Schema

Five tables in the main DuckDB, all prefixed `ledger_`.

`ledger_forecast_run` -- one immutable row per recorded run, carrying the manifest's full provenance:
`run_id` (PK), `created_at`, `as_of`, `season`, `gw_from`, `gw_to`, `commit_sha`, `database_sha256`,
`artifact_sha256`, `base_seed`, `monte_carlo_draws`, `fixture_points_support_max`,
`freshness_cold_start`, `worktree_clean`, `row_count`, `roster_size`, `fixture_count`,
`contract_identities` (JSON), `component_modes` (JSON), `bootstrap_capture_id`, `bootstrap_known_at`,
`bootstrap_payload_sha256`, and `schedule_capture_ids` (JSON).

`ledger_prediction_player_gameweek` -- PK `(run_id, season, gw, code)`, every `ForecastArtifactRow`
field including the full `distribution` (`DOUBLE[]`) and all five degradation flags
(`cold_start_player`, `stage_a_league_average_team`, `attacking_signal_cold_start`,
`assist_signal_cold_start`, `transferred_no_rescale`). `fixture_ids` and `kickoff_times` are stored
as JSON arrays, preserving the fixture linkage. Nullable live fields (`web_name`, `team_code`,
`now_cost`, `selected_by_percent`, `chance_of_playing`) stay `NULL`; nothing is coerced to zero.

`ledger_prediction_player_fixture` -- PK `(run_id, season, fixture, code)`, the fixture-grain
transport added by P1.2. Carries `gw`, `kickoff_time`, `position`, `team_id`, nullable `team_code`,
`opponent_team_id`, `was_home`, the full per-fixture `distribution` (`DOUBLE[]`),
`expected_points`, `expected_bonus`, and `stage_a_league_average_team`. This is the grain the
composer works at; the gameweek table is its convolution, and the artifact proves that relation on
every read.

`ledger_prediction_team_fixture` -- PK `(run_id, season, fixture, team_id)`, two rows per fixture.
Carries `gw`, `kickoff_time`, `team_code`, `opponent_team_id`, `was_home`, `lambda_for`,
`lambda_against`, `probability_clean_sheet`, `goals_for_distribution` (`DOUBLE[]`), and
`stage_a_league_average_team`. These are the fixture-difficulty primitives the BI layer publishes.

Both fixture tables are written inside the same transaction as the run and its gameweek rows, so a
vintage can never be half recorded at one grain and whole at another. A schema-version-1 artifact
carries no fixture rows, so recording one leaves both tables empty for that run; that is a complete
vintage for its own schema version, not a partial one.

`ledger_outcome_player_fixture` -- a **separate** table at `(season, code, fixture)` grain,
carrying `attached_at`, `total_points_as_recorded`, and `points_under_rules_2026_27`. It is joined to
predictions only at read time and only after a fixture is final. The recorded FPL points and the
points replayed under this repository's scoring config are **separately named columns** and are
never conflated (R1).

## `run_id` derivation

`run_id = sha256` of a canonical JSON identity record that includes `artifact_sha256` -- the hash of
the whole manifest and every row -- plus the run's `as_of`, season, horizon, `commit_sha`,
`database_sha256`, `base_seed`, and `schema_version`. Because `artifact_sha256` is included, **any**
change to any field or row yields a different `run_id`, while byte-identical input yields the same
one. It never depends on wall-clock time, so re-generating an identical forecast and re-ingesting it
is recognised as the same run rather than duplicated. `created_at` is a ledger-side wall-clock stamp
and is deliberately **not** part of the identity.

## Append-only guarantees

- **No overwrite.** `record_forecast` refuses an existing `run_id` (`DuplicateRunError`); the module
  exposes no update or delete path for a recorded prediction. The CLI turns that refusal into an
  idempotent no-op (exit 0, nothing written) so a pipeline that runs twice neither fails nor
  duplicates a vintage.
- **New vintages, never mutations.** A later run for the same `(season, gw, code)` is a new `run_id`
  and new rows; the earlier vintage is untouched.
- **Fail closed.** The run row and every prediction row are written in one transaction; a mid-ingest
  error rolls the whole thing back and leaves the ledger unchanged. Outcome attachment is likewise
  transactional. The P1.3 domain boundary rejects a missing/false finalization flag, NULL points,
  or duplicate source player-fixture key before calling the ledger writer.
- **Outcome idempotency without mutation.** A re-run that presents the same finalized values for an
  existing `(season, code, fixture)` skips that row and reports an idempotent no-op. A newly
  finalized fixture appends normally. A re-presented key with either point measure changed raises an
  error instead of overwriting an actual, preserving the append-only guarantee.

## Knowledge time

`as_of` is taken verbatim from `ForecastArtifactManifest.as_of`, which the forecaster sets to the
real deadline instant. It is the most important column in the schema and is stored without
transformation. The artifact carries an explicit `as_of`, so nothing here is inferred or invented.

## Open gaps

- **Player-fixture grain — closed by P1.2.** `AGENTS.md` priority 9 wants **both** player-fixture
  and player-gameweek predictions retained, and both are now recorded. Artifact schema version 2
  transports the per-fixture distributions and the team-fixture primitives, and the ledger stores
  them in `ledger_prediction_player_fixture` and `ledger_prediction_team_fixture`. Nothing reaches
  around the artifact into the model: the rows are the same composed distributions the gameweek
  rows are convolved from, and that relation is re-checked on every serialise and read. Vintages
  recorded before P1.2 remain schema version 1 and legitimately have no fixture rows.
- **Outcome ingestion path — closed by P1.3.** `fpl.storage.outcomes` validates and selects
  finalized player-fixture outcomes from the marts; `fpl.jobs.attach_outcomes` is the thin CLI that
  attaches them. It preserves recorded and 2026/27-replayed points as distinct measures, rejects
  NULL/unfinalized/duplicate source rows, treats exact re-runs as no-ops, appends new fixture keys,
  and rejects changed values for an attached key. Two fixtures for one player in a double gameweek
  remain two rows because the grain includes `fixture`.
- **Read/BI layer — implemented development-only.** The atomic star-schema export consumes the
  ledger without querying around it. Dashboard schema v4 then derives exact cumulative player
  endpoints from the published player-gameweek PMFs: xP plus inclusive `P(<=2)` and
  `P(>=2/4/6/10/15)`. Cross-gameweek probabilities are convolved in the Python emitter under an
  explicit independence assumption; the browser selects published scalars and never computes a
  probability from the ledger primitives.
