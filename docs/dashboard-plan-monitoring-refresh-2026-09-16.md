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
- Frontend: 56 files / 467 tests passed with two workers.
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

Live refresh completion and the existing scheduler action are recorded below after
operational verification. Local preview is `http://127.0.0.1:4173/`; this does not
claim a production deployment or a remotely accessible preview.
