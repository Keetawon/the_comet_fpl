# V2 defensive contribution — first development evaluation

Run date: 2026-09-04
Contract: `config/v2_dc_evaluation.yaml` 1.0
Result: `results/v2_dc_development.json`
Population: 7,859 player-fixtures, 2025-26 only (DC exists in no other archived season)

**Status: development-only, NOT promoted, and it fails its gate.** But unlike the team-engine
and GK-saves candidates, this one fails for a diagnosed and separable reason, and the mechanism
it was built to demonstrate is confirmed.

## Headline

| model | log score | Brier | AUC | mean predicted | observed |
| --- | --- | --- | --- | --- | --- |
| `trailing_dc_threshold_hit_bernoulli_v1` | **0.34247** | 0.10416 | 0.7755 | 0.1328 | 0.1387 |
| `team_environment_share_dc_threshold_v2` | 0.34994 | **0.10051** | **0.8801** | 0.0559 | 0.1387 |

V2 **loses the primary metric by 2.18%** against a gate needing +1%, so it does not pass. It
wins Brier by 3.5% and AUC by **13.5%**.

## The pre-registered mechanism test passes

The contract required, before the run, that a candidate claiming "the team scale does not
travel with a transferred player" must improve **more** on transferred players than on
everyone else — otherwise it is improving for some other reason.

| slice | rows | V1 log | V2 log | log lift | Brier lift | AUC V1 → V2 |
| --- | --- | --- | --- | --- | --- | --- |
| **transferred** | 363 | 0.15343 | 0.13591 | **+11.42%** | **+12.46%** | 0.770 → **0.923** |
| not transferred | 7,496 | 0.35162 | 0.36030 | −2.47% | +3.35% | 0.771 → 0.877 |

V2 wins the transferred slice on every metric and loses the rest on log score. That is the
predicted pattern, and it is direct evidence for the repository's own measured rule: DC is a
property of the team system (team hit rates 0.333 to 0.146), so a transferred player's
expectation must be rescaled to the destination club rather than carried over.

**The slice is small — 363 rows — so treat the margin as directional, not settled.** It was
declared small in the contract's limitations before the run, not discovered afterwards.

## Why V2 loses overall: a calibration defect with a measured cause

V2 does not rank badly. It ranks far better than V1 — AUC 0.7755 → 0.8801, and on forwards
0.630 → **0.955**. What it does is **under-predict by a factor of 2.5**: mean predicted 0.0559
against an observed rate of 0.1387, where V1 sits at 0.1328 against 0.1387.

The reliability table shows the bias is present in every bucket:

| bucket | V1 predicted → observed | V2 predicted → observed |
| --- | --- | --- |
| [0.0, 0.1) | 0.0405 → 0.0406 | 0.0135 → **0.0663** |
| [0.1, 0.2) | 0.1285 → 0.1373 | 0.1442 → **0.3397** |
| [0.3, 0.4) | 0.3242 → 0.3756 | 0.3434 → **0.6021** |
| [0.5, 0.6) | 0.5113 → 0.4336 | 0.5432 → **0.7358** |

V1 is close to the diagonal; V2 is below it everywhere. A log score charges `-log(p)` on every
event at an understated `p`, so it punishes this hard. A bounded quadratic barely notices, and
AUC is invariant to any monotone transform, so it sees only the ranking. Hence the split
verdict.

### The cause is measured, and it is the Poisson

V2 converts an expected DC count into a threshold probability through a Poisson. Real
defensive actions cluster, so that is wrong in a specific direction. Measured over 2025-26
appearances of 60 minutes or more:

| position | n | mean DC | variance | variance / mean | actual P(≥ threshold) | Poisson at the same mean |
| --- | --- | --- | --- | --- | --- | --- |
| DEF | 3,026 | 7.451 | 13.998 | **1.88** | 0.2697 | 0.2180 |
| MID | 3,265 | 7.857 | 16.622 | **2.12** | 0.1792 | **0.1019** |
| FWD | 765 | 4.090 | 6.582 | **1.61** | 0.0118 | **0.0011** |

A Poisson has variance equal to its mean. DC counts carry **roughly twice** that, so the true
distribution has a much fatter right tail, and a Poisson evaluated at the correct mean
understates `P(count ≥ threshold)` for every player whose mean sits below the threshold — which
is most of them.

**This explains the position pattern exactly.** Midfielders have both the highest dispersion
(2.12) and the largest Poisson shortfall (0.1019 against an actual 0.1792, a 76%
under-statement), and midfielders are V2's worst slice at **−14.42%** log. Forwards have the
most extreme shortfall in relative terms (10x) but almost no hits to lose, so V2 still wins
there (+26.48%) on the strength of its ranking.

V1 is immune to this because it never passes through a count distribution at all: it estimates
the threshold probability directly as a shrunk empirical frequency. It buys calibration by
giving up resolution.

## What this licenses, and what it does not

**Not promotion.** The contract declares `promotion_requires_prospective_window`, DC exists in
one archived season, and the candidate misses its primary metric.

**Not a retune.** V2 is left exactly as committed. Swapping the Poisson for an over-dispersed
count model after seeing this result is precisely the post-hoc tweak pre-registration exists to
prevent. It needs a **separately named candidate with its own amendment**, and the dispersion
parameter must be fitted inside each fold, not taken from the table above — that table is a
diagnostic measured on the evaluation population and using it directly would be leakage.

**What it does establish** is narrower and more useful than a pass would have been: the V2
decomposition — team defensive-action environment x player role share x minutes exposure — is
a materially better *ordering* of who reaches the threshold (AUC +13.5%), and it is better in
the specific place the architecture predicts (transferred players, on every metric). The
failure is located in the count-to-probability conversion, which is a different component from
the allocation being tested.

Compare the GK Saves V2 result, where the hypothesis itself was refuted because the quantity it
sought to predict turned out to be largely unpredictable. This is the opposite situation: the
signal is real and the packaging is wrong.

## Limitations, declared before the run

* **One season.** No cross-season generalisation evidence exists in this archive, whatever the
  result says.
* **363 transferred rows.** Small, with a wide interval. Directional evidence only.
* **Poisson shape.** Now measured rather than suspected; see above.
* **Minutes independence.** This evaluation feeds V2 the *realised* on-pitch share so that the
  DC allocation is isolated from the minutes model. A prospective run would have to use a
  predicted exposure, and would be correspondingly worse.
