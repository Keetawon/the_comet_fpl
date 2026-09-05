# Corroborated omitted-SOT zeros: additive development preregistration

Date: 2026-09-06 (Asia/Bangkok). Status at registration: **not evaluated**.

Candidate: `retrospective_corroborated_zero_sot_team_environment_v2`.
Evidence class: `retrospective_backfill_development`. Promotion is forbidden.

## Question and scope

Does historical SOT, including separately corroborated omitted zeros, improve the same goals+xG
team-goal distribution? This is a new, post-audit development hypothesis, not a correction of the
first candidate's frozen result. The owner authorized investigating missingness and continuing
with this bounded successor. No team-average imputation, territory, SDP xG replacement, new
estimator, selection-procedure change, or production wiring is licensed.

The first SOT result remains inconclusive at its original bytes and provenance. These seasons
have already been inspected: even a successful new result is development evidence, not independent
confirmation. `docs/v2-goals-xg-error-audit.md` records a separate inner-selection hypothesis;
that change is deliberately not included here.

## Source semantics: coverage-only investigation

`results/pl_sdp_sot_zero_audit.json` verifies all 1,900 canonical historical payload content hashes,
raw/staging agreement, the fixture crosswalk, permanent team codes and both sides. There are
3,800 team-sides in 2021-22 through 2025-26. All 3,715 explicitly measured SOT values are positive;
85 omit `ontargetScoringAtt`. None of these omissions alone licenses zero.

The versioned policy `config/pl_sdp_sot_zero_interpretation.yaml` allows a separately interpreted
zero only when either:

1. A manually reviewed match report explicitly corroborates zero SOT for that exact season,
   fixture, permanent team and SDP match identity; or
2. Measured off-target/blocked attempts exhaust the measured positive shot total, the opposing
   FPL goalkeeper SOT-allowed proxy is explicitly zero, and no related target/goal field contains
   positive, malformed or explicitly NULL evidence.

If one shot component is omitted, the other must itself exhaust the total; no missing component
is written as zero. An explicit NULL SOT remains NULL even with an independent report. Invalid
explicit counts fail closed. Explicit non-null SOT always wins and is never replaced. Unresolved
omissions remain NULL. The new column is `shots_on_target_corroborated`; `shots_on_target`, raw
JSON, staging, marts and capture timestamps are not updated.

This is corroboration, not a universal arithmetic identity. Seven explicitly measured SOT rows
have a shot-partition residual of -1; they are enumerated without adjustment in the audit.
West Ham at Wolves has inconsistent components and requires the independent report. The FPL
saves-plus-conceded proxy is not an exact SOT measurement: Opta distinguishes last-line blocks,
ordinary blocks, goalkeeper saves and own-team attempts. See
[Opta's event definitions](https://www.statsperform.com/opta-event-definitions/).

Five reviewed match reports supply independent evidence where simple concordance fails:

| Season / FPL fixture / team code | Team and match | SDP match ID | Corroboration |
|---|---|---:|---|
| 2024-25 / 124 / 4 | Newcastle at Palace, 1-1 | 2444593 | [Premier League report recounting the Palace match](https://www.premierleague.com/en/news/4177908); Newcastle's goal was an own goal |
| 2024-25 / 190 / 21 | West Ham v Liverpool, 0-5 | 2444659 | [Premier League match report](https://www.premierleague.com/en/news/4205597) |
| 2024-25 / 242 / 8 | Chelsea at Brighton, 0-3 | 2444711 | [Chelsea match report](https://www.chelseafc.com/en/news/article/match-report-brighton-3-0-chelsea) |
| 2024-25 / 269 / 4 | Newcastle at Liverpool, 0-2 | 2444738 | [TNT match coverage](https://www.tntsports.co.uk/football/premier-league/2024-2025/live-liverpool-newcastle-united_mtc1524011/live-commentary.shtml) |
| 2025-26 / 200 / 21 | West Ham at Wolves, 0-3 | 2562094 | [Premier League match report](https://www.premierleague.com/en/news/4516523/wolves-3-westham-0-match-report-3-january-2026) |

The fixed snapshot resolves all 85 omissions: 80 by concordant accounting/proxy evidence and five
by reports. In the scored seasons, those counts are 37 and five (42 total). This does not assert
that every future omission will be zero. The audit retains the reason, raw fields, provider
identity, original known-at, content hash and report evidence for every interpretation.

## Population frozen by coverage, not performance

Eligibility inherits the first experiment's **at least 95% joint goals/xG/SOT availability** and
at least two eligible seasons. All scored seasons must be fully represented in the result: no
discarding hard fixtures or low-history rows. Goals and xG are the unchanged FPL-archive fields.

| Season | Goal-observed team-sides | Existing xG | Raw explicit SOT | Corroborated zeros | SOT after interpretation | Joint coverage | Eligible |
|---|---:|---:|---:|---:|---:|---:|---|
| 2021-22 | 760 | 0 | 739 | 21 | 760 | 0% | No |
| 2022-23 | 760 | 488 | 738 | 22 | 760 | 64.2105% | No |
| 2023-24 | 760 | 760 | 754 | 6 | 760 | 100% | Yes |
| 2024-25 | 760 | 760 | 740 | 20 | 760 | 100% | Yes |
| 2025-26 | 760 | 760 | 744 | 16 | 760 | 100% | Yes |

Thus score 2,280 team-sides / 1,140 matches / 114 observed-GW folds in 2023-24 through 2025-26.
Coverage is source availability, not prior-history availability at GW1. At each fold, only
completed prior events enter history; all earlier archive seasons may train. SOT history length
and cold starts are reported separately. No scoring was performed to choose the coverage policy.

## Frozen model and evaluation procedure

The new YAML inherits `config/v2_real_sot_retrospective_evaluation.yaml` by its exact SHA-256.
Its estimator, all eight prior model/harness source files, and the two frozen result files must
remain byte-identical. The new candidate identity, interpretation policy and output are additive.

- Context baseline: `trailing_goals_attack_defence`.
- Primary control: `retrospective_goals_xg_control_v1`, on the identical folds and target rows.
- Candidate: the same `MultiSignalTeamEngine`, adding only the interpreted SOT input for team
  attack and opponent defence with the existing home/away treatment. Audit-only shot components,
  xGOT and FPL proxies are not fitting features.
- Target: recorded FPL-archive team goals. xG remains existing FPL-archive `expected_goals`.
- Output: the unchanged proper Poisson goals PMF with support 0..10 and folded upper tail,
  rate floor 0.05. SOT is a count-valued input, not a new Gaussian target.
- Expanding training, observed-GW outer batches, first kickoff cutoff, at least eight prior
  observed GWs, and minimum three team matches. Predict all target-GW fixtures from one pre-GW
  state; only subsequent folds can consume these observations.
- Recency half-life grid: 40, 80, 160, 320, 640 days, or no decay. Prior-match grid: 2, 4, 8,
  16, 32. The existing goals-only decay/prior selection and 0.25-step blend simplex are unchanged.
- Inner holdout: latest six observed GWs, with at least ten prior observed GWs for selection.
  As in the control, inner ratings are fitted once before the holdout block. This known update-
  schedule limitation is retained to isolate SOT semantics; no weekly-inner-refit change is made.
- Scaling: each training fit's mean goals divided by its jointly measured signal mean. Inner
  scales are fitted on inner training only; outer scales on outer training only. No global fit,
  future normalization, or outer-result weight tuning.
- Minimum signal coverage: 0.25. Unavailable SOT is dropped and remaining weights renormalized;
  with no SOT the candidate reduces to the goals+xG control. It does not impute averages.
- Promoted priors: attack 0.719, defence 1.309. The existing season transitions, permanent team
  identities, returning-team handling and cold-start fallback are unchanged.
- Seed: 20260904. No random split, recalibration fit or post-run parameter adjustment.

Primary metric: mean log score, lower is better. Also retain CRPS/RPS, randomized PIT-80 coverage,
MAE, signed mean error, Poisson deviance, predictive variance, within-GW rank correlation, and
predicted-rate mean/spread. Slices: season, venue, promoted status, GW1-6/later, cold start and SOT
history 0 / 1-2 / 3-5 / 6+. All are diagnostics, never tuning targets. PIT draws restart at the
fixed seed within each block, as before; slice PIT counts are not additive.

Development gate is unchanged: at least **1% relative log-score improvement over the goals+xG
control**, no CRPS regression, randomized PIT-80 absolute error at most 0.05, no season log-score
regression, identical populations and zero event/GW leakage. Paired loss diagnostics are
descriptive; correlated team-sides/GWs do not become independent confirmation by reporting a
standard error. Passing supports retrospective development only, never promotion.

Each prediction now retains its complete PMF for all three models, target, stable identity,
cutoff and slice metadata. This enables error auditing without recreating predictions. Per-fold
losses, fitted parameters/scales, interpretation counts and history-identity hashes are retained.
The first run's result is not rerun to add these outputs.

## Time boundary and provenance

`CorroboratedSotBackfillView` exists only under `fpl.validate`. It composes the separate historical
reader, not `PointInTimeView` or a production feature source. Every row still requires completed
goals, a corroborated crosswalk and `source_match_kickoff < prediction_as_of`; target-GW rows
are rejected. Later capture knowledge is explicitly permitted only by this retrospective
capability. Neither a boolean escape hatch nor a production import is added.

Canonical version remains the earliest successful, complete whole match-stats payload, ordered
by `fetched_at` then `payload_id`, before inspecting SOT. Later revisions never fill the earlier
version. The interpretation must match its original capture ID, SHA, known-at, provider match ID,
kickoff and both stable team identities. The policy's later review time is retained separately;
neither review nor capture time is backdated. The live PIT `known_at <= as_of` rule is unchanged.

Before the single formal outer run, commit implementation, tests, this preregistration, policy and
coverage audit. `git status --porcelain` must be empty. The runner refuses a dirty worktree or an
existing result, and revalidates clean Git HEAD, config, source, DB, audit and capture identities
before emission. No `--allow-dirty` or overwrite option exists. Do not rerun after seeing scores.

Frozen registration inputs:

- Base config: `73ebf92613b8efb39838079b42b576afea2f2d43c775758372293c4d64edaed0`.
- Interpretation policy: `52bd6f1ad975f7a683bff6bcca685f32d838c4d1dfd747a33df934860b013347`.
- Coverage/semantics audit: `3d662e09e541e924c218fe4edf1cf7f11289d2d13f4577fb0dc2bf56a596cb4a`.
- Database: `0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8`.
- Canonical capture manifest: `084137d2e03babbf9d8361e49be0f23ba19ae3baed34c5d9d0605264ea37057f`.
- First real-SOT result: `32a3332dd92e30b160a632d6ad68ee268cbfd3367a27340e365583c2e9ca7e7d`.
- Earlier V2 result: `bb80b26f88a01f8aee803b1e0eff61b55cc1712625357d3444dd73b297bad6ac`.

The formal artifact records the new config SHA, clean Git SHA, all source fingerprints, UTC start
and completion, seed, folds/rows, evidence class and inherited version-policy identity. It writes
only `results/v2_corroborated_zero_sot_development.json`. No existing result, DB or live forecast
is rewritten. Tests must establish raw preservation, NULL behavior, version selection, stable
identity, truncation equivalence, same-GW isolation, fold-local scaling, deterministic PMFs,
control equivalence, strict-path exclusion, dirty refusal and write-once output before scoring.

Do not implement territory or a second candidate in this session. Interpret this one result,
document it separately, retain failures as failures, and require explicit prospective evidence
before any promotion discussion.
