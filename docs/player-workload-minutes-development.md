# Workload / role minutes: retained development evaluation

## Verdict and boundary

`retrospective_workload_role_minutes_offset_v1` ran **once** on 2026-09-07.
Its scoped verdict is **INCONCLUSIVE**: mean log score improves only **0.00353654%**
against the exact CURRENT control, below the preregistered 1% bar. Full Stage B is
**INELIGIBLE** because 114 evaluated folds do not meet its unchanged 181-fold
requirement. Only 38 folds carry the new workload season. Neither synthesis,
promotion, nor a prospective-default change is permitted. Keep CURRENT minutes.

This is `retrospective_workload_role_and_archive_price_proxy_development`
evidence, not a historical deadline-known forecast. The candidate is left as
registered, without retuning or another formal run. The earlier dated registration
record remains true at its own commit; this is its additive result record.

## Frozen procedure and fair comparison

The [preregistration](player-workload-minutes-evaluation-v1-preregistration.md)
and `config/player_workload_minutes_evaluation.yaml` were frozen before scoring at
`cb11a64`. The clean evaluation HEAD was
`9f9e32d351495e73a32c8d76f5e21c189f5990b3`: the intervening authorized merge added
only five daily snapshot files, changing no evaluation code or configuration.
The run began at 12:36:25.807521 UTC and completed at 12:42:03.359794 UTC.

CURRENT is the cached `retrospective_current_minutes_proxy_v1`, not a newly fitted
minutes model or an old result-table comparator. The four original Stage B
baselines are separately evaluated on the identical eligible population. There
are 86,755 player-fixture predictions, including DNPs, over 114 folds. All **821
direct archive-price proxy/cold rows remain in the denominators and retain exactly
their CURRENT PMFs**: 327 / 224 / 270 by season. Dropping these rows cannot turn
this record into a clean deadline-known result.

The four features are witnessed positive nominal minutes during the preceding
168 hours, divided by 180 and capped at one, multiplied by the four broad
starting-role probabilities. The offset is
`q[k] proportional to p_current[k] * exp(beta[k] dot x)`, with bin-zero coefficients
fixed at zero. The 12 fitted coefficients use the frozen ridge-1 mean-NLL
objective, zero initialization, step 2/3, at most 200 updates and gradient-infinity
tolerance 1e-10. A fit requires eight prior eligible GWs and 200 eligible rows;
there is no hyperparameter search. The 27 enabled fits begin at 2025-26 GW12.

The role input is the original sequentially OOS transition arm, not its stronger
EWMA diagnostic. It describes broad role conditional on a hypothetical start,
not starting probability or physical role minutes. This joint workload/role
offset is not a role-only ablation, so its result cannot identify a separate
causal workload or role effect. Every fit excludes the complete target GW;
prior observed labels require kickoff plus six hours strictly before cutoff.

## Retained scores

Lower is better for proper scores; higher is better for starter ranking.
PIT-80 targets 0.8. Full-precision scores, calibration buckets and every
preregistered slice remain in the result JSON.

| Metric | CURRENT | Candidate |
|---|---:|---:|
| Mean log score | 0.6785766402663648 | 0.6785526421235454 |
| RPS | 0.29323512284578457 | 0.29321023985501027 |
| Brier, any minutes | 0.10762599318145935 | 0.1076202538594291 |
| Brier, 60+ minutes | 0.10033513695833648 | 0.10032471818492449 |
| PIT-80 coverage | 0.8144660250129675 | 0.814442971586652 |
| Within-position/GW Spearman P(60+) | 0.6928245894253208 | 0.6934074539436172 |

| Season | Rows / folds | CURRENT mean log score | Candidate mean log score |
|---|---:|---:|---:|
| 2023-24 | 29,725 / 38 | 0.6703252289539172 | 0.6703252289539172 |
| 2024-25 | 27,283 / 38 | 0.7169302390886806 | 0.7169302390886806 |
| 2025-26 | 29,747 / 38 | 0.6516452510369722 | 0.6515752621681685 |

Five of six CURRENT-control diagnostics pass; only the required 1% log lift fails.
Eight of ten frozen Stage B diagnostics pass. The failures are minimum folds and
starter ranking against the best original baseline: approximately 0.69341 versus
0.71921 for `last_observed_player_minutes` (3.5873% regression). Improving slightly
on CURRENT's ranking is not the same as satisfying that frozen baseline guardrail.

The paired candidate-minus-CURRENT mean log-score difference is
-0.000023998142819462748; its 114-GW-clustered normal 95% interval is
[-0.000034059893020540315, -0.000013936392618385181]. On 2025-26 alone it is
-0.00006998886880366056, with interval
[-0.00009285540086089518, -0.000047122336746425944] over 38 GWs.
These are not serial-dependence-adjusted intervals and do not override the 1% bar.

## Coverage and limitations

Earlier seasons' 57,008 rows keep exact CURRENT predictions. In 2025-26 the
pre-fit population has 9,551 feature-active rows, 8,169 role-history-cold fallbacks,
11,627 positive-workload-unavailable fallbacks, 270 CURRENT-cold rows and 130
witnessed-zero-nominal-volume fallbacks. Feature-active does not mean every row
receives a fitted correction: the frozen minimum-history gate also applies.

The independently reconstructed workload source contains 574 earliest complete
final competitive-match bundles across six competitions, retaining the 39 finalized
cup matches with aggregate/penalty/extra-time result labels. Nominal positive exposure is
only a witnessed lower bound, not complete competitive minutes, exact rest, or
proof of registration/absence. Original later capture times stay retrospective.
The archive target-roster and price proxies, and six-hour completion proxy, do not
establish real-deadline knowledge-time validity. No missing workload becomes zero.

## Independent reconciliation

The two final independent audits pass **12,349,170 checks, zero failures**:
11,249,573 distribution/training/metric checks and 1,099,597 source-feature checks.
They import no FPL model code, call no formal runner, perform no model fit or
coefficient updates, and write no source database.

The audits reconstruct every CURRENT/candidate four-bin PMF, all four baseline
PMFs, all 114 fold hashes, target identities and proxy lineage, causal training
membership/hashes, feature/fallback records, sufficient statistics, final objective
and gradients, every score/slice/reliability bucket/PIT/rank statistic, clustered
uncertainty and gate. PMFs, features, training hashes and final objective/gradient
certificates match exactly; maximum metric arithmetic discrepancy is 1.18683e-13
from summation order. Saved monotone objective traces and the fixed strong-convexity
condition certify the 27 enabled fits without repeating their optimizer updates.

Two initial incomplete audit-construction receipts remain externally preserved:
the audit reader first assumed role manifest entries had a season field, then
assumed the archive had no live rows. Correcting those audit assumptions establishes
the actual required condition: no live rows are known at historical cutoffs.
Neither correction changed or reran the candidate.

## Immutable artifacts and provenance

The following are byte-for-byte additive copies; `.gitattributes` disables newline
conversion for exactly these retained files.

| Retained artifact | SHA-256 |
|---|---|
| [Development result](../results/player_workload_minutes_development.json) | `9c66f48d7879654b7edca33aceadc124bb6cd6ec64cef5c45744c5ab130e364d` |
| [Independent distribution audit](../results/player_workload_minutes_independent_audit.json) | `aa43e7208d7ef5cf6b42b668e3545c24d87442b7a67420b0b34578b0eb132f7b` |
| [Independent feature audit](../results/player_workload_minutes_feature_audit.json) | `99871bdfbd353b7240e3df1f5844253939ab2e319d6acf1f2163912f13510671` |

The original result, full fold records and runtime receipts remain under
`D:/Personal/fpl-operations/verification/workload-minutes-development-20260907T123600Z`;
independent scripts, final results and initial audit receipts remain under
`D:/Personal/fpl-operations/verification/workload-minutes-independent-audit-20260907T124000Z`.
The JSON provenance retains the complete model-source and upstream pins. Principal
identities are:

- Configuration: `6d483e21d2a55015b75d7378551fe80fb2fa0d7c1a36b02babe182cfe7ac97ba`.
- Archive database: `0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8`.
- CURRENT minutes manifest: `5b813d58b71bad97a5c81774aaf70c0bca5f4e0e3bcd518e6f26e0acfea19bac`.
- Original OOS role result: `c330d44a227ff6ff10cce1d5813f582d48dadfa181816c9333d6389358940809`.
- Coverage receipt: `770206f0c151694501cc06b95631b554b172b956e8cfe10363481f474f3cf982`.
- Feature identity: `a94d5555714a6f77c8c5068a1a98cd3a2db72592e68725ef080cb1e49d0bb23a`.

Source/config/database and upstream/fold hashes were independently checked before
the evaluation source freeze was released. Retention changes no frozen evaluation,
model, gate, optimizer input, prospective default, or synthesis eligibility.
