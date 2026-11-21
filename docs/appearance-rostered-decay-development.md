# Rostered-decay appearance weight: single development evaluation (2026-11-21)

**Status: evaluated ONCE; all three pre-registered default-switch gates PASSED; the default
switched in the same change set's separate commit.** The preregistration
(`docs/appearance-rostered-decay-preregistration.md` +
`config/appearance_decay_evaluation.yaml`, contract 1.0) was committed at `24aba9b` (with the
frontier/availability refinements at `4dcba54` and `51b1a2c`) before the run. The immutable
result is `results/appearance_decay_evaluation_v1.json`, produced from a clean worktree at git
`51b1a2c` against the local dev database. There is no second run and no retuning.

## Selection (training boundaries 2022-23 / 2023-24 / 2024-25; 59 folds, 22,220 scored rows)

| arm | pooled mean log loss |
|---|---|
| `seasonal` calendar weight | 0.47754 |
| decay c=1 | **0.43478** |
| decay c=2 | 0.43827 |
| decay c=3 | 0.44219 |
| decay c=5 | 0.44965 |
| decay c=8 | 0.45913 |

Selected `c* = 1.0` (monotone in the grid: the faster the stale prior fades, the better).

## Held-out 2025-26 boundary (20 folds, 7,655 scored rows)

| measure | `seasonal` | `rostered_decay` c=1 | relative |
|---|---|---|---|
| pooled mean log loss | 0.48159 | **0.43697** | -9.29% |
| GW1-3 phase | 0.59760 | 0.56193 | -5.97% |
| GW4-6 phase | 0.57137 | 0.46129 | -19.27% |
| GW7-10 phase | 0.46324 | 0.40174 | -13.28% |
| GW11-20 phase | 0.42739 | 0.40649 | -4.89% |
| benched-prior subpop (rate < 0.2, 301 rows) | 0.42617 | 0.37597 | -11.78% |

Every phase improves; nothing regresses (max phase relative regression 0.0). The GW4-6 and
GW7-10 phases -- exactly where the stale prior met the shipped calendar weights 0.5 -- improve
most, matching the defect's mechanism.

## Gates (all passed)

1. Held-out pooled mean log loss beats `seasonal`: **pass** (0.43697 < 0.48159).
2. Held-out GW7-20 phase beats `seasonal`: **pass** (both phases).
3. No phase regresses by more than 2% relative: **pass** (0.0).

`default_switch_authorised: true` → the prospective default switched to
`--appearance rostered_decay` with `ROSTERED_DECAY_C = 1.0`, and the monitoring
classification's prospective-default triple is now `v3` / `coupled` / `rostered_decay`
(pre-switch `seasonal` vintages are recorded sensitivities and stay selectable). The
optimizer plan classification (keys on `v3`+`coupled` only) is unchanged by the switch.

## Population and coverage

29,875 scored rows; 24,848 blend-ineligible rows reported (no prior-season record under the
prospective-path semantics -- both arms identical for them by construction); **zero**
model-fallback rows among scored players (predicted by the preregistration: a scored player
has >= 10 eligible prior-season rows, so the trailing-5 window always has >= 5). 2022-23 has
19 folds, not 20 (GW7 does not exist that season -- iterated observed gameweeks, not assumed).

## Caveats (inherited, unchanged)

The target-roster and first-kickoff cutoff proxies are Stage B's documented unversioned
proxies; this is development evidence under them, not real-deadline validity. The evaluation
is archive-only: the 2025-26 -> 2026-27 boundary (the live one) was excluded from training
and gate and becomes the first prospective window in which the mode runs for real. The cold
start / launch-price prior cannot bind in the scored population (a scored player has a
prior-season record by construction); it remains part of the shipped mode's path.
