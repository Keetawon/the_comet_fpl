# Development roadmap: GW1 decision pack, then BI

Status: active execution plan  
Last updated: 2026-08-17  
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

**Implementation status (2026-08-14): implemented, offline-tested, and produced once from the
retained rehearsal vintages.** `src/fpl/artifacts/decision_comparison.py` owns the schema,
derivation, deterministic `comparison_id`, and atomic no-clobber write;
`fpl.jobs.compare_decisions` is the thin entry point; `docs/decision-comparison-artifact.md` is the
contract and `docs/gw1-deadline-runbook.md` step 12 the operational context.

It reads only the four frozen artifacts, touches no database, and re-derives each ledger `run_id`
from that forecast's own manifest and canonical bytes, so nothing is re-forecast or re-solved. It
fails closed instead of reporting when the two forecasts disagree on cutoff, horizon, database,
seed, draws, live captures or contracts; when they declare the same `component_modes`; when a plan
names a different forecast hash than the one it is paired with; or when a plan's first-gameweek
expected points do not reconcile to that forecast's own rows.

Rehearsal output: `comparison_id`
`181e1aaa98b602c2b21c9be32927f1168c4a05c70222754e2237c76a1bf75e54`, reproduced bit for bit on a
second run to a fresh path. Squad overlap 8/15, GW1 XI overlap 7/11, captain and vice-captain both
disagree. Cross-evaluated captain gaps: +2.07 xP under the default model and +1.42 xP under the
diagnostic, each computed inside a single model.

**Absolute EV is not comparable between the paths** (322.79 against 249.46 over GW1-5 measures the
two models' calibration against each other, not squad quality), so the captain question is answered
by cross-evaluation and never by comparing one model's EV with the other's.

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

- By 2026-08-15: finish optimizer artifact hardening and its tests. **Done (2026-08-14).**
- By 2026-08-18: complete one clean end-to-end rehearsal on the latest committed snapshot; record it
  as a real pre-deadline vintage, not as the final team. **Done (2026-08-14); see P0.2.**
- On 2026-08-20: produce a preliminary decision pack so there is a safe fallback if the final API
  capture or local machine fails.

  **A first preliminary pack was produced early, on 2026-08-14**, at HEAD
  `a149f31b88da9b29f921d1cb8e5690d527b15cc6`, on the same latest committed snapshot
  (`2026-08-13T072348Z`) the rehearsal used — the preliminary step takes the latest committed
  snapshot and captures nothing, so no newer input existed. Steps 1-12 ran in order, the full gate
  was green (1,418 passed), and all four artifacts plus the comparison validated through their
  readers.

  **It reproduces the rehearsal's decision exactly and therefore adds no new information.** All
  2,905 prediction rows are bit-identical to the rehearsal for both paths, and both optimizer
  artifacts carry the *same* `decision_sha256` (default `14eff5b3…c8e767`, diagnostic
  `1f63e2c0…182df5`) with a *different* `run_id` (default `3d5de107…f200ca1`, diagnostic
  `960b4994…ce5aedde`). That split is the contract working as designed: `decision_sha256` binds what
  was decided, `run_id` binds what produced it, and only the producing commit and database hash
  moved. Ledger vintages `6ccb5445…e69396` (default) and `b2ea050b…6a8a646` (diagnostic); comparison
  `9c66ad3b…9ba6a7`.

  Two operational facts were confirmed rather than assumed: a full `build_db` rebuild **preserves**
  recorded ledger vintages (2 before, 2 after, then 4 once the preliminary pair was recorded), and
  recording a forecast changes `database_sha256` for any later run, which is why the runbook
  generates both forecasts before any ledger write.

  **The 2026-08-20 slot still stands.** Its value is fresher data, and re-running it then on a newer
  committed snapshot is what makes it a real fallback rather than a relabelled rehearsal.

  **A fresher preliminary pack was produced on 2026-08-16**, at HEAD
  `301912e06c7fafe33cacd3ed434ff3667da4c6f9`, from the then-latest committed snapshot
  `2026-08-16T063551Z` (season `2026-27`, 20 teams, 380 fixtures, 587 elements — six more than the
  08-13 capture). Steps 1-12 ran in order: all `SHA256SUMS` verified, DuckDB rebuilt with all 21
  committed daily packages loaded, and both forecasts generated before any ledger write on
  `database_sha256 b68f6e041a0d1a0e101f389052fe84f288d33bd163c605a30d20339f5dded8d9`
  (`bootstrap_known_at 2026-08-16T06:35:51Z <= as_of 2026-08-21T17:30:00Z`; 2,935 = 581 x 5 plus
  the six new roster players). Ruff, format, and strict mypy were clean; pytest ran 1,540 passed /
  4 skipped / 13 failed, where all 13 are the documented WinError-1314 non-elevated-symlink
  failures in the `test_bi_export.py` publish path (unchanged machine baseline, unrelated to the
  P0 pipeline) — not the all-green gate of the 08-14 pack.

  **Unlike the 08-14 pack this one changes both decisions**, so it adds information: default
  `decision_sha256 3ad7a98e…88bcb7` (was `14eff5b3…c8e767`), diagnostic `135b49fb…a96caf` (was
  `1f63e2c0…182df5`). Chain: default forecast `4bb3879f…d01eac` -> ledger run `881cbd54…7469f6` ->
  optimizer run `b3e9f2a7…93c3bb`; diagnostic forecast `bc9b72f1…17b69d` -> ledger run
  `253c2eb2…5ef315` -> optimizer run `f4246357…6002c7`; comparison
  `79c4785d10dad712fd5f675afb656931d3aff2e033e7ba2bc800743072073eb8`.

  - Default: £100.0m squad, GW1 EV 64.77, GW1-5 EV 322.86, zero hits; XI Donnarumma — Tarkowski,
    Virgil, Van Hecke, O'Reilly — Gibbs-White (V), Szoboszlai, Mbeumo, E.Le Fée — Watkins, Haaland
    (C); bench Heaton (GK), Hamer, Bidwell, Scarlett.
  - Diagnostic: £97.5m squad, GW1 EV 50.17, GW1-5 EV 250.29, zero hits; captain B.Fernandes, vice
    Tarkowski.
  - Structure unchanged from the earlier vintages: squad overlap 8/15, GW1 XI overlap 7/11, captain
    and vice both disagree. Cross-evaluated captain gaps moved to +1.84 xP Haaland over B.Fernandes
    under the default model (+3.68 armband; was +2.07) and +1.61 xP B.Fernandes over Haaland under
    the diagnostic (+3.22; was +1.42) — the two models still each prefer their own captain.

  This pack supersedes the 08-14 pack as the standing fallback vintage (same procedure, fresher
  committed input, changed decisions). The 2026-08-20 and deadline slots are unaffected.
- On 2026-08-21: capture and commit the latest official data, rerun the sequential pipeline roughly
  2-3 hours before the deadline, and lock the owner decision no later than 30 minutes before the
  deadline. Do not trade reproducibility for a last-minute unrecorded refresh.

P0 is complete only when the owner has the final legal GW1 team and the forecast, ledger, optimizer,
and comparison artifacts can be traced by immutable IDs and SHA-256 values.

## P1: BI semantic export and decision dashboard

Begin after P0 is rehearsed and safe. Build the semantic/export boundary before UI work. BI and the
dashboard must never query the mutable production DuckDB directly.

### P1.1 — Freeze semantic contract v1

**Implementation status (2026-08-14): frozen, typed, and executable.**
`src/fpl/publish/contract.py` declares the schema as validated data,
`docs/bi-semantic-contract.md` is its authoritative prose counterpart, and
`tests/test_bi_semantic_contract.py` pins it with 45 tests. The two files change together.

The contract is executable rather than prose because every expensive defect here has been
join-shaped. `SemanticContract.validate_contract()` rejects, by construction: a join touching a
season-scoped id (`element_id`, `team_id`, `opponent_team_id`) without binding `season`; a forecast
fact missing `run_id`/`as_of` or not keying on `run_id`; an outcome fact carrying `run_id`; a
`many_to_one` join that does not bind its target's full grain and would fan out; a nullable column
that does not declare what its NULL means; and a nullable or absent grain column. Each rejection has
a test that constructs the violation and asserts it is caught.

**Three dimensions were added to the roadmap's original five**, each forced by a documented
invariant, not by taste:

- `dim_player_season` — `web_name`, `position` and `element_id` are season-scoped, so a single
  `code`-grain player dimension carrying them would misreport them or fan cross-season queries out;
- `dim_player_stint` — club membership is time-scoped within a season, and `AGENTS.md` forbids
  resolving club from a player dimension, so without this there is nowhere correct to resolve it;
- `dim_team_season` — the season-scoped `team_id` on every fact needs somewhere to resolve to a
  cross-season `team_code`.

`dim_player` and `dim_team` remain as named, narrowed to permanent identity only: `dim_player`
carries no club and no position.

`NullMeaning` deliberately has no `zero` option, so an unmeasured xG can never be published as a
measured `0.0`. `fact_forecast_player_fixture`, `fact_forecast_team_fixture` and `fact_player_form`
are declared but listed in `contract.NOT_YET_SOURCED`, giving P1.2 and P1.6 a fixed target and
letting the P1.4 exporter refuse to publish a partial contract silently.

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

**Implementation status (2026-08-14): implemented, offline-tested, and verified end to end.**
Artifact schema version 2 adds `player_fixture` and `team_fixture` record types alongside the
unchanged player-gameweek rows; the ledger gains `ledger_prediction_player_fixture` and
`ledger_prediction_team_fixture`, written inside the run's own transaction. Contract in
`docs/prospective-points-artifact.md` and `docs/prediction-ledger.md`; tests in
`tests/test_fixture_grain_transport.py`.

It is an output/contract change only. The composer already produced per-fixture distributions and
the job already held the Stage A team-goal distributions; both were simply discarded at write time.
`lambda_against` and the clean sheet are read off the opponent's own scored distribution, so a team
row cannot disagree with the player rows beside it. **No component model, composer, objective or
default changed**, and a real GW1-2 run reproduces the same player-gameweek rows as before.

**The mapping is enforced rather than asserted.** On every serialise and every read each gameweek
row is re-derived from its own player-fixture rows: fixture ids and kickoff times must match, the
distributions must convolve to exactly the stored gameweek distribution, expected bonus must sum,
and the Stage A fallback flag must be the OR across the player's fixtures. So the two grains cannot
drift apart silently — which matters because the convolution is not invertible.

Schema version 1 stays readable and the frozen pre-P1.2 vintages are unaffected: a version-1
manifest declares neither fixture count, and supplying fixture rows under version 1 fails closed.
`fact_forecast_player_fixture` and `fact_forecast_team_fixture` are consequently removed from
`contract.NOT_YET_SOURCED`, leaving only `fact_player_form` (P1.6).

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

**Implementation status (2026-08-14): implemented and offline-tested.**
`src/fpl/storage/outcomes.py` owns source selection and validation; the thin
`fpl.jobs.attach_outcomes` CLI wires it to the existing ledger transaction. It reads
`mart_target_player_fixture` only at `(season, code, fixture)` grain and treats the season-qualified
`stg_fixture.finished = TRUE` value as the authoritative official-fixtures finalization signal.
Eligible fixtures must also have `kickoff_time < as_of`, both separately named point measures must
be non-NULL, and a source duplicate is rejected. Exact re-runs are idempotent no-ops; new fixture
keys append; any changed value for an attached key fails closed rather than weakening append-only
history. Offline temp-DuckDB tests cover the happy path, NULL/unfinalized/duplicate failures,
idempotency, append-only addition, transaction rollback, and a double-gameweek player.

Build the thin job that attaches outcomes only for finalized fixtures. It must:

- read at player-fixture grain;
- preserve `total_points_as_recorded` and `points_under_rules_2026_27` as different measures;
- reject NULL/unfinalized outcomes, duplicate keys, and partial transactions;
- be idempotent for the same finalized payload and append-only for new fixtures;
- include failure-path and double-gameweek tests.

### P1.4 — Atomic pivot-friendly export

**Implementation status (2026-08-14): implemented and contract-tested.**
`src/fpl/publish/export.py` now owns the atomic, versioned Parquet boundary and
`fpl.jobs.export_bi` is the thin CLI. It publishes all fourteen frozen v1 tables, validates the
complete staged export before an atomic generation-pointer swap, and refuses source drift, broken
season-qualified joins, non-finite/altered NULL values, stale opt-in freshness, and concurrent
clobbering. `docs/bi-export-contract.md` defines the read-only consumer boundary, layout, manifest,
all-vintage run selection, and explicit optimizer-plan input. `tests/test_bi_export.py` covers the
offline boundary plus an archive-build smoke test.

**Two follow-up fixes (2026-08-14), found by an independent clean-environment verification and both
now landed:**

1. *Undeclared `pytz` runtime dependency.* The provenance reads fetched `TIMESTAMPTZ` via DuckDB
   `fetchall()`, which converts to a Python `datetime` through `pytz` — not a declared dependency
   (the project pins `tzdata` for `zoneinfo`). On a clean install the export failed with
   `ModuleNotFoundError` as soon as any forecast vintage or optimizer plan was present. Fixed by
   reading those instants with `epoch_us()` (exact microseconds, no timezone name, no `pytz`).

2. *Live-season dimension sourcing.* The six identity dimensions were sourced from the archive marts
   only, which cover completed seasons — so a real (upcoming-season) forecast vintage failed
   referential integrity because its new players/clubs/fixtures/gameweeks had no dimension row. The
   dimensions now union the archive marts with the versioned live staging for seasons the marts do
   not carry. A new `stg_live_team_version` (flattened from the bootstrap `teams` payload at
   snapshot-load time) supplies the live season's `team_id → team_code` map, which was previously
   only raw JSON. Point-in-time policy: latest committed snapshot per entity (current registry);
   forecast facts keep their own `as_of`, so no leakage. A fresh build with no snapshots stays
   historical-only. See `docs/bi-export-contract.md` and `tests/test_bi_export.py`
   (`test_live_season_dimensions_are_sourced_from_the_snapshot_registry`).

Create domain code under a new `src/fpl/publish/` package and keep the job entry point thin.

- Export versioned Parquet facts/dimensions plus a strict manifest with schema version, creation
  time, source run IDs, source/max `known_at`, row counts, hashes, and freshness.
- Build the full export in a sibling temporary directory, validate it, then atomically replace the
  published directory.
- Test grain, referential integrity, NULL preservation, row accounting, deterministic ordering,
  schema drift, stale inputs, and failure cleanup.
- The dashboard and external BI tools read only this read-only export.

### P1.5 — Fixture difficulty contract

**Implementation status (2026-08-15): implemented, offline-tested, and archive-smoke-tested.**
`fpl.publish.export` derives formula-version `fixture-ease-v1` at per-team-fixture grain from the
immutable stored lambdas, with a per-`(run_id, season)` positive denominator backed by at least two
rows. Rejected denominators and zero `lambda_against` produce real Parquet NULLs, never zero/NaN/
infinity. The raw lambdas stay beside the denominator and three directed ease measures. Official FDR
is joined separately on `(season, fixture, team_id)`: archive `mart_fact_team_match.fdr`, or the
latest live `mart_team_fixture_live.fdr` capture for a season the archive mart does not carry. It is
never blended into an ease index. Contract and export details are in
`docs/bi-semantic-contract.md` and `docs/bi-export-contract.md`; deterministic offline and archive
coverage is in `tests/test_bi_export.py`.

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

**Implementation status (2026-08-14): implemented and offline-tested.**
`fpl.transform.facts:build_player_form` materializes `mart_fact_player_form` at the long
`(season, gw, code, window)` grain and `build_db` rebuilds it after the component and target marts.
It treats the existence of a `mart_fact_player_fixture` row as rostered, uses observed gameweek
anchors and their latest kickoff as the point-in-time boundary, preserves both legs of a double
gameweek, and never creates a row for a missing gameweek. Availability aggregates rostered rows;
productivity aggregates `minutes >= 1` rows only. xG/xA sums and per-90 denominators use only the
matching measured rows, points come only from `mart_target_player_fixture.points_under_rules_2026_27`,
and unmeasured starts, xG/xA, and DC stay NULL rather than becoming zero. P1.6 sources the last
semantic-contract table, so `contract.NOT_YET_SOURCED` is now empty.

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

**P1.6b addition (owner-approved, 2026-08-15): `fact_team_form`.** The backward team-form companion
at `(season, gw, team_code, window)` grain, added to the semantic contract and the Parquet export in
the same change (declared and sourced together, so never in `NOT_YET_SOURCED`; semantic contract
stays at v1, an additive table exactly as P1.5's columns were). It mirrors `build_player_form`'s
anchoring exactly — observed gameweeks, window ending at the anchor gameweek inclusive, the anchor
gameweek's latest kickoff as the point-in-time boundary, both double-gameweek legs counted, no
fabricated blank-gameweek match — and is keyed on `team_code` only. Unmeasured `team_xg`/`team_xgc`
(all of 2021-22) stay NULL with their per-match rates, never zero. `fpl.transform.facts:
build_team_form` materializes `mart_fact_team_form`, rebuilt by `build_db` after the other marts.
It exists to feed the P1.7 fixture-matrix **Team** page's recent-form block.

### P1.7 — Dashboard MVP

**P1.7a backend read-model export (2026-08-15): implemented, offline-tested.**
`src/fpl/publish/dashboard_json.py` + thin `fpl.jobs.export_dashboard_json` publish
versioned per-page application JSON (`fixture_matrix.json`, `players.json`) derived **only**
from a published P1.4 Parquet export via Polars — no DuckDB handle is opened at all. It
reuses the Parquet exporter's atomic generation-swap machinery (sibling staging dir, validate,
symlink swap, concurrent no-clobber, failure cleanup), verifies the source export's manifest
self-hash and every file SHA it reads, and emits a manifest whose `content_sha256` excludes
only `generated_at` so identical inputs are byte-identical. NULL stays JSON `null` (ease
indices, official FDR, xG/xA, rates, not-yet-persisted fixture probabilities); objects key on
`run_id` + `season` + `team_code`/`code` only; club labels resolve season-safely through
`dim_team_season`; player fixture chips carry the club's ease/FDR joined on the
season-qualified fixture-team key; availability is a passed-through reported overlay. The
read models cover the two exploration pages only; the summary / next-GW / forecast-vs-actual /
optimizer pages are later additive files. Contract: `docs/dashboard-json-contract.md`; the
runbook notes the emitter as optional post-decision output. Tests:
`tests/test_dashboard_json.py` (publication tests need the directory-symlink privilege, as
for `tests/test_bi_export.py`; the archive smoke test is self-contained — it seeds a
synthetic future-season vintage into a throwaway copy of the built database, so it holds on
any machine with `build_db` run, with or without recorded real vintages).

**P1.7b UI part 1 (2026-08-16): implemented.** `dashboard/` is a new self-contained Vite +
React + TypeScript + Tailwind + shadcn/ui + @tanstack/react-table app reading ONLY the
static JSON read models (never DuckDB, never Parquet in-browser). The sidebar lists all six
pages in roadmap order with the five unimplemented ones as labelled stubs. Shipped: the
shared direction-labelled difficulty colour scale with legend and a model-ease vs official
FDR colour-source toggle (never blended); the FixtureTicker (opponent + venue + headline,
NULL → neutral dashed chip with no number, blank gameweek → empty slot, double gameweek →
two chips); the Overall/Attack/Defense view toggle (defence colours on clean-sheet
probability anchored at the loaded league mean); the venue + gameweek-range filter bar
bounded by the vintage horizon; and the Fixture matrix (Team) page — one row per club,
recent form from `fact_team_form` labelled with its anchor season (last season at GW1),
expandable per-fixture table exposing raw lambdas, clean-sheet probability, all three ease
indices, official FDR, and the Stage A league-average flag beside the composite. Vitest
component tests (12) cover bucket direction, NULL→neutral, and DGW two-chip behaviour;
`npm run build`, `tsc`, and `oxlint` are clean. Dev data: a real schema-v2 vintage
(GW1-5 default architecture, run `86a072ade6dd4d56…`) is recorded in the dev ledger and
its read models render the page; the generated JSON under `dashboard/public/data/` is
gitignored and regenerable via `dashboard/README.md`.

**P1.7d Summary + Next GW pages (2026-08-16): implemented.** The read-model manifest grows
to schema version 2 with two additive files (v1 record shapes unchanged):
`summary.json` (latest run + parsed component modes, roster coverage, next-gameweek
first/last kickoff from `dim_gameweek` — deadlines are a typed NULL in the export and are
never fabricated — top-5 next-GW/horizon/flagged xP, ease extremes with FDR beside, plans
present) and `next_gw.json` (every `fact_optimizer_plan` plan joined season-safely to its
own forecast run's per-gameweek EV, ownership/availability overlay, and flags; weeks with
roles/captain/vice/bench order/hits/squad cost; a full-horizon per-gameweek `player_xp` map
so the UI's 1/3/5-GW selector sums inside one model — any unmeasured gameweek makes the
summed horizon EV null, never partial; `component_modes` from `dim_forecast_run` labels
which architecture produced each plan). The emitter reads two more source tables
(`dim_gameweek`, `fact_optimizer_plan`) and fails closed on plans referencing unknown
forecast runs, weeks outside the horizon, mixed decisions, players the forecast never
rated, or missing captain/vice. **The default-vs-diagnostic diff is derived in the UI from
the complete plans, not precomputed, and cross-plan EV is never compared anywhere** (the
P0.3 calibration lesson is baked into the page copy). The Summary page is the app landing
route. Optimizer plans reach the export only as explicit `--optimizer-plan` inputs, each
resolving to exactly one recorded ledger forecast run; no plans in the export means a "no
plans" state, never a fabricated squad.

**P1.7c Players page (2026-08-16): implemented.** One additive read-model change ships
with it: each `players.json` fixture row now also carries the player's CLUB primitives for
that fixture (`team_lambda_for`, `team_lambda_against`, `team_probability_clean_sheet`),
joined on the same season-qualified fixture-team key as the ease fields, so the expanded
player row shows the raw numbers behind the chip colour with no client-side join. No
model, composer, optimizer, contract table, or Parquet export changed. The page reuses the
shared FixtureTicker (now generic over team/player fixture shapes), view toggle, colour
scale + FDR colour-source toggle, and venue/gameweek filter bar, and adds player filters:
position, team, price range, minimum average minutes (last 5), and availability. The chip
headline is the fixture xP and its colour follows the active view's club metric (defence
colours on the club defence ease — the player's own clean-sheet probability is a separate,
separately-shown measure that is null until the ledger persists it); expanding a row swaps
attack-detail vs defence-detail column ordering and always shows the muted remainder, the
form anchor season label, and the full per-fixture primitive set. Unmeasured values stay
"–" everywhere (a null price or minutes never satisfies a filter bound). Vitest grew to 21
tests (player chip semantics: xP headline vs colour metric, FDR source, NULL→neutral, null
xP; page smoke incl. expandable primitives and overlay labelling). Dev read models were
regenerated from the recorded vintage so the new fields carry real data.

**P1.7e Forecast-vs-actual + Optimizer-audit pages (2026-08-16): implemented.** Two read
models ship. `forecast_vs_actual.json` scores each recorded vintage against its own season's
finalised outcomes (points under 2026/27 rules) via a read-time join at `(season, gw, code)`:
rows, mean EV/actual, bias, MAE, and CRPS (double-sum discrete CRPS from the stored
full-points distribution; a malformed pmf scores null, never an invented number), split by
position and gameweek, plus a P(≥2 points) calibration table. Unfinalised outcome rows are
excluded from every sum. **With no finalised outcomes inside any vintage's horizon — the
2026-27 GW1 state — `has_outcomes` is false and the page shows the framework with an explicit
explanation, never zero-filled numbers**; no historical vintage is recorded, so there is
nothing to score against yet. `optimizer_audit.json` exposes the full provenance behind each
optimizer decision; to carry it across the BI boundary the semantic contract gains an
additive `dim_optimizer_run` (grain `optimizer_run_id`, sourced only from the explicit
optimizer-artifact export inputs — no plans passed, no rows published — joining
many-to-one to `dim_forecast_run`; contract stays at v1 like every additive table so far)
with both Git commits, forecast artifact SHA, squad-rule path/version/SHA, full solver
identity/options/seed/status, the bounded-search policy, the rules snapshot, the assumptions,
and the development-only status as three deterministic JSON columns plus scalars. The audit
page renders provenance, solver, policy with its declared optimality scope, constraints,
assumptions, and the transfer path with hits; the squad/XI themselves are not duplicated —
the page reads `next_gw.json`. The app shell now routes all six pages with no stubs. Dev
data: the dev ledger carries a diagnostic vintage (run `407668b6…`) beside the default
(`86a072ad…`), and two dev-only optimizer plans (default `7ce5b0c8…`, diagnostic
`90683dfc…`, both `risk_lambda=0`, clean worktree) feed the export, so the Next-GW diff and
the audit page render real plans.

Build only after the export contract and its tests pass. Minimum pages:

1. **GW1 decision:** squad, XI, captain/vice, bench, EV, ownership, availability, flags, and
   default-vs-diagnostic differences.
2. **Fixture matrix:** overall/attack/defence ease for GW1 and rolling 3/5-GW horizons, with raw
   lambdas and home/away filters. The **Team** view also shows recent form from `fact_team_form`
   (last 3/5/10 and season-to-date).
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
- revisit cards only if a real decision is shown to turn on their measured margin;
- build the manager-team transfer-suggestion wizard per
  `docs/manager-team-suggestions.md` (manager_id input, own-squad transfer suggestions with
  exact free-transfer/-4-hit accounting, up to five locked must-keep players via `--lock`,
  the `--min-bench-appearance` bench gate, selling-value-aware budget checks); the
  optimizer-side primitives (`--lock`, `initial_banked_free_transfers`, the bench gate) are
  already implemented and tested — the remaining work is the manager ingest boundary, value
  accounting, and the dashboard page.

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
