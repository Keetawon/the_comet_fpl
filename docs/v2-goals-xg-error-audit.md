# Goals+xG control: diagnostic audit of the existing real-SOT result

Date: 2026-09-05. Status: descriptive, post-evaluation diagnosis; no new model fitted or scored.

This audit reads `results/v2_real_sot_development.json` and checks the recorded observations
against the existing archive using a read-only connection. The source result remains frozen at
SHA-256 `32a3332dd92e30b160a632d6ad68ee268cbfd3367a27340e365583c2e9ca7e7d`, produced from clean
commit `9fafb12e0d03250660206a7bbcfece20569eae3f`. All eight recorded source fingerprints still
match. The audited branch HEAD is `58f7b4e01a403aa806d25141f931fec42be842b4`.

The subject is `retrospective_goals_xg_control_v1`, compared on identical observations with
`trailing_goals_attack_defence`. There are 2,280 team-fixture predictions, 1,140 matches, and
114 observed-gameweek folds across 2023-24, 2024-25, and 2025-26. These already-inspected seasons
remain development evidence. The existing SOT verdict remains inconclusive.

## 1. The clearest relative weakness is early season

Positive lift below means lower log loss for the goals+xG control than the trailing-goals baseline.
Bias is predicted minus observed goals per team-fixture.

| Scope | Rows | Control log loss | Baseline log loss | Control lift | Bias | Control PIT-80 |
|---|---:|---:|---:|---:|---:|---:|
| Overall | 2,280 | 1.489436 | 1.496896 | +0.4984% | -0.00423 | 80.83% |
| GW1-6 | 358 | 1.442178 | 1.435401 | -0.4721% | +0.05656 | 84.36% |
| Later gameweeks | 1,922 | 1.498239 | 1.508350 | +0.6704% | -0.01555 | 79.86% |
| Home | 1,140 | 1.534440 | 1.538589 | +0.2696% | +0.02194 | 82.46% |
| Away | 1,140 | 1.444432 | 1.455203 | +0.7402% | -0.03039 | 81.67% |
| Promoted club | 342 | 1.286007 | 1.287677 | +0.1297% | +0.01741 | 83.63% |
| Established club | 1,938 | 1.525335 | 1.533817 | +0.5530% | -0.00804 | 80.75% |

Early season is 15.7% of the population. It contributes 2.4260 additional summed log-loss units
relative to the baseline, while later gameweeks save 19.4346 units. Its mean predicted goals
are 1.47556 against 1.41899 observed, a 3.99% overprediction. This localizes a weakness relative
to the comparator; it does not establish its cause or the size of an achievable improvement.

Raw loss cannot be ranked across unrelated slices as if higher loss always meant a worse model:
their outcome distributions differ. The relevant comparisons above use identical rows in each
slice. Promoted clubs have weak within-gameweek rank correlation (0.1122), but the report has no
uncertainty for that slice and it is a smaller, restricted population. Cold-start coverage is
only 24 rows; its 91.67% PIT-80 is too thin to drive a model change by itself.

## 2. Overall mean bias hides season-level differences

Observed means below are recovered as `predicted_rate_mean - mean_error` and independently agree
with the archive's goal totals. Each season contains 760 team-sides and 380 matches.

| Season | Mean predicted goals | Mean observed goals | Relative mean bias | Control lift vs baseline |
|---|---:|---:|---:|---:|
| 2023-24 | 1.51410 | 1.63947 | -7.65% | +0.4409% |
| 2024-25 | 1.51325 | 1.46711 | +3.15% | +0.9114% |
| 2025-26 | 1.44156 | 1.37500 | +4.84% | +0.1329% |

The mean error across all seasons is nearly zero because seasonal errors cancel. The control
still beats the baseline on log loss in every eligible season. These observations do not justify
a global rate correction: `docs/phase4-stage-a-recency-audit.md` already tested seasonal league-
level rescaling and found no useful improvement. That closed experiment is not reopened here.

## 3. A concrete selection-procedure hypothesis

`MultiSignalTeamEngine._inner_split` selects the latest six observed gameweeks within the outer
training window. `_select_decay_and_prior` and `_select_weights` fit on history before that block,
then score every holdout fixture using the same fitted ratings. The outer runner instead refits
the model before every target gameweek. The inner and outer update schedules therefore differ.

Read-only inspection of actual fold histories confirmed, in each of the three seasons:

- GW1 selection uses the previous season's GW33-38;
- GW6 selection still includes the previous season's GW38 plus the current season's GW1-5.

The selected control xG weight changes on 62 of 111 adjacent within-season transitions (55.9%).
Changes by season are 24/37, 16/37, and 22/37. This is evidence of variable selection; changing
weights can also be a legitimate response to new information, so it does not prove overfitting.

**The bounded hypothesis to preregister next is whether matching inner selection to weekly
refitting improves the unchanged goals+xG model.** A separately named candidate would select the
existing half-life, prior, and blend settings by walking through the inner holdout gameweeks,
refitting each signal and its scale on earlier matches before predicting each complete batch.
It would retain the feature set, grids, goal distribution, population, and outer protocol. The
same-population existing control remains the main comparator. No candidate is implemented or
preregistered by this audit.

This is a hypothesis generated from inspected development results, not a confirmed explanation
of the early-season regression. It changes the selection procedure rather than declaring a new
seasonal mean correction. Prior dynamic Stage A candidates remain separate frozen evidence;
their results cannot establish the benefit of this procedural change in the V2 goals+xG engine.

## 4. Limits of the retained artifact

The result retains aggregate slices and per-fold fitted settings, but no per-fixture predicted
distributions and no per-fold loss totals. Consequently this audit cannot:

- identify the individual clubs or matches responsible for errors;
- separate failures to score from failures to predict goals conceded for a particular club;
- measure zero-goal or high-score-tail reliability from the exact stored probabilities;
- establish whether the early-season regression repeats independently in every season;
- attach paired uncertainty to the control-vs-baseline slice differences.

Those claims would require the original prediction rows. The frozen run was not rerun to recreate
them. Any new evaluation should retain fixture-level probabilities and outcomes for later error
analysis, subject to its own preregistered output and provenance contract.

PIT draws restart from the fixed seed separately for each reported slice. Thus slice PIT-80
counts are not additive into the overall PIT-80 count; the stored within-slice comparisons remain
the correct descriptive evidence. No tail-shape conclusion is inferred from PIT-80 alone.

## 5. Missing-data follow-up: team-average imputation

A subsequent read-only check examined the owner's suggestion to fill gaps with team averages.
In the three eligible seasons, archive xG has 0 missing values out of 2,280 team-fixture rows;
canonical SDP SOT is missing on 42/2,280 rows (1.8421%). The gaps are 6, 20, and 16 rows in
2023-24, 2024-25, and 2025-26 respectively.

Missing SOT is associated with low scoring: 41 of those team-sides scored zero goals and one
scored one. None of the 2,238 non-null SDP SOT values is an explicit zero. Joining to the
opponent's existing FPL-derived `shots_on_target_allowed_proxy` gives 38 zeros and four ones.
The four nonzero-proxy cases are `(season, fixture, team_code)`:

- `(2024-25, 124, 4)`, one recorded goal;
- `(2024-25, 190, 21)`, zero goals;
- `(2024-25, 242, 8)`, zero goals;
- `(2024-25, 269, 4)`, zero goals.

This is evidence consistent with provider omission of zeros, not proof that every missing SOT
is zero. The goalkeeper proxy has its own semantics and is not substituted for provider SOT.
The exception cases still require source investigation. Team-average substitution could inflate
low-SOT matches and change both attacking and opponent-defensive estimates.

Before the model-selection hypothesis above is implemented, verify the provider's missing-value
semantics for these gaps. If an imputation experiment is later justified, compute estimates from
prior available matches only, preserve NULL in the raw/observed fields, label estimated inputs,
and keep measured coverage distinct from imputed coverage. Treating an estimated count as an
independent observed match would also overstate the available information. Neither existing
observations nor the frozen SOT result were altered by this check.

## Verification and handoff

The analysis used stored metrics, ordinary arithmetic, source inspection, and read-only archive
queries. Archive counts and goal totals match all three recorded season observation means. The
formal result hash and all model-source fingerprints match their frozen values. No model
training, formal evaluation, tuning, code/config edit, or model promotion occurred. No regression
tests were required for this documentation-only audit.

Subsequent owner-authorized follow-up is separate: see
`docs/v2-corroborated-zero-sot-design.md` and `results/pl_sdp_sot_zero_audit.json` for the completed
missing-value investigation and new preregistration. The diagnostic statements above describe
the earlier read-only audit, not a rerun or reinterpretation of its frozen source result.
