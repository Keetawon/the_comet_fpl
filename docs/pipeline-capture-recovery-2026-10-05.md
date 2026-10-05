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

The independent main-branch hourly FPL reporting path removes the desktop/SDP
dependency specifically for public injuries, news, prices and official FDR.
It does not move inference, match statistics or outcome scoring to the cloud.

Recovery evidence and test logs are retained privately under the root checkout's
`data/artifacts/pipeline-recovery-20261005/` directory.
