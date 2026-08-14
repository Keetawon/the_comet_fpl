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

Commands are PowerShell from the repository root (`D:\Personal\workspace\the_comet_fpl`). Every
execution gets a new timestamp/commit directory under `D:\tmp\gw1\`; rehearsal, preliminary, and
deadline vintages never reuse a path. Substitute an equivalent out-of-repo root if preferred.
`uv run` equivalents are acceptable.

```powershell
$ErrorActionPreference = "Stop"
$outRoot = "D:\tmp\gw1"
$runKind = "rehearsal"  # use "preliminary" or "deadline" on those runs
$deadline = "2026-08-21T17:30:00Z"
```

## Step 1 — Verify a clean `main` and authoritative `origin/main`

```powershell
git rev-parse --abbrev-ref HEAD          # expect: main
git fetch origin main -q
if ($LASTEXITCODE -ne 0) { throw "git fetch failed" }
git status --porcelain --untracked-files=all   # expect: no output (clean)
git rev-parse HEAD origin/main           # note both; they must match after Step 2
```

Verify: the branch is `main` and the worktree is clean. If the worktree is dirty, stop and resolve
it before syncing — do not stash-and-forget a real change.

## Step 2 — Sync only when the worktree is clean

```powershell
# Only if Step 1 showed a clean worktree:
git checkout -B main origin/main -q
if ($LASTEXITCODE -ne 0) { throw "main checkout failed" }
git reset --hard origin/main -q
if ($LASTEXITCODE -ne 0) { throw "main reset failed" }
git rev-parse HEAD origin/main           # expect: identical SHAs
$head = git rev-parse HEAD
$runStamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$out = Join-Path $outRoot "$runStamp-$($head.Substring(0, 12))-$runKind"
if (Test-Path -LiteralPath $out) { throw "immutable run directory already exists: $out" }
New-Item -ItemType Directory -Path $out | Out-Null
Set-Content -LiteralPath (Join-Path $out "RUN-HEAD.txt") -Value $head -NoNewline
```

Verify: `HEAD == origin/main`, and note the new unique `$out`. The daily live snapshots are the
irreplaceable input; they are already committed, so a hard reset to `origin/main` cannot lose them.

## Step 3 — Verify the latest committed snapshot manifest and the GW1 deadline

```powershell
# Resolve the latest committed package and inspect its summary manifest:
$latestSnapshot = Get-ChildItem snapshots\daily\*\* -Directory |
    Sort-Object FullName | Select-Object -Last 1
$latestSnapshot.FullName
Get-Content -Raw (Join-Path $latestSnapshot.FullName "manifest.json")

# SHA256SUMS, not manifest.json, is the payload checksum contract:
$sumFile = Join-Path $latestSnapshot.FullName "SHA256SUMS"
Get-Content $sumFile | ForEach-Object {
    $expected, $relative = $_ -split "\s+", 2
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $relative.Trim()).Hash.ToLowerInvariant()
    if ($actual -ne $expected.ToLowerInvariant()) {
        throw "snapshot checksum mismatch: $relative"
    }
}
git status --porcelain --untracked-files=all  # still expect no output
```

Verify: the summary manifest reports season `2026-27`, 20 teams, 380 fixtures,
`fixtures_first_kickoff = 2026-08-21T19:00:00Z`, and
`bootstrap_first_deadline = 2026-08-21T17:30:00Z`. The checksum loop must finish silently. Confirm
the capture is committed and recent; the freshness gate treats a pre-GW1 cutoff as a legitimate
season-start cold start.

## Step 4 — Build DuckDB

```powershell
.\.venv\Scripts\python.exe -m fpl.jobs.build_db
if ($LASTEXITCODE -ne 0) { throw "database build failed" }
```

Verify: the job completes and promotes the database with one atomic replacement. `build_db` preserves
existing live snapshot state and refuses to overwrite a concurrently changed target.

## Step 5 — Load snapshots sequentially

```powershell
# Daily captures. Run sequentially; DuckDB is single-writer.
Get-ChildItem snapshots\daily\*\* -Directory | Sort-Object FullName | ForEach-Object {
    .\.venv\Scripts\python.exe -m fpl.jobs.load_snapshots $_.FullName
    if ($LASTEXITCODE -ne 0) { throw "daily snapshot load failed: $($_.FullName)" }
}
# Any finalized player-history packages, if present:
Get-ChildItem snapshots\player-history\*\* -Directory -ErrorAction SilentlyContinue |
    Sort-Object FullName | ForEach-Object {
        .\.venv\Scripts\python.exe -m fpl.jobs.load_snapshots $_.FullName
        if ($LASTEXITCODE -ne 0) { throw "player-history load failed: $($_.FullName)" }
    }
```

Verify: each load revalidates the committed package checksums and commits atomically. A checksum
mismatch or loader error rolls that package back; stop and investigate rather than proceeding.

## Step 6 — Run the full local gate

```powershell
.\.venv\Scripts\pytest.exe -q
if ($LASTEXITCODE -ne 0) { throw "pytest gate failed" }
.\.venv\Scripts\ruff.exe check src tests
if ($LASTEXITCODE -ne 0) { throw "Ruff lint gate failed" }
.\.venv\Scripts\ruff.exe format --check .
if ($LASTEXITCODE -ne 0) { throw "Ruff format gate failed" }
.\.venv\Scripts\mypy.exe src
if ($LASTEXITCODE -ne 0) { throw "mypy gate failed" }
```

Verify: all four are green. Do not generate a deadline forecast from a checkout that fails the gate.

## Step 7 — Generate the default GW1-5 artifact

Defaults are the frozen decision defaults (`attacking=v3`, `assists=coupled`, `appearance=seasonal`,
`share-signal=auto`), so they need no flags. Output goes outside the repo.

```powershell
$default = "$out\prospective-2026-27-gw1-5-default.jsonl"
.\.venv\Scripts\python.exe -m fpl.jobs.prospective_points_v1 --output $default
if ($LASTEXITCODE -ne 0) { throw "default forecast failed" }
(Get-FileHash -Algorithm SHA256 $default).Hash        # record the artifact SHA-256
```

Verify: the job prints the DEVELOPMENT-ONLY disclaimer and a leaderboard, and logs the written row
count and SHA-256. It refuses output from a dirty worktree. Record the SHA-256.

## Step 8 — Generate the V1/V1 diagnostic before any ledger write

The diagnostic must use the identical cutoff, horizon, draws, seed, database, and live captures as
the default; only the two component flags differ. Generate it now, while DuckDB is still byte-for-
byte unchanged. Recording a forecast mutates the ledger inside DuckDB, so recording the default
first would make the diagnostic's database hash different.

```powershell
$diag = "$out\prospective-2026-27-gw1-5-v1v1.jsonl"
.\.venv\Scripts\python.exe -m fpl.jobs.prospective_points_v1 --attacking v1 --assists v1 --output $diag
if ($LASTEXITCODE -ne 0) { throw "diagnostic forecast failed" }
(Get-FileHash -Algorithm SHA256 $diag).Hash
```

## Step 9 — Prove input parity, then record both artifacts sequentially

Check the immutable manifests before allowing either ledger mutation:

```powershell
$defaultManifest = Get-Content -LiteralPath $default -TotalCount 1 | ConvertFrom-Json
$diagManifest = Get-Content -LiteralPath $diag -TotalCount 1 | ConvertFrom-Json
foreach ($field in @("as_of", "season", "gw_from", "gw_to", "base_seed",
                     "monte_carlo_draws", "database_sha256")) {
    if ($defaultManifest.$field -ne $diagManifest.$field) {
        throw "default/diagnostic provenance mismatch: $field"
    }
}
$defaultLive = $defaultManifest.live_inputs | ConvertTo-Json -Depth 10 -Compress
$diagLive = $diagManifest.live_inputs | ConvertTo-Json -Depth 10 -Compress
if ($defaultLive -ne $diagLive) { throw "default/diagnostic live-input provenance mismatch" }
$defaultContracts = $defaultManifest.contracts | ConvertTo-Json -Depth 10 -Compress
$diagContracts = $diagManifest.contracts | ConvertTo-Json -Depth 10 -Compress
if ($defaultContracts -ne $diagContracts) { throw "default/diagnostic contract mismatch" }
if ($defaultManifest.component_modes.attacking_mode -ne "v3" -or
    $defaultManifest.component_modes.assists_mode -ne "coupled" -or
    $defaultManifest.component_modes.appearance_mode -ne "seasonal") {
    throw "default artifact does not use the frozen decision architecture"
}
if ($diagManifest.component_modes.attacking_mode -ne "v1" -or
    $diagManifest.component_modes.assists_mode -ne "v1" -or
    $diagManifest.component_modes.appearance_mode -ne "seasonal") {
    throw "diagnostic artifact does not use the declared V1/V1 architecture"
}

.\.venv\Scripts\python.exe -m fpl.jobs.record_forecast $default 2>&1 |
    Tee-Object -FilePath (Join-Path $out "ledger-default.txt")
if ($LASTEXITCODE -ne 0) { throw "default ledger recording failed" }
.\.venv\Scripts\python.exe -m fpl.jobs.record_forecast $diag 2>&1 |
    Tee-Object -FilePath (Join-Path $out "ledger-v1v1.txt")
if ($LASTEXITCODE -ne 0) { throw "diagnostic ledger recording failed" }
```

Retain both printed ledger run IDs. Re-recording is an idempotent no-op, never a duplicate or
overwrite. The V1/V1 path remains diagnostic only; it cannot change the default or promote a model.

## Step 10 — Optimize both artifacts at `risk_lambda=0` into immutable optimizer artifacts

```powershell
$defaultPlan = "$out\optimizer-plan-default.json"
$diagPlan    = "$out\optimizer-plan-v1v1.json"
.\.venv\Scripts\python.exe -m fpl.jobs.optimize_squad $default --risk-lambda 0 --output $defaultPlan
if ($LASTEXITCODE -ne 0) { throw "default optimization failed" }
.\.venv\Scripts\python.exe -m fpl.jobs.optimize_squad $diag    --risk-lambda 0 --output $diagPlan
if ($LASTEXITCODE -ne 0) { throw "diagnostic optimization failed" }
```

Verify: each run prints its plan to stdout and writes an immutable, provenance-bearing artifact
(see `docs/stage-e-squad-optimizer.md`). The write refuses a dirty worktree, refuses to overwrite an
existing destination, and embeds a `decision_sha256` plus a `run_id` derived from the decision and
complete behaviour-defining provenance.
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
- **Squad legality.** The optimizer artifact reader independently validates all initial and weekly
  squads against its content-hashed rule snapshot: budget, club cap, position quotas, formation,
  lineup/bench partition, captain/vice, transfer deltas/free-transfer state/hits, horizon, and
  aggregate point reconciliation.
- **Run identities.** Record each optimizer `run_id`, `decision_sha256`, and ledger `run_id`.
  Re-optimizing identical bytes under the same clean commit/solver/search policy reproduces both
  optimizer hashes and identical decision content.

```powershell
# Example spot-checks (PowerShell + jq-style inspection via python):
foreach ($p in @($defaultPlan, $diagPlan)) {
  .\.venv\Scripts\python.exe -c @"
import sys
from pathlib import Path
from fpl.artifacts.optimizer_plan import read_optimizer_artifact
d = read_optimizer_artifact(Path(sys.argv[1]))
w0 = d.plan.weeks[0]
print('run_id', d.run_id, 'decision_sha256', d.decision_sha256)
print('squad', len(d.initial_squad.members), 'cost', d.initial_squad.cost_tenths,
      'weeks', len(d.plan.weeks), 'xi', len(w0.starting_xi),
      'cap', w0.captain.code, 'vice', w0.vice_captain.code)
"@ $p
}
```

Verify: both reads succeed, squad is 15, cost is at most 1000, weeks is five, XI is 11, and both
hashes are printed. Any illegal/tampered decision fails before the summary prints.

## Step 12 — Retain both vintages and produce the comparison

Keep both forecast JSONLs, both ledger `run_id`s, and both optimizer artifacts, then produce the
DEV-ROADMAP P0.3 decision comparison with the dedicated job. It reads only the four frozen artifacts,
touches no database, and re-derives each ledger `run_id` from that forecast's own manifest and
canonical bytes, so nothing is re-forecast or re-solved:

```powershell
$comparison = "$out\decision-comparison.json"
$comparisonReport = "$out\decision-comparison.md"
.\.venv\Scripts\python.exe -m fpl.jobs.compare_decisions `
  --default-forecast $default --default-plan $defaultPlan `
  --diagnostic-forecast $diag --diagnostic-plan $diagPlan `
  --output $comparison --report $comparisonReport
if ($LASTEXITCODE -ne 0) { throw "decision comparison failed" }
```

Verify: the job prints the Markdown decision aid, writes both outputs immutably (no-clobber), and
records a `comparison_id` covering both paths' content hashes and run identities. It **fails closed**
rather than producing a misleading report: the two forecasts must share `as_of`, season, horizon,
database, seed, draws, live captures and contracts and must differ in `component_modes`; each plan
must name the forecast it is paired with; and each plan's first-gameweek expected points must
reconcile to that forecast's own rows. Re-running with identical inputs reproduces the artifact bit
for bit.

The report covers what P0.3 requires: selected 15, cost, ownership, GW1 EV and GW1-5 EV, GW1
XI / captain / vice / ordered bench, players common to both paths and players unique to either,
captain agreement with a **cross-evaluated** EV gap (each model scores both captains, so the gap is
never taken across two different scales), availability/status and every cold-start / Stage A
league-average / attacking / assist / transfer flag, the bounded transfer scenario and any hits with
the frozen-price caveat, and all provenance and ledger/optimizer run IDs.

The comparison is a decision aid, not a promotion test. Do not choose a model because one named player
looks more plausible. The GW1 lineup and captaincy are read from the GW1 (first) week of the default
optimizer artifact; the GW1-5 horizon informs initial squad value.

## Deadline-day timing

- **By 2026-08-15:** finish and gate the durable optimizer artifact implementation.
- **By 2026-08-18:** run Steps 1-12 with `$runKind = "rehearsal"` on the latest committed snapshot.
  Retain it as a real pre-deadline vintage and a safe fallback if the final capture or machine fails.
- **On 2026-08-20:** run a preliminary vintage with `$runKind = "preliminary"`; retain it as the
  preferred fallback if deadline-day capture cannot complete safely.
- **On 2026-08-21, roughly 2-3 hours before the deadline:** capture the latest official data with
  the exact repository job below, verify and commit that new snapshot package, push it, verify the
  worktree is clean, then rerun Steps 1-12 with `$runKind = "deadline"` on that committed HEAD.

```powershell
.\.venv\Scripts\python.exe -m fpl.jobs.daily_snapshot
if ($LASTEXITCODE -ne 0) { throw "deadline snapshot failed" }

$capturedSnapshot = Get-ChildItem snapshots\daily -Directory -Recurse |
  Where-Object { Test-Path (Join-Path $_.FullName "manifest.json") } |
  Sort-Object FullName -Descending |
  Select-Object -First 1
if ($null -eq $capturedSnapshot) { throw "no captured snapshot package found" }

Get-Content (Join-Path $capturedSnapshot.FullName "manifest.json")
Get-Content (Join-Path $capturedSnapshot.FullName "SHA256SUMS") | ForEach-Object {
  $parts = $_ -split "  ", 2
  if ($parts.Count -ne 2) { throw "malformed SHA256SUMS line: $_" }
  $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $parts[1]).Hash.ToLowerInvariant()
  if ($actual -ne $parts[0].ToLowerInvariant()) {
    throw "snapshot checksum mismatch: $($parts[1])"
  }
}

git add -- $capturedSnapshot.FullName
git status --short
git config user.email noreplyanthropic.com
git config user.name Claude
git commit -m "Capture 2026/27 GW1 deadline snapshot" `
  -m "Co-Authored-By Claude Opus 4.8 noreplyanthropic.com" `
  -m "Claude-Session https//claude.ai/code/session_01KJ48EQQXUVw6TGZQ2ib37h"
# Publish the exact committed capture before rebuilding and running the decision procedure.
git push -u origin main
if ((git status --porcelain --untracked-files=all)) {
  throw "worktree must be clean before the deadline decision run"
}
```

- **No later than 30 minutes before the deadline:** lock the owner decision. Do not trade
  reproducibility for a last-minute unrecorded refresh; any late news-driven override is recorded
  separately from the model output, with its time and reason.
