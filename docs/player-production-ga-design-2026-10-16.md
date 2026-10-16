# Owner-directed player models and goal-involvement event V1

The owner explicitly requested production use of the complete New xP comparison
on October 16, 2026 and confirmed inclusion of duration-conditioned DC. The owner
also confirmed that “more than 1 G+A” means at least two combined goals and FPL
assists in a gameweek. This is an operational adoption decision, not a changed
scientific verdict. Preserve every prior experiment, metric, gate and artifact.

The adopted player stack is sparse attacking priors plus the frozen fully nested
last-ten-appearance conversion V2 coefficients and duration DC. Minutes, football
environment selection, cards, saves, bonus logic and availability semantics stay
as in the comparison. Conversion goals: k=1, ridge=100, bound=.5,
beta=.13642959649545564; assists: k=1, ridge=.1, bound=.5,
beta=.1960665313904956. Selection and fitting ended before 2026/27. The original
covered-season conversion result is inconclusive: goals worsened .03499%, assists
improved .06547%. Choosing operational use does not turn that into a gate pass.

## New research preregistration

Candidate `gameweek_goal_involvement_event_v1` is a separate binary classifier for
P(goals + FPL assists >= 2). It calibrates the adopted components' common-appearance
baseline; it does not change xP or assert a newly fitted joint count distribution.
For a fixture the conditional goal/assist PMFs share one minutes appearance gate.
Combine fixture P(0) and P(1) by convolution across every player-GW leg before
calibration. This includes one involvement in each of two fixtures. It is neither
P(goal)*P(assist) nor the sum of fixture threshold probabilities.

Inputs are the frozen conversion V2 out-of-fold predictions and their exact
prepared-input manifest. Do not regenerate or rejudge the conversion experiment,
and never apply the final 2025/26 conversion fit to earlier historical rows.
Use all 181 observed folds (133,964 fixture rows) across 2021/22–2025/26, with the
114 xG-covered folds separately reported. Aggregate by (season, GW, stable code).
Every expected leg and both component labels must be present. No missing label is
zero-filled. Historical target roster, first kickoff, and last kickoff +3h outcome
availability remain unversioned proxies, not evidence of real-deadline validity.
GW1–6 of 2026/27 and GW7 outcomes never fit or select this classifier.

Model: penalized logistic regression with four shrunk position intercepts and an
optional shared slope correction around logit(component probability). The fixed
feature clips probabilities to [1e-6,1-1e-6], clips logits to [-12,6], rounds to
one decimal, and uses identical transformation at fit and inference. This is a
registered approximation, never a full-data fitted transform. The ridge penalty
is centered on zero corrections (identity); grid [100,10,1] crossed with fixed
slope / fitted slope. Include the exact uncalibrated baseline as an off option.
Tie order: off, then larger ridge, then fixed slope. Do not class-balance, oversample
events, or adjust the grid after observing results.

Full expanding nested walk-forward: before each outer cutoff, select on the last
six completely available earlier GWs. Refit every setting on only folds whose
complete labels precede each inner cutoff. Require twelve complete earlier GWs
and twenty events for a learned fit; otherwise use baseline. Every selected model
is refit before its outer forecast. Final selection uses the same procedure at
2026-07-01 and then refits all eligible historical data. Save every fold's
coefficients, inner losses, selected parameters and predictions. Commit code,
tests and this protocol before one exclusive formal run; preserve interruption
evidence and never silently rerun a claimed experiment.

Comparators: component baseline, a past-only position event rate with Beta(.5,49.5)
cold prior, and last-ten observed player-GW event rate shrunk by ten position-prior
observations. These descriptive comparators are not conversion features. FPL
ep_next is unavailable as a legitimate historical probability of this event and
is not substituted. Report log loss, Brier, fixed ten-bin reliability with counts,
calibration error, event counts, by-season/position/cold-start/DGW cohorts and
within-position/GW AUC. Retain paired GW-cluster bootstrap log-lift intervals
(2,000 samples, seed 202627). Prediction spread is not accuracy.

Serving gate fixed before fitting: at least 1% covered-season log-loss lift over
the component baseline, nonworse Brier, no season log regression above 2%, and
absolute calibration error no more than baseline +.002; all 181 folds must be
accounted for. If any gate fails, publish the exact component probability and
retain the trained event classifier as shadow. This controls only which event
probability is served, not the owner's already-confirmed xP adoption. Even a pass
remains retrospective development evidence with the stated historical proxies.

## Publication contract

New immutable forecasts bind both component and event-model configuration hashes.
Retain original artifacts and scientific labels. Legacy vintages have unavailable
event probabilities; never backfill them from later fits. A genuinely blank GW is
0. Calibration is applied only to GWs with scheduled fixtures. A zero appearance
probability for every leg remains structural zero. A missing/incomplete forecast
is unavailable. Preserve independent-gameweek assumptions explicitly.

Add Players-only sortable columns immediately after the selected-start-GW xP:
`G+A ≥2 GW{start}` and `Avg G+A ≥2 · 5 GW`. The latter is the arithmetic mean of
the five published probabilities at start..start+4, including true blanks. It is
unavailable if any of those five GWs is missing or extends beyond the season end.
No shortened window or cumulative-five-GW event probability is substituted.
Python computes these values; the browser selects the exact published start GW.
Availability remains a separate overlay and never multiplies these probabilities.

### Input-only preflight correction, before any fit or claim

The initial input validation at 9f9a0b6 rejected the no-xG historical fallback:
frozen V2 preserves the independent trailing Poisson PMF there, without an
appearance mixture. Those explicitly flagged fallbacks must be treated as
conditional input and gated once, matching the live composer fallback convention.
Only nonfallback PMFs have their known appearance mixture inverted. This is a
new event-baseline mapping, not a change to the old conversion result. No event
fit, outer score or formal run claim existed at this rejection. Preserve the
no-xG evidence caveat and test this mapping before the formal run.
