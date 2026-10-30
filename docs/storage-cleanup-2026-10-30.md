# Owner-requested storage cleanup — 2026-10-30

The owner requested an update check and immediate cleanup of bloated backups and
stale operational outputs in `D:\Personal\fpl-operations` and the `the_comet_fpl`
codebase ("มี อัพเดท เช็คหน่อยว่าอันไหนเคลียร์ได้บ้าง", "จัดไป").

This maintenance safely reclaimed **35,992,729,600 bytes (33.52 GB / 35.99 GB decimal)**,
restoring drive D: free space from **39.99 GB (19.9%)** to **73.28 GB (36.5%)**.
The actively executing scheduled task (`dashboard-20261030T080009Z-c95f77ec`, PID 34916)
was protected throughout and continues capturing SDP data without interruption.

---

## 1. Reclaimed Space Breakdown

| Location / File | Action | Reclaimed |
|---|---|---:|
| `dashboard-runs/dashboard-20261027T030034Z-8c090ad3/forecast-source.duckdb` | Superseded uncompressed forecast source database (Oct 27) | 8.05 GB |
| `dashboard-runs/dashboard-20261027T030034Z-8c090ad3/recovery.duckdb.gz` | Gzip archive older than 72 hours (exceeds 48h TTL) | 1.38 GB |
| `dashboard-runs/dashboard-20261027T030034Z-8c090ad3/generation/` | Superseded preview export directory (Oct 27) | 1.66 GB |
| `dashboard-runs/dashboard-20261030T024052Z-efdeeb42/forecast-source.duckdb` | Forecast source database superseded by 07:11Z cycle | 8.20 GB |
| `dashboard-runs/dashboard-20261030T024052Z-efdeeb42/recovery.duckdb` | Superseded recovery copy (verified successor: `00b9c291`) | 8.05 GB |
| `dashboard-runs/dashboard-20261030T024052Z-efdeeb42/generation/` | Superseded preview export directory (02:40Z) | 1.70 GB |
| `runs/20261028T000849.737083Z-3817aed3/before.duckdb` | Superseded pre-capture backup of `operational.duckdb` | 1.48 GB |
| `runs/20261029T015646.509330Z-86becb57/before.duckdb` | Superseded pre-capture backup of `operational.duckdb` | 1.48 GB |
| `runs/20261030T015940.587801Z-106b6187/before.duckdb` | Superseded pre-capture backup of `operational.duckdb` | 1.52 GB |
| **Total Reclaimed** | | **33.52 GB** |

---

## 2. Protected Assets Verification

All core operational and scientific evidence remained strictly protected:
- **Active primary database**: `D:\Personal\fpl-operations\data\sdp-primary-v2.duckdb` (8.26 GB).
- **Active in-flight execution**: `dashboard-runs/dashboard-20261030T080009Z-c95f77ec/` (PID 34916).
- **Latest verified recovery backup**: `dashboard-runs/dashboard-20261030T060002Z-00b9c291/recovery.duckdb` (8.20 GB, SHA256 `9bebacdaa4b8d955718d6a0173a0b450c26605b9fce9bbbe9f545fcd8dca4199`).
- **Latest forecast replay source**: `dashboard-runs/dashboard-20261030T060002Z-00b9c291/forecast-source.duckdb` (8.26 GB, SHA256 `b193f3c5178b9e2a4881f57c853b270bba77dca3c3bcaf83ce822e4fd950f54b`).
- **Registered predictions**: All `predictions/*.jsonl` files intact.
- **Runtime credentials & Plan Server**: Untouched.

---

## 3. Post-Cleanup System State

- **Drive D: Free Space**: **73.28 GB free** out of 200.98 GB (36.5% free).
- **Scheduled Task Status**: Healthy and actively running cycle `c95f77ec`.
