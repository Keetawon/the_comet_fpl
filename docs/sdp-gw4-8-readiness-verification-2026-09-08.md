# GW4–8 checkpoint and observed-statistics delivery verification

The checkpoint adapter and two descriptive dashboard routes are implemented. The
registered GW4–8 cohort is **PENDING**: no selected GW has finalized and no future
performance metric has been computed. Current FPL/SDP data were refreshed on the
existing owner host. A local preview serves the new exports. Live Pages publication
and browser screenshots remain blocked as described below.

## Frozen identity and prospective selection

Starting commit: `e7b3b3415b5d27e2b7cfc3f987fab022a1dedf0b`.
Branch: `claude/comet-fpl-v2-architecture-mqrj8f`, worktree `.worktrees/sdp_test`.
The model remains `17cfa2267ce4d7c89f96842220f40471b81152d2`.
GW1–3 V2 remains MIXED / NO FREEZE, retrospective diagnostic evidence only.
Original V1 remains INVALIDATED_BY_IMPLEMENTATION_BUG. Neither audit was rerun.

The selected pair is
`0cca9d810d3f984f30f53d37a8ad3a494f20266d910e4acc1ec161bce582fafb`:

| Property | Verified value |
|---|---|
| Forecast cutoff | 2026-09-08 03:52:24.844595 UTC |
| Actual pair registration | 2026-09-08 03:53:18.937809 UTC |
| Forecast emitter | `2a96e91ee49604e152f77e47ff6e1bcf9d7037af` |
| Primary SHA256 | `566fe684a14ce2edc707286968d470891e7854e7e1ac44733fc0ab3d17d4914a` |
| Shadow SHA256 | `d1e48736d869a697f79e9b383a0d627f7a3632e1b4b18321c933dc421385361e` |
| Population per role | 654 players, 50 fixtures, 3,270 player-GW and 3,270 player-fixture rows, 100 team sides |
| Frozen selectors | 21 SDP_PRIMARY; 29 SDP_INCOMPLETE_FALLBACK |

The original bootstrap deadline witness and all 556 referenced source versions
were revalidated read-only. The original forecast-source DB remains unchanged.
All 57 transitive inference/config Git blobs agree between emitter and model freeze;
an older emitter commit does not imply different model content.

No prior fixed-origin/rolling selection rule or numerical final promotion gate was
found. The later selection addendum was committed before this refresh and before
eligible checkpoint outcomes were inspected, at
`116db25e1d3046a6b6369c736f01d4bc657e5157`. Its actual registration time is
13:23:50 UTC on September 8. It is not backdated to the forecast's creation.
The fixed-origin cohort and later rolling vintages remain separate. There is no
new numerical promotion threshold.

## Real refresh and schedule

The existing `daily_pl_sdp --lookback-days 5 --workload --player-history` flow ran
against `D:/Personal/fpl-operations/data/sdp-primary-v2.duckdb` from
**13:24:07.750092 to 13:53:39.210386 UTC**, with its normal writer lock and verified
pre-write backup. Receipt:
`sdp-primary-runs/20260908T132407.750092Z-7cd8385d/report.json`.
Exit 0; capture/staging health true; no request failures.

The new authoritative bootstrap says **GW3 is current, finished and data_checked**;
GW4 is next and unfinished. There is **no partially completed GW**. Thirty fixtures
have finalized in total across GW1–GW3. The latest match kickoff is September 6,
15:30 UTC. The next official
deadline is **September 12, 12:30 UTC / 19:30 Asia/Bangkok**, witnessed by the new
bootstrap, not inferred from the clock.

| Source | Actual refreshed coverage |
|---|---|
| FPL player-history capture | 657 payloads, 654 registered players; known_at 13:35:11.208041 UTC |
| FPL observed player fixtures | 1,890 rows; xG/xA measured on all 1,890; 929 positive-minute rows |
| SDP team payloads | 30/30 current fixtures retained; 13 bounded revision requests succeeded, zero new stat payload versions |
| SDP core validity | 26/30: GW1 9/10, GW2 8/10, GW3 9/10 |
| Still incomplete | FPL fixtures 7, 19, 20, 28; retained with unavailable SDP metrics |
| SDP lineups/events | 10/10 recent PL matches refreshed; 401 matched player-fixture participation rows |
| Other workload competitions | Existing six-competition flow checked; no additional completed relevant cup/European match selected |

Successful checks do not advance unchanged payload known_at. The latest current
team-stat raw version remains September 7, 14:38:12.903979 UTC. The newest SDP
listing is September 8, 13:53:35.925253 UTC; the dashboard labels this broader
timestamp “Latest SDP known”, rather than implying every statistic was revised.

The existing **The Comet FPL - SDP primary V2** task is registered, enabled and
Ready. Last scheduled result 0; next run September 9, 00:00 UTC / 07:00 Bangkok.
It includes workload but not full player history; the runbook's explicit refresh
includes both. The health check at 14:01:23 UTC reported healthy and successful
capture age **0.128811 hours**. There was no unresolved WAL/lock after the writer
closed. The unrelated legacy **The Comet FPL - daily SDP** task last returned 1;
it uses a different database and was left unchanged. No scheduler or infrastructure
was added or migrated. The ordinary pre-deadline flow remains independently callable;
this task generated no replacement forecast.

## Checkpoint execution

`score_sdp_checkpoint --attach-outcomes --backup NEW_PATH` validated the pair,
then called the existing authoritative attachment under the existing writer lock.
It appended 654 player and 20 team outcomes for already-finalized matches;
1,236 player and 40 team outcomes were exact existing repeats. No selected GW4–8
outcome was eligible.

Both initial scoring and its read-only repeat returned **PENDING**, zero finalized
GWs, zero scored player/team pairs, and report version
`c1ba2f464f3deedd219b73349640929476f4a678ff9b5fd2ba6b966529323562`.
The repeat returned `created: false` with identical bytes. All performance metrics
remain uncomputed. The report retains the 21/29 forecast selector split separately
from current source completeness.

Synthetic integration proves whole-GW/DGW finality, common paired populations,
signed official errors/ranks, per-leg PMF coarsening, the existing log floor,
vintage separation and immutable report versions. Future reports expose per-GW,
pooled, position, selector, top-K/captain and team scores. No component sidecars
were retained for this pair, so component/forensic diagnostics remain NULL with
reasons. Availability-adjusted decisions are not silently mixed with raw scoring.
Five-GW block uncertainty waits for all selected blocks; row count is never called
independent temporal evidence.

## Dashboard delivery and source reconciliation

The existing application now includes **Team stat from SDP** and
**Players stat from SDP**. The public sidecar has 44 SDP team metrics, two clearly
labelled FPL team-score fields and 16 FPL player fields. It includes exact mirrored
opponent shots/xG, source-native attacking/box/possession/passing/defensive/discipline
counts, and actual FPL minutes, starts, xG/xA, goals/assists, saves, DC, BPS/bonus/cards.
Optional missing metrics remain NULL; unreconciled provider semantics remain flagged.
There are **no detailed SDP individual-player stats** in retained endpoints.
Player SDP data are explicit XI/bench/broad-position participation observations;
FPL enrichment is never called SDP xG/xA. Nominal event-clock durations are excluded
from per-90 denominators.

Season/GW/venue/team and recent-three/five filters, name search, player position and
minimum minutes, sortable tables, detail logs, trends, up-to-three comparisons and
CSV exports are descriptive only. Counts sum; possession is explicitly a per-match
mean; player rates use matched actual FPL minutes. The current default has 20 teams
and 654 players. Thirteen teams have complete three-match xG/opponent-xG for the
scatter; seven remain unavailable. There are 387 positive-exposure player rates,
267 players with zero observed minutes, 469 below 180 minutes and 185 at 180–449 minutes.
No player has 450 minutes yet. Historical team coverage is very uneven and never
presented as complete six-season coverage.

Two team and two player rows were independently reconciled to raw hashes,
provider fields, deterministic identities, official fixture-time clubs, actual
minutes and explicit formation membership. All checks passed. Both complete real
sidecars passed the frontend parser; the separate exports differed only in as_of.

Three current-season SOT values are now recorded as owner-confirmed display
corrections at `2026-09-08T14:40:50.135115Z`: fixture 7 Aston Villa,
fixture 20 Aston Villa and fixture 28 Spurs, each with value zero. Their immutable
raw SDP payloads omit `ontargetScoringAtt`; none is rewritten. Exact shot-accounting
reconciliation and the opponent's official FPL goalkeeper record (90+ minutes,
zero saves) corroborate the owner confirmation without changing provider validity.
Fixture 19 Fulham remains NULL because it has no owner confirmation. The current
provider health population therefore remains **26 core-valid of 30 completed
fixtures across GW1-GW3**, while **three separate display corrections** are exposed
with provenance in the table, charts and CSV.

The first full public package was correctly refused because this operational DB
has no required platform optimizer plans. The failed generation was preserved.
The completed preview explicitly retains a sanitized existing dashboard base
generated September 4, 06:53 UTC, with its older forecast vintage, while the new
tabs use the new statistics. Fresh BI/read-model exports are retained separately.
No optimizer or forecast was rerun to manufacture plans. Windows symlink
publication still fails with inherited WinError 1314; validated before_publish
copies were retained using the documented existing hook, not called a passed gate.

Final statistics export as_of: **2026-09-08 15:17:24.331811 UTC**;
7,256,219 bytes; SHA256
`c47fe610b9b8c8382a3cb0d7cedba1ee985ae496210fdd7dd7191b5c426af26d`.
Eighteen HTTP-served preview assets matched their built bytes, including the
sidecar and both new route labels in the JS bundle.

Local owner-host preview, not public deployment:

- <http://127.0.0.1:4173/#team-stat-sdp>
- <http://127.0.0.1:4173/#players-stat-sdp>

Browser discovery returned zero connected browsers. Therefore rendered desktop/
mobile review, console inspection and screenshots are **not verified**; HTTP and
React interaction tests are not substitutes for those checks. The owner was asked
to connect Browser. The existing live Pages flow is main-only, and this task forbids
a main merge. The optional immutable SDP release-companion step is prepared on V2,
but no release pin, live site or default branch was changed. These are the two
remaining delivery blockers, not modeling work.

## Verification and evidence

- New checkpoint/export/privacy integration: 94 tests passed; after the explicit
  retained-base addition, all six wrapper tests passed (two additional cases).
- Relevant production/SDP/player/scouting regressions: 206 passed, including
  synthetic forecast/optimizer isolation. Existing PuLP deprecations remain.
- Frontend: focused SDP suite 42 passed; 19 affected library/page tests passed
  after final CSV labels. Earlier full suite: 345 passed, one existing unchanged
  PlayersPage timeout; that test passed once in isolation without timeout changes.
- Ruff `src tests`: passed; strict mypy `src`: 227 files passed; changed eight
  Python files format check passed; TypeScript/Vite build passed.
- Frontend lint: zero errors, nine inherited Fast Refresh warnings. Existing
  bundle-size warning remains. No claim of full-repository green.
- Initial default pytest temp path failed with inherited Windows access denial.
  One rerun using a new explicit writable basetemp passed; no repeated retries.
- Independent frozen-file check: **392/392 unchanged**, including model/config,
  old V1/V2 evidence, both committed forecast artifacts and original source DB.
- Independent before/after operational ledger check: **149,025 complete rows in
  five forecast/pair tables unchanged**, including xP, PMFs, team environments and
  provenance. No optimizer tables existed in either operational copy; code hashes
  and synthetic isolation cover the unchanged optimizer behavior.

External evidence root:
`D:/Personal/fpl-operations/verification/gw4-8-checkpoint-20260908T131550Z`.
The additive machine-readable readiness receipt records hashes and exact coverage;
private DBs/raw captures are not published. Follow the
[existing-host command runbook](sdp-gw4-8-operations-and-dashboard-2026-09-08.md)
for the next checkpoint. No future matches are awaited by a polling process.

**PLAYER MODEL FROZEN — GW4–8 PROSPECTIVE CHECKPOINT.**
