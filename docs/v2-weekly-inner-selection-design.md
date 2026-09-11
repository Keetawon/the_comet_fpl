# Goals+xG weekly inner selection: preregistration v1

Status: development-only, frozen before formal outer scoring. Owner-authorized
2026-09-06. Candidate: `retrospective_goals_xg_weekly_inner_selection_v1`.
The source diagnosis is in `v2-weekly-inner-selection-diagnostic.md`.

## Question and single change

Does selecting the existing goals+xG model's settings using weekly inner refits,
matching the outer refit schedule, improve its goal distributions? This hypothesis
was generated after inspecting previous development results. It is not independent
confirmation and does not establish the cause of early-season weakness.

The exact control is `retrospective_goals_xg_control_v1`. Keep its existing staged
search: select half-life/prior on **goals**, then select goals/xG blend weights.
Only the inner refit schedule changes. A joint search is explicitly out of scope.
The original `MultiSignalTeamEngine` implementation remains byte-identical and
available. A separate validation-only `WeeklyRefitTeamEngine` reuses its estimator.

## Population, inputs and outputs

- Evidence class: `retrospective_archive_development`, never promotion evidence.
- Provider/inputs: existing `fpl_archive` **goals and expected_goals only**. No SDP
  observations, imputation, SOT, xGOT, territory, possession, DC or player features.
- Target: unchanged historical recorded team goals; permanent `team_code` identity.
- Scoring seasons: **2023-24, 2024-25, 2025-26**, inherited from the original
  performance-blind 95% joint-coverage selection. Do not reselect seasons or rows.
- Exactly **2,280 team-fixture predictions, 1,140 fixtures, 114 observed-GW folds**.
- Historical training: all archive matches with kickoff strictly before the current
  cutoff, expanding across seasons. NULL is not zero; no changed targets.
- Outer cutoff: target observed GW's first kickoff; all its fixture legs share that
  state. Minimum outer history: eight observed GWs. No random or contiguous-GW split.
- Same multiplicative attack/opponent-defence/venue ratings and goal-scaled blend;
  same Poisson output, support 0..10 with inherited tail handling and rate floor 0.05.
- Historical roster/first-kickoff knowledge-time proxies and fixed-prior caveats
  remain. No capture timestamps, strict PIT, prospective forecasts or defaults change.

## Frozen search and weekly semantics

Inherit the SHA-pinned `config/v2_real_sot_retrospective_evaluation.yaml` engine,
walk-forward, metrics, gate and seed. Its SOT candidate is **not** instantiated.

| Setting | Frozen value |
|---|---|
| Half-life order (days) | 40, 80, 160, 320, 640, no decay |
| Prior strength order (matches) | 2, 4, 8, 16, 32 |
| xG weight order | 0, 0.25, 0.50, 0.75, 1; goals weight = 1 - xG weight |
| Inner holdout / minimum preceding GWs | 6 / 10 observed GWs |
| Minimum club history / signal coverage | 3 matches / 0.25 |
| Promoted attack / defence prior | 0.719 / 1.309 |
| Seed | 20260904 |

1. Obtain the same six holdout keys from the inherited `_inner_split`.
2. For each decay/prior setting and each holdout GW, filter the **original outer
   history** to kickoff strictly before that inner GW's first kickoff. Fit goals
   ratings and predict all target-GW sides without any within-GW update.
3. Aggregate negative log score by **scored team-fixture row**, not equally by GW;
   select decay/prior, then repeat weekly signal/scaling fits for blend selection.
4. Each signal's scale is mean goals / mean signal over its current jointly measured
   training rows. Reference exponential decay to the latest current training kickoff,
   exactly as before; no full-data normalization or future match observations.
5. Delayed/DGW legs are scored together in their target batch but only enter later
   fits once their individual kickoff precedes that later cutoff. Never blindly
   append a full previous GW; admit delayed earlier non-holdout legs when available.
6. Keep outer-prediction-season promoted-prior context unchanged throughout inner
   selection, including across summer. Keep full-fit signal eligibility and existing
   unavailable-signal renormalization. This tests the update schedule only, not every
   difference between historical inner context and prospective deployment.
7. Exact-equality ties retain the first setting in the explicit orders above (no
   tolerance-based near-tie tuning). Signal names are alphabetical, then the existing
   simplex is lexicographic. Insufficient-history fallback remains 160 days / 8
   prior matches; insufficient blend history is equal available weights. Unavailable
   xG does not become zero. Cold-start and returning-club handling remain inherited.

## Reproduction prerequisite and provenance

Complete implementation, synthetic tests and this contract, commit, and require an
empty `git status --porcelain` before any formal pass. No `--allow-dirty` option.

First run **only the unchanged control** on all eligible folds. Compare its ordered
fixture identities, goals, venues, cutoffs, slice labels, every PMF, fold parameters,
signal fits, overall and fixed-population slice scores to the SHA-pinned corroborated
SOT artifact's **control records only**, also checking the first SOT artifact's
control aggregates. Exact discrete identity/count agreement and absolute numeric
tolerance **1e-12** are required. Stop before candidate fitting if reproduction fails.
Do not rewrite either reference or run an old SOT candidate.

After control reproduction, reserve one durable local execution claim for the new
candidate, then run its outer evaluation once. A started candidate is not silently
retried after interruption. Results are write-once and postflight rechecks clean Git,
HEAD, config, model/source, database and frozen-evidence hashes before publication.

Retain Git HEAD, UTC start/end, config/base-config SHA256, database SHA256, relevant
source SHA256, coverage-reference SHA256, all frozen result hashes, seed, eligible
seasons, exact cutoffs/counts and per-fold input hashes. The unchanged historical SDP
manifest may be fingerprinted as population provenance only; SDP is not a model input.

## Metrics, diagnostics and gate

Reuse the unchanged score implementation: mean log score (primary), CRPS/RPS,
randomized PIT-80 and deciles, mean error, MAE, mean predictive variance/deviance,
predicted-rate mean and sample SD, within-GW Spearman. PIT draws restart at the fixed
seed for each slice as in the control; slice PIT counts are not additive.

Retain all fixture PMFs/outcomes, paired team-side loss differences, paired fixture
loss sums/means, per-GW loss differences, both selected inner scores, and old/new
selected half-life, prior strength and xG weight for every outer fold.

For row-weighted paired mean difference d, N team-side rows and G GWs, report the
cluster-sandwich SE:

`sqrt(G/(G-1) * sum_g((sum_i_in_g(delta_i) - n_g*d)^2)) / N`.

Also retain the old unweighted-GW-mean diagnostic under an explicitly different
label. Neither accounts for serial dependence across GWs, so neither is independent
confirmation or a promotion test.

Fixed slices: season; GW1-6 versus GW7+; home/away; promoted/established; control-
defined cold start/established. No slice-driven tuning. Report each season's early
and later phase too, as a diagnostic only.

Gate inherited unchanged: **at least 1% relative log-score lift against exact
control**, zero aggregate CRPS regression, randomized PIT-80 absolute error at most
0.05, no season log-score regression, identical population, and zero event/target-GW
violations. Passing yields `SUPPORTED_FOR_DEVELOPMENT`; a nonpositive log lift yields
`REFUTED`; a positive lift missing any gate yields `INCONCLUSIVE`. None is promotion.

Post-result read-only parameter diagnostics: distributions and cross-selector
disagreement counts; within-season adjacent-GW changes (exclude summer boundaries);
xG-weight-zero frequency; Shannon entropy in bits, per parameter and combined setting;
early-season selections. Entropy measures selection diversity, not automatically
harmful instability. Do not tune after observing any result.

Recommend exactly one subsequent direction based on the frozen result; implement no
second candidate, no territory/SOT/DC expansion, and no production/default change.
