# The Comet — FPL decision dashboard

Static Vite + React + TypeScript + Tailwind + shadcn/ui + @tanstack/react-table app. It
renders the **static JSON read models** published by the Python layer and nothing else —
it never queries DuckDB and never reads Parquet in the browser.

## Generate the data

From the repository root (Windows PowerShell; the venv is `.venv`). A fresh clone has no
database — build it from the committed archive and daily snapshots first (detail in
`docs/gw1-deadline-runbook.md` steps 4-5):

```powershell
.\.venv\Scripts\python.exe -m fpl.jobs.build_db --db data\fpl.duckdb
Get-ChildItem snapshots\daily\*\* -Directory | Sort-Object FullName | ForEach-Object {
    .\.venv\Scripts\python.exe -m fpl.jobs.load_snapshots --db data\fpl.duckdb $_.FullName
}
```

Record schema-v2 forecast vintages (needs a clean Git worktree). Record **both** the
default and the diagnostic architecture so the Next-GW page's default-vs-diagnostic diff
and the optimizer-audit page each have two plans to show:

```powershell
.\.venv\Scripts\python.exe -m fpl.jobs.prospective_points_v1 --db data\fpl.duckdb --output gw1_5_default.jsonl
.\.venv\Scripts\python.exe -m fpl.jobs.record_forecast --db data\fpl.duckdb gw1_5_default.jsonl
.\.venv\Scripts\python.exe -m fpl.jobs.prospective_points_v1 --db data\fpl.duckdb --attacking v1 --assists v1 --output gw1_5_diagnostic.jsonl
.\.venv\Scripts\python.exe -m fpl.jobs.record_forecast --db data\fpl.duckdb gw1_5_diagnostic.jsonl
```

`next_gw.json` and `optimizer_audit.json` need one immutable optimizer plan per recorded
vintage, optimized from that vintage's own forecast artifact (clean worktree; the job
fails closed otherwise):

```powershell
.\.venv\Scripts\python.exe -m fpl.jobs.optimize_squad gw1_5_default.jsonl --output plan_default.json
.\.venv\Scripts\python.exe -m fpl.jobs.optimize_squad gw1_5_diagnostic.jsonl --output plan_diagnostic.json
```

Publish the BI Parquet export and the dashboard read models, then copy the read models
where the dev server serves them (gitignored):

```powershell
.\.venv\Scripts\python.exe -m fpl.jobs.export_bi --db data\fpl.duckdb `
    --optimizer-plan plan_default.json --optimizer-plan plan_diagnostic.json `
    --output <bi-export-dir>
.\.venv\Scripts\python.exe -m fpl.jobs.export_dashboard_json --input <bi-export-dir> --output <dashboard-dir>
Copy-Item <dashboard-dir>\*.json dashboard\public\data\
```

Note: both publish steps end in an atomic directory-symlink swap, which needs the
directory-symlink privilege. On Windows that means an elevated shell or Developer Mode;
on Linux/CI it just works. In a plain non-elevated Windows shell the swap is refused and
the staged generation is **cleaned up** — there is nothing left to copy manually. Publish
through the `before_publish` hook instead, which runs after validation and immediately
before the swap:

```powershell
@'
import shutil
from pathlib import Path
from fpl.publish.dashboard_json import export_dashboard_json
from fpl.publish.export import export_bi


def keep_staged(target, destination):
    def hook():
        staged = next(target.parent.glob(f".{target.name}.*.tmp"))
        shutil.copytree(staged, destination, dirs_exist_ok=True)
    return hook


plans = [Path("plan_default.json"), Path("plan_diagnostic.json")]
bi = Path("<bi-export-dir>")
try:
    export_bi(Path("data/fpl.duckdb"), bi, optimizer_plan_paths=plans,
              before_publish=keep_staged(bi, Path("bi-export-copy")))
except OSError:
    pass  # swap refused; the validated content is in bi-export-copy
models = Path("<dashboard-dir>")
try:
    export_dashboard_json(Path("bi-export-copy"), models,
                          before_publish=keep_staged(models, Path("dashboard/public/data")))
except OSError:
    pass
'@ | .\.venv\Scripts\python.exe -
```

`manifest.json` is optional for the app (every record repeats its `run_id`/`as_of`); copy
it when available. Each page fetches only its own file(s); `players.json` (the largest) is
fetched only by the Players page.

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
- **Summary** (implemented, P1.7d): the landing snapshot from `summary.json` — latest run
  with its component modes, roster coverage, the next gameweek's first kickoff (deadlines
  are not sourced, so none is shown), headline xP lists, availability-flag risk (labelled as
  a reported overlay), fixture-ease extremes with FDR beside, and the optimizer plans
  present.
- **Next GW suggestion** (implemented, P1.7d): the development-only optimizer plan from
  `next_gw.json` — XI by position with captain/vice badges, ordered bench, transfer path
  with hits (frozen prices), a squad table with a 1/3/5-GW EV selector bounded by the
  vintage horizon, ownership/availability overlay and flags, and — when two architectures
  are present — the default-vs-diagnostic diff as set overlaps only. Cross-plan EV is never
  compared: it measures the models' calibration against each other, not squad quality.
- **Forecast vs actual** (implemented, P1.7e): each recorded vintage scored against its own
  season's finalised outcomes (points under 2026/27 rules, read-time join at
  `(season, gw, code)`) — EV/actual/bias/MAE/CRPS by position and gameweek plus a
  P(≥2 points) calibration table. With no finalised outcomes (the 2026-27 GW1 state) the
  page shows the framework and says why; unfinalised rows are excluded, never read as zero.
- **Optimizer audit** (implemented, P1.7e): the provenance behind each optimizer decision
  from `optimizer_audit.json` — Git heads and the clean-worktree guarantee, forecast and
  squad-rule inputs, solver identity/options/seed/status, the bounded-search policy with its
  declared optimality scope, the verified squad-rule constraints, the explicit assumptions,
  and the transfer path with hits (full squad/XI on the Next GW page). Always carries the
  development-only banner.

`next_gw.json` and `optimizer_audit.json` need optimizer plans in the Parquet export: pass
each immutable optimizer artifact when publishing, e.g. `export_bi --optimizer-plan
<plan.json>` (repeatable; each plan must resolve to a recorded ledger forecast run).

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
