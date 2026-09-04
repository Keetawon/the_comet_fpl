# Development roadmap: GW1 decision record, then decision analytics

Status: active execution plan  
Last updated: 2026-09-01<br>
Target: 2026/27 GW1  
Deadline: `2026-08-21T17:30:00Z` (`2026-08-22 00:30` Asia/Bangkok)  
First kickoff: `2026-08-21T19:00:00Z`

This is the canonical near-term delivery order. `AGENTS.md` remains the authority for correctness,
model history, frozen contracts, and working protocol. If a task does not advance one of the two
owner goals below, defer it unless it is required to keep the deadline path correct.

**Post-deadline note (2026-08-26).** The GW1 deadline has passed. Dated statements below about
pending 2026-08-20/21 operations are retained as the delivery record and do not authorize a rerun
or reinterpretation of frozen artifacts. The local manager-team workflow is now implemented
development-only. The ordered P2 dashboard program is implemented development-only: contracts
first, then player and team deep analytics, then exact player/team prediction monitoring, then
evidence-bound insight summaries. Its implementation and automated gates are complete; final
responsive in-browser visual verification remains pending where recorded in P2.5. No model default
or frozen evaluation changed. P2.5 owns any later post-deadline work.

## Owner goals

1. Produce an auditable, legal GW1 squad, starting XI, captain, vice-captain, and bench before the
   deadline.
2. Produce a decision dashboard/export for fixture difficulty and player/team form, including
   pivot-ready xG, xA, minutes, starts, goals, assists, bonus/BPS, defensive contribution, clean
   sheets, on-pitch goals conceded, saves, xGC, points, and EV; then add risk-aware player/team
   exploration, exact forecast monitoring, and evidence-bound page summaries.

The goals are ordered. Goal 1 may not be delayed by dashboard polish or new model research.

## Bird's-eye goal status

- **Goal 1 is operationally ready but not complete.** The forecast, ledger, optimizer, comparison,
  and Plan Builder paths are implemented and rehearsed, and the immutable 2026-08-17 evening pack
  remains the standing fallback. Completion still requires the mandatory 2026-08-20 fallback pack,
  the 2026-08-21 final run, and manual confirmation of the final team in the official FPL UI.
- **Goal 2's MVP, deep analytics, exact parallel monitoring, evidence-bound summaries, and
  explicit prior/current-season player/team actual ranges have completed development-only implementation
  and automated gates; final responsive in-browser visual verification remains pending.** Semantic contract
  version 6, the ten established dashboard files at schema version 9, two separate provisional
  schema-version-1 files, immutable player/team outcomes, the atomic static-JSON
  boundary, nine read-only analytic/decision pages, Plan Builder, and the browser-only Squad Draft sandbox are shipped
  development-only. P1.8's full Players-page
  form matrix and additive observed
  defensive fields are implemented in code and focused tests; the failure-atomic local database
  rebuild and atomic BI/static republish completed on 2026-08-19, so they are visible locally.
  The final deadline vintage still requires the same controlled refresh inside Goal 1. The local
  manager-team path is implemented development-only. P2.2 player/team deep analytics, P2.3's
  corrected append-only outcome boundary with parallel comparison pages, and P2.4's deterministic
  summaries plus optional evidence-bound renderer are complete development-only.

## Current baseline

The 2026-08-26 dashboard-program audit began with clean local `main` at `7e82915`, equal to
`origin/main`. This is the baseline before the documentation-first contract and implementation
series; later handoff records the new commits and full gate rather than rewriting this audit point.

- The latest committed live snapshot was captured at `2026-08-18T06:39:18Z` and contains 590
  elements, 20 teams, 38 events, and 380 fixtures. Its first kickoff is
  `2026-08-21T19:00:00Z`; its deadline is `2026-08-21T17:30:00Z`.
- At the start of this dated audit, the local DuckDB, formal development forecasts, optimizer
  plans, and published dashboard read models derived from the `2026-08-17T06:50:35Z` snapshot with
  587 players and 2,935 player-gameweek rows. That sentence is a historical baseline, not a claim
  about the post-P2.4 republished generation.
- The prospective pipeline emits a canonical, provenance-bearing player-gameweek JSONL artifact.
- The append-only DuckDB prediction ledger is implemented in `src/fpl/storage/ledger.py`, with the
  thin `fpl.jobs.record_forecast` entry point. It records player-gameweek and player-fixture
  forecast distributions, with outcomes attached separately.
- Stage E selects a legal 15-player squad and exact weekly lineup/captain, then performs a bounded
  multi-GW transfer search. The forced-transfer/no-transfer pruning defect is fixed, and immutable
  platform/default, diagnostic, and custom-plan identities are separated fail-closed.
- The BI semantic-v6/star export, fixture difficulty and player/team form/actual facts, the ten
  established schema-v9 static files plus two separate provisional schema-v1 files, nine read-only
  analytic/decision pages, Plan Builder, and Squad Draft are implemented
  development-only. The browser reads only published JSON and never DuckDB. Player/Team analytics
  and separate Player/Team prediction-monitoring pages are current; the old
  `#forecast-vs-actual` route is only a player-page alias.
- The localhost plan service was live and ready at audit time (PuLP 3.3.2, CBC 2.10.3, clean and
  idle), and the dashboard preview served the latest frontend. These are transient service checks,
  not substitutes for the final immutable artifacts.
- Focused P2.3 ledger/outcome, semantic/export validation, dashboard-emitter/public-package, strict
  frontend loader/page/route tests, dashboard production build, and lint passed. The broader Python
  gate on this Windows host still reaches only the atomic publish boundary in the directory-symlink
  cases: `WinError 1314` means the shell lacks symlink privilege, not that a semantic/read-model
  assertion failed. This is still not an unqualified green formal gate; use Developer Mode, an
  elevated/symlink-capable environment, or an explicitly approved documented run before declaring
  it green.
- The local database is rebuildable. Daily snapshots are the irreplaceable source and must remain
  committed.

Open operational gaps:

- the outcome/evidence for the dated fallback/final runs and official-FPL submission must be
  reconciled separately; this P2 update does not backfill them;
- `chance_of_playing_next_round` is repeated across GW1-5;
- manager captures now carry current purchase/selling values and cash, but future prices and
  future selling-value changes remain frozen at forecast `now_cost`;
- authenticated My Team access, hosted manager accounts, and capture-retention policy remain open;
- real prospective forecast monitoring remains empty until immutable finalized 2026/27 outcomes
  are attached.

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

P0 remains the only deadline gate. P1 shipped early and may be refreshed only after the decision
artifacts are secure; no further BI polish may delay P0. Work top to bottom.

### P0.0 — Immediate sync and code freeze

**Audit status (2026-08-19): action required before the next artifact run.** The audit found local
`main` clean at `299de22`, with six reviewed implementation commits ahead of `origin/main` and zero
behind. Review and commit this documentation reconciliation with the approved implementation
history, then push the complete history without rewrite. The committed 08-18 snapshot has 590
players, while the current DuckDB and published development forecasts still use the 08-17
587-player snapshot. Never relabel those older artifacts as 08-18 or final output.

Execute in this order:

1. Preserve today's exact Python and dashboard evidence. Before calling the formal gate
   unqualified green, use a symlink-capable/elevated environment or obtain explicit approval for
   the documented `WinError 1314` environmental result.
2. Review and commit the documentation reconciliation with the six audited implementation
   commits, then push the complete approved history to `origin/main` without rewriting history.
3. Verify a clean worktree and `origin/main...HEAD` divergence of `0 0`.
4. Freeze code and component defaults until after the deadline, except for a demonstrated blocker
   in the deadline path. Do not spend the remaining window on model research or dashboard polish.
5. Treat the mandatory 2026-08-20 pack as the next authorized forecast refresh; do not create an
   ad hoc 08-18/08-19 recommendation between audited slots.

Acceptance: `git status --porcelain` is empty;
`git rev-list --left-right --count origin/main...HEAD` returns `0 0`; both gates and their exact
results are recorded; and the frozen component modes remain `v3`/`coupled`/`seasonal`/`auto`.

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

  **A third preliminary pack was produced on 2026-08-17** (rerun at the owner's request to pick
  up the optimizer fixes), at HEAD `2097842f1517cc82d95b6574581122151cc9f1ea`, from the
  CI-captured snapshot `2026-08-17T065035Z` (season `2026-27`, 20 teams, 380 fixtures, 587
  elements). Steps 1-12 ran in order on `database_sha256
  3032d30b03878573eb2e8ad5928c1e4c1ff78b22048024d98cbe8964adc334b5`
  (`bootstrap_known_at 2026-08-17T06:50:35Z <= as_of 2026-08-21T17:30:00Z`; 2,935 = 587 x 5).
  Ruff, format, and strict mypy were clean; pytest ran 1,559 passed / 4 skipped / 13 failed —
  the same documented WinError-1314 non-elevated-symlink `test_bi_export.py` baseline.

  **This pack is the first run under the fixed optimizer** (commit `85408c0`): the bench
  tie-break no longer ranks zero-availability players first, so the injured Heaton (status
  `i`, chance 0) is replaced by Forster as the default bench goalkeeper and the injured
  Danns is replaced by Destan on the diagnostic bench. The XIs and EVs are otherwise
  unchanged from the 08-16 pack (bench points are outside the objective, so the fix moves
  bench composition, not EV): default GW1 EV 64.77 / GW1-5 322.86, diagnostic 50.17 / 250.31.

  Chain: default forecast `05c18f2f…0973ca` -> ledger run `23a90303…f125d` -> optimizer run
  `b8193a48…05388` (decision `ade247f6…a0bb13`); diagnostic forecast `ce879c5b…d381e6` ->
  ledger run `5a3f94e2…bc80` -> optimizer run `19df6672…7dbba` (decision `c1b3cfc0…a17fee`);
  comparison `d5abca8b75874c9c1031db1ea515062bcfbd51daefedcae1ea8324cfdcbb6a24`. Structure
  is unchanged from the 08-16 pack: squad overlap 8/15, XI overlap 7/11, captain and vice
  disagree, cross-evaluated captain gaps +1.84/+3.68 (default) and +1.61/+3.22 (diagnostic).

  A clearly-labelled **sensitivity run** with the new `--min-bench-appearance 0.25` bench gate
  was produced from the same default forecast (optimizer run `32d16478…44d4399`, decision
  `781ec06c…c6ffd`): identical XI, captain, and EV, with exactly one bench change —
  Scarlett -> Destan. It is a sensitivity analysis beside the EV result, never a replacement
  for it, and is not part of the ledger or the comparison.

  This pack supersedes the 08-16 pack as the standing fallback vintage. The 2026-08-20 and
  deadline slots are unaffected.

  **The pack was rerun the same day (evening 2026-08-17)** at HEAD
  `60eeb038c8c8ee32cfd9aa4bfe9b19fd08cbff9a` to fold in the equally-priced-filler ownership
  preference (commit `37a7165`), on the same `2026-08-17T065035Z` snapshot. Steps 1-12 in
  order, same gate state (Ruff/format/mypy clean; pytest 1,560 passed / 4 skipped / 13
  environmental failures). Prediction rows are unchanged (same snapshot and roster); the
  ledger carries more vintages than the morning run, so the forecast manifests record a new
  `database_sha256 9da73c23…` and new artifact SHAs. Chain: default forecast
  `c7fc877b…b4b9c` -> ledger run `4a6f9964…78a57` -> optimizer run `92d055c4…1e43f`
  (decision `3a4c96c1…df8f`); diagnostic forecast `dfa5b846…ead8f` -> ledger run
  `c3fced75…19846` -> optimizer run `aad4e4e8…db2f58` (decision `bada0ad6…6d68d`);
  comparison `b6081f9ba45256c300cd105517eb3b89ab70bebddf9500fdeb5489f3e414c3e6`.

  The ownership preference is visible in the recorded default bench: Dubravka (22.1%
  owned) over Forster (3.2%) in goal, Diop (18.2%) over Bidwell (0.1%), Kusi-Asare (7.1%)
  over Scarlett (1.6%) -- all at identical prices, GW1 EV unchanged at 64.77, horizon
  322.86 -> 323.33 (only the transfer path shifts). The `--min-bench-appearance 0.25`
  sensitivity run (optimizer `95a450db…fc1c`) is now squad-identical to the default plan:
  the ownership-selected bench already clears the 25% gate, so the threshold does not bind
  on this vintage. This rerun supersedes the morning pack as the standing fallback vintage.

  **2026-08-19 audit:** the retained 08-17 evening pack at
  `D:\tmp\gw1\20260817T120028Z-60eeb038c8c8-preliminary` remains the standing fallback;
  comparison
  `b6081f9ba45256c300cd105517eb3b89ab70bebddf9500fdeb5489f3e414c3e6` and producing HEAD
  `60eeb038c8c8ee32cfd9aa4bfe9b19fd08cbff9a` remain immutable historical identities. The newly
  committed 08-18 snapshot has 590 players, but the local database and development read models
  still contain the 08-17/587-player vintage. The 08-20 slot is therefore mandatory, not optional.

  **2026-08-20 fallback acceptance:** from the clean, synchronized, frozen HEAD, execute runbook
  Steps 1-12 on the newest committed snapshot. Generate the default and diagnostic forecasts before
  either ledger mutation; require identical cutoff, database, live inputs, seed, draws, and
  contracts except for their declared component modes. Re-read and validate both ledger vintages,
  both optimizer artifacts, and the comparison; record all run IDs, decision hashes, artifact
  SHA-256 values, snapshot identity, database hash, and exact gate results. Copy the complete pack
  to a second location, verify that copy, and designate it as the standing fallback. Publishing BI
  read models is optional and comes only after the decision pack and verified copy are secure.

- On 2026-08-21: capture, checksum, commit, and push the latest official data; verify the repository
  is clean and synchronized; then execute Steps 1-12 sequentially roughly 2-3 hours before the
  deadline (about 21:30-22:30 Asia/Bangkok on 2026-08-21). Validate the default/diagnostic
  comparison and immutable artifact chain. If that run fails closed, use the verified 08-20 pack;
  do not trade reproducibility for a last-minute unrecorded refresh.
- After choosing the final plan, **manually submit it in the official FPL UI**. Enter all 15
  players; verify the budget, maximum-three-per-club rule, legal formation, starting XI, captain,
  vice-captain, and ordered bench; save/confirm before
  `2026-08-21T17:30:00Z` (`2026-08-22 00:30` Asia/Bangkok). Lock the owner decision no later
  than `2026-08-21T17:00:00Z` (`2026-08-22 00:00` Asia/Bangkok), and retain a confirmation
  timestamp plus screenshot or official reference. Any owner override is recorded separately with
  time and reason. The optimizer and dashboard never submit a team automatically.

P0 is complete only when the owner has a confirmed legal GW1 team in the official FPL UI, the
submission evidence is retained, and the final forecast, ledger, optimizer, and comparison
artifacts can be traced by immutable IDs and SHA-256 values.

## P1: BI semantic export and decision dashboard

**Historical bird's-eye status (2026-08-19): substantially implemented development-only.** The semantic
contract/export, fixture-grain forecast transport, outcome attachment, atomic static publish
boundary, fixture difficulty and player/team form views, all six analytic pages, Plan Builder, and
the browser-only Squad Draft sandbox are present. The browser reads only static JSON and never the
mutable production DuckDB. The
Players form-column repair is implemented in code/tests, including observed clean sheets, on-pitch
goals conceded, saves, and xGC. The local development database and BI/static read models were
refreshed successfully and atomically on 2026-08-19. The final deadline vintage must still be
rebuilt, exported, and republished through the P0 sequence; the local refresh does not replace that
artifact. Forecast-versus-actual becomes informative only after outcomes finalize. Manager import
remains separate P2 work.

This dated P1 snapshot predates the P2.2/P2.3 additions. The current status and route counts are
recorded in the Goal 2 and P2 sections above and below.

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

**Implementation status (updated 2026-08-19): implemented and offline-tested.**
`fpl.transform.facts:build_player_form` materializes `mart_fact_player_form` at the long
`(season, gw, code, window)` grain and `build_db` rebuilds it after the component and target marts.
It treats the existence of a `mart_fact_player_fixture` row as rostered, uses observed gameweek
anchors and their latest kickoff as the point-in-time boundary, preserves both legs of a double
gameweek, and never creates a row for a missing gameweek. Availability aggregates rostered rows;
productivity aggregates `minutes >= 1` rows only. xG/xA sums and per-90 denominators use only the
matching measured rows, points come only from `mart_target_player_fixture.points_under_rules_2026_27`,
and unmeasured starts, xG/xA, DC, and xGC stay NULL rather than becoming zero. The P1.8 additive
extension also transports clean sheets, on-pitch goals conceded, saves, and xGC. Basic defensive
counts sum appeared rows and are NULL when there was no appearance; an appeared source row with a
missing basic count fails closed. xGC sums measured appeared rows and is NULL only when none was
measured. P1.6 sources the last semantic-contract table, so `contract.NOT_YET_SOURCED` is now empty.

Keep availability and productivity separate:

- availability windows use recent rostered player-fixture rows and report appearances, starts,
  minutes, and DNPs;
- productivity windows use appeared rows and report xG, xA, goals, assists, bonus, BPS, defensive
  contribution, clean sheets, on-pitch goals conceded, saves, xGC, and points;
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
At that milestone the read models covered the two exploration pages only; the summary / next-GW /
forecast-vs-actual / optimizer pages were later additive files. Contract:
`docs/dashboard-json-contract.md`; the
runbook notes the emitter as optional post-decision output. Tests:
`tests/test_dashboard_json.py` (publication tests need the directory-symlink privilege, as
for `tests/test_bi_export.py`; the archive smoke test is self-contained — it seeds a
synthetic future-season vintage into a throwaway copy of the built database, so it holds on
any machine with `build_db` run, with or without recorded real vintages).

**P1.7b UI part 1 (2026-08-16): implemented.** `dashboard/` is a new self-contained Vite +
React + TypeScript + Tailwind + shadcn/ui + @tanstack/react-table app reading ONLY the
static JSON read models (never DuckDB, never Parquet in-browser). At that milestone the sidebar
listed all six analytic pages in roadmap order with the five unimplemented ones as labelled stubs.
Shipped then: the
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

**P1.7b additive fixture horizon (2026-08-20): implemented in code/tests, uncommitted.**
`fixture_matrix.json` now carries a separately versioned current-at-export schedule overlay
from the full official `dim_fixture` season, bound to the BI export timestamp and database
hash. The Fixture Matrix offers 5/10/15-GW views. Forecast chips, colours, primitives, and
average-ease sorting remain confined to the recorded model horizon; later gameweeks show
neutral opponent/home-away/kickoff fixture context only. The overlay is explicitly not the
schedule known at an older forecast vintage and does not widen the forecast, ledger, or
optimizer. This dashboard-only work must not delay or alter the P0 deadline artifacts.

**P1.7b additive view-owned fixture measures (2026-08-28): implemented.** Fixture Matrix
card headlines are independent of the colour-source toggle. Attack shows published fixture
`lambda_for` as modelled expected goals for, Defense shows published per-fixture clean-sheet
probability, and Overall retains overall ease; Opponent strength, Club ease, and Official FDR
affect only the background. The Attack horizon column is a complete sum of modelled fixture
lambdas and the Defense column is a complete sum of clean-sheet probabilities labelled as an
expected clean-sheet count, never as `P(at least one)`. DGW legs count separately, any missing
selected leg fails the corresponding aggregate closed, and schedule-only rows beyond the recorded
forecast show no forecast headline and enter no total. Frontend deterministic facts and optional
server-owned insight evidence use the same published view metric. This changes no model, emitter,
read-model schema, ledger, or optimizer contract.

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

**Historical P1.7e Forecast-vs-actual + Optimizer-audit milestone (2026-08-16): implemented.** Two read
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
the page reads `next_gw.json`. The app shell routes all six original analytic pages with no stubs;
Plan Builder is the seventh route and Squad Draft is the eighth. Dev
data: the dev ledger carries a diagnostic vintage (run `407668b6…`) beside the default
(`86a072ad…`), and two dev-only optimizer plans (default `7ce5b0c8…`, diagnostic
`90683dfc…`, both `risk_lambda=0`, clean worktree) feed the export, so the Next-GW diff and
the audit page render real plans.

P2.3 supersedes only this milestone's single monitoring file and route: dashboard schema v5 uses
separate `player_forecast_vs_actual.json` and `team_forecast_vs_actual.json` read models and pages.

**P1.7f Platform/custom plan separation + exclusions (2026-08-18): implemented,
offline-tested.** Dashboard read-model schema version 3 gives every optimizer decision an
explicit `plan_kind` (`platform_default`, `platform_diagnostic`, or `user_custom`), stable display
label, and compact lock/exclusion/bench policy. Legacy constrained artifacts without
`plan_origin` are classified as custom from their recorded constraints; new interactive runs
record the origin explicitly. Next GW now owns only the formal platform default and diagnostic
sensitivity, so a custom V3 run can never win by hash order or local storage. Plan Builder owns
the exact user run id, stays on its own result page after solve, and fails visibly rather than
substituting another squad when that id is missing. Summary separates the platform recommendation
from the latest user plan; Optimizer Audit retains all runs with distinct labels. The shared player
picker supports up to five green locks and fifteen red exclusions. Exclusions are enforced through
the initial ILP, every future transfer candidate/squad, artifact validation, run-id provenance,
plan server, read model, and UI; lock/exclusion overlap and unknown/unselectable codes fail closed.
At this dated P1 milestone, `manager_id` was saved only for the post-deadline importer and was
explicitly not applied to a GW1 fresh-squad solve. The P2 implementation recorded below supersedes
that UI boundary without changing the historical P1 result.

**P1.7g Plan Builder decision UX (2026-08-19): implemented and focused-tested.** The fresh-squad
wizard exposes the eligible pool with reusable top and bottom pagination; a bottom-page change
returns focus to the first result without forcing the user to scroll back up. Locks remain green,
exclusions red, and the submitted rule snapshot is frozen while the optimizer runs. The solve card
uses an accessible, calm, indeterminate staged state with honest messages and no fabricated
percentage. A solved custom plan stays separate from the platform recommendation and renders an
exact 15-player sortable analysis table: captain, vice, bench roles, and row colours are fixed to
GW1 even when sorted; sortable columns expose `Total 3 GWs xP`, `Total 5 GWs xP`, and raw
`GW1 xP` through `GW5 xP`; expanded rows show each gameweek's forecast and in-plan role/status.
Missing or malformed exact-run data fails visibly. At this dated milestone the remaining gap was
the post-deadline manager import and selling-value workflow; the P2 implementation below now fills
that local development boundary.

**P1.7h Per-gameweek squad xP and Bench Boost screen (2026-08-19): implemented and
dashboard-tested.** Next GW and Plan Builder append three selected-plan-only rows to the player
table footer: `Planned XI xP (11)`, `Planned bench xP (4)`, and `Planned squad xP (15)`. Each
gameweek is derived from that `PlanWeek`'s exact post-transfer membership and roles; cumulative
columns sum the corresponding complete weekly groups. These are raw player-model xP sums, so the
captain appears once like every other player and captain multipliers, hits, autosubs, and
vice-captain fallback are deliberately excluded. Null player xP, missing gameweeks, and malformed
squads fail closed rather than publishing partial totals. Sorting, filters, pagination, and the
Next GW compare-all scope do not change the selected plan's footer. The highest complete bench-xP
gameweek is marked, with an exact tie resolved to the earliest GW. This is only a loaded-horizon
screen: the optimizer does not optimize bench points, and the read model has no chip inventory or
competing chip windows, full-season forecast, or measured future availability. It is not a
best-season Bench Boost recommendation and never compares totals across model architectures. This
P1 addition changes no delivery gate: the 08-20 fallback pack, 08-21 final pack, and owner's
manual FPL verification remain the sole P0 priority and acceptance path.

**P1.7i Browser-only Squad Draft sandbox (2026-08-21): implemented and dashboard-tested.**
Squad Draft binds to exactly one formal platform-default forecast vintage and its exact recorded
rules snapshot. It permits a partial or complete manual selection up to 15 players, enforces FPL
position maxima and three-per-club, and deliberately treats £100m as an advisory rather than a
constraint so users can explore high-value hypothetical squads. Its sortable/fullscreen table
shows deadline-vintage price, raw GW1-GW5 xP, strict Total 3/5-GW xP, and a sorting-invariant final
footer row with selected cost and xP totals. Complete legal 15-player drafts may show a
best-legal-XI/bench loaded-horizon screen and individual xP shortlist, but neither is a chip
recommendation: manager ownership, chip inventory, transfers/hits, autosubs, captain fallback,
competing windows, later gameweeks, and future measured availability are unavailable. State is
versioned and browser-local; at this dated P1 milestone the route never called the plan server,
emitted an optimizer artifact, or changed the formal/custom plan read models. P2 now adds a
bounded direct manager import through the local Plan Server while preserving browser-local draft
state and leaving formal/custom plan read models unchanged.

**P1.7j Cumulative player-outcome read model (2026-08-25): implemented and offline-tested.**
Dashboard schema version 4 adds `player_horizons.json`, with one endpoint per player for every
`gw_to` in the forecast run. Python convolves the published player-gameweek PMFs and emits
cumulative xP, inclusive `P(points <= 2)`, and inclusive `P(points >= 2/4/6/10/15)`. The emitter
reconciles PMF mass and means, the full roster/gameweek population, player identities, and exact
run endpoints at full precision before publishing compact positional rows quantized to six
decimal places; exact zero/one probability boundaries remain exact. The browser may decode,
select, filter, sort, and sum published
xP; it never sums probabilities, reads a PMF, derives a CCDF, or manufactures a model quantity
from display primitives. The values are raw model distributions, unadjusted for the reported
availability overlay, and cross-gameweek composition is explicitly versioned as independent
marginal convolution. Raw PMFs remain absent from the bulk payload; any future CCDF drill-down
must receive precomputed points through a separately versioned lazy shard. The Players table now
loads the strict v4 file and exposes all six inclusive probability columns for an exact cumulative
endpoint. A shifted start or Home/Away filter suppresses them with an explanation; such filters
may still sum xP but cannot condition a marginal probability. The measured 599-player/five-endpoint
design budget was about 305 KB raw and 76 KB gzipped **per vintage**; the current compact
609-player development vintage measures 259,421 / 75,155 bytes. An all-vintage file scales with
the number of recorded runs.

### P1.8 — Complete Players-page form exposure after P0

**Status (2026-08-19): implementation, focused tests, and local development publication
complete.** The semantic contract, form mart, Parquet export, static emitter, and Players UI now
carry starts, xG/90, xA/90, bonus, BPS, DC, clean sheets, on-pitch goals conceded, saves, and xGC.
The view matrix is explicit: Overall shows common + attack + defence + outcome form columns;
Attack shows common + attack + outcome; Defence shows common + defence + outcome. CS applies to
GK/DEF/MID, GC and xGC to GK/DEF, saves to GK, and DC to DEF/MID/FWD; inapplicable and unmeasured
cells stay dashes with distinct explanations. These are backward-looking observed form measures.
Future player-level saves/DC/GC/xGC forecasts remain unavailable and are never inferred from club
forecast primitives.

Acceptance state: focused schema, transform, export, static-read-model, and UI tests cover measured,
NULL, view, and position-applicability behavior without client-side recalculation. A failure-atomic
local database rebuild populated the additive columns and the local BI/static generation was
atomically republished successfully. Migration alone still leaves pre-existing rows NULL. The final
deadline vintage must repeat rebuild/export/republish through P0; this local development refresh
does not satisfy or replace that deadline artifact. Manager-team import was assigned to P2 and is
now recorded in that section as a separate post-deadline implementation.

Build only after the export contract and its tests pass. Minimum pages:

1. **GW1 decision:** squad, XI, captain/vice, bench, EV, ownership, availability, flags, and
   default-vs-diagnostic differences.
2. **Fixture matrix:** overall/attack/defence ease for GW1 and rolling 3/5-GW horizons, with raw
   lambdas and home/away filters. The **Team** view also shows recent form from `fact_team_form`
   (last 3/5/10 and season-to-date).
3. **Player-form pivot:** position/team/price filters; rolling 3/5/10 minutes, starts, xG, xA,
   xG/90, xA/90, goals, assists, bonus/BPS, DC, clean sheets, on-pitch goals conceded, saves,
   xGC, points, and upcoming EV.
4. **Forecast versus actual:** EV/actual, bias, CRPS/calibration, and rank/capture by position and
   horizon after outcomes exist.
5. **Optimizer audit:** run provenance, constraints, selected squad, transfer path, hits, solver
   status, and assumptions.

The dashboard is explanatory. It must expose the primitives behind composite scores and must not
silently turn ownership into selection utility.

## P2: after the deadline

The current implementation order is binding. Complete each contract and its focused tests before
advancing; none of these tasks changes a prospective model default or frozen evaluation.

### P2.1 - Freeze the dashboard analytics, monitoring, and insight contracts

**Status (2026-08-26): contract freeze complete; P2.2, P2.3, and P2.4 are implemented
development-only.** The
detailed boundaries are frozen in:

- `docs/dashboard-deep-analytics.md`;
- `docs/prediction-vs-actual-dashboard.md`;
- `docs/dashboard-ai-summaries.md`;
- the planned amendments in the BI, ledger, dashboard JSON, deployment, and dashboard runbook docs.

The contracts explicitly separate future exposure exploration from retrospective model diagnosis,
pin complete-gameweek finality, preserve exact stored team PMFs, and make the language model a
bounded renderer over cited facts rather than a source of analytics.

Acceptance: every new quantity has a source grain, direction, null/finality rule, allowed consumer
operation, and test; implementation cannot silently weaken these requirements.

### P2.2 - Player and team deep analytics

**Status (2026-08-26): implemented development-only; focused and full dashboard tests pass.**
Player analytics and Team analytics use only the cumulative/forecast axis values introduced in
dashboard schema version 4 and retained unchanged in current schema version 9. Version 7 added
forecast-owned cold-start provenance for reporting eligibility; version 8 added normalized team
history for Fixture Matrix drill-downs; version 9 adds only fixture-time club/opponent presentation
identity to normalized player actuals. None changes an analytics axis or model quantity.
The pages do not reach around P2.3's outcome facts.

- Player views: price-versus-cumulative-xP Pareto frontier; published inclusive haul-versus-downside
  frontier; ownership-versus-xP differential view; and explicitly labelled observed-form versus
  future-xP context.
- Team views: forecast `lambda_for` versus `lambda_against`; attack opportunity versus expected
  clean-sheet count; and observed team form versus future lambdas. Include fixture count and Stage-A
  league-average fallback count.
- Use only the selected run's modelled fixtures. Current schedule-only proxy rows never enter an
  analytics axis.
- Provide accessible, keyboard-operable SVG plus an exact table/list. Null axis values are omitted
  with counts, never coerced to zero. Pareto geometry is display logic, not optimization.
- Keep visible chart copy concise, include one view-specific How-to-read note, and place tooltips
  edge-aware so they do not clip. Full exact metric/provenance text remains in accessible names and
  the authoritative table even when the visible run id or axis label is shortened.
- Let users tighten the horizontal chart viewport and focus on the efficient/Pareto set when
  outliers compress a dense cluster. Classification still uses the full filtered eligible set;
  viewport controls never change exact tables or insight facts. Player probability bounds use
  displayed percent units. Invalid ranges fail open to the full chart.
- Call outputs player value/risk and club-environment shortlists. Never claim an optimal squad,
  guaranteed return, calibrated current-season goal level, or the best asset inside a club.
- Do not add an EV-versus-standard-deviation or Sharpe view: those axes are empirically collinear
  here. A true constrained portfolio frontier needs joint correlations/samples and squad rules at
  the Python publish/optimizer boundary; the current browser frontier is direct-value Pareto
  geometry over individual players or club environments.
- Label player/team past-vs-future form as latest-at-export reporting context, not state frozen at
  the selected forecast vintage. Show the row's observed `(season, as_at_gw)` anchor because an
  older forecast may be displayed beside later form; this comparison remains explanatory only.
- Player analytics excludes directly published `cold_start_player` rows by default and offers an
  explicit include control. This changes only reporting eligibility and Pareto membership. It must
  not infer newcomer status or alter xP/probabilities; any three-appearance bridge would require
  separately named, pre-registered model research and evaluation and is not part of this change.

Acceptance: pure direction-aware Pareto and aggregation tests cover ties, nulls, vintage isolation,
exact fixed-start horizon endpoints, double and blank gameweeks, venue filtering, expected-count
labelling, fallback accounting, cold-start opt-in, unclipped pointer/keyboard tooltips,
loading/error/empty states, and accessible table equivalence.

### P2.3 - Exact parallel player/team prediction monitoring

**Status (2026-08-26): implemented development-only; focused backend/frontend tests pass.** The
ambiguous player-only aggregate has been replaced by explicit player and team read models and pages.
This is a correctness repair, not merely a visual extension.

1. Persist official home/away scores in live fixture versions. Add an append-only
   `ledger_outcome_team_fixture` with two reciprocal rows per finalized fixture; exact reattachment
   is a no-op and changed outcomes fail closed.
2. BI semantic contract version 3 transports exact team goal PMFs and exports player/team finalized
   outcomes from their ledger tables. It never reconstructs a PMF from a lambda or reads around the
   immutable attachment boundary for monitoring.
3. Dashboard schema version 5 publishes `player_forecast_vs_actual.json` and
   `team_forecast_vs_actual.json`, including coverage, scalar observations, score blocks, splits,
   and calibration. Raw PMFs remain backend-only.
4. Player gameweek scoring requires the whole official gameweek and every forecast fixture leg to
   be final. A partial double gameweek scores zero rows. Team defence CRPS uses the opponent's exact
   stored goal PMF; clean-sheet Brier uses the published clean-sheet probability.
5. Add separate Player prediction vs actual and Team prediction vs actual routes. The old route is
   a temporary alias to the player page. Charts always have exact table equivalents and signed-error
   direction labels.

Acceptance: the hand-computed and failure cases in
`docs/prediction-vs-actual-dashboard.md` pass through ledger attachment, Parquet round-trip, static
publication, public-package sanitization, strict frontend loading, and both pages. On this Windows
host, tests that exercise the final generation-symlink swap require Developer Mode or an elevated
shell; `WinError 1314` at that last OS call is recorded as environment-specific rather than a
product/metric failure.

### P2.4 - Deterministic and optional AI insight summaries

**Status (2026-08-26): implemented development-only.** Every route has a network-free deterministic
insight panel. Summary, Fixture matrix, Players, Player analytics, Team analytics, Player prediction
vs actual, and Team prediction vs actual additionally offer an explicit **Explain with AI** action
when the trusted local insight service is enabled. Next GW suggestion, Optimizer audit, Plan
Builder, and Squad Draft remain deterministic-only.

- The provider-neutral Python service and optional Z.AI GLM adapter use the existing
  protected local server boundary. The browser never holds the API key and hosted static builds make
  no provider call. Server-only configuration is `FPL_INSIGHTS_PROVIDER=zai_glm`,
  `FPL_INSIGHTS_API_KEY`, `FPL_INSIGHTS_MODEL`, and optional credential-free HTTPS
  `FPL_INSIGHTS_BASE_URL`.
- The adapter uses Z.AI's general Open Platform API, not its coding-tools endpoint. Coding Plan
  quota is not assumed to license general application calls; configure a general API key/balance
  under the current provider terms.
- Requests send only exact typed page/vintage/filter selectors. The server verifies the selected
  schema-v9 manifest and file hashes, reconstructs the allowlisted facts from that static
  generation, and refuses mismatched provenance before provider/cache work. No PMFs, caller prose,
  arbitrary prompts, manager/custom-plan identifiers, squads, bank, selling values, capture data,
  credentials, or full page payloads cross the boundary.
- Structured provider output contains fact-id selections/relation enums rather than prose. Python
  renders canonical cited statements. Bounded timeouts/body, narrow retries, rate limiting, true
  single-flight, safe errors, and an ignored provenance-aware cache remain mandatory.
  AI-selected output never supplies canonical numbers, arithmetic, a probability, a model verdict, or decision
  provenance.

Acceptance: implemented security, privacy, provider, cache, server, frontend, stale-response, and
per-route tests cover the cases in `docs/dashboard-ai-summaries.md`. Hosted mode makes no insight
network request, provider use requires explicit opt-in, and every disabled, timeout, rate-limit,
malformed, or upstream failure leaves the deterministic summary usable.

Local acceptance refresh (2026-08-26): a fresh official capture reported all ten GW1 fixtures
final with scores. Outcome attachment appended 610 player-fixture facts and 20 reciprocal team
sides. The semantic-v3 generation hash is
`22c2c25745c6140a6b87d5fac412f56794b72e53365bb068c92c9110b2a57362`; the validated schema-v5
dashboard generation hash is
`258f0e1f77b536949f82fb4e0f79694f4a52b4a36902f1ed6692ff9832f03cf3`. GW1-capable vintages
publish 584 scored player-gameweeks with three explicitly missing immutable outcomes and 20/20
scored reciprocal team sides. Newer GW2-start vintages correctly have no GW1 observations, so both
monitoring pages default to the newest scored prospective-default (`v3` / `coupled` / `seasonal`)
vintage instead of a later-recorded diagnostic, while leaving every role-labelled vintage
selectable. With no scored prospective default they fall back to a scored alternative, then a
pending prospective default, then the newest remaining vintage. The obsolete
`forecast_vs_actual.json` is absent from the replaced generation.

### P2.5 - Other post-deadline work

Only after the ordered dashboard program above, unless an operational blocker requires otherwise:

- **Players explicit Season–GW Actual history (implemented development-only 2026-08-26;
  season-boundary scope correction 2026-08-28).** BI
  semantic contract v4 extends `fact_player_fixture_actual` with deterministic latest live
  components only when the exact append-only finalized player outcome exists. Dashboard schema v7
  publishes normalized `player_actuals.json` records at `(season, code)` grain instead of
  duplicating observations per forecast vintage. Publication is limited to each forecast season
  and its immediate predecessor, with the predecessor present only when finalized observations
  exist. The Players route exposes two chronological `Actual from` / `Actual to` endpoints whose
  page-wide options are the exact finalized `(season, gw)` keys from only the selected run's
  forecast season and its published predecessor. Default/reset selects the latest five keys—at
  2026-27 GW1, `Actual from: 2025-26 GW35` through `Actual to: 2026-27 GW1`. The range inclusively
  retains every published key between its endpoints without interpolating absent
  numeric gameweeks; it may cross the season boundary only when those endpoints explicitly show
  that scope. Forecast GWs still control only future fixtures and xP. Cross-season rows join on
  permanent player `code`, every DGW fixture leg is retained, and no player receives individual
  backfill outside the shared selected range. The
  six overlapping threshold-probability columns are removed from this dense table and remain
  available in Player analytics. The observed season/GW scope is displayed once above compact
  stat headers instead of being repeated inside `App`. A dedicated sortable
  `xP GW{Forecast From}` column appears immediately after `Pts` and defaults descending for quick
  starter/bench review. At the run's fixed start/all-venue scope it selects the exact published
  cumulative endpoint; shifted or venue-filtered scopes strictly sum complete published fixture
  xP for that GW. DGW legs are all included, a true blank is zero, and null/incomplete evidence
  remains unavailable and sorts last; availability is still a separate overlay. Browser arithmetic
  is limited to summing published observed
  components and forming the documented descriptive per-90 ratios from matching published
  measured-minute denominators. The table also shows observed xGI immediately after xA as the
  display-only xG + xA sum, unavailable unless both aggregates are measured; this adds no forecast
  field or read-model schema member. The Players display exposes BPS/App as the selected-range BPS
  total divided by appearances; all played DGW legs count, DNPs do not, and incomplete appeared-row
  evidence stays unavailable. Normalized actuals retain their fixture-grain BPS scores, the legacy
  form BPS measure remains a total, and BPS/App adds no read-model field. Insight request schema v4
  carries exact `actual_season_from` / `actual_gw_from` and `actual_season_to` / `actual_gw_to`
  endpoints. Both endpoints must be exact members of the page-wide published period set; the
  selected scope is their inclusive chronological slice, so absent numeric GWs are not invented.
  Acceptance requires archive/
  live duplicate rejection, finalized-ledger gating, complete-GW filtering, NULL preservation,
  range/DGW aggregation tests, a schema-v7 atomic republish, and visual verification.

  The local semantic-v4/schema-v6 refresh completed after commit `e234197`: the BI generation hash
  is `1cf46ab421320595df4c4246feeb98ac27a4f3531124efdbfec2e063fbad363e` and the dashboard
  generation hash is `4cdcd729077cfa66102a4b2581fb2c8852d61b3bd8bb780ccfac0cc43d71676c`.
  Both formal platform vintages attach 610 finalized GW1 fixture rows, and the other recorded
  vintages attach 587-609 rows according to their exact selectable-player registry; every range is
  GW1-GW1 with no prior-season substitution. Contract, point-in-time, UI, build, lint, type, and
  HTTP smoke checks pass. An interactive visual click-through remains pending because no
  controllable browser was connected to the implementation session.

  The schema-v7 refresh completed locally on 2026-08-27 from that same immutable semantic-v4
  export. Its dashboard content hash is
  `cb7759b13484ec939a040b98ed75fd39f2faa5e0faa5db28a41c14ef7338d2c2`; both
  `dashboard/public/data` and `dashboard/dist/data` carry the identical validated generation.
  `player_actuals.json` contains 1,078 season/player records and 17,692 finalized fixture rows:
  468 / 17,082 for 2025-26 and 610 / 610 for 2026-27. No older season is transported. The
  selected GW2-6 forecast still marks Horníček (`code=470551`) as a cold start, so the default
  Player analytics reporting scope excludes him without altering his forecast. Automated DOM,
  contract, build, lint, and HTTP checks cover the implementation; a responsive visual
  click-through remains pending because the browser-control runtime reported no connected browser.

  Schema v7 additionally publishes the forecast-owned `cold_start_player` flag and defaults Player
  analytics to Established evidence, with an explicit Include cold starts control. This is a
  reporting-only risk screen. The discovered live/archive history-path inconsistency and any
  proposed three-appearance probability bridge remain separate forecast work; neither is silently
  folded into this dashboard change.

- **Historical rolling latest-five-GW expanded rows (implemented development-only 2026-08-28;
  season-boundary correction 2026-08-28).** The main Players aggregate remains bound to its
  selectable inclusive Season–GW endpoint range. Expansion is an independent fixed rolling history
  over normalized `player_actuals.json`: it takes the page-wide set of the latest five distinct season-qualified
  finalized GW labels across the forecast season and its immediate predecessor, preserves every
  double-gameweek fixture leg, labels rows by season/GW, and orders them newest first. At 2026-27
  GW1 this means 2026-27 GW1 plus 2025-26 GW38 through GW35. Cross-season membership uses permanent
  player `code`; newcomers without predecessor rows remain shorter. It exposes only observed
  fixture metrics:
  `Match` (season/GW, fixture-time Club, and kickoff date), `Opp (H/A)`, minutes/start, goals,
  assists, xG, xA, fail-closed display xGI, clean sheets, on-pitch goals conceded, saves, raw DC
  actions, xGC, bonus, raw BPS, and points. The shared Next GW table retains the future fixture/xP
  drill-down; Players never substitutes it into historical detail.

  Dashboard schema v9 extends each normalized player-actual fixture with `team_code`,
  `team_short_name`, `opponent_team_code`, `opponent_short_name`, and `was_home`. These are the
  fixture-time identities already owned by BI semantic v5: the publisher resolves each club through
  `dim_team_season` on `(season, team_id)`, reconciles fixture side, venue, gameweek, and permanent
  codes to `dim_fixture`, and uses the fixture dimension's kickoff as the canonical presentation
  timestamp. It never uses the selected forecast player's current club,
  season-end membership, a bare season-scoped id, or a name join. Transfers therefore retain their
  actual club for each leg; fixture ids reused in another season cannot collide; prior-season rows
  involving a now-relegated club remain labelable; and promoted players without prior Premier
  League evidence stay shorter. This dashboard-only transport does not change BI semantic contract
  v5 or insight request schema v4.

  BI semantic contract v5 adds `fact_team_fixture_actual` at
  `(season, fixture, team_id)` grain with direct official GF/GA and nullable source-row xG/xGC,
  summed BPS, and raw DC actions. Present-row finality and measurement are checked, but these
  aggregates do not claim an independent source-roster completeness witness. Dashboard schema v8
  adds normalized `team_actuals.json` at
  `(season, team_code)` grain, bounded to published forecast seasons and their immediate
  predecessors. Fixture Matrix's expanded-history scope defaults to the same page-wide rolling
  latest-five season-qualified window across the forecast season and its immediate predecessor,
  newest first, while explicit single-season options remain available and every DGW leg is
  retained. Cross-season club membership uses permanent `team_code`; promoted clubs without prior-
  Premier-League rows remain
  shorter rather than inheriting a relegated club through season-scoped `team_id`. Unavailable
  present-row components remain NULL, and the future matrix chips remain summary context rather
  than expanded forecast detail.

  Possession and shot counts remain absent. Official FPL/archive sources do not publish them, and
  the repository's existing FBref integration is only an unpopulated operator-vendored defensive-
  actions CSV with no possession/shot contract. No proxy from xG, threat, saves, or another measure
  is permitted. Adding either field later requires a separately approved, licensed, versioned
  source and provenance contract.

  Acceptance requires semantic-v5 grain/join/NULL/overlap checks, complete-GW and finalized-ledger
  gating, schema-v9 normalized-file validation and fixture-identity reconciliation,
  immediate-predecessor bounds, season-qualified
  current-to-predecessor rolling-window tests, permanent-identity/no-substitution checks,
  DGW/latest-five ordering tests, route-specific player detail tests, Fixture Matrix loading/error/
  empty states, public-package inclusion, atomic BI/static republish, and responsive visual
  verification. This reporting change does not alter a forecast, model default, frozen evaluation,
  optimizer input, or monitoring score.

- **Completed-match provisional preview and daily capture (implemented development-only
  2026-09-01; local refresh evidence still pending).** The append-only
  `.github/workflows/provisional-player-history.yml` capture runs at 01:00 UTC / 08:00 Bangkok with
  a 05:00 UTC / 12:00 Bangkok recovery pass under the shared `api-snapshot` concurrency group. It
  starts only after a scored fixture leg is marked `finished_provisional=true` or `finished=true`.
  The 08:00 pass may no-op on a cheap signal covering every scored fixture plus latest-GW
  event-live; the 12:00 recovery and every manual dispatch always perform the full supported-player
  element-summary sweep and no-op only on identical canonical content. Endpoint-specific response
  bounds, the first-kickoff/
  first-deadline rollover guard, same-signal before/after checks, and a minimum 20 aggregate history
  rows per eligible fixture fail closed before a timestamp/content-identified package is written under
  `snapshots/player-history-provisional/<season>/gw-<gw>/` without overwriting an earlier capture.
  The existing later finalized workflow and outcome-attachment policy remain unchanged.

  BI semantic contract v6 adds the separate run-independent
  `fact_provisional_player_fixture_observation` and
  `fact_provisional_team_fixture_observation` facts. Export eligibility is deliberately narrower
  than a score alone: only the latest complete player-history capture's same-capture fixture rows
  with `finished_provisional=true OR finished=true`, non-null schedule identity, and both scores are
  considered. They remain separate provisional-display evidence until any player/team archive or
  immutable-ledger final evidence exists, when one shared anti-join removes the whole fixture from
  both provisional facts atomically. Completeness requires exactly one bootstrap, one fixtures
  payload, and one element-summary for every supported bootstrap player (element types 1-4). Player/team/fixture
  identity and `observed_at` must agree, team sides must be reciprocal, and provisional rows may
  not overlap finalized facts at the same grain.

  Dashboard generation keeps the ten established files at schema v9 and additively publishes
  `player_provisional_actuals.json` and `team_provisional_actuals.json` under independent schema v1
  envelopes with one `captured_at`. Only Players and Fixture Matrix consume them. The browser marks
  provisional periods/rows, requires identity agreement before a finalized fixture supersedes a
  provisional fixture, and keeps provisional raw `total_points_as_recorded` distinct from finalized
  `points_under_rules_2026_27`. A selected provisional Players range disables the optional language
  renderer but retains deterministic facts. Neither prediction-versus-actual route, either
  append-only ledger, or any monitoring score accepts provisional evidence.

  A future manually reviewed sanitized dashboard-data ZIP includes both provisional files so its
  validated manifest remains complete. That is not automatic publication: the public Pages site
  remains pinned to an owner-reviewed immutable release through `public-data-release.json`, and a
  local snapshot load/read-model refresh cannot move that pin. No provisional row count, manifest
  hash, or local dashboard freshness claim is recorded here until the controlled local refresh
  produces that evidence.

- measure and contract per-GW availability semantics;
- design future price-change and future selling-value handling;
- monitor recorded real-deadline forecasts against finalized outcomes;
- decide whether a newly named positional attacking-allocation candidate is warranted;
- the price-informed starter prior is **built** for cold starts (held-out MAE 0.3835 ->
  0.3086, t = -5.57) together with a club-relative cap; the open half is the ownership
  term, which must be fitted on history and scored once on 2026/27 GW2 onward -- the live
  GW1 window was spent comparing encodings and can no longer validate it;
- revisit cards only if a real decision is shown to turn on their measured margin;
- **Manager-team transfer workflow (implemented development-only 2026-08-23; acceptance still
  pending).** The public picks endpoint was live-measured not to contain purchase/selling values.
  `fpl.ingest.manager_team` therefore supports GW1-started entries only, starts from committed GW1
  launch prices, maps season-scoped elements to stable codes, replays public
  permanent transfers and chips, reconciles the latest revealed squad and bank, and derives
  purchase/selling values plus remaining free transfers. It emits an atomic, immutable private
  capture bound to payload, snapshot, and full selectable-player registry hashes. Later starters,
  missing evidence, or a capture/forecast registry mismatch fail closed rather than inventing
  prices. This is public-entry reconstruction, not authenticated My Team state.
- The manager optimizer starts from that exact 15, allows moves in the first forecast gameweek,
  carries cash and per-player sale basis, and charges only new moves beyond the effective
  remaining FT count at four points each. Already-incurred hits are recorded as sunk. A 0-5 FT
  override is explicit provenance. Up to five owned locks mean never sell; an owned exclusion is
  forced out in the first forecast gameweek and a non-owned exclusion is never bought. Future
  prices remain frozen, and the bounded transfer search makes no global-optimality claim.
- The local Plan Server accepts an explicit `--forecast` and adds strict `/manager-team` and
  `/manager-team/capture`, member-only `/manager-team/members` and
  `/manager-team/members/capture`, and `/manager-plan` beside the existing `/plan`. Plan Builder
  and the manager optimizer retain exact full selectable-registry binding. Players and Squad Draft
  use only the member endpoints, which tolerate unrelated registry additions after exact
  reconciliation of all 15 captured players against forecast gameweek, identity, position, club,
  and price. Plan Builder shows
  HOLD/OUT/IN, FT, cash, sunk/new hits, and offers both the optimized and captured-current-team
  Squad Draft handoffs. Squad Draft also has a direct manager-ID capture shortcut that preserves
  the old draft on failure. Manager captures/context stay out of shared read models; the public
  pack removes user-custom plans and rejects manager IDs, current squads, bank, and selling values.
  Hosted authentication, ownership verification, accounts/entitlements, and a selections log
  remain unimplemented. See `docs/manager-team-suggestions.md` and `dashboard/README.md`.
- **Players private manager-squad filter (implemented development-only 2026-08-27).** The local
  Players route uses `/manager-team/members` to verify an exact 15-player scope by stable code against
  the selected forecast's planning GW, position, club identity, and deadline price. It composes with
  every existing player/forecast/actual filter, preserves the active table atomically on fetch or
  mapping failure, resets pagination after narrowing, clears on forecast-vintage changes, and
  places the complete filter panel immediately before the scrollable player table. League-wide
  additions outside the captured squad do not block this display filter; optimizer routes remain
  full-registry fail-closed.
  Hosted static builds cannot call it. Deterministic facts follow the visible scope, while the
  optional renderer is disabled so no manager or capture field can enter the public insight
  contract. Acceptance requires focused success/intersection/reset/failure/partial-mapping/privacy
  tests, full frontend tests/build/lint, local Plan Server HTTP verification, and an interactive
  click-through when a controllable browser is connected.
- **Players searchable multi-select filters (implemented development-only 2026-08-28).** The
  Players table adds a stable-code searchable Player selector and multi-select Position/permanent-
  team-code selectors. Empty means all, values are ORed within one selector and ANDed across
  selectors, all other filters, and My squad. Options remain anchored to the complete active
  vintage; vintage changes reconcile unavailable player/team codes, and global reset clears every
  selection. This is a page-local UI change: no read model, optimizer registry, or shared decision-
  page selector changes. Insight request schema v4 remains scalar, so name-restricted and multi-
  position/team scopes are deterministic-only rather than being broadened silently; singleton
  Position/Team scopes retain exact renderer eligibility. Acceptance requires search/reset/OR/AND/
  My-squad/vintage/accessibility tests, full frontend tests/build/lint, and an interactive
  click-through when a controllable browser is connected.

These were not GW1 blockers. The post-deadline implementation remains separate and changes no
frozen forecast or evaluation.

## P3: V2 — the football-first prediction engine

Status: Milestones A-I implemented development-only, 2026-09-04. Milestone J deferred.
Authoritative description: `docs/v2-architecture.md`. This section is delivery sequencing;
`AGENTS.md` owns the correctness and model-history record.

**P3 does not displace P0 or P2.5, and it changes no default.** V1 is untouched, no frozen
evaluation was re-run or re-judged, and both V2 candidates failed their pre-registered gates and
are left as committed.

### Delivered

| milestone | content | state |
| --- | --- | --- |
| A | SDP source, raw capture, measured fixture-identity audit | implemented |
| B | typed staging, provider-tagged V2 team-match mart, coverage reporting | implemented |
| C | point-in-time V2 access, tactical rolling marts | implemented |
| D | `FixtureEnvironment` contract + multi-signal football engine | implemented |
| E | GK Saves V2 | implemented, **evaluated, refuted** |
| F | DC environment V2 | implemented, **evaluated**: gate missed, mechanism confirmed |
| G | composer integration via `component_engine_v2` | implemented |
| H | V2 prospective football forecast (`prospective_environment_v2`) | implemented |
| I | optimizer compatibility | free — the composer input type is unchanged |
| J | dashboard / analytics exposure of V2 team profiles | **not started** |

### Measured outcome, and what it forbids

* Harness validation: the incumbent scores **1.50030** under the V2 harness against Phase 1's
  frozen **1.5003**, on 181 folds and 3,640 predictions in both.
* Team environment: **+0.2867%** against a 1% gate, with 2021-22 regressing **-0.21%**. Failed.
* GK Saves V2: pooled **+0.168%** log, but per season **+1.37%, +2.28%, -1.10%, -1.24%, -0.27%**.
  Failed, and refuted in the well-informed regime.
* DC V2: **-2.18%** log against a 1% gate, so it fails -- but its pre-registered mechanism
  test passes, with the transferred-player slice at **+11.42%** log / **+12.46%** Brier and AUC
  0.770 -> 0.923. The failure is a calibration defect with a measured cause: DC counts are
  ~2x over-dispersed relative to a Poisson (variance/mean 1.88 / 2.12 / 1.61 by position), so
  the Poisson threshold conversion under-predicts, worst for midfielders -- which is V2's worst
  slice. See `docs/v2-dc-development.md`.
* None may be retuned or re-run. `results/v2_team_environment_development.json` and
  `results/v2_dc_development.json` are immutable.

### Remaining work, in dependency order

1. **Capture SDP where egress exists.** Nothing above tested a single SDP metric, because the
   provider has never been reachable. Run `python -m fpl.jobs.audit_pl_sdp --probe` on the owner's
   machine or via `.github/workflows/pl-sdp-capture.yml`, record `pl_sdp.season_ids`, backfill,
   then `--stage`. **Read the three coverage-first reports before fitting anything.**
2. **Verify the metric dictionary against a real payload.** Every provider field name currently
   carries `verified_semantics: false`. Promote only what the reconciliation corroborates; extend
   the dictionary from `unmapped_provider_fields` rather than guessing again.
3. **Then, and only then, run ablation rungs C and D.** They are currently bit-identical to rung B
   and are untested, not null. This is the single highest-value remaining experiment: it is the
   only one that can say whether shot volume and territory carry information beyond xG.
4. **An over-dispersed DC threshold model**, as a separately named candidate with its own
   amendment. This is the best-evidenced next model experiment in the repository: the
   allocation is already shown to rank well (AUC +13.5%) and the defect is isolated to the
   count distribution. The dispersion parameter must be fitted inside each fold -- the measured
   variance/mean figures in `AGENTS.md` come from the evaluation population and using them
   directly would be leakage.
5. **Milestone J** — expose the V2 team profiles (attack/defence quality, dominance, pressing,
   low-block tendency, directness, width, duel profile) through the semantic export and dashboard.
   Deferred deliberately: publishing a tactical profile derived from a provider whose field
   semantics are unverified would put an unbacked claim in front of a user.

### Explicitly out of scope until a gate is cleared

Wiring V2 into `jobs/prospective_points_v1.py`, changing the prospective default, or presenting a
V2 number as a recommendation. `jobs/prospective_environment_v2.py` exists precisely so the
football forecast is available for analysis without any decision path consuming an ungated
candidate.

## Required gate and handoff

Run jobs sequentially. Before any implementation handoff:

```powershell
.\.venv\Scripts\pytest.exe -q
.\.venv\Scripts\ruff.exe check src tests
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\mypy.exe src
Push-Location dashboard
npm test
npm run build
npm run lint
Pop-Location
```

Before any 08-20 or 08-21 artifact run, also require:

```powershell
git status --porcelain
git rev-list --left-right --count origin/main...HEAD
```

The first command must emit nothing and the second must emit `0 0`. Record the exact Python and
dashboard gate results; historical green runs are evidence, not a replacement for this check.

Report changed files, tests and exact results, output schemas with one sample record, measured
constants for any non-trivial policy, unresolved assumptions, generated run IDs/hashes, and the
chosen GW1 squad/lineup/captain when the final run is authorized. Commit and push only when the
owner explicitly requests it.
