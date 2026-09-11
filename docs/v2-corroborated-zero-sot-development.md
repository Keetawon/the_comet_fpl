# Corroborated omitted-zero SOT: development result

Verdict: **INCONCLUSIVE**. Development-only; nothing is promoted or retuned.

The single formal outer run used clean preregistration commit
`59b53e057853567bf2e5de58d43773cca229d4c8`, pushed to the V2 branch before scoring. It ran once
from 2026-09-05 20:31:03.446690 UTC to 20:33:50.821958 UTC (2026-09-06 in Bangkok), taking
167.375 seconds through scoring. No second outer run or post-result parameter search occurred.

Artifact: `results/v2_corroborated_zero_sot_development.json`, schema version 1, 4,219,064 bytes,
SHA-256 `e8d1a5c0fcce42946d3bf8e798f52e208ac79168c2453e4c0840c1be65c009c5`.
The separate [design](v2-corroborated-zero-sot-design.md) was frozen before this run.

## What changed, and what did not

Candidate `retrospective_corroborated_zero_sot_team_environment_v2` adds only historical SOT to
the identical goals+xG architecture, now using a separately corroborated interpretation of
omitted zeros. It changes no targets, xG provider/definition, scored population, estimator, grid,
inner-selection policy, goal distribution, promoted-team rule or prospective default.

The coverage-only audit checked 1,900 exact retained match payloads. In the scored seasons,
2,238 SOT values were explicitly measured and 42 were omitted. The 42 omissions were corroborated
as zero: 37 through concordant shot accounting and FPL proxy evidence, five through explicit
match reports. All are labelled interpretations, not newly discovered explicit provider fields.
Raw NULLs, staging and marts were not filled. Explicit NULL or unresolved evidence remains NULL
under the policy. No team-average imputation was implemented.

| Season | Goal-observed sides | Existing xG | Raw explicit SOT | Corroborated zeros | Joint availability after interpretation | Scored |
|---|---:|---:|---:|---:|---:|---|
| 2021-22 | 760 | 0 | 739 | 21 | 0% | No |
| 2022-23 | 760 | 488 | 738 | 22 | 64.2105% | No |
| 2023-24 | 760 | 760 | 754 | 6 | 100% | Yes |
| 2024-25 | 760 | 760 | 740 | 20 | 100% | Yes |
| 2025-26 | 760 | 760 | 744 | 16 | 100% | Yes |

The inherited 95% joint-coverage rule therefore selects the same three seasons. Earlier seasons
can train only after their events occur. The run scored 2,280 team-sides / 1,140 matches /
114 observed-GW folds, with zero target exclusions. Prior-history availability still differs
from full-season source availability: the scored history-length slices contain 8 / 16 / 26 /
2,230 rows for 0 / 1-2 / 3-5 / 6+ prior SOT observations.

## Primary answer

Historical SOT provides a **small positive observed lift, not sufficient evidence of meaningful
improvement**. Mean log score is 1.488525 against the same-population goals+xG control's 1.489436:
**+0.061188% relative improvement**, far below the preregistered 1% threshold. This is a log-loss
improvement, not a claim of 0.061188 percentage points of match-prediction accuracy.

The paired mean loss difference is -0.00091135. The inherited GW-level diagnostic standard error
is 0.00067968 (row-level 0.00077332). The improvement is only about 1.34 times the GW diagnostic
SE; it is not independent confirmation. Unequal GW sizes and serial dependence further limit
simple uncertainty summaries. These are already-inspected development seasons.

| Model | Mean log score | CRPS / RPS | PIT-80 coverage | Mean error | MAE |
|---|---:|---:|---:|---:|---:|
| Trailing-goals context baseline | 1.496896 | 0.631038 | 80.3070% | -0.043650 | 0.928922 |
| Same goals+xG control | 1.489436 | 0.626658 | 80.8333% | -0.004226 | 0.931538 |
| Corroborated-zero SOT candidate | 1.488525 | 0.625844 | 80.7018% | -0.005318 | 0.930619 |

CRPS improves **0.129783%**. PIT-80 absolute error improves from 0.8333 to 0.7018 percentage
points, a small three-row change; it is not proof of a broad calibration improvement. MAE improves
by 0.0009185 goals, but mean-level bias becomes slightly more negative. The old baseline remains
better on MAE and overall PIT-80 absolute error. The scientific comparison is against goals+xG,
not just against that older baseline.

The goals+xG and trailing-goals overall reports reproduce their first-run records exactly. Their
fixed-population slice reports and all 114 control parameter/scale selections also reproduce
exactly. SOT-history slices are not used for that equivalence claim because interpreted history
can change their membership. The first SOT candidate and the older V2 result remain byte-frozen;
this result does not revise their verdicts.

## Season consistency and diagnostic slices

| Season | Rows | Control log | Candidate log | Log lift | CRPS lift | Control / candidate PIT-80 |
|---|---:|---:|---:|---:|---:|---:|
| 2023-24 | 760 | 1.541525 | 1.539330 | +0.142399% | +0.265805% | 80.5263% / 80.3947% |
| 2024-25 | 760 | 1.481843 | 1.481908 | -0.004405% | +0.010245% | 82.7632% / 82.6316% |
| 2025-26 | 760 | 1.444940 | 1.444336 | +0.041816% | +0.102851% | 81.3158% / 81.3158% |

Two seasons improve, but 2024-25 regresses slightly. Thus both the primary-lift and no-season-
regression gates fail. CRPS, PIT-80, identical population and event/GW-isolation checks pass:
four of six checks passed, not a development-gate pass.

Diagnostic log lifts against the same control:

| Slice | Rows | Log lift |
|---|---:|---:|
| Home | 1,140 | +0.123653% |
| Away | 1,140 | -0.005170% |
| Promoted | 342 | +0.162422% |
| Established | 1,938 | +0.046126% |
| GW1-6 | 358 | -0.010364% |
| Later GWs | 1,922 | +0.074017% |
| Cold start | 24 | +0.326244% |

The cold-start population is far too small to support a policy change. Slice PIT draws restart
at the fixed seed in the inherited scorer, so slice coverage counts are not additive. Some
calibration slices worsen (for example promoted clubs and the tiny 3-5-history slice), even
though overall PIT-80 improves. No slice was used to retune the candidate.

## What SOT actually changed

The selector chose zero SOT weight in **65/114 folds**. Nonzero selections were 0.25 in 15 folds,
0.50 in 11, 0.75 in seven and 1.00 in 16. All SOT scale fits used prior observations only; their
source coverage is 100% after labelled interpretations, not 100% explicit raw measurement.

- **Level:** mean predicted goals decreased by 0.001092, slightly worsening aggregate mean bias.
- **Discrimination:** within-GW Spearman increased from 0.326618 to 0.330194, a small change.
- **Shrinkage:** predicted-rate SD fell from 0.430612 to 0.421244, a 2.1755% reduction in rate
  spread. Candidate/control rate correlation is 0.993331; mean absolute rate change is 0.023515.
- **Dispersion:** no independent dispersion model was added. Both outputs remain the same
  Poisson goal marginals, so their distribution shape changes only through the predicted rate.

The result is mostly small rate redistribution and shrinkage, with a modest rank improvement.
It is not evidence that a richer football feature set will deliver a material gain. Recovering
these omitted zeros did not reveal a hidden 1% improvement.

## Evidence boundary, provenance and independent reconciliation

The separate validation-only `CorroboratedSotBackfillView` retains raw SOT and creates only
`shots_on_target_corroborated`. It uses the original earliest-successful-complete whole-payload
policy, ordered by capture time then payload ID. Every interpretation matches the exact raw
capture ID, SHA, known-at, match, kickoff and permanent teams. Later revisions are not selected.

Historical match kickoff must precede each prediction cutoff, the trusted historical match must
be complete, and the whole target GW is excluded. Original September 2026 `known_at` values and
the separate interpretation-review time are retained. Strict `PointInTimeView`, prospective
forecasts, optimizer, dashboards and promotion paths remain unchanged and reject later-known
historical data. No database rows or capture timestamps were rewritten.

Formal provenance:

- Clean Git HEAD: `59b53e057853567bf2e5de58d43773cca229d4c8`.
- Config SHA: `ef0bc8a6068931a13b0331451abaa728eba7936c314228bca76bd4622aeaf8d0`.
- Database SHA: `0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8`.
- Audit SHA: `3d662e09e541e924c218fe4edf1cf7f11289d2d13f4577fb0dc2bf56a596cb4a`.
- Interpretation policy SHA: `52bd6f1ad975f7a683bff6bcca685f32d838c4d1dfd747a33df934860b013347`.
- Canonical capture manifest SHA:
  `084137d2e03babbf9d8361e49be0f23ba19ae3baed34c5d9d0605264ea37057f`.
- Evidence class: `retrospective_backfill_development`; seed: `20260904`.

The artifact retains every fixture PMF for all three models, all targets, fold cutoffs, slice
metadata, fitted parameters/scales, interpretation counts and per-fold input-identity hashes.
An identity excerpt of the first prediction is:

```json
{"key":"2023-24:1:43","season":"2023-24","gw":1,"was_home":false,
 "as_of":"2023-08-11T19:00:00+00:00","observed_goals":3,
 "cold_start":false,"promoted":false,"early_season":true,"sot_history_band":"6+"}
```

The full record additionally contains `distributions`, mapping the three exact model names to
11-bin PMFs. Independent post-run arithmetic checked all 6,840 distributions for finite,
nonnegative unit mass, reconciled all 2,280 targets/venues/GWs to the unchanged archive, and
reproduced log loss, CRPS and PIT bins/coverage for all 48 overall/slice model blocks. This reads
stored predictions; it does not fit models or rerun outer evaluation. A separate read-only input
audit reproduced all 114 historical input hashes and interpretation counts, and all 342 retained
per-fold model-score blocks reconciled too: 390 overall/slice/fold model blocks in total. Source
and DB fingerprints still match the formal provenance. No model was fitted in either check.

## Verification and next experiment

The complete pre-run [verification record](v2-corroborated-zero-sot-verification.md) documents:
241 relevant regression tests passed (including 56 new tests); full pytest 2,185 passed,
14 Windows symlink-privilege failures, four corresponding skips; Ruff lint and mypy passed;
11 untouched pre-existing format offenders remain. Dashboard tests passed 312/312, build and
lint passed with existing warnings. The full repository gate is not unqualified green.

**Should we preregister territory / box touches next? NO.** The isolated SOT increment remains
far below the meaningful-lift bar and still regresses in a season and the early-season slice.

The single highest-value next development experiment is the already identified procedural
hypothesis: preregister an unchanged goals+xG candidate whose **inner holdout advances/refits
weekly, matching outer deployment**, instead of fitting once before the six-GW holdout. Keep
its features, grids and targets fixed and compare against the exact existing control. This
may address selection instability, but the present result does not prove that cause or promise
an improvement. It needs separate authorization and preregistration; it is not implemented here.
Strict-prospective evidence remains necessary for any eventual promotion.
