# Post-capture dashboard interruption recovery — 2026-09-24

The September 22 17:00 Bangkok cycle completed capture at 17:52, then stopped
during public dashboard packaging. Its receipt remained `RUNNING / dashboard`.
Windows records sleep at 17:56:52 and wake at 20:10:47; the existing task has a
two-hour execution limit. This is consistent with termination across sleep, but
the exact terminating event is not established. No Python crash was recorded.

The unresolved pre-cycle checkpoint correctly blocked subsequent refreshes,
including September 24 at 13:00. The last complete capture/export/R2/retention
cycle finished September 22 at 16:01 Bangkok. The prior retention-memory repair
did not cover an interrupted export that had never reached public publication.

## Recovery boundary

The existing refresh entry point now handles this narrow post-capture case under
its existing cycle lock. It requires all of the following:

- A policy-v2 `RUNNING / dashboard` receipt with a recorded capture exit code of
  0 or 1, and no public-publication attempt. Exit 1 can describe existing SDP gaps;
  it cannot substitute for complete FPL history.
- The original PID is positively known to have exited. Active, reused, malformed
  or inaccessible process identities remain blocked; elapsed time is insufficient.
- No optimizer or frontend-build subprocess was started. Their log markers keep
  recovery blocked because a child process can outlive its parent.
- The exact database, recovery path and backup SHA256 match the original receipt.
- A complete FPL player-history capture exists between the cycle's start and its
  recorded transition to dashboard work.
- No unresolved WAL/writer state, and an exact schema/multiset proof that every
  original immutable raw/version/ledger row remains in the active database.

A read lease excludes database writers throughout proof and archiving. An
append-only `interruption-review-*.json` binds the original receipt hash, PID,
checkpoint hash and row proof. The existing local audit archiver then preserves
the checkpoint losslessly, verifies compressed and decompressed bytes, publishes
its receipt, and retires only the redundant uncompressed file. A failure preserves
the checkpoint. The original failed receipt, logs and partial export are unchanged.

Only then may the normal flow create a new pre-cycle checkpoint and run a fresh
capture/export/publication. This does not label the interrupted run successful or
publish its partial export. Failed captures, ordinary failed jobs and interrupted
publications remain blocked for review. The two verified recovery copies plus one
in-flight copy, ordinary two-generation retention and disk guard remain unchanged.
Lossless interruption archives and partial exports are retained as incident evidence.

Checkpoint hashing now streams through the standard library rather than loading
the full multi-gigabyte database into Python memory. No new dependency is added.

## Verification

The focused refresh, retention, archive and process-lock gate passed **127 tests**.
It includes successful recovery followed by fresh capture, exact archived bytes,
unchanged original evidence, and refusals for active/unknown PID, failed capture,
publication/subprocess already started, wrong identity/hash, missing history, missing immutable
rows, WAL, unknown policy versions and archive failure. Repository-wide lint,
changed-file formatting and strict typing across all 243 source files pass.

The existing task was started on demand at 14:02 Bangkok. Recovery proved all
546,720 immutable row occurrences across 24 tables. The 3,736,875,008-byte rollback
checkpoint is preserved in a verified 694,513,381-byte local archive. Its original
SHA256 is unchanged, and its original failed receipt and partial export remain.
The new run began fresh capture at 14:05 under the normal writer lock.

The full suite run produced **4,666 passed, four skipped, 18 failed and 17 errors**.
Its exact 35 failed/error test IDs match the retained September 22 run, with zero
differences. These concern Windows symlink privilege, existing frozen AGENTS/model
identity assumptions, the older reference-component minutes fixture and a missing
live-team table in an adapter fixture. The final focused run additionally verifies
three conservative policy/subprocess refusal cases added during review. Global
formatting still flags ten unchanged files. No unrelated gate repair was made.

## Completed existing-host execution

Run `dashboard-20260924T070216Z-3b55d862` completed successfully at **15:03 Bangkok**:
capture, local export/build, R2 publication and retention all passed. The fresh FPL
capture contains all 670 required endpoints, including 667 player histories, with
actual source time `2026-09-24T07:17:16.311738Z`. Capture/staging finished healthy
at 14:49 with zero identity/schema failures. All 50 finalized fixtures are retained;
46 remain SDP core-valid and the same four incomplete fixtures retain fallback.
All 14 revision requests and the required incomplete-history rechecks succeeded.
Workload capture reported no errors. Unchanged SDP responses retain their original
knowledge timestamps; successful rechecking does not relabel their knowledge time.

Public publication finished at **14:58 Bangkok**, with all 17 files verified and
generation `ecd7a6185e2507427196def54c8dab4c980b2061c4db42405ce4ac3cc00ce478`.
Independent HTTPS downloads verified the pointer, website-origin CORS, no-store
pointer caching, and five public file hashes/sizes. GW1–5 contain 50 finalized
fixtures, 100 team sides and 3,206 player-fixture rows, with no provisional rows;
both prediction-versus-actual exports score through GW5.

Retention completed with two verified raw recovery checkpoints. It archived one
older checkpoint and retired 847,386,115 bytes of obsolete export data. The exact
interrupted checkpoint archive, original receipt, logs and partial export remain.
All 188 protected source/config/result files and ten forecast artifacts matched
their pre-task hashes. The existing bound plan was reused; no forecast was generated.

The scheduler reports **Enabled / Ready / last result 0**, unchanged PT2H and
sign-in triggers, with next run **17:00 Bangkok**. A locked read-only readiness
check passed the next-cycle recovery preflight without allocating another copy or
starting another capture. This verifies the on-demand execution of the existing
task and its readiness, not a future unattended run.

The September 14 GW5–9 forecast remains unchanged and explicitly dated.
`next_fixture_gw=6` and `forecast_rollover_required=true` remain visible; GW6
forecast generation is a separate pre-deadline operation.

Local evidence is retained under `data/artifacts/pipeline-recovery-20260924/`:
`before.json`, `pytest-focused.log`, `pytest-full.log`, `mypy.log`,
`capture-health-after.json`, `after-public-verification.json`,
`readiness-after.json` and `scheduler-after.json`. This repair changes no model,
scoring, optimizer semantics, public-file allowlist, task timing, sleep behavior
or frozen research record.
