# Phase 0 — Design for review

> Historical design record. Phase 0b subsequently added atomic manifests, event-live and
> finalized element-summary capture, checksum-verified file loading, versioned current-season
> facts/schedules, and `known_at <= as_of` enforcement. For current operational behavior, use
> `README.md`, `AGENTS.md`, and the executable tests; unresolved scoring verification remains.

Status: **awaiting approval, no implementation code written yet.**

Every number below was re-measured against the real archive (5 seasons pulled from
`vaastav/Fantasy-Premier-League`) before writing this document. Section 1 records where my
measurements agree with the spec, where they diverge, and three findings the spec does not cover.

---

## 1. Audit results

### 1.1 Confirmed exactly

| Spec claim | Measured | Status |
|---|---|---|
| ~139,000 rows in `fact_player_fixture` | 139,039 raw → **139,029** after dedup | ✅ |
| exactly 3,800 rows in `fact_team_match` | **3,800** (760 × 5 seasons) | ✅ |
| 2,217 duplicated player-GW cells in 2021-22 | **2,217** | ✅ |
| 409 duplicated player-GW cells in 2025-26 | **409** (419 raw − 10 exact dupes) | ✅ |
| 10 exactly-duplicated rows in 2025-26 | **10**, all fully identical | ✅ |
| Salah `element` 233/283/308/328/381, `code` 118748 | exact match | ✅ |
| `element`→`code` match rate 100% | **100.000%** all five seasons | ✅ |
| team id 3 = Brentford → Bournemouth → Burnley | exact match | ✅ |
| 1,797 players; 187 span 5 seasons; 238 new in 2025-26 | **1797 / 187 / 238** | ✅ |
| GK `defensive_contribution` always 0 | max = **0** | ✅ |
| DC hit rates: DEF 20.8% @10, MID 11.0% @12, FWD 0.6% @12 | **20.8 / 11.0 / 0.6** | ✅ |
| home 1.092, away 0.908, league mean 1.463 goals | **1.092 / 0.908 / 1.463** | ✅ |
| `team_xgc` = max(player xGC) ≈ 1.40 vs actual 1.38 | **1.395 vs 1.375** (2025-26) | ✅ |
| `corr(team xG, goals)` ≈ 0.504 | **0.502** (2025-26) | ✅ |
| Schema drift: `expected_*`+`starts` from 2022-23; DC family 2025-26 only; `mng_*` 2024-25 only | exact match | ✅ |
| GK goal value untested — no GK scored | GK goals 2025-26 = **0** | ✅ flag in code |

### 1.2 Divergences — resolved, and they change what the tests assert

**a) Minutes distribution is a 2025-26 figure, not a pooled one.**
61.4% zero / 26.3% 60+ is *exactly* 2025-26. Pooled across five seasons it is 59.5% / 28.3%,
and it ranges 57.2–61.7% by season. → the test asserts against **2025-26**, with the pooled
value recorded as a looser range check.

| season | zero-min | 60+ |
|---|---|---|
| 2021-22 | 58.8% | 31.3% |
| 2022-23 | 57.2% | 29.6% |
| 2023-24 | 61.7% | 26.4% |
| 2024-25 | 58.1% | 28.3% |
| **2025-26** | **61.4%** | **26.3%** |

**b) The 2.8% position-change figure only holds for `players_raw.element_type`.**
Using `merged_gw.position` gives 7.3% (131/1797); using `players_raw.element_type` gives
**2.8% (51/1797)** — the spec's number. Cause: the `merged_gw.position` label vocabulary drifts:

- 2021-22 contains **both `GK` and `GKP`**
- 2024-25 contains an **`AM`** label
- 2022-23 / 2023-24 / 2025-26 use `GK`/`DEF`/`MID`/`FWD`

→ **`element_type` is the canonical position**, normalised `1→GK, 2→DEF, 3→MID, 4→FWD`;
`GKP→GK` and `AM→MID` when reading the archive label. Within 2025-26 the two sources agree on
**0 of 29,747 rows** disagreeing, so the scoring replay is unaffected by the choice.

**c) `xP` contamination is directionally confirmed, magnitude differs.**
I measure `corr(xP rolling-3, same-GW total_points) = 0.313` (spec: ~0.40) and
`corr(xP, same-GW points) = 0.346`. Same conclusion — far too high for a pre-match feature —
but since I can't reproduce the exact statistic, the test is **structural**: `xP` must not exist
as a column in any `stg_` or `mart_` table. That is what the DoD actually asks for.

**d) Appearance-point share, 2025-26:** GK 59.4 / DEF 57.9 / MID 55.3 / FWD 52.2 (spec: 59.5 /
59.1 / 55.6 / 51.5). DEF is 1.2pp off. All inside the spec's "51–60%" claim, so the test asserts
the **51–60% band per position** rather than exact values.

### 1.3 New findings the spec does not cover

**FINDING 1 — the scoring calculator can reach 100.000%, not 99.997%.**
I replay **29,747 / 29,747 = 100.000%** of 2025-26, including the row the spec calls an
unreproducible glitch:

```
Ashley Barnes, FWD, GW22, minutes=0, yellow_cards=1, bps=-3, total_points=-1
```

This is reproducible if **card penalties are not gated behind `minutes > 0`**. FPL scores a
booking for an unused substitute; gating cards on appearance yields 0 and loses the row — which
is what a 29,746 result indicates. → the calculator applies cards ungated, and
`tests/test_scoring.py` asserts **exact equality on all 29,747 rows** (stricter than the DoD).
The Barnes row gets a named regression test so the behaviour can't be refactored away.

**FINDING 2 — 2022-23 `expected_*` are present-but-zero for GW1–15. This is very likely your
Stage A xG inversion.**
The columns exist from 2022-23, but for GW1–15 every value is literal `0.0`:

```
2022-23 GW1 : xG sum = 0.0   goals = 24
...
2022-23 GW15: xG sum = 0.0   goals = 35     (14 GWs, 0.0 xG, 344 goals)
2022-23 GW16: xG sum = 27.66 goals = 29     <- real data starts
```

Season-level effect: `team_xg` mean **0.963** vs actual goals **1.426**, and
`corr(team_xg, goals)` only **0.332** versus 0.587 / 0.593 / 0.502 for the three later seasons.
This is gotcha 5 (zero vs null) occurring *inside* a season, so a "column present?" check misses
it. Training an xG-based Stage A on 2022-23 ingests 14 gameweeks of fake zeros — the plausible
mechanism behind the xG model scoring 0.181 against goals' 0.260. → nullified at the `stg_` layer
via a declared override in `config/data_quality.yaml`, with a test asserting NULL for GW≤15 and
NOT NULL for GW≥16. Not silently patched in code.

**FINDING 3 — `sum()` over an all-NULL group returns 0.0, silently re-introducing gotcha 5.**
Building `team_xg` for 2021-22 (no xG columns at all) yields `0.0`, not NULL, which dragged my
first pooled `team_xg` mean to 1.08. Every aggregate in `facts.py` is null-guarded
(`NULL` unless at least one non-null input) and a test asserts 2021-22 `team_xg IS NULL`.

---

## 2. Blocker: the FPL live API is not reachable from this environment

```
$ curl https://fantasy.premierleague.com/api/bootstrap-static/
curl: (56) CONNECT tunnel failed, response 403
proxy status: {"kind":"connect_rejected",
  "detail":"gateway answered 403 to CONNECT (policy denial or upstream failure)",
  "host":"fantasy.premierleague.com:443"}
```

`raw.githubusercontent.com` works, so the **entire archive path is unaffected** — storage,
crosswalks, fact tables, the scoring calculator and every test in the DoD can be built and
verified here. What cannot be done in this environment:

1. no live integration test of the API client;
2. `daily_snapshot` cannot capture a real payload here;
3. **`config/scoring_2026_27.yaml` cannot be verified against the live `game_config.scoring`** —
   it will be hand-written from the spec's section 5 table and marked `verified: false`.

Proposed handling (decision needed — see section 8): build the client fully against the
documented response shapes with pydantic models, unit-test it against checked-in sample payloads
plus a local stub server, and have `daily_snapshot` exit non-zero with an explicit
"egress blocked" diagnostic rather than writing an empty snapshot. Then the job is correct the
moment it runs somewhere with egress.

---

## 3. Module structure

Repo root is `the_comet_fpl/` — the spec's `fpl-model/` wrapper directory is dropped, since
nesting a second project root inside the repo buys nothing. The spec puts `jobs/` at top level
but the DoD requires `python -m fpl.jobs.daily_snapshot`; the importable path wins, so `jobs/`
lives inside the package.

```
the_comet_fpl/
  pyproject.toml                  uv, py3.12, ruff, mypy strict on src/
  README.md                       clone -> populated DB path
  config/
    sources.yaml                  archive URLs, seasons, rate limit
    scoring_2025_26.yaml          replay target; verified: true
    scoring_2026_27.yaml          live rules; verified: false until API reachable
    data_quality.yaml             declared nullify overrides (FINDING 2)
    model.yaml                    stub, Phase 1+
  src/fpl/
    types.py          Position, PlayerMatchStats, Season, AsOf
    config.py         pydantic loaders for the YAML above
    ingest/
      archive.py      download + land 4 files x 5 seasons -> raw_
      fpl_api.py      httpx client, 1 req/s, retry, pydantic response models
    storage/
      db.py           connection, migrations, layer helpers
      schema.sql      all DDL (section 4)
    transform/
      crosswalk.py    element->code, team name/id->season team_id, position normalise
      facts.py        stg_ -> mart_ fact builders
      quality.py      range validation, anomaly log, data_quality.yaml application
    features/
      pit.py          PointInTimeView + AsOf  (API only in Phase 0, no features)
    models/
      scoring.py      calculate_points(stats, rules, position) -> int
    jobs/
      build_db.py     full rebuild: archive -> raw -> stg -> mart
      daily_snapshot.py
  tests/
    test_scoring.py         full-season replay + unit cases + Barnes regression
    test_crosswalk.py       gotchas 1, 2, 10
    test_grain.py           gotchas 3, 4, and row-count invariants
    test_point_in_time.py   R4: static guard + truncation equivalence
    test_schema_drift.py    gotchas 5, 6, 7, 11 + FINDINGS 2 & 3
    test_facts.py           team_match aggregation, team_xgc, home/away
    test_quality.py         gotcha 13 range validation
    test_config.py          rules-as-config round trip
    test_api_client.py      offline: rate limit, retry, pydantic validation
  docs/phase0-design.md
```

Not built in Phase 0: `ingest/calendar.py`, `models/{team_strength,minutes,events,simulate,optimise}.py`,
`validate/`, `dashboard/`, `features/{team,player}.py`.

**Dataframe choice: Polars**, used consistently. Decisive reason: this project turns on
null-vs-zero semantics, and Polars keeps integer columns nullable without the float coercion
Pandas applies. Findings 2 and 3 are both null-semantics bugs.

---

## 4. Storage schema

DuckDB, single file at `data/fpl.duckdb`. Layers `raw_` → `stg_` → `mart_`.

### 4.1 raw layer — as landed, immutable

Raw tables are **all-VARCHAR**. This is deliberate: `""` and `"0.0"` must stay distinguishable to
detect gotcha 5 and FINDING 2, and any cast at landing time is an irreversible interpretation.
Casting happens once, in `stg_`.

```sql
CREATE TABLE raw_merged_gw (
  _source_url   VARCHAR NOT NULL,
  _ingested_at  TIMESTAMPTZ NOT NULL,
  season        VARCHAR NOT NULL,
  -- union of all columns observed across 2021-22..2025-26, every one VARCHAR.
  -- absent-in-source resolves to NULL and is distinguished from empty via
  -- raw_source_columns below.
  name VARCHAR, position VARCHAR, team VARCHAR, xP VARCHAR, element VARCHAR,
  fixture VARCHAR, round VARCHAR, "GW" VARCHAR, kickoff_time VARCHAR,
  minutes VARCHAR, starts VARCHAR, goals_scored VARCHAR, assists VARCHAR,
  clean_sheets VARCHAR, goals_conceded VARCHAR, saves VARCHAR,
  penalties_saved VARCHAR, penalties_missed VARCHAR, own_goals VARCHAR,
  yellow_cards VARCHAR, red_cards VARCHAR, bonus VARCHAR, bps VARCHAR,
  total_points VARCHAR, opponent_team VARCHAR, was_home VARCHAR,
  team_h_score VARCHAR, team_a_score VARCHAR,
  expected_goals VARCHAR, expected_assists VARCHAR,
  expected_goal_involvements VARCHAR, expected_goals_conceded VARCHAR,
  defensive_contribution VARCHAR, tackles VARCHAR, recoveries VARCHAR,
  clearances_blocks_interceptions VARCHAR,
  influence VARCHAR, creativity VARCHAR, threat VARCHAR, ict_index VARCHAR,
  value VARCHAR, selected VARCHAR, transfers_in VARCHAR, transfers_out VARCHAR,
  transfers_balance VARCHAR, modified VARCHAR,
  mng_win VARCHAR, mng_draw VARCHAR, mng_loss VARCHAR, mng_goals_scored VARCHAR,
  mng_clean_sheets VARCHAR, mng_underdog_win VARCHAR, mng_underdog_draw VARCHAR
);

-- the actual header of every landed file: lets stg_ tell
-- "column absent from source" apart from "value empty". Backs gotcha 5.
CREATE TABLE raw_source_columns (
  season VARCHAR NOT NULL, source_table VARCHAR NOT NULL,
  column_name VARCHAR NOT NULL, ordinal INTEGER NOT NULL,
  PRIMARY KEY (season, source_table, column_name)
);

CREATE TABLE raw_fixtures    (_source_url VARCHAR, _ingested_at TIMESTAMPTZ, season VARCHAR, ...);
CREATE TABLE raw_teams       (_source_url VARCHAR, _ingested_at TIMESTAMPTZ, season VARCHAR, ...);
CREATE TABLE raw_players     (_source_url VARCHAR, _ingested_at TIMESTAMPTZ, season VARCHAR, ...);

-- R5. append-only, never updated, never deleted.
CREATE TABLE snapshot_bootstrap (
  captured_at TIMESTAMPTZ NOT NULL,
  gw          INTEGER,
  endpoint    VARCHAR NOT NULL,
  payload     JSON NOT NULL,
  sha256      VARCHAR NOT NULL,
  PRIMARY KEY (captured_at, endpoint)
);
```

### 4.2 stg layer — typed, deduped, crosswalked

```sql
CREATE TABLE stg_player_fixture (   -- dedup on (season, element, fixture); xP dropped here
  season VARCHAR, element INTEGER, code INTEGER, fixture INTEGER,
  gw INTEGER, kickoff_time TIMESTAMPTZ, position VARCHAR,
  team_id INTEGER, opponent_team_id INTEGER, was_home BOOLEAN,
  minutes INTEGER, starts INTEGER, ...      -- nullable ints, never zero-filled
  PRIMARY KEY (season, element, fixture)
);
CREATE TABLE stg_fixture (season VARCHAR, fixture INTEGER, pulse_id INTEGER, gw INTEGER,
  kickoff_time TIMESTAMPTZ, team_h INTEGER, team_a INTEGER,
  team_h_score INTEGER, team_a_score INTEGER,
  team_h_difficulty INTEGER, team_a_difficulty INTEGER,   -- FDR, Phase 1 baseline
  finished BOOLEAN, PRIMARY KEY (season, fixture));
CREATE TABLE stg_team   (season VARCHAR, team_id INTEGER, team_name VARCHAR,
  short_name VARCHAR, team_code INTEGER, pulse_id INTEGER, PRIMARY KEY (season, team_id));
CREATE TABLE stg_player (season VARCHAR, element INTEGER, code INTEGER, opta_code VARCHAR,
  web_name VARCHAR, element_type INTEGER, position VARCHAR, team_id INTEGER,
  PRIMARY KEY (season, element));
```

### 4.3 mart layer — modelling-ready

Named with the `mart_` prefix so the DoD's `SELECT * FROM mart_fact_team_match LIMIT 5` works.

```sql
CREATE TABLE mart_dim_player (          -- grain: code x season
  code INTEGER, season VARCHAR, element_id INTEGER, web_name VARCHAR,
  position VARCHAR NOT NULL,            -- from element_type; see 1.2(b)
  team_id INTEGER, opta_code VARCHAR,
  PRIMARY KEY (code, season)
);

CREATE TABLE mart_dim_team (            -- grain: season x team_id
  season VARCHAR, team_id INTEGER, team_name VARCHAR, short_name VARCHAR,
  pulse_id INTEGER,
  PRIMARY KEY (season, team_id)
);

CREATE TABLE mart_fact_player_fixture ( -- grain: code x fixture. ~139,029 rows
  season VARCHAR NOT NULL, gw INTEGER NOT NULL, fixture INTEGER NOT NULL,
  pulse_id INTEGER, kickoff_time TIMESTAMPTZ NOT NULL,
  code INTEGER NOT NULL, position VARCHAR NOT NULL,
  team_id INTEGER NOT NULL, opponent_team_id INTEGER NOT NULL, was_home BOOLEAN NOT NULL,
  minutes INTEGER, starts INTEGER, goals_scored INTEGER, assists INTEGER,
  clean_sheets INTEGER, goals_conceded INTEGER, saves INTEGER,
  penalties_saved INTEGER, penalties_missed INTEGER, own_goals INTEGER,
  yellow_cards INTEGER, red_cards INTEGER, bonus INTEGER, bps INTEGER,
  expected_goals DOUBLE, expected_assists DOUBLE, expected_goals_conceded DOUBLE,
  defensive_contribution INTEGER, tackles INTEGER, recoveries INTEGER,
  clearances_blocks_interceptions INTEGER,
  value INTEGER, selected INTEGER, transfers_in INTEGER, transfers_out INTEGER,
  total_points INTEGER,       -- replay target only; never a model target (R1)
  PRIMARY KEY (season, code, fixture)
);

CREATE TABLE mart_fact_team_match (     -- grain: team x fixture. exactly 3,800 rows
  season VARCHAR NOT NULL, gw INTEGER NOT NULL, fixture INTEGER NOT NULL,
  pulse_id INTEGER, kickoff_time TIMESTAMPTZ NOT NULL,
  team_id INTEGER NOT NULL, opponent_team_id INTEGER NOT NULL, was_home BOOLEAN NOT NULL,
  goals_for INTEGER, goals_against INTEGER,
  team_xg DOUBLE,        -- null-guarded SUM(player xG); NULL when unmeasured (FINDING 3)
  team_xgc DOUBLE,       -- null-guarded MAX(player xGC); validated 1.395 vs 1.375
  team_bps INTEGER, rest_days INTEGER,
  fdr INTEGER,           -- PROPOSED ADDITION: this team's difficulty, Phase 1 baseline
  PRIMARY KEY (season, team_id, fixture)
);
```

Three deliberate deviations from the spec's column lists, all flagged for approval in section 8:
`fdr` added to `fact_team_match`; `total_points` retained in `fact_player_fixture` (replay target
only, never a model target); `pulse_id` added to `dim_team` (it is in `teams.csv` and is the
Phase 5 join key, so it costs nothing to keep now).

`influence/creativity/threat/ict_index` and `expected_goal_involvements` stay in `raw_` only —
the latter is `xG + xA` and derivable, the ICT family is not in the spec's feature list. Promoting
them later is one migration.

---

## 5. Feature-layer API (R4)

No features are built in Phase 0. The **access layer** is, because `test_point_in_time.py` has to
enforce R4 structurally in Phase 0 and the API is what the spec most wants reviewed.

The core idea: features cannot reach a fact table except through `PointInTimeView`, and that class
never accepts caller SQL.

```python
# src/fpl/features/pit.py


class LeakageError(RuntimeError):
    """Raised when an access pattern could read post-as_of information."""


@dataclass(frozen=True, slots=True)
class AsOf:
    ts: datetime

    def __post_init__(self) -> None:
        if self.ts.tzinfo is None or self.ts.utcoffset() is None:
            raise LeakageError("as_of must be timezone-aware UTC")


# Every column that is only knowable after kickoff.
OUTCOME_COLUMNS: frozenset[str] = frozenset(
    {
        "minutes",
        "starts",
        "goals_scored",
        "assists",
        "clean_sheets",
        "goals_conceded",
        "saves",
        "penalties_saved",
        "penalties_missed",
        "own_goals",
        "yellow_cards",
        "red_cards",
        "bonus",
        "bps",
        "total_points",
        "expected_goals",
        "expected_assists",
        "expected_goals_conceded",
        "defensive_contribution",
        "tackles",
        "recoveries",
        "clearances_blocks_interceptions",
        "goals_for",
        "goals_against",
        "team_xg",
        "team_xgc",
        "team_bps",
    }
)

# Knowable before kickoff — schedule metadata only.
SCHEDULE_COLUMNS: tuple[str, ...] = (
    "season",
    "gw",
    "fixture",
    "pulse_id",
    "kickoff_time",
    "team_id",
    "opponent_team_id",
    "was_home",
    "fdr",
)


class PointInTimeView:
    """The only sanctioned reader of mart_ facts inside features/.

    Two accessors, two different guarantees:

      observed_*(...)  outcome data, hard-filtered to kickoff_time < as_of.
                       The filter is appended by this class; callers cannot
                       pass SQL or a predicate that could remove it.

      schedule(...)    fixture metadata, may include future rows, but the
                       projection is restricted to SCHEDULE_COLUMNS, so a
                       future outcome is not merely filtered out — it is
                       not in the returned frame at all.
    """

    def __init__(self, con: DuckDBPyConnection, as_of: AsOf) -> None: ...

    def observed_player_fixtures(
        self,
        *,
        codes: Sequence[int] | None = None,
        seasons: Sequence[str] | None = None,
        columns: Sequence[str] | None = None,
    ) -> pl.DataFrame: ...

    def observed_team_matches(
        self,
        *,
        team_ids: Sequence[int] | None = None,
        seasons: Sequence[str] | None = None,
        columns: Sequence[str] | None = None,
    ) -> pl.DataFrame: ...

    def schedule(
        self,
        *,
        team_ids: Sequence[int] | None = None,
        until: datetime | None = None,
    ) -> pl.DataFrame: ...  # rejects any OUTCOME_COLUMNS request
```

A feature is then a pure function of the view, which is what makes the leak test possible:

```python
# Phase 1+ shape, shown here only to pin the signature down now.
FeatureFn = Callable[[PointInTimeView, int], float | None]  # (view, entity_id) -> value
```

Making leakage awkward, in four layers:

1. **`AsOf` rejects naive datetimes**, so "which timezone" can never silently shift the boundary.
   Archive `kickoff_time` is tz-aware ISO-8601; the GW1 deadline is `2026-08-21T17:30:00Z`.
2. **No caller SQL.** `columns` is validated against an allowlist per table; `schedule()` raises
   `LeakageError` on any outcome column. The `kickoff_time < as_of` predicate is concatenated by
   the view itself, after the caller's filters.
3. **Static guard test.** `test_point_in_time.py` AST-scans `src/fpl/features/` and fails if any
   module other than `pit.py` imports `duckdb`, calls `.execute(`/`.sql(`, references a `mart_`
   or `stg_` table name, or reads a file. A new feature *cannot* be written with a bypass and
   still pass CI.
4. **Truncation-equivalence test — the real leak test.** For a sweep of `as_of` values, build
   against the full database and against a database physically truncated to `as_of`, and assert
   the results are identical:

   ```python
   for as_of in sweep:
       full = PointInTimeView(full_db, AsOf(as_of))
       trunc = PointInTimeView(truncated_to(as_of), AsOf(as_of))
       assert_frame_equal(accessor(full), accessor(trunc))
   ```

   Any accessor that forgot its filter returns extra rows from the full DB and fails. This is the
   testable form of the spec's "shifting `as_of` earlier never changes an already-computed value":
   a value computed at `T` is invariant to the existence of data after `T`. A monotonicity check
   rides along — for `T1 < T2` the row set at `T1` must be a subset of that at `T2`.

---

## 6. Scoring calculator

```python
def calculate_points(stats: PlayerMatchStats, rules: ScoringRules, position: Position) -> int
```

- `ScoringRules` is a frozen pydantic model loaded from `config/scoring_<season>.yaml`. No scoring
  constant appears in Python (R2). Adding 2027/28 is a new YAML file.
- `PlayerMatchStats` is frozen, fully typed, with `int | None` for anything that may be unmeasured.
  **`None` is never coerced to 0.**
- Bonus is **passed through** from the recorded value in Phase 0, per the DoD. BPS→bonus ranking
  arrives in Stage D.
- Validated rules, each with the replay as evidence:
  - appearance 1 at `0 < minutes < 60`, 2 at `minutes >= 60`
  - clean sheet requires `minutes >= 60` **and** recorded `clean_sheets == 1`
  - `goals_conceded // 2` penalty, GK and DEF only
  - `saves // 3`, GK only
  - **cards are not gated on minutes** (FINDING 1 — Ashley Barnes)
  - DC: rules-gated *and* stat-gated. Points only when the season's rules define a DC threshold
    **and** the stat is non-null. A pre-2025-26 row has `defensive_contribution = NULL` and scores
    nothing, without a null being read as a zero.
  - GK goal = 10 carries an explicit comment: **untested, no GK scored in 2025-26.**

---

## 7. Test matrix — every testable item in section 4 of the spec

| # | Gotcha | Test | Asserted value |
|---|---|---|---|
| 1 | `element` reassigned; `code` stable | `test_crosswalk.py` | Salah 233/283/308/328/381 → 118748; match rate **100.000%** |
| 2 | team ids reassigned | `test_crosswalk.py` | id 3 → Brentford/Bournemouth/Burnley; name↔id round trip 100% |
| 3 | grain is (code, fixture) | `test_grain.py` | PK uniqueness; dup player-GW = **2217** (2021-22), **409** (2025-26) |
| 4 | 10 duplicate rows in 2025-26 | `test_grain.py` | 29,757 → **29,747**; the 10 are fully identical |
| 5 | schema drift, NULL not zero | `test_schema_drift.py` | `expected_*` NULL for all 2021-22; DC NULL pre-2025-26; `starts` NULL 2021-22 |
| 6 | DC is a count | `test_schema_drift.py` | observed range **0–29** |
| 7 | GK DC always 0 | `test_schema_drift.py` | `MAX(dc) WHERE position='GK'` = **0** |
| 8 | minutes distribution | `test_facts.py` | 2025-26 zero **61.4%**, 60+ **26.3%** (±0.1pp) |
| 9 | thin history | `test_crosswalk.py` | **1797** players; **187** span 5; **238** new in 2025-26 |
| 10 | position changes | `test_crosswalk.py` | **51/1797 = 2.8%** via `element_type` |
| 11 | drop `xP` | `test_schema_drift.py` | `xP` absent from every `stg_`/`mart_` table |
| 12 | keep `pulse_id` | `test_facts.py` | non-null on all 3,800 team-match rows |
| 13 | pre-season glitches | `test_quality.py` | range validators fire; anomalies logged not swallowed |
| 14 | fixtures/bootstrap season skew | `test_api_client.py` | client refuses to join fixture↔bootstrap team ids without a season match |
| — | FINDING 1 | `test_scoring.py` | **29,747/29,747** exact; named Barnes regression |
| — | FINDING 2 | `test_schema_drift.py` | 2022-23 `expected_*` NULL for GW≤15, NOT NULL for GW≥16 |
| — | FINDING 3 | `test_facts.py` | 2021-22 `team_xg IS NULL`, not 0.0 |
| — | row counts | `test_facts.py` | `fact_player_fixture` **139,029**; `fact_team_match` **3,800** |
| — | team aggregation | `test_facts.py` | `team_xgc` mean **1.395** vs conceded **1.375** (2025-26) |
| — | home advantage | `test_facts.py` | home **1.092**, away **0.908**, mean **1.463** |
| — | R4 | `test_point_in_time.py` | static guard + truncation equivalence |
| — | R2 | `test_config.py` | rules load from YAML; no scoring constants in `src/` |

---

## 8. Decisions I need before implementing

1. **FPL API egress is blocked (section 2).** Preferred: build + offline-test the client and
   snapshot job, ship `scoring_2026_27.yaml` as `verified: false`, and have `daily_snapshot` fail
   loudly here. Alternative: you allowlist `fantasy.premierleague.com`, or paste one
   `bootstrap-static` payload for me to vendor as a test fixture and verify the 2026/27 rules
   against.
2. **`fdr` on `mart_fact_team_match`** — added for the Phase 1 naive-FDR baseline. Confirm.
3. **`total_points` retained on `mart_fact_player_fixture`** — needed as the replay target. It is a
   documented R1 hazard; my alternative is to keep it in `stg_` only and have the replay test read
   from there. Say which you prefer.
4. **Scoring test strictness** — I intend to assert **100.000%** (29,747/29,747), not the DoD's
   99.997%. Stricter than asked, and it will fail loudly if anyone re-gates cards on minutes.
5. **`scoring_2025_26.yaml`** ships alongside the 2026/27 file so the replay runs against its own
   season's rules rather than next season's. My replay shows the two are identical across every
   component involved, but hard-coding that equivalence would violate R2.

---

# 9. Findings from implementation

Recorded after the plan was approved and built. Section 1 covers what the audit found before
any code was written; these emerged from making it work.

## 9.1 `AM` is the Assistant Manager element, not a position

The initial plan proposed normalising the archive's drifted position labels as
`GKP -> GK` and `AM -> MID`. **The `AM` half was wrong.** `AM` is `element_type` 5, the
Assistant Manager element:

- 322 rows in 2024-25, across **20 managers** (Guardiola, Frank, Hürzeler, …)
- all with 0 minutes, scored entirely through the `mng_*` columns
- `element_type` 5 appears in the 2024-25 `players_raw` and **no other season**, confirming
  the specification's note that the manager element was removed in 2025-26

They are now excluded rather than coerced. Mapping them to MID would have fed 322
zero-minute non-players into every minutes and rate model.

**Row-count consequences** — the exclusion moves two of the numbers in section 1:

| Quantity | With managers | Excluding managers (as built) |
|---|---|---|
| `mart_fact_player_fixture` rows | 139,029 | **138,707** |
| distinct players | 1,797 | **1,777** |
| players spanning five seasons | 187 | **187** (unchanged) |
| new in 2025-26 | 238 | **238** (unchanged) |
| position changes | 51 (2.8% of 1,797) | 51 (**2.9%** of 1,777) |

The specification's 139,029 and 1,797 both counted managers. The 51 position-changers and
the span counts are unaffected.

## 9.2 Cards for unused substitutes are systematic, not a glitch

Section 1.3's Finding 1 identified one row — Ashley Barnes, 2025-26 GW22 — as reproducible.
Building the full-history replay showed it is one of **ten**:

| Season | GW | Player | Card | Points | BPS |
|---|---|---|---|---|---|
| 2021-22 | 30 | Kenneh | yellow | −1 | −3 |
| 2022-23 | 16 | Lascelles | yellow | −1 | −3 |
| 2022-23 | 19 | Lascelles | yellow | −1 | −3 |
| **2022-23** | **28** | **Matheus** | **red** | **−3** | **−9** |
| 2023-24 | 3 | Rodák | yellow | −1 | −3 |
| 2023-24 | 18 | Bettinelli | yellow | −1 | −3 |
| 2023-24 | 27 | Felipe | yellow | −1 | −3 |
| 2023-24 | 31 | Turner | yellow | −1 | −3 |
| 2024-25 | 8 | Sarabia | yellow | −1 | −3 |
| 2025-26 | 22 | Barnes | yellow | −1 | −3 |

All ten reproduce exactly. The red card matters independently: it confirms `red_cards` is
also ungated on minutes, which no yellow-only example could establish.

So the Barnes row is not a data glitch at all — it is one instance of documented FPL
behaviour that a minutes-gated calculator gets wrong ten times over.

## 9.3 The replay is exact across all five seasons, not just 2025-26

**138,707 / 138,707 = 100.000%.** Recorded `total_points` for every season equals points
recomputed under the 2025-26 ruleset.

This works *because* `defensive_contribution` is NULL rather than zero before 2025-26: the
ruleset then awards no DC, which is exactly what those seasons' rules did. It is a strong
end-to-end check on the null-vs-zero handling. Had the column been zero-filled the seasons
would still replay, but a genuinely-zero DC would have become indistinguishable from an
unmeasured one — and every defender's DC-per-90 would be biased low.

## 9.4 Gameweek numbering is not contiguous

**2022-23 has no gameweek 7.** It was cancelled following the death of Queen Elizabeth II in
September 2022 and its ten fixtures were redistributed, leaving GW8 with seven matches. That
season has 37 distinct gameweeks; all 380 fixtures are present.

Consequence for Phase 1: a walk-forward backtest must iterate the *observed* gameweeks, not
`range(1, 39)`. Assuming contiguity would train on an empty gameweek and could mis-align the
train/predict split by one.

## 9.5 Rest-day tail differs from the specification

Under the definition "calendar days between a team's consecutive kickoffs":

| Measure | Specification | As built |
|---|---|---|
| median | 7 | **7** ✅ |
| share ≤ 4 days (2025-26) | 14.3% | **18.5%** |
| H1 vs H2 share ≤ 4 days | 12.2% / 16.3% | **15.3% / 21.6%** |

The median and the H1 < H2 direction agree; my tail is uniformly ~3–5pp heavier, so this
looks like a definitional difference rather than a construction error. The minimum gap is
**2 days** (six team-matches on 2021-12-28, the COVID-disrupted festive period); every other
season floors at 3.

The tests therefore assert the median, the 2-day floor and the H1 < H2 direction, and
**do not** assert a fixed ≤4-day share. Congestion gets measured properly in Phase 2; if you
want a specific definition pinned now, say which.

## 9.6 Two smaller items

- **Polars `sum()` over an all-NULL group returns 0.0** (section 1.3, Finding 3) was
  confirmed in practice: it dragged an early pooled `team_xg` mean to 1.08 against a true
  1.41. All team aggregates are consequently built in SQL, where `SUM`/`MAX` return NULL.
- **BPS range bounds were widened once**, from ±(20,120) to (−35,145). The observed range is
  [−25, 128] and both ends are real football: −25 is a defender with an own goal and a red
  card, 128 a hat-trick plus assists. The range check surfaced them for review, which is what
  it is for; the bounds now sit just outside the observed extremes.

## 9.7 2026/27 scoring verification resolution

Resolved on 2026-07-27. A real official bootstrap scoring extract confirms 17 fields. The seven
thresholds and units omitted by that payload are confirmed separately by captured official
published scoring sources, with source URLs, capture times, and SHA-256 values recorded in
`config/scoring_2026_27.yaml`. Payload, documentation, and replay evidence remain separate.

Two branches stay under `verification.unverified`: `goals_scored.GK`, because no goalkeeper goal
exists in the replay data, and `clean_sheets.points.FWD`, because a zero-valued branch cannot be
distinguished from omission by replay. The ruleset is therefore not described as fully validated.
