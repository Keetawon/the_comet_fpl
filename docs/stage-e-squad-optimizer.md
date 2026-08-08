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

Three operational gaps remain open before the plan can be described as operational:

1. the current `chance_of_playing_next_round` overlay is repeated across the whole forecast horizon,
   which needs a measured per-GW policy;
2. optimiser output needs its own Git/worktree, squad-config, search-policy, and solver provenance,
   separately from forecast provenance; and
3. all future affordability checks use the deadline's static `now_cost`; price changes and FPL
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

PuLP/CBC is the one added production dependency. It gives an auditable exact binary linear solve for
the fixed-squad selection problem, remains small relative to the existing scientific stack, and
avoids maintaining a custom combinatorial solver. CBC uses its deterministic single-process default
and a fixed random seed. Bench points remain absent from the primary objective; among exactly tied
primary optima, a second solve chooses minimum squad cost and then stable code rank so the full
15-player output is reproducible.

## Transfers and optimality limits

After the exact fixed-squad solve, a deterministic bounded dynamic program plans transfers through
the horizon. Before each post-GW1 deadline it credits the configured free transfer, capped at five;
unused transfers remain banked and each excess transfer subtracts four points. Every visited squad
is legal and every visited lineup/captain choice is exact.

The transfer path is deliberately bounded for predictable local runtime. Candidate players are the
initial squad plus the top configured horizon utilities per position. Each state generates zero,
one, or two same-position replacements, ranks them by current-GW player-utility improvement, retains
at most 200 legal transitions, and keeps a 30-state beam. The current truncation does not reserve the
zero-transfer proposal, which is the confirmed defect above. Even after that is fixed, the reported
transfer plan is exact only within visited states; it is not a global optimality claim outside the
configured candidate-pool, depth, transition, and beam limits. These limits live in configuration
rather than Python.

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

## Run

First create the artifact using the sequential recipe in the artifact document, then run:

```powershell
.\.venv\Scripts\python.exe -m fpl.jobs.optimize_squad D:/tmp/prospective-points-2026-27-gw1-5.jsonl
.\.venv\Scripts\python.exe -m fpl.jobs.optimize_squad D:/tmp/prospective-points-2026-27-gw1-5.jsonl --risk-lambda 0.5
```

The command prints canonical JSON containing artifact and rule provenance, the initial 15-player
squad, each gameweek's XI/captain/vice/bench, transfers, free-transfer state, hit cost, expected
points, risk-adjusted objective, and every simplifying assumption.

Offline tests use synthetic, hand-computable artifacts. They pin squad, captain, budget and club-cap
constraints, distribution-driven risk sensitivity, and cases where a four-point hit is and is not
worth taking.
