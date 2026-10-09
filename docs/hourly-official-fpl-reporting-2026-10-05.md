# Hourly official FPL reporting

## October 9 activation — complete

The owner explicitly approved transferring the existing R2 publishing credentials
to GitHub's encrypted `production-fpl` environment. The environment now permits
only the `main` branch. The three required secrets and bucket variable are
configured, and `official-fpl-refresh.yml` is **active** with its existing
minute-17 hourly schedule. No secret values entered Git, logs or public artifacts.

The first cloud run, [37967569068](https://github.com/Keetawon/the_comet_fpl/actions/runs/37967569068),
completed successfully. Its capture at **2026-10-09 17:37:39 UTC** contains 667
players and 760 fixture sides. Independent HTTPS verification confirmed the
new capture, production-origin CORS and `Cache-Control: no-store`.
This run was manually dispatched to test the now-enabled scheduled workflow;
an actual cron-triggered run has not yet been observed at this verification.
The October 5 pending-activation account below is historical, not current status.

## October 5 repair and implementation

The public dashboard stopped at its September 28 publication because a subsequent
desktop run died during capture. Its recovery checkpoint then blocked every later
refresh before new data could be loaded. The previous September repair covered
interrupted retention, not this earlier capture phase.

The owner authorized hourly cloud updates on October 5. The lightweight
`official-fpl-refresh.yml` workflow captures official bootstrap and fixtures at
minute 17 of every hour, independently of the desktop, DuckDB, SDP and inference.
GitHub schedules can be delayed; this is an hourly schedule, not an exact delivery
SLA. The existing full SDP and outcome refresh remains a separate desktop job.

The cloud job uses the existing retrying FPL client, requires all 20 clubs, 38
gameweeks, 380 fixtures and a complete-size player pool, and rejects season skew,
duplicate identities, invalid flags and invalid FDR. Players use permanent codes;
fixture sides require same-season fixture, permanent club/opponent and venue.
Missing values remain unavailable. It projects only public reporting fields.

It retains immutable compressed source payloads and the reporting document under
`live-fpl/captures/<capture-id>/`, verifies their bytes by reading them back, then
conditionally replaces `live-fpl/current.json` with `Cache-Control: no-store`.
An ETag condition prevents concurrent overwrite, and older timestamps cannot
replace newer ones. Failure before publication keeps the previous document.
The standard public-dashboard sanitizer and generation pointer are unchanged.

The browser pins one validated reporting capture for its page session and applies
only current availability, current price and official FDR through the shared
Players/Fixtures loaders. Summary, player/team analytics, player fixture chips,
the gameweek matrix and the EPL portion of All competitions use these loaders.
Forecast prices, xP, PMFs, player components, optimizer inputs and stored artifacts
are untouched. No current value is copied into a historical model feature.
Newer embedded reporting is retained when the independent capture is older.

The site labels the independent FPL capture time on every page. It warns after
three hours; a Check latest action reloads the page without mixing forecast
generations. SDP/outcome freshness and forecast dates remain separately visible.
Local tools and unapproved origins make no new network request. A missing or
invalid hourly feed leaves the published dashboard usable with an explicit notice.

The workflow reads credentials only from the `production-fpl` GitHub environment,
restricted to `main`. It has repository read permission, one publication
concurrency group and a ten-minute limit. Raw public captures are also retained
as 30-day workflow artifacts. Credentials stay outside source control, public
files, artifacts and logs; the runtime profile is temporary and owner-readable.

## Verification

The first publication captured 667 players and 760 fixture sides on October 5 at
17:15 Bangkok. Compared with September 28, there were 10 substantive availability
or news changes and 26 price changes. The official fixture API's FDR values at
that capture matched the previous publication; no FDR change is invented.

Focused Python publication/current-availability tests pass 55 checks, including
failed readback, timestamp rollback, concurrent publication, season/identity
errors and NULL semantics. The frontend suite passes 787 tests, and its build and
lint pass (nine existing lint warnings). Repository Ruff and strict mypy pass;
ten existing files still fail the global formatting gate.

The full root Python gate completed with 4,463 passed, four skipped, 67 failed
and 22 errors. Failures include the retained frozen-input/source-identity
assertions, Windows symlink privileges, reference-component fixtures and a local
stub connection failure. It is not a green full gate. The changed Python paths
pass their focused tests; the recovery branch separately passes 119 focused
checks and 32 checks against its isolated commit. All 183 protected artifact
hashes and the pre-existing owner edits were verified unchanged.

## Activation status

The first public reporting capture is published and verified over HTTPS with
the production origin's CORS header and no-store caching. The frontend deployed
successfully in Pages run `37298527051`. Production browser verification confirmed
Konsa's October 5 report (doubtful, 75%, unspecified injury) and the new Summary
availability reports. All competitions starts at October 5 and the gameweek
matrix starts at GW6. Both expose official FDR. The scheduled workflow remains
disabled pending its credential configuration.
Activation is pending specific owner approval to transfer the existing publishing
credentials to the encrypted main-only GitHub environment. Automatic approval
review rejected that transfer pending explicit authorization. No credentials
have been transferred and the hourly workflow is not yet enabled on main.

The repaired full refresh published generation
`d0ba3551548616302bd04dadca47bde9492daac9d9b75339106ac317f6f8acc8`
on October 5 at 17:56 Bangkok. Independent HTTPS verification matched all 17
files by SHA256 and size, the no-store pointer, production CORS and manifest
binding. Its FPL source is 17:22 Bangkok, SDP export 17:48 and dashboard export
17:49. The next fixture GW is 6; finalized and scored outcomes remain GW5.
The September 14 GW5-9 forecast is unchanged and still carries its own date and
rollover-required flag. A current reporting capture does not renew a forecast.
Retention finished successfully at 18:00 Bangkok; the next-cycle lock and recovery
preflight passed without starting another capture or database copy. The desktop
task remains enabled, with its next trigger at 19:00 Bangkok.

Pages run `37299448249` deployed the final wording successfully after retrying a
transient GitHub HTTP 500 on the pinned release download. Production browser
verification confirmed the final label and today's embedded FPL reports; the
full-dashboard overdue warning has cleared.

Private audit evidence is in `data/artifacts/pipeline-recovery-20261005/`.
