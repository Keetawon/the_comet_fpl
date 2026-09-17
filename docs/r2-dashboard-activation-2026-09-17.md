# R2 publication activation record

The first dedicated R2 dashboard generation was published on September 17, 2026.
The production website has not yet switched to R2. PR #10 remains the review
boundary for the availability fix and optional frontend transport; no main merge
or production deployment was performed during this activation.

## Verified storage publication

- Bucket: `the-comet-dashboard`, Standard storage, confirmed in the owner's UI.
- Credentials: the owner entered bucket-scoped object read/write keys into the
  interactive local helper. Its owner-only SDK profile and non-secret publication
  config are outside Git. Credentials were not printed or placed in `.env`,
  browser assets, reports or GitHub variables.
- A bounded authenticated listing returned HTTP 200 with no existing objects.
- The owner connected `data.thecometfpl.com`; normal HTTPS verification passed.
- Successful publication finished at `2026-09-17T07:54:42.415104+00:00`.
- Receipt: `D:/Personal/fpl-operations/dashboard-runs/r2-20260917T075225Z-9f98789e/receipt.json`.
- Status: `COMPLETE`, 16 verified public files, `already_current: false`.
- Generation: `674fb2aa1d7937039382f86c94a814ed939a38ced6ac9c46f36008456c36b927`.
- Public data manifest: `ab0fed1ecc4b217c346a09597a5571fd2966915b4a7617698064de83b0a20244`.
- The pointer was conditionally created only after the immutable uploads passed
  read-back content, encoding, metadata and inventory checks. No earlier pointer
  existed. Original local generations and prediction artifacts were not replaced.

The source remains the retained September 17 04:11 UTC FPL capture and the
September 14 GW5–9 forecast vintage. Publication time does not become source
knowledge time. João Pedro's separate current report is doubtful, 75%, with its
actual source time; published xP and forecast-time status remain unchanged.

## Temporary storage correction

The first publication attempt failed with `PublicDashboardPackageError` before
any pointer write during local disk exhaustion. Its failed receipt remains at
`dashboard-runs/r2-20260917T074039Z-ae39e286/receipt.json`. A parallel isolated
frontend build explicitly failed with `ENOSPC` while copying public data.

Only redundant scratch copies created by this session were removed, reclaiming
about 400 MB. Original generations, forecasts, raw captures and receipts remain.
R2 preparation now uses system `TemporaryDirectory` storage (C: on this host) and
removes its own sanitization copies on success or failure. It retains the same
source validation, compressed bytes, inventory, pointer contract and receipts.
The final six-file backend regression suite passed 75 tests, including temporary
cleanup and source-preservation checks. Ruff, formatting and strict mypy passed
for the changed module/tests. The previous 583 frontend tests remain applicable;
no frontend source changed during this storage correction.

An isolated hosted R2-enabled build also passed with public-directory copying
disabled: its runtime intentionally requests remote R2 data. It did not replace
the existing local preview or deploy the website.

## Capacity incident and subsequent owner-authorized cleanup

The normal operational pipeline still uses D:, which had approximately 456 MB
free. The current DB is 2,774,806,528 bytes. Each normal refresh retains a full
pre-capture backup and a full pre-outcome backup. The newly measured completed
generation is 782,113,860 bytes. Together this implies at least **6.33 GB per
cycle**, before live DB growth, WAL, build copies and other temporary headroom.
The earlier complete cycle retained 6.06 GB. At twelve cycles daily, retention
can grow by tens of GB per day; R2 does not solve local backup retention.

A bounded metadata inventory found 32 immediate full-DB copies totaling 63.61 GB
across `dashboard-runs`, `sdp-primary-runs` and older operational `runs`. The owner
subsequently authorized safe cleanup and automatic retention. Certified redundant
copies and stale synthetic tests/exports were removed, restoring capacity.
The new policy retains one verified post-success operational recovery copy,
two Dashboard generations, and all required frozen source evidence. See
[the storage cleanup and retention record](operational-storage-retention-2026-09-17.md).
No active database, forecast, raw evidence, model, credential, lock or WAL was removed.

The existing two-hour/sign-in task is enabled, but its action still lacks
`--r2-config`. Do not claim automatic public updates: first finish live CORS and
browser verification, verify the recovered operational flow, and complete the reviewed
frontend cutover. Preserve the existing task's locks, backups and identity when
adding its optional publication argument.

## CORS verified; browser and automatic publication pending

After the owner saved the policy, live HTTPS verification completed at
`2026-09-17T09:15:41Z`: **51/51 CORS checks passed** (GET of `current.json`
and HEAD of all 16 immutable files for each of the three approved origins).
The response permits the exact requesting origin and the pointer remains
`Cache-Control: no-store`. An unrelated origin receives no allow-origin header.
GETs of the manifest, publication status and competitive schedule also matched
their pinned SHA256 values. The public pointer did not change during this check.
Evidence: `data/artifacts/availability-20260917/r2-cors-verification-20260917T091541Z.json`.

This is HTTP evidence, not a rendered browser pass. The supported browser runtime
returned `No browser is available`; documented discovery returned `[]`.
No screenshots or browser PASS were fabricated and no production assets changed.
Automatic approval review rejected appending `--r2-config` to the scheduled task
because the required hosted-browser check remained unsatisfied. The attempted
PowerShell command did not execute, so the existing task is unchanged.

The GitHub
`PUBLIC_DASHBOARD_DATA_POINTER` variable has not been activated, and the existing
Pages workflow still deploys only main. The reviewed frontend must be deployed
before the production website can consume R2. The uploaded generation is ready
for that verification, not proof that the live Dashboard has switched.
