# Team venue form V1: preregistration

Owner authorized this separate development experiment after the dashboard release.
Release PR17 merged at `3fc5b3439a0eda6ea35510febf09945ce15a8e3b`; Pages run
35563614244 succeeded and the live Score Prediction page was inspected in Chrome.
The experiment starts from that commit on `codex/team-venue-form-v1`.
No production configuration, forecast, selector, or historical result is replaced.
There is one fixed six-arm execution; failed identities are retained, never overwritten.

## Production and source audit before training

The operational checkout's `models/sdp_environment.py` loads
`config/sdp_v2_frozen_parameters.json` (SHA256
`043ae6ab2afef1064ce7a3d8544552b7f4fae247216daff6556257fe01f1526b`).
It uses five Tactical State dimensions, shared ridge delta style forecasts, Poisson
shot volume, fractional-Poisson mean xG/shot, and global goals/xG conversion.
`football_environment.yaml` selects SDP V2 with exact trailing-goals attack/defence
fallback and incumbent shadow; GK challenger remains shadow only. The operational
and research source/parameter bytes agree. Football-policy YAML differs only in
CRLF/LF, with identical parsed content. The operational scheduled refresh remains
`fpl.jobs.refresh_dashboard` and never runs this experiment.

C0 reproduces the **procedure** with historical fold-local fits, never the terminal
2025/26 parameters applied backwards. No superseded tactical goal-offset model or
inner hyperparameter search is included: they are not the production chance chain.
The original frozen result is only a post-run C0 numerical reconciliation reference;
its upstream predictions are not candidate inputs.

C0 is an event-causal reconstruction of the production **training/inference arithmetic**,
not a strict replay of its operational capture-health selector. A strict historical
selector would reject the later SDP captures. All six arms share the explicit
retrospective evidence license; no operational fallback policy is weakened.

Read-only retained database: `.worktrees/sdp_test/data/fpl.duckdb`, SHA256
`0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8`.
Recomputed the original omitted-SOT audit before training: every report field agrees,
1,900 raw payloads verified, 85 omissions (80 shot-accounting plus FPL keeper proxy,
5 explicitly reviewed independent reports). Join binds season, fixture, permanent
team/opponent codes, venue, SDP match, capture, actual knowledge time and payload hash.
Raw SOT stays NULL; interpreted SOT and its reason are separate. Opponent SOT-against
is only the reciprocal observation, not independent corroboration. Neither xG nor
another field is filled. Explicit null, contradiction, or unconfirmed omission fails
closed. Measured zero remains eligible in the fixed window.

Historical capture times are September 4, 2026. This is **retrospective development**,
not historical deadline PIT. First observed kickoff per season/GW is the inherited
cutoff proxy; completed archive rows with earlier kickoff are the inherited completion
proxy. Actual historical final-whistle/availability timestamps cannot be claimed.
Whole target-GW batch (including delayed/DGW legs) is excluded; delayed legs can enter
later fits only after their actual event. No knowledge timestamp is rewritten.

## Population and fit procedure

3,800 team-fixture sides / five seasons (2021/22–2025/26), 189 observed GW batches.
Train sequentially on earlier evidence; score all 2,280 sides / 1,140 fixtures /
114 GWs in 2023/24–2025/26. These three seasons each have 100% paired coverage of
original archive goals, original archive player-summed xG, and SDP total shots.
Earlier seasons supply training/prior evidence only. Missing predictors invoke exact
incumbent fallback; they do not remove targets. Compare all arms on identical rows.

Five dimensions unchanged: SOT/total attempts, log1p(box touches), possession/100,
forward/total passes, and -log1p(opponent shots). Fit shared home-and-away style ridge
models (penalty 1, minimum 160 rows), using own/opponent state plus home flag. Learn
dimension deltas from earlier **OOS** states. For each arm regenerate all states and
style forecasts, then call the unchanged chance walk-forward implementation on that
arm's own OOS outputs. Keep fold-local scaling, volume and quality ridge 1, minimum
160 rows, quality bounds [1e-6,1], global conversion prior exposure 20/minimum160,
rate floor .05, 0..10 tail-folded Poisson, and exact incumbent fallback unchanged.
Incumbent goal priors also fit each historical cutoff. No cached upstream substitution.

## Fixed six arms

All windows select rows before looking at feature missingness. Sort actual kickoff,
then fixture for deterministic ties; current season and stable club code only. An
unmeasured slot consumes its weight. Normalize on measured values **within** the
selected five matches, never reach farther back. Expanding league priors retain
earlier seasons and only cutoff-eligible rows. No previous-season team form carryover.

- C0: unchanged raw-SOT state, weights [1,.707,.5,.354,.25], n/(n+2) league pooling.
- C1: C0 with exact corroborated-zero interpretation; all other dimensions/targets unchanged.
- A: C1 with weights [.40,.30,.20,.07,.03]; retains n/(n+2) overall prior pooling.
- B: last five same-venue matches with the new weights; `w=n/(n+3)` per feature;
  `w*raw_venue_WMA+(1-w)*measured_expanding_same_venue_league_prior`.
- C (primary): `w*raw_venue_WMA+(1-w)*A`. No venue evidence -> A; no overall
  evidence -> expanding league prior. No additional venue n/(n+2) pooling.
- D: C except raw venue summary is the weighted median. Sort measured values ascending,
  choose first value passing half the retained weight; at exactly half (absolute
  tolerance 1e-12) average that value and the next measured value. Targets remain
  original goals/shot counts/xG, never medians.

For B, if no same-venue league evidence exists, use the overall expanding league prior;
if neither exists return NULL and inherited fallback. C/D use overall A's prior in that
case. Counts are per feature, max5. Own home is paired with opponent away and vice versa,
even when a team has both venues in a DGW: states are keyed by (club, target venue).
Retain both raw windows, counts, fixture keys, oldest kickoff, age in exact days, total
window matches and opponent context for every prediction. Venue age describes span,
not another weight or feature.

## Evaluation frozen before results

Primary comparison: C against C1 (separates form from zero interpretation), and C
against C0 as the required current-method guard. Report all six without selecting
the best post hoc. Contrasts C1-C0, A-C1, B-A, C-A, C-B, D-C isolate the stated changes.
Use existing mean goal NLL/log floor, goal CRPS, reciprocal clean-sheet Brier,
randomized PIT80 seed20260907, goal bias/MAE and within-GW Spearman definitions.
Report season, home/away, early GW1–6/later, promoted and cold/coverage slices; stage
shot/xG errors, quality exposure-weighted errors, and conversion diagnostics.
Keep paired GW-clustered uncertainty (114 clusters; not serial-dependence adjusted),
per-GW scores, and explicit fallback counts. No false independent-row inference.

SUPPORTED for **development only** requires against BOTH C0 and C1: >=1% NLL and
>=1% CS Brier improvement, non-regressing CRPS, no seasonal NLL/CS regression,
PIT80 absolute error <=.05, identical population and zero causal validation failures.
REFUTED if C regresses either primary score >=1% against either control; otherwise
INCONCLUSIVE. Any provenance/leakage/numerical failure INVALIDATES this run identity.
These new gates do not reinterpret any prior verdict and never authorize promotion.

Synthetic checks precede one formal run. Save claim/config/source/database fingerprints
before fitting; save each arm's predictions and fitted provenance write-once before
the combined scorecard. Recheck all tracked existing files and database afterward.
No retuning, new features, additional weight sets, or production integration.
