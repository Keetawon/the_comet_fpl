# Predicted-environment Gamma–Poisson DC: retained development result

`retrospective_predicted_environment_gamma_poisson_dc_v1` is **INCONCLUSIVE**.
It improves overall threshold log loss by **3.5652%** against the exact current DC
component, but fails the preregistered requirement to improve the past-witnessed
transfer slice. It is not eligible for the development synthesis and is not promoted.
The same-input Poisson diagnostic must not be selected as a replacement after this result.

The single formal run used clean preregistration/evaluation commit
`f0c52fe1e5546dd21e8f37b75bb8022c2d9c8bae`, from
2026-09-07T10:42:42.577911+00:00 to 10:44:18.899023+00:00. It completed normally.
There was no second fit/evaluation, parameter search, retuning or production change.

## Fixed population and forecastable inputs

The [design](dc-predicted-environment-v1-design.md) and
[config](../config/dc_predicted_environment_evaluation.yaml) were committed before
scoring. Only 2025-26 has measured archive DC targets and complete team CBIRT.
After ten prior measured gameweeks, the fixed primary population is **7,859 measured
outfield appearances, GW11–38, 28 folds**. The unconditional diagnostic retains all
**19,856 outfield roster rows** in those same folds. No actual target exposure selects
a predictive rate. The primary outcome is the loaded-rule position threshold hit,
not an observed count likelihood; full count PMFs are retained as decomposition evidence.

The shared current-selector reference remains 114 folds / 86,755 player-fixture rows /
821 direct archive-price proxy rows. This cohort intersects 12 primary and 74 full-roster
proxy rows. All 307 transfer targets are identified from earlier same-season stable-club
roster witnesses, including DNP witnesses; future full-season club stints are not used.
Excluding proxy rows is diagnostic only, not a replacement population.

Inputs are prior archive team CBIRT, position-specific player DC intensity, and the
unchanged shared predicted minutes. Team CBIRT includes CBI, tackles and recoveries;
DEF player DC excludes recoveries, whereas MID/FWD DC includes them. The intensity
ratio is therefore **not a conserved player share**. No SDP SOT, tactical features,
role labels or target-match team totals enter this candidate.

The fixed last-five team environment shrinks toward the fold-local league mean with
five prior matches. The player's last-five position-matched intensity ratio shrinks
with five league opportunities. Prior outfield mean minutes within each shared bin
scale the predicted full-match count. Every source satisfies `kickoff+6h < cutoff`
and excludes the entire target season/GW. Historical capture-time validity is not
asserted; strict prospective paths are unchanged.

One league-pooled NB2 dispersion is computed only from earlier sequential OOS
forecasts and subsequently observed counts. It subtracts Poisson and predicted
minutes-mixture variance, requires 200 rows and shrinks by `N/(N+100)`.
The 28 outer dispersions range **0.065125–0.080853**. GW11 uses 2,587 earlier OOS
appearances; GW38 uses 10,154. No frozen full-season variance constant is reused.
Both count arms preserve support 0..59 plus 60+ overflow, exact zero means and
original NULL/fallback semantics. Only the dispersion differs between the two arms.

## Results against the exact CURRENT comparator

The incumbent is `trailing_dc_threshold_hit_bernoulli_v1`, alpha=5 and window=5.
Direct-class versus actual component-factory probabilities reproduce exactly for
all 19,856 roster rows before the candidate claim. Their complete prediction hash is
`a6fb288ba96a762dd803ea9a74a2ab1d06e21a4c5e2d61e54bba9aebf2408312`.

| Arm | Mean binary log loss | Brier | AUC |
|---|---:|---:|---:|
| Exact CURRENT V1 | 0.342467929 | 0.104162934 | 0.775464 |
| Same-input Poisson diagnostic | 0.331565030 | 0.102935943 | 0.805131 |
| Gamma–Poisson candidate | 0.330258420 | 0.102396036 | 0.804368 |

The candidate improves log loss **3.5652%** and Brier **1.6963%** versus CURRENT.
The paired log-loss difference is −0.01220951; its 28-GW-clustered standard error is
0.00354490 and normal 95% interval is [−0.01915751, −0.00526151]. These intervals do
not adjust for serial dependence or establish prospective deployment evidence.

**Most of the aggregate gain is not the distribution change.** The prior-only
environment plus predicted exposure already gives the Poisson diagnostic a 3.1836%
log improvement versus CURRENT. NB adds only **0.3941%** beyond that same-input
Poisson: difference −0.00130661, GW-clustered SE 0.00119282, 95% interval
[−0.00364453, +0.00103131]. The incremental dispersion gain is not well resolved.

## Robustness and the failed gate

| Slice | Rows | CURRENT log | Poisson log | NB log |
|---|---:|---:|---:|---:|
| GW11–19 | 2,534 | 0.368376 | 0.353931 | 0.349194 |
| GW20–29 | 2,819 | 0.333378 | 0.323673 | 0.324230 |
| GW30+ | 2,506 | 0.326495 | 0.317827 | 0.317892 |
| Home | 3,930 | 0.319398 | 0.309391 | 0.310477 |
| Away | 3,929 | 0.365544 | 0.353745 | 0.350045 |
| Past-witnessed transfer | 307 | 0.140017 | 0.134332 | 0.142172 |
| No past-witnessed transfer | 7,552 | 0.350698 | 0.339583 | 0.337904 |

The transfer candidate log loss **regresses 1.5396%**, and transfer Brier worsens
from 0.033375617 to 0.034316182 (2.8181% relative regression), despite higher AUC.
Better ranking is not enough to satisfy the frozen proper-score requirement.
The direct-price/cold-start slice contains only 12 primary rows, all non-events;
its AUC is undefined and NB log loss is 0.106861 versus CURRENT 0.106065.
Do not use this tiny slice to tune a cold-start exception.

Five of six gates pass: overall 1% log improvement, nonregressing Brier, exact
population, single reported season passing and zero temporal leakage. The required
transfer improvement fails. One measured season cannot demonstrate cross-season
robustness; GW1–10 were upstream development history, not scored primary folds.

This does not reinterpret the old DC V2 result. The separate
[evidence qualification](v2-dc-evidence-qualification.md) documents that old research
used target-match actual team DC and actual minutes. Its conditional/oracle figures
cannot demonstrate the forecastability established or tested by this new design.

## Provenance and independent verification

Original database: `data/fpl.duckdb`, SHA256
`0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8`.
Config SHA256: `dd62d5db901d10e1004d7750763c7caaa97adf7e8b9820eaeba2220c209b02e4`.
Target-identity SHA256:
`0360247b82d979615df6e1c73974ed53a405555e5720a23ac376e7e5e62d79a4`.
The database, old model source/config/results and shared minutes evidence are preserved.

The retained [result](../results/v2_dc_predicted_environment_development.json) has SHA256
`a54ae95ca7a9111278fbc33b499021fa5bfc2cd6f0dbe788518d7de4157273f3`.
Its 38 OOS and 28 outer fold receipts identify the complete local raw output under
`D:/Personal/fpl-operations/verification/dc-predicted-environment-20260907T104500Z`.
That directory retains full conditional/unconditional count PMFs, outcomes, inputs,
capture-free archive history fingerprints, exact minutes lineage and dispersion certificates.
The summary JSON is not a claim that those external large fold files are stored in Git.

The [independent audit](../results/v2_dc_predicted_environment_independent_audit.json)
passes **7,358,810 checks with zero failures**, max numerical difference
4.86e−15. It checked all 542 source pins while HEAD/worktree still matched the clean
run, the original DB hash, all 38 complete prior-history fingerprints, every retained
count PMF and hit probability, exact CURRENT arithmetic, all labels and slices,
calibration buckets, AUC ties, uncertainty and gates. It called no estimator or runner.
Audit SHA256: `3ecca83fea49514328cb29a8d0cea79174aacf713338bb2c7612aa44df978dd5`.

The initial audit and a correction are both retained. Its sole initial failure was
the verifier reassociating `5*(hits/n)` as `(5*hits)/n` before hashing floats; numerical
checks already agreed, but byte hashes differed. The separate addendum checks all
19,856 CURRENT probabilities in the exact original operation order and reproduces
their hash. No model, prediction, score or formal result changed. Audit scripts are
under `D:/Personal/fpl-operations/verification/dc-independent-audit-20260907T105000Z`.

The pre-formal G-specific gate passed **55 tests**, Ruff/format and strict mypy on
both new modules. Repository-wide/environmental gate evidence is reported separately;
this is not a claim that unrelated Windows symlink failures were resolved.

Retain CURRENT DC for synthesis/defaults. This result motivates future investigation
of transfer calibration, not a post-result choice of the Poisson diagnostic or a
second candidate in this run.
