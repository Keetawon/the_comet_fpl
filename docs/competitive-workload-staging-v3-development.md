# Competitive interpretation V3: retained additive operational cycle

Clean run `54d9ffee89e161f6a57f4e35d4b93b4de2893b54` completed at
2026-09-07T09:48:01.059669Z. One independently corroborated `StraightRed` alias recovers
43 interpretations, from 515 to **558 valid matches out of 574**. None regresses.
No HTTP requests, model fits, default changes or old-version overwrites occurred.

| Competition | Valid V2 | Valid V3 | Captured |
|---|---:|---:|---:|
| Premier League | 342 | 371 | 380 |
| FA Cup | 38 | 41 | 43 |
| League Cup | 36 | 37 | 38 |
| Champions League | 59 | 65 | 69 |
| Europa League | 27 | 29 | 29 |
| Conference League | 13 | 15 | 15 |

Unresolved actors, missing substitution IDs and other contradictory evidence remain unusable.
Raw and earlier interpretations are retained, not repaired in place. Independently measured
PL starting-role coverage is **8,162/8,360 = 97.6316%**, above the fixed 95% threshold.
All 29,747 target roster rows / 380 fixtures / 38 GWs and 270 2025-26 price-proxy flags match
the separate historical minutes reference. This establishes source coverage, not role accuracy.

The actual staging audit compares 11,261 measured appeared durations: nominal-period MAE
0.259036 minutes, 99.9467% within two minutes of FPL. Six outliers exceed two minutes; the
full signed distribution and exact rows remain in the result. Nominal clipping is unchanged.
Derived nominal duration is not provider-reported/FPL minutes. Exact all-competitive workload
and physical rest remain NULL without trusted registration intervals; witnessed lower bounds
are the only licensed historical feature capability.

## Preserved storage and actual command

Source V2 DB:
`D:/Personal/fpl-operations/development/competitive-workload-20260907T091500Z.duckdb`,
SHA256 `5b6eb100bd770f6fc53e9206d542510d1d4ee4ffe6b533825c718e9625212e8d`.
New V3 DB:
`D:/Personal/fpl-operations/development/competitive-workload-v3-20260907T094600Z.duckdb`,
SHA256 `a8584ce79f421e0bd43057f3a8f63bac03e30b59cc1c2407b8a7c28387a35021`.

```powershell
python -m fpl.jobs.restage_competitive_participation_v3 `
  --source-db D:\Personal\fpl-operations\development\competitive-workload-20260907T091500Z.duckdb `
  --db D:\Personal\fpl-operations\development\competitive-workload-v3-20260907T094600Z.duckdb `
  --results D:\Personal\fpl-operations\verification\competitive-workload-v3-stage-20260907T094600Z
```

The new DB contains 1,148 whole versions, 43,961 participation rows, 1,161 raw receipts,
two ingestions and two coverage versions. Independent **25,677 checks, zero failures** verify
every original 574 V2 version, 21,036 V2 participation row, raw bytes and knowledge timestamps
are unchanged. Original archive, V2 and V3 database hashes recheck; no WAL remains. No
production consumer has been switched to this new database.

Byte-identical reports: `results/competitive_workload_staging_v3.json`, SHA256
`2df5d126c466edb2cf3e6f78e4bf3df9a24c350a44f47d2fc890d31ec3bf46c9`, and
`results/competitive_workload_staging_v3_independent_audit.json`, SHA256
`82094c15ce3260585a3f72e74df259f90423e1e821c4d23bb517b9f895de51de`.

## Pre-model finality-filter finding

The first role coverage-only scaffold audit is separately retained in
`results/player_role_coverage_initial_finality_filter.json`, SHA256
`799d45e902ce979170fce741455b91a38889393b6bc767e2c7f4d33e801a971e`.
Its PL denominator is correct, but it selected only 535 historical source bundles: a
PL-only completion helper rejected 39 completed cup/Europe Aggregate, PenaltyShootout and
AfterExtraTime results. No role was fitted or scored. The new role runner must use the
already-audited competitive finality contract and publish a new coverage snapshot before
final preregistration. Preserve the initial report rather than relabelling its source universe.
