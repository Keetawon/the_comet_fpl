# GW1-3 Player Model audit V2 scorecard — 2026-09-08

**Diagnostic verdict: MIXED. Resource decision: NO — FREEZE.** Strict input replay executes the intended incumbent fallback exactly. The retrospective SDP counterfactual slightly improves CRPS and signed-points MAE, but worsens log loss; ranking utility is mixed. These three retrospective model-development GWs do not establish a severe localized component defect justifying repair. Continue the already-planned GW4-8 prospective checkpoint; do not open another feature/research branch or change any model.

This is a **RETROSPECTIVE FROZEN DIAGNOSTIC**, never prospective promotion evidence. Lane A is input-PIT-clean for its reconstructed inputs; model development occurred after these outcomes were observable. Lane B is **RETROSPECTIVE DEVELOPMENT COUNTERFACTUAL** and cannot promote V2. n_GW = 3, irrespective of the number of player rows.

## Immutable identities and serializer repair

| Boundary | Identity |
| --- | --- |
| Starting / original invalid final SHA | c76af405df863b73ee118069da6fd022615f9c93 |
| Unchanged model freeze / Phase A end | 17cfa2267ce4d7c89f96842220f40471b81152d2 |
| Original preregistration | 0a7c7640288ae785003075fbcec1c63772f6e203 |
| Serializer repair | 1e5d93831a2c1564af6349389b6f0c523cd1818e |
| V2 preregistration / formal execution | 602b1c5a8e441025ac9bf02854c52768babbfc55 |
| New audit ID | player_model_gw1_3_20260908_v2 |
| Formal start UTC | 2026-09-08T10:54:54.969976+00:00 |
| All forecasts frozen UTC | 2026-09-08T10:57:46.897161+00:00 |
| Completion UTC | 2026-09-08T10:57:58.338409+00:00 |

Original `player_model_gw1_3_20260908_v1` remains permanently **INVALIDATED_BY_IMPLEMENTATION_BUG**. Its run-start, historical-inputs, invalid-run, both unavailable results, original config/preregistration and INVALID scorecard remain byte-identical. It failed before player inference, forecasts, outcome loading or scoring. The old transport sorted integer keys before JSON converted them to strings, changing 1/2/10 into 1/10/2 on replay. The additive encoder normalizes mapping keys before sorting, rejects collisions such as `{1: "a", "1": "b"}`, recursively normalizes values and rejects unsupported keys/NaN/Infinity. UTF-8, ASCII escaping, compact separators and one trailing LF are fixed. The old encoder remains for V1 reproducibility; write-once publication and byte verification are unchanged.

The [V2 erratum](player-model-gw1-3-preregistration-v2-2026-09-08.md) references the [original frozen contract](player-model-gw1-3-preregistration-2026-09-08.md). Only audit identity, output references and canonical transport changed. The original runner, metrics, historical input values, comparator and scientific rules are unchanged. Exactly one V2 formal invocation ran; no provisional scoring, retuning, new data, inference replay or formal rerun followed it.

## Frozen model and comparator

| Component | Exact operational identity |
| --- | --- |
| assists | team_coupled_xa_share_assists (assist_rate * lambda_team) |
| bonus | hybrid_bps_bonus_match_simulator (exact_bps + fold-local residual) |
| defensive_contribution | trailing_dc_threshold_hit_bernoulli_v1 |
| goals | minutes_gated_coupled_team_share_attacking_goals_v3 (team-coupled) |
| minutes | concentration_adaptive_shrinkage_player_minutes_v3 |
| saves | gk_saves_poisson_from_team_conceded_v1 |
| team_clean_sheet | sdp_v2_with_incumbent_fallback |

The incumbent is the existing recursive shadow: the **same current player components** with `trailing_goals_attack_defence` replacing the team environment. It is not a newly invented older full-player baseline. Both arms share registry, population, schedule, scoring, cutoff, 2,000 draws, base seed 202627 and points support 0..34. Each target GW is a separate one-GW horizon. Attacking=v3, appearance=seasonal, share_signal=auto, assists=coupled. Availability remains the existing separately reported overlay; raw xP/PMFs are scored without multiplying that overlay. Goal/assist shares, BPS residual estimation and the existing prior-history minutes fitting procedure are unchanged. That fixed procedure selected alpha=2, decay=0.7, lambda=0.75 in every fold; there was no audit-driven parameter search. GK H remains shadow-only and was unavailable at these cutoffs. Attacking Usage scouting, OOP, formation and role premiums are absent from inference. No optimizer, production model, FixtureEnvironment or selector changed.

## Historical reconstruction and coverage

| GW | Cutoff UTC | Registry known_at UTC | Forecasts | Scored / unique players | Fixtures | Eligible current-season history rows |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-08-21T17:30:00+00:00 | 2026-08-21T06:41:56+00:00 | 599 | 598 | 10 | 0 |
| 2 | 2026-08-28T17:30:00+00:00 | 2026-08-27T17:19:42+00:00 | 616 | 609 | 10 | 610 |
| 3 | 2026-09-04T17:30:00+00:00 | 2026-09-04T11:05:54.219177+00:00 | 652 | 652 | 10 | 1236 |

All three cutoffs are the frozen official deadline evidence: August 21, August 28 and September 4 at 17:30 UTC. Registry and fixture schedule payload identities are retained in `historical-inputs.json`; its decoded logical content equals V1 exactly. GW1 has no current-season history. GW2 uses the August 26 08:16:56 UTC history capture; GW3 uses September 2 03:22:31.942069 UTC. Twenty pinned CSVs from five prior seasons were ingested in July/August before these cutoffs, suitable as priors for these 2026/27 targets, without claiming historical PIT for the old seasons. Raw/mart reconciliation and pinned source DB hashes pass. Prior target-GW/DGW legs remain excluded as a whole batch. Missing workload stays NULL; no qualifying workload source existed at these deadlines.

| GW | Registry capture | History capture |
| --- | --- | --- |
| 1 | file-858950223a33ab8404ce0fd30f3000c419d30b618dcf5d28f6ed68ceed9ce5f2 | NULL |
| 2 | file-321c1e26c9312efb39ee229e524d7d3a20386ecc59d93befe81e18e3d7a60098 | file-9ae9ec83222c4a58f3dd6b274ee9ffe7d8ce7ad51bb4bf6e488a2ef7d80edf45 |
| 3 | 77b836c9-84c6-4481-b709-8249dce1228d | 0a71ceff-f3fe-4b69-b797-b652c97aeda9 |

All twelve forecasts and their diagnostic sidecars were frozen before the official outcome reader was invoked. Outcomes come from the pinned complete September 8 capture `1bfb3d92-6d5e-48bf-a665-1f489dc6c1da` (known_at 03:37:39.610696 UTC), after exact official-GW/fixture finality and stable player/fixture/club/opponent/position checks. 1,867 forecasts and 1,890 outcome rows yield **1,859 common scored player-fixtures, 652 unique players**. Every scored player-GW has one fixture here, so those grain totals coincide. Eight fixture-side outcomes are missing; 31 outcome identities are outside the frozen forecast population. Neither is silently added or zero-filled. A player observed on another fixture side is not relabelled to match the forecast.

| Excluded forecast GW | Fixture | Stable player code | Reason |
| --- | --- | --- | --- |
| 1 | 7 | 199798 | MISSING_OUTCOME |
| 2 | 11 | 438234 | MISSING_OUTCOME |
| 2 | 11 | 465694 | MISSING_OUTCOME |
| 2 | 16 | 220362 | MISSING_OUTCOME |
| 2 | 16 | 463034 | MISSING_OUTCOME |
| 2 | 16 | 517052 | MISSING_OUTCOME |
| 2 | 17 | 231065 | MISSING_OUTCOME |
| 2 | 20 | 98980 | MISSING_OUTCOME |

## Executed environment selection

| Lane | GW | Selector | Fixtures | Player-fixtures | Fixture IDs |
| --- | --- | --- | --- | --- | --- |
| strict | 1 | SDP_MISSING_FALLBACK | 10 | 599 | 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 |
| strict | 2 | SDP_MISSING_FALLBACK | 10 | 616 | 11, 12, 13, 14, 15, 16, 17, 18, 19, 20 |
| strict | 3 | SDP_MISSING_FALLBACK | 10 | 652 | 21, 22, 23, 24, 25, 26, 27, 28, 29, 30 |
| retrospective_sdp | 1 | SDP_PRIMARY | 10 | 599 | 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 |
| retrospective_sdp | 2 | SDP_INCOMPLETE_FALLBACK | 2 | 132 | 16, 20 |
| retrospective_sdp | 2 | SDP_PRIMARY | 8 | 484 | 11, 12, 13, 14, 15, 17, 18, 19 |
| retrospective_sdp | 3 | SDP_INCOMPLETE_FALLBACK | 5 | 327 | 22, 23, 24, 25, 29 |
| retrospective_sdp | 3 | SDP_PRIMARY | 5 | 325 | 21, 26, 27, 28, 30 |

Strict: all **30 fixtures / 1,867 forecasts** use `SDP_MISSING_FALLBACK`. The SDP model artifact was first known September 7 07:05:48.740385 UTC, after every target cutoff. Executed current/incumbent player records and component bytes are identical; all 1,859 scored PMFs, xP, expected bonus, component inputs and losses agree exactly. Provenance envelopes correctly differ in selection/execution metadata, so whole JSONL files are not claimed identical.

Counterfactual: 23 SDP-primary fixtures / 1,408 forecasts and seven incomplete-fallback fixtures / 459 forecasts. The scored subsets are 1,404 primary and 455 fallback rows. All fallback player records/components remain byte-identical to incumbent. Missing `ontargetScoringAtt` in required prior source matches 7, then 7/19/20, causes the retained fail-closed cases. No weakened health or identity gate revives an older valid row. This lane uses the frozen actual evidence frontier September 8 09:53:00.642943 UTC and waives historical SDP/model availability only. Actual source timestamps remain truthful; target and future matches cannot enter features. The SDP model training frontier is 2025/26 GW38. This availability waiver is why Lane B is explanatory only.

## Total-points scorecard

Lower CRPS, log loss and MAE are better. Bias = predicted minus observed. Spearman is the frozen within-GW signed-points rank statistic. Proper scores use the composer's coarsened 0..34 points support; signed official points remain intact for MAE/bias/ranking. Seven negative official observations are coarsened to zero for proper scores only; none exceed 34. Existing Monte Carlo PMFs have seven zero-target bins in strict/incumbent and eight in Lane B; log loss uses the frozen 1e-12 floor. This tail sensitivity is disclosed, not repaired by changing draws or support.

### Lane A strict

| GW | Arm | Rows | CRPS | Log loss | xP MAE | Bias | Spearman |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | current | 598 | 1.107243 | 1.690868 | 1.677718 | 0.032748 | 0.443052 |
| 1 | incumbent | 598 | 1.107243 | 1.690868 | 1.677718 | 0.032748 | 0.443052 |
| 2 | current | 609 | 0.967984 | 1.596508 | 1.517419 | 0.137210 | 0.478306 |
| 2 | incumbent | 609 | 0.967984 | 1.596508 | 1.517419 | 0.137210 | 0.478306 |
| 3 | current | 652 | 0.944363 | 1.532810 | 1.481857 | 0.130533 | 0.467406 |
| 3 | incumbent | 652 | 0.944363 | 1.532810 | 1.481857 | 0.130533 | 0.467406 |
| Pooled | current | 1859 | 1.004496 | 1.604521 | 1.556511 | 0.101265 | 0.462921 |
| Pooled | incumbent | 1859 | 1.004496 | 1.604521 | 1.556511 | 0.101265 | 0.462921 |

### Lane B retrospective counterfactual

| GW | Arm | Rows | CRPS | Log loss | xP MAE | Bias | Spearman |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | current | 598 | 1.097894 | 1.721828 | 1.660947 | 0.022258 | 0.449425 |
| 1 | incumbent | 598 | 1.107243 | 1.690868 | 1.677718 | 0.032748 | 0.443052 |
| 2 | current | 609 | 0.966707 | 1.598460 | 1.513217 | 0.130222 | 0.479094 |
| 2 | incumbent | 609 | 0.967984 | 1.596508 | 1.517419 | 0.137210 | 0.478306 |
| 3 | current | 652 | 0.943338 | 1.535322 | 1.479922 | 0.120816 | 0.469110 |
| 3 | incumbent | 652 | 0.944363 | 1.532810 | 1.481857 | 0.130533 | 0.467406 |
| Pooled | current | 1859 | 1.000711 | 1.616001 | 1.549061 | 0.092193 | 0.465876 |
| Pooled | incumbent | 1859 | 1.004496 | 1.604521 | 1.556511 | 0.101265 | 0.462921 |

Strict improvements are exactly zero in all three GWs. Counterfactual CRPS and MAE improve in all three; log loss worsens in all three. Pooled relative CRPS improvement is **0.376829%**, MAE improvement **0.478633%**, and log-loss regression **0.715443%**. These disagreement patterns and strict equality imply the original frozen **MIXED** verdict.

| Scope / metric | Current mean | Incumbent mean | Difference current - incumbent |
| --- | --- | --- | --- |
| FALLBACK / crps | 0.963185 | 0.963185 | 0.000000 |
| FALLBACK / log_score | 1.594722 | 1.594722 | 0.000000 |
| FALLBACK / signed_absolute_error | 1.534565 | 1.534565 | 0.000000 |
| SDP_PRIMARY / crps | 1.012872 | 1.017884 | -0.005012 |
| SDP_PRIMARY / log_score | 1.622896 | 1.607697 | 0.015200 |
| SDP_PRIMARY / signed_absolute_error | 1.553759 | 1.563623 | -0.009864 |

| Counterfactual paired loss | GW-block descriptive 95% lower | Upper |
| --- | --- | --- |
| crps | -0.007579 | -0.001077 |
| log_score | 0.002079 | 0.024598 |
| signed_absolute_error | -0.014014 | -0.002404 |

Intervals enumerate the preregistered 27 ordered three-GW block resamples; they are descriptive with only three independent temporal blocks. All strict intervals are [0, 0]. They cannot establish prospective or strong temporal validation.

## Position and evidence slices

| Position | Rows | Strict/inc CRPS | Lane B CRPS | Strict/inc MAE | Lane B MAE | Strict/inc bias | Lane B bias | Strict/inc Spearman | Lane B Spearman | Strict/inc log | Lane B log |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GK | 205 | 0.647667 | 0.642681 | 1.154998 | 1.145888 | 0.296183 | 0.281259 | 0.549170 | 0.552395 | 0.988615 | 0.984069 |
| DEF | 614 | 1.132626 | 1.126907 | 1.737087 | 1.728257 | 0.034638 | 0.026407 | 0.423981 | 0.422854 | 1.624069 | 1.625841 |
| MID | 820 | 1.023507 | 1.021856 | 1.536884 | 1.530635 | 0.051379 | 0.040852 | 0.448927 | 0.452647 | 1.761687 | 1.787210 |
| FWD | 220 | 0.908538 | 0.903316 | 1.499834 | 1.493305 | 0.291530 | 0.290986 | 0.461524 | 0.475189 | 1.538077 | 1.539238 |

DEF has the highest CRPS/MAE; MID the highest log loss. FWD and GK show the largest positive points biases. Counterfactual CRPS improves in all positions, but DEF ranking slightly declines and MID log loss worsens most. Full position/GW/calibration/evidence slices remain in both immutable JSON results.

| Evidence slice | Value | Rows | Strict/inc CRPS | Lane B CRPS | Strict/inc bias | Lane B bias |
| --- | --- | --- | --- | --- | --- | --- |
| cold_start | False | 1458 | 1.016537 | 1.012136 | 0.182933 | 0.166353 |
| cold_start | True | 401 | 0.960718 | 0.959171 | -0.195671 | -0.177443 |
| transfer | False | 1702 | 0.997185 | 0.993198 | 0.074533 | 0.065198 |
| transfer | True | 157 | 1.083757 | 1.082152 | 0.391067 | 0.384847 |
| promoted | False | 1540 | 1.020765 | 1.016458 | 0.155276 | 0.134222 |
| promoted | True | 319 | 0.925957 | 0.924692 | -0.159478 | -0.110702 |
| venue | away | 940 | 0.924820 | 0.920780 | 0.126219 | 0.113706 |
| venue | home | 919 | 1.085993 | 1.082468 | 0.075742 | 0.070189 |

## Component scorecard and calibration

Count distributions are the existing appearance-gated marginals. Bonus has an expectation and P(any), not a stored full bonus PMF. DC has a fantasy-award probability, not a raw-action distribution. Team CS is deduplicated to 60 club-fixture sides and remains the opponent goal-PMF mass at zero. No independent ad-hoc CS model was introduced.

| Component | Rows | Strict/inc expected | Lane B expected | Observed | Strict/inc MAE | Lane B MAE | Strict/inc CRPS | Lane B CRPS | Strict/inc log | Lane B log |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| assists | 1859 | 0.042483 | 0.041963 | 0.041958 | 0.076616 | 0.076351 | 0.039745 | 0.039666 | 0.163972 | 0.164037 |
| bonus | 1859 | 0.102890 | 0.102936 | 0.103819 | 0.179372 | 0.179600 | NULL | NULL | NULL | NULL |
| goals | 1859 | 0.046861 | 0.046289 | 0.043034 | 0.079584 | 0.079225 | 0.040201 | 0.040031 | 0.163648 | 0.163499 |
| minutes_scoring_proxy | 1859 | 39.597037 | 39.597037 | 31.563206 | 28.000672 | 28.000672 | NULL | NULL | NULL | NULL |
| saves | 205 | 1.016093 | 1.007436 | 0.790244 | 0.965465 | 0.936038 | 0.574834 | 0.556173 | 0.970139 | 0.961580 |

| Event | Rows | Strict/inc probability | Lane B probability | Observed rate | Strict/inc Brier | Lane B Brier |
| --- | --- | --- | --- | --- | --- | --- |
| any_bonus | 1859 | 0.051314 | 0.051330 | 0.050027 | 0.044893 | 0.044670 |
| appearance | 1859 | 0.495925 | 0.495925 | 0.492200 | 0.202856 | 0.202856 |
| assists_any | 1859 | 0.038874 | 0.038572 | 0.038193 | 0.035946 | 0.035893 |
| dc_award | 1654 | 0.066109 | 0.066109 | 0.057437 | 0.050280 | 0.050280 |
| goals_any | 1859 | 0.042128 | 0.041829 | 0.039268 | 0.036463 | 0.036319 |
| minutes_60_plus | 1859 | 0.336640 | 0.336640 | 0.337278 | 0.177891 | 0.177891 |
| player_60plus_clean_sheet | 1859 | 0.093441 | 0.091100 | 0.101668 | 0.088459 | 0.087893 |
| saves_any | 205 | 0.318289 | 0.321336 | 0.258537 | 0.142949 | 0.142029 |
| team_clean_sheet | 60 | 0.255206 | 0.247981 | 0.266667 | 0.192812 | 0.188405 |

The minutes number is explicitly a **scoring-bin proxy**, using representatives 0/59/89/90, not a physical expected-minutes forecast. Its MAE 28.000672 and bias +8.033831 must not be interpreted as proof of an eight-minute model bias. Actual starting probability is unavailable; 656 starts are observed but no start-model Brier is invented. P(any) and P60 pooled means are close to observed rates, with concerning calibration shape: P(any) in [0.8,0.9) averages 0.851962 versus 0.640449 observed (267 rows); P60 in [0.8,0.9) averages 0.845171 versus 0.675439 (114 rows). Frozen false-nailed diagnostic: 38/155 at P60 >=0.8; missed starters: 24/365 at P(any) <0.2. These warrant monitoring, not a new fitted minutes mechanism.

| Position | Rows | Minutes proxy MAE | Minutes proxy bias | False nailed count / eligible | Missed starters count / eligible |
| --- | --- | --- | --- | --- | --- |
| DEF | 614 | 29.181969 | 2.809853 | 16/60 | 4/109 |
| FWD | 220 | 30.502069 | 16.135077 | 0/3 | 1/29 |
| GK | 205 | 19.474032 | 4.792159 | 10/50 | 6/98 |
| MID | 820 | 28.576694 | 10.582356 | 12/42 | 13/129 |

Minutes/evidence slices below use the same unchanged model in both lanes. Zero-minute errors are represented by appearance calibration and false-nailed cases; the frozen scorer has no separate physical-minute DNP MAE, so that metric is NULL.

| Evidence slice | Value | Rows | Minutes proxy MAE | P(any) predicted | P(any) observed | P60 predicted | P60 observed |
| --- | --- | --- | --- | --- | --- | --- | --- |
| cold_start | False | 1458 | 27.689088 | 0.535413 | 0.497942 | 0.364016 | 0.358025 |
| cold_start | True | 401 | 29.133565 | 0.352352 | 0.471322 | 0.237102 | 0.261845 |
| cold_start | UNAVAILABLE | 0 | NULL | NULL | NULL | NULL | NULL |
| promoted | False | 1540 | 27.363630 | 0.524305 | 0.503896 | 0.356413 | 0.347403 |
| promoted | True | 319 | 31.076049 | 0.358918 | 0.435737 | 0.241187 | 0.288401 |
| promoted | UNAVAILABLE | 0 | NULL | NULL | NULL | NULL | NULL |
| transfer | False | 1702 | 27.034866 | 0.489014 | 0.480024 | 0.328866 | 0.330200 |
| transfer | True | 157 | 38.470747 | 0.570850 | 0.624204 | 0.420916 | 0.414013 |
| transfer | UNAVAILABLE | 0 | NULL | NULL | NULL | NULL | NULL |

Goals are mildly overpredicted in aggregate; assists and bonus totals are close. GK save counts are overpredicted, but their appearance gating prevents attribution to the save-rate component alone. MID DC awards are overpredicted in this small sample. None establishes a localized severe defect. Raw BPS outcomes and fold-local residual parameters are retained in forensic details, but no separately valid raw-BPS PMF score exists. Goals-conceded point residuals are retained; a separate player goals-conceded distribution score was not defined by the frozen scorer and remains NULL. Cards, penalties, own goals, player shots/xG/xA, raw DC-action PMF and full bonus PMF metrics remain unavailable, not zero.

| Position / event | Rows | Strict/inc probability | Lane B probability | Observed | Strict/inc Brier | Lane B Brier |
| --- | --- | --- | --- | --- | --- | --- |
| GK / any_bonus | 205 | 0.042751 | 0.042420 | 0.024390 | 0.026755 | 0.026210 |
| GK / appearance | 205 | 0.342699 | 0.342699 | 0.287805 | 0.127945 | 0.127945 |
| GK / assists_any | 205 | 0.006710 | 0.006645 | 0.000000 | 0.000305 | 0.000286 |
| GK / dc_award | 0 | NULL | NULL | NULL | NULL | NULL |
| GK / goals_any | 205 | 0.006030 | 0.005967 | 0.000000 | 0.000305 | 0.000287 |
| GK / minutes_60_plus | 205 | 0.338007 | 0.338007 | 0.287805 | 0.125629 | 0.125629 |
| GK / player_60plus_clean_sheet | 205 | 0.087154 | 0.084310 | 0.078049 | 0.064477 | 0.063238 |
| GK / saves_any | 205 | 0.318289 | 0.321336 | 0.258537 | 0.142949 | 0.142029 |
| DEF / any_bonus | 614 | 0.046417 | 0.046271 | 0.050489 | 0.046207 | 0.046123 |
| DEF / appearance | 614 | 0.493084 | 0.493084 | 0.532573 | 0.205291 | 0.205291 |
| DEF / assists_any | 614 | 0.033046 | 0.033028 | 0.024430 | 0.023416 | 0.023415 |
| DEF / dc_award | 614 | 0.099481 | 0.099481 | 0.105863 | 0.089120 | 0.089120 |
| DEF / goals_any | 614 | 0.028031 | 0.027984 | 0.021173 | 0.021697 | 0.021631 |
| DEF / minutes_60_plus | 614 | 0.377258 | 0.377258 | 0.408795 | 0.189768 | 0.189768 |
| DEF / player_60plus_clean_sheet | 614 | 0.100502 | 0.097923 | 0.114007 | 0.099584 | 0.098899 |
| DEF / saves_any | 0 | NULL | NULL | NULL | NULL | NULL |
| MID / any_bonus | 820 | 0.049434 | 0.049462 | 0.054878 | 0.047274 | 0.047070 |
| MID / appearance | 820 | 0.524418 | 0.524418 | 0.521951 | 0.217633 | 0.217633 |
| MID / assists_any | 820 | 0.053504 | 0.052924 | 0.052439 | 0.049397 | 0.049326 |
| MID / dc_award | 820 | 0.058293 | 0.058293 | 0.036585 | 0.034684 | 0.034684 |
| MID / goals_any | 820 | 0.046600 | 0.045835 | 0.053659 | 0.048804 | 0.048676 |
| MID / minutes_60_plus | 820 | 0.319826 | 0.319826 | 0.320732 | 0.187369 | 0.187369 |
| MID / player_60plus_clean_sheet | 820 | 0.093528 | 0.090992 | 0.103659 | 0.090270 | 0.090012 |
| MID / saves_any | 0 | NULL | NULL | NULL | NULL | NULL |
| FWD / any_bonus | 220 | 0.079970 | 0.080714 | 0.054545 | 0.049250 | 0.048872 |
| FWD / appearance | 220 | 0.540433 | 0.540433 | 0.459091 | 0.210784 | 0.210784 |
| FWD / assists_any | 220 | 0.030579 | 0.030299 | 0.059091 | 0.053993 | 0.053832 |
| FWD / dc_award | 220 | 0.002106 | 0.002106 | 0.000000 | 0.000005 | 0.000005 |
| FWD / goals_any | 220 | 0.098437 | 0.098957 | 0.072727 | 0.065367 | 0.064833 |
| FWD / minutes_60_plus | 220 | 0.284675 | 0.284675 | 0.245455 | 0.158118 | 0.158118 |
| FWD / player_60plus_clean_sheet | 220 | 0.079270 | 0.078783 | 0.081818 | 0.073010 | 0.072254 |
| FWD / saves_any | 0 | NULL | NULL | NULL | NULL | NULL |

| Points event | Strict/inc predicted | Lane B predicted | Observed | Strict/inc Brier | Lane B Brier |
| --- | --- | --- | --- | --- | --- |
| blank_le2 | 0.804160 | 0.805327 | 0.820871 | 0.134335 | 0.133677 |
| points_ge10 | 0.019700 | 0.019207 | 0.024744 | 0.023433 | 0.023343 |
| points_ge5 | 0.110227 | 0.108934 | 0.108123 | 0.090779 | 0.090190 |

All stored PMFs validate. Aggregate blank/5+/10+ rates are reasonably close, though higher-probability buckets and rare tails have visible miscalibration. Seven/eight zero-sample target bins show the finite 2,000-draw tail limitation. This is usable diagnostic output with weaknesses, not evidence of impossible distributions or comprehensive calibration approval.

## Top-K and captain diagnostics

Selections rank frozen raw xP on the common scored population, with stable-code ties. They are descriptive rankings, not optimizer reruns. The exact code lists, actual-top lists and overlaps are in the immutable result. Strict current = incumbent; Lane B incumbent also has these same scores. Hindsight regret is never a fitting objective.

| GW | Arm | Top K | Mean realized | Median | Hit >=5 | Hit >=10 | Actual top-K overlap |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Strict/inc | 10 | 2.800000 | 2.000000 | 0.200000 | 0.000000 | 0/10 |
| 1 | Strict/inc | 25 | 3.640000 | 2 | 0.280000 | 0.120000 | 4/25 |
| 1 | Strict/inc | 50 | 3.060000 | 2.000000 | 0.240000 | 0.060000 | 11/50 |
| 2 | Strict/inc | 10 | 6.800000 | 4.000000 | 0.400000 | 0.300000 | 3/10 |
| 2 | Strict/inc | 25 | 4.720000 | 2 | 0.280000 | 0.200000 | 6/25 |
| 2 | Strict/inc | 50 | 4.240000 | 2.500000 | 0.320000 | 0.140000 | 14/50 |
| 3 | Strict/inc | 10 | 4.200000 | 3.000000 | 0.400000 | 0.100000 | 1/10 |
| 3 | Strict/inc | 25 | 3.000000 | 2 | 0.240000 | 0.040000 | 4/25 |
| 3 | Strict/inc | 50 | 2.800000 | 2.000000 | 0.200000 | 0.040000 | 10/50 |
| 1 | Lane B current | 10 | 2.800000 | 2.000000 | 0.200000 | 0.000000 | 0/10 |
| 1 | Lane B current | 25 | 3.160000 | 2 | 0.240000 | 0.040000 | 3/25 |
| 1 | Lane B current | 50 | 3.680000 | 2.000000 | 0.340000 | 0.060000 | 14/50 |
| 2 | Lane B current | 10 | 7.500000 | 4.000000 | 0.400000 | 0.400000 | 4/10 |
| 2 | Lane B current | 25 | 4.920000 | 2 | 0.320000 | 0.200000 | 7/25 |
| 2 | Lane B current | 50 | 4.240000 | 2.000000 | 0.320000 | 0.140000 | 14/50 |
| 3 | Lane B current | 10 | 3.300000 | 2.500000 | 0.300000 | 0.000000 | 0/10 |
| 3 | Lane B current | 25 | 3.240000 | 2 | 0.280000 | 0.040000 | 4/25 |
| 3 | Lane B current | 50 | 2.720000 | 2.000000 | 0.200000 | 0.040000 | 10/50 |

| GW | Arm | Top K | Selected players: actual points | Mean realized | Hindsight regret total |
| --- | --- | --- | --- | --- | --- |
| 1 | Strict/inc | 1 | Haaland (223094): 2 | 2.000000 | 15 |
| 1 | Strict/inc | 3 | Haaland (223094): 2; Gibbs-White (222531): 2; O'Reilly (472769): 2 | 2.000000 | 42 |
| 1 | Strict/inc | 5 | Haaland (223094): 2; Gibbs-White (222531): 2; O'Reilly (472769): 2; Szoboszlai (424876): 8; Mbeumo (446008): 2 | 3.200000 | 60 |
| 2 | Strict/inc | 1 | Mbeumo (446008): 11 | 11.000000 | 12 |
| 2 | Strict/inc | 3 | Mbeumo (446008): 11; Szoboszlai (424876): 4; Virgil (97032): 1 | 5.333333 | 34 |
| 2 | Strict/inc | 5 | Mbeumo (446008): 11; Szoboszlai (424876): 4; Virgil (97032): 1; B.Fernandes (141746): 23; Haaland (223094): 13 | 10.400000 | 24 |
| 3 | Strict/inc | 1 | Szoboszlai (424876): 3 | 3.000000 | 12 |
| 3 | Strict/inc | 3 | Szoboszlai (424876): 3; Virgil (97032): 6; Haaland (223094): 9 | 6.000000 | 24 |
| 3 | Strict/inc | 5 | Szoboszlai (424876): 3; Virgil (97032): 6; Haaland (223094): 9; Gibbs-White (222531): 3; O'Reilly (472769): 0 | 4.200000 | 45 |
| 1 | Lane B current | 1 | Gibbs-White (222531): 2 | 2.000000 | 15 |
| 1 | Lane B current | 3 | Gibbs-White (222531): 2; Haaland (223094): 2; Mbeumo (446008): 2 | 2.000000 | 42 |
| 1 | Lane B current | 5 | Gibbs-White (222531): 2; Haaland (223094): 2; Mbeumo (446008): 2; O'Reilly (472769): 2; Szoboszlai (424876): 8 | 3.200000 | 60 |
| 2 | Lane B current | 1 | Mbeumo (446008): 11 | 11.000000 | 12 |
| 2 | Lane B current | 3 | Mbeumo (446008): 11; Szoboszlai (424876): 4; Virgil (97032): 1 | 5.333333 | 34 |
| 2 | Lane B current | 5 | Mbeumo (446008): 11; Szoboszlai (424876): 4; Virgil (97032): 1; B.Fernandes (141746): 23; E.Le Fée (484420): 3 | 8.400000 | 34 |
| 3 | Lane B current | 1 | Szoboszlai (424876): 3 | 3.000000 | 12 |
| 3 | Lane B current | 3 | Szoboszlai (424876): 3; Gibbs-White (222531): 3; Haaland (223094): 9 | 5.000000 | 27 |
| 3 | Lane B current | 5 | Szoboszlai (424876): 3; Gibbs-White (222531): 3; Haaland (223094): 9; Mbeumo (446008): 8; Virgil (97032): 6 | 5.800000 | 37 |

Top-1 actual points are 2/11/3 in both lanes; regrets 15/12/12. Counterfactual top-10 means are 2.8/7.5/3.3 versus incumbent 2.8/6.8/4.2. Ranking changes do not produce consistent decision gains. All captain points are raw, before a captain multiplier. For K=3/5 the frozen field is total shortlist regret against the actual top-K sum, not three/five independent captain decisions.

## Frozen top-25 forensic misses

The preregistered classifier chooses the largest absolute analytic point residual. Categories are noncausal: a GOALS label identifies a scoring residual and does not prove that minutes, role or ability estimation played no part. Owner categories A/J remain available; no manual reassignment after inspecting names is performed. CLEAN_SHEET and GOALS_CONCEDED map to D; GOALS to B, ASSISTS to C, MINUTES to A, SAVES to E, DC to F, BONUS to G, MULTIPLE to I, unexplained remainder to J. Availability is retained as context, not inferred as causal H.

### Strict/current = incumbent

Counts: {'GOALS': 19, 'ASSISTS': 1, 'CLEAN_SHEET': 5}. Top-25 absolute error sum: 270.953500 points. MINUTES-labelled share: 0.000000 points (0.0%). That zero is a classification result, not proof that minutes contribute zero error; a causal minutes share is unavailable.

| GW | Player / stable code | Position | Fixture | xP | Actual | Absolute error | Largest residual category | Minutes proxy / actual | Goals expected / actual | Assists expected / actual | Availability |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2 | B.Fernandes / 141746 | MID | 18 | 5.884500 | 23 | 17.115500 | GOALS | 78.81/90 | 0.0875/3 | 0.7042/1 | a / 1.0 |
| 1 | De Cuyper / 465730 | DEF | 7 | 2.971500 | 17 | 14.028500 | GOALS | 61.85/77 | 0.0184/1 | 0.3174/1 | a / 1.0 |
| 1 | Mendy / 606930 | DEF | 4 | 1.343000 | 15 | 13.657000 | GOALS | 26.26/63 | 0.0464/1 | 0.0420/0 | a / 1.0 |
| 1 | Sangaré / 513545 | MID | 2 | 0.808500 | 14 | 13.191500 | ASSISTS | 22.19/75 | 0.0269/0 | 0.0267/2 | a / 1.0 |
| 1 | Ajayi / 146426 | DEF | 4 | 1.288000 | 14 | 12.712000 | GOALS | 26.26/63 | 0.0464/1 | 0.0420/0 | a / 1.0 |
| 3 | Vuskovic / 610799 | DEF | 23 | 0.036000 | 12 | 11.964000 | GOALS | 1.20/90 | 0.0022/1 | 0.0015/0 | a / 1.0 |
| 3 | Mitchell / 244723 | DEF | 24 | 3.121500 | 15 | 11.878500 | GOALS | 77.01/73 | 0.0658/2 | 0.0445/0 | a / 1.0 |
| 1 | Hinshelwood / 532529 | MID | 7 | 4.122000 | 16 | 11.878000 | GOALS | 65.71/63 | 0.3492/2 | 0.0679/0 | a / 1.0 |
| 3 | Isak / 219168 | FWD | 21 | 1.158000 | 13 | 11.842000 | GOALS | 31.84/63 | 0.0983/2 | 0.0026/0 | a / 1.0 |
| 3 | Bogle / 226182 | DEF | 23 | 2.265000 | 14 | 11.735000 | GOALS | 66.93/60 | 0.0039/1 | 0.2033/0 | a / 1.0 |
| 2 | Cherki / 466052 | MID | 11 | 2.648500 | 14 | 11.351500 | GOALS | 61.39/81 | 0.0912/2 | 0.1548/0 | a / 1.0 |
| 1 | Stach / 466525 | MID | 6 | 2.492000 | 13 | 10.508000 | GOALS | 61.95/90 | 0.0683/1 | 0.0694/0 | a / 1.0 |
| 2 | Dedić / 463726 | DEF | 15 | 0.996500 | 11 | 10.003500 | CLEAN_SHEET | 25.24/90 | 0.0309/0 | 0.0306/1 | a / 1.0 |
| 1 | Kayode / 607464 | DEF | 2 | 3.193000 | 13 | 9.807000 | GOALS | 83.45/75 | 0.1029/1 | 0.0437/0 | a / 1.0 |
| 1 | White / 198869 | DEF | 1 | 1.363000 | 11 | 9.637000 | CLEAN_SHEET | 33.94/90 | 0.0020/0 | 0.0255/1 | a / 1.0 |
| 1 | Palmer / 244851 | MID | 10 | 3.452000 | 13 | 9.548000 | GOALS | 60.96/82 | 0.2328/1 | 0.0591/1 | a / 1.0 |
| 2 | Groß / 60307 | MID | 16 | 3.468000 | 13 | 9.532000 | GOALS | 83.57/90 | 0.0923/1 | 0.1622/1 | a / 1.0 |
| 3 | Janelt / 204580 | MID | 22 | 1.569000 | 11 | 9.431000 | GOALS | 52.21/90 | 0.0077/1 | 0.0679/0 | a / 1.0 |
| 2 | Gibbs-White / 222531 | MID | 14 | 4.087500 | 13 | 8.912500 | GOALS | 74.14/90 | 0.2827/1 | 0.1466/1 | d / 0.75 |
| 1 | Ødegaard / 184029 | MID | 1 | 2.130500 | 11 | 8.869500 | GOALS | 50.87/75 | 0.0371/1 | 0.1478/0 | a / 1.0 |
| 2 | Hall / 487838 | DEF | 15 | 2.133000 | 11 | 8.867000 | CLEAN_SHEET | 64.98/90 | 0.0279/0 | 0.0620/0 | a / 1.0 |
| 3 | George / 550615 | MID | 30 | 1.139500 | 10 | 8.860500 | GOALS | 34.19/90 | 0.0098/1 | 0.1267/0 | a / 1.0 |
| 3 | Barnes / 201666 | MID | 27 | 3.207500 | 12 | 8.792500 | GOALS | 66.42/90 | 0.1932/1 | 0.1806/1 | a / 1.0 |
| 2 | Calafiori / 466075 | DEF | 20 | 2.584000 | 11 | 8.416000 | CLEAN_SHEET | 55.37/90 | 0.0771/0 | 0.0611/1 | a / 1.0 |
| 1 | Trafford / 432720 | GK | 6 | 0.584500 | 9 | 8.415500 | CLEAN_SHEET | 18.90/90 | 0.0000/0 | 0.0000/0 | a / 1.0 |

### Counterfactual current

Counts: {'GOALS': 20, 'ASSISTS': 1, 'CLEAN_SHEET': 4}. Top-25 absolute error sum: 271.260000 points. MINUTES-labelled share: 0.000000 points (0.0%). That zero is a classification result, not proof that minutes contribute zero error; a causal minutes share is unavailable.

| GW | Player / stable code | Position | Fixture | xP | Actual | Absolute error | Largest residual category | Minutes proxy / actual | Goals expected / actual | Assists expected / actual | Availability |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2 | B.Fernandes / 141746 | MID | 18 | 5.478000 | 23 | 17.522000 | GOALS | 78.81/90 | 0.0755/3 | 0.6072/1 | a / 1.0 |
| 1 | De Cuyper / 465730 | DEF | 7 | 3.034500 | 17 | 13.965500 | GOALS | 61.85/77 | 0.0185/1 | 0.3200/1 | a / 1.0 |
| 1 | Mendy / 606930 | DEF | 4 | 1.376000 | 15 | 13.624000 | GOALS | 26.26/63 | 0.0474/1 | 0.0429/0 | a / 1.0 |
| 1 | Sangaré / 513545 | MID | 2 | 0.810000 | 14 | 13.190000 | ASSISTS | 22.19/75 | 0.0250/0 | 0.0247/2 | a / 1.0 |
| 1 | Ajayi / 146426 | DEF | 4 | 1.322000 | 14 | 12.678000 | GOALS | 26.26/63 | 0.0474/1 | 0.0429/0 | a / 1.0 |
| 3 | Isak / 219168 | FWD | 21 | 1.023500 | 13 | 11.976500 | GOALS | 31.84/63 | 0.0738/2 | 0.0019/0 | a / 1.0 |
| 3 | Vuskovic / 610799 | DEF | 23 | 0.036000 | 12 | 11.964000 | GOALS | 1.20/90 | 0.0022/1 | 0.0015/0 | a / 1.0 |
| 3 | Mitchell / 244723 | DEF | 24 | 3.121500 | 15 | 11.878500 | GOALS | 77.01/73 | 0.0658/2 | 0.0445/0 | a / 1.0 |
| 1 | Hinshelwood / 532529 | MID | 7 | 4.148000 | 16 | 11.852000 | GOALS | 65.71/63 | 0.3520/2 | 0.0684/0 | a / 1.0 |
| 3 | Bogle / 226182 | DEF | 23 | 2.265000 | 14 | 11.735000 | GOALS | 66.93/60 | 0.0039/1 | 0.2033/0 | a / 1.0 |
| 2 | Cherki / 466052 | MID | 11 | 2.576500 | 14 | 11.423500 | GOALS | 61.39/81 | 0.0865/2 | 0.1469/0 | a / 1.0 |
| 1 | Stach / 466525 | MID | 6 | 2.520500 | 13 | 10.479500 | GOALS | 61.95/90 | 0.0707/1 | 0.0719/0 | a / 1.0 |
| 2 | Dedić / 463726 | DEF | 15 | 0.988000 | 11 | 10.012000 | CLEAN_SHEET | 25.24/90 | 0.0279/0 | 0.0276/1 | a / 1.0 |
| 1 | White / 198869 | DEF | 1 | 1.250000 | 11 | 9.750000 | CLEAN_SHEET | 33.94/90 | 0.0017/0 | 0.0221/1 | a / 1.0 |
| 1 | Palmer / 244851 | MID | 10 | 3.292000 | 13 | 9.708000 | GOALS | 60.96/82 | 0.2175/1 | 0.0552/1 | a / 1.0 |
| 1 | Kayode / 607464 | DEF | 2 | 3.422500 | 13 | 9.577500 | GOALS | 83.45/75 | 0.0955/1 | 0.0406/0 | a / 1.0 |
| 2 | Groß / 60307 | MID | 16 | 3.468000 | 13 | 9.532000 | GOALS | 83.57/90 | 0.0923/1 | 0.1622/1 | a / 1.0 |
| 3 | Janelt / 204580 | MID | 22 | 1.569000 | 11 | 9.431000 | GOALS | 52.21/90 | 0.0077/1 | 0.0679/0 | a / 1.0 |
| 3 | Barnes / 201666 | MID | 27 | 2.877000 | 12 | 9.123000 | GOALS | 66.42/90 | 0.1643/1 | 0.1536/1 | a / 1.0 |
| 1 | Ødegaard / 184029 | MID | 1 | 2.011500 | 11 | 8.988500 | GOALS | 50.87/75 | 0.0322/1 | 0.1280/0 | a / 1.0 |
| 2 | Hall / 487838 | DEF | 15 | 2.142000 | 11 | 8.858000 | CLEAN_SHEET | 64.98/90 | 0.0251/0 | 0.0559/0 | a / 1.0 |
| 3 | George / 550615 | MID | 30 | 1.242000 | 10 | 8.758000 | GOALS | 34.19/90 | 0.0121/1 | 0.1558/0 | a / 1.0 |
| 2 | Calafiori / 466075 | DEF | 20 | 2.584000 | 11 | 8.416000 | CLEAN_SHEET | 55.37/90 | 0.0771/0 | 0.0611/1 | a / 1.0 |
| 2 | Gibbs-White / 222531 | MID | 14 | 4.589500 | 13 | 8.410500 | GOALS | 74.14/90 | 0.3356/1 | 0.1740/1 | d / 0.75 |
| 2 | Ndoye / 456512 | MID | 14 | 0.593000 | 9 | 8.407000 | GOALS | 28.72/65 | 0.0038/1 | 0.0012/0 | a / 1.0 |

Full per-miss goal/assist/CS/conceded/save/DC/bonus residuals, team/opponent PMFs, BPS, availability, actual minutes and stable identities are retained in each result JSON. The largest strict miss is B.Fernandes GW2: 5.8845 xP versus 23, dominated by three goals. Goal-event residuals dominate 19/25 strict cases and 20/25 counterfactual cases. There is no post-result model change or named-player tuning.

## Verification, limitations and delivery

165 serializer/identity/original-audit/source/replay/metric tests passed, and 164 production/component/SDP/scouting regression tests passed. The earlier serializer-only 19-test group also passed and overlaps the combined group. Ruff `check src tests` passed. Strict mypy over all source plus both new tests passed (224 files). Changed-file formatting passed for four Python files. The production/scouting regression proves unchanged forecast and optimizer output; source/config hashes additionally prove this repair does not touch those paths. No formal forecasts were rerun for testing.

Post-run checks: all 12 forecast JSONL artifacts validate and reproduce byte-for-byte through the existing reader/writer; all 24 forecast/sidecar hashes match the pre-outcome freeze; all 19 JSON receipts/diagnostics/results round-trip under the corrected canonical encoder. This is transport replay, not another inference or scoring run. All 339 original model/science/config pins and all eight original audit implementation pins remain unchanged. Original V1 receipt/result/report hashes, source DB hash and the descriptive Phase A scouting files remain unchanged. Frozen AttackingRolePremiumV1 remains **REFUTED**. Existing SDP owner-directed adoption and all frozen scientific verdicts are unchanged.

Independent read-only reconciliation additionally checked 562 referenced raw payloads and 548 distinct source-provenance versions against retained hashes, HTTP status, byte counts, fetched_at and known_at. All contributing matches precede target cutoffs and target GWs remain excluded. Lane B truthfully retains later-known source versions. Strict GW3 has some eligible source records, but the SDP model artifact itself is still unavailable, so fallback is required. Incumbent forecast artifact bytes also agree across both lanes for each GW. Independent review performed no inference or scoring.

Inherited limitations were not repeatedly rerun: four Phase A dashboard Windows symlink skips, 26 legacy imported-test-fixture strict type errors when those bodies are included, pre-existing global-format failures, and a synthetic equal-utility optimizer tie ambiguity. The selected 164-test regression group passed with 304 PuLP deprecation warnings. None is the original V1 serializer defect. No full-repository-green claim is made.

This task changes only new transport/identity support, tests and additive documentation/results. No production Player Stats, xP, PMFs, optimizer, captain/transfer policy, FixtureEnvironment, SDP primary/fallback, prospective capture or model config changed. Main/default remain untouched; no PR, merge, rebase or history rewrite. Commit boundaries and final clean/push checks are reported in the owner handoff; the result commit cannot contain its own SHA.

### Artifact identities

| Immutable external artifact | SHA256 |
| --- | --- |
| strict-result.json | ae9ecf14b76d9e4b6e037f6362d5e4e6c860bafc354874ec8ef82f2bfe742d93 |
| retrospective_sdp-result.json | 7cc0f81e50412886633c312e512b43bb94d3c0f2078c4a8eea6f9c9a3894afb4 |
| completion.json | 900734fad1851b163bf2e83100576ba5fef6acad83f4ca2a5a46d4c1dc08a700 |
| prediction-freeze.json | c577d10606133ba444dbb1d72c3f73c802b3622e77442ff1aca3c16f5968ad47 |
| official-outcomes.json | 113cff1f8f30b90b9d34c13680a935c647c9467f4f3a4e5fc05bdb6a6c21230f |
| historical-inputs.json | 0c6d15c5a668c042887db038d9c238eb47a83c9d1b3299887809505de3bfd961 |
| run-start.json | 23922b74def0e2115698b30508dbb4c44ca319d49cf5dd9f5ce738af7ad99f64 |

The exact lane-result bytes are copied to [strict V2](../results/player_model_gw1_3_strict_v2_2026-09-08.json) and [retrospective SDP V2](../results/player_model_gw1_3_retrospective_sdp_v2_2026-09-08.json). The [V2 verification manifest](../results/player_model_gw1_3_verification_v2_2026-09-08.json) contains source/model/implementation/receipt fingerprints, coverage, selector counts, test status and the full twelve-forecast artifact index. External receipts remain under `D:/Personal/fpl-operations/verification/player-model-gw1-3-audit-20260908T095300Z/formal-v2`. No original V1 artifact is overwritten.

**Decision: MIXED. NO — FREEZE.** Monitor minutes calibration, GK/FWD bias, rare-point tail support, positional/component scores, fallback health and primary-versus-shadow ranking through the already-planned GW4-8 true prospective checkpoint. This session ends at measurement and reporting; no repair or new feature research is authorized by this result.
