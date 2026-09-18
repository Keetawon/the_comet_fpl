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

### Completed live verification

The unchanged existing task was started on demand at 12:55 Bangkok on Sept 18;
its scheduled 13:00 trigger did not create a second worker. Full capture completed
at 13:39, R2 publication at 13:48 and retention at 13:51. Task Scheduler subsequently
reported Ready / result 0, with the next trigger at 15:00. Both PID sidecars and the
operational database WAL were absent after completion. This is a verified on-demand
execution of the registered action, not proof of a future unattended trigger.

The complete FPL capture covered 662 endpoints. Capture health was healthy with no
current identity/schema failures: all 40 current fixtures were captured, but only
36 were SDP core-valid. Four existing incomplete fixtures retain fallback; successful
requests do not manufacture missing provider fields. SDP revisions and workload
capture completed through the existing paths.

Independent public downloads verified pointer/file hashes and CORS for the website.
Bogle's current FPL price was 4.6m and Haaland's 15.6m across all 28 published vintages;
these are current display prices, not replacements for frozen forecast prices.
All 80 current team-match goal classifications were complete. The Leeds 4-1 Newcastle
fixture showed Leeds 2 open-play + 1 evidenced set-piece + 1 own goal received,
Newcastle 1 open-play, and zero unclassified goals. Source-bound display accounting
remains separate from provider core validity.

Verification passed 156 focused/health tests, Ruff and changed-file formatting for
six Python files, and strict mypy for four source modules. Post-run hashes matched
all 226 pre-task protected files and all ten forecast artifacts. The bound existing
plan was reused; no forecast, optimizer plan or model was regenerated.

Detailed local receipts and public-download checks are under
`data/artifacts/refresh-recovery-20260918/` (ignored operational evidence).

### Storage limitation identified during verification

Retention completed and removed a 3.06 GB duplicate, but COMPLETE means that its
eligible cleanup finished, not that total storage is bounded. Afterwards there were
ten database copies in dashboard-runs (27.66 decimal GB); database copies outside
the active data directory totaled about 49.03 GiB. Drive D had 56.89 GiB free.

Routine-generation references protect the latest two generations. Frozen references
and legacy/manual-review exceptions override this cap. In particular, the current
reference scanner can also pin a run/hash merely because it appears in a tracked
audit document. Duplicate retirement only covers copies matching the newest recovery;
identical older protected copies can therefore remain. No backup policy was changed
in this repair, and no additional manual deletion was performed.

The owner requested discussion of a bounded policy. A separate decision should define
ordinary recovery/export limits, an explicit frozen archive inventory, deduplication
that preserves required paths, and a byte/free-space preflight. Private replay archives
must not be uploaded to the public dashboard bucket. These are proposals, not enabled
retention settings or authorization to discard evidence.
