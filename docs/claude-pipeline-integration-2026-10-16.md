# Claude pipeline integration — 2026-10-16

The owner requested merging Claude's three pushed commits: `5694119` (retain resolved
players when unregistered academy members appear in a club squad), `96765b6` (separate
midweek load from rest verdict), and `245d318` (cloud provisional-preview publication).
The operational integration merges that exact branch into the existing player-model
and mobile-payload release. Main receives those changes and the missing, already-used
rest-report publisher dependencies without importing unrelated model research.

The entire registered player roster remains the reporting population. The Summary
widget still displays its existing top 15 by raw xP; no display-limit change was part
of the source commits. National-team participation remains unavailable and incomplete
schedule evidence still cannot establish full rest. The new nominal-minute load
categories are descriptive and do not alter forecasts, prices or optimizer inputs.

Integration checks identified and repaired four deployment compatibility issues:

- Old immutable schema-v1 rest reports omit both new load fields. They retain their
  original validation contract; partially supplied new fields still fail closed.
- Provisional restatements use compact public read-model bytes and the canonical
  indented manifest, preserving no-op replay after R2 sanitization.
- The reader checks the mobile byte budgets before downloading any payload. The
  publisher rejects a changed base generation before writing objects, and retains
  the existing conditional pointer update during upload.
- The workflow reads main after capture completion, accepts only trusted main-branch
  triggers, and reuses the existing `production-fpl` secret/variable names. No new
  credential is created or copied.

The focused operational integration suite passes 142 checks. Ruff checks pass and
strict mypy passes on 254 source files. The existing full-suite baseline and main
formatting failures documented by the mobile repair are separate from these changes.
Further main integration, full-suite and publication results are recorded at delivery.

The full operational suite completed with 4,655 passed, 156 skipped, 64 failed and
22 errors. All 86 failing node IDs exactly match the independently reproduced
pre-change baseline; no new failures. Main's focused integration also passes all
142 checks. PR #23 merged normally as `ab44a88`; CI still stops on the same eight
pre-existing formatting failures, without a new formatting failure in this PR.

Operational checkout activation to `d881580` held the existing refresh lock after
the running cycle completed. The rest-only publication changed exactly
`sdp/rest_summary.json`; every other public file remained identical. All 667 players
remain included, with 172 witnessed midweek appearances and 495 unknown verdicts.
The live rest cutoff is 2026-10-16 17:22:16 UTC; generation
`03788fb2f5a11588e111f04e47cee471a373da21166886fb4dcf9c51abd646a9`.
`players.json` remains 11,399,271 bytes. Cloud stage-only workflow run 38938901632
succeeded and correctly reported no changes because the preview already matched.

The running desktop refresh is allowed to finish before its checkout changes. The
new cloud path updates only provisional player/team observations and their observed
team form. It carries forecasts, finalized histories, rest evidence and monitoring
data forward without recalculation.
