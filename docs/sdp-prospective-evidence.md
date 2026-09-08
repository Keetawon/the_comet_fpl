# SDP prospective-evidence pair registry

**Status: development-only operational hardening under the owner-directed SDP architectural
adoption (2026-09-07). Frozen historical experimental verdicts are unchanged and nothing here
awaits a scientific promotion verdict.**

The SDP-backed V2 prospective default (`jobs/prospective_points_v1.py`) publishes a **primary**
artifact (SDP football environment active) and an **incumbent shadow** artifact with the
environment disabled (`forecast_role = "shadow_incumbent"`). This module binds those two
artifacts as ONE pre-deadline comparison pair and — when the ledger does not yet hold the
vintages — inserts both, atomically, in the SAME transaction as the pair row. The parent
`pre_deadline_forecast` flow calls the CLI automatically after immutable artifacts publish; it
preserves an exact forecast-source database copy beforehand so ledger mutations can never break
replay.

Strictly additive; every failure is a refusal, never a repair. Outcome attachment stays with the
existing authoritative jobs; no frozen result, config, model, or player default is touched.

## Files

| File | Role |
| --- | --- |
| `src/fpl/storage/sdp_evidence.py` | Domain: additive table, atomic vintage+pair ingest, fail-closed verification, read projections |
| `src/fpl/jobs/record_sdp_evidence.py` | CLI: two artifact paths + explicit `--db`; inserts vintages and pair in one transaction |
| `src/fpl/jobs/report_sdp_evidence.py` | Read-only report projection (team / player-gameweek / player-fixture grains) |
| `tests/test_sdp_evidence.py` | Offline behavioural tests of every refusal and the happy path |

## What gets recorded

One row per pair in `ledger_sdp_evidence_pair` (created idempotently by
`ensure_sdp_evidence_schema`; `schema.sql` unchanged):

* `prediction_id` — deterministic SHA-256 over `(schema, primary_run_id, shadow_run_id, season,
  gw_from, gw_to, as_of)`.
* `season`, `gw_from`, `gw_to`, `as_of`, `primary_run_id` / `primary_artifact_sha256`,
  `shadow_run_id` / `shadow_artifact_sha256` — the run ids are derived exactly as
  `ledger.derive_run_id` derives them, from the canonical artifact bytes, so the bound hashes
  ARE the ledger's own identity for each vintage.
* `created_at` — the ACTUAL record entry instant (`datetime.now(UTC)`; there is no
  caller-supplied stamp). New ledger vintages inserted by the same call carry the same stamp.
* `deadline_evidence` — which capture witnessed the deadlines, its payload hash, and the official
  deadline used for every included gameweek.
* `source_provenance` — both sides' full provenance surface: bootstrap capture identity, FPL
  knowledge time, schedule captures, registry hash, contract identities, component modes.
* `verification` — what was checked and what was found (manifest parity, membership counts,
  stored populations, kickoff counts, roles, hash binding, SDP provenance validation counters).

A pair can never be half-recorded: both vintages and the pair row commit or roll back together
(`ledger._insert_run` / `ledger._insert_predictions` are reused inside the pair transaction, and
schemas are ensured before it). A failure leaves zero partial new predictions.

## Pre-deadline rule (no backdating)

`record_pair` always stamps the pair with the actual current time. Tests monkeypatch the module
clock (`sdp_evidence._now`); production code never accepts an arbitrary caller-supplied past
stamp. At that instant, ALL of the following must hold:

1. `created_at <= the official deadline` of every gameweek in `[gw_from, gw_to]`; an expired
   deadline is a refusal, so an old output can never be passed off as a prior commitment.
2. Every predicted kickoff is strictly future.
3. `as_of <= created_at` — no future cutoff.
4. Deadlines are witnessed from the EXACT cutoff-known bootstrap the runs consumed (the
   `snapshot_payload` row matching the runs' `bootstrap_capture_id`), with the retained raw bytes
   re-hashed against the stored sha256 AND the runs' declared bootstrap hash; event identities
   must be unique and every included gameweek needs a deadline. Deadlines are never inferred from
   kickoffs, and a bootstrap captured after the record entry instant cannot witness anything.
5. Every forecast run must already exist at the record entry instant (for pre-existing vintages,
   the stored `created_at` may not be later than the pair stamp).
6. Both runs must have been produced from a clean worktree (ledger `worktree_clean` flag).

An already-recorded pair is an idempotent no-op checked BEFORE any deadline logic, so an
identical repeat still returns the same id and keeps the original `created_at` even after the
deadline has passed. A repeat with different binding values raises `PairConflictError`.

## Pairing verification (fail closed)

Both artifacts are validated as canonical serialisations first: the presented file bytes must
hash to exactly the canonical `artifact_bytes` serialisation, or the record is refused
(`ArtifactNotCanonicalError`).

The two sides must then agree on everything except the football environment and forecast role:

* **Manifest parity** — `artifact_schema`, `schema_version`, `status`, `as_of`, season, `gw_from`,
  `gw_to`, `commit_sha`, `database_sha256`, `base_seed`, `monte_carlo_draws`,
  `fixture_points_support_max`, roster/fixture counts, the FULL contract identity set, and the
  FULL `live_inputs` (bootstrap capture id, known_at, payload hash, schedule capture ids, and the
  selectable-player registry hash) must be identical.
* **Exact membership** — the `(season, gw, code)` player-gameweek rows must match pairwise
  including position, club identity, and the exact `fixture_ids` list (so blank gameweeks and
  double-gameweek legs are pinned); every player-fixture row must match on gameweek, kickoff,
  position, club/opponent identity, and venue; every team-fixture row likewise. Same counts with
  different codes, fixtures, legs, or components are refused.
* **Component modes** — only `football_environment.provenance`,
  `football_environment.primary`, and `forecast_role` may differ; every other mode (all player
  component models) must be identical.
* **Population recount** — after the vintage inserts, stored row counts must equal the manifests'
  declared counts at both grains.

## Mandatory SDP provenance and source validation

* The primary MUST carry `football_environment.provenance` declaring
  `primary = "sdp_v2"` and `fallback = "trailing_goals_attack_defence"`, plus a well-formed
  frozen model sha256 whose `model_known_at` precedes the cutoff.
* The primary MUST bind `shadow_incumbent_artifact_sha256`, and it MUST equal the shadow's
  canonical artifact hash (required, never optional).
* Every consumed `source_versions` entry must resolve to a retained `raw_pl_sdp_payload` row
  with the declared sha256, whose receipt `fetched_at` equals the declared consumed `known_at`
  and precedes the cutoff; a declared match-metadata receipt is validated the same way. A later
  operational refresh receipt time is NEVER accepted as a consumed source time. The generic
  knowledge-time/hash scan explicitly skips the `refresh` receipt subtree for exactly that
  reason.
* The shadow MUST declare `forecast_role = "shadow_incumbent"` and MUST NOT carry any SDP
  primary provenance or environment-primary claim.

## Read/report projection

`fpl.storage.sdp_evidence` exposes `load_pair`, `list_pairs`, `pair_team_fixture_rows`,
`pair_player_fixture_rows`, and `pair_player_gameweek_rows`. The report job
(`python -m fpl.jobs.report_sdp_evidence`) opens the database read-only (`--db` required and
explicit) and emits, at `--grain team|player-gameweek|player-fixture|all` (default `team`):

* the pair binding with provenance and verification payloads;
* an explicit **standing** block naming the owner-directed architectural adoption and that frozen
  experimental verdicts are unchanged;
* an **operations** block with the selector rate/reason counts, fallback configuration, model
  identity, latest SDP knowledge time, consumed-source validation counts, and per-role outcome
  attachment counts over the included grains;
* team rows (run x club x fixture: identity, kickoff, stored `lambda_for` / `lambda_against` /
  clean-sheet probability / full goals-for PMF, per-fixture selector, artifact hash, and the
  separately attached official signed score);
* player-gameweek rows (stored convolved distribution, fixture legs, and an outcome that is
  attached — with summed signed actuals — only when EVERY leg's finalized outcome is attached; a
  partial double gameweek is never scored) — the grain for within-gameweek Spearman and signed
  error metrics;
* player-fixture rows (stored per-leg PMF and its separately attached signed actuals,
  `total_points_as_recorded` and `points_under_rules_2026_27` never conflated).

Absent outcomes remain NULL; they are never zero-filled. Report file writes use atomic
temp-file replacement.

## Using the retained rows for metrics — candid CLI limitations

The retained rows are at the exact grains those metrics consume:

* **Team:** `goals_for_distribution` beside the official signed score ⇒ Goal NLL, clean-sheet
  Brier, CRPS, PIT/reliability calibration per run role.
* **Player (gameweek grain):** the convolved full-points PMF beside the summed finalized leg
  actuals ⇒ player NLL, CRPS, signed MAE, within-gameweek Spearman of expected points, and
  `P(points <= 2)` / `P(points >= 5)` / `P(points >= 10)` calibration (a Python-side PMF sum,
  never a browser calculation).
* **Player (fixture grain):** per-leg PMFs beside per-leg signed actuals.

What this delivery does **not** do:

1. **No metric is computed by the report CLI**; the metric implementations remain the existing
   validate-layer scoring APIs and are not re-plumbed here.
2. **Unfinalized or partial-gameweek evidence is never scorable**: `outcome.attached = false`
   rows must be excluded by any consumer; the existing attachment jobs remain the only finality
   authority.
3. **Per-fixture SDP source knowledge times** are run-grain only (`source_versions` deduplicated
   by the environment); the per-fixture selector is exposed, the exact source version per fixture
   is not re-derived.
4. **No new thresholds, gates, or model fitting** exist here, and nothing re-runs, re-judges, or
   reinterprets any frozen result.

## CLI

```bash
# Parent, after both immutable artifacts publish; this job OWNS the writer lock:
python -m fpl.jobs.record_sdp_evidence \
    --primary D:/FPL/predictions/gw4.jsonl \
    --shadow  D:/FPL/predictions/gw4.shadow-incumbent.jsonl \
    --db      D:/FPL/operational.duckdb     # explicit EXISTING operational database
```

The CLI takes `daily_pl_sdp.writer_lock` on the explicit database (failing closed on
overlap, stale locks, or unresolved WALs), refuses a database that does not already
exist (no schema-only fallback, no default path), and calls `record_pair` on the yielded
write connection. Schema initialization happens inside `record_pair` before its
transaction.

```bash
# Read-only reporting:
python -m fpl.jobs.report_sdp_evidence \
    --prediction-id <id> --db D:/FPL/operational.duckdb \
    [--grain team|player-gameweek|player-fixture|all] [--output report.json]
```

Exit codes: `0` recorded (or identical repeat: same id, original stamp kept); `1` refused
(reason on stderr, nothing written — including zero partial ledger vintages).

## Second-audit refinements (2026-09-08)

* **Adopted team-environment CS mode pair.** `component.team_clean_sheet` may differ
  between the sides ONLY as the exact adopted pair — primary
  `sdp_v2_with_incumbent_fallback`, shadow `trailing_goals_attack_defence`. Every player
  component mode must still be identical.
* **Normalized consumed-source knowledge times — normative reader only.** Every declared
  `source_versions` entry MUST exactly equal one FULL canonical `SdpStateRow.provenance`
  emitted by `sdp_runtime.load_sdp_state(con, cutoff=as_of, season=...)` — the strict
  reader that revalidates raw bytes, statuses, identity, metadata, and core fields, and
  whose reported `known_at` is already the normalized maximum of the stats fetch time,
  the FPL metadata known time, and the selected SDP match-metadata receipt time (so a
  metadata-delayed capture is legitimately accepted). There is NO empty-reader exception:
  declared sources with a reader that yields zero rows are a refusal, as are key
  mismatches (unwitnessed payload), shape mismatches (missing/extra canonical fields),
  and any field disagreement. Because the reader is cutoff-selected by construction, an
  exact match also proves every consumed time preceded the cutoff. Declaring no sources
  (an all-fallback forecast) requires no witnessing.
* **Bootstrap knowledge time.** The witness additionally requires the retained capture
  time to EQUAL the manifests' declared `bootstrap_known_at` and that knowledge time to
  precede the forecast cutoff.
* **Missing-model all-fallback pairs.** Absent frozen-model provenance (`model_sha256` /
  `model_known_at` null, absence preserved) is acceptable ONLY when every fixture
  selector decision is an explicit fallback; `SDP_PRIMARY` selectors always require a
  valid frozen model and non-empty validated source versions.
* **Selector decision coverage.** The provenance must carry exactly one selector decision
  per predicted fixture, and each decision's season, gameweek, and home/away club codes
  must match the artifact's actual fixture rows.
* **Official gameweek finality in the player-gameweek report grain.** A player-gameweek
  outcome is available only when the gameweek is officially final per the established
  authority (every fixture of the gameweek `finished IS TRUE`, over `stg_fixture` or the
  latest live fixture versions — the `dim_gameweek` rule) AND every leg's finalized
  outcome is attached. With no finality witness the outcome remains unavailable; it is
  never zero-filled or partially scored.
