# Deep analytics dashboard contract

Status: contract frozen and first implementation completed development-only on 2026-08-26. The
dashboard read-model schema version 4 is sufficient for this implementation; this document does
not change a model, forecast vintage, optimizer objective, or published probability.

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

The value and differential fronts are Pareto-nondominated sets, not convex hulls and not optimal
squads. A player is dominated only when another eligible player is no worse on both axes and
strictly better on at least one. Exact ties use stable player `code` ordering for display without
claiming that either player dominates the other.

Filters reuse the Players page's position, team, price, minimum last-five average minutes, and
availability controls. The page also selects the observed form window and, for upside/downside,
the published haul threshold. A null axis value removes that point and increments a visible
"not plotted" count; null is never zero. Bubble size may encode ownership and colour may encode
position, but both need a legend and neither changes dominance.

The accessible table beside the chart is authoritative for exact values. SVG points must be
keyboard-focusable and expose player, axes, frontier state, vintage, and horizon to assistive
technology. The page must state that price and ownership are deadline-vintage overlays and the
probability distribution is raw and does not apply the reported availability multiplier.

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
- Route and sidebar tests expose Player analytics and Team analytics without changing formal
  optimizer or manager-team state.
