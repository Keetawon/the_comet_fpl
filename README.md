# FPL points-prediction system

Produces, for every FPL player and gameweek, a **full distribution of fantasy points** —
not a point estimate — because the three questions a manager actually asks have three
different answers:

| Question | Statistic |
|---|---|
| Who do I transfer in? | `E[points]` over the next N gameweeks |
| Who do I captain? | `P(points >= 10)` — the right tail |
| Is this differential worth it? | `Var(points)` and effective ownership |

A single `xP` answers only the first.

**Current status: Phase 0b (historical and live data foundation) complete.** No models yet.
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
It is idempotent — rerunning produces the same database. Add `--refresh` to re-download.

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
config/       sources, scoring, data quality, and Phase 1 evaluation contracts
src/fpl/
  ingest/     archive.py, fpl_api.py, live_snapshot.py, snapshot_files.py
  storage/    db.py, schema.sql
  transform/  crosswalk.py, facts.py, quality.py
  features/   pit.py   -- point-in-time access layer (R4)
  models/     scoring.py
  validate/   metrics.py, folds.py, baselines.py, harness.py -- Stage A evaluation
  jobs/       build_db.py, daily_snapshot.py, load_snapshots.py, verify_rules.py
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
| 1 | Stage A team model + validation harness | harness run; **candidate fitted, gate not cleared** |
| 2 | Stage B minutes model | not started |
| 3 | Stages C/D player events + simulation | not started |
| 3b | Stage E squad optimiser + `publish` static export | not started |
| 4 | Dashboard v1 | not started |
| 5 | External competition calendar — only if Phase 2 shows lift | not started |

Phase 3b is an addition to the original phasing, which ended Phase 3 at simulation and had no
phase delivering Stage E. A GW1 squad is a Stage E output — 15 players, £100.0m, 2/5/5/3, max
3 per club — so it needs a slot ahead of the dashboard.

`publish` writes static JSON rather than being queried live: the dashboard updates once per
gameweek, which is a static-site shaped workload. `docs/publish-contract.md` fixes that
boundary so Streamlit v1 is a thin renderer over the same artefact a React frontend would
consume, and swapping frontends later costs nothing. Nothing downstream of `publish` queries
DuckDB.

`docs/phase0-design.md` records the audit behind the schema decisions, including where
measured values diverged from the original specification and why.

`docs/phase1-evaluation-contract.md` fixes the Stage A entity/grain, point-in-time cutoff,
observed-gameweek walk-forward, required baselines, proper distribution metrics, calibration
outputs, reporting slices, and promotion gates before the first candidate is fitted.

---

## The Stage A bar

```bash
python -m fpl.validate.harness            # every baseline, every fold
python -m fpl.validate.harness --season 2025-26
```

181 walk-forward folds, 3,640 team-fixture predictions, one fold per *observed* gameweek.
Nothing is fitted yet; these are the honest comparators a model has to beat.

| baseline | mean log score | mean CRPS | PIT 80% | raw 80% | MAE |
|---|---|---|---|---|---|
| `trailing_goals_attack_defence` | **1.5003** | 0.6393 | 0.798 | 0.930 | 0.943 |
| `trailing_xg_attack_defence` | 1.5107 | 0.6460 | 0.803 | 0.944 | 0.966 |
| `naive_fdr` | 1.5262 | 0.6580 | 0.799 | 0.929 | 0.976 |
| `promoted_team_pooled_prior` | 1.5481 | 0.6739 | 0.794 | 0.929 | 1.012 |
| `league_home_away_goals` | 1.5522 | 0.6764 | 0.794 | 0.929 | 1.016 |

A candidate must reach **1.4853** to clear the contract's 1% relative-lift gate, without
regressing CRPS, in every reported season.

### The Stage A candidate: a documented non-promotion

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
