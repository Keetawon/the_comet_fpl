# Table capture reliability repair

Owner request: capture the expanded table, with the current filters/order and a
`www.thecometfpl.com` watermark, without remaining on Preparing indefinitely.
Starting commit: `fd0fd9a2befe84609b3c84f35febd5ed07a0c806`.

## Cause and repair

The previous renderer waited for the entire document's `fonts.ready` without a
deadline. Its dependency's PNG path also awaited `requestAnimationFrame` after
image decoding. Opening a foreground preview can hide the source tab, where
animation frames may be suspended. Both were unbounded waits. Computed styles
were additionally copied twice across thousands of player-table elements.

Keep the existing HTML-to-SVG dependency for faithful table rendering. Convert
that self-contained SVG to PNG using image load and canvas directly, without an
animation-frame dependency or the unrelated global font-ready promise. Retain
bounded font/image embedding (five-second resource budget), a twenty-second
asynchronous render deadline, cleanup and an actionable error. Browser scheduling
and the initial synchronous snapshot can add to that deadline; this is not a
hard wall-clock promise on every device.

Freeze styles once, omitting duplicate theme-variable declarations because their
computed longhands are already resolved. Avoid copying those computed styles a
second time. Preview now reports three stages and includes the domain watermark
in the exported image's header and footer. No screenshot service, extension,
screen-recording permission, new dependency or automatic image upload is used.

## Capture scope

One click expands a private copy of all scrollable table content horizontally and
vertically. It preserves the current page, filter/order and open detail rows;
the live table remains unchanged. It does not silently traverse pagination or
include filtered-out players. The image labels the page and forecast/observed
scope supplied by its caller, and separates capture time from data freshness.
Download PNG, fit/actual-size preview and explicit native sharing remain available.
Blocked decorative CDN images may be omitted; names and numbers are retained.

## Verification

- Browser plugin initialization succeeded but browser selection reported
  `No browser is available`; discovery returned `[]`. Used the existing isolated
  Chrome CDP test instance, not the owner's browser profile.
- Ten actual browser capture checks passed: calendar, fixture matrix, Players,
  Squad Draft and filtered SDP, each at desktop and mobile widths. Inspected the
  generated PNGs, including their final row/footer and rightmost columns.
- Both Players captures succeeded with animation-frame callbacks deliberately
  suspended and a font-ready promise deliberately left unresolved. Source table
  text stayed identical before/after capture. No uncaught browser exceptions.
- Final measured click-to-preview times: Players 5.85s desktop / 5.31s mobile;
  calendar 2.61s / 2.44s; fixtures 1.16s / 1.23s; Draft and filtered SDP under 0.6s.
  These are local observations, not cross-device performance guarantees.
- Evidence: ignored local `data/artifacts/capture-fix-20260916/verification.json`,
  `players-desktop-capture.png`, `players-mobile-capture.png`,
  `calendar-desktop-capture.png` and corresponding preview screenshots.
- Full dashboard suite: 56 files / 471 tests passed. Final focused rerun after
  the theme-variable size reduction: 14 passed. TypeScript/Vite build passed.
  Lint: zero errors, nine existing Fast Refresh warnings. `git diff --check` passed.
- No Python/model/config/result/data-export changes. No inference, optimizer solve,
  ingestion, historical audit or forecast regeneration was run for this repair.

Local preview remains `http://127.0.0.1:4173/`. Hard-refresh before trying Capture
again; already-open Preparing windows belong to the previous page code. This
does not claim a production deployment or ownership of the mock watermark domain.

## Center watermark follow-up

The owner additionally requested a faint mark that remains when the image's header
is cropped. All table captures now burn `www.thecometfpl.com` directly into the
PNG's center, tilted 15 degrees at 12% opacity. The text scales with the image;
no logo upload or extra resource request is needed. The same marked PNG is used
for preview, download and sharing. The live table and its values are unchanged.
