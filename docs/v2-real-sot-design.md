# V2 real SOT retrospective development design

Status: pre-registered before outer evaluation. Candidate performance must not amend this document.

## Question and isolation

The single question is whether historical team shots on target add predictive signal for the team
goal distribution beyond the existing goals+xG V2 engine.

The comparison changes one signal only:

| Role | Identity | Signals |
|---|---|---|
| Context baseline | `trailing_goals_attack_defence` | recorded goals |
| Exact control | `retrospective_goals_xg_control_v1` | recorded goals, existing archive xG |
| Candidate | `retrospective_real_sot_team_environment_v1` | control plus real SDP SOT |

The frozen historical candidate `v2_env_c_goals_xg_sot` is not reused. Its source provider was
`fpl_archive`, whose SOT column was entirely unavailable; it therefore reduced bit-for-bit to its
goals+xG predecessor. That artifact remains immutable and is not evidence for or against SOT.

## Evidence and population

Evidence class is `retrospective_backfill_development`, as defined in
`docs/v2-retrospective-backfill-policy.md`. Target goals and xG come from `fpl_archive`; SOT comes
only from the exact verified SDP field `ontargetScoringAtt`, using the earliest-successful complete
payload policy. Original capture timestamps are retained.

Season eligibility is selected from feature coverage only. The fixed rule is at least 95% joint
availability of recorded goals, archive xG, and canonical retrospective SDP SOT over completed
team-fixture rows, with at least two qualifying seasons. The pre-score audit measured:

| Season | Rows | Goals | Archive xG | SDP SOT | Joint | Joint coverage |
|---|---:|---:|---:|---:|---:|---:|
| 2021-22 | 760 | 760 | 0 | 739 | 0 | 0.00% |
| 2022-23 | 760 | 760 | 488 | 738 | 472 | 62.11% |
| 2023-24 | 760 | 760 | 760 | 754 | 754 | 99.21% |
| 2024-25 | 760 | 760 | 760 | 740 | 740 | 97.37% |
| 2025-26 | 760 | 760 | 760 | 744 | 744 | 97.89% |

The eligible scoring seasons are therefore 2023-24, 2024-25, and 2025-26. Every completed target
team-fixture in those seasons remains in the scoring population: target-match SOT is a future
observation and is never an eligibility filter. Earlier archive seasons may contribute prior match
history inside a fold, but are not scored. Missing historical SOT remains `NULL` and follows the
pre-registered signal fallback.

## Estimator and fold-local selection

Control and candidate use the unchanged `MultiSignalTeamEngine`. Each signal fits the same
multiplicative team attack, opponent defence, and home/away rate structure. SOT is converted to the
goals scale inside each fold as `mean(training goals) / mean(training SOT)` on jointly measured
prior rows; no full-data normalization is permitted.

The expanding history is time-decayed. The existing grids are frozen unchanged:

- half-life days: 40, 80, 160, 320, 640, or no decay;
- prior strength: 2, 4, 8, 16, or 32 matches;
- minimum three matches before replacing a team prior;
- six observed gameweeks in the inner holdout after at least ten inner-training gameweeks;
- signal coverage floor 25%;
- blend simplex step 0.25;
- promoted attack/defence priors 0.719 and 1.309;
- goal-rate floor 0.05 and terminal goal bin 10.

Half-life and prior strength are selected on goals inside the training fold. Blend weights are then
selected on the same fold's inner holdout after refitting every available signal to the inner
training rows. The candidate simplex contains the exact control at SOT weight zero. When SOT is
unavailable or below its fold coverage floor it is rejected, `NULL` is never changed to zero, and
the candidate reduces to the available control signals.

## Outer walk-forward

Observed gameweeks come from the data, not `range(1, 39)`. A fold is eligible after eight prior
observed gameweeks. For each eligible target gameweek:

1. take archive history with kickoff strictly before the target game's first kickoff;
2. obtain retrospective SOT through a view instantiated at that same cutoff;
3. fit the context baseline, exact control, and candidate independently on that prior history;
4. predict both sides of every target fixture from the same pre-gameweek state;
5. score the full batch, then allow those matches into later folds.

No target xG or SOT is projected into prediction inputs. Stable `team_code`, the measured SDP
crosswalk, existing promoted-team priors, and existing season-transition behaviour are unchanged.

## Metrics, diagnostics, and gate

Primary: mean negative log score. Also report discrete CRPS/RPS, randomized PIT calibration and
PIT 80% coverage, mean error, MAE, predictive variance, Poisson deviance, and within-gameweek rank
correlation. The random seed is frozen in the additive YAML contract.

Report overall and by season, home/away, promoted/established, GW1-6/later, model cold-start, and
prior SOT history bands `0`, `1-2`, `3-5`, and `6+`. These slices are diagnostic and cannot retune
the candidate. Predicted-rate mean and standard deviation plus paired candidate-control rate changes
diagnose level, discrimination, and shrinkage. Both outputs remain Poisson, so SOT does not introduce
a separate conditional-dispersion parameter.

The candidate is supported only if, on identical rows and folds:

- mean log score improves at least 1% over the goals+xG control;
- CRPS does not regress;
- randomized PIT-80 absolute error is at most 0.05;
- no eligible season's mean log score regresses;
- distribution mass, event-time, identity, and same-gameweek isolation checks all pass.

A passing verdict is `SUPPORTED FOR RETROSPECTIVE DEVELOPMENT ONLY`. A non-positive primary lift is
`REFUTED`; a positive result that misses any gate is `INCONCLUSIVE`. No outcome promotes a model.
