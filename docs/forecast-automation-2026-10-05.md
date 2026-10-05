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
registered primary SHA. The owner explicitly authorized lossless compression and
retirement of older automated replay copies. Retention keeps the two newest
successful automated replay databases uncompressed, independently of the much
more frequent dashboard exports. Older successful automated copies require a
matching forecast-source path/hash and successful forecast/evidence receipts, then
the existing archiver checks the decompressed hash before retiring the original.
Every compressed copy and its verification receipt remain. Legacy, failed and
unregistered copies remain untouched. Restore with `python -m fpl.jobs.audit_db_archive
restore --source <original-forecast-source.duckdb> --root D:/Personal/fpl-operations`;
restoration refuses overwrite and verifies exact original bytes. The source copy
and pair registry keep their existing writer locks.
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
run. The existing odd-hour two-hour schedule, sign-in catch-up, ignore-overlap,
retry and lock settings remain. The execution limit is now four hours because
capture, simulation, plan and publication share one cycle. The separate cloud
FDR/injury feed does not run the model. Its hourly GitHub Actions activation still
awaits explicit authorization to transfer the publishing credentials into encrypted
repository environment secrets; this desktop activation does not enable that job.

## Verified activation and first publication

The existing `The Comet FPL - SDP primary V2` Windows task was updated and started
on October 5. The retained before/after task XML differs only in the added
`--refresh-forecasts` argument and the execution limit (`PT2H` to `PT4H`).
No second schedule or overlapping writer was introduced.

The cycle finished at `2026-10-05T16:16:55.386342+00:00`, with publication and
retention both `COMPLETE`. Windows reports task result `0`, no running instance
and the next check at October 6, 01:00 Asia/Bangkok. A subsequent read-only policy
check returned `NOT_DUE` with no reasons, proving identical current inputs do not
immediately start another forecast. Retention preserved the new replay database;
no older automated forecast copy yet qualified for compression. The compression
and exact-byte restoration path passed its dedicated tests.

Cycle `dashboard-20261005T150131Z-fa0c3dd4` captured current FPL/SDP inputs, generated
and registered the primary/incumbent-shadow pair, generated its bound platform
plan, built the dashboard and published generation
`8cebbe8bd3ed24001118036853507d22f0e8072699c022f273fd53e8abd7f394`.
Independent HTTPS retrieval verified the byte counts and SHA-256 hashes of all
17 public files, the manifest bindings, CORS and no-store behavior. The live
generation reports `forecast_regenerated: true`.

| Evidence | Actual value (UTC) |
| --- | --- |
| FPL capture known at | `2026-10-05T15:13:46.521835+00:00` |
| Forecast cutoff | `2026-10-05T15:46:49.827634+00:00` |
| Evidence recording entry | `2026-10-05T15:49:32.727421+00:00` |
| Publication | `2026-10-05T16:11:59.513670+00:00` |
| Horizon and population | 2026-27 GW6–10; 20 teams, 50 fixtures, 667 players |
| Clean forecast code | `222368b048c0de477a8c60f78cd1619a508accd8` |
| Primary run | `c47e24173efcf78258e64f293e29629d0f0eb2bd01a40f8fa5603d5dab34d5a9` |
| Evidence pair | `fe4f8bc499677689aac52cfa274bb174257f7d279e1a041bfde8455de457f0ca` |

The retained primary artifact is
`D:/Personal/fpl-operations/predictions/scheduled-20261005T154618.409666Z.jsonl`.
Its SHA-256 is `817733fb1fc04bbe671abe67abf9194587a6de6a7a12cfae0337f322a75eda94`;
the incumbent-shadow SHA is
`4b3618927ca4c3d54ee4c58382aabec461ac6a2c859f4fa15236d2aff080deb8`.
The retained `forecast-source.duckdb` SHA is
`0db46b846904cc546eb5741e08ce2c24d0113d941c8f34542486e775f7ef5e3a`.
Independent verification reconciled the registered pair, equal cutoffs and live
inputs, future deadlines/kickoffs at recording, the exact replay input hash,
all ten prior forecast artifact hashes and 183 protected configuration/result/
forecast hashes. Component selections, contracts, seed and 2,000 draws match the
previous forecast. No fitting, retuning or historical reevaluation occurred.

The separate official FDR/injury/price feed was also refreshed at
`2026-10-05T16:06:20.839416+00:00` and verified over HTTPS against its exact local
bytes. This one-off refresh is not evidence that the hourly cloud job is enabled.

## Validation record

248 focused pipeline, capture, PIT, evidence, recovery, retention and publisher
tests passed; the final trigger suite passed 20 tests and the final retention/
archive suite passed 80. Global Ruff and strict mypy (244 source files) pass.
The full suite has **4,707 passed, four skipped, 18 failed and 17 errors**: the exact
35 failed/error test IDs match the retained September 28 baseline, with no new
failures. The existing ten-file repository formatting debt was not rewritten.
The full repository gate is therefore not all green.

Private verification receipts and task XML are retained under
`data/artifacts/forecast-automation-20261005/` in the main checkout, including
`forecast-verification.json`, `after-public-verification.json`,
`official-fpl-http-verification.json` and `gate-comparison.json`.
The final task status and unchanged-input policy check are in
`completion-verification.json` and `no-op-verification.json`. Operational
capture, forecast, publication and retention receipts remain under the cycle
directory in `D:/Personal/fpl-operations/dashboard-runs/`.
