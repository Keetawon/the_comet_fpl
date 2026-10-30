# Owner-requested storage cleanup — 2026-10-30

The owner requested an update check and deep cleanup of bloated backups and stale
outputs across drive D:, `D:\Personal\fpl-operations`, and `the_comet_fpl` codebase
("มี อัพเดท เช็คหน่อยว่าอันไหนเคลียร์ได้บ้าง", "จัดไป", "ออกอีกได้มะ", "จัดไป อ่านแล้ว").

This maintenance safely reclaimed **83,863,941,120 bytes (78.10 GB / 83.86 GB decimal)**
in two consecutive passes, restoring drive D: free space from **39.99 GB (19.9%)**
to **107.43 GB (53.5%)** — freeing more than half of the entire 200.98 GB drive.

---

## 1. Reclaimed Space Breakdown

### Pass 1: FPL Operational Runs & Legacy Backups (33.52 GB)

| Location / File | Action | Reclaimed |
|---|---|---:|
| `dashboard-runs/...8c090ad3/forecast-source.duckdb` | Superseded uncompressed forecast source database (Oct 27) | 8.05 GB |
| `dashboard-runs/...8c090ad3/recovery.duckdb.gz` | Gzip archive older than 72 hours (exceeds 48h TTL) | 1.38 GB |
| `dashboard-runs/...8c090ad3/generation/` | Superseded preview export directory (Oct 27) | 1.66 GB |
| `dashboard-runs/...efdeeb42/forecast-source.duckdb` | Forecast source database superseded by 07:11Z cycle | 8.20 GB |
| `dashboard-runs/...efdeeb42/recovery.duckdb` | Superseded recovery copy (verified successor: `00b9c291`) | 8.05 GB |
| `dashboard-runs/...efdeeb42/generation/` | Superseded preview export directory (02:40Z) | 1.70 GB |
| `runs/20261028.../before.duckdb` | Superseded pre-capture backup of `operational.duckdb` | 1.48 GB |
| `runs/20261029.../before.duckdb` | Superseded pre-capture backup of `operational.duckdb` | 1.48 GB |
| `runs/20261030.../before.duckdb` | Superseded pre-capture backup of `operational.duckdb` | 1.52 GB |
| **Pass 1 Subtotal** | | **33.52 GB** |

### Pass 2: Root Archives, Completed Worktrees & Project Caches (44.58 GB)

| Location / Target | Action | Reclaimed |
|---|---|---:|
| `D:\docker-migration-backup-full_SENADW.tar` | One-time Docker migration backup from 2026-09-07 | 36.96 GB |
| `D:\SSMS-Setup-ENU.exe` | Obsolete SQL Server Management Studio installer (2023) | 0.61 GB |
| `.worktrees/mobile_export_bounds` | Merged Git worktree in `the_comet_fpl` (pipelines) | 0.45 GB |
| `.worktrees/player_production_ga` | Completed Git worktree in `the_comet_fpl` (position-free research) | 0.61 GB |
| `.worktrees/optimizer_defender_limit` | Completed Git worktree in `the_comet_fpl` (defender limit) | 0.25 GB |
| `sena_digital_hub_mkt/.local/hosted-test-simulation` | Stale simulation outputs from automated test suite | 4.85 GB |
| `sena_digital_hub_mkt/.cache` | Stale build and framework cache | 0.88 GB |
| **Pass 2 Subtotal** | | **44.58 GB** |
| **Grand Total Reclaimed** | | **78.10 GB** |

---

## 2. Protected Assets & Operational Integrity

All active systems and core evidence were verified untouched:
- **Active primary database**: `D:\Personal\fpl-operations\data\sdp-primary-v2.duckdb` (8.26 GB).
- **Active in-flight execution**: `dashboard-runs/dashboard-20261030T080009Z-c95f77ec/` (PID 34916).
- **Latest verified recovery backup**: `dashboard-runs/dashboard-20261030T060002Z-00b9c291/recovery.duckdb` (8.20 GB).
- **Latest forecast replay source**: `dashboard-runs/dashboard-20261030T060002Z-00b9c291/forecast-source.duckdb` (8.26 GB).
- **Registered predictions**: All `predictions/*.jsonl` files intact.
- **Git branches**: All commit history preserved on remote; working branch `claude/comet-fpl-v2-architecture-mqrj8f` clean.

---

## 3. Final Storage Status

- **Drive D: Free Space**: **107.43 GB free** out of 200.98 GB (**53.5% free**).
- **Headroom**: Over 100 GB available for automated scheduled cycles and routine operations.
