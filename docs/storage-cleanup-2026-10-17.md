# Owner-requested storage cleanup — 2026-10-17

The owner requested removal of unused backups and experiment outputs, including
`D:\Personal\fpl-operations`, followed by commit and push. This maintenance
reclaimed **15,600,363,353 bytes (15.60 GB)** without deleting unique research,
forecast or recovery evidence. D: had **30,106,787,840 bytes free** after cleanup;
free space can also change through concurrent local work.

| Completed action | Reclaimed bytes |
| --- | ---: |
| 145 completed synthetic-test, generated-build and regenerable-cache folders | 3,910,114,020 |
| 182 byte-identical copies of old dashboard exports | 5,759,206,073 |
| Lossless compression of one superseded recovery database | 5,931,043,260 |
| **Total** | **15,600,363,353** |

The initial inventory covered the repository and operations directory without
following junctions. Deletion used explicit resolved paths inside those roots,
rejected linked paths, and left inaccessible targets in place. A broad elevated
cleanup request was rejected by automatic approval review; it was replaced by
the verified duplicate-file removal and lossless archive operations below.
No ownership or access-control changes were made to force deletion.

## Export duplicates

The review compared 245 generated JSON/ZIP files from completed September and
early-October dashboard verification folders. SHA-256 and byte counts identified
63 unique files. One copy of every unique file remains. All 182 removed copies
have an explicit mapping to their surviving identical file, with hashes checked
before deletion and the survivors checked again afterward.

Only named generated dashboard payloads were eligible. Original manifests,
receipts, logs, source databases and model results remain. Current operational
generations and the public R2 bucket were not cleanup targets. Historical local
presentation folders may now be incomplete; an individually removed file can be
restored by copying its mapped surviving file back to its original path.

## Superseded recovery archive

The October 16 13:17 run's `recovery.duckdb` was compressed using the existing
`fpl.jobs.audit_db_archive` implementation. Its 7,190,622,208 original bytes are
preserved in a 1,259,578,948-byte gzip file and its adjacent verification receipt.
The source SHA-256 is
`776273faae8caf1ab10517115cab0ce1acd56c0b4525338b80cf47ca056da654`.
The archive SHA-256 is
`36ca3436d0fa050361bc95566e74716aae05f06c8efdb700041fa4e6ea50484e`.

The two newer raw recovery copies, from the October 16 16:00 and 18:00 runs,
were verified against their completed receipts and remain uncompressed.
The primary refresh task was temporarily disabled, its existing cycle lock and
a read-only active-database lease were held, and the task was restored in a
`finally` block. The active database's size and modification time were unchanged.
The task was verified **Enabled / Ready** afterward.

Explicit restoration remains available through the existing archive command:

```powershell
& D:/Personal/fpl-operations/.venv/Scripts/python.exe -m fpl.jobs.audit_db_archive restore `
  --root D:/Personal/fpl-operations `
  --source D:/Personal/fpl-operations/dashboard-runs/dashboard-20261016T131722Z-9eb6ee48/recovery.duckdb
```

## Retained evidence

The 40 registered forecast files retain their SHA-256 identities. Model source,
configurations, frozen results, Git history/stash, the saved source-control
backup, current databases, private plans, runtime environments and credentials
were excluded. No model fitting, forecast regeneration or publication occurred
as part of this cleanup. Separate staged source edits from concurrent local work
were excluded from the maintenance commit.

Detailed inventories, path guards, duplicate mappings, deletion receipts,
archive verification and final checks are local under
`.tmp/storage-cleanup-20261017/`. The archive's permanent receipt remains adjacent
to the archive in the operations directory.
