# Prediction Ledger Specification

Status: Implemented. The append-only prediction ledger in DuckDB stores prospective forecast
vintages emitted by `fpl.artifacts.prospective_points`.

## Purpose and Motivation

Every historical model evaluation in this repository carries the "development-only" caveat
because historical evaluations rely on unversioned, outcome-derived proxies for player rosters
and knowledge-time cutoffs. This caveat cannot be resolved retroactively with historical data.

The prediction ledger provides the single infrastructure mechanism to establish a provable,
pre-deadline record. By recording predictions into an immutable, append-only ledger before
match kickoffs (e.g. before the 2026/27 GW1 deadline at `2026-08-21T17:30:00Z`), the exact
knowledge time (`as_of`), input snapshot IDs, model contract identities, and full points
distributions are permanently pinned. A prediction reconstructed later from a snapshot is
structurally weaker evidence than a forecast recorded prior to the deadline.

---

## Schema Architecture

All prediction ledger tables in DuckDB use the `ledger_` prefix.

### 1. `ledger_forecast_run`

Stores global manifest metadata, provenance, input hashes, and execution configuration for each
recorded forecast run.

| Column | Type | Description |
|---|---|---|
| `run_id` | `VARCHAR PRIMARY KEY` | Stable, deterministic SHA-256 hash of manifest identity properties |
| `created_at` | `TIMESTAMPTZ NOT NULL` | Instant when the run was recorded into the ledger |
| `as_of` | `TIMESTAMPTZ NOT NULL` | Knowledge cutoff instant (point-in-time boundary) |
| `season` | `VARCHAR NOT NULL` | Target season (e.g. `'2026-27'`) |
| `gw_from` | `INTEGER NOT NULL` | Starting gameweek of the forecast horizon |
| `gw_to` | `INTEGER NOT NULL` | Ending gameweek of the forecast horizon |
| `commit_sha` | `VARCHAR NOT NULL` | Git commit SHA of the code emitting the forecast |
| `database_sha256` | `VARCHAR NOT NULL` | SHA-256 digest of the DuckDB database used |
| `artifact_sha256` | `VARCHAR NOT NULL` | SHA-256 digest of the ingested `.jsonl` artifact file |
| `base_seed` | `BIGINT NOT NULL` | Base seed used for Monte-Carlo simulation |
| `monte_carlo_draws` | `INTEGER NOT NULL` | Number of Monte-Carlo draws per fixture |
| `fixture_points_support_max` | `INTEGER NOT NULL` | Maximum points support bound |
| `row_count` | `INTEGER NOT NULL` | Total forecast rows in the artifact |
| `roster_size` | `INTEGER NOT NULL` | Number of stable player `code` identities in the roster |
| `fixture_count` | `INTEGER NOT NULL` | Number of scheduled fixtures in the horizon |
| `contract_identities` | `JSON NOT NULL` | Serialized map of component contract names, versions, and hashes |
| `bootstrap_capture_id` | `VARCHAR NOT NULL` | Live API bootstrap snapshot ID |
| `bootstrap_payload_sha256` | `VARCHAR NOT NULL` | SHA-256 digest of the bootstrap static payload |
| `schedule_capture_ids` | `JSON NOT NULL` | Array of live fixture schedule snapshot IDs |

---

### 2. `ledger_prediction_player_gameweek`

Stores player-gameweek forecasts and full points probability distributions for every run.

- **Primary Key**: `(run_id, season, gw, code)`
- **Foreign Key**: `run_id` references `ledger_forecast_run(run_id)`

| Column | Type | Description |
|---|---|---|
| `run_id` | `VARCHAR NOT NULL` | Parent forecast run ID |
| `season` | `VARCHAR NOT NULL` | Target season |
| `gw` | `INTEGER NOT NULL` | Target gameweek |
| `code` | `INTEGER NOT NULL` | Permanent player identity (`code`) |
| `web_name` | `VARCHAR` | Player display name (nullable) |
| `position` | `VARCHAR NOT NULL` | Position (`'GK'`, `'DEF'`, `'MID'`, `'FWD'`) |
| `team_id` | `INTEGER NOT NULL` | Season-scoped team ID |
| `team_code` | `INTEGER` | Permanent cross-season team code (nullable) |
| `now_cost` | `INTEGER` | Cost in tenths of £M (nullable) |
| `selected_by_percent` | `DOUBLE` | Ownership percentage (nullable) |
| `availability_status` | `VARCHAR NOT NULL` | FPL availability status code |
| `chance_of_playing` | `DOUBLE` | Reported chance of playing next round (nullable) |
| `availability_multiplier` | `DOUBLE NOT NULL` | Multiplier applied to expected points overlay |
| `fixture_ids` | `JSON NOT NULL` | Array of scheduled fixture IDs in this gameweek |
| `kickoff_times` | `JSON NOT NULL` | Array of kickoff ISO timestamps matching `fixture_ids` |
| `expected_points` | `DOUBLE NOT NULL` | Raw expected points before availability adjustment |
| `availability_adjusted_expected_points` | `DOUBLE NOT NULL` | Expected points after availability multiplier |
| `expected_bonus` | `DOUBLE NOT NULL` | Expected bonus points component |
| `distribution` | `DOUBLE[] NOT NULL` | Full discrete probability distribution array |
| `cold_start_player` | `BOOLEAN NOT NULL` | Flag: player has no prior history |
| `stage_a_league_average_team` | `BOOLEAN NOT NULL` | Flag: team uses league-average fallbacks |
| `attacking_signal_cold_start` | `BOOLEAN NOT NULL` | Flag: attacking signal is cold-started |
| `assist_signal_cold_start` | `BOOLEAN NOT NULL` | Flag: assist signal is cold-started |
| `transferred_no_rescale` | `BOOLEAN NOT NULL` | Flag: transferred player without rescale |

---

### 3. `ledger_outcome_player_fixture`

Stores actual match outcomes attached after fixtures finalize.

- **Primary Key**: `(season, code, fixture)`

| Column | Type | Description |
|---|---|---|
| `season` | `VARCHAR NOT NULL` | Season identifier |
| `code` | `INTEGER NOT NULL` | Permanent player identity |
| `fixture` | `INTEGER NOT NULL` | Fixture ID |
| `attached_at` | `TIMESTAMPTZ NOT NULL` | Instant actuals were attached to the ledger |
| `total_points_as_recorded` | `INTEGER` | Contemporaneous rules recorded total points |
| `points_under_rules_2026_27` | `INTEGER` | Points replayed under 2026/27 rules contract |

> **Crucial Rule**: Actual outcomes are **never merged or updated into prediction rows**. The
> outcome table is joined to prediction vintages at read/evaluation time. `total_points_as_recorded`
> and `points_under_rules_2026_27` are strictly separately named to prevent cross-ruleset target
> contamination (violating R1).

---

## Deterministic `run_id` Derivation

`run_id` is derived deterministically by computing a SHA-256 hash over the canonical JSON representation of the manifest's identity fields:

- `as_of` (ISO string)
- `season`, `gw_from`, `gw_to`
- `commit_sha`, `database_sha256`
- `base_seed`, `monte_carlo_draws`, `fixture_points_support_max`
- `row_count`, `roster_size`, `fixture_count`
- `freshness_cold_start`, `worktree_clean`
- `contracts` (sorted contract names, versions, and SHA-256 hashes)
- `component_modes` (sorted key-value pairs)
- `bootstrap_capture_id`, `bootstrap_payload_sha256`, `schedule_capture_ids` (sorted tuple)

Re-ingesting an identical artifact produces the exact same `run_id`. Modifying any input parameter (such as `base_seed` or `as_of`) produces a distinct `run_id`.

---

## Append-Only Guarantees

1. **No UPDATE or DELETE API**: The storage module (`fpl.storage.ledger`) exposes no UPDATE or DELETE path for prediction rows or forecast runs.
2. **Duplicate Run Refusal**: Re-ingesting an existing `run_id` raises `DuplicateRunError` and aborts without modifying database state. This prevents silent duplicate writes or unintended overwrites.
3. **Multi-Vintage Retention**: A later forecast run for the same `(season, gw, code)` produces a new `run_id`. Both vintages are retained side-by-side in `ledger_prediction_player_gameweek` under their respective `run_id` keys, allowing complete historical auditability of forecast updates over time.
4. **Transaction Atomicity**: Ingest operates inside a single DuckDB transaction (`BEGIN TRANSACTION` / `COMMIT`). Any failure mid-ingest triggers a `ROLLBACK`, leaving the ledger unaffected.

---

## Open Items and Gaps

1. **`as_of` Knowledge Time Boundary**:
   - `as_of` is sourced directly from `ForecastArtifactManifest.as_of` (UTC timestamp). The ledger records it verbatim into `ledger_forecast_run.as_of`.

2. **Player-Fixture Grain vs Player-Gameweek Artifact**:
   - Repository correctness rule 9 requires retaining both player-fixture and player-gameweek predictions.
   - The prospective artifact contract (`ForecastArtifactRow`) emits predictions at player-gameweek grain `(season, gw, code)` with convolved double-gameweek distributions, while embedding `fixture_ids` and `kickoff_times`.
   - The ledger records the player-gameweek grain faithfully and preserves fixture linkage. Reconstructing un-convolved per-fixture probability distributions from the artifact remains an open item until an explicit player-fixture transport contract is added upstream.
