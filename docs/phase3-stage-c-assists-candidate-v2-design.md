# Stage C assists Candidate V2 — design (exposure-weighted xA team share)

**Status: pre-registration, development-only.** Candidate V2
(`exposure_weighted_xa_team_share_assists_v2`) is pre-registered under
`config/phase3_stage_c_assists_evaluation.yaml` amendment 1.2 (contract v1.2) **before any V2
evaluation**. It is additive: it changes no v1.0/1.1 population, target roster, baseline, metric,
gate, seed, or calibration field, and is judged by the unchanged v1.0 promotion gate. No V2
historical run is authorized by this document; the development runner
(`fpl.validate.dev_assists_candidate_v2`) is provenance-ready but is the single explicitly authorized
clean run, never a test.

V2 is the **assists analogue** of the goals Candidate V4 (see
[`phase3-stage-c-attacking-candidate-v4-design.md`](phase3-stage-c-attacking-candidate-v4-design.md)
for the full statement of every shared choice: Option-A window, position-specific cold-start prior,
fold-local global bin means for `E[minutes]`, fixed `prior_minutes = 90`, the frozen
`trailing_5_player_minutes` baseline, the V3 cold-start audit, the composer defect, and the scope
sequencing). This document records only what differs for assists.

## Hypothesis

> **Separating per-minute assist productivity from predicted exposure improves point-in-time proper
> scores over raw per-appearance xA shares.**

## Exact formulas and units (assists-specific)

Assists scale with team goals by a fold-local league assist rate, so the club's assisted-goal
expectation is `lambda_team * assist_rate` and is allocated by an xA-exposure weight:

```
# xA-only per-minute productivity (Option-A window; NULL xA excluded from signal AND minutes)
player_xa_per_min_i = sum(xA over window measured rows) / sum(minutes over the same rows)
position_xa_per_min[pos] = sum(xA over appeared measured rows at pos) / sum(minutes)  # position-specific

shrunk_xa_per_min_i = (sum(xA) + 90 * position_xa_per_min[pos_i]) / (sum(minutes) + 90)

# fold-local league assist rate (sum(assists) / sum(goals_scored) over minutes-not-null history)
team_assist_lambda = lambda_team * assist_rate        # the assisted-goal expectation for the club
assist_weight_i = shrunk_xa_per_min_i * E[minutes_i]  # NO p_play factor
assist_lambda_i = team_assist_lambda * assist_weight_i / sum_j(assist_weight_j)
=> sum_i assist_lambda_i == team_assist_lambda   (in expectation)
```

`assist_rate` falls back to the pre-registered `0.90` only when a fold has scored zero goals
(degenerate early fold). The prediction is `Poisson(assist_lambda_i)` over `0..10`.

### Conservation

**Underlying Poisson-rate conservation in expectation**: `sum_i assist_lambda_i ==
team_assist_lambda` by construction. Not per-draw realised-count conservation; V2 is never fed to the
composer in this slice.

## Assists-specific locked choices

- **xA-only, NO creativity fallback.** The signal is `expected_assists` only; this candidate never
  reads `creativity`. NULL xA is unmeasured and never zero-filled (excluded from both the signal sum
  and the minutes sum). xA shares xG's measured-coverage profile (NULL in 2021-22, partial 2022-23,
  100% from 2023-24).
- **Team scale = `lambda_team * fold_local_assist_rate`.** Assists require a team goal; the
  assisted-goal total is the team-goal expectation times the measured league
  `sum(assists)/sum(goals_scored)` (~0.90, stable 0.89–0.94 across seasons).
- **Stage-A-uninformative fallback = v1.0 trailing-ASSISTS rate** (`TrailingPlayerAssistRateBaseline`,
  `alpha = 5.0`), not the goals trailing rate. V2 is standalone (it does not subclass a goals
  candidate): assists have their own label, baselines, and signal.

Every other choice (Option-A window, position-specific cold-start prior, fold-local global bin means
for `E[minutes]`, `prior_minutes = 90`, frozen `trailing_5_player_minutes` baseline, no composer
integration) is identical to goals V4.

## File boundary (additive; no frozen file modified)

Created:
- `src/fpl/models/attacking_assists_v2.py` — the candidate (standalone; reuses V2-goals' Stage A
  training projection constants and V3's fold-history helpers, consumes `attacking_exposure`).
- `src/fpl/validate/dev_assists_candidate_v2.py` — provenance-ready development runner (co-scores
  assists V1 live as the comparator; same provenance discipline as the V4 runner).
- `tests/test_attacking_assists_v2.py`, `tests/test_dev_assists_candidate_v2.py`.
- This document.

Modified (additive amendments / schema only):
- `config/phase3_stage_c_assists_evaluation.yaml` (`1.1 → 1.2`, amendment 1.2,
  `stage_c_assists_candidate_v2` block).
- `src/fpl/config.py` (`Phase3StageCAssistsCandidateV2Policy`, the optional-then-required field,
  the `1.2` amendment history entry, the extended `_candidate_required_after_v1_0` validator).
- `tests/test_phase3_stage_c_assists_evaluation.py` (version pin `1.2`; V2 contract tests).

Not touched (frozen): `points_composition.py`, `prospective_points_v1.py`, `attacking_assists_v1.py`,
`attacking_v{1,2,3}.py`, `minutes_v3.py`, every existing dev runner, all gate/baseline/metric
config, all recorded numbers, the prospective default.

## Measurement plan (Phase B, only after authorization)

Same leakage-safe discipline and full-population-vs-covered-season handling as goals V4. Comparators:
assists V1 (`xa_informed_trailing_player_assists_v1`, live co-score) and the two v1.0 assists
baselines, all on identical eligible rows. Judging within xA-covered seasons (2023-24, 2024-25,
2025-26); full-population figures (incl. 2021-22 / partial 2022-23) reported separately, never the
verdict. Conservation diagnostic: per fixture `sum_i assist_lambda_i` vs `team_assist_lambda`. No
combined full-points score. No promotion verdict.
