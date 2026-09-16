# Broad starting role V1: retained development result

`retrospective_broad_starting_role_transition_v1` ran once from clean
`9e1b34d9881cefdb45165c3e564b99b5c57141bc`, 2026-09-07
10:06:24.761958–10:06:59.671385 UTC. Preregistration commit `ff37c3f` was followed
only by the normal merge of main snapshot `d6299be` (six additive provisional
capture files, no code). No previous result or candidate was rerun.

**SUPPORTED_FOR_DEVELOPMENT against its fixed primary baselines; transition
mechanism NOT supported against matched recent-state persistence.** Both statements
are required. Do not switch arms, retune, claim promotion or bury the stronger
diagnostic after observing this result.

## Data and scope

2025-26, 380 fixtures, 38 whole-GW batches, 29,747 outcome-free pre-GW predictions.
Score the same 8,162 measured FPL starters in every arm: 97.6316% of 8,360 starters.
The remaining198 labels stay excluded with explicit source reasons. The retained
574 competitive bundles supply19,320 mapped history observations, including cup
extra-time/shootout/aggregate finality. No target XI/actual role enters predictors.

Only four provider-licensed broad roles are supported: GK, DEF, MID, FWD. This is
P(role | hypothetical start), not starting probability, substitute role, or a fine
tactical taxonomy. Recent last-five starts, fixed weights1,.707,.5,.354,.25,
n/(n+2) pooling and strength2 transition prior remain unchanged. Target-GW fixtures
are isolated; prior completed events satisfy the six-hour conservative exclusion.
Original capture/interpretation timestamps stay later-known retrospective evidence.

## Frozen scores

| Arm | Mean NLL | Four-class Brier | Accuracy |
|---|---:|---:|---:|
| League role prior | 1.241570946 | .682249059 | 39.8432% |
| Smoothed last role | .722032115 | .369851807 | 89.2061% |
| Preregistered transition | .480621097 | .223390234 | 88.3362% |
| Matched recent-state persistence, diagnostic | **.422154657** | **.189604006** | **89.7207%** |

Primary NLL lift is33.43494%, with nonregressing Brier and maximum class marginal
bias.0116453 below the fixed.05 bound. The primary proper-score gate passes despite
slightly lower classification accuracy; accuracy was not substituted for that gate.
However transition NLL is **13.84953% worse than matched persistence**. Its paired
loss excess is.05846644, GW-clustered SE.01306931, normal95% interval
[.03285060,.08408228]. These38-cluster intervals do not adjust for serial dependence.

| Slice | Labels | Smoothed last NLL | Transition NLL | Matched persistence NLL |
|---|---:|---:|---:|---:|
| GW1–6 | 1,298 | .830048503 | .794575993 | .678177170 |
| GW7+ | 6,864 | .701605938 | .421251421 | .373740143 |

Role history is useful relative to a league prior; this experiment does not establish
additional value from transition smoothing. The deliberately fixed downstream
role covariate remains the preregistered transition output, not an opportunistic
replacement by the best diagnostic. Downstream component gates still decide value.
Only one season is covered; cross-season stability is unproved.

## Evidence, proxy and tests

- Result `results/player_role_history_development.json`, SHA256
  `c330d44a227ff6ff10cce1d5813f582d48dadfa181816c9333d6389358940809`.
- Independent audit `results/player_role_history_independent_audit.json`, SHA256
  `d895d8ad359b31da06f8a90ed6bdf95e0c47b87660bed16e70f4bb53cb52fadf`:
  **4,192,346 checks, zero failures**, including all four PMFs, labels, slices,
  original source hashes, transition certificates and event/GW boundaries; no refits.
- Config SHA256 `03ef03ab8d9724f9239c4517fa193d81cfb4179c975f7ad7506f14d4cb0827f3`.
- V3 operational DB SHA256
  `a8584ce79f421e0bd43057f3a8f63bac03e30b59cc1c2407b8a7c28387a35021`, unchanged.
- All full typed prediction files and source versions reside at
  `D:/Personal/fpl-operations/verification/player-role-development-20260907T100600Z`;
  the completed result retains each fold SHA and its scored rows. Their historical
  prediction cutoff, not the September execution time, owns each OOS source boundary.
- The roster cache includes270 direct price-proxy flags in this season; role predictors
  do not read prices. Full downstream reference remains86,755rows/821direct proxy
  rows across three seasons, never an exact historical deadline registry claim.
- Final pre-run focused gate140passed; Ruff and changed-file format/strict mypy passed.
  Inherited Windows symlink and unrelated full-format failures remain documented.

The executed entry point was `python -m fpl.validate.dev_player_role_history` with
explicit V3 DB, immutable minutes manifest, stage result, corrected coverage-v2,
final config and the new external output directory. Production defaults, optimizer
inputs, source databases and frozen Phase A/F/prior artifacts remain unchanged.
