# Current V2 player model: frozen GW1-3 diagnostic preregistration

This is a **RETROSPECTIVE FROZEN DIAGNOSTIC**, not prospective confirmation, a
promotion gate, or permission to tune. The model was developed after these outcomes
were observable. Even an input-PIT-clean replay cannot remove that development-process
contamination. Three gameweeks do not provide many independent temporal experiments.

## Freeze and scope

Phase A was completed and pushed cleanly at
`17cfa2267ce4d7c89f96842220f40471b81152d2`. That exact commit is the model/config freeze.
The descriptive scouting layer remains outside every inference and optimizer path.
Attacking Role Premium V1 remains **C: REFUTED**; its experiment is not rerun.

The accompanying `config/player_model_gw1_3_audit.yaml` pins 339 pre-existing source,
configuration, instruction and result files. It also pins the immutable read-only
forecast source database to SHA256
`538560454f551a48eeaf015c318f7dea0fc6a34fccc56ee7f0e2b117ef7330d6`.
The preregistration commit records this document, configuration, validation adapters,
runner and synthetic tests before real predictions or scoring. Runtime provenance
records that actual execution commit separately from the Phase A model identity.

There is one shared Git-common-directory claim for
`player_model_gw1_3_20260908_v1`. The output directory is fixed in the config, publication
is exclusive/write-once, and resume/overwrite is forbidden. A failed run retains its
identity and partial artifacts. A model implementation defect invalidates the audit;
it is not silently fixed and rescored. No new data are fetched and the database is
never written. No main merge, default-branch change, PR or history rewrite is authorized.

## Exact current model and required comparator

Call the unmodified `predict_prospective_points` once per lane and gameweek, with
`gw_from == gw_to == target_gw`, at that GW's official deadline. Preserve:

| Setting | Frozen value |
|---|---|
| Attacking | `v3`, minutes-gated team-coupled trailing xG share |
| Appearance | `seasonal`, existing season-boundary correction |
| Share signal | `auto` |
| Assists | `coupled`, existing trailing xA allocation and league assist scale |
| Draws | 2,000 per fixture |
| Base seed | 202627; existing deterministic fixture-seed derivation |
| Fixture points support | 0 through 34, existing tail folding |
| Team environment | `sdp_v2`, existing selector and incumbent fallback |
| Incumbent | Existing recursive `football_environment_primary=disabled` shadow |
| GK H | Existing prospective shadow-only policy; never scoring |

The comparator is **the same current player components with the incumbent team
environment**, not a newly assembled older full-player model. Registry, schedule,
cutoff, draws, seed, scoring rules and horizon are identical. The incumbent remains
`trailing_goals_attack_defence`. The current minutes component is the existing V3
concentration-adaptive estimator plus its existing price/cold-start and seasonal
corrections. Its normal history-only six-GW nested parameter-selection routine is
preserved exactly; this audit introduces no search, alternatives or target-result
tuning. Routine fitting on allowed history is part of the frozen inference procedure.

The default suite retains its existing xG-goals V1 and xA-assists V1 estimators where
the current implementation uses them, GK saves V1, and defensive-contribution V1.
The default team-coupled goals and assists paths are unchanged. Clean sheets derive
from the opponent goal PMF. Joint per-fixture BPS/bonus composition, fitted residual
procedure, scoring lookup and measured conceded exposure `(0, .344, .813, 1)` remain
unchanged. No cards, penalties or other absent component is invented for this audit.

Availability is the existing reported overlay. Score raw published distributions/xP;
do not multiply their PMFs by availability or use adjusted utility as a new forecast.
Retain status/multiplier for diagnostics. Starting probability is not provided by the
four-bin minutes contract and must remain unavailable.

## Historical inputs and exact cutoffs

All 56 retained bootstrap witnesses agree on these official deadlines. Selected
pre-deadline registries and schedules each contain ten future target fixtures.

| GW | Official cutoff UTC | Registry known_at UTC | Players | Prior current-season history |
|---|---|---|---:|---|
| 1 | 2026-08-21 17:30 | 2026-08-21 06:41:56 | 599 | None; valid preseason state |
| 2 | 2026-08-28 17:30 | 2026-08-27 17:19:42 | 616 | GW1 capture, 2026-08-26 08:16:56 |
| 3 | 2026-09-04 17:30 | 2026-09-04 11:05:54.219177 | 652 | GW1-2 capture, 2026-09-02 03:22:31.942069 |

Exact selected capture IDs are frozen in the YAML. The selected bootstrap and
schedule hashes are:

| GW | Bootstrap SHA256 | Fixtures SHA256 |
|---|---|---|
| 1 | `7db0a660b7c0a71c0bb71cbfc8feb2db780439a7d5190a6843224a9cad60b7e1` | `0058ca4b1a4645ddf1c863c2fb31629ef581f14a85cec9ec49affcf7ef54fdbf` |
| 2 | `c9ae2a5045ca93ddab3645bf6d91ef4e3bbfe9fff2aed93a61e40b4460928a56` | `ff77d62793e06a7b24c9789ca1be5722733483c7d0261728a3961f8bfa7da684` |
| 3 | `b3b4a99cb5e3479d92a0e7b85df86dab32f59bed5894cc731d380591f4eeec57` | `f2f590480b98e10de09c5aabc734dfcc6cb0061cdcd8998cc9ee02d7fb18e25b` |

The five archive priors are permissible for these 2026/27 cutoffs: all 20 retained
CSV hashes match their July 26-August 19 ingestion receipts, with no later archive
ingestion. The last raw ingestion was August 19 at 09:00:51.396626 UTC. Bidirectional
multiset comparisons show zero differences between those CSVs and every raw table,
and between unchanged transformation SELECTs and eight consumed staging/mart tables.
The marts contain 138,707 prior player fixtures and 3,800 prior team sides.
These receipts establish possession before GW1, **not** availability at 2021-26
historical deadlines. No retrospective timestamp is relabelled.

The metadata inventory verified 1,255 selected raw payload hashes and source
completeness without scoring outcome values. Current-history captures provide 610
prior GW1 rows for GW2 and 1,236 GW1-2 rows for GW3. Missing evidence stays NULL.
Fixture-time identity, historical position, permanent player/team codes and exact
schedule sides are used; no fuzzy names, current-club substitution or pulse-ID shortcut.

### Lane A: strict actual input availability

Use the unmodified production input reader and selector. Every live source must be
known by the deadline and every historical event must precede it. Exclude the whole
target GW, including all DGW legs. The metadata preflight rejects a target leg already
inside historical time rather than allowing within-GW learning.

The frozen SDP parameter artifact is known only at
`2026-09-07T07:05:48.740385Z`, later than all three cutoffs. The exact production
loader therefore gives `SDP_MISSING_FALLBACK` (model unavailable at cutoff).
There are no SDP captures before GW1/GW2 and only two current match-stat captures
before GW3; this does not waive the frozen model-availability gate. No workload
lineup/event evidence is available before these cutoffs. GK H's September 7 artifact
is likewise unavailable and remains shadow-only. Expect strict V2 and incumbent
equality; assert it without tolerance on every fallback player distribution and input.
Still score the absolute player-model quality.

### Lane B: retrospective SDP counterfactual

This explanatory lane uses actual retained evidence as of
`2026-09-08T09:53:00.642943+00:00`. Load the same frozen SDP parameters and unchanged
source-health reader at that real frontier. Explicitly waive only historical
availability of SDP/crosswalk evidence and that parameter artifact. Preserve every
original source/model timestamp and hash in output.

The source-version policy is the latest whole valid production source at that
evidence frontier; an invalid latest version does not revive an older payload.
Historical football-event and whole-GW cutoffs still apply. Only current fixtures
whose identities exist in the historical FPL schedule may enter. The historical
schedule also owns required recent-match coverage; subsequent FPL identities cannot
enlarge the population. Missing/incomplete/schema/identity failures still fail closed.
The parameter training frontier is the frozen 2025/26 GW38 fold, before every target.

`sdp_counterfactual.py` pins the production selector source and model fingerprints,
mirrors its selection arithmetic and calls its unchanged prediction implementation.
Its scoped adapter restores the original selector after use. It never changes DB
rows, model parameters, timestamps or production modules. The recursive disabled
incumbent bypasses the adapter. Synthetic strict-eligible parity tests must pass.
This lane is **RETROSPECTIVE DEVELOPMENT / COUNTERFACTUAL**, never prospective
evidence, and cannot determine promotion or overrule Lane A.

## Forecast freeze, outcomes and scoring

Produce all twelve artifacts (2 lanes x 3 GWs x current/incumbent), plus transparent
composer-input sidecars, before invoking the official-outcome reader. The observer
calls the exact composer once, consumes no random numbers, preserves arguments and
records the component PMFs already used. Freeze all artifact hashes and validate
the complete manifest before reading outcomes. No target rows are fed back within
a GW. Prior completed GWs enter later predictions only via deadline-eligible captures.

The outcome source is the pinned complete player-history capture
`1bfb3d92-6d5e-48bf-a665-1f489dc6c1da`, captured at
`2026-09-08T03:37:39.610696Z`, manifest SHA256
`60a69282830fca5f757bddd11a10f51ec074ead4fed8aacad20f825c31c2c526`.
It has 654 summaries, bootstrap, fixtures and event-live. Before scoring, verify raw
hashes, official GW finality, completed fixture state and exact player/fixture/team/
opponent/GW identity. Missing history is not zero points. Report missing, contradictory,
extra and nullable outcome rows explicitly; use only common valid observations.
Player-fixture totals use the official recorded 2026/27 points, with no reinterpretation
of historical scoring rules. Source roster completeness alone is not outcome finality.

Primary proper metric: existing total-points **CRPS**. Secondary: existing log score
(probability floor `1e-12`), signed-points xP MAE, predicted-minus-actual mean bias,
and Spearman. The current composer folds negative points into zero and high points
into 34. Thus CRPS/log score assess that explicitly coarsened target, not an exact
signed-points PMF. Report folded observations and zero-support/floor hits. For DGWs,
convolve exact fixture PMFs and sum individually coarsened outcomes for proper
scores; sum signed official outcomes for MAE/bias. Missing any leg excludes that GW.

Report fixture and player-GW grains, pooled/GW/position/selector/cold-start/transfer
slices, and probability calibration for points <=2, >=5 and >=10 in ten fixed bins.
Promoted-club labels are reporting-only: exact current stable club codes absent from
the complete, pre-deadline-witnessed prior PL team dimension; missing evidence is NULL.
They are appended to diagnostic sidecars after inference and never enter the composer.
Rank within GW by raw xP, breaking ties by stable code. Top 10/25/50 report mean,
median, >=5/>=10 hit rates and deterministic actual-top-K overlap. Captain top1/3/5
report actual points; regret is the eligible hindsight maximum minus top1 actual.
This is descriptive utility, never a training objective.

Paired differences are current-minus-incumbent on identical valid observations.
Report each GW's direction. Enumerate all 27 three-GW bootstrap resamples for a
descriptive 95% interval. State `n_GW = 3`; player rows do not create independent weeks.

## Component and forensic diagnostics

Use existing distributions and scoring rules, not new models. Score appearance and
P(60+) calibration, expected-minutes proxy from bin representatives `(0,59,89,90)`,
and minute MAE. False-nailed: P(60+) >=.8 and actual minutes <60. Missed starter:
P(appearance) <.2 and actual starts=1. Exact starting probability remains NULL.

For goal/assist/save counts, apply the same appearance gate as composition, then
report available proper/count expectation metrics. Team CS is opponent-PMF mass
at zero against the official team score, deduplicated by fixture/team. Player CS
credit uses existing minute-bin eligibility and conceded-exposure thinning. Report
DC award probability/observed threshold, not invented raw-action counts. Report
expected bonus MAE/bias and any-bonus probability Brier; no full bonus PMF exists.
Missing source components remain unavailable. Residual BPS parameters are diagnostic
inputs, not an invented BPS forecast.

After formal scoring, select the top 25 absolute player-GW raw-xP errors, stable season/GW/code
tie-break. Show observed versus expected points/minutes/components, environment and
availability. Use fixed descriptive categories MINUTES/START, GOAL EVENT VARIANCE,
ASSIST EVENT VARIANCE, TEAM GOAL/CS ENVIRONMENT, GK SAVE, DC, BONUS/BPS, AVAILABILITY,
MULTIPLE, UNEXPLAINED. Transport labels map these to MINUTES, GOALS, ASSISTS,
CLEAN_SHEET/GOALS_CONCEDED, SAVES, DC, BONUS, MULTIPLE and UNEXPLAINED. Availability
is retained as context, not assigned a causal residual. Component residual dominance
is descriptive arithmetic, not causal identification; absent components remain
unexplained. No miss triggers a fix.

## Diagnostic verdict and resource decision

Issue exactly one verdict, prioritizing valid Lane A:

- **PROMISING** only for better pooled proper score, favorable direction in at least
  two GWs, and no major positional/component calibration or structural failure.
- **MIXED** for exact/essential similarity, conflicting metrics/GWs, offsetting
  components, or insufficient temporal evidence. Exact strict fallback equality is MIXED.
- **WORSE** only for materially concerning, consistent proper-score degradation
  supported by GW/component evidence. No new numerical promotion threshold is invented.
- **INVALID** for unreconstructable required evidence, leakage, comparator mismatch,
  changed frozen inputs, or unexplained fallback output differences.

Lane B is explanatory only. Absolute model deficiencies must still be reported even
if the paired difference is zero. The resource answer is NO: freeze and wait for the
GW4-8 true prospective checkpoint, unless a clear localized implementation failure
justifies owner consideration of a bounded repair. This task implements no repair or
successor. Scouting stays descriptive; no attacking-usage, role, OOP, formation or
new environment feature enters inference.

## Verification and operation

Synthetic tests cover cutoff/GW/DGW/future isolation, evidence classes/timestamps,
identity, paired/fallback equality, deterministic seeds/replay, source/model guards,
observer transparency, immutable publication and outcome-after-forecast ordering.
Run focused tests, relevant production/SDP/player regressions, Ruff, strict mypy and
changed-file formatting. Report inherited Windows symlink/global-format limitations.

After the preregistration commit, execute once from the V2 worktree:

```powershell
D:/Personal/fpl-operations/.venv/Scripts/python.exe -m fpl.jobs.evaluate_player_model_gw1_3
```

The fixed output path, source path, actual evidence frontier, runtime versions and
frozen hashes are in the YAML. Original forecasts, receipts, outcomes and results
remain immutable; only additive final reports are committed afterward.
