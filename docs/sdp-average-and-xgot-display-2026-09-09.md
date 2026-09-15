# SDP averages and owner-confirmed xGOT display

The Team stat from SDP table now defaults to **Average per match**. The
Players stat from SDP table defaults to **Average per appearance**, using
actual FPL minutes greater than zero to identify appearances. Tables, sorting,
comparison charts and filtered CSV exports use the same arithmetic. Totals
remain selectable, as does player per-90 display with its existing actual-minute
denominator. Match logs retain individual match observations.

An average requires every contributing match to have a measured or explicitly
corrected display value. Unknown player minutes keep the per-appearance average
unavailable; they are not treated as DNPs. Zero-appearance players have no average.
Player match counts, witnessed SDP starts, FPL appearances and total exposure
remain visible as sample-size context. Percentages remain explicitly labelled
match means, never sums or an invented pooled percentage. Last-three/last-five
display filters and all model windows are unchanged.

## Four additional display corrections

The owner's new xGOT confirmation was recorded at **2026-09-09T07:24:08Z**.
It is separate from the earlier SOT/blocked-shot confirmations, whose timestamps
and records remain unchanged. Display-correction policy version 3 adds exactly:

| Fixture | Match | Corrected club | SDP match ID | xGOT display | Evidence |
|---|---|---|---:|---:|---|
| 7 | Brighton–Aston Villa | Aston Villa | 2645201 | 0 | Owner-confirmed |
| 19 | Sunderland–Fulham | Fulham | 2645213 | 0 | Owner-confirmed |
| 20 | Aston Villa–Arsenal | Aston Villa | 2645206 | 0 | Owner-confirmed |
| 28 | Nottingham Forest–Spurs | Spurs | 2645224 | 0 | Owner-confirmed |

Each record pins the original raw payload SHA256, provider match/side identity,
actual source known-at and new confirmation time. The exporter rechecks the
existing shot-accounting and opposite-goalkeeper evidence. It rejects explicit
NULL/value replacements in the pinned raw payload, contradictory positive or
malformed on-target evidence, identity mismatches and future confirmations.
A later measured provider version takes precedence without erasing the record.

These raw payloads **omit** `expectedGoalsOnTarget`; they do not explicitly
report zero. Existing off-target plus blocked-attempt evidence exhausts total
attempts and supports the separately corroborated zero-SOT interpretation.
That is supporting evidence for these owner-confirmed xGOT zeros, not proof that
all omitted SDP fields universally mean zero. `shotOffTarget` is not shots from
outside the penalty area. The earlier bounded sparse-count assumption policy
is unchanged; other continuous fields are not globally zero-filled.

The sidecar is schema version 4. Its original `sdp.expected_goals_on_target`
remains NULL; the separate `display_corrections` map supplies zero with provenance.
The browser accepts existing schema versions 2/3 and new version 4; xGOT
corrections require version 4. Tables, match logs and CSV expose owner-confirmed
provenance. No derived opponent metric is invented for xGOT.

## Why “Unavailable” appeared

Two different states were being presented with the same word:

1. A metric could not be aggregated because one match lacked a value. xGOT was
   outside the older sparse-count zero policy and had no separate confirmation.
2. The match-log status described the provider's core completeness. Even with
   corrected display values, the raw provider still lacks required fields.

The match log now labels the second state **Partial SDP**, with an explanation
that individually available/corrected cells can still be displayed. This does
not change underlying health flags or the model selector. Detailed SDP player
statistics remain unavailable; the player tab continues to identify detailed
statistics as FPL observations and SDP as participation evidence.

## Verified local delivery

The read-only sidecar export ran with cutoff `2026-09-09T07:34:26.721264+00:00`
against the existing operational DB; no provider backfill or forecast job ran.

- Current coverage: **30 completed fixtures across GW1–GW3**; provider core-valid
  **26/30**, unchanged.
- Explicit owner-confirmed display corrections: **9 direct cells** (the previous
  five plus four xGOT cells), across four fixtures. Four SOT opponent mirrors
  remain separate from this count.
- Current-season sparse-count assumptions: **83 cells**, unchanged.
- Raw team observations, player observations, fixture evidence and original
  correction records match the previous export exactly.
- Three-match xGOT averages: Aston Villa **0.0252**, Fulham **0.9940333333**,
  Spurs **0.5046**. Only the specified match values are set to display zero;
  other matches retain their measured values.
- Sidecar SHA256:
  `2860822fa3ba5612414c71a10f49ea81a73cdc1f91a5a84008eca5d17ea1dad1`.

The preview at `http://127.0.0.1:4173/#team-stat-sdp` and
`http://127.0.0.1:4173/#players-stat-sdp` serves this exact sidecar and the rebuilt
average controls. It is local to the existing host, not a production deployment.
The served-data check uses the actual TypeScript validator and aggregation/CSV
functions and retains both average CSVs under
`D:/Personal/fpl-operations/verification/sdp-average-xgot-20260909/`.

Verification: 52 focused Python tests, 9 publication/scouting-isolation regression
tests and 48 Dashboard tests passed. Global Ruff and strict mypy (229 source
files) passed; changed Python formatting passed; TypeScript/Vite build and
frontend lint passed. Existing PuLP deprecation, frontend Fast Refresh and bundle
size warnings remain. This does not claim a full-repository test pass.

Browser discovery returned `[]`; selecting the local preview returned
`No browser is available`. Interaction tests run through the existing DOM test
suite; no new rendered-browser screenshot or visual pass is claimed.

All 26 protected current forecast/public read-model files retain their hashes.
The existing 392-file preservation registry was also reconciled against the
current starting state at `c4df0cb`, retaining the separately recorded source-wiring
and dashboard-vintage changes completed before this task. No further change was found.
Model sources, production configuration, selector, optimizer and frozen research
files are outside this change. Existing forecasts are not recalculated or relabelled.
