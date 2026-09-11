# FPL xG supplement for observed team analysis — 2026-09-11

The owner authorized FPL xG as a **descriptive Dashboard supplement** where SDP xG
is absent. Starting SHA: `942ac4c12533460a0286816a6ddf30dd425e2bc1`, on
`claude/comet-fpl-v2-architecture-mqrj8f`. This change does not supply data to the
football environment, player models, selector, optimizer or historical experiments.

## Display and source contract

Sidecar schema 6 adds `team_matches[].display_supplements`. Raw `sdp` values,
`status`, `dashboard_status`, display corrections and assumptions retain their
previous values. Older sidecars remain readable. Missing xG is never zero-filled.

- Prefer observed SDP xG, including an actual zero. Only when absent, display the
  validated sum of recorded FPL archive player `expected_goals`, **including GK**.
- xGA uses the opposing team's validated sum from that same fixture. No player
  xGC summation and no allocation of SDP team statistics to players occurs.
- Read the existing raw archive tables and reconcile each season's row counts and
  single ingestion timestamp against its immutable `raw_ingest_log` receipts.
  Retain all four source hashes: merged player history, players, fixtures and teams.
- Resolve players by season-local element and permanent code. Resolve club by
  fixture side, opponent, venue and exact archived team name/code. End-season
  player club membership is not used to rewrite a transferred player's past club.
- Exact duplicate raw rows are deduplicated. Conflicting player-fixture repeats,
  contradictory identities, missing/nonfinite/negative xG, missing exposure or
  starts, unfinished fixtures and post-cutoff captures fail closed.
- Every recorded player row must have measured xG and valid actual minutes/starts;
  each team must have eleven explicit starts and at least eleven appearances.
  Both sides must pass. DNP rows must explicitly carry zero minutes/starts/xG;
  missing DNP xG does not become zero. Existing declared data-quality NULL repairs
  apply, including the 2022/23 GW1–15 unmeasured zero prefix.
- This checks the complete **recorded** roster, not an independent source witness
  that every substitute was captured. The display/provenance states that limit.
- The conservative availability time is the latest actual ingestion of the four
  retained inputs (`2026-08-19T09:00:51.396626+00:00` here), never match kickoff or
  the legacy archive mart's historical proxy. Evidence stays
  `retrospective_descriptive`; no historical PIT claim is created.
- The supplement contains a deterministic hash of the contributing stable player
  identities, minutes, starts and xG, plus season/fixture/GW/side/club bindings.
  Supplemented display rows advance their own `known_at` to include this source;
  original source records are untouched.

Tables/profile cells show an **FPL** badge, with actual capture time, coverage and
hashes in provenance. Trends, the xG/xGA scatter, comparisons, sort and CSV use the
same value accessor. CSV identifies `SDP / marked FPL` and retains provenance per
metric. xG percentages are not rescaled; rounded FPL player totals may differ from
SDP match xG. Mixed-source comparisons carry this limitation. No raw FPL enrichment
is relabelled as an SDP observation. Other metrics and their denominators are unchanged.

## Actual retained coverage

All counts below are **fixtures**, with two team sides per fixture.

| Season | SDP xG fixtures | Additional FPL-supplemented fixtures | Displayed xG/xGA coverage | Unchanged provider core-valid |
|---|---:|---:|---:|---:|
| 2021/22 | 3 | 0 | 3 / 380 | 3 |
| 2022/23 | 2 | 244 | 246 / 380 | 2 |
| 2023/24 | 3 | 377 | 380 / 380 | 3 |
| 2024/25 | 170 | 210 | 380 / 380 | 159 |
| 2025/26 | 380 | 0 | 380 / 380 | 363 |
| 2026/27 | 30 | 0 | 30 / 30 | 26 |

Current 30 fixtures are the total across **GW1–GW3**, not 30 in GW3.
The four current owner-confirmed dashboard-valid fixtures remain separate from
the 26 provider core-valid fixtures. No FPL supplement upgrades either count.

Full-season frontend aggregation now supports all 20 clubs on the xG/xGA scatter
for 2023/24, 2024/25 and 2025/26. The oldest two full seasons still lack complete
coverage: no full-season xG average/scatter is fabricated by dropping missing
matches. Narrower covered GW ranges remain usable. Shots, passing, possession and
other available SDP metrics continue to work independently.

## Export, replay and preview

No network ingestion/backfill was run. The existing read-only operational export
reused captured data; its generation timestamp is distinct from source freshness.

- As-of: `2026-09-11T10:22:34.358377+00:00`.
- Latest SDP: `2026-09-11T02:00:25.273378+00:00`.
- Latest FPL current-history enrichment: `2026-09-09T05:41:30.018462+00:00`.
- New sidecar SHA256:
  `4e2d05feb055738b9220d145e59e114bde0756549570c2920122b5038fc0fe05`.
- Previous sidecar SHA256:
  `bcf74a478703fa6d9e65c91de382564c974d5bb4301f922f2285fe5d848eccd0`.
- Immutable old/new exports, replay, receipts, coverage, CSVs and preservation
  checks: `D:/Personal/fpl-operations/verification/fpl-xg-supplement-20260911/`.
- All 12 original CSV files used by the supplements were independently hashed
  against their source receipts. The exporter itself uses the retained raw tables
  and ingestion receipts, so it needs no new cache-path configuration.
- A second export at the identical cutoff reproduced identical bytes. The actual
  frontend parser accepted it and its aggregation/CSV code reproduced the stated
  coverage. Raw SDP cells, existing player rows, corrections, assumptions and
  provider-health counts are unchanged from the retained prior sidecar.
- Installed only the validated SDP sidecar in public and built assets, preserving
  its previous version. No forecast/dashboard-base regeneration was performed.
  The existing preview serves byte-identical sidecar and compiled assets at
  `http://127.0.0.1:4173/#team-stat-sdp` (local-only). No production deployment.

Future ordinary sidecar builds automatically apply the same checks. The existing
CLI is unchanged; an explicit new output path is required for each export:

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
python -m fpl.jobs.export_sdp_stats --db D:/Personal/fpl-operations/data/sdp-primary-v2.duckdb --as-of <actual-UTC-time> --output <new-immutable-output>/sdp_stats.json
```

Use the existing Dashboard publication/install flow for the validated sidecar.
Do not replace frozen forecast source snapshots or rerun inference to publish it.

## Verification and limits

- 99 focused Python tests pass (archive supplement, SDP export, dashboard validation
  and build integration). Synthetic cases cover incomplete sums, explicit zero,
  duplicate/conflicting rows, transfer identity, availability, receipt validation,
  historical placeholder exclusion, opposite-side binding and unchanged SDP priority.
- 62 frontend tests pass across parser, arithmetic/CSV, SDP page, scatter and team
  analytics. The FPL badges, trends, match log and unchanged health are DOM-tested.
- Strict mypy, TypeScript, Vite build, changed-file Ruff and formatting pass.
  Oxlint reports zero errors and the existing nine Fast Refresh warnings; Vite
  retains its existing bundle-size warning. No full-repository-green claim.
- Browser skill attempted `getForUrl`: `No browser is available`. Documented
  troubleshooting returned `[]` from browser discovery. No screenshots or real
  desktop/mobile visual pass are claimed. HTTP checks and DOM tests are not visual
  browser verification; that review remains outstanding.
- All 415 previously protected source/config/result/prediction hashes match their
  recorded values. Research verdicts and both GW1–GW3 audit identities are untouched.
  No production policy, model parameter, xP/PMF, optimizer plan or current player
  statistic changed. Operational DB access was read-only.

This fills a **display coverage** gap. It makes no claim that missing historical
Dashboard cells caused V2's frozen experimental results, or that these supplements
improve predictions.
