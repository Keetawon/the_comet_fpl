# Chance creation → quality → goals: preregistration 1.0

Candidate `retrospective_chance_creation_team_environment_v1` is a NEW family. No old tactical
candidate is rerun or reinterpreted. Its config is `config/v2_chance_creation_evaluation.yaml`.
No outer candidate fitting/scoring has occurred when this design is committed. All parameters
below are fixed; there is no outer-guided or nested grid search in this bounded V1.

## Targets and coverage-only population

`results/v2_chance_target_audit.json` licenses goals, existing FPL/archive summed player xG and
SDP `totalScoringAtt`. The source database is read-only and hash-pinned. A complete 380-fixture
season qualifies when at least 95% of its sides have paired goals+xG+shots and an earlier complete
PL season exists. Measured joint coverage: 2021-22 0/760; 2022-23 488/760; 2023-24, 2024-25 and
2025-26 each 760/760. Thus the last three seasons supply ALL 2,280 team-side rows / 114 GWs.
No row is dropped for a missing recent predictor; use exact incumbent fallback. The previous
tactical experiment's 2024 exclusion was about complete five-dimensional observed targets;
this NEW chance-target coverage rule is decided without inspecting this candidate's scores.

SDP total attempts are provider-labelled, development-licensed, not independently verified
against every PL UI definition. xG remains the trusted existing archive signal, never later SDP
xG (coverage only 6/760, 340/760, 760/760 in these seasons). Their ratio is an explicit cross-source
development measure, not provider-reported shot quality. Missing != zero. Other retained target
coverage, explicit zeros and missingness appear in the audit. Big chances are too incomplete to
require; box/inside-box counts are not extra targets. No inferred zero, average fill or target repair.

## Frozen upstream and temporal boundary

Reuse the **stored out-of-sample** tactical state predictions in the immutable numeric1 result,
SHA `d52973687d2983c9fc3159365e8dde865ac60a7b1ddb0d0db6e5dc3268efd11c`.
Its five continuous dimensions are attack precision, dangerous territory, control, directness,
defensive suppression. Last-five newest-first weights 1,.707,.5,.354,.25, n/(n+2) league-prior
pooling, season-reset recent state and fixed ridge-1 delta forecaster remain unchanged.
All 3,800 historical side predictions / 189 batches exist, including training-only 2024 rows.
They were generated prequentially independently of the old goal-correction hyperparameter search.
Do not read old goal-correction coefficients, outer performance or same-target actual style into
predictors. Verify source hashes, exact identity/reciprocity, one cutoff per GW, state and style-fit
event boundaries before fitting. Original raw capture IDs, SHA, known_at and version policy remain
retained. This is retrospective backfill development, NOT proof of historical deadline knowledge.
No production PointInTimeView interface or global escape flag is added.

Each GW is one batch. Only previous-batch records whose actual kickoff precedes the new cutoff
are visible. Postponed legs are not absorbed early just because their nominal GW was predicted.
Prediction cutoff is the existing first-kickoff proxy (equal to the first fixture kickoff, strictly
after every eligible source event); preserve it for exact incumbent comparability and label proxy validity.
Any downstream conversion fit uses earlier OOS chance predictions, never an in-sample chance fit.

## Two chance means and strongly pooled conversion

Both models use exactly 13 prematch inputs: own five predicted dimensions, opponent five,
venue indicator, log own incumbent rate and log reciprocal opponent incumbent rate. No automatic
pairwise interactions. Fold-local centering/scaling only; every scaler and coefficient is retained.
Minimum 160 measured rows per stage. Fixed ridge penalty 1.0 (mean loss plus half-ridge penalty,
penalized intercept, matching the existing ridge convention) for both stages, no search/ties.

Volume is a Poisson log-mean regression of measured SDP shots, with fold-local pooled mean shot
offset. Quality is a **fractional response quasi-Poisson mean**, not a count distribution for xG:
fit measured archive xG with observed shot exposure times fold-local sum(xG)/sum(shots) offset.
Never round xG. Zero-shot rows have undefined quality and do not fit that stage; positive xG with
zero shots fails closed. At prediction, use unit shot exposure to get xG/shot, clamp prediction
to [1e-6,1] while retaining unclipped values, then multiply by predicted shots. Targets are never
clipped. No positive measured fold anchor means no fit and incumbent fallback. The quality stage
is trained on observed exposure, not in-sample predicted shots; the composed xG prediction for
every historical training fixture is nevertheless fully OOS in event time.

Conversion is GLOBAL league-only, deliberately excluding recent player/team finishing flexibility:
`(sum(prior observed goals)+20)/(sum(prior OOS predicted xG)+20)`, prior mean 1 and prior exposure
20 expected-xG units. At least 160 prior measured goals/xG/shots rows with OOS chance predictions
are required. No goals select its strength. Raw goal rate = volume × quality × conversion; then
the existing .05 floor and Poisson 0..10 (tail folded at10) apply. Zero opportunity is zero BEFORE
the explicit inherited floor. Fallback is exact incumbent PMF, never a reparameterized substitute.
The positive log-link predicts positive means; an all-zero fold anchor does not manufacture a zero
forecast and instead triggers the stated incumbent fallback. Exact zero observed labels remain
measured zero. CS is the reciprocal opponent PMF mass at0, not an independent classifier.

## Exact incumbent and formal discipline

Primary comparator is current `TrailingGoalsAttackDefence`: expanding prior goals with six-match
league pooling, existing promoted/cold-start behavior, venue, .05 floor, Poisson support0..10.
Reproduce all 3,800 cached incumbent PMFs and eligible 2,280 rows against BOTH the retained path
and current `prospective_team_scored`, tolerance1e-12; fail before reserving the candidate if any
identity/outcome/cutoff/count/PMF differs. No historical research winner replaces this comparator.

Run ONE new candidate after a clean commit. Refuse dirty worktree, wrong branch, existing claim,
existing result, WAL, changed DB/config/source/upstream/coverage hashes. Reserve an fsync-backed
exclusive claim before chance fitting; failed numerical execution consumes the identity and retains
failure evidence, requiring a new explicit amendment rather than a silent retry. Recheck provenance
before publication. Record Git/config/model/database/evidence hashes, seed20260907, UTC time,
exact rows/cutoffs/PMFs, source versions, scalers, OOS training-key hashes and conversion provenance.

Compute budget: 189 batches × at most2 small 14-coefficient fits =378 bounded fits; no combinatorial
grid. Each Newton fit has fixed iteration/backtracking limits and must certify convergence. Existing
numerical precedent suggests minutes, not an unbounded search. Synthetic tests, not real candidate
scores, establish solver behavior. The full historical upstream cache is immutable input, not refit.

## Gate, diagnostics and interpretation

SUPPORTED requires BOTH >=1% NLL and CS-Brier relative improvements over exact incumbent,
nonregressing CRPS, no full-season NLL/CS regression, PIT80 absolute error<=.05, same population
and zero leakage. REFUTED if either primary score regresses >=1%; otherwise INCONCLUSIVE unless
all gates pass. Every verdict remains development-only; no promotion.

Report overall, each season, GW1-6/GW7+, home/away, promoted/established, cold-start (<3 measured
recent matches in any dimension), and confidence-high (all five measured recent matches both sides)
versus low. Score NLL, CRPS, CS Brier/reliability, PIT80, mean error, MAE, rate SD, within-GW rank.
Retain paired fixture losses, per-GW averages and GW-clustered SE/normal intervals (not adjusted for
serial dependence), all PMFs and latent rates. Chance diagnostics compare shots/xG with available
same-club trailing-five measured means, quality with its fold-local pooled anchor, xG with incumbent
goals rate (explicitly not a pure xG model), and report conversion distribution and fixed volume/
quality/conversion attribution. These are diagnostic only; do not prune weak dimensions and rerun.
Any post-result successor gets a separate preregistration. The accepted-component synthesis rule
remains passed successor else exact incumbent; this phase does not activate a production component.
