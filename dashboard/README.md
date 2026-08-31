# The Comet — FPL decision dashboard

Static Vite + React + TypeScript + Tailwind + shadcn/ui + @tanstack/react-table app. It
renders the **static JSON read models** published by the Python layer and nothing else —
it never queries DuckDB and never reads Parquet in the browser.

## 2026-08-26 dashboard program

Schema v9 is the current development-only application contract. The ordered program is:

1. **Implemented development-only:** Player analytics and Team analytics over existing published
   values, following `../docs/dashboard-deep-analytics.md`;
2. **Implemented development-only:** schema-v5 parallel player/team prediction-versus-actual pages
   with complete-gameweek finality, following `../docs/prediction-vs-actual-dashboard.md`;
3. **Implemented development-only:** a deterministic insight panel on every route and an optional,
   evidence-bound trusted-server language renderer
   on public analytical routes, following `../docs/dashboard-ai-summaries.md`;
4. **Implemented development-only:** the Players route reads normalized finalized observations
   from `player_actuals.json` and exposes explicit chronological `Actual from` / `Actual to`
   Season–GW endpoints. Their page-wide options are limited to the forecast season and its
   immediately preceding season, with the predecessor present only when finalized observations
   were published. The default/reset scope is the latest five keys (at 2026-27 GW1, 2025-26 GW35
   through 2026-27 GW1); an explicitly displayed range may cross the season boundary, but no season
   or missing gameweek is silently substituted. Schema v9 adds the exact fixture-time Club,
   Opponent, and venue identity used by the expanded Players rows;
5. **Implemented development-only:** `team_actuals.json` provides the parallel normalized
   finalized team-fixture history for Fixture Matrix expanded rows. Its Actual scope defaults to
   the page-wide rolling latest five distinct season-qualified finalized gameweeks across the
   forecast season and its immediate predecessor; explicit single-season options remain available,
   and double-gameweek legs are retained.

The implemented deep-analytics routes are `#player-analytics` and `#team-analytics`; both are
linked directly in the sidebar and retain an exact-table equivalent for every chart.

All eleven routes render their deterministic summary without a network dependency. The seven
public renderer-eligible routes are Summary, Fixture matrix, Players, Player analytics, Team
analytics, Player prediction vs actual, and Team prediction vs actual. Next GW suggestion,
Optimizer audit, Plan Builder, and Squad Draft remain deterministic-only because they contain
decision or private local state.

The static hosted build never receives a model-provider key and never calls Z.AI or any other
provider. Deterministic summaries remain available there and the optional action is unavailable.
Local provider configuration belongs to the trusted Python server environment, never `VITE_*`,
static JSON, a URL, browser storage, logs, cache records, or Git.

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

`manifest.json` is optional only for deterministic/base page loading because every record repeats
its `run_id`/`as_of`; it is required for optional AI eligibility and the server's exact generation
verification, so deployment packages always include it. `players.json` is by far the largest file and is shared by the Summary,
Players, and Next-GW pages; it is fetched and parsed once per browser session (a
module-level cache in `src/data/load.ts`). Introduced in schema v4 and retained in schema v9,
`player_horizons.json` carries cumulative xP plus inclusive `P(<=2)` and `P(>=2/4/6/10/15)` for every
player and exact forecast endpoint. Python computes those probabilities by convolving the
published gameweek PMFs at full precision, then emits a compact positional row whose named values
are quantized to six decimals. Exact zero/one probability boundaries are preserved. The browser
data layer validates the field dictionary, decodes the row, and selects an exact
`(run_id, season, code, gw_to)` endpoint; it never sums probabilities or parses a PMF.
`player_actuals.json` and `team_actuals.json` are run-independent normalized historical files;
their strict schema-v9 loaders preserve fixture grain and NULLs rather than consulting forecast
fixture arrays. Every normalized player-actual fixture also carries its fixture-time club,
opponent, and venue identity. The publisher resolves those identities within their own season,
checks gameweek/side/venue/codes against `dim_fixture`, and uses that dimension's kickoff as the
canonical presentation timestamp.

## Solve from the dashboard (local plan server)

The wizard's **Solve now** button targets a tiny local HTTP service that runs the *same* jobs the
runbook does — never a reimplementation. From the
repository root:

```powershell
.\.venv\Scripts\python.exe -m fpl.jobs.plan_server `
    --base <dev-latest-directory> `
    --forecast <current-prospective-points.jsonl>              # 127.0.0.1:8765
.\.venv\Scripts\python.exe -m fpl.jobs.plan_server --host 0.0.0.0 `
    --base <dev-latest-directory> --forecast <current-prospective-points.jsonl>
```

`--forecast` binds both scratch and manager solves to one explicit prospective artifact. If it
is omitted, the legacy `<base>/gw1_5_default.jsonl` convention remains; post-deadline operation
should pass the current artifact explicitly.

### Optional evidence-bound Z.AI summaries

Provider rendering is disabled by default. To enable the implemented Z.AI adapter for the seven
public analytical routes, configure the general Open Platform API in the trusted PowerShell process
before starting the same Plan Server. Replace the placeholder in a private shell or source it from
a local secret manager; never commit a real key or put it in a `VITE_*` variable:

```powershell
$env:FPL_INSIGHTS_PROVIDER = "zai_glm"
$env:FPL_INSIGHTS_API_KEY = "<general-Open-Platform-API-key>"
$env:FPL_INSIGHTS_MODEL = "glm-4.7"
# Optional; omit to use the implemented default.
$env:FPL_INSIGHTS_BASE_URL = "https://api.z.ai/api/paas/v4/"

.\.venv\Scripts\python.exe -m fpl.jobs.plan_server `
    --base <dev-latest-directory> `
    --forecast <current-prospective-points.jsonl> `
    --dashboard-data dashboard\public\data
```

`GET /insights/status` and `POST /insights/summary` use the same same-origin/approved-LAN-token
boundary as the other local endpoints. After **Explain with AI** is clicked, the browser submits
only an exact page/vintage/filter selector. The server revalidates the explicitly selected
schema-v9 dashboard generation (`--dashboard-data`, default `dashboard/public/data`) and constructs
the fact packet itself. The provider cannot receive caller prose, a free-form prompt, PMF,
manager/capture identifier, squad, bank, purchase/selling value, credential, or custom plan state.
The provider returns fact-id selections rather than prose; Python renders canonical cited text and
React never renders provider HTML or executable Markdown. Timeouts, disabled configuration, rate
limits, bad selections, malformed output, or provider failures leave the deterministic panel
intact.

Only a validated response and safe provenance are cached under the ignored Plan Server base. Keys,
selector requests, resolved facts, raw provider bodies, and failures are neither cached nor logged.
The cache key binds the canonical server-resolved evidence, provider, model, and prompt version.
Z.AI Coding Plan quota is licensed for
supported coding tools and must not be assumed to cover general application traffic; use a general
Open Platform API key/balance under the current provider terms.

Loopback use is deliberately zero-friction. A LAN-bound server prints a fresh per-launch access
token; paste it into Plan Builder on the phone. The browser sends it only in the
`X-FPL-Plan-Token` header. Every non-loopback request requires that token, and only a dashboard
origin hosted by this machine is accepted.

`POST /plan {"locks": [code...], "excludes": [code...],
"min_bench_appearance": 0.25|null}` runs
`fpl.jobs.optimize_squad` on the selected forecast with your rules, writes a unique
timestamped immutable artifact under `<base>\my-rules\`, then republishes the BI export and
read models carrying the required standing default/diagnostic plans plus that exact interactive
plan. The server refuses to solve if either standing artifact is absent and verifies all three
plan kinds in the browser-facing read model before reporting success. The
artifact records `search_policy.plan_origin=user_custom`; locks are capped at five, exclusions at
fifteen, and their sets must not overlap. This keeps interactive plans distinguishable from formal
platform suggestions downstream. `GET /status` reports busy/stage/worktree state. The browser
never computes anything — it
asks this process to run the fail-closed jobs and then refetches the published JSON.

The development-only own-team surface adds four manager-team POST endpoints plus the manager
optimizer endpoint:

- `/manager-team {"manager_id": 123}` fetches the public entry/picks/transfers/history payloads,
  reconstructs purchase and selling values from the committed start-deadline bootstrap plus
  transfer replay, maps season-scoped elements to stable player codes, and atomically creates
  `<base>/manager-captures/<capture_id>.json`;
- `/manager-team/capture {"capture_id": "manager-..."}` reloads that exact immutable capture;
- `/manager-team/members {"manager_id": 123}` and
  `/manager-team/members/capture {"capture_id": "manager-..."}` serve only the read-only Players
  filter and non-optimizer Squad Draft. They tolerate unrelated selectable-player additions but
  still reconcile the exact 15 members against the forecast season, planning gameweek, stable
  code, position, club identity, and deadline price before returning anything;
- `/manager-plan` consumes the capture id, locks, exclusions, threshold, and optional
  `free_transfers_override` (0-5), then runs the same optimizer/publish chain from the imported
  squad.

Plan Builder and the manager optimizer require the manager capture and active forecast to agree on
season, first gameweek, and a canonical full selectable-player registry hash covering season
element, stable code, club, position, and price. Volatile bootstrap statistics are deliberately
excluded. The member-only endpoints do not weaken that optimizer gate: their narrower contract is
valid only for displaying the captured 15, while any optimizer solve still fails closed until its
complete transfer-candidate registry is refreshed. Public reconstruction currently
fails closed for entries that started after GW1 because their acquisition prices are unavailable.
An exact registry mismatch invalidates the imported capture and its player rules in Plan Builder
and returns the user to **Import my team** while preserving the manager id. Refresh both paired
forecast artifacts, their standing plans, and their ledger records first; then use **Get your
team** again. A successful fresh fetch re-checks the server, and any other solve error keeps an
explicit **Re-check** action available instead of leaving the tab terminally disabled.
The first forecast gameweek may contain transfers.
Captured bank and per-player selling values govern affordability; already-incurred hits are sunk,
while newly recommended transfers beyond the effective remaining free transfers cost four points
each. A lock is an owned never-sell player. An owned exclusion is forced out in the first
forecast gameweek; a non-owned exclusion is never bought. Future prices remain frozen.

These endpoints use public FPL data and do not authenticate ownership of a manager ID. Captures
and manager artifact context are private local inputs and are not added to the shared dashboard
read models. See `../docs/manager-team-suggestions.md` for the reconstruction and provenance
contract.

Solver readiness in `/status` includes the separately observed PuLP package and CBC binary
versions, the discovery-attempt count, and a component-specific failure reason. A failed startup
probe is retried from status after a short cooldown; concurrent status requests return cached
state instead of queuing CBC launches. Browser diagnostics name only the failed component and
exception type, while full exception details remain in the server log. Every solve forces a fresh
probe even after a previously good identity. No retry supplies a default or accepts a partial
identity, and the isolated optimizer child still re-verifies both versions before it may write the
provenance-bound artifact.

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
published read-model directory. The local plan server also generation-swaps both `public/data`
and an existing `dist/data` after validating the exact custom run, so the documented
`vite preview` loop sees the same complete read-model generation without rebuilding the
JavaScript bundle. A failed swap cannot be reported as a successful solve. The server restores
every target it can; if the operating system also blocks restoration, it preserves the
`.previous` directory and reports the exact backup-to-target recovery path instead of deleting
the last good generation.

## Public hosting

The supported zero-cost hosted shape is GitHub Pages plus an immutable, sanitized dashboard-data
ZIP pinned in `public-data-release.json`. The hosted build is read-only: analytical pages and
manual Squad Draft work in the browser, while Plan Builder never probes a visitor's local
optimizer and directs exact solves back to a trusted machine. Manager fetch/solve and direct
manager-to-Draft import likewise require the trusted local Plan Server; the hosted site has no
manager account, capture store, or authenticated My Team integration. The public-data packager
removes user-custom plans and rejects manager IDs, bank/selling values, current-squad payloads,
workstation paths, or secret-like values before rebuilding and validating the manifest.

See [Public dashboard deployment](../docs/dashboard-deployment.md) for the one-time Pages setting,
release/pin workflow, privacy boundary, refresh, and rollback procedure.

## Vintages and images

- An export carries **every recorded forecast vintage** (each recorded run), so the
  exploratory pages have a **vintage selector** and default to the default-architecture
  run referenced by the default optimizer plan. Teams and players therefore appear once,
  never once per recorded run.
- Player photos and club badges are constructed from the permanent `code`/`team_code`
  keys against the external FPL CDN (`resources.premierleague.com`). A failed/missing
  image degrades to a neutral monogram chip — never to another player or club.

## Pages

The app has eleven sidebar routes: nine analytical/read-model pages (Summary, Fixture matrix, Team
analytics, Players, Player analytics, Next GW suggestion, Player prediction vs actual, Team
prediction vs actual, and Optimizer audit), the interactive Plan builder, and the browser-only
Squad draft sandbox. The legacy `#forecast-vs-actual` hash remains only as an alias to the player
comparison page and is not a twelfth navigation item.

- **Fixture matrix** (implemented, P1.7b): the fixture pivot — one row per club of the
  selected vintage, **one column per gameweek** (two chips in a double gameweek), with
  5/10/15-GW display controls. The forecast remains bounded to its recorded horizon
  (currently GW1-5); GW6-10/15 comes from a separately versioned current official-schedule
  overlay. It carries current official FDR but no later fixture lambdas, forecasts, or ease
  indices. The selected metric source owns the sortable average, each card headline, and its
  matching colour tier. **Opponent strength** shows the opponent's selected-vintage strength index
  with `Avg Opp str (GWx-y)`; **Club ease** shows the view-specific attack, defence, or overall ease
  index with `Avg Club ease (GWx-y)`; **Official FDR** shows FDR with `Avg FDR`. Later chips may use
  explicitly labelled opponent-strength or club-ease proxies composed from the selected vintage's
  GW1-5 club-average lambdas; they have no later fixture model or venue adjustment. Official FDR
  uses the current schedule-owned value.
  The overlay carries the BI-export timestamp and database hash and is explicitly not the schedule
  known at an older forecast vintage.
  The matrix is default sorted by the selected source average, highest first (any column re-sorts).
  Every measured visible leg counts, including both DGW legs and measured schedule-only cards;
  unavailable values are omitted rather than zero-filled. Changing to 10 or 15 GWs extends both
  the source average and card display with the explicitly labelled schedule values or proxies.
  Recent form is one compact
  line labelled with its anchor season (at GW1 that is *last* season). Colour source is a
  three-way toggle: **opponent strength** (default; a display-time club-quality index
  derived from the vintage's published lambdas — 100 = average club, higher = stronger
  opponent = red, so a strong club's own row is no longer uniformly green), the row club's
  model ease (overall/attack/defence views), or official FDR. Expanding a row is historical; its
  Actual scope defaults to the page-wide rolling latest five distinct season-qualified finalized
  gameweeks across the forecast season and its immediate predecessor, newest first, with explicit
  single-season options and every double-gameweek leg retained. The
  detail columns are match/GW and kickoff, opponent and venue, official GF/GA, source-row xG/xGC,
  summed BPS, and raw defensive-contribution actions. These component sums are not independently
  roster-reconciled. Rows show season plus GW. Returning clubs join across seasons only on permanent
  `team_code`; a promoted club with no prior-Premier-League row has a shorter expansion rather than
  inheriting another club's history. NULL components remain dashes. Possession and shots are
  unavailable in the approved sources. The existing FBref path is an unpopulated operator-vendored
  defensive-actions CSV and cannot provide them, so the UI does not display a proxy. Future
  fixture-level drill-down remains on Next GW only.
- **Players** (implemented, P1.7c + P1.8 code/tests): the player-form pivot from
  `players.json` plus normalized `player_actuals.json` — one row per player of the selected
  vintage (photo + club badge) merging
  a selected finalized Season–GW endpoint range with per-gameweek xP chips and a range-total xP.
  The actual scope appears once in a compact strip above the table, so the first observed leaf is
  simply `App`. A Players-only sortable `xP GW{Forecast From}` column sits immediately after
  `Pts` and defaults descending for starter/bench review. It selects the exact cumulative
  endpoint at a compatible fixed-start/all-venue scope and otherwise uses the existing strict raw
  fixture-xP sum: both DGW legs count, a true blank is 0.0, and null/duplicate/incomplete evidence
  remains a dash sorted last. It never applies the availability overlay. A one-GW selection hides
  the otherwise duplicate range-total column.
  The form-column matrix is view-specific: **Overall** = App, Starts, Min/g, G, A, xG, xA,
  xGI, xG/90, xA/90, CS, GC, Saves, DC, xGC, Bonus, BPS/App, Pts; **Attack** = App, Starts, Min/g, G,
  A, xG, xA, xGI, xG/90, xA/90, Bonus, BPS/App, Pts; **Defence** = App, Starts, Min/g, CS, GC, Saves,
  DC, xGC, Bonus, BPS/App, Pts. Position applicability is explicit: CS = GK/DEF/MID, GC and xGC
  = GK/DEF, Saves = GK, and DC = DEF/MID/FWD. A dash remains a dash for both an inapplicable
  position and an unmeasured value; the cell tooltip distinguishes the reason. These are observed
  form measures only. xGI is the display-only sum of observed xG + xA and stays unavailable when
  either component is unavailable; it is not a forecast field. BPS/App is the backward-looking
  selected-range BPS total divided by appearances: every played DGW leg counts once, DNPs are
  excluded, and incomplete appeared-fixture BPS evidence stays unavailable. The published BPS
  value on each normalized actual remains fixture-grain, while the legacy form BPS measure remains
  a total. Future
  player-level saves/DC/GC/xGC forecasts are unavailable and are not
  inferred from club lambdas or clean-sheet probabilities. Filters include a searchable
  multi-select Player box (stable player code), multi-select Position and Team boxes (permanent
  team code), price range, minimum average minutes (last 5), availability, plus the shared
  view/venue/gameweek bar, all inside a distinct Filters panel placed immediately before the
  scrollable table. Empty identity selections mean all; selections are ORed within each box and
  ANDed across boxes. Player labels include club and position to disambiguate duplicate names,
  and the option lists always come from the complete active forecast vintage rather than the
  already-filtered rows. A vintage change preserves only player/team selections that still exist,
  so no invisible stale code can keep the table empty. These multi-select controls are local to
  Players; shared decision-page filters remain scalar. Local
  development additionally offers **My squad**: a Manager ID is resolved through the trusted Plan
  Server's member-only endpoint, all 15 stable player codes plus position, club, price, and
  planning-GW metadata must match the selected forecast vintage before the scope is activated,
  and the verified membership then intersects every other filter. Unrelated league-wide registry
  additions do not block this display-only scope; the optimizer's complete-registry gate remains
  unchanged. A failed or partial
  import leaves the existing table scope unchanged. Changing forecast vintage clears the private
  scope and requires a fresh verification; hosted static builds cannot use it. Rows are compact
  and paginated. On Players, the main aggregate reads the inclusive page-wide range between its
  explicit chronological Season–GW endpoints. The endpoint options cover only the forecast season
  and its immediate predecessor, default/reset to the latest five finalized keys, join players by
  permanent `code`, retain every DGW leg, and never backfill a player outside the shared range. The
  expanded row is a separate fixed rolling history over `player_actuals.json`: it takes the
  page-wide set
  of the latest five distinct season-qualified finalized GW labels across the forecast season and
  its immediate predecessor, preserves every DGW leg, and orders the result newest first. It shows
  `Match` (season/GW, fixture-time Club, and kickoff date), `Opp (H/A)`, then minutes/start,
  goals, assists, xG,
  xA, fail-closed display xGI, clean sheets, on-pitch goals conceded, saves, raw DC actions, xGC,
  bonus, raw BPS, and points; it contains no future xP, probability, lambda, ease, or FDR field.
  Cross-season player rows join only on permanent `code`; fixture-time clubs and opponents use
  permanent `team_code` values resolved through that fixture's season. A transfer is labelled with
  the club represented by the exact actual row, while a newcomer without prior-season evidence
  stays shorter and is never matched by name or season-scoped `element_id`.
  The shared `PlayerStatTable` retains a separate forecast-detail mode for the Next GW squad table,
  which is the only future player-fixture drill-down. The failure-atomic local development database
  rebuild and atomic BI/static
  republish completed on 2026-08-19, so P1.8 values are visible in the local static UI. An existing
  database's additive columns remain NULL until rebuilt, and the final deadline vintage must repeat
  rebuild/export/republish through P0.
  Schema v4 adds the strict `player_horizons.json` outcome values: cumulative xP, `P(≤2)`, and
  `P(≥2/4/6/10/15)` at the selected exact endpoint. They always cover every fixture from the
  forecast run's start, assume independent gameweeks, and remain raw/unadjusted for the reported
  next-round availability overlay. Published scalars are six-decimal emitter values, not
  browser-derived values. The dense Players table keeps cumulative xP but omits the six
  overlapping probability columns; Player analytics exposes the exact blank/haul endpoints.
  The time axes stay separate: **Forecast GWs** filters upcoming fixtures and xP, while **Actual
  from / Actual to** selects an inclusive chronological range from the page-wide exact finalized
  Season–GW keys across the forecast season and, only when present in `player_actuals.json`, its
  immediate predecessor. The controls do not numerically interpolate absent GWs, and their default
  is the latest five available keys. A forecast range never silently reinterprets historical form
  or actuals. Deterministic insight facts follow the verified My
  squad scope, but the optional remote renderer is disabled while that private filter is active:
  manager ID, capture identity, and squad membership never enter the public insight request. The
  same fail-closed evidence rule disables the renderer for a selected player name or more than one
  Position/Team because insight request schema v4 cannot express those scopes. Empty and singleton
  Position/Team selections continue to use its exact scalar selector; deterministic facts always
  follow the visible rows.
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
  against each other, not squad quality. Three rows in the player table footer use only the
  selected platform plan: planned XI xP (11), planned bench xP (4), and planned squad xP
  (15). They are derived from each gameweek's post-transfer plan and remain fixed while the
  comparison rows are sorted, filtered, paginated, or expanded to the whole player pool.
  The highest complete bench-xP gameweek inside the loaded horizon is marked. **Forward team to
  Squad Draft** seeds the exact selected optimizer run's first-week 15 in the browser sandbox.
- **Plan builder** (implemented development-only, fresh-squad and manager paths): the interactive
  side of the manager workflow (`../docs/manager-team-suggestions.md`). **Get your team** sends a
  manager ID to the local Plan Server, previews the reconstructed 15 with bank, selling value,
  remaining free transfers, and sunk hits, and then optimizes from that immutable capture.
  Authenticated My Team access is not implemented.
  The picker exposes the full eligible priced population with shared search/filters, 50 rows per
  page, and pagination at both the top and bottom. Users can select up to five green locks and
  fifteen red exclusions; the sets are disjoint. Fresh-squad position, club-cap, population, and
  cheapest-completion budget guards remain. On the manager path locks are owned never-sell
  players, owned exclusions are forced out in the first forecast gameweek, and non-owned
  exclusions are never bought. The user can retain the reconstructed remaining FT count or record
  a 0-5 override. **Solve now** checks the forecast,
  clean worktree, Python environment, PuLP, and CBC through the local plan server, then shows
  honest stage-based preparation/optimization/publication feedback rather than a fabricated
  percentage. The exact `user_custom` run stays on Plan Builder and fails visibly if the published
  read model does not contain it; it never replaces or redirects to the formal Next GW suggestion.
  Its result is a sortable 15-player table whose first-gameweek
  XI/captain/vice/ordered-bench roles remain
  fixed while sorting. It exposes `Total 3 GWs xP`, `Total 5 GWs xP`, raw loaded-gameweek xP
  columns, and
  an expanded per-gameweek membership/role view. Its footer is bound to the exact custom plan and
  shows the same planned XI, bench, and 15-player raw xP sums, calculated from each week's
  post-transfer roles rather than the fixed first-week display membership. A manager result also
  shows HOLD or OUT/IN per gameweek, FT/cash before and after, new hits, and the separately reported
  sunk hits. Once published, it offers both **Forward suggested team to Squad Draft** and **Use
  captured current team in Squad Draft**.
- **Squad draft** (implemented development-only browser sandbox with a local import shortcut):
  without a handoff it binds to exactly
  one formal platform-default forecast vintage. An explicit `optimizer_run_id` handoff from Next GW
  or Plan Builder instead resolves that exact plan, matching audit/rules snapshot, and forecast
  vintage, then replaces the browser draft with its first-week optimized 15. The handoff fails
  closed on a missing/ambiguous run, mismatched audit, missing player, or structurally invalid
  squad. A manager-current handoff reloads the exact private capture instead. The page's direct
  **Fetch current team** shortcut creates a new manager capture and atomically replaces the draft
  only after all 15 players map into the exact selected forecast/rules context; failure preserves
  the old draft. This non-optimizer import uses the member-only endpoint, so an unrelated new
  league registration does not block it; any owned-player position, club, or deadline-price drift
  still fails atomically. The user can then select zero to 15 players manually. It enforces duplicate, position,
  squad-size, and three-per-club
  limits but deliberately does not enforce the standard £100m budget; an over-budget draft is
  labelled as such rather than blocked. The sortable/fullscreen selected-player table shows
  deadline-vintage cost, raw loaded-gameweek xP, strict Total 3/5-GW xP, and a final footer row
  whose cost
  and xP totals remain invariant under sorting. Draft state is isolated in versioned
  run-qualified browser storage and never calls the optimizer or replaces a platform/custom
  plan. Its best-legal-XI/bench and highest-player screens are loaded-horizon planning context,
  not chip recommendations: direct import provides only the captured current 15 and values;
  chip optimization, autosubs, captain fallback, competing chip windows, authenticated account
  state, and the rest of the season remain unavailable.
- **Player prediction vs actual** (implemented development-only, P2.3): scores one recorded
  player-gameweek only after the official gameweek and every forecast fixture leg are final. A
  partial double gameweek contributes no scored observation. It reads
  `player_forecast_vs_actual.json`, reports coverage/finality, xP versus replayed points, signed
  residual (`actual - forecast`), MAE/RMSE/CRPS, slices, calibration, and exact tables. The legacy
  `#forecast-vs-actual` hash aliases this page. It defaults to the newest vintage with scored rows;
  newer pending vintages remain selectable.
- **Team prediction vs actual** (implemented development-only, P2.3): reads
  `team_forecast_vs_actual.json` at directed team-fixture grain. Attack CRPS scores the named
  club's exact stored goals PMF; defence CRPS scores the opponent's exact PMF; neither PMF is
  recreated from a lambda or sent to the browser. Clean-sheet Brier uses the published probability.
  Positive attack residual means more goals scored than forecast; positive defence residual means
  more conceded than forecast and is worse. Coverage/finality and exact table equivalents remain
  visible when no prospective outcomes are attached. It uses the same newest-scored-vintage
  default while retaining every published vintage in the selector.
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
- Plan-table footer totals are raw player-model xP summaries for one selected plan. The captain
  is counted once like every other player; captain multipliers, hits, normal autosubs, and
  vice-captain fallback are excluded. Nulls propagate, and sorting or filtering the player rows
  never changes the full plan totals. The highest bench-xP marker is a loaded-horizon screen, not
  season advice: chip inventory, competing chip windows, the full season, and future measured
  availability are unavailable, and the optimizer itself does not optimize bench points.
- Squad Draft totals use only the selected browser draft and one exact formal forecast vintage.
  A true blank gameweek contributes zero, while missing or non-finite forecast values make the
  dependent total unmeasured; partial sums are never shown as complete totals.
- Expected points may be summed from complete published values. Probabilities may never be added,
  subtracted, complemented, or reconstructed from PMFs in JavaScript. Filtering/sorting player
  records and drawing presentation geometry are allowed. Any future CCDF drill-down must load a
  small backend-precomputed shard; the bulk payload contains no PMF.
- Deep-analytics charts may compute direction-labelled Pareto and quadrant display geometry from
  direct published axes. They are not optimizers. Team expected clean sheets is explicitly a sum of
  per-fixture probabilities (an expected count), never labelled as a probability.
- The analytics pages label that nondominated set as an efficient frontier and provide chart-only
  horizontal min/max and frontier-focus controls for crowded plots. Frontier membership is still
  classified on every filtered eligible row; the exact table and insight facts do not change, and
  the page reports hidden points. Probability-axis inputs use displayed percent units. This is not
  a Markowitz mean-variance/Sharpe frontier: a portfolio view would require backend-published joint
  samples or covariances plus squad constraints.
- Player analytics defaults to **Established evidence**, excluding only rows whose selected
  forecast explicitly publishes `cold_start_player=true`; **Include cold starts** restores them.
  This reporting filter changes the eligible Pareto population, not any forecast value. A
  three-appearance probability bridge would require separately named, pre-registered model
  research and evaluation; it is not part of this reporting change.
- Every analytics view includes concise How-to-read guidance. Visible tooltips use short labels,
  flip at chart edges to avoid clipping, and retain full exact provenance in accessible names and
  the authoritative table.
- Past-vs-future form is latest at static export, not frozen at a selected forecast vintage. Those
  views show the per-row season/gameweek form anchor and warn that form can post-date an older run;
  it remains context only and is never treated as future utility or a model input. Form
  availability still gates which context points are axis-complete.
- Every route's implemented deterministic insight panel derives from visible published facts. Any
  optional remote explanation is explicit opt-in, cites allowlisted fact ids, never receives
  private manager/custom-plan state, and never supplies canonical numbers.
