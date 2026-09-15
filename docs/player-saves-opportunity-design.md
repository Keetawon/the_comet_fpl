# Frozen OOS shot opportunity -> GK saves V1

Candidate `retrospective_oos_shot_opportunity_gk_saves_v1`, retrospective development
only. No changes to current defaults, keeper skill, minutes model, team goal PMF,
bonus, scoring constants, or count-distribution family. No old candidate is rerun.

## One football mechanism

The frozen Phase A intermediate shot-volume forecast improved shot RMSE relative
to persistence; its Goal/CS candidate remains INCONCLUSIVE and is not promoted.
This new downstream experiment consumes **only its retained prequential shot
predictions**, never refitting Phase A or using its goal corrections. It tests
whether that separately forecasted opportunity can improve saves without imposing
SOT = predicted goals / (1-save fraction).

Before scoring, `results/player_saves_opportunity_coverage.json` selects the same
three jointly covered complete seasons,2023-24 through2025-26. Corresponding
shot+SOT team-side coverage is754/760,740/760,744/760, all above95%. The42absent
SOT fields remain NULL, not inferred zeros; this may bias the measured precision
pool and is an explicit source limitation. Do not repair it after seeing results.
Source fields are `totalScoringAtt` (provider-labelled development semantics) and
independently corroborated `ontargetScoringAtt`, joined to the **same canonical
original payload**. Field presence does not license all246metrics.

Use2,313recorded GK appearances with measured saves and conceded goals:
776/770/767by season,114whole-GW folds. All keeper labels are retained even when
their target SOT is missing; only the SOT diagnostic then lacks that label.
There is more than eight historical prior GWs before every nominated fold.

## Fixed estimator and inputs

For each fold, use earlier measured pairs with `kickoff+6hours < cutoff`, excluding
the entire target season/GW. Precision is `sum(SOT)/sum(shots)`, pooled across the
league. Require160measured sides and positive shot exposure, otherwise exact
incumbent fallback. No fitted team/keeper precision, grid, tuning or new family.

For keeper K against opponent O:

`predicted_SOT_faced = frozen_OOS_predicted_shots(O) * prior_pooled_precision`.

`saves_rate = predicted_SOT_faced * unchanged_incumbent_league_save_fraction`.

The save fraction remains the exact current `GkSavesV1` arithmetic:
sum(prior GK saves)/sum(prior GK saves+conceded), original clamp/fallback unchanged.
It remains a scored-FPL proxy conversion, not newly verified physical save skill.
The only new volume source is the OOS shot forecast; no saves-goals identity is
used to generate candidate SOT. Explicit zero opportunity gives exact zero rate.

The current prospective component predicts a full-match conditional-on-appearance
Poisson; preserve that convention rather than simultaneously adding exposure
corrections. Actual target minutes select the appeared scoring cohort only, not
the rate. Shared cached minutes/price lineage is retained for cold/proxy diagnostics
but never used by this saves component. Thus the821missing historical price rows
still exist in the full player reference, without becoming this model's predictor.
Report any intersecting rows separately; exclusion is diagnostic only.

Preserve Poisson support0..9 plus10+overflow and existing scoring-only1e-12floor.
Do not replace conditional PMFs with a new marginal minutes mixture. Any future
composer applies appearance exactly once as before. Missing upstream volume or
precision retains the exact incumbent PMF, never zero-filled measurements.

## OOS / identity / reproduction

Canonical upstream result SHA256
`f4cc595384102112ba2c41f118396d4176a6f7000a6f3c1753b5edf1a1ae952f`.
Only original predicted volume, fixture/cutoff/reciprocal club IDs and upstream
training provenance enter forecast objects. Target shots/SOT/saves are labels in
separate records. Original known_at is retained, not rewritten to historical time.
The upstream volume/state/style fit maxima must precede the target cutoff with
the conservative completion margin. Whole-GW/DGW/postponed timing remains fixed.

Before reserving a new claim, reproduce all3,800historical **incumbent** team PMFs
against retained and actual prospective paths using the existing comparator-only
helper. This does not execute the Phase A candidate. Then compare direct
`GkSavesV1` with the actual component-suite factory for all2,313keeper rows exactly.
Current helper history and the six-hour exclusion must agree; fail closed otherwise.

## Frozen gate and compute

Retain the stricter existing GK contract: at least1%relative mean-NLL improvement,
nonregressing CRPS, PIT80within.05 of.8 and **each reported season clearing1%
and both CRPS/PIT guardrails**.
Require zero leakage and exact population. SUPPORTED only if all pass; REFUTED
if aggregate NLL worsens at least1%; otherwise INCONCLUSIVE. Every verdict is
development-only and no automatic production activation is allowed.

Retain season, home/away, GW1–6/GW7+, cold/established, price/non-price and fixed
predicted-SOT<4/at-least4slices. Report CRPS/RPS, PIT80, MAE, bias, rate SD,
within-GW Spearman, per-row paired loss and GW-clustered normal95%uncertainty
(no serial-correlation adjustment). Compare measured SOT RMSE against incumbent
implied-SOT as a diagnostic, not a post-result feature selector.

Bound:114simple ratios plus no new upstream fits and2,313Poisson outputs. The
comparators perform bounded existing team fits; no nested search. Expected minutes,
not hours; refuse dirty/WAL/hash drift and any existing shared-Git candidate claim.
Commit config/design/tests/code before one formal run, retain all original and new
PMFs and source/cutoff/capture evidence, independently audit without refitting.
No numerical retry under this identity; follow a separate amendment if invalidated.
