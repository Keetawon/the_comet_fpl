# V2 football engine and GK saves V2 — first development evaluation

Run date: 2026-09-04
Contracts: `config/v2_team_environment_evaluation.yaml` 1.0, `config/v2_gk_saves_evaluation.yaml` 1.0
Result: `results/v2_team_environment_development.json`
Provider at evaluation time: `fpl_archive` (no SDP payload had yet been captured)

**Status: development-only. Neither candidate is promoted, and neither cleared its gate.**
Both contracts declare `promotion_requires_prospective_window`, so no historical result here
could have promoted anything even had it passed.

**Postscript, 2026-09-05:** real SDP data now exists, but nothing below was rerun or reinterpreted.
The historical backfill was first known in September 2026, so feeding it into the old folds without
an as-of provider-version contract would violate point-in-time evaluation conditions. The capture
evidence and the work still required before a genuine SOT/territory ablation are recorded in
`docs/pl-sdp-real-provider-validation-2026-09-05.md`.

## Provenance

Produced at HEAD `ac2fefd` with a **clean worktree**, verified by the runner rather than
asserted: `dev_v2_team_environment` refuses to run against a dirty worktree, because Phase 1
Candidate V3's result was invalidated in part because "the runner accepted a dirty worktree"
and its number is now void for comparison.

An earlier run of the same evaluation was made before that guard existed, and recorded
`clean_worktree: false`. It was discarded and re-run rather than published. The re-run
reproduced **every figure in this document to five decimal places** — the six overall model
scores, all five per-season team-environment lifts, and all five per-season saves lifts — so
the numbers below carry an independent reproducibility check as well as clean provenance.

## Harness validation before anything else

The best baseline, `trailing_goals_attack_defence`, scores **1.50030** over 181 folds and 3,640
team-fixture predictions. The frozen Phase 1 record is **1.5003 over 181 folds and 3,640
predictions**. The V2 harness reproduces the incumbent's number to five decimal places on an
independently-built population, which is the evidence that the comparison below is measuring
models rather than measuring a new harness.

## Team environment: does not clear the gate

| model | mean log | CRPS | PIT-80 | lift vs best baseline |
| --- | --- | --- | --- | --- |
| `v2_env_b_goals_xg` | 1.49599 | 0.63722 | 0.7945 | **+0.2867%** |
| `v2_env_c_goals_xg_sot` | 1.49599 | 0.63722 | 0.7945 | +0.2867% |
| `v2_env_d_goals_xg_sot_territory` | 1.49599 | 0.63722 | 0.7945 | +0.2867% |
| `v2_env_a_goals` | 1.49990 | 0.63984 | 0.7953 | +0.0265% |
| `trailing_goals_attack_defence` | 1.50030 | 0.63925 | 0.7942 | — |
| `trailing_xg_attack_defence` | 1.51074 | 0.64599 | 0.7989 | −0.6962% |

The gate needs 1% and a non-regression in every reported season. It gets 0.2867%, and
**2021-22 regresses by −0.2108%**, so it fails on both counts.

Per-season lift of rung B over the incumbent: 2021-22 **−0.21%**, 2022-23 +0.05%,
2023-24 +0.44%, 2024-25 **+0.91%**, 2025-26 +0.13%.

**Rungs C and D are bit-identical to rung B, and that is the coverage constraint, not a null
result.** `shots_on_target` and `touches_in_opposition_box` exist only in the `pl_sdp` provider,
which had not been captured for this frozen run, so those rungs had no additional signal to add.
The upper half of the ablation ladder is declared and implemented but **untested**. Nothing here
says anything about whether shot volume or territory helps.

### What the blend actually learned

The inner holdout selects the xG weight per fold, and it rises monotonically with coverage:

| season | folds | folds where xG cleared the coverage floor | mean selected xG weight |
| --- | --- | --- | --- |
| 2021-22 | 30 | 0 | — |
| 2022-23 | 37 | 6 | **0.000** |
| 2023-24 | 38 | 38 | 0.362 |
| 2024-25 | 38 | 38 | 0.579 |
| 2025-26 | 38 | 38 | 0.645 |

Two things follow. First, the engine is not being credulous about xG: in the six 2022-23 folds
where xG was available at all, the holdout chose to weight it **zero**. Second, rung B equals
rung A exactly in 2021-22 and almost exactly in 2022-23, so the pooled +0.2867% is an average
over two seasons where the candidate could not differ from its own floor. This is the same
regime effect already recorded for Stage A: **never quote the pooled figure as the answer.**

## GK saves: the hypothesis is refuted in the regime that matters

| model | mean log | CRPS | PIT-80 | rows using the engine signal |
| --- | --- | --- | --- | --- |
| `gk_saves_v2_from_expected_shots_faced` | 2.00631 | 1.04694 | 0.7626 | 3686 / 3686 |
| `gk_saves_v1_from_team_conceded` | 2.00969 | 1.05358 | 0.7604 | 0 |

Pooled, V2 improves log score by +0.168% and CRPS by +0.63%. **Both figures are misleading and
the per-season split inverts them:**

| season | V1 log | V2 log | lift |
| --- | --- | --- | --- |
| 2021-22 | 2.02003 | 1.99231 | **+1.37%** |
| 2022-23 | 2.06283 | 2.01574 | **+2.28%** |
| 2023-24 | 2.04561 | 2.06817 | **−1.10%** |
| 2024-25 | 1.99898 | 2.02375 | **−1.24%** |
| 2025-26 | 1.92263 | 1.92777 | −0.27% |

V2 wins the two seasons before xG coverage is complete and loses every season after it. The
crossover is exactly where the football engine's goal rate stops being goals-only and starts
carrying xG — the same boundary as the table above.

**The mechanism is measurable, and it says the premise was wrong.** Measured over 2025-26's 767
goalkeeper appearances:

| quantity | value |
| --- | --- |
| corr(V1 implied shots faced, V2 predicted shots faced) | **0.764** |
| corr(V1 implied shots faced, ACTUAL shots faced) | **0.310** |
| corr(V2 predicted shots faced, ACTUAL shots faced) | **0.279** |
| sd(V1 implied) / sd(V2 predicted) / sd(actual) | 1.14 / 0.93 / **2.16** |
| mean(V1) / mean(V2) / mean(actual) | 4.40 / 4.40 / 4.12 |

The V2 candidate was motivated by a real measurement: `corr(team shots on target allowed, goals
allowed) = 0.621` over 3,800 team-matches, so V1's identity discards ~61% of the variance in
shots faced. **That variance turns out to be almost entirely unpredictable.** Neither model's
prediction reaches a correlation of 0.32 with what actually happens, and both predict with less
than half the spread of reality. The two predictions agree with each other (0.764) far more than
either agrees with the outcome, and in the well-informed regime V1's rearrangement of its goal
rate is the **better** of the two.

So V2's small pooled CRPS gain is not better discrimination. It is a slightly more conservative
rate — sd 0.93 against 1.14 — which scores marginally better when neither prediction carries
much information. That is winning by shrinking, and it does not survive being split by season.

**Do not re-open this on the correlation argument.** A realised correlation between two
outcomes is not an upper bound on the predictable relationship between them, and this is the
second time in this repository that a promising realised statistic has failed to convert:
compare the Stage A recency audit, where a level correction that fixed the level exactly was
worth −0.01%.

## Limitations

* At this evaluation's frozen knowledge time no SDP data existed, so rungs C and D remain untested.
  The later 2026-09-05 capture does not retroactively change that result.
* Both saves models truncate the distribution at 10 saves. Five of 3,846 goalkeeper appearances
  (0.13%) exceed it. Both are truncated identically, so the comparison is fair, but neither
  model can score an 11-save match correctly.
* Both saves models are under-dispersed: PIT-80 of 0.7626 and 0.7604 against a nominal 0.80.
  Fixing that is a separate question from where the shot volume comes from.
* The historical target roster and first-kickoff cutoff remain unversioned proxies, so
  real-deadline validity is unproven for everything here.

## What this licenses

Nothing is promoted. `trailing_goals_attack_defence` remains the Stage A model and
`gk_saves_v1` remains the composer's saves component. Both V2 candidates are left as committed
and are **not retuned**: tuning a candidate after seeing its result is what the pre-registered
contract exists to prevent.

The next experiment worth running is stated in `DEV-ROADMAP.md`; it is not more shrinkage
tuning, and it is not a re-run of either candidate.
