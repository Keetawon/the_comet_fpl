# Attacking Role Premium V1 preregistration, 2026-09-08

This is a bounded development-only **conditional attacking-usage persistence** experiment.
The owner authorizes exactly one control and one candidate on the frozen 2023/24 class-B
archived-snapshot population. It is not an exact-role classifier, unconditional player EV
model, FPL-points model, production promotion, or a new historical availability claim.
The earlier feasibility verdict D and historical source verdict B remain unchanged.

Starting SHA: `4fd1c5fdf271aef329d196a22236f8f9310254d7`.
Branch: `claude/comet-fpl-v2-architecture-mqrj8f`; initially clean and synchronized,
59 commits ahead / one behind remote main. No historical data is fetched in this task.
The clean commit containing this document, config, tested implementation and population
receipt is the preregistration identity. No real candidate predictions or scoring precede it.

## Frozen evidence and population

Use `results/historical_player_attacking_backfill_manifest_2026-09-08.json` and the exact
`results/historical_player_attacking_backfill_independent_audit_2026-09-08.json` population.
Their SHA256 values are `56da2a8c52f96c2d7d4b68586d86d9eeee3fc4011ae17235ddcf940b58dcf03c`
and `146a7209c412e20fbebb63c3c8377097d95b1cd711baf5cf465cb78da4edb409` respectively.
The 26,312-row observation file SHA256 is
`0d699021537dc7e636f0dfb8e4484f98fc57263663806631c5c8e075b0c5cefc`.

Evidence remains **ARCHIVED_AS_OF / class B**. Source, capture and availability timestamps
are retained unchanged. Cutoffs are the already audited archived-snapshot instants; exact
historical FPL deadlines and independently attested original public GitHub push times remain
unproven. No kickoff-minus-duration or event-end deadline is invented.

The frozen target population is 36 GWs / 24,947 player-fixture targets / 763 players:
DEF 9,106; MID 12,185; FWD 3,656. GW17's 607 rows, 165 absent cutoff-registry rows and eleven
cutoff-club mismatches remain excluded. GW1 supplies history only. The excluded target GW17
can supply historical observations to later GWs once those observations are source-available;
target exclusion is not deletion of legitimate later historical evidence.

Before registration, the independent raw/source audit was replayed without scoring and
reproduced every coverage count. A new typed loader also independently reconstructs the exact
cutoff registry, historical position, fixture-side clubs, future schedule and target identities.
A population receipt freezes target identity/cutoff hashes separately from target statistics.
The target identity fingerprint is
`f2467d7fc5a66df79c6d2d8c33b7adcca0085143d2ba0c2884bfce07624743ec`;
coverage-only reconstruction finds 7,403 paired-measured target rows with minutes >=45.
The eligible population consists of retained observed target labels; it is not a claim that
THE COMET forecast a complete live roster historically.

## Inputs and isolation

Feature input is a typed observation containing only season/GW/fixture/player identity,
historical FPL position, prior minutes/starts/xG/xA and source availability/provenance. Target
input contains only source-known schedule and identity, including historical position, club,
opponent and venue. Actual target statistics are held in a separate outcome interface.

For a cutoff, history must be in 2023/24, have kickoff strictly before cutoff, and have both
source-known and available times no later than cutoff. Only class B is admitted. Every target-GW
leg and target fixture is excluded. Revisions select the earliest eligible complete source row;
later corrections do not fill earlier NULLs. Current target performance can enter history only
for later eligible cutoffs. No previous-season data is added.

No goals, assists, points, ICT, price, ownership, formation, SDP tactical features, team totals,
FixtureEnvironment or expected minutes enter either predictor or peer distribution. Team,
opponent and venue are identity/descriptive selectors only; neither predictor adjusts for them.
The development-only typed capability reuses timestamp validation but does not modify or grant
retrospective access through the production FeatureSource API.

## One exact control and candidate

For each position, the prior xG/90 and xA/90 are the exposure-weighted rates across positive-minute,
paired-measured eligible historical rows in that position. The player's own eligible history is
included in the pooled prior. No training exposure for a position fails closed; it is not zero.

For player exposure M minutes and observed xG or xA total X, with positional rate p per 90:

`shrunk_rate = (90 * X + 450 * p) / (M + 450)`.

Zero player exposure returns p exactly. This is the same 450-minute prior strength for every
position and both arms, with no parameter fitting or search.

- **Control:** all eligible prior player exposure within this season.
- **Candidate:** newest 360 prior player-minutes, ordered by kickoff then fixture ID descending.

If the oldest included match crosses the 360-minute boundary, its aggregate xG/xA is multiplied
by included minutes divided by that match's observed minutes. This is proportional aggregate
weighting, not reconstruction of exact within-match opportunity timing. For less than 360
observed minutes, both use all available history and the same prior; no history is discarded.

All witnessed positive minutes consume the recent window, including rows with unavailable
opportunity. Only paired-measured portions contribute numerator and effective shrinkage exposure;
missing fields are never zeros and cannot cause the window to reach farther backward. Unknown
minutes encountered before filling the recent window fail closed. Valid zero-minute DNPs
contribute no exposure or opportunity and are distinct from missing-field rows.
`historical_minutes` and `recent_window_minutes` report paired-measured rate exposure, not total
workload. All acquired real rows have paired xG/xA, so this distinction does not change this
frozen population. Starts/appearance counts remain separate and preserve unknown values.

The candidate's maximum player weight is 360/(360+450). The control can accumulate more player
weight as the season progresses. Thus this is the specified recent-window-plus-shrinkage
mechanism; it does not separately identify recency versus its induced stronger shrinkage.
No alternate concentration, half-life, window, position-specific prior or sensitivity run is made.

## Descriptive attacking premium

For each cutoff, construct one candidate rate state per historically observed same-position
player with positive eligible paired exposure. This peer set is history-derived, not the future
outcome roster. Include the player itself when eligible; a cold target is ranked against these
already observed peers. Contradictory within-season registered positions fail closed.

For each candidate rate, use the midrank empirical CDF:
`percentile = (number_less + 0.5 * number_equal) / number_of_peers`.

`AttackingRolePremiumV1 = 0.5 * xG_percentile + 0.5 * xA_percentile`.

Retain both percentiles and candidate-minus-control xG90/xA90/xGI90 shifts. xGI is always
computed from xG+xA, not supplied as an independent feature. Genuine zeros and percentile ties
are preserved. The composite is bounded by [0,1], but averaging percentiles does not make its
own distribution uniform. Composite thresholds .90/.975 are score thresholds, not a claim that
exactly 10%/2.5% of players occupy them. No binary OOP flag or tactical position is produced.
Aggregate xG/xA cannot distinguish open-play advanced usage from set-piece threat.
The primary experiment compares rate predictions; it does not identify incremental predictive
value from the percentile transformation independently of those rates.

## Walk-forward and targets

Iterate the exact observed audited folds, not an assumed contiguous gameweek range. Build
priors, control, candidate and peer percentiles from the eligible history for the cutoff.
Predict every audited target in the whole GW and publish its immutable prediction bytes before
reading the batch's target xG, xA, minutes or starts for scoring. DGW legs cannot update one
another. Combined prediction and scored-label artifacts remain separate.

For a meaningful target appearance, observed rates are `90*xG/minutes`, `90*xA/minutes` and
`90*(xG+xA)/minutes`. The **primary evaluation slice is target minutes >=45**. Target minutes
choose this retrospective scoring slice only; they never enter prediction or premium.
All strictly positive minutes and 1-44 minute appearances are descriptive secondary slices.
Zero-minute rows still receive predictions, but their per-90 target is unavailable rather than
zero. This result is conditional persistence, not a full appearance/EV forecast.

## Metrics, uncertainty and decision rule

Primary metric: pooled player-fixture xGI90 MAE, equal weight per qualifying target row.
Relative lift is `(control_MAE - candidate_MAE) / control_MAE`.
Secondary metrics are xG90/xA90 MAE, mean signed error (prediction minus observation), mean
prediction/observation, pooled Spearman and within-position/GW Spearman with average tied ranks.
Undefined correlations, empty slices and zero-control relative lifts remain NULL.

Conditional ranking diagnostics take ceil(0.1*N) rows in each scored position/GW, ordered by
predicted xGI90 descending then player code and fixture ID. Report their pooled future xGI90
mean and lift over the pooled conditional population. These are retrospective conditional
rank diagnostics, not a pre-match appearance shortlist.

Use 10,000 paired whole-GW bootstrap draws, seed 20260908, sampling the scored GW clusters
with replacement and retaining original player-row weighting within each draw. Report 2.5%
and 97.5% linearly interpolated quantiles for absolute and relative MAE improvement. This
one-season GW-cluster interval does not eliminate serial dependence from repeated players or
overlapping training histories. A relative draw with zero comparator loss is undefined; all
draws must be defined to support the candidate.

SUPPORTED requires every owner gate plus the preregistered uncertainty interpretation:

1. pooled xGI90 MAE relative improvement >=1%;
2. pooled xG90 and xA90 MAE relative regression each <=0.5%;
3. DEF xGI90 MAE direction non-negative;
4. no position with >=100 primary rows regresses xGI90 MAE by more than 5%;
5. pooled and each such position's absolute mean signed xGI90 error increases by <=0.05;
6. causal/PIT and integrity checks pass, all required positional guardrails have sufficient rows;
7. the bootstrap lower bound of relative lift is >0 and every relative draw is defined.

The 5% positional and 0.05 absolute-bias limits operationalize the owner's qualitative
catastrophe/calibration guardrail before any result is seen. They are not fitted thresholds.
Materiality is required even for a statistically positive result. A primary relative loss
of at least 1% with the bootstrap upper bound below zero is REFUTED. Every other failure to
satisfy the support gate is INCONCLUSIVE; a validity failure is INVALID. No attractive example
can change the decision.

## Frozen post-result diagnostics

Only after the generic formal result is written, report positional, GW, venue and exposure
slices; history buckets 0, 1-89, 90-269, 270-449, 450-899 and 900+ paired minutes; no prior
appearance, one prior meaningful (>=45-minute) appearance, established (>=2 meaningful), and
short-only/unknown-history groups. Fixed season thirds are GW1-13, 14-26 and 27-38; the first
contains only target GW2-13 in this population.

Positive usage shift requires candidate xGI90 >=1.25*control, absolute difference >=0.05 and
recent exposure >=180 minutes. On the primary slice, persistence means target xGI90 >=1.25*control
and target-minus-control >=0.05; mean reversion is target-minus-candidate xGI90. Report shift
counts, future usage, candidate/control errors and position counts against descriptive non-shift
rows. This is not a matched causal effect or a model selection criterion.

For DEF premium >=.90 and >=.975, retain every case and report exposure, candidate xG90/xA90,
shift, future outcome and errors where target exposure permits. Select top-five, closest-to-.5
five and lowest-five DEF score cases over all predictions, with GW/code/fixture tie order,
without consulting outcomes. Report absent/low-minute outcome labels as unavailable rate cases.
Only then look for O'Reilly, Hume and De Cuyper in the retained 2023/24 registry using exact source
name lookup and stable-code identity. If absent, say NOT IN AUDITED POPULATION. No new source
or season is fetched to create examples. No formation or FixtureEnvironment increment is tested.

## Execution, immutability and checks

The config, design, tested sources and population hashes must be committed clean before the
single formal run claim. Reuse the shared Git-common-directory exclusive evaluation claim and
write-once artifact publication. Pin prior frozen artifacts, raw observations and receipts,
implementation dependencies, runtime identity, Git HEAD and configuration before and after
execution. A failed execution retains its claim and invalid identity; it is never silently
resumed or overwritten.

An explicit offline verification replay uses identical frozen inputs and the original formal
provenance/claim, writes to a new directory, and must reproduce formal result and prediction bytes.
It is verification of the same registered run, not another model-selection opportunity. An
independent arithmetic/PIT audit checks stored values without fitting or choosing a new candidate.

Focused synthetic checks cover event/knowledge availability, target and DGW exclusion, historical
position, missing versus zero, fractional recent-window bounds, exact shrinkage and midrank premium,
cold starts, historical peer/positional priors, forbidden inputs, future truncation and replay.
Population and runner checks cover frozen hashes/exclusions, label separation, clean claims and
publish-before-score order. Run relevant broader tests, Ruff, strict mypy and changed-file format.
Inherited Windows symlink/global-format failures are reported separately, not repeatedly retried.

No existing model, production capture, SDP architecture, fixture environment, optimizer, frozen
result, main or default branch is changed. No PR or history rewrite is authorized. Only additive
V2 work is committed and pushed. The final result determines exactly one next task under the
owner's A/B/C/D mapping; that next task is not implemented in this session.
