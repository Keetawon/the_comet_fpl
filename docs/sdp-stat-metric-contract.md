# Observed SDP dashboard metric contract

Version 1, 2026-09-08. This additive reporting contract does not change any model,
forecast, optimizer, frozen evaluation, or scientific verdict.

`sdp_stats.json` is a descriptive sidecar, served separately at
`/sdp/sdp_stats.json`. The established public dashboard package and its schema-v9
read models retain their existing sealed contract.

## Source boundary

Team statistics come from retained Premier League SDP match-stat payloads. The
existing `load_sdp_state` reader revalidates HTTP status, raw hash/length, completed
PL match identity, exact FPL fixture crosswalk, reciprocal club identity, required
core fields, numeric constraints and latest cutoff-eligible source versions. A
malformed later revision does not revive an older valid version. The exporter
does not load model artifacts or publish the reader's tactical-state vector.

The current source inventory contains no retained SDP endpoint carrying detailed
individual player match statistics. Team shots, xG, passes, touches and defensive
actions are never allocated to individual players. Consequently, player `sdp`
metric objects are empty and `source_status.player_stats` is `UNAVAILABLE`.

Operational SDP lineup/event interpretations can provide explicit starting-XI,
bench, appearance and broad provider-position observations. The exporter uses only
valid `sdp_competitive_match_version` records whose referenced raw sources are
retained and verified. It accepts competition 8 (PL) only for these EPL dashboard
rows. Cup participation retains its existing workload path; cup tactical data
does not enter these team rows. Identity uses the established fixture crosswalk
and validated stable player `code`; provider player IDs and FPL codes are separate
fields. Unmapped players remain `code: null`. Names never join identities.

Current-season player FPL enrichment comes from one latest cutoff-eligible,
complete `player-history` capture: exactly one bootstrap, fixtures source and
element-summary for each supported registered player. Its manifest and raw
payload checksums must reconcile. An invalid latest capture makes enrichment
unavailable. No older complete capture is silently substituted. Independently
verified bootstrap/fixture metadata remains usable when the optional player-summary
population is missing or invalid; healthy SDP participation does not depend on
the success of FPL player-metric enrichment.

FPL registration position is taken from that season's captured registry, with
season-local identity/position contradictions rejected. Fixture-time club and
opponent come from the history row's exact home/away side and official fixture,
never from the player's current club. Transfers therefore retain the club
represented in each match. These are current-season enrichments, not a claim of
historical SDP individual-stat coverage.

## Envelope and row grain

The envelope has `schema: "fpl.sdp-stats"`, `json_schema_version: 1`, `as_of`,
`source_status`, `coverage`, `metrics`, `gameweeks`, `team_matches` and
`player_matches`.

`source_status` separately reports team statistics, individual player statistics,
player lineups and FPL enrichment as `AVAILABLE`, `PARTIAL` or `UNAVAILABLE`.
It includes latest SDP/FPL knowledge timestamps, latest completed kickoff and
short source limitations. The latest SDP timestamp is the latest retained
cutoff-eligible fetch, not an assertion that every fixture passed validation.

Coverage counts are row counts: `team_matches` counts club-fixture sides;
`player_matches`, `sdp_lineup_player_matches`, `fpl_player_matches` and
`unmapped_players` count player-fixture rows. `team_failures` counts distinct
fixtures with unavailable SDP core evidence. A genuinely captured FPL player row
with missing minutes still counts as a source row. `seasons` lists the exact
retained seasons represented, without implying uniform metric coverage.

Team grain is `(season, fixture, team_code)`. Player grain is
`(season, fixture, code)` for mapped players, or the separate
`(season, fixture, provider_player_id)` identity when unmapped. Duplicate identities
fail closed. Double-gameweek legs remain separate.

Both row types carry season, GW, fixture, kickoff, permanent club/opponent codes,
their season-qualified display names, home/away, knowledge timestamp, status,
provider match ID where available, and opaque `source_version`. The version binds
the retained source content/interpretation without publishing capture IDs, raw
bodies, request paths, local database paths, private manager state, or PMFs.

Team rows have separate `sdp` and `fpl` dictionaries. A team row with unavailable
SDP data stays in the population with all SDP fields NULL; its independently
measured official FPL score can still be present. Thus team `UNAVAILABLE` status
does not erase a valid FPL score. Player rows similarly separate SDP membership
fields, nominal duration, FPL minutes and FPL metrics.

`FINAL` means the fixture has ended, not that provider statistics are immutable.
`PROVISIONAL` retains explicit official provisional completion. Ordinary provider
corrections can appear only in a new immutable export. Player
`total_points_as_recorded` always means the observed FPL API value; it is not
renamed to, combined with, or substituted for ledger-owned replayed points.

The current-season `gameweeks` array carries official bootstrap `finished`,
scheduled fixture count, ended fixture count and source knowledge time. It is
independent of how many SDP rows are valid. A partly completed GW remains partial
even when every currently available statistics row is valid. Historical seasons
without this contemporaneous completeness witness remain explicitly unwitnessed
by this array; filenames or observed rows do not prove official GW finality.

## Metric inventory

The team provider catalog reuses `config/pl_sdp_metrics.yaml` unchanged. It retains
each canonical name, exact provider aliases, metric group, numeric type,
description and `verified_semantics` flag. Existing independent corroboration is
limited to goals, expected goals and shots on target. Field presence alone does
not upgrade the remaining semantics. Conflicting aliases, NULL, booleans,
non-finite/negative values and fractional count values remain unavailable.
Possession outside 0–100 remains unavailable. Required production-core failures
make the whole SDP fixture unavailable; missing optional metrics remain NULL.

The configured catalog covers goals/xG/xGOT; shots, SOT and box/outside-box/blocked
shots; big chances; opposition-box touches and territory entries; possession;
passing, directness, long passes and crosses; tackles, interceptions, clearances,
blocks and recoveries; possession recoveries by third; aerial/ground duels;
fouls, cards and offsides. Availability is measured separately for every metric.
Unconfigured raw provider fields are retained in the operational raw store but
are not assigned new football semantics in this dashboard task.

Two observed opponent fields are added without model inference:
`shots_allowed` is the exact paired opponent `shots`, and
`expected_goals_allowed` is the exact paired opponent `expected_goals`, from the
same validated match payload. They inherit the corresponding semantic certainty.

Official current-season team `goals_scored` and `goals_conceded` are labelled
`source: fpl`; they use exact official home/away score fields. They are separate
from SDP's goal count, whose source definition can differ for own goals.

Player FPL enrichment includes:

| Group | Captured fields |
|---|---|
| Exposure | minutes, starts |
| Attack | expected_goals, goals_scored |
| Creation | expected_assists, assists |
| Defence | clean_sheets, goals_conceded, expected_goals_conceded, defensive_contribution |
| GK | saves |
| Discipline | yellow_cards, red_cards |
| FPL points | total_points_as_recorded, bonus, bps |

Every catalog entry declares `key`, `label`, `group`, `source`, `scope`, `unit`,
`aggregation`, `per90_denominator` and `verified_semantics`; description and exact
provider spelling accompany it. Metric identity is `(scope, source, key)`, since
the same name can legitimately occur in different sources/grains.

## Denominators and aggregation

NULL is never zero. A measured zero remains zero, including a witnessed FPL DNP.
Signed recorded points/BPS retain valid negatives. Actual minutes outside 0–120
and starts outside 0/1 become unavailable.

Current SDP workload durations use
`nominal_period_clock_intervals_v1_not_fpl_minutes`. The public
`nominal_minutes_sdp` exposes only that nominal observation. `minutes_sdp` is NULL
throughout: nominal period intervals must not become elapsed-minute or FPL
per-90 denominators. A 90th-minute substitute can have nominal duration zero
despite a witnessed appearance.

Player FPL per-90 values divide an observed metric by its matching FPL minutes
only, with positive measured total exposure. Team totals/per-match averages use
actual selected fixture sides. Percentage fields, including possession, remain
per-match means and are never summed. No pass-completion percentage is invented
from a mixture of incomplete numerator/denominator evidence.

An aggregate is unavailable when a selected fixture lacks its metric or required
matching minute denominator. The UI exposes measured/selected coverage, so a
partial total cannot masquerade as a full-range statistic. Source rows, not
numeric GW gaps, define last-three/last-five windows; every DGW leg counts.

## Availability, publication and verification

All source reads require actual `known_at <= as_of` and observed kickoff before
`as_of`. A future export cutoff is rejected. Historical SDP captured retrospectively
retains its real later knowledge time; this descriptive view establishes no
historical pre-deadline PIT claim.

The exporter opens DuckDB read-only and uses the existing fsync plus exclusive
hard-link publication helper for a complete new JSON file. Interrupted/failed
publication cannot leave a partial final file. Exact
input/as-of replay is byte-identical. Existing exports cannot be overwritten.
The CLI returns SHA256, byte count, source status and coverage without local source
paths. The public validator accepts only the documented schema/catalog, identities,
nullable finite metrics and source timestamps; extra model/private fields fail.

```powershell
python -m fpl.jobs.export_sdp_stats `
  --db D:/Personal/fpl-operations/data/sdp-primary-v2.duckdb `
  --output <new-release>/public/sdp/sdp_stats.json `
  --as-of <actual-UTC-timestamp>
```

Run this after the existing capture/normalization workflow has completed and its
database writer has closed. The dashboard build wrapper binds this sidecar to its
public release while leaving the existing sealed read-model package unchanged.
No network request, provider credential, model fit, forecast, or optimizer action
is performed by this exporter.
