# Candidate V3 development result: concentration-adaptive shrinkage

> **DEVELOPMENT ONLY — NOT A PROMOTION VERDICT.** The historical archive (2021-22 through
> 2025-26) is development evidence under two unversioned proxies (the target roster and the
> first-kickoff cutoff), not a real-deadline holdout. No number here promotes a model. Candidate
> V3 is **not promoted**: it fails the v1.2 starter-ranking gate — and the reason it could not be
> promoted regardless is the unversioned proxies.

Single clean historical development run, 2026-07-30, against a pristine `build_db`-rebuilt archive.
Machine-readable record: [`evidence/phase2-stage-b-candidate-v3-2026-07-30.json`](evidence/phase2-stage-b-candidate-v3-2026-07-30.json).

## Identity and provenance

| | |
|---|---|
| Candidate | `concentration_adaptive_shrinkage_player_minutes_v3` (amendment 1.4, contract v1.4) |
| Commit | `9ba2f9fbd8e38fb36974eeaac790932abfb60639` (clean worktree before and after) |
| Config fingerprint | `1c57edc55e20083250c8c94c3718c21d6ee63ffa529d89be73c8bc7cf82b6082` |
| Candidate source fingerprint | `2777082c7931a9299657c1173ff96ebf4df91ed35a6e5b4c4b83b9b68c2a8170` |
| Archive fingerprint | `fd2bceca53fb4789df5fcd9a05c68576c23e68cd15f22d84c961876cf9ff4ec3` |
| Seed | 202627 |
| Folds / eligible predictions / leakage | 181 (30/37/38/38/38) / 133,964 / 0 |

### Validity gate: baselines reproduce V1/V2 bit-for-bit

The archive fingerprint differs from the V1/V2-era `c37aa58c…` (a different DuckDB build), so
comparability was confirmed the rigorous way: the four baselines reproduce V1's and V2's frozen
overall values **bit-for-bit** (mean log score `position_minutes_frequency` 1.0491566551300036,
`trailing_5_team_position_minutes` 1.1271469209895286, `trailing_5_player_minutes`
3.1264177104931354, `last_observed_player_minutes` 7.0258624391112665, and every RPS/Brier/Spearman
in kind), with identical fold count, prediction count, and zero leakage. The historical facts are
therefore identical to the V1/V2 runs, and V3's candidate number is directly comparable.

## Required baselines and Candidate V3 (overall)

Lower log, RPS, Brier-any, and Brier-60+ are better; higher Spearman-p60 is better (report-only
except as the v1.2 starter-ranking gate). The best (best-directional) value in each scored column
is bolded.

| model | log | RPS | Brier any | Brier 60+ | Spearman p60 |
|---|---:|---:|---:|---:|---:|
| **concentration_adaptive_shrinkage_player_minutes_v3** | **0.71205** | **0.29193** | **0.10635** | **0.09863** | 0.69726 |
| position_minutes_frequency | 1.04916 | 0.59531 | 0.23766 | 0.20115 | — (group-constant) |
| trailing_5_team_position_minutes | 1.12715 | 0.58225 | 0.23134 | 0.19734 | 0.12846 |
| trailing_5_player_minutes | 3.12642 | 0.31901 | 0.11552 | 0.10885 | 0.70219 |
| last_observed_player_minutes | 7.02586 | 0.38054 | 0.13365 | 0.12650 | **0.70851** |

V3 is the best of all five models on **every proper score** (log, RPS, both Brier margins). PIT-80
coverage is 0.81457 (|error| 0.01457); prediction coverage 1.0; 27,971 cold starts.

## The v1.2 gate (each a development diagnostic; never combined into a verdict)

| Gate criterion | Bar (best-per-metric) | V3 | Result |
|---|---|---|---|
| `minimum_primary_relative_lift` ≥ 1% | `position_minutes_frequency` 1.04916 | +32.13% | PASS |
| RPS no-regression | `trailing_5_player_minutes` 0.31901 | 0.29193 (+8.49%) | PASS |
| Brier-any no-regression | `trailing_5_player_minutes` 0.11552 | 0.10635 (+7.94%) | PASS |
| Brier-60+ no-regression | `trailing_5_player_minutes` 0.10885 | 0.09863 (+9.39%) | PASS |
| **Spearman-p60 no-regression** | **`last_observed` 0.70851** | **0.69726 (−1.59%)** | **FAIL** |
| PIT-80 |err| ≤ 0.05 | — | 0.01457 | PASS |
| coverage ≥ 1.0 | — | 1.0 | PASS |
| folds ≥ 181 | — | 181 | PASS |
| per-season log no-regression | — | 0 of 5 regress | PASS |
| zero leakage | — | 0 | PASS |

`combined_promotion_verdict` is **null** in the evidence record. Nine of ten diagnostics pass; the
starter-ranking gate fails.

## The hypothesis is refuted — the goalkeeper ranking did not recover

V3 was designed to recover the goalkeeper/starter ranking V2 lost, by shrinking less where the
history is concentrated. It did not:

| position | V2 Spearman | V3 Spearman | Δ | `last_observed` (bar) | n |
|---|---:|---:|---:|---:|---:|
| GK  | 0.8153 | 0.8156 | **+0.0003** | 0.8650 | 14,890 |
| DEF | 0.6833 | 0.6882 | +0.0049 | 0.6818 | 44,678 |
| MID | 0.6593 | 0.6536 | −0.0057 | 0.6382 | 58,386 |
| FWD | 0.6449 | 0.6317 | −0.0132 | 0.6490 | 16,010 |

Goalkeeper ranking — the target of the whole design — barely moved (+0.0003) and stayed far below
the `last_observed` bar (0.8650). Aggregate Spearman *fell* (0.70071 → 0.69726), because FWD and
MID ranking degraded. **The starter-ranking gap is not a shrinkage-strength problem.** Sharpening a
concentrated distribution toward a one-hot compresses the P(60+) differences *among* nailed
starters (they all move toward ≈1.0), which reduces rank resolution rather than improving it. The
ranking signal `last_observed` captures is crisp single-fixture recency, and no amount of
re-weighting or adaptive shrinkage on a five-fixture window recovers it.

## Adaptation was genuinely selected — it just optimises the wrong thing

The pre-registered risk was that the inner selector (which optimises log score, not ranking) might
pick small `lambda`. The opposite happened: **`lambda > 0` was selected in all 175 selectable
folds** (the 6 `lambda = 0` folds are the `< 14`-history fallback):

| (decay, alpha, lambda) | folds |
|---|---:|
| (0.7, 2.0, 0.75) | 146 |
| (0.5, 2.0, 0.75) | 23 |
| (1.0, 5.0, 0.0) — fallback | 6 |
| (0.7, 5.0, 0.75) | 4 |
| (0.9, 5.0, 0.75) | 1 |
| (0.5, 2.0, 0.5) | 1 |

Modal `lambda = 0.75`. So the log-score signal for adaptation was strong — concentration-adaptive
shrinkage genuinely improves the distribution — which is exactly why V3 wins every proper score.
But log-score improvement and ranking improvement are not the same objective here: sharpening
helps the former and hurts the latter. The candidate could not be gamed toward the gate because the
inner objective stayed log score, as pre-registered.

## Slices

- **By season (mean log score, no regression):** lifts vs `position_minutes_frequency` of +27.57%
  (2021-22), +31.77% (2022-23), +33.08% (2023-24), +31.87% (2024-25), +34.89% (2025-26). No
  per-season regression.
- **Transfer (reported plainly):** `changed_team_code` regresses **−23.99%** vs the comparator
  (V3 1.55106 vs 1.25096, n=367) — worse than V2's −16.48%. Sharpening a concentrated *old-club*
  history makes the wrong post-transfer prediction more confident, so the concentration mechanism
  actively harms transferred players. `same_team_code` +32.58% (n=132,390); `no_prior` ties the
  comparator by construction.
- **Calibration (report-only, gates nothing):** PIT-80 coverage 0.81457 (|error| 0.01457), the
  best-calibrated of the three candidates on the band measure.

## V3 vs V2 (diagnostic)

| metric | V3 | V2 | direction |
|---|---:|---:|---|
| log | 0.71205 | 0.72625 | better |
| RPS | 0.29193 | 0.29568 | better |
| Brier-any | 0.10635 | 0.10791 | better |
| Brier-60+ | 0.09863 | 0.10005 | better |
| Spearman-p60 | 0.69726 | 0.70071 | **worse** |

V3 is the best distributional minutes model built so far and the worst starter ranker of the three
candidates on aggregate. The two moved in opposite directions, which is the whole finding.

## Verdict

**DEVELOPMENT ONLY. Not promoted.** V3 fails the v1.2 starter-ranking gate (Spearman-p60 0.69726 vs
best baseline 0.70851, −1.59%), a larger miss than V2's. Independently, no historical number could
promote it: the target roster and first-kickoff cutoff are unversioned proxies, so real-deadline
knowledge-time validity is unproven. Per the pre-registration, V3 is left as committed and is **not
retuned** after this result.

The result is a clean, informative negative:
1. Concentration-adaptive shrinkage is the best minutes model here on every proper score — the
   distributional hypothesis is supported.
2. It does **not** recover starter ranking; goalkeeper ranking is essentially unchanged and
   aggregate ranking regresses. Sharpening trades rank resolution for distributional accuracy.
3. The starter-ranking gap therefore is not addressable by tuning shrinkage strength on a
   five-fixture window. A future candidate that targets ranking would need a different structure —
   e.g. a crisp last-observed component for the P(60+) margin — not more shrinkage adaptation. That
   is a separately-named future hypothesis, not a retune of V3.

The amendment 1.2 starter-ranking gate is what makes this legible: without it, V3 posts the best
log score, the best RPS, and both best Brier margins and reads as an obvious promotion, while
actually ranking who starts and plays 60+ *worse* than every prior model. The gate caught exactly
the failure it was added to catch.
