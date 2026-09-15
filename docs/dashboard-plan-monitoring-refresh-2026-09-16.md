# Dashboard plan and monitoring refresh

This delivery updates reporting and operations only. Player/model configuration,
optimizer algorithms, stored forecasts and frozen research results are unchanged.

## Causes and changes

- The SDP/dashboard build refreshed observations without supplying current optimizer
  artifacts. Its base-retention path therefore kept the GW3-7 platform plan.
  The refresh now binds the latest registered primary by artifact SHA256 and supplies
  a validated current plan to the existing BI emitter. One newest plan per platform
  role is selected consistently for Summary, Next GW and Optimizer audit; immutable
  originals and old generations remain available. Cross-vintage diagnostic comparisons
  are suppressed, while old diagnostics retain their actual dates. Repeated publication
  compares the existing public provenance representation (source-body digests and the
  public rules path), so sanitization does not look like a changed plan. Actual
  decision/source-hash changes still fail closed.
- Monitoring intentionally opens the latest *scored* forecast. It now has separate
  latest-scored/latest-published controls plus a manifest-bound freshness receipt.
  A future forecast can be inspected while scores remain pending. GW finality and
  every DGW leg are still required; missing outcomes never become zero.
- Daily outcome attachment can opt into skipping explicitly unfinished live matches.
  The existing strict API default is unchanged. Unknown finality, identity failures
  and conflicting final outcomes still fail closed.
- Player comparisons put forecast, actual and signed residual side by side. Tables
  have search, sorting, largest-error ordering, pagination, sticky headers and optional
  detailed metrics. Team tables follow the selected Attack/Defence/Clean-sheet view.
  Search/sorting affect the table only; scorecards/charts retain the selected GW scope.
  Calibration/detail tables are expandable. No scores or probabilities are recomputed
  in the browser. Team analytics and Player analytics are hidden, including direct routes.

## Existing-host operation

`python -m fpl.jobs.refresh_dashboard` combines the existing FPL/SDP/workload capture
(with complete player histories), locked/backed-up outcome attachment, bound platform
plan reuse or unchanged optimization, fresh BI/SDP exports, validation and Vite build.
Use the explicit paths in [the operations runbook](sdp-primary-operations.md).
It never invokes player inference or overwrites a forecast. A newly due forecast
vintage still comes from the existing `pre_deadline_forecast` procedure; a rollover
warning prevents an older horizon from being presented as a current one.

The platform plan produced for GW5-9 uses retained forecast run
`8f73804604b1bff46b72570e5a2fd561505d12d77cd8fe5531bff6b2913c962a`,
as of `2026-09-14T03:39:12.726789+00:00`. Plan run:
`aadf01432a138b069672f093cf933f5e72336e2b6785869ed04d50196a3a5b59`.
Plan SHA256: `276c74c192a6d0ff74cc89890c6bdc9a28d5430ab03c8d483dc00656f7e0a4c4`.
It was generated with the unchanged optimizer from clean commit `667d400`.

## Verification

- Python: 63 focused refresh/finality/checkpoint tests passed, plus 14 live-snapshot regressions.
- Frontend: 56 files / 467 tests passed with two workers. After adding explicit
  primary/shadow labels, the affected 19 tests passed (including the new regression).
- Ruff and changed-Python-file formatting passed; strict mypy passed on four source files.
- TypeScript/Vite build passed. Frontend lint: zero errors, nine inherited Fast Refresh
  export warnings. An initial unrestricted frontend run had concurrent timeouts; the
  bounded complete run passed. Default Windows pytest-temp access failed once;
  a fresh writable operational test directory resolved it. No full-repository claim.
- Chrome desktop 1440x1000 and mobile 390x844: all four affected routes loaded;
  current plan, vintage switching, search, reset and pending states checked. Fixed
  mobile selector overflow and sticky comparison headers. No horizontal page overflow
  or uncaught runtime exceptions in the verified routes. Screenshots and receipts:
  `data/artifacts/dashboard-review-20260915/` (local, ignored).
- The in-app browser capability was discovered but exposed no browser instances.
  Verification used installed Chrome with a separate temporary CDP profile, without
  touching the owner's browser profile.
- Current player forecast rows (17,284) and team fixture forecast rows (560) were
  equal before/after the retained-data publication repair. Model, optimizer, feature,
  configuration and results directories have no changes in this delivery.

The preceding table Capture/Share delivery is commit `667d400`: Fixture Matrix
opens All competitions / Weekly / 10 GWs. Shared capture previews preserve displayed
filters/order/page, include THE COMET branding, and offer PNG download/native share.
Desktop/mobile capture evidence for calendar, fixtures, Players, Squad Draft and
filtered SDP is in `data/artifacts/table-capture-20260915/`. No image upload is automatic.

Live refresh completion and the existing scheduler action are recorded below. Local preview is `http://127.0.0.1:4173/`; this does not
claim a production deployment or a remotely accessible preview.


## Completed live verification

- FPL capture `8b91555b-e9cc-4e72-84bc-f0e1af810192`, known at
  `2026-09-15T16:52:58.656023Z`: 662 payloads, including one bootstrap, fixtures,
  event-live and all 659 supported player element summaries. Manifest SHA256:
  `c58984de0621819607736d75ddcfa5d580f190b0b9a4f6758b00abd8d1f1ed83`.
- The morning source still had provisional GW4. This new source marks GW1-4
  `finished=true` and `data_checked=true`; 40 total completed fixtures across GW1-4.
  GW5 is next, official deadline `2026-09-18T17:30:00Z`.
- Daily capture ran `2026-09-15T16:41:46Z` to `17:22:03Z`. Capture receipt
  `dashboard-runs/20260915T164146.083594Z-025b766a/report.json` is healthy and staging
  verified. It retains 40/40 match payloads, 80 normalized team sides and 320 tactical
  rows. Production provider-core validity remains **36/40**, with existing incomplete
  fixtures 7, 19, 20 and 28; display corrections do not change that policy. Latest
  covered match is `2026-09-14T19:00:00Z`. Latest SDP known_at is
  `2026-09-15T17:00:24.646949Z`. No identity/schema failures reported this capture.
- That long-running process had loaded the pre-fix publication transport and stopped
  before installation when the same plan appeared in sanitized public form. The
  failed receipt is retained as `dashboard-20260915T164146Z-b63e8205/receipt.json`.
  No capture was repeated. The corrected `refresh_dashboard --skip-capture` completed
  at `2026-09-15T17:29:37.941157Z` (00:29 Bangkok, September 16), reused the verified
  plan, attached outcomes idempotently and built the served preview. Receipt:
  `dashboard-runs/dashboard-20260915T172449Z-c6418871/receipt.json`.
- The new publication contains all 2,549 attached player-fixture and 80 team-fixture
  outcomes across GW1-4. Its default scored primary vintage is run
  `660302216bdfac866003ef50e8077953bb297ff87412252bc796f27c8adbdd2f`,
  as of September 9, GW4-8, with 654 GW4 player-gameweek rows and 20 GW4 team sides.
  Its incumbent shadow is labelled separately. These are individually selected
  monitoring vintages, not a replacement or pooled reinterpretation of the fixed-origin
  GW4-8 checkpoint. Future GW5-9 forecasts correctly remain unscored.
- Public manifest: `bc2777048eaddf78cd4d561ebbe64a1b0147588e161543aac68fa76c6938eb33`.
  Source/public/dist files match. Chrome confirmed selectable GW4, current GW5-9 plans,
  primary/shadow labels, sorting, search/reset, all three team views and pending-future
  states at both sizes. Eight page/viewport combinations passed with zero console
  errors, uncaught exceptions or failed local asset responses. Twelve final screenshots
  are retained beside `verification.json` and `completion.json`.
- Original forecast ledger verification is exact: 28 run headers, 86,420 player-GW
  rows, 86,420 player-fixture rows and 2,800 team-fixture rows have identical before/after
  JSON fingerprints against the pre-refresh backup. All 177 tracked protected model,
  feature, optimizer, configuration, results and inference files are unchanged from
  turn-start `a5a2314d85e1f5b40f2fdd1488488453588f4a6b`.

## Scheduler and access

Updated only the existing **The Comet FPL - SDP primary V2** task action. It is enabled
and Ready, next run September 16 at 07:00 Bangkok. Trigger, principal, two 30-minute
retries and two-hour limit are byte-equivalent in retained XML before/after checks.
It now executes the runbook's `refresh_dashboard` command with absolute operational
paths. The current verified plan is cached in `D:/Personal/fpl-operations/dashboard-plans`.
No additional scheduler was created; the other existing capture task was untouched.

The new action has been verified by running its command manually; its first automatic
07:00 firing has not yet occurred. LastTaskResult=1 belongs to the previous action,
not the completed manual refresh. The owner machine must be on and signed in.
Local verification receipts/XML are in `data/artifacts/dashboard-review-20260915/`.

Open `http://127.0.0.1:4173/` on the owner machine and hard-refresh (Ctrl+Shift+R).
The preview and optimizer service were left running. Main/default branch and remote
production deployment were not changed. New model development was not started.
