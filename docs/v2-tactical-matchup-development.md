# Tactical Matchup V1: incomplete execution, no performance verdict

**INCONCLUSIVE — numerical execution failure, not an evaluated improvement or rejection.**
Development only. The authorized one-shot attempt was made on 2026-09-07 and failed before
complete evaluation/publication. There is no candidate log score, CS Brier, style-forecast
accuracy, season/slice comparison or paired uncertainty to report. Missing results are not
zeros and the absence of a result is not a measured failure to clear 1%.

## Git and preregistration

- Starting clean local V2 SHA: `462e46cf76f2628b2d57ea0c8726d781048d90e5`.
- Verified remote V2: `9228892ba2abda80dd8dc8011c93302c6aad9710`; the three local
  revision/daily and weekly-SOT commits were preserved, not recreated or rerun.
- The single main-only snapshot commit `4acaca20989388aa66142e25beeaa5f395a3ea9c`
  was normally merged at `9e861de6ae76a9ea4da32070726ade9eff5a14dd`.
- Clean preregistration/evaluation SHA: `672a36d9d6fc446bb7492eb89eebd63f15bee860`.
  Design, implementation, synthetic tests and measured coverage were committed before
  the sole formal invocation. No implementation or model parameter changed afterward.

Candidate: `retrospective_tactical_matchup_team_environment_v1`. Config SHA256:
`a640ff31f6d1701df12ee9ba3267636ea2856a49cd1496ef68d658b60317c781`.
The [state](v2-tactical-state-design.md), [forecaster](v2-next-match-style-forecaster-design.md)
and [matchup](v2-tactical-matchup-design.md) preregistrations remain unchanged.

## What was actually completed

The coverage-only audit inspected 245 numeric provider fields across 1,921 canonical
whole-payload captures. Five continuous dimensions were fixed: attack precision (SOT/shots),
log box touches, possession share, forward-pass share, and negative log opponent shots.
Six exact raw keys, original knowledge times and earliest complete whole-payload versions
are retained; only SOT has independent semantic corroboration among these input keys.

State uses actual last-five current-season PL matches, fixed newest-first weights
`1,.707,.5,.354,.25`, explicit `n/(n+2)` pooling toward a strictly-prior measured league mean,
and a season reset. Unmeasured matches consume window slots; raw NULL remains NULL.
Venue is a league-pooled ridge-penalized home indicator, not separate home/away histories.

Before fitting, the >=95% paired-all-dimension rule selected **2023-24 (98.4211%) and
2025-26 (95.7895%)**. Planned population: 760 fixtures, 1,520 sides, 76 outer GW folds.
2024-25 was excluded from outer scoring at 94.7368%, but can supply strictly prior measured
training history. This nonconsecutive, omission-dependent population limits generalization.

The exact current default is `TrailingGoalsAttackDefence`, not weekly goals+xG or a dynamic
research successor. Despite its name, it has no recency decay: it uses expanding archive
recorded goals, six-match league shrinkage, venue means and neutral unknown-team ratios.
The candidate anchors its log rate to that incumbent, preserving its Poisson support 0..10
and exact reciprocal PMF-zero clean-sheet identity. Neither default nor inputs changed.

Before the candidate claim, incumbent reproduction **passed** against both the retained
reference PMFs and the actual prospective helper: 1,520 sides, 76 folds, identical identities,
outcomes and cutoffs; maximum absolute PMF difference **0.0** at tolerance `1e-12`.

| Metric on the selected population | Reproduced incumbent | Tactical candidate |
| --- | ---: | --- |
| Mean negative log score | 1.4976075134626126 | Unavailable: run incomplete |
| Clean-sheet Brier | 0.1700257027333172 | Unavailable |
| CRPS / RPS | 0.6309287474700235 | Unavailable |
| PIT-80 coverage | 0.8105263157894737 | Unavailable |
| Mean absolute error | 0.9283510477669025 | Unavailable |
| Mean prediction error | -0.06878436807403207 | Unavailable |
| Predicted-rate SD | 0.4968152952641397 | Unavailable |
| Within-GW Spearman | 0.30992478169306303 | Unavailable |

Do not compare these two-season incumbent values to a different historical population's
aggregate. No old SOT candidate was rerun to obtain them; only the authorized incumbent
reproduction and arithmetic on its already-retained reference distributions were used.
The CS Brier is independent post-failure arithmetic on those identical retained PMFs:
2023-24 0.16034483299294514; 2025-26 0.17970657247368924. It is not a recovered candidate
score or evidence that the interrupted runner completed its scoring stage.

## Exact failed attempt

The permanent environment executed once, from the clean V2 worktree:

```text
D:\Personal\fpl-operations\.venv\Scripts\python.exe -u -m fpl.validate.dev_v2_tactical_matchup --db D:\Personal\workspace\the_comet_fpl\.worktrees\sdp_test\data\fpl.duckdb
```

Claim time: `2026-09-07T04:31:55.882994+00:00`. Last started historical batch:
**123/189, 2024-25 GW10**, logged at 04:33:18.312 UTC. The process exited **1**.
This batch is training history for the later eligible outer season; its outer-ineligible
status does not exempt numerical fitting from the frozen procedure.

```text
dev_v2_tactical_matchup.py:658 -> run_tactical_walk_forward
tactical_matchup.py:351 -> _goal_fit
tactical_matchup.py:170 -> fit_poisson_offset
tactical_math.py:227
ValueError: Poisson Newton backtracking failed to find a safe descent step
```

All 30 Armijo step trials were rejected. The log does not retain the offending penalty,
iteration, gradient, objective or proposed rates, so the actual numerical cause is **not
established**. Near-optimum floating-point objective rounding is a plausible code-level
failure mode, not a measured diagnosis of this fold. This was not a provider/network failure.
An independent bounded synthetic-only numerical probe did not reproduce the exception;
it neither identifies the actual cause nor authorizes a real-data replay.

The runner did not reach aggregate scoring, its successful postflight snapshot, or atomic
publication of full predictions. Some earlier predictions existed only in process memory;
none were salvaged, selectively scored or presented as a completed experiment. Do not infer
a completed outer-row count from the progress log. No second run, real-data diagnostic
refit, penalty change, solver repair or new candidate was undertaken afterward.

`results/v2_tactical_matchup_development.json` is explicitly an **execution-failure record**
assembled from the log, claim and independent checks, NOT the normal runner's successful
output. It retains null candidate metrics and incomplete status. Keeping it at the reserved
result path makes the existing write-once guard refuse an accidental fresh-checkout rerun;
the original ignored local claim is also preserved. No source behavior was changed to do so.

## Integrity, checks and interpretation

Research database:
`D:\Personal\workspace\the_comet_fpl\.worktrees\sdp_test\data\fpl.duckdb`.
SHA256 before and after is unchanged:
`0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8`.
Original root and operational daily databases were not written. Capture timestamps,
strict prospective/PIT paths, frozen prior results, dashboard and optimizer defaults remain
unchanged. A successful model postflight was not fabricated after the failed attempt.

See [verification record](v2-tactical-matchup-verification.md): 138 new tests pass; full
Python population is 2,497 passed / 14 Windows symlink failures / 4 skips. Ruff lint and
strict mypy pass; eleven unchanged files fail full formatting. Dashboard initially has
308 passed / 4 failures, with all 70 tests in its three failed files passing a serial
diagnostic; build/lint pass with existing warnings. The full gate is **not entirely green**.

All ten requested performance interpretation questions remain unanswered: forecastability
versus persistence, incremental goal/CS value, interactions versus recent-only state,
venue/opponent sensitivities, adjustment size, seasonal/early-season consistency, ordering
versus shrinkage, and operational value require complete predictions. The architecture has
not earned replacement of the incumbent, but has not been scientifically refuted either.

The separate [competitive workload probe](competitive-workload-source-audit.md) succeeded:
all five cup/Europe competitions returned HTTP 200, with XI/bench/substitution evidence but
no direct player-minutes field. It supplied no tactical input and no model result.

**Exactly one next model direction:** request a separately authorized numerical-method
amendment for this same tactical hypothesis, with robust convergence diagnostics and synthetic
near-optimum tests, then preregister any renewed evaluation before fitting. Preserve this
failed attempt; do not add features, alter the 1% gates or automatically restart V1.
