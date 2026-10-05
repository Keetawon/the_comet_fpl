# Scheduled forecast refresh

The owner selected **after-match updates and daily freshness checks** on October 5.
The prior two-hour desktop job captured data and exported observations but never
called inference. A current capture could therefore coexist with September 14's
GW5–9 forecast. This change connects the existing forecast/evidence path to that
same job; no model parameters, components or historical verdicts change.

`refresh_dashboard --refresh-forecasts` runs this sequence under the existing cycle
lock: capture FPL/SDP/workload, check forecast policy, generate/register a pair when
due, attach finalized outcomes, obtain the bound platform plan, export/build,
publish through the existing explicit R2 config, and retain recovery evidence.
Without the flag, the command retains its observation-only behavior.
`scripts/comet.ps1 refresh` enables the forecast check for local refreshes.

The policy selects the first official gameweek whose deadline is still future,
with a five-GW horizon clipped at season end. It never derives a GW from the
latest played fixture or forecasts the remaining legs of an already-deadline-passed
GW. A forecast is due when:

- no registered primary exists or its source-comparison receipt is absent;
- its season/horizon differs from the official next GW;
- completed FPL fixture/history content or retained SDP stats/lineups/events changes;
- official fixture assignments, kickoffs or deadline times change; or
- the registered forecast cutoff is at least 24 hours old.

Capture timestamps, current prices/ownership and injury reporting alone do not
trigger repeated simulation. The content comparison excludes market counters and
FDR; injury availability stays a reporting overlay. The underlying team forecast
distributions feed player predictions through the existing composer. The displayed
opponent-strength index is derived from the newly published team forecast; the
browser's strength number is not itself an input to player inference.

The latest complete, same-season FPL player-history capture must be within eight
hours, have matching manifest/payload hashes and cover every captured player.
The scheduling comparison uses only source versions known by its actual check time.
Inference independently applies all existing PIT, identity, source-health and
deadline gates. New or corrected data is never backdated. Within one hour of the
next deadline the job reports `DEFERRED_DEADLINE`; it does not start a simulation
unlikely to finish recording in time. The recorder still checks the actual time.

Each automated cycle isolates its capture receipts under `capture/`. When it
forecasts, the cycle retains `forecast-source.duckdb`, `forecast.json`, both immutable
JSONL artifacts, and a `.refresh.json` content-comparison receipt bound to the
registered primary SHA. Existing retention recognizes the scientific input and
keeps it. The source copy and pair registry keep their existing writer locks.
New output names refuse overwrite. No partial/unregistered pair is selected by
filename or modification time.

Forecast failure is explicit in `receipt.json:forecast_refresh`; the cycle can still
publish updated observed data using the last registered forecast. Its final exit
code is nonzero so the scheduler retries. A failed publication keeps the prior
public pointer. An interrupted inline forecast can use the existing proven-dead
post-capture recovery proof: exact checkpoint binding, no WAL/live owner, complete
capture and preservation of every pre-cycle immutable row. Its forecast artifacts
and input copy are retained, never overwritten or silently resumed.

This remains desktop automation: the owner must be signed in and Windows able to
run. Keep the existing odd-hour two-hour schedule, sign-in catch-up, ignore-overlap,
retry and lock settings. Increase the old two-hour execution limit to four hours:
the capture, simulation, plan and publication now share one cycle. The separate
hourly cloud FDR/injury feed does not run the
model. Activation and the first real forecast/publication must be verified after
committing the clean implementation; source edits cannot be forecast provenance.

Offline verification before activation: 248 focused pipeline, capture, PIT,
evidence, recovery, retention and publisher tests passed. Global Ruff passes and
strict mypy passes all 244 source files. The full test gate is retained separately;
the existing ten-file repository formatting debt was not rewritten. Neither the
configuration/results/model files nor existing forecast artifacts were changed.
