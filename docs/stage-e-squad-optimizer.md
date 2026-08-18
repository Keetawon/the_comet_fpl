# Stage E squad optimizer

Status: implemented, development-only. Its output is a deterministic decision aid over a
development-only forecast artifact, not a validated FPL recommendation.

## Post-implementation review status

The saved GW1-5 result reconciles: every squad and formation is legal, transfer/free-transfer/hit
accounting is exact, and the reported 330.4045 expected points equals the five weekly lineup and
captain totals with zero hits.

The no-transfer pruning defect is now **fixed**. `_successor_squads` seeded the current squad at an
immediate improvement of 0.0, sorted every proposal by descending improvement, and truncated to
`transition_limit_per_state`. Because any swap with a positive immediate improvement sorts above the
hold action, and for a 15-man squad against a large candidate pool the number of positive-improvement
swaps far exceeds the limit (200 in the shipped config), the hold action was truncated away
essentially always -- so the planner was **forced to churn every gameweek regardless of the hit
cost**, unable to represent banking a transfer or avoiding a -4. This is stronger than "can remove the
legal no-transfer action": in practice it removed it whenever any transfer improved. The fix reserves
the current squad in every successor set so it survives truncation regardless of ranking; the returned
set may now be `limit + 1`, and the single caller iterates it, mapping a returned current squad to a
zero-transfer, zero-hit week. Regression tests cover the reservation directly (failing-test-first;
across transfer depths 1-2, transition limits, and candidate-pool sizes; and the control where hold is
already the best proposal) and end to end (with no free transfer available, a +0.5 upgrade cannot
repay its -4 hit, and the plan now holds instead of being forced to churn).

The truncation can still drop other legal-but-not-immediately-improving actions -- a transfer that is
weak now but sets up a future gameweek -- but that is the documented bounded-search approximation, not
a defect: the no-transfer case is categorically different because holding is the canonical "do
nothing" baseline that must always be representable, not an optimality-within-bounds question.

The optimiser-provenance gap is now **closed**: `--output` writes a durable, immutable,
provenance-bearing artifact with its own Git/worktree, squad-config, search-policy, and solver
provenance, separate from the forecast's (see [Durable optimizer artifact](#durable-optimizer-artifact)
below). Two operational gaps remain open before the plan can be described as operational:

1. the current `chance_of_playing_next_round` overlay is repeated across the whole forecast horizon,
   which needs a measured per-GW policy; and
2. all future affordability checks use the deadline's static `now_cost`; price changes and FPL
   selling values are not modelled.

## Input boundary

The optimizer reads only the versioned prospective-points JSONL artifact documented in
`docs/prospective-points-artifact.md`. It has no DuckDB dependency or outcome access. Stable player
`code` is the identity; `team_id` is used only inside the artifact's single season and `team_code`
is retained for reporting.

## Verified 2026/27 rules

`config/squad_2026_27.yaml` records the exact live rules and their provenance. The captured official
bootstrap payload confirms a 15-player squad, a 100.0m budget represented as 1000 tenths, at most
three players per club, 2 GK / 5 DEF / 5 MID / 3 FWD, 11 starters, one bench goalkeeper, three
outfield substitutes, and the formation bounds 1 GK / 3-5 DEF / 2-5 MID / 1-3 FWD. The official
help sources confirm double captain points, vice-captain fallback, one new free transfer after each
deadline, a five-transfer bank cap, and a four-point cost for each transfer beyond those available.
The captured payload also sets the live per-gameweek transfer cap to 20.

All of these squad and transfer rules are verified; none is inferred. The broader scoring config
still has two explicitly unexercised replay edge cases, so this work does not describe the entire
ruleset as fully validated.

## Expected-value objective and constraints

The exact initial-squad ILP maximizes, over GW1-5:

```text
sum(availability-adjusted ExP for each starting XI)
+ sum((captain multiplier - 1) * captain availability-adjusted ExP)
```

It enforces the budget, exact squad position counts, three-per-club cap, 11-player XI, legal
formation, one captain, and captain-in-XI constraints. The current bench simplification is explicit:
bench points and autosub probability are excluded from the objective. The solver still emits one
bench goalkeeper, a deterministic outfield bench order, captain, and vice-captain. Vice fallback is
not assigned an expected value. Ownership is reported but does not affect selection.

The same deadline-known `now_cost` is used for every gameweek in the horizon. This is a frozen-price
planning assumption, not a forecast of future affordability. The plan must be regenerated at each
deadline; it does not model future market prices or selling-value profit rules.

### Optional bench-appearance gate (`--min-bench-appearance P`)

Because bench points are absent from the objective, the tie-break otherwise fills the bench with
the cheapest legal filler, who may be a player who never plays -- useless as a rotation option.
`--min-bench-appearance P` (default `0.0`, disabled, the historical behaviour) requires every
OUTFIELD player benched in any planned gameweek to show an appearance probability of at least
`P`. It is one linear constraint per (player, gameweek) in the ILP
(`bound >= P * (in_squad - starts)`, since `in_squad - starts` is exactly the benched
indicator), and the transfer planner rejects any successor whose lineup for a planned gameweek
benches below the gate, so a later transfer cannot reintroduce dead bench weight.

The measure is `1 - P(0 points)` read from the stored full-points distribution, scaled by the
availability overlay -- a conservative LOWER bound on appearance probability, because a
non-appearance lands entirely in the zero-points cell while a player can also appear and score
nothing. It is derived from the immutable artifact rows, so already-recorded vintages can be
re-optimized with the gate without re-forecasting. Two exemptions are deliberate: the bench
GOALKEEPER is exempt (a backup keeper plays only on an unforecastable starter injury, so no
meaningful threshold is attainable and gating it would make every squad illegal), and a player
may still be selected with a sub-threshold bound if he STARTS every planned gameweek. A
threshold no legal squad can satisfy fails closed as an infeasibility error naming the
threshold. The value is provenance: recorded in the artifact's `search_policy`, bound into the
`run_id`, and documented in the decision's assumptions.

### Locked must-keep players (`--lock CODE`, at most five)

`--lock CODE` (repeatable; the five-lock cap is an owner product rule, not a rules-engine
limit) pins a player into the squad: the ILP forces him in and the transfer planner never
ships him out, so the optimizer assigns every remaining quota around the owner's must-keep
players. Locks compose with the bench gate rather than overriding it -- a locked player who
cannot clear `min_bench_appearance` is exempt because the explicit must-keep instruction outranks
the rotation heuristic. A locked set that makes no legal squad possible (position quotas, club
cap, budget) fails closed naming the locks. Locked codes are provenance: recorded in
`search_policy.locked_codes`, bound into the `run_id`, and listed by name in the decision's
assumptions.

### Excluded players (`--exclude CODE`, at most fifteen)

`--exclude CODE` is repeatable and uses stable player `code`. An excluded player is removed from
the initial ILP population and the bounded transfer candidate pool, so he cannot appear in the
initial squad or enter in any later gameweek. A player cannot be both locked and excluded;
unknown or unpriced codes, overlaps, and more than fifteen exclusions fail closed. Exclusions are
recorded in `search_policy.excluded_codes`, enter the `run_id` only when non-empty (preserving old
v1 artifact identities), and are listed by name in the assumptions. Interactive runs also record
`search_policy.plan_origin=user_custom`; current platform jobs record `platform` explicitly.
Artifacts written before origin provenance was introduced read it as legacy `null`, preserving
their original run IDs. The dashboard then infers a constrained legacy plan as user-custom and
normalises the emitted read-model policy; the durable artifact itself is never rewritten.

### Manager free-transfer state

`plan_transfers(initial_banked_free_transfers=B)` seeds the DP with a manager's carried free
transfers instead of the fresh-season zero, bounded by the rules' bank cap. The hit arithmetic
itself is unchanged and was always exact: each gameweek grants one free transfer, unused
transfers bank up to the cap, and every transfer beyond the grant costs the configured
-4 hit. This parameter is what a manager-team suggestion (see
`docs/manager-team-suggestions.md`) passes after deriving the manager's banked state from
their transfer history.

PuLP/CBC is the one added production dependency. It gives an auditable exact binary linear solve for
the fixed-squad selection problem, remains small relative to the existing scientific stack, and
avoids maintaining a custom combinatorial solver. CBC uses its deterministic single-process default
and a fixed random seed. Bench points remain absent from the primary objective; among exactly tied
primary optima, a second solve chooses minimum squad cost and then stable code rank so the full
15-player output is reproducible. One override is ordered before price in that tie-break: a player
the availability overlay rules out (multiplier 0 in any planned gameweek, e.g. injured with a 0%
chance) ranks behind every available filler at any price -- otherwise the cheapest injured player
is the tie-break's favourite bench filler and the plan suggests someone who can never come on
(measured on the 2026-08-16 preliminary pack: Heaton, status `i`/chance 0, was the default plan's
bench goalkeeper in GW1-2). A second ordered preference follows price: among **equally-priced**
fillers the tie-break prefers the **most-selected players** (deadline bootstrap ownership) --
crowd vetting that a cheap pick is a real Premier League rotation option rather than a
never-playing squad player. Price still dominates (a cheaper unpopular filler always beats a
costlier popular one); unmeasured ownership carries no preference; the stable code rank still
breaks exact ties so solves stay reproducible.

## Transfers and optimality limits

After the exact fixed-squad solve, a deterministic bounded dynamic program plans transfers through
the horizon. Before each post-GW1 deadline it credits the configured free transfer, capped at five;
unused transfers remain banked and each excess transfer subtracts four points. Every visited squad
is legal and every visited lineup/captain choice is exact.

The transfer path is deliberately bounded for predictable local runtime. Candidate players are the
initial squad plus the top configured horizon utilities per position. Each state generates zero,
one, or two same-position replacements, ranks them by current-GW player-utility improvement, retains
at most 200 ranked legal transitions plus the reserved zero-transfer action, and keeps a 30-state
beam. Reserving the hold action prevents pruning from forcing a transfer or hit when neither is
repaid. The reported transfer plan remains exact only within visited states; it is not a global
optimality claim outside the configured candidate-pool, depth, transition, and beam limits. These
limits live in configuration rather than Python.

This bound was selected by timing the same point-in-time GW1-5 artifact before wiring it. A 100×20
search finished in 22.6 seconds but lost 5.14 expected points relative to the broad reference; the
200×30 search finished in 49.4 seconds and was only 0.09 points (0.027%) lower. The 300×50 search
was operationally unstable on repetition, exceeding 12 minutes, so the smaller stable bound is the
documented production-run policy. These figures measure search approximation, not forecast lift.

## Optional distributional-risk diagnostic

`--risk-lambda L` changes each player-gameweek utility to:

```text
availability-adjusted mean - L * availability_multiplier * E[(mean - points)+]
```

The downside term is computed from the complete stored probability distribution. `L=0` is exactly
the expected-value objective. A positive value is only a sensitivity analysis until prospective
evidence shows it improves an owner-defined utility; a changed squad is not evidence that the
risk-aware version is better.

## Durable optimizer artifact

`--output PATH` writes an immutable, provenance-bearing record of the decision, defined and validated
in `src/fpl/artifacts/optimizer_plan.py` and kept out of the thin job. It is the optimiser analogue of
the prospective-points artifact: the artifact module owns the schema, serialisation, run-id
derivation, and atomic write; the job discovers provenance and maps the optimiser's domain objects
into the typed records.

- **Schema.** `schema = "fpl.optimizer-plan"`, `schema_version = 1`, and an explicit development-only
  `status`. Serialised as canonical JSON (sorted keys, `allow_nan=False`); every float field rejects
  non-finite values at construction.
- **Run identity and decision integrity.** `decision_sha256` covers the embedded legality rules,
  initial squad, every weekly squad/XI/captain/vice/bench/transfer, aggregate points, and assumptions.
  `run_id` then covers that digest plus the forecast/rules hashes, optimiser commit, complete search
  policy, and complete PuLP/CBC identity including discovered versions, options, seed, and status.
  Only relocatable paths and wall-clock time are excluded. Both hashes are re-derived on read.
- **Provenance.** The input forecast (path, SHA-256, schema/version, `as_of`, horizon, forecast
  commit); the optimiser's own Git HEAD and clean-worktree state; the squad-rules path, contract
  version, and file SHA-256; the solver name, required PuLP/CBC versions, deterministic options and
  seed, and solve status; and the complete search policy
  (candidate pool, transfer depth, transition limit, beam width, free-transfer state, `risk_lambda`,
  search method, and declared optimality scope).
- **Solver discovery.** PuLP's installed-distribution version and imported-module version must
  agree when both are available (the module version is accepted only when distribution metadata is
  unavailable). CBC must print an explicit `Version: ...` line from its actual configured binary;
  the job retries the two supported version flags for transient Windows first-launch failures, but
  never substitutes a default or an inferred version. Any unresolved or conflicting identity still
  refuses durable artifact output. The local plan server performs the same preflight at startup and
  exposes its Python executable/prefix and the two verified versions in `GET /status`; the
  optimizer child independently repeats discovery before writing an artifact.
- **Decision and offline legality.** The chosen 15-player squad and cost, plus every gameweek's
  post-transfer 15, XI, captain, vice-captain, bench goalkeeper, ordered bench, transfers,
  free-transfer state, hits, and explicit assumptions. Reading validates budget, club cap, position
  quotas, formation, lineup/bench partition, captaincy, transfer deltas/state, horizon, and aggregate
  point reconciliation without loading DuckDB or mutable config.
- **Provenance race safety.** The job hashes and parses the same in-memory forecast/rules bytes under
  a clean HEAD, rechecks those bytes, HEAD, and worktree before publication, and checks again after
  publication. Drift removes the just-written output and fails closed.
- **Atomicity and immutability.** The write flushes a unique sibling temporary file and atomically
  creates the destination as a hard link. That filesystem create-if-absent operation gives exactly
  one winner under concurrent writes; it never relies on exists followed by replace. An existing
  destination, incomplete solver identity, dirty worktree, unresolved commit, or provenance drift
  refuses output. Put output outside the repository so it does not dirty the checkout.

## Run

First create the forecast artifact using the sequential recipe in the artifact document, then run:

```powershell
# stdout plan only (unchanged behaviour):
.\.venv\Scripts\python.exe -m fpl.jobs.optimize_squad D:/tmp/prospective-points-2026-27-gw1-5.jsonl
# also write the immutable, provenance-bearing optimizer artifact:
.\.venv\Scripts\python.exe -m fpl.jobs.optimize_squad D:/tmp/prospective-points-2026-27-gw1-5.jsonl --output D:/tmp/optimizer-plan-default.json
# risk sensitivity analysis (clearly labelled; never replaces the EV result):
.\.venv\Scripts\python.exe -m fpl.jobs.optimize_squad D:/tmp/prospective-points-2026-27-gw1-5.jsonl --risk-lambda 0.5 --output D:/tmp/optimizer-plan-risk.json
```

A successful command prints canonical JSON to stdout containing artifact and rule provenance, the
initial 15-player squad, each gameweek's XI/captain/vice/bench, transfers, free-transfer state, hit
cost, expected points, risk-adjusted objective, and every simplifying assumption. When `--output` is
supplied it additionally writes the durable artifact described above.

Offline tests use synthetic, hand-computable artifacts. They pin squad, captain, budget and club-cap
constraints, distribution-driven risk sensitivity, and cases where a four-point hit is and is not
worth taking. `tests/test_optimizer_artifact.py` also pins decision tamper rejection, offline
legality, complete behavior identity, concurrent no-clobber, failure cleanup, and pre/postflight
drift suppression.
