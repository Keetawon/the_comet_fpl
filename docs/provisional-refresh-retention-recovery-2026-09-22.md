# Dashboard provisional data: retention recovery, 2026-09-22

The public dashboard retained a September 20 data generation. Its GW5 provisional
label correctly described that capture (6/10 completed fixtures); it did not describe
the latest official results. Frontend deployment does not refresh the R2 data pointer.

The September 20 cycle completed capture, outcome attachment, dashboard generation
and R2 publication, then its exact backup-containment query exhausted the configured
1 GiB DuckDB memory budget. The unresolved recovery checkpoint correctly blocked
subsequent cycles before another database copy or capture, including September 22
at 13:00 Bangkok. This was a retention failure, not insufficient disk space.

## Repair

- Partition the existing `EXCEPT ALL` proof into 64 deterministic buckets of the
  first column. Hashes select buckets only: full rows, NULLs and duplicate counts
  are still compared exactly. Memory remains limited to 1 GiB; unknown schemas,
  failed proofs, active writers and WALs still fail closed. Highly skewed data can
  still exceed the limit and must be reported, never accepted without proof.
- Before allocating a new checkpoint, retry retention only for a cycle whose
  capture/local completion and configured public publication already succeeded.
  Require its exact database, recovery path and backup SHA256 under the existing
  cycle lock. Failed/interrupted captures and publications still require review.
- A successful cleanup creates `retention-recovery.json`, bound to the original
  receipt and recovery hashes. The original failure receipt is unchanged. A partial
  cleanup or invalid resolution blocks another full copy. Repeated checks accept
  the verified resolution without repeating that cleanup.

The two recovery checkpoints plus one in-flight limit, two dashboard generations,
scientific pins, 30/20 GiB space guard and R2 public-file allowlist are unchanged.
No model, finality rule, forecast, optimizer or scientific result changes.

## Existing-host operation

The existing scheduled action remains every two hours plus sign-in. Run the same
flow manually when the task is idle; it holds the same cycle/writer locks:

```powershell
cd D:/Personal/workspace/the_comet_fpl/.worktrees/v2
./scripts/comet.ps1 refresh
./scripts/comet.ps1 status
```

Inspect `dashboard-runs/<run>/receipt.json` and `refresh.log` for stage/status.
Confirm `public_publication.status` and `retention.status` are both `COMPLETE`,
then verify the published generation's official finality and source capture time.
Never change a provisional label by hand or remove an unresolved lock/WAL.

Execution evidence and before/after protected-file hashes are retained locally in
`data/artifacts/provisional-refresh-20260922/`; these are not public dashboard assets.

## Completed verification

The repaired cycle `dashboard-20260922T064052Z-ba69ca54` published at 14:35
Bangkok and completed retention at 14:38 on September 22 (exit 0). Public generation
`61aa936ef75704f6876177e82356f64c1c1ce5493946e61d63f7edb87e86dd17`
was independently downloaded with website-origin CORS and file hashes verified.

- GW1–5: 50 finalized fixtures, 100 team sides and 3,206 player-fixture rows.
  GW5: 20 team sides and 658 player-fixture rows. No provisional rows remain in
  these gameweeks; both prediction-versus-actual exports score through GW5.
- Live Players shows `Actual to: 2026-27 GW5` without the provisional notice.
  The September 14 GW5–9 prediction vintage remains explicitly dated and unchanged;
  `next_fixture_gw=6` and `forecast_rollover_required=true` are separately reported.
- All 188 protected source/config/result files and ten forecast artifacts matched
  the pre-task hashes. The original failed receipt is byte-identical. The existing
  bound optimizer plan was reused; no inference or forecast replacement occurred.
- Retention completed with two recovery checkpoints and two dashboard generations.
  Referenced older database bytes were losslessly archived, not discarded.
- The unchanged enabled task automatically started again at 15:00; its capture
  completed successfully at 15:47. Capture health returned healthy/exit 0, with
  46/50 current fixtures SDP core-valid, four existing incomplete fixtures, and no
  identity/schema failures. Provider completeness is separate from FPL finality.
  At verification this subsequent cycle was building its dashboard, not yet claimed
  as a completed publication. Next scheduled trigger: 17:00 Bangkok.

Validation: 168 focused refresh/retention/lock/capture/R2/finality tests passed;
Ruff check passed and strict mypy passed across 243 source files. Changed Python
files passed formatting. The full suite completed with 4,652 passed, four skipped,
18 failed and 17 errors. Remaining failures concern stale frozen AGENTS/model
identity assumptions, unavailable Windows symlink privilege, an older reference
component fixture assuming one minutes model, and a missing live-team table in an
adapter test fixture. These paths were not changed; the full suite is not reported
as green. Repository-wide formatting also flags ten unchanged files. No unrelated
model, scientific pin or environment repair was made to clear these checks.
