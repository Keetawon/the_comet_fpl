# Public Squad Draft import: authorized activation

## September 17 activation update

The owner explicitly confirmed public Squad Draft and the read-only team service, then
completed Cloudflare OAuth. This supersedes the earlier preparation restriction below for
Squad Draft only. The optimizer, Plan Builder, private captures and local Plan Server remain
unavailable in hosted mode. No model, forecast, source snapshot or public-data release changes.

The Worker is deployed at `https://manager-api.thecometfpl.com/manager-team`, version
`c3145f8a-f2aa-4220-9570-de8c03cdf8bf`. Deployed-origin testing returned 15 unique players,
public picks GW4 and next planning GW5. CORS preflight returned 204 with the exact allowed
origin and no credential allowance. Responses remain `no-store`; no console or body logging
was added. Original deployment `cde061b3-0c75-434a-a3a6-948cea433fbf` failed imports because
workerd rejects `redirect: "error"`. Local runtime debugging identified that incompatibility;
the deployed repair uses `manual` and rejects non-2xx responses without following redirects.
A dedicated redirect rejection regression covers it. Free-plan deployment also required
omitting the custom CPU-limit setting; no plan upgrade was made.

The hosted UI imports only a complete, matching 15-player squad. It displays source GW,
actual fetch time, Free Hit limitations and published-price context. Incomplete identities,
mismatched planning GW and network failures leave the existing editable draft unchanged.
The browser does not persist Manager ID; its saved draft contains selected stable codes and
the response identity. Restored public drafts are labelled as edited snapshots, not live
ownership. Hosted routes reject both private manager-capture and optimizer handoffs.

Final verification: **503 dashboard tests across 58 files passed**, including all 17 Worker
tests. Both strict TypeScript checks and the hosted build passed; lint passed with nine
inherited Fast Refresh warnings. `git diff --check` passed. Python checks were not rerun:
no Python or model files changed, and their content was checked against the frozen receipt.
The original preparation record is retained below as history.

At the activation check, public Google DNS resolved the Worker to Cloudflare and www to
GitHub Pages, but the workstation resolver still returned `208.91.112.55` for both.
Endpoint checks therefore used the public DNS address with normal TLS verification, not
an insecure certificate bypass. GitHub Pages still reported no custom-domain certificate;
its HTTPS www request independently failed hostname validation. This is a separate website
TLS/publication limitation, not a failure of the deployed Worker certificate.

## Activation verification evidence

- Deployed checks on September 17 at 03:37 UTC: valid request 200 / 15 unique players,
  invalid Manager ID 400, disallowed Origin 403. Repository variable
  `PUBLIC_MANAGER_IMPORT_URL` now points to the verified endpoint; only a new hosted build
  consumes it. No token is in that variable.
- Browser verification at 03:42 UTC: desktop 1440x1100 and mobile 390x844 imported all 15
  official players through the actual Worker, real browser CORS and normal API TLS validation.
  Missing-manager failure retained all 15 selections; clear reset the draft; hosted
  Plan Builder navigation stayed blocked. Mobile document width equals its 390px viewport.
  There were no JavaScript runtime exceptions or local Plan Server calls.
- This was **a local hosted-build preview**, not proof that GitHub Pages had published it.
  Test-only request interception served unchanged local frontend assets under the allowed
  origin; the oversized existing public JSON used a loopback asset server with permission
  limited to the disposable browser profile. API requests/responses were not intercepted.
  The API hostname used its independently checked public DNS answer because local DNS was
  stale. TLS checking stayed enabled. The in-app Browser capability had returned no available
  browser; an isolated headless Chrome profile was used instead.
- Several existing external Premier League player photos were blocked/unavailable and fell
  back to initials. This does not affect squad identity or import; no zero-network-error claim
  is made. The large existing player JSON also remains an initial-load limitation.
- Local evidence: `data/artifacts/public-squad-20260917/browser-verification.json`,
  `squad-draft-desktop.png`, `squad-draft-mobile.png`, and
  `squad-draft-failure-preserves-team.png`. These are ignored operator review artifacts,
  not public downloadable squad exports.
- All 668 pinned model/source/config/results/snapshot files remained byte-identical.
  No forecast, optimizer, model evaluation, or data-refresh job was executed.

## Original preparation record (before confirmation)

Starting branch: `claude/comet-fpl-v2-architecture-mqrj8f`,
`a877ff058f0ee9fdec86e9adde071868d3706bf0`.

The owner requested public Squad Draft with Manager ID import. This preparation adds a
small isolated read-only Cloudflare Worker and a typed browser client. Neither is connected
to the hosted routes or deployment workflow. The automatic approval reviewer rejected the
proposed UI integration because it changes the recorded local-only boundary and introduces
an online service. Hosted access remains unchanged pending explicit confirmation of that
exception. This document does not supersede AGENTS.md's current hosted-access rules.

## Exact proposed service

- Host only `POST https://manager-api.thecometfpl.com/manager-team` on the owner's existing
  Cloudflare account. Keep the Dashboard itself on GitHub Pages.
- Read three fixed official FPL endpoints: bootstrap, entry and that entry's latest revealed
  gameweek picks. Map season-local element IDs to stable player and club codes using the
  same current bootstrap. Reject incomplete/ambiguous identity or event evidence.
- Return 15 members, season, source GW/deadline, next planning GW, active chip, actual fetch
  timestamp and response identity. No authenticated account access, purchase/selling prices,
  bank, free-transfer estimates, optimization, or current-ownership claim.
- Public picks can omit transfers made before the next deadline. A Free Hit squad is explicitly
  identified as temporary. This import is a seed for manual editing, not an authenticated team sync.
- No database, retained manager store, console/body logging or provider credentials. Responses
  are `no-store`; Manager ID travels in a POST body. Only configured origins receive CORS access.
  The browser omits cookies, credentials and referrers. CORS is not authentication.
- A native Cloudflare rate limiter allows 20 imports/minute per connecting IP. Shared networks
  may share this allowance; the limit is approximate and local to a Cloudflare location, not a
  global quota or billing guarantee. No open proxy or user-selected upstream URL is supported.
- No local Plan Server exposure, no ports opened, no optimizer execution, no model changes.

## Prepared implementation and verification

`dashboard/worker/manager-import.ts` implements the isolated service.
`dashboard/worker/wrangler.jsonc` contains its proposed custom domain, exact origin allowlist,
disabled Worker logs and rate-limit binding. The configuration has **not** been deployed.
`dashboard/src/lib/publicManagerTeam.ts` validates the separate public-picks response and
atomically resolves all members against a selected same-season forecast and its recorded
squad rules. Existing local manager-capture and optimizer imports remain untouched.
The new browser client is unused until the hosted integration is separately allowed.

A local read-only execution against public FPL manager 1 on
`2026-09-17T02:58:32.870Z` returned 15 unique stable codes, season `2026-27`, picks GW4,
next planning GW5. This verifies official upstream acquisition from the owner machine,
**not** Cloudflare runtime egress, deployed CORS or the hosted UI. The receipt is retained
locally at `data/artifacts/public-squad-20260917/live-upstream-check.json` and contains no
manager name or squad membership.

Focused tests: **77 passed** across adapter, browser boundary, existing Squad Draft,
App access, Sidebar and Plan Server client. Lint exits zero with nine inherited Fast Refresh
warnings. App TypeScript and the new strict Worker type check pass. All 668 pinned
Python/source/config/results/snapshot files are checked against the before-change receipt.
No historical audit, inference, optimizer or data refresh was run.

## Activation sequence after the hosted-service exception is confirmed

1. Wire only hosted Squad Draft to `fetchPublicManagerTeam`; show the source GW, unrevealed
   transfer limitation, Free Hit note and published-price provenance. Retain atomic failure
   and local-only optimizer restrictions. Add UI regression and desktop/mobile browser checks.
2. Authenticate the owner to Cloudflare using Wrangler OAuth; do not paste tokens into chat or
   place them in a browser build. From `dashboard`, deploy the reviewed adapter with
   `npx wrangler@4 deploy --config worker/wrangler.jsonc`. The custom domain must be added
   through the Worker configuration; no changes to the existing apex/www Pages records are needed.
3. Verify the deployed endpoint using an allowed Origin and a Manager ID, including preflight,
   15-player reconciliation, unavailable upstream, and rate-limit behavior. Official FPL may
   reject cloud egress even when owner-machine requests work; do not enable the button on that basis.
4. Only after that verification, bind `VITE_PUBLIC_MANAGER_IMPORT_URL` to the deployed HTTPS
   endpoint in the existing Pages build. Reuse the existing sanitized data release unchanged.
   Review/merge through the owner's existing GitHub workflow; do not publish directly from a
   modified local data directory.
5. Verify the served site at `#squad-draft`. Roll back the UI integration or clear the endpoint
   configuration to disable network imports; the manual draft stays usable. Removing the Worker
   is a separate owner-controlled action and is not necessary to stop imports in the UI.

Cloudflare deployment credentials and browser account access were unavailable during preparation.
The Browser skill was read; runtime selection returned `No browser is available` and discovery
returned `[]`. No screenshots or hosted browser pass are claimed. No public service or route was
enabled and no production deployment was made by this preparation.
