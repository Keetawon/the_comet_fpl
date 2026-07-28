# Candidate V3 invalidation: development result is INVALID for comparison

**STATUS: INVALIDATED.** Candidate V3's single historical development evaluation is **not a
non-promotion** — it is **invalid for model comparison or promotion**. Its aggregate, season,
cohort, CRPS, log-score, cold-start, and parameter-selection numbers must not be read, quoted,
or compared against any baseline or candidate. The trailing-goals baseline remains Stage A,
unchanged. This document supersedes the verdict in
[`phase1-candidate-v3-development.md`](phase1-candidate-v3-development.md); that file is kept
unchanged below its invalidation banner as an **audit record of the original values** only.

A later candidate (`dynamic_team_goals_v4`, contract amendment 1.5) is pre-registered
separately to fix the four defects named here. V4 has not been evaluated and this document
makes no claim about V4.

## Why the result is invalid rather than merely non-promoted

A documented *non-promotion* (V1, V2) is an honest number produced by a leakage-safe
procedure that simply did not clear the gate. V3's number is not that. Review of
`src/fpl/models/dynamic_team_goals.py` and `src/fpl/validate/dev_candidate_v3.py` found four
defects. Two are leakage (the model used information it should not have had at the cutoff),
one is a fitting procedure that does not match its own specification, and one makes the
recorded provenance unreliable. A leakage-tainted score cannot be salvaged by its being short
of the gate: the same leakage could just as easily have flattered it, so the number carries no
information about the model at all.

## Confirmed defects

### 1. Inner selection predicted all six held-out gameweeks from one frozen state

`_select_hyperparameters` replays the inner training matches through `_filter(...)` **once** to
a single state, then `_holdout_log_score(holdout_rows, state)` scores **every** holdout match
from that one frozen state. There is no per-holdout-gameweek predict-then-advance loop. A true
nested walk-forward would, for each chronological observed holdout gameweek, predict every
fixture in it from the pre-gameweek state, score, and only then absorb that gameweek's results
before moving to the next. Freezing the state collapses all six gameweeks onto one prediction,
so the selected `(learning_rate, retention, season_retention)` triple was chosen by a procedure
that does not match the walk-forward the contract specifies. The reported parameter-selection
counts (slowest learning rate in 153/181 folds, strongest summer shrinkage in 92/181) are
therefore artefacts of this collapsed procedure, not evidence about team-strength dynamics.

### 2. Cold-start residuals used the dynamic state before six matches, and returning promoted clubs kept old match counts

During fitting, the residual that drives the gradient step is computed against
`venue * exp(attack[team] + defence[opponent])` — the **raw dynamic rate**, not the cold-start
substituted rate that `_match_rate` applies at prediction time. So a club with fewer than six
matches has its strength updated from its first match using a residual measured against an
under-trained dynamic value, and the six-match cold-start rule is enforced at prediction but
**not** in fitting. Separately, at a season boundary the promoted branch resets a club's
attack and defence to the prior but **never resets `counts`**, which only ever increments. A
club relegated and promoted back therefore carries its previous Premier-League match count and
is never treated as cold-start again. Both contradict the declared six-match cold-start rule.

### 3. Promoted priors came from full-archive future outcomes (target leakage)

The promoted cold-start priors `0.719` (attack) and `1.309` (defence) are the **full-archive
measured constants** — estimated over all five seasons of promoted cohorts. They are applied as
fixed priors for promoted clubs in **every** season and **every** fold, including early folds
whose `as_of` precedes the seasons those estimates were drawn from. The 2021-22 opening fold
therefore predicts promoted clubs with a prior estimated partly from 2022-23…2025-26 outcomes:
event/target leakage through the prior. Because the prior directly moves the rate for every
cold-start prediction, the development report's `Leakage failures: 0` — which counts only the
harness's per-fold `kickoff_time < as_of` and truncation checks — is **false as a leakage
claim**. The harness's checks did not and could not see a leak smuggled in through a config
constant.

### 4. The runner accepted a dirty worktree while recording only a clean-looking SHA

`_commit_sha()` runs only `git rev-parse HEAD`, which returns the current commit **regardless
of uncommitted changes**, and its own docstring states it "keeps the runner usable from a dirty
tree rather than crashing." There is no `git status --porcelain` gate. An evaluation run over a
modified, uncommitted tree would therefore record the clean HEAD SHA while scoring the altered
code, so the recorded provenance cannot be trusted to identify what was actually scored. The
V3 development report's `evaluated under commit` line is consequently not a reliable
identifier of the scored code.

## What this changes

- **No V3 number is comparable.** Aggregate (1.4956), per-season, promoted-status, home/away,
  CRPS (0.6373), deviance, PIT coverage, cold-start count (84), and the parameter-selection
  counts are all invalidated. Do not quote them as a baseline, a comparator, or a V2 peer.
- **The Stage A model and every gate are unchanged.** The trailing-goals baseline
  (`1.5003`) and the 1% lift threshold (`1.4853`) stand exactly as before; V3 never entered
  the gate and still does not.
- **V3's code is left in place, frozen and labelled invalid.** Per the contract, a result may
  not be repaired after evaluation; the honest record is that V3 was evaluated under a
  leakage-tainted procedure and its number is void. The implementation is not modified to make
  its old result appear valid.
- **Contract amendment 1.5** records this invalidation as context for the separately
  pre-registered, leakage-safe Candidate V4. `candidates_evaluated_before_amendment` is `3`
  (V1, V2, and the invalid V3), reflecting that V3 produced a (now-void) development number
  before V4's policy was fixed.

## Original values (audit record only — DO NOT compare)

The values below are reproduced verbatim from the now-invalidated development report and are
retained **only** as an audit trail of what the defective procedure printed. They are not
evidence about the dynamic model.

| Field | Original (INVALID) value |
|---|---|
| Mean log score | 1.4956 |
| Mean CRPS | 0.6373 |
| Poisson deviance | 1.1267 |
| PIT 80% coverage | 0.802 |
| Raw 80% coverage | 0.937 |
| Within-gameweek Spearman | 0.319 |
| Cold starts | 84 |
| Folds / predictions | 181 / 3,640 |
| Per-season log (2021-22…2025-26) | 1.5014 / 1.5082 / 1.5390 / 1.4756 / 1.4551 |
| Parameter selections | learning_rate 0.05×153; retention 0.985×79, 1.0×78; season_retention 0.5×92 |

These reproduce [`phase1-candidate-v3-development.md`](phase1-candidate-v3-development.md);
that file now carries an invalidation banner and is preserved unchanged for auditability.
