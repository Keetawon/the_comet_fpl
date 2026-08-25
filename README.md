# FPL points-prediction system

Produces, for every FPL player and gameweek, a **full distribution of fantasy points** —
not a point estimate — because the three questions a manager actually asks have three
different answers:

| Question | Statistic |
|---|---|
| Who do I transfer in? | `E[points]` over the next N gameweeks |
| Who do I captain? | `P(total points >= 10)` through an exact cumulative gameweek endpoint |
| Is this differential worth it? | `Var(points)` and effective ownership |

A single `xP` answers only the first.

**Current status: the data foundation, development-only forward pipeline through Stage E,
append-only forecast/outcome ledger, versioned BI semantic export, atomic static publish boundary,
and eight-route decision dashboard are implemented; no forecast component or squad recommendation
is promoted as production-valid.**
Phase 1 Candidates V1 and V2 were fitted under the fixed walk-forward contract and correctly not
promoted. Candidate V3's development result was invalidated for leakage; its leakage-safe successor
V4 was evaluated once and also missed the fixed gate, so `trailing_goals_attack_defence` remains the
Stage A model. Phase 2's minutes Candidates V1/V2/V3 are development-only; V2/V3 fail the frozen
starter-ranking gate. Phase 3's team-coupled, minutes-gated attacking Candidate V3 is the best
development-evaluated candidate but remains unpromoted. The exposure-weighted successors have each
now had their single historical development run and neither is promoted: goals V4
(`exposure_weighted_xg_team_share_attacking_goals_v4`) misses its aggregate bar at -0.44% and ties
V3 (-0.01%), though it wins both guardrails and gains monotonically in the xG-covered seasons
(+1.24% / +5.03% / +7.14%) while the two pre-xG seasons drag the pooled figure down; assists V2
(`exposure_weighted_xa_team_share_assists_v2`) clears the baseline bar at +1.85% but is **behind the
V1 already in the composer** (-0.11% log). V2 wins the bounded guardrails by separating players far
more aggressively than V1, but every confident reliability bucket over-predicts in both models and
V2 puts five to ten times as many rows there, which the log score charges for and a bounded
quadratic score does not -- resolution bought with reliability, not a narrower distribution.
Stage D v3 composes the components by seeded Monte-Carlo and awards bonus through a joint
per-fixture BPS simulation across both clubs.

The prospective job now emits a reproducible, provenance-bearing JSONL artifact containing one
full-points distribution per `(season, gw, code)`. Stage E consumes only that artifact and produces
a deterministic legal squad, lineup, captain, bench, and bounded multi-GW transfer plan. Both are
explicitly development-only. The provenance-guarded Stage D EV walk-forward backtest has now been
**run once** under contract 1.2 over the final ten observed gameweeks of 2025/26
(`results/ev_backtest_2025_26_gw29_38.json`). Its headline is negative for the current default: the
**V1 diagnostic comparator outscores the V3/coupled primary on every scored metric** (log 2.0510 vs
2.0899, NDCG@20 0.7926 vs 0.7762), the primary's one apparent win being aggregate calibration
(EV/actual 1.0163 vs 0.9473). It decides nothing -- the comparator is pre-registered as a diagnostic
and not a gate, and the run carried the composer P(play) double-gating defect plus historical
roster and first-kickoff cutoff proxies. **That calibration win has since been measured to be two
errors cancelling**: the composer applied P(play) twice and destroyed 11.11% of all goal and assist
mass, which offset an over-prediction elsewhere; with the defect fixed the same rows give EV/actual
1.0430. The frozen artifact keeps its defective numbers and is not re-run. A component
decomposition then showed the composer accurate to -0.5% across what it actually models, with the
residual bias being the unmodelled cards / own goals / missed penalties, and identified a second
real defect: the goals-conceded penalty was charged in full to short appearances. **That is now
also fixed** -- conceded goals are binomially thinned to a measured per-bin on-pitch exposure
(0.344 / 0.813 / 1.0, which is *not* minutes/90), cutting the clean-sheet and penalty errors by 66%
and 58%. Both repairs move the aggregate total the wrong way, because it was previously near zero
only through offsetting errors; the residual is now concentrated in the unmodelled negative
components (417 points) and a low-scoring-window regime effect. See
`docs/phase4-composer-p-play-double-gating-fix.md`.

**A third defect explained the composer's under-dispersion, and is also fixed.** The frozen run's
PIT-80 coverage of 0.7404 against a nominal 0.80 traced to the trailing-five minutes estimate being
a raw `counts / n` over at most five rows: every marginal took one of six values, and
`P(play) = 1.000` was routine. Measured over 101,306 point-in-time rows, a raw `5/5` actually
predicts appearance **0.897** and a raw `0/5` predicts **0.039**, so nailed starters had no lower
tail and fringe players no upper tail. `models/minutes_shrinkage.py` replaces it with a
point-in-time Dirichlet posterior whose concentration was fitted on 2021-22..2024-25 with 2025-26
held out, plus a separate regime for zero-appearance windows. On the same 8,224 rows:
**PIT-80 0.74538 -> 0.79985**, CRPS +2.46%, mean log score +51.59%, clean-sheet error -0.4%. MAE
regresses 3.73%, which is the expected point-versus-distribution trade and is reported rather than
omitted. Unlike Stage B's shrinkage candidates it *gains* rank resolution (within-position AUC on
`P(60+)` +1.02%), because the raw estimator tied pure-absence and substitute-only windows together.
See `docs/phase4-composer-minutes-shrinkage-fix.md`. On the first live 2026/27 GW1-5 run -- the
cross-summer boundary the estimator was never fitted against -- the degenerate `P(play) = 0.0` is
gone (0 of 570 players, was one on the raw estimator), but the boundary surfaces a bounded, narrow
under-prediction: a nailed starter rested through the May dead rubbers has an all-zero window mapped
to the out-of-side floor, and the `0.7 * prior + 0.3 * recent` blend caps him at ~0.71 (Vicario
0.576 against a 0.816 prior). It is left unfixed before GW1 -- conservative, ~1-7 players, and a
change to a measured-optimal blend -- and recorded in
`docs/phase4-season-boundary-appearance-underprediction.md`. The no-transfer pruning defect is
fixed, and the optimiser now emits an immutable, provenance-bearing decision artifact whose reader
revalidates legality offline. Before operational use, horizon availability semantics and future
price/selling-value handling remain explicit unmeasured scenario gaps. The append-only ledger now
retains player-gameweek, player-fixture, and team-fixture forecast vintages, with finalized outcomes
attached separately. The versioned BI semantic/star export, atomic Parquet/static-JSON publish
boundary, platform/custom-plan separation, lock/exclusion flow, and dashboard are implemented
development-only. Dashboard read-model schema v4 publishes backend-convolved cumulative player
xP, `P(<=2)`, and `P(>=2/4/6/10/15)` at each exact horizon endpoint. xP may be summed in the
browser; probabilities never are, and raw PMFs stay out of the bulk payload. The values are raw
and availability-unadjusted, with independent gameweeks an explicit composition assumption. The
emitter validates full precision first, then transports named values in six-decimal compact rows;
the browser only decodes their versioned field order. The dashboard exposes six read-only
analytic/decision routes plus Plan Builder
and a browser-only Squad Draft sandbox. The local, development-only manager path now reconstructs
a public manager squad into an immutable private capture, applies current bank/purchase/selling
values and remaining free transfers, and can optimize transfers from the first forecast
gameweek. Squad Draft remains bound to one exact forecast vintage and recorded rules snapshot,
enforces roster shape and club caps, reports deadline-price cost and xP, and deliberately does not
enforce the standard budget; it can now be seeded manually, from an optimized plan, or from an
exact manager capture;
the Players form repair is implemented in code/tests with view-specific starts, xG/90, xA/90,
bonus, BPS, DC, clean-sheet, on-pitch goals-conceded, saves, and xGC columns. Those defensive
fields are backward-looking observed form only; future player-level saves/DC/GC/xGC forecasts
remain unavailable and are never synthesized from club primitives. A failure-atomic local
development database rebuild and atomic BI/static republish completed on 2026-08-19, so the fields
were visible in that local generation; migration alone would leave existing rows NULL. That dated
refresh did not itself satisfy or replace the historical final-deadline capture. Plan Builder
supports both fresh-squad
custom scenarios and local manager-ID own-team transfer planning. The public endpoint does not
expose purchase/selling prices, so the manager path currently supports GW1-started entries only,
reconstructs them from committed GW1 launch prices plus public transfer replay, maps season-scoped
elements to stable player codes, and fails closed on incomplete provenance or a selectable-player
registry mismatch. Authenticated My Team access, hosted manager
accounts, future price changes, and production validation remain open.
The official 2026/27 payload confirms 17 configured scoring fields, and official published
rules now confirm the seven thresholds/units that payload omits. Two edge cases remain
explicitly unexercised, so the ruleset is not described as fully validated. The Phase 1
evaluation contract is defined before model fitting — see [Phasing](#phasing).

---

## Quick start: clone to populated database

```bash
git clone <this repo> && cd the_comet_fpl

# 1. Environment (Python 3.12, uv)
uv venv --python 3.12
uv pip install -e '.[dev]'

# 2. Download the archive and build the database (~2 minutes, ~20 MB downloaded)
uv run python -m fpl.jobs.build_db

# 3. Verify
uv run pytest
```

`build_db` downloads five seasons from the
[vaastav/Fantasy-Premier-League](https://github.com/vaastav/Fantasy-Premier-League)
archive into `data/archive/`, lands them into `data/fpl.duckdb`, and builds every layer.
It is idempotent — rerunning produces the same database — and failure-atomic. The job clones
the existing database into a sibling work file so append-only live snapshots survive, applies
declared additive schema migrations with new historical values left NULL, rebuilds the
archive-derived layers there, and uses one atomic replacement only after success. If the
production database changes during the build, promotion aborts and preserves the newer file.
Add `--refresh` to re-download.

Then:

```bash
uv run python -c "
import duckdb
con = duckdb.connect('data/fpl.duckdb', read_only=True)
con.sql('SELECT * FROM mart_fact_team_match LIMIT 5').show()
"
```

### Requires network access to

- `raw.githubusercontent.com` — the historical archive
- `fantasy.premierleague.com` — the live API, for `daily_snapshot`

If the live API is unreachable, `build_db` and the whole test suite still work: they use
the archive only. **No test requires network access at all** — the suite is skipped or run
against vendored fixtures. See [Snapshots (R5)](#snapshots-r5).

---

## Layout

```
config/       sources, scoring, data quality, and versioned evaluation contracts
src/fpl/
  artifacts/  stable prospective-points and optimizer-decision transport contracts
  ingest/     archive.py, fpl_api.py, live_snapshot.py, snapshot_files.py
  storage/    db.py, schema.sql
  transform/  crosswalk.py, facts.py, quality.py
  features/   pit.py   -- point-in-time access layer (R4)
  models/     scoring plus Stage A team, Stage B minutes, and Stage C attacking models
  optimize/   Stage E squad, lineup, captain, and bounded transfer planning
  validate/   walk-forward folds, metrics, baselines, harnesses, and guarded dev runners
  jobs/       build/load/snapshot plus prospective forecast and optimiser entry points
tests/
.github/workflows/               -- CI plus daily and finalized-history R5 capture
```

## Storage layers

`raw_` (as landed, immutable) → `stg_` (typed, deduped, crosswalked) → `mart_`
(modelling-ready). DuckDB, single file: five seasons is ~139k rows and a few MB, so a
database server would be unjustified operational cost.

Raw archive tables are **all-VARCHAR** on purpose. `""` and `"0.0"` must stay
distinguishable, because "not measured" and "measured as zero" are different facts and
zero-filling biases every rate. Casting happens once, at the `stg_` boundary.

### The mart is split by table role, not by layer

| Table | Rows | Read by |
|---|---|---|
| `mart_fact_player_fixture` | 138,707 | **the feature builder, only** |
| `mart_fact_team_match` | 3,800 | the feature builder |
| `mart_dim_player` / `mart_dim_team` | 1,777 codes / 100 | the feature builder |
| `mart_fact_player_fixture_live` | versioned current season | the feature builder through `known_at` |
| `mart_team_fixture_live` | versioned current schedule | the feature builder through `known_at` |
| `mart_target_player_fixture` | 138,707 | the validation harness and dashboard |
| `mart_target_completeness` | per season × ruleset | the validation harness |

`mart_fact_player_fixture` holds **components only — no points column of any kind**,
enforced by test. Recorded `total_points` lives at `stg_player_fixture` and nowhere else.

`mart_target_player_fixture` carries `total_points_as_recorded` alongside
`points_under_rules_<ruleset>` recomputed from components by the calculator. The
recomputed column is the point: recorded points are denominated in whichever season's
rules applied at the time, so they are not a cross-season quantity and cannot be a model
target. Models predict, and backtests score against, `points_under_rules_2026_27`. The
recorded column is retained purely to benchmark against FPL's own `ep_next`, which was
produced under contemporaneous rules.

`mart_target_completeness` records which components a ruleset needs that a season never
measured — applying 2026/27 rules to 2021-22 understates defenders, because
`defensive_contribution` did not exist then. The bias is unavoidable; recording it lets
the harness exclude or weight those seasons instead of trusting a broken target.

## Design rules

Violating any of these silently invalidates the model, so each is enforced by test rather
than by discipline.

- **R1 — never model `total_points`.** Scoring rules change between seasons, so recorded
  points from 2022-23 and 2026-27 are different quantities. Model the events, then apply
  the current season's scoring function.
- **R2 — scoring rules are configuration.** Every constant lives in
  `config/scoring_<ruleset>.yaml`. Adding 2027/28 is a new file, not a code change.
- **R3 — model distributions, not expected values.** FPL scoring is a set of step
  functions (clean sheet needs exactly 0 conceded; appearance points jump at exactly 60
  minutes; DC pays at exactly 10 or 12). For all of these `E[f(X)] != f(E[X])`.
- **R4 — point-in-time correctness is enforced by tests.** See below.
- **R5 — snapshot the live API every day, forever.** The API retains only the current
  season at per-gameweek granularity. At rollover it is destroyed permanently.
- **R6 — separate the minutes model from the rate models.** Rates from all history,
  minutes from recent trajectory. A blended points-per-gameweek average rates James Hill
  (27.3 minutes over the first ten gameweeks of 2025-26, 90.0 over the last ten) as a
  fringe player when he is a nailed starter.

### R4: how leakage is prevented

Features never receive a database connection. They receive a `FeatureSource` — a
capability restricted to the component fact tables, which cannot name a `mart_target_*`
table. Four runtime layers plus two static ones:

1. `AsOf` rejects naive datetimes, so timezone cannot silently move the boundary.
2. No caller SQL; column names are validated against a per-table allowlist.
3. `observed_*` appends `kickoff_time < as_of` itself, after any caller filters.
4. Live facts and schedules additionally select only versions with `known_at <= as_of`.
5. `schedule()` may return future rows but projects only pre-kickoff columns — a future
   outcome is absent, not merely filtered.
6. An **AST scan** fails any module in `features/` that imports duckdb, calls `.execute(`,
   or names a table directly.
7. **Truncation equivalence**: for a sweep of `as_of` values, results built against the
   full database must equal results built against a database physically truncated to
   `as_of`. A forgotten filter returns extra rows and fails.

Layer 6 is the testable form of "shifting `as_of` earlier never changes an already-computed
value": a value computed at `T` is invariant to the existence of data after `T`.

## Snapshots (R5)

The FPL API keeps only the current season at per-gameweek granularity; `history_past`
gives season totals only. At season rollover the per-gameweek data is destroyed
permanently, and **missing a week is unrecoverable**.

Two execution paths:

```bash
# Lightweight daily capture: bootstrap, fixtures, and active event-live.
uv run python -m fpl.jobs.daily_snapshot

# After a gameweek finalises: also capture every authoritative element-summary history.
uv run python -m fpl.jobs.daily_snapshot --player-history

# Proves the full code path without network, against a local stub server.
uv run python -m fpl.jobs.daily_snapshot --dry-run

# Verify and ingest one or more committed workflow snapshot packages.
uv run python -m fpl.jobs.load_snapshots snapshots/daily/2026-08-22/2026-08-22T060000Z
uv run python -m fpl.jobs.load_snapshots snapshots/player-history/2026-27/gw-1
```

`daily_snapshot` **exits non-zero with an explicit diagnostic** when egress is blocked. A
capture header, payload manifest, legacy raw rows, and typed live rows commit in one DuckDB
transaction; a mid-write or loader failure rolls all of them back. Checksums are revalidated
when committed file packages are loaded.

`.github/workflows/snapshot.yml` is the lightweight durable path: a daily 06:00 UTC cron
captures `bootstrap-static`, `fixtures`, and event-live. `player-history.yml` checks daily for
a newly finalized gameweek and then captures every `element-summary` into one compressed,
checksummed package. Element history, not the gameweek-aggregated live feed, supplies the
`(season, code, fixture)` rows needed for double gameweeks. Both workflows are shell-only so
a broken Python environment cannot stop irreplaceable raw capture.

It also logs the **first `kickoff_time` in the fixtures payload** on every run. As of
2026-07-26 that endpoint still returns the completed 2025-26 fixtures while
`bootstrap-static` has already rolled over to 2026/27 teams and deadlines, so the snapshot
history records the exact day the fixtures endpoint rolls over.

## Scoring

```python
calculate_points(stats: PlayerMatchStats, rules: ScoringRules, position: Position) -> int
```

Validated by replaying **all 29,747 player-fixture rows of 2025-26** against that season's
rules and reproducing the recorded total exactly — 29,747/29,747, 100.000%.

Reaching 100% requires that **card penalties are not gated on minutes played**: FPL scores
a booking for an unused substitute. Ashley Barnes, 2025-26 GW22 — 0 minutes, 1 yellow,
recorded −1 — is the row that distinguishes a correct calculator from a 99.997% one, and
it has a named regression test.

`goals_scored.GK` (10 points) is **untested either way**: no goalkeeper scored in 2025-26,
measured across all 29,747 rows, so no replay can exercise it.

For 2026/27, provenance keeps three evidence classes separate: values present in the live
payload, values stated by captured official rule sources, and branches exercised by real-data
replay. The seven payload omissions are now covered by official rules; `goals_scored.GK` and the
zero-valued forward clean-sheet branch remain explicitly unexercised rather than being promoted
by documentation alone.

## Data notes worth knowing

Every one of these is a test.

| Hazard | Detail |
|---|---|
| `element` id is reassigned yearly | Salah is 233 → 283 → 308 → 328 → 381. Stable key is `code` (118748). Match rate 100.000%. |
| Team ids are reassigned yearly | Id 3 = Brentford (2021-22) → Bournemouth → Burnley (2025-26). |
| The grain is `(code, fixture)` | Double gameweeks are real: 2,217 duplicated player-gameweek cells in 2021-22, 409 in 2025-26. |
| 2025-26 has 10 exact duplicate rows | Same player, same fixture, twice — all byte-identical. |
| Schema drift, NULL never zero | `expected_*` and `starts` from 2022-23; `defensive_contribution` family 2025-26 only; `mng_*` 2024-25 only. |
| 2022-23 `expected_*` are present-but-**zero** for GW1–15 | Repaired to NULL via `config/data_quality.yaml`. See below. |
| `AM` is not a position | It is the Assistant Manager element (`element_type` 5), 2024-25 only: 322 rows, 20 managers, all 0 minutes. Excluded, not coerced. |
| Goalkeeper `defensive_contribution` is always 0 | Measured max 0. |
| `xP` is contaminated | Derived from `ep_this` scraped after the gameweek finished. Dropped at ingest; tested absent from every `stg_`/`mart_` table. |
| Player-level home/away and opponent-tier splits | Deliberately excluded — a player faces top-six opposition ~6 times a season. Home advantage is a league constant (1.092 home, 0.908 away, mean 1.463). |

### The 2022-23 expected_* defect

The columns exist from GW1 but are recorded as literal `0.0` until GW16: team xG sums to
exactly zero across gameweeks 1–15 while 344 goals were actually scored. Left alone, the
season's `team_xg` mean is 0.963 against actual goals of 1.426, and
`corr(team_xg, goals)` is 0.332 versus 0.587 / 0.593 / 0.502 for the three later seasons.

This is the "zero vs null" hazard occurring *inside* a season, so a column-presence check
misses it. It is the most likely cause of an xG-trained team model underperforming a
goals-trained one, and it is repaired declaratively in `config/data_quality.yaml` rather
than patched in transform code, so the repair is auditable and its effect is asserted.

## Development

```bash
uv run pytest                      # full suite, no network required
uv run ruff check . && uv run ruff format --check .
uv run mypy                        # strict, on src/
```

Tests marked `archive` need the built database; run `build_db` first or they skip.

## Phasing

| Phase | Deliverable | Status |
|---|---|---|
| **0b** | Historical/live ingestion, PIT facts, scoring calculator, snapshots | **complete** |
| 1 | Stage A team model + validation harness | harness run; **V1/V2 fitted, gate not cleared**; V3 development invalidated; V4 development-only (not promoted) |
| 2 | Stage B minutes model | frozen baselines/metrics/walk-forward harness complete; V1/V2/V3 development-evaluated (development-only, none promoted); V2 and V3 both fail the v1.2 starter-ranking gate — V3 wins every proper score but ranks starters worse, refuting the concentration-adaptive hypothesis |
| 3 | Stages C/D player events + simulation | attacking V1 historical probe and team-coupled V2/V3 development-evaluated; exposure-weighted goals V4 (-0.44% vs baseline, ties V3) and assists V2 (+1.85% vs baseline, -0.11% vs the incumbent V1) each run once, development-only, neither promoted; Stage D v3 composer, prospective forecast, and the GW29-38 EV backtest all run and development-only, with the V1 comparator outscoring the V3 primary |
| 3b | Stage E optimiser + prediction ledger | optimiser, stable input/decision artifacts, no-transfer repair, append-only forecast/outcome ledger, and private public-manager capture plus selling-value/free-transfer-aware transfer planning implemented development-only; horizon availability and future price/selling-value changes remain open |
| 4 | BI semantic export + dashboard | versioned semantic/star export, atomic Parquet and schema-v4 static JSON with cumulative player outcomes, platform/custom plan separation, locks/exclusions, six analytic routes, manager-aware Plan Builder, and Squad Draft with optimized/current-team handoffs implemented development-only; real-deadline validation and authenticated hosted manager operation remain open |
| 5 | External competition calendar — only if Phase 2 shows lift | not started |

Phase 3b is an addition to the original phasing, which ended Phase 3 at simulation and had no
phase delivering Stage E. The implemented optimiser respects the verified 2026/27 squad, budget,
club, formation, captain, bench, free-transfer, and hit rules. Its fixed-squad ILP is exact; its
multi-GW transfer path is explicitly bounded. See
[`docs/stage-e-squad-optimizer.md`](docs/stage-e-squad-optimizer.md) and
[`docs/prospective-points-artifact.md`](docs/prospective-points-artifact.md).

The immutable forecast ledger retains every recorded pre-deadline player-gameweek,
player-fixture, and team-fixture vintage with its `as_of`, input hashes, and model/component
identities; historical vintages are never overwritten. Finalized outcomes attach through a
separate append-only job. The versioned BI semantic export publishes pivot-friendly Parquet, and
the atomic static publisher derives the dashboard's JSON read models from that export, including
the schema-v4 cumulative player endpoint file. Dashboards
and BI tools consume those read-only outputs, never the mutable production DuckDB. The eight
dashboard routes are Summary, Fixture matrix, Players, Next GW suggestion, Forecast vs actual,
Optimizer audit, Plan Builder, and Squad Draft. Formal platform default/diagnostic plans remain
separate from user-custom plans and browser-local drafts. The local manager-ID path keeps its
immutable capture and manager context private, while the public pack strips user-custom and
manager data. See `docs/manager-team-suggestions.md`, `docs/bi-semantic-contract.md`,
`docs/bi-export-contract.md`,
`docs/dashboard-json-contract.md`, and `dashboard/README.md`.

`docs/phase0-design.md` records the audit behind the schema decisions, including where
measured values diverged from the original specification and why.

`docs/phase1-evaluation-contract.md` fixes the Stage A entity/grain, point-in-time cutoff,
observed-gameweek walk-forward, required baselines, proper distribution metrics, calibration
outputs, reporting slices, and promotion gates before the first candidate is fitted.

`docs/phase2-evaluation-contract.md` pre-registers the Stage B (player minutes) contract. Version
1.0 froze the registered player population, `(season, code, fixture)` grain, four ordered
minute bins whose 60-minute boundary is cross-checked against the scoring rules, required
baselines, metrics, and promotion gate. The exact baselines, metrics/calibration, and
baselines-only player-fixture walk-forward harness are implemented and offline-tested; see
`docs/phase2-stage-b-implementation.md`. The baseline-only full-archive run is **complete as a
baseline-only development and calibration record** (position prior = lowest mean log score at
1.04916; a future 1% aggregate lift would need ≤ about 1.03867; no baseline dominates, since
`trailing_5_player_minutes` leads on RPS and both Brier margins), recorded in
[`docs/phase2-stage-b-baseline-development.md`](docs/phase2-stage-b-baseline-development.md).
It is a development number under two unversioned historical proxies (target roster, first-kickoff
cutoff), so real-deadline knowledge-time validity is unproven. Additive amendment 1.1
pre-registers Candidate V1 `shrunk_trailing_5_player_minutes_v1` without changing
the frozen v1.0 gate or any comparison policy; see
[`docs/phase2-stage-b-candidate-v1-design.md`](docs/phase2-stage-b-candidate-v1-design.md).
Candidate V1's exact closed-form estimator, true six-observed-gameweek inner selector, and dedicated
development runner are now implemented and deterministically offline-tested. The runner scores the
candidate and four unchanged baselines on identical rows, records fold parameters, opens DuckDB
read-only, rechecks clean Git/config/model-source/database provenance, and emits a complete strict-JSON
reconciliation record only after postflight verification. It has now been run once as a clean
historical development run: Candidate V1 reaches mean log score 0.74198 (+29.28% over the
position-prior comparator) and improves on the best baseline value of every metric **except the
within-position Spearman-p60 starter ranking** (where it regresses, 0.69090 vs 0.70851), but it is
**development-only and not promoted** — the historical target roster and first-kickoff cutoff are
unversioned proxies, so real-deadline knowledge-time validity is unproven; see
[`docs/phase2-stage-b-candidate-v1-development.md`](docs/phase2-stage-b-candidate-v1-development.md).
The baseline number remains a development number, not an upper bound. Additive amendment 1.2
(contract v1.2) tightens the promotion gate for **future** candidates only: each bounded guardrail
(RPS, Brier-any, Brier-60+) is now measured against the best baseline value of its own metric, and a
new `maximum_spearman_p60_relative_regression: 0.0` starter-ranking gate requires a candidate to rank
who starts and plays 60+ at least as well as the best baseline. It evaluates nothing, changes no
v1.0/1.1 policy, and does not re-judge V1. Additive amendment 1.3 (contract v1.3) pre-registers
Candidate V2 `recency_weighted_trailing_player_minutes_v2` — V1 with a geometric recency weight on
the same trailing-5 window (it reduces exactly to V1 at decay = 1.0). V2 and its development runner
are implemented and offline-tested, and V2 has now been run **once** as a clean historical
development run (2026-07-30, against a pristine rebuilt archive): mean log score 0.72625, the best
of the five models on all four bounded scored metrics and an improvement on Candidate V1 on all
five, but it **fails the v1.2 starter-ranking gate** (aggregate Spearman-p60 0.70071 vs the best
baseline 0.70851, −1.10%; nine of ten diagnostics pass). It is development-only and not promoted
(unversioned proxies); see
[`docs/phase2-stage-b-candidate-v2-development.md`](docs/phase2-stage-b-candidate-v2-development.md).
Additive amendment 1.4 (contract v1.4) pre-registers Candidate V3
`concentration_adaptive_shrinkage_player_minutes_v3` — V2 with a shrinkage strength that adapts to
the concentration of the weighted history (`alpha_eff = alpha·(1 − λ·C)`; reduces exactly to V2 at
λ = 0). It is diagnosed from V2's by-position evidence: V2's only gate failure (starter ranking) is
almost entirely goalkeepers, whose near-deterministic histories a uniform shrinkage blurs. V3 and
its development runner are implemented and offline-tested, and V3 has now been run **once** as a
clean historical development run (2026-07-30, against a pristine rebuilt archive whose baselines
reproduce V1/V2 bit-for-bit): mean log score 0.71205 — the best of all five models on every proper
score (log/RPS/Brier-any/Brier-60+) — but it **fails the v1.2 starter-ranking gate** (Spearman-p60
0.69726 vs the best baseline 0.70851, −1.59%, worse than V2). The hypothesis is refuted: goalkeeper
ranking barely moved (0.8153 → 0.8156) and λ > 0 was selected in all 175 selectable folds, so
adaptation sharpens the distribution but does not recover ranking. Development-only and not
promoted; see
[`docs/phase2-stage-b-candidate-v3-development.md`](docs/phase2-stage-b-candidate-v3-development.md).

---

## The Stage A bar

```bash
python -m fpl.validate.harness            # every baseline, every fold
python -m fpl.validate.harness --season 2025-26
```

181 walk-forward folds, 3,640 team-fixture predictions, one fold per *observed* gameweek.
These are the fixed comparators both Stage A candidates are judged against.

| baseline | mean log score | mean CRPS | PIT 80% | raw 80% | MAE |
|---|---|---|---|---|---|
| `trailing_goals_attack_defence` | **1.5003** | 0.6393 | 0.798 | 0.930 | 0.943 |
| `trailing_xg_attack_defence` | 1.5107 | 0.6460 | 0.803 | 0.944 | 0.966 |
| `naive_fdr` | 1.5262 | 0.6580 | 0.799 | 0.929 | 0.976 |
| `promoted_team_pooled_prior` | 1.5481 | 0.6739 | 0.794 | 0.929 | 1.012 |
| `league_home_away_goals` | 1.5522 | 0.6764 | 0.794 | 0.929 | 1.016 |

A candidate must reach **1.4853** to clear the contract's 1% relative-lift gate, without
regressing CRPS, in every reported season.

### Candidate V1: a documented non-promotion

`dixon_coles_team_goals` — schedule-adjusted joint Poisson ratings on `team_code`, exponential
time decay with the half-life chosen inside each fold, and a promoted-club prior — scores
**1.4886**, beating every pre-registered baseline. It does not clear the gate:

| gate | result |
|---|---|
| log score lift ≥ 1% | **fail** — +0.78% |
| CRPS does not regress | pass — +1.29% |
| calibration (PIT 80%) | pass — 0.800, error 0.000 |
| ≥ 20 folds | pass — 181 |
| every reported season ≥ 1% | **fail** — 2021-22 −0.24%, 2023-24 +0.80%, 2025-26 +0.47% |

The diagnosis is not "the model is weak", it is *where* its information comes from. Split by
phase of season, it wins exactly where cross-season history and xG exist and loses where they
do not:

| season | GW1–9 | GW10–19 | GW20–38 |
|---|---|---|---|
| 2021-22 (no prior season, no xG) | −0.40% | −0.07% | −0.30% |
| 2022-23 | **+2.09%** | +1.35% | +0.54% |
| 2023-24 | **+2.61%** | +1.04% | −0.12% |
| 2024-25 | +0.10% | **+2.30%** | +1.86% |
| 2025-26 | −0.34% | −0.75% | +1.48% |

2021-22 is the archive's first season, so the model's three advantages — cross-season decay,
the xG signal, and a promoted prior built from earlier seasons — all have nothing to work
with there. Requiring it to beat a trailing ratio by 1% using strictly less information than
the trailing ratio uses is a bar it cannot clear by being better at football.

Per the contract, that is a **documented non-promotion, not a reason to move the bar**. The
gate stays as pre-registered; the baseline ships until a candidate clears it honestly.

### Candidate V2: a documented non-promotion

Contract 1.3 records V1's implementation defects and fixes them in a separately named
`dixon_coles_team_goals_v2`. Its search space was committed before one outer evaluation. No
outer baseline or threshold changed.

| result | Candidate V2 | best required baseline | gate |
|---|---:|---:|---|
| mean log score | **1.4939** | 1.5003 | **fail** -- +0.4284%, needs +1% |
| mean CRPS | **0.6355** | 0.6393 | pass -- +0.5842% |
| PIT 80% coverage | 0.803 | 0.798 | pass -- error 0.003 |
| fixture coverage | 3,640 / 3,640 | 3,640 / 3,640 | pass |
| leakage failures | 0 | 0 | pass |

The evaluation ran on 2026-07-28 over the complete 2021-22 through 2025-26 archive. Percentage
lifts use the unrounded aggregates retained by the harness; the displayed scores are rounded to
four decimals.

The per-season log gate fails in 2021-22 (-0.14%), 2022-23 (+0.15%), 2023-24 (+0.55%),
and 2025-26 (+0.02%); only 2024-25 clears 1% (+1.43%). CRPS also regresses in 2021-22,
2022-23, and 2025-26. All seasons pass calibration, coverage, fold-count, population, and
leakage guardrails.

The exact six-gameweek holdout ran in 171 folds; the first 10 used the declared no-decay,
8-match fallback. Half-life selections were 40/80/160/320/640/no-decay in
27/43/42/18/16/35 folds. Prior selections were 2/4/8/16/32 matches in
72/20/41/24/24 folds. The 2-match boundary is recorded evidence for a future structural
hypothesis, not permission to widen V2 after observing it.

**xG or recorded goals as the training signal?** **xG — wherever xG is measured.** Over the
three seasons with complete coverage it wins by +0.71% relative lift and takes each of them
individually on both proper scores. The pooled five-season figure says the opposite only
because it is measuring xG's absence: 2021-22 carries no xG at all, so the xG baseline
degenerates exactly to the league intercept (1.5736 = 1.5736), and 2022-23 carries it for 64%
of team-fixtures. Quoting the pooled number as "goals win" would be reading a data gap as a
result.

**Contract amendment 1.1 — the calibration gate now names its metric.** The original gate,
`interval_80_maximum_absolute_error`, did not say which 80% interval it meant, and the obvious
one is wrong for counts. The central interval between integer quantiles covers strictly more
than 80% by construction, and the excess measures the discreteness of the distribution rather
than the model. That makes the gate point backwards: at a true rate of 1.80 a *correct* model
misses 80% by 0.164 and fails, while a model predicting 2.40 — 33% too high — misses by 0.002
and passes. Across five true rates the raw measure was closest to nominal at the correct rate
in zero cases; the randomised-PIT band coverage is exactly 0.80 at the truth in all five. The
gate is now `pit_interval_80_maximum_absolute_error`, same 0.05 tolerance, with the raw figure
still reported. Recorded in `config/phase1_evaluation.yaml` under `amendments:` and explained
in [`docs/phase1-evaluation-contract.md`](docs/phase1-evaluation-contract.md#amendments); the
loader rejects a version bump that has no amendment record. Made with zero candidates
evaluated, which is the only condition under which amending a pre-registered gate is honest.

### Candidate V3: development-only result, now INVALIDATED

> **INVALIDATED for comparison.** A review after V3's single development run found four
> defects — one of them leakage: the promoted prior was estimated from full-archive future
> seasons. The inner holdout scored all six gameweeks from one frozen state rather than a true
> walk-forward, and the six-match cold-start prior / returning-promoted count handling, are
> specification/fitting defects; the runner's dirty-worktree acceptance is a provenance defect.
> V3's number (1.4956) and every slice, CRPS, cold-start, and parameter-selection figure are
> therefore **void for comparison or promotion** and are kept only as an audit record. Nothing
> about the Stage A model or any gate changed. Full detail in
> [`docs/phase1-candidate-v3-invalidation.md`](docs/phase1-candidate-v3-invalidation.md). The
> leakage-safe successor `dynamic_team_goals_v4` is pre-registered separately (contract
> amendment 1.5). It had not yet been evaluated when V3 was invalidated; its later
> development-only result is recorded in
> [`docs/phase1-candidate-v4-development.md`](docs/phase1-candidate-v4-development.md). The
> narrative below is the original V3 record.

`dynamic_team_goals_v3` is a **development-only structural probe**, not a promotion candidate.
It tests whether team strength is a slowly time-varying latent quantity best estimated
**sequentially** — a mean-reverting online Poisson filter in log space that carries each
club's strength forward as a state one match can move, with explicit summer shrinkage —
rather than V2's batch re-fit on an expanding window. Amendment 1.4 pre-registers it and its
grid; no baseline, gate, tolerance, eligible row, or the V2 policy changes, and it is never
substituted for V2 by the default harness command (a separate `fpl.validate.dev_candidate_v3`
runner reuses the harness but prints a DEVELOPMENT ONLY report).

Its single historical development evaluation scored **1.4956** against the unchanged
`trailing_goals_attack_defence` baseline (1.5003), a **+0.3128%** lift — better than the
baseline but short of the 1% promotion gate, and a touch behind V2 (1.4939). It improves CRPS
(0.6373 vs 0.6393), passes calibration (PIT-80 error 0.002), and regresses only in 2021-22
and 2025-26. The boundary selections (slowest learning rate in 153/181 folds, strongest
summer shrinkage in 92/181) are recorded as diagnostics for a future hypothesis, not as
permission to widen the grid. Full result and caveats in
[`docs/phase1-candidate-v3-development.md`](docs/phase1-candidate-v3-development.md). The
trailing-goals baseline remains the Stage A model.

### Candidate V4: leakage-safe successor, development-only result, not promoted

`dynamic_team_goals_v4` is pre-registered (contract amendment 1.5) as the leakage-safe structural
successor to the invalidated V3. It keeps V3's sequential dynamic filter and fixes all four V3
defects: the inner holdout is a true per-observed-gameweek walk-forward, the six-match cold-start
prior is used in the fitting residual as well as prediction, returning promoted clubs reset their
eligible count, and the promoted prior is estimated fold-locally from earlier promoted cohorts
(no full-archive constant, neutral `1.0/1.0` fallback). The three leakage-safety fixes are pinned
on as frozen config fields.

Its single historical development evaluation scored **1.4945** against the unchanged
`trailing_goals_attack_defence` baseline (1.5003), a **+0.3888%** lift — real but modest, short of
the 1% promotion gate, and fractionally behind V2 (1.4939) on both proper scores. It improves CRPS
(0.6363 vs 0.6393), has exactly nominal PIT-80 calibration (0.800, tied with V1 and better than
V2), regresses only in 2021-22 and 2025-26, and runs leakage-safe (140 cold starts, 0 leakage
failures, all three procedure pins fired in 181/181 folds). **This is a development-only number,
not a promotion verdict**; the structural hypothesis is competitive with — not better than —
the corrected batch candidate V2, and the trailing-goals baseline remains Stage A. Full result
and caveats in
[`docs/phase1-candidate-v4-development.md`](docs/phase1-candidate-v4-development.md). Design and
the frozen grid in [`docs/phase1-candidate-v4-design.md`](docs/phase1-candidate-v4-design.md).
