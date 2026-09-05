# Premier League SDP as a data source

`https://sdp-prem-prod.premier-league-prod.pulselive.com` is the JSON backend behind
premierleague.com. This document records what is known, what is assumed, and what happens when
an assumption turns out wrong.

## Status: first full real-provider capture validated

On 2026-09-05 the owner machine completed the first real capture and audit of five historical
seasons plus current completed matches. It retained 1,921 match-stat payloads (3,842 team sides),
staged 598,137 provider-field values, reconciled
all 2,280 scheduled fixtures without ambiguity, and populated the V2 marts under provider
`pl_sdp`. Exact evidence is recorded in
`docs/pl-sdp-real-provider-validation-2026-09-05.md` and the four `results/pl_sdp_*.json`
artifacts. This validates the data integration; it does not retroactively license a point-in-time
model evaluation from payloads first captured in September 2026.

The configured seasons endpoint returned HTTP 400 with content type
`application/problem+json` and the provider message `This endpoint is not enabled for API access`.
That is a provider response, not the earlier HTTP-CONNECT egress-policy denial. The initial
authoring environment's 403 therefore remains evidence about that environment only, not evidence
that the provider rejects access generally. The owner machine and the existing GitHub Actions
workflow remain the supported capture environments.

## It is not a published API

It is private infrastructure serving a public website. Consequences that are designed for
rather than hoped away:

| risk | mitigation |
| --- | --- |
| endpoint shapes change | envelopes are probed against an ordered list of known container keys; an unrecognised one RAISES rather than returning an empty list, so "no matches" and "the contract changed" cannot look alike |
| field names change or are added | every provider field lands in the tall metric store whether or not the dictionary claims it; `audit_pl_sdp` reports unmapped fields; extending the dictionary is a config change, not a migration |
| field names are wrong in our dictionary | each metric declares an ALIAS LIST, not one name; two aliases present with different values fail closed rather than letting declaration order pick |
| the provider goes away | raw payloads are retained verbatim and staging is rebuildable from them with no further requests |
| a statistic is restated later | landing is content-addressed, so a restatement lands as a NEW row beside the original and `known_at` stays meaningful |
| we hammer someone's website | ~1 request / 1.5s, bounded retries, `Retry-After` honoured and capped, pagination bounded three ways |

## Endpoints

| logical name | path | used for |
| --- | --- | --- |
| `seasons` | `/api/v2/competitions/{competition}/seasons` | configured discovery route; live provider returned HTTP 400 disabled on 2026-09-04 |
| `matches` | `/api/v2/matches?competition=8&season={id}[&matchweek={gw}]` | the match list |
| `match` | `/api/v2/matches/{match_id}` | one match's metadata |
| `match_stats` | `/api/v3/matches/{match_id}/stats` | **the team-side metrics V2 consumes** |
| `match_lineups` | `/api/v3/matches/{match_id}/lineups` | declared, not yet consumed |
| `match_events` | `/api/v1/matches/{match_id}/events` | declared, not yet consumed |

Competition 8 is the Premier League.

### Real match-list pagination

The live match-list response uses a `data` list plus a `pagination` object. On 2026-09-04:

* `page=0&pageSize=100` returned only 10 rows and
  `pagination={_limit: 10, _prev: null, _next: ...}`; those legacy page parameters were ignored;
* `_limit=2` returned match ids `2645195`, `2645198`; repeating the request with the opaque
  `_next` token returned `2645197`, `2645199`, proving cursor advancement;
* `_limit=20` returned the 20 completed 2026-27 GW1-2 matches and another `_next` token.

The client follows `pagination._next`, stops on an absent token or no forward progress, and retains
every raw page under the configured page cap. The completed capture enumerated all 380 scheduled
matches in each configured season rather than treating one page as season coverage.

## Season ids are measured and unmapped labels are refused

The mapping from a season label to the provider's numeric season id is not documented and
must not be guessed. Direct match-list requests on 2026-09-04 established these mappings from
records carrying `competitionId = "8"`, competition `Premier League`, and August kickoff dates
for the named season:

| season label | real SDP season id |
| --- | ---: |
| `2021-22` | 2021 |
| `2022-23` | 2022 |
| `2023-24` | 2023 |
| `2024-25` | 2024 |
| `2025-26` | 2025 |
| `2026-27` | 2026 |

These values are now recorded in `config/sources.yaml`. Asking for any other season still raises
instead of fetching something. Fetching the wrong year and labelling it correctly is worse than
fetching nothing: it would attach one season's football to another season's fixtures, and every
downstream check could appear internally consistent.

To populate it, where the provider is reachable:

```
python -m fpl.jobs.audit_pl_sdp --probe
```

The probe tries the configured seasons endpoint first. Because that route is currently disabled,
the confirmed mappings above came from direct match queries and were accepted only after checking
competition identity and real kickoff dates. Any future discovery fallback must apply the same
corroboration and must not treat a numeric convention as evidence.

## Operational sequence

```
python -m fpl.jobs.audit_pl_sdp --probe                    # only for an unmapped provider season
python -m fpl.jobs.backfill_pl_sdp --season 2024-25        # historical, per season
python -m fpl.jobs.audit_pl_sdp --stage                    # stage + measure identity + report
python -m fpl.jobs.build_db                                # rebuild, including the V2 marts
python -m fpl.jobs.capture_pl_sdp --lookback-days 5        # daily, after matches complete
```

`capture_pl_sdp` fetches the match list, then stats only for matches that have finished and are
not already captured, so a daily run costs a handful of requests. Where it sits relative to the
existing pipeline:

```
pre-match    FPL bootstrap / fixtures snapshot   schedule, prices, availability
post-match   SDP match + stats capture           what happened on the pitch
finalised    FPL outcome attachment              official points, append-only
```

## Fixture identity is measured, not assumed

`stg_fixture.pulse_id` already exists, and it is plausible that it equals the SDP `matchId`.
That is a hypothesis. `jobs.audit_pl_sdp --stage` measures it and writes
`results/pl_sdp_identity_audit.json` carrying `pulse_id_match_rate`, per-season counts, and
every ambiguity and contradiction found.

Resolution order per fixture:

1. `pulse_id == sdp_match_id`, then corroborated on season, kickoff (±3h), score, and teams;
2. otherwise candidates by season and kickoff, narrowed by teams and then score when multiple;
3. accept only one candidate whose Home/Away teams corroborate; anything else fails closed.

`pulse_id_match_rate` is `None`, not `0.0`, when no fixture carried a `pulse_id` — "the
question could not be asked" is a different finding from "the answer is no". Club names are
used only to narrow/corroborate a season-and-kickoff candidate, never as fuzzy identity: a name map
where one label resolves to two clubs across seasons drops that label rather than picking. A
fuzzy match that is wrong is indistinguishable from one that is right.

The full real audit answered the hypothesis: **FPL `pulse_id` is not SDP `matchId`**. The exact
match count was 0 of 1,900 pulse-bearing historical fixtures (0%). All 2,280 fixtures instead
resolved uniquely through the deterministic season/kickoff/team fallback; every kickoff and
home/away identity corroborated, with zero ambiguity, contradiction, duplicate claim, or unmatched
fixture. The fallback is therefore required data plumbing, not a temporary exception.

## Reconciliation, not reconciling away

`results/pl_sdp_reconciliation.json` compares, on identical rows, quantities both providers
measure by different routes:

* SDP `expected_goals` against the archive's summed per-player xG;
* SDP `shots_on_target_allowed` against the goalkeeper `saves + goals_conceded` proxy;
* SDP `expected_goals_allowed` (the opponent's xG, mirrored) against FPL's own per-player xGC.

Where they disagree, **both values are retained in separate columns**. The disagreement is
information about the sources, and forcing agreement would destroy it.

## The dictionary is verified conservatively and safe to be wrong

The first real match-stats payload exposed these exact field spellings:

* result/shooting: `expectedGoals`, `expectedGoalsOnTarget`, `totalScoringAtt`,
  `ontargetScoringAtt`, `attemptsIbox`, `attemptsObox`, `bigChanceCreated`,
  `bigChanceScored`, `bigChanceMissed`;
* territory/passing/width: `touchesInOppBox`, `finalThirdEntries`, `penAreaEntries`,
  `possessionPercentage`, `totalPass`, `accuratePass`, `fwdPass`, `backwardPass`, `totalCross`,
  `accurateCross`, `cornerTaken`;
* defending/press: `totalTackle`, `wonTackle`, `interception`, `totalClearance`,
  `outfielderBlock`, `ballRecovery`, `possWonAtt3rd`, `possWonMid3rd`, `possWonDef3rd`, `saves`;
* duels/discipline: `aerialWon`, `aerialLost`, `duelWon`, `duelLost`, `fkFoulLost`,
  `totalOffside`, `yellowCard`, `redCard`.

This verifies that those keys occurred, not what they mean or whether they exist in every season.
Several hypothesised aliases were proven **not** to be synonyms because they coexist with different
values: `attemptsIbox` versus `attIboxTarget`, `fwdPass` versus `totalFwdZonePass`, and
`yellowCard` versus `totalYelCard` are examples. The total-attempt/directional-pass measures are
mapped narrowly; ambiguous alternatives remain unmapped and losslessly retained in the tall store.
The full audit observed 246 provider fields: 42 mapped, 203 unmapped numeric, and one unmapped
nonnumeric field. Only `goals`, `expectedGoals`, and `ontargetScoringAtt` currently satisfy the
dictionary's independent-reconciliation rule and carry `verified_semantics: true`. Other core
fields are present and often pass strong football invariants, but remain semantically unverified
in config until independent evidence exists. The tall store and exhaustive metric-inventory report
mean a future mapping correction loses no provider value.
