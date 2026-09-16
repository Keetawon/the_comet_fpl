# Player role / OOP source investigation — 2026-09-08

**Verdict B — SOURCE PARTIAL.** SDP supplies usable starting XI, bench, formation and
source-native formation bands in this bounded sample. Exact tactical slots and functional
roles require additional evidence or inference. The maximum defensible source-derived
resolution is **Level 2**, conditional on a valid explicit formation.

This is a source investigation and additive development-only interpretation. No player model
was trained, tuned, backtested, promoted or changed. The existing frozen broad-role study was
not rerun or rejudged. SDP primary, incumbent fallback/shadow, GK shadow, points composition,
optimizer, prospective ledger and historical scientific verdicts remain unchanged.

## Answers and scope

| Question | Answer |
|---|---|
| Can SDP identify the starting XI? | Yes in the sample: 44 explicit formation XIs and two validated existing membership fallbacks, each with 11 unique players. This is not a universal coverage guarantee. |
| Can it identify formation? | Explicit annotation and nested rows agree on all 44 present sides; two sides lack formation. |
| Can it identify formation bands? | Yes as source-native row grouping on 484 starters. These are declared starting-formation bands, not measured movement over the match. |
| Does within-line order prove left/right/central meaning? | No. Ordered arrays exist; their tactical orientation is unvalidated. |
| Maximum observed-role resolution? | Level 2 structural bands. Broad provider positions support Level 1. Levels 3–5 are unsupported. |
| Deterministic FPL mapping coverage? | 829/936 roster appearances (88.5684%); sampled PL subset 721/721 (100%). |
| Can this support an OOP detector now? | It can expose position/structure discrepancies for inspection, but cannot establish material functional OOP. Every diagnostic is UNKNOWN under the frozen rule. |
| Can it support future role prediction? | It supplies prior observed membership/band history for a separately designed study; predictive validity is untested here. |
| What remains unknown? | Within-line tactical orientation, functional role, in-match role changes, substitute role, provider publication time, and broader historical coverage. |
| Start historical role backfill? | No. Resolve the coarse inference design first; no backfill was started. |

The sample is fixed before named case inspection: the original 13 participation bundles
(2025-26: eight PL, two League Cup, two Champions League, one Conference League), plus all
10 distinct completed PL lineup/event matches in the preserved September 8 operational
forecast-source database. Its 40 workload interpretation versions are reduced to ten latest
whole source bundles before counting. There are 23 matches, 46 sides, 26 clubs, 936 roster
appearances and 593 distinct provider player IDs. FA Cup and Europa League are not represented
in this sample; this does not imply provider unavailability. Older retained captures were not
swept or backfilled. **Zero network requests** were made for this investigation.

The [machine-readable result](../results/player_role_source_audit_2026-09-08.json) contains
every raw field inventory, match, exact ordered formation ID array, player position, identity,
substitution, timestamp, source hash, case study and coverage breakdown. It retains all
69 match/endpoint references, representing 51 distinct raw payload hashes. Original raw bytes
remain in their existing persistent storage; a remote clone does not acquire those bytes.

## Frozen generic interpretation

[The new source contract](../config/player_role_source_audit.yaml) was frozen at
`2026-09-08T04:49:16Z`, before named-player inspection. SHA256:
`a695452fbc12fd1d414d1d64b44c02addee53626c17cd06d4b66093ded7ead5a`.
The classifier does not inspect names, prices, goals, xG, touches or other same-match
performance. Names select display cases only after exact identity and generic interpretation.
The first six unique exactly mapped starters in season/match/team/provider-ID order are the
control sample; this deterministic choice happens to select six Arsenal players from one match.

The new parser calls the **unchanged** `competitive_participation_v2` validator for XI/bench,
reciprocal identities and event sequences. Missing/null/empty-object formation retains its
existing membership fallback, with structural indices NULL. Malformed present formation never
uses that fallback. Empty rows, duplicate identities and unknown roster references fail closed.
Annotation disagreement preserves validated membership and raw indices but withholds bands.

Valid annotation sizes must equal the source row sizes after adding the explicit single GK
row. Bands are labelled only `goalkeeper_line`, `defensive_line`, `interior_line_1`,
`interior_line_2`, etc., and `forward_line`. These are relative formation rows, not CB/FB/WB,
AM/DM, winger or striker classifications. `formation_line_index` and
`formation_member_index` are zero-based source indices. The original nested arrays and
provider player objects survive unchanged. **No `observed_role_family` is emitted.**

The predeclared OOP rule requires independently corroborated material functional advancement
or depth. Broad position and row grouping alone are insufficient: all 936 diagnostics are
`UNKNOWN`, including apparently conventional roles. No arbitrary score or tuned threshold
is introduced. A substitute never inherits the replaced player's formation slot or role.

## Exact observed schema

Counts below use actual parent-object denominators. The JSON inventory retains every observed
key, its type counts, missing count and explicit NULL count, including metadata and root envelopes.

| Object / field | Presence | Observed type / NULL |
|---|---:|---|
| Player `id`, `firstName`, `lastName`, `position`, `shirtNum` | 936/936 each | string; no explicit NULL |
| Player `isCaptain` | 936/936 | boolean; no explicit NULL |
| Player `knownName` | 86/936 | string; 850 absent |
| Player `subPosition` | 429/936 | broad-position string; 507 absent |
| Lineup side `teamId`, `players`, `managers`, `formation` | 46/46 each | string, array, array, object |
| Nonempty formation `teamId`, `formation`, `lineup`, `subs` | 44/46 each | string, string, nested array of string IDs, array of string IDs |
| Empty formation object | 2/46 | `{}`; not malformed and not zero-filled |
| Manager `id`, `firstName`, `lastName`, `type` | 46/46 each | string; `knownName` appears once |
| Event side `id`, `name`, `shortName`, `subs`, `cards`, `goals` | 46/46 each | strings / arrays |
| Substitution `playerOnId`, `playerOffId`, `time`, `period`, `timestamp` | 201/201 each | strings; no explicit NULL |
| Goal `playerId`, `goalType`, `time`, `period`, `timestamp` | 52/52 each | strings; no explicit NULL |
| Goal `assistPlayerId` | 52/52 | 32 strings, 20 explicit NULLs |
| Card `playerId` | 91/91 | 86 strings, 5 explicit NULLs |
| Card `type`, `time`, `period`, `timestamp` | 91/91 each | strings; no explicit NULL |
| Player-level `teamId`, coordinates, tactical side, explicit slot/order/index, role labels, starter boolean | 0 observed | Absent, not invented |
| Endpoint-root `matchId` in lineups/events | 0/23 each | Match identity comes from retained request identity plus corroborated metadata/sides |
| Provider schema version / publication timestamp | 0 observed | Unknown |

`position=Substitute` is a roster label; `subPosition` supplies a broad category where present.
Neither is a universally reliable participation flag. There are 506 validated starters,
428 bench members and two unassigned roster entries. Those two keep started, bench,
appeared, minutes and formation indices NULL: the previously retained Millwall record
`2603048/108801`, and current Manchester City record `2645222/472769`.
The latter is not declared withdrawn, injured or unused without additional evidence.

The events endpoint contains substitutions, goals and cards, not a physical tracking feed.
Raw substitution period/minute/timestamp/actors are retained, and timestamps must lie between
kickoff and the **events endpoint's own** retained knowledge time. Nominal V2 minutes remain
labelled nominal, not physical elapsed time. They do not infer a substitute's tactical role.

## Formation evidence and coverage

All 44 explicit annotations agree with exact nested row sizes; all flattened XIs contain
11 unique roster-known IDs, with disjoint known benches. Source broad positions are internally
compatible with the grouping: first rows are GK, second rows Defender, final rows Forward.
Interior rows carry Midfielder or Forward depending on the annotated shape. This is internal
source consistency, not independent corroboration of functional roles.

| Formation annotation | Team sides | Exact row sizes including GK |
|---|---:|---|
| 4-2-3-1 | 20 | 1, 4, 2, 3, 1 |
| 3-4-2-1 | 10 | 1, 3, 4, 2, 1 |
| 4-3-3 | 9 | 1, 4, 3, 3 |
| 4-1-4-1 | 2 | 1, 4, 1, 4, 1 |
| 5-4-1 | 2 | 1, 5, 4, 1 |
| 3-5-2 | 1 | 1, 3, 5, 2 |
| Absent | 2 | Unavailable |

Ten provider players occur at different formation line indices across sampled matches.
The JSON retains their exact match/shape/index witnesses. A change of annotation can change
an index without proving functional movement. Of 128 multi-member lines, only 22 are ordered
by numeric player ID: the arrays contain real source order, but this does not identify its
tactical meaning. Repetition of an index is likewise not independent validation of side.

The retained official PL frontend bundle contains a broad-position fallback helper (`yV`)
that groups GK/Defender/Midfielder/Forward in that order, preserves roster order within groups,
and marks `isFallback: true`. Its adjacent helper selects a side by `formation.teamId`.
The bundle does not establish left/right/central semantics; its lazily loaded lineup renderer
was not retained. Display orientation would not itself establish a functional match role.

Evidence: `https://www.premierleague.com/resources/v1.52.5/scripts/bundle-es.min.js`, captured
`2026-09-07T04:01:39.029125Z`, HTTP 200, `text/javascript`, SHA256
`3d131eda71095165a45254906ba65540fc9d3777f91ba8603c8d15d5f64dcd1b`.
Exact bytes and receipt line 6 remain under
`D:/Personal/fpl-operations/verification/competitive-workload-20260907T040018Z/`.
The [existing independent source-resolution record](competitive-participation-source-resolution.md)
corroborates final XI/bench membership in the Millwall replacement case; it explicitly does
not license tactical-role inference. No new public API contract is claimed.

| Scope | Sides | Explicit formation | XI / bench recoverable | Broad position rows | Band / starters | Exact FPL mapping | Substitution timing |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2025-26 retained pilot | 26 | 24/26 | 26/26 | 535/535 | 264/286 | 428/535 | 114/114 |
| 2026-27 operational | 20 | 20/20 | 20/20 | 401/401 | 220/220 | 401/401 | 87/87 |
| Combined | 46 | 44/46 (95.65%) | 46/46 | 936/936 | 484/506 (95.65%) | 829/936 (88.57%) | 201/201 |
| PL subset | 36 | 36/36 | 36/36 | 721/721 | 396/396 | 721/721 | 153/153 |

Within-line indices are available for the same 484 starters. Semantically validated within-line
tactical orientation is **0/484**. Bands cover 484/936 total roster appearances (51.71%); bench
and unassigned players correctly have no starting-formation band. These are sample denominators,
not historical league-wide coverage estimates. Team and formation-family breakdowns are retained
in the JSON; the team table below makes the uneven sample explicit.

| Provider club | Sides | Explicit formation | Mapped / roster | Bands / starters | Substitution times |
|---|---:|---:|---:|---:|---:|
| Manchester United (1) | 1 | 1/1 | 20/20 | 11/11 | 5 |
| Leeds United (2) | 1 | 1/1 | 20/20 | 11/11 | 4 |
| Arsenal (3) | 8 | 8/8 | 163/163 | 88/88 | 39 |
| Newcastle United (4) | 2 | 2/2 | 40/40 | 22/22 | 10 |
| Tottenham Hotspur (6) | 1 | 1/1 | 20/20 | 11/11 | 5 |
| Aston Villa (7) | 1 | 1/1 | 20/20 | 11/11 | 5 |
| Chelsea (8) | 1 | 1/1 | 20/20 | 11/11 | 4 |
| Coventry City (9) | 1 | 1/1 | 20/20 | 11/11 | 5 |
| Everton (11) | 2 | 2/2 | 40/40 | 22/22 | 7 |
| Liverpool (14) | 2 | 2/2 | 40/40 | 22/22 | 9 |
| Nottingham Forest (17) | 2 | 2/2 | 40/40 | 22/22 | 9 |
| West Ham United (21) | 2 | 2/2 | 40/40 | 22/22 | 6 |
| Crystal Palace (31) | 7 | 6/7 | 143/143 | 66/77 | 27 |
| Brighton and Hove Albion (36) | 1 | 1/1 | 20/20 | 11/11 | 3 |
| Ipswich Town (40) | 1 | 1/1 | 20/20 | 11/11 | 4 |
| Manchester City (43) | 2 | 2/2 | 41/41 | 22/22 | 8 |
| Port Vale (50) | 1 | 1/1 | 1/20 | 11/11 | 5 |
| Fulham (54) | 1 | 1/1 | 20/20 | 11/11 | 5 |
| Sunderland (56) | 2 | 2/2 | 40/40 | 22/22 | 6 |
| Hull City (88) | 1 | 1/1 | 20/20 | 11/11 | 5 |
| Bournemouth (91) | 1 | 1/1 | 20/20 | 11/11 | 5 |
| Brentford (94) | 1 | 1/1 | 20/20 | 11/11 | 5 |
| Millwall (103) | 1 | 1/1 | 1/21 | 11/11 | 5 |
| Athletic Club (174) | 1 | 1/1 | 0/23 | 11/11 | 5 |
| Dynamo Kyiv (194) | 1 | 0/1 | 0/23 | 0/11 | 5 |
| Olympiakos (202) | 1 | 1/1 | 0/22 | 11/11 | 5 |

## Identity and case studies

Mapping uses only exact season-qualified FPL `opta_code == p{provider_player_id}`. Names
never establish identity. Ambiguous or contradictory anchors yield NULL; opposite sides share
the same identity audit. Team codes require explicit witnesses from independently reconciled
PL fixture crosswalks, including for PL clubs appearing in cup matches. Numeric overlap with
a registry team code is insufficient. Unknown other-competition fixture/team identity stays NULL.

The historical registry is the retained 2025-26 archive dimension; the current registry is
bootstrap capture `1bfb3d92-6d5e-48bf-a665-1f489dc6c1da`, known at
`2026-09-08T03:37:39.610696Z`, SHA256
`01fa0e3d2d034fa87536ddacdbd710fd81ddbe7c19d489f3064e499a6ade7d81`.
Historical FPL position is an archive-season registration label, not a historical deadline
snapshot. Its fresh identity/position interpretation is available only at this audit's actual time.

There are zero contradictory provider/code mappings and zero reverse duplicate mappings in
the sampled records. Of 593 provider IDs, 489 map in at least one sampled season and 107 are
unmapped in at least one; three belong to both sets. Their historical NULLs remain NULL despite
later current-season anchors. The 107 unmapped roster appearances are League Cup 39,
Champions League 45 and Conference League 23; none is in the PL subset.

Nineteen players have different observed club endpoints across seasons. Their exact match and
kickoff witnesses remain in the JSON, without inferred transfer dates or continuous registration.
The current sample includes 60 roster appearances for promoted Hull, Ipswich and Coventry.
There are 105 current mapped players without a previous-season FPL registry witness; this is
source absence, not a newly defined production cold-start classification.

All case rows below use the same predeclared UNKNOWN diagnostic. Indices are zero-based;
`interior 2` means only the second interior source row. Exact source hashes and knowledge times
are retained per row in the JSON. No network expansion targeted these players.

| Player (FPL code; position) | Match / kickoff UTC | SDP / FPL fixture | Formation | Membership | Provider broad label | Line / member | Structural band | Level / OOP |
|---|---|---|---|---|---|---|---|---|
| O'Reilly (472769; DEF) | Arsenal vs Manchester City; 2025-09-21T15:30:00Z | 2561936 / 41 (2025-26) | 4-1-4-1 | XI | Defender | 1 / 3 | defensive_line | 2 / UNKNOWN |
| O'Reilly (472769; DEF) | Manchester City vs Coventry City; 2026-09-05T14:00:00Z | 2645222 / 26 (2026-27) | 4-2-3-1 | Unassigned (NULL) | Substitute / Defender | NULL / NULL | NULL | 1 / UNKNOWN |
| Hume (487676; DEF) | Crystal Palace vs Sunderland; 2025-09-13T14:00:00Z | 2561929 / 35 (2025-26) | 4-3-3 | XI | Defender | 1 / 0 | defensive_line | 2 / UNKNOWN |
| Hume (487676; DEF) | Brentford vs Sunderland; 2026-09-05T14:00:00Z | 2645216 / 22 (2026-27) | 4-2-3-1 | Bench | Substitute / Defender | NULL / NULL | NULL | 1 / UNKNOWN |
| De Cuyper (465730; DEF) | Brighton and Hove Albion vs Leeds United; 2026-09-05T14:00:00Z | 2645217 / 23 (2026-27) | 4-2-3-1 | XI | Midfielder | 3 / 2 | interior_line_2 | 2 / UNKNOWN |

De Cuyper's DEF registration versus a provider Midfielder label in row 3 is a directly
observed discrepancy worth retaining. It does not by itself establish how advanced he played,
which side he occupied, or positive functional OOP. O'Reilly's current unassigned entry cannot
be interpreted as a bench appearance or zero minutes. Hume's current bench membership provides
a broad substitute category but no starting-formation slot.

| Control | FPL position | Provider position | Line / member | Source band | Diagnostic |
|---|---|---|---|---|---|
| Raya (154561) | GK | Goalkeeper | 0 / 0 | goalkeeper_line | UNKNOWN |
| Ødegaard (184029) | MID | Midfielder | 2 / 0 | interior_line_1 | UNKNOWN |
| Merino (195384) | MID | Midfielder | 2 / 2 | interior_line_1 | UNKNOWN |
| Gyökeres (224117) | FWD | Forward | 3 / 1 | forward_line | UNKNOWN |
| Gabriel (226597) | DEF | Defender | 1 / 2 | defensive_line | UNKNOWN |
| Eze (232413) | MID | Forward | 3 / 2 | forward_line | UNKNOWN |

All controls: Arsenal vs Nottingham Forest, 2025-09-13T11:30:00Z, SDP 2561926 / FPL 31, formation 4-3-3, starting XI, evidence Level 2.

The source-determined controls include an FPL MID in a provider Forward row as well as matching
broad categories. Both remain UNKNOWN for functional OOP; the rules were not designed around
the three named examples.

## PIT, immutability and reproducibility

`ObservedRole_t` here is a completed-match structural label. `PredictedRole_t` would be a
separate future model using prior role history and pre-cutoff manager/system, formation,
teammate-availability, opponent and venue evidence. **Actual target-match formation, lineup,
substitutions, shots, xG, touches or events must never predict that same match pre-deadline.**

Every observed row carries kickoff, provider match/player/team IDs, season-qualified FPL identity
where available, source hashes/versions, and these distinct timestamps:

- `source_known_at`: independently witnessed provider publication time; NULL throughout this
  sample because it was not supplied. Existing receipt fields named `known_at` are retained
  unchanged in provenance and are not relabelled as provider publication.
- `capture_known_at`: the latest actual metadata/lineup/event receipt and original retained
  knowledge boundary. The historical recorder's receipt and RawPayload timestamps differ by
  roughly 1–2 ms; both survive and the later original boundary is respected.
- `event_capture_known_at`: the events endpoint's own retained boundary, checked independently.
- `identity_known_at`: includes exact FPL player/fixture and corroborated club witness availability.
- `interpretation_known_at`: actual new interpretation time; it cannot precede any required
  evidence or the frozen generic rules.
- `available_at`: maximum of those source, capture, interpretation and identity boundaries.

The availability guard checks all boundaries and requires the observation's kickoff before
the requested cutoff. All 936 target pre-kickoff checks reject access. This contract is not
registered in a production feature-readable mart, scoring path or optimizer. Capturing historical
matches in September 2026 never creates historical 2025 deadline evidence.

Final execution commit: `13152e7d0174e372f245be03aa70d67c324f81a9`.
Final interpretation: `2026-09-08T05:08:40.015047Z`.
Starting task SHA: `8ac78b1c4afdcff57bb63b38decfd683332c4b04`, matching the owner instruction.
Execution used a clean V2 worktree. Initial source-audit receipts are retained separately; the
later club-provenance safeguard changed no source observations or diagnostic classification.

```powershell
python -m fpl.jobs.audit_player_role_source --retained D:/Personal/fpl-operations/verification/competitive-participation-20260907T070000Z --db D:/Personal/fpl-operations/sdp-primary-runs/pre-deadline-20260908T032637.982207Z/forecast-source.duckdb --output D:/Personal/fpl-operations/verification/player-role-source-audit-20260908T050700Z/result-r2.json
```

The runner is offline and read-only. Output must be a new path. Repeat verification uses
`--replay-of <original-result>` with a different output path and the same execution commit;
it preserves the original interpretation time and refuses any changed result, source or config.
It does not recast a replay as a new historical observation. Two separate Python processes
produced byte-identical final JSON, SHA256
`6a92fc3e421d3d74de543a080a61077364435545e5dcd7d1ff26068563faf607`.
The tracked result is an exact byte copy. New fingerprinted files have explicit Git byte preservation.

The source DB remains
`538560454f551a48eeaf015c318f7dea0fc6a34fccc56ee7f0e2b117ef7330d6`.
The untouched frozen research DB remains
`0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8`.
Original raw payloads are rehashed before/after; no payload, timestamp, revision, ledger row or
frozen result is overwritten. The operational DB itself was not opened for writing.

## Verification and repository boundaries

| Check | Result |
|---|---|
| Focused source/participation/capture/staging/PIT/no-pytz tests | 319 passed |
| Existing role and production SDP/workload regressions | 132 passed |
| Ruff `check .` | Passed |
| Strict mypy `src` | Passed, 204 source files |
| Changed-file formatting | Passed, four Python files |
| Git whitespace check | Passed |
| Same-input replay | Byte-identical |
| Independent raw/source/identity/availability reconciliation | 12,201 checks, zero failures |

The independent script and receipt are retained under
`D:/Personal/fpl-operations/verification/player-role-source-audit-20260908T050700Z/` as
`independent_raw_structure_audit.py` and `independent-raw-r2.json`. Receipt SHA256:
`26ead7a491127105d5bc700f9df618b8aa7b7a464d938a746dad3c699abb8cb9`.
It independently checks the raw nested arrays, all 201 substitution records, 936 player records,
knowledge boundaries, exact identities and club witnesses, including both unassigned NULL cases.

The full suite was not rerun. Previously documented Windows symlink privilege failures and
11 unrelated global-format failures remain inherited; no repository-wide pass is claimed.
The earlier console inspection hit Windows cp874 when printing an accented name; UTF-8 output
resolved the display issue without changing the retained JSON or any data.

Only new source-audit config, parser, CLI, tests, this report and its result were added; the
existing `.gitattributes` gained rules for these new files. Frozen configs/results, historical
role research, production models/features/storage and the prospective ledger have no changes.
Local main remains `ede17377216807ca2635879d1153e268dcd04fe6`; remote main/default remains
`4a58f079057d79189bd31a782e5f3c860b3c097f`. No merge, rebase, history rewrite, PR or default-branch
change is authorized or performed. Delivery is confined to the existing V2 branch.

**Exactly one next task:** design a pre-registered coarse role-inference study using formation
band plus prior role history, **without using same-match player statistics as predictors of
that same match's role**. That next task is not implemented in this session.
