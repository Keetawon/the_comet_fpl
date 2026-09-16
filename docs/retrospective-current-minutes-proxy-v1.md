# Current minutes comparator: explicit historical price proxy V1

Owner-authorized additive contract, 2026-09-07; base revision `ba24f23`.
Comparator identity: `retrospective_current_minutes_proxy_v1`.
Evidence class: `retrospective_archive_price_proxy_development`.
This is a comparator-input amendment, NOT a fitted candidate or a promotion.
No formal model run is authorized by this document itself.

## The narrowly relaxed input

The earlier audit correctly blocked exact current-default historical replay: all51 retained
bootstrap captures/30,483 player versions concern2026-27, not the evaluated historical seasons.
The owner now permits the measured `mart_fact_player_fixture.value` in FPL integer tenths ONLY
where unavailable historical deadline prices block the current cold-start minutes selector.
This is an explicit historical knowledge-time proxy, not proof of deadline availability and
not a repair to raw data. No `known_at` is rewritten or invented. Original source identities,
nullable actual capture times, database SHA256 and every consulted archive row are retained.

Existing positive deadline-known prices take precedence. Archive NULL or absent source rows
remain unavailable and block this proxy; they are not interpreted as a proven nullable API price.
A genuinely measured archive zero follows the unchanged zero-price helper no-op, with proxy
provenance retained. There is no average filling, interpolation, launch/final-season price
substitution, new pricing model, or change to goals/xG/minutes/stat targets.

The necessary established-teammate price witnesses for the existing cold cap are also in scope:
same stable current club, same position, eligible trailing history, most-recent eligible-season
appearance rate >=0.70 and at least10 rows. This does NOT use price to modify that established
player's own minutes prediction. All consulted witness prices remain in the cold row's lineage,
including witnesses that did not supply the maximum. The current cap, coefficients, conditional
playing shape and order of operations remain unchanged.

## Safe isolated interface

`validate.retrospective_minutes_proxy.reproduce_with_archive_cold_price_proxy` first calls the
unchanged `reproduce_default_minutes` with the same already-fitted V3 output and prior summaries.
Every successful non-price-dependent path returns that exact result. Its lazy archive loader is
not invoked for established players, sparse non-cold players, sufficient recent overrides, or
already-complete deadline-price evidence. Non-price blockers are never bypassed.

Only unresolved cold-price evidence invokes the separately typed `HistoricalPriceRoster`.
The declared archive target roster must be complete under the EXISTING historical roster proxy;
that declaration is not relabelled a complete live registry. Source population remains measured
archive player-fixture minutes, including DNP zeros and separate DGW legs. Stable identity and
the first eligible target-GW kickoff proxy are unchanged. Any missing roster, ambiguous identity,
or missing required own/witness price fails closed before returning a minutes distribution.

The wrapper is restricted to2023-24,2024-25,2025-26 and always emits retrospective-only evidence
with promotion forbidden. It is not a `PointInTimeView` option or a new prospective job argument.
Production jobs, model defaults, optimizer inputs, live price access and the strict reproduction
helper are untouched. Callers must preserve this evidence class into any downstream composition;
they may not extract the probabilities and relabel them prospective.

## DGW price and identity policy, fixed before scoring

Use the target season/GW's own archive fixture rows. For each required player, ALL retained
legs in that GW must agree on measured price, stable club and position. Retain all source legs;
never select the latest leg, maximum value, convenient earlier value or another gameweek.
Duplicate player-fixture identities fail. Even if the target's own leg has a usable value,
a contradictory second leg blocks that required player. No match outcome or realised minutes
enters price selection. First-kickoff batching still prevents target-GW outcomes updating priors.

The caller must provide the complete declared GW source rows, not silently prefilter conflicts.
This small pure helper deliberately does not query a mutable database, fit V3, infer registration
dates, or rerun the full points composer.

## Unchanged model mathematics

Reuse the exact current selector functions, not the frozen EV-backtest adapter:

- V3 is fitted on ALL prior measured archive minutes, not the current-club-filtered subset.
- Trailing summaries use the current frontier-season OR current-club eligibility rule.
- Three or more eligible recent rows select the existing shrunk equal-weight trailing-five
  bins (including the distinct all-zero/out-of-side regime); otherwise retain the fitted V3 shape.
- Only a price-sensitive cold fallback invokes the existing `apply_price_starter_prior`.
- Apply the existing `season_boundary_minutes` using the target fixture's month afterward.
- Retain the four bins0/1-59/60-89/90+, all fixed constants and current upstream priors.

The config pins the unchanged source hashes. These constants were developed on historical data;
replaying CURRENT behavior retrospectively does not make those historical seasons unseen tests.

## Coverage-only readiness; no fitting or scoring

Frozen database SHA256:
`0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8`.

| Season | Target rows | Cold price-dependent | No earlier archive history | Only excluded stale-club history | Conflicting/missing required price rows |
|---|---:|---:|---:|---:|---:|
|2023-24|29,725|327|302|25|0|
|2024-25|27,283|224|201|23|0|
|2025-26|29,747|270|239|31|0|
|Total|86,755|821|742|79|0|

The821 cold rows span808 player-GWs (317/222/269). All required cold own values and qualified
same-club/position witness values agree across their DGW legs. There are zero required identity
or NULL-price gaps. The same witness may be consulted by multiple cold players:1,801 consultations
(576/578/647) at cold-player-GW grain are NOT1,801 distinct players. This is input readiness,
not model performance or a changed-population evaluation.

## Later evaluation obligations

Both control and candidate must consume IDENTICAL proxy metadata and prior evidence. Freeze
their identities, parameters, population, run claim, hashes and gates in a separate clean
preregistration before fitting/scoring. Report all rows plus proxy-dependent, non-proxy-dependent,
cold-start and established slices. Excluding proxy-dependent rows is diagnostic only and must
never replace the nominal whole-population comparison. At full-points grain, cold-player minutes
may affect established players through shared attack allocation or bonus competition: propagate
the proxy dependency through those interactions rather than calling such outputs non-proxy.

No old result, contract, candidate identity or claimed run is reopened. No production promotion
follows from this source amendment or from a later retrospective result alone.
