# R1 delivery: observed midweek context on Summary

R1 is a descriptive overlay. Summary shows the **top 15 players by the selected
forecast's raw published next-gameweek xP**, descending, with permanent player code
as the deterministic tie breaker. It replaces the two short player-to-watch lists;
the full Players page remains available. Rest, news, status and horizon xP do not
change this ordering. Existing availability badges remain separate reporting context.

The next GW comes from the published Summary contract, within the selected
forecast season and horizon. No older starting GW is silently substituted. Double
gameweeks use the existing strict raw-xP helper; incomplete or duplicate fixture
evidence is unavailable. This is one GW's ranking, not a new recommendation model.

## Evidence repair

The original R1 commit is `6a31539164939e4807dc3b6c61c9b8a6a6c863f7`.
Delivery starts from operational V2 `290cf74024717776cf05868cbd8da9bc3d6c02a5`
and includes that work additively, preserving the current recovery/retention fixes.

The latest whole interpretation **known by the cutoff** is selected before filtering
its match time. A failed or empty later revision cannot disappear behind an older
valid side. Exact retained provider-club bridges retain failed fixture identities;
unresolved identities and contradictory times fail closed with match IDs. A
transferred player's witnessed prior-club appearance remains linked by permanent
player code; the upcoming PL match belongs to the current registered club.

The five-day workload capture subset is **not** a complete fixture catalogue. Even
a traversed competitive schedule does not prove that all played fixtures were
captured. Consequently, this operational report currently emits `midweek_played`
where there is a valid witnessed appearance, and `unknown` otherwise. It does not
claim `full_rest` from absent records. The pure domain contract permits `full_rest`
only with explicit complete coverage and usable club-side interpretations.

The last seven days are reviewed. Midweek means Monday–Thursday UTC. Gaps are
kickoff-to-kickoff hours and whole Europe/London calendar days, **not recovery time**.
International-window overlap is qualified even when no last appearance is known;
national-team call-ups remain uncaptured. A partially measured workload total stays
NULL. Nominal SDP minutes never replace FPL's actual league minutes.

For PL comparisons, the retained corroborated fixture crosswalk plus permanent
player code, venue, opponent, kickoff and cutoff-known FPL history must agree.
The report carries both values and their capture/version provenance. A mismatch or
missing source leaves the FPL comparison unavailable; names never resolve identity.

## Publication and display

`build_sdp_dashboard` now emits `public/sdp/rest_summary.json` at the same reporting
cutoff, from a read-only DB connection, for the complete public player registry.
It validates the schema and privacy boundary, writes once, and binds its bytes and
SHA256 into the existing generation receipt. No new scheduler or provider call is
introduced. The existing `refresh_dashboard` path produces it on each successful
generation and the existing R2 publisher carries it in its immutable inventory.

R2 accepts exactly the existing 16-file generation or the explicitly extended
17-file generation. A rest file without its matching receipt, a missing file with
a receipt, tampering or private fields fails publication. Old generations remain
readable. Summary reads only the selected published generation; it never queries
DuckDB or fetches a sidecar from another vintage.

Joining requires the exact season, player code, club and next fixture/GW/kickoff.
A future report, started next fixture, schedule mismatch or absent sidecar shows
an explicit unavailable state while the raw xP table remains usable. Evidence and
limitations are expandable. Model output and current observed reporting timestamps
remain visibly separate.

## Operations

Use the existing refresh task and its existing locks, recovery policy and R2 config.
Do not start a second refresh while it runs. A standalone read-only report is:

```powershell
$env:PYTHONPATH = 'D:/Personal/workspace/the_comet_fpl/.worktrees/v2/src'
& D:/Personal/fpl-operations/.venv/Scripts/python.exe -m fpl.jobs.rest_summary `
  --db D:/Personal/fpl-operations/data/sdp-primary-v2.duckdb `
  --out D:/Personal/fpl-operations/rest-reports
```

The standalone command writes timestamped JSON/text without overwriting earlier
files. Run only while the operational writer is idle. Private `--codes` or
`--code-file` CLI reports are not public exports; the dashboard exporter never
passes a squad selector.

The local review uses the existing Vite application at `http://127.0.0.1:4174/`.
It is accessible on this computer only. Public UI publication remains the existing
reviewed main-branch/GitHub Pages workflow; a branch push does not publish the UI.

## Verification record

Focused tests cover revision/cutoff semantics, failed sides, missing data,
transfers, exact FPL comparison, ranking/ties/DGWs, legacy exports, privacy,
receipt hashes, write-once output and unchanged forecast export bytes. Actual run,
browser and frozen-file verification counts are recorded in the delivery result.
No historical model audit is rerun and no frozen verification record is rewritten.

The operational read-only run at **2026-09-19 07:17:26 UTC** covered 662 registered
players: 174 witnessed midweek appearances at player level, 488 unknown verdicts,
and zero full-rest claims. Rebuilding at the same cutoff reproduced the document
exactly. All 221 last-witnessed PL appearances joined to exact FPL minutes; 162
values matched and 59 differed between the two duration definitions. Neither
source was modified or silently substituted. Seven unresolved opponent-club sides
remain explicit source issues. This actual-time report is after the GW5 deadline;
it is not presented as a pre-deadline commitment.

Verification: 151 backend integration tests, 64 focused frontend tests, strict
mypy over 243 source files, Ruff, formatting and the frontend build passed. Pytest
reported a cache-directory permission warning; frontend lint retained nine existing
Fast Refresh warnings and no errors. All 226 previously pinned model/config/research
files and all ten retained forecast artifacts were unchanged. The machine-readable
record is `results/rest_summary_delivery_2026-09-19.json`.

Chrome verification rendered exactly 15 player rows on desktop and at 390×844.
Mobile table scrolling stays inside its container (no page-width overflow), the
evidence disclosure and full Players navigation work, and console inspection found
no warnings/errors. Actual screenshots are retained locally under
`data/artifacts/r1-closure-20260919/summary-{desktop,mobile}.png`, with hashes in the
delivery record. A transient screenshot/selector tool timeout was recovered using
a fresh tab; it is not counted as a successful screenshot attempt.

The already-running operational refresh completed at 07:20:51 UTC, published its
original 16-file R2 generation and completed retention. It used the prior code;
this report does **not** claim that run published R1. Subsequent successful refreshes
from the integrated operational branch include the new sidecar. The reviewed local
preview already uses the new report. Public Summary UI is not deployed by this task.
