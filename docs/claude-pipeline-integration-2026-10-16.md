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

The running desktop refresh is allowed to finish before its checkout changes. The
new cloud path updates only provisional player/team observations and their observed
team form. It carries forecasts, finalized histories, rest evidence and monitoring
data forward without recalculation.
