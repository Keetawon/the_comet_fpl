# Goal-involvement event V1: full nested development result

The single formal run completed from clean `a50afeff67447e719072527d0b7d97af8f90fed6`.
All 181 historical folds and 133,964 fixture inputs reconcile to 128,443 complete
player-gameweeks; the xG-covered seasons contain 84,999 player-gameweeks.
No 2026/27 outcome was used in fitting or selection. Historical roster and outcome
availability still use the documented unversioned proxies.

| Covered-season score | Component probability | Nested event classifier |
| --- | ---: | ---: |
| Log loss | 0.0432207248230 | 0.0429404689705 |
| Brier | 0.0091362324564 | 0.0091146430425 |

Log-loss lift is **0.64843%**, below the preregistered 1% bar. The paired
GW-cluster bootstrap 95% interval is **[-0.10366%, +1.41474%]**. Brier, calibration,
season-regression and full-coverage checks pass. Overall serving gate: **FAIL**.
The published probability therefore remains the exact component-based calculation;
the learned classifier is retained as prospective shadow. This does not reverse
the separate owner-directed adoption of the complete New xP player stack.

Final inner selection chooses ridge **1**, with a fitted slope. The final fit uses
128,443 rows / 1,328 events before 2026-07-01. Logit slope is **0.622972518665**;
position intercepts (GK, DEF, MID, FWD) are **-1.759951920729, -1.863330219081,
-1.038128941771, -0.783382836484**. These are the best setting within the registered
grid under the final inner selection, not a claim of a globally optimal model.

Independent arithmetic reconciles every selected prediction (maximum difference
5.56e-17), all 181 inner windows / 1,065 references, strict complete-label cutoff
eligibility, row counts and covered scores. No parameters were refitted during
verification. The frozen evidence is in `results/goal_involvement_v1_development/`.
Result SHA-256: `7c43ed2df7d783e37e00ddcda89ad9a50ff155a49d74ec0a1cc85a9d53376d41`.
