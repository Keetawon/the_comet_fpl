# Full-player points synthesis V1: retained development result

**INCONCLUSIVE. Keep the incumbent.** The separately preregistered
`retrospective_player_points_synthesis_v1` completed ONCE. Its 0.0570413% mean
negative-log-score lift misses the fixed 1% bar, CRPS slightly regresses, and the
GW-clustered uncertainty includes no improvement. No retuning or promotion.

## What was actually tested

Apply the predeclared full-gate-passed-successor-else-incumbent rule, not a
post-result selection: **only H GK saves** replaces a component. Team Goal/CS,
current-proxy minutes, coupled player goals/assists, DC, absent cards and joint
BPS/bonus stay incumbent. D/E retain their 114-versus-181-fold ineligibility;
the scoped assists pass does not authorize its inclusion. F/G failed guardrails.

The comparator is a **retrospective proxy implementation of the current
prospective selector**, NOT exact historical deadline reproduction. Both arms
use the same archive-price substitution only on the 270 authorized cold-start
rows within this cohort. The original 821-row historical registry gap remains
explicit; the other 551 rows are outside the coverage-qualified cohort.

The fixed population is 2025-26: 38 GWs, 380 fixtures and 29,747 roster rows,
including DNPs. Older missing DC labels remain NULL rather than zero-filled.
All 380 incumbent fixtures first reproduced exactly against the unmodified
reference and empty synthesis wrapper: every composed field, zero PMF tolerance.
Only then was the single shared claim reserved. No upstream model was refitted.

Saved H parameters were projected onto all 3,427 GK roster rows, not selected
using actual appearances. All 767 overlapping H witnesses match exactly and
2,660 target DNP rows remain in the experiment. The full retained 2,313-row H
projection also reproduces at zero tolerance before the synthesis claim.

## Overall result

Lower NLL/CRPS/MAE/Brier is better. PIT80 targets 0.8.

| Metric | Current-proxy incumbent | H-only synthesis |
|---|---:|---:|
| Mean floored NLL | 1.088996402 | 1.088375224 |
| CRPS | 0.669071035 | 0.669132236 |
| Randomized PIT80 | 0.797693885 | 0.797861969 |
| Coarsened-target MAE | 1.079155528 | 1.079456096 |
| Signed-target MAE | 1.083088698 | 1.083389266 |
| Coarsened-target mean error | +0.111847833 | +0.112681094 |
| Mean xP | 1.271595035 | 1.272428295 |
| Within-GW Spearman | 0.684007420 | 0.683832593 |
| Brier points <=2 | 0.094567976 | 0.094589470 |
| Brier points >=5 | 0.067069540 | 0.067072816 |
| Brier points >=10 | 0.016453522 | 0.016450946 |
| Zero empirical target-PMF bins / log-floor hits | 79 | 78 |

NLL relative lift **+0.0570413%**; CRPS relative change **-0.0091471%** (worse).
Paired candidate-minus-incumbent loss is -0.000621177453, GW-clustered SE
0.001239879023 and normal 95% interval [-0.003051340338, +0.001808985432],
over 38 clusters. This interval is not serial-dependence adjusted. The small
directional mean is not compelling evidence of an end-to-end improvement.

Five of seven checks pass: identical population, zero temporal violations,
position guard, PIT80 and ranking guard. The fixed 1% primary bar and no-CRPS-
regression guard fail. Neither is loosened after inspection.

## Frozen diagnostic slices

| Slice | Rows | Current NLL | Candidate NLL | Relative lift |
|---|---:|---:|---:|---:|
| 2025-26 / overall | 29,747 | 1.088996402 | 1.088375224 | +0.05704% |
| GW1-6 | 4,330 | 1.272642688 | 1.272964095 | -0.02526% |
| GW7+ | 25,417 | 1.057710711 | 1.056928956 | +0.07391% |
| Home | 14,879 | 1.107228027 | 1.104417652 | +0.25382% |
| Away | 14,868 | 1.070751289 | 1.072320928 | -0.14659% |
| Promoted team | 4,754 | 1.001696882 | 1.005922585 | -0.42185% |
| Established team | 24,993 | 1.105601928 | 1.104058810 | +0.13957% |
| GK | 3,427 | 0.658281011 | 0.652889075 | +0.81909% |
| DEF | 9,733 | 1.178683922 | 1.178683922 | 0% |
| MID | 13,309 | 1.117743473 | 1.117743473 | 0% |
| FWD | 3,278 | 1.156274693 | 1.156274693 | 0% |
| Direct proxy / cold start | 270 | 1.218760329 | 1.217770925 | +0.08118% |
| Non-proxy / established player | 29,477 | 1.087807805 | 1.087190001 | +0.05679% |
| Witnessed nominal workload >90m / 7d | 2,086 | 2.257545216 | 2.258794103 | -0.05532% |
| Witnessed nominal workload (0,90m] / 7d | 7,465 | 2.089288997 | 2.086197260 | +0.14798% |
| Workload feature unavailable | 20,196 | 0.598563789 | 0.598662644 | -0.01652% |

Proxy exclusion is diagnostic only and does not change the verdict or nominated
population. Conservative propagated dependence is retained for 4,830 team-proxy
and 7,688 fixture-proxy rows. Role confidence and rotation-risk slices, full
reliability curves, and every GW's paired fixture/player losses are in the result.
Workload slices describe D's usable positive-witness nominal-minute lower bound,
not complete competitive coverage, exact rest, or all witnessed appearances.

GK full-points CRPS also worsens (0.393199058 -> 0.393730290) despite its 0.81909%
NLL improvement. Non-GK PMFs and bonus outputs are unchanged in this retained run;
this is a read-only diagnostic, not an added gate. The actual incumbent BPS code
does not explicitly feed drawn saves/DC/cards into BPS: their indirect residual
treatment remains unchanged. This experiment cannot establish the benefit of a
future save-aware bonus model and does not authorize one.

H remains a supported **saves-count** development result (+2.22404% NLL across
three seasons), but that does not imply a material full-points improvement.
The synthesis changes only GK inputs; it neither tests a new outfield ordering
nor justifies added full-pipeline complexity. One fully measured season cannot
establish cross-season robustness.

## Evidence limits retained, not repaired after scoring

Historical provider observations retain actual later capture timestamps; source
event cutoffs and whole-GW isolation are enforced without weakening prospective
PointInTimeView. Historical roster, first-kickoff and completion proxies remain.
No current target lineup, recorded minutes or ICT enters its predictor.

Scoring replays all measured components with loaded 2026/27 rules, including
recorded bonus/cards/penalties/own goals. Preserve signed outcomes. The inherited
PMF support is 0..34, so the registered proper-score target is explicitly
`min(34,max(0,signed_target))`. There are 77 negative targets (one DNP -1), none
above 34. This is not a calibrated signed-points PMF. The inherited fixed 2,000
Monte Carlo draws, fixture seed from 202627, 1e-12 log floor and zero empirical
bins limit the strict properness of the reported floored NLL. No smoothing or
seed/draw tuning follows this result. Rare card/penalty/own-goal prediction gaps
and the incumbent component-independence approximations remain disclosed.

## Provenance and independent verification

Preregistration / formal evaluation clean HEAD:
`e716ec1b9299578369f1e394c901e3b1a82bc3ea`.
Run started 2026-09-07T13:13:47.800040Z; finished 13:19:59.623265Z.

- Config SHA256: `32f4fb23282e2081897060701446252fb40a75cf450e363b25937f5c58fb7047`.
- Research DB SHA256: `0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8`.
- Target identity SHA256: `bbad5f15f9969568af0fc078c80e1725ffaf2b0be661b6831f553cd7c4063566`.
- Result SHA256: `0d3599fd5d95a9e301c8f4ea465e71bf235499446f318a3c22403f5d9328543d`.
- Audit SHA256: `358badbf26be931377075518fe4b9bca2204d63e6950bf78127e55c6da187b94`.
- Independent audit: **4,297,806 checks, zero failures**, first artifact audit.
  Every PMF, target, saved projection, source/claim hash, slice and gate reconciles.
  Overall/slice arithmetic difference is zero; maximum paired-interval difference
  is 4.34e-19. This audit runs no fits, forecast simulation or formal runner.

Byte-exact retained summaries:
`results/player_points_synthesis_development.json` and
`results/player_points_synthesis_independent_audit.json`. Their source and output
manifests retain all hashes. Complete paired 35-bin PMFs, original control files,
saved conditional H PMFs and bonus diagnostics are retained locally at:

`D:/Personal/fpl-operations/verification/full-player-pmf-synthesis-20260907T131000Z`

Independent audit, scripts and synthetic audit checks:

`D:/Personal/fpl-operations/verification/points-synthesis-independent-audit-20260907T131000Z`

Command executed ONCE, using the persistent project Python environment:

```powershell
& D:\Personal\fpl-operations\.venv\Scripts\python.exe -m fpl.validate.dev_player_points_synthesis --db D:\Personal\workspace\the_comet_fpl\.worktrees\sdp_test\data\fpl.duckdb --inputs D:\Personal\fpl-operations\verification\points-synthesis-draft-20260907T110000Z\inputs.json --output D:\Personal\fpl-operations\verification\full-player-pmf-synthesis-20260907T131000Z
```

## Tests and disposition

Before scoring: 180 focused tests passed; Ruff and strict mypy (189 source files)
passed; all ten changed Python files passed format. The corrected broader suite
passes **3,572 tests, four skipped, zero failures** in 417.82s, excluding
`tests/test_bi_export.py`. Its known inherited Windows symlink-privilege failures
are not silently counted as passing. The prior broader attempt had one
order-dependent test failure, corrected only in its invalid-input construction
before preregistration/evaluation; no model arithmetic changed. Eleven unrelated
pre-existing files still fail global formatting. Therefore the entire repository
gate is NOT described as all green. No frontend/default route changed.

Final read-only checks also confirm all 65 Python files changed during the amended
program pass format, global Ruff passes, and strict mypy still passes 189 source
files. The additive `results/football_program_completion_verification.json`
records the exact corrected test command/XML digest, unchanged database hashes
and eleven global-format exceptions. It is not another model evaluation.

The original research/root databases and all previously frozen artifacts remain
preserved. Only additive V2 evidence is committed. No optimizer, dashboard,
prospective default, production configuration, schedule or main-branch change.

**One next direction:** prospective shadow validation of the accepted GK-saves
opportunity chain, including its downstream points distribution, while retaining
the incumbent. Accumulate real knowledge-time-valid evidence rather than retuning
these frozen historical candidates. This next direction is not implemented here.
