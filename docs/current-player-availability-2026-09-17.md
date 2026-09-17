# Current FPL availability and dashboard publication

The owner reported that João Pedro looked available on the public Dashboard despite
new FPL injury news. This is a current-status reporting defect, not evidence that
the frozen forecast or a historical evaluation should be rewritten.

## Reconciled evidence

At 2026-09-17 06:34 UTC the official FPL bootstrap reported stable player code
475168 as `d` (doubtful), with a **75% chance for GW5**, and news
`Unspecified injury - 75% chance of playing`. It did not report a confirmed absence.
The news timestamp was 2026-09-16T19:00:09.919929Z.

The complete operational player-history capture already held the same status:
`ad4858b4-4522-4922-9031-39a0ebc1cf3f`, captured
2026-09-17T04:11:29.535067Z, 662 payloads. Its bootstrap payload SHA256 is
`770f970adc3dd66ecdb9ceb566a1ca9bf74696958d07b8ad9a662b8ab9cea88d`.
Twenty players had status or reported-chance differences from the latest primary
forecast, including one change from null to 100% without a status change.

The live site's players JSON SHA256 at 06:37 UTC was
`e18355f17d076373e15d5347b477f2dd8d0b05568102aba2913a04e9c11a47e6`.
It still showed João Pedro as `a` with null chance from the September 14 forecast.
The selected forecast's `as_of` was 2026-09-14T03:39:12.726789Z. Public manifest
`10a2db48d1b2b26c02d1baf02eebffb5df01c3097a17c3bf92b29bed7e270453`
was generated September 17 at 02:53 UTC. A recent export timestamp did not mean
that forecast-owned availability was current.

## Two distinct gaps

1. Player exports deliberately retained the forecast's original availability.
   Refreshing observations therefore could not refresh the status badge. Current
   official status needs separate timestamped reporting provenance.
2. The owner-machine capture/export/build task updates the local Dashboard.
   GitHub Pages consumes a separately pinned sanitized release. The existing
   four-hour task did not upload or activate a public data release.

R2 can close the second gap only when the publisher uploads validated public
generations and the website reads the activated generation. Storage alone cannot
fix the first gap. Raw databases, private plans, manager data and original prediction
inputs must not be published as dashboard assets.

## Owner-authorized two-hour schedule

At 2026-09-17T06:40:10Z the existing `The Comet FPL - SDP primary V2` task was
changed from `PT4H` to `PT2H`. It remains enabled and Ready. The anchor remains
September 16 at 11:00 Bangkok, giving odd-hour runs (01:00, 03:00, …, 23:00).
The next Windows-reported run after the change was September 17 at 15:00 Bangkok.
The preceding 11:00 run returned result 0.

The two-minute owner sign-in trigger, action, account, settings and registration
metadata were verified unchanged. Existing IgnoreNew, retries, two-hour execution
limit, writer locks and backups remain in force. This does not wake a sleeping PC
or run while the signed-in owner session is unavailable. Exact before/after XML and
verification receipt are retained in
`data/artifacts/scheduler-two-hour-20260917T064009Z/`.

## Implemented reporting repair

The operational dashboard builder now adds `current_availability` to a copied,
resealed generation before public sanitization. One complete retained bootstrap
per season supplies exact stable-code identities, original source hash, actual
capture time, official status, next-GW chance and news. Missing current evidence
is null; it is never silently filled from an older player snapshot. Forecast-time
availability fields remain intact.

Players tables/details, Summary and Squad Draft share the reporting badge.
Current filters use the current reporting object; Hide unavailable still means
only official status `u`, not injuries, doubts or suspensions. Legacy packages
explicitly label forecast status with its original date. Current status never
changes xP, PMFs, prices, optimizer inputs or historical scorecards.

The shared Avail filter supports multiple current FPL statuses (Available,
Doubtful, Injured, Suspended, Unavailable, Not available, Not announced and
Unknown / unreported). Selections are ORed together and intersect the other
table filters. Empty selection means all statuses, subject to the separate
Hide unavailable preference, which remains on by default. Explicitly selecting
Unavailable turns that preference off; checking it again removes Unavailable
from the selection. Clear filters restores the defaults. Matching uses the
reported status code, not the chance percentage; missing or unrecognised current
evidence stays unknown. Current-status selections keep the forecast-vintage AI
renderer disabled. The Players page displays 25 rows per page.

The shared Avail badge shows status only to keep table columns compact. The
official next-round percentage stays in its tooltip when FPL supplies it.
Injured (`i`), suspended (`s`) and explicitly reported 0% use a
dark-red background with light text in both themes; doubtful nonzero chances stay
amber. Status text remains visible so color is not the only signal. Missing
chance stays unreported, never inferred as 0% or 100% from status. These display
styles do not change ingestion, availability filters or forecast values.

The new local generation completed at 2026-09-17T06:48:59Z, public manifest
`ab0fed1ecc4b217c346a09597a5571fd2966915b4a7617698064de83b0a20244`.
All 17,284 player records across retained vintages preserve every original field
exactly, with only the new object added. All 226 pre-recorded model/config/result
file hashes and all 10 operational forecast artifact hashes were unchanged.
Local receipts and the actual browser screenshot are under
`data/artifacts/availability-20260917/`. The Windows symlink privilege limitation
occurred; the existing validated-copy publication fallback was used and reported.
This is local verification, not a claim that the hosted site has been updated.

## Publication and checks

The immutable review release is
[`dashboard-data-ab0fed1ecc4b-availability-20260917`](https://github.com/Keetawon/the_comet_fpl/releases/tag/dashboard-data-ab0fed1ecc4b-availability-20260917).
The working-branch pin selects that package and both validated companions. It can
deploy through the existing Pages workflow without waiting for R2 activation;
uploading the release alone does not change the live site.

The full frontend suite passed 583 tests; the final focused backend integration
suite passed 73 tests, including the SDP-provenance privacy regression. TypeScript,
frontend build, targeted Ruff and strict mypy passed. Frontend lint retained nine
existing Fast Refresh warnings. Desktop and mobile browser checks displayed the
75% doubtful status and its real FPL capture provenance with no observed exception
or failed request. Screenshots remain under the local evidence directory above.

The optional R2 transport and its pending remote setup are documented in
[the publication runbook](r2-dashboard-publication-readiness-2026-09-17.md).
