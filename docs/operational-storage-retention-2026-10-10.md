# Operational storage retention and disk guardrail update (2026-10-10)

The owner authorized bounding operational retention, purging obsolete local run
archives and test artifacts, and calibrating the disk space preflight thresholds
on October 10, 2026. This changes operational storage limits and maintenance only.
Forecast models, scoring rules, predictions, and analytical contracts are unchanged.

## Incident and root cause

On October 10, 2026, the scheduled primary refresh task (`The Comet FPL - SDP primary V2`)
failed with exit code 1 at its 11:00 Bangkok run. Drive D: had fallen to 32.22 GiB
free. The operational disk preflight check (`operational_disk.py`) calculated:

```
RuntimeError: insufficient disk space for D:\Personal\fpl-operations\dashboard-runs\dashboard-20261010T040002Z-ecf65b4d:
32.22 GiB free, 12.24 GiB required, 19.98 GiB projected free; minimum is 20 GiB; allocation blocked, no data deleted
```

Because the cycle failed closed before capture or build, the post-cycle automatic
retention routine (`prune_runs`) was never reached. The system entered an operational
deadlock: insufficient disk space prevented the refresh cycle from starting, which
prevented the retention pruner from retiring superseded recovery checkpoints.

Investigation of `D:\Personal\fpl-operations` (~75 GB) and the repository (~25 GB)
identified four major sources of unbounded disk growth:

1. **Unpruned forecast source snapshots in `dashboard-runs/`**: Runs that regenerated
   forecasts created uncompressed copies of `forecast-source.duckdb` (~5.5 to 5.8 GB
   each). Because retention discovery treated any directory containing
   `forecast-source.duckdb` as a permanent reference, these multi-gigabyte files were
   never deleted or compressed.
2. **Accumulating gzip archives (`recovery.duckdb.gz`)**: Earlier retention passes
   compressed older `recovery.duckdb` files into `.duckdb.gz` (~600 MB - 1 GB each).
   Over 30 of these archives accumulated across September and October, consuming
   23.44 GB.
3. **Duplicate database copies in repository artifacts**:
   - `data/artifacts/pipeline-recovery-20260928/` contained duplicate copies of
     `operational.duckdb` (`legacy-original` 1.31 GB and `legacy-trial` 1.31 GB).
   - `.worktrees/sdp_test/data/sdp-recovery/20260906T142605Z/` contained an obsolete
     `fpl-operational.duckdb` (1.06 GB).
4. **Synthetic test fixtures and temporary caches**:
   - `.worktrees/sdp_test/data/artifacts/retention-policy-20260918/` contained 1.27 GB
     of synthetic `pytest-*` and `mypy-*` test environments from earlier verifications.
   - Playwright and browser test caches in `data/artifacts` accumulated thousands of
     temporary browser profiles, WebAssembly, and model cache files.

## Owner-authorized policy update

The following storage retention rules are established:

1. **Steady-state recovery retention**: The operational pipeline maintains **one verified
   recovery copy** (`recovery.duckdb` in the latest successful run) and up to two recent
   dashboard export generations. When a cycle completes and its recovery is verified,
   superseded recovery copies are retired.
2. **Forecast source lifecycle**: Historical `forecast-source.duckdb` copies must be
   compressed or retired once the corresponding forecast is registered in
   `predictions/*.jsonl` and published. Uncompressed 5+ GB source copies must not be
   retained permanently in routine run directories.
3. **Rolling archive retention**: Compressed `.duckdb.gz` archives in `dashboard-runs/`
   are bounded to a rolling 48-hour window (or last 2 gameweeks). Stale archives beyond
   this window are retired during maintenance.
4. **Non-permanent artifact cleanup**: Synthetic test directories (`pytest-*`, `mypy-*`),
   temporary `.tmp/` scratch files, and browser/automation cache profiles are non-permanent
   and must be purged after verification.
5. **Calibrated space guardrails (`operational_disk.py`)**:
   - **Warning threshold**: 15 GiB projected free (lowered from 30 GiB).
   - **Hard block threshold**: 10 GiB projected free (lowered from 20 GiB).
   This avoids artificial lockouts on 200 GB partitions while still preserving a safe
   10 GiB headroom for OS and background operations.

## Cleanup verification and results

On October 10, 2026, the following items were safely purged:

| Target | Description | Reclaimed |
|---|---|---:|
| `data/artifacts/pipeline-recovery-20260928/legacy-*` | Redundant operational DB copies | 2.62 GB |
| `.worktrees/sdp_test/data/sdp-recovery/20260906T142605Z/` | Obsolete recovery database | 1.06 GB |
| `retention-policy-20260918/` (synthetic test dirs) | Pytest and mypy test environments | 1.27 GB |
| `dashboard-runs/dashboard-20261008T040010Z.../forecast-source.duckdb` | Uncompressed forecast DB snapshot | 5.44 GB |
| `dashboard-runs/dashboard-20261009T180007Z.../forecast-source.duckdb` | Uncompressed forecast DB snapshot | 5.81 GB |
| `runs/20260928.../before.duckdb` & `runs/20260929.../before.duckdb` | Obsolete legacy backups | 2.70 GB |
| `dashboard-runs/*.duckdb.gz` (older than 48 hours) | Stale compressed run archives | 17.50 GB |
| Stale test caches (`.pytest_tmp_*`, `.mypy_cache_*`, empty temp dirs) | Intermediate cache dirs | 0.31 GB |
| **Total reclaimed** | | **36.71 GB** |

- **Drive D: Free Space**: increased from **32.22 GB** to **68.93 GB**.
- **Active Data Preservation**: The active production database (`sdp-primary-v2.duckdb`,
  6.01 GB), registered forecasts in `predictions/`, optimizer state in `plan-server/`,
  and the latest verified recovery copies were verified and remain untouched.
- **Regression Tests**: All 12 tests in `tests/test_operational_disk.py` and all 55 tests
  in `tests/test_refresh_dashboard.py` pass cleanly.
- **Pipeline Unblocked**: The scheduled task preflight now calculates projected free space
  well above both the 10 GiB minimum and 15 GiB warning thresholds.
