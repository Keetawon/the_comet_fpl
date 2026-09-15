# Additive qualification of the frozen DC V2 diagnostic

The frozen `results/v2_dc_development.json`, original source and original report
remain byte-for-byte retained. This note records a source-level limitation discovered
before any new successor evaluation; no old candidate was refitted or rerun.

`dev_v2_dc.load_dc_frame` joins the **target fixture's observed** archived team
`defensive_actions`. `run_folds` passes that target value directly to `v2.predict`,
alongside the target player's realised `minutes / 90`. Consequently the retained
V2 ranking and transferred-player results are **oracle-conditional allocation
diagnostics**, not evidence that a prospective team environment can be forecast.

The original realised-minutes limitation was documented, but the observed target
team environment was not called out equally clearly. Its direct inclusion means
the old figures must not be used as a predictive comparator or a deployable signal
claim. This note does not replace or retroactively rerun the frozen record.

There is also a separate specification limitation: V2 estimates `player DC /
team defensive actions` from appeared rows without normalising that ratio for the
player's exposure, then multiplies the prediction by minutes exposure again.
This can thin a partial-appearance signal twice. The full-season variance/mean
table alone therefore does not prove that the entire log-score deficit is caused
by the Poisson family, nor can it provide a fold-safe dispersion parameter.

A newly preregistered successor must use a prior-only forecast of team actions,
an explicitly exposure-normalised player intensity ratio, and predicted minutes.
Its primary comparator remains exact current `DefensiveContributionV1`; a
same-input Poisson diagnostic isolates the additional Gamma-Poisson count shape.
Dispersion must be estimated from earlier sequential out-of-sample forecasts,
never from the frozen evaluation-season variance table. This remains development
evidence, not historical deadline knowledge or production promotion.
