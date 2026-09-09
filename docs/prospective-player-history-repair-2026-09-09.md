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

Verification and actual before/after forward outputs will be recorded additively
after the new capture and forecast complete. An xP change alone is not evidence
of improved predictive accuracy.
