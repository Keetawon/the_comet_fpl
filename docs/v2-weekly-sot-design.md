# Real SOT on the weekly-inner control: preregistration v1

Owner-authorized 2026-09-07. Status at registration: **not evaluated**.
Candidate: `retrospective_goals_xg_sot_weekly_inner_selection_v1`.
Control: `retrospective_goals_xg_weekly_inner_selection_v1`.
Evidence class: `retrospective_backfill_development`; promotion forbidden.

## One question

Does real historical SDP SOT add predictive information beyond goals plus existing archive
xG when BOTH models use the already-frozen weekly-inner refitting procedure? This is a
post-result development hypothesis on previously inspected seasons, not independent
confirmation. Previous SOT candidates and the previous weekly-selection result stay frozen.
Do not run their formal entry points, reinterpret their verdicts, or tune this successor
after seeing its outer results.

Only the SOT signal is added. No territory, box touches, possession, passes, xGOT, player
features, defensive-contribution model, new model family, new xG provider or average
imputation. Keep old data and retained SDP captures regardless of the result. A wider
spread of predictions is not itself evidence of better predictive accuracy.

## Exact inherited model and source

Reuse the frozen weekly selector methods and multi-signal attack/opponent-defence/venue
ratings without editing their files. The new validation-only class has exactly three
fixed signal specifications: archive `goals`, archive `expected_goals`, and signal name
`shots_on_target` from `shots_on_target_corroborated`. The control is the old weekly
candidate, NOT `retrospective_goals_xg_control_v1` with frozen-inner selection.

The fixed corroborated-zero policy is inherited unchanged from
`config/pl_sdp_sot_zero_interpretation.yaml` and `results/pl_sdp_sot_zero_audit.json`.
Raw NULLs remain NULL. Separately interpreted omitted zeros require the already-audited
version-specific corroboration; no new zero rule or team average is introduced here.
Other shot components/FPL proxies are audit evidence only, never fitting columns.

Canonical SOT version: earliest successfully captured complete whole match-stats payload,
ordered by original `fetched_at` then `payload_id`, before inspecting SOT. Preserve original
capture ID, known-at, body SHA, crosswalk, provider match ID and permanent club identities.
Do not substitute the operational latest-revision PIT view: that would change another
scientific input. Historical later capture is explicitly permitted only in this separate
retrospective validation capability; strict production `known_at <= as_of` stays intact.

Use the unchanged frozen database read-only, explicitly:
`D:/Personal/workspace/the_comet_fpl/.worktrees/sdp_test/data/fpl.duckdb`.
SHA256: `0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8`.
Do not initialise, stage, or write this DB. The daily ingestion database remains separate.

## Population and event-time protocol

Keep the performance-blind 95% joint-coverage population inherited from the first audit.
No new eligibility decision or changed scored rows. The coverage/interpretation audit is
revalidated without scoring; its historical source counts are:

| Season | Goal sides | Archive xG | Raw SOT | Corroborated zeros | Interpreted SOT | Joint coverage | Scored |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 2021-22 | 760 | 0 | 739 | 21 | 760 | 0% | No |
| 2022-23 | 760 | 488 | 738 | 22 | 760 | 64.2105% | No |
| 2023-24 | 760 | 760 | 754 | 6 | 760 | 100% | Yes |
| 2024-25 | 760 | 760 | 740 | 20 | 760 | 100% | Yes |
| 2025-26 | 760 | 760 | 744 | 16 | 760 | 100% | Yes |

Before preregistration, `validate_audit` was rerun read-only on the pinned local DB and
reproduced the frozen coverage/semantics audit, verifying all 1,900 raw payloads with no
raw-value or known-at changes. No model fitting or candidate scoring was performed.

Exactly 2,280 team-sides / 1,140 matches / 114 observed-GW folds across 2023-24 through
2025-26. Target is recorded team goals from the trusted archive, not backfilled SDP goals.
All earlier archive seasons may train; source availability is not prior-history length.
Join SOT only by `(season, fixture, team_code)`, one-to-one, preserving archive rows/xG.

Each target GW uses its first-kickoff cutoff. Training observations require kickoff strictly
before that cutoff and no target-GW identity overlap. Predict the entire GW before any
update. Delayed/DGW legs are in their full target batch; only legs individually kicked off
before a later cutoff enter that later fit. Keep stable team codes across seasons. The
unversioned historical roster/first-kickoff and inherited fixed promoted-prior caveats remain.

## Frozen settings and selection

| Setting | Value |
| --- | --- |
| Half-life order, days | 40, 80, 160, 320, 640, no decay |
| Prior order, matches | 2, 4, 8, 16, 32 |
| Blend | Nonnegative simplex, step 0.25, sums to 1 |
| Inner holdout / minimum preceding history | 6 / 10 observed GWs |
| Minimum outer history / club history | 8 observed GWs / 3 matches |
| Minimum signal coverage | 0.25 |
| Promoted attack / defence | 0.719 / 1.309 |
| Rate floor / Poisson support | 0.05 / 0..10, inherited folded tail |
| Seed | 20260904 |

Goals select decay/prior FIRST. Then available goals/xG/SOT select blend weights. This is
not a joint grid search. For every setting, refit before each inner holdout GW using only
prior events, predict its whole batch, aggregate log loss by team-side row. No random split,
within-GW updates, full-dataset normalization, or outer-result selection.

Scale each signal by mean goals / mean signal over jointly measured rows in that training
fit; refit the scale within every inner and outer training window. Keep the frozen initial
inner-window signal-availability dimension rule and unavailable-fit weight renormalization.
Order signal names alphabetically and enumerate the existing simplex lexicographically.
Exact-score ties take the first explicit grid setting; no tolerance-based near-tie tuning.
Retain the inherited 160-day / 8-match no-selection fallback and equal available blend when
inner history is insufficient. An absent SOT signal drops out and the model reduces to
weekly goals+xG. Outer-season promoted context, season transitions and returning-club
handling are unchanged. SOT is a count input, not a new target distribution; output stays
a proper Poisson GOALS distribution, with no independently fitted dispersion parameter.

## Metrics, shared slices, and decision rule

Primary: mean negative log score (lower is better). Also retain CRPS/RPS, randomized PIT-80
and deciles, mean error, MAE, deviance, predictive variance, predicted-rate mean/sample SD,
within-GW Spearman, paired team-side/fixture/GW losses, and GW-clustered standard error.
The clustered sandwich uses the prior row-weighted formula; its normal 95% interval is
descriptive, not serial-dependence-adjusted or a correction for repeated research seasons.

Fixed diagnostic slices: season; home/away; promoted/established; early GW1-6/later GW7+;
each season's early/later phase; shared reference cold-start labels; SOT history 0/1-2/3-5/6+.
The frozen weekly result retained legacy-control cold-start labels. Use those same fixed
labels for reproduction and both new score blocks, while retaining the actual engines'
fold parameters and diagnostics. Never silently change a slice population. PIT seed restarts
within each score block as before, so slice coverage counts are not additive.

New diagnostic only: P(goals=0) Brier score and reliability by fixed 0.1-width probability
bins, including counts/mean probability/observed frequency. For a club's clean sheet the
relevant P0 is its OPPONENT's goals PMF in that fixture. Both reciprocal sides are present,
so pooled and full-season zero-goal scores also describe pooled reciprocal clean-sheet
scores, but a home-goals-zero slice is NOT a home-clean-sheet slice. No recalibration,
clean-sheet tuning, or new promotion threshold is derived from this diagnostic.

Development gate, frozen before evaluation: >= **1% relative mean-log-score lift versus
the exact weekly goals+xG control**, no aggregate CRPS regression, PIT-80 absolute error
<=0.05, no per-season log-score regression, identical populations, zero event/GW leakage.
With the stored control, 1% requires candidate mean log score <= **1.471784370454**.
If log lift <=0, verdict `REFUTED`; a positive lift missing any gate is `INCONCLUSIVE`;
all gates passed means `SUPPORTED_FOR_DEVELOPMENT`, never production promotion.

If lift is below 1%, retain the existing model/defaults as the owner requested. Even a
pass requires prospective confirmation and separate owner approval before operational use.
Retain new raw SDP data in either case: rejecting this fitted SOT increment is not a reason
to delete evidence or stop revision capture. Diagnose level/ranking/rate spread separately;
do not call reduced spread inherently worse or claim a new dispersion mechanism.

## Clean provenance, reproduction, one run

Commit infrastructure first, then implementation/tests/config/this preregistration. Require
empty `git status --porcelain`; no dirty override. The explicit DB, coverage, canonical
manifest, zero audit/policy, inherited configs, frozen results and relevant implementation
sources are SHA256-pinned or snapshotted. Record actual Python/library versions, clean HEAD,
new config hash, source hashes, DB hash, UTC start/end, seed, folds/rows and evidence class.

Reproduce ONLY the weekly control through its existing pure walk-forward function, not an
old formal entry point. Check its ordered fixture identities/outcomes, all PMFs and score
blocks, common archive training hashes, parameters, fitted scales, inner scores/diagnostics
and guards against the frozen weekly artifact at absolute tolerance **1e-12**, with exact
discrete counts/identities. A failed check stops before new candidate fitting.

After reproduction and snapshot recheck, reserve an exclusive durable execution claim for
this NEW candidate. Run the candidate once; do not silently retry after interruption or
retune from outer results. Recheck clean provenance before exclusive result publication.
Retain all fixture PMFs/outcomes, shared contexts, per-fold parameters/scales/inner scores,
input hashes and distinct SOT version-identity hashes. Keep the failed result if it fails.

Pin the old weekly result to
`79f3a0815271a95cd0e39874aaa20fa89d3b1df0875a5e780c0317a961424d35`;
canonical SDP manifest to
`084137d2e03babbf9d8361e49be0f23ba19ae3baed34c5d9d0605264ea37057f`;
coverage report to
`7b37ce3998f1f252a6b1d7ea7978b1f916f7bf414eb8c942eae87e2bc50c5a6d`.
Additional exact contract/policy hashes are in the new YAML and frozen inherited contracts.

Write only the new `results/v2_weekly_sot_development.json` and subsequent development note.
No old result/config/model edit, production/default/optimizer switch, second candidate,
territory experiment, main merge, rebase, PR or push. Local additive commits are authorized.
