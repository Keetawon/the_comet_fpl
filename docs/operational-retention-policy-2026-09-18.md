# Local recovery and retention policy - 2026-09-18

Owner-approved operational storage policy. No model, forecast, scoring, selector,
optimizer or historical scientific result changes are authorized or made here.

## Limits and recovery meaning

- Keep the latest **two verified recovery checkpoints** for the operational database.
  Selection uses completed receipts, exact source path, SHA256 and timestamps, never
  directory spelling alone. A failed copy cannot displace a verified checkpoint.
- A scheduled refresh creates **one in-flight pre-cycle checkpoint** before any writes.
  Capture and outcome attachment share it; they do not make separate full copies.
  After a successful publication this same copy becomes a retained recovery checkpoint.
  It rolls back the complete cycle to its pre-refresh state. It is not described as
  containing observations captured later in that cycle.
- Keep the latest **two successful dashboard export generations**. Preserve small capture
  receipts, logs, finality evidence and retired export manifests separately.
- An unresolved prior in-flight checkpoint blocks another full copy until inspected.
  It must never cause an accumulating sequence of full copies on every retry.
- Explicit frozen audit/replay evidence is outside the ordinary recovery rotation, but
  local DuckDB copies are compressed. This exception is listed and measurable, not an
  excuse to treat every incident note as a permanent source pin.

## What creates an evidence pin

Structured config/results, retained forecast headers and scientific/source manifests
continue to protect replay bytes. Structured frozen evidence under `docs/data/` is
also retained. Prose in `docs/*.md` no longer pins full databases merely because it
mentions a run or hash. Existing scientific metadata is never rewritten to remove a pin.
A current generation's source references expire when that ordinary generation retires.

## Local audit archives

The standard-library gzip archive is private and adjacent to the original file.
An append-only `.duckdb.gz.receipt.json` records original path, original byte count and
SHA256, archive SHA256, encoding and actual verification time. Compression streams bytes,
verifies the decompressed hash and size, fsyncs/publishes exclusively, then rechecks the
original before removing its uncompressed copy. Failures preserve the original.

Replay requires explicit restoration to the original path. The restore command refuses
an existing destination and verifies exact bytes before publication; original scientific
manifests and recorded historical source times remain untouched.

```powershell
$python = 'D:/Personal/fpl-operations/.venv/Scripts/python.exe'
& $python -m fpl.jobs.audit_db_archive verify --root D:/Personal/fpl-operations --source '<original audit .duckdb path>'
& $python -m fpl.jobs.audit_db_archive restore --root D:/Personal/fpl-operations --source '<original audit .duckdb path>'
```

Do not restore while another job writes the database. After replay, the same compression
command can verify/archive the unchanged restored copy again. Active `data/`, runtime,
forecast and optimizer directories are never compression/cleanup targets.

## Space guard

Check the destination filesystem before allocating a database copy, archive or restoration.
Warn when projected free space is below **30 GiB**. Block before allocation when projected
free space would be below **20 GiB**. The refresh receipt exposes its initial budget check;
individual copies also check current free space. This is a preflight, not a filesystem quota:
unrelated applications and unbounded source growth can still consume the shared drive.
Never delete protected evidence merely to make the check pass. A blocked refresh keeps the
last published dashboard and records its failure rather than claiming fresh data.

## Cleanup safety and public boundary

Pause new scheduled triggers for the one-time maintenance, allow active work to finish,
and hold the existing cycle gate. Refuse unresolved database WAL/writer state. Validate
resolved paths and reject junctions/symlinks before any deletion. Retiring unpinned old
backups requires proof that every retained immutable raw/version/ledger row occurrence
survives in a verified recovery. Unknown schemas or failed proofs remain preserved for review.

Only intended dashboard exports can reach R2: the existing fixed public-file allowlist and
sanitizer are unchanged. Audit archives, DuckDB databases, restore receipts, private plans
and credentials are never uploaded to the public bucket by this workflow.

## Verification and cleanup record

Synthetic tests cover rotation, source pins, pre-cycle reuse, copy failure, low-space
boundaries, compression corruption, restore identity and public-file rejection. The actual
cleanup totals and retained checkpoints are recorded below after safe execution.
