# One bounded disciplinary component: development only

Candidate `retrospective_exposure_pooled_disciplinary_v1` is separately registered in
`config/player_disciplinary_evaluation.yaml`. No formal candidate evaluation has run.
The current composer supplies zero disciplinary outcomes; this remains the incumbent,
but beating a degenerate zero-risk forecast is not sufficient evidence of useful player
modelling. An additional fold-local position/exposure control is therefore also mandatory.

## Target audit and scoring boundary

The read-only audit at
`D:/Personal/fpl-operations/verification/disciplinary-target-audit-20260907T090400Z/result.json`
measured 138,707 retained archive player-fixtures: 131,252 `(yellow=0, red=0)`,
7,228 `(1,0)` and 227 `(0,1)`. There are no missing card labels or `(1,1)` rows.
Ten rows have cards with zero recorded minutes (nine yellow, one red); all remain labels.

The [official FPL rules](https://www.premierleague.com/es/news/4661029) independently state
that red-card deductions already include yellow-card deductions, and explicitly include
receiving a card in the fantasy definition of playing. The local HTTP 200 body was retained
at **2026-09-07T08:55:37.618092+00:00**, SHA256
`7614a64985ae9fdc6f59d1e12dcd15b1234b96886486d8d73b61eee69a753728`.
The directory name is an operator run identifier, not the capture timestamp.

Thus the model predicts **FPL-encoded scored outcomes**, not a physical card-event process.
Physical first-yellow/second-yellow/straight-red sequences are not identifiable from the
archive columns. No independent yellow/red Bernoullis, fabricated mutual-exclusion claim,
or automatic recoding of a future joint target is allowed. A new `(1,1)` encoded target
fails the coverage preflight and requires source interpretation, not silent erasure.

Only loaded scoring-rule values are used. The existing points calculator remains unchanged;
its nonappearance card scoring is correct for observed bench bookings. The owner requested
the new predictive composer to assign bin-zero exactly no cards. That **on-pitch-only
approximation** is not the complete rule and must never erase bench-card observations.
All-row card scores include them with the predeclared probability floor. Conditional
appeared-row diagnostics report the limitation separately.

## Football process and restrained pooling

Inputs are prior appearance exposure and scored disciplinary counts, permanent player code,
recorded historical position, and the same prospective-selector minutes proxy for both arms.
For this first component, role, tactical and workload effects are **not fitted**. This isolates
whether hierarchical personal tendency adds useful information beyond position and exposure.
It makes no claim about those contextual mechanisms or current-match card timing.

For each scored cause (yellow outcome or red outcome), the league rate per minute is
`(events + .5)/(appearance_minutes + 90)`, using prior rows only. The position rate is
pooled toward that league rate with 4,500 exposure minutes. Player/position rates pool
toward their position with 4,500 minutes for yellow and **45,000 for rare red outcomes**.
No short trailing card streak, per-player tuning or future-season estimate is used.
Transfers preserve permanent player identity; a change of recorded position starts its
new position-specific personal pool. Historical zero-minute cards remain separately counted,
not assigned invented on-pitch exposure or used in rate denominators.

For prior-fitted hazards `h_y`, `h_r` and the fold-local mean exposure `m` of a predicted
minutes bin, let `a = 1-exp(-(h_y+h_r)*m)`. The conditional categorical PMF is
`(1-a, a*h_y/(h_y+h_r), a*h_r/(h_y+h_r))`. The minutes-zero bin is exactly `(1,0,0)`.
Marginalize over all four shared predicted minutes probabilities exactly once. Empty
training bins use the existing contract representatives `(0,59,89,90)` as an explicitly
declared model fallback, not as imputation of a provider's missing minutes. Short observed
exposure after a dismissal can be endogenous; the hazard approximation does not claim
independent card timing or causal effects on substitution/conceded-goal risk.

## Population, comparison and gates

Use the exact shared 114-GW, 86,755-row 2023-24 through 2025-26 reference population.
The 821 price-proxy-dependent rows and 85,934 non-proxy rows are separately scored.
All history must precede the first-kickoff cutoff proxy and exclude the entire target GW;
postponed earlier-GW events in the future cannot enter. Histories before 2023-24 are allowed
as prior training observations, not scored target additions. No real-deadline reconstruction
claim is made. All rows, cold/established, per-season, position, venue, early/later, and
observed-exposure diagnostics are frozen before scoring. Excluding the 821 rows is strictly
diagnostic and never changes the nominated population or selected model.

One deterministic candidate, no grid or inner tuning: at most 114 inexpensive count-summary
fits. Both the exact zero-card incumbent and position-only informative control use the same
minutes PMFs. The additional control uses precisely the candidate's fitted position hazards
without personal shrinkage. The primary joint log score must improve by at least 1% versus
both controls, and yellow log loss by 1% versus the informative control. Yellow Brier, red
log/Brier and every full-season joint log score must not regress versus the informative
control. Both marginal absolute calibration biases must be <= .02; zero leakage and full
coverage are mandatory. Reliability and rare-event average precision are diagnostic only.
Normal GW-clustered paired-loss intervals are reported, not used for post-hoc tuning.

These new disciplinary criteria do not amend Stage B/C's 181-fold requirements or any frozen
previous contract. A numerical pass licenses only the predeclared development synthesis,
never production. The runner must pin this config, model, source audit, database, completed
minutes-cache manifest/independent reproduction, Git clean HEAD and all frozen evidence;
reproduce controls, reserve an exclusive claim, score once, and retain full three-state
PMFs and conditional-bin distributions. A failed result is not retried or retuned.

## Composer boundary (implementation still pending)

Any optional disciplinary component must be absent by default and prove bit-exact legacy
composition with it disabled. Extra card draws must use a separate deterministic RNG stream
so they do not perturb incumbent goals, assists, saves, DC or bonus draws. Apply the scored
card outcome to an appeared player's total before final support clamping. Existing BPS
residuals already absorb unmodelled card effects; do not add a second card BPS penalty or
begin a new BPS study. The unchanged conceded-exposure approximation does not model continued
post-dismissal conceded penalties. These are declared limits, not silently changed contracts.
