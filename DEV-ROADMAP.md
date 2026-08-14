# Development roadmap: GW1 decision pack, then BI

Status: active execution plan  
Last updated: 2026-08-13  
Target: 2026/27 GW1  
Deadline: `2026-08-21T17:30:00Z` (`2026-08-22 00:30` Asia/Bangkok)  
First kickoff: `2026-08-21T19:00:00Z`

This is the canonical near-term delivery order. `AGENTS.md` remains the authority for correctness,
model history, frozen contracts, and working protocol. If a task does not advance one of the two
owner goals below, defer it unless it is required to keep the deadline path correct.

## Owner goals

1. Produce an auditable, legal GW1 squad, starting XI, captain, vice-captain, and bench before the
   deadline.
2. Produce a decision dashboard/export for fixture difficulty and player form, including pivot-ready
   xG, xA, minutes, starts, goals, assists, bonus/BPS, defensive contribution, points, and EV.

The goals are ordered. Goal 1 may not be delayed by dashboard polish or new model research.

## Current baseline

Verified on `main` at `c158df1` on 2026-08-13; re-check HEAD and the latest snapshot before acting.

- The latest committed live snapshot was captured at `2026-08-13T07:23:48Z` and contains 581
  elements, 20 teams, 38 events, and 380 fixtures.
- The prospective pipeline emits a canonical, provenance-bearing player-gameweek JSONL artifact.
- The append-only DuckDB prediction ledger is implemented in `src/fpl/storage/ledger.py`, with the
  thin `fpl.jobs.record_forecast` entry point. It currently records player-gameweek forecasts and
  separate player-fixture outcomes.
- Stage E selects a legal 15-player squad and exact weekly lineup/captain, then performs a bounded
  multi-GW transfer search. The forced-transfer/no-transfer pruning defect is fixed.
- The full repository gate was green after the ledger and optimizer fixes: 1,326 tests passed,
  Ruff was clean, formatting was clean, and strict mypy passed. This is historical evidence, not a
  substitute for rerunning the gate after changes.
- The local database is rebuildable. Daily snapshots are the irreplaceable source and must remain
  committed.

Open operational gaps:

- `chance_of_playing_next_round` is repeated across GW1-5;
- future prices use deadline `now_cost`; price changes and selling value are not modelled;
- the ledger lacks player-fixture forecast distributions and an outcome-ingestion job;
- the versioned BI semantic/star-schema export and dashboard do not exist.

## Delivery rules until the GW1 deadline

- Freeze the current component defaults: `attacking=v3`, `assists=coupled`,
  `appearance=seasonal`, and `share-signal=auto`.
- Do not tune or special-case the rested-starter floor, cold-start goalkeeper prior, promoted-team
  prior, positional attacking allocation, cards, or any individual player.
- Do not rerun, amend, or reinterpret a frozen historical evaluation.
- The V1 goals/V1 assists path is a diagnostic comparator, not a promoted replacement. Run it beside
  the default and report disagreements; do not silently change the default.
- Availability remains a reported overlay. For the decision pack, apply the current multiplier to
  GW1 only. Later-GW reuse is an explicit scenario assumption and must not be presented as measured.
- Use deadline prices for the GW1 initial squad. Label later-GW affordability and transfer plans as
  frozen-price scenarios; they are not price forecasts.
- No manual opinion may alter a stored probability distribution. A late owner decision based on
  news must be recorded separately from the model output, with its time and reason.
- DuckDB jobs run sequentially. All deadline outputs are immutable and identified by hashes/run IDs.

## P0: GW1 decision pack

P0 blocks BI implementation. Work top to bottom.

### P0.1 — Durable optimizer artifact

Harden `fpl.jobs.optimize_squad` without changing its objective or search behavior.

**Implementation status (2026-08-14): complete and offline-tested.** The deadline rehearsal and
final deadline run remain outstanding operational work.

Required output contract:

- a versioned schema and explicit development-only status;
- atomic write through a flushed unique sibling temporary file and an atomic create-if-absent
  promotion, including concurrent-writer no-clobber behavior;
- input forecast artifact path, SHA-256, schema/version, run `as_of`, horizon, and forecast commit;
- optimizer Git HEAD and clean-worktree status;
- squad-rule path, contract version, and file SHA-256;
- solver name/version/options/status and deterministic seed/options;
- complete search policy: candidate-pool bound, transfer depth, transition limit, beam width, free
  transfer state, risk lambda, and declared optimality scope;
- the chosen squad, GW1 XI, captain, vice-captain, bench, cost, and each horizon transfer step;
- explicit assumptions for bench/autosubs, availability, ownership, static prices, and selling value;
- a stable optimizer run identity derived from the input and behavior-defining provenance;
- strict JSON (`allow_nan=False`) and deterministic ordering for identical inputs;
- offline tests for schema, provenance completeness, deterministic identity, no-clobber, and
  failure-atomic cleanup.

Acceptance: two runs with identical inputs make identical decision content/run identity; a malformed
or dirty input state fails closed; the existing hand-computable squad and transfer tests still pass.

### P0.2 — One sequential deadline runbook

Add a concise `docs/gw1-deadline-runbook.md`. Prefer a thin orchestration entry point only if it
removes operator error without moving business logic into `src/fpl/jobs/`.

**Implementation status (2026-08-14): authored, and executed end to end once as a retained
rehearsal** on `main` at `724f8287368f1961a5a7bf7be4c9fe1aaba9f701`, ahead of the 2026-08-18 due
date. All eleven steps ran in order with no deviation and no step failing closed:

- snapshot `2026-08-13T072348Z` verified (season `2026-27`, 20 teams, 380 fixtures,
  first kickoff `2026-08-21T19:00:00Z`, first deadline `2026-08-21T17:30:00Z`); all 18 committed
  daily packages re-verified, 54 `SHA256SUMS` entries, zero mismatches;
- DuckDB rebuilt and all 18 snapshots loaded sequentially; full gate green with the archive present
  (1,377 passed, zero skipped; Ruff, format, and strict mypy clean);
- both forecasts generated before any ledger write, so both record the same
  `database_sha256 = f062360d…c1446`; each is 2,905 rows = 581 roster x 5 gameweeks, `as_of`
  `2026-08-21T17:30:00Z`, `bootstrap_known_at 2026-08-13T07:23:48Z <= as_of`;
- manifests agree on `as_of`, season, horizon, seed, draws, database, live inputs, and contracts,
  and differ only in `component_modes` (`v3`/`coupled` against `v1`/`v1`, both `seasonal`);
- both recorded sequentially in the ledger as distinct vintages, then both optimized at
  `risk_lambda=0` into immutable artifacts that re-read and re-validate through
  `read_optimizer_artifact`.

Rehearsal identities are retained outside the repository. Default forecast
`fc0fad1b…31b0c` -> ledger run `f9bbd862…70de25` -> optimizer run `786d79cc…fe02e3`
(decision `14eff5b3…c8e767`). Diagnostic forecast `a9397a3e…44ca3a` -> ledger run
`7a8c8495…b6381a` -> optimizer run `93234e61…bda8cf` (decision `1f63e2c0…182df5`).

Re-optimizing the default forecast to a fresh path reproduced the artifact bit for bit (same
`run_id`, `decision_sha256`, and file SHA-256), and re-running to an existing path was refused. This
rehearsal is a pre-deadline vintage, not the final team; the official deadline run is still due.

The runbook must execute, in order:

1. verify branch/HEAD and a clean worktree;
2. verify the latest committed snapshot manifest and the official GW1 deadline;
3. rebuild DuckDB and load all daily snapshots sequentially;
4. run the full local gate;
5. generate the default GW1-5 artifact (`v3/coupled/seasonal/auto`);
6. before any ledger write mutates DuckDB, generate the V1/V1 diagnostic artifact on the identical
   cutoff, horizon, draws, seed, database, and live captures;
7. compare the two forecast manifests and require identical input/database/schedule identities
   except for the declared component architecture;
8. record the default and diagnostic artifacts sequentially in the append-only ledger;
9. optimize both artifacts at `risk_lambda=0`; optional risk runs are clearly labelled sensitivity
   analyses and never replace the EV result;
10. verify hashes, manifests, `known_at <= as_of`, row accounting, probability sums, squad legality,
    cost, club cap, formation, captain/vice, aggregate reconciliation, and no-clobber behavior;
11. produce a short comparison report and retain every artifact/run identity.

The GW1 view is read from the GW1-5 artifact; do not create a redundant forecast merely to filter one
gameweek. The five-gameweek horizon informs initial squad value, while the GW1 row informs lineup and
captaincy.

### P0.3 — Decision comparison

The final report must show, for default and diagnostic paths:

- selected 15, cost, ownership, GW1 expected points, and GW1-5 expected points;
- GW1 XI, captain, vice-captain, and ordered bench;
- players selected by both paths and players unique to either path;
- captain agreement/disagreement and the EV gap between alternatives;
- availability/status fields and all cold-start, Stage A league-average, attacking/assist fallback,
  and transfer flags;
- the bounded transfer scenario and all hits, with the frozen-price caveat;
- provenance and ledger run IDs.

The comparison is a decision aid, not a promotion test. Do not choose a model because one named
player looks more plausible.

### P0.4 — Rehearsal and deadline schedule

- By 2026-08-15: finish optimizer artifact hardening and its tests.
- By 2026-08-18: complete one clean end-to-end rehearsal on the latest committed snapshot; record it
  as a real pre-deadline vintage, not as the final team.
- On 2026-08-20: produce a preliminary decision pack so there is a safe fallback if the final API
  capture or local machine fails.
- On 2026-08-21: capture and commit the latest official data, rerun the sequential pipeline roughly
  2-3 hours before the deadline, and lock the owner decision no later than 30 minutes before the
  deadline. Do not trade reproducibility for a last-minute unrecorded refresh.

P0 is complete only when the owner has the final legal GW1 team and the forecast, ledger, optimizer,
and comparison artifacts can be traced by immutable IDs and SHA-256 values.

## P1: BI semantic export and decision dashboard

Begin after P0 is rehearsed and safe. Build the semantic/export boundary before UI work. BI and the
dashboard must never query the mutable production DuckDB directly.

### P1.1 — Freeze semantic contract v1

Define each table's grain, keys, null semantics, source owner, and allowed joins before writing the
exporter.

Dimensions:

- `dim_forecast_run`
- `dim_player`
- `dim_team`
- `dim_fixture`
- `dim_gameweek`

Facts:

- `fact_forecast_player_fixture`
- `fact_forecast_player_gameweek`
- `fact_forecast_team_fixture`
- `fact_player_fixture_actual`
- `fact_player_form`
- `fact_optimizer_plan`

Every forecast fact includes `run_id` and `as_of`. Every actual stays separate until finalization.
`code` is the cross-season player key; `team_code` is the cross-season club key; fixture facts use
`(season, code, fixture)` or `(season, team_code, fixture)` as appropriate. Preserve nullable values.

### P1.2 — Add fixture-grain forecast transport

The current public artifact and ledger preserve only player-gameweek distributions. Add a versioned
fixture-grain transport rather than reverse-engineering component values from a convolved GW PMF.

Retain:

- player-fixture full-points distribution and EV;
- player-gameweek convolved distribution and EV;
- team-fixture predicted goals for/against, clean-sheet probability, fixture/opponent/home-away
  context, and fallback flags;
- the exact mapping from player-fixture rows to their derived player-gameweek row.

This is an output/contract change only. It must not alter the component models or composer.

### P1.3 — Outcome attachment

Build the thin job that attaches outcomes only for finalized fixtures. It must:

- read at player-fixture grain;
- preserve `total_points_as_recorded` and `points_under_rules_2026_27` as different measures;
- reject NULL/unfinalized outcomes, duplicate keys, and partial transactions;
- be idempotent for the same finalized payload and append-only for new fixtures;
- include failure-path and double-gameweek tests.

### P1.4 — Atomic pivot-friendly export

Create domain code under a new `src/fpl/publish/` package and keep the job entry point thin.

- Export versioned Parquet facts/dimensions plus a strict manifest with schema version, creation
  time, source run IDs, source/max `known_at`, row counts, hashes, and freshness.
- Build the full export in a sibling temporary directory, validate it, then atomically replace the
  published directory.
- Test grain, referential integrity, NULL preservation, row accounting, deterministic ordering,
  schema drift, stale inputs, and failure cleanup.
- The dashboard and external BI tools read only this read-only export.

### P1.5 — Fixture difficulty contract

Publish primitives first: predicted goals for (`lambda_for`), predicted goals against
(`lambda_against`), clean-sheet probability, opponent, venue, date, and official FDR.

Use a versioned, clearly directed ease index only after denominator and coverage checks:

```text
attack_ease_index  = 100 * lambda_for / league_average_team_lambda
defence_ease_index = 100 * league_average_team_lambda / lambda_against
overall_ease_index = sqrt(attack_ease_index * defence_ease_index)
```

`100` means league-average and higher means easier/better for the named team. Keep the raw lambdas
beside the indices. Never call an ease index "difficulty" without displaying its direction, and do
not blend official FDR into the model index.

### P1.6 — Player-form contract

Keep availability and productivity separate:

- availability windows use recent rostered player-fixture rows and report appearances, starts,
  minutes, and DNPs;
- productivity windows use appeared rows and report xG, xA, goals, assists, bonus, BPS, defensive
  contribution, and points;
- expose rolling 3/5/10 windows and season-to-date values;
- calculate xG/90 and xA/90 only over rows where the signal is measured:

```text
xG_per_90 = 90 * sum(expected_goals) / sum(minutes on those same measured-xG rows)
xA_per_90 = 90 * sum(expected_assists) / sum(minutes on those same measured-xA rows)
```

Return NULL when the matching minutes denominator is zero. Never zero-fill unmeasured xG/xA, and
never multiply a per-90 display rate by expected minutes inside the reporting layer.

### P1.7 — Dashboard MVP

Build only after the export contract and its tests pass. Minimum pages:

1. **GW1 decision:** squad, XI, captain/vice, bench, EV, ownership, availability, flags, and
   default-vs-diagnostic differences.
2. **Fixture matrix:** overall/attack/defence ease for GW1 and rolling 3/5-GW horizons, with raw
   lambdas and home/away filters.
3. **Player-form pivot:** position/team/price filters; rolling 3/5/10 minutes, starts, xG, xA,
   xG/90, xA/90, goals, assists, bonus/BPS, DC, points, and upcoming EV.
4. **Forecast versus actual:** EV/actual, bias, CRPS/calibration, and rank/capture by position and
   horizon after outcomes exist.
5. **Optimizer audit:** run provenance, constraints, selected squad, transfer path, hits, solver
   status, and assumptions.

The dashboard is explanatory. It must expose the primitives behind composite scores and must not
silently turn ownership into selection utility.

## P2: after the deadline

Only after P0 and the BI MVP are secure:

- measure and contract per-GW availability semantics;
- design price-change and selling-value handling;
- monitor recorded real-deadline forecasts against finalized outcomes;
- decide whether a newly named positional attacking-allocation candidate is warranted;
- investigate a price-informed starter prior on a fresh, pre-registered validation window;
- revisit cards only if a real decision is shown to turn on their measured margin.

These are not GW1 blockers and must not be rushed into the current forecast.

## Required gate and handoff

Run jobs sequentially. Before any implementation handoff:

```powershell
.\.venv\Scripts\pytest.exe -q
.\.venv\Scripts\ruff.exe check src tests
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\mypy.exe src
```

Report changed files, tests and exact results, output schemas with one sample record, measured
constants for any non-trivial policy, unresolved assumptions, generated run IDs/hashes, and the
chosen GW1 squad/lineup/captain when the final run is authorized. Commit and push only when the
owner explicitly requests it.
