# Premier League SDP as a data source

`https://sdp-prem-prod.premier-league-prod.pulselive.com` is the JSON backend behind
premierleague.com. This document records what is known, what is assumed, and what happens when
an assumption turns out wrong.

## Status: implemented, never captured

**No SDP payload has ever been observed by this repository.** Every Pulselive,
premierleague.com and fantasy.premierleague.com host is refused by the build environment's
egress policy (HTTP 403 on CONNECT — a policy denial, not a server error). The adapter, staging
layer, identity crosswalk, jobs and tests are complete and exercised against vendored payload
shapes; the `pl_sdp` provider has zero rows.

Capture must therefore run where the provider is reachable. Two places qualify, and both are
established patterns in this repository:

* the owner's machine, which already runs the deadline runbook;
* a GitHub Actions workflow, which is how `snapshot.yml` has captured the FPL API daily since
  2026-07 without depending on any developer machine having egress.

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
| `seasons` | `/api/v2/competitions/{competition}/seasons` | season-id discovery (best effort) |
| `matches` | `/api/v2/matches?competition=8&season={id}[&matchweek={gw}]` | the match list |
| `match` | `/api/v2/matches/{match_id}` | one match's metadata |
| `match_stats` | `/api/v3/matches/{match_id}/stats` | **the team-side metrics V2 consumes** |
| `match_lineups` | `/api/v3/matches/{match_id}/lineups` | declared, not yet consumed |
| `match_events` | `/api/v1/matches/{match_id}/events` | declared, not yet consumed |

Competition 8 is the Premier League.

## Season ids are unknown and are refused rather than guessed

The mapping from a season label to the provider's numeric season id is not documented and
cannot be inferred. `pl_sdp.season_ids` in `config/sources.yaml` starts **empty**, and asking
for an unmapped season raises with instructions rather than fetching something. Fetching the
wrong year and labelling it correctly is worse than fetching nothing: it would attach one
season's football to another season's fixtures, and every downstream check would pass.

To populate it, where the provider is reachable:

```
python -m fpl.jobs.audit_pl_sdp --probe
```

It tries the `seasons` endpoint first and falls back to probing candidate ids and inferring the
label from the earliest kickoff each returns. It prints a YAML block to paste into
`config/sources.yaml`.

## Operational sequence

```
python -m fpl.jobs.audit_pl_sdp --probe                    # once: discover season ids
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

1. `pulse_id == sdp_match_id`, then corroborated on season, kickoff (±3h) and score;
2. otherwise a deterministic fallback on season and kickoff, narrowed by score, used **only**
   when exactly one candidate remains;
3. anything else fails closed.

`pulse_id_match_rate` is `None`, not `0.0`, when no fixture carried a `pulse_id` — "the
question could not be asked" is a different finding from "the answer is no". Club names are
used only to corroborate a match already made by other means, never to make one: a name map
where one label resolves to two clubs across seasons drops that label rather than picking. A
fuzzy match that is wrong is indistinguishable from one that is right.

## Reconciliation, not reconciling away

`results/pl_sdp_reconciliation.json` compares, on identical rows, quantities both providers
measure by different routes:

* SDP `expected_goals` against the archive's summed per-player xG;
* SDP `shots_on_target_allowed` against the goalkeeper `saves + goals_conceded` proxy;
* SDP `expected_goals_allowed` (the opponent's xG, mirrored) against FPL's own per-player xGC.

Where they disagree, **both values are retained in separate columns**. The disagreement is
information about the sources, and forcing agreement would destroy it.

## The dictionary is unverified and safe to be wrong

Every entry in `config/pl_sdp_metrics.yaml` carries `verified_semantics: false`, seeded from the
Opta/Pulselive vocabulary the site has historically used. Promote an entry only when a real
payload has been inspected **and** the reconciliation report corroborates the value. Until then
the tall store and the unmapped-field report mean a wrong guess loses nothing.
