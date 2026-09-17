# Public Players squad filter and mobile import

The owner authorized the Players page to reuse the existing public-team service.
Its hosted filter had remained disabled by the earlier local-only policy even
after public Squad Draft was enabled. No direct browser-to-FPL call is introduced.

Hosted Players now uses the same read-only Cloudflare endpoint as Squad Draft.
`publicSquadMembers` atomically matches all 15 permanent player codes, same season,
planning GW, position and club to the selected forecast. It returns the original
published player objects: prices, points, PMFs and model inputs are unchanged.
Squad Draft retains its additional squad-structure rules. The existing local
Plan Server path remains separate.

The filter intersects other player controls, shows the public source GW and actual
capture time, preserves the prior scope on failed import and clears on vintage
changes. Free Hit and unrevealed-transfer limitations remain explicit. Hosted
Manager IDs are not read from or written to local storage; active membership keeps
AI rendering disabled. No manager data enters static exports, requests to AI or URLs.

## Mobile failure diagnosis

The reported screenshot was on `http://www.thecometfpl.com`. The deployed Worker's
exact allowlist accepts HTTPS origins. Actual preflight verification returned
**403 for HTTP** and **204 for HTTPS**. The screenshot's Manager ID returned **200,
15 unique players, source GW4, planning GW5** through HTTPS. This was an origin/TLS
problem, not a mobile FPL identity or player-data failure.

An automatic approval review rejected temporarily adding HTTP origins. That change
was not applied. The owner explicitly chose to repair HTTPS instead. The Worker
configuration and its HTTPS-only allowlist remain unchanged.

Authoritative DNS and GitHub Pages health showed correct GitHub A/CNAME records,
valid HTTPS eligibility and no CAA blockage, but no issued website certificate.
Re-saving the same domain alone did not change that. The existing workflow-hosted
custom domain was removed and immediately restored, using a configuration guard
and a `finally` restoration. This follows GitHub's certificate-provisioning repair:
https://docs.github.com/en/pages/getting-started-with-github-pages/securing-your-github-pages-site-with-https

GitHub subsequently reported an **approved** certificate covering both
`www.thecometfpl.com` and `thecometfpl.com`, expiring 2026-12-16. **Enforce HTTPS was
enabled.** DNS, repository default branch, main content and Worker settings were
unchanged. Approval is distinct from TLS rollout to every serving edge; check the
actual served certificate before declaring worldwide readiness.

Cached HTTP pages now receive a specific secure-site explanation on network failure
instead of only a generic retry message. No TLS verification is bypassed.

## Verification and publication boundary

- 77 focused import/draft/privacy tests passed, TypeScript and lint passed (nine
  inherited Fast Refresh warnings). The full normal-environment suite passed
  512 tests before the final HTTP error-message regression was added.
- One initial full-suite invocation inadvertently inherited hosted build variables,
  disabling local-only test paths; it was rerun with the normal test environment.
  Those failures were test invocation errors, not evidence of inherited app defects.
- Real isolated Chrome, hosted assets at the allowed HTTPS origin, real deployed API:
  Squad Draft imported 15; Players verified 15. Both preserved state on a real 404
  test, and clearing worked. Mobile was 390px with no horizontal overflow; desktop
  was 1440px. No JavaScript runtime exceptions or local Plan Server requests occurred.
  Some optional external player images were blocked by the browser (ORB); import
  and membership verification were unaffected. No all-network-success claim is made.
- Screenshots and receipts are retained locally under
  `data/artifacts/manager-filter-20260917/`. Test assets were local; the API/CORS/TLS
  were real. This verifies the integration without claiming an unpublished Players
  frontend is already served on production.
- Existing PR #8 was merged by the owner at 04:00:43 UTC. These follow-up changes
  require their own publication review. No main merge or historical rerun occurred.

The separately committed goal-pattern fix and corrected sanitized data companion
are described in `sdp-goal-pattern-refresh-2026-09-17.md`. Original predictions,
model configuration and frozen scientific artifacts are unchanged.
