# R2 publication activation record

The first dedicated R2 dashboard generation was published on September 17, 2026.
The production website has not yet switched to R2. PR #10 remains the review
boundary for the availability fix and optional frontend transport; no main merge
or production deployment was performed during this activation.

**Latest state, 17:58 Bangkok:** the full scheduled refresh passed, its new public
generation was uploaded and verified, and the existing task now includes R2
publication. The first scheduled R2 execution is due at 19:00 and has not yet been
witnessed. Frontend cutover and rendered R2 acceptance remain pending. Earlier
pending statements below record the preceding steps; see the final section for
the current activation evidence.

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
No active database, forecast, model or credential was removed. A later retention
verification defect deleted three historical publication database copies; their
immutable raw rows survive, but exact database bytes are not restored. See the
[incident record](operational-retention-incident-2026-09-17.md). Only that stopped
verification process's resolved cycle lock was subsequently retired with recorded
ownership checks; unresolved legacy database locks/WALs remain untouched.

The existing two-hour/sign-in task is enabled, but its action still lacks
`--r2-config`. Do not claim automatic public updates: CORS and corrected local
rebuild/retention now pass, but finish browser verification and the reviewed
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

## Follow-up connection and publication review

Read-only checks at 10:11 UTC confirmed that the live site still serves the
02:53 UTC Pages export (source known at 02:22 UTC). Remote main at
`cd48fbc200cbf9abc04bfce10f0184b8bbd78795` lacks the shared R2 resolver and workflow
variable wiring. Setting a repository variable alone cannot update that frontend.
That inspection changed no variable, scheduled action, main branch or production deployment.

The supported browser selector again returned `No browser is available` and
discovery returned an empty list. The plugin's read-only diagnostics, repeated
outside the sandbox, found Chrome installed and running but its ChatGPT extension,
native-host manifest and registry binding absent. No substitute browser-control
mechanism or fabricated screenshots were used. The owner was directed to the app's
Settings > Computer Use > Google Chrome installation flow, rather than unrelated
extensions named Native Host. Browser rollout and app settings can affect that UI.
See the [official browser setup guide](https://learn.chatgpt.com/docs/chrome-extension).
The owner subsequently clarified that this session uses **Codex CLI**, not the
Desktop app. The Settings > Computer Use guidance was therefore inapplicable and
was withdrawn. No Desktop installation, extension or native host is required to
operate this pipeline. Rendered-browser verification remains unexecuted in the
available session; it is separate from Python ingestion and R2 publication.

Draft [PR #10](https://github.com/Keetawon/the_comet_fpl/pull/10) is mergeable but
its CI run `35207639341` failed the repository-wide format check. Ruff lint passed;
mypy and tests were then skipped. All ten format offenders also fail at immutable
merge base `e10d043a1809a6cad1575dca79c43e632e4598a1` using Ruff 0.16.0; nine are
unchanged by the PR, and the overlapping `dashboard_json.py` already had formatting
debt before its availability addition. Retention/R2 modules are not the offenders.
No unrelated formatting cleanup or green whole-repository gate is claimed.
The exact file list and live HTTP identities remain in
`data/artifacts/availability-20260917/live-r2-frontend-pr-audit-20260917.json`.

## Scheduling and browser verification are separate

The Windows Task Scheduler task is this host's existing cron equivalent. It runs
Python ingestion every two hours and after sign-in; it needs no Chrome extension,
ChatGPT Browser plugin or native host. The R2 publisher also uses the S3 API
directly and has no browser dependency. A browser connection is needed only for
the agent's rendered Dashboard acceptance check before the pending public
cutover. That verification blocker must not be described as an ingestion failure.

The intended automated path is the existing task's capture, validation, Dashboard
generation, optional R2 publication, and retention. No second scheduler is needed.
The static website and R2 remain reachable while the PC is off, but new data can
only be captured when the existing local task can run. At this inspection the task
lacked the optional R2 argument. The final section records its subsequent addition;
a successful scheduled publication must still be witnessed before claiming that
the complete scheduled path has run.

The retained R2-enabled hosted build under
`data/artifacts/availability-20260917/r2-hosted-build` embeds the correct public
pointer but is not served by an existing preview. Existing local listeners serve
bundled or older public builds. The bucket permits the three approved HTTPS site
origins, not localhost: a check with `Origin: http://127.0.0.1:4192` returned no
allow-origin header. Starting that build locally alone would therefore not create
a working R2 browser preview. No local URL is presented as a verified R2 preview,
and no CORS extension or production deployment was made during this inspection.

## Full scheduled capture and rebuild verified

The existing 17:00 Bangkok task completed the full capture and local refresh,
without a second job or `--skip-capture`. Run
`dashboard-20260917T100010Z-3c7f5a31` captured successfully at
`10:45:22.661550Z`, completed its Dashboard at `10:51:24.686986Z`, and finished
retention at `10:53:09.301497Z`. Task Scheduler reported exit 0 and Ready, with
the next trigger at 19:00 Bangkok.

- All 662 FPL capture payloads passed hash, size and count verification, including
  all 659 requested player histories. The latest bootstrap was captured at
  `10:11:36.418414Z`; Joao Pedro is reported doubtful with 75% next-round chance.
- Official fixtures show 40 finalized matches across GW1-4, ten per GW, with no
  partially ended GW. SDP retained all 40; **36 are production core-valid**.
  Fixtures 7, 19, 20 and 28 retain `SDP_INCOMPLETE_FALLBACK`. All 14 revision
  requests succeeded, but none produced a new payload version. Source knowledge
  times were preserved; request success does not remove those field limitations.
- The local preview and built distribution match all 16 generation files. All
  17,284 published forecast records retain their original frozen fields and
  fixture xP. All 226 baseline model/config/research hashes and ten forecast-file
  hashes also match. The plan was reused and `forecast_regenerated` is false.
  Forecast GW5-9 remains dated September 14; fresh observations do not change its date.
- Retention completed with its receipt intact, removing 3,625,496,003 bytes of a
  verified duplicate and an older ordinary generation. D: had 81,896,402,944 bytes
  free. The new ordinary recovery is 2,836,934,656 bytes, SHA256
  `7160f628bf0deb99d4b8f5dd24ab1c99b827f453796d25b5abcc2957278edff1`.
  Three other database copies remain explicit source/scientific exceptions,
  including two copies of the previous pinned source hash. This is not a claim
  that only one database copy exists across all retained evidence.

The independent proof is
`data/artifacts/availability-20260917/full-refresh-verification-20260917T105405Z.json`;
the actual task check is
`data/artifacts/availability-20260917/full-refresh-scheduler-verification-20260917T105507Z.json`.
Prior failed capture and retention-incident receipts remain unchanged.

## New generation published; existing task connected

Standalone publication of that completed generation finished successfully at
`10:56:58.586321Z`, with all 16 uploaded objects verified before the pointer update.
The new generation is
`cffa2e58622d9d47e00b1e2126b7179e666079d4002bed5f72b8224b17eb7046`.
Its receipt is
`D:/Personal/fpl-operations/dashboard-runs/r2-20260917T105452Z-a988c066/receipt.json`.
The preceding immutable generation remains retained. At `10:57:27Z`, HTTPS
verification passed all 51 CORS checks and three downloaded payload SHA256 checks,
with a stable pointer and `no-store` caching. Evidence:
`data/artifacts/availability-20260917/r2-cors-verification-20260917T105727Z.json`.

After this full-cycle and publication verification, the narrowly scoped scheduler
change was approved and executed at `10:57:55.5619537Z`. It appended only
`--r2-config "D:/Personal/fpl-operations/r2/publication.json"` to the existing task.
Before/after XML checks prove that its triggers, settings, principal, executable
and working directory were preserved. It remains enabled with its two-hour and
sign-in triggers. The evidence is
`data/artifacts/availability-20260917/scheduler-r2-enabled-20260917T105755Z.json`.
No new task, browser installation, GitHub variable or frontend deployment was used.

This resolves the earlier rejected storage-automation step with independently
verified capture and publication evidence, while leaving the separate browser
acceptance and frontend cutover pending. The next scheduled attempt is 19:00
Bangkok. No subsequent scheduled publication receipt has been observed yet; the
successful standalone upload is not mislabelled as that future run. Existing
failure receipts remain intact and no frozen forecast was regenerated.
The final post-publication check again matched all 226 model/config/research files
and ten forecast hashes; its receipt is
`data/artifacts/availability-20260917/post-r2-freeze-verification-20260917T105953Z.json`.
