# Squad Draft current-forecast binding

Squad Draft's direct manager import was blocked because its default forecast came
from the retained platform optimizer plan (GW3–7), while the running Plan Server
and current published forecast both covered GW4–8. The manager capture correctly
planned GW4; the client correctly rejected the mismatched GW3 context.

Ordinary Squad Draft now selects `summary.latest_run`, reconciles its identity,
season, timestamp and horizon with the player manifest, and uses that run's
published player values. It continues to take structural squad rules from the
exact audited platform plan, requiring the same season. Forecast and rules
provenance are labelled separately. Missing current player data or mismatched
metadata fails closed instead of silently reverting to an old optimizer forecast.
No optimizer solve, forecast regeneration, model change or data republication is
needed to fix this binding.

Explicit optimizer and captured-manager handoffs remain pinned to their original
plan and forecast. Saved drafts remain bound to their original forecast; opening
a newer forecast does not rewrite their browser storage. A direct manager import
replaces the draft only after validating all 15 stable codes, positions, clubs,
prices, planning GW and structural squad rules. Failed imports preserve storage
and the currently displayed selection.

Local verification replayed the latest retained private capture through
`POST /manager-team/members/capture`, without fetching a provider or printing
manager identity. All 15 members matched the current 654-player forecast
`660302216bdfac866003ef50e8077953bb297ff87412252bc796f27c8adbdd2f`,
which starts at GW4. Synthetic UI regressions cover rollover to GW4 and GW5,
unavailable/mismatched current forecasts, failed-import preservation and exact
historical handoffs. Forecasts, retained plans and frozen research stay unchanged.

After updating the existing local dashboard build, reload
`http://127.0.0.1:4173/#squad-draft` (without an optimizer handoff fragment), check
the displayed forecast GW, and use **Fetch current team**. Weekly operation still
requires a current published forecast and the Plan Server's explicit `--forecast`
argument to agree; this repair does not relax that requirement.
