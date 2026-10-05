# Hourly official FPL reporting

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

Private audit evidence is in `data/artifacts/pipeline-recovery-20261005/`.
