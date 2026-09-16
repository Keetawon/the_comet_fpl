# Insight summary placement

Insight summary now follows the main content on all dashboard routes. Ten page
components moved their existing panel; Plan Builder and Squad Draft already
placed their local-only panels last. Player/Team Analytics retain a bounded
chart width after removing the adjacent insight column. DOM and keyboard reading
order match the visual order.

Insight items, caveats, source identities, filter scopes, private-squad guards
and explicit-action AI behavior remain identical. Existing page-level freshness,
provisional-data and availability notices remain beside their original content.
No forecast, optimizer, source export or model procedure changed.

Verification: 155 existing page/App/insight tests pass, as do TypeScript/build and
frontend lint. Existing nine Fast Refresh warnings and the large-bundle warning
remain. All 404 protected fingerprints and the SDP sidecar hash remain unchanged.
The unchanged Python suite was not rerun; its previously reported global-format
limitations remain outside this layout change.

The in-app browser had no available session. Isolated installed Chrome verified
12 routes at 1440px desktop and 390px mobile: each panel follows page content,
contains no internal horizontal overflow, and initiates no AI request. The SDP
search filter updates both the table and bottom summary. No JavaScript exceptions
occurred. Some image requests reported `ERR_BLOCKED_BY_ORB`; image sources and
fallback handling were unchanged, and no claim of a network-error-free app is made.

Local screenshots and receipts are in `data/artifacts/insight-bottom-20260915/`.
The existing preview at `http://127.0.0.1:4173/` serves the new build; reload an
open page. No production deployment or main-branch merge is included.
