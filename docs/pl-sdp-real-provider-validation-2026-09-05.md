# Premier League SDP real-provider validation — 2026-09-05

Status: **SDP integration gate green; full repository gate not green in this Windows environment;
retrospective model evaluation not yet licensed**.

This is the first comprehensive evidence record built from the live Premier League SDP provider. It is
additive to the frozen V2 development results. No model was rerun, retuned, promoted, or changed.
`results/v2_team_environment_development.json` remains immutable prior evidence.

## Access and capture provenance

The operator observed the owner machine reach
`https://sdp-prem-prod.premier-league-prod.pulselive.com` directly. GitHub Actions was not used.

| Probe | Result |
| --- | --- |
| `/api/v2/competitions/8/seasons` | HTTP 400, `application/problem+json`; provider says the endpoint is not enabled for API access |
| rate-limit headers on the failed catalogue probe | limit 300 requests / 60 seconds; 298 remaining |
| `/api/v2/matches` | HTTP 200, `application/json`; real cursor-paginated Premier League match records |
| `/api/v3/matches/{id}/stats` | HTTP 200, `application/json`; a bare two-side team-stat list |

The successful responses advertised cache windows of 5 seconds for matches and 30 seconds for
stats, with stale-while-revalidate/stale-if-error allowances. These headers, the disabled-catalogue
response, and the transient 504 are operator-observed session evidence; only successful response
bodies are retained in the raw database. The capture respected the configured 1.5-second pacing
and bounded retry policy. One match-stat
request initially returned 504; the idempotent resume fetched it successfully without replacing any
retained payload. A second resume also captured one newly completed current-season match.

The exact content-addressed raw store contains 1,946 payloads: 25 match-list pages and 1,921 match
stats payloads. Recomputed byte counts and SHA-256 values matched every retained stats payload.
Every stats payload parsed as exactly two distinct Home/Away sides with a numeric metric set; the
structural-failure count was zero.

## Confirmed season identifiers

The catalogue endpoint was unavailable, so each mapping was proved from real match records carrying
Premier League competition identity and kickoff dates inside the labelled season. No numeric-year
convention was assumed.

| Label | SDP season id |
| --- | ---: |
| 2021-22 | 2021 |
| 2022-23 | 2022 |
| 2023-24 | 2023 |
| 2024-25 | 2024 |
| 2025-26 | 2025 |
| 2026-27 | 2026 |

## Fixture identity result

The hypothesized identity is false:

```text
FPL fixture pulse_id == SDP matchId: 0 / 1,900 (0.0%)
```

All 2,280 FPL fixtures and all 2,280 SDP matches nevertheless resolved one-to-one. The fallback
selects candidates by season and kickoff, narrows multiple candidates by teams and then score, and
always corroborates Home/Away team codes before acceptance. The real SDP `teamId` equals the FPL
permanent `team_code`; it is not the season-scoped FPL team id.

| Check | Result |
| --- | ---: |
| fallback mappings | 2,280 |
| kickoff corroborated | 2,280 |
| Home/Away clubs corroborated | 2,280 |
| scores corroborated where both sources had a score | 1,920 / 1,920 |
| ambiguities | 0 |
| contradictions | 0 |
| duplicate SDP claims | 0 |
| unmatched FPL / SDP matches | 0 / 0 |

Example: 2021-22 FPL fixture 1 carries `pulse_id=66342`, while its uniquely corroborated SDP
`matchId` is `2210271`.

For 2026-27, the latest FPL capture had scores for 20 fixtures while SDP had already captured 21.
The additional result is match `2645221`, Ipswich 0-2 Liverpool; its absent FPL score is stale
source timing, not an identity contradiction.

## Real payload and metric inventory

Sample match `2645195` is competition `8` / Premier League, provider season `2026`, 2026-27 GW1,
Arsenal (`teamId=3`, Home) 3-0 Coventry City (`teamId=9`, Away), kickoff
2026-08-21 20:00 UTC, status `NormalResult`. Its match-stats response is 7,245 bytes with SHA-256
`014597c8a4a7f7f54781dc08e2ba1a8c1eb76f2888020b977100c9f0aeead2da`. The Home side has
180 provider fields, Away 158, with 193 in their union. Both sides map 40 fields. Examples:

| Metric | Home | Away |
| --- | ---: | ---: |
| expectedGoals | 1.8822 | 0.2043 |
| expectedGoalsOnTarget | 2.4369 | 0.0369 |
| totalScoringAtt / ontargetScoringAtt | 20 / 6 | 4 / 1 |
| attemptsIbox / attemptsObox | 10 / 10 | 1 / 3 |
| touchesInOppBox | 36 | 3 |
| possessionPercentage | 64.1 | 35.9 |
| totalPass / accuratePass | 616 / 565 | 347 / 271 |
| totalTackle / wonTackle | 9 / 6 | 4 / 2 |
| interception / totalClearance / outfielderBlock | 5 / 24 / 1 | 9 / 30 / 9 |
| ballRecovery / duelWon / aerialWon | 44 / 37 / 11 | 42 / 34 / 17 |
| saves | 1 | 2 |

Fields absent from a side's payload stay NULL, even where match context suggests zero. For example,
this response omits Home
`bigChanceCreated`/`bigChanceMissed` and Away `bigChanceScored`/`totalOffside`; ingestion does not
invent zeroes for them.

`results/pl_sdp_metric_inventory.json` is the exhaustive machine-readable semantics report. For
all 246 observed provider fields it records `provider_field`, an example value, mapped local field,
semantic-verification status, reason/evidence, notes, and numeric/text counts. It separately lists
all 203 unmapped numeric fields; `fastestPlayer` is the only unmapped nonnumeric field.

The following exact live fields have independently ingested/derived FPL corroboration and are
marked verified:

| Provider field | Local field | Independent evidence |
| --- | --- | --- |
| `goals` | `goals` | official fixture score and summed FPL player goals |
| `expectedGoals` | `expected_goals` | summed FPL player expected goals |
| `ontargetScoringAtt` | `shots_on_target` | FPL goalkeeper saves + goals-conceded proxy |

Verification applies to the exact first live key above; accepted fallback spellings do not inherit
that status and would be reported as unverified if observed. Other observed names—including xGOT,
shot zones, box touches, possession, passing, defensive actions, regains, and duels—are
corroborated by exact live spelling, official Opta terminology,
and zero-violation football invariants, but remain `verified_semantics: false` because no
independent numeric source has yet met the dictionary contract. Supporting definitions:
[Premier League stats clarification](https://www.premierleague.com/en/stats/clarification),
[Opta event definitions](https://www.statsperform.com/opta-event-definitions/), and
[Stats Perform xGOT definition](https://www.statsperform.com/insights/introducing-expected-goals-on-target-xgot/).

## Historical coverage

Counts are non-NULL values over captured team sides. The five completed seasons each have
760/760 sides. Current 2026-27 has 42 captured sides from 21 matches out of the 760-side schedule.

| Season | xG | xGOT | Shots | SOT | Box touches | Possession | Passes | Defensive constituents | Duels/aerials |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| 2021-22 | 6 | 4 | 760 | 739 | 759 | 760 | 760 | 760/760/701/760/760 | 760 |
| 2022-23 | 4 | 2 | 760 | 738 | 760 | 760 | 760 | 760/759/719/760/760 | 760 |
| 2023-24 | 6 | 6 | 760 | 754 | 760 | 760 | 760 | 760/760/708/760/760 | 760 |
| 2024-25 | 340 | 328 | 760 | 740 | 760 | 760 | 760 | 760/759/718/760/760 | 760 |
| 2025-26 | 760 | 743 | 760 | 744 | 760 | 760 | 760 | 760/759/720/760/760 | 760 |
| 2026-27 | 42 | 39 | 42 | 39 | 42 | 42 | 42 | 42/42/40/42/42 | 42 |

The defensive tuple is tackles/interceptions/outfielder blocks/clearances/recoveries. Tackles won,
final-third entries, penalty-area entries, total/accurate/forward/backward passes, middle- and
defensive-third regains, and all four duel fields also have near-complete or complete coverage.
The locally derived aggregate `defensive_actions` is not populated from SDP; its constituents are.

Provider `goals` is non-NULL on only 72-79% of team sides through 2024-25, strongly consistent with
historical zero omission. Those NULLs must not be filled with zero. Goals become complete in
2025-26. Standalone SOT and box touches are broadly available from 2021-22. In 2025-26,
goals+xG+box touches are complete and SOT is jointly non-NULL on 744/760 sides (97.89%); whether
that is sufficient for a future preregistered test has not been established.

The current coverage report's `capturable` denominator is 20 matches from the latest FPL snapshot,
while 21 SDP matches have stats. Therefore 42/40 appears as 105%; this is a source-timing mismatch,
not a valid completeness percentage. Scheduled coverage remains 42/760 (5.53%).

## Reconciliation and football sanity

Differences below are SDP minus the independent FPL/archive measure. Both source values are retained.

| Comparison | Rows | Exact | Mean diff | MAE | Range |
| --- | ---: | ---: | ---: | ---: | ---: |
| match score vs FPL fixture score | 1,920 matches | 1,920 | 0 | 0 | 0 to 0 |
| SDP goals vs summed player goals | 3,052 sides | 3,051 | 0.000328 | 0.000328 | 0 to 1 |
| SDP xG vs summed player xG | 1,106 sides | 5 | -0.009532 | 0.032890 | -1.023 to 0.7096 |
| opponent SDP xG vs FPL team xGC | 1,106 sides | 11 | -0.002172 | 0.025786 | -4.306 to 0.7296 |
| SDP SOT allowed vs saves+goals proxy | 3,715 sides | 2,985 | 0.033917 | 0.211575 | -2 to 3 |

One provider stats anomaly is retained: 2024-25 fixture 365 has official metadata/FPL score Chelsea
1-0 Manchester United, but its stats payload reports `goals=1` and `goalsConceded=1` for both sides.
No source was coerced to match the other. The largest xGC discrepancy is Fulham at Newcastle,
2023-24 fixture 168: opponent SDP xG 3.514 versus archive xGC 7.82; the six-row season slice is too
sparse for a season-level inference. SOT-proxy differences are expected because the proxy is not a
direct SDP measurement.

All nine row-level sanity families pass with zero violations across their applicable non-NULL rows:
two sides per match; no negative counts; SOT <= shots; inside+outside shots reconcile within one;
possession in [0,100] and two sides sum to 100 within 0.2; accurate passes <= passes; accurate
crosses <= crosses; and tackles won <= tackles.

## Database state

| Layer | Real SDP rows |
| --- | ---: |
| raw content-addressed payloads | 1,946 |
| staged match versions / distinct matches | 2,380 / 2,280 |
| staged team sides | 3,842 |
| staged tall provider metrics | 598,137 |
| fixture crosswalk | 2,280 |
| `mart_fact_team_match_stats_v2` (`provider='pl_sdp'`) | 3,842 rows / 1,921 fixtures |
| tactical-form mart (`provider='pl_sdp'`) | 14,784 |

Every provider match in the V2 fact has exactly two team rows. There are no side, crosswalk-key,
duplicate-claim, or Home/Away violations. Counts printed by the build (7,642 V2 rows and 29,400
tactical rows) include both `fpl_archive` and `pl_sdp`; they must not be reported as SDP-only.

## Verification gate

| Gate | Result |
| --- | --- |
| SDP/config/no-pytz focused pytest | 96 passed |
| full pytest | 2,079 passed, 4 skipped, 14 failed |
| Ruff check, `src tests` | passed |
| Ruff format check, `src tests` | failed: 219 files already formatted; 11 unrelated pre-existing files would be reformatted |
| strict mypy, `src` | passed, 133 source files |
| GitHub capture workflow | not used; local provider access succeeded |

The full repository gate is therefore **not green in this environment**. All 14 pytest failures
have the same unrelated Windows `WinError 1314` cause in BI export tests
that exercise atomic directory publication through `os.symlink`; the current process does not hold
the required symbolic-link privilege. The one SDP-relevant synthetic identity fixture exposed by
the first full run was corrected to use the live provider's permanent team-code semantics and passes.

## Modelling readiness

**Can we now genuinely test SOT? NO.**

**Can we now genuinely test territory/box touches? NO.**

Raw signal coverage is now real: SOT and box touches begin in 2021-22. The first season with
complete goals+xG+box touches and high-coverage SOT is 2025-26. But every historical SDP payload was first captured
in September 2026. The latest-value team-match mart and `load_team_frame` evaluation reader do not
preserve/filter a provider version by `known_at`; using the backfill in old folds would silently
give those folds future capture knowledge. Historical goal omission also makes a provider-goals
target outcome-dependent before 2025-26.

The earliest high-coverage joint raw-signal season is **2025-26**. The earliest possible honest
prospective season is **2026-27 after the 2026-09-05 capture**; the outcome horizon and sample size
needed for a genuine test are not established yet.

The single highest-value next experiment is to implement and test that as-of SDP reader, then
pre-register a newly named goals+xG+real-SOT walk-forward candidate. Territory should be a later
additive rung. The immutable historical C/D candidate identities must not be reused.
