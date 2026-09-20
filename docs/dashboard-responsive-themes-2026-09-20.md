# Responsive navigation and owner artwork themes

Local delivery on `codex/match-preview`, based on
`f039f921cc0bab8a61caa5439d9dd70af4829e09`. This is presentation work only.
No provider activation, publication, model change or forecast regeneration.

## Design and interaction

The four owner references in `D:/Personal/image/The Comet FPL` define the
desktop/mobile day/night direction: sky blue daylight, navy night, cyan navigation,
frosted panels and a small comet mark. The interface is real responsive HTML/SVG,
not a flattened screenshot. The four supplied background PNGs are retained under
`dashboard/public/images/backgrounds/` without modifying their contents. CSS selects
the appropriate viewport/theme asset; no remote artwork, fonts or new dependency.

- Desktop: the sidebar switches between 256px labels and an 80px icon rail. The
  preference is stored as `comet:sidebar-collapsed`; disabled storage is harmless.
  Icon-only links retain accessible names and hover titles. The breadcrumb uses the
  same page metadata as navigation.
- Mobile below 768px: no permanent left rail. A hamburger or **More** opens the
  existing Radix dialog navigation; Summary, News and Players have bottom shortcuts.
  Escape, backdrop, Close, route changes and resizing to desktop close the drawer.
  Focus returns to its trigger. Safe areas are respected; navigation occupies layout
  space rather than covering the last content rows.
- The viewport shell clips outer overflow while the main region scrolls. Its
  positioned containing block prevents offscreen accessibility labels from growing
  the document and causing two vertical scrollbars.
- Light/dark selection, native control `color-scheme`, button state and saved
  preference now agree. Previously the button read the root class before App's
  initialization effect applied a saved dark preference, so its first click could
  reapply dark. Both initialize from the same saved/system preference. Storage
  denial no longer prevents a temporary theme change.
- Summary, News and Score Prediction use the shared glass/hero surfaces. News
  search controls fit mobile and topic chips scroll horizontally. Tables, plot label
  halos, tooltips and capture backgrounds keep opaque semantic colors. Daylight
  links use darker blue ink; cyan filled controls use navy labels. Existing fixture,
  availability and SDP attack/defence colors retain their meanings. Reduced-motion
  and reduced-transparency preferences are supported.

## Verification

- Full frontend suite: **741 tests / 71 files pass**, including navigation, hosted
  route restrictions, blocked storage, theme initialization and existing dashboard
  calculations. Final log: `data/artifacts/match-preview-20260919/theme-vitest-final.log`.
- App, Node-config and Worker TypeScript checks pass. Changed-file oxlint has no
  errors; the existing `initTheme` Fast Refresh non-component export warning remains.
  Static Vite build and `git diff --check` pass. No Python source changed; the known
  broader Python baseline failures recorded in the earlier delivery were not rerun.
- Real Chrome browser verification at desktop 1646px / 1440px and a responsive
  390x844 viewport: collapse/expand and reload persistence, day/night first click,
  mobile drawer/Escape/route closing, bottom navigation, News empty filter/reset,
  Summary, Score Prediction and Players route rendering. Mobile document measures
  390x844 with no outer overflow; desktop measures 1440x900. Viewport emulation is
  not a physical iOS/Android device test.
- The initial Players preview error was a missing synthetic local data envelope,
  not a production loader defect. Empty sample actuals/horizon envelopes were added
  to ignored preview data so its unavailable observations render honestly. No live
  data, manager account or API was consumed.
- Final browser console warning/error list is empty. Screenshot tooling occasionally
  timed out at `Page.captureScreenshot`; successful actual captures are retained:
  `theme-desktop-day.png`, `theme-desktop-dark-collapsed.png`,
  `theme-desktop-summary-dark.png`, `theme-mobile-day.png`,
  `theme-mobile-dark.png`, `theme-mobile-drawer.png`, under the same artifact directory.
  They show explicitly synthetic DEMO data and are not football evidence.
- Rechecked retained operational SHA256 manifests: **167 frozen files and 10
  forecast artifacts unchanged**, excluding Python bytecode. Receipt:
  `theme-frozen-check.json`. No diff under `src/fpl`, `config`, `results` or `AGENTS.md`.

## Local review

Preview: <http://127.0.0.1:4177/#news> on this computer only. If stopped, run from
this worktree's `dashboard` directory:

```powershell
node node_modules/vite/bin/vite.js preview --configLoader runner --host 127.0.0.1 --port 4177 --strictPort
```

This task does not change the live site, scheduler, public-data pointer, model,
optimizer, public-team Worker, privacy rules or published forecasts. Source dates
and missing-data states remain visible. The owner requested local retention;
no push, merge or deployment is included.
