# Goal-pattern reconciliation and four dashboard views

This is a descriptive follow-up to `sdp-goal-pattern-columns-2026-09-14.md`.
The earlier export and its initially unavailable set-piece column remain retained.
No model, forecast, optimizer, provider health rule or frozen experiment changes.

The retained 2026/27 sample is 39 completed fixtures across GW1–GW4, not 39
fixtures in GW4. GW4 remains partial. The source cutoff is unchanged:
2026-09-14T03:47:39.528929+00:00. This task made no provider capture.
The new interpretation was recorded at **2026-09-14T16:32:54.945584+00:00**;
it is not represented as knowledge available at the source cutoff.

## Accounting and coverage

| Classification | Goals |
|---|---:|
| SDP `goalsOpenplay` | 78 |
| Confirmed set-piece origins, including penalties | 25 |
| Opponent own goals | 5 |
| Unclassified origin | 1 |
| Official and SDP total | 109 |

All 78 team-match sides reconcile to official fixture scores. Full set-piece
counts are available for 77/78 sides. The Brighton side of Chelsea–Brighton is
partial: zero recorded open-play goals, one corroborated set-piece goal, one
opponent own goal and one unclassified goal. Its complete set-piece total stays
NULL, including in a multi-match average. The fourth chart can still show the
one confirmed goal alongside an explicitly hatched unknown segment.

Own goals are allocated to the beneficiary from the **opponent's** `ownGoals`
field. They remain a separate category even if their move began at a corner.
The accounting remainder is a reconciliation check, not a generic classifier.
Set-piece attempts and assisted set-piece goals alone do not establish totals:
rebounds can be unassisted, and a goal can follow a recycled delivery or throw-in.
Set piece here includes penalty goals, direct free kicks and corroborated
corner/free-kick/throw-in phases. No omitted field is converted to zero.

## Previously unresolved match sides

The following 14 sides include the previously checked Villa case and the 13
additional sides. The evidence manifest binds each side to season, fixture,
permanent club identities, kickoff, venue, SDP match identity and exact raw hash.
It retains the source links and a short interpretation note per side.

| Fixture | Scoring side / opponent | Confirmed set-piece goals | Evidence |
|---|---|---:|---|
| 2 | Brentford / Spurs | 1 | Kayode corner rebound. [Brentford report](https://www.brentfordfc.com/en/news/article/match-reports-brentford-3-tottenham-hotspur-0-premier-league-22-08-2026) |
| 3 | Everton / Palace | 1 | Barry quick-free-kick phase. [Sky report](https://www.skysports.com/football/everton-vs-crystal-palace/559446) |
| 4 | Hull / Man Utd | 2 | Ajayi corner rebound; Mendy free-kick header. [TNT commentary](https://www.tntsports.co.uk/football/premier-league/2026-2027/live-hull-city-manchester-united_mtc21883259/live-commentary.shtml), [Guardian report](https://www.theguardian.com/football/2026/aug/22/hull-manchester-united-premier-league-match-report) |
| 8 | Man City / Bournemouth | 1 | Guehi corner header. [Guardian report](https://www.theguardian.com/football/2026/aug/23/manchester-city-bournemouth-premier-league-match-report) |
| 12 | Everton / Bournemouth | 1 | Tarkowski after an uncleared corner. [PA report](https://www.belfasttelegraph.co.uk/sport/football/premier-league/everton-deny-bournemouth-victory-with-james-tarkowskis-stoppage-time-equaliser/a/160693537.html) |
| 15 | Newcastle / Spurs | 1 | Wissa corner second ball. [Spurs report](https://www.tottenhamhotspur.com/news/1087602/second-half-goals-seal-win-for-magpies) |
| 16 | Chelsea / Brighton | 3 | Lavia corner; Neto and Palmer throw-in phases. [Chelsea report](https://www.chelseafc.com/en/news/article/match-report-chelsea-4-3-brighton), [Guardian report](https://www.theguardian.com/football/2026/aug/30/chelsea-brighton-premier-league-match-report) |
| 16 | Brighton / Chelsea | 1 + 1 unknown | Gross late set-piece header; Yalcouye's initial restart remains insufficiently corroborated. Joao Pedro own goal stays separate. [Brighton report](https://www.brightonandhovealbion.com/media-article/mft-match-report-chebha-pl--report), [Chelsea report](https://www.chelseafc.com/en/news/article/match-report-chelsea-4-3-brighton) |
| 23 | Leeds / Brighton | 1 | Bogle recycled corner. [Leeds report](https://www.leedsunited.com/en/news/report-brighton-and-hove-albion-1-1-leeds-united) |
| 23 | Brighton / Leeds | 1 | Vuskovic corner header. [Brighton report](https://www.brightonandhovealbion.com/media-article/mft-pl-bhalee-match-report-2026) |
| 27 | Newcastle / Bournemouth | 1 | Ramsey free-kick second-ball rebound. [Match commentary](https://www.playmakerstats.com/live/2026-09-05-newcastle-bournemouth/12253117) |
| 29 | Chelsea / Arsenal | 1 | Rogers free-kick second ball. [Guardian report](https://www.theguardian.com/football/2026/sep/06/arsenal-chelsea-premier-league-match-report) |
| 31 | Aston Villa / Forest | 1 | Alysson short-corner header. [Guardian report](https://www.theguardian.com/football/2026/sep/12/aston-villa-nottingham-forest-premier-league-match-report) |
| 33 | Hull / Chelsea | 1 | Belloumi's second goal, corner rebound. [Chelsea report](https://www.chelseafc.com/en/news/article/match-report-chelsea-2-2-hull) |

An independently published description of Yalcouye's initial restart was not
strong enough to close the final gap. A fan analysis suggests a quick throw-in,
but official reports describe the rebound without establishing that initial
restart. The display does not upgrade this to confirmed. Match-report titles
alone are insufficient identity evidence: a reused Chelsea Arsenal-report URL
referred to another match and was rejected.

The other positive remainders are exhausted by six explicit penalties and two
direct free-kick goals. On 56 sides the measured total, open-play and opponent
own-goal values leave a zero remainder. These zeros are bounded accounting
results, not missing-field assumptions. Earlier seasons have different coverage
and unverified relationships; this audit does not fill their missing cells.

## Delivery contract

`config/sdp_goal_pattern_display_audit.json` is a display evidence manifest, not a
model configuration. Schema 7 adds nullable `goal_patterns` receipts. The raw
`sdp.set_piece_goals` remains NULL because the provider did not supply this total.
The shared UI accessor reads the separately audited value for tables, sorting,
averages, trends, comparisons and CSV. Tooltip/CSV provenance distinguishes
SDP capture time, audit time, raw hash, source links and unclassified goals.

Only the pinned match/side/raw version qualifies. A changed provider payload,
different fixture identity or contradictory official goal total does not inherit
the old interpretation. It returns to unavailable pending another source audit.
Provider-valid remains **35/39**, with **4 owner-confirmed** dashboard fixtures
separate. No goal-pattern receipt upgrades SDP core health or model eligibility.

The existing bottom section now contains four panels in order:

1. Attack — SOT/match vs xG/match, orange.
2. Defence — SOT conceded/match vs xGA/match, blue.
3. Goals vs xG — observed FPL goals/match vs source-labelled xG/match, purple.
4. Goal patterns — stacked open play, confirmed set piece, opponent own goal and
   unclassified counts, with matched game counts and a bounded scroll area.

All four share the existing season/GW/recent/venue/team filters and club selection.
The fourth panel needs receipts for every selected match before displaying a
club's total. The third includes own goals in the official team score and says so.
Neither finishing differences nor recent display windows imply future performance.

## Verification and local preview

65 focused Python tests, 62 source-supplement/SDP validity and selector regressions,
and 70 focused frontend tests pass. Ruff passes across
source/tests; strict mypy passes all 231 source files; changed Python formatting
and the TypeScript/Vite build pass. Existing nine Fast Refresh lint warnings and
the Vite chunk-size warning remain. Sandbox cache/temporary-directory access
needed scoped execution permission; no unrelated cleanup was performed.

The in-app browser returned `No browser is available` and an empty browser list.
Installed Chrome 153 was then used with a fresh isolated headless profile. Actual
render checks passed at desktop 1440px and mobile 390px, with no horizontal page
overflow, JavaScript exceptions or failed HTTP/assets. All four panels respond
to the team filter and share the selected club. The actual browser-generated CSV
download completed: 20 clubs, Villa set-piece average 0.25, Brighton complete
set-piece average blank with the unclassified-goal reason retained. A Windows
download-path issue in the test harness was resolved with a native profile path;
the application download code required no change.

Local evidence lives in the ignored
`data/artifacts/sdp-goal-pattern-review-20260914/`: desktop/mobile screenshots,
browser receipt, previous export, new export and byte-identical replay export.
New sidecar SHA256:
`3bffaf95b66e518ef15dc385af818deeae07e0aff74fcf5238fad00d681f564b`.

Removing only the new goal receipts, schema increment, goal-audit note and updated
set-piece catalog metadata reproduces the old sidecar logically exactly. Player
rows, raw metric cells, source timestamps and health counts are unchanged.
All **404** protected model/config/research/forecast fingerprints match; the 13
old mutable dashboard-base exports are explicitly outside that freeze comparison.
Neither historical audit nor player/team inference was rerun.

The existing local preview serves the updated assets and data at
`http://127.0.0.1:4173/#team-stat-sdp`. The optimizer server remains on port 8765.
This is local delivery, not a main-branch merge or production publication.
