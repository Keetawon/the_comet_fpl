# Owner-requested storage cleanup and lock recovery — 2026-11-06

The owner requested review and cleanup of disposable files across relevant operational
and workspace folders ("รีวิวไฟล์ที่ลบได้ในโฟลเดอร์ที่เกี่ยวข้องหน่อย", "ok ลบเลย").

This maintenance safely reclaimed **74,387,707,904 bytes (69.28 GB / 74.39 GB decimal)**,
restoring drive D: free space from **51.52 GB (25.6%)** to **120.77 GB (60.1%)**.
In addition, an interrupted cycle resulting from an unexpected host restart was safely
recovered, DuckDB WAL flushed, lock unblocked, and preflight certified.

---

## 1. Reclaimed Space Breakdown

| Category / Location | Action | Reclaimed |
|---|---|---:|
| `dashboard-runs/...732d35cb/recovery.duckdb` | Superseded raw recovery copy (Nov 3) | 8.86 GB |
| `dashboard-runs/...c95f77ec/forecast-source.duckdb` | Superseded raw forecast source (Oct 30) | 8.41 GB |
| `dashboard-runs/...732d35cb/forecast-source.duckdb` | Superseded raw forecast source (Nov 3) | 8.86 GB |
| `dashboard-runs/...732d35cb/generation/` | Superseded preview export directory (Nov 3) | 1.94 GB |
| `dashboard-runs/...75cfe85d/recovery.duckdb` | Interrupted capture checkpoint compressed to archive | 7.36 GB |
| `dashboard-runs/.../*.duckdb.gz` (16 archives & receipts) | Rolling TTL purge of compressed archives older than 48 hours | 23.52 GB |
| `runs/.../before.duckdb` (6 daily backups) | Legacy pre-capture backups of `operational.duckdb` | 10.32 GB |
| **Total Reclaimed** | | **69.28 GB** |

---

## 2. Lock & Interrupted Cycle Recovery

- **Crash diagnosis**: Host restart killed background PID 11092 during cycle `75cfe85d`,
  leaving `sdp-primary-v2.duckdb.daily-sdp.lock` and an uncheckpointed `.wal` file.
- **Recovery actions**:
  1. Connected to `sdp-primary-v2.duckdb` and executed clean `CHECKPOINT;`, flushing WAL
     changes and removing `sdp-primary-v2.duckdb.wal`.
  2. Acquired and released `operational_lock`, archiving the dead PID lock sidecar to
     `sdp-primary-v2.duckdb.daily-sdp.lock.recovered/` with full provenance receipt.
  3. Certified immutable-row proof of pre-cycle checkpoint `75cfe85d\recovery.duckdb`,
     compressed it to gzip archive, and recorded `capture-interruption-review-*.json`.
- **Preflight certification**: Scheduled task `The Comet FPL - SDP primary V2` verified
  `Status: Ready`, fully unblocked for subsequent automated cycles.

---

## 3. Protected Assets & Storage Verification

- **Active primary database**: `D:\Personal\fpl-operations\data\sdp-primary-v2.duckdb` (8.86 GB) intact.
- **Active operational database**: `D:\Personal\fpl-operations\data\operational.duckdb` (1.87 GB) intact.
- **Latest verified recovery backup**: `dashboard-runs\dashboard-20261106T071832Z-67b60d17\recovery.duckdb` (8.86 GB).
- **Latest verified forecast source**: `dashboard-runs\dashboard-20261106T071832Z-67b60d17\forecast-source.duckdb` (8.86 GB).
- **Registered predictions**: `predictions/*.jsonl` all intact.
- **Drive D: Final Free Space**: **120.77 GB free** out of 200.98 GB (60.1% free).
