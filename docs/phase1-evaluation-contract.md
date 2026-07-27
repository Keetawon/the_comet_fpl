# Phase 1 evaluation contract

**Status: contract implemented; Stage A model not started.** The machine-readable source is
`config/phase1_evaluation.yaml`, validated by `Phase1EvaluationConfig`. This document explains
the decisions; it does not override that file.

## Scope and entry gate

Phase 1 predicts a probability distribution for team goals at
`(season, fixture, team_id)` grain. Team IDs remain season-scoped. It does not yet predict player
minutes, player events, bonus, or FPL points.

Model implementation starts only when all of these are true:

1. Phase 0b facts and point-in-time access tests pass.
2. The seven scoring values omitted by `game_config.scoring` have named authoritative evidence.
3. Full archive database replacement is failure-atomic, with a failure-path test.
4. This contract and its tests pass unchanged before the first candidate is fitted.

The third item is still outstanding. Phase 1 model code must not start by working around it.

## Walk-forward split

Each fold predicts one **observed** gameweek at its FPL deadline. The training view contains only
outcomes with `kickoff_time < as_of` and only live versions with `known_at <= as_of`. It iterates
gameweeks present in the facts rather than `1..38`; 2022/23 has no GW7.

The window expands after at least eight observed gameweeks. A team needs six prior matches for
team-specific estimates; otherwise the candidate must use its declared cold-start prior and
report that prediction as a cold start. Every transform, prior fit, and hyperparameter derived
from data is fitted inside the fold. NULL remains unavailable, never zero. The seed is fixed.

## Required comparisons

| Comparator | Purpose |
|---|---|
| League home/away goals | Transparent intercept-only floor |
| Trailing goals attack/defence | Simple observed-goals strength |
| Trailing xG attack/defence | Tests whether xG adds usable signal |
| Naive FPL FDR | Product-facing fixture-difficulty baseline |
| Promoted-team pooled prior | Makes the cold-start policy measurable |

Goals-trained and xG-trained candidates must be shown separately. A candidate cannot select the
better one after aggregating folds without also reporting both fold and season results.

The downstream player-points harness is pinned now to three minimum comparisons: legitimate FPL
`ep_next`, trailing-five recorded points, and naive FDR. `ep_next` is evaluated only against
`total_points_as_recorded`, because it was generated under the contemporary scoring rules. It is
never used as a model feature or compared as though historical recorded points were denominated
under the 2026/27 ruleset.

## Metrics and promotion

The primary metric is mean log score (lower is better), with mean CRPS as a second proper
distribution score.
Poisson deviance and goal MAE are diagnostics, not substitutes for distribution scoring.
Randomized PIT and 80% predictive-interval coverage expose calibration; Spearman correlation is
reported within gameweek as a ranking diagnostic.

A Stage A candidate is promoted only if, on every reported season:

- mean log score improves by at least 1% over the best required eligible baseline on the same
  prediction rows, using `(baseline - candidate) / abs(baseline)`;
- CRPS does not regress relative to that baseline;
- observed 80% interval coverage is within five percentage points of 80%;
- at least 98% of eligible team-fixtures receive a prediction;
- at least 20 walk-forward folds are evaluated; and
- point-in-time and truncation-equivalence tests have zero failures.

The report must include fold, season, promoted-status, and home/away slices plus counts for
predictions, exclusions, cold starts, and uncertainty. A headline aggregate without those counts
does not satisfy the gate.

## Exit criterion

Phase 1 exits when one reproducible Stage A configuration passes the promotion gate, its exact
config and seed are committed, and the results include all required baselines, metrics, slices,
coverage, exclusions, and calibration evidence. If no candidate passes, the correct outcome is a
documented non-promotion, not a relaxed post-hoc threshold.
