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

On SDP-primary fixtures, a complete incumbent forecast is also written to
`unique-gw4-vintage.shadow-incumbent.jsonl`. Only the primary file is passed to the optimizer;
the primary manifest binds the shadow hash. Do not publish the shadow as the platform default.
The primary artifact must exist and pass its existing reader validation before optimizer use.
Both artifacts remain separate immutable prospective evaluation vintages.

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
