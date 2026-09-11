# Role / exposure opportunity: retained separate development evaluations

## Verdicts and unchanged full gate

The separately registered goals and assists identities each ran **once** on
2026-09-07. Both are full Stage C **INELIGIBLE**: 114 evaluated folds do not meet
the unchanged 181-fold requirement, and only 38 folds carry OOS role evidence.
Neither candidate may enter development synthesis, replace a default or be promoted.
Keep CURRENT goals and assists, regardless of the scoped assists result.

| Separate candidate | Log-score lift vs CURRENT | Scoped numeric verdict | Full verdict |
|---|---:|---|---|
| `retrospective_role_exposure_player_goals_v1` | +4.235774954% | INCONCLUSIVE; 8/10 diagnostics pass | INELIGIBLE |
| `retrospective_role_exposure_player_assists_v1` | +2.756233763% | SUPPORTED; 10/10 diagnostics pass | INELIGIBLE |

Goals fails the required best-baseline primary and season-consistency checks.
Assists' scoped support is not a full-gate pass or synthesis permission. Neither
claim is retuned, rerun, pooled into the other, or reinterpreted as promotion.

## Frozen identities and fair controls

The [design and final registration](player-opportunity-design.md) and
`config/player_opportunity_evaluation.yaml` preceded both claims at `cb11a64`.
The clean evaluation HEAD was `9f9e32d351495e73a32c8d76f5e21c189f5990b3`;
the intervening authorized merge added only five daily snapshot files, no
evaluation code or configuration. Goals ran 12:35:59.055268-12:48:39.533478 UTC;
assists ran 12:36:08.226332-12:48:39.538653 UTC, with separate exclusive claims,
external output directories and final results.

Both use `retrospective_current_component_proxy_v1` with exactly the cached
`retrospective_current_minutes_proxy_v1` PMFs and complete CURRENT component
inputs. There is no minutes refit, no substitution of the workload challenger,
no upstream role/team refit and no Monte Carlo draw. The two unchanged required
Stage C baselines are fitted on the same prior-event/whole-GW population and
scored on identical rows. Old V4-goals/V2-assists numbers are not fair comparators
for these different CURRENT minutes/component inputs and are not reused.

Each run retains **86,755 rows / 114 folds**, including DNPs and every DGW leg.
All **821 direct archive-price proxy/cold rows retain exact CURRENT PMFs** and
remain in every all-row comparison: 327 / 224 / 270 by season. Same-club proxy
dependence remains separately labelled; a proxy-excluded slice cannot establish
historical deadline-known validity. The complete immutable CURRENT reference and
each target identity/PMF were reproduced before the separate formal claim.

## What was tested

This is a fixed joint change to a soft-role prior, exposure weighting and player
shrinkage, **not a role-only ablation**. Gains cannot be attributed to role alone.
The four role probabilities are conditional on a hypothetical start, used only as
pre-match soft covariates; they are not P(start), observed role-minute exposure,
actual substitute roles or permanent player positions. Only the original OOS
transition-role arm is used, not its stronger EWMA diagnostic.

Separate measured xG/xA-per-minute hierarchies shrink soft-role rates toward the
league rate with 900 minutes, then each player's last-five-appeared eligible
measured signal with 90 minutes. Selecting five appeared eligible rows precedes
dropping NULL signal; missing measurements are never zero-filled or replaced by
older rows. Predicted exposure uses the exact CURRENT minutes PMF and fold-local
prior bin means. The model has no grid or numerical optimizer and no second
P(play) multiplier. All target-GW rows are excluded and observed training labels
require kickoff plus six hours strictly before cutoff.

Only eligible players' existing CURRENT budget is reallocated. All ineligible
players retain their exact rates and conditional PMFs. The original team cap,
Poisson support 0..10/tail folding, and appearance mixture applied exactly once
are unchanged. Conservation is **pre-cap eligible-pool rate-budget conservation**,
not exact post-cap means or realized per-draw team goals. Assists retains the
original fold-local league-assist-rate scale, not a substituted constant.

## Scores and coverage regimes

Lower is better for scores; PIT-80 targets 0.8. All precision, calibration,
intermediate signal diagnostics and registered slices remain in the JSON files.

| Metric | Goals CURRENT | Goals candidate | Assists CURRENT | Assists candidate |
|---|---:|---:|---:|---:|
| Mean log score | 0.1559187356676299 | 0.1493143689136092 | 0.13882165237895794 | 0.1349954031253863 |
| RPS | 0.0336625262343144 | 0.033595009022197815 | 0.03193337189978903 | 0.031828495011377314 |
| Brier, at least one | 0.030106548933273743 | 0.030049913450602046 | 0.029343347769628512 | 0.029243865926853612 |
| PIT-80 coverage | 0.8001498472710507 | 0.800806869921042 | 0.7990432828079074 | 0.7993775574894819 |
| Prediction mean | 0.03811281682494122 | 0.03811281694585633 | 0.03422127637706736 | 0.03422127637717323 |
| Mean prediction error | 0.00028214424122846414 | 0.0002821443621435753 | -0.0002551226777421584 | -0.00025512267763628534 |
| Prediction MAE | 0.06433431121702035 | 0.06477284277163861 | 0.061240811392307096 | 0.06144549732663862 |
| Prediction SD | 0.08380886206409446 | 0.07969799164708696 | 0.06465922495937067 | 0.061617107770780694 |

The best required trailing baseline mean log score is 0.14135570526481822 for
goals and 0.14146448823930605 for assists; positional baselines score
0.15244384300642463 and 0.14754348509214166 respectively. Goals improves CURRENT
but remains worse than its required trailing baseline overall. MAE worsens
slightly in both candidates; it is retained as a diagnostic, not hidden or
substituted for the preregistered proper-score gate.

| Season | Rows / folds | Goals CURRENT / candidate NLL | Assists CURRENT / candidate NLL |
|---|---:|---:|---:|
| 2023-24 | 29,725 / 38 | 0.16846568554138286 / 0.16846568554138286 | 0.14060797407473502 / 0.14060797407473502 |
| 2024-25 | 27,283 / 38 | 0.15881310410236696 / 0.15881310410236696 | 0.14239585083761785 / 0.14239585083761785 |
| 2025-26 | 29,747 / 38 | 0.14072644269683493 / 0.12146527895780014 | 0.13375851092084137 / 0.12259952836819381 |

All older-season outputs are exact CURRENT fallbacks, not extra seasons of new
role evidence. The 2025-26 lifts are +13.68695419% goals and +8.34263366% assists.
The goals trailing baseline is 0.14879882839164352 / 0.14438572220638088 /
0.13113905191619354 across the three seasons; its older-season advantage explains
the failed required-baseline consistency check. The assists trailing baseline is
0.1451821397248383 / 0.14460343039026033 / 0.1348706485542309.
The pooled result must always be read beside this one-role-season boundary.

For each candidate, 16,193 rows receive a new allocation; 29,747 have a retained
role forecast (which includes cold forecasts, not necessarily usable role support).
Fallback counts are identical: 57,704 unsupported-prior-role, 821 CURRENT-cold,
11,370 unavailable-current-role and 667 unmeasured-recent-signal rows. Together
with corrected rows these account for the complete 86,755-row denominator.

The overall paired candidate-minus-CURRENT mean log-score differences and
114-GW-clustered normal 95% intervals are:

- Goals: -0.0066043667540207265; [-0.009918467153431514, -0.0032902663546099387].
- Assists: -0.0038262492535716315; [-0.005915105481151775, -0.0017373930259914874].

For the 38-GW role season only, goals is -0.019261163739034796 with interval
[-0.02766705815237798, -0.010855269325691612]; assists is -0.011158982552647558
with interval [-0.016641521712000038, -0.005676443393295076]. These intervals are
not serial-dependence-adjusted and do not waive either frozen gate.

## Independent reconciliation and limitations

Each independent audit passes **9,758,661 checks, zero failures**. It imports no
FPL model code, fits no candidate or upstream model, repeats no formal runner and
writes no source database. It independently reconstructs source/role identities,
all four scored PMFs per row and their exact appearance mixtures, closed-form
baselines, hierarchy sufficient statistics/history hashes, causal membership,
window selection, fallback reasons, allocations/caps, complete metrics/slices,
PIT/reliability, GW-cluster intervals and every numeric/full-gate Boolean.

The maximum numerical discrepancies are 8.881784197001252e-16 for goals and
4.440892098500626e-16 for assists. Before permitting additive repository work,
the independent source preflight also verified the original source/config/Git,
138,707 archive rows, 29,747 original OOS-role DTO certificates, upstream caches
and every completed fold hash. The later arithmetic audit used only frozen
external outputs and read-only archive data.

The evidence class remains `retrospective_role_and_archive_price_proxy_development`.
Archive roster/price proxies, original later competitive captures and conservative
six-hour completion assumptions do not prove historical deadline knowledge.
No capture timestamp is rewritten. Prequential role certificates establish event
ordering, not contemporaneous public availability. Only one source-covered role
season exists, and this joint construction cannot establish a role-only effect.
No result supplies a full-points or optimizer validation claim.

## Immutable artifacts and provenance

These are byte-for-byte additive copies, protected from Git newline conversion.

| Retained artifact | SHA-256 |
|---|---|
| [Goals result](../results/player_opportunity_goals_development.json) | `2ae0a4aa06acd0b883b60f5b14151b25f0f506b3260a5bf6d5f2bc70bc402485` |
| [Assists result](../results/player_opportunity_assists_development.json) | `0e168375f6928b7245816c77cb0e2de135dcc5ed92984d132d3a18cbf9c74a0b` |
| [Goals independent audit](../results/player_opportunity_goals_independent_audit.json) | `a780d6b3c81fc3129a89efb9022483f446cff68b44c43e53cb343e7189cc3a2a` |
| [Assists independent audit](../results/player_opportunity_assists_independent_audit.json) | `af90ff6f95540b81f3114ea2144f98311f4049a00e9a4a09fac86751962b53fa` |

Original complete fold records and runtime receipts remain beneath
`D:/Personal/fpl-operations/verification/player-opportunity-goals-20260907T123600Z`
and `D:/Personal/fpl-operations/verification/player-opportunity-assists-20260907T123600Z`.
The independent script and original audit results remain beneath
`D:/Personal/fpl-operations/verification/opportunity-independent-audit-20260907T130000Z`.
Full model-source and upstream pins remain in each JSON. Principal SHA-256 pins:

- Configuration: `958df33180b85215db9d2b336d051f5d5d0510d3aebe38cc96e2b48d7ecce16f`.
- Archive database: `0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8`.
- Complete CURRENT component manifest: `c76bb1936b332b05bd8e3970af3dbd5b3e95c428d1005783c59d82b88d8f04b9`.
- CURRENT minutes manifest: `5b813d58b71bad97a5c81774aaf70c0bca5f4e0e3bcd518e6f26e0acfea19bac`.
- Original OOS role result: `c330d44a227ff6ff10cce1d5813f582d48dadfa181816c9333d6389358940809`.

Retention changes no prior evaluation, model, gate, CURRENT component/default,
optimizer input, or synthesis eligibility. These separate once-only records are
closed development evidence, not permission for another run or post-result tuning.
