# Tactical Matchup numerical amendment: completed development result

**INCONCLUSIVE. Keep the current incumbent.** The single preregistered amended run completed
on 2026-09-07: goal negative log score improves **0.274885%**, clean-sheet Brier improves
**0.483597%**. Both miss their unchanged 1% materiality requirements. All other aggregate
gate checks pass, but paired GW-clustered intervals include zero. This is retrospective
development evidence, not promotion or proof of historical real-deadline availability.

The previous V1 attempt remains an immutable numerical failure, not a scored result. This
separately authorized amendment changed numerical solution/diagnostics only; no feature,
population, model family, statistical grid or gate changed after seeing performance.

## Git, execution and provenance

- Starting local and verified remote V2: `464c86fd24fca210cb3c75af367ebd5ab721173d`.
- No main-only commits on the verified fetch; no main merge in this continuation. Earlier
  normal snapshot merge and the local weekly-SOT history remain intact.
- Clean preregistration/evaluation commit: `e76a54b988d7fb1c71cc86a86e95979aaf89afe2`.
- Candidate: `retrospective_tactical_matchup_team_environment_v1_numeric1`.
- Config SHA256: `9493b01638a0d1cbe65e154aefcda1b96ebacf0461be787878efc8bb915480b4`.
- Result: `results/v2_tactical_numeric_development.json`, SHA256
  `d52973687d2983c9fc3159365e8dde865ac60a7b1ddb0d0db6e5dc3268efd11c`.
- UTC start/end: `2026-09-07T05:10:05.993105+00:00` /
  `2026-09-07T05:15:42.243866+00:00`; one invocation, exit 0, no retry/resume.
- Read-only database: `D:\Personal\workspace\the_comet_fpl\.worktrees\sdp_test\data\fpl.duckdb`;
  SHA256 `0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8`.
- SDP earliest-complete-whole-payload manifest SHA256:
  `f12a915d14e2f8d3c8ca718b242b91c41c3d3c6d3546383d319c7692f878835d`.
- Execution claim SHA256: `534c7b77a4ace1f123d76326918f311ae869a15d47d08175c17955a44ff4263e`.

The result records all source fingerprints, parent failure/source identities, runtime,
original known_at values, seed 20260904, full PMFs, all historical OOS style predictions and
fold diagnostics. All 189 complete historical batches are also retained in ignored
`data/evaluation-checkpoints/retrospective_tactical_matchup_team_environment_v1_numeric1/`.
These checkpoints are evidence, never a resume cache. Publication followed a successful
unchanged-source/config/DB/clean-Git postflight check. Result/docs commits are later than the
evaluation commit, as required; their changes are not misrepresented as pre-evaluation files.

## Frozen state and population

The [numerical amendment](v2-tactical-numerical-amendment.md) inherits all three original
state/style/matchup designs and their hash-pinned contract without statistical overrides.

| Dimension | Exact source / formula | Semantic status |
| --- | --- | --- |
| Attack precision | `ontargetScoringAtt / totalScoringAtt` | SOT independently corroborated; shot denominator provider-labelled |
| Dangerous territory | `log1p(touchesInOppBox)` | Provider-labelled development use |
| Control | `possessionPercentage / 100` | Provider-labelled development use |
| Directness | `fwdPass / totalPass` | Provider-labelled development use |
| Defensive suppression | `-log1p(opponent totalScoringAtt)` | Provider-labelled development use |

Raw missing is not zero, and a zero ratio denominator stays unavailable. Recent state uses
actual last-five current-season PL slots, newest-first weights `1,.707,.5,.354,.25`, normalized
only over measured values, then `n/(n+2)` pooling to strictly prior league evidence. Missing
matches consume slots; season boundary resets recent club state. One league-pooled penalized
venue indicator replaces separate stale home/away windows. No permanent team-style classes.

Paired both-side/all-five-dimension >=95% coverage selected 2023-24 (748/760 sides, 98.4211%)
and 2025-26 (728/760, 95.7895%) BEFORE scoring. Outer 2024-25 remains excluded at 94.7368%; it
can supply strictly prior training history. All goals targets remain: **760 fixtures,
1,520 sides, 76 folds**. Actual precision is measured on 1,498 outer rows; the other four
dimension targets on 1,520. No outer target was dropped for an absent tactical label.
Coverage-based, nonconsecutive selection and outcome-dependent provider omissions limit
generalization; do not interpret these two seasons as the whole historical population.

Style ridge-delta penalty stays 1; goal offset penalties stay disabled/10/1/.1, selected from
the same six prior prequential GWs after ten earlier GWs. Minimum fitting history is 160
rows. All scaling is prior-fold local. Style predictions used in goal fitting were genuinely
out-of-sample in event time, never fitted on their own tactical targets. Same-GW and delayed
DGW boundaries remain intact. Late capture timestamps are retained, not rewritten.

## Incumbent and main result

The exact prospective incumbent is `trailing_goals_attack_defence`, not weekly goals+xG.
Despite its name it uses expanding archive goals with six-match league pooling and venue
means, not a rolling recency decay. Its Poisson 0..10 support, floor .05 and reciprocal
clean-sheet definition remain unchanged. The challenger is a regularized log-rate correction
around that incumbent, not an independent clean-sheet classifier.

Before candidate fitting, all **1,520 identities / 76 folds** reproduce against BOTH retained
reference PMFs and the actual prospective helper, maximum PMF difference **0.0**, tolerance
1e-12. After fitting, the exact same keys, targets and incumbent PMFs are checked again.

| Metric | Incumbent | Tactical amendment | Change |
| --- | ---: | ---: | ---: |
| Goal NLL (lower better) | 1.497607513 | 1.493490819 | +0.274885% lift |
| CS Brier (lower better) | 0.170025703 | 0.169203463 | +0.483597% lift |
| CRPS / RPS | 0.630928747 | 0.627279931 | +0.578325% lift |
| MAE | 0.928351048 | 0.928044961 | Essentially unchanged |
| Mean prediction error | -0.068784368 | -0.028630700 | Less underprediction |
| PIT-80 coverage | 0.810526316 | 0.817763158 | Further from nominal 0.8 |
| Mean predicted goals | 1.438452474 | 1.478606142 | +0.040153668 |
| Predicted-rate SD | 0.496815295 | 0.546201230 | +9.94% |
| Within-GW outcome Spearman | 0.309924782 | 0.310011912 | Essentially unchanged |

CS calibration-in-the-large improves: mean forecast 0.263570 -> 0.257726 versus observed
0.230921, though it still overpredicts clean sheets. PIT-80 absolute error worsens from
0.010526 to 0.017763, within the frozen .05 guard. Hence calibration is mixed, not uniformly
better; the 0.5-0.6 CS bucket also remains sparse and overconfident.

Paired candidate-minus-incumbent NLL difference = **-0.004116694**, GW-clustered SE
**0.002319442**, normal 95% interval **[-0.008662801, +0.000429413]**. CS difference =
**-0.000822240**, SE **0.000478470**, interval **[-0.001760041, +0.000115562]**.
Both intervals cross zero. These are descriptive 76-GW clustered intervals, without
serial-dependence or repeated-research/season-reuse adjustment, not a definitive significance
claim. Six of eight gate checks pass; both primary materiality checks fail.

## Robustness (relative improvements; negative means worse)

| Slice | Team sides | Goal NLL lift | CS Brier lift |
| --- | ---: | ---: | ---: |
| 2023-24 | 760 | +0.4511% | +0.8247% |
| 2025-26 | 760 | +0.0863% | +0.1793% |
| GW1-6 | 238 | +0.0627% | -0.2250% |
| GW7+ | 1,282 | +0.3131% | +0.6234% |
| Home | 760 | +0.3723% | +0.3196% |
| Away | 760 | +0.1706% | +0.6874% |
| Promoted | 228 | -0.0663% | +1.6285% |
| Established | 1,292 | +0.3272% | +0.3606% |
| Cold start | 40 | 0.0000% | 0.0000% |
| High state confidence | 1,398 | +0.2829% | +0.5369% |
| Low state confidence | 122 | +0.1834% | -0.0462% |
| High prior style-error risk | 222 | +0.1404% | -0.4026% |
| Low prior style-error risk | 1,295 | +0.2985% | +0.6112% |

Direction is positive across both full eligible seasons, but substantially weaker in
2025-26. Early-season CS regresses; the architecture did not solve that weakness. The 238
early rows are the exact schedule population, not an assumed 240. CS venue/promoted slices
refer to the defending team; they use its opponent's PMF. Style-error-risk uses only prior
OOS errors, not the current target's realized error. Unknown risk has three rows, no lift.

## Is next-match style actually forecastable?

| Dimension | Persistence RMSE | Forecaster RMSE | MSE improvement | Forecast rank correlation |
| --- | ---: | ---: | ---: | ---: |
| Attack precision | 0.160825 | 0.154236 | +8.03% | -0.0021 |
| Dangerous territory | 0.431869 | 0.396714 | +15.62% | 0.4665 |
| Control | 0.111745 | 0.094782 | +28.06% | 0.6515 |
| Directness | 0.053773 | 0.052283 | +5.46% | 0.5734 |
| Defensive suppression | 0.409840 | 0.380298 | +13.90% | 0.4063 |

Yes: all five MSEs improve over the recent-state persistence baseline. Control, territory
and suppression have meaningful held-out discrimination; directness mostly persists.
Precision's improved MSE with essentially zero correlation is consistent with reducing
noisy predictions toward an average, NOT evidence that next-match shot precision is ranked
usefully. Do not equate lower style MSE or realized statistical correlation with goal lift.

The largest standardized opponent-associated contribution is control (mean absolute .2608
prior-SD units); venue effects are largest for suppression (.1259) and territory (.1191).
These are contributions of correlated fitted regressors, not causal effect estimates.
The result retains actual/predicted/persistence/current/opponent state, all scaling and
coefficients, context and cutoff per row, plus by-season/venue/early-season style scores.

## Does the added matchup structure matter?

The preregistered diagnostic arms reuse the primary selected penalty; they are not separately
optimized candidates and cannot be retrospectively substituted for the nominated challenger.

| Retained arm | Goal NLL | CS Brier |
| --- | ---: | ---: |
| Recent state only, no interactions | 1.494177997 | 0.169226028 |
| Predicted state, no interactions | 1.493489061 | 0.169244260 |
| Predicted state + three interactions (primary) | 1.493490819 | 0.169203463 |

Predicted style provides only a small additional NLL gain over recent state alone. Adding
the three interactions is microscopically WORSE on NLL than predicted main effects, with a
tiny CS benefit. There is no demonstrated material value from the interaction terms.

The selector disables the adjustment in 28/76 outer folds (5 in 2023-24, 23 in 2025-26),
chooses penalty .1 in 34 and 1 in 14, never 10. Corrections are nonzero on 958/1,520 rows;
none hits the +/- .5 clip. Mean absolute goal-rate change is .06222, signed change +.04015.
This is NOT just narrowing/shrinking the forecast rates: rate spread increases 9.94%, and
521/14,624 non-tied within-GW pairs reverse ordering (3.56%). However outcome-ranking
Spearman barely moves. Conditional dispersion has not independently changed: the same
Poisson family ties its variance to its rate. Most measurable benefit is level/calibration
adjustment, not a proven improvement in matchup discrimination.

**Operational conclusion:** style forecasts contain real development signal, but this
specific route from state through interaction correction to goals/CS does not justify its
extra complexity under the owner's materiality bar. Keep the incumbent and continue retaining
SDP observations/revisions; this is not evidence that the source itself is useless.

## Numerical and independent validation

All 636 actual Poisson fits converge: 540 primary and 96 diagnostic; 27 early fitting slots
use the unchanged insufficient-history fallback. There are 1,875 accepted Newton steps,
all full steps, no backtracking; maximum four updates. Maximum final gradient is
9.5273e-10 and maximum final undamped step 3.9042e-10; no fit exceeds the absolute 1e-9
gradient threshold even without its roundoff allowance. Seventy-seven valid tiny decreases
would be lost/nonnegative under whole-objective subtraction. At the old stopping GW all
three penalties now converge, supporting the rounding concern without proving which old
unretained matrix/penalty caused its failure. No old candidate was replayed.

Independent read-only verification performs **58,268 checks, zero failures**: exact reference
identities/PMFs, four-arm overall and slice NLL/CRPS/CS/PIT/MAE, all 1,608 training-membership
blocks, 1,535 fold-local scalers, 636 convergence certificates, inner selections, 3,800
historical rows and every one of the 189 checkpoint/source/config/DB/claim hashes. The
runner's own temporal trace has 11,383 boundary checks and zero violations.

Logs and independent reports are in
`D:\Personal\fpl-operations\verification\tactical-numeric-20260907`:
`formal-once.log`, `independent-verification.json`, `independent-solver-audit.json`, and
`retained-performance-analysis.json`. Their read-only scripts perform no model refitting.

[Verification record](v2-tactical-numeric-verification.md): 74 new tests and 259 unique
new/affected checks pass; existing full partition is 2,496 passed / 15 failed / 4 skipped.
The combined new/affected partition also passes after publication: 259 tests in 58.90 s.
Fourteen failures are unchanged Windows symlink privilege errors; the localhost socket
failure passes its five-case isolated recheck. Ruff and strict mypy (149 files) pass; eleven
unchanged files fail full formatting. Dashboard 312 tests/build/lint pass with existing
warnings. Do not call the whole repository gate green.

Original root/research databases, raw captures, all previous frozen results, strict
prospective/PIT paths, production defaults and optimizer/dashboard inputs are unchanged.
No new ingestion, schedules, player roles, DC model, promotion, main merge-back or PR.

## Separate workload probe and exactly one next direction

The already-retained [competitive workload audit](competitive-workload-source-audit.md)
remains separate: all five requested cup/Europe competitions returned real HTTP 200 during
that earlier data-only probe, with XI/bench/substitution evidence but no direct minutes field.
It was neither rerun nor fed into this amended model. A later data step would validate
participation-interval reconstruction and the FPL player crosswalk before any workload use.

**One recommended next model direction, not implemented:** preregister a bounded
**shot-creation -> goals two-stage team model with strongly pooled conversion**, still judged
against the exact incumbent. Territory/control/opponent-shot suppression are forecastable,
whereas precision has virtually no held-out ranking signal and the direct interaction
correction adds negligible value. That supports testing an explicit chance-volume mechanism
with restrained finishing variation, rather than adding further tactical dimensions to this
offset. It does NOT prove that the proposed successor will win. Give it a new design, fixed
population and materiality contract before any evaluation; do not retune this retained result.
