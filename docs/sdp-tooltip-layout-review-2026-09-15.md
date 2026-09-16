# SDP chart tooltip layout review

Presentation-only repair from `cba87c75c886cb13dc2342719e5a70ca0f388089`.
The previous absolute tooltip had only a maximum width. Near the chart edge,
shrink-to-fit layout reduced the label column to a few words and made the card
taller than the visible screen. Its vertical placement did not measure available
viewport space.

The existing shared scatter now uses the already-installed Radix positioning
primitive, anchored to the actual SVG point. Cards have a 320px width bounded by
the viewport, collision-aware placement, and bounded scrolling when necessary.
Names, observation counts, axis values and additional metrics have separate
visual hierarchy. Numeric values stay right-aligned without wrapping; source
labels and correction markers remain present. Hover, keyboard focus and touch
open the card; Escape, outside interaction and an explicit close button dismiss
it. Pointer movement into the card keeps it open for reading and scrolling.

This covers Attack meets defence, Attack, Defence and Goals vs xG. Goal-pattern
native hover summaries now put each goal category on its own line. Trend-point
summaries show season/GW, opponent/venue, metric, value and source succinctly;
the match log retains full provenance instead of putting hashes into a tooltip.
Native browser title styling remains browser-controlled.

## Verification

- 64 focused frontend tests pass across the shared scatter, SDP plots/page and
  existing Player/Team Analytics pages.
- TypeScript/build and frontend lint pass. The existing nine Fast Refresh lint
  warnings and Vite large-chunk warning remain.
- Python Ruff check and strict mypy pass (231 source files). Global Python format
  check still flags 11 unchanged files. Initial cache-write restrictions were
  resolved by a cache-free format check and writable-cache mypy invocation.
- The unrelated full Python/Windows symlink suite was not rerun for this UI edit.
- The in-app browser returned no available browser; an isolated installed Chrome
  session performed the visual verification instead. Desktop 1440×1080, compact
  820×764 at 1.5 scale and mobile 390×844 were checked, including light/dark themes.
  39 hover placements passed bounds checks. Touch selection/close, outside
  dismissal, keyboard focus/Escape and source text passed. No JavaScript
  exceptions, failed network requests or page horizontal overflow were observed.
- Actual screenshots and the browser receipt are retained locally under
  `data/artifacts/sdp-tooltip-review-20260915/`, including
  `zoomed-attack.png`, `desktop-defence.png`, `mobile-attack.png`,
  `desktop-dark-defence.png` and `desktop-overview.png`.
- All 404 protected model/config/research/forecast fingerprints are unchanged.
  SDP public and built sidecars remain identical at SHA256
  `24db05500a2ce494a31fcde288ba3b0cf2ff892d4ac2acce2c119dce468d915a`.
  No source refresh, forecast generation, optimizer run or historical scoring
  occurred. Coordinates, metric values, missingness and provenance are unchanged.

The existing local preview serves the repaired assets at
`http://127.0.0.1:4173/#team-stat-sdp`. Reload an open page to load the new bundle.
This is a local preview update; no production deployment or main merge is included.
