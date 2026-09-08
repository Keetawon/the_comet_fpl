# Attacking Role Premium: retained-data feasibility, 2026-09-08

**Verdict D — INSUFFICIENT DATA.**
`INSUFFICIENT_DATA_FOR_ATTACKING_ROLE_PREMIUM_STUDY`

The requested study stops at phase 2, before score construction or formal preregistration.
There are only three completed gameweek batches with genuinely cutoff-eligible evidence,
and only two batches following captured current-season player observations. This is too
little longitudinal replication to assess recent usage changes, their persistence and their
incremental predictive value across the requested slices. Five seasons of retrospective
xG/xA do not create five seasons of historical knowledge-time evidence.

This is a source/feasibility decision, not a negative predictive result, a numeric promotion
threshold or a reinterpretation of any previous study. No player scores, positional percentiles,
shrinkage strength, regime-shift threshold, candidate weights or materiality gate were chosen.
No candidate was fitted, tuned, evaluated, promoted or integrated. Formal evaluation: **NO**.
Candidate preregistration commit: **not reached**. The new YAML registers the inventory scope
and feasibility decision only; it is not a frozen candidate design.

## Scope and retained evidence

Starting commit: `fcf8dc9636edceb8e40133db7a1a82ce756bde47`, matching the owner instruction.
Branch: `claude/comet-fpl-v2-architecture-mqrj8f`. Starting worktree was clean, with local and
remote V2 equal; remote-main divergence was 55 ahead / 1 behind.
Inventory boundary: `2026-09-08T06:34:33Z`, the actual task-start observation time.

The audit opens the preserved pre-deadline source database read-only:

`D:/Personal/fpl-operations/sdp-primary-runs/pre-deadline-20260908T032637.982207Z/forecast-source.duckdb`

SHA256: `538560454f551a48eeaf015c318f7dea0fc6a34fccc56ee7f0e2b117ef7330d6`.
It reuses the completed role-source result, SHA256
`6a92fc3e421d3d74de543a080a61077364435545e5dcd7d1ff26068563faf607`.
No new network request, player capture, source probe or historical backfill was made.

Sources inspected include the raw archive headers/ingest receipts, player-fixture marts,
versioned live registry/history, raw FPL snapshots, raw SDP team statistics, lineups/events,
the role-source result and retained forecast provenance. The raw FPL inventory covers all
5,671 element-summary payloads and 11,180 history-row versions. The SDP inventory covers
1,931 match-stat payload versions / 3,862 team sides and ten current lineup/event pairs.
Versions are distinguished from unique matches and player-fixture observations.

The earlier role audit's 23 matches are a bounded interpreted sample, not all retained
participation data. The separate workload capture report records 574 historical matches /
1,148 lineup-event endpoints, including all 380 PL matches in 2025-26, captured September 7.
Those endpoints supply participation evidence, not a measured player shot/touch stream.
Their capture does not extend the earlier strict-cutoff evaluation period.

## Player opportunity coverage

Counts below include outfield DNP rows where retained; appearances require positive measured
minutes. They are inventory counts, not a frozen predictive population. Player counts within
position/season can overlap after registration changes.

| Season | Player-fixture rows | Stable players | Appearances | Minutes | xG and xA measured rows |
|---|---:|---:|---:|---:|---:|
| 2021-22 | 22,537 | 654 | 9,722 | 681,069 | 0 |
| 2022-23 | 23,714 | 693 | 10,575 | 680,719 | 16,092 |
| 2023-24 | 26,312 | 765 | 10,608 | 680,238 | 26,312 |
| 2024-25 | 24,414 | 702 | 10,796 | 680,067 | 24,414 |
| 2025-26 | 26,320 | 744 | 10,725 | 680,157 | 26,320 |
| Archive total | 123,297 | 1,577 | 52,426 | 3,402,250 | 93,138 |
| Latest live 2026-27 GW1-3 | 1,682 | 583 | 869 | 53,723 | 1,682 |

| FPL position | Archive rows / players / appearances | Latest-live rows / players / appearances |
|---|---|---|
| DEF | 46,293 / 586 / 18,928 | 623 / 214 / 330 |
| MID | 60,343 / 788 / 26,474 | 835 / 291 / 434 |
| FWD | 16,661 / 254 / 7,024 | 224 / 78 / 105 |

Player xG and xA are the available direct opportunity measures. Coverage is complete in the
three latest archive seasons and the live sample, absent in 2021-22 and partial in 2022-23.
Minutes support exposure; starts are absent in 2021-22. Threat and creativity are provider
composite indicators, not measured shots or key passes. Expected goal involvement is redundant
with xG+xA and supplies no new independent opportunity dimension.

There are no player shots, SOT, non-penalty shots/xG, key passes, chances created, box touches,
penalty-area entries or crosses in these retained raw player-match sources. No individual
open-play/set-piece tags establish a separation. Goals and assists remain outcomes, not
substitutes for missing opportunity counts. Missing fields remain NULL/unavailable.

The SDP statistics envelope is team-side grain (`side`, `teamId`, `stats`). Its
`fastestPlayer` object is speed/identity evidence, not a player attacking-stat array.
Team `attOpenplay`, `attSetpiece`, `attAssistOpenplay` and `attAssistSetplay` cannot distinguish
an individual defender's set-piece threat from open-play advanced usage. Team xG/shots/box
touches are not silently assigned to players. No team-share denominator or composite score
was constructed after the feasibility stop.

## Actual deadline-eligible support

The current retained raw archive version has `_ingested_at = 2026-08-19T09:00:51.396626Z`.
Matching archive hashes also have earlier July 26 ingestion-log witnesses. Either boundary
is later than every archive target season and earlier than 2026/27 GW1. The audit conservatively
uses the current raw-version boundary. Thus archive observations can be legitimate prior
information for GW1-3 in 2026/27, while they cannot be relabelled as known before their
original historical deadlines. Source-native historical positions and clubs remain intact.

| GW | Official deadline UTC | Latest outfield outcome rows | Exact pre-cutoff registry/club match | Appeared matched rows |
|---|---|---:|---:|---:|
| 1 | 2026-08-21 17:30 | 543 | 531 | 287 |
| 2 | 2026-08-28 17:30 | 556 | 542 | 282 |
| 3 | 2026-09-04 17:30 | 583 | 581 | 287 |
| Total | Three chronological GW batches | 1,682 | 1,654 | 856 |

The 28 unmatched rows comprise 21 absent pre-cutoff registry entries and seven position/club
mismatches. This is a joined-coverage audit: eventual outcome membership is not a licensed
prospective roster. A future evaluation must freeze the full registry and fixture population
before reading target outcomes, including DNPs and every DGW leg.

First retained live player-history availability is August 25 15:53:15.572138Z for GW1,
September 1 01:48:41.593805Z for GW2, and September 7 15:05:40.829517Z for GW3.
GW1 performance can inform GW2; GW2 performance can inform GW3. GW3 observations can only
inform later predictions. GW4's September 12 deadline and outcomes have not occurred.

Prior paired-measured xG/xA exposure among the exact-registry population is substantial for
many returning players, but it does not increase the number of target GW clusters:

| Target GW | >=90 prior minutes | >=180 | >=360 | >=720 | No prior row | No positive measured exposure |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 391 | 368 | 357 | 332 | 88 | 104 |
| 2 | 404 | 364 | 355 | 329 | 4 | 67 |
| 3 | 433 | 387 | 366 | 342 | 21 | 79 |

These are player-target counts, not unique independent players. Measured exposure requires
positive minutes and both xG/xA; missing signal contributes neither numerator nor exposure.
Within the current season alone, history before a completed target reaches at most 180 minutes;
no such target has >=360 or >=720 current-season prior minutes. At the inventory end, after
all three GWs, 232 unique players have >=90 minutes and 165 have >=180; none has >=360 or >=720.

Last measured historical club differs from the cutoff registry club for 54 / 23 / 31 targets
in GW1 / GW2 / GW3. Last measured FPL position differs for 12 / 4 / 4. These are witnessed
changes, not inferred transfer dates or registration intervals. Club identities use permanent
codes through season-qualified dimensions; player joins use stable FPL code, never names.
No premium or meaningful-shift count is computed: those fields are NULL, not zero.

## Fixture and formation context

The immutable DB contains 22 earlier forecast vintages. Retained incumbent goal PMFs and
fixture context cover all 30 completed fixtures / 60 unique team sides, with at least one
source-eligible vintage by each official deadline. An independent availability check reconciles
creation time, declared cutoff, FPL bootstrap hash/time and schedule capture times. Latest chosen
CS values exactly equal opponent PMF mass at zero. This checks retained artifacts; it does not
rerun a model or establish incremental predictive value.

Ten early GW1 vintages were generated before their forward-declared deadline cutoff. That
original provenance is preserved; generation time is not rewritten to equal the deadline.
The earliest SDP capture is also not uniformly after all current deadlines: before GW3 it
includes older-season observations and two current-season fixtures. Those are legitimate
pre-cutoff observations once captured, but do not establish a complete SDP-backed target
environment or a previously published SDP-primary forecast for these GWs.

The completed observed-role interpretation became available September 8. Consequently zero
of its formation-band records are eligible at the three completed target cutoffs. No target
formation or retrospective September interpretation is smuggled into those predictions.
Formation support is optional; its absence alone is not the feasibility failure. Existing
incumbent fixture context is available, and its absence is not claimed as a failure either.

## Scientific questions left open

| Owner question | Answer supported by this audit |
|---|---|
| 1. Useful player attacking statistics? | xG/xA have useful retrospective coverage; strict evaluation support is limited as above. |
| 2. Best metrics to separate attacking profiles within position? | Not estimated. xG and xA are available; no comparative score/correlation study was run. |
| 3. Open-play usage versus set-piece threat? | Not reliably separable from retained individual data. |
| 4. Required shrinkage? | Not fitted or selected. Exposure coverage is reported without choosing a prior strength. |
| 5. Premium stability? | Unknown; no premium constructed. |
| 6. Frequency of material recent shifts? | Unknown/NULL; no shift definition or threshold selected. |
| 7. Positive-shift persistence? | Not evaluated; the shortage of longitudinal batches is decisive. |
| 8. Better next-match shots prediction? | Not testable with current player-shot coverage. |
| 9. Better next-match xG prediction? | Not evaluated. |
| 10. Better next-match xA prediction? | Not evaluated. |
| 11. Incremental formation-band value? | Not evaluated; no existing role interpretation passes completed target cutoffs. |
| 12. Is formation necessary? | It remains optional in the requested architecture; necessity has not been empirically tested. |
| 13. Value beyond FixtureEnvironment? | Not evaluated; retained incumbent context exists and must be a fair comparator later. |
| 14. Especially useful for DEF? | Unknown; defenders did not determine a score, threshold or selected sample. |
| 15. MID/FWD performance? | Unknown; both are included in source coverage only. |
| 16. Find attacking defenders without exact labels? | A plausible study objective, not an established result or confirmed OOP classification. |
| 17. O'Reilly, Hume, De Cuyper? | New attacking-stat case analysis not reached; no generic methodology was frozen. Prior source-audit cases remain unchanged. |
| 18. Safe future Player Stats input? | A potential future contract only. No score is validated or licensed for model input now. |
| 19. Is exact Player Role prediction necessary? | It is not a prerequisite for the requested opportunity study. This audit makes no empirical claim about its eventual incremental value. |

No MAE, RMSE, rank correlation, calibration, count loss, persistence or confidence-slice
result is reported. No reliable-versus-low-confidence classification, positional normalization,
shrinkage or recent-versus-long-term method is preregistered at this stopped phase.

## Reproduction, safeguards and verification

The additive CLI reads pinned inputs and emits a deterministic, write-once JSON inventory.
It has no network, fitting, model evaluation or production-writing path. The config/result
retain the strict knowledge-time boundary and input hashes; external execution receipts retain
actual start/completion times separately from the fixed inventory boundary.

```powershell
python -m fpl.jobs.audit_attacking_role_premium_feasibility --db D:/Personal/fpl-operations/sdp-primary-runs/pre-deadline-20260908T032637.982207Z/forecast-source.duckdb --role-result results/player_role_source_audit_2026-09-08.json --config config/attacking_role_premium_study.yaml --output D:/Personal/fpl-operations/verification/attacking-role-premium-feasibility-20260908T063433Z/feasibility.json
```

Use a new output path for a replay. Historical source versions remain immutable. A later
revision cannot enter an earlier cutoff, NULL is never filled from an older value, same-GW
history is excluded, and target observations are separated from eligibility inventories.
The generic archive PIT API alone does not prove historical knowledge-time validity when
the archive table has no `known_at`; this auditor additionally checks retained ingestion time.
It introduces no retrospective exception to production `FeatureSource`.

The immutable inventory is retained in
[`results/attacking_role_premium_feasibility_2026-09-08.json`](../results/attacking_role_premium_feasibility_2026-09-08.json).
Its embedded Git identity is the clean audit execution commit, not a candidate preregistration.

| Verification | Result |
|---|---|
| New feasibility tests | 23 passed, 0.83 seconds |
| Existing PIT, live snapshot, observed-role, SDP-primary and ledger regressions | 162 distinct tests passed |
| Ruff `check .` | Passed |
| Strict mypy `src` | Passed, 205 source files |
| Changed-file Ruff formatting | Both new Python files passed |
| Git whitespace check | Passed |
| Pre-existing config/result/model/feature/artifact/storage fingerprints | 157 checked, none changed |
| Independent source/deadline/exposure/identity reconciliation | Matched the inventory counts |
| Independent retained forecast context reconciliation | 112 raw hashes, 30 fixtures / 60 sides, zero failures |

The broader invocation initially passed 113 tests but hit 49 setup errors because Windows
denied access to the default pytest temporary directory (`WinError 5`). Only those blocked
cases were rerun with a new isolated `--basetemp`; all 49 passed. This required no source or
permission changes. The new focused tests also used a new isolated temp directory.
The full repository suite and global formatting were not rerun. Previously documented
Windows symlink-privilege failures and 11 unrelated global-format failures remain inherited;
no repository-wide green claim is made.

Execution receipts, the two independent reconciliation scripts and test reports are retained
under `D:/Personal/fpl-operations/verification/attacking-role-premium-feasibility-20260908T063433Z/`.
`independent-pit.json` has SHA256
`064859e5906ebd0d6b57a20a0067814a9a9023799e6d88aa8450150b380d2428`;
`independent-context.json` has SHA256
`5afff68046e91d68cae6917acc5656f9924a10621d7597fcf32e1836a4a5795d`.
Their scripts and actual execution times are pinned inside those receipts. These are inventory
reconciliations, not repetitions of frozen scientific evaluations.

Score/normalization/shrinkage/causal-prediction tests are not claimed: those components were
deliberately not implemented. Applicable source/version/identity/batch/NULL/replay tests and
existing PIT/production regressions verify the additive audit boundary.

Frozen research, production player models, SDP primary/fallback/shadow behavior, optimizer
and prospective evidence ledger remain unchanged. No main/default-branch modification, merge,
PR, rebase or history rewrite is performed. Delivery is confined to the V2 branch.

**Exactly one next task:** design a bounded player attacking-stat historical backfill,
including explicit retained publication/availability evidence and a feasibility assessment of
which historical cutoffs it can actually support. A new backfill's capture time must remain
current; downloading old matches cannot manufacture historical PIT evidence. That design and
backfill are not implemented in this session.
