# Phase 0b knowledge-time feature audit

**Status:** read-only investigation + design note. Changes no model, config, contract, or
frozen policy. It answers one question: at a real 2026/27 deadline, can the models source their
trailing features by *knowledge time* (`known_at <= as_of`) from the versioned daily snapshot,
instead of by *event time* (`kickoff_time < as_of`) from the post-hoc archive?

**One-line answer:** the capture and the leak-safe read API both already exist and cover every
feature the models use, but **no model, harness, or prospective job is wired to source trailing
features from the versioned snapshot** — they all read the archive (`mart_fact_player_fixture`)
filtered only by `kickoff_time`. Because the archive contains no current-season rows during a
live season, this is a genuine blocker for real-deadline validity, not a cosmetic one.

Nothing below asserts that the ruleset or any model is validated. Candidate V1/V2/V3 remain
development-only and unpromoted.

---

## 0. What was read (evidence base)

- `AGENTS.md` / `README.md` — correctness rules (event vs knowledge time; preserve daily live
  data; season-scoped `team_id`/`element_id`; `code` as cross-season key).
- `src/fpl/ingest/live_snapshot.py` — capture contract, `write_capture`, `load_capture`.
- `src/fpl/ingest/snapshot_files.py` — committed-package verification and load.
- `src/fpl/ingest/fpl_api.py` — `ElementHistory` field set (the per-fixture payload schema).
- `src/fpl/jobs/daily_snapshot.py` — daily capture entry point.
- `src/fpl/jobs/prospective_minutes_v1.py` — the one live/prospective model path.
- `src/fpl/jobs/load_snapshots.py` — loader CLI.
- `src/fpl/features/pit.py` — `AsOf` / `FeatureSource` / `PointInTimeView` read API.
- `src/fpl/validate/attacking_harness.py`, `src/fpl/validate/minutes_harness.py` — backtest
  feature sourcing.
- `src/fpl/storage/schema.sql`, `src/fpl/storage/db.py` — snapshot/live/mart tables,
  `FEATURE_READABLE_TABLES`.
- `config/sources.yaml`; `.github/workflows/snapshot.yml`, `.github/workflows/player-history.yml`.
- `data/fpl.duckdb` (opened read-only) and `snapshots/` (committed captures).

Live DB state observed (read-only, `data/fpl.duckdb`): `mart_fact_player_fixture` = 138,707 rows
across **only** 2021-22..2025-26; `mart_fact_player_fixture_live`, `stg_live_player_version`,
`stg_live_player_fixture_version`, `mart_team_fixture_live`, `snapshot_capture` = **0 rows**.
Committed snapshots: 5 pre-season `daily/` captures (2026-07-27..31), **0** `player-history/`
captures. So today the versioned tables are empty; the only feature data in the DB is the archive.

---

## 1. Inventory — what each snapshot run captures, with stamp and grain

There are **two** capture cadences, and they capture different things.

### 1a. Daily snapshot (`.github/workflows/snapshot.yml`, 06:00 UTC; `jobs/daily_snapshot.py`)

Fetches `bootstrap-static`, `fixtures`, and `event-live/{gw}` (`daily_snapshot.py:71-82`).
`include_player_history` defaults to `False` (`daily_snapshot.py:64,201`), so **element-summary
is not fetched daily**. What it promotes:

| Payload | Promoted to | Grain | Stamp | Columns |
|---|---|---|---|---|
| bootstrap-static → elements | `stg_live_player_version` | `(season, element, capture_id)` | `known_at` = capture time | identity/registration only: `code`, `web_name`, `element_type`, `position`, `team_id`, `now_cost`, `status` (`live_snapshot.py:255-292`; schema `schema.sql:199-212`) |
| fixtures | `stg_live_fixture_version`, `mart_team_fixture_live` | `(season, fixture, capture_id)` / `(season, team_id, fixture, capture_id)` | `known_at` = capture time | schedule metadata only: `gw`, `kickoff_time`, `team_h/a`, `*_difficulty`/`fdr`, `finished`, `rest_days` (`live_snapshot.py:294-378`; schema `schema.sql:214-227,436-450`) |
| event-live | **not promoted** — raw payload only | — | — | Deliberately dropped from the load path: `load_capture` handles only bootstrap/fixtures/element-summary (`live_snapshot.py:243-514`). event-live aggregates double gameweeks and is kept as a raw safety net (`live_snapshot.py:4-6`, `daily_snapshot` docstring). It is **not** a per-fixture feature source. |

So the daily run supplies the versioned **roster** and **schedule**, but **no per-fixture event
stats**.

### 1b. Player-history snapshot (`.github/workflows/player-history.yml`, 07:30 UTC)

Fetches `element-summary/{id}/` for every player, but **writes only when the latest finished
gameweek advances** (workflow header; `player-history.yml:47-72`), i.e. roughly once per completed
GW. Loaded via `snapshot_files.load_directory` with `mode="player-history"`. This is the **only**
source of per-fixture event stats:

| Payload | Promoted to | Grain | Stamp | Columns |
|---|---|---|---|---|
| element-summary → history | `stg_live_player_fixture_version`, `mart_fact_player_fixture_live` | `(season, code, fixture, capture_id)` | `known_at` = capture time | full component set: `minutes`, `starts`, `goals_scored`, `assists`, `clean_sheets`, `goals_conceded`, `saves`, penalties, cards, `bonus`, `bps`, `expected_goals`, `expected_assists`, `expected_goals_conceded`, `threat`, `creativity`, `defensive_contribution`, `tackles`, `recoveries`, `clearances_blocks_interceptions`, `value`, `selected`, `transfers_in/out` (`fpl_api.py:152-192`; `live_snapshot.py:419-514`; schema `schema.sql:389-434`) |

Manifest fields written per capture: `captured_at`, `season`, `history_through_gw`,
`element_payloads`, `player_fixture_rows` (`player-history.yml:104-114`).

**Distinction (per the task):** the versioned live/element/status fields (roster, cost, status,
schedule/FDR) come from the **daily** run; the per-fixture event stats that the models actually
consume come **only** from the **player-history** run. The two are stamped identically
(`known_at` = wall-clock capture time) but arrive on different cadences.

---

## 2. Stamp integrity — is `known_at`/`captured_at` set at capture time, and does it fail loud?

**Set at capture time, not backfilled — confirmed.**

- The workflow stamps `STAMP="$(date -u +...Z)"` at fetch time and writes it as manifest
  `captured_at` (`snapshot.yml:41`, `player-history.yml:102-114`).
- On load, `write_capture` uses `stamp = captured_at or datetime.now(UTC)`
  (`live_snapshot.py:119`) and rejects a naive datetime (`live_snapshot.py:120-121`). That single
  `stamp` is written as `known_at` on **every** promoted row — player versions
  (`live_snapshot.py:265`), fixtures (`:315,338`), and every element-history row (`:424`). So
  `known_at` = "when we captured it", which is the correct knowledge-time semantics: it is when
  the value became known to us, independent of `kickoff_time`.
- Consequence worth stating: because element-summary re-lists the **whole** season history on
  each capture, a fixture's stats become visible at `as_of` only once *some* capture taken after
  that fixture has landed with `known_at <= as_of`. The stamp is the capture instant, never the
  match instant — so cadence (Section 6) governs visibility.

**Fail-loud guarantees — present at capture/load, absent at read.**

- Partial capture is refused: "every endpoint must succeed or the whole capture is abandoned and
  the process exits non-zero" (`daily_snapshot.py:9-13`); `write_capture` refuses an empty capture
  (`live_snapshot.py:117-118`) and wraps the header + all payload rows + derived rows in one
  `BEGIN/COMMIT/ROLLBACK` transaction (`live_snapshot.py:125-166`).
- The workflows use `set -euo pipefail`, `curl --fail`, HTTP-200-only, non-empty and valid-JSON
  gates (`snapshot.yml:53-80`).
- Committed packages are checksum-verified (`snapshot_files.py:22-46`) and every payload is
  re-hashed against its recorded sha256 on load (`live_snapshot.py:180-184`); manifest counts are
  cross-checked (`snapshot_files.py:80-96`).
- **Gap:** there is **no freshness assertion at *read* time.** `PointInTimeView` returns whatever
  has `known_at <= as_of` and never checks that a capture covering the most recent completed GW
  actually exists. A missing/stale capture **fails safe** (the model silently uses older history)
  rather than leaking, but it fails *silently*. A real-deadline forecast should refuse to emit
  when the last completed GW is not yet captured (recommended in Section 7).

**Minor stamp note:** `OUTCOME_COLUMNS` in `pit.py:61-95` omits `threat` and `creativity`, though
both are post-match Opta indices. `observed_*` hard-filters by `kickoff_time` regardless, so this
does not leak there, but the `player_registry` projection guard (`assert_no_outcome_columns`,
`pit.py:469,491-495`) would **not** reject a projection that named `threat`/`creativity`. Worth
adding them to `OUTCOME_COLUMNS` for defence in depth (not a live defect today).

---

## 3. Feature gap — do the snapshots capture an `as_of`-sourceable equivalent of each feature?

Features the current models actually consume:

- **Minutes model (Stage B baselines + Candidate V1/V2/V3):** the trailing-5 **minutes**
  distribution and the position prior; history is `minutes` per prior fixture
  (`minutes_harness.py:325-334`).
- **Goals model (Stage C):** trailing **goals_scored** and **expected_goals** (xG); the harness
  selects `goals_scored` and `expected_goals` from prior rows
  (`attacking_harness.py:150-161`).
- **Assists idea (not yet a candidate):** would need **expected_assists** and **creativity**.

| Feature | Captured in snapshot? | Source payload / table | Stamp | Gap |
|---|---|---|---|---|
| `minutes` (trailing-5, minutes model) | **yes** | element-summary → `mart_fact_player_fixture_live` (`fpl_api.py:166`, `live_snapshot.py:434`) | `known_at` | none in capture; consumers don't read it (Section 5) |
| `goals_scored` (goals model) | **yes** | element-summary → live table (`fpl_api.py:169`, `live_snapshot.py:436`) | `known_at` | as above |
| `expected_goals` / xG (goals model) | **yes** | element-summary → live table (`fpl_api.py:180`, `live_snapshot.py:448`) | `known_at` | as above; subject to post-hoc revision (Section 6) |
| `expected_assists` (assists idea) | **yes** | element-summary → live table (`fpl_api.py:181`, `live_snapshot.py:449`) | `known_at` | none in capture |
| `creativity` (assists idea) | **yes** | element-summary → live table (`fpl_api.py:184`, `live_snapshot.py:451`) | `known_at` | none in capture; revisable |
| `threat` (used as shot proxy in staging notes) | **yes** | element-summary → live table (`fpl_api.py:183`, `live_snapshot.py:450`) | `known_at` | revisable; absent from `OUTCOME_COLUMNS` (Section 2) |
| target **roster** (which players to predict) | **yes** | bootstrap → `stg_live_player_version` | `known_at` | none; already read via `player_registry` |
| **schedule / opponent / venue / FDR** | **yes** | fixtures → `mart_team_fixture_live` | `known_at` | none; already read via `schedule()` |
| player **club at time `t`** (transfers) | **partial** | live rows carry per-fixture `team_id`; registry carries current club | `known_at` | fine per-fixture; cross-season stint resolution still needs `code` + fact-row `team_id`, per AGENTS rule |

**Every trailing feature the models use is captured with a `known_at` stamp.** There is no
capture-side gap for any modelled feature. The gap is entirely on the **read/consumer** side.

---

## 4. Reconstructability — can each player's trailing-5 window be rebuilt from snapshots alone?

**In principle, yes; in practice, not on any wired path today.**

- Current-season (2026/27) trailing history lives in `mart_fact_player_fixture_live`, one
  bitemporal version per `(season, code, fixture, capture_id)` with `known_at`
  (`schema.sql:389-434`). Selecting the newest version per fixture with `known_at <= as_of`
  reconstructs the exact window as it was known at a deadline — `pit.py:_select_latest_known`
  does precisely this (`pit.py:231-266`).
- Prior-season history (2021-22..2025-26) comes from the archive `mart_fact_player_fixture`. This
  is knowledge-time-valid *for prior seasons only*: those matches completed before the 2026/27
  season began, so `kickoff_time < as_of` is a sound knowledge bound for them. `observed_player_
  fixtures` already unions the two sources (`pit.py:353-367`).

**What is missing to make it true:**

1. **The blocker (Section 5):** the models/harnesses/prospective job read trailing history from
   the archive only, never from the live table. During 2026/27 the archive holds **no**
   current-season rows (confirmed: archive seasons are 2021-22..2025-26 only). So a real
   in-season trailing-5 built via `player_fixture_history` would be composed entirely of *prior
   seasons* — the player's 2026/27 GW1..GW(n-1) minutes/goals/xG would be **invisible**. The
   window would be silently wrong for every in-season gameweek.
2. **The captures must be loaded.** `player-history` packages are committed to `snapshots/` but
   only enter the live tables via `jobs/load_snapshots` (`load_snapshots.py`). The current DB has
   them un-loaded (0 live rows). A real-deadline run must load the latest player-history package
   first.
3. **Cold start at season start.** At 2026/27 GW1 there are no 2026/27 captures yet, so the
   trailing window must come entirely from prior seasons keyed by **`code`** (never bare
   `element_id`/`team_id`, per AGENTS). A newly promoted or newly listed player with no
   prior-season row has an empty window and correctly falls to the position prior (the minutes
   baseline's `q` fallback; `prospective_minutes_v1.py:19-23`). This is a genuine, unavoidable
   dependence on the archive for pre-capture history — acceptable and knowledge-time-valid because
   prior seasons are genuinely in the past, provided the join uses `code`.

---

## 5. Read API — does `features/pit.py` already expose a leak-safe versioned read?

**Yes — the read capability already exists and is correct.** No new API is needed; the work is to
*use* it.

- `PointInTimeView.observed_player_fixtures` returns component rows and, when the live table
  exists, unions `mart_fact_player_fixture` (archive, `kickoff_time < as_of`) with
  `mart_fact_player_fixture_live` selected by `_select_latest_known(known_at <= as_of)`, newest
  version per `(season, code, fixture)` (`pit.py:288-302,353-367,231-266`). This is exactly the
  knowledge-time trailing-feature read the models need.
- `player_registry` selects the roster from `stg_live_player_version` with `known_at <= as_of`,
  identity-only, guarded against outcome columns (`pit.py:442-488`).
- `schedule()` / `upcoming_fixtures` union the versioned live schedule by `known_at`, dedup
  keep-last, and project schedule-only columns (`pit.py:371-438`).
- `AsOf` rejects naive datetimes (`pit.py:41-57`); `FeatureSource` cannot name a `mart_target_*`
  table (`db.py:47-48`, `pit.py:180-190`); the live tables are in `FEATURE_READABLE_TABLES`
  (`db.py:28-45`).

**Where it is (not) used:**

- **Backtest harnesses do NOT use it.** `attacking_harness.run_attacking_fold` issues raw SQL on
  `mart_fact_player_fixture` for both history and targets (`attacking_harness.py:150-161,180-191`).
  `minutes_harness` likewise (`minutes_harness.py:184-192,318-334,341-354`). This is correct for a
  *historical development backtest* (the archive is the only source and is judged by event time),
  but it means the harnesses prove **event-time** correctness only, never knowledge-time.
- **The one prospective job uses the API for roster and schedule but NOT for features.**
  `prospective_minutes_v1` builds the roster from `player_registry` and the fixtures from
  `schedule()` (`prospective_minutes_v1.py:159-185`), but sources trailing history from
  `player_fixture_history` (`:188`), which is the raw archive read
  (`minutes_harness.py:318-334`). So even the registered live path reads its **features** from the
  archive, not the versioned snapshot.

**Smallest change needed (specify only, do not implement):** route trailing-feature sourcing
through `PointInTimeView.observed_player_fixtures` (or an equivalent `known_at`-gated union) so
that, for a live `as_of`, current-season history comes from `mart_fact_player_fixture_live` by
`known_at` and prior seasons from the archive. Concretely, `player_fixture_history` (the shared
builder used by both the prospective job and, by design intent, the fold harness) should read the
union rather than `mart_fact_player_fixture` alone. No new class or method is required — the
union already exists in `observed_player_fixtures`.

---

## 6. Edge cases and recommended rules

### Congested fixtures (a match finishing < ~48h before the next deadline)
- Cause: `player-history` writes at 07:30 UTC and only when bootstrap reports the GW `finished`
  (`player-history.yml:47-72`). Between a late kickoff and the next deadline there may be < 24h,
  and the completed-GW capture may not yet have landed/loaded.
- Behaviour today: **fails safe** — if no capture with `known_at <= as_of` covers the last match,
  `observed_player_fixtures` simply omits it and the window is staler; it never leaks. But it is
  silent.
- **Recommended rules:** (a) add a deadline-triggered capture (`workflow_dispatch` on a schedule
  anchored to `deadline_time`, not only 06:00/07:30) to shrink the latency window; (b) at read
  time, assert that a `player-history` capture with `known_at <= as_of` and
  `history_through_gw >= last_completed_gw` exists, and **refuse to emit** a prospective forecast
  otherwise (fail loud, per Section 2's gap).

### FPL/Opta ICT revisions (`threat`/`creativity`/xG changing after the fact)
- The bitemporal PK `(season, code, fixture, capture_id)` (`schema.sql:433`) stores each revision
  as a new version; `_select_latest_known` picks the newest `known_at <= as_of`
  (`pit.py:251-265`). A revision landing *after* `as_of` is correctly excluded — the model sees
  the value as it stood at the deadline. **This is already handled correctly**, conditional on
  daily captures continuing to run so revisions are versioned rather than overwritten.
- **Recommended rules:** never overwrite a prior capture (already enforced: append-only,
  `schema.sql:43-52`); keep the daily cadence through the whole season so late revisions are
  captured with their own `known_at`; add `threat`/`creativity` to `OUTCOME_COLUMNS`
  (`pit.py:61-95`) for guard completeness. (`influence`/`ict_index` are not captured by
  `ElementHistory` and are not modelled, so no action.)

### Postponed / rearranged fixtures
- The fixtures payload is versioned in `stg_live_fixture_version` / `mart_team_fixture_live` by
  `known_at`; `schedule()` unions and dedups keep-last on `(season, fixture, team_id)`
  (`pit.py:419-432`), and `upcoming_fixtures` filters `since = as_of`. A fixture postponed to a
  date after `as_of` correctly drops out of the predicted set under the latest known schedule; a
  rescheduled fixture reappears as a new version. `detect_season_skew` additionally refuses a
  fixtures payload that belongs to the prior season (`fpl_api.py:218-242`, enforced in the
  loader `live_snapshot.py:296-301` and workflow `player-history.yml:75-80`).
- **Recommended rules:** source the *prediction* schedule for a live run exclusively from
  `upcoming_fixtures`/`schedule()` (the versioned live schedule), never from the archive — the
  prospective job already does this (`prospective_minutes_v1.py:170`). Treat a fixture whose
  latest known `kickoff_time` moved across `as_of` as out-of-scope for that deadline.

---

## 7. Recommendation — moving feature sourcing from archive to versioned snapshot

Prioritised; blocker vs nice-to-have made explicit. (All are specifications for later, separately
scoped work — none are implemented here.)

**P0 — genuine blocker. Wire trailing-feature sourcing to the versioned read.**
Route `player_fixture_history` (and, for a future knowledge-time backtest, the harness history
queries) through `PointInTimeView.observed_player_fixtures` / a `known_at`-gated union instead of
raw `mart_fact_player_fixture`. Until this is done, any in-season 2026/27 prospective run builds
its trailing window from prior seasons only (the archive has no current-season rows), which is
silently wrong. The read API already exists (`pit.py:353-367`); this is a sourcing change, not a
new capability. This is the single biggest blocker.

**P1 — operational prerequisites (blockers for a real deadline, but not code-model changes).**
1. Load the latest committed `player-history` package into the live tables before a deadline
   (`jobs/load_snapshots`); the current DB has zero live rows, so a run today would see an empty
   current-season history even after P0.
2. Add a **read-time freshness gate**: refuse to emit a prospective forecast unless a
   `player-history` capture with `known_at <= as_of` covers the most recent completed GW. Today a
   missing capture fails safe but silently (Section 2).
3. Add deadline-anchored capture triggers to shrink the congested-fixture latency window
   (Section 6).

**P2 — hardening / nice-to-have.**
- Add `threat`/`creativity` to `OUTCOME_COLUMNS` (`pit.py:61-95`) for guard completeness.
- Document/verify that all cross-season trailing joins in the live path use `code` (and fact-row
  `team_id` for club), never bare `element_id`/`team_id` — the AGENTS invariant that already cost
  0.022 log score once.
- Consider promoting a note that `event-live` is a raw safety net only and must never be used as a
  per-fixture feature source (it aggregates double gameweeks; `live_snapshot.py:4-6`).

**Not a blocker (already correct by design):** ICT-revision handling, postponement handling, and
season-start cold start via `code`-keyed prior-season history are all sound given the bitemporal
capture and the existing read API — they need the daily cadence to keep running, not new code.

---

## Appendix — the crux in one sentence

The knowledge-time machinery is built and complete on the **capture** side
(`live_snapshot.py`, both workflows) and on the **read** side (`pit.py`), and every modelled
feature is captured with a `known_at` stamp; the failure is that the **feature-sourcing seam**
still points at the post-hoc archive by `kickoff_time`, so the versioned snapshot the whole
apparatus exists to produce is never actually read for trailing model features.
