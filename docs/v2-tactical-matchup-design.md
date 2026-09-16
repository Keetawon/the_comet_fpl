# Tactical Matchup V1: single formal development contract

Config: `config/v2_tactical_matchup_evaluation.yaml`. Read the linked
[state](v2-tactical-state-design.md) and [style forecaster](v2-next-match-style-forecaster-design.md)
specifications. The owner specifically authorizes reopening tactical architecture; this does
not reinterpret the old in-sample style audit or any frozen weighted-blend result.

## Exact incumbent and single new architecture

Primary comparator is the CURRENT prospective `TrailingGoalsAttackDefence`, source in
`validate/baselines.py`, used by `jobs/prospective_points_v1.py:prospective_team_scored`.
It fits all prior archive goals (no last-N cap, no decay), fixed six-match league shrinkage,
historical league home/away goal means, neutral missing-club ratios 1/1, floor .05.
Returning clubs retain stable-code goals history. Empty-history home/away priors are1.4/1.2.
Its name must not be mistaken for the weekly goals+xG model or dynamic V4. It currently reads
archive outcomes, not live/SDP outcomes. No operational consumer is changed by this experiment.

Incumbent marginals are Poisson support0..10 with the tail folded into10; no rho correction.
Preserve exact latent `rate_for` alongside PMFs; NEVER reconstruct offset rate from the
tail-folded PMF mean. Correction zero returns the incumbent PMF exactly.

The candidate consumes both sides' predicted next-match five-dimensional states (ten main
effects) and ONLY three products: own precision * opponent suppression, own territory *
opponent suppression, own directness * opponent control. No automatically generated
interactions. Fit a regularized Poisson log-rate correction with **incumbent latent rate as
offset**, objective mean Poisson NLL + `penalty*sum(beta²)/2`. All coefficients including
intercept shrink toward zero. Training predictors are sequential OOS style predictions;
training offset is the incumbent prediction actually produced before that historical GW.
Feature centering/scaling is fitted inside each goal fit. Counts remain targets under a
proper goal PMF, not a Gaussian goal regression. Current raw target stats are never features.

Select correction strength from ordered `[disabled,10,1,.1]`. Disabled is exact incumbent.
Minimum160 training rows with complete OOS predicted-state pairs. Select by aggregate
team-side negative log score over last6 observed inner GWs, requiring10 earlier observed GWs.
Each inner GW is predicted after a refit on prior actual events only. Cache those identical
prequential per-penalty fits/predictions rather than recomputing them at later outer cutoffs.
Delayed inner targets are not scored until their event precedes the outer cutoff. Insufficient
history defaults disabled. Choose the FIRST declared option within1e-12 of the GLOBAL minimum
score, favoring zero correction then stronger regularization. This avoids chained pairwise
near-ties and is independent of dictionary ordering. No random splits or future normalization.

Prediction adjustment is clipped to[-.5,.5] log-rate, then apply unchanged floor.05 and
unchanged Poisson support. Newton fitting max40 iterations, tolerance1e-9, deterministic
backtracking; nonconvergence/numerical failure stops, never silently chooses another model.
No new dependency. Fixed seed20260904 owns randomized PIT; fitting itself is deterministic.

## Diagnostic controls, not additional candidate searches

One formal candidate and one materiality gate. To answer the owner's requested structural
questions, retain two **predeclared diagnostic-only** goal corrections on identical outer rows:
(1) recent state only, ten main effects, no interactions; (2) predicted next state, ten main
effects, no interactions. Both reuse the PRIMARY candidate's selected penalty, with no
independent search, gate or promotion eligibility. Fit only their own prior OOS/past inputs.
Comparisons diagnose whether forecasts/interactions add value at the selected regularization;
they do not claim independent optimality. Never switch the nominated candidate to a better
diagnostic arm after the result. These all execute once inside the same claimed experiment.

## Population, scoring and gate

Coverage selected2023-24/2025-26 BEFORE fitting:1520 sides,760 fixtures,76GW folds. No row
drop because target tactical fields are absent; unavailable prediction features fall back.
Primary goals remain trusted archive recorded goals. P(CS) is exactly reciprocal opponent
PMF[0], not an independently fitted classifier. CS venue/promoted slices use DEFENDING team's
context, unlike own-score P0 slices. Retain both directions to prevent reporting confusion.

Primary requirements: >=1% relative goal NLL improvement AND >=1% relative CS Brier improvement
against exact incumbent; CRPS non-regression; no full-season NLL/CS Brier regression; randomized
PIT80 error<=.05; identical populations; zero leakage. Strong supported result needs ALL.
Directional improvement missing any bar: INCONCLUSIVE. Material worsening (>=1% NLL or CS
Brier regression), or no dimension improving style MSE over persistence: REFUTED. Otherwise
INCONCLUSIVE. SUPPORTED is development-only, never promotion.

Retain overall, eligible season, GW1-6/GW7+, home/away, promoted/established, current-state
cold start(min count=0), confidence high(min both-side count>=3)/low. A style-error-risk slice
uses mean prior available OOS standardized squared style error over each club's last5 events,
high>1/low<=1, otherwise unknown; NEVER classify its predictor using current target error.
Metrics: NLL, CS Brier/reliability, CRPS/RPS, PIT80/histogram, mean error, MAE, rate mean/SD,
within-GW Spearman, full paired fixture losses, row-weighted GW-clustered SE/95% interval.
Uncertainty is descriptive: no serial-dependence/researcher-season-reuse adjustment.

## Provenance / execution

Source DB `data/fpl.duckdb` hash pinned in config, opened read-only with no WAL. Operational
daily DB is NOT used or changed. Hash config, audit, exact canonical source versions, all model,
reader, scorer, incumbent and prospective adapters, skills/contract docs, and frozen prior
results. Record clean HEAD/runtime/UTC/seed before and after. Commit implementation/tests/design
BEFORE the formal invocation; refuse dirty worktrees and any prior durable claim/result.

Before claiming candidate: reproduce all incumbent PMFs and identities/outcomes on the selected
population against retained `v2_corroborated_zero_sot_development.json` at1e-12, and against
the actual prospective helper. Score retained reference on this selected population rather
than comparing a three-season aggregate to two seasons. Failure stops before candidate fitting.
Reserve durable exclusive one-run claim in ignored `data/evaluation-claims`; interruption does
not authorize restart. Retain every side's incumbent/candidate/diagnostic fullPMFs, predicted
styles, outcomes, reciprocal CS, fold parameters/scalers and timing guards. Atomic no-clobber
result publication only after provenance recheck. Old results are never rewritten or rerun.
