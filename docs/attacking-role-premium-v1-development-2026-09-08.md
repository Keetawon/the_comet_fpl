# Attacking Role Premium V1 development result, 2026-09-08

**Verdict: C - REFUTED.** The fixed recent-360-minute candidate worsens conditional next-match xGI/90 MAE by 1.854% versus the all-season shrunk player-history control. The paired GW-blocked 95% interval is a 1.115% to 2.621% regression. The result remains frozen; there is no retuning, alternate window, new season, model fitting or production integration.

This conclusion concerns the specified window-plus-shrinkage mechanism on class-B archived evidence and target appearances of at least 45 minutes. It does not independently test the percentile transformation, every possible attacking-usage signal, or exact tactical OOP. It is not an unconditional player-fixture EV or full FPL-points forecast.

## Population, preregistration and execution

- Starting SHA: `4fd1c5fdf271aef329d196a22236f8f9310254d7`.
- Clean preregistration SHA: `deafed70a1a2fbe65701f719523fbcb064efde8b`.
- Branch: `claude/comet-fpl-v2-architecture-mqrj8f`; starting local/remote agreement 0/0, 59 ahead / one behind remote main.
- Exactly one formal evaluation. Explicit replay verifies the same run, not another candidate or verdict selection.
- Formal execution: `2026-09-08T08:36:59.704059+00:00` to `2026-09-08T08:38:21.602504+00:00`.
- Evidence remains **ARCHIVED_AS_OF / CLASS-B SNAPSHOT-CUTOFF**, not class-A exact historical FPL deadline replay.

The 26,312 acquired 2023/24 rows remain the only observation source. The reproduced target population is 36 GWs, 24,947 rows and 763 stable player codes; all targets receive predictions. Primary conditional scoring contains 7,403 paired-measured appearances with target minutes >=45. Actual target minutes and attacking outcomes never enter the predictor.

| Position | Audited targets | Primary >=45-minute targets |
| --- | --- | --- |
| DEF | 9106 | 3050 |
| MID | 12185 | 3489 |
| FWD | 3656 | 864 |

Target sequence: 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38. GW1 supplies history. The 607 GW17 target rows, 165 absent cutoff-registry rows and eleven cutoff-club mismatches remain excluded. Available GW17 observations may enter later history under the existing contract.

Frozen target identity/cutoff SHA256: `f2467d7fc5a66df79c6d2d8c33b7adcca0085143d2ba0c2884bfce07624743ec`. Observation SHA256: `0d699021537dc7e636f0dfb8e4484f98fc57263663806631c5c8e075b0c5cefc`. Every target uses deterministic historical position and fixture-time club identity. Source/capture/available timestamps are unchanged. Exact historical FPL deadlines and independently attested original public archive push times remain unproven.

## Frozen mechanism

For each position and cutoff, pool eligible positive-minute paired xG/xA history into exposure-weighted positional priors. The control uses all eligible current-season player exposure; the candidate uses the newest 360 witnessed minutes. The oldest boundary match is prorated by included/observed minutes, an aggregate weighting convention rather than inferred event timing. Both use `(90*opportunity + 450*position_prior90)/(measured_minutes + 450)`. No parameters are fit or selected.

The premium is the equal-weight average of candidate xG90 and xA90 midrank percentiles against one state per historically observed same-position player, including self. It is a bounded descriptive score; its own distribution is not uniform. Historical exposure remains separately visible. A cold-start score ranks a positional prior and is not evidence that the player has actually shown advanced usage.

Only prior minutes, starts, xG, xA and historical FPL position enter the mechanism. Goals, assists, points, ICT, formation, team attacking totals, FixtureEnvironment, availability predictions and expected minutes are absent. Identity fields support ordering and diagnostics only. The candidate also shrinks more strongly after the control accumulates a long history, so this experiment does not disentangle recency from induced shrinkage. Aggregate xG/xA cannot distinguish open-play advanced usage from set-piece threat.

## Primary metrics and frozen gates

| Metric | Control | Candidate | Relative MAE lift |
| --- | --- | --- | --- |
| xgi90 MAE | 0.198499 | 0.202179 | -1.854% |
| xg90 MAE | 0.150727 | 0.153617 | -1.918% |
| xa90 MAE | 0.090508 | 0.092655 | -2.373% |
| xGI90 pooled Spearman | 0.542396 | 0.524093 | not applicable |

Positive lift means lower candidate error. The absolute MAE-improvement interval is [-0.005181, -0.002211]; relative interval [-2.621%, -1.115%]. All 10,000 paired whole-GW draws are defined, seed 20260908, preserving row weighting. One season and repeated overlapping player histories limit interpretation of this cluster interval.

The candidate fails the >=1% xGI improvement, <=0.5% xG/xA regression, and non-negative DEF gates. The primary loss exceeds 1% and the bootstrap upper bound is below zero, meeting the preregistered REFUTED rule. Calibration, catastrophic positional-slice guards and PIT checks pass. No diagnostic can override this decision.

| Position | Primary rows | Control xGI90 MAE | Candidate xGI90 MAE | xGI lift | xG lift | xA lift | Control/Candidate Spearman | Positive shifts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DEF | 3050 | 0.111025 | 0.111604 | -0.522% | -1.127% | -1.965% | 0.234400 / 0.194610 | 101 |
| MID | 3489 | 0.232689 | 0.239294 | -2.838% | -2.809% | -2.875% | 0.430550 / 0.389015 | 442 |
| FWD | 864 | 0.369223 | 0.372042 | -0.764% | -0.717% | -0.727% | 0.239420 / 0.194193 | 59 |

All three positions regress. MID contributes the largest decline; the DEF direction is also negative. Premium quantiles by position and every secondary component metric are retained in the immutable result.

| Ranking / bias diagnostic | Control | Candidate |
| --- | --- | --- |
| Mean within-position/GW xGI90 Spearman | 0.294252 | 0.256832 |
| Top-decile future xGI90 mean | 0.456116 | 0.428193 |
| Top-decile lift over conditional mean | +83.553% | +72.316% |
| Mean signed xGI90 error | 0.013934 | 0.012986 |
| Mean predicted xGI90 | 0.262427 | 0.261479 |
| Mean observed xGI90 | 0.248492 | 0.248492 |

Ranking uses 108 position/GW groups and 798 conditional top-decile rows per arm. Both mildly overpredict the conditional mean. The candidate slightly improves mean bias while worsening absolute error and ranking; bias alone is insufficient.

## History, time and exposure diagnostics

| Prior measured minutes | Rows | Control MAE | Candidate MAE | Lift |
| --- | --- | --- | --- | --- |
| 0 | 56 | 0.151437 | 0.151437 | +0.000% |
| 1-89 | 297 | 0.239981 | 0.239981 | +0.000% |
| 90-269 | 907 | 0.209165 | 0.209165 | +0.000% |
| 270-449 | 801 | 0.195148 | 0.195473 | -0.167% |
| 450-899 | 1722 | 0.194248 | 0.194145 | +0.053% |
| 900+ | 3620 | 0.195915 | 0.203419 | -3.830% |

Arms coincide below 360 prior minutes by construction. The 900+ bucket loses 3.830%; this is a descriptive localization of the fixed mechanism's loss, not authorization to choose a new window or exposure gate.

| Fixed season third | Rows | Control MAE | Candidate MAE | Lift |
| --- | --- | --- | --- | --- |
| early_gw1_13 | 2462 | 0.208734 | 0.208751 | -0.008% |
| middle_gw14_26 | 2445 | 0.193688 | 0.197809 | -2.128% |
| late_gw27_38 | 2496 | 0.193116 | 0.199979 | -3.554% |

| Prior-appearance slice | Rows | Control MAE | Candidate MAE | Lift |
| --- | --- | --- | --- | --- |
| established_history | 6733 | 0.196237 | 0.200284 | -2.062% |
| no_prior_appearance | 56 | 0.151437 | 0.151437 | +0.000% |
| one_prior_meaningful_appearance | 428 | 0.223218 | 0.223218 | +0.000% |
| only_short_prior_appearances | 186 | 0.237674 | 0.237674 | +0.000% |

| Venue | Rows | Control MAE | Candidate MAE | Lift |
| --- | --- | --- | --- | --- |
| AWAY | 3709 | 0.194293 | 0.196776 | -1.278% |
| HOME | 3694 | 0.202722 | 0.207605 | -2.409% |

The broader positive-minute slice has 10,051 rows and -0.990% xGI90 lift. The 1-44-minute slice has 2,648 rows and -0.192% lift. All 14,896 zero-minute targets retain predictions but have unavailable rate labels. These broader slices do not replace the primary population.

## Positive-shift and high-premium DEF diagnostics

The frozen positive-shift rule selects 602 primary cases: DEF 101, MID 442, FWD 59. Persistence under the predeclared target-versus-control rule is 23.090%. Mean target-minus-candidate xGI90 is -0.088974, indicating substantial mean reversion in this selected subset.

| Slice | Rows | Future xGI90 mean | Control MAE | Candidate MAE | Lift |
| --- | --- | --- | --- | --- | --- |
| Positive shift | 602 | 0.191683 | 0.160639 | 0.202512 | -26.066% |
| Non-shift | 6801 | 0.253521 | 0.201850 | 0.202150 | -0.149% |

Shift cases have a 26.066% MAE regression and lower raw future usage than non-shift cases. Those populations differ in position and baseline usage; this is not a matched causal comparison. The control closely matches the shift subset mean while the candidate overpredicts it.

| DEF premium score | All predicted cases | Primary cases | Mean prior minutes | Candidate xG90 | Candidate xA90 | Mean shift | Future xGI90 | Control/Candidate MAE | Lift |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0.9 | 167 | 83 | 1094.361446 | 0.101035 | 0.137502 | -0.005982 | 0.239380 | 0.190151 / 0.185037 | +2.690% |
| 0.975 | 28 | 5 | 1033.000000 | 0.135483 | 0.176332 | 0.000870 | 0.356129 | 0.296217 / 0.298274 | -0.695% |

High-premium defenders show greater future xGI90 than the full DEF conditional mean (0.108765), so the score can describe attacking profiles. The >=.90 subgroup gain does not change the failed pooled/DEF result; >=.975 has only five meaningful targets. These are composite score thresholds, not literal joint percentile coverage, and none confirms a tactical role.

Every selected case is stored with exact target identity, prior minutes, component rates/percentiles, shift, frozen outcome, and errors in `results/attacking_role_premium_v1_cases_2026-09-08.json`. Rates/errors remain NULL below 45 target minutes. The following fifteen cases use the preregistered score ordering, not observed success; repeats are player-fixture cases, not a forced distinct-player shortlist.

### Top five

| Player / stable code | GW / fixture | Premium | Prior minutes | Target minutes | Candidate xG90/xA90 | Shift xGI90 | Future xGI90 | Control/Candidate absolute error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Ben Chilwell / 172850 | 16 / 154 | 0.991176 | 334.000000 | 0 | 0.127344 / 0.182419 | 0.000000 | NULL | NULL / NULL |
| Ben Chilwell / 172850 | 22 / 219 | 0.988827 | 347.000000 | 45 | 0.125416 / 0.187134 | 0.000000 | 0.000000 | 0.312550 / 0.312550 |
| Ben Chilwell / 172850 | 15 / 150 | 0.988095 | 334.000000 | 0 | 0.127424 / 0.182598 | 0.000000 | NULL | NULL / NULL |
| Ben Chilwell / 172850 | 13 / 127 | 0.987578 | 334.000000 | 0 | 0.127384 / 0.182169 | 0.000000 | NULL | NULL / NULL |
| Ben Chilwell / 172850 | 11 / 110 | 0.987421 | 334.000000 | 0 | 0.127615 / 0.182709 | 0.000000 | NULL | NULL / NULL |

### Middle five

| Player / stable code | GW / fixture | Premium | Prior minutes | Target minutes | Candidate xG90/xA90 | Shift xGI90 | Future xGI90 | Control/Candidate absolute error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Victor Lindelöf / 184667 | 3 / 28 | 0.500000 | 45.000000 | 45 | 0.052419 / 0.073455 | 0.000000 | 0.040000 | 0.085874 / 0.085874 |
| Scott McKenna / 168281 | 7 / 67 | 0.500000 | 416.000000 | 0 | 0.054520 / 0.057043 | 0.007214 | NULL | NULL / NULL |
| Ethan Pinnock / 231065 | 7 / 67 | 0.500000 | 540.000000 | 90 | 0.102297 / 0.041488 | 0.002506 | 0.080000 | 0.061279 / 0.063785 |
| Yasser Larouci / 432990 | 7 / 69 | 0.500000 | 195.000000 | 0 | 0.062885 / 0.050706 | 0.000000 | NULL | NULL / NULL |
| Antonee Robinson / 169528 | 10 / 94 | 0.500000 | 720.000000 | 90 | 0.035789 / 0.080133 | 0.025668 | 0.220000 | 0.129746 / 0.104078 |

### Lowest five

| Player / stable code | GW / fixture | Premium | Prior minutes | Target minutes | Candidate xG90/xA90 | Shift xGI90 | Future xGI90 | Control/Candidate absolute error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Kurt Zouma / 103192 | 4 / 38 | 0.025194 | 270.000000 | 90 | 0.035772 / 0.046503 | 0.000000 | 0.200000 | 0.117725 / 0.117725 |
| Ezri Konsa Ngoyo / 199798 | 5 / 41 | 0.026786 | 360.000000 | 90 | 0.031471 / 0.041612 | 0.000000 | 0.020000 | 0.053083 / 0.053083 |
| Illia Zabarnyi / 477580 | 6 / 53 | 0.027397 | 450.000000 | 90 | 0.031624 / 0.039967 | 0.006159 | 0.070000 | 0.004568 / 0.001591 |
| Jarrad Branthwaite / 480455 | 8 / 75 | 0.029221 | 450.000000 | 90 | 0.030883 / 0.039094 | -0.032002 | 0.260000 | 0.158020 / 0.190023 |
| Illia Zabarnyi / 477580 | 5 / 42 | 0.032143 | 360.000000 | 90 | 0.031471 / 0.042723 | 0.000000 | 0.000000 | 0.074194 / 0.074194 |

All five top score cases belong to Ben Chilwell; four have no meaningful target exposure. They were retained rather than replaced by more attractive examples. A per-playing-time score does not predict whether a player appears.

Named cases: Hume and De Cuyper are **NOT IN AUDITED POPULATION**. The exact retained surname search finds **Tommi O'Reilly**, stable code 515599, historical MID, with 20 GW19-38 target rows, all zero minutes and no prior positive exposure. Those scores are the positional prior; there is no evaluable persistence outcome. This surname hit must not be presented as Nico O'Reilly. Nico O'Reilly is not in the audited source population. No additional season or source was fetched to force a named case.

## PIT, reproducibility and artifact identity

The independent post-result audit reconciles every one of 24,947 predictions and labels, 152 retained raw payload hashes, 36 archived target cutoffs, all historical priors/recent windows/percentiles/history hashes, metrics and 10,000 bootstrap draws. It also verifies all 72 ordered prediction-freeze/outcome events. Zero discrepancies at 1e-12 arithmetic tolerance. It uses a separate implementation without project prediction/scoring imports. A separate case audit checks all 230 entries (197 unique player-fixtures), raw source names and conditional outcome/error joins with zero discrepancies.

An explicit replay produces byte-identical formal results, all batch predictions, combined predictions and labels. Target-GW/DGW exclusion, source-known and available cutoffs, class-C rejection, future-truncation invariance, historical identity, NULL semantics and cold starts are covered by focused tests. Cutoff enforcement is relative to the audited class-B snapshot, not an invented official deadline. Capture timestamps remain current backfill times.

All 328 pre-existing fingerprinted files, all twelve pinned implementation dependencies, old feasibility/source/backfill artifacts, and both reference DuckDB files retain their original hashes. No production model, FixtureEnvironment, SDP primary/fallback, optimizer, prospective capture or ledger was changed. Main/default branch remain untouched; no PR, merge, rebase or history rewrite occurred. The separate main checkout retains its untracked `.worktrees/`, `scripts/`, and two `sdp_live_probe_2645215` JSON files; this task leaves them untouched.

| Artifact | SHA256 |
| --- | --- |
| attacking_role_premium_v1.yaml | 08589200d0285309fcfd0ef3620509d06f24c5b422e3dd629428d39657f040b7 |
| attacking_role_premium_v1_population_2026-09-08.json | 1cff23498587cbbaccabad008a490c81dc7c4678f679703809ae296054f13533 |
| attacking_role_premium_v1_development_2026-09-08.json | de2bd6839de4ca246554010cad337445fc30faa9d89d408147d3dce41cec9e08 |
| attacking_role_premium_v1_diagnostics_2026-09-08.json | c0830c2d4420c984aa8bbcc974c7df01c0c652baffa4778a2e7a712c111bc26d |
| attacking_role_premium_v1_cases_2026-09-08.json | 3ddf2f7c7b61862195b2b61ba89bfd8d6f2e54aece44c22dc951a21c18f3c3e4 |
| attacking_role_premium_v1_independent_audit_2026-09-08.json | 2c5774577a918ac6313d3dc2e6df3f37d1879e63434ab883e07edf4deda02297 |
| attacking_role_premium_v1_verification_2026-09-08.json | 3fc72e75e5216753967e6d204426aeb70b94d1b78a1c9f770e62ee65474e9a36 |

Full immutable prediction bytes (100,408,349 bytes) and run receipts are retained outside Git at `D:/Personal/fpl-operations/verification/attacking-role-premium-v1-20260908T080834Z`. Combined prediction SHA256: `c1baa1a24593d4064eb394381431b67ab36aeef9445e226b634a478379afbf7e`; scored labels SHA256: `8adf68b56b9b9f1004bec1a04f1678e50022fddcd070d9324963faa567f1b9f6`. The formal result binds all per-GW hashes. Original claim, execution receipts, preregistration review and independent audit scripts remain there. Independent case-audit SHA256: `35e906719abae43cacb6e625dd01505a61f91029df6443e2518b3ce96c49f54a`.

Commands from the V2 worktree, using `D:/Personal/fpl-operations/.venv/Scripts/python.exe`:

```text
python -m fpl.jobs.evaluate_attacking_role_premium_v1 --output-dir <evidence>/formal-v1
python -m fpl.jobs.evaluate_attacking_role_premium_v1 --replay <evidence>/formal-v1 --output-dir <evidence>/replay-v1
python -m fpl.jobs.evaluate_attacking_role_premium_v1 --diagnostics <evidence>/formal-v1 --output-dir <evidence>/diagnostics-v1
python <evidence>/independent_v1_audit.py --run-dir <evidence>/formal-v1 --config config/attacking_role_premium_v1.yaml --output <evidence>/independent-v1-audit.json
```

The formal claim is already consumed. These commands record what ran; do not issue another formal claim for V1. Verification replays require an untouched new output directory and unchanged scientific provenance.

## Verification status

| Check | Result |
| --- | --- |
| Focused pytest | 90 passed; zero failures/skips |
| Broader regressions | 142 passed; zero failures/skips |
| Repository Ruff | python -m ruff check . - pass |
| Strict mypy | python -m mypy --strict src/fpl - pass, 211 source files |
| Changed Python format | Eight new source/test files pass Ruff format --check |
| Independent full numerical/PIT reconciliation | PASS, zero discrepancies |
| Same-input replay | Byte-identical |
| Frozen files/databases | 328 old files and two DBs unchanged |

Broader tests: `test_point_in_time.py`, `test_historical_player_attacking.py`, `test_historical_player_attacking_backfill.py`, `test_attacking_role_premium_feasibility.py`, and `test_sdp_primary.py`. Focused tests are the four new V1 test files. JUnit paths/hashes and check commands are retained in the verification result.

The full repository suite and global formatting were not rerun. Previously recorded Windows symlink WinError1314 and eleven unrelated global-format failures remain inherited limitations. A writable external pytest basetemp avoids the known default temporary-directory WinError5. Only the scoped checks listed above are verified.

## Exactly one next task

Retain AttackingRolePremiumV1 only as descriptive scouting/dashboard information and do not integrate it into Player Stats prediction. No dashboard or successor modeling implementation is performed in this session.
