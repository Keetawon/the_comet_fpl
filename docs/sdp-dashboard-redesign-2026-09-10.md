# SDP football observatory redesign

The team SDP route now puts the league picture and a club profile before the detailed
statistics table. This is a descriptive UI change over the existing observed-data export.
It does not refresh sources, generate predictions, change models, or change evidence policy.

## Review

Open `http://127.0.0.1:4173/#team-stat-sdp` on the existing host. This is a local preview,
not a published Internet URL. If the preview is stopped, run from `dashboard/`:

```powershell
npm run build
npm run preview -- --host 127.0.0.1 --port 4173 --strictPort
```

The existing GitHub Pages publication workflow is unchanged. This task does not merge main,
create a release, update the public data pin, or deploy production.

## Presentation and navigation

- Retain the exact `Team stat from SDP` label and `#team-stat-sdp` route.
- Consolidate the duplicate `Players stat from SDP` navigation into `Players`. Retained
  detailed player statistics are FPL observations and already have a dedicated Players page.
  `#players-stat-sdp` remains a bookmark alias to Players, with Players active in navigation.
  SDP participation evidence remains in the immutable export; no evidence is deleted.
- Use the existing Geist typography, light/dark theme, SVG chart and fullscreen primitives.
  Emerald accents and comparison colors are scoped to this page. No dependency was added.
- Display the export timestamp separately from forecast/optimizer vintages. The season
  snapshot distinguishes total match coverage across GWs from the latest covered GW.
- Keep season, exact GW endpoints, venue, recent window and club filters. Last 3/5 means
  **up to** that many available matches; no previous-season substitution or invented matches.
- Place the xG-created/xG-conceded scatter beside an observed club profile, including league
  medians, value percentiles, match sparklines and recent/full-selected-range context.
- Offer Overview, Attacking, Build-up, Defending, Duels & discipline, and All metrics views.
  The table retains sorting, comparison of up to three clubs, fullscreen, match logs and CSV.
  Comparison and match logs remain inside the fullscreen element so they can still be used.
- Collapse technical provenance into an expandable section while retaining correction marks
  and measured/selected coverage beside table values. FPL scores are explicitly labelled.

## Descriptive arithmetic

All observed values, zero corrections, assumptions, per-match averages and CSV output reuse
`sdpStats.ts`. The loader, export schema and provider validation are unchanged. No new ratio
or tactical-role estimator is introduced.

Profile and scatter values always use per-match averages. The table and comparison share an
explicit Average/Totals selector; percentage fields remain per-match means in either mode.
The trend and match log retain individual match values, including missing gaps and the
provenance of owner-confirmed/assumed zeros.

The benchmark population consists of all clubs for the same season, GW endpoints, venue and
recent window. Club selection, search and the three-club comparison do not redefine it.
Only clubs with complete metric coverage participate. The median is the median of those
club-level values. The descriptive midrank percentile is:

```text
100 * (clubs with lower value + 0.5 * clubs with equal value) / eligible clubs
```

Fewer than two eligible clubs, or an unavailable subject value, gives no percentile. Higher
value is not a quality score, especially for defensive workload and possession. Benchmarks
include the same marked corrections/assumptions as the visible data. Full-range comparisons
share the selected season/GW/venue scope, without the last-N restriction; overlapping windows
are disclosed and are not interpreted as a persistence test.

## Verification

- 110 frontend tests passed across the SDP page/data/arithmetic, shared scatter/fullscreen,
  navigation, Players and Fixture Matrix regression groups.
- 16 Python SDP export/validation tests passed.
- TypeScript build passed. Frontend lint passed with nine inherited Fast Refresh warnings.
- Ruff passed; strict mypy passed for 229 source files.
- Existing Vite bundle-size warning remains. No unrelated cleanup or historical audit ran.
- 415 protected model/config/research/forecast/read-model files matched the pre-existing
  preservation inventory. The SDP export and its served preview copy remain byte-identical:
  SHA256 `314235c4fbba80cc1be3fa4bc0f8d80338163779358b610106b9f5a8ff73d36f`.
- The local preview serves the new application bundle and the unchanged SDP export.

**Visual verification is pending.** The browser runtime returned `No browser is available`
and discovery returned no connected browsers. A fallback attempt to launch installed Chrome
headless with an isolated review profile and screenshot path was rejected by automatic policy
review (`blocked by policy`). No screenshot was produced, and HTTP/build checks are not
reported as visual testing. Desktop/mobile geometry, real browser console/network behavior and
native fullscreen should be visually reviewed before production publication.

Operational verification receipt: `sdp-redesign-20260910/verification.json` in the existing
host's verification directory. It contains no new forecast or outcome evaluation.
