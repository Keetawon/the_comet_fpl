# Interrupted unchanged capture recovery — 2026-10-05

After the successful September 28 publication, run
`dashboard-20260928T042009Z-c18c804f` stopped during capture. The original receipt
remains RUNNING/capture; PID 13508 has exited. Its last log entry is an FPL
element-summary request at 11:22:56 Bangkok. The termination cause is unproved.
Subsequent invocations refused its retained checkpoint before new capture.

The operational database and its checkpoint are byte-identical, SHA256
`88ce7e3afecde1c62f5edbb5f96177cf840e8477b0f6d8cea0b3528ba22b3fd3`.
There was no WAL. The repair permits retry only for a dead capture owner with a
receipt bound to this database and checkpoint, no publication or child build,
and exact unchanged database bytes. It recovers a dead capture sidecar with the
existing OS guard and WAL veto, holds a read lease, verifies immutable rows and
losslessly archives the duplicate checkpoint. Original receipts remain untouched;
an additive review binds their hashes and the preservation proof. Changed bytes,
live/unknown owners, WALs and failed archive verification still stop recovery.

This handles both abruptly interrupted RUNNING captures and failed captures
whose database is unchanged. It neither restores a database nor discards a WAL.
The September post-capture export repair and other pre-existing work remain
preserved separately. No models, forecast artifacts or defaults are changed.

The prepared hourly FPL reporting path removes the desktop/SDP
dependency specifically for public injuries, news, prices and official FDR.
It does not move inference, match statistics or outcome scoring to the cloud.
Its cloud activation is pending the specific publishing-credential transfer
approval; no secret has been transferred. The recovery, lock and retention suite
passes 119 tests, and the isolated recovery commit passes 32 tests independently
of the preserved earlier uncommitted September repair.

The repaired refresh `dashboard-20261005T100849Z-134987ee` completed capture
without failures, validated the dashboard, and published all 17 files at
17:56 Bangkok on October 5. Its public generation is
`d0ba3551548616302bd04dadca47bde9492daac9d9b75339106ac317f6f8acc8`.
Independent HTTPS readback verified every size and SHA256, current source dates,
manifest binding, CORS and no-store pointer. Capture inventory contains all 50
completed current-season fixtures with no missing matches or identity
contradictions; this does not waive incomplete provider core fields.
The September 14 GW5-9 forecast remains byte-identical, and publication status
still marks forecast rollover required. All 183 protected artifact hashes and
pre-existing owner edits were verified unchanged after publication.
Retention completed at 18:00 Bangkok and the process exited zero. The next-cycle
operational lock, idle-database and recovery preflight passed at 18:01 without
starting a capture or allocating another database copy. The existing task remains
enabled with its next trigger at 19:00 Bangkok; this proves retry readiness, not
an additional automated capture.

Recovery evidence and test logs are retained privately under the root checkout's
`data/artifacts/pipeline-recovery-20261005/` directory.
