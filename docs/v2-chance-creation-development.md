# Chance creation development: INCONCLUSIVE (2026-09-07)

Candidate: `retrospective_chance_creation_team_environment_v1`. This is one completed
retrospective-development evaluation, not promotion. The current prospective incumbent remains
`trailing_goals_attack_defence`; no production, optimizer or dashboard selector changed.

## Frozen execution and population

Design/config/implementation/tests were preregistered at
`0beb0f51370cefdd441356b32e78b7f9f22b349d`. A pre-fit metadata serialization correction,
documented in `v2-chance-preflight-correction.md`, was committed before evaluation at
`6529e71a85e45d276759ec3a5d9824382f5a5431`. It changed no scientific parameter or observation.
The initial invocation stopped before comparator/claim/fitting. The corrected execution reserved
one exclusive claim and completed once, 07:04:46.796272 through07:05:48.740385 UTC.

All 3,800 historical incumbent PMFs reproduced against both the retained cache and the actual
current prospective adapter with maximum absolute difference **0.0**, tolerance1e-12.
Coverage selected2023-24,2024-25,2025-26: 760/760 paired goals+archive-xG+SDP-shots sides each.
The scored population is **2,280 sides,1,140 fixtures,114 complete GW batches**. The historical
state cache contains189 batches;309 chance-stage models were fitted within the378-fit bound.
No scored row used fallback. Event-time, same-GW and in-sample stacking violations were zero.

Five frozen OOS tactical dimensions, last-five weights1,.707,.5,.354,.25 and n/(n+2) pooling
feed fixed ridge-1 volume and quality means. Archive xG is unchanged; later SDP xG is not used.
Goal rate is predicted shots times predicted xG/shot times global pooled OOS conversion.
The incumbent Poisson0..10 family and .05 floor remain; CS is opponent PMF mass at zero.
No current-fixture observed style or chance target becomes its own predictor. Original SDP
capture times remain later-known historical evidence, not fabricated historical deadlines.

## Result against the exact same-population incumbent

| Metric | Incumbent | Candidate | Relative improvement |
|---|---:|---:|---:|
| Goal NLL | 1.496896051 | 1.490035478 | +0.4583199% |
| CS Brier | 0.171251344 | 0.169951345 | +0.7591175% |
| CRPS | 0.631037556 | 0.625746502 | +0.8385% |
| Goal expectation MAE | 0.928921819 | 0.938221030 | -1.0011% |
| PIT-80 coverage | 0.810964912 | 0.814473684 | Slightly farther from0.8 |
| Mean prediction error | -0.043650236 | +0.045586397 | Bias changes sign |
| Within-GW Spearman | 0.298037026 | 0.312268930 | +0.014231904 absolute |

Both1% primary gates fail. The2025-26 CS regression also fails the fixed seasonal guardrail.
Five of eight recorded checks pass. This does not support replacing the incumbent.
The earlier tactical experiment scored only two seasons: its aggregate is not a like-for-like
numerical comparator for this new three-season run.

Candidate-minus-incumbent paired NLL is-0.006860573, GW-clustered SE0.003901451,
normal95% interval[-0.014507417,+0.000786270]. CS difference is-0.001299999,
SE0.001114575, interval[-0.003484565,+0.000884567]. Both include zero. These114-cluster
normal intervals do not adjust for serial dependence and are not proof of a stable gain.

| Slice | Sides | NLL improvement | CS Brier improvement |
|---|---:|---:|---:|
| 2023-24 | 760 | +0.9311% | +2.8113% |
| 2024-25 | 760 | +0.2529% | +0.6759% |
| 2025-26 | 760 | +0.1647% | -0.9916% |
| GW1-6 | 358 | -1.4310% | -1.7974% |
| GW7+ | 1,922 | +0.7932% | +1.2323% |
| Home | 1,140 | +0.0304% | +1.7858% |
| Away | 1,140 | +0.9108% | -0.4455% |
| Promoted | 342 | -1.7049% | +5.0744% |
| Established | 1,938 | +0.7788% | +0.3521% |
| Cold tactical state | 182 | -1.8305% | -2.7890% |
| High state confidence | 1,630 | +0.9599% | +1.6602% |
| Low state confidence | 650 | -0.8813% | -1.4198% |

CS is a defensive, reciprocal-opponent quantity: promoted-team CS improvement is not evidence
that their own attack prediction improves. That attack slice regresses. Slice definitions were
fixed before scoring; none was used to remove rows or retune this candidate.

## Football interpretation

The intermediate **volume** forecast is useful: paired shot RMSE5.643711→4.788716,
15.15% better than available same-club trailing-five measured shots (2,276 pairs).
Predicted-xG RMSE0.875173→0.775213 improves11.42% versus trailing-five xG (2,275 pairs).
Against incumbent goal rate, which is not a pure xG forecast, xG RMSE improves3.42%.
Quality barely beats the fold-local pooled anchor: exposure-weighted xG/shot RMSE
0.046898701→0.046686640, only0.4522% improvement across all2,280 sides.

Conversion is deliberately global and close to1: range0.986178–1.038236 across eligible folds,
median1.010522. Descriptive log-component SD is0.21582 for volume,0.03485 for quality and
0.01421 for conversion. This is accounting, not a causal ablation proving which layer caused lift.

The candidate raises mean predicted goals1.450209→1.539446 while narrowing rate SD
0.492195→0.383516 (-22.08%). It also changes ordering:2,772/21,875 non-tied within-GW
pairs reverse, and candidate/incumbent rank correlation is0.887599. It is neither an effectively
zero correction nor merely a constant rescaling. Some ordering improves, but outcome MAE worsens.
Aggregate CS frequency is better aligned:26.0321%→22.9317% predicted against23.2018% observed.
That improvement does not remove early-season/cold-state/latest-season weaknesses.

Conclusion: chance creation is forecastable, but this fixed decomposition does not translate
that into sufficiently material, robust Goal/CS improvement. **INCONCLUSIVE**, development-only,
left as run. No new candidate, changed pooling, extra feature or rerun follows from these slices.
The predeclared synthesis rule would retain the incumbent team component; no full synthesis has
been evaluated because the player-data prerequisites are blocked separately.

## Evidence and checks

- Result: `results/v2_chance_creation_development.json`, SHA256
  `f4cc595384102112ba2c41f118396d4176a6f7000a6f3c1753b5edf1a1ae952f`.
- Config SHA256:`3edb29cd29cbe7b3ab42e11eda9ab53dc061c7902602dd16ce7893f9b8640728`.
- Research DB:`D:\Personal\workspace\the_comet_fpl\.worktrees\sdp_test\data\fpl.duckdb`,
  SHA256:`0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8`, unchanged.
- Coverage SHA256:`7d84bfec69b6e6dac1c95d973a723c7e4dbb218432cf5945d5616cb8664fb163`.
- SDP capture-version identity:`8ce709b42edf7aae840906db4fbf3756c2b3fc48b0829296c07d3fa1899f67f4`.
- Upstream frozen style SHA256:`d52973687d2983c9fc3159365e8dde865ac60a7b1ddb0d0db6e5dc3268efd11c`.
- All303 pinned source/evidence files were unchanged at completion. Full PMFs, original capture
  lineage, OOS prediction/training identities, scalers, coefficients and fold certificates are retained.
- Independent read-only verification passed117,195 arithmetic/provenance checks with zero
  failures. All309 final gradients/objectives were recomputed at retained coefficients without
  optimization; maximum final gradient4.86e-13. All retained aggregate/slice/GW metrics and
  clustered uncertainties reproduce. See `results/v2_chance_creation_independent_audit.json`.
- Final focused suite316passed. Ruff check passed; strict mypy156source files passed.
  Broader suite2,687passed/14failed/4skipped; all14 failures are inherited Windows symlink
  WinError1314. That broader collection preceded the final runner regression additions, covered
  by the316-test final focused suite. Format check retains11pre-existing unrelated failures;
  all newly added source/tests are formatted. This is not an all-green repository gate.

The executed command was `python -m fpl.validate.dev_v2_chance_creation --db <research DB>`
using `D:\Personal\fpl-operations\.venv\Scripts\python.exe`. External logs:
`D:\Personal\fpl-operations\verification\football-program-20260907T070000Z\`.
PowerShell's logging pipeline surfaced `NativeCommandError` for INFO records written to stderr
and returned status1; the retained completed artifact and independent checks, not that wrapper
status alone, establish completion. The model was not rerun to change an exit status.
