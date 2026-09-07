# Football program: incumbent and prerequisite audit

Status: read-only groundwork, not preregistration, a model evaluation, a readiness claim,
or promotion. Frozen Stage B/C/GK/DC and composition evidence remains unchanged.

## Reproducible inventory

```powershell
& 'D:\Personal\fpl-operations\.venv\Scripts\python.exe' -m fpl.jobs.audit_football_program `
  --db 'D:\Personal\workspace\the_comet_fpl\.worktrees\sdp_test\data\fpl.duckdb' `
  --output 'D:\Personal\fpl-operations\verification\NEW-RUN\football-program-audit.json'
```

Both paths must be explicit. The database must already exist without a WAL. The job opens
a DuckDB read lease, hashes the database before/after its queries, checks repository evidence
did not change, and exclusively creates a new report. It never initializes/checkpoints a
database, stages data, contacts a provider, fits models, or changes defaults. Missing tables
are unavailable, not zero coverage. Raw lineup/event version counts are not validated player
minutes or identity coverage. An interrupted report write may leave a partial file; preserve it
and choose a new output path, rather than overwriting an audit.

The report hashes and fully parses all discovered Stage B/C retained JSON, Stage D/BPS results,
the GK evidence inside `results/v2_team_environment_development.json`, and
`results/v2_dc_development.json`. It retains their metric/provenance blocks, not duplicate
fixture PMF arrays. Missing required artifacts are explicitly listed. Source/config fingerprints
identify the actual current comparator; neither old result numbers nor this narrative substitutes
for validating a new historical adapter against those sources.

## Current incumbent is a composed path

`jobs/prospective_points_v1.predict_prospective_points` defaults to `attacking=v3`,
`appearance=seasonal`, `share_signal=auto`, `assists=coupled`:

- Minutes starts with fitted concentration-adaptive V3. With at least three eligible rows,
  seasonal mode uses equal-weight trailing-five with alpha **3.5**, position/pooled priors
  (500-row minimum), and a distinct all-zero-history profile. A ten-row prior appearance rate
  receives weight .7 in August/September, .5 in October/November, otherwise zero. Cold starts
  have the existing price/incumbent overlay; stale former-club history is excluded by the
  prospective trailing-eligibility rule.
- Goals and assists use the composer's own predicted appearance probability and normalize
  trailing appeared xG/xA shares to team goals / assisted goals. The team model is
  `trailing_goals_attack_defence`; assists scale by fold-local sum(assists)/sum(goals), fallback
  .90. The .75 default in `component_engine_v2` is not this route.
- Allocation rates are unconditional. The composer receives conditional-on-appearance rates
  through `conditional_rate`, with the existing team-rate cap. Conservation is an expectation
  property with explicit caps/fallbacks, not a claim of shared realized team totals per draw.
- GK saves V1, DC threshold-hit V1 and joint BPS bonus remain installed. Full points uses
  2,000 fixture-seeded draws, seed 202627, support 0..34, and conceded exposure
  `(0,.344,.813,1)`. Availability is a separate overlay. Cards, own goals and penalties are
  not drawn in the incumbent.

The old EV adapter is useful scaffolding but does not implement all current seasonal,
current-club and newcomer rules. Its immutable 2026-08-07 result belongs to commit `8af5760`,
before double-gating, conceded-exposure and shrinkage repairs. Reproducing that number is not
reproducing today's incumbent. A separately tested retrospective adapter is required.

Inherited-constant caveat: alpha3.5 was selected on 2021-22..2024-25; price coefficients were
fit on 2023-24/2024-25; the behind-incumbent cap used evidence including 2025-26. Applying
these unchanged constants to earlier folds is a retrospective current-incumbent benchmark,
not proof those learned constants were historically out-of-sample. Do not silently refit them
and still call the comparator exact.

The local research DB has **51 snapshot captures, all in 2026-27**, from
2026-07-27T09:48:30Z through2026-09-04T11:05:54Z. There is no retained historical deadline
bootstrap/registry for 2021-22 through2025-26. Archive fixture `value` is measured but unversioned;
it is not proof of deadline `now_cost`. The current cold-start selector also needs the complete
cutoff registry's same-club/same-position established-player prices. An unknown historical price
cannot silently become a known API NULL, launch price or final-season price. Therefore the
requested exact live-input historical D/J comparator is blocked on price-dependent cold starts.
Price-independent established-player mathematics can be reproduced under the already explicit
archive identity proxy, but that subset is not the full requested population. Do not claim a
complete current-default PMF replay or introduce a new price proxy without an explicit contract.

## Cards: predictions are not observed scoring

The archived FPL target is the recorded joint yellow/red pair, not a reconstructed event
sequence. The initial local audit observed only `(0,0)`, `(1,0)`, `(0,1)` over 138,707 rows,
with no missing card counts. That does not independently prove double-yellow event semantics.
The command remeasures joint states (including nulls and raw blank strings) every time.

There are ten archived zero-minute card rows, including Ashley Barnes, 2025-26 GW22,
fixture215, stable code44699: minutes0, yellow1, red0, recorded/replayed points -1.
`tests/test_scoring.py::test_ashley_barnes_gw22_regression` pins this evidence.

An on-pitch-only *generative model* may enforce zero simulated card points for a simulated
nonappearance without changing actual scoring. Marginalize with predicted appearance, not
target minutes; retain all actual bench cards and disclose the dependency approximation.
Never add an observed `minutes > 0` card-scoring gate or silently remove these targets.
Keep the existing BPS residual contract: it already absorbs omitted card BPS effects.

## Required decisions before development evaluations

D needs an exact-incumbent minutes adapter, OOS role/workload predictions and a new contract.
The old four-bin gate includes 1% log lift, best-baseline-per-metric RPS/Brier nonregression,
starter-ranking nonregression, PIT error <=.05, complete coverage, zero leakage and 181 folds.
A different coverage-limited population must be explicit in an additive contract.

E needs separate goals/assists identities, conditionality and team-total conservation tests,
and role/minutes marginalization without in-sample stacking. F needs joint recorded-card
semantics and its own proper-score contract. I mechanically selects retained passed successors
or the incumbent and must reproduce old PMFs/RNG exactly with cards disabled.

J must use complete replayed targets and the exact current incumbent on identical rows.
Only 2025-26 has complete historical 2026/27-rule targets in the inspected archive: earlier
seasons lack player DC even though partial replay totals exist. Proper-score targets retain
the incumbent's folding `min(max(actual,0),34)`; raw bias/MAE/ranking retain negative actuals.
DGW PMFs convolve without truncation. All learned upstream predictions used for downstream
fitting must be sequentially out-of-sample. Capture counts and passed unit tests alone do not
establish any of these scientific prerequisites.
