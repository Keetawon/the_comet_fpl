# First retained operational competitive workload staging

This data-only cycle completed at **2026-09-07T09:16:23.819687+00:00** from clean
`71c11bff29e29ff1bdc827720a9ab51cf21ac560`. No model was fitted or scored.

Source: `D:/Personal/workspace/the_comet_fpl/.worktrees/sdp_test/data/fpl.duckdb`,
SHA256 `0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8`.
New operational copy:
`D:/Personal/fpl-operations/development/competitive-workload-20260907T091500Z.duckdb`,
SHA256 `5b6eb100bd770f6fc53e9206d542510d1d4ee4ffe6b533825c718e9625212e8d`.
The source remains unchanged; no WAL remains. Default consumers still use their original
databases. Five isolated development tables retain 574 whole-match versions, 21,036
roster observations, 1,161 raw receipts, one ingestion and one coverage version.

Command actually executed:

```powershell
python -m fpl.jobs.stage_competitive_workload `
  --source-db D:\Personal\workspace\the_comet_fpl\.worktrees\sdp_test\data\fpl.duckdb `
  --db D:\Personal\fpl-operations\development\competitive-workload-20260907T091500Z.duckdb `
  --capture D:\Personal\fpl-operations\verification\competitive-workload-2025-20260907T083100Z `
  --pilot-result D:\Personal\fpl-operations\verification\competitive-participation-v2-20260907T083000Z\result.json `
  --results D:\Personal\fpl-operations\verification\competitive-workload-stage-20260907T091500Z
```

## Coverage is not implied by successful capture

All 574 matches have retained raw data, but only 515 interpret without errors under V2:

| Competition | Valid interpretations | Captured matches |
|---|---:|---:|
| Premier League | 342 | 380 |
| FA Cup | 38 | 43 |
| League Cup | 36 | 38 |
| Champions League | 59 | 69 |
| Europa League | 27 | 29 |
| Conference League | 13 | 15 |

The independent audit ran **32,015 checks with zero integrity failures**, rehashing all
1,161 retained raw BLOBs and checking both database hashes. It confirms no identity or measured
starter/appearance contradiction. One exact provider/FPL player identity, Tyler Onyango,
has no archive row for PL fixture 10; this is a missing target, not a wrong-player join.
Twelve unassigned roster observations remain unknown, not measured DNPs.

Four duration differences exceed the pilot's two-minute tolerance. They arise from clipping
stoppage-time endpoints at nominal period boundaries: Buendia 23 vs FPL 33, Traore 2 vs 6,
Gudmundsson 45 vs 49, Trossard 17 vs 20. Raw event clocks remain retained. The pilot's original
nominal-duration definition and result are not rewritten, and no tolerance is relaxed.

Role coverage uses **all 8,360 independently recorded FPL starters** as its denominator:
7,524 valid role labels, **90.00%**, below the fixed 95% requirement. The audit retains all
836 excluded identities. No formal role candidate scoring is licensed by this snapshot.
PL failures: 31 unsupported `StraightRed` interpretations, five missing/nondecimal sub-on
IDs, one unknown raw position and one unknown dismissal actor. A separately named
source-corroborated interpretation amendment may handle the exact card-type alias; it must
not silently fix NULL actors, edit V2 reports or fabricate participation.

## Evidence retained

Complete byte-identical reports: `results/competitive_workload_staging_v2.json`, SHA256
`a41152f86e382f12797cd9e688b149c065996773a05ef984bdc899606686d8a8`, and
`results/competitive_workload_staging_v2_independent_audit.json`, SHA256
`46f0605e60b00a44fdad43a2349bb1fc82b7d300723df0e5650a1eb59603e004`.
External originals remain in the command's new results directory. The later independent
read-only audit accurately records concurrent implementation edits rather than claiming
clean formal-model provenance. The original staging run itself was clean.

Exact workload totals and physical rest remain unavailable without trusted historical
registration intervals. The populated reader exposes separately typed witnessed-participation
lower bounds with the six-hour completion proxy and whole-target-GW isolation; no absent
source is called a rested zero. Strict prospective paths do not read these development
tables. Original databases, frozen Phase A and all earlier evaluations remain unchanged.
This is a data-access record, not a player-model result or production promotion.
