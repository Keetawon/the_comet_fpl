# Workload / broad-role minutes offset V1: evaluation preregistration

Candidate `retrospective_workload_role_minutes_offset_v1`; development evidence only.
Exact evaluation config SHA256:
`6d483e21d2a55015b75d7378551fe80fb2fa0d7c1a36b02babe182cfe7ac97ba`.
This document and the exact config/source bytes must be committed cleanly before the
single formal claim. No candidate has been fitted or scored by the prerequisite audit.

## Question and exact comparator

Does a bounded correction using recent witnessed competitive minutes and the frozen
prequential broad-role forecast improve the CURRENT prospective minutes-selector PMF?
The comparator is `retrospective_current_minutes_proxy_v1`, not the best historical
minutes research candidate. Every control PMF is read from the frozen 114-fold cache;
the original V3 minutes model is not refitted. Seasonal appearance, current-club
selection, learned constants, four bins and original selector/price lineage remain
unchanged. The current learned constants have already seen historical development
evidence; this is not a newly unseen prospective benchmark.

The owner's historical archive-value cold proxy affects 821 reference rows (327 / 224 / 270
by season). It is an explicit identity/price reconstruction limitation, not a
historical live registry or verified deadline price. Both arms use identical controls.
It never becomes a workload or role predictor; cold rows are exact-control fallbacks.

## Population fixed by feature-only coverage

Use exactly 2023-24,2024-25,2025-26;114 complete target-GW batches and86,755 player-fixture
rows (29,725 / 27,283 / 29,747), including every recorded zero-minute nonparticipant.
DGW legs remain distinct. No player is excluded for missing workload, missing role,
unknown registration, a failed cup interpretation or a cold start.

The read-only 2026-09-07coverage audit SHA
`770206f0c151694501cc06b95631b554b172b956e8cfe10363481f474f3cf982`
measures 9,551 feature-active 2025-26rows (32.107% of 29,747) before any candidate fit.
The other 2025-26rows comprise 8,169 role-history-cold,11,627 unavailable-positive-workload,
270 current-control cold starts and130 witnessed zero-nominal-volume fallbacks.
All 57,008 earlier-season rows are unchanged-control fallbacks because this workload/role
capture covers 2025-26only. Those 76 nominal folds are NOT additional workload evidence.

All 574 retained six-competition match bundles are selected under the original-capture
earliest-complete-final policy and the pinned V3 interpretation.39 cup finals with
aggregate/penalty/extra-time result labels remain included. Invalid whole-match
interpretations remain explicit unknown evidence; their affected windows are not
relabelled as rest or zero workload. No exact rest-hours predictor is licensed.

## Fixed algorithm and stacking

The separate `player-workload-minutes-design.md` fixes the pure algorithm in full.
Four predictors, in GK/DEF/MID/FWD order, are:

`min(witnessed_positive_nominal_minutes_in_previous168hours /180,1) * P(role|hypothetical_start)`.

The role input is the frozen transition-role candidate, NOT its better matched-EWMA
persistence diagnostic. The Phase C result supported its predeclared primary controls
but did not support transition attribution against that stronger diagnostic. There is
no post-result substitution of the role arm here.

For minutes-bin probabilities, `q[k] proportional to p_current[k]*exp(beta[k] dot x)`;
bin 0 coefficients are zero, giving 12 fitted coefficients. Fixed ridge 1 on mean categorical
NLL, no intercept, step 2/3, max 200 updates, gradient-infinity tolerance 1e-10, zero
initialization. No grid, random split or hyperparameter selection. Require 8 eligible
prior GW batches AND 200 eligible prior rows; otherwise keep the exact control.
Nonfinite values/nonconvergence consume the claim and produce an immutable failed
artifact, not retuning or an unreported second run.

Every upstream role prediction comes from its own pre-GW state and retains original
source versions/capture timestamps/interpretation timestamps. The target's actual XI,
role, minutes or formation never enters its predictor object. All target-GW fixtures
are excluded from workload/role sources; earlier kickoffs in a DGW cannot update later
legs. All known events must precede cutoff. Without a verified whistle, kickoff + 6 hours
must strictly precede cutoff. The same conservative margin applies when historical
minutes labels enter a later correction fit. This is an exclusion proxy, not proof of
actual match-end time, a provider SLA or prospective permission.

Normalize no feature using future/full-dataset values. The capped volume and frozen
role probabilities need no fitted scaling. Original NULL/zero distinctions remain.

## Scores and unchanged stricter gate

Predict every target GW as one batch, then absorb its labels. The proper-scoring
functions are the unchanged Stage B functions: NLL with scoring-only 1e-12 floor,
ordered-category RPS, Brier-any, Brier60+, randomizedPIT-80, reliability bucket counts
and within-(season,GW,position)Spearman60+. Fixed PIT seed 202627 and original row order.
Undefined ranking remains NULL and fails an applicable ranking gate.

Require at least 1% NLL lift versus exact current control, no aggregate RPS/either Brier
regression, no starter-ranking regression, and no season-level NLL regression against
that same control. Also retain EVERY original Stage B v1.4 gate through its existing
gate helper: 1% versus best required baseline NLL, best-per-metric RPS/Brier bars,
best-defined starter ranking, PIT-80absolute error <= .05, full prediction coverage,
zero leaks, per-season comparison to its globally chosen baseline, and181 minimum folds.
Reproduce the four unchanged closed-form baselines on these same rows with fold-local
prior history; do not compare different-population five-season headline numbers.

**114 nominal folds do not meet 181.** No synthetic padding or lowering that threshold.
Therefore the candidate is full-gate INELIGIBLE and never a passed synthesis successor,
even if every numerical diagnostic improves. Verdict is REFUTED if overall relative
NLL lift is below -1%; otherwise INCONCLUSIVE. Production/default minutes remain unchanged.

Report all proper metrics overall and by season, position, venue, GW1-6/GW7+, current
cold start, direct price proxy, prior-only transfer status/history cohort and
feature-active status. Compare paired per-row loss with GW-clustered uncertainty
both over all 114 nominal folds and separately over the 38 workload-season folds.
The cluster calculation is not a serial-dependence adjustment.

## Clean, write-once provenance and retention

Inputs are explicit: immutable original archive DB, separate V3 operational DB,
current-minutes manifest + folds, C result + 38 role fold files, V3 stage report and coverage
audit. No DB is copied over, default path changed or database written. Reject WAL,
hash/source drift, wrong branch, dirty worktree, missing targets and changed PMFs.
First validate full population and exact cached-control PMF equality; only then
reserve the candidate's exclusive claim in the shared Git common directory.

Retain source/config/tests/frozen-results/document hashes, current HEAD, both database
hashes, all original price/role/version references, cutoff and timestamps. One immutable
file per fold carries every player-fixture PMF for both arms and four baselines,
observed minutes/bin, feature evidence, source versions, fit coefficients/objective trace,
training hash and all fallbacks. Record actual ending provenance and fail before final
success publication if any source/HEAD/database changed. Claim survives failure.
All 114 current-minutes and 38 role cache fold files are hash-checked again at
postflight, alongside the original role source-version ledger. Completion time is
recorded only after scoring summaries and the final provenance check finish.
There is no allow-dirty, second candidate, automatic promotion or retuning route.

## Bounded computation, not a performance trial

The coverage pass took 37.87 seconds. At most 38 workload-season folds can fit a
correction, each using at most 9,551 eligible rows and 200 updates plus its final
gradient check. The eight-prior-batch rule and growing history make these deliberately
loose bounds. A synthetic-only benchmark with 9,551 invented rows, fixed zero
coefficients and three gradient evaluations took 0.03698 seconds per gradient: the
loose 38-by-201 arithmetic envelope is about 282.5 seconds. This excludes reference
baseline/data validation, serialization and I/O, and is not a wall-clock guarantee.
No actual targets or candidate fit were used to estimate it.

The optimizer consumes already validated four-feature tuples. Role lookup and
provenance serialization happen before optimizer iterations, not on every gradient
update. Whole source versions and role batches are shared in memory, not copied into
every gradient row. Numerical nonconvergence never licenses a larger iteration budget.
