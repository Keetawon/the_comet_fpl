# Manager-team transfer suggestions — design record

Status: **design only, not implemented** (owner direction 2026-08-17). Delivery slot: after
the 2026/27 GW1 deadline, as a P2 item (see `DEV-ROADMAP.md`). This document is the plan of
record for the wizard flow; nothing here changes a model, a frozen evaluation, or the GW1
decision path.

## 1. The user flow

A manager who already owns a team wants transfer suggestions for THEIR squad, not a fresh
15. The wizard flow:

1. **Identify** — the user supplies their FPL `manager_id` (the number in
   `fantasy.premierleague.com/entry/{manager_id}`).
2. **Import** — the system fetches the manager's current 15, their bank/squad value, and
   their transfer history, and maps every pick onto the stable player `code` used by the
   forecast artifacts.
3. **Constrain** — the user may **lock up to 5 players** they refuse to sell, set the
   **bench-appearance threshold** (already shipped: `--min-bench-appearance`), and the
   system derives their **banked free transfers** so hits are charged honestly: every
   transfer beyond the free grant costs the configured **-4 hit**.
4. **Suggest** — the optimizer runs the already-implemented exact fixed-squad lineup and the
   bounded transfer planner *from the manager's own squad as the initial state*, and emits
   per-gameweek: who to transfer out/in, whether each move is free or a -4 hit, the new
   XI/captain/vice/bench, and expected points before and after hits.
5. **Review** — the dashboard shows the current squad beside the suggested path with the
   EV delta, hits, and every caveat (frozen prices, GW1-only availability overlay,
   development-only status).

## 2. Why this is mostly already built

The hard parts exist and are tested:

| Wizard need | Already implemented |
| --- | --- |
| Exact lineup for a squad I do not choose | `exact_lineup` (Stage E fixed-squad solve) |
| "Who should I transfer?" | `plan_transfers` bounded DP over successor squads |
| -4 per transfer beyond the free grant | `hit_cost_points` + free-transfer banking, exact |
| "I have 2 banked free transfers" | `plan_transfers(initial_banked_free_transfers=B)` |
| "Keep my 5 favourite players" | `locked_codes` / `--lock` (never transferred out) |
| "Bench must be playable" | `--min-bench-appearance` gate, held across transfers |
| Auditable, immutable suggestions | the optimizer artifact contract |

What is genuinely NEW is the data boundary (manager fetch + mapping + value accounting) and
the UI. Nothing about the forecast, composer, or the frozen evaluation history changes.

## 3. Data boundary (the only new network surface)

Public FPL endpoints (subject to shape verification against a live capture before any code
is written — never promote an inferred shape to a confirmed fact):

- `GET /api/entry/{manager_id}/` — manager identity, current event, points. Used for
  validation ("is this a real manager?") and the wizard greeting.
- `GET /api/entry/{manager_id}/event/{event}/picks` — the 15 picks for an event. Each pick
  carries the season-scoped `element` id, the captaincy multiplier, and — critically —
  `purchase_price`/`selling_price`, which give the manager's REAL squad value and bank
  (the roadmap's "selling value not modelled" gap is only about *future* price moves; the
  current value is knowable). Before a first save for the current event, fall back to the
  latest completed event's picks as the current-squad proxy, labelled as such.
- `GET /api/entry/{manager_id}/transfers/` (+ `/history` for chips) — transfer history per
  event, used to DERIVE the banked free-transfer state (see §5).

Repository rules that bind this work:

- New network behaviour needs retries, bounded timeouts, shape validation, and offline tests
  with vendored fixtures (`AGENTS.md` working protocol). The `ingest` package owns this;
  nothing leaks into features/optimize.
- Event time and knowledge time differ: every manager capture is versioned with
  `captured_at`, hashed, and recorded in the emitted artifact's provenance. A suggestion is
  reproducible only against its captured inputs, exactly like the forecast artifacts.
- `element` (element_id) is season-scoped: picks map to the stable `code` through THIS
  season's bootstrap, which the daily snapshots already carry. Never join a bare
  `element_id` across seasons.
- The dashboard never gains a network client. The static app reads only published JSON read
  models (see §7).

## 4. Selling value and the budget check

`validate_squad` today checks `sum(now_cost) <= budget` — correct for a fresh squad at a
deadline, WRONG for a manager whose players have appreciated. The manager path must use:

```text
affordability: sum(selling_price of retained players) + sum(now_cost of incoming players)
               <= squad value (selling prices) + bank
```

with both `squad value` and `bank` read from the picks payload. Future price moves remain
unmodelled: every later-gameweek affordability statement stays a frozen-price scenario, as
the runbook already labels them.

## 5. Deriving banked free transfers (needs measurement, not assumption)

FPL grants one free transfer per gameweek (two for the first deadline of a restart season),
banks unused transfers up to the configured cap, and playing most chips (wildcard, free
hit) consumes/reset that state. The banked count for the NEXT deadline must be derived from
`/transfers` history by replaying: entitlement(event) -> carried(event+1), event by event,
with chip weeks identified from `/history`. **The exact chip semantics (does a wildcard week
bank or forfeit?) is a verification item against the official rules and a live manager's
known state before shipping** — record the answer in this file when measured. The derived
value feeds `plan_transfers(initial_banked_free_transfers=B)` and is displayed in the UI as
"you have N free transfers; this plan uses X free and Y hits (-4Y)".

## 6. Locks, threshold, and infeasibility UX

Locks (`--lock`, max 5) and the bench gate compose; the wizard must translate solver
failures into wizard language:

- locked player below the appearance threshold -> "he will start every gameweek" (the
  solver does this automatically) or suggest unlocking;
- locked set breaks position/club/budget legality -> name the conflicting locks;
- threshold no legal squad meets -> suggest lowering it.

The manager's own CURRENT squad is never "illegal" (the game enforces legality), but a
threshold applied to it can be unsatisfiable — the wizard must show which bench players
fail the gate BEFORE suggesting transfers, so the user understands why the planner holds or
hits.

## 7. Presentation boundary and the future hosted product

The dashboard is a static consumer and stays one. The local flow is:

```powershell
# thin job, wraps ingest + mapping + the existing optimizer
fpl.jobs.suggest_manager_transfers --manager-id 123456 `
    --lock 425746 --lock 152982 `
    --min-bench-appearance 0.25 `
    --output <manager-suggestion-artifact.json>     # immutable, provenance-bearing
# then a read-model emitter derives manager_plan.json for the dashboard "My team" page
```

The manager id and the wizard inputs are chosen at job time, not in the browser; the
dashboard page renders the published suggestion file.

**Future SaaS mode (login, one manager id per user, paid extra ids).** When this becomes a
hosted product, the boundary is already drawn for it: authentication, the one-manager-per-
account entitlement, and payments live in a NEW thin service layer around the domain
functions — never inside `src/fpl/optimize` or the artifact contracts. The service owns the
user-to-manager_id mapping; the suggestion artifact carries `manager_id`, the capture
hashes, and the policy (locks, threshold, banked transfers) so an audit can always answer
"whose team, whose data, which policy produced this". Nothing about the domain changes when
the paywall arrives; a free tier is simply "one manager_id per account".

## 8. Suggestion artifact (sketch)

Reuse the optimizer artifact contract, adding manager provenance: manager_id, entry/picks
and transfers capture ids + SHA-256 + captured_at, derived banked transfers with the
derivation's version, the used bootstrap capture (for element->code), plus the existing
forecast/rules/solver/policy blocks. Development-only status and the frozen-price caveat
remain mandatory fields. Immutability and no-clobber behavior are inherited unchanged.

## 9. Open items (each needs a measured answer before implementation)

1. Verify the live shape of `/entry/{id}/event/{n}/picks` (selling prices, bank) and
   `/entry/{id}/transfers` against a real manager; vendor fixtures for offline tests.
2. Measure the chip/free-transfer banking rules from the official rules page and one live
   manager with a known state.
3. Decide the candidate-pool policy for a manager search (the pool bound currently ranks by
   horizon utility; managers may want "only players I can afford now").
4. Post-deadline sequencing: this is P2 work and must not displace the GW1 decision pack or
   the BI MVP.
