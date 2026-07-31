# Stage C Attacking Goals — Candidate V2 (coupled team share) — development record

> [!IMPORTANT]
> **Development record only — not a promotion result.** Candidate V2
> (`coupled_team_share_attacking_goals_v2`) was pre-registered under amendment 1.2 (contract
> version `1.2`) and run **once** as a clean historical development run. `combined_promotion_verdict`
> is `null`: V2 is judged by no promotion gate. The historical target roster and first-kickoff
> cutoff are unversioned archive proxies, so real-deadline knowledge-time validity is unproven, and
> a second historical evaluation is not permitted. Nothing here is retuned. V2 is worse than the
> best baseline and than Candidate V1 on every scored metric; the team-share-coupling structural
> hypothesis is refuted on this archive.

## 1. Provenance and governance

| field | value |
| --- | --- |
| contract version | `1.2` (additive amendment; v1.0/1.1 population, roster, baselines, metrics, gate unchanged) |
| candidate | `coupled_team_share_attacking_goals_v2` |
| pinned constants | `alpha = 5.0`, `share_window = 5`, Poisson over `0..10` |
| evaluation date | 2026-08-01 |
| reconciliation record | `docs/evidence/phase3-stage-c-attacking-candidate-v2-2026-08-01.json` (`schema: stage_c_candidate_v2_development/v1`) |
| runner | `src/fpl/validate/dev_attacking_candidate_v2.py` |
| commit sha | `62e97be3521705acd460d4342eafa7a8cb38aa39` (clean worktree) |
| run window (UTC) | started `2026-07-31T18:33:20Z`, ended `2026-07-31T18:36:48Z` |
| population | 133,964 eligible predictions over 181 folds (30 / 37 / 38 / 38 / 38) |
| exclusions | 0 |
| cold starts | 1,207 |
| leakage failures | 0 across all 181 folds |
| provenance | preflight + postflight recheck of worktree, HEAD, config, candidate-source (V2) and V1-diagnostic-source fingerprints, and database fingerprint — all stable |

The runner fingerprints both `attacking_v2.py` (the candidate) and `attacking_v1.py` (re-scored
live for the V2-vs-V1 diagnostic co-score, not a gate). Candidate V1's live re-score reproduced its
recorded development number bit-for-bit (overall mean log score `0.137813`), confirming the archive,
folds, and eligible rows are identical to V1's own evaluation.

## 2. Estimator (recap)

For each fold, V2 refits the frozen Stage A `trailing_goals_attack_defence` on team-match history
(`kickoff_time < as_of`) and allocates each club's expected goals `lambda_team` among its eligible
roster in the fixture by a trailing attacking share: `rate_i = lambda_team * share_i`,
`sum_i share_i = 1`, so `sum_i rate_i = lambda_team` (Poisson thinning). Each player's share signal
is the mean of `expected_goals` (xG-covered seasons 2023-24+) or `threat` (else) over the trailing 5
**appeared** prior rows (`minutes > 0`); a cold-start player takes the positional mean of the same
signal type; a zero-signal roster takes equal shares. Where Stage A is uninformative the candidate
falls back to the exact v1.0 trailing-player rate. Full specification: see the design record
`docs/phase3-stage-c-attacking-candidate-v2-design.md`.

## 3. Overall results

| model | mean log score (↓) | RPS (↓) | Brier P(≥1) (↓) | PIT-80 abs. err (≤0.05) |
| --- | :---: | :---: | :---: | :---: |
| positional_goal_rate_poisson | 0.154512 | 0.036650 | 0.032843 | 0.0044 |
| **coupled_team_share_attacking_goals_v2** | **0.153232** | **0.035671** | **0.031920** | **0.0038** |
| trailing_player_goal_rate_poisson (comparator) | 0.143547 | 0.035129 | 0.031384 | 0.0020 |
| xg_informed_trailing_player_goals_v1 (diagnostic) | 0.137813 | 0.034600 | 0.030862 | 0.0032 |

**Primary lift vs `0.143547`: −6.7472%** (candidate 0.153232; required ≥ +1.0%). V2 is worse than
both required baselines and worse than Candidate V1.

## 4. Estimator path split (the headline diagnostic)

| slice | stage_a_coupled_appeared | stage_a_coupled_cold_start | stage_a_uninformative | equal_share |
| --- | ---: | ---: | ---: | ---: |
| overall | 103,428 (77.21%) | 30,536 (22.79%) | 0 | 0 |
| 2021-22 | 14,747 (71.23%) | 5,957 (28.77%) | 0 | 0 |
| 2022-23 | 21,500 (81.12%) | 5,005 (18.88%) | 0 | 0 |
| 2023-24 | 21,456 (72.18%) | 8,269 (27.82%) | 0 | 0 |
| 2024-25 | 22,613 (82.88%) | 4,670 (17.12%) | 0 | 0 |
| 2025-26 | 23,112 (77.70%) | 6,635 (22.30%) | 0 | 0 |

Stage A was informative in every fold (the team-match window is never empty after the 8-gameweek
warmup), so the stage-A-uninformative fallback never fired and the equal-share fallback never fired.
The cold-start share path (positional-mean signal fill) accounts for 22.79% of predictions, matching
the 1,207 cold-start players shared with the baselines.

## 5. Per-season mean log score (primary, ↓)

| season | folds | Candidate V2 | `trailing…` | lift | V2 RPS | V2 Brier(≥1) |
| --- | :---: | :---: | :---: | :---: | :---: | :---: |
| 2021-22 | 30 | 0.158737 | 0.152725 | −3.9367% | 0.037404 | 0.033242 |
| 2022-23 | 37 | 0.154318 | 0.143548 | −7.5025% | 0.036226 | 0.032155 |
| 2023-24 | 38 | 0.158377 | 0.148799 | −6.4367% | 0.037184 | 0.032954 |
| 2024-25 | 38 | 0.154579 | 0.144386 | −7.0594% | 0.036363 | 0.033005 |
| 2025-26 | 38 | 0.142057 | 0.131139 | −8.3254% | 0.031820 | 0.028757 |

V2 regresses against the comparator in all five seasons on mean log score, and on RPS and Brier(≥1)
in all five. (Per the contract's xG-covered-seasons judging, the xG-signal seasons are 2023-24+; V2
regresses in those as well as in the threat-signal seasons.)

## 6. Development diagnostics vs the frozen v1.0 gate

Each row is one labelled diagnostic (`DEVELOPMENT DIAGNOSTIC ONLY`); they are **not** combined into a
verdict. **4 of 8 diagnostics pass.**

| diagnostic | result | detail |
| --- | :---: | --- |
| aggregate mean-log-score lift ≥ 1.0% | **FAIL** | lift −6.7472% (0.153232 vs `trailing…` 0.143547) |
| no aggregate RPS regression | **FAIL** | regression +1.5433% (0.035671 vs 0.035129) |
| no aggregate Brier(≥1) regression | **FAIL** | regression +1.7094% (0.031920 vs 0.031384) |
| PIT-80 abs. error ≤ 0.05 | PASS | 0.0038 |
| prediction coverage ≥ 1.0 | PASS | 1.0000 (133,964 / 133,964) |
| folds evaluated ≥ 181 | PASS | 181 |
| zero leakage failures | PASS | 0 |
| no per-season mean-log-score regression | **FAIL** | 5 of 5 seasons regress (−3.94% … −8.33%) |

**V2-vs-V1 diagnostic co-score (NOT a gate):** V2 0.153232 vs V1 0.137813 → **mean-log-score lift
−11.1887%**. V2 is worse than V1 on RPS (0.035671 vs 0.034600) and Brier (0.031920 vs 0.030862) too.

## 7. Verdict

**DEVELOPMENT-ONLY — NOT PROMOTED.** Candidate V2 is not promoted and is judged by no promotion
gate. Two independent reasons:

1. **Proxy caveat (governs regardless of the number).** The historical target roster
   (`target_roster.historical_roster_status = archive_proxy_unversioned_at_real_deadline`) and
   first-kickoff cutoff (`cutoff.prediction_time = archive_first_kickoff_proxy_for_gameweek_deadline`)
   are unversioned archive proxies, so real-deadline knowledge-time validity is unproven; availability
   is excluded; the historical number is a development number, **not an upper bound**. The Stage A
   coupling adds no new leakage surface (it uses only `kickoff_time < as_of` team-match history and
   the existing target-roster proxy) but depends on the same proxy.
2. **The number itself.** Even setting the proxy caveat aside, V2 fails every scored gate diagnostic:
   it is worse than the best baseline on mean log score, RPS, and Brier(≥1), regresses in all five
   seasons, and is 11.19% worse than Candidate V1. The structural hypothesis is **refuted** on this
   archive.

The best required Stage C attacking baseline (`trailing_player_goal_rate_poisson`) remains the Stage C
attacking model until a separately pre-registered candidate clears the unchanged promotion gate
against prospective data.

## 8. What the result tells us (diagnostic only)

Allocating the Stage A team-goal expectation among players by a trailing attacking share
**underperforms** predicting each player independently from their own trailing history. V2's overall
mean log score (0.153232) sits next to the *positional* baseline (0.154512), not the trailing
baseline (0.143547) or V1 (0.137813) — the share allocation plus the 22.79% cold-start positional-mean
fills pull predictions toward positional-average behaviour and lose the per-player trailing signal
that the trailing baseline and V1 exploit. Conservation (rates summing to `lambda_team`) is
structurally correct but does not help scoring: it anchors the team total while flattening the
between-player differences that drive goal-scoring accuracy. A share-based successor would need to
preserve per-player rate resolution (e.g. a residual individual finishing term on top of the share)
rather than allocate the team mean wholesale. V2 is left as committed and is **not retuned**.
