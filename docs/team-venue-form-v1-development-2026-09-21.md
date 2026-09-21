# Team venue form V1: completed development experiment

**INCONCLUSIVE.** The preregistered primary Hybrid WMA (C) does not improve goal
log loss or clean-sheet Brier over either control. Its shot-volume and xG errors
improve slightly, but that does not establish better final goal distributions.
No model, selector, player component, dashboard forecast or optimizer is changed.
No weights, priors or gates were adjusted after scoring; no second formal run occurred.

## Delivery and experiment identities

The requested dashboard release was completed first: [PR 17](https://github.com/Keetawon/the_comet_fpl/pull/17),
merge `3fc5b3439a0eda6ea35510febf09945ce15a8e3b`, successful
[Pages run 35563614244](https://github.com/Keetawon/the_comet_fpl/actions/runs/35563614244).
The live [Score Prediction page](https://www.thecometfpl.com/#score-prediction)
was inspected in Chrome: five desktop cards per row, integer score with its smaller
model decimal underneath, ten fixtures, dated provenance and no console errors.
The public release did not enable paid news fetching or publish private draft notes.

Research is separate on `codex/team-venue-form-v1`, based on that merge.
Preregistration/code/test commit: `e890ab5a94903825df88a6b96ae823b680b12a14`.
Formal identity: `team_venue_form_v1_20260921`; completed `2026-09-21T05:47:23.819295Z`.
See [preregistration](team-venue-form-v1-preregistration-2026-09-21.md) and
[fixed config](../config/team_venue_form_v1.yaml).

Production was verified from the actual operational path and frozen parameter
content, rather than a superseded research candidate. It uses SDP V2 shared style
ridge, shot-volume and chance-quality fits, pooled conversion, and the existing
trailing-goals fallback/shadow policy. Parameter SHA256 remains
`043ae6ab2afef1064ce7a3d8544552b7f4fae247216daff6556257fe01f1526b`.
C0 recreates that fitting procedure before each target cutoff; it never applies
terminal 2025/26 parameters to earlier matches. Its 3,800 historical PMFs agree
exactly with the original chance-creation procedure (maximum difference **0.0**).

## Data and evidence boundary

Read-only archive: `.worktrees/sdp_test/data/fpl.duckdb`, 985,673,728 bytes;
SHA256 `0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8`.

Training covers 3,800 team-fixture sides in five seasons, 2021/22 through 2025/26,
with 189 observed GW batches. Scoring covers the identical **2,280 sides / 1,140
fixtures / 114 GWs** in 2023/24 through 2025/26 for all six arms. Those scored
seasons have complete paired original archive goals, archive player-summed xG,
and SDP shot counts. There are no scored fallback rows in any arm. Earlier
seasons provide prior/training information only; absent xG remains absent.

This is **retrospective development**, not historical deadline PIT. The SDP
captures were obtained in September 2026. The inherited historical cutoff is
first actual kickoff in each season/GW; earlier completed archive rows use their
kickoff as the existing completion proxy. Exact historical deadline availability
and final-whistle timestamps cannot be claimed. Actual source knowledge times
remain intact. C0 is an event-causal reconstruction of training/inference arithmetic,
not a replay claiming that the production capture-health selector knew later captures.

All target-GW legs are isolated as a batch, including DGWs. Delayed matches enter
later training only after their actual event. Each arm regenerates its own historical
states and OOS style predictions, then sequentially refits shot volume, quality and
conversion. Old upstream predictions are not substituted into candidate training.
Each arm recorded 309 fitted stage models and zero event, same-GW or in-sample
stacking violations. Fits, parameters and all prediction rows are retained locally.

## Omitted SOT reconciliation

The original omitted-SOT audit reproduced exactly against **1,900 raw payloads**.
It licenses 85 separate interpreted zeros: 80 with shot accounting plus the FPL
keeper proxy, and five supported by explicitly reviewed independent match reports.
Of these, 42 are in the three scored seasons. Season, fixture, permanent team and
opponent codes, venue, SDP match, capture, payload hash and actual known-at were
bound before fitting. Raw SOT remains NULL; interpretation reason and hash remain
beside `shots_on_target_corroborated`. No xG or other statistic was imputed.

Example: 2021/22 fixture 16, team code 45 against 43, payload
`c791bd1a4262560b383d87ae1026a85e70a70c6e88713aa110d978e42b3fdb0e`:
raw NULL, interpreted 0 under `shot_accounting_and_fpl_proxy_zero`, actually known
`2026-09-04T16:58:50.401639Z`. All 85 decisions are in the verification receipt.
The opponent's SOT-against is the reciprocal observation, never independent support
for a zero interpretation. Confirmed zero consumes a valid window slot.

## Six-arm scorecard

Lower is better for all three scores. Each row has 2,280 scored observations.

| Arm | Form construction | Goal log loss | Goal CRPS | CS Brier |
|---|---|---:|---:|---:|
| C0 | Current procedure, raw SOT | 1.490035 | 0.625747 | 0.169951 |
| C1 | C0 plus corroborated zero SOT | 1.489780 | 0.625586 | 0.169931 |
| A | Overall WMA | 1.490430 | 0.626081 | 0.170076 |
| B | Venue WMA + venue league prior | 1.491120 | 0.626283 | 0.170083 |
| C, primary | Venue/overall Hybrid WMA | 1.490109 | 0.625708 | 0.169975 |
| D | Hybrid weighted median | 1.489833 | 0.625496 | 0.169962 |

Positive lift means improvement. These are fixed contrasts, not a search for a winner.

| Contrast | Log-loss lift | CS-Brier lift |
|---|---:|---:|
| C1 vs C0: zero interpretation | +0.0172% | +0.0118% |
| A vs C1: new overall recency | -0.0437% | -0.0851% |
| B vs A: venue/prior replacement | -0.0463% | -0.0039% |
| C vs A: hybrid venue addition | +0.0216% | +0.0595% |
| C vs B: overall rather than league anchor | +0.0678% | +0.0633% |
| D vs C: weighted median | +0.0185% | +0.0074% |
| C vs C0: primary current-method guard | -0.0049% | -0.0138% |
| C vs C1: primary form comparison | -0.0221% | -0.0256% |

C fails both preregistered 1% materiality requirements and both seasonal
non-regression requirements. It also marginally regresses CRPS against C1.
PIT80 coverage is 81.84% for C (C0 81.45%, C1 81.36%), inside its frozen tolerance;
population and causal validations pass. The regression is below the 1% refutation
boundary, hence **INCONCLUSIVE**, rather than SUPPORTED or REFUTED.
D is not promoted or selected post hoc because a small secondary metric looks better.

For C minus C1, mean paired log-loss difference is **+0.000329**, with GW-clustered
normal 95% interval **[-0.001604, +0.002262]**; CS Brier difference is **+0.0000435**,
interval **[-0.000493, +0.000580]**. Negative favors C. C minus C0 log-loss interval
is [-0.001826, +0.001972]. There are 114 temporal clusters, not 2,280 independent
experiments; the inherited cluster method does not adjust serial dependence.

## Slices and intermediate stages

All slices use the same C0 cohort labels. Positive percentages favor C over C1.

| Slice | Sides | C log loss | Log-loss lift | CS-Brier lift |
|---|---:|---:|---:|---:|
| 2023/24 | 760 | 1.534126 | -0.0326% | -0.3276% |
| 2024/25 | 760 | 1.489225 | +0.1620% | +0.2006% |
| 2025/26 | 760 | 1.446975 | -0.2011% | +0.0188% |
| Home | 1,140 | 1.538165 | -0.0266% | +0.1462% |
| Away | 1,140 | 1.442052 | -0.0172% | -0.2228% |
| GW1-6 | 358 | 1.453626 | +0.1706% | +0.5179% |
| GW7+ | 1,922 | 1.496904 | -0.0570% | -0.1293% |
| Promoted clubs | 342 | 1.314117 | -0.3887% | +0.0963% |
| Cold start | 182 | 1.476161 | +0.0383% | +0.2030% |

| Arm | Shot MAE | Shot RMSE | Quality exposure-weighted MAE | xG MAE |
|---|---:|---:|---:|---:|
| C0 | 3.731531 | 4.788535 | 0.036507 | 0.610830 |
| C1 | 3.731408 | 4.788030 | 0.036499 | 0.610973 |
| A | 3.737336 | 4.800820 | 0.036511 | 0.611445 |
| B | 3.728162 | 4.795180 | 0.036429 | 0.612106 |
| C | 3.704156 | 4.764657 | 0.036419 | 0.609297 |
| D | 3.714898 | 4.777192 | 0.036449 | 0.610540 |

Quality diagnostics use 29,842 measured shot exposures. Conversion was refitted
from each arm's own earlier OOS predicted xG, with unchanged regularization. Across
the scored cutoffs it ranges 0.990119-1.040913 for C, versus 0.985514-1.036651 for C1.
C goal bias is +0.04444, goal MAE 0.938812, within-GW Spearman 0.310404;
C1 values are +0.04457, 0.937906 and 0.314538. Better intermediate volume errors
do not translate into a material improvement in final goals or clean sheets.

The same-venue window is substantially older than five consecutive matches.
Its oldest observation has median age **69.94 days**, maximum **104.90 days** among
nonempty scored windows. Venue-window counts 0/1/2/3/4/5 occur on
120/121/119/120/120/1,680 scored sides. Those windows stay within season, never reach
past the selected five slots to replace a missing value, and retain per-feature
counts. The effective blend reaches only 62.5% venue even at five valid observations.

## Verification and retained artifacts

The independent read-only verifier checked **439,863 assertions, zero failures**:
114,000 state arithmetic checks, exact windows/counts/ages, reciprocal clubs/states,
unchanged targets and timestamps, causal fit bounds, six artifact hashes, eight
byte-identical score replays, and all **598** preregistered file fingerprints.
The source database hash is unchanged. Replay performs **zero model refits**.
Original results, production files, forecasts and all other contributors' work remain intact.

- [Formal result](../results/team_venue_form_v1_20260921.json), SHA256
  `87a959e3fe98d4852225cf2c7bab974031d0ec4d93a57f2e2846685ce0dc664a`.
- [Independent verification](../results/team_venue_form_v1_verification_20260921.json),
  SHA256 `2c2eeef55670976d73467ec9a030ac558e80896c09071b7c3d214b1bc39c2886`.
- Local immutable inputs, claim, six compressed prediction/fit artifacts and completion
  receipt: `data/artifacts/team_venue_form_v1_20260921/` in the research worktree.
  Their hashes are in the formal result. These are research artifacts, not R2 public exports.
- [Read-only verifier](../scripts/verify_team_venue_form_v1.py): with `PYTHONPATH=src`,
  run `python scripts/verify_team_venue_form_v1.py --verify-existing` from this worktree.
  It needs those retained local artifacts and does not regenerate predictions.
  Do not rerun the formal runner: its identity is reserved and write-once.

New focused tests: **20 passed**. Relevant tactical/chance/SOT/PIT/selector regression
group: **212 passed, 18 skipped** before the final additional serialized replay test;
that test is included in the 20-test final focused pass. Ruff source/tests/verifier,
changed Python formatting, and strict mypy on **241 files** pass.

The full suite is **not green**: 4,322 passed, 156 skipped, 64 failed, 22 errors.
Of these, 51 failures and all 22 errors reproduce with **exactly identical node IDs**
on the untouched pre-experiment Python checkout (stale provenance pins/legacy
contract expectations). The remaining 13 are documented Windows BI-export symlink
privilege errors (`WinError 1314`). No new venue-form test fails. Global formatting
also retains ten pre-existing failures; no unrelated cleanup was performed.

The result establishes no production improvement. The existing production model,
configuration, historical scientific conclusions and retained forecasts remain unchanged.
