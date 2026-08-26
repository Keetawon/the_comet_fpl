# Player and team prediction-versus-actual dashboard contract

Status: **implemented development-only, 2026-08-26**. This schema-version-5 correctness repair
replaces the former player-only aggregate with parallel player and team monitoring.

## Purpose and boundary

These pages diagnose a recorded forecast against immutable finalized outcomes. They do not select
players or clubs. A residual describes what happened relative to that vintage; it is not a future
selection feature and is never mixed into deep-analytics rankings.

Predictions remain keyed by `run_id`; outcomes carry no `run_id` and join only at read time. Both
come through the published BI export. The static emitter computes scoring metrics from exact stored
distributions. The browser only filters, groups already-published observations, draws geometry, and
renders the published metrics.

## Finality and coverage

Player-gameweek scoring is all-or-nothing. A `(season, gw)` is eligible only when every official
fixture in that gameweek is authoritatively final and every forecast fixture leg for the player has
an attached immutable outcome. In a double gameweek, one completed leg and one pending leg scores
nothing; comparing a full convolved forecast with a partial actual is forbidden.

Missing attached outcomes remain missing. Every run reports forecast, pending, final-eligible,
missing-outcome, scored, and distribution-scored counts so an empty or partial state cannot look
like zero performance.

Team scoring is at `(run_id, season, fixture, team_id)`. A fixture is eligible only after an
immutable two-sided outcome has been attached. The two rows must be reciprocal and agree on
home/away, opponent, score, gameweek, and kickoff; null or changed finalized scores fail closed.

## Ledger and BI amendment

The implementation includes an append-only `ledger_outcome_team_fixture` at
`(season, fixture, team_id)` beside `ledger_outcome_player_fixture`. Exact repeats are idempotent;
changed repeats are rejected. The outcome attachment job validates and appends both player and team
outcomes without mutating predictions. Current live fixture capture must persist official home and
away scores so prospective team outcomes do not depend on reconstructing goals from player events.

BI semantic contract version 3 adds:

- `goals_for_distribution` to `fact_forecast_team_fixture`, transported exactly from the ledger;
- `fact_finalized_player_fixture_outcome`, sourced only from the player outcome ledger;
- `fact_finalized_team_fixture_outcome`, sourced only from the team outcome ledger.

The prior mart-oriented `fact_player_fixture_actual` remains available for form/history consumers
during migration but is not the monitoring source. A defensive goal PMF is the opponent's exact
stored goals-for PMF for the same recorded fixture. It is never recreated from `lambda_against`.

## Dashboard read models, version 5

The ambiguous `forecast_vs_actual.json` is replaced by two explicit files. The old
`#forecast-vs-actual` route remains as a temporary navigation alias to the player page; old
schema-v4 files are not silently accepted as version 5.

### `player_forecast_vs_actual.json`

Observation grain: `(run_id, season, gw, code)`.

Each run carries provenance and coverage; overall blocks; splits by gameweek, position, and
forecast-time team; threshold calibration; and scalar observations for drill-down. An observation
contains identity, forecast xP, actual replayed points, signed error `actual - forecast`, absolute
error, CRPS when the stored PMF is valid, and the already-computed inclusive threshold
probabilities needed by calibration. PMFs are excluded from the JSON.

Score blocks publish row and PMF-row counts, forecast and actual totals/means, bias, MAE, RMSE, and
CRPS. Calibration covers inclusive `P(total <= 2)` and `P(total >= 2/6/10)`. If log score is added
later, zero-likelihood/off-support rows must be counted explicitly; a hidden epsilon floor is
forbidden.

### `team_forecast_vs_actual.json`

Observation grain: `(run_id, season, fixture, team_code)`.

Each observation carries team/opponent identity, gameweek, kickoff, venue, `lambda_for`, actual
goals for, attack residual, `lambda_against`, actual goals against, defence residual, clean-sheet
probability/outcome, attack CRPS from the team's PMF, defence CRPS from the opponent PMF,
clean-sheet Brier score, and the Stage-A fallback flag.

Each run reports coverage plus separate attack, defence, and clean-sheet score blocks; splits by
gameweek, club, venue, and fallback status; and calibration for goal and clean-sheet events. The
emitter validates two forecast sides and opponent reciprocity before scoring.

## Pages

Player prediction vs actual provides vintage/completed-gameweek filters, KPI cards, an
expected-versus-actual scatter with identity line, residual leaders and laggards, reliability
views, and the existing position/gameweek score tables.

Team prediction vs actual provides Attack, Defence, and Clean sheet views, predicted-versus-actual
scatter, cumulative club residual tables, gameweek and venue slices, reliability views, and a
coverage/finality notice. Positive attack residual means more goals than forecast; positive
defence residual means more goals conceded than forecast and is therefore worse. Labels state the
direction instead of relying on colour alone.

Both pages provide an accessible table equivalent. P2.4 will derive a deterministic insight packet;
its optional AI renderer may explain only those published facts under
`docs/dashboard-ai-summaries.md`. That summary layer is active next and is not part of this P2.3
implementation.

## Acceptance and implementation evidence

- A partial double gameweek scores zero player-gameweek observations; a fully final double
  gameweek aggregates both legs exactly once.
- Missing player outcomes increment coverage and never become zero.
- Team attachment writes exactly two reciprocal immutable rows; false/null finality, null scores,
  duplicates, inconsistent sides, and changed repeats fail closed.
- Team PMFs round-trip exactly through Parquet; an asymmetric fixture proves defence CRPS uses the
  opponent PMF.
- Hand-computed bias, MAE, RMSE, CRPS, Brier, and calibration examples match.
- Legacy runs without fixture transport produce explicit unavailable coverage.
- Both files are validated, hashed, counted, atomically published, and public-package allowlisted.
- UI tests cover populated, empty, pending, missing-coverage, null, and malformed-schema states.

Focused P2.3 tests pass across live score capture, reciprocal/idempotent/conflict-safe outcome
attachment, semantic-v3 declaration and Parquet projection, exact PMF round-trip, complete-GW/DGW
finality, hand-computed player/team scores, public-package allowlisting, strict frontend loading,
route aliases, and both page states. The dashboard production build and lint also pass.

Tests that execute the final generation-symlink swap require directory-symlink privilege. A plain
Windows shell without Developer Mode/elevation reaches the validated publish boundary and then
raises `WinError 1314`; that is an environment-specific OS permission limitation, not a metric,
finality, or product-validation failure. It does mean the formal atomic-publish gate is not called
unqualified green on that host until rerun in a symlink-capable environment.
