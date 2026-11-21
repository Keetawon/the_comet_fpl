# Preregistration: rostered-decay appearance weight (`rostered_decay_appearance_weight_v1`)

**Status at commit: preregistered, NOT scored.** This document and
`config/appearance_decay_evaluation.yaml` are committed before any scoring. The single
evaluation runs once from a clean worktree, its immutable result lands in
`results/appearance_decay_evaluation_v1.json`, and the constant it selects becomes
`ROSTERED_DECAY_C` in `src/fpl/jobs/prospective_points_v1.py`. Nothing here re-judges a
frozen evaluation, retunes a shipped model, or changes the prospective default: `seasonal`
stays bit-for-bit reproducible, and the default switches only in a separate recorded
commit if and only if every gate below passes.

## The defect being repaired (context, not evidence)

Two live-path data defects interact in the appearance layer (both confirmed from
published vintages; see `docs/prospective-live-data-plumbing-2026-11-21.md`):

1. `prior_season_appearance_rate` reads the archive mart, whose latest season is fixed
   during a live season. In November 2026 the blended "nailed-ness" rate is therefore
   always a 2025-26 rate, whether the target is GW1 or GW15.
2. The blend weight keys on the target's **calendar month** (0.7 Aug/Sep, 0.5 Oct/Nov, 0
   from December), so it decays on the calendar while its input stays stale all season.
   Measured proxy evidence over the 2023-24→2024-25, 2024-25→2025-26 and 2025-26→2026-27
   boundaries puts the best in-season prior weight at ~0.15-0.3 at GW4-6, GW7-10 and
   GW11-20; the shipped 0.5 is worse everywhere in that proxy. For players benched last
   season and starting now, w=0.5 gives log loss 0.77-0.83 against 0.52-0.60 at w=0.

## The candidate

`w(n) = 0.7 * c / (c + n)`, with `n` the player's **current-season rostered gameweeks
before the cutoff** (a rostered GW is one the player has a consumed row for, played or
DNP -- he was in the squad). Properties:

* `n = 0` (a genuine season-boundary target) keeps the measured boundary anchor 0.7 --
  the blend that best predicts a next-season opener. The candidate cannot alter the
  shipped boundary behaviour.
* The weight fades exactly as current-season rostered evidence accrues, at a
  pre-registered rate `c` selected on training boundaries only.
* A player absent from the squad keeps his `n` frozen, so his stale prior retains weight
  coherently with his equally stale trailing window.

The comparator is the shipped `seasonal` calendar weight, unchanged.

## Evaluation regime (pre-registered)

* **Training boundaries** (select `c`): target seasons 2022-23, 2023-24, 2024-25.
* **Held-out boundary** (gate): target season 2025-26.
* **Targets**: GW1-20 of each target season, one cutoff per GW = that GW's first kickoff
  (the documented first-kickoff cutoff proxy; unversioned, same caveat as Stage B).
* **Population**: every player with a target-season row at the scored GW (the
  target-roster proxy). The **scored subset** carries a prior-season appearance record
  under the prospective-path semantics (fact-row-resolved current club, eligibility rule,
  the Defect-1b not-available rule); blend-ineligible players cannot depend on `w` and
  are reported, not scored.
* **Real composer minutes path** (both arms share everything but `w`): equal-weighted
  trailing-5 bins with the Dirichlet shrinkage (alpha 3.5, out-of-side regime split,
  position priors) via the production helpers; the prior-season rate via
  `prior_season_appearance_rate` restricted to seasons the live path would hold archived
  (strictly before the target season); the blend and when-playing redistribution exactly
  as `season_boundary_minutes`. The launch-price starter prior applies only to cold
  starts, which by construction are outside the scored subset (no prior record); it is
  part of the shipped mode's path but cannot bind here.
* **Metric**: pooled mean Bernoulli log loss on `minutes >= 1`, probabilities clipped
  at 1e-6. Phase splits GW1-3 / GW4-6 / GW7-10 / GW11-20 and the benched-prior
  (`prior < 0.2`, `n >= 10`) and established-prior (`prior >= 0.6`) subpopulations are
  reported.
* **Selection**: `c*` = argmin pooled TRAINING mean log loss over the pre-registered grid
  {1, 2, 3, 5, 8}; ties resolve to the smaller `c`.

## Gates (all must hold on held-out 2025-26 for a default switch)

1. Held-out pooled mean log loss(`rostered_decay`, `c*`) < `seasonal`.
2. Held-out GW7-20 phase mean log loss < `seasonal` (the in-season staleness being
   repaired).
3. No phase split regresses by more than 2% relative.

On failure the mode still ships as `--appearance rostered_decay` at the selected `c` and
the default stays `seasonal`; there is no retuning and no second run.

## Known unversioned proxies (inherited, stated)

The target roster and the first-kickoff cutoff are the Stage B proxies: real-deadline
knowledge-time validity is unproven. Archive seasons prior to 2022-23 carry no xG; the
appearance path does not consume xG, so coverage is unaffected. The 2025-26→2026-27
boundary is NOT in this evaluation's training or gate (its live captures are partial);
it becomes the first prospective window in which the mode runs for real.
