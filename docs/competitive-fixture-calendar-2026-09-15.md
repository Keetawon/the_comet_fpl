# Club calendar: all competitions

The Fixture Matrix now has an additive **All competitions** view. Club rows and
compact 84px period columns show **Weekend / GWx** and **Midweek / competition**.
The default begins with the cup week before the selected forecast's first GW.
Quick controls show 5, 10 or 15 GWs; a custom date range remains available.
Dates and UK kickoff times are in accessible match tooltips and CSV cells.

League cells use the existing selected-vintage opponent-strength display index,
or explicitly selected current official FDR. Cup/European cells remain grey on
every weekday. A weekend cup tie is labelled **Cup week**, not midweek.
Headers follow the earliest listed fixture in each period. Empty cup periods
are omitted. This is a schedule display, not a fatigue estimate or model input.

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
