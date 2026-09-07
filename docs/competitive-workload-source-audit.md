# Competitive workload source feasibility audit

Data-only local probe, 2026-09-07, 04:01:01–04:05:14 UTC. This is **not** model
evidence, a complete competition capture, or an operational minutes feed. Nothing here
enters Tactical Matchup V1. No database was opened or written; no ingestion configuration,
schedule, production default, player model, or optimizer input changed.

## Finding

**The existing SDP host serves all five requested competitive competitions.** Actual
match-list, lineup and event responses returned HTTP 200 for FA Cup, League Cup, Champions
League, Europa League and Conference League. The sampled payloads contain enough ingredients
to investigate participation/minutes reconstruction, but do **not** contain a direct
per-player minutes-played field. Complete workload coverage and the FPL player crosswalk
remain unvalidated.

### Discovery, not guessed IDs

The [official Premier League fixtures page](https://www.premierleague.com/en/matches/premier-league/2026-27)
loaded [this public website bundle](https://www.premierleague.com/resources/v1.52.5/scripts/bundle-es.min.js).
Its explicit competition constants identify the five IDs below. The same bundle declares
`/api/v2/competitions/{id}/details`, `/api/v2/matches`,
`/api/v3/matches/{id}/lineups` and `/api/v1/matches/{id}/events`.
No undocumented numeric ID search, authenticated route, or access-control workaround was used.

The real competition-details responses independently corroborate names/IDs and return
`seasons: [{season, id, ...}]`; every one explicitly maps `Season 2025/2026` to `2025`.
Requests without a season initially returned older matches, not the latest season. Therefore
a future collector must explicitly discover/select its season rather than assume omission
means current. Advertised catalogue dates below are **not** measured historical coverage.

| Competition | Verified SDP ID | Latest advertised season | Sampled 2025/26 match | Match-list / lineups / events |
| --- | ---: | --- | --- | --- |
| English FA Cup | 1 | 2025/26, ID 2025 | 2607219: Luton 4–3 Forest Green, 2025-10-31 | 200 / 200 / 200 |
| English League Cup | 2 | 2026/27, ID 2026 | 2568211: Barnet 2–2 Newport, penalties 2–4, 2025-07-29 | 200 / 200 / 200 |
| UEFA Champions League | 5 | 2026/27, ID 2026 | 2601789: Athletic Club 0–2 Arsenal, 2025-09-16 | 200 / 200 / 200 |
| UEFA Europa League | 6 | 2026/27, ID 2026 | 2601950: Midtjylland 2–0 Sturm Graz, 2025-09-24 | 200 / 200 / 200 |
| UEFA Conference League | 1125 | 2026/27, ID 2026 | 2602203: Dynamo Kyiv 0–2 Crystal Palace, 2025-10-02 | 200 / 200 / 200 |

The first four catalogues advertise seasons from 2013/14, Conference from 2021/22.
The 2026/27 fixtures were not enumerated; FA Cup's catalogue currently ends at 2025/26,
which is not proof that a later season's fixtures can never become available.
Friendlies, Summer Series and Community Shield were not requested.

## Actual fields and limitations

| Requirement | Observed evidence | Limit |
| --- | --- | --- |
| Fixture and competition | `matchId`, `competitionId`, `competition`, `season`, `round`, sometimes `matchWeek` | Cup rounds are not FPL gameweeks. Qualifying-round completeness is unmeasured. |
| Kickoff | `kickoff`, `kickoffTimezoneString`, `kickoffTimezone` | The samples carry `Europe/London` wall time even at continental venues; reuse the timezone-aware parser, not stadium-local assumptions. |
| Team identity | Match/event `homeTeam.id`/`awayTeam.id`; lineup `teamId` | Provider identity is not an automatically verified FPL crosswalk. |
| Player identity | Lineup `players[].id`, names, shirt number, `isCaptain` | 15 Arsenal IDs recur between the sampled PL and UCL rosters. That is narrow within-provider evidence, not an exhaustive FPL identity audit. |
| Starting XI / bench | `players[].position`, with `Substitute` and `subPosition`; sometimes `formation.lineup`/`formation.subs` | All ten recent team sides have exactly 11 non-substitutes. Bench counts vary, so never hardcode 9 or 12. |
| On/off events | `subs[].playerOnId`, `playerOffId`, `time`, `period`, `timestamp` | Match-time labels are strings, not measured player duration; half-time changes and stoppage time need explicit semantics. |
| Minutes played | **No direct player-minutes field** in sampled lineups/events | Must derive and independently validate participation intervals, or discover a separate direct source later. Do not label derived values as provider-reported minutes. |
| Extra time | Match 694835 has `clock: "122"`, `resultType: "PenaltyShootout"`; event `period: "ExtraSecondHalf"`, times 115, 120, 121 | A penalty shootout does not itself imply 120 minutes. Match 2568211 has a shootout but clock 99 and no sampled extra-time event. |
| Formation / position | E.g. Arsenal 4-3-3 versus Athletic 4-2-3-1; player broad position plus formation rows | Both Conference sides have `formation: {}`. Older 2013 samples also lack it. Broad roster position is not a validated player-role label. |
| Cards | `cards[].type`, `playerId`, `period`, `time`, `timestamp` | One recent FA Cup card has null `playerId`; do not invent the recipient or assume it changes on-field exposure. |

For the five recent matches, checks passed on all ten team sides: match/lineup/event team IDs
agree; roster IDs are unique; every substitution on/off ID exists in that side's roster;
and each nonempty formation's XI/bench IDs exactly match the position-labelled roster.
Eight sides have a formation, two do not. These are **sample checks**, not a season-wide
coverage percentage.

One genuine interval edge case already appears: Athletic player `619506` is substituted on
at minute 61 and off at minute 81. A future workload transform must handle multiple events
per player rather than assume every substitute stays on until full time. The raw events,
including nullable values, were preserved unchanged. No minutes were calculated in this probe.

### Existing collector cannot simply be switched to cups

The configured client already offers `fetch_match_lineups` and `fetch_match_events`; source
search found no capture/staging job consuming them. They remain declarations plus the raw
probe here, not an operational retained participation pipeline.

The PL-specific `is_completed_scored_match` predicate is also insufficient for cups. Its
completed-label set does not accept `PenaltyShootout`; the observed old Conference records
have `period: FullTime` but no `resultType`, so `parse_match_summary` falls back to numeric
`phase: "1"` and that predicate rejects them too. The 2013 extra-time sample even retains
`period: Live` despite an old kickoff, a shootout result and a 122-minute clock. This is a
provider-status contradiction to resolve explicitly, not permission to loosen the PL job.
No production predicate was changed.

## HTTP and retained provenance

Local execution used `D:\Personal\fpl-operations\.venv\Scripts\python.exe` and the repository's
`PlSdpClient` with configured 30-second timeout, 1.5-second within-client pacing, at most four
retries and existing capped `Retry-After` handling. Requests were sequential and only the
first two match-list records were requested per competition/season; no pagination or backfill
was performed. Separate one-shot processes do not share that client's pacing clock, so a
future combined collector must keep a single client for all requests.

There were **38 SDP HTTP responses, all 200**, and three official-page/asset responses
(one normal 302 redirect, two 200). All SDP responses were `application/json`; no 403/407
egress denial, 429, provider error, or retry occurred. Match/events responses carried
`Cache-Control: max-age=5, stale-while-revalidate=120, stale-if-error=86400`; lineups used
`max-age=10, stale-while-revalidate=600, stale-if-error=86400`; details used max-age 30.
CloudFront `Via`/`X-Cache` were retained; no rate-limit header was surfaced. These caching
headers are not a publication SLA.

The generic probe printer attempted list extraction on three successful object-shaped
responses (competition details and the extra-time lineup/events) and printed
`SdpSchemaError`; this was its optional display helper expecting a list, **not** a failed
HTTP request or evidence of an incompatible provider response. All bodies were retained
and parsed correctly by the subsequent object-aware offline inspection.

All 41 response bodies are retained byte-for-byte, with SHA256, URL, selected HTTP headers
and actual capture time in:

`D:\Personal\fpl-operations\verification\competitive-workload-20260907T040018Z\`

Files:

- `requests.jsonl`: complete HTTP manifest, including raw filenames and hashes.
- `competition_samples.json`: initial older match discovery and sample response shapes.
- `recent_samples.json`: competition-details payloads, confirmed seasons, recent samples and hashes.
- `offline_inspection.json`: roster/side accounting, fields, missingness and integrity results.
- `probe.py`: bounded, no-database network probe using the existing client.
- `inspect_retained.py`: runnable offline hash, roster and reciprocal-identity checks.
- Timestamp/SHA-named `.raw` files: exact source bytes, including the official page/bundle.

Selected hashes:

| Evidence | SHA256 |
| --- | --- |
| Official JS competition/endpoint definitions | `3d131eda71095165a45254906ba65540fc9d3777f91ba8603c8d15d5f64dcd1b` |
| UCL 2601789 lineups | `e9fdcbd0ede6b8b18cc7aefd87b1898152df897f39558fe9d4022a7c69b9e4e1` |
| UCL 2601789 events | `882cd0743875bbdbd69f2b7a1bc3ec4c2423a5b038db9e0f77fd4cdf950bc818` |
| Conference 2602203 lineups, missing formation | `a4bf6c5a0010c7e37af7b77778ebc87328ea61e059950ab91a1670f21b4b6f6f` |
| League Cup 694835 extra-time events | `44d17b6f51b3c573b28dcaf63173c86a236b8ac82ef1dcd0d2ee40b99edea1f9` |

Executed probe modes: `initial`; `url` for the official matches page and its discovered
bundle; `competitions`; `sdp /api/v2/competitions/1/details`; `recent`; and `sdp` for the
two extra-time sample endpoints. The standalone `inspect_retained.py` check exited 0:
41/41 hashes/byte counts valid, ten recent team sides reconciled, zero roster/substitution
identity failures. There is no source-code change requiring a new repository test suite.

## Smallest next data step

Preregister a **separate data-only participation pilot** for a handful of PL clubs over a
short competitive window, retaining fixture revisions plus lineups/events on persistent
storage. First reconcile the provider player IDs to stable FPL `code`, independently check
normal-time, half-time, substitute-on-then-off, red-card and 120-minute exposure, and audit
all expected competitive fixtures including qualifying rounds. Keep raw known-at timestamps
and schedule revisions; do not use future lineups as historical pre-match knowledge.

Only after that pilot proves completeness should a durable cup/Europe workload collector be
proposed. The existing PL tactical evaluation and daily PL ingestion remain unchanged.
