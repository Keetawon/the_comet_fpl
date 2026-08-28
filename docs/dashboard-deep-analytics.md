# Deep analytics dashboard contract

Status: contract frozen and first implementation completed development-only on 2026-08-26. The
cumulative inputs introduced in dashboard read-model schema version 4 and retained in current
schema version 9 are sufficient for this implementation. Version 8's normalized team history and
version 9's player-actual fixture-time club/opponent identity do not change an analytics axis; this
document does not change a model, forecast vintage, optimizer objective, or published probability.

## Decision question

The two new pages answer a narrow question: which published player and club environments offer the
best trade-off between opportunity, cost or ownership, and an explicit downside measure over one
forecast vintage? They are exploration tools, not optimizers and not evidence that a model is
production-valid.

Deep analytics and forecast monitoring stay separate:

- deep analytics uses future forecast values to compare possible FPL exposure;
- forecast-versus-actual uses finalized outcomes to diagnose calibration and error;
- a large historical residual is never converted into a future buy or avoid signal.

The browser reads only the atomic static JSON export. It may filter, sum already-published expected
values, rank records, and compute Pareto/frontier or quadrant display geometry. It may not create a
probability, convolve a PMF, fit a trend, turn a per-90 rate into a forecast, or query DuckDB.

### What "efficient frontier" means here

The UI may call the direction-aware Pareto set an **efficient frontier** because it answers the
same exploration question as an asset screen: which individual choices are not worse on both of
the displayed return/risk axes? It is not a Markowitz mean-variance portfolio frontier, a convex
hull, or evidence that intermediate combinations are attainable. The browser never estimates a
covariance matrix or reruns the composer.

Expected points versus standard deviation and a Sharpe-like ratio are deliberately excluded. On
the published composer distributions, standard deviation is approximately proportional to the
square root of EV, so those views mostly rank the mean twice. The player risk/reward view instead
uses the exact published cumulative `P(total <= 2)` and `P(total >= threshold)` endpoints. The
team views use direct published attack/defence lambdas and expected clean-sheet count; they do not
claim to be a portfolio-return distribution. A future constrained portfolio frontier would need
joint, provenance-bearing samples or covariances plus FPL squad rules and must be computed and
published in Python, not inferred by the browser from marginal PMFs.

Chart focus is presentation state only. A user may set horizontal minimum/maximum bounds or show
only the already-classified frontier to inspect a crowded cluster. Pareto membership is always
computed first over the complete filtered eligible population; chart focus never reclassifies a
point, changes the exact table, or changes deterministic/AI insight facts. The page reports how
many eligible points are hidden. Invalid bounds fail open to the full chart. Probability-axis
controls are displayed as percentages and converted only for the viewport predicate; this does
not create or transform a model probability.

## Player analytics

The page binds to exactly one `(run_id, season)` and one exact cumulative endpoint `gw_to`, starting
at that run's fixed `gw_from`. The cumulative probability views are therefore unavailable for a
shifted start or venue subset. Inputs are `players.json` and the corresponding exact record in
`player_horizons.json`; no PMF reaches the browser.

Four views are allowed:

| View | Horizontal axis | Vertical axis | Better direction |
| --- | --- | --- | --- |
| Value frontier | deadline price, GBP | cumulative xP | left and up |
| Upside/downside | published inclusive `P(total <= 2)` | published inclusive `P(total >= 6/10/15)` | left and up |
| Differential | deadline ownership percent | cumulative xP | left and up |
| Past vs future | one directly published observed form rate/value | cumulative xP | explanatory only |

Every view includes a short, view-specific **How to read** note beside the controls. It names both
axes and their better direction, explains whether frontier membership applies, and states the
decision limitation: value is not a legal squad, probability endpoints are not summable,
differential is not a recommendation to avoid popular players, and past-versus-future is context
rather than a causal or model-quality claim.

The value, upside/downside, and differential fronts are Pareto-nondominated sets, not convex hulls and not optimal
squads. A player is dominated only when another eligible player is no worse on both axes and
strictly better on at least one. Exact ties use stable player `code` ordering for display without
claiming that either player dominates the other.

Filters reuse the Players page's position, team, price, minimum last-five average minutes, and
availability controls. The page also selects the observed form window and, for upside/downside,
the published haul threshold. A null axis value removes that point and increments a visible
"not plotted" count; null is never zero. Bubble size may encode ownership and colour may encode
position, but both need a legend and neither changes dominance.

Player analytics also consumes the directly published forecast provenance
`cold_start_player`. Cold-start rows are excluded from the analytics population by default and a
visible count explains the exclusion. An explicit **Include cold starts** control opts
them back in; when enabled, they participate normally in axis completeness and Pareto
classification and remain visibly labelled as cold starts. This is reporting-only eligibility:
it does not alter, replace, discount, or regenerate any player's published forecast value. The UI
must not infer cold-start status from form, current-season appearances, ownership, or missing
actuals. A model-side rule that bridges newcomers until three appearances would change forecast
probabilities and requires a separately named pre-registration and evaluation before it may become
a prospective default.

The accessible table beside the chart is authoritative for exact values. SVG points must be
keyboard-focusable. The page header and chart metadata identify the selected season, forecast
`as_of`, shortened run identifier, fixed `gw_from`, selected `gw_to`, and any latest-at-export
observed form anchor; the full run id, metric names, horizon, and provenance remain in the SVG
description/accessibility name and exact table. Axis titles always include the measure and unit.
A concise visible tooltip exposes player, club/position, both exact axis values, frontier state,
and cold-start state; it
must detect the chart edges and flip or clamp its placement so no content is clipped outside the
plot or viewport. Hover, pointer focus, and keyboard focus expose equivalent content. The
accessible name and authoritative table carry the full provenance even when the visible tooltip
uses shortened labels. The page must state that price and ownership are deadline-vintage overlays
and the probability distribution is raw and does not apply the reported availability multiplier.

Observed form is reporting context with a different time anchor: `players.json` attaches the
latest form snapshot available at static export to every forecast-run record. It is not a frozen
copy of form as known at the selected run's `as_of`, so it can post-date an older selected vintage.
Past-vs-future must label this limitation and expose each player's own `(season, as_at_gw)` anchor
in the exact table. It remains explanatory only and is never treated as future utility or a model
input; form availability still determines which context points are axis-complete and therefore the
view's coverage and descriptive fact population.

## Team analytics

The team page uses only modelled rows in `fixture_matrix.json` for one selected vintage. Current
schedule-only rows beyond that vintage may remain visible on Fixture Matrix but never enter these
analytics. Both legs of a double gameweek count; a blank week contributes no fixture and is not
fabricated.

Version 1 exposes three direct, risk-aware environment views:

| View | Horizontal axis | Vertical axis | Interpretation |
| --- | --- | --- | --- |
| Attack/defence environment | summed `lambda_against` (minimise) | summed `lambda_for` (maximise) | two-sided fixture environment |
| Attack with defensive floor | expected clean sheets (maximise) | summed `lambda_for` (maximise) | attacking opportunity plus defensive floor |
| Past vs future | observed team xG/GF or xGC/GA per match | future summed matching lambda | regime/context check only |

Each team view has its own **How to read** note naming both axes and directions. It distinguishes a
two-sided environment screen from an attacking screen with a defensive floor, and labels
past-versus-future as a scale/context comparison only.

`expected clean sheets` is the sum of per-fixture `probability_clean_sheet` values. It is an
expected count, not `P(at least one clean sheet)`. The browser must never add probabilities and
label the result as a probability. The page shows fixture count, per-fixture averages beside totals,
and the number of `stage_a_league_average_team` fallback rows. It exposes the raw lambdas that drive
the chart and repeats that Stage A is best read as a relative fixture signal, not a calibrated
current-season absolute scoring level.

The page may compute Pareto geometry with declared axis directions and median quadrants for visual
orientation. Labels use "club environment" or "exposure shortlist", never "optimal team",
"guaranteed", or "safe". Club outputs do not identify the best player inside a club, account for
price, minutes, set pieces, transfer costs, or the three-player club cap; users must carry a club
signal into Players or Plan Builder for asset-level decisions.

Team form follows the same latest-at-export rule and is not aligned to the selected forecast
vintage. Past-vs-future therefore labels the limitation and displays each club's own
`(season, as_at_gw)` anchor in the exact table. A later form anchor beside an older forecast is
explicit reporting context, not point-in-time model evidence or a causal comparison.

Team charts follow the same presentation contract as player charts: page/chart metadata shows the
season, forecast `as_of`, shortened run identifier, horizon, and axes with units. The edge-aware
visible tooltip carries the club, both exact axis values, and frontier/context state. Keyboard
focus exposes equivalent content, while the accessible name and exact table retain full run/horizon
provenance, fixture/fallback counts, and the form anchor.

## Shared insight facts

Each page emits a small deterministic fact packet for the shared insight panel. Eligible facts are
the selected scope, frontier members, strongest/weakest direct values, omitted-null counts,
fallback counts, and the caveats above. Fact construction may perform allowed sums, ranks, and
geometry only. It never sends the full player payload, a PMF, or private manager/custom-plan data.
The optional language renderer is governed by `docs/dashboard-ai-summaries.md`.

## Acceptance

- Pure unit tests cover dominance in every direction, ties, duplicate coordinates, and nulls.
- Player tests prove exact-vintage/exact-endpoint lookup and that no probability is summed or
  reconstructed.
- Team tests prove vintage isolation, horizon and venue filtering, double/blank-gameweek behaviour,
  expected-clean-sheet labelling, and fallback accounting.
- Both pages provide chart and table equivalents, loading/error/empty states, keyboard access,
  axis labels, legends, source vintage, and caveats.
- Horizontal chart bounds and frontier-only focus are user-adjustable presentation controls. Tests
  prove they leave the authoritative table, full-population Pareto membership, and insight scope
  unchanged, handle invalid bounds safely, and use percent units for probability axes.
- Player tests prove published cold-start provenance is excluded by default, can be included only
  by explicit user action, is never inferred from observations, and changes neither stored values
  nor the forecast contract.
- Every view has specific How-to-read copy. Tooltip tests cover pointer and keyboard parity, exact
  values/provenance, and edge-aware placement without clipping.
- Route and sidebar tests expose Player analytics and Team analytics without changing formal
  optimizer or manager-team state.
