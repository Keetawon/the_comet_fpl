# Public dashboard payload repair — 2026-10-16

The live generation `21692b8a85a7c506365ec15ce556a5e8bb076c534d2ae3cdbe14234946420a9c`
contained 56 forecast vintages and 35,960 full player records. Its uncompressed
`players.json` was **289,830,082 bytes**. The landing page parsed that entire file
before selecting one vintage. This confirms excessive browser memory demand;
an exact iOS process-memory threshold or a physical-device Jetsam trace was not measured.

## Public projection

Both `build_sdp_dashboard` (including scheduled `refresh_dashboard`) and the public
package CLI now request a bounded mobile projection. The BI export, ledger,
original generation, forecast artifacts and scientific evaluations are unchanged.
The existing sanitizer runs first, including on records later omitted by the
projection. Private-plan removal, forbidden-field checks and provenance redaction
are not weakened.

- Planning retains Summary's exact latest run, both formal plan bindings, and the
  latest incumbent-shadow run at the same cutoff, season and GW horizon. At most
  four distinct runs are permitted. Stale formal plans keep their original vintage.
- Players, cumulative horizons, fixture-matrix teams and manifest run selectors
  use that same population. Every retained record is copied without recalculation.
- Monitoring has its own run metadata. It retains complete stored accuracy blocks
  for the latest non-shadow and shadow runs in each of six recent **scored starting-GW
  windows**, plus active runs. Selection uses cutoff/creation time and identity,
  never error scores. It does not claim that selected runs are a new paired trial
  or that retrospective runs were recorded before a deadline. Original metadata,
  finality, observations, aggregates and calibration blocks stay intact.
- Final/provisional actuals retain the active roster's permanent codes in the
  current and immediately preceding season, preserving every included fixture leg.
  Season-qualified selectors, DNP/null semantics and replayed versus recorded
  points remain unchanged. The measured release retains all 1,147 player-history
  records and all 37 team-history records.
- Accuracy insight requests resolve their run against the appropriate hash-verified
  monitoring document; planning requests still require an active manifest run.
- Public JSON is compact, with unchanged schema-v9 envelopes and strict types.
  SHA-256 hashes, row counts and the package ZIP are rebuilt and revalidated.

The uncompressed publication limits are 15 MB for players and actuals, 2 MB for
horizons/fixture matrix/team accuracy, and 20 MB for player accuracy. Package and R2
gates reject oversized releases before promotion/upload; existing live data remains
intact. The hosted client also checks the pointer's declared byte count before
fetching a bounded file. This protects against a recurrence without relying on gzip
or its compressed `Content-Length`. The legacy sanitizer API remains usable without
projection for local callers; public build/CLI entry points explicitly enable it.

## Measured replacement

| File | Previous bytes | Replacement bytes |
| --- | ---: | ---: |
| players.json | 289,830,082 | 11,399,271 |
| player_horizons.json | 15,301,976 | 847,505 |
| player_forecast_vs_actual.json | 42,957,990 | 5,397,997 |
| player_actuals.json | 15,181,142 | 9,100,709 |
| fixture_matrix.json | 8,201,512 | 375,150 |
| team_forecast_vs_actual.json | 3,903,073 | 557,341 |

The replacement contains 1,985 player records across three selectable runs:
current GW7–11 primary `1faf389a…`, same-cutoff shadow `f6c722ca…`, and retained
GW3–7 diagnostic `c198907c…`. Eleven monitoring vintages remain, including GW1–6
evidence. Retained forecasts, xP, goal-involvement probabilities, observations and
score blocks are compared exactly to the original generation before publication.

The Players headers use the requested mathematical symbol: `GA≥2 GWx` and
`Avg_GA≥2 5GWs`, immediately after `xP GWx–xx`.

## Rebuild and publication

The immediate repair repackages the already completed generation from
`dashboard-20261016T131722Z-9eb6ee48`, retaining its captured data, source timestamps
and sidecar pins. It does not open/write the database, recapture sources, train
models, regenerate forecasts or solve optimizer plans. The new receipt records
the original generation and source manifest explicitly.

For a subsequent read-model rebuild from the existing operational database:

```powershell
$release = 'D:/Personal/fpl-operations/dashboard-runs/<new-release>/generation'
$previous = 'D:/Personal/fpl-operations/dashboard-runs/<latest-complete>/generation/public/data'
& 'D:/Personal/fpl-operations/.venv/Scripts/python.exe' -m fpl.jobs.build_sdp_dashboard `
  --db 'D:/Personal/fpl-operations/data/sdp-primary-v2.duckdb' `
  --output $release --base-dashboard $previous
& 'D:/Personal/fpl-operations/.venv/Scripts/python.exe' -m fpl.jobs.publish_r2_dashboard `
  --generation $release --r2-config 'D:/Personal/fpl-operations/r2/publication.json' `
  --runs 'D:/Personal/fpl-operations/dashboard-runs'
```

Run from the operational checkout with its `src` on `PYTHONPATH`, between refreshes.
Use a new output directory. The publisher validates the complete generation,
uploads immutable objects, verifies their hashes/lengths and updates `current.json`
last under the existing operational lock.

Regression coverage includes multiple historical runs and repeated horizons,
exact record/null/DGW preservation, cutoff-safe score-independent selection,
season/roster scope, missing plan rejection, privacy checks on discarded rows,
deterministic replay, atomic failure, byte limits, and monitoring-only insight IDs.
Release evidence and test limitations are recorded alongside the publication result.
