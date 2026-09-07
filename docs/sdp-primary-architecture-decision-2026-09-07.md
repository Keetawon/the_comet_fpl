# SDP primary architecture: owner decision, 2026-09-07

**Owner-directed architectural adoption. SDP-backed V2 is the primary football-environment
architecture. Historical experimental verdict remains INCONCLUSIVE under its frozen gate.
Incumbent retained as operational fallback and prospective shadow comparator.**

This decision is authorized only on `claude/comet-fpl-v2-architecture-mqrj8f`, starting at
`a2f7e0c53f38ca680864dbe2923ffbc5f89256bf`. No main-branch merge, PR, or repository default-branch
change is authorized. This additive record overrides earlier operational-default freezes only
for the football-environment path on this branch. It changes no scientific verdict.

## Decision and scientific boundary

Phase A did **not** pass its previous 1% scientific gate. Approximately +0.458% Goal NLL and
+0.759% CS Brier improvement remain INCONCLUSIVE. The dated completion report, full-player PMF
report, all A-J results, claim registries, fitted research sources and gates remain frozen.
There is no new historical evaluation, hyperparameter selection, fitting of a candidate,
retuning, or post-hoc score-based model selection in this adoption.

The owner nevertheless chooses the SDP architecture for its information richness, directional
team-process utility, substantially improved shot-volume/predicted-xG forecasts in the retained
development evidence, reuse across football components, and ability to capture current/future
observations prospectively. These are architectural and operational reasons, not a new claim of
scientific superiority. Existing artifact `development_only_not_validated` labels remain honest
about component and end-to-end validation; they do not prevent the authorized operational use.

Minutes, player goals, assists, cards/absent cards, DC, saves scoring and bonus retain the current
prospective component choices. They consume the selected team-goal distributions where their
incumbent algorithms already require them. **No A-J player challenger is automatically promoted.**
H GK saves passed its component development gate but remains prospective **shadow-only**. Its
conditional saves PMF and incumbent comparator are recorded separately and never enter scoring.
The frozen full-player synthesis result is not rejudged.

## Runtime

```text
FPL API + SDP
      |
      v
SDP Football Environment
      |
      v
Tactical / Chance [frozen inference parameters, actual cutoff-known EPL rows]
      |
      v
Team Goal / CS <----- explicit whole-fixture selector
      |                    ^
      |             incumbent trailing_goals_attack_defence
      |             [fallback when SDP invalid; shadow when SDP primary]
      v
Existing Player Pipeline
      |
      v
FPL Points PMF          incumbent full-points shadow -> separate immutable artifact
```

`config/football_environment.yaml`, validated by the existing Pydantic/YAML configuration
system, declares `football_environment_primary: sdp_v2`,
`football_environment_fallback: trailing_goals_attack_defence`, `shadow_incumbent: true`,
`gk_saves_candidate_mode: shadow`, `lookback_days: 5`, and workload competitions
`[8, 1, 2, 5, 6, 1125]`. It pins SHA256s of both inference-only parameter artifacts.
`--football-environment disabled` bypasses this configuration and source path and reproduces
the incumbent numerical behavior with the same inputs, seed and draws.

The team parameter artifact copies the **last chronological retained fold** (2025-26 GW38),
including the corresponding frozen style fits, chance volume/quality fits and conversion.
The choice is by timestamp, not score. The exporter calls no fit or evaluation function.
The snapshot carries its actual original result availability time, result SHA256, and exact
frozen inference-source hashes. It cannot be loaded at an earlier prediction cutoff.
H's separate artifact copies the last chronological retained pooled precision and records its
source result/fold hashes. No H refit occurs. The incumbent save-rate estimator remains unchanged.

## Exact primary selector

At prediction cutoff T, select complete immutable source/fixture metadata versions with
`known_at <= T` and completed kickoff before T. Revalidate their raw bytes, hashes, status,
identity, field schema and numeric consistency. Production never uses `RetrospectiveBackfillView`.
Use the frozen state/matchup/chance arithmetic on those eligible EPL observations, excluding the
target gameweek as the existing state contract requires.

For each upcoming fixture, both clubs' latest five officially completed current-season matches
(or all completed matches where fewer than five exist) must have valid SDP records. A club with
no current-season matches may use the frozen league-prior cold start if eligible prior evidence
exists; it cannot borrow another club's history. Both sides switch together:

| Condition | Persisted selector |
| --- | --- |
| All required evidence and frozen model valid; finite complete environment | `SDP_PRIMARY` |
| No eligible model/source/history or missing required fixture | `SDP_MISSING_FALLBACK` |
| Raw hash/status/schema/numeric/model corruption | `SDP_SCHEMA_FALLBACK` |
| Competition, season, fixture or club identity contradiction/ambiguity | `SDP_IDENTITY_FALLBACK` |
| Missing core fields, incomplete latest revision, incomplete tactical state | `SDP_INCOMPLETE_FALLBACK` |
| Pre-prediction refresh failed | `SDP_SOURCE_FALLBACK` |

Model-availability/schema failure precedes source failure; target identity contradiction takes
precedence over either. Within a fixture, examine home then away, newest required match first,
with fixture identity as a deterministic tie break. A later malformed known revision cannot
silently revive an older complete version. An older prediction cutoff cannot see that revision.
There is no partial field coalescing, imputed zero, fuzzy match or `pulse_id == SDP matchId`
assumption. The existing season/kickoff/team/score crosswalk supplies fixture identity.

The incumbent is computed before selection and remains available if SDP is missing or rejected.
If any fixture uses SDP, a second complete incumbent forecast is composed with identical player
choices, seed and draws. CLI publication writes it to `<stem>.shadow-incumbent.jsonl`, then binds
its content hash into the primary artifact. Existing files are never overwritten; a failed primary
publication may leave an unreferenced shadow file, never a falsely published primary.

## Football data and health

SDP is a first-class production provider for EPL detailed stats and lineups/events, and supported
competitive lineups/events. Existing immutable `raw_pl_sdp_payload` and versioned football facts
are reused. Every field is retained in raw/tall staging even when no model consumes it.

Core fields are `expectedGoals`, `totalScoringAtt`, `ontargetScoringAtt`, `attemptsIbox`,
`touchesInOppBox`, `possessionPercentage`, `totalPass`, and `accuratePass`. Required absence
invalidates the whole match. Optional xGOT, final-third/box entries, forward/backward passing,
crosses, tackles, interceptions, clearances, blocks, recoveries, zonal regains, aerials, duels and
cards remain nullable. Booleans, NaN/infinity, negatives, fractional counts, possession above
100, or subcounts exceeding totals are rejected. Provider omission is never interpreted as zero.

`FixtureEnvironment` retains the exact goal PMFs and opponent equivalents, predicted shots,
predicted xG (distinct from the converted PMF mean), context-projected SOT, and frozen five-axis
tactical/opponent contexts including box pressure, possession and forward-passing fraction.
Unsupported raw-scale xGOT, territory and defensive-action forecasts remain NULL; observed
source fields and transformed tactical context do not become fabricated forecasts.
**Clean sheet is exactly the opponent goal PMF's zero mass.**

## Workload foundation

The production collector discovers Premier League, FA Cup, League Cup, Champions League,
Europa League and Conference League matches using their explicit provider competition IDs.
It requests completed competitive **lineups/events only**; competitive catalogues use a distinct
raw endpoint label excluded from EPL stats staging. Cup tactical stats never enter Tactical State V1.
Current-season exact EPL crosswalk witnesses corroborate club identities; player joins require
unique season-qualified `opta_code = p{provider_player_id}`. Names and fuzzy matching are unused.

`sdp_competitive_match_version` retains append-only interpretations, immutable source references,
actual interpretation/identity/source times and hashes of the existing V3 participation parsers.
Unresolved players remain unresolved. Latest whole versions are selected before workload rolling;
raw availability is rechecked. No retrospective `dev_*` workload table is read by production.

Positive nominal exposure supplies explicit `witnessed_minutes_last_72h_lower_bound`,
`witnessed_minutes_last_7d_lower_bound`, `witnessed_minutes_last_14d_lower_bound`, last-observed
appearance/start age, witnessed midweek starts, and played90/played120 evidence. Missing or
unresolved relevant evidence makes the window unavailable, never zero. Exact total-window
`minutes_last_*`, exact last-start/appearance age and player/team rest hours remain NULL without
continuous membership/complete-exposure/whistle evidence. Nominal clock intervals are not FPL
minutes or exact physical rest. Future capture progressively adds witnesses; it does not erase
historical coverage limitations, infer international/other uncaptured exposure, or alter incumbent
expected minutes. Integrating these features into a new minutes model requires separate design.

## Prospective provenance and monitoring

The unchanged version-2 forecast artifact contains canonical JSON at
`manifest.component_modes['football_environment.provenance']`: prediction cutoff, exact FPL
snapshot capture/hash/known_at, SDP source and metadata versions/hashes/fetched_at/known_at,
normalization/schema identifiers, frozen parameter/hash/version, configuration, fixture selectors,
incumbent goal PMFs, primary rich environments, workload sources, H shadows, refresh receipt/hash,
and the full incumbent shadow artifact hash. Existing Git/config/database/player-component/seed
provenance remains in the manifest. Primary and shadow have explicit forecast roles.

Current/future SDP observations use actual capture times. Historical SDP first captured
retrospectively in September 2026 is usable only after that availability; it is **not** retroactively
historical PIT evidence. Unchanged responses retain their original immutable receipt time; changed
responses append a new version, including A -> B -> A. No historical `known_at` is rewritten.

Exact paired team PMFs and official fixture keys support future Goal NLL, CS Brier, CRPS,
calibration, within-GW ranking and early-GW/home-away/promoted-team slices. Promoted flags require
a complete immediately preceding PL team dimension; unavailable classification remains NULL.
Selector counts provide fallback rate and reason counts. Evaluate matched finalized outcomes
on the same prospective fixture population; do not substitute research outcomes or hindsight
reconstructions. This change emits the evidence and introduces no new scientific promotion gate.

Daily JSON/CLI reports include capture success rate, expected/captured/core-valid matches,
latest completed match, latest retained/valid source times, age since successful capture,
schema/identity failures and workload counts by competition. Forecast output additionally counts
SDP_PRIMARY/fallback team sides and player-fixture predictions and records every reason.
See the [operational runbook](sdp-primary-operations.md) for capture, pre-deadline and rollback.
