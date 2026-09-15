# Predicted-environment Gamma-Poisson DC: additive preregistration

Candidate: `retrospective_predicted_environment_gamma_poisson_dc_v1`.
Evidence: `retrospective_archive_price_proxy_development`; no production promotion.
This is a new development architecture, not a retune or rerun of DC V2. The
[additive source qualification](v2-dc-evidence-qualification.md) distinguishes the
old oracle-conditional diagnostic from a prospective-input experiment. No target
fixture team total, target playing time, or frozen full-season variance enters a
new predictor. The numerical rules below are frozen before formal prediction.

## Coverage and exact population

The coverage-only audit `results/dc_predicted_environment_coverage.json` pins the
unchanged original database SHA256
`0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8`.
Only 2025-26 supplies DC and team CBIRT: 29,747/29,747 player rows and 760/760 team
rows are measured. All 10,725 outfield appearances have measured DC and a matching
team environment. Earlier archived seasons have no measured DC; NULL is not zero.

Retain the original DC population policy: measured appeared DEF/MID/FWD, after at
least ten prior measured observed GWs. This gives **7,859 rows, 28 folds**. Sorted
`(season,gw,fixture,code)` identity SHA256 is
`0360247b82d979615df6e1c73974ed53a405555e5720a23ac376e7e5e62d79a4`.
The corresponding complete outfield roster contains **19,856** rows, retained only
as an additional unconditional-hit diagnostic. Neither its inclusion nor a proxy
exclusion may replace the primary appeared population.

The primary transferred slice uses only past information: any prior dated archive
roster witness at a different permanent team code in the same season. DNP witnesses
are retained; no continuous-registration inference is made. All subsequent
post-transfer appearances stay in the slice: **307** primary rows. This differs
deliberately from the old 363-row full-season future-stint flag. The old flag is
not a predictor or the new primary mechanism test.

## Comparator and isolation

Primary: exact current `trailing_dc_threshold_hit_bernoulli_v1`, using unchanged
`DefensiveContributionV1` and the current component-suite factory: alpha 5,
trailing five measured appearances, fold-local position hit-rate prior, loaded
2026/27 position thresholds. Its appearance-conditioned prediction is the value
currently passed to the composer. Both the direct class and existing factory must
reproduce it exactly before candidate predictions. Research V2 is not a comparator.

A new **same-input Poisson** diagnostic uses the candidate's identical predicted
environment, ratio, minutes weights and fallback with dispersion exactly zero.
It isolates the incremental effect of Gamma-Poisson shape; a win over incumbent
alone does not establish that shape caused the win. No SOT, role, tactical,
opponent feature, or venue effect is added in this bounded component.

## Historical event-time boundary

Use the shared current-minutes proxy cache and its unchanged predicted four-bin
PMFs, complete price/selector lineage and first-target-kickoff cutoff. All prior
player/team observations must satisfy `kickoff + 6 hours < cutoff`, excluding the
entire target `(season,gw)`, including earlier DGW legs and postponed fixtures.
Six hours is a conservative development exclusion, not a verified final whistle.
The coverage audit finds zero otherwise-eligible 2025-26 rows within this margin,
so exact current V1 history is reproduced on this population. If later data would
break that equality, fail comparator reproduction rather than alter the incumbent.

Generate every target GW's mean forecasts from one frozen pre-GW state, then
make the completed batch eligible for later folds. Historical capture knowledge
is unproven and is never rewritten; this remains the named retrospective regime.

## Prior-only mean construction

Team opportunity is archived **CBI + tackles + recoveries** across all player
rows. It is not the sum of heterogeneous FPL DC labels: DEF DC omits recoveries,
whereas MID/FWD DC includes them. The audit independently reconciles every raw
row and all 760 team totals with zero missing summands or disagreements. The
player quantity below is therefore an intensity ratio, not a conserved share.

1. Let `L` be the mean of all prior measured team CBIRT totals. Team environment
   is `(sum(last five team totals) + 5*L)/(n_team + 5)`. A club without a measured
   history uses this prior league estimate, never its future-season average.
2. Each prior measured appearance contributes count `y` and opportunity
   `e = team_CBIRT * minutes/90`. Position prior is `sum(y)/sum(e)` over prior
   positive-opportunity appearances at that position. A missing/zero denominator
   supplies no ratio; it is not imputed. A player's count exceeding its complete
   team opportunity total is a contradiction and fails closed.
3. Over the player's latest five measured positive-opportunity appearances at
   the same observed position, use
   `ratio = (sum(y) + 5*L*position_prior)/(sum(e) + 5*L)`.
   Permanent player identity carries this ratio across clubs, while the target
   club supplies its new environment. Position changes use that position's pool.
4. Full-match mean is `environment*ratio`. Played-bin means multiply it by the
   fold-local mean prior outfield minutes in that bin, divided by 90. Empty prior
   bins use fixed existing-contract representatives `(0,59,89,90)`, explicitly a
   model fallback, not filling a missing provider observation. Bin zero is zero.

All shrinkage constants are fixed at five; no grid or outer-result adjustment.

## Prequential dispersion, not an evaluation-season variance

Retain each earlier GW's immutable out-of-sample mean DTO with target identity,
prediction cutoff, maximum source kickoff, history SHA256, environment, ratio,
per-bin means and shared predicted minutes. Its target count is attached only as
an observation for later fitting. The count must never generate its own mean.

For prior observed appearances with a valid mean and positive predicted appearance
probability, normalise the predicted played-bin weights to `q`. Let `mu_bar` be
`sum(q*mu_bin)`, `S = sum(q*mu_bin^2)`, and `V_bins = max(0,S-mu_bar^2)`.
The single pooled NB2 dispersion, with `Var(Y|bin) = mu + alpha*mu^2`, is

`alpha = max(0, sum((y-mu_bar)^2 - mu_bar - V_bins)/sum(S)) * N/(N+100)`.

At least **200** eligible prior out-of-sample appearances and a positive
denominator are required; otherwise alpha is exactly zero (Poisson). The
subtraction prevents the already-modelled predicted-minutes mixture variance
from being attributed to NB overdispersion again. Observed minutes only select
the appeared training cohort, never the forecast's bin or count mean.

This is one global league-pooled dispersion, no position-specific estimates or
search. Negative excess variance resolves to the Poisson boundary. No arbitrary
dispersion cap is fitted. Finite arithmetic and the as-of boundary are checked;
unrepresentable numerical values fail the run. Dispersion fitted for another
or later target cutoff cannot be applied to a mean prediction.

## PMFs, minutes and fallback

Retain Gamma-Poisson count probabilities on `0..59` plus `60+` overflow, conditional
on appearance and unconditional. Thresholds 10/12 are loaded from scoring rules,
so overflow preserves their hit probabilities. The same-input alpha-zero path
delegates the existing Poisson PMF exactly. A zero mean is an exact zero-count
point mass. A stable log-CDF computes NB overflow without cancelling its small
tail at large dispersion. No missing count is filled and no model-rate floor is
introduced; the existing scoring-only probability floor remains `1e-12`.

The primary appeared cohort is scored against the **conditional-on-appearance**
hit probability `sum(q*P(count>=threshold|bin))`; no actual target minutes are
consulted. The unconditional diagnostic is `predicted_p_play * conditional_hit`.
Both use the same cache as current V1, whose diagnostic probability is likewise
`predicted_p_play * V1_hit`. Neither appearance gate is applied twice.

If the prior opportunity ratio is unavailable, retain the row and exact current
V1 conditional probability. If predicted appearance is zero, retain that same
explicit conditional fallback and unconditional zero. An unavailable count PMF
stays NULL rather than being invented from a Bernoulli. Record every fallback.

## Gates and bounded run

Retain the established DC gate: at least 1% relative primary binary log-score
lift against exact current V1, no Brier regression, and improvement on the
past-witnessed transferred slice. Require the reported season to pass, no leakage,
identical primary rows and acceptable calibration reporting. AUC with half-credit
ties, reliability bins, position, GW phase, transfer, cold/proxy and predicted
exposure slices, paired GW-clustered uncertainty, conditional/unconditional
counts and same-input Poisson are mandatory diagnostics, not retuning selectors.
No cross-season generalisation can be established from this sole covered season.

Generate at most 38 prior-only environment states and 28 primary outer outputs;
there is no hyperparameter search. Seed 20260907 is recorded although the pure
component is deterministic and draws no randomness. Complete source/config/tests
must be cleanly committed before any candidate forecast. The runner must reserve
one shared-Git claim, retain full predictions, verify source/database/cache hashes
before and after, refuse dirty provenance and refuse result overwrite. A failed
run stays failed. The outcome cannot promote or modify any prospective default.
