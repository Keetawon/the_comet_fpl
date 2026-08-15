# The Comet — FPL decision dashboard

Static Vite + React + TypeScript + Tailwind + shadcn/ui + @tanstack/react-table app. It
renders the **static JSON read models** published by the Python layer and nothing else —
it never queries DuckDB and never reads Parquet in the browser.

## Generate the data

From the repository root (Windows PowerShell; the venv is `.venv`):

```powershell
# 1. Forecast + record a schema-v2 vintage (needs a clean Git worktree; see the GW1 runbook)
.\.venv\Scripts\python.exe -m fpl.jobs.prospective_points_v1 --db data\fpl.duckdb --output <forecast.jsonl>
.\.venv\Scripts\python.exe -m fpl.jobs.record_forecast --db data\fpl.duckdb <forecast.jsonl>

# 2. Publish the BI Parquet export and the dashboard read models
.\.venv\Scripts\python.exe -m fpl.jobs.export_bi --db data\fpl.duckdb --output <bi-export-dir>
.\.venv\Scripts\python.exe -m fpl.jobs.export_dashboard_json --input <bi-export-dir> --output <dashboard-dir>

# 3. Copy the read models where the dev server serves them (gitignored)
Copy-Item <dashboard-dir>\*.json dashboard\public\data\
```

Note: the two publish steps end in an atomic directory-symlink swap, which needs the
directory-symlink privilege on Windows. Without it (non-elevated shell) the swap is
refused after the generation is staged; the staged generation under
`.<name>.*.tmp` is complete and can be copied manually. On Linux/CI this does not apply.

`manifest.json` is optional for the app (every record repeats its `run_id`/`as_of`); copy
it when available. `players.json` is only fetched by the Players page.

## Run

```powershell
cd dashboard
npm install
npm run dev        # http://localhost:5173, reads public/data/
npm run build      # tsc -b + vite build -> dist/
npm run preview    # serve the built app
npm test           # Vitest component tests
npm run lint       # oxlint
```

The data location is configurable: `VITE_DATA_BASE` (default `/data`, i.e. `public/data`).
A static build serves whatever JSON was in `public/data` at build time; to deploy, build
after copying fresh read models, or serve `dist/` behind a `/data` route pointing at a
published read-model directory.

## Pages

- **Fixture matrix** (implemented, P1.7b): one row per club — recent form (labelled with
  its anchor season; at GW1 that is *last* season), a per-fixture ticker over the vintage
  horizon, and an expandable row with every primitive beside the composite ease indices
  (raw `lambda_for`/`lambda_against`, clean-sheet probability, official FDR, Stage A
  league-average flag).
- **Players** (implemented, P1.7c): the player-form pivot from `players.json` — one row per
  (run, player) merging backward form (anchor-season-labelled, 3/5/10/STD window selector)
  with the vintage's per-fixture xP. Filters: position, team, price range, minimum average
  minutes (last 5), availability, plus the shared view/venue/gameweek bar. The chip headline
  is the fixture xP; its colour follows the active view's CLUB metric (or official FDR), and
  the expanded row exposes every primitive behind the colour (club lambdas, clean sheets,
  ease indices) beside the player's own probabilities, with attack- vs defence-detail column
  ordering driven by the view.
- Summary, Next GW suggestion, Forecast vs actual, Optimizer audit: stubs, in roadmap order.

## Rules the UI must keep

- Colour direction is always labelled: **green = easier/better, red = harder**. Ease
  indices are directed (100 = league average, higher = easier) and carry their formula
  version; official FDR is a separate toggleable colour source, never blended into an
  ease value.
- `null` means unmeasured: blank/neutral chip or cell, never `0`, `""`, or a fabricated
  colour. A blank gameweek is an empty ticker slot.
- Primitives stay visible beside any composite (expand a team row; hover a chip).
- Availability is a reported overlay valid for the next gameweek only; it is passed
  through and never folded into a distribution or EV.
