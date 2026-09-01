# Provisional completed-match data refresh

## Purpose and correctness boundary

FPL exposes two different completion states. `finished_provisional=true` means the match has ended
and the website can show a score and provisional player statistics. `finished=true` is the later
API flag required by the repository's official outcome-attachment path, but the flag by itself is
not an immutable ledger row or a finalized dashboard actual.

The early-view pipeline preserves that distinction:

1. `.github/workflows/provisional-player-history.yml` captures completed fixture legs and their
   full player histories into a timestamped, append-only provisional package.
2. `.github/workflows/player-history.yml` independently captures the authoritative package after
   bootstrap reports the gameweek `finished=true`.
3. `fpl.jobs.attach_outcomes` remains unchanged and accepts only final fixture versions. Provisional
   rows must never enter prediction-versus-actual scores, calibration, CRPS, or model evaluation.

A non-null score is not enough to call a match complete because live matches also have scores. The
capture gate requires both home/away scores and either `finished_provisional=true` or
`finished=true`. A partially played weekend is valid preview scope: each completed leg can appear,
while in-progress and future legs remain absent.

The BI preview uses a shared fixture-level handoff rule. A scored fixture with either completion
flag remains explicitly provisional display evidence until any row exists for that fixture in
`mart_fact_player_fixture`, `mart_fact_team_match`, `ledger_outcome_player_fixture`, or
`ledger_outcome_team_fixture`. At that first final-evidence row, both provisional facts exclude the
entire fixture atomically—no partial player roster or single provisional club side survives. The
finalized actual and prediction-monitoring gates remain unchanged.

## Durable schedule

Bangkok does not observe daylight saving time, so the UTC schedules are stable:

| Workflow | UTC | Bangkok | Result |
| --- | ---: | ---: | --- |
| Provisional history | 01:00 daily | 08:00 daily | First morning preview |
| Provisional recovery | 05:00 daily | 12:00 daily | Picks up late corrections |
| Lightweight API snapshot | 06:00 daily | 13:00 daily | Bootstrap, fixtures, event-live safety net |
| Finalized player history | 07:30 daily | 14:30 daily | Writes only after official GW finality advances |

All jobs use the same `api-snapshot` concurrency group. They never cancel an in-progress capture.
The 08:00 provisional pass may compare a cheap signal with previous packages before the expensive
sweep. Its fixture projection covers every score-present provisional/final fixture, not only the
numerically latest GW, so an older or postponed schedule/result correction cannot be silently
skipped. The complete latest-GW event-live payload supplies the player aggregate part of that
change signal; element-summary remains the authoritative fixture-grain source.

The 12:00 recovery and every `workflow_dispatch` always perform the authoritative full supported-
player element-summary sweep even when the cheap signal matches. Only after canonical payload
hashing may an identical `content_sha256` produce a no-op. Each HTTP response has an endpoint-
specific maximum file size enforced both by curl and by a post-download byte check. Before ids are
crosswalked, the workflow rejects a fixtures payload whose first kickoff precedes bootstrap's first
deadline—the known season-rollover skew. After the sweep it refetches bootstrap, fixtures, and the
latest-GW event-live payload, refuses any changed signal or scored-GW set, and requires at least 20
aggregate history rows for every eligible fixture. The coverage check is per fixture rather than
per player, so a legitimately unused player is not rejected. Within each element-summary payload,
every history row must name the requested element and each fixture id may appear at most once.

Provisional packages live at:

```text
snapshots/player-history-provisional/<season>/gw-<gw>/<UTC timestamp>-<content hash prefix>/
```

Each directory contains compressed bootstrap, fixture, latest-event-live, and full element-summary
payloads, `SHA256SUMS`, and a manifest. The manifest's signal gameweeks and completed/provisional/
final fixture-id arrays cover the full scored capture scope. It also records the eligible-fixture
count and the minimum per-fixture history-row threshold. The content hash is computed from canonical
payload hashes, not archive timestamps. An existing target is never overwritten; the cheap 08:00
pass may no-op on an identical signal, while recovery/manual passes no-op only after an identical
full-sweep `content_sha256`.

## Loading a package locally

The GitHub workflow commits raw packages; it does not mutate a developer's local DuckDB or a
running dashboard. Pull only into a clean checkout, then load packages sequentially because DuckDB
is single-writer:

```powershell
git status --short
git pull --ff-only origin main

Get-ChildItem snapshots\player-history-provisional\*\gw-*\* -Directory |
    Where-Object { Test-Path (Join-Path $_.FullName "manifest.json") } |
    Sort-Object FullName |
    ForEach-Object {
        .\.venv\Scripts\python.exe -m fpl.jobs.load_snapshots `
            --db data\fpl.duckdb $_.FullName
        if ($LASTEXITCODE -ne 0) { throw "provisional snapshot load failed: $($_.FullName)" }
    }
```

The existing loader names any package with `element-summary.tar.gz` as `player-history`. This does
not promote provisional evidence: the fixture version retains `finished_provisional` and
`finished` separately, and outcome attachment still checks `finished=true`.

After a new finalized package is committed, load it through the existing path and only then run
the official attachment:

```powershell
Get-ChildItem snapshots\player-history\*\gw-* -Directory |
    Where-Object { Test-Path (Join-Path $_.FullName "manifest.json") } |
    Sort-Object FullName |
    ForEach-Object {
        .\.venv\Scripts\python.exe -m fpl.jobs.load_snapshots `
            --db data\fpl.duckdb $_.FullName
        if ($LASTEXITCODE -ne 0) { throw "final snapshot load failed: $($_.FullName)" }
    }

$asOf = (Get-Date).ToUniversalTime().ToString("o")
.\.venv\Scripts\python.exe -m fpl.jobs.attach_outcomes `
    --db data\fpl.duckdb --season 2026-27 --as-of $asOf
if ($LASTEXITCODE -ne 0) { throw "final outcome attachment failed" }
```

Regenerate the BI/dashboard read models through the established commands in
`dashboard/README.md`. Do not regenerate a forecast merely to refresh observed statistics.

No repository-owned Windows scheduled task is installed. Automatically pulling into an active,
possibly dirty development checkout or replacing a DuckDB used by the Plan Server is not a safe
unattended action. The GitHub workflows are the durable daily capture; local ingestion remains an
explicit single-writer operation until a dedicated service workspace and lock are configured.

## Local versus public data

`dashboard/public/data/` is gitignored. Loading a snapshot or regenerating local read models does
not update GitHub Pages. The hosted site accepts only a reviewed, sanitized, immutable GitHub
Release ZIP named by `dashboard/public-data-release.json`; it never reads the mutable DuckDB or raw
snapshot directories. The current `unpublished` pin disables deployment.

Publishing a future generation is a separate owner action documented in
`docs/dashboard-deployment.md`. Any future manually reviewed sanitized ZIP includes the two
provisional schema-v1 files so the validated read-model manifest remains complete. They keep their
explicit status, raw points name, and capture time and never replace finalized ledger facts.
Creating that ZIP still does not deploy it: Pages changes only when the owner publishes the
immutable release and manually commits its exact pin.
