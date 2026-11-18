# Pipeline Interruption Recovery and Storage Cleanup — 2026-11-18

## 1. Incident Diagnosis

On 2026-11-09 at 17:47 Bangkok (10:47 UTC), during run `dashboard-20261109T100008Z-ad284a30`
(PID 8076), an abrupt host reboot occurred during the revision capture phase of GW11.
This left:
- `D:\Personal\fpl-operations\data\sdp-primary-v2.duckdb.wal` (30,773,200 bytes)
- `D:\Personal\fpl-operations\data\sdp-primary-v2.duckdb.daily-sdp.lock` (PID 8076)
- `D:\Personal\fpl-operations\data\operational.duckdb.wal` (5,508,693 bytes)
- `D:\Personal\fpl-operations\data\operational.duckdb.daily-sdp.lock` (PID 30456)
- An uncompressed pre-cycle rollback copy `recovery.duckdb` (9,667,883,008 bytes) in
  `dashboard-20261109T100008Z-ad284a30`.

Because `operational_lock` strictly fails closed whenever an unresolved WAL exists,
all subsequent scheduled runs every 2 hours failed at phase `acquire_lock` with:
`RuntimeError: unresolved WAL: close writers and inspect recovery before retrying`.
The pipeline became stale by ~210 hours.

## 2. Recovery Actions

Under fail-closed procedure and verified immutable row preservation:
1. **PID Dead Verification**: Confirmed both PID 8076 and PID 30456 were dead.
2. **Hash Verification**: Verified SHA256 of active `sdp-primary-v2.duckdb` matched
   the pre-cycle rollback copy `recovery.duckdb` (`ce5e54f1eb19ad52e70b770aa721e0aeaa841090b059c707dfdaed49dc0fa6e7`),
   proving the main database pages had not drifted.
3. **WAL Preservation**: Safely archived `sdp-primary-v2.duckdb.wal` into
   `dashboard-20261109T100008Z-ad284a30/sdp-primary-v2.duckdb.wal.interrupted` for audit.
4. **Lock Recovery & Rollback Compression**:
   - Recovered both dead locks into their respective `.daily-sdp.lock.recovered/` archives.
   - Executed `assert_no_inflight_backup` which ran `_verify_backup` (multiset proof across
     all immutable tables), emitted `capture-interruption-review-66c5a021e0ed4e048ee27de654ac24c8.json`,
     and compressed `recovery.duckdb` to `recovery.duckdb.gz` (1.65 GB).
5. **Operational Fallback Checkpoint**:
   - Checkpointed `operational.duckdb` cleanly via DuckDB Python API, removing its WAL and
     compacting database size from 2.13 GB down to 1.73 GB.

## 3. Full Pipeline Execution

Run `dashboard-20261118T023152Z-06e3bc96` was executed:
- Created clean pre-cycle recovery checkpoint.
- Fetched all 675 official FPL player summaries and latest matches.
- Attached 672 player-fixture outcomes and 20 team-fixture outcomes.
- Built static dashboard (`dashboard_built: true`).
- Successfully published 17 static data files to Cloudflare R2 (`https://data.thecometfpl.com`)
  with generation `bee68e559959ec17e7cf074aaaf79c9a6d2d4bcdaaf835a3ecdae4b58e83fab2`.
- Operational retention completed successfully (`retention: status COMPLETE`).

## 4. Storage Cleanup on Drive D

With user authorization, safe non-essential files were cleaned:
- Deleted orphaned duplicate worktree `.worktrees/v2` (2,536.2 MB) and empty worktree stubs.
- Pruned git worktree metadata via `git worktree prune`.
- Deleted obsolete pre-cycle `before.duckdb` copies in `fpl-operations/runs/` (3,910.6 MB).
- Deleted gzipped recovery backups older than 7 days in `dashboard-runs/` (4,585.4 MB).
- Deleted 129 failed acquire_lock run stubs from the interruption window.

## 5. Storage Impact Summary

| Metric | Before | After | Change |
| :--- | :---: | :---: | :---: |
| Drive D Free Space | 51.52 GB | **93.39 GB** | **+41.87 GB** |
| Drive D Free % | 25.6% | **46.5%** | **+20.9%** |
| Pipeline Status | Stale (210h) | **Healthy / Updated** | Recovered |
| Public R2 Pointer | Nov 9 | **Nov 18** | Current |
