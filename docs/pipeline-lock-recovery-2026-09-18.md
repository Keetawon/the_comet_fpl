# Dashboard refresh interruption recovery ? 2026-09-18

The Sept 18 morning refresh failed before capture because the previous process left
both the dashboard-cycle and database-writer PID sidecars behind. The outer lock
was acquired before logging/error handling, so `pythonw` retries produced no receipt.
Windows records sleep beginning Sept 17 23:10:54.498 Bangkok, four seconds after
the last capture log, and waking Sept 18 08:46:45.713. The task has a two-hour
execution limit and an interactive-user principal. Task history was disabled;
exact process termination (logoff, timeout after resume, or other interruption)
is not established. No corresponding Python crash event was found.

## Repair

All three existing lock writers use one standard-library helper: capture,
dashboard refresh and standalone R2 publication. A permanent `.guard` file carries
a nonblocking OS lock which the OS releases on process exit. It must not be deleted.
Under that guard, recovery requires a parseable PID proven absent by the OS;
active/reused PIDs, permission errors and malformed legacy locks remain blocked.
Database paths also require no WAL and a successful read-only DB probe. Existing
DuckDB backup/read/write leases and retention vetoes remain unchanged.

Recovery archives the original lock bytes, SHA256 and actual recovery time under
`<lock>.recovered/` before replacing the sidecar. There is no age-only unlock and
no automatic WAL deletion or recovery. Native Windows inspection opens a read-only
process handle; it never sends a signal to the recorded PID.

Every dashboard attempt writes `receipt.json`, `refresh.log` and `fatal.log` before
acquiring the cycle lock. Atomic receipts expose PID, stage and actual timestamps;
R2/retention explicitly say RUNNING until they complete. Lock/startup failures
therefore remain visible even without a console. Native crash dumps are best effort;
forced termination cannot be promised to produce a Python traceback.

The existing signed-in Windows task still repeats every two hours. No second
scheduler or cloud runtime was added. A sleeping/offline machine cannot capture;
restart recovers only safe abandoned state. Unknown/WAL failures need inspection.
The normal flow still demands a fresh complete FPL player-history capture before
publishing; SDP source incompleteness is reported separately and retains fallback.

## Verification

Synthetic tests exercise exited owners, forced child exit, concurrent reclaimers,
active/unknown/malformed PID refusal, WAL refusal, exact archived bytes, startup
failure receipts, no-console execution, complete capture-to-R2 ordering and repeat
runs. A two-sidecar integration test confirms recovery without DB mutation.
Models/config, frozen forecasts, scoring and optimizer semantics are unchanged.
Live scheduled-task verification is recorded below after execution.
