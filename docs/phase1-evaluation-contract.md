# Phase 1 evaluation contract

**Status: contract and harness implemented at version 1.1; Stage A model not started.** The
machine-readable source is `config/phase1_evaluation.yaml`, validated by
`Phase1EvaluationConfig` and executed by `src/fpl/validate/`. This document explains the
decisions; it does not override that file.

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
reported within gameweek as a ranking diagnostic. Both the raw and PIT-based 80% coverages are
reported, but only the PIT one is gated -- see amendment 1.1.

A Stage A candidate is promoted only if, on every reported season:

- mean log score improves by at least 1% over the best required eligible baseline on the same
  prediction rows, using `(baseline - candidate) / abs(baseline)`;
- CRPS does not regress relative to that baseline;
- randomised-PIT 80% band coverage is within five percentage points of 80%;
- at least 98% of eligible team-fixtures receive a prediction;
- at least 20 walk-forward folds are evaluated; and
- point-in-time and truncation-equivalence tests have zero failures.

The report must include fold, season, promoted-status, and home/away slices plus counts for
predictions, exclusions, cold starts, and uncertainty. A headline aggregate without those counts
does not satisfy the gate.

## Amendments

A pre-registered contract that can be edited silently is not pre-registered. Every version
after 1.0 therefore carries a machine-readable record in `amendments:`, and the loader rejects
a version bump without one. The record states how many candidates had been evaluated when the
change was made, because that -- not the wording of the reason -- is what determines whether an
amendment is legitimate.

### 1.1 -- the calibration gate names its metric (2026-07-27, 0 candidates evaluated)

`promotion.interval_80_maximum_absolute_error` becomes
`promotion.pit_interval_80_maximum_absolute_error` at the same tolerance of 0.05.
`pit_interval_80_coverage` joins the required calibration outputs. The raw coverage remains
reported and is no longer gated.

The superseded key did not say which interval it meant, and the harness built the obvious one:
the central interval between integer quantiles, `[q0.1, q0.9]` with `q_p = min{g : F(g) >= p}`.
For a count distribution that interval covers `F(q0.9) - F(q0.1 - 1)`, which is strictly
greater than 0.80 by construction. The excess is the discreteness of the pmf, not an error the
model made, and it does not shrink with more data.

The failure is not that the gate is hard. It is that it points the wrong way:

| true rate | model rate | raw coverage | \|error\| | old gate | PIT coverage | \|error\| |
|---|---|---|---|---|---|---|
| 1.80 | **1.80** (correct) | 0.9636 | 0.164 | **fail** | 0.8000 | 0.000 |
| 1.80 | 2.40 (33% high) | 0.7983 | 0.002 | **pass** | 0.7832 | 0.017 |

Gating the raw figure would have rejected a perfectly specified model and promoted a badly
biased one. Swept over true rates 1.0, 1.35, 1.6, 1.8 and 2.2, the raw measure is closest to
nominal at the correct rate in **zero of five** cases. The randomised PIT of a correctly
specified model is exactly `Uniform(0, 1)`, so its `[0.1, 0.9]` band coverage is exactly 0.80
at the truth in all five and degrades away from it. On the archive, all five Stage A baselines
score 0.787-0.804 on the PIT measure and 0.927-0.942 on the superseded one.

The tolerance is carried over unchanged at 0.05. The amendment fixes which quantity is
measured, not how strict the gate is. Applied per reported season -- 600 to 760 predictions --
0.05 is roughly 3.1 to 3.4 binomial standard errors: a screen against gross miscalibration
rather than a precision test.

**Known and deliberately not fixed here.** Band coverage is necessary but not sufficient for
calibration: a model can hold exactly 0.80 inside the band while being non-uniform within it. A
Kolmogorov-Smirnov or chi-square test on the PIT histogram would be the stronger check. Adding
it is a further amendment and remains an owner decision; it is recorded so the weakness is not
silently inherited.

## Exit criterion

Phase 1 exits when one reproducible Stage A configuration passes the promotion gate, its exact
config and seed are committed, and the results include all required baselines, metrics, slices,
coverage, exclusions, and calibration evidence. If no candidate passes, the correct outcome is a
documented non-promotion, not a relaxed post-hoc threshold.
