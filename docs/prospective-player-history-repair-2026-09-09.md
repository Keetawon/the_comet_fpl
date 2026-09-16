# Prospective player-history wiring repair

The owner authorized repairing the stale player-history inputs and recalculating
future xP on September 9. This is a source-wiring correction, with no parameter
search, recency change, player-specific adjustment or historical audit rerun.
The starting V2 commit is `b47ce77609d2fb29e41713a15926f220c0f18ef8`.

## Defect and repair

The retained September 8 forecast had current FPL history available before its
cutoff, but several consumers queried `mart_fact_player_fixture` directly. The
freshness gate checked capture availability; it did not establish consumption.
Seasonal minutes replaced the live-aware fitted minutes estimate with an
archive-only last-five distribution. Goal/assist share windows, ICT proxies,
last-club/cold-start detection and component calibration histories had the same
source gap. This is an implementation defect, not evidence for different weights.

The prospective job now selects one shared archive/live history through the
existing `PointInTimeView`. Live revisions require `known_at <= as_of` and match
kickoff strictly before cutoff. A live whole-row revision wins an overlapping
archive identity before missing minutes are excluded. Unknown statistics are not
filled from older versions or converted to zero. Goal/assist fits exclude unknown
labels; BPS calibration requires its measured inputs. Fixture-time club identity
is season-qualified and contradictory mappings fail closed. Current-season
transfer observations remain eligible without rewriting their represented club.
Timestamp serialization is normalized to UTC independently of DuckDB session zone.

Minutes, goal/assist shares, ICT, last club, component histories, BPS residual rows
and the existing league assist-rate calculation consume that same selected history.
The actual **previous-season appearance prior remains archive-only**: current-season
appearance frequency must not silently replace that separately named prior.
Team environment, SDP selector/fallback, scoring/composition, component estimators,
configuration, seeds and draw counts are unchanged. Existing historical adapters
retain their default archive-only reads. No old scientific verdict is rejudged.

## Prevention and provenance

New artifacts carry `player_history.contract` and `player_history.provenance` in
the existing manifest extension. They bind the selected row hash, live-version
hash, source capture IDs, latest live knowledge time, counts by season/GW and
eligible latest-five fixture/appearance identities for the active registry.
The existing immutable source DB and artifact hash retain the complete input.
An additional runtime check refuses a forecast when the completed GW credited by
the freshness gate is absent from the consumed history. Synthetic regressions
exercise actual input consumption, future-match/capture exclusion, whole revision
selection, NULL preservation, transfers, cold starts and deterministic forecasts.

## Operational use and evidence boundary

Run from a clean committed V2 worktree with the existing operational database:

```powershell
$python = 'D:/Personal/fpl-operations/.venv/Scripts/python.exe'
& $python -m fpl.jobs.pre_deadline_forecast `
  --db D:/Personal/fpl-operations/data/sdp-primary-v2.duckdb `
  --runs D:/Personal/fpl-operations/sdp-primary-runs `
  --gw-from 4 --gw-to 8 `
  --output D:/Personal/fpl-operations/predictions/player-history-repair-20260909-gw4-8.jsonl
```

The command refreshes sources with actual timestamps, backs up the operational
database, emits primary/shadow artifacts and registers the new pair before its
deadlines. Use the established `build_sdp_dashboard` command to export this new
stored forecast to the current dashboard, retaining existing plan provenance.
Never overwrite the old fixed-origin pair or substitute this repaired vintage
into `config/sdp_gw4_8_checkpoint.yaml`. The old cohort remains available for its
original scorecard, explicitly qualified by the discovered wiring defect. The
newly generated forecast is the current operational view and a separate vintage.

All previously frozen predictions, configs, model estimator sources, results and
dated reports are retained. The prospective orchestration source deliberately
changes under this repair authorization; do not claim its fingerprint still
equals the original model-freeze orchestration file. Old artifacts reproduce at
their pinned code/source identities, and no old audit is rerun here.

## Completed forward run

The repair was committed and pushed as `78753019e109f25ddb030325eff1010e63af8c52`
before capture/inference. The operational job ran from 05:30:28 to 05:58:27 UTC
on September 9; refresh, inference and evidence registration all exited zero.
The new cutoff is **2026-09-09 05:52:47.485385 UTC**. Its actual pair-registration
timestamp is **05:53:48.660523 UTC**, before every included deadline. Retained
official bootstrap evidence gives the GW4 deadline as September 12, 12:30 UTC.

The selected history contains 140,597 prior rows, including 1,890 live rows:
GW1 610, GW2 626, GW3 654. The 30 completed fixtures are the total across GW1–3.
SDP capture retains 30/30 matches; provider core validity remains 26/30. Fixtures
7, 19, 20 and 28 still fail the unchanged core contract. Display corrections
and owner-directed sparse-count assumptions do not change that contract.
The forecast has 21 SDP-primary fixtures and 29 incomplete fallbacks, unchanged.

Primary and shadow each contain 654 players, 50 fixtures, 3,270 player-GW rows,
3,270 player-fixture rows and 100 team-fixture rows. Their populations, component
contracts, seeds and 2,000 draws match. Their player-history provenance is identical.
Both artifacts pass canonical byte round-trip and PMF/expectation validation.
All 100 team-forecast rows are exactly equal to the old vintage. Of the 3,270
common player-GW rows, 3,182 xP values change; no player population was added or removed.

| Player | GW4 old xP | GW4 repaired xP | GW4–8 repaired xP |
|---|---:|---:|---|
| João Pedro (475168) | 3.5830 | 5.1660 | 5.1660, 4.4325, 5.0440, 4.3520, 5.2435 |
| Gyökeres (224117) | 3.3275 | 2.8130 | 2.8130, 2.9390, 3.3955, 2.6765, 2.9930 |

Gyökeres' consumed last-five minutes are now **17, 7, 0, 0, 12**; João Pedro's
are **0, 90, 90, 90, 90**. A read-only trace of the unchanged minutes arithmetic
gives Gyökeres P(any)=0.86151 and P(60+)=0.22985, versus João Pedro 0.87838 and
0.72970. These are model probabilities, not actual expected-minute measurements.
Gyökeres does not become a certain DNP: the existing shrinkage and September
70% previous-season appearance blend remain in force. No claim is made that
these assumptions are newly validated. An xP change alone does not establish
improved predictive accuracy.

New pair: `3c7f1f8b86e5972f74db07116d2d13cc86461c248e79a6a680bfdf8fbc29efb9`.
Primary artifact SHA256:
`3a7aca22fbdb3b55227d30b4e427255792f4b0aaeddba808389ec9d5e11811f4`.
Shadow artifact SHA256:
`6eac960a24d9b00bd792765d74051119c01ccfdd65015eacebed10ef1c9ebae9`.
Source DB SHA256:
`915561bdc110beeebb1978010e43cf78becb74745f38f7478c33fd7726624d83`.
Full machine-readable validation is in
`results/prospective_player_history_repair_2026-09-09.json`.

## Dashboard delivery and server limitation

`build_sdp_dashboard` refreshed the existing pages and SDP sidecar from the
operational DB, retaining only the existing optimizer plans from the old base.
The exported actuals reconcile all 1,890 current player-fixture and 60 team-side
rows. The current primary run is
`660302216bdfac866003ef50e8077953bb297ff87412252bc796f27c8adbdd2f`.
Summary now excludes incumbent-shadow vintages when selecting its default;
equal registration timestamps cannot select a shadow by hash ordering. Shadow
and old vintages remain selectable. Public metadata retains the player-history
contract and provenance digest, excluding its internal serialized source body.

The existing Vite preview was rebuilt successfully at
**http://127.0.0.1:4173/#players** (owner machine only). Served summary, players,
fixtures and manifest bytes match the new static build. Every one of its 3,270
player-fixture xP values matches the immutable repaired artifact, and the default
horizon is GW4–8. Existing optimizer plans retain their original provenance;
no new optimizer solve or remote deployment occurred.

The in-app browser skill was attempted: setup returned **No browser is available**
and discovery returned `[]`. HTTP/value verification and frontend tests passed;
there is no claim of visual browser verification or new screenshots. Windows
symlink publication remained unavailable; the existing validated before-publish
retention/copy mechanism installed the local preview successfully.

Automatic approval review rejected the attempted Plan Server restart with
**blocked by policy** and no further reason. That command did not execute; the
existing server on port 8765 still has the old forecast argument. Do not use it
for a new solve until the owner restarts it with the repaired artifact. After
stopping the identified old Plan Server (PID 19936 at verification), run:

```powershell
Set-Location D:/Personal/workspace/the_comet_fpl/.worktrees/sdp_test
$env:PYTHONPATH = "$PWD/src"
& D:/Personal/fpl-operations/.venv/Scripts/python.exe -m fpl.jobs.plan_server `
  --host 127.0.0.1 --port 8765 `
  --base D:/Personal/workspace/the_comet_fpl/data/plan-server `
  --forecast D:/Personal/fpl-operations/predictions/player-history-repair-20260909-gw4-8.jsonl `
  --dashboard-data D:/Personal/workspace/the_comet_fpl/.worktrees/sdp_test/dashboard/public/data
```

## Verification status

- Source-wiring focused tests: **56 passed**; relevant broader group: **231 passed**.
- Dashboard Python regressions excluding publication/lock/symlink cases:
  **83 passed, 3 skipped, 4 deselected**. Targeted frontend tests: **45 passed**.
- Global Ruff check and strict mypy pass (229 source files). Vite/TypeScript build
  passes, retaining its existing large-chunk warning. `git diff --check` passes.
- Five changed Python files pass formatting. `dashboard_json.py` and its old
  test file have inherited formatting differences outside this repair; those
  unrelated changes were deliberately not included.
- A larger run stopped at **1,339 passed, 149 deselected, one failure and two
  setup errors**. The freeze-hash test still expects the old orchestration file;
  that mismatch is the intentional authorized repair, not an environment failure.
  Reference-component synthetic fixtures expect one minutes fit, while automatic
  incumbent shadow runs two. That setup failure was reproduced using the exact
  pre-repair `b47ce77` source. No historical evaluation was run or changed.
- All **348** pre-change protected config/model/result/report/forecast files
  remain byte-identical. The earlier 392-file freeze receipt still has 391 matches;
  its sole source exception is the explicitly repaired prospective job. All old
  audit receipts, result hashes, frozen predictions and model estimator/config
  files remain intact. Main is untouched.
