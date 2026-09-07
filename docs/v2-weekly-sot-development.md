# Weekly-inner real-SOT development result

Date: 2026-09-07. Verdict: **INCONCLUSIVE**, retrospective development only, not promoted.
One formal candidate run is complete. Do not rerun, retune, or overwrite its result.

## Decision

Adding real historical SOT to the weekly-inner goals+xG model improves mean negative log
score by only **0.066134%**, from **1.486650879246 to 1.485667700136**. This misses the
preregistered 1% bar by a wide margin and slightly regresses in 2024-25. Retain the existing
model/defaults as the owner requested. This is not a percentage-point improvement in the
fraction of correctly predicted match results.

The wider-spread concern is partly supported descriptively: SOT reduces across-fixture
predicted-rate SD by **2.6314%**. But narrower predictions are not inherently less accurate:
log score, CRPS and MAE improve slightly. The separate zero-goal/reciprocal clean-sheet
Brier diagnostic gets slightly worse. The evidence does not support switching models.
It does not establish that the SDP data itself is inferior or should be discarded.

## Exact experiment

- Candidate: `retrospective_goals_xg_sot_weekly_inner_selection_v1`.
- Exact control: `retrospective_goals_xg_weekly_inner_selection_v1`, not the older
  frozen-holdout goals+xG model.
- Only added signal: real SDP `ontargetScoringAtt`, under the unchanged version-specific
  corroborated omitted-zero policy. Archive goals and xG stay unchanged. No other SDP
  metric, team-average imputation, tactical feature or new distribution family enters.
- Both use the frozen weekly inner refits, goals-first decay/prior search, existing grids,
  priors, Poisson output, rate floor and seed **20260904**.
- Same population: **2,280 team-sides / 1,140 fixtures / 114 observed-GW folds**, 2023-24
  through 2025-26. Joint coverage is 100% in each scored season after the inherited
  interpretation; raw SOT remains separately nullable. No eligibility was reselected.
- The source audit revalidated **1,900 canonical historical payloads** before fitting.
  Earliest-complete version selection, original capture times and stable identities remain.
  Each outer fold retains a distinct SOT-history hash; eligible prior SOT sides grow from
  1,520 to 3,780. Cold-history rows are kept, not dropped.
- Control reproduction was exact: **maximum PMF difference 0.0**, identical scores,
  parameters, scales, inner diagnostics and archive hashes on all 114 folds, inside 1e-12.
  Reference/model cold-start labels happened to have zero disagreements in this real run;
  the differing-label case is protected synthetically.
- **2,736 inner-stage batches checked**, zero event-time or target-GW overlap violations.
  Goals-only half-life/prior selection is identical in all 114 control/candidate folds.

## Overall scores

Lower is better for log score, CRPS, MAE and Brier. PIT-80 should be close to 80%.

| Metric | Weekly goals+xG | Same model + SOT |
| --- | ---: | ---: |
| Mean negative log score | 1.486650879 | 1.485667700 |
| CRPS / RPS | 0.624360149 | 0.623482866 |
| MAE | 0.928009198 | 0.927209519 |
| Mean error, prediction minus outcome | -0.004370013 | -0.007271746 |
| PIT-80 coverage | 81.0965% | 81.1404% |
| PIT-80 absolute error | 1.0965 pp | 1.1404 pp |
| Mean predicted rate | 1.489489636 | 1.486587903 |
| Across-fixture predicted-rate SD | 0.428101618 | 0.416836564 |
| Within-GW Spearman | 0.333304749 | 0.334215918 |
| Mean predictive variance | 1.489329941 | 1.486443221 |
| P(goals=0) Brier | 0.168614448 | 0.168748271 |

CRPS improves **0.140509%**, MAE **0.086171%**. Aggregate PIT calibration is slightly
farther from nominal, though well within the frozen five-percentage-point guardrail.
Mean bias moves slightly farther from zero. This is not an across-the-board improvement.

Paired candidate-minus-control mean log loss is **-0.0009831791**, with row-weighted
GW-clustered SE **0.0007458257** over 114 season-qualified clusters. Its normal-approximation
95% interval is **[-0.0024449975, +0.0004786393]**, which includes zero. This descriptive
interval does not adjust for serial dependence or reuse of previously inspected seasons.
The result is neither independent confirmation nor real-deadline deployment evidence.

The primary lift and no-season-regression gates fail. Aggregate CRPS, PIT, population and
event/batch-isolation guards pass. No gate or parameter was changed after the result.

## Season and phase

| Season | Rows | Control log | SOT log | Relative log lift | Control / SOT CRPS |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2023-24 | 760 | 1.537995623 | 1.536771331 | +0.079603% | 0.660212 / 0.659370 |
| 2024-25 | 760 | 1.478042201 | 1.478371611 | -0.022287% | 0.617876 / 0.617986 |
| 2025-26 | 760 | 1.443914814 | 1.441860158 | +0.142298% | 0.594992 / 0.593093 |

| Phase | Rows | Control log | SOT log | Relative log lift |
| --- | ---: | ---: | ---: | ---: |
| GW1-6 | 358 | 1.434679573 | 1.434332297 | +0.024206% |
| GW7+ | 1,922 | 1.496331279 | 1.495229653 | +0.073622% |

Early-season log lift is -0.067864%, -0.035721%, +0.174429% by season, respectively: not
consistent. Home improves 0.092498%, away 0.038150%; promoted 0.117873%, established
0.058424%. The cold-start slice improves 0.331841% but contains only **24 rows**. SOT-history
0 has eight unchanged predictions; 1-2 has 16 rows (+0.524053%); 3-5 has 26 (-0.035033%);
6+ has 2,230 (+0.064791%). Small diagnostic slices did not drive tuning.

## What changed, including clean sheets

SOT weights across 114 folds: 0 / .25 / .5 / .75 / 1 in **56 / 20 / 9 / 14 / 15** folds;
mean weight **0.307018**. Goals-only half-life/prior choices stay exactly identical. Each
fold's xG/SOT/goals weights, scales and inner losses are retained, not selected from outer
scores. The control/candidate rate correlation is 0.992284 and mean absolute rate change
is 0.027413 goals. Mean level changes by -0.002902 goals, ranking improves only slightly,
and across-fixture spread contracts 2.6314%. Both models remain Poisson: no independent
dispersion mechanism was introduced, and a lower across-fixture rate SD is not a new
within-fixture dispersion fit.

The diagnostic is specifically P(the predicted team scores zero). A club's clean-sheet
probability is the **opponent's** zero-goal PMF mass in that fixture. Because the scored
population contains both reciprocal sides, pooled/full-season scores can be mirrored to
clean sheets; do not relabel a home-goals-zero slice as home clean sheets.

P0 Brier regresses **0.079366%** overall. By season the control/SOT values are
0.156256/0.156173, 0.169494/0.169575, and 0.180093/0.180497. Overall mean predicted P0 is
24.4863% / 24.4574%, versus the observed 23.2018%; aggregate zero-rate bias shrinks slightly
but the proper binary score worsens. Fixed 0.1-bin reliability counts/means are retained
in the JSON. No clean-sheet recalibration or post-result gate was fitted.

## Provenance and preservation

Starting/verified remote SHA: `9228892ba2abda80dd8dc8011c93302c6aad9710`.
Infrastructure was committed separately at `adfa948`. Preregistration and formal evaluation
use clean **`fd514cfae508fc98c313881ef990c8cf390be800`**. No main sync/merge/rebase or push.

Run UTC: **2026-09-07 02:41:31.974622 to 03:00:07.617720**, about 18m36s including exact
control reproduction. The SOT execution claim was reserved only after reproduction.
No `--allow-dirty`, second candidate invocation or historical formal rerun was used.

| Evidence | SHA256 |
| --- | --- |
| New evaluation config | `5fe7fa8e8682db1fae45d1d45e8a8dba516f33f66fae1179b65150e4332622d7` |
| Frozen read-only database | `0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8` |
| New result | `c94cf71a52e926970656733e746d8a0b661c050152647e5de78bde9b0cd8227f` |
| Canonical SDP manifest | `084137d2e03babbf9d8361e49be0f23ba19ae3baed34c5d9d0605264ea37057f` |
| New execution claim | `594c8debd1e4aa70d19547d12316bf1fcfc13c1cac6197d5065de46b11a353aa` |

The full JSON records current infrastructure/model/source hashes, inherited contracts/audit,
Python 3.12.14 and library versions, all **4,560 full 11-bin PMFs**, outcomes, cutoffs,
season/club/opponent identities, fixed slices, paired losses and fold diagnostics. Example:
`2023-24:1:43`, away versus team 90, observed goals 3, both model log losses 1.648322113.
No prediction distribution is regenerated from a mean for the audit.

Research DB remains explicitly
`D:/Personal/workspace/the_comet_fpl/.worktrees/sdp_test/data/fpl.duckdb`; it was not refreshed
or written. The persistent daily DB at `D:/Personal/fpl-operations/data/operational.duckdb`
is separate. Strict prospective revision-PIT, forecasts, optimizer/dashboard defaults,
original databases, previous model sources/configs and frozen result artifacts remain
unchanged by this experiment. Original SDP known-at metadata was never rewritten.

Checks and exact environmental failures: [verification](v2-weekly-sot-verification.md).
New tests: 46 passed. Full partition union: 2,358 passed / 15 failed / 4 skipped; 14 failures
are pre-existing Windows symlink privilege errors and the one local-HTTP abort passes its
five-test rerun unchanged. Ruff/mypy pass; 11 pre-existing formatting offenders remain.
Dashboard 312 tests, build and lint pass. This is not an unqualified green repository gate.

Read-only postflight reconciliation passed **11,438 assertions with zero failures**,
including every archive identity/outcome, all PMFs, independently calculated overall
log/CRPS/P0 scores and source/DB hashes. All 1,140 reciprocal fixture pairs also reconciled;
mirrored clean-sheet Brier equals the pooled zero-goal Brier exactly. No model was refitted.

## Next decision

**Do not preregister territory/box touches from this result.** The isolated SOT increment
is below 1%, uncertain, inconsistent by season and does not improve the pooled clean-sheet
proper score. Keep current model/defaults and continue the already-established strict-
prospective data/revision collection. Do not expand this blend, delete SDP evidence, rerun
old candidates or implement another model in this session. A future architecture hypothesis
would need its own justification, authorization and preregistration.
