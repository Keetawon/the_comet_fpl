# SDP primary operations

This runbook implements the [owner's architecture decision](sdp-primary-architecture-decision-2026-09-07.md).
It applies only to the V2 branch. Preserve research databases, payloads, results and claim records.
Use a persistent Python environment installed from this checkout and an explicit separate
operational DuckDB. Never point daily ingestion at the default/research database.

## Daily post-match capture

```powershell
python -m fpl.jobs.daily_pl_sdp --db D:/FPL/operational.duckdb --runs D:/FPL/runs --lookback-days 5 --workload
```

The existing locked/backed-up wrapper refreshes official FPL fixtures/registry/outcomes, fills
missing EPL stats, refreshes completed matches in the five-day lookback, stages the retained
versions, runs strict PIT/production-health checks, and captures supported competitive exposure.
Use `--player-history` when this cycle should also refresh every supported FPL element summary.
Individual capture is available as `python -m fpl.jobs.capture_pl_sdp --db ... --lookback-days 5`;
the lookback now implies refresh of already retained recent stats, not just missing rows.
`python -m fpl.jobs.capture_sdp_workload --db ... --lookback-days 5` captures workload separately
under the same writer lock. It never requests cup tactical statistics.

Register a daily local task using the existing script (current user must remain signed in):

```powershell
./scripts/register_daily_pl_sdp.ps1 -PythonPath D:/FPL/.venv/Scripts/python.exe -DatabasePath D:/FPL/operational.duckdb -RunRoot D:/FPL/runs -TaskName 'The Comet FPL - SDP primary V2' -At '07:00' -Workload
```

The task uses hidden `pythonw`, skips overlapping instances, retries twice at 30-minute intervals,
and runs missed schedules when available. Existing tasks are never overwritten. This local task
is not an always-on hosted scheduler; pre-deadline refresh closes the sleeping/offline-machine gap.
Do not change the repository default branch to enable Actions.

Ordinary provider corrections are accepted as new immutable versions. No research-style
multi-snapshot revision probe is required before production use. Capture receipt success and
source `known_at` are separate: an unchanged response does not advance its original source time.

The staged daily cycle also rechecks incomplete core statistics among each club's last five
completed PL matches, including required matches older than the ordinary lookback. The individual
collector exposes this as `--recheck-required-history`. This bounded recheck fetches provider
corrections; it neither fills missing fields nor drops an incomplete required match from selection.
Receipts retain both the actual request time and the retained source version/time, so a successful
unchanged response does not masquerade as newly known football evidence.

The remote service/timer package and exact installation, storage, restart and health instructions
are in [remote runtime](sdp-primary-remote-runtime.md). No remote host has been deployed:
**BLOCKED ONLY ON RUNTIME AUTHORIZATION / CREDENTIALS**. GitHub Pages is static hosting and cannot
run persistent ingestion. Do not substitute ephemeral Actions files for the operational database.

## Pre-prediction / pre-deadline

From a clean committed V2 checkout:

```powershell
python -m fpl.jobs.pre_deadline_forecast --db D:/FPL/operational.duckdb --runs D:/FPL/runs --gw-from 4 --gw-to 8 --output D:/FPL/predictions/unique-gw4-vintage.jsonl
```

This refreshes FPL including complete player history, refreshes recent SDP plus workload,
normalizes/checks health, and then sets the cutoff to actual post-refresh time unless `--as-of`
is explicitly supplied. A historical explicit cutoff cannot consume the new captures. The
existing FPL freshness/registry/schedule gates remain mandatory. `--skip-player-history` is an
explicit operational option only when already-retained official history satisfies those gates.

A failed SDP refresh produces `SDP_SOURCE_FALLBACK`; the incumbent still attempts a forecast.
Missing/invalid FPL prerequisites may independently stop both paths. The command does not mask
that failure or invent fixtures/players. If a shared database is locked by another writer, let
that writer finish before retrying; do not remove a live lock. No default DB is substituted.

A complete incumbent forecast is also written when SDP is enabled, including all-fallback runs, to
`unique-gw4-vintage.shadow-incumbent.jsonl`. Only the primary file is passed to the optimizer;
the primary manifest binds the shadow hash. Do not publish the shadow as the platform default.
The primary artifact must exist and pass its existing reader validation before optimizer use.
Both artifacts remain separate immutable prospective evaluation vintages.

The pre-deadline command preserves `forecast-source.duckdb` in its unique receipt directory before
prediction. Both primary and shadow read this same snapshot. Later captures and evidence-ledger
writes cannot change the replay input; retain this copy and the forecast's exact code commit.
`forecast.json` records actual start/completion, cutoff, refresh/forecast/evidence exit codes and
source/primary/shadow hashes. An explicit future cutoff is rejected before any refresh begins.
`refresh-report.json` binds every capture and failure receipt with its hash, including a failure
after the collector wrote its own receipt. Missing or malformed receipts force the source-failure
fallback. Failure to retain a stable source copy stops the build with a durable failure receipt.
SDP-enabled primary and shadow publication is atomic and refuses to overwrite an existing file,
including competing writers. Explicitly disabled forecasts retain their prior publication behavior.

After publication, the production command records both artifacts and their comparison binding in
the operational prediction ledger. The pair must pass exact source/population/component checks
and be recorded before every included official deadline. The recording timestamp comes from the
clock, never from the forecast cutoff. A recording failure leaves the artifacts and source copy
intact, returns nonzero, and must be resolved before treating the run as collected evidence.
See [prospective evidence](sdp-prospective-evidence.md) for retained grains and outcome attachment.
Direct `prospective_points_v1` runs remain useful for read-only replay; use the pre-deadline entry
point for automatically refreshed and recorded production comparisons.

For an already refreshed operational DB, the normal `prospective_points_v1` CLI defaults to the
explicit YAML primary selector. Pass `--refresh-report <cycle/report.json>` to bind a successful
receipt, or use the pre-deadline command so failures are handled automatically. Direct runs still
enforce source cutoff validity but do not assert that a network refresh just happened.

## Fallback, rollback and reports

`--football-environment disabled` on `prospective_points_v1` reproduces the incumbent path and
does not load SDP/configuration or produce a primary shadow. Alternatively, commit an explicit
`football_environment_primary: disabled` YAML change on V2. Do not alter player-component modes
or H shadow status as a side effect of rollback.

Each daily run has a unique directory containing backup, before/after inventories, logs,
staging audits and `report.json`. `healthy`/`consumer_ready` retain their transport/staging meaning;
`production_health` separately reports stricter core-field eligibility. A transport-complete
match can still fail the primary selector. Forecast CLI counts/report provenance are the
authoritative primary/fallback counts; zero requests or no proved evidence is NULL, not 100%
success or zero workload. A partial capture retains successful immutable raw records.

Archive reports, parameters, future-known rows and current live corrections must not be edited
to reduce fallback counts. Diagnose source health and capture completeness, and use the incumbent
until a valid version is actually available. Keep raw payload storage and the separate operational
DB backups long enough to reconstruct every published prospective vintage.

The [September 8 operational verification](sdp-fallback-and-operations-hardening-2026-09-08.md)
records the real 31m 36.9s full build, immutable paired evidence and unchanged 21/29 fixture split.
Use `sdp_capture_health` for capture status, `audit_sdp_fallbacks` for a saved vintage's exact
attribution, and `report_sdp_evidence` for its retained primary/shadow rows. The full `--grain all`
export can take several minutes on the current Windows database; the default team report is
the smaller operational view.

After official finality and a complete player-history refresh, append outcomes using the existing
job, with capture/forecast writers stopped and the explicit operational DB:

```powershell
python -m fpl.jobs.attach_outcomes --db D:/FPL/operational.duckdb --season 2026-27 --as-of <actual-UTC-time>
```

This job appends finalized player/team outcomes separately, keeps identical repeats idempotent,
and rejects changed repeats. It never replaces a prediction. Player-gameweek scoring also requires
official gameweek finality and every predicted fixture leg. Missing outcomes remain unavailable.

## Descriptive Dashboard xG supplements

The existing `export_sdp_stats` / Dashboard build now emits schema 6. Where historical
SDP xG is missing, explicitly marked FPL archive player sums may supplement the
display after source, identity, exposure and completeness checks. No new CLI/config
is required. Raw SDP, provider core validity and prediction selection are unchanged.
See [the source contract and verified coverage](sdp-fpl-xg-display-supplement-2026-09-11.md)
for capture-time semantics, remaining gaps, CSV provenance and publication commands.
