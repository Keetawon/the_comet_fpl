# Stage C Attacking Goals — Candidate V3 (minutes-gated coupled share) — development record

> [!IMPORTANT]
> **Development record only — not a promotion result.** Candidate V3
> (`minutes_gated_coupled_team_share_attacking_goals_v3`) was pre-registered under amendment 1.3
> (contract version `1.3`) and run **once** as a clean historical development run. `combined_promotion_verdict`
> is `null`: V3 is judged by no promotion gate. Although V3 **passes all eight frozen gate diagnostics
> on the archive**, it is NOT promoted: the historical target roster and first-kickoff cutoff are
> unversioned archive proxies AND the Stage B minutes input is itself a development proxy, so
> real-deadline knowledge-time validity is unproven, and a historical evaluation is not a promotion.
> A second historical evaluation is not permitted; nothing here is retuned.

## 1. Provenance and governance

| field | value |
| --- | --- |
| contract version | `1.3` (additive amendment; v1.0/1.1/1.2 population, roster, baselines, metrics, gate unchanged) |
| candidate | `minutes_gated_coupled_team_share_attacking_goals_v3` |
| pinned constants | `alpha = 5.0`, `share_window = 5`, minutes baseline `trailing_5_player_minutes`, Poisson over `0..10` |
| evaluation date | 2026-08-01 |
| reconciliation record | `docs/evidence/phase3-stage-c-attacking-candidate-v3-2026-08-01.json` (`schema: stage_c_candidate_v3_development/v1`) |
| runner | `src/fpl/validate/dev_attacking_candidate_v3.py` |
| commit sha | `b6c9f4cb21bf1f49e88fb508dab694e6e241a951` (clean worktree) |
| population | 133,964 eligible predictions over 181 folds (30 / 37 / 38 / 38 / 38) |
| exclusions | 0 |
| cold starts | 1,207 |
| leakage failures | 0 across all 181 folds |
| provenance | preflight + postflight recheck of worktree, HEAD, config, and V3/V2/V1 candidate-source fingerprints, and database fingerprint — all stable |

The runner fingerprints `attacking_v3.py` (the candidate) plus `attacking_v2.py` (live V3-vs-V2
co-score) and `attacking_v1.py` (V3-vs-V1 cited diagnostic). The live V2 co-score reproduced V2's
recorded development number bit-for-bit (overall mean log score `0.153232`), confirming the archive,
folds, and eligible rows are identical to V2's own evaluation.

## 2. Estimator (recap)

V3 is V2 with each player's coupled team-share rate gated by an appearance probability from the
frozen Stage B baseline `trailing_5_player_minutes` (`p_play = P(minutes >= 1) = 1 - dist[0]`), refit
fold-local on `kickoff_time < as_of`:

    weighted_i = share_i * p_play_i
    rate_i     = lambda_team * weighted_i / sum_j(weighted_j)   =>   sum_i rate_i = lambda_team.

`share_i` is V2's trailing attacking share (xG in covered seasons else threat, over appeared prior
rows). The renormalisation conserves the team total; minutes and per-appearance attacking rate are
kept as separate components (R6). Full specification: see the design record
`docs/phase3-stage-c-attacking-candidate-v3-design.md`.

## 3. Overall results

| model | mean log score (↓) | RPS (↓) | Brier P(≥1) (↓) | PIT-80 abs. err (≤0.05) |
| --- | :---: | :---: | :---: | :---: |
| xg_informed_trailing_player_goals_v1 (recorded) | 0.137813 | 0.034600 | 0.030862 | 0.0032 |
| **minutes_gated_coupled_team_share_attacking_goals_v3** | **0.140500** | **0.034401** | **0.030680** | **0.0012** |
| trailing_player_goal_rate_poisson (comparator) | 0.143547 | 0.035129 | 0.031384 | 0.0020 |
| positional_goal_rate_poisson | 0.154512 | 0.036650 | 0.032843 | 0.0044 |
| coupled_team_share_attacking_goals_v2 (diagnostic) | 0.153232 | 0.035671 | 0.031920 | 0.0038 |

**Primary lift vs `0.143547`: +2.1227%** (candidate 0.140500; required ≥ +1.0%). V3 beats both
required baselines on every metric.

## 4. Estimator path split (the headline diagnostic)

| slice | stage_a_coupled_appeared | stage_a_coupled_cold_start | stage_a_uninformative | equal_share |
| --- | ---: | ---: | ---: | ---: |
| overall | 103,428 (77.21%) | 30,536 (22.79%) | 0 | 0 |
| 2021-22 | 14,747 (71.23%) | 5,957 (28.77%) | 0 | 0 |
| 2022-23 | 21,500 (81.12%) | 5,005 (18.88%) | 0 | 0 |
| 2023-24 | 21,456 (72.18%) | 8,269 (27.82%) | 0 | 0 |
| 2024-25 | 22,613 (82.88%) | 4,670 (17.12%) | 0 | 0 |
| 2025-26 | 23,112 (77.70%) | 6,635 (22.30%) | 0 | 0 |

The path structure is identical to V2's (gating rescales rates within a path; it does not change
which path a target takes). Stage A was informative in every fold; the stage-A-uninformative and
equal-share fallbacks never fired.

## 5. Per-season mean log score (primary, ↓)

| season | folds | Candidate V3 | `trailing…` | lift | V3 RPS | V3 Brier(≥1) |
| --- | :---: | :---: | :---: | :---: | :---: | :---: |
| 2021-22 | 30 | 0.150934 | 0.152725 | +1.1743% | 0.036273 | 0.032139 |
| 2022-23 | 37 | 0.142570 | 0.143548 | +0.6840% | 0.034818 | 0.030779 |
| 2023-24 | 38 | 0.146964 | 0.148799 | +1.2360% | 0.035838 | 0.031649 |
| 2024-25 | 38 | 0.139808 | 0.144386 | +3.1723% | 0.034962 | 0.031620 |
| 2025-26 | 38 | 0.125582 | 0.131139 | +4.2402% | 0.030771 | 0.027736 |

V3 improves on the comparator in all five seasons on mean log score (and on RPS and Brier(≥1) in all
five). The lift grows with xG/minutes-history depth: smallest in the threat-only/partial seasons
(2021-22, 2022-23) and largest in the fully-covered recent seasons (2024-25, 2025-26).

## 6. Development diagnostics vs the frozen v1.0 gate

Each row is one labelled diagnostic (`DEVELOPMENT DIAGNOSTIC ONLY`); they are **not** combined into a
verdict. **8 of 8 diagnostics pass.**

| diagnostic | result | detail |
| --- | :---: | --- |
| aggregate mean-log-score lift ≥ 1.0% | PASS | lift +2.1227% (0.140500 vs `trailing…` 0.143547) |
| no aggregate RPS regression | PASS | lift +2.0732% (0.034401 vs 0.035129) |
| no aggregate Brier(≥1) regression | PASS | lift +2.2425% (0.030680 vs 0.031384) |
| PIT-80 abs. error ≤ 0.05 | PASS | 0.0012 |
| prediction coverage ≥ 1.0 | PASS | 1.0000 (133,964 / 133,964) |
| folds evaluated ≥ 181 | PASS | 181 |
| zero leakage failures | PASS | 0 |
| no per-season mean-log-score regression | PASS | 0 of 5 seasons regress (all improve +0.68% … +4.24%) |

**V3-vs-V2 diagnostic co-score (NOT a gate):** V3 0.140500 vs V2 0.153232 → **mean-log-score lift
+8.3093%** — minutes gating rescues the coupled approach. **V3-vs-V1 cited diagnostic (NOT a gate):**
V3 0.140500 vs V1 recorded 0.137813 → **−1.9494%** — V3 clears the gate but does not beat the best
independent candidate (V1) on the archive.

## 7. Verdict

**DEVELOPMENT-ONLY — NOT PROMOTED**, even though V3 passes every frozen gate diagnostic on the
archive. Candidate V3 is not promoted and is judged by no promotion gate. Three reasons:

1. **Proxy caveats (govern regardless of the number).** The historical target roster
   (`target_roster.historical_roster_status = archive_proxy_unversioned_at_real_deadline`) and
   first-kickoff cutoff (`cutoff.prediction_time = archive_first_kickoff_proxy_for_gameweek_deadline`)
   are unversioned archive proxies, so real-deadline knowledge-time validity is unproven; availability
   is excluded; the historical number is a development number, **not an upper bound**.
2. **The Stage B minutes input is itself a development proxy.** `trailing_5_player_minutes` is a frozen
   baseline (so no unpromoted-candidate dependency), but it is fit on unversioned archive history, so
   `p_play` carries the same knowledge-time caveat as the rest of the pipeline.
3. **A historical evaluation is not a promotion.** Promotion requires a separately pre-registered
   candidate to clear the unchanged gate against **prospective** data.

The best required Stage C attacking baseline (`trailing_player_goal_rate_poisson`) remains the Stage C
attacking model until a separately pre-registered candidate clears the unchanged promotion gate
against prospective data.

## 8. What the result tells us (diagnostic only)

Minutes gating is the difference between a failed and a gate-clearing structural hypothesis. V2
allocated the team-goal expectation among roster players but treated every player as certain to
appear, which pulled predictions toward the positional average (V2 0.153232, near the positional
baseline). Gating each player's rate by `P(minutes >= 1)` — keeping appearance probability and
per-appearance attacking rate as separate components (R6) — lets the team total flow to the players
actually likely to play, and V3 jumps to 0.140500 (+8.31% over V2), beating both baselines in every
season and clearing the full frozen gate. V3 nonetheless remains 1.95% behind V1 (the independent
xG-informed candidate), so among gate-clearing Stage C attacking candidates V1 is still the best on
the archive; the coupled, appearance-aware allocation is viable and gate-clearing but not yet
superior to the independent approach. V3 is left as committed and is **not retuned**.
