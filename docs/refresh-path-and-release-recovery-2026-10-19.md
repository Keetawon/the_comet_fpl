# Full refresh and release recovery — 19 October 2026

The owner requested a full refresh after approving the Summary briefing order.
The prior desktop action still used the removed `.worktrees/v2` working directory
and preview path. Its 17 October capture, forecast registration and optimizer
completed, but export failed because that preview manifest no longer existed.
Later scheduled starts failed before Python could run.

The existing task now runs from `.worktrees/sdp_test`, which owns the operational
Python installation, and builds the main checkout's `dashboard/public` preview.
Before/after task XML verifies that only those two paths changed. Triggers,
principal, retry settings, overlap policy and forecast/publication arguments are
unchanged.

Before restarting, manual review verified the failed cycle's original receipt,
exited process, completed history capture, registered forecast and bound plan.
An exact schema/multiset comparison proved that all its immutable records remain
in the active database. The existing audit archiver preserved its checkpoint
losslessly and verified both compressed and decompressed hashes before removing
the duplicate uncompressed file. Its original failed receipt remains unchanged;
all 42 prior forecast artifact hashes match. Private review and task evidence is
retained under `.tmp/full-refresh-20261019` and the original operational run.

The frontend deployment also exposed a compatibility defect introduced by
`7bbddb9`: changing the set-piece description made the validator reject the
already-pinned immutable SDP companion, although its original data and metadata
were valid. Validation now accepts exactly the current catalog or the previously
published catalog with its original set-piece description. Every other catalog
field and every numeric/provenance validation remains enforced. New exports keep
the current description. No historical file or classification is rewritten.

The regression checks accept both known descriptions without mutating either
document, reject other description/source/unit/provider/semantics changes, and
confirm that invalid numbers still fail for a legacy document.

All 74 SDP statistics and goal-pattern tests pass. Changed-file lint, formatting
and strict type checking pass. The exact 15,006,678-byte pinned companion with
SHA256 `3579bff9314471e9a9174072d1813523a00994fc2cf5592fd7303e231f699c49`
also passes the complete validator without changing its bytes. The initial
frontend deployment passed its dashboard test/lint/build job before encountering
this legacy companion error. Deployment run `39258755248` passed with the
compatibility fix and the requested Summary briefing order. Live HTTPS assets
were verified; no browser session was available for visual inspection.

The refresh also exposed a misleading rollover warning: a forecast for GW8-12
was treated as outdated because the final GW7 fixture had not ended. Rollover
now requires the forecast start to be behind the next unfinished match scope.
The browser applies the same directional guard when reading older immutable
receipts. GW7 finality warnings and pending accuracy scores remain unchanged.
Regression cases cover forecast starts behind, equal to, and ahead of that
unfinished gameweek. This changes only freshness reporting, not predictions.
