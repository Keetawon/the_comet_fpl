# V2 real-SOT retrospective development result

Status: **INCONCLUSIVE**. This is retrospective development evidence, not promotion evidence.

The single formal outer evaluation ran once on 2026-09-05 from clean Git commit
`9fafb12e0d03250660206a7bbcfece20569eae3f`. It scored 2,280 team-fixture sides in 114 observed-
gameweek folds. The immutable result is `results/v2_real_sot_development.json` (SHA-256
`32a3332dd92e30b160a632d6ad68ee268cbfd3367a27340e365583c2e9ca7e7d`).

## Answer

REAL historical shots on target produced a very small improvement beyond the identical goals+xG
control, but it did not clear the pre-registered development gate and was not consistent by
season. Mean log score moved from 1.489436 to 1.488879, a relative lift of **0.0374%** against the
required 1%. The paired mean log-loss difference was -0.000557 with gameweek-clustered standard
error 0.000670, so the observed improvement is smaller than one standard error.

The result is therefore `INCONCLUSIVE`, exactly as the frozen verdict mapping requires for a
positive primary lift that misses the gate. It is not a model promotion and does not alter any
prospective default.

## Same-population results

| Model | Mean log score | CRPS/RPS | PIT-80 | Mean error | MAE |
|---|---:|---:|---:|---:|---:|
| trailing-goals context baseline | 1.496896 | 0.631038 | 80.31% | -0.04365 | 0.92892 |
| goals+xG control | 1.489436 | 0.626658 | 80.83% | -0.00423 | 0.93154 |
| goals+xG+REAL-SOT candidate | 1.488879 | 0.626136 | 80.83% | -0.00010 | 0.93204 |

Against the exact control, CRPS improved 0.0833%. Overall PIT-80 coverage and its 0.83 percentage-
point absolute calibration error were unchanged. MAE regressed by 0.00051, while mean error moved
closer to zero. The primary log-score gate failed; the no-season-regression gate also failed. The
overall CRPS, PIT, identical-population, and zero-leakage checks passed.

| Season | Rows | Control log | Candidate log | Log lift | CRPS lift | Control / candidate PIT-80 |
|---|---:|---:|---:|---:|---:|---:|
| 2023-24 | 760 | 1.541525 | 1.539251 | +0.1475% | +0.2796% | 80.53% / 80.39% |
| 2024-25 | 760 | 1.481843 | 1.481886 | -0.0029% | +0.0202% | 82.76% / 82.63% |
| 2025-26 | 760 | 1.444940 | 1.445500 | -0.0388% | -0.0695% | 81.32% / 81.32% |

Only 2023-24 improved on the primary metric. The two later seasons regressed slightly, so the
aggregate gain is not stable historical evidence.

## What SOT changed

The inner selection assigned zero SOT weight in 72 of 114 folds. Across the remaining folds the
selected weights were 0.25 (14 folds), 0.50 (11), 0.75 (7), and 1.00 (10); the all-fold mean was
0.2127. Each fold fitted the SOT scale only on prior jointly measured rows. The recorded scales
ranged from 0.3201 to 0.3262 goals per SOT unit and prior-row SOT coverage ranged from 97.17% to
98.02%.

The candidate-control rate correlation was 0.99473 and the mean absolute rate change was only
0.02081 goals. Mean predicted rate rose by 0.00413 goals, improving aggregate level bias. Within-
gameweek Spearman moved only from 0.32662 to 0.32771. Predicted-rate standard deviation fell from
0.43061 to 0.41996, a ratio of 0.9753. Thus SOT mainly nudged the level and mildly shrank cross-team
discrimination; it did not introduce a new dispersion model because both outputs remain Poisson.

## Evidence boundary and provenance

Targets and xG remained on `fpl_archive`; the only added field was verified SDP
`ontargetScoringAtt`. The retrospective reader selected the earliest successful complete payload,
preserved `capture_id`, real `known_at`, and `payload_sha256`, and required match kickoff before
each fold cutoff. All event-time, identity, and same-gameweek guard counts were zero. The strict
prospective `known_at <= as_of` path was unchanged.

The performance-blind 95% joint-coverage audit selected 2023-24, 2024-25, and 2025-26. Its 1,900-
capture manifest uses SHA-256 `084137d2e03babbf9d8361e49be0f23ba19ae3baed34c5d9d0605264ea37057f`.
All real matches currently have one successful captured version, so earliest-version selection is
deterministic on real data but only its multi-version behaviour is exercised by synthetic tests.

Formal provenance:

- config SHA-256: `73ebf92613b8efb39838079b42b576afea2f2d43c775758372293c4d64edaed0`;
- database SHA-256: `0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8`;
- coverage SHA-256: `7b37ce3998f1f252a6b1d7ea7978b1f916f7bf414eb8c942eae87e2bc50c5a6d`;
- frozen prior V2 result SHA-256 remained
  `bb80b26f88a01f8aee803b1e0eff61b55cc1712625357d3444dd73b297bad6ac`;
- evidence class: `retrospective_backfill_development`;
- random seed: `20260904`.

## Next decision

Do **not** pre-register territory or box touches next. The isolated SOT increment is below the
development threshold, statistically weak, and regresses in two of three seasons. Accumulate
strict-prospective SOT evidence instead; any later territory hypothesis needs a new justification
and preregistration rather than treating this inconclusive result as a supported rung.
