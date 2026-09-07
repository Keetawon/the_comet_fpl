# Broad starting-role V1: final pre-score registration

Candidate `retrospective_broad_starting_role_transition_v1`; retrospective competitive
development only. This separately finalizes the unchanged fixed algorithm in
`docs/player-role-history-v1-design.md` and `config/player_role_history_v1.yaml`.
It does not authorize production use, infer target starting lineups, change any minutes
model or relax Stage B/C gates. No formal role scoring preceded this registration.

## Population chosen from coverage only

Frozen source DB:
`D:/Personal/fpl-operations/development/competitive-workload-v3-20260907T094600Z.duckdb`,
SHA256 `a8584ce79f421e0bd43057f3a8f63bac03e30b59cc1c2407b8a7c28387a35021`.
The source audit records all 574 competitive bundles and 19,320 valid mapped roster-history
observations. Exactly **8,162 of 8,360 FPL-recorded PL starters (97.6316%)** have usable
independently interpreted broad-role labels, exceeding the predeclared 95% threshold.
The 198 excluded starters and their source failures remain explicit.

Forecast every one of the **29,747 archive roster rows**, including DNPs, in 380 fixtures
and 38 complete gameweek batches for 2025-26. Score only the same 8,162 measured starter
labels in all four arms. No early-gameweek exclusion or warmup deletion is introduced.
The immutable minutes reference supplies only target identity/schedule and separate price
lineage, not its fitted minutes or prices as role predictors. Its underlying archive hash
`0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8` is distinct from the V3 DB.
The 270 direct price-proxy rows in this season are retained diagnostically; role probabilities
do not consult archive price. The complete downstream minutes reference still has 821 proxy
rows across three seasons and cannot be relabelled as deadline-known registry evidence.

Coverage is pinned by `results/player_role_coverage_v1.json`, SHA256
`48c01dac3d94f4dfb3dc3c66d6fd2c954ca21d50b9338420143215caa500aed1`.
The initial 535-bundle coverage report is preserved separately. Its pre-score scaffold used
a PL-only finality helper; the new runner uses the independently audited competitive
FullTime/NormalResult/AfterExtraTime/Aggregate/PenaltyShootout boundary, nonnegative scores
and kickoff before original capture. No parser, role algorithm, target label or previous
audit was rewritten. This correction added 39 completed source bundles, not scored targets.
`results/player_role_coverage_finality_amendment_audit.json` retains the before/after checks.

## Fixed hypothesis, algorithms and temporal boundaries

Forecast **P(GK, DEF, MID, FWD | hypothetical start)** from raw licensed starting labels.
This is neither P(start) nor a substitute's observed role. Formation membership confirms
historical labels only; target XI, actual target role, FPL position and target minutes do
not enter predictors. Foreign/unresolved identities and unsupported role labels remain NULL.

Use up to five recent measured starts within the latest witnessed stable-club spell,
newest-first weights `[1,.707,.5,.354,.25]`, normalized over measured starts. The prior is
the fold-global earlier-role frequency, uniform only without observations. Pool the
four-by-four transition table with strength 2; with `alpha=n/(n+2)`, predict
`alpha*(recent @ transition)+(1-alpha)*prior`. No fitted grid, random split or stochastic
seed is used. Fixed category order GK/DEF/MID/FWD resolves equal-probability labels.

Comparators: fold-global prior and `(last-role onehot+2*prior)/3`. A required matched
recent-state persistence diagnostic uses the **same** EWMA and shrinkage without the
transition matrix. A win over the weaker last-role baseline alone cannot establish
transition value. Weak dimensions may not be removed after scoring.

Every source must precede the complete target-GW first-kickoff proxy, exclude every target
GW PL fixture, and pass the six-hour completion exclusion when a verified whistle is absent.
Known later events/end timestamps reject the source. Postponed/DGW legs are handled by actual
event time and a common pre-GW state, never sequential target updates. Historical capture and
interpretation times remain later-known and unmodified. Whole source versions are chosen by
earliest complete **final original capture**, then fixed version/hash ties, not by model scores.

## Frozen score, gate and output

Primary: categorical mean NLL, floor 1e-12. Require at least 1% relative lift over the better
of the two fixed baselines, no four-state Brier regression against its best baseline, maximum
full-season absolute class marginal bias .05, and zero temporal violations. Retain class,
venue, GW1-6/GW7+, cold/measured-history, price/non-price slices, calibration, accuracy,
paired loss and GW-clustered uncertainty. There is only one season: cross-season robustness
cannot be claimed. The matched persistence comparison governs mechanism attribution and
is diagnostic, not a post-result opportunity to alter the gate.

`config/player_role_history_evaluation.yaml` pins this exact policy, algorithm/config,
database, staging, coverage and minutes-manifest hashes. Config SHA256:
`03ef03ab8d9724f9239c4517fa193d81cfb4179c975f7ad7506f14d4cb0827f3`.
Estimate: 38 deterministic count/transition fits over at most 19,320 historical rows and
29,747 forecast rows, no nested search; a few minutes including full provenance and JSON I/O.

Before fitting, reproduce the complete roster, label coverage and every source hash, require
clean V2 HEAD and reserve one exclusive candidate claim in Git's shared common directory.
No alternate output/worktree can consume a second run. Store all 29,747 typed OOS predictions,
four-arm probabilities, original source/version/knowledge evidence and later-known counts,
plus all 8,162 labels and metrics. An upstream forecast used by downstream minutes/opportunity
models must come from that historical fixture's own immutable pre-GW prediction, never a
role model fitted on its target. Failure is retained; no retuning or silent numerical retry.
