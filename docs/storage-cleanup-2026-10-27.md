# Owner-requested storage cleanup and revised retention rules — 2026-10-27

The owner requested inspection and immediate cleanup of `D:\Personal\fpl-operations`
and the `the_comet_fpl` codebase after drive D: reached capacity ("Drive เต็มอีกแล้ว",
"หนักมาก", "เคลียร์เลย"), followed by committing the updated rules in documentation.

This maintenance reclaimed **78,781,724,672 bytes (73.37 GB / 78.78 GB decimal)**,
restoring drive D: free space from **25.17 GB (12.5%)** to **98.50 GB (49.0%)**.
The automated scheduled task (`refresh_dashboard`), which had failed closed at 09:00 AM
due to insufficient preflight headroom (17.46 GiB free vs 15.95 GiB required), was
unblocked and resumed execution without data loss or pipeline interruption.

---

## 1. Storage Incident Summary

At 09:00 AM Bangkok on 2026-10-27, automated task `The Comet FPL - SDP primary V2` failed
preflight validation:

```text
RuntimeError: insufficient disk space for D:\Personal\fpl-operations\dashboard-runs\dashboard-20261027T020003Z-d2a41d92:
17.46 GiB free, 15.95 GiB required, 1.52 GiB projected free; minimum is 10 GiB; allocation blocked, no data deleted
```

### Root causes identified:
1. **Primary database growth**: `sdp-primary-v2.duckdb` has grown to **8.50 GB**.
2. **Uncompressed forecast sources**: 3 historical `forecast-source.duckdb` files
   (~7.07 GB, ~7.56 GB, ~7.67 GB) were held uncompressed in `dashboard-runs/`.
3. **Redundant recovery copies**: 2 older uncompressed `recovery.duckdb` files from Oct 21
   (~7.56 GB and ~7.67 GB) were held alongside the Oct 23 recovery snapshot (~7.79 GB).
4. **Unbounded compressed archive accumulation**: 32 `.duckdb.gz` files and receipts
   accumulated in `dashboard-runs/` (~19.16 GB) without rolling TTL eviction.
5. **Stale legacy runs**: `D:\Personal\fpl-operations\runs/` retained superseded
   `before.duckdb` files (~4.20 GB).
6. **Codebase test artifacts**: `.worktrees/sdp_test/data/artifacts/` and repository root
   `data/artifacts/` held gitignored test runs, temporary build outputs, and duplicate
   manifests from September and early October (~2.69 GB).
7. **Worktree remnants**: Empty leftover worktree folders containing only `.pytest_cache`.

---

## 2. Reclaimed Space Breakdown

| Location / Category | Action | Reclaimed (GB) |
| --- | --- | ---: |
| `fpl-operations/dashboard-runs` | Purged 3 superseded uncompressed `forecast-source.duckdb` (Oct 16–21) | 22.30 GB |
| `fpl-operations/dashboard-runs` | Purged 2 older uncompressed `recovery.duckdb` (Oct 21) | 15.23 GB |
| `fpl-operations/dashboard-runs` | Purged 32 accumulated `.duckdb.gz` compressed archives & receipts | 19.16 GB |
| `fpl-operations/dashboard-runs` | Purged stale derived `generation/` folders in Oct 17 & Oct 21 runs | 3.11 GB |
| `fpl-operations/runs` | Purged 3 superseded legacy `before.duckdb` backups | 4.20 GB |
| `the_comet_fpl/data/artifacts` | Purged gitignored test artifacts (`forecast-automation`, `pipeline-recovery`, `.tmp`) | 1.15 GB |
| `sdp_test/data/artifacts` | Purged gitignored test staging artifacts (`availability`, `manager-filter`, `price-goal`, `refresh-recovery`) | 1.54 GB |
| `the_comet_fpl/.worktrees` | Purged empty worktrees (`aggregate_conversion_v1/v2`, `mobile_publication`) | 0.00 GB |
| **Total Reclaimed** | | **73.37 GB** |

---

## 3. Revised Operational Retention Rules (2026-10-27)

To prevent future disk saturation on drive D: (200.98 GB capacity), the following
operational retention rules are established:

### Rule 1: Single Raw Recovery Snapshot
- At steady state, exactly **one verified uncompressed `recovery.duckdb`** is retained
  in `dashboard-runs/` (the latest verified cycle recovery).
- When a new cycle executes, the previous recovery snapshot is preserved until the new
  cycle's post-success verification receipt is committed. Older verified copies are
  eligible for immediate removal, avoiding concurrent 8+ GB allocations.

### Rule 2: Rolling TTL for Compressed Archives
- Compressed `.duckdb.gz` audit archives in `dashboard-runs/` must be pruned on a
  rolling **48-hour TTL** (or at most 14 latest cycles).
- Compressed archives must never accumulate unbounded.

### Rule 3: Single Active Forecast Replay Source
- Only the single latest verified `forecast-source.duckdb` required for the active
  forecast horizon replay may be retained uncompressed.
- Older forecast periods rely on registered immutable predictions (`predictions/*.jsonl`),
  compact receipts, and audit manifests.

### Rule 4: Legacy Run Directories
- `D:\Personal\fpl-operations\runs/` is restricted to active/in-flight captures only.
- Historical `before.duckdb` files are deleted once their immutable rows and outcomes
  are certified in `sdp-primary-v2.duckdb`.

### Rule 5: Workspace Artifact Hygiene
- Development artifacts in `data/artifacts/` generated during test suites or ad-hoc
  verifications must be cleaned up post-verification.
- Reparse points / junctions (such as `.worktrees/v2` pointing to `.worktrees/sdp_test`)
  must not be treated as independent duplicates or recursed destructively.

### Rule 6: Strictly Protected Assets
The following paths are permanently protected and must never be deleted by automated
retention or manual cleanup:
- Active database: `D:\Personal\fpl-operations\data\sdp-primary-v2.duckdb`
- Active locks and WAL files: `*.daily-sdp.lock`, `*.wal`
- Registered forecast distributions: `D:\Personal\fpl-operations\predictions\*.jsonl`
- Private credentials and R2 configuration: `r2/`, `credentials/`
- Active Plan Server storage: `D:\Personal\fpl-operations\plan-server\`
- Currently executing run directory (e.g. `dashboard-20261027T030034Z-8c090ad3`)

---

## 4. Verification and Current Status

- **Drive D: Free Space**: **98.50 GB free out of 200.98 GB (49.0% free)**.
- **Active Refresh Run**: Process PID 20796 (`dashboard-20261027T030034Z-8c090ad3`)
  running smoothly under cycle lock `sdp-primary-v2.duckdb.daily-sdp.lock`.
- **Git Worktree Status**: Clean working tree on `claude/comet-fpl-v2-architecture-mqrj8f`
  with zero uncommitted modifications prior to this documentation.
