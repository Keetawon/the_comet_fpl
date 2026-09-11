# Frozen GW4–8 checkpoint and observed SDP dashboard operations

Current publication repair: see
[SDP data reconciliation](sdp-dashboard-data-reconciliation-2026-09-08.md).
`build_sdp_dashboard --base-dashboard` now retains only the existing plan blocks;
the operational generation supplies refreshed actuals and stored forecast exports.
It refuses to install a preview if current FPL fixture/player rows are absent from
the established actual/provisional exports. It no longer packages the entire stale
base. Missing SDP fields remain NULL; provider core validity is independent of
the descriptive per-field display. The existing command below remains applicable.

The player model remains frozen at `17cfa2267ce4d7c89f96842220f40471b81152d2`.
The GW1–3 V2 audit remains MIXED / NO FREEZE; V1 remains invalid. No inference,
parameter change, new model research or historical audit rerun is part of this work.

The fixed-origin cohort is selected in
[the dated addendum](sdp-gw4-8-checkpoint-addendum-2026-09-08.md) and
`config/sdp_gw4_8_checkpoint.yaml`, committed as
`116db25e1d3046a6b6369c736f01d4bc657e5157` before the refresh and checkpoint scoring.
It retains the original 03:53:18 UTC registration, rather than backdating this rule.
Rolling vintages require separate one-GW contracts and reports. They cannot replace
or be pooled with this fixed-origin comparison.

## Existing-host commands

Use the V2 worktree and explicit operational database. These commands neither build
the research database nor regenerate a forecast. Unique output paths preserve older
receipts. Run them sequentially; do not overlap a scheduled writer.

```powershell
Set-Location D:/Personal/workspace/the_comet_fpl/.worktrees/sdp_test
$python = 'D:/Personal/fpl-operations/.venv/Scripts/python.exe'
$db = 'D:/Personal/fpl-operations/data/sdp-primary-v2.duckdb'
$stamp = [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$checkpoint = "D:/Personal/fpl-operations/verification/checkpoint-$stamp"
New-Item -ItemType Directory -Path $checkpoint | Out-Null

# Existing bounded capture procedure: actual timestamps, immutable raw versions.
& $python -m fpl.jobs.daily_pl_sdp --db $db `
  --runs D:/Personal/fpl-operations/sdp-primary-runs `
  --lookback-days 5 --workload --player-history
if ($LASTEXITCODE -ne 0) { throw 'Inspect retained capture receipt before continuing' }

& $python -m fpl.jobs.sdp_capture_health --db $db `
  --runs D:/Personal/fpl-operations/sdp-primary-runs --max-success-age-hours 30

# Existing authoritative finality/attachment under existing writer lock and backup.
& $python -m fpl.jobs.score_sdp_checkpoint --db $db `
  --contract config/sdp_gw4_8_checkpoint.yaml `
  --attach-outcomes --backup "$checkpoint/before-outcomes.duckdb" `
  --output "$checkpoint/fixed-origin.json"
if ($LASTEXITCODE -ne 0) { throw 'Checkpoint refused; preserve its inputs and inspect the error' }

# Read-only deterministic repeat; does not reattach or regenerate predictions.
& $python -m fpl.jobs.score_sdp_checkpoint --db $db `
  --contract config/sdp_gw4_8_checkpoint.yaml `
  --output "$checkpoint/fixed-origin.json"

# Existing BI and dashboard publishers, public sanitizer, then observed SDP sidecar.
& $python -m fpl.jobs.build_sdp_dashboard --db $db `
  --output "$checkpoint/dashboard" --preview-public dashboard/public `
  --base-dashboard D:/Personal/workspace/the_comet_fpl/dashboard/public/data
if ($LASTEXITCODE -ne 0) { throw 'Dashboard generation refused' }
Push-Location dashboard
npm run build
npm run preview -- --host 127.0.0.1 --port 4173 --strictPort
Pop-Location
```

`daily_pl_sdp` owns its existing exclusive writer lock and pre-write backup.
The checkpoint's optional attachment step uses the same lock with a new backup,
validates the selected pair before mutation, and calls the unchanged authoritative
`attach_finalized_outcomes` with the actual current UTC time. It closes the writer
before read-only scoring. A conflicting finalized correction is refused; neither
this adapter nor a dashboard refresh overwrites the old outcome or prediction.
Do not remove a stale lock/WAL to force execution.

The already-installed `The Comet FPL - SDP primary V2` task uses the same operational
DB and runs daily at 07:00 Asia/Bangkok. Its existing command includes `--workload`,
but not the optional full `--player-history` stream. The explicit refresh above
captures that stream. The independent pre-deadline job remains callable through
the existing [operations runbook](sdp-primary-operations.md); use a new rolling
output path if a later pre-deadline forecast is requested. Do not overwrite the
fixed-origin GW4–8 artifacts. No new scheduler or remote runtime is installed.

## Report contract

`score_sdp_checkpoint` binds prediction ID, both artifact hashes, original emitter,
population, clean-forecast flag and scoring support before reading outcomes. It
uses existing stored gameweek PMFs and the existing metric primitives. Player
rows require official whole-GW finality plus every finalized DGW leg. Missing
outcomes remain NULL with exclusions; team rows use exact reciprocal identities.
Raw signed official points and replayed points stay distinct. Proper-score DGW
targets sum the individually coarsened fixture targets, preserving the stored
convolved support and `1e-12` log floor.

Reports include pooled/per-GW/position scores, selector slices, top-K and captain
diagnostics, PMF calibration and exact paired differences. Raw forecast decision
metrics are labelled separately from unavailable availability-adjusted metrics.
Component PMFs and forensic component attribution are NULL when old forecasts did
not retain sidecars; no inference is reconstructed. The minutes scoring-bin proxy
is not promoted into a physical expected-minutes diagnostic.

Uncertainty retains exhaustive paired GW-block resampling with multiplicity and
the existing quantile convention. It is computed only after all five selected
fixed-origin GW blocks have finalized scored evidence (`5^5 = 3,125` block draws).
Earlier and separately labelled rolling reports show NULL intervals, finalized
and scored GW counts, and the reason. Even five GWs remain a small temporal sample.
There is no new numerical promotion threshold. Before outcomes qualify the report
is **PENDING** with uncomputed metrics.

Canonical reports use the repaired integer-key JSON transport and existing atomic
write-once publication. Identical repeats are idempotent; changed source evidence
requires another report path. Forecast, contract, outcome/finality projections and
metric implementation hashes bind each version.

## Dashboard and publication

The existing app now has **Team stat from SDP** (`#team-stat-sdp`) and
**Players stat from SDP** (`#players-stat-sdp`). Both consume the additive public
`/sdp/sdp_stats.json` sidecar, outside the established sealed `/data` manifest.
See the [metric/source contract](sdp-stat-metric-contract.md). Source-native SDP
values without independent reconciliation retain that qualification; their frozen
dictionary flags are unchanged. FPL enrichment is explicitly labelled, and no
player shots, SOT, box touches or exact tactical roles are invented.

Season/GW/team/venue/recent filters, sortable comparison tables, match details,
up-to-three comparisons, observed charts, exposure labels and filtered CSV exports
are descriptive. Actual FPL minutes provide the matching per-90 denominator;
nominal SDP event-clock durations do not. Partial-GW ended matches may appear in
descriptive views while the prospective scorer still waits for whole-GW finality.
Nothing from these pages enters xP, PMFs, optimizer, transfers or captaincy.

### Owner-confirmed SOT display corrections

`config/sdp_dashboard_display_corrections.yaml` records three exact display-only
zeros confirmed by the owner at `2026-09-08T14:40:50.135115Z`: Aston Villa in
fixtures 7 and 20, and Spurs in fixture 28. The exporter applies the value only
after the confirmation cutoff and only when the deterministic fixture/provider
crosswalk, raw payload hash, omitted provider field, shot-accounting evidence and
official opponent-goalkeeper zero-save evidence all match the pinned policy.

The raw SDP field remains NULL, the source row remains `UNAVAILABLE`, and the
provider core-valid count remains 26/30. The correction is copied to the opponent's
`shots_allowed` display with the same provenance so tables, charts and CSV exports
remain consistent. Fixture 19 Fulham is deliberately absent from the policy and
stays unavailable. A missing `ontargetScoringAtt` is never globally interpreted as
zero. These display corrections cannot affect the environment selector, prediction,
PMF or optimizer.

The current operational DB has no `platform_default` / `platform_diagnostic`
optimizer plans. The unchanged public sanitizer therefore correctly refused the
first all-operational package. Its failed generation is retained. The explicit
`--base-dashboard` command above reads the existing validated dashboard generation
without editing that checkout. It preserves its original forecast vintage while
the two new statistics tabs consume the freshly captured sidecar. The receipt
records both generations separately. New BI and dashboard exports are still
retained from the operational DB, but no plans are invented or recomputed to make
them publishable. Omit this option only when the operational DB already contains
the complete required plans. The option is never an automatic fallback.

`build_sdp_dashboard` retains each generation outside Git, reuses the existing
BI/read-model/public-packaging validation and writes a receipt. On a Windows host
without symlink privilege, it uses the already-documented `before_publish` hook
to retain validated copies and explicitly reports that atomic publication failed.
It never calls that formal gate green. Only sanitized `/data/*.json` and validated
`/sdp/sdp_stats.json` are copied to the existing Vite public directory. Databases,
private receipts and raw sources are not copied. Preview is local to this host.

The existing GitHub Pages workflow remains **main-only**. Its optional SDP companion
step downloads only `sdp_stats.json` from the same immutable pinned release, verifies
size/SHA256 and the public schema, and places it outside `/data` before the existing
hosted build. No new infrastructure, credential or deployment branch is introduced.
For a future authorized publication, create one new release containing both the
generated `dashboard-public-data.zip` and `public/sdp/sdp_stats.json`; update the
existing `dashboard/public-data-release.json` with the new package metadata and:

```json
"sdp_asset": {
  "name": "sdp_stats.json",
  "sha256": "<receipt.sdp_sidecar.sha256>",
  "size_bytes": 123
}
```

Use the receipt's exact byte count instead of the illustrative `123`. An absent
companion pin gives an explicit unavailable state; it never falls back to another
source URL. Publishing the branch to the live Pages site still requires a separately
authorized main-branch change. This task does not authorize or execute that change.
