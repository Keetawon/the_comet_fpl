---
name: validate-fpl-walk-forward
description: Design, implement, or review leakage-safe walk-forward validation for FPL team, minutes, player-event, simulation, and optimizer models. Use for Phase 1+ modelling, train/test splits, backtests, baselines, calibration, model comparisons, lift gates, or deciding whether a model is ready to advance.
---

# Validate FPL Walk-Forward

Require model comparisons to be reproducible, point-in-time correct, and decision-relevant.

## Establish the evaluation contract

Read `AGENTS.md`, the README phasing and R1-R6 rules, the point-in-time access layer, relevant
model code, and existing validation documentation.

Before fitting, write down:

- prediction entity and grain;
- prediction cutoff and knowledge-time policy;
- training window and minimum history;
- observed gameweeks to iterate;
- target ruleset and component completeness policy;
- baselines;
- primary metrics, guardrails, and an explicit promotion threshold.

Never assume gameweeks are contiguous or loop over `range(1, 39)`. Iterate observed
season/gameweek values; 2022-23 has no GW7.

## Validate by model stage

- **Team model:** compare goals- and xG-based transparent baselines, naive FDR, promoted-team
  priors, likelihood/deviance, and forecast calibration.
- **Minutes model:** evaluate zero-minute, 1-59, 60-89, and 90-minute probabilities plus
  calibration and proper scoring rules. Keep minutes separate from event rates.
- **Player events and points:** evaluate component distributions before derived fantasy points.
  Apply the target season's scoring rules instead of modelling recorded cross-season
  `total_points`.
- **Simulation:** validate full-distribution calibration, tail probabilities, variance,
  dependence assumptions, and Monte Carlo stability.
- **Optimizer:** compare feasible decisions under fixed information and constraints; separate
  initial squad, transfers, chips, and risk preferences.

## Minimum comparisons

Include the model, FPL `ep_next` when legitimately available at cutoff, trailing-form baselines,
and the phase-specific naive baseline. Report:

- a proper distribution score such as log loss, Brier score, or CRPS as appropriate;
- reliability/calibration with bucket counts;
- within-position/gameweek ranking metrics where ranking is a product decision;
- coverage, exclusions, cold-start cohorts, and uncertainty;
- fold-level and season-level results, not only a pooled mean.

## Guard against leakage

Use `$guard-fpl-point-in-time` for feature and split review. Fit every transform inside the
training fold. Pin random seeds and configuration. Preserve NULLs and exclude or explicitly
weight rows with incomplete target components.

## Handoff

Provide the evaluation contract, fold boundaries, baseline definitions, metrics with
uncertainty, cohort failures, and the pass/fail result against the predeclared lift gate. Do not
promote a model based only on one aggregate metric.
