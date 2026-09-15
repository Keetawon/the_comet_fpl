# SDP fallback and operations hardening — 2026-09-08

**Owner-directed architectural adoption. SDP-backed V2 is the primary football-environment architecture.
Historical experimental verdict remains INCONCLUSIVE under its frozen gate.
Incumbent retained as operational fallback and prospective shadow comparator.**

This additive operational report does not rerun or reinterpret a frozen experiment. Phase A did
not pass its previous 1% gate. Player defaults remain unchanged and GK H stays shadow-only.

## Saved forecast attribution

Starting commit: `52924f99d83ba4a7b4b72867d7d70ac77d728741` on
`claude/comet-fpl-v2-architecture-mqrj8f`. The starting worktree was clean and matched the expected SHA.
The original forecast is GW4–8 (50 fixtures), not an official single GW48.
Prediction cutoff: `2026-09-07 15:20:00.757039+00:00`.
Primary artifact SHA-256: `413e817eb965b328af3b4cd99102584bd4f8b51eb283c418c76e8f37ca7f0be9`.
Original source database SHA-256: `b0803710312565d70015adedc5f223a9acc84c04e46578908157037a511437b5`.

The original database was retained by the next scheduled capture as its immutable before-image.
An independent read-only reconciliation against that image attributes every one of the 29 saved
fallback fixtures. The original artifact and cutoff are preserved. The full machine-readable
[baseline audit](data/sdp-fallback-baseline-audit-2026-09-08.json) retains team identities, cutoff,
kickoff, eligible and required counts, last valid fixture and source time, prior availability,
blocking raw hashes/versions, missing fields, classification and action for every fixture.

| Reason | Fixtures | Fixable now at original cutoff | Legitimate fallback |
|---|---:|---:|---:|
| SDP_INCOMPLETE | 29 | 0 | 29 |
| Other attribution categories | 0 | 0 | 0 |

All 29 use selector `SDP_INCOMPLETE_FALLBACK`. Each club has three officially completed
current-season matches, so its required count is three within the frozen maximum-five window.
Whole-match validation rejects both tactical sides when either side lacks a core field.
Cutoff-eligible league history makes the frozen shrinkage prior available for every row, but
that prior cannot waive an incomplete match already present in required recent history.
No team in this population is an actual zero-history cold start.

In the table, H/A counts are eligible/required matches. Last-valid IDs are official FPL fixture
IDs; the linked JSON also records their kickoff and actual source known_at. Every row shares the
cutoff above and the LEGITIMATE FAIL-CLOSED classification. Blocking IDs refer to the source
table immediately below, making each row's exact missing field and source time explicit.

| Fixture | Home | Away | Kickoff (UTC) | H count | A count | Last valid H/A | Blocking history |
|---:|---|---|---|---:|---:|---|---|
| 31 | Aston Villa | Nott'm Forest | 2026-09-12 14:00:00+00:00 | 1/3 | 2/3 | 25/14 | 20, 28, 7 |
| 35 | Liverpool | Fulham | 2026-09-12 14:00:00+00:00 | 3/3 | 2/3 | 21/24 | 19 |
| 36 | Sunderland | Arsenal | 2026-09-12 19:00:00+00:00 | 2/3 | 2/3 | 22/29 | 19, 20 |
| 37 | Spurs | Everton | 2026-09-12 16:30:00+00:00 | 2/3 | 3/3 | 15/30 | 28 |
| 38 | Coventry City | Brighton | 2026-09-13 13:00:00+00:00 | 3/3 | 2/3 | 26/23 | 7 |
| 42 | Brighton | Arsenal | 2026-09-19 14:00:00+00:00 | 2/3 | 2/3 | 23/29 | 20, 7 |
| 45 | Man City | Sunderland | 2026-09-20 13:00:00+00:00 | 3/3 | 2/3 | 26/22 | 19 |
| 47 | Nott'm Forest | Coventry City | 2026-09-19 16:30:00+00:00 | 2/3 | 3/3 | 14/26 | 28 |
| 48 | Spurs | Aston Villa | 2026-09-19 11:30:00+00:00 | 2/3 | 1/3 | 15/25 | 20, 28, 7 |
| 50 | Fulham | Man Utd | 2026-09-20 15:30:00+00:00 | 2/3 | 3/3 | 24/30 | 19 |
| 51 | Arsenal | Leeds | 2026-10-10 11:30:00+00:00 | 2/3 | 3/3 | 29/23 | 20 |
| 52 | Aston Villa | Brentford | 2026-10-10 14:00:00+00:00 | 1/3 | 3/3 | 25/22 | 20, 7 |
| 55 | Crystal Palace | Nott'm Forest | 2026-10-11 13:00:00+00:00 | 3/3 | 2/3 | 24/14 | 28 |
| 57 | Ipswich Town | Fulham | 2026-10-10 14:00:00+00:00 | 3/3 | 2/3 | 21/24 | 19 |
| 59 | Man Utd | Spurs | 2026-10-10 16:30:00+00:00 | 3/3 | 2/3 | 30/15 | 28 |
| 60 | Sunderland | Brighton | 2026-10-10 14:00:00+00:00 | 2/3 | 2/3 | 22/23 | 19, 7 |
| 61 | Bournemouth | Sunderland | 2026-10-18 13:00:00+00:00 | 3/3 | 2/3 | 27/22 | 19 |
| 63 | Brighton | Crystal Palace | 2026-10-18 13:00:00+00:00 | 2/3 | 3/3 | 23/24 | 7 |
| 65 | Fulham | Hull City | 2026-10-17 14:00:00+00:00 | 2/3 | 3/3 | 24/25 | 19 |
| 68 | Newcastle | Aston Villa | 2026-10-17 16:30:00+00:00 | 3/3 | 1/3 | 27/25 | 20, 7 |
| 69 | Nott'm Forest | Arsenal | 2026-10-18 15:30:00+00:00 | 2/3 | 2/3 | 14/29 | 20, 28 |
| 70 | Spurs | Coventry City | 2026-10-19 19:00:00+00:00 | 2/3 | 3/3 | 15/26 | 28 |
| 71 | Arsenal | Everton | 2026-10-24 14:00:00+00:00 | 2/3 | 3/3 | 29/30 | 20 |
| 72 | Aston Villa | Man City | 2026-10-24 11:30:00+00:00 | 1/3 | 3/3 | 25/26 | 20, 7 |
| 73 | Chelsea | Spurs | 2026-10-24 16:30:00+00:00 | 3/3 | 2/3 | 29/15 | 28 |
| 74 | Coventry City | Fulham | 2026-10-24 14:00:00+00:00 | 3/3 | 2/3 | 26/24 | 19 |
| 77 | Ipswich Town | Nott'm Forest | 2026-10-23 19:00:00+00:00 | 3/3 | 2/3 | 21/14 | 28 |
| 78 | Liverpool | Brighton | 2026-10-25 14:00:00+00:00 | 3/3 | 2/3 | 21/23 | 7 |
| 80 | Sunderland | Leeds | 2026-10-25 16:30:00+00:00 | 2/3 | 3/3 | 22/23 | 19 |

## Four incomplete historical sources

All omitted fields below are `ontargetScoringAtt`; an omitted field remains NULL.
Additional available statistics cannot license an inferred zero.

| FPL fixture | SDP match | Side with missing SOT | Raw fetched_at | Normalized known_at at cutoff |
|---:|---:|---|---|---|
| 7 | 2645201 | Aston Villa | 2026-09-04 17:47:07.612331+00:00 | 2026-09-07 15:09:28.407423+00:00 |
| 19 | 2645213 | Fulham | 2026-09-04 17:47:22.418236+00:00 | 2026-09-07 15:09:28.407423+00:00 |
| 20 | 2645206 | Aston Villa | 2026-09-04 16:17:39.555102+00:00 | 2026-09-07 15:09:28.407423+00:00 |
| 28 | 2645224 | Spurs | 2026-09-07 14:37:57.266972+00:00 | 2026-09-07 15:09:28.407423+00:00 |

Action for all affected fixtures: re-fetch required incomplete sources. If the provider supplies
a valid correction, retain a new immutable version and use it only at or after its actual known_at.
The original-cutoff audit remains 21 primary / 29 fallback even if a later correction becomes valid.

## Operational repairs

- The ordinary five-day capture window could miss an older incomplete match still required by
  the selector. The staged daily revision pass now rechecks incomplete core evidence within
  each club's last five completed PL matches. Core validation, identity and model arithmetic
  are unchanged. This repairs capture coverage, not the provider's missing statistics.
- Capture receipts distinguish the actual request timestamp from the retained source's original
  fetched_at/known_at and hash. Unchanged responses remain idempotent.
- An SDP-enabled all-fallback forecast also emits the complete incumbent shadow. This retains
  paired populations during outages and permits honest fallback-rate evaluation.
- Pre-deadline builds preserve the exact source database before prediction and ledger writes.
  Future cutoffs are rejected. The build receipt records source, primary and shadow hashes.
- Every capture/failure receipt is bound through one hashed refresh receipt. A collector failure
  after it emitted a receipt cannot drop that provenance. Missing/malformed receipts force source
  fallback; snapshot/build exceptions retain a failure receipt. SDP-enabled artifact publication
  atomically refuses overwrite, including a concurrent writer, while disabled behavior is preserved.
- The paired ledger reuses existing forecast/outcome storage, revalidates complete consumed-source
  provenance through the strict SDP reader, and rejects an empty reader for declared sources.
  Bootstrap knowledge time and official deadlines are checked against immutable FPL bytes.
  Outcome reporting selects a fixture's latest version before assigning its current gameweek.
- Interrupted daily capture records failure when Python handles the interrupt. Forced termination
  can still leave an unresolved WAL/lock; recovery is explicit and preserves prior evidence.

## Verification status

The independent baseline audit and the production audit CLI reconcile all 29 fixture identities,
saved reasons, every blocking match, home/away names, eligible/required history counts and last
valid matches. All 50 rederived selector reasons agree with the saved decisions. Re-derivation
uses the audited checkout's frozen artifact and reports its hash; saved decisions remain
authoritative if a future checkout differs.

The real saved artifacts also pass manifest/population/component parity and strict validation of
556 consumed SDP source versions and their metadata receipts. This was a read-only check; the
old prediction was not relabeled or backfilled into the new prospective pair registry.

The real build completed successfully from clean implementation commit
`2a96e91ee49604e152f77e47ff6e1bcf9d7037af`. The
[verification receipt](data/sdp-operational-verification-2026-09-08.json) retains the command,
timestamps, hashes, source example, capture rechecks, pair identity, deadline witness and checks.

| Population | Before | After |
|---|---:|---:|
| SDP_PRIMARY fixtures | 21 | 21 |
| Incumbent fallback fixtures | 29 | 29 |
| Fallback rate | 58% | 58% |

There are **zero fixable fixture causes at either audited cutoff and 29 legitimate fallbacks**.
The same fixture IDs and four missing-SOT sources listed above remain. The capture-coverage defect
is repaired: the revision pass fetched 13/13 matches, including all four required-history rechecks
and three matches older than the ordinary lookback. Every SDP response was unchanged; no missing
provider statistic was manufactured and no raw knowledge time advanced on an unchanged response.

## Real pre-deadline verification

```powershell
python -m fpl.jobs.pre_deadline_forecast --db D:/Personal/fpl-operations/data/sdp-primary-v2.duckdb --runs D:/Personal/fpl-operations/sdp-primary-runs --gw-from 4 --gw-to 8 --draws 2000 --output D:/Personal/fpl-operations/predictions/sdp-primary-v2-20260908-hardening-gw4-8.jsonl
```

- Started `2026-09-08T03:26:37.939208Z`; completed `03:58:14.813444Z` (31m 36.9s).
  Refresh, forecast and evidence exit codes were all zero. Allow a substantial pre-deadline
  margin for full player-history capture, normalization and ledger insertion; this is not an
  instantaneous build. The existing `--skip-player-history` option requires already-sufficient
  official history and is not a substitute for missing prerequisites.
- FPL refresh fetched the bootstrap, schedule, event-live and all 654 player histories. The new
  snapshot is `1bfb3d92-6d5e-48bf-a665-1f489dc6c1da`, known at
  `2026-09-08T03:37:39.610696Z`. This is a new source snapshot, not an old-data-only build.
- The latest completed PL match detected was FPL fixture **29**, Arsenal vs Chelsea,
  kickoff `2026-09-06T15:30:00Z`, SDP match **2645215**. Its raw stats hash is
  `477e0196cff70c8aaf9fa04d5585b6f8e255d75405d9dc88072723ff0a9a1673`, originally fetched
  `2026-09-07T14:37:45.225593Z`. Its consumed normalized known_at is
  `2026-09-08T03:37:39.610696Z`, reflecting the new FPL metadata dependency. The receipt lists
  this run's actual request time separately. Unchanged SDP bodies retain original raw times.
- Normalization updated all 52 current valid team-source bindings to the new FPL metadata
  version. Strict staging passed; tactical/chance construction and fixture-environment selection
  ran through the real points job. Transport coverage remained 30/30 and core validity 26/30,
  with four incomplete matches, zero current schema/identity failures and no global failure.
- The prediction cutoff was actual post-refresh time `2026-09-08T03:52:24.844595Z`.
  The preserved source DB hash is
  `538560454f551a48eeaf015c318f7dea0fc6a34fccc56ee7f0e2b117ef7330d6`.
- Primary artifact hash:
  `566fe684a14ce2edc707286968d470891e7854e7e1ac44733fc0ab3d17d4914a`.
  Incumbent shadow hash:
  `d1e48736d869a697f79e9b383a0d627f7a3632e1b4b18321c933dc421385361e`.
  A read-only replay using the same source DB, cutoff, commit, refresh receipt, seed, draws and
  output basename reproduced **both artifacts byte-for-byte**. The replay was not a new evidence row.
- An injected `httpx.ConnectError` at the refresh boundary was separately run through the real
  wrapper, points pipeline and ledger on an isolated operational DB copy. It produced 50/50
  `SDP_SOURCE_FALLBACK` fixtures, exactly matching the incumbent shadow, and recorded the pair
  with a real clock cutoff. These controlled-test artifacts are explicitly excluded from the
  production evidence ledger; no actual provider outage is claimed.
- Two later retained provider versions were excluded at the original September 7 cutoff.
  Its 1,112 selected football rows retained the same state hash before/after later captures.
  This is an operational cutoff check, not a rerun or relabeling of historical research.
  Focused tests also cover changed stats revisions, malformed data, NULLs and duplicate captures.

## Active prospective ledger

Production pair ID: `0cca9d810d3f984f30f53d37a8ad3a494f20266d910e4acc1ec161bce582fafb`.
Actual record-entry time: `2026-09-08T03:53:18.937809Z`; transaction completed before the build
finished. The exact retained bootstrap witnesses all five future official deadlines, starting
with GW4 at `2026-09-12T12:30:00Z`. Every predicted kickoff was also future.

The pair contains **3,270 player-gameweek, 3,270 player-fixture and 100 team-fixture rows per role**,
with identical 654-player/50-fixture populations, FPL snapshot, scoring contracts, player
components, cutoff, seed and draws. All 556 consumed SDP source versions and metadata receipts
were revalidated; every consumed known_at is within cutoff. CS remains opponent PMF mass at zero.
Repeating the record command preserved the pair ID and original created_at. The operational
database has one new SDP comparison pair; its other 22 forecast vintages predate this delivery.
The full-grain report confirms that every new pair outcome is pending/unattached. Original
predictions remain immutable; existing finalized-outcome attachment is a separate append-only
operation. Metric computation is deferred until outcomes exist; this task adds no new model claim.

```text
FPL API + SDP -> refresh / immutable raw / normalization / PIT + health
                                      |
                             explicit fixture selector
                               /                    \
               SDP Tactical / Chance              incumbent fallback
                    Team Goal / CS                (when invalid)
                               \                    /
                                existing player pipeline -> primary points PMF
Incumbent comparator ----------> existing player pipeline -> shadow points PMF
                                both immutable vintages -> prospective ledger
```

## Checks and inherited limitations

| Check | Result |
|---|---|
| Selector, revision, pre-deadline and artifact focused/regression set | 105 passed |
| Evidence ledger and adjacent outcome/transport set | 78 passed |
| Capture, daily wrapper and remote-runtime set | 50 passed |
| Relevant broader regression set | 461 passed |
| Ruff `check .` | Passed |
| Strict mypy `src` | Passed, 202 source files |
| Changed Python file formatting | Passed, 19 files |
| Global formatting diagnostic | 11 unchanged inherited files need formatting; 499 already formatted |
| Git whitespace check | Passed |

These test sets overlap; their counts are not a unique-test total. The final corrected focused
set passed after fixing a test's expected wording for a missing-model failure. The global-format
failures are confined to unchanged insights/publish files and their tests (listed in the receipt).
The full test suite was not rerun: the prior verification documents Windows symlink-permission
failures and skips outside this change. No full-suite success is claimed.

Frozen configurations, parameters, model/validation code, dated research reports and result
artifacts have no diff from the starting commit. The research DB remains
`0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8`.
Local main remains `ede17377216807ca2635879d1153e268dcd04fe6`; remote main remains
`4a58f079057d79189bd31a782e5f3c860b3c097f`, and the default branch remains main.
No merge, PR, default-branch change, player research or GK scoring promotion occurred.
Only the V2 implementation and additive verification documentation are authorized for push.

## Monitoring

```powershell
python -m fpl.jobs.sdp_capture_health --runs D:/Personal/fpl-operations/sdp-primary-runs --db D:/Personal/fpl-operations/data/sdp-primary-v2.duckdb --max-success-age-hours 30
python -m fpl.jobs.report_sdp_evidence --db D:/Personal/fpl-operations/data/sdp-primary-v2.duckdb --prediction-id 0cca9d810d3f984f30f53d37a8ad3a494f20266d910e4acc1ec161bce582fafb --grain team
python -m fpl.jobs.audit_sdp_fallbacks --db D:/Personal/fpl-operations/data/sdp-primary-v2.duckdb --artifact D:/Personal/fpl-operations/predictions/sdp-primary-v2-20260908-hardening-gw4-8.jsonl --output D:/Personal/fpl-operations/verification/new-fallback-audit.json
```

Health verification found four completed receipts, none running/malformed/failed, and a healthy
latest capture. Its four current incomplete matches are reported separately from 1,374 failures
across all retained seasons. Do not present historical coverage limitations as current capture
failures. Capture/workload coverage, fallback reasons, freshness, capture lag, source identity and
schema failures should be monitored over the next prospective GWs.


## Runtime and prospective period

No authorized remote runtime has been found. Static GitHub Pages and the absence of self-hosted
Actions runners do not provide persistent capture. The [remote package](sdp-primary-remote-runtime.md)
is prepared for an authorized host; remote execution has not occurred:
**BLOCKED ONLY ON RUNTIME AUTHORIZATION / CREDENTIALS**.

The [operations runbook](sdp-primary-operations.md) covers daily and pre-deadline commands.
The [prospective evidence contract](sdp-prospective-evidence.md) covers immutable paired predictions
and separately appended outcomes. An old prediction is never backfilled as a pre-deadline record.

Do not reopen player-component research during this task. Reconsider only after enough genuinely
prospective GWs/fixtures exist for meaningful comparison, capture is stable, fallback coverage is
understood, PIT/provenance defects are resolved, and GK-shadow evidence can inform an end-to-end
points assessment. These conditions introduce no numeric promotion threshold and authorize no
retuning of frozen candidates.
