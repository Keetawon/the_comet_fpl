# Full-player PMF population: coverage decision before scoring

Measured on 2026-09-07 against the preserved research database
`data/fpl.duckdb`, SHA256
`0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8`.
This is a data-only decision, before Phase G/H candidate scoring and before any
new full-points control or synthesis simulation. No model was fitted or scored.

The shared current-selector proxy reference contains 86,755 player-fixture rows,
114 complete GW folds and 821 direct price-proxy rows. Require **100% measured
full-points target components** on that reference population within each season,
including zero-minute rows. Missing components cannot be replaced with zero.

| Season | Reference rows | Each of the 12 other scoring components | DC measured | Eligible |
|---|---:|---:|---:|---|
| 2023-24 | 29,725 | 29,725 | 0 | No |
| 2024-25 | 27,283 | 27,283 | 0 | No |
| 2025-26 | 29,747 | 29,747 | 29,747 | Yes |

The other components are minutes, goals_scored, assists, clean_sheets,
goals_conceded, saves, penalties_saved, penalties_missed, own_goals, yellow_cards,
red_cards and bonus, exactly `_LABEL_COMPONENT_COLUMNS` in the existing full-points
label path. Counts were measured with `count(column)` over
`mart_fact_player_fixture`, restricted to those three seasons, measured minutes,
and positions GK/DEF/MID/FWD, grouped by season. The existing pinned minutes
reference independently fixes identities rather than accepting count equality as
identity proof.

The nominated Phase J cohort is therefore **2025-26, all 38 GWs, 380 fixtures,
29,747 rows**, with **270 direct archive-price proxy rows**. Both arms must use
those identical rows and the same current-selector proxy inputs. The upstream
821-row historical registry gap remains explicit; the other 551 proxy rows belong
to the two seasons excluded solely for absent target DC. Report direct proxy,
non-proxy, cold-start and established slices; proxy exclusion is diagnostic only.
Also retain conservative team-allocation and fixture-bonus proxy dependence.

The target remains the existing **full points including recorded bonus**, replayed
from measured components under the loaded 2026/27 scoring rules, not archived
`total_points`. This is not a change to non-bonus points or permission to erase
penalties/cards/own goals from realised targets. No current-target ICT is a
predictor: the separate current-component reference uses historical trailing ICT.
Any existing support coarsening must be declared in the forthcoming separate
synthesis contract and retain the original signed target alongside it.

One eligible season cannot establish cross-season robustness or prospective
validity. The new synthesis gate and complete design are still to be preregistered;
this coverage decision is already fixed and must not change after component or
full-points results are inspected. No candidate is accepted by this population
audit. Stage B/C's separate 181-fold requirements are unchanged.

Independent target-only identity reconciliation confirms all29,747rows/38GWs/
380fixtures and270direct proxies. Ordered target-key SHA256:
`bbad5f15f9969568af0fc078c80e1725ffaf2b0be661b6831f553cd7c4063566`.
Replayed signed targets range -3..24:77negative labels (DEF56,MID16,GK4,FWD1),
none above34. One zero-minute row has -1; it remains in the labels and is not
silently erased by the predictor's no-appearance rule. The exact current support
is0..34, so the existing proper-score target is explicitly coarsened to
`min(34,max(0,signed_target))`, while raw signed targets and separate signed
bias/MAE remain retained. This is NOT a calibrated signed-points PMF claim.
The original full-points scoring target is still replayed including bonus/cards;
its legacy support limitation is disclosed, not repaired in this program.
Independent read-only audit:
`D:/Personal/fpl-operations/verification/full-points-label-audit-20260907T104000Z/result.json`.

## Outcome-independent component application, fixed before G/H results

If GK-saves H passes, its conditional appeared-keeper scoring cohort must NOT
become a synthesis switch. Apply its frozen per-fold pooled precision and unchanged
save fraction with the retained OOS opponent-shot forecast to **every GK roster
row**, including DNP targets. This is an outcome-free application of retained fitted
parameters, not another fit or H evaluation. Extract and validate unique per-fold
parameters; never infer eligibility from whether a keeper has a scored H row.
The unchanged joint composer subsequently gates on **drawn**, not actual, minutes.

If DC G passes, use the retained all-outfield roster predictions in its eligible
folds. Its preregistered minimum of ten measured **prior** GWs supplies the early
season fallback to incumbent. Never choose a component using target DC, actual
appearance, label availability or the eventual target score. If a required
outcome-free projection cannot be reproduced, fail closed before synthesis scoring.
Failed or otherwise gate-ineligible successors retain incumbent behavior for the
entire nominated component, not only for convenient rows.
