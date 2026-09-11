# Next-match tactical delta forecaster V1

Part of the single [tactical matchup preregistration](v2-tactical-matchup-design.md).
All five dimensions remain fixed regardless of their eventual diagnostic performance.

Inputs are five estimated recent dimensions for this team, the five for its opponent,
and home=1/away=0. No club label, target goals, target tactical measurement, cup fixture,
player input, or future-normalized quantity is a predictor. Fit one output per dimension
on its measured target rows (no missing-target imputation), predicting **observed next state
minus the pre-match recent state**. Minimum 160 complete predictor/measured-target rows per
output; otherwise persistence. Use ridge, fixed penalty 1.0, objective mean squared residual
plus penalty times squared coefficient norm. All coefficients, including intercept and venue,
shrink toward zero. Fit predictor scaling only on that fit's training rows; zero SD becomes
one. The five outputs share the input architecture, not a missingness-forced row population.

Predict `recent + delta`; clip shares to [0,1], log-box-volume >=0, negative log-attempts-faced
<=0 (logical domain bounds only). Without a complete recent state on either side, persistence
remains nullable and the goal layer falls back to incumbent. No learned team venue coefficient.

Generate historical style predictions sequentially, before each GW using only earlier
completed events. Retain predictor cutoff, max training event, source keys and fit/scaler
diagnostics. **The goal layer trains only on these event-time out-of-sample predictions**,
never a style model refitted on its own target fixture. Reusing cached historical predictions
is safe because their fixed ridge procedure has not seen the later cutoff or target.

Retain observed, recent/persistence, predicted, opponent state, venue and errors for every
dimension where measured. Report MAE, RMSE, MSE standardized by the strictly-prior target
SD, Pearson/rank correlation, season, venue and GW1-6/GW7+ slices. Report venue-only and
opponent-state contributions from frozen coefficients as explanatory sensitivities, not causal
effects. No dimension removal or subsequent refit after inspecting these diagnostics.
