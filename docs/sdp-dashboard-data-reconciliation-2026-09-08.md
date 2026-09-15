# SDP statistics and dashboard freshness reconciliation

This is a descriptive publication repair. The player model, configuration,
selector, optimizer, raw provider payloads, frozen forecasts and historical audit
results are unchanged. Starting commit: `9dd9961a03229502e24f4d4b1a6cc4e50ee6f772`.

## What was wrong

The builder exported fresh operational read models, but `--base-dashboard` then
packaged an entire older generation to obtain its existing optimizer plans.
Consequently the SDP sidecar was current while Players, Fixture Matrix and the
other shared actual-history consumers remained at GW2. The fix retains only
the existing plan blocks, with their exact original forecast-vintage identities.
Actuals, schedule, registered forecast exports and monitoring now come from the
operational generation. It does not run inference or an optimizer.

Publication now checks exact current FPL fixture/player identities against the
established actual/provisional exports. A newly dated build containing old actuals
fails this check. Provisional display coverage does not establish outcome finality
for scoring. Existing signed-points and complete-GW scoring rules are unchanged.

Separately, four incomplete-core SDP matches caused all statistics for both teams
to disappear from the descriptive export, including Arsenal's GW2 goals. Current
incomplete matches now undergo independent raw hash/status, latest revision,
PL/season, completed-match, kickoff, exact crosswalk and both-team checks. Measured
fields are exposed individually; absent/invalid fields stay NULL. The production
health result remains UNAVAILABLE for these matches and is not promoted by display.

An earlier display-only SOT correction was incorrectly mirrored into **total shots
allowed**. It now mirrors into **shots on target allowed**. Total shots allowed
retains the opponent's observed total attempts. The three original confirmations,
their actual timestamps and original raw sources are unchanged.
A later validated explicit provider SOT value supersedes the display correction
without deleting the earlier owner-confirmation record or blocking the refresh.

## Raw missing-field inventory

Audit of retained current PL sources at `2026-09-08T16:04:20.717244Z`: 30 completed
fixtures **across GW1–3**, 60 team-match rows. There are 92 omitted cells across
51 rows among the 42 source-native metric definitions (derived opponent metrics
excluded). All 92 are omitted aliases, rather than explicit NULL values. Goals
are present on all 60 rows; no blanket missing-to-zero conversion is justified.

| Missing source metric | Team-match rows |
|---|---:|
| Big chances scored | 25 |
| Offsides | 15 |
| Big chances missed | 13 |
| Big chances created | 10 |
| Saves | 6 |
| Possession won in attacking third | 5 |
| xGOT | 4 |
| Shots on target | 4 |
| Shots blocked | 4 |
| Outfielder blocks | 3 |
| Corners | 1 |
| Shots outside box | 1 |
| Accurate crosses | 1 |

The four core-field omissions are all `ontargetScoringAtt`:

| GW | Fixture | Team | Opponent | Total shots | Off target | Blocked | Display SOT |
|---|---:|---|---|---:|---:|---:|---|
| 1 | 7 | Aston Villa | Brighton | 6 | 6 | NULL | 0, owner-confirmed |
| 2 | 19 | Fulham | Sunderland | 11 | 3 | 8 | NULL, unresolved |
| 2 | 20 | Aston Villa | Arsenal | 7 | 5 | 2 | 0, owner-confirmed |
| 3 | 28 | Spurs | Forest | 11 | 7 | 4 | 0, owner-confirmed |

Shot accounting supports the zero hypothesis for these particular records; it
does not establish universal sparse-zero provider semantics, particularly for
optional or differently defined fields. Fulham remains unavailable. Do not infer
SOT from failure to score a goal. The full local 60-row and 92-cell CSV inventories
retain each source hash and original known-at time under
`D:/Personal/fpl-operations/verification/sdp-missing-fields-20260908T160420Z/`.

Arsenal's observed goals are **3, 1, 2 = 6** for GW1–3. The owner-specified
`/api/v1/matches/2645195/` was also fetched once at actual capture time
`2026-09-08T16:15:55.427733Z`: HTTP 200, 407 bytes, `homeTeam.score=3`,
`homeTeam.id="3"`, `period="FullTime"`. Exact response bytes are retained at
`D:/Personal/fpl-operations/verification/arsenal-source-check-20260908T161554Z/`;
SHA256 `669a81e6eae4eb86f849e825ff729c91d63ac1a35c3abef1dad9b173c0d0492a`.
This check did not rewrite operational or forecast source versions.

## Visible data and source limits

The Team tab defaults to an overview of goals, attempts, SOT, xG, possession,
passing, tackles and fouls. Visible group buttons expose all 45 SDP team metrics
(42 source-native plus three exact opponent mirrors), including territory,
crosses, defensive actions, discipline and set pieces. Cells with incomplete
selected-range evidence say **Unavailable**, rather than allowing a small `0/N`
coverage label to be confused with an observed zero. Trends, comparisons, tables
and CSV share the same nullable values and labelled correction layer.

Passing direction, long passes, possession and crossing describe observed play
patterns. No inferred tactical play-type classifier was introduced.

Detailed SDP player shots, SOT, passing and box touches remain unavailable in the
retained captures. The Players SDP tab exposes supported SDP participation and
explicitly labelled **FPL** detailed statistics. Current coverage is 1,890 FPL
player-fixture rows, 401 SDP lineup-player rows. Team counts are not allocated to
players. Actual FPL minutes remain the matched per-90 denominator.

## Verified local generation

Final generation: `D:/Personal/fpl-operations/verification/sdp-dashboard-final-20260908T161920Z/`.
Actual build interval: `16:19:21.057932Z`–`16:21:08.076357Z` on September 8.
Latest retained FPL source: `13:35:11.208041Z`; SDP: `13:53:35.925253Z`.
Latest included kickoff: September 6, `15:30Z`. The rebuild is not relabelled as a
new capture. **26/30 provider core-valid fixtures and three owner-confirmed display
corrections** remain separate. All 60 current team sides now retain their measured
descriptive fields, including sides belonging to those four incomplete matches.

The served player actuals contain 1,890 current rows and team actuals 60 current
rows over GW1, GW2 and GW3, reconciled to the sidecar. Both monitoring exports are
refreshed through the existing publisher, not a historical audit rerun.

The existing plans keep their September 3 cutoff and original identities. The
registered GW4–8 forecast vintage remains September 8, `03:52:24.844595Z`, with
registration `03:53:18.937809Z`; a current statistics export does not regenerate
either vintage. Serialized internal forecast provenance is represented by its
SHA256 in the public component labels; full source details and PMFs remain in
their original retained artifacts, not embedded in public labels.

| Artifact | SHA256 |
|---|---|
| Public ZIP | `ab66781876d96f665b34900ef9a1eb9be77f8df13f65102f72a57cf810184e5c` |
| SDP sidecar | `78fd78e0b9c79e59d3662f2d4168151f866ac5d75bc4ec6bd0fe724456714bad` |
| Public manifest content | `a13cf8d93819a2389953b49b8b63e9f986393ff36e5d963f08e6901fed520df8` |

HTTP retrieval from the running local preview matched the retained hashes exactly,
including the Arsenal goals and unresolved Fulham SOT. Preview:
`http://127.0.0.1:4173/#team-stat-sdp` and `#players-stat-sdp`, plus `#players` and
`#fixtures`. These URLs work on the existing owner host only. Refresh the page to
load the new generation. Plan Server remains on `127.0.0.1:8765`.

Browser skill discovery found the in-app Node browser runtime, but
`agent.browsers.list()` returned `[]`; its selector reported `No browser is
available`. Actual desktop/mobile visual verification and screenshots remain
blocked. HTTP hash checks and DOM integration tests are not claimed as visual QA.

## Verification and publication boundary

- Python focused, refresh integration, SDP-primary and scouting/forecast/optimizer
  isolation regressions: **85 passed**. No production forecast was regenerated.
- Frontend SDP contract/arithmetic/interaction tests: **41 passed**.
- Ruff checks pass; strict mypy passes for **228 source files**; six changed Python
  files pass formatting. Frontend TypeScript/Vite build passes; lint has nine
  existing Fast Refresh warnings, and the existing bundle-size warning remains.
- Existing Windows symlink privilege limitation is reported; the documented
  validated pre-publication copies are retained. The eleven inherited global
  formatting failures were not repaired or labelled green.
- Independent frozen-file reconciliation: **392/392 unchanged**, including the two
  GW4–8 forecasts, all model/config fingerprints and both audit identities.
  Receipt SHA256: `7d8c6b8430d6fc6021ceb936623536b293041da5e853bf954f6786d751545f5e`.
- Public-export isolation: the 13,352 previously published player rows and 440
  team rows retain all checked forecast values; 13,352 player-horizon rows retain
  every horizon endpoint (669,800 exact checks). The two existing plan documents
  are logically identical. The additional 1,308 player-vintage rows expose the
  already registered primary/shadow pair; they are not newly generated forecasts.

No production deployment, main merge or default-branch change occurred. The new
public package is retained locally; publication still requires owner review of
the existing broad draft PR and approval of its main-branch integration and
immutable release/pin update. No release asset was overwritten. GW4–8 remains
PENDING under the existing fixed-origin checkpoint contract.
