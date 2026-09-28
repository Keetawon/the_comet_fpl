# Published-cycle retention recovery — 2026-09-28

The September 24 17:00 Bangkok cycle published its dashboard successfully, then
stopped during retention. Its original receipt says `COMPLETE / retention` with
retention `RUNNING`. Thirty-one later attempts failed before capture because the
recovery gate recognized completed publication only with phase `finished`.
The scheduler was firing; daily desktop use could not clear this recovery gate.
The precise cause of the original process termination remains unproved.

The owner explicitly authorized this scoped repair in the otherwise protected V2
worktree. The existing retention retry now also recognizes an interrupted
retention phase, requiring a valid positive PID proven to have exited before any
recovery begins. Existing publication, database/path/hash, immutable-row retention,
archive and minimum-copy checks remain in force. The original receipt stays
unchanged; a separate hash-bound resolution records successful recovery.

Once verified, that resolution remains valid even if Windows later reuses the old
PID. A mismatched receipt or checkpoint, active/unknown initial owner, failed
publication or incomplete retention still blocks another cycle.

The unrelated legacy daily SDP database was blocked by a September 7 WAL. Its
original database, WAL and lock metadata were copied with write-excluding file
handles and matching SHA256 hashes. A separate trial used DuckDB's native WAL
replay, then the original was recovered under the operational guard. All 44 tables
were compared exactly, including duplicate and NULL rows, against the recovered
trial. No WAL was manually discarded. The original bytes and recovery receipts
remain in the private local incident directory.

The existing legacy scheduled task was then run on demand. It finished at 10:39
Bangkok on September 28 with `healthy=true`, `consumer_ready=true`, verified
staging and no failures. All 50 completed fixtures were captured; 46 remain
core-valid and the same four incomplete fixtures retain fallback. Identity and
schema failures are zero. Task Scheduler reports Ready, last result 0, and the
unchanged next daily trigger at 07:00 Bangkok on September 29.

The homepage freshness warning is a separate main-branch frontend change. It uses
the existing eight-hour capture-health limit, keeps forecast dates separate, and
does not expose operational paths, private drafts or credentials.

## Validation and evidence

The focused refresh/retention/process-lock suite passes 112 tests. The final
PID-reuse check passes all 42 refresh tests. The independently prepared commit,
excluding the earlier dirty September 24 repair, passes all 25 of its refresh
tests. Repository-wide Ruff lint and strict mypy across 243 source files pass;
ten unchanged files remain outside the global formatting gate.

The full Python run produced 4,678 passed, four skipped, 18 failed and 17 errors.
The 35 failed/error test IDs exactly match the retained September 24 run. These
remain the Windows symlink privilege failures, existing frozen identity checks,
reference-component fixtures and the older adapter fixture. The final focused
PID-reuse checks passed after that full run started. This is not a green full gate.
The separate frontend passed all 777 tests, lint and build; Pages deployment
`36373212449` succeeded for main commit `9a9da66` and the notice was verified live.

## Completed primary refresh

Primary run `dashboard-20260928T030715Z-d475343f` completed at **11:03 Bangkok**
on September 28 with capture exit 0, successful public publication and complete
retention. Capture finished healthy and consumer-ready at 10:53, with all 50
expected completed fixtures retained, 46 core-valid, and zero identity/schema
failures. The same four incomplete matches were rechecked successfully; their
unchanged source versions keep their original knowledge dates and fallback.
The workload capture reported no errors. Both capture-health CLIs report healthy.

The FPL source is dated **10:22 Bangkok**, the SDP export **10:53**, the dashboard
export **10:54**, and public publication **11:00**. Generation
`eded838b63c4bc379da93f69519c522d9c42cdbe3832758f8705a06df5ec8fb5`
was independently downloaded over HTTPS: all 17 file hashes and sizes matched,
the publication receipt binds the manifest, and the pointer has no-store caching
and website-origin CORS. Reloading production shows the September 28 capture
and clears the overdue warning. The latest changed SDP version remains September
24 because the newly checked responses were unchanged; that is not a failed refresh.

Retention preserved two verified rollback copies and retired 4,584,130,575 bytes
only after its existing preservation checks. The earlier recovery also retained
the original incident receipt and archived its older checkpoint losslessly.
A locked next-cycle preflight passed at **11:04** without starting another capture
or allocating a database copy. The normal 11:00 scheduled invocation was observed;
it safely refused overlap while this manual refresh was still publishing. Its
lock refusal is retained as its own receipt and is not relabelled a successful run.
Primary task triggers and retry settings were not changed. This verifies the
completed manual cycle and readiness, not a future unattended success.

All **183** protected model/config/result/forecast hashes still match the saved
baseline. The four root, six V2 and twelve news-note pre-existing changed files
were preserved; the two authorized recovery files retain their earlier edits in
addition to this scoped change. Local main matches the deployed warning commit;
the temporary merged warning branch was removed. No V2 architecture was merged
into main. The September 14 GW5–9 forecast and its reused plan remain unchanged;
GW6 pre-deadline forecast generation is separate from this data refresh.

Private evidence is under `data/artifacts/pipeline-recovery-20260928/`, including
the complete cycle receipt, both capture-health reports, original legacy DB/WAL
copies, recovery proof, exact full-gate comparison, independent public-file
verification, next-cycle readiness and protected-artifact preservation records.
