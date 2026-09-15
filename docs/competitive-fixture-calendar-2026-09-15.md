# Club calendar: all competitions

The Fixture Matrix now has an additive **All competitions** view. Club rows and
compact 84px period columns show **Weekend / GWx** and **Midweek / competition**.
The default begins with the cup week before the selected forecast's first GW.
Quick controls show 5, 10 or 15 GWs; a custom date range remains available.
Dates and UK kickoff times are in accessible match tooltips and CSV cells.

The **Weekly / Daily** toggle retains the chosen teams, horizon, dates and
difficulty source. Weekly remains the default. Daily uses continuous 76px UK-date
columns, including empty dates, with kickoff times on the match cards. Each day
inside a verified international window is yellow; cup cards stay blue, and any
overlapping club game remains visible. Club labels and date headers remain sticky;
horizontal scrolling and fullscreen support longer ranges. A maximum of 366 days
prevents an accidental huge date range from freezing the browser; the user can
shorten the range or return to Weekly, with no silent clipping.

Daily's **listed gap** counts clear UK calendar dates between the previous listed
club fixture and the current one, excluding both match dates. Wednesday to Saturday
therefore shows `2d listed gap`. It uses the same club's complete retained schedule,
including fixtures outside the displayed date range, and is unaffected by team
filters. No previous dated game, or any undated game for that club, leaves the gap
unavailable. This is schedule spacing, **not physical player rest**: missing cup
rounds, national-team appearances, training, travel and actual participation are
not established. It does not compute rest hours or change minutes/forecast inputs.

Daily shows only fixtures on the selected dates. DGW legs retain their official GW
and a DGW marker even when another leg falls outside the visible dates. Weekly
continues to retain all selected GW legs and its existing BGW rules. Empty daily
cells mean no listed club fixture, never a BGW or proven rest. TBC fixtures remain
in the undated section. CSV follows the active view, with exact daily dates,
kickoff times, listed-gap wording and international-window provenance; filenames
include `daily` or `weekly`. Reset returns to the default Weekly view.

International dates in Daily now start **collapsed** into one yellow column per
verified window. Its header offers **+ Expand / − Collapse**, independently for
each window and usable with keyboard/touch in fullscreen. Expansion restores the
individual dates; focus follows the replacement header. Partial date selections
fold only their included dates. Day counts continue to report the full selected
duration alongside the number of displayed columns. Every listed club fixture is
retained when folded, with its match date visible, and CSV retains the folded date
range plus each game's timestamp. Listed gaps are unchanged. Reset clears expansion
choices; Weekly retains its existing compact international columns.

Daily verification: 36 calendar/page/fullscreen tests pass, including continuous
empty dates, DST, deterministic replay, same-day fixtures, out-of-view predecessors,
undated gaps, daily clipping versus whole-GW retention, and CSV consistency.
TypeScript/Vite and lint pass with the previously recorded warnings. Actual Chrome
verification covers Weekly/Daily round trips, a 19-day selection, all 20 clubs in
1720×1080 fullscreen, 390×844 horizontal scrolling, readable gap tooltips, and a
completed 20-club CSV download. No JS errors or failed requests were observed.
Evidence: `data/artifacts/competitive-calendar-daily-20260915/`. Model/configuration,
published input JSON and frozen prediction/research artifacts were not modified.

League cells use the existing selected-vintage opponent-strength display index,
or explicitly selected current official FDR. Cup/European cells use blue on
every weekday, distinct from the neutral grey league-difficulty tier. This colour
was updated after owner review; it indicates competition type, not difficulty.
A weekend cup tie is labelled **Cup week**, not midweek.
Headers follow the earliest listed fixture in each period. Empty cup periods
are omitted. This is a schedule display, not a fatigue estimate or model input.

International windows have a separate yellow column, including when the selected
date range contains no club fixtures. The 2026/27 windows are 21 September–6 October
2026, 9–17 November 2026 and 22–30 March 2027, as published by the
[Premier League](https://www.premierleague.com/en/news/4689113/when-are-the-international-breaks-for-202627)
on 5 September 2026 and checked on 15 September 2026. The first falls between
GW5 and GW6. One compact column spans the entire window; its dates, source and
meaning are exposed in the tooltip, provenance and CSV. These are schedule
annotations, not player call-ups, workload or confirmed rest. Existing club
fixtures and DGW legs are never removed if their dates overlap a window.
No break is inferred from an empty schedule, and no unverified season inherits
these dates. The three published windows are retained in
`dashboard/src/data/internationalBreaks.ts`; another season requires verified
calendar evidence before annotations can be added.

International-window verification: 31 calendar/Fixture Matrix/fullscreen tooltip tests pass,
including inclusive date filtering, no inferred windows for unsupported seasons,
unchanged DGW legs, empty club schedules, colour-mode independence and CSV source
labels. TypeScript/Vite build and frontend lint pass (existing bundle-size and
nine Fast Refresh warnings remain). Desktop and mobile Chrome checks confirm
the September and November columns appear between the correct published GWs,
with no console or request failures. Screenshots and the local browser receipt
are in `data/artifacts/competitive-calendar-international-20260915/`.
Browser inspection also found portal tooltips hidden behind the native fullscreen
layer. The shared tooltip now mounts inside the active native/fallback fullscreen
container; inline behaviour remains unchanged. Calendar tooltip paragraphs use
a vertical layout so dates and source notes remain readable.

## Double and blank gameweeks

Every league leg belongs to its official FPL GW, including midweek games.
Multiple legs stack with individual difficulty colours and a **DGW** badge.
Selecting any part of a GW retains all its legs, even if another leg is outside
the date filter or has no confirmed kickoff. Missing times remain TBC.

**BGW** means no league fixture is assigned to that team/GW in the current
complete-season official schedule overlay (`_build_current_schedule`). The
column stays visible even if the selected club is blank. An absent season/team
schedule or an unknown GW is **Unavailable**, not BGW. Blank cup cells mean no
listed fixture, never confirmed rest. Subsequent official amendments may change
a schedule; neither label predicts whether a player will appear.

## Sources and publication

- EPL identity, GW, dates and FDR: existing `fixture_matrix.json` official FPL
  schedule overlay, explicitly current-at-export and separate from forecasts.
- Cup/Europe: new small `sdp/competitive_schedule.json`, read only from retained
  `competitive_matches` raw SDP pages. No new network requests or backfill.
- Club identity: existing validated season-specific EPL fixture crosswalk,
  corroborated raw SDP match metadata and permanent FPL team codes. No fuzzy
  matching or assumption that provider identifiers equal FPL identifiers.
- Each competition retains selected source hashes, payload identities and true
  version timestamps. Repeated unchanged captures retain their original times.
- Follow the latest root page's exact cursor chain; orphaned old pages never
  enter a new catalogue. Missing pages are PARTIAL. Invalid hash, HTTP, schema,
  duplicate identity or looping cursor fails that competition closed. A
  terminated empty catalogue is NOT_PUBLISHED, not proof of no future games.

Retained 2026/27 export: 20 verified PL clubs; League Cup 23 unique fixtures,
Champions League 40, Europa League 24, Conference League 6; FA Cup not yet listed.
These are **season catalogue counts**, not counts in the visible date filter.
Source-version dates span September 7–11; the public calendar was assembled on
September 15 from those retained versions. This is not a new capture receipt.
Other competitions outside the existing six-provider-competition collection
are not claimed covered. Unknown future draws are not invented.

`build_sdp_dashboard` now exports the calendar in the same read-locked generation
as the established dashboard and SDP statistics; `install_preview` already
installs its public JSON. Raw captures, normalizations, prediction artifacts,
player components, configuration, optimizer and frozen research are untouched.
The 13 pre-existing dashboard JSON files were verified byte-identical.

The existing Pages workflow accepts an optional `competitive_schedule_asset`
alongside `sdp_asset` in the same immutable release pin. It has the same
`name`/`sha256`/`size_bytes` validation and public-schema check. Old releases
without the new companion remain usable: the view discloses unavailable cup
coverage and retains EPL. No release, production deployment or main merge is
performed here. Publish the generated companion with the next authorized public
data release; never expose the operational database or raw bundles.

Local review: `http://127.0.0.1:4173/#fixtures` → **All competitions**.
The existing preview and optimizer services remain running. Browser captures,
downloaded CSV, public export/replay receipts and source reconciliation are
retained under `data/artifacts/competitive-calendar-20260915/` (local, ignored).

## Verification

International-date folding verification (2026-09-15): 38 focused frontend tests
pass, including independent windows, clipped ranges, retained overlapping club
fixtures, keyboard focus and CSV timestamps. TypeScript/Vite build and frontend
lint pass with the existing nine Fast Refresh warnings and bundle-size warning.
Installed Chrome verified actual desktop (1720×1080) and mobile (390×844)
rendering, Enter-key and touch expansion/collapse, fullscreen and CSV download.
The default 50-date range folds to 35 columns; all 135 displayed club fixture
cards and their listed gaps remain identical after expansion. The CSV contains
20 club rows plus its header. No JavaScript exceptions or failed requests were
observed. Screenshots and the browser receipt are retained locally under
`data/artifacts/competitive-calendar-folded-20260915/`. Model, configuration,
forecast and source-data paths remain unchanged from
`2e68806e239a89d05949862c8a6a40670e8952d5`.

- Python: 21 focused schedule/publication/freshness tests pass. Raw hashes,
  revisions, exact cursor selection, identity, future-source exclusion, missing
  dates, partial catalogues and write-once deterministic publication are covered.
- Frontend: 22 calendar/Fixture Matrix tests pass, including DGW stacking and a
  BGW-only selected club. TypeScript/Vite build and frontend lint pass; the nine
  existing Fast Refresh warnings and existing large-bundle warning remain.
- Changed Python files pass Ruff, formatting and strict mypy (two source modules).
  The inherited Windows default pytest temp-folder permission issue was avoided
  using an isolated workspace `--basetemp`; it is not a test skip.
- Browser: the installed browser skill found no connected browser (`list=[]`).
  Installed Chrome with an isolated profile then verified desktop 1720×1080 and
  mobile 390×844, team selection/reset, grey cup colours, difficulty switching,
  fullscreen, and an actual completed CSV download. Zero JS exceptions/network
  failures. Ten GWs produce 15 compact periods with verified 84px columns.
- Every one of the 93 exported cup/European matches reconciles to its retained
  raw metadata and payload hash. Re-exporting at the same cutoff is byte-identical.
- Companion SHA256:
  `b39654111176321faa4dff75fbc6985cf2d519855d425b66f66ed66d713fa649`.
- Model/config/source-normalization/frozen-result paths are unchanged from
  starting commit `0fb43ded3b772c282744666e3364ac6a483ffc0d`; all 13 existing
  dashboard data JSON files are byte-identical. No inference or audit was run.
