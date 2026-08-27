# Manager-team transfer suggestions -- as-built record

Status: **implemented development-only for local use on 2026-08-23**. Plan Builder can now
capture a public FPL manager's current permanent squad, optimize from that squad, show the
recommended OUT/IN path and transfer costs, and forward either the suggested squad or the
captured current squad to Squad Draft. Squad Draft also has a direct manager-ID import shortcut.
The original build-from-scratch path remains available and separate.

This is not an authenticated FPL "My Team" integration, a hosted account service, or a
production-validated recommendation. It changes no forecast model, prospective default, or
frozen historical evaluation.

## User workflow

### Plan Builder

1. Choose **Get your team** and enter a positive FPL manager ID, or continue with the existing
   **Build from scratch** path.
2. The local Plan Server fetches the manager's public FPL state, reconstructs the permanent 15,
   writes one immutable private capture, and returns a bounded preview: entry name, picks event,
   planning gameweek, bank, selling value, remaining free transfers, already-incurred hits, and
   the mapped players.
3. Choose up to five locked players and up to fifteen excluded players, plus the existing
   outfield-bench appearance threshold. On the manager path:

   - a lock must be in the imported squad and means **never sell**;
   - an owned exclusion means **force out in the first forecast gameweek**;
   - a non-owned exclusion means **never buy**;
   - lock/exclusion overlap fails before solving.
4. Use the reconstructed remaining free-transfer count or choose an explicit 0-5 override. An
   override is retained in optimizer provenance; it does not mutate the manager capture.
5. Run the real optimizer. The result shows HOLD or OUT/IN by gameweek, free transfers before and
   after, cash before and after, and new hit points. Hits already paid before capture are shown as
   sunk context and are never charged twice.
6. After a successful manager solve, choose either:
   - **Forward suggested team to Squad Draft** -- seeds the optimized first-forecast-GW 15; or
   - **Use captured current team in Squad Draft** -- reloads the exact private capture and seeds
     the pre-suggestion 15.

The result remains a `user_custom` plan on Plan Builder and never replaces the formal platform
suggestion on Next GW.

### Squad Draft shortcut

Squad Draft has its own **Fetch current team** action. It captures a manager by ID and atomically
replaces the browser draft only after all 15 stable player codes map into Squad Draft's exact
forecast vintage and recorded squad rules. A failed fetch, stale capture, missing player, or
structurally invalid squad leaves the existing draft unchanged. This shortcut does not optimize
transfers; Plan Builder owns that workflow.

Squad Draft still displays forecast `now_cost` and treats the standard budget as advisory. The
manager preview's selling value and cash are capture facts, not a new Squad Draft budget rule.

### Players statistics shortcut

The local Players route has a separate **My squad** display filter. It reuses the same trusted
Manager ID capture, but it neither changes a draft nor runs the optimizer. Before activating the
scope, the browser requires all 15 stable player codes to exist in the selected forecast vintage
and checks planning gameweek, position, club code, and deadline price. Any missing or mismatched
player fails atomically and leaves the current table unchanged. Once verified, squad membership is
an AND condition over the existing position, team, price, minutes, availability, forecast-GW,
actual-season, and Actual-GW controls. Changing forecast vintage clears the scope and requires a
fresh fetch.

This filter is local/private state. It is unavailable in hosted static builds, is never written to
the static read models or URL, and never enters the public AI insight request. The Players page's
deterministic facts follow the visible squad-filtered rows; **Explain with AI** is disabled until
the user returns to all players.

## Public-manager reconstruction boundary

The public picks response does **not** contain purchase or selling prices. The implementation does
not invent them. A capture fetches and validates the current-season public endpoints for:

- current bootstrap-static data;
- the manager entry;
- the latest revealed picks and the manager's start-event picks;
- transfer history; and
- entry history, including chips and per-event transfer costs.

It then reconstructs ownership and values as follows:

1. Require `started_event == 1`. A later starter's acquisition prices can change before that
   event's deadline, and the public API does not expose the evidence needed to reconstruct them.
2. Select the latest committed daily bootstrap snapshot captured at or before the GW1 deadline.
   Its fixed launch prices establish the starting squad's purchase prices.
3. Map season-scoped FPL `element` IDs to stable player `code` values. Bare element IDs are never
   joined across seasons.
4. Replay permanent public transfers, using the recorded `element_out_cost` and
   `element_in_cost`. A Free Hit event's temporary squad is not applied to permanent ownership.
5. Reconcile the replayed permanent squad to the latest revealed picks when those picks are
   comparable, then apply confirmed transfers already made for the next planning event.
6. Reconcile cash from the latest picks bank plus those post-picks transfer prices.
7. Compute current selling price in integer tenths:

   ```text
   current <= purchase: selling = current
   current >  purchase: selling = purchase + floor((current - purchase) / 2)
   ```

Every required endpoint is fetched before publication. Missing deadline snapshots, malformed
payloads, unmapped players, missing prices, replay mismatches, illegal squad shape, or an active
Wildcard/Free Hit for the planning event fail closed. The currently supported scope is a
current-season entry that started in GW1, whose next planning event immediately follows its latest
revealed picks, and whose GW1 deadline has a committed repository snapshot. Later-starting entries
fail closed instead of receiving invented purchase prices. This public reconstruction may lag
authenticated account state; authenticated My Team access is not implemented.

## Free transfers and hits

The capture replays the public event history under the recorded 2026/27 rules: one grant per
event, banked up to five. Wildcard and Free Hit preserve the bank that existed before the chip but
consume that event's new grant. Reported transfer costs are reconciled to `-4` for each transfer
beyond the available grant; disagreement fails closed.

For the next planning deadline, confirmed transfers already present in the public log are applied
to the squad, bank, and remaining free-transfer count. Any hit caused by those moves is recorded as
`existing_hit_points`: it is already incurred and therefore does not reduce the prospective
optimizer objective again. Only newly suggested moves beyond the effective remaining free
transfers cost four points each. The first forecast gameweek is actionable; unlike the legacy
fresh-squad plan, it may contain transfers.

The UI permits a 0-5 remaining-FT override because public state and a user's current account view
can differ. The optimizer artifact records both the capture source and override value.

## Selling-value-aware optimization

The manager path does not reject an appreciated owned squad merely because its market price
exceeds the fresh GBP 100.0 budget. Its state carries cash and a sale basis for every owned player:

```text
cash after = cash before
             + sum(captured selling values of outgoing players)
             - sum(frozen now_cost of incoming players)
```

Negative cash is illegal. A player bought inside the scenario receives that frozen `now_cost` as
both purchase and later sale basis. The state key includes squad, cash, free transfers, and sale
basis, so financially different paths are not merged.

Lineup selection is exact for each visited squad. The multi-gameweek transfer search remains the
existing deterministic bounded search; it makes no global-optimality claim. All future prices are
frozen at the forecast artifact's known `now_cost`: future rises, falls, and sale-value changes are
not forecast. The usual later-gameweek availability-overlay caveat also remains.

## Immutable private capture and optimizer artifact

`fpl.ingest.manager_team` emits schema `fpl.manager-team-capture` version 2 with status
`development_only_public_manager_import`. The content-derived `manager-<sha256>` capture ID binds
the normalized squad, manager/event state, values, free-transfer replay, chip history, capture
time, source payload hashes, committed deadline-snapshot hashes, and the current full selectable-
player registry hash. The Plan Server stores it
under `<base>/manager-captures/<capture_id>.json` with atomic create/no-clobber behavior.

A manager solve emits optimizer artifact schema version 2. Its private `manager_context` binds the
capture ID and SHA-256, capture time, manager ID, picks/planning events, bank, effective initial
free transfers and any override, sunk hits, and every owned player's purchase/selling values.
Artifact validation independently replays squad legality, first-week transfers, free-transfer
banking, hit costs, and cash transitions. Existing schema-version-1 scratch-plan identities remain
unchanged.

Manager captures and manager artifact context are local private inputs. They are not added to the
shared player or optimizer dashboard read models.

## Local Plan Server

Run the server against the exact prospective-points artifact whose first gameweek is the manager's
next planning event:

```powershell
.\.venv\Scripts\python.exe -m fpl.jobs.plan_server `
    --base <dev-latest-directory> `
    --forecast <prospective-points.jsonl>
```

Omitting `--forecast` retains the legacy `<base>/gw1_5_default.jsonl` convention; post-deadline
work should pass the current artifact explicitly. The capture and forecast must agree on season,
first gameweek, and a canonical registry hash over every selectable player's season element,
stable code, position, club, and price. Volatile points, ownership, and event fields in the full
bootstrap payload do not invalidate that decision registry. The durable optimizer rechecks the
same binding; the HTTP preview is not the sole provenance guard.

| Endpoint | Purpose |
| --- | --- |
| `GET /status` | solver, forecast, worktree, and current-stage readiness |
| `POST /plan` | existing build-from-scratch custom solve |
| `POST /manager-team` with `{"manager_id": 123}` | fetch, reconstruct, store, and preview a new capture |
| `POST /manager-team/capture` with `{"capture_id": "manager-..."}` | reload exactly one immutable capture |
| `POST /manager-plan` | solve locks, exclusions, threshold, and optional FT override from a capture |

Loopback use needs no token. Non-loopback/LAN requests require the per-launch
`X-FPL-Plan-Token` and existing same-machine origin check. A durable solve still requires a clean
Git worktree, verified PuLP/CBC identity, the exact forecast, and the standing platform artifacts
needed for the shared publish boundary.

## Hosted/public privacy boundary

The supported hosted dashboard is static and read-only. It has no FPL credential, manager account,
manager capture store, or optimizer service. The public-data packager removes `user_custom` plans
and rejects manager IDs, bank/selling values, current-squad payloads, workstation paths, and other
private fields. Neither manager capture nor manager suggestion data is shipped in the public pack.

The local manager-ID workflow uses FPL's public endpoints and does not authenticate ownership of
that ID. Login, authenticated My Team state, one-manager-per-account entitlements, payments, and an
append-only hosted selections log remain unimplemented service-layer work.

## Known limitations and follow-up

- Development-only: no claim is made here that a live end-to-end manager solve or hosted workflow
  has passed a production acceptance gate.
- Only GW1-started entries in the bounded next-event public reconstruction scope above are
  supported; later-start, historical, and cross-season reconstruction require authenticated or
  otherwise exact acquisition-price evidence.
- An active planning Wildcard or Free Hit is rejected rather than modeled.
- Public endpoints can lag what a signed-in manager sees; the recorded remaining-FT override is
  the explicit correction path.
- Future prices and future selling values remain frozen scenarios.
- Chip optimization, autosubs, captain fallback, and authenticated account state remain absent.
- Capture retention/deletion policy, hosted authentication, entitlements, and selections-log
  persistence remain future service concerns.
