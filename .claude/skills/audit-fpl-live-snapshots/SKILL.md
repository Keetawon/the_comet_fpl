---
name: audit-fpl-live-snapshots
description: Audit, design, implement, or monitor durable FPL live API capture and snapshot ingestion. Use for daily_snapshot, GitHub snapshot workflows, bootstrap-static, fixtures, event-live, element-summary, season rollover, snapshot manifests, freshness alerts, atomic writes, or loading committed snapshots into raw/staging/mart tables.
---

# Audit FPL Live Snapshots

Require unrecoverable live FPL data to be captured completely, immutably, and usefully.

## Read first

- `AGENTS.md`
- README R5 and snapshot sections
- `config/sources.yaml`
- `src/fpl/ingest/fpl_api.py`
- `src/fpl/jobs/daily_snapshot.py`
- `src/fpl/storage/schema.sql`
- `.github/workflows/snapshot.yml`
- Relevant API fixtures and tests

## Audit the full data loop

Trace each required field through:

`API endpoint -> captured artifact -> manifest/provenance -> loader -> raw -> staging -> mart
-> point-in-time feature access`

Do not call capture complete merely because `bootstrap-static` and `fixtures` are archived.
Preserve player/gameweek outcomes with `event/{gw}/live/`, per-player histories, or another
explicitly justified source.

## Required guarantees

1. **Coverage:** Record endpoint, season, gameweek, capture time, response shape, row/entity
   counts, and required-field coverage.
2. **Season safety:** Detect bootstrap/fixtures rollover skew before joining season-scoped IDs.
3. **Immutability:** Never overwrite a prior capture.
4. **Atomicity:** Fetch and validate every required endpoint before writing. Wrap database
   batches in a transaction; build file captures in a temporary location and atomically move.
   Add a mid-write failure test proving rollback.
5. **Integrity:** Store hashes and a machine-readable manifest. Bound response sizes and reject
   empty, invalid, or implausibly small payloads.
6. **Usability:** Implement and test the loader. A committed snapshot that no pipeline consumes
   is only a backup, not an operational data path.
7. **Point-in-time:** Preserve `captured_at`/`known_at`; do not collapse multiple observed
   versions of schedules, prices, news, or availability.
8. **Operations:** Alert when the latest successful capture exceeds the freshness threshold.
   Keep network-free fixture tests plus a separately controlled live smoke check.

## Review GitHub Actions

Minimize permissions, pin third-party actions by commit SHA, sanitize untrusted API-derived
values before shell or output use, prevent concurrent capture races, and verify that retry/push
logic cannot publish a partial day.

## Validate

Run the API/snapshot tests and a deliberate failure-path test. When changing the workflow, also
run an available YAML/action lint and ShellCheck-compatible review.

## Handoff

Report endpoint coverage, latest capture freshness, manifest/integrity status, atomicity proof,
rollover state, loader status, and any unrecoverable interval. Separate local Python capture
from the durable GitHub capture if their contracts still differ.
