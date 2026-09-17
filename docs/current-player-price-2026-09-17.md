# Current FPL price reporting

The Players table displayed De Cuyper's frozen forecast price of **48 tenths
(£4.8m)** even though the retained FPL bootstrap already reported **49 tenths
(£4.9m)**. Availability had a current reporting overlay; price still read the
forecast-owned `now_cost`. Re-ingestion alone could not repair that display.

The official FPL API was checked at `2026-09-17T15:03:11.876135Z`: player code
`465730`, element `115`, `now_cost=49`. The existing complete retained capture
`3cae1acf-8de7-4d6e-97c0-7f70a9d2342c`, captured at
`2026-09-17T13:40:49.988338Z`, already contains the same value. Its bootstrap hash
is `b9863c9417dfc101933af2ff76b460d91cb09b72088cfdfc1429a5482868a58f`.

## Correction and isolation

Each dashboard player may now carry `current_price`, an additive FPL reporting
object with season, stable code, positive integer-tenths price (or null), actual
capture time, capture ID, source hash and `current_reported_not_forecast`
semantics. It comes from the same validated retained bootstrap as current
availability. Invalid identities, invalid prices, inconsistent captures and
post-export timestamps fail closed. Missing prices are not zero-filled or
borrowed from an older capture.

Players uses current price for the table, numeric sorting and price bounds.
Summary player cards use it too. Tooltips expose the source time, and captured
tables distinguish current FPL prices from their forecast vintage. Legacy or
missing current prices stay unavailable. Optional forecast-vintage AI rendering
is disabled when current-price bounds select the Players scope.

The original `now_cost`, xP, PMFs and registered forecast files remain unchanged.
Plan Builder, Squad Draft, Next GW plans and the deadline-price analytics view
retain their existing forecast prices and budget/matching rules. Shared filters
label that price basis explicitly. Current price is not a manager-specific selling
price, and does not silently update a saved plan's affordability.

## Subsequent updates

The existing `build_sdp_dashboard` reporting step now adds both current overlays.
The existing two-hour `refresh_dashboard --r2-config ...` job therefore carries
subsequent captured FPL price changes through validation, public sanitization and
the immutable R2 generation/pointer publication. No additional scheduler, model
run or per-player override is needed.

For this correction the retained bootstrap already agrees with the live API, so
the existing refresh can use `--skip-capture` and the verified existing optimizer
plan. This rebuilds reporting from retained evidence without claiming a new
capture time or regenerating a forecast. The regular scheduled task continues
to capture normally. Browser tabs retain their pinned data generation until
reloaded.

Tests cover price changes versus frozen fields, null/invalid/mismatched source
records, current sorting/filtering, planning-price isolation and sanitized package
round trips. The preserved forecast/hash checks and publication receipt establish
operational delivery separately from the code change.
