# Workload / broad-role minutes offset V1: fixed algorithm only

Identity: `retrospective_workload_role_minutes_offset_v1`.
Evidence class: `retrospective_workload_role_and_archive_price_proxy_development`.
The algorithm below is fixed before any real-data fit or formal scoring. It is a
pure development component, not a replacement forecast/default, final population
registration, accepted successor, synthesis input or model-performance result.

## Exactly one bounded correction

The control is the already-retained four-bin
`retrospective_current_minutes_proxy_v1` distribution in the unchanged order
`0 / 1-59 / 60-89 / 90+`. No V3 fit, prior, price rule, season-boundary correction,
roster, target, FPL position or baseline distribution is changed. `control_from_cache`
is a pure bridge from an already validated shared-cache fold; it retains its manifest,
fold hash, maximum prior event, cold/proxy status and original selector/price lineage.

The only input volume is the independently witnessed competitive nominal minutes
**lower bound** in the previous168hours. It is neither total player workload, exact
elapsed exposure, an inferred registration interval nor evidence that an unobserved
player rested. Unavailable workload is never set to zero. Unknown off-scope matches,
incomplete catalogues and unresolved membership remain explicit source limitations.
Positive valid witnesses can support a lower bound despite that unknown universe.

The only role input is the prequential four-way
`P(GK, DEF, MID, FWD | hypothetical start)` from the separately named broad starting-role
forecaster. These are soft provider broad-role probabilities, not the target's actual
role, actual XI, FPL position, permanent tactical identity or a starter probability.

Freeze four features, in GK/DEF/MID/FWD order:

`w = min(witnessed_nominal_minutes_7d / 180, 1)`

`x[r] = w * P(next broad starting role = r)`.

The180-minute cap bounds the predictor and represents up to two nominal full matches;
it does not alter the retained source volume. A240-minute lower bound remains240 in
diagnostics although its scaled volume is1. No count of appearances, rest-hours proxy,
venue, team indicator, player indicator, FPL price, opponent, tactical statistic,
intercept or additional interaction enters this experiment.

Let `p[k]` be the exact current-control PMF. The correction is:

`q[k] = p[k] * exp(beta[k] dot x) / sum_j(p[j] * exp(beta[j] dot x))`.

Fix `beta[0] = [0,0,0,0]`; the other three rows contain12coefficients total. The model
therefore changes only relative minutes-bin probabilities, leaving the same categorical
target and support. It does not replace the dynamic control with another minutes model.

## Fixed strong shrinkage and deterministic fitting

Use eligible prior prequential rows only and minimize:

`mean(categorical negative log likelihood) + (1/2) * sum(beta**2)`.

The fixed ridge penalty is1.0 on the **mean** loss, not the summed loss. This deliberately
anchors the correction strongly toward zero without tuning its strength from target
results. Workload is incomplete and broad role is a coarse conditional forecast; a
small first correction is more defensible than a weakly regularized large adjustment.
There is no grid, inner selection, tie-breaking search, random split or seed.

The operational Python environment has neither NumPy nor SciPy. No dependency is added:
only12coefficients require deterministic full-batch gradient descent with stable softmax,
zero initialization, step`2/3`, at most200updates and gradient-infinity tolerance`1e-10`.
This is not an unconstrained generic optimizer. Because `||x||² <= 1`, the multinomial
covariance has spectral norm at most`1/2`; adding ridge1 gives a global gradient
Lipschitz bound`1.5` and strong-convexity bound`1`. The fixed step is therefore bounded
before observing any model result. The unique ridge solution needs no incidental
dictionary tie-breaking. Training rows have a fixed chronological/fixture/player order
and reductions use `math.fsum`. Retain objective trace, iterations and final gradient.
Nonfinite values or nonconvergence fail explicitly; they do not trigger retuning or a
quietly successful baseline result.

Correction fitting requires BOTH at least8distinct eligible prior PL season/GW batches
and at least200eligible prior player-fixture rows. Otherwise coefficients remain exactly
zero and every prediction retains the control. Those thresholds count eligible features
and prior labels only, not future rows or extra all-fallback folds. They are not a
replacement for the separate full Stage B eligibility requirement.

## Exact fallback, missingness and identity

Return the original control PMF object, without recomputing/renormalizing it, when:

- the player is a current-control cold start;
- any control bin has zero mass (an outcome-independent support rule; no log-floor
  smoothing or new positive support is licensed);
- the target's exact provider identity, positive observed workload or prequential
  role forecast is unavailable;
- there is no witnessed current-club measured starting-role history;
- the source explicitly witnesses a zero-nominal-duration cameo;
- the minimum prior-row/batch thresholds fail, all coefficients are zero, or the
  effective correction for this feature vector is exactly zero.

The actual zero-duration cameo remains an appearance; it is not a rested-player label.
NULL durations remain NULL, and only the existing measured source values form the
lower bound. Invalid/contradictory identity, duplicate revisions, target leakage,
inconsistent aggregates or malformed PMFs are errors rather than convenient fallbacks.
Uncorrected rows remain in the unchanged all-player evaluation denominator. Feature-only
eligible rows are the fitting subset, never a replacement headline target population.

## Event time, same-GW state and stacking

Every training observation contains an immutable predictor object and a separate
observed minutes-bin label. There is no target-minute/role/lineup field in the predictor
interface. The control and role forecast must have been generated for that historical
row's own pre-GW cutoff. A control maximum-training event or role maximum-training event
at/after that cutoff is rejected. The role prediction retains its source-row SHA and
the original global-role forecast artifact must remain available downstream.

Observed workload is selected by exact provider/competition/season/match IDs and exact
player crosswalk. It must exclude the COMPLETE target GW, not only its own fixture.
Every referenced7-day witness must reconcile to a retained completed capture, same
player identity, actual nominal source values and a kickoff strictly before the cutoff.
Any known final-event/end timestamp at/after cutoff rejects the witness. If no verified
whistle exists, reuse the committed conservative rule: kickoff plus **six hours** must
be strictly before cutoff. This remains a development completion-time proxy, not an
actual whistle or provider SLA; original capture/interpretation times are retained.

Each minutes correction fit accepts a historical minutes label only when its actual
kickoff plus **six hours** is strictly before the outer cutoff, and excludes every
target season/GW row irrespective of its kickoff. This conservative completion proxy
also protects against a postponed prior-GW match still being played near the cutoff;
it neither changes original timestamps nor claims to know its actual final whistle.
Same-GW historical upstream predictions must share one cutoff and stable club identity.
All target fixtures, including DGW legs, are then predicted from that one immutable fit.
No target fixture can update another. Future/postponed matches cannot enter history by
nominal GW numbering. No full-dataset normalization or upstream in-sample role fit is
allowed; later-captured provider evidence remains explicitly retrospective throughout.

## Provenance and later evaluation obligations

Retain the model identity/evidence class, fit cutoff, all prior/eligible row and batch
counts, exact fallback counts, coefficients, solver diagnostics, training input hash,
maximum prior target event, per-row role probabilities, scaled and original workload,
source capture/hash/interpretation identities, late knowledge times, completion proxy
and unresolved-workload reasons. The current price-proxy lineage remains attached to
the control; coupled allocations and joint bonus must later propagate dependence as
specified in the owner amendment. No knowledge timestamp is rewritten.

The final evaluation config and exact rows/folds will be frozen only AFTER coverage
audit, before formal scoring. It must retain the original Stage B proper-score,
calibration/ranking/coverage requirements and the181-fold minimum from
`config/phase2_evaluation.yaml`. The currently retained114nominal reference folds and
only38workload-season folds **do not meet that requirement**. A scoped positive numeric
result is therefore full-gate **INELIGIBLE** and cannot enter the passed-successor
synthesis. No filler folds, favorable subset or changed threshold repairs eligibility.

Offline hand calculations validate features, first gradient/step, normalized PMFs,
finite-difference derivatives, known-context changes, zero/fallback exact identity,
thresholds, deterministic convergence, same-GW/DGW/future isolation, stable crosswalks
and prequential role provenance. They establish implementation mechanics only.
No real-data fit, forecast, formal evaluation or promotion is authorized by this
algorithm-only document.
