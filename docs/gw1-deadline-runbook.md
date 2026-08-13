# GW1 deadline runbook

Status: operational runbook for the 2026/27 GW1 decision pack. Development-only outputs.

This is the single, sequential procedure for producing the auditable GW1 squad, XI, captain,
vice-captain, and bench before the deadline, plus the diagnostic comparison DEV-ROADMAP P0.3
requires. It composes existing entry points; it introduces no new business logic. `AGENTS.md` remains
the authority for correctness and frozen contracts, and `DEV-ROADMAP.md` for delivery sequence.

- **Deadline:** `2026-08-21T17:30:00Z` (`2026-08-22 00:30` Asia/Bangkok).
- **First kickoff:** `2026-08-21T19:00:00Z`.
- **Default forecast horizon:** GW1-5. The GW1 row is read from that artifact; GW1 is never
  forecast a second time on its own.

## Invariants this runbook must not violate

- **The GW1 view is read from the GW1-5 artifact.** The five-gameweek horizon informs initial squad
  value; the GW1 row informs the lineup and captaincy. Do not generate a separate single-gameweek
  forecast to filter one gameweek.
- **The V1/V1 path is a diagnostic comparator only.** Run it beside the default and report
  disagreements. It cannot change the default (`attacking=v3`, `assists=coupled`,
  `appearance=seasonal`, `share-signal=auto`) and it cannot promote a model.
- **Next-round availability is valid for GW1 only.** The `chance_of_playing_next_round` overlay is
  applied to GW1 in the decision view. Its reuse across GW2-5 is an explicit scenario assumption,
  labelled as such, never presented as measured.
- **Later prices and selling values are static/unknown.** All gameweeks use the deadline `now_cost`.
  GW2-5 affordability and any transfer plan are frozen-price scenarios, not price forecasts.
- **A manual owner decision never modifies a stored distribution.** A late news-driven change is
  recorded separately, with its time and reason, beside the model output — never edited into it.
- **DuckDB jobs run sequentially.** DuckDB is single-writer; never run two of these jobs against the
  same database at once.
- **No frozen historical evaluation is rerun, amended, or reinterpreted.** This runbook produces
  prospective forecasts and a decision; it touches none of the frozen archive results.
- **All deadline outputs are immutable and identified by SHA-256 and run IDs.** Write generated
  artifacts OUTSIDE the repository so they never dirty the checkout; every forecast and optimizer
  job refuses to emit from a dirty worktree, and the optimizer artifact refuses to overwrite an
  existing destination.

## Conventions

Commands are PowerShell from the repository root (`D:\Personal\workspace\the_comet_fpl`). Generated
artifacts go under `D:\tmp\gw1\` so they never dirty the checkout. Substitute an equivalent
out-of-repo directory if you prefer. `uv run` equivalents are acceptable.

```powershell
$ErrorActionPreference = "Stop"
$out = "D:\tmp\gw1"
New-Item -ItemType Directory -Force -Path $out | Out-Null
$deadline = "2026-08-21T17:30:00Z"
```

## Step 1 — Verify a clean `main` and authoritative `origin/main`

```powershell
git rev-parse --abbrev-ref HEAD          # expect: main
git fetch origin main -q
git status --porcelain --untracked-files=all   # expect: no output (clean)
git rev-parse HEAD origin/main           # note both; they must match after Step 2
```

Verify: the branch is `main` and the worktree is clean. If the worktree is dirty, stop and resolve
it before syncing — do not stash-and-forget a real change.

## Step 2 — Sync only when the worktree is clean

```powershell
# Only if Step 1 showed a clean worktree:
git checkout -B main origin/main -q
git reset --hard origin/main -q
git rev-parse HEAD origin/main           # expect: identical SHAs
```

Verify: `HEAD == origin/main`. The daily live snapshots are the irreplaceable input; they are already
committed, so a hard reset to `origin/main` cannot lose them.

## Step 3 — Verify the latest committed snapshot manifest and the GW1 deadline

```powershell
# The most recent committed daily snapshot directory and its manifest:
Get-ChildItem snapshots\daily | Sort-Object Name | Select-Object -Last 1
Get-Content (Get-ChildItem snapshots\daily\*\*\manifest.json | Sort-Object FullName | Select-Object -Last 1).FullName
```

Verify: the manifest lists the expected endpoints (`bootstrap-static`, `fixtures`, event-live) with
checksums, and its capture time is recent. Confirm the official GW1 deadline is `2026-08-21T17:30:00Z`
(the forecaster's default `as_of`). The freshness gate treats a pre-GW1 cutoff as a legitimate
season-start cold start.

## Step 4 — Build DuckDB

```powershell
.\.venv\Scripts\python.exe -m fpl.jobs.build_db
```

Verify: the job completes and promotes the database with one atomic replacement. `build_db` preserves
existing live snapshot state and refuses to overwrite a concurrently changed target.

## Step 5 — Load snapshots sequentially

```powershell
# Daily captures. Run sequentially; DuckDB is single-writer.
Get-ChildItem snapshots\daily\*\* -Directory | Sort-Object FullName | ForEach-Object {
    .\.venv\Scripts\python.exe -m fpl.jobs.load_snapshots $_.FullName
}
# Any finalized player-history packages, if present:
Get-ChildItem snapshots\player-history\*\* -Directory -ErrorAction SilentlyContinue |
    Sort-Object FullName | ForEach-Object {
        .\.venv\Scripts\python.exe -m fpl.jobs.load_snapshots $_.FullName
    }
```

Verify: each load revalidates the committed package checksums and commits atomically. A checksum
mismatch or loader error rolls that package back; stop and investigate rather than proceeding.

## Step 6 — Run the full local gate

```powershell
.\.venv\Scripts\pytest.exe -q
.\.venv\Scripts\ruff.exe check src tests
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\mypy.exe src
```

Verify: all four are green. Do not generate a deadline forecast from a checkout that fails the gate.

## Step 7 — Generate the default GW1-5 artifact

Defaults are the frozen decision defaults (`attacking=v3`, `assists=coupled`, `appearance=seasonal`,
`share-signal=auto`), so they need no flags. Output goes outside the repo.

```powershell
$default = "$out\prospective-2026-27-gw1-5-default.jsonl"
.\.venv\Scripts\python.exe -m fpl.jobs.prospective_points_v1 --output $default
(Get-FileHash -Algorithm SHA256 $default).Hash        # record the artifact SHA-256
```

Verify: the job prints the DEVELOPMENT-ONLY disclaimer and a leaderboard, and logs the written row
count and SHA-256. It refuses output from a dirty worktree. Record the SHA-256.

## Step 8 — Record the default artifact in the append-only ledger before the deadline

```powershell
.\.venv\Scripts\python.exe -m fpl.jobs.record_forecast $default
```

Verify: it prints `recorded run <run_id>: 2026-27 GW1-5, <N> predictions, as_of 2026-08-21T17:30:00Z`.
Record the ledger `run_id`. Re-running is an idempotent no-op (`already recorded; ledger unchanged`),
never a duplicate or an overwrite. This is the pre-deadline commitment; do it before the deadline.

## Step 9 — Generate and record the V1/V1 diagnostic on identical inputs

The diagnostic must use the identical cutoff, horizon, draws, seed, database, and live captures as the
default; only the two component flags differ. The forecaster's `as_of`, horizon, seed, and draws are
already fixed defaults, so passing only `--attacking v1 --assists v1` holds everything else equal.

```powershell
$diag = "$out\prospective-2026-27-gw1-5-v1v1.jsonl"
.\.venv\Scripts\python.exe -m fpl.jobs.prospective_points_v1 --attacking v1 --assists v1 --output $diag
(Get-FileHash -Algorithm SHA256 $diag).Hash
.\.venv\Scripts\python.exe -m fpl.jobs.record_forecast $diag
```

Verify: same `as_of`, `gw_from`, `gw_to`, `base_seed`, `monte_carlo_draws`, `database_sha256`,
`bootstrap_capture_id`, and `schedule_capture_ids` in both manifests (line one of each JSONL); only
`component_modes` differs. This path is diagnostic only — it cannot change the default or promote a
model.

## Step 10 — Optimize both artifacts at `risk_lambda=0` into immutable optimizer artifacts

```powershell
$defaultPlan = "$out\optimizer-plan-default.json"
$diagPlan    = "$out\optimizer-plan-v1v1.json"
.\.venv\Scripts\python.exe -m fpl.jobs.optimize_squad $default --risk-lambda 0 --output $defaultPlan
.\.venv\Scripts\python.exe -m fpl.jobs.optimize_squad $diag    --risk-lambda 0 --output $diagPlan
```

Verify: each run prints its plan to stdout and writes an immutable, provenance-bearing artifact
(see `docs/stage-e-squad-optimizer.md`). The write refuses a dirty worktree, refuses to overwrite an
existing destination, and embeds a `run_id` derived only from the behaviour-defining provenance.
`risk_lambda=0` is the expected-value objective; any positive-`risk_lambda` run is a clearly labelled
sensitivity analysis and never replaces the EV result.

## Step 11 — Verify the outputs

Confirm, for each artifact:

- **Forecast manifest and hashes.** Line one of each JSONL is the manifest. Check `row_count ==
  roster_size * (gw_to - gw_from + 1)`, the `worktree_clean` flag is `true`, and the recorded
  `database_sha256`, `commit_sha`, and contract SHA-256 values are present. Re-hash each JSONL and
  compare to the SHA-256 you recorded in Steps 7 and 9.
- **Knowledge time.** `bootstrap_known_at <= as_of` and every schedule capture is `known_at <= as_of`
  (the forecaster selects only such captures; confirm the manifest's `as_of` is the deadline).
- **Row accounting and PMFs.** Every forecast row's `distribution` is finite, non-negative, sums to
  one within `1e-9`, and reconciles to `expected_points`; the artifact reader enforces this, so a
  clean `record_forecast` and a clean `optimize_squad` read are the check.
- **Squad legality.** In each optimizer artifact, `initial_squad.members` has 15 unique players,
  `cost_tenths <= 1000` (budget), at most three players share a `team_id` (club cap), and each week's
  formation obeys 1 GK / 3-5 DEF / 2-5 MID / 1-3 FWD with 11 starters, one captain, and a distinct
  vice-captain. The optimizer enforces these; verification is reading them back.
- **Run identities.** Record each optimizer `run_id` and each ledger `run_id`. Re-optimizing the same
  artifact with the same options reproduces the same optimizer `run_id` and identical decision
  content.

```powershell
# Example spot-checks (PowerShell + jq-style inspection via python):
foreach ($p in @($defaultPlan, $diagPlan)) {
  .\.venv\Scripts\python.exe -c @"
import json, sys
d = json.load(open(sys.argv[1], encoding='utf-8'))
m = d['initial_squad']['members']
codes = [x['code'] for x in m]
clubs = {}
for x in m: clubs[x['team_id']] = clubs.get(x['team_id'], 0) + 1
w0 = d['plan']['weeks'][0]
print('run_id', d['run_id'])
print('squad_ok', len(codes) == 15 and len(set(codes)) == 15,
      'cost', d['initial_squad']['cost_tenths'],
      'max_per_club', max(clubs.values()),
      'xi', len(w0['starting_xi']),
      'cap', w0['captain']['code'], 'vice', w0['vice_captain']['code'])
"@ $p
}
```

Verify: `squad_ok` is `True`, `cost <= 1000`, `max_per_club <= 3`, `xi == 11`, and captain != vice.

## Step 12 — Retain both vintages and produce the comparison

Keep both forecast JSONLs, both ledger `run_id`s, and both optimizer artifacts. Produce the decision
comparison DEV-ROADMAP P0.3 specifies (default vs diagnostic): selected 15, cost, ownership, GW1 EV
and GW1-5 EV, GW1 XI / captain / vice / ordered bench, players common to both paths and players unique
to either, captain agreement and the EV gap between alternatives, availability/status and every
cold-start / Stage A league-average / attacking / assist / transfer flag, the bounded transfer
scenario and any hits with the frozen-price caveat, and all provenance and ledger/optimizer run IDs.

The comparison is a decision aid, not a promotion test. Do not choose a model because one named player
looks more plausible. The GW1 lineup and captaincy are read from the GW1 (first) week of the default
optimizer artifact; the GW1-5 horizon informs initial squad value.

## Deadline-day timing

- **On 2026-08-20:** run Steps 1-12 once as a rehearsal on the latest committed snapshot and record it
  as a real pre-deadline vintage — a safe fallback if the final capture or the machine fails.
- **On 2026-08-21, roughly 2-3 hours before the deadline:** capture and commit the latest official data
  (daily snapshot), then rerun Steps 1-12 on that HEAD.
- **No later than 30 minutes before the deadline:** lock the owner decision. Do not trade
  reproducibility for a last-minute unrecorded refresh; any late news-driven override is recorded
  separately from the model output, with its time and reason.
