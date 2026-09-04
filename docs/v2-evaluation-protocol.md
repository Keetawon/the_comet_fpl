# V2 evaluation protocol

Contracts: `config/v2_team_environment_evaluation.yaml`, `config/v2_gk_saves_evaluation.yaml`
Runner: `python -m fpl.validate.dev_v2_team_environment --results results/`

## The discipline, restated

Both contracts were written before any V2 candidate had been scored, for the reason
`config/phase1_evaluation.yaml` was: a candidate must not be able to choose its folds,
baselines, metrics or gate after seeing its own result. Neither contract amends, reinterprets,
re-runs or re-judges Phase 1, and no value in a V1 config changed.

The typed loaders enforce what prose cannot:

* a `contract_version` other than 1.0 with no matching amendment record is **refused**;
* a `gameweeks` policy other than `observed_only` is **unrepresentable** — 2022-23 has no GW7,
  and assuming contiguity misaligns that whole season's split by one;
* `forbid_random_split` and `forbid_full_dataset_fitting` are `Literal[True]`, so they cannot be
  turned off by editing the config;
* `calibration` is `Literal["randomised_pit"]`, because Phase 1 amendment 1.1 measured that a
  raw central interval on a count distribution exceeds 0.80 by construction and **prefers
  biased models** — at a true rate of 1.80 the correct model scores 0.164 and a model 33% high
  scores 0.002;
* a saves contract without exactly one declared incumbent is **refused**: a comparison without a
  baseline has no bar.

## The nested-ladder rule

This is the one requirement specific to V2. The ablation candidates must form a chain under
inclusion:

```
A  goals
B  goals + xG
C  goals + xG + shots on target
D  goals + xG + shots on target + box touches
```

A ladder whose rungs merely *differ* cannot attribute a lift to a signal, because two rungs
could differ in two ways at once. `V2Ablation` validates containment and refuses anything else,
and every rung is the SAME estimator — the engine reuses `team_goals.fit_ratings` verbatim — so
a difference between rungs is the signal and not the functional form.

## Walk-forward

One fold per observed gameweek. Train on everything kicked off before the gameweek's first
kickoff, predict every team-fixture in it, advance. Gameweeks come from the values present in
the facts, never `range(1, 39)`.

Hyperparameter selection is nested inside each fold: the decay and prior strength are chosen on
a six-gameweek holdout at the end of the training window, then the blend weights are chosen on
the same holdout with every signal **refitted on the inner window**. Reusing the full-window fit
to choose weights would be selecting for a model that had already seen the holdout.

Selecting decay and prior on the goals signal alone, rather than jointly with the weights, is a
deliberate bound on search cost: a joint search is 35x larger and would be resolved on six
gameweeks of team-matches, which cannot support it. Both stages are strictly inside the training
window.

## Baselines are re-run, never quoted

The Phase 1 baselines are re-run on identical rows rather than compared against their frozen
Phase 1 numbers, because those were produced under a different population definition and
quoting them would be a cross-contract comparison.

This also validates the harness. `trailing_goals_attack_defence` scores **1.50030** over 181
folds and 3,640 predictions here, against Phase 1's frozen **1.5003 over 181 folds and 3,640
predictions**. A harness that could not reproduce the incumbent would not be measuring models.

## Scoring

Every model is scored only on rows EVERY model produced. Scoring on anything else compares
populations rather than models.

Metrics are proper for the predicted quantity: mean log score (primary), CRPS, RPS, randomised
PIT-80 coverage, MAE and mean error. Ranking metrics are secondary decision diagnostics, never
promotion criteria.

## Splits are mandatory

A pooled figure has misled this repository three times — xG coverage, home advantage, and the
Stage A Poisson zero — so every result is reported split by season, venue, promoted club, early
season, and signal-coverage regime before it is discussed. The V2 saves result is the fourth
instance: pooled it reads +0.168%, and split by season it inverts.

## Gate, and why passing it would still not promote

```
minimum_relative_log_lift: 0.01
maximum_crps_relative_regression: 0.0
pit_interval_80_maximum_absolute_error: 0.05
require_each_reported_season_to_pass: true
promotion_requires_prospective_window: true
```

The last line is the important one. The historical target roster and first-kickoff cutoff are
unversioned outcome-derived proxies, so **no historical result can establish real-deadline
validity** — the same caveat that keeps every Stage B and Stage C candidate development-only. A
candidate that clears every numeric gate here is still development-only until a prospective
window says otherwise.

## Failed candidates stay

Both V2 candidates failed. They are left as committed, are not retuned, and their result is
recorded in full in `docs/v2-team-engine-development.md`. Tuning a candidate after seeing its
result is exactly what pre-registration exists to prevent, and a refuted hypothesis with a
measured mechanism is more useful than a tuned number.
