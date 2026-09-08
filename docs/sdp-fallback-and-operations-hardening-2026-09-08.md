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

Final live pre-deadline, paired-ledger and quality-gate verification will be recorded here before
push. No after-refresh improvement is claimed at this stage.

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
