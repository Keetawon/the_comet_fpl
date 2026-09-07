# Revision-safe SDP observations and durable local capture

Additive 2026-09-07 operational update: the [owner decision](sdp-primary-architecture-decision-2026-09-07.md)
now selects SDP as the V2 primary with incumbent fallback/shadow. The existing raw/version PIT
contract below is preserved. Production adds stricter whole-match health and refuses to revive
an older complete payload when the latest known revision is malformed or incomplete. Daily CLI
lookback defaults to five days; `--workload` adds competitive lineups/events. The
[production runbook](sdp-primary-operations.md) adds pre-deadline refresh and configuration.
The original dated scope below describes the earlier correctness change, not this new adoption.

Owner-authorized correctness/operations change, 2026-09-06. No model fit, evaluation,
forecast, scoring-rule change, default switch, or reinterpretation of frozen evidence.

## Why the old tests were insufficient

The recovery cycle retained both Ipswich–Liverpool stats versions in raw/staging, but the
reporting mart retained only the newest. After rebuilding, the pre-revision cutoff lost both
team rows (42→40 current-season rows). Rejecting future values alone therefore did not prove
stable historical replay. The required assertion is equality of the complete returned frames:

1. read cutoff T;
2. capture a later revision and rebuild;
3. read T again: football and tactical frames must be identical;
4. read after the revision: corrected measurements and original provenance must be visible.

## Read-model contract

`mart_fact_team_match_stats_v2` and `mart_fact_team_tactical_form_v2` remain latest-only
reporting/reconciliation surfaces. Existing audit populations and historical result files
are not redefined by changing their grain.

The additive `mart_fact_team_match_stats_v2_version` is the SDP model-read surface. Its
identity is `(season, fixture, team_id, provider, capture_id, metadata_capture_id)`.
Each complete stats payload is paired with retained, complete fixture metadata versions.
It carries `capture_id`, `payload_sha256`, `source_known_at`, `metadata_capture_id`, and
`metadata_known_at`; effective `known_at` is the later of the two source times. Neither
source time is replaced with kickoff or rebuild time. Both reciprocal sides must come from
the SAME stats payload and exact metadata capture, with permanent team-code corroboration.

Selection happens inside `FeatureSource`/`PointInTimeView`, not in caller SQL:

1. filter effective `known_at <= as_of`;
2. per `(season, fixture, team_id, provider)` choose descending
   `(source_known_at, capture_id, metadata_known_at, metadata_capture_id)`;
3. filter selected `kickoff_time < as_of`;
4. apply typed caller filters/projections.

The two source-version dimensions are selected together from retained combinations, so
later fixture kickoff/GW changes cannot rewrite earlier frames. Incomplete legacy metadata
captures without both exact-capture team registry witnesses are ineligible. Wrong non-NULL
club codes or reciprocal identities are errors, not grounds for a fuzzy replacement.
Incomplete stats remain in raw/staging and cannot displace a complete model observation.
Missing metrics remain NULL, including a new revision changing a previously measured value
to NULL; there is no per-field last-non-null coalescing or team-average imputation.

The new read model is additive/idempotent. Its payload×metadata combinations are intentionally
simple at local scale; optimize storage only after profiling, without collapsing knowledge
history. Schema creation alone is not migration: eligible SDP reporting identities without
a companion cause a fail-closed error directing the operator to stage an operational copy.

Archive `fpl_archive` observations retain their existing unversioned historical proxies.
This change does not manufacture historical capture validity for them. Validation-only
`RetrospectiveBackfillView` remains a separate capability, not a prospective boolean flag.

## Tactical rolling

The PIT tactical accessor recomputes rolling features read-only from the selected vintage's
match rows, sharing the reporting builder's exact arithmetic. Select one revision per match
BEFORE rolling; apply output/window filters AFTER rolling. A revision is never an extra match.
The trailing 3/5/10 and season-to-date windows, ratios with complete numerator/denominator
inputs, season-qualified stable clubs and DGW legs retain their definitions. Anchors choose
the last observed leg deterministically by kickoff then fixture ID. Knowledge time is the
maximum contributing observation time. No full-dataset scaling or model fitting is involved.

Consequently a historical window may contain fewer matches at an early capture cutoff than
the latest reporting window. That is correct: it must use only matches actually observed by T.
An older-event match first captured later can enter later cutoffs without changing earlier ones.

## Provider reversions

Content deduplication must not erase A→B→A. The first body's existing content-derived ID and
all old raw rows remain unchanged. A returning body gets a deterministic capture-event ID
derived from the base ID plus its actual UTC capture time; its body SHA remains the original
content address. Consecutive unchanged observations reuse the latest retained event. Exact
historical reimports are idempotent; unrepresented out-of-order or conflicting equal-time
observations fail closed rather than inventing a revision chronology. This applies to stats
and match-list request streams. The retrospective earliest-captured policy is unchanged.

## Regression evidence

`tests/test_pl_sdp_revision_pit.py` covers full-frame rebuild invariance, latest correction,
raw/staging/model provenance, late older-event discovery, pre-existing equal-time ties,
A→B→A, NULL/zero, reciprocal sides, DGWs, event/capture cutoffs, source truncation, filters,
missing migration and later live metadata changes. Transform tests separately check incomplete
stats/metadata, wrong stable identities, missing anchors and raw provenance.

An additional offline check uses the ACTUAL retained Ipswich–Liverpool payloads (2645221),
in an in-memory DB only. With T=`2026-09-06T14:36:13.039092Z`, adding the real later revision
and rebuilding leaves both old-cutoff frames identical. The new cutoff sees Ipswich xG
0.7318→0.7535 and Liverpool xG 0.6609→0.6861. It still has two team rows and one match per
tactical window, not two matches. Full local evidence is stored under
`D:/Personal/fpl-operations/verification/real-revision-regression.json` (not a model result).

The migrated persistent database independently restored all 42 current-season team rows
at that cutoff (21 matches, 168 tactical rows). At `2026-09-06T16:22:50Z` it exposes 58 team
rows (29 matches, 232 tactical rows). Everton–Manchester United, SDP 2645218, was newly
captured at `2026-09-06T15:47:32.617736Z`: both sides are absent at T and present later.
Ipswich–Liverpool selects the old/new actual xG values above at the corresponding cutoffs.
See `D:/Personal/fpl-operations/verification/operational-before-repeat.json`; the full
old-cutoff football/tactical frames were also saved for comparison after the next rebuild.

## Offline gate on the installed environment

The final full suite on permanent Python 3.12.14 / the frozen dependency lock completed on
2026-09-06 at approximately 23:23 Bangkok: **2,313 passed, 14 failed, 4 skipped**, 5,194 warnings,
522.66 seconds. All 14 failures are the existing `tests/test_bi_export.py` directory-symlink
`WinError 1314` privilege restriction; the four dashboard publication skips explicitly cite
the same privilege. No PIT, revision, daily ingestion or missing-`pytz` failure remains.
This is NOT an entirely green repository gate.

`ruff check src tests` passes; strict `mypy src` passes for 141 source files. The full
`ruff format --check .` retains 11 pre-existing offenders (324 files already formatted):
`src/fpl/insights/{contracts,evidence}.py`,
`src/fpl/publish/{contract,dashboard_json,export}.py`, and
`tests/{test_bi_export,test_bi_semantic_contract,test_dashboard_json,test_insights,`
`test_public_dashboard,test_snapshot_workflows}.py`. Unrelated files were not reformatted.

Authoritative local log prefix:
`D:/Personal/fpl-operations/verification/gate-py312-20260906T164430Z-final-`.
The timestamp-like component is a filename label, not the actual run time; use log/file
metadata for timing. Earlier gate logs and the initially failed clean-environment check
are retained, not overwritten. The new cold-process audit regression verifies all four
reports, exact UTC microsecond timestamps and NULL measurements without `pytz` installed.

## Durable local runbook

Use a separate operational DB on persistent disk. This host's installed locations are:

- Python: `D:/Personal/fpl-operations/.venv/Scripts/python.exe` (Python 3.12, frozen uv lock).
- DB: `D:/Personal/fpl-operations/data/operational.duckdb`.
- Runs/backups: `D:/Personal/fpl-operations/runs/<UTC-run-id>/`.
- Source checkout: V2 worktree, never an automatic switch to main.

The environment is installed editable from
`D:/Personal/workspace/the_comet_fpl/.worktrees/sdp_test`; do not remove/move that worktree
or edit its source during a scheduled cycle. The daily task neither pulls Git nor updates
dependencies. Provider requests use the existing 1.5-second pacing, 30-second timeout and
bounded four-retry configuration. It does not start model, dashboard or optimizer jobs.

The DB was created under a read-only DuckDB lease using the existing no-WAL/hash-verified
copy safeguard from the preceding recovery DB. Original default and frozen/recovery files
stay preserved; local consumers are not silently redirected.

```powershell
& 'D:/Personal/fpl-operations/.venv/Scripts/python.exe' -m fpl.jobs.daily_pl_sdp `
  --db 'D:/Personal/fpl-operations/data/operational.duckdb' `
  --runs 'D:/Personal/fpl-operations/runs'
```

The job takes a sidecar lock, refuses unresolved WAL or an external writer, backs up under
a read lease, then holds a DuckDB writer lease across the sequential cycle. It runs official
snapshot capture, a no-lookback current-season missing pass, seven-day revision capture,
transactional staging/audit, and actual PIT/mart visibility checks. A failure leaves completed
raw captures intact and emits a nonzero result. Run reports, config/source hashes and logs
are new files; backups are not automatically deleted. Check disk space and agree a retention
policy before prolonged unattended operation.

`--raw-only` runs the same durable capture while deliberately deferring staging and reporting
`consumer_ready=false`. This mode prevents losing observations while a feature migration is
being developed; it is not a green model-consumer gate.

Freshness compares expected completed IDs (provider completion plus corroborated official
ended fixtures) against complete raw stats and post-stage PIT access. It distinguishes
missing, incomplete, awaiting publication, unresolved identity and provider completion lag.
It records actual listing-check time separately from latest retained body time: an unchanged
response intentionally does not advance the original body's known_at. No fixed 14.3-hour
publication SLA is assumed. Capture exceptions/per-match failures fail the run even if an
underlying CLI would return zero.

```powershell
./scripts/register_daily_pl_sdp.ps1 `
  -PythonPath 'D:/Personal/fpl-operations/.venv/Scripts/python.exe' `
  -DatabasePath 'D:/Personal/fpl-operations/data/operational.duckdb' `
  -RunRoot 'D:/Personal/fpl-operations/runs' -At '07:00'
```

Registration refuses an existing task or Temp paths. The task is current-user, limited,
interactive-logon; the owner must be signed in (a locked session is acceptable). It cannot
run on a powered-off PC or guarantee a 07:00 capture while logged out. StartWhenAvailable
catches missed runs when available, overlapping runs are ignored, the bounded client retry
policy remains in force, and the task retries twice 30 minutes apart. pythonw suppresses an
unwanted console. The helper's `-WhatIf` validates without activating anything.
Battery power does not interrupt an active database cycle. The task does not wake a sleeping
machine. A process crash or forced shutdown can leave a lock/WAL: inspect the recorded PID and
DuckDB recovery state before removing a stale sidecar; automatic retries do not bypass it.
Keep the configured current season and this editable source checkout valid at season rollover.

The task `The Comet FPL - daily SDP` was registered on this host and manually started through
Task Scheduler on 2026-09-06 at 23:05 Bangkok time, using permanent Python 3.12.14. Its first
scheduled time is 2026-09-07 07:00 Bangkok. Registration is not by itself proof of a successful
capture-and-stage cycle; use the per-run `report.json` and scheduler exit status below.

The clean permanent environment exposed an existing audit-report dependency defect that the
older developer environment masked: DuckDB `fetchall()` of timezone-aware timestamps tried to
import undeclared `pytz`. The repository explicitly does not depend on `pytz`; the correction
uses epoch microseconds and reconstructs the same UTC instants/NULLs, with a cold-process
real audit-CLI regression. This is an audit-access fix, not a new dependency or metric change.

## Verified scheduled cycle and handoff

The corrected, actual Task Scheduler run is
`D:/Personal/fpl-operations/runs/20260906T162303.209690Z-6197b38a/`.
It ran from `2026-09-06T16:23:03.209690Z` to `16:37:05.487097Z` (about 14 minutes).
Scheduler `LastTaskResult=0`; `report.json` records `healthy=true`,
`consumer_ready=true`, `staging_status=verified`, and no failures. The next scheduled
execution is 2026-09-07 at 07:00 Bangkok. No lock or WAL remained after successful closure.

Provider match-list and stats requests returned HTTP 200. Expected completed matches = 29,
retained complete = 29, missing = 0, unresolved = 0, contradictions = 0, incomplete = 0.
Official FPL separately reported 20 finalized and 9 provisionally ended fixtures; their
finality flags were not rewritten. Across this task, Everton–Manchester United was the one
newly captured completed match, increasing the retained current-season population from
28 to 29. Each narrow refresh checked 10 recent stats payloads without finding a changed
stats body. The final run added one match-list body version, not a stats revision.

The audit reconciles 2,280 / 2,280 fixture identities with zero ambiguities, contradictions,
unmatched identities or staging schema failures. It does not assume pulse_id = SDP matchId.

| Surface | All rows/versions | Current-season SDP |
| --- | ---: | ---: |
| Raw SDP payloads | 1,960 (1,930 stats, 30 match-list versions) | See run manifest |
| Staged team-side versions | 3,860 | All complete payload versions retained |
| Staged numeric metric versions | 601,273 | NULL remains distinct from zero |
| Latest team-match reporting mart, both providers | 7,658 | 58 |
| SDP payload × metadata model-read versions | 6,440 | 2,640 |
| Latest tactical reporting mart, both providers | 29,464 | 232 |

Version rows are NOT additional matches: the strict current-season reader returns exactly
29 matches / 58 reciprocal sides and 232 tactical rows. The complete 42-row football and
168-row tactical frames at the old cutoff remained identical after the subsequent live
capture and rebuild. Evidence:
`D:/Personal/fpl-operations/verification/operational-verification.json`.
The separate actual-payload regression above also explicitly adds the later Ipswich revision
between the two old-cutoff reads, rather than relying only on this repeated-build check.

Final operational SHA256:
`b73459ba54a59ebb4a9da27cd0f97eb804b2803f49141ebdc41324fb5a65cdf8`.
All three original/default/recovery DB hashes remain unchanged, as do the 107 protected
result/config/model/validation files checked against the preceding recovery manifest.
Exact preserved paths and hashes are in `operational-verification.json`; initial copy
provenance is in `verification/initial-copy.json`. Both runs preceding the corrected one,
including the first scheduled audit failure, remain intact with their logs and backups.

Only `D:/Personal/fpl-operations/data/operational.duckdb` is refreshed. Default consumers
still point to their original databases; `consumer_ready` is about this explicitly selected
operational DB, not a dashboard, optimizer, forecast or promotion switch. Raw endpoints
remain `matches` and `match_stats`: SDP lineups/events were not captured or scheduled.
The separate official FPL `event-live` snapshot is not an SDP lineup/event backfill.

Git stayed on `claude/comet-fpl-v2-architecture-mqrj8f` at
`9228892ba2abda80dd8dc8011c93302c6aad9710`, independently matching the remote at the final
check (0/0 divergence). Changes are uncommitted as instructed; no push, merge, rebase or PR.
No formal model evaluation was run from this dirty implementation worktree.

If cloud execution is used later, restore/save the DB or versioned raw evidence through
explicit persistent storage. An ephemeral GitHub-hosted runner's DuckDB file is not persistence.

## Research boundary

The owner permits NEW model development once these two prerequisites are verified; a prior
candidate's failure to beat 1% does not forbid research. This permission does not amend old
gates or turn retrospective evidence into promotion. Before any next outer evaluation freeze
a separately named hypothesis, population, comparator, metrics, evidence class, appropriate
decision criteria and clean committed provenance. Do not retune against outer results, rerun
old candidates, or change prospective/default/optimizer use automatically.

## Authorized local commit follow-up (2026-09-07)

The owner subsequently authorized committing this infrastructure before one separately
preregistered weekly-inner SOT experiment, without pushing. A fresh focused check exposed
a test-clock dependency: the synthetic official capture used wall time while its PIT cutoff
was fixed to 2026-09-06. The fixture now records its explicit synthetic `NOW`; production PIT
and capture-time handling are unchanged. The initial default-temp run was blocked by Windows
ACL (`WinError 5`); checks use a new explicit test-only `--basetemp` directory instead.
