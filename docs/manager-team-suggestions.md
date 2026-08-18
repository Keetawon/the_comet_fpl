# Manager-team transfer suggestions — design record

Status: **wizard v2 shipped on the dashboard (Plan builder page) 2026-08-18** — the
fresh-squad path now keeps user-specific results on this page, supports up to five green locks
and fifteen red exclusions through the real optimizer, and keeps the formal platform suggestion
separate on Next GW. The manager_id import, the selections-log
backend, and the hosted mode remain design-only, delivery after the 2026/27 GW1 deadline as
P2 items (see `DEV-ROADMAP.md`). Nothing here changes a model, a frozen evaluation, or the
GW1 decision path. The owner confirmed the wizard is END-USER-FACING frontend, not an owner
tool: its language, guards, and error messages are written for users.

## 1. The wizard flow (owner sketch 2026-08-17, refined)

The owner's sketch: *have own team? (manager_id → read team) or not → pick up to 5 locked
players and exclude up to 15 avoided players (shared search + filters; warn when the money left
or remaining population cannot complete a legal squad; rotation threshold here too) → confirm
(own team shown / suggestion shown + locks + exclusions + threshold) →
next → optimize under the conditions → summary.* The refinement below keeps that shape and
fixes the three things the optimizer's actual contract forces: (a) locks mean "must include"
on the fresh path but "never sell" on the own-team path; (b) the budget pre-flight only
exists on the fresh path (an owned squad's affordability is the solver's job); (c) the
"confirm a suggestion" step cannot precede the run — the pre-run screen confirms the RULES,
not a team, and the suggested team appears only in the summary.

### Screen 1 — Start

- Choice: **Import my team** (enter `manager_id`) or **Build from scratch**.
- Import validates inline and previews the entry (team name, overall rank, current GW) so a
  typo is caught before anything else; error states: not found, no picks saved yet (offer
  the fresh path), a pick that does not map into the forecast roster (block with names).
- Horizon selector (GW1-5 default; 1/3/5 bounded by the loaded vintage). The vintage is the
  default architecture and is displayed, never chosen — cross-model EV comparison is
  forbidden by P0.3 and the UI must not invite it.

### Screen 2 — Set your rules

- **Own team:** the imported 15 renders read-only with the role-coloured pivot rows
  (availability, xP, flags), plus the derived banked free transfers and bank — the "-4 per
  transfer beyond the free grant" rule is stated here, next to the number of free transfers
  the user actually has.
- **Lock picker (both paths, max 5):** the Players pivot with a lock toggle — search bar,
  position/team/price/minutes/availability filters already exist there. Guards computed
  client-side so the solver never has to fail closed on something the UI knew: per-position
  quota (locking a 4th FWD is impossible), club cap (no 4 locks from one club), and on the
  fresh path the **budget pre-flight**: warn when committed cost passes ~90% of budget, and
  block with numbers when `sum(lock now_cost) + cheapest legal completion of the remaining
  quotas > budget` (a sum-of-k-cheapest-per-position lower bound; club-cap infeasibility is
  rare and falls back to the solver's named error). The own-team path shows no budget check
  on locks — the user already owns them.
- **Exclude picker (both paths, max 15):** the same search and filters in a separate mode.
  Locked selections are green and excluded selections red. The sets are disjoint and the UI
  requires removing one rule before applying the other. Exclusions are omitted from the fresh
  squad's cheapest-completion preflight and mean never-select initially / never-buy later.
- **Rotation threshold** (both paths): plain-language selector (Off / 25% / 50%) with the
  semantics inline — outfield bench players must be AT LEAST this likely to appear, bench
  goalkeeper exempt, measure is a conservative lower bound. The picker shows each player's
  appearance lower bound so users see who clears the gate before choosing.

### Screen 3 — Review the rules (pre-run confirmation)

A policy card, not a team: green locks and red exclusions with photos and prices, threshold,
horizon, and per path either the budget headroom (fresh) or squad value + bank + banked free
transfers + the -4
rule (own team). Frozen-price and availability-overlay caveats are printed here once, so
the summary can stay clean. The primary button runs the optimization.

### Screen 4 — Calculate

The browser does not reimplement the solver (PuLP/CBC lives in Python). The local plan server
invokes the real optimizer with `--lock`, `--exclude`, and `--min-bench-appearance`, republishes
the read models, and returns the immutable optimizer run id; the exact command remains visible as
an offline fallback. On completion Plan Builder stays on its own result screen and renders only
that exact run id. If it is absent after republishing, the page fails visibly instead of showing
the platform squad or another custom run.

Localhost requests need no credential. For the optional phone/LAN preview, the server prints a
fresh per-launch token which Plan Builder sends only as `X-FPL-Plan-Token`; all non-loopback
requests require it. The publish also fails closed unless both formal standing artifacts and the
exact custom run appear in `next_gw.json`.

### Screen 5 — Summary

- Fresh path: the 15 with cost and horizon EV, GW1 XI/captain/vice/bench in role-coloured
  rows, the transfer path with hits, lock icons on pinned players, availability flags, and
  the standard development-only caveats.
- Own-team path: **HOLD is presented as a positive recommendation when it is optimal**
  (it frequently is — banked free transfers are often worth more than a forced move);
  otherwise per-GW in/out with a "free" or "-4 hit" badge, EV before/after hits, the new
  XIs, and an explicit "locked players: untouched" line.
- Optional but recommended: a **cost-of-locks comparison** — the same model re-run without
  the user's locks beside the locked run, same scale, so the UI can say "keeping your five
  costs about N xP over the horizon". This is a same-model comparison (legitimate, unlike
  cross-model EV) and is the wizard's most persuasive screen.

### Wizard control → optimizer flag map

| Wizard control | Fresh path | Own-team path |
| --- | --- | --- |
| Import my team | — | manager squad = initial state (no initial-squad ILP) |
| Banked free transfers (derived) | — (fresh season: 0) | `initial_banked_free_transfers=B` |
| Lock player (≤5) | `--lock CODE` (must-include) | `--lock CODE` (never-sell) |
| Exclude player (≤15) | `--exclude CODE` (never-select) | `--exclude CODE` (never-buy) |
| Rotation threshold | `--min-bench-appearance P` | `--min-bench-appearance P` |
| Horizon | artifact GW range | artifact GW range |

## 1a. Prior flow summary (superseded by the screen spec above)

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

Locks (`--lock`, max 5), exclusions (`--exclude`, max 15), and the bench gate compose; the wizard
must reject lock/exclude overlap before solving and translate solver
failures into wizard language:

- locked player below the appearance threshold -> explain that the explicit must-keep rule exempts
  him from the bench threshold;
- locked set breaks position/club/budget legality -> name the conflicting locks;
- excluded or locked code is unknown/unpriced -> name it; excluded players never enter any future
  transfer squad;
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

## 7a. Selections-log backend (owner direction 2026-08-17, design only)

When the hosted mode arrives, a thin persistence service sits beside the wizard and records
every user configuration as an append-only log row:

```text
(user/account id, manager_id when imported, vintage run_id, locked codes,
rotation threshold, created_at)  ->  later joined to the produced plan's run_id
```

Purposes: audit and correction of what a user actually selected (the owner's "correct the
users select logs"), analytics on which locks/thresholds users choose, and the entitlement
checks behind one-manager-per-account with paid extra seats. The log lives in the service
layer -- the optimizer and artifact contracts stay pure, and a log row never mutates a
recorded plan; corrections append a new row with a reason, mirroring the ledger's
append-only discipline.

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
