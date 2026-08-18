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
it when available. `players.json` is by far the largest file and is shared by the Summary,
Players, and Next-GW pages; it is fetched and parsed once per browser session (a
module-level cache in `src/data/load.ts`).

## Solve from the dashboard (local plan server)

The wizard's **Solve now** button targets a tiny local HTTP service (stdlib only, no new
dependency) that runs the *same* jobs the runbook does — never a reimplementation. From the
repository root:

```powershell
.\.venv\Scripts\python.exe -m fpl.jobs.plan_server            # 127.0.0.1:8765
.\.venv\Scripts\python.exe -m fpl.jobs.plan_server --host 0.0.0.0   # reachable from the LAN preview
```

Loopback use is deliberately zero-friction. A LAN-bound server prints a fresh per-launch access
token; paste it into Plan Builder on the phone. The browser sends it only in the
`X-FPL-Plan-Token` header. Every non-loopback request requires that token, and only a dashboard
origin hosted by this machine is accepted.

`POST /plan {"locks": [code...], "excludes": [code...],
"min_bench_appearance": 0.25|null}` runs
`fpl.jobs.optimize_squad` on the dev-latest default forecast with your rules, writes a unique
timestamped immutable artifact under `dev-latest\my-rules\`, then republishes the BI export and
read models carrying the required standing default/diagnostic plans plus that exact interactive
plan. The server refuses to solve if either standing artifact is absent and verifies all three
plan kinds in the browser-facing read model before reporting success. The
artifact records `search_policy.plan_origin=user_custom`; locks are capped at five, exclusions at
fifteen, and their sets must not overlap. This keeps interactive plans distinguishable from formal
platform suggestions downstream. `GET /status` reports busy/stage/worktree state. The browser
never computes anything — it
asks this process to run the fail-closed jobs and then refetches the published JSON.

Every correctness property is inherited: the optimizer still refuses a dirty Git worktree
(the UI surfaces that as a pre-check — commit first), runs are serialized one at a time, and
artifacts stay no-clobber and provenance-bound. The deadline pack itself still comes from the
sequential runbook; interactive plans are additional dev vintages.

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

For phone/LAN testing serve the **built** app, not the dev server — the dev server
recompiles on demand and is slow on a phone:

```powershell
npm run build
npx vite preview --host 0.0.0.0 --port 4173   # http://<your-LAN-IP>:4173/
```

The data location is configurable: `VITE_DATA_BASE` (default `/data`, i.e. `public/data`).
A static build serves whatever JSON was in `public/data` at build time; to deploy, build
after copying fresh read models, or serve `dist/` behind a `/data` route pointing at a
published read-model directory.

## Vintages and images

- An export carries **every recorded forecast vintage** (each recorded run), so the
  exploratory pages have a **vintage selector** and default to the default-architecture
  run referenced by the default optimizer plan. Teams and players therefore appear once,
  never once per recorded run.
- Player photos and club badges are constructed from the permanent `code`/`team_code`
  keys against the external FPL CDN (`resources.premierleague.com`). A failed/missing
  image degrades to a neutral monogram chip — never to another player or club.

## Pages

- **Fixture matrix** (implemented, P1.7b): the fixture pivot — one row per club of the
  selected vintage, **one column per gameweek** (two chips in a double gameweek), default
  sorted by average ease (easiest first, any column re-sorts). Recent form is one compact
  line labelled with its anchor season (at GW1 that is *last* season). Colour source is a
  three-way toggle: **opponent strength** (default; a display-time club-quality index
  derived from the vintage's published lambdas — 100 = average club, higher = stronger
  opponent = red, so a strong club's own row is no longer uniformly green), the row club's
  model ease (overall/attack/clean-sheet views), or official FDR. Expanding a row exposes
  every primitive (raw `lambda_for`/`lambda_against`, clean-sheet probability, all ease
  indices, opponent strength, official FDR, Stage A league-average flag) ordered by
  kickoff time.
- **Players** (implemented, P1.7c): the player-form pivot from `players.json` — one row per
  player of the selected vintage (photo + club badge) merging backward form (3/5/10/STD
  window selector; App, Min/g, G, A, xG, xA, Pts columns) with per-gameweek xP chip
  columns and a range-total xP. Filters: position, team, price range, minimum average
  minutes (last 5), availability, plus the shared view/venue/gameweek bar, all inside a
  distinct Filters panel. Rows are compact and paginated; the expanded row exposes every
  primitive behind the chip colour ordered by kickoff time, with attack- vs defence-detail
  column ordering driven by the view. The same shared table (`PlayerStatTable`) powers the
  Next GW squad table.
- **Summary** (implemented, P1.7d): the landing page — next gameweek kickoff (deadlines are
  not sourced, so none is shown), one optimizer squad summary card per plan (GW1 squad xP,
  cost, hits, captain/vice, XI and bench lines), an availability watch (the official
  injury/doubt overlay with chance %), players to watch (GW1 and horizon xP), and teams to
  watch (easiest/hardest schedules with recent form and the fixture strip). All derived
  client-side from the selected vintage's read models.
- **Next GW suggestion** (implemented, P1.7d): the development-only optimizer plan from
  `next_gw.json` — XI by position with captain/vice badges, ordered bench, transfer path
  with hits (frozen prices), and the **same player pivot table as the Players page**:
  squad-only by default with a "Compare all players" toggle, the shared filters, plan EV
  columns (GW1 xP, 1/3/5-GW EV selector) before the per-GW fixture chips, and C/V/bench
  badges on names. When two architectures are present, the default-vs-diagnostic diff is
  set overlaps only. Cross-plan EV is never compared: it measures the models' calibration
  against each other, not squad quality.
- **Plan builder** (implemented, wizard v1): the configuration side of the manager-wizard
  design (`docs/manager-team-suggestions.md`) — start screen (manager import marked
  post-deadline; build-from-scratch live), a lock picker with search/position filter and the
  per-position/club-cap/max-5 guards, a live budget pre-flight (locks + cheapest legal
  completion vs the rules snapshot read from a recorded optimizer artifact), the rotation
  threshold selector, and **Solve now** through the local plan server (above) with the exact
  command as the offline fallback. The browser never solves; the result renders through the
  Next GW page (preselected automatically) once the plan server records it.
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

- Colour direction is always labelled. Ease indices are directed (100 = league average,
  higher = easier) and carry their formula version; **opponent strength** is the reversed
  direction (100 = average club, higher = *stronger opponent* = harder = red) and is a
  display-time derivation from the published lambdas; official FDR is a separate
  toggleable colour source. The three are never blended.
- `null` means unmeasured: blank/neutral chip or cell, never `0`, `""`, or a fabricated
  colour. A blank gameweek is an empty ticker slot.
- Primitives stay visible beside any composite (expand a row; hover a chip).
- Availability is a reported overlay valid for the next gameweek only; it is passed
  through and never folded into a distribution or EV.
