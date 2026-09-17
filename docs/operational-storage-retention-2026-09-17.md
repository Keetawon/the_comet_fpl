# Operational storage cleanup and retention

The owner authorized deletion of stale generated data and bounded operational
backup retention on September 17, 2026. This changes storage operations only.
Forecasts, model/configuration files, scientific verdicts, and the capture and
selection evidence rules are unchanged.

The first real retention verification subsequently exposed a source-pin discovery
defect and was stopped. Three historical publication source copies were deleted;
their immutable rows survive, but exact old database bytes have not been restored.
See the [incident and correction record](operational-retention-incident-2026-09-17.md).
The manual cleanup totals below exclude those unintended deletions.

## Automatic policy

After a successful local refresh and, when configured, successful R2 publication,
`refresh_dashboard` writes its completed receipt, creates a SHA256-verified
post-success `recovery.duckdb` under the existing cycle lock, and invokes retention.
The recovery includes the newly captured observations and attached outcomes.
The steady-state target is **one full operational recovery copy and two Dashboard
generations**, rather than two new full databases retained every two hours.
Copies required while a cycle is in progress remain until success is proved.

Every retired database must be an exact immutable-row multiset subset of the
**surviving recovery copy**, including raw payloads, snapshots, player/fixture
versions, forecast distributions, outcomes and the SDP evidence ledger. Schema
differences, unknown tables, missing rows, unresolved locks/WALs and linked paths
fail closed. Proof comparison uses bounded memory and system temporary storage
(C: on this host). It never opens a source database for writing.

Registered forecast headers are inspected in full, including hashes and paths inside
serialized component provenance. Publication/replay manifests outside Git and
operational verification metadata are included with fail-closed traversal.
Frozen config/results/document references and
`forecast-source.duckdb` are protected. These immutable replay sources are not
ordinary rolling backups and can exceed the one-copy limit. Legacy Dashboard
generations without explicit database attribution require manual review.

Original reports, logs, before/after inventories and staging diagnostics remain.
Embedded generation receipts/manifests are copied byte-for-byte outside an old
generation before that generation is removed. Small historical receipt folders
therefore remain visible; the retention limit applies to their multi-gigabyte
payloads, not to the number of diagnostic directories. Capture health continues
to see failures and successes rather than having failures erased by cleanup.

No pruning occurs after a failed refresh or failed configured publication.
Retention failure is separately recorded while preserving the true local refresh
status and causes a nonzero process exit. An unverified recovery copy cannot
replace the previous one. No scheduler change or second scheduled task is needed;
the existing two-hour/sign-in action imports this updated job.

## September 17 cleanup

Initial cleanup removed 4.87 GB of repository synthetic tests/caches, 1.95 GB of
old export intermediates, and two redundant backups totaling 4.53 GB. The next
bounded pass removed 258 stale synthetic pytest directories (31.67 GB), thirteen
certified redundant databases (27.78 GB), and seven old Dashboard generations
(1.80 GB). Every database deletion had full raw/ledger retention proof; copies
with publication hash references additionally retained byte-identical protected
peers. Original capture and invalid-run receipts were preserved.

A final certified pass retired two more ordinary copies (4.71 GB), retaining
the existing 2,774,806,528-byte recovery snapshot, byte-identical to the active
database. No new copy was necessary for this manual cleanup. The seven deletion
receipts total **77,304,130,390 bytes**; D: then had **78,005,936,128 bytes free**.
Sizes here are decimal GB, not GiB.

One separately reviewed checkpoint copy then passed all 24 immutable-table
checks and had no retained path/hash references. Removing its 1,588,604,928 bytes
brought the eight manual cleanup receipts to **78,892,735,318 bytes**, with
**79,594,315,776 bytes free** before the local verification refresh.
Five nested replay copies examined in that final pass remain protected by explicit
forecast-source paths, including a byte-identical duplicate whose original path
is itself part of the immutable replay contract.

The requested blanket deletion of `development`, `verification`, and legacy
`runs` is unsafe: these also contain pinned model/research inputs and four legacy
databases whose immutable rows are not all in the current SDP database. They are
explicit exclusions, not silently treated as disposable backups. `.venv`, active
`data`, `predictions`, `plan-server`, `dashboard-plans`, private R2 credentials,
and unresolved old operational lock/WAL files remain untouched.

Detailed byte counts, proof hashes, exclusions and deletion receipts are retained
locally under `data/artifacts/availability-20260917/`. The final verification
record distinguishes this completed cleanup from subsequent routine ingestion.

## Verification and operations

Use the existing scheduled action. For read-only capture health:

```powershell
& D:/Personal/fpl-operations/.venv/Scripts/python.exe -m fpl.jobs.sdp_capture_health `
  --runs D:/Personal/fpl-operations/dashboard-runs `
  --db D:/Personal/fpl-operations/data/sdp-primary-v2.duckdb
```

The 15:00 Bangkok run failed on disk capacity before capture. Cleanup must not
turn that failed receipt into a success: only a genuinely successful later run
can change the latest capture-health verdict. The separate older
`sdp-primary-runs` root was healthy before cleanup. Tests verify byte-preserved
receipts and identical health output before/after retention at a fixed time.

Final local verification at 09:05 UTC reproduced both roots' complete health
reports exactly at their original check times: the older SDP root remains exit 0,
and the Dashboard root remains exit 1 for its preserved disk-full failure.
All 226 frozen model/config/research files and 10 retained forecast files matched
their before-cleanup SHA256 values. The eight-file regression group passed
148 tests, including the requested `test_refresh_dashboard.py`, real DuckDB
immutable-row comparisons, recovery mismatch, concurrent live-DB advancement,
source pins, health preservation, failure paths and R2 temporary cleanup.
Ruff, changed-file formatting and strict mypy (three source modules) passed.

R2 publication is separate: the first public generation is uploaded and its HTTP
CORS checks pass. Browser verification, frontend cutover and the optional scheduled
R2 argument retain their own readiness
requirements in `r2-dashboard-activation-2026-09-17.md`.
