# SDP primary operations

This runbook implements the [owner's architecture decision](sdp-primary-architecture-decision-2026-09-07.md).
It applies only to the V2 branch. Preserve research databases, payloads, results and claim records.
Use a persistent Python environment installed from this checkout and an explicit separate
operational DuckDB. Never point daily ingestion at the default/research database.

### Owner-machine entry point (2026-09-16)

Open `D:/Personal/workspace/the_comet_fpl/.worktrees/v2/THE-COMET.code-workspace`.
From that checkout run `./scripts/comet.ps1 refresh`, `./scripts/comet.ps1 status`,
or `./scripts/comet.ps1 start`. These wrap the existing commands with the operational
database, receipt, forecast, plan and public-export paths. `start` selects the latest
registered primary by hash. It refuses an occupied port belonging to another
checkout/vintage instead of stopping it. Logs are in `D:/Personal/fpl-operations/services`.

The primary and legacy SDP tasks now use the `v2` entry path; the primary dashboard
public path was updated too. Triggers, principals and settings were preserved.
The dated schedule record below describes its earlier update; use the
[workspace guide](workspace-organization-2026-09-16.md) for the latest path change
and rollback evidence. `v2` is a junction to the preserved physical `sdp_test`
checkout, not another copy. Do not delete its target.

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

### Current club form reconciliation (2026-09-15)

`build_sdp_dashboard` now derives club form from the same finalized/provisional
match logs it publishes for expanded histories. All team-form consumers share
that output, including Fixtures, Summary and Team Analytics. Its publication
gate rejects stale aggregates as well as missing observations. A successful
capture alone is not a complete dashboard refresh: run the existing export,
validation and preview/build steps together, then reload the browser to replace
its session data cache. Never regenerate a forecast merely to update form.

Form windows stay within the selected forecast's season and show actual match
counts; the separately labelled expanded-history scope can cross seasons. See
[the root cause, verified repair and current totals](current-team-form-repair-2026-09-15.md).

### All-competition calendar (2026-09-15)

The same `build_sdp_dashboard` command now also writes
`public/sdp/competitive_schedule.json`; preview installation copies it along with
the existing public exports. The input is the already-retained competitive
match catalogue from `capture_sdp_workload`, including future listed matches.
No separate scheduler, fixture model or workload inference is introduced.
Use **Fixture matrix → All competitions** to inspect Weekend/GW and Midweek
columns, DGWs/BGWs, exact source coverage and dates. Missing cup catalogues stay
unavailable, and empty future draws stay not-yet-listed. See the
[calendar contract and publication instructions](competitive-fixture-calendar-2026-09-15.md).

Observation refreshes reconcile current FPL fixture rows against the published
forecast player population using exact `(season, code)` identities. Players added
to FPL after the retained forecast stay in the descriptive statistics sidecar;
the build receipt lists their source-only fixture identities separately. They do
not receive invented forecasts, and their absence from forecast-owned Players
does not block refreshing everyone else's observations. Missing observations for
any published current-season forecast player still stop publication. This also
keeps an observed-data refresh independent of forecast regeneration.

The existing `export_sdp_stats` / Dashboard build now emits schema 6. Where historical
SDP xG is missing, explicitly marked FPL archive player sums may supplement the
display after source, identity, exposure and completeness checks. No new CLI/config
is required. Raw SDP, provider core validity and prediction selection are unchanged.
See [the source contract and verified coverage](sdp-fpl-xg-display-supplement-2026-09-11.md)
for capture-time semantics, remaining gaps, CSV provenance and publication commands.

### Complete current-plan and monitoring refresh (2026-09-15)

Use the single existing-host flow instead of capture alone:

```powershell
& D:/Personal/fpl-operations/.venv/Scripts/python.exe -m fpl.jobs.refresh_dashboard `
  --db D:/Personal/fpl-operations/data/sdp-primary-v2.duckdb `
  --runs D:/Personal/fpl-operations/dashboard-runs `
  --forecast-dir D:/Personal/fpl-operations/predictions `
  --preview-public dashboard/public `
  --plan-store D:/Personal/fpl-operations/dashboard-plans
```

Run in the V2 checkout with its existing Node dependencies. This calls the bounded
FPL/SDP/workload capture **with full player history**, attaches final outcomes under
the existing lock and new backup, selects the latest **registered primary by hash**,
reuses or creates its unchanged optimizer plan, rebuilds all read models, validates
and installs public assets, and runs the dashboard build. It never invokes player
inference or replaces a forecast. `--skip-capture` uses retained source timestamps;
`--optimizer-plan PATH` can seed an already verified platform plan without a solve.

The public contract still carries one plan per platform role. Newest plans are
selected consistently across suggestion, summary and optimizer audit. A diagnostic
from another cutoff/horizon stays labelled with its original range and cannot be
used in the default-vs-diagnostic comparison. Original artifacts and prior export
generations remain immutable.

The daily attachment path skips only live fixtures explicitly marked
`finished=false`. The attachment API's strict default remains unchanged. Missing
identity, unknown finality, missing components and conflicting finalized outcomes
still fail. Player scores require the **entire official GW and every DGW leg**.
Fully played but not-yet-final GWs remain pending.

`public/sdp/publication_status.json` is an independently versioned receipt bound
to the public manifest hash. It separates source freshness, ended-but-unfinalized
GWs, latest scored GWs, forecast horizon and plan presence. A rollover warning
appears when the first GW with remaining fixtures differs from the registered
forecast start. Use the existing `pre_deadline_forecast` job with a **new** output
path when a new forecast vintage is due, then this same refresh command. Never
regenerate a forecast just to attach outcomes.

Each unique `dashboard-runs/dashboard-*` retains a receipt, backup and build/optimizer
logs; reusable plan artifacts live in `dashboard-plans`. Do not remove locks/WALs
to force a run. Capture or validation failures are explicit and do not relabel old
source evidence. Windows symlink failures remain accurately reported; validated
copies use the established publication fallback.

For new task registrations, `register_daily_pl_sdp.ps1` accepts `-DashboardPublic`,
`-ForecastDirectory` and `-PlanStore` together. It still refuses to overwrite an
existing task. Update an existing action explicitly, keeping its trigger/principal
and retry settings. The owner machine must be running. No cloud runtime is added.

Reload the browser after a refresh to replace its session cache. Vite preview
serves rebuilt `dashboard/dist`; changing DuckDB or public JSON alone is not enough.
Production publication remains a separate review.

### Owner machine: every four hours and at sign-in (2026-09-16)

The owner authorized changing the timing of the existing
`The Comet FPL - SDP primary V2` task. It is enabled and Ready, with:

- An indefinite four-hour trigger anchored at 2026-09-16 11:00 Asia/Bangkok:
  **03:00, 07:00, 11:00, 15:00, 19:00, 23:00** local time.
- An owner-only Windows sign-in trigger delayed by two minutes for startup/network
  initialization. This runs after signing in, not before sign-in at unattended boot.
  Locking the screen while remaining signed in does not disable the task.
- The unchanged `refresh_dashboard` action and explicit operational paths above:
  FPL/SDP/workload capture, normalization, final outcomes, dashboard exports/build.
  New forecasts remain a separate pre-deadline operation.
- Existing `StartWhenAvailable`, `IgnoreNew`, two retries spaced 30 minutes apart,
  two-hour execution limit, battery support and database locks/backups retained.
  It does not wake a sleeping PC. Missed schedules are eligible for catch-up when
  Windows can run the task; offline/network failures retain the existing retry policy.

Only the two triggers changed: action, principal, settings and registration
metadata were compared against the exported XML and remained identical. Windows
normalized the trigger's account SID into an account name; resolving that name
back to its SID verified the same owner. The other `daily SDP` task, which uses a
different database, was unchanged. No additional task, credentials or service
account were created.

Configuration was verified at 2026-09-16T03:47:38Z through both ScheduledTasks and
the native Task Scheduler interface. Next firing: 11:00 Bangkok. The preceding
scheduled run's result is 0; a future automatic four-hour/sign-in firing has not
yet been observed. No extra full capture was launched just to test registration.

Exact before/after XML and verification receipts are retained locally in
`data/artifacts/scheduler-four-hour-20260916T034531Z/`. `before.xml` is the rollback
definition; preserve it. To inspect timing and the last completion:

```powershell
$name = 'The Comet FPL - SDP primary V2'
Get-ScheduledTask -TaskName $name | Select-Object TaskName, State, Triggers
Get-ScheduledTaskInfo -TaskName $name |
  Select-Object LastRunTime, LastTaskResult, NextRunTime
```

To restore the previous schedule, first check that the task is not running and
that its action has not changed since this backup, then restore that exact XML:

```powershell
$backup = 'data/artifacts/scheduler-four-hour-20260916T034531Z/before.xml'
Register-ScheduledTask -TaskName 'The Comet FPL - SDP primary V2' `
  -Xml ([IO.File]::ReadAllText((Resolve-Path -LiteralPath $backup).Path)) -Force
```

The registration helper still defaults to a daily schedule for **new** tasks;
rerunning it is neither required nor allowed to overwrite this existing task.
This schedule change does not modify pipeline/model code or frozen evidence.

### Two-hour update and current availability (2026-09-17)

The owner changed the existing four-hour task to **every two hours** on September
17. It retains the odd-hour anchor (01:00, 03:00, ... 23:00 Bangkok) and two-minute
sign-in trigger. Action, account, retry/lock/backup behavior and settings are
unchanged. Exact verification and rollback XML are documented in
`current-player-availability-2026-09-17.md`. This supersedes the four-hour timing
above; it does not imply automatic public publication or run while the PC is off.

Current FPL availability is a separate reporting overlay. Original forecast
status and all predictions stay immutable. A fresh observed-data export must not
be represented as proof that forecast-time injury information is current.

### Goal-origin display refresh (2026-09-17)

The existing dashboard exporter now reaccounts new or revised current-season
goal-pattern sources on each refresh, retaining source-bound manual audits where
their raw hash still matches. Unknown origins are displayed as Unclassified;
they never default to open play. This does not change capture windows, provider
core validity, selection policy or forecasts. See
`sdp-goal-pattern-refresh-2026-09-17.md` for source reconciliation and verification.
Local refresh/build and public release publication remain separate operations.
