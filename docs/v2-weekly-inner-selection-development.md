# Weekly inner-selection development result

Date: 2026-09-06. Verdict: **INCONCLUSIVE**, development-only, not promoted.
The one formal run is complete; do not rerun, retune, reinterpret its preregistration,
or overwrite `results/v2_weekly_inner_selection_development.json`.

## Outcome

Weekly inner refits improve the unchanged goals+xG control's mean negative log score
from **1.489436133244 to 1.486650879246**, a **0.187001% relative lift**. This is below
the preregistered **1%** requirement (candidate log score at most 1.474541771911).
All three full seasons improve, as do aggregate CRPS and MAE. Only the primary lift
check fails; all five other frozen development checks pass. This is a small positive
procedural result, not a demonstrated material accuracy upgrade or promotion verdict.
Log-score lift is not a percentage-point change in match-result classification accuracy.

The prompt's premise was confirmed in source: both legacy inner-selection stages fit
once before their six-GW holdout, while outer evaluation refits before every target GW.
The minimal additive implementation reuses the existing estimator and preserves its
staged search: **goals select decay/prior, then goals+xG select blend weights**. Joint
optimization would have changed another procedure and was not implemented.

## Exact comparison and provenance

- Control: `retrospective_goals_xg_control_v1` (unchanged legacy frozen-inner selection).
- Candidate: `retrospective_goals_xg_weekly_inner_selection_v1`.
- Signals: recorded goals and existing `fpl_archive.expected_goals` only. No SDP/SOT,
  territory, possession, xGOT, player feature, imputation, or new distribution family.
- Same 2023-24 through 2025-26 population: **2,280 team-sides, 1,140 fixtures, 114 folds**.
- Same grids: half-life 40/80/160/320/640/no decay; prior 2/4/8/16/32; xG weight
  0/0.25/0.5/0.75/1. Same cold-start thresholds, outer-season promoted priors, scaling,
  rate floor 0.05, Poisson support 0..10, seed **20260904**, cutoffs and targets.
- Both models fit before a complete target-GW batch. Every inner weekly fit filters
  actual kickoff times, including delayed/DGW legs. No within-GW updates occur.
- **1,368 measured inner-stage batches checked; zero event-time or target-GW violations**.
  Outer population, cutoffs and input hashes agree in every fold.
- Strict prospective/PIT, forecast jobs, optimizer, production defaults, all existing
  model files and frozen result artifacts remain unchanged. Historical roster, first-
  kickoff and inherited fixed-prior caveats remain; this is not real-deadline evidence.

Git starting/verified remote SHA: `449c9dbd72cb3dcc9c52ae153a995b8bcdb2b852`.
Two additive main snapshot commits, `b03cc8d` and `1030469`, were synchronized by normal
merge `8c4d5f0c59b5c9b199668dfc51ea043ebc37ec57`. Only twelve new snapshot files were added;
the evaluation database was not refreshed. No rebase, main promotion or PR.

Preregistration and evaluation both use clean commit
**`507c3d28b96114b73274d5089bdf70845e3dca36`**. Implementation, tests, design and verification
were committed before formal scoring. Git/config/source/database hashes were checked before
and after the run. A durable exclusive claim was reserved only after control reproduction;
it prevents a second candidate invocation even after interruption. No `--allow-dirty` path.

| Fingerprint | SHA256 |
|---|---|
| Evaluation config | `4d485f961a69b8064dc4b8dc968f34b440cde1ff27c8cc51cec768259bbee929` |
| Database | `0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8` |
| Result | `79f3a0815271a95cd0e39874aaa20fa89d3b1df0875a5e780c0317a961424d35` |
| Weekly selector source | `c5570d61300dc3cc0051aca9590591e79b0e21efb24eb1f6259ca0a60d234985` |
| Runner source | `e8aa6cb72ac62ed83c3c6d9e56ffca2bac603469b72e72cc0fd2e06ea3599d3b` |
| Ancestral coverage report | `7b37ce3998f1f252a6b1d7ea7978b1f916f7bf414eb8c942eae87e2bc50c5a6d` |
| Ancestral SDP manifest | `084137d2e03babbf9d8361e49be0f23ba19ae3baed34c5d9d0605264ea37057f` |

The SDP manifest is population provenance only, never model input. Full inherited/frozen
source and result fingerprints are retained in the result's `provenance` block. Run time:
2026-09-06 **09:48:22–09:57:00 UTC** (about 8m38s, including control reproduction).

## Control reproduction prerequisite

The old control was rerun **alone first**, not either old SOT candidate. It reproduces
2,280 rows / 114 folds and all ordered fixture identities, outcomes, venues, cutoffs,
fixed-population slice scores, parameters and signal fits. Mean log score and CRPS
differences are exactly **0.0**; maximum absolute PMF difference is
**5.551115123125783e-16**, below the frozen absolute tolerance **1e-12**. Original first-SOT
control aggregates also agree. The reference result was never rewritten.

## Overall metrics and uncertainty

Lower is better for log score, CRPS and MAE. PIT coverage should be near 80%.

| Metric | Frozen-inner control | Weekly-inner candidate |
|---|---:|---:|
| Mean negative log score | 1.489436133 | 1.486650879 |
| CRPS / RPS | 0.626657793 | 0.624360149 |
| MAE | 0.931537854 | 0.928009198 |
| Mean error (prediction - actual) | -0.004225776 | -0.004370013 |
| PIT-80 coverage | 80.8333% | 81.0965% |
| PIT-80 absolute error | 0.8333 pp | 1.0965 pp |
| Mean predicted rate | 1.489633873 | 1.489489636 |
| Across-fixture predicted-rate SD | 0.430611597 | 0.428101618 |
| Within-GW Spearman | 0.326617654 | 0.333304749 |
| Mean predictive variance | 1.489478110 | 1.489329941 |

CRPS improves **0.366650%**, MAE **0.378799%**. Aggregate PIT-80 moves slightly farther
from nominal coverage, but remains well within the frozen five-percentage-point guardrail.
Do not call this an across-the-board calibration improvement.

Paired candidate-minus-control mean log loss: **-0.002785254**. Row-weighted, GW-clustered
standard error: **0.001250207**, over 114 season-qualified clusters. Its normal-approximation
95% interval is **[-0.005235660, -0.000334848]** (negative favors weekly selection), equivalent
to approximately **0.0225%–0.3515%** relative improvement with the control fixed. The interval
excludes zero under that approximation, but is far below the 1% materiality bar. It does not
adjust for serial dependence across GWs or reuse of previously inspected development seasons;
it is not independent confirmation. The separately labelled unweighted-GW-mean SE is 0.001243975.

## Season and phase slices

| Season | Rows | Control log | Weekly log | Relative lift | Control / weekly CRPS |
|---|---:|---:|---:|---:|---:|
| 2023-24 | 760 | 1.541525 | 1.537996 | +0.2290% | 0.663475 / 0.660212 |
| 2024-25 | 760 | 1.481843 | 1.478042 | +0.2565% | 0.620747 / 0.617876 |
| 2025-26 | 760 | 1.444940 | 1.443915 | +0.0709% | 0.595752 / 0.594992 |

The gain is directionally consistent across all three full seasons, but varies in size.

| Phase | Rows | Control log | Weekly log | Relative lift | Control / weekly PIT-80 |
|---|---:|---:|---:|---:|---:|
| GW1-6 | 358 | 1.442178 | 1.434680 | +0.5199% | 84.36% / 83.52% |
| GW7+ | 1,922 | 1.498239 | 1.496331 | +0.1273% | 79.86% / 79.97% |

Early-season gain is **not universal**: 2023-24 +0.7768%, 2024-25 +1.0360%, but
2025-26 **-0.2482%**. Later-GW gains are +0.1336%, +0.1178%, +0.1304%, respectively.
The 358 early rows are the unchanged population, not an invented 360-row balanced sample.

Other fixed slices improve in log score: home +0.2274%, away +0.1441%, promoted +0.0554%,
established +0.2066%, control-defined cold starts +0.8295% (only 24 rows), non-cold starts
+0.1809%. Retain the small cold-start denominator; no slice was used for tuning. Complete
slice CRPS/PIT/calibration and every GW's paired loss are in the result.

## Selection stability

Old and new settings disagree in **74/114 folds (64.9%)** on at least one parameter.

| Parameter | Old vs new disagreement | Old adjacent changes | Weekly adjacent changes |
|---|---:|---:|---:|
| Half-life | 36/114 | 61/111 | 58/111 |
| Prior strength | 29/114 | 55/111 | 51/111 |
| xG weight | 54/114 | 62/111 | 60/111 |
| Any setting | 74/114 | 100/111 | 96/111 |

Adjacent comparisons exclude summer boundaries. Joint switches fall from 90.1% to 86.5%,
so stability improves only modestly; selection remains highly changeable. Early-season
joint switches are unchanged at 13/15; prior switches improve 8→6, while xG-weight switches
increase 7→8. There is no general early-season stabilization claim.

| Setting distribution (ordered) | Old counts | Weekly counts |
|---|---|---|
| Half-life: 40, 80, 160, 320, 640, no decay | 16, 14, 30, 16, 19, 19 | 8, 12, 38, 17, 17, 22 |
| Prior: 2, 4, 8, 16, 32 | 31, 16, 12, 15, 40 | 31, 13, 10, 20, 40 |
| xG weight: 0, .25, .5, .75, 1 | 25, 19, 22, 14, 34 | 12, 28, 14, 19, 41 |

Zero xG weight drops from **25/114 (21.9%) to 12/114 (10.5%)**; in early season, 7/18→4/18.
The weekly selector more often keeps xG and less often chooses the shortest half-life.
Parameter entropy (bits) decreases: half-life 2.5353→2.4160, prior 2.1655→2.1467,
xG weight 2.2610→2.1724, joint setting 5.9654→5.6559. Entropy measures diversity, not proof
of harmful instability. Every fold's exact settings and both selected inner-stage scores
are retained; old/new inner scores use different update schedules and are not identical
holdout forecasting tasks.

## Interpretation and single next recommendation

1. **Did log score improve?** Yes, +0.1870%, below the materiality gate.
2. **Did GW1-6 improve?** Aggregate +0.5199%, but 2025-26 early season regressed.
3. **Did later GWs improve?** Yes, +0.1273%, positive in each season.
4. **Season consistency?** Full-season gains are positive in all three; early-phase consistency
   is not established. The result does not diagnose every early-season weakness.
5. **Stability?** Modestly improved overall, not stabilized; early joint switching is unchanged.
6. **Was the mismatch material?** It changed selections and produced a small useful measured
   gain, but **did not meet the predeclared 1% materiality threshold**. It is not the sole cause
   of model weakness and not merely a parameter change with zero predictive consequence.
7. **What changed in predictions?** Mean level is nearly unchanged (-0.000144 goals); rate SD
   contracts only 0.58%, with somewhat better ranking. This is consistent with a small refinement
   in relative team/fixture rates, not a new dispersion model or broad mean correction. Individual
   setting contributions are not separately identified by this one procedural experiment.

Recommend **A only: separately preregister one real-SOT incremental test against this frozen
weekly-inner goals+xG control**, retaining development-only status. The consistent small
procedural gain justifies testing whether the previous frozen-inner procedure affected SOT's
incremental value; it does not establish that SOT will help. Existing SOT results stay frozen,
and the successor needs a new identity/contract and explicit owner authorization. This result
does not justify a broad architecture rewrite or choosing an unrelated DC experiment on its
own. No next experiment, model promotion, territory feature or production change was implemented.

## Retained artifact and verification

Schema version 1 stores two full 11-bin PMFs for every team-side (**4,560 PMFs**), exact
outcomes, fixture/opponent permanent identities, cutoffs, per-row and per-fixture paired losses,
per-GW scores, both selectors' settings/inner losses, measured guards, aggregate/slice metrics,
clustered uncertainty and clean provenance. Example identity: `2023-24:1:43`, away versus
team code 90, cutoff/kickoff `2023-08-11T19:00:00+00:00`, observed goals 3; old/new log loss
1.670343468 / 1.648322113. The JSON retains the complete PMFs, not only these scalars.

Offline verification: **156 focused tests passed**, including 80 new tests. Partitioned
full-suite union: **2,265 passed, 14 pre-existing Windows symlink failures, 4 skipped**.
Ruff lint passed; strict mypy passed all 139 source files; new-file format passed, with
11 unchanged repository format offenders. Dashboard: 312 tests passed, build/lint passed
with existing warnings. This is not an unqualified green repository gate; exact failures
and commands are in `v2-weekly-inner-selection-verification.md`.

Post-run independent read-only reconciliation passed **31,265 checks with zero discrepancies**:
264 overall/slice/fold model-score blocks recomputed from the retained PMFs, every fixture and
recorded target verified against the read-only archive, every parameter diagnostic and inner
guard reconciled, and all source/config/database/reference/claim hashes rechecked. The clustered
loss difference and SE reproduced exactly. This did not refit or rerun any model.
