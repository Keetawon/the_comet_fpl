# Repository agent instructions

These instructions apply to the entire repository and to every agent or sub-agent working in
it. More specific `AGENTS.md` files may add local guidance, but they must not weaken the data
correctness rules below.

## Mission and current state

This project predicts a full Fantasy Premier League (FPL) points distribution per player and
gameweek. It is a Python 3.12 data and modelling codebase built around DuckDB, Polars, Pydantic,
HTTPX, YAML configuration, pytest, Ruff, and strict mypy.

### Active delivery objective (2026-08-26)

The 2026/27 GW1 deadline has passed. `DEV-ROADMAP.md` remains the canonical execution order and the
dated P0 record remains immutable; do not infer that the owner completed the official-FPL submission
steps unless their evidence is present. The post-deadline dashboard program was implemented
development-only in this order:

1. freeze the instruction, roadmap, semantic, read-model, monitoring, and AI-summary contracts;
2. add player and team deep-analytics pages over already-published forecast values;
3. repair player forecast-versus-actual finality and add the parallel team comparison path through
   append-only outcomes and exact stored distributions;
4. add deterministic insight summaries to every route and an optional, evidence-bound language
   renderer for public analytical pages.

All eleven routes now have an immediate deterministic summary. Only Summary, Fixture matrix,
Players, Player analytics, Team analytics, Player prediction vs actual, and Team prediction vs
actual may invoke the optional renderer, and only after explicit user action. Next GW suggestion,
Optimizer audit, Plan Builder, and Squad Draft remain local deterministic-only. Hosted static
builds never call an insight provider. Provider keys are server-process secrets and must never enter
`VITE_*`, static JSON, URLs, browser storage, logs, cache records, or Git. The browser sends only
typed public selectors; Python verifies the static generation, constructs the facts, and renders
canonical text from provider-selected fact ids. Failure always leaves deterministic facts usable.
Players is renderer-eligible only in its public scope: activating its local private **My squad**
Manager ID filter keeps deterministic visible-row facts but disables the optional renderer. Manager
ID, capture identity, entry metadata, and squad membership never enter an insight request, URL,
static read model, cache identity, or provider call.
The implemented Z.AI adapter targets the general Open Platform API; never assume a GLM
Coding Plan quota licenses general dashboard traffic without a separate provider agreement.

The new pages do not authorize model research, retuning, or reinterpretation of frozen evaluations.
Deep analytics ranks future published player/club environments; forecast monitoring diagnoses past
errors. Historical residuals are never converted into future selection utility. Freeze the current
prospective defaults, do not tune individual players or reopen frozen evaluations, and preserve any
manual owner override separately with its time and reason. This file remains authoritative for
correctness, model history, and working protocol; the roadmap owns delivery sequence and acceptance
criteria.

Phase 0b's historical and live data foundation is implemented and tested. Phase 1's Stage A
harness and Candidates V1/V2 are implemented; neither cleared the fixed promotion gate. V2 was
pre-registered under contract 1.3 before its single outer evaluation and scored 1.4939 against
the 1.5003 best baseline, only a 0.4284% lift against the required 1%. Candidate V3
(`dynamic_team_goals_v3`) is a development-only structural probe pre-registered under contract
amendment 1.4; its single historical development evaluation is **INVALIDATED** (not merely
non-promoted) — review found four defects: one leakage defect (the promoted prior drew on
full-archive future seasons), two specification/fitting defects (the inner holdout scored all
six gameweeks from one frozen state; the six-match cold-start prior was prediction-only and
returning promoted clubs kept old match counts), and one provenance defect (the runner accepted
a dirty worktree). So V3's 1.4956 number and every slice/CRPS/cold-start/parameter figure are
void for comparison and are kept only as an audit record. Candidate V4
(`dynamic_team_goals_v4`, amendment 1.5) is the leakage-safe successor pre-registered before any
evaluation: it keeps V3's sequential dynamic filter and fixes all four defects with frozen
procedure pins and a fold-local promoted-prior estimator. Its single historical development
evaluation (1.4945 mean log score, +0.3888% lift over the 1.5003 baseline, short of the 1% gate,
fractionally behind V2) is development-only and not a promotion verdict; the trailing-goals
baseline remains Stage A.
Phase 2's Stage B (player minutes) prerequisites are implemented and offline-tested. Contract
version 1.0 froze the exact four baselines, distribution metrics/calibration, and player-fixture
walk-forward harness (`docs/phase2-stage-b-implementation.md`). Additive amendment 1.1
pre-registered Candidate V1 `shrunk_trailing_5_player_minutes_v1`; it changes none
of the version 1.0 population, roster, bins, baselines, metrics, gate, or calibration policy. The
baseline-only full-archive run is **complete as a baseline-only development and calibration
record** (corrected run, 2026-07-29) — 181 folds,
133,964 eligible predictions, zero exclusions, zero leakage, 27/27 runner assertions passed, and a
full independent reconciliation (four overall reports, all 20 season-baseline rows, 48 reliability
curves / 480 buckets) with zero validation failures. The position prior
`position_minutes_frequency` is lowest at mean log score 1.04916 (a future 1% aggregate lift would
need <= about 1.03867), but it leads only on mean log score: `trailing_5_player_minutes` leads on
RPS and both Brier margins, overall and in every season, so **no baseline dominates**. It is a
development number under two unversioned historical proxies (target roster, first-kickoff cutoff),
so real-deadline knowledge-time validity is unproven. See
`docs/phase2-stage-b-baseline-development.md`. Candidate V1 and its dedicated development runner
are implemented with deterministic offline tests. The runner integrates Candidate V1 with the
four unchanged baselines on identical eligible rows, records fold-local parameter selections, and
rechecks clean Git/config/model-source/database provenance before emitting a complete reconciliation
record. It has now been run **once** as a clean historical development run: Candidate V1 reaches
mean log score 0.74198 (+29.28% over the position-prior comparator) and improves on the best
baseline value of every metric **except the within-position Spearman-p60 starter ranking** (where
it regresses, 0.69090 vs 0.70851), but it is **development-only and not promoted** — the historical
target roster and first-kickoff cutoff are unversioned proxies, so real-deadline knowledge-time
validity is unproven; see `docs/phase2-stage-b-candidate-v1-development.md`. The historical number
is a development number, not an upper bound. Additive amendment 1.2 (contract v1.2) tightens the
promotion gate for **future** candidates only — each bounded guardrail (RPS, Brier-any, Brier-60+)
is measured against the best baseline value of its own metric, and a new
`maximum_spearman_p60_relative_regression: 0.0` starter-ranking gate requires a candidate to rank
who starts and plays 60+ at least as well as the best baseline; it evaluates nothing, changes no
v1.0/1.1 policy, and does not re-judge V1. Additive amendment 1.3 (contract v1.3) pre-registers
Candidate V2 `recency_weighted_trailing_player_minutes_v2` — V1 with a geometric recency weight on
the same trailing-5 window (reduces exactly to V1 at decay = 1.0), selected jointly with alpha on
the same nested walk-forward, judged by the 1.2 gate unchanged. V2 and its development runner are
implemented and offline-tested, and V2 has now been run **once** as a clean historical development
run (2026-07-30, against a pristine rebuilt archive): mean log score 0.72625, improving on every
baseline on all four bounded scored metrics and on Candidate V1 on all five, but **failing the
v1.2 starter-ranking gate** (aggregate Spearman-p60 0.70071 vs the best baseline 0.70851, −1.10%;
nine of ten diagnostics pass). It is development-only and not promoted (unversioned proxies); see
`docs/phase2-stage-b-candidate-v2-development.md`. Additive amendment 1.4 (contract v1.4)
pre-registers Candidate V3 `concentration_adaptive_shrinkage_player_minutes_v3` — V2 with a
concentration-adaptive shrinkage strength `alpha_eff = alpha*(1 - lambda*C)`, where `C` is the
normalised Herfindahl concentration of the weighted trailing history (reduces exactly to V2 at
lambda = 0). It is diagnosed from V2's by-position evidence: V2's only gate failure (starter
ranking) is almost entirely goalkeepers (V2 0.8153 vs `last_observed` 0.8650), whose
near-deterministic histories a uniform shrinkage blurs. V3 and its provenance-guarded development
runner are implemented and deterministically offline-tested, and V3 has now been run **once** as a
clean historical development run (2026-07-30, against a pristine rebuilt archive whose four
baselines reproduce V1/V2 bit-for-bit): mean log score 0.71205, the best of the five models on all
four proper scores, but it **fails the v1.2 starter-ranking gate** (Spearman-p60 0.69726 vs the
best baseline 0.70851, −1.59%; worse than V2). The hypothesis is **refuted**: goalkeeper ranking
barely moved (0.8153 → 0.8156) and λ > 0 was selected in all 175 selectable folds (modal λ = 0.75),
so concentration-adaptive shrinkage sharpens the distribution but does not recover ranking —
sharpening a concentrated distribution compresses P(60+) among nailed starters and reduces rank
resolution. It is development-only and not promoted (unversioned proxies); see
`docs/phase2-stage-b-candidate-v3-development.md`. V3 is left as committed and is not retuned.

Phase 3's Stage C (player attacking goals) attacking Candidate V1
`xg_informed_trailing_player_goals_v1` has been development-evaluated **once** as a clean
historical run (2026-07-31, contract version 1.1 / amendment 1.1): mean log score 0.137813, a
+3.99% lift over the best baseline `trailing_player_goal_rate_poisson` (0.143547), improving on
every proper distribution metric overall and in every season with zero per-season regression.
It is **development-only and not promoted**, and an audit reclassifies it as a **historical
xG-signal probe, not a production Stage C architecture**: its player goal distributions are
independent Poisson marginals with **no Stage A team-goal input, no Stage B minutes input, and
no team-goal-total allocation or conservation**, its zero-minute player-fixture history
conflates availability/minutes with attack rate, and it carries **no destination-team,
opponent, or venue context and no transfer rescaling**. So the only conclusion it supports is
narrow — **xG beats recent recorded goals as the attacking signal where xG is measured on this
archive** — and the end-to-end team-coupled Stage C architecture remains unvalidated. A
post-run code audit also found that `poisson_pmf` had carried an implicit `1e-9` model-rate
floor (now corrected: a zero rate degenerates to an exact point mass on zero goals, and any
positive rate uses its actual value); the historical record stays pinned to its original commit
SHA and is **not rerun or rejudged**. The next model work is a **separately named, separately
pre-registered team-coupled candidate composing Stage A + Stage B**, which is not pre-registered
here. See `docs/phase3-stage-c-attacking-candidate-v1-development.md` and
`docs/phase3-stage-c-design.md`.

Stage C's team-coupled successors are now pre-registered and development-evaluated (both left as
committed, not retuned). Candidate V2 (`coupled_team_share_attacking_goals_v2`, amendment 1.2)
allocates the frozen Stage A team-goal expectation among a club's players by a trailing attacking
share (Poisson thinning, `rate_i = lambda_team * share_i`) — **refuted**: worse than the baseline
and than V1 on every metric (−6.75% log). Candidate V3
(`minutes_gated_coupled_team_share_attacking_goals_v3`, amendment 1.3) gates V2's shares by the
frozen Stage B `trailing_5_player_minutes` baseline and is the **best attacking candidate** (mean
log 0.140500, +2.12% over the best baseline, passes all eight frozen gate diagnostics, improves in
every season) but stays **development-only, not promoted** (unversioned proxies plus a development
minutes proxy). See `docs/phase3-stage-c-attacking-candidate-v{2,3}-development.md`.

The Stage C exposure-weighted successors replace the per-appearance share with a shrunk
xG/xA-per-minute rate multiplied by unconditional expected minutes from the frozen
`trailing_5_player_minutes` distribution, then normalise to the same Stage A team scale. They use
xG/xA only, a fixed 90-minute position-specific prior, and conserve the team rate in expectation.
They do not change the frozen composer or the prospective default. Each has now been run **once**
as a clean historical development evaluation (2026-08-07, against a freshly rebuilt archive whose
full suite passes 1,276 tests with zero skips). Both are **development-only, not promoted**, are
left as committed, and are **not retuned or re-judged**. Both share the identical estimator path
split -- 19.44% cold start, 22.29% equal share, 58.27% exposure weighted -- because both key off
the same Stage A exposure and xG/xA coverage.

Goals Candidate V4 (`exposure_weighted_xg_team_share_attacking_goals_v4`, goals contract 1.4)
**misses its aggregate bar**: mean log score 0.14418 against the best baseline
`trailing_player_goal_rate_poisson` at 0.14355, a lift of **-0.4426%** where 1% was required, and
**-0.0149% against V3** (0.14416) -- indistinguishable, marginally behind. Two of eight development
diagnostics fail (aggregate log lift; per-season regression). It nonetheless wins **both**
guardrails against the baseline (RPS 0.03476 vs 0.03513, +1.06%; Brier>=1 0.03101 vs 0.03138,
+1.20%) and posts the best PIT-80 absolute error of the four models at 0.0009.

**The pooled goals figure measures xG's absence, not the candidate.** Per-season lift splits
exactly on coverage: 2021-22 **-11.02%**, 2022-23 -7.05%, 2023-24 +1.24%, 2024-25 +5.03%, 2025-26
**+7.14%**. 2021-22 runs 100% on the equal-share fallback because there is no xG to weight exposure
with, so the candidate degenerates and the two pre-xG seasons drag the pooled number below the bar.
This is the same regime effect already recorded for Stage A; never quote the pooled figure as the
answer. Whether the covered-season gain is real or regime-specific is not decidable from one run.

Assists Candidate V2 (`exposure_weighted_xa_team_share_assists_v2`, assists contract 1.2) **clears
the baseline bar but loses the head-to-head**: mean log score 0.14010 against
`trailing_player_assist_rate_poisson` at 0.14273, **+1.8458%**, with both guardrails improving
(RPS 0.03240 vs 0.03314, +2.26%; Brier>=1 0.02978 vs 0.03052, +2.43%) and seven of eight
diagnostics passing -- the failure is per-season regression confined to 2021-22 (-4.68%), again the
no-xA season on the equal-share fallback. But against the incumbent
`xa_informed_trailing_player_assists_v1` already in the composer, V2 is **behind on mean log score:
0.14010 vs 0.13994, -0.1104%**, while winning both guardrails against it (RPS 0.03240 vs 0.03279;
Brier 0.02978 vs 0.03018).

**The V2-vs-V1 gap is resolution bought with reliability, not a narrower distribution.** The
`P(>=1 assist)` reliability curves show V2 separating players far more aggressively than V1: it
moves 2,815 rows out of the lowest bucket and multiplies the confident buckets -- [0.2,0.3) 884 ->
2,076, [0.3,0.4) 47 -> 480, [0.4,0.5) 16 -> 80. That is **higher resolution**, and per bucket V2 is
actually the better-calibrated of the two at the top ([0.3,0.4) over-predicts by +0.073 against
V1's +0.112; [0.4,0.5) +0.120 against +0.228). But **every confident bucket over-predicts in both
models**, and V2 exposes five to ten times as many rows to that bias. A bounded quadratic score
barely notices a 0.02-0.07 over-prediction; the log score charges `-log(1 - p)` on every non-event
at the inflated `p`, so the same rows that win RPS and Brier lose mean log score. Do **not** read
this as the Stage B Candidate V3 pattern: V3 improved *all four* proper scores including log and
failed only on rank resolution, which is close to the opposite trade.

Results: `results/stage_c_goals_candidate_v4_development.json`,
`results/stage_c_assists_candidate_v2_development.json`. Designs:
`docs/phase3-stage-c-attacking-candidate-v4-design.md` and
`docs/phase3-stage-c-assists-candidate-v2-design.md`.

Stage D (composition) and a prospective forecasting path are implemented and **development-only**.
The composer (`models/points_composition.py`) draws the fitted component distributions and applies
the 2026/27 rules by seeded Monte-Carlo: v1 (core five components), v2 (+ saves + DC), v3 (full
points including bonus, via a joint per-fixture BPS simulation so own-scoring/own-bonus and the
one-winner-per-fixture couplings are represented). The prospective job
(`jobs/prospective_points_v1.py`) forecasts a full-points xP distribution per player over a future
gameweek horizon (default GW1-5) from the versioned live registry + schedule: **goals are
team-coupled Candidate V3 by default** (opponent-aware via `lambda_team`, minutes-gated;
`--attacking v1` reverts to independent per-player), **appearance uses a season-boundary correction
by default** (`--appearance seasonal`; `--appearance model` reverts), and live availability is a
reported overlay never folded into the distribution. The `seasonal` appearance recent estimate is
the **equal-weighted average of the last five matches (no recency weight)**, then blended with the
full prior-season appearance rate in early season; a recency weight (as the Stage B V3 minutes model
carries) lands hardest on the dead-rubber final gameweek and is measurably wrong at the boundary
(see the measured constant below). A recency audit of the whole composer confirmed appearance was
the **only** recency-weighted signal: xG-share and xA-share (`mean_trailing_signal`), the DC hit
rate, and the pooled GK save rate are all equal-weighted or league-pooled and were left unchanged.
It is point-in-time safe but carries every stage's development caveats and is not a
production forecast. Running it needs the live snapshots loaded (`jobs/load_snapshots`); the loaded
bootstrap also carries prices (`now_cost`), penalty/set-piece order, per-player xG, and ownership.
The prospective job now emits a canonical, provenance-bearing JSONL artifact with one full-points
distribution per `(season, gw, code)`. Stage E consumes only that artifact and implements an exact
fixed-squad ILP plus a deterministic bounded transfer planner under the verified 2026/27 squad
rules. It is development-only, not a validated recommendation. The confirmed no-transfer pruning
defect is fixed: the current squad is reserved in every successor set, so holding and banking a
transfer cannot be truncated away. The optimizer now has a versioned, immutable, fail-closed
artifact contract that binds the complete decision to the forecast, rules, Git HEAD, search policy,
and fully discovered solver identity; its reader independently revalidates squad, lineup, captain,
bench, transfer, horizon, and aggregate legality. Interactive user-custom runs build a fresh squad
and support up to five locked players and fifteen excluded players end-to-end; exclusions are
absent from the initial squad and every future transfer squad, and lock/exclusion overlap fails
closed. The post-deadline local Manager Team path separately captures a public manager entry,
reconstructs purchase/selling values where its evidence is sufficient, and optimizes transfers from
that exact squad; it remains private local development functionality rather than a hosted account
or authenticated My Team integration. Dashboard read-model schema version 3 introduced the
explicit separation of formal platform default/diagnostic plans from user-custom plans, and
version 4 added cumulative player-horizon endpoints, and version 5 split the ambiguous
player-only comparison into separate
`player_forecast_vs_actual.json` and `team_forecast_vs_actual.json` read models. Player scoring
requires complete official-gameweek finality and every forecast fixture leg, so a partial double
gameweek produces no scored player-gameweek. Team attack CRPS uses the club's exact stored goal PMF;
team defence CRPS uses the opponent's exact PMF for that fixture, never a distribution regenerated
from `lambda_against`. The browser receives only published scalar observations and score blocks;
raw PMFs remain behind the Python emitter. The version-4 player-horizon rule remains: the browser
selects exact cumulative xP and inclusive `P(points <= 2)` / `P(points >= 2/4/6/10/15)` endpoints
and never sums probabilities or derives a CCDF/model quantity. Schema version 9 remains current
for the ten established read-model files: it retains version 8's normalized player/team history,
cumulative endpoints, and forecast-owned
`cold_start_player` provenance, and extends every `player_actuals.json` fixture with its
fixture-time `team_code`, `team_short_name`, `opponent_team_code`, `opponent_short_name`, and
`was_home`. Python resolves those club identities through the season-qualified team dimension,
reconciles side, venue, gameweek, and permanent codes to `dim_fixture`, and publishes that
fixture dimension's kickoff as the canonical presentation timestamp. A browser never infers an
historical opponent from the player's current club. The separate
`player_provisional_actuals.json` and `team_provisional_actuals.json` preview envelopes each use
their own JSON schema version 1; they do not bump or reinterpret any established schema-v9 file.
The Players route exposes two explicit chronological `Actual from` / `Actual to` endpoints. Their
options are the page-wide exact finalized or explicitly provisional `(season, gw)` keys from only
the selected forecast season and its immediate predecessor, ordered from predecessor to forecast
season. The default and reset scope is the latest five such keys; at 2026-27 GW1 that is
`Actual from: 2025-26 GW35` through
`Actual to: 2026-27 GW1`. Selection includes every published key between the endpoints, without
inventing absent numeric gameweeks. This main aggregate may therefore cross the season
boundary only when its displayed endpoints explicitly do so. It never silently substitutes a
season, reuses the forecast-horizon selector, or collapses double-gameweek legs; it only sums
already-published observed components. The selected key range is page-wide, joins players across
seasons only on permanent `code`, and never backfills an individual player's missing history from
outside that range. The dense table presents that shared observed scope once above compact
`App`/stat headers. A Players-only sortable
`xP GW{Forecast From}` column sits immediately after `Pts` and defaults descending for XI/bench review:
it uses the exact fixed-start cumulative endpoint when compatible, otherwise strictly sums the
selected GW's published fixture xP, including every double-gameweek leg. A true blank is zero;
null, non-finite, duplicate, or incomplete fixture evidence stays unavailable and sorts last. The
reported availability overlay is never applied to this raw xP. The Players profile shows observed
xGI immediately after xA as the display-only sum of the selected Season–GW endpoint range's
aggregated xG and xA; if either component is unavailable, xGI remains unavailable. It is not a
transported field, a forecast, or permission to derive future goal involvement in the browser. The Players profile
displays Saves/App, DC/App, and xGC/App instead of their selected-range totals. Saves/App and
DC/App divide their complete appeared-fixture values by appearances; DC remains raw actions, not
fantasy DC points. xGC/App divides the measured xGC total by its matching measured appearances so
partial source coverage is never zero-filled. All three exclude DNPs, count every played DGW leg,
and remain position-applicable exactly as their former totals. The profile also displays BPS/App as
the selected-range observed BPS total divided by appearances. Each played DGW leg counts once,
DNPs are excluded, and any missing BPS on an appeared row makes the ratio unavailable. Normalized
actuals retain fixture-grain Saves, DC, xGC, and BPS, while the selected-range aggregate and legacy
form measures remain totals. A sortable Pts/App sits immediately before Pts so the existing
`Pts` / `xP GW{Forecast From}` adjacency remains unchanged. Pts/App averages only appeared fixture
legs, uses replayed 2026/27 points for finalized rows and raw recorded FPL points for provisional
rows, and stays unavailable if any included appeared leg lacks its status-correct points value.
Rare zero-minute points remain in the adjacent Pts total but do not enter this productivity rate.
These rates are backward-looking descriptive arithmetic, not model quantities. A provisional
player row keeps the API's mutable points only as
`total_points_as_recorded`; a finalized row keeps `points_under_rules_2026_27`. The browser selects
the correctly named measure by explicit outcome status and never aliases, combines, or replays the
provisional value. The main table remains bound to its explicit Season–GW endpoint range, but its
expanded history is a separate fixed rolling view: it retains every fixture in the page-wide latest
five distinct **season-qualified** finalized or explicitly provisional ended-match gameweeks across
the forecast season and its immediate predecessor,
then sorts newest first. At 2026-27 GW1 that window is 2026-27 GW1 followed by 2025-26 GW38 through
GW35. Every row displays its season as well as its GW. Cross-season player membership is joined only
on permanent `code`; a newcomer without predecessor-season evidence stays shorter and is never
backfilled by name or season-scoped `element_id`. Expanded rows show `Match` (season/GW,
fixture-time Club, and kickoff date) plus `Opp (H/A)`, then observed fixture-grain xG, xA,
fail-closed display xGI, DC, raw BPS,
and the other published actual components; they never show future prediction primitives. A player
who transferred is labelled with the club represented by that exact fixture row, and promoted or
relegated clubs are never substituted through a current-season registry. The shared table's future
fixture/xP
drill-down belongs to Next GW only. Its local **My squad** filter
uses the trusted public-manager capture through the explicit member-only Plan Server route and
activates only after all 15 stable codes match the selected forecast vintage's planning gameweek,
position, resolved club identity, and deadline price. Unrelated additions elsewhere in the full
selectable-player registry do not block this display-only filter or the non-optimizer Squad Draft;
Plan Builder and every optimizer solve retain the exact full-registry fail-closed gate. It then
intersects the existing filters without changing any published value. Partial/mismatched imports
fail atomically, a vintage change clears the private scope, hosted static builds never expose the
network action, and the complete Players filter panel remains immediately before the scrollable
table. The Players table additionally exposes a searchable player-name multi-select keyed by
permanent player `code` and multi-select Position and Team controls keyed by the position enum and
permanent `team_code`. Empty selection means all; choices are ORed within a control and ANDed
across controls and the verified My squad membership. Options always come from the complete active
forecast vintage, and a vintage change prunes unavailable player/team codes so a hidden stale
selection cannot empty the table. These controls are page-local. Players' **Min min/g** filter
uses the exact selected Actual-from/to fixture rows, divides observed minutes by appearances with
at least one minute, excludes zero-minute DNPs, counts every played DGW leg, and fails closed on
missing minute evidence; decision routes and Player Analytics retain the existing forecast-owned
last-five average-minutes selector. Insight request schema v4 is unchanged; any name selection,
multiple Position/Team selection, active selected-range Min min/g bound, or selected actual range
containing provisional evidence makes Players deterministic-only because that scope cannot be
represented exactly, while an empty or singleton Position/Team selection over finalized evidence
with no Min min/g bound retains the exact existing scalar renderer scope. Player Analytics defaults
to the reporting-only Established evidence scope, which excludes forecast-marked cold starts from its
shortlist/Pareto population; the explicit include control restores them without changing xP or any
probability. Never infer cold-start status from observations or treat this filter as a model change.
Any proposed bridge through a player's first three appearances requires a separately named,
pre-registered, evaluated model candidate.
BI semantic contract version 4 extends the observed player-fixture fact with deterministic latest
live components only when an exact append-only finalized outcome exists; the ledger owns both
points measures for those rows. Insight request schema version 4 carries the exact paired
`actual_season_from` / `actual_gw_from` and `actual_season_to` / `actual_gw_to` endpoints plus the
typed `include_cold_starts` selector so optional evidence stays aligned with the visible scope.
Analytics copy and tooltips remain concise;
full exact run/as-of/horizon/metric provenance stays in accessible names and authoritative tables.
Two forecast/transfer scenario gaps remain:
`chance_of_playing_next_round` is repeated across the whole horizon, and future transfers use the
deadline's static prices with no price-change or selling-value model. The append-only prediction
ledger is implemented in `src/fpl/storage/ledger.py` and records immutable player-gameweek,
player-fixture, and team-fixture forecast vintages from the JSONL artifact. Player and team fixture
outcomes are attached separately and append-only; each finalized fixture appends two reciprocal
team sides from official home/away scores, and exact repeats are idempotent while changed repeats
fail closed. BI semantic contract version 5 retains version 4's exact team PMF, ledger-owned
finalized player/team outcome facts, and finalized-live observed-player source, and adds
`fact_team_fixture_actual` at `(season, fixture, team_id)` grain. It publishes direct official
goals for/against plus nullable source-row xG/xGC, summed BPS, and raw DC actions; live component
eligibility is proven for present rows but is not an independent source-roster completeness
witness. DGW legs remain separate and unavailable evidence remains NULL. Fixture Matrix's expanded-
history scope defaults to one page-wide rolling window covering the latest five distinct season-
qualified finalized or explicitly provisional ended-match gameweeks across the forecast season and
its immediate predecessor, newest first, while explicit single-season options remain available.
Every row labels both season and GW, and provisional periods/rows are marked as such.
Cross-season club membership joins only on permanent `team_code`; promoted clubs without prior-
Premier-League evidence stay shorter rather than inheriting another club's history. Possession
and shots remain absent: the official/archive sources do not carry them and the existing
operator-vendored FBref defensive-actions path cannot supply them, so no proxy is allowed. The
BI semantic contract version 6 retains every finalized v5 fact and adds the separate
`fact_provisional_player_fixture_observation` and
`fact_provisional_team_fixture_observation` facts. They carry no `run_id` and come only from one
latest complete player-history capture per season: exactly one bootstrap, one fixtures payload,
and one element-summary for every supported element type 1-4 player. Only score-present same-
capture fixture rows with `finished_provisional=true OR finished=true` and non-null schedule
identity are considered. They remain separate provisional-display evidence until any player/team
archive or immutable-ledger final evidence exists; a shared anti-join then removes the whole
fixture from both provisional facts atomically. Fixture/player/team identity and `observed_at` must
agree, team sides must be reciprocal, and any residual provisional/finalized overlap fails closed.
These facts never enter the
append-only outcome ledgers, prediction-versus-actual read models, calibration, CRPS, or model
evaluation; official `finished=true` attachment remains the only final monitoring path. Only
Players and Fixture Matrix may merge their separate schema-v1 preview files, with finalized rows
winning after identity reconciliation. The append-only provisional capture runs daily at 01:00 UTC
(08:00 Bangkok) with a 05:00 UTC (12:00 Bangkok) recovery under the shared `api-snapshot`
concurrency group. The morning pass may skip on a cheap all-scored-fixture plus latest-GW
event-live signal; the recovery and every manual dispatch always sweep all supported element
summaries, then no-op
only on identical canonical content. Response-size, season-rollover, before/after signal, and
per-eligible-fixture aggregate history-coverage guards fail closed. Loading into the single-writer
local DuckDB and republishing local read models remain explicit operator actions. A future reviewed public ZIP includes both preview files to
preserve a complete validated manifest, but Pages stays manually pinned to the exact immutable
release in `public-data-release.json`; local refresh and daily capture do not deploy it. The Fixture
Matrix's selected metric source owns all three aligned displays: the sortable average
column, every fixture-card headline, and every fixture-card colour tier. **Opponent strength**
shows the opponent's selected-vintage display-time strength index and labels the column
`Avg Opp str (GWx-y)`; **Club ease** shows the row club's view-specific published attack,
defence, or overall ease index and labels it `Avg Club ease (GWx-y)`; **Official FDR** shows the
fixture's official FDR and labels it `Avg FDR`. The selected Attack/Defense/Overall view chooses
only the Club-ease dimension; it never makes a card headline disagree with the active source tab.
For schedule-only rows beyond the forecast vintage, Opponent strength and Club ease use their
explicit selected-vintage display proxies while Official FDR uses the current schedule-owned
value. These later values remain display context, not later fixture forecasts. Source averages
include every measured visible fixture leg, including both DGW legs and measured schedule-only
cards; unavailable values are omitted and are never zero-filled. The browser averages only
published values or the already-sanctioned display proxies and never derives a new model forecast.
The
versioned BI semantic export, atomic static JSON publish boundary,
and dashboard are implemented development-only. The application currently has nine read-only
analytic/decision routes (Summary, Fixture matrix, Team analytics, Players, Player analytics, Next
GW suggestion, Player prediction vs actual, Team prediction vs actual, and Optimizer audit), plus
the interactive Plan Builder and Squad Draft routes. The legacy `#forecast-vs-actual` hash is only a
temporary alias to the player page. Both prediction-monitoring routes classify each immutable
vintage from its complete declared component modes: only `v3` goals / `coupled` assists /
`seasonal` appearance is the prospective default, `v1` / `v1` / `seasonal` is the diagnostic
comparator, any other complete triple is a recorded sensitivity, and missing modes remain
unclassified. They open on the newest **scored prospective-default** vintage; if none exists they
fall back, in order, to the newest scored vintage, newest pending prospective default, and newest
remaining vintage. Every selector option remains available, ordered newest-first, and names both
its role and all three modes. Timestamp order alone never promotes a diagnostic above a scored
prospective default. Squad Draft uses one formal
forecast vintage, enforces roster shape and club caps, and reports price/xP without enforcing the
standard budget; it can also receive a private local manager capture but remains neither optimizer
output nor a shared read model. Goal 2's
Players-page form repair is implemented in code and focused tests: Overall, Attack, and Defence
views expose their explicit form-column matrices, including observed clean sheets, on-pitch goals
conceded, saves, and xGC with position-aware applicability. A failure-atomic local development
database rebuild and atomic BI/static republish completed on 2026-08-19, so those values are now
visible in the local dashboard. Additive migration alone still leaves existing form rows NULL, and
the final deadline vintage must run the same rebuild/export/republish sequence inside P0. These
fields are backward-looking form, not future player-level defensive forecasts. Future
saves/DC/GC/xGC primitives are unavailable and must remain absent/NULL rather than being inferred
from club lambdas or clean-sheet probabilities. The analytics, monitoring, and insight-summary
boundaries are specified in `docs/dashboard-deep-analytics.md`,
`docs/prediction-vs-actual-dashboard.md`, and `docs/dashboard-ai-summaries.md`. See also
`docs/phase4-*`, `docs/prospective-points-artifact.md`, `docs/prediction-ledger.md`, and
`docs/stage-e-squad-optimizer.md`.

The Stage D prospective-EV walk-forward backtest has now been **executed once** (2026-08-07) under
`config/phase4_ev_backtest_evaluation.yaml` contract 1.2, at commit `8af5760`, and its immutable
result is `results/ev_backtest_2025_26_gw29_38.json`. It is **never re-run, amended, or re-judged**.
It covers the final ten observed gameweeks of 2025/26, comparing the current V3 goals /
coupled-assists architecture with a V1 goals / V1 assists diagnostic comparator on identical rows.
Anchors matched the contract exactly: GW29-38, 99 fixtures, 8,224 player-fixture rows, 7,894
player-GW rows, 841 players, `mart_target_completeness` complete for 2025-26 / `2026_27`, 16 hashed
source files unchanged, clean worktree and unchanged HEAD at both pre- and postflight.

**The V1 independent comparator outscores the V3 coupled primary.** On identical rows: mean log
score 2.0899 vs **2.0510**, CRPS 0.6351 vs **0.6328**, NDCG@20 0.7762 vs **0.7926**, top-20 capture
0.7763 vs **0.7968**, top-20 overlap 0.25 vs **0.35**, MAE 0.9423 vs **0.9156**, cumulative Spearman
0.9515 vs 0.9520. The primary loses or ties on every scored metric. Its one apparent win is
aggregate calibration: **EV/actual 1.0163 against 0.9473**, a signed bias of +146.4 against -472.3
on an 8,955-point actual total.

**That calibration win has since been measured to be two errors cancelling, and is not evidence
for the coupled architecture.** It was originally read as conservation of the team goal total
showing through. It was not: the composer was applying P(play) twice and destroying **11.11%** of
all goal and assist mass (537.05 allocated, 477.40 realised), so the roster never conserved
`lambda_team` at all. That loss was offsetting an over-prediction elsewhere. With P(play) applied
once the same 8,224 rows give EV 9339.92 and EV/actual **1.0430** (bias +384.9). The defect is now
fixed forward (`docs/phase4-composer-p-play-double-gating-fix.md`); the frozen artifact keeps the
defective numbers, is not re-run or re-judged, and reproduces only at its pinned commit `8af5760`.

**This decides nothing.** The comparator is pre-registered as
`development_diagnostic_only_not_a_promotion_gate`; the run carried the composer P(play)
double-gating defect; and the target roster and first-kickoff cutoff are unversioned
outcome-derived proxies. It cannot authorize production use, promotion, or a change of default.

**A component decomposition with P(play) applied once locates the remaining bias, and it is mostly
not a modelling error.** Across the components the composer models it is accurate to **-0.5%**
(9322.3 against 9372.0). The apparent +4.3% is the **unmodelled negative components** -- cards, own
goals, missed penalties -- worth 417 points over the window and held at zero by design. Inside that
near-zero total, three things differ in kind and must not be lumped together:
(a) the **goals-conceded penalty was a real specification defect**, -175.7 points and the largest
single gap -- FPL charges a GK/DEF only for goals conceded while on the pitch, but the composer
charged every appearing player the full-match conceded distribution; (b) clean sheets under-predicted
by 7.0%, the same defect from the other side; (c) **goals over-predicting by 12.8% is regime, not
miscalibration** -- GW29-38 ran at 2.576 goals per fixture, the lowest window in the archive
(season means 2.729/2.732/3.147/2.845/2.645) against a Stage A expectation near the pooled 2.9,
about 1.9 standard errors low on 99 fixtures. Do not tune Stage A to a 99-fixture sample; that is
the home-advantage mistake recorded above.

**(c) has since been re-measured on a second window and the "nothing to do" half of that reading
is wrong.** On 2025-26 GW10-28 (191 fixtures, 14,959 rows, disjoint from the diagnosis window)
goals over-predict by **+7.2%**, and the directly measured Stage A expectation is **2.869 against
an actual 2.712** (ratio 1.058), versus **2.849 against 2.576** (ratio 1.106) on GW29-38. Stage A's
expectation moves 0.7% between the windows while reality moves 5.0%: it is anchored near the
pooled mean and **does not track the current season's scoring level**. 2025-26 delivers 2.645 over
its full 380 fixtures, about 2.5 standard errors below that anchor, and the season-to-season spread
(2.645 to 3.147) is far wider than the 0.087 standard error of a season mean. So the residual is a
season-level miss, not a 99-fixture fluke. Tuning `lambda` to the season in progress is still
forbidden for the same reason as before. See `docs/phase4-composer-out-of-window-validation.md`.

**The Stage A recency / time-decay audit that finding licensed has now been run, and its answer is
NO -- do not build it.** Blending the league level toward the season to date
(`w = N/(N+k)`, `k = 120` team-matches selected on 2021-22..2024-25 with 2025-26 held out) fixes
the level almost exactly (2.868 -> **2.733** against an actual 2.750) and is worth **-0.01%** of
team-grain log score, flat across the whole `k` grid from -0.11% to +0.03%. At the composer grain
it is worth CRPS +0.00%, PIT-80 -0.0001, log -0.31%, and decisions barely move (per-gameweek
top-20 overlap 19.21/20, same captain in 18 of 19 gameweeks). The reason it cannot help is that
**the league scoring level is not a free parameter**: lowering it improves goals (+7.2% ->
+2.5%), the conceded penalty and saves, and breaks the clean sheet by the same amount (+5.7% ->
**+11.5%**), leaving the modelled total unchanged at +2.9% -> +3.0%. A level bias is also nearly
invisible to a proper score at this grain by construction -- a Poisson charges about
`(dlambda)^2/2lambda`, so 4% costs ~0.1% at `lambda ~ 1.4`, which is why five seasons of Stage A
work never surfaced it. Do not re-open this on the level argument. See
`docs/phase4-stage-a-recency-audit.md`.

(a) and (b) are now **fixed**. Goals conceded are charged only for the share of the match a player
was on the pitch, binomially thinned to a measured per-bin exposure (see the measured constant
below). Clean sheet error fell -7.0% -> -2.4% and the penalty error +43.3% -> +18.0%, cutting their
combined absolute error 269.9 -> 104.9 points (61%). **The aggregate total moved the wrong way,
-0.5% -> +1.2%, and that is expected**: it was previously near zero only because the clean-sheet and
penalty errors offset the goals and assists regime error. Concentrating the residual in one
identified place beats a total that is right for the wrong reasons -- the latter cannot be improved,
because every real repair moves it. The largest remaining composer gap is now the **unmodelled
negative components** (cards, own goals, missed penalties): 417 points, 4.7% of actual full points,
held at zero by design.

That 417 is now measured and is **deliberately left unmodelled** (owner decision, 2026-08-07):
yellow cards 374 points, red 30, own goals 14, missed penalties 4, penalties saved +5. Do not
describe it as rare -- **cards are 90% of it and are not rare**: 374 bookings in 8,224 rows, a
booking-prone player picks one up every 2.3 appearances, and the rate persists (split-half
correlation 0.44 within 2025-26, mean 0.123 per appearance, sd 0.101). The reason to skip it is
size, not frequency: the mean effect is **-0.051 points per row**, and over a five-gameweek horizon
the spread between the most and least booked nailed starter is about **1.6 points**, small against
the residual elsewhere. Revisit only if a decision turns on that margin.

Two figures need reading with care. **Cumulative Spearman near 0.95 is inflated** by ranking all 841
players including non-starters -- it largely measures who plays; the honest within-gameweek figure
is 0.70-0.78 and cumulative top-20 overlap is 5 of 20. **PIT-80 coverage was 0.7404 against a
nominal 0.80** in the frozen run, so the fixture distributions were too narrow.

**That under-dispersion has since been located and fixed forward, and it was one defect.** The
composer's trailing-five minutes estimate was a raw maximum-likelihood `counts / n` over at most
five rows, so every marginal took one of six values and `P(play) = 1.000` was routine. Measured
over 101,306 point-in-time rows from 2021-22 to 2024-25, a raw `5/5` actually predicts appearance
**0.897** and 60+ minutes **0.869**, and a raw `0/5` predicts **0.039** -- so a nailed starter got
no lower tail and a fringe player no upper tail. `models/minutes_shrinkage.py` replaces it with a
point-in-time Dirichlet posterior (`alpha = 3.5`, selected on 2021-22..2024-25 with 2025-26 held
out; `alpha = 0.0` reproduces the raw estimate exactly). On the same 8,224 GW29-38 rows,
**PIT-80 0.74538 -> 0.79985** (nominal 0.80), CRPS +2.46%, mean log score +51.59%, clean-sheet
error -2.4% -> **-0.4%**. **MAE regresses 3.73% and that is the expected trade**: MAE is a point
metric that rewards the `P(play) = 0` rows the repair removes, while CRPS -- its proper
distributional generalisation -- improves. Two further things must not be misread: a zero-appearance
window is a **separate regime** with its own measured profile (extrapolating the shrinkage to
`k = 0` gives 0.16 against a measured 0.039), and the shrinkage target is the **in-squad**
population (bin-0 frequency 0.304), never the pooled one (0.594). **This is not the Stage B
shrinkage failure**: the estimator is strictly increasing in the observed count so it cannot
reorder within a position, and per-gameweek within-position AUC on `P(60+)` *improves* +1.02%
(better in 123 of 152 groups) because the raw estimator tied pure-absence and substitute-only
windows together at zero when they realise 60+ minutes 0.9% and 13.4% of the time. See
`docs/phase4-composer-minutes-shrinkage-fix.md`. Contract 1.2 pins the BPS residual fit, and
`trailing_ict` is bit-reproducible across DuckDB thread counts. Keep `results/` tracked; commit each
immutable result before any later run -- every candidate runner's postflight fails closed on a dirty
worktree, so an uncommitted artifact silently invalidates the next run after it has done all its
work.

The official 2026/27 payload confirms 17 scoring fields; captured official rule sources confirm
the seven thresholds/units absent from it. Two replay edge cases remain explicitly unexercised.
Do not describe the ruleset as fully validated while either remains under
`verification.unverified`.

Full archive rebuilds are failure-atomic: `build_db` rebuilds a sibling DuckDB, preserves
existing live snapshot state, refuses to overwrite a concurrently changed target, and promotes
with one atomic replacement only after success.

`README.md` is the best current overview. Treat `docs/phase0-design.md` as a mixed historical
design/as-built audit: its opening status and pre-implementation decisions are stale. The
append-only prediction ledger, player/team fixture-grain forecast transport, reciprocal finalized
outcome attachment, BI semantic v6 export, atomic ten-file schema-v9 plus two-file provisional-
schema-v1 static publish boundary, and eleven-route dashboard are all
implemented development-only. The dashboard reads only versioned static JSON derived from the
published Parquet export; it never queries the mutable production DuckDB. Deep analytics and exact
player/team monitoring and deterministic/optional evidence-bound insight summaries are implemented
development-only. P2.5 in `DEV-ROADMAP.md` owns any later post-deadline work; this implementation
does not authorize a model-default change or reinterpretation of a frozen evaluation.

## V2: the football-first prediction engine (2026-09-04)

V2 is an architectural addition, not a replacement. **V1 is untouched**: no model, config,
frozen result, candidate document, ledger row or prospective default changed, and no frozen
evaluation was re-run, amended or re-judged. V2 is development-only and nothing in it is
promoted.

`docs/v2-architecture.md` is the authoritative description. In outline:

```
Premier League / FPL data -> football data layer -> football engine -> fixture environment
    -> FPL component engine -> full points distribution -> decision / optimizer
```

The contract between the football half and the FPL half is `FixtureEnvironment`
(`src/fpl/artifacts/fixture_environment.py`). Components receive it; they never query a table.
Because `models/component_engine_v2.py` produces the composer's existing
`ComponentDistributions`, the composer, the prospective artifact contract and the optimizer are
unchanged — V2 plugs in at a boundary that was already in the right place.

### The football data layer is provider-agnostic, and that is the design point

`mart_fact_team_match_stats_v2` is *the team-match football fact* at one club x one fixture,
carrying a `provider` column — it is **not** "the SDP table". Two providers share the grain:

* **`fpl_archive`** — derived from marts already in this repository. Available for every season,
  so V2 is runnable and evaluable with no external capture.
* **`pl_sdp`** — the Premier League SDP backend. The owner machine completed the first real
  capture of five historical seasons plus current completed matches on 2026-09-05: 1,921
  match-stat payloads / 3,842 team sides now populate the provider fact. The exhaustive inventory
  observed 246 fields; only goals, xG, and SOT currently
  satisfy the independent-reconciliation rule for `verified_semantics: true`. See
  `docs/pl-sdp-real-provider-validation-2026-09-05.md`. The source remains network-dependent, and
  every unverified or unmapped value stays losslessly available rather than guessed.

Sharing one grain makes reconciliation structural rather than a script, and where two providers
measure the same concept by different routes **both values are kept in separate columns** —
`expected_goals_allowed` (the opponent's xG mirrored) and `expected_goals_conceded_measured`
(FPL's per-player xGC) are the standing example. A metric a provider does not carry is NULL.

Metric columns on the V2 tables are generated from `config/pl_sdp_metrics.yaml` by
`storage.db.ensure_sdp_metric_columns`, exactly as ruleset target columns are generated from the
scoring configs: adding a metric is a config change, never a schema migration. Unmapped provider
fields land in the tall store `stg_pl_sdp_team_match_metric` and are reported by
`jobs.audit_pl_sdp`, so a wrong guess in the dictionary is lossless rather than destructive.

### Identity is measured, never assumed

Whether `stg_fixture.pulse_id` equals the SDP `matchId` is a question, and
`jobs.audit_pl_sdp --stage` answers it into `results/pl_sdp_identity_audit.json`. Resolution is
pulse_id first (corroborated on season, kickoff within 300 seconds, score, and teams), then a
deterministic fallback on season and kickoff, narrowing multiple candidates by teams and then
score. A selected
candidate's Home/Away teams are always corroborated. Ambiguity, contradiction, and one SDP match
claimed by two fixtures all fail closed.
Club names corroborate a match already made; they never make one, and a name resolving to two
clubs across seasons is dropped rather than picked. `pulse_id_match_rate` is `None`, not `0.0`,
when no fixture carried a pulse_id.

The real audit measured `pulse_id == matchId` at **0/1,900 (0%)**. All 2,280 fixtures instead
resolved one-to-one by season and kickoff, narrowing multiple candidates by teams and then score,
and always corroborating Home/Away team codes before accepting a match. All 2,280 reconciled
kickoffs are now exactly equal after resolving SDP's `Europe/London` wall time to UTC; the maximum
absolute delta is zero seconds. There was zero ambiguity, contradiction, duplicate claim, or
unmatched fixture. That fallback is required plumbing, not a temporary bridge.

### V2 evaluation results: both candidates failed, and are left as committed

`config/v2_team_environment_evaluation.yaml` and `config/v2_gk_saves_evaluation.yaml` were
pre-registered before any candidate ran. Both declare
`promotion_requires_prospective_window`, so no historical result could promote anything.
Full record: `docs/v2-team-engine-development.md`; result:
`results/v2_team_environment_development.json`.

**Harness validation.** The incumbent `trailing_goals_attack_defence` scores **1.50030** over
181 folds and 3,640 predictions under the V2 harness, against the frozen Phase 1 record of
**1.5003 over 181 folds and 3,640 predictions**. The harness reproduces the incumbent to five
decimal places, which is what makes the comparisons below about models rather than about a new
harness.

**Team environment: not promoted, fails its gate.** Best rung (`goals + xG`) scores 1.49599, a
**+0.2867%** lift against a 1% bar, and **2021-22 regresses -0.2108%**, so it fails the
per-season non-regression rule as well. Rungs C and D are bit-identical to B because `pl_sdp`
was uncaptured at that frozen evaluation's knowledge time: the upper ablation ladder is
**untested, not null**, and nothing here says whether shot volume or territory helps. The
inner-holdout xG weight rises monotonically with coverage (0 folds fitted in 2021-22; 6 folds
in 2022-23 at a selected weight of **0.000**; then 0.362 / 0.579 / 0.645), so the pooled figure
averages over two seasons in which the candidate could not differ from its own floor.

**GK saves V2: not promoted, and the hypothesis is refuted in the regime that matters.** The
candidate replaced V1's identity — in which shots on target faced is a deterministic function of
goals conceded — with a directly predicted shots-faced quantity. Pooled it improves log score
+0.168% and CRPS +0.63%, and **the per-season split inverts that**: +1.37% (2021-22) and +2.28%
(2022-23), then **-1.10%, -1.24%, -0.27%** once the engine's goal rate carries xG. The crossover
is exactly the xG-coverage boundary. Both candidates are left as committed and are **not
retuned**.

### V2 job surface

```
python -m fpl.jobs.audit_pl_sdp --probe              # discover provider season ids (network)
python -m fpl.jobs.backfill_pl_sdp --season 2024-25  # historical capture (network)
python -m fpl.jobs.capture_pl_sdp --lookback-days 5  # incremental capture (network)
python -m fpl.jobs.audit_pl_sdp --stage              # stage + identity/coverage/reconciliation
python -m fpl.jobs.build_db                          # rebuild, including the V2 marts
python -m fpl.validate.dev_v2_team_environment --results results/
python -m fpl.jobs.prospective_environment_v2 --gw-from 1 --gw-to 5
```

`.github/workflows/pl-sdp-capture.yml` is a durable raw-inspection path, mirroring `snapshot.yml`
(curl/gzip/jq only, no Python) so a Python refactor cannot stop a capture. It is statically valid
against the observed cursor/result envelopes, but cannot be dispatched until the workflow exists
on the default branch, and no checksum-validating importer for its packages exists yet. The six
configured season ids are live-verified; the first capture used direct local provider access. Any
new season still requires evidence rather than a guessed id.

## Non-negotiable correctness rules

Preserve the R1-R6 rules in `README.md` and their tests.

- Never use recorded `total_points` as a model feature or cross-season model target. Model
  components/events and apply the target season's scoring rules.
- Scoring constants belong in `config/scoring_<ruleset>.yaml`, not Python. A rules change
  requires config validation and replay tests.
- Model distributions, not only expected values.
- All modelling features must be point-in-time correct. Use timezone-aware UTC instants and
  the `FeatureSource`/`PointInTimeView` capability; observed results use `kickoff_time < as_of`.
- Code under `src/fpl/features/` must not import DuckDB, issue SQL, accept a raw database
  connection, read `mart_target_*`, or expose future outcome columns through schedule data.
- Preserve daily live data because it cannot be reconstructed after season rollover.
- Keep the minutes model separate from per-minute event/rate models.

Also preserve these data contracts:

- Player identity is stable `code`; `element_id` (or archive field `element`) is season-scoped
  and reassigned yearly. Never filter or join a bare `element_id` across multiple seasons.
  Require a season-qualified `(season, element_id)` key, or `code` for cross-season player
  tracking. `code` is 1:1 with the player's permanent identity across all seasons. The failure
  mode is identical to team IDs: `element_id` values are reused across seasons for completely
  different players. For example, `element_id = 308` resolves to Almiron (2021-22), Aké
  (2022-23), Salah (2023-24), Ward (2024-25), and Heath (2025-26). Joining on `element_id`
  across seasons merges five different players into one historical profile. Additionally,
  `web_name` can drift between seasons (for example, `Salah` to `M.Salah`), making `code` the
  only valid primary key for tracking players over time.
- Team IDs are season-scoped. Never filter or join a bare team ID across multiple seasons.
  Require a season-qualified `(season, team_id)` key, or `mart_dim_team.team_code` for
  cross-season club identity. This rule has been broken once already, inside the Stage A
  baselines, and it cost 0.022 of mean
  log score and inverted the xG-versus-goals answer before anyone noticed -- the 26 distinct
  clubs in a four-season window were being compressed into 20 id slots.
  `team_code` is 1:1 with the club (27 codes, 27 names over five seasons) and is the only
  key permitted for following a club between seasons, which Dixon-Coles time decay and
  promoted-team priors both require. The failure mode is not merely that ids move but that
  they return: id 10 is Leeds, Leicester, Fulham, Ipswich, then Fulham again, so a
  cross-season join on team_id appears to work and yields a Fulham history with Ipswich in
  the middle of it.
- A player can turn out for more than one club inside a season, so "which team is this
  player on" is a question with a time in it. `mart_dim_player.team_id` records only the
  club a player finished the season at: measured 242 transfer stints, of which the
  dimension matches 120. Resolve a player's club from the fact row's `team_id` or from
  `mart_dim_player_stint`, never from `mart_dim_player`. Do not assume two stints -- three
  clubs in one season occurs.
- When a player moves, his attacking *share* travels with him and the team *scale* does
  not. Defensive contribution is a property of the team system rather than the player
  (measured team hit rates range from 0.333 to 0.146), so a transferred player's DC
  expectation must be rescaled to the destination club, never carried over.
- Player-fixture grain is `(season, code, fixture)`, not player-gameweek. Double gameweeks are
  real; exact duplicate source rows are not.
- `NULL` means unmeasured or unavailable and must not be silently converted to zero.
- Assistant Manager elements (`element_type == 5`) are not players and stay excluded.
- Raw archive tables remain all-VARCHAR. Interpret and repair values only at the staging
  boundary, with declarative repairs in `config/data_quality.yaml`.
- Snapshots, database rebuilds, and publish exports that claim all-or-nothing behavior must
  actually use a transaction or an atomic temp-output replacement. Add a failure-path test.
- Event time and knowledge time are different. `kickoff_time` prevents use of future match
  outcomes, but schedules, postponements, availability, and API fields must also be versioned
  by `known_at`/`captured_at` before they are safe for walk-forward backtests.
- A provider metric this repository has never observed is an ASSUMPTION. Keep its provider
  field names as alias lists carrying `verified_semantics: false`, retain every unmapped field
  in the tall metric store, and promote a name to verified only after a real payload has been
  inspected AND reconciled against an independent source.
- Two providers measuring the same concept by different routes get two columns. Never fill one
  from the other, and never reconcile a disagreement away -- the disagreement is information
  about the sources.
- Fixture identity across data sources is measured, not assumed. Corroborate on enough
  dimensions to be deterministic, fail closed on ambiguity or contradiction, and never
  fuzzy-match: a wrong fuzzy match is indistinguishable from a right one.
- A post-match measurement added to a feature-readable table must be registered in
  `features.pit.OUTCOME_COLUMNS` in the same change. A new column that silently defaults to
  "safe to read from the future" is the leak the point-in-time layer exists to prevent.
- Never project a bare `TIMESTAMPTZ` into a `fetchall()`/`fetchone()` result. DuckDB converts
  it through `pytz`, which this project does not depend on (it pins `tzdata` for `zoneinfo`),
  so such a query passes on a machine that happens to have `pytz` and raises on a clean
  install. Project `epoch_us(...)` and rebuild the instant in Python. The Arrow path
  (`to_arrow_table()` into Polars) is unaffected. Found three times now -- BI export, outcome
  and ledger attachment, and the V2 SDP transform -- and guarded behaviourally by
  `tests/test_no_pytz_dependency.py`.

## Repository map and boundaries

- `config/`: sources, scoring rules, and declarative data-quality policy.
- `src/fpl/ingest/`: external archive/API boundaries and raw payload handling, including
  `pl_sdp` (the Premier League SDP client: raw-preserving, schema-drift tolerant, loud on an
  envelope it cannot interpret).
- `src/fpl/storage/`: DuckDB connection policy, schema, and append-only prediction ledger.
- `src/fpl/transform/`: raw-to-staging crosswalks, validation, facts, and targets.
- `src/fpl/features/`: point-in-time-safe read API and, later, feature construction.
- `src/fpl/validate/`: walk-forward folds, proper scoring rules, Stage A baselines, harness.
  It reads outcomes, which the feature layer may not -- scoring a prediction needs the label.
- `src/fpl/models/`: scoring, the Stage A team-goals models, Stage B minutes candidates, and
  Stage C attacking-goals baselines/probes.
  V2 adds `football_engine_v2` (one attack/defence rating system per football signal),
  `gk_saves_v2`, `defensive_environment_v2`, and `component_engine_v2` (the adapter onto the
  unchanged composer input).
- `src/fpl/artifacts/`: stable, typed prospective-points and optimizer-decision transport contracts.
- `src/fpl/optimize/`: Stage E squad, lineup, captain, and bounded transfer planning.
- `src/fpl/jobs/`: thin orchestration/CLI entry points.
- `tests/`: executable data contracts; vendored API fixtures keep tests offline.
- `docs/`: design records, operational runbooks, and the static publish contract.

Keep network clients, transformation logic, feature access, statistical models, orchestration,
and presentation contracts separated. Jobs should coordinate domain functions rather than
accumulating business logic. Nothing downstream of the BI/static `publish` boundary may query
DuckDB.

## Working protocol

1. Read `README.md`, `DEV-ROADMAP.md`, the relevant config, implementation, and tests before
   changing a contract. Inspect `git status --short` and preserve unrelated or user-owned changes.
2. State assumptions when FPL rules or upstream payload shape have not been verified. Never
   promote synthetic fixtures or inferred rules to confirmed facts.
3. Prefer an explicit typed contract at external boundaries. New network behavior needs
   retries, bounded timeouts, shape validation, and offline tests.
4. For schema or pipeline changes, test grain, row accounting, null semantics, season-scoped
   joins, idempotence, failure atomicity, schema drift, and point-in-time behavior.
5. For model work, define the walk-forward split and baselines before fitting. Iterate observed
   gameweeks rather than assuming `1..38`; 2022-23 has no GW7. Report calibration and
   distribution metrics in addition to ranking/point metrics.
6. Update code, tests, configuration, and the relevant documentation in the same change when
   a contract or roadmap status changes.
7. Keep tests deterministic and network-free. Use the local stub and clearly-labelled vendored
   fixtures. Archive-backed tests may be marked `archive`.
8. Prediction runs are immutable facts. The implemented ledger must retain every run and forecast
   vintage with `as_of`, creation time, input hashes, component/contract identities, and stable run
   ID. Extend it append-only; never update an old forecast row with a newer prediction.
9. Keep predictions and outcomes separate. Attach actuals only after the fixture is final, at
   player-fixture grain `(season, code, fixture)`; aggregate to gameweek only downstream. Recorded
   points and points replayed under `scoring_2026_27` must remain separately named. Team outcomes
   attach independently at `(season, fixture, team_id)` with two reciprocal sides. A convolved
   player-gameweek forecast may be scored only when the complete official gameweek and every one of
   that player's forecast fixture legs are final; a partial double gameweek is never scored.
10. Internal marts or a ledger may use DuckDB, but BI, dashboard, and public consumers receive an
    atomic read-only export (prefer pivot-friendly Parquet plus versioned application JSON). They
    never query the mutable production database.
11. Reporting may filter, sort, sum already-published expected values, and compute Pareto or
    quadrant presentation geometry. It may not derive a model quantity from primitives, add or
    condition probabilities, recreate a distribution from a mean, or multiply an observed per-90
    display rate by forecast minutes. Exact multi-fixture/horizon probabilities and scoring metrics
    are computed in the Python publish layer from stored distributions.
12. A browser may send only exact typed public selectors to a language-rendering boundary. The
    trusted server verifies the selected static generation and constructs a bounded,
    provenance-keyed allowlist of already-published facts. A provider may select/group fact ids; it
    never authors canonical numbers or prose and performs no arithmetic, probability work, causal
    inference, model verdict, or decision provenance. Deterministic summaries remain available on
    every route. Provider keys stay in a trusted server process; never put them in Vite/static
    assets, URLs, browser storage, logs, or Git, and never send manager, squad, bank, selling-value,
    capture, or custom-plan data to a third party.

Run the smallest relevant tests while iterating, then use the full local gate before handoff:

```powershell
.\.venv\Scripts\pytest.exe -q
.\.venv\Scripts\ruff.exe check src tests
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\mypy.exe src
```

Equivalent `uv run` commands are acceptable. Do not add a new dependency casually; justify it
against the small single-file data scale, update `pyproject.toml` and the lockfile together,
and keep production dependencies separate from development tools.

## Measured constants

These were measured against the archive in this repository and supersede any external
figure. `docs/research-adaptation.md` carries the evidence and the contradicting sources.

- Home advantage is **pooled with decay, never taken from the last one or two seasons**.
  Per-season gaps are 0.208 / 0.416 / 0.321 / 0.092 / 0.303 goals; a single season's
  estimate has a standard error near 0.09, the same size as the "collapse" some sources
  report, and 2025-26 rebounded after 2024-25's low. Pooled value 0.268.
- Promoted-team prior: attack **0.719x** league (sd 0.157), defence **1.309x** (sd 0.228),
  as the mean of per-team ratios rather than a ratio of pooled means. The spread is the
  point -- Fulham 2022-23 arrived at 1.015 and Southampton 2024-25 at 0.466 -- so the prior
  must carry its variance and yield quickly to observed matches. Defence improves over a
  season (+31% conceded in GW1-10, +14% from GW11) while attack does not, so the two sides
  decay differently.
- Finishing (goals minus xG) does not persist: FWD 0.138, MID 0.060, DEF -0.103
  season-to-season. Shrink it essentially fully to the positional mean.
- Defender attacking signal is **xA, not xG**: persistence 0.784 against 0.319.
- Goalkeeper save rate is a league constant at **67.3% +/- 0.4pp** over five seasons, so
  individual deviation is almost all noise. `saves + goals_conceded` is the only available
  proxy for shots on target faced.
- Team strength combines **multiplicatively**: `atk x def_opponent` correlates 0.439 with
  goals scored, the subtractive form 0.070. Facing the weakest quartile of defences yields
  1.935 goals against 1.040 for the strongest -- a 1.86x range.
- Any persistence figure must be measured **within position**. Pooled across positions
  xG/90 reads 0.871, which measures the position rather than the player.
- **xG beats recorded goals as the Stage A training signal wherever xG is measured**, by
  +0.71% relative lift on mean log score over the three seasons with complete coverage, and
  it wins each of them individually on both proper scores. Pooled over all five seasons goals
  wins by 0.70%, but that figure measures xG's *absence*: 2021-22 carries none at all (the xG
  baseline degenerates exactly to the league intercept) and 2022-23 only 64%. Never quote the
  pooled number as the answer.
- **80% interval coverage must never be gated on a raw central interval for a count
  distribution.** `[q0.1, q0.9]` covers `F(q0.9) - F(q0.1 - 1)`, strictly above 0.80 by
  construction, and the excess measures the pmf's discreteness rather than the model. It
  therefore prefers wrong models: at a true rate of 1.80 the correct model misses 80% by
  0.164 and a model biased 33% high misses by 0.002. Across true rates 1.0-2.2 the raw
  measure was closest to nominal at the correct rate in zero of five cases. A correctly
  specified model's randomised PIT is exactly `Uniform(0, 1)`, so its band coverage is
  exactly 0.80 at the truth. Contract amendment 1.1 gates
  `pit_interval_80_maximum_absolute_error`; the raw figure stays reported.
- Polars `group_by` without `maintain_order=True` partitions across threads, so a float sum
  is not bit-reproducible: 16 of 20 repeat aggregations on this archive disagreed, and the
  difference reached the reported log score. Every aggregation feeding a pre-registered
  evaluation must pin the order.
- The **Dixon-Coles low-score correction cannot change a marginal**. Summing the corrected
  joint over the opponent's goals, the two cells touching `own = 0` cancel exactly because
  `q(1) = lambda_opp * q(0)` for a Poisson, and the same holds at `own = 1`; measured shift is
  under 3e-17. So `rho` cannot improve any Stage A score, and a candidate reporting a gain
  from it is reporting noise. Fit it for the joint, which Stage D needs, and never apply it to
  a marginal prediction.
- The Stage A candidate's edge is **cross-season history and xG, not functional form**. Split
  by phase of season it gains +2.09% and +2.61% in the opening nine gameweeks of 2022-23 and
  2023-24, and loses throughout 2021-22, which has neither a preceding season nor any xG.
  Judge a team model by regime, not by a pooled figure that averages those away.
- Candidate V2 is also a **documented non-promotion**: log score 1.4939, CRPS 0.6355,
  PIT-80 0.803, 3,640/3,640 predictions, 84 cold starts, and zero leakage failures. It misses
  aggregate log lift and the per-season log gate in four seasons; CRPS regresses in 2021-22,
  2022-23, and 2025-26. Its 2-match prior-grid boundary was selected in 72 of 181 folds. This
  is diagnostic evidence for a new structural hypothesis, not permission to widen V2 post hoc.
- **Appearance at a season boundary is measured-uncertain and the trailing window is its worst
  phase.** For nailed players (season minutes >= 1800), appearance `P(min>=1)` is 0.876 in Aug-Nov
  and only 0.804 in May (dead-rubber rotation); a prediction at a GW1 deadline whose trailing-five
  window is those May rows underrates a nailed starter by ~7pp. The full prior-season appearance
  rate predicts a next-season opener better than the last five rows (MAE 0.244 vs 0.252; a
  0.7*long + 0.3*recent blend is best, 0.237). But do not over-trust it: a player nailed last
  season (0.913) appears only **0.776** early next season on average — transfers, injuries, and lost
  spots make cross-season appearance genuinely hard (MAE ~0.22 for every method). Lift rested-but-
  nailed starters at the boundary; never treat "available" (`status`) as "starts".
- **The trailing-appearance window must be equal-weighted, never recency-weighted, at a season
  boundary.** The final gameweek is a dead rubber: measured over three boundaries, nailed starters
  (>= 0.85 start rate over GW1-37) collapse to **0.73 started / 0.21 did-not-play** in GW38
  (goalkeepers 0.97 -> 0.75 / 0.25), so it is the single least representative match of the season —
  yet a geometric recency weight lands its heaviest weight there. Raya, an ever-present (37/38 at a
  full 90), reads as a raw p_play of **0.51** under the Stage B V3 recency weight. Equal-weighting
  the last five predicts a next-season opener strictly better than recency-weighting everywhere
  (overall MAE 0.223 vs 0.234; goalkeepers 0.181 vs 0.195). This is why the prospective composer's
  `seasonal` appearance uses a plain last-five average, not the model's recency-weighted estimate.
  The same audit measured that recency does **not** help the xG signal either (equal-5 MAE 0.0944
  vs recency-5 0.0957 predicting next-season xG/appearance for attackers) — but the xG/xA/DC signals
  already equal-weight appeared rows, so only appearance needed the fix.
- **A player's exposure to his team's conceded goals is not his share of the minutes.** FPL charges
  the goals-conceded penalty, and awards the clean sheet, only on goals conceded *while the player
  was on the pitch*. Measured directly (the archive's player `goals_conceded` is already an on-pitch
  figure) as `mean(player conceded) / mean(team conceded)` over GK/DEF rows by Stage B minutes bin:
  **0.344** (1-59, 3,986 rows), **0.813** (60-89, 2,324 rows), **0.999** (90, 16,464 rows). The same
  bins average **0.254 / 0.837 / 1.000** of the match *by minutes*, so a substitute sees **35% more**
  of his team's conceded goals than his time on the pitch implies -- he comes on into a game already
  going badly, and late goals are more frequent. Never derive this fraction from minutes. Pooled
  across positions: per-position spread is modest where measurable (bin 1: DEF 0.341, MID 0.316,
  FWD 0.295; bin 2: DEF 0.814, MID 0.776, FWD 0.736) but the goalkeeper cells carry 73 and 16 rows.
  Charging every appearing player the full-match distribution over-charged substitutes **4.2x**
  (0.559 against an actual 0.133).
- **`rest_days` cannot see cup or European congestion.** The archive is Premier League only (380
  fixtures per season, no competition field), and `rest_days` is the gap between a team's
  consecutive PL fixtures — so a midweek FA Cup / League Cup / Champions/Europa fixture is invisible
  and a truly-congested player reads as fully rested. No minutes model uses `rest_days` today, and
  true congestion is not computable from this data without an external all-competitions fixture
  feed. Month / phase-of-season is the only available congestion proxy.
- **A raw trailing-five appearance count is badly over-confident, and `k = 0` is a separate
  regime.** Measured over 101,306 point-in-time rows (2021-22..2024-25), what raw `k/5` actually
  predicts is: `0/5` -> play **0.039** / 60+ **0.036**; `1/5` -> 0.310 / 0.279; `2/5` -> 0.459 /
  0.419; `3/5` -> 0.588 / 0.543; `4/5` -> 0.736 / 0.695; `5/5` -> **0.897** / **0.869**. Five
  Bernoulli trials do not support a probability of 0 or 1, and a composer that draws a minutes bin
  from one gets no lower tail for a nailed starter and no upper tail for a fringe player. For
  `k >= 1` the realised rate is near-linear in `k` (a Dirichlet posterior, concentration **3.5**
  fitted out of sample), but extrapolating that line to `k = 0` predicts 0.16 against a measured
  **0.039** on 43,139 rows -- a zero-appearance window means injured / suspended / out of the side,
  a persistent state, and needs its own measured profile. Shrink toward the **in-squad** bin
  frequency (bin-0 **0.304**), never the pooled one (**0.594**), which double-counts absences the
  regime split already removed. Positional priors are required for goalkeepers, whose profile
  (0.741, 0.005, 0.001, 0.253) is nothing like an outfielder's.
- **Shrinking a five-row count buys rank resolution rather than costing it** -- the opposite of the
  Stage B V1/V2/V3 result, so do not assume the Stage B failure generalises. The posterior mean is
  strictly increasing in the observed count, so within a position it cannot reorder; and the raw
  estimator *ties* pure-absence and substitute-only windows together at `P(60+) = 0` when they go
  on to play 60+ minutes **0.9%** and **13.4%** of the time (17,069 rows in 2025-26). Measured
  per-gameweek within-position AUC on `P(60+)` rises 0.90886 -> 0.91815. Measure ranking with AUC,
  not an average-rank Spearman: on a binary outcome with a large tie block the Spearman reads
  -10.9% where AUC reads +2.2%, and the AUC figure is the correct one.
- **At a season boundary the shrinkage floor and the appearance blend under-predict rested-nailed
  starters, but the degenerate zero is gone.** Measured on the first live 2026/27 GW1-5 prospective
  run (`as_of` = the real GW1 deadline), the regime the estimator was never fitted against. **Zero**
  of 570 roster players are predicted a final `P(play)` of exactly 0.0 (was one on the raw
  `counts / n` estimator): the shrinkage floor plus the `seasonal` blend removes the degenerate zero
  on live cross-summer data. Zero-history players route to the position prior (constant per position:
  GK 0.2496, DEF 0.4089, MID 0.4387, FWD 0.4216), never to "will not play" -- but a genuine
  first-choice **goalkeeper** with no PL history reads 0.25 because the GK prior is reserve-dominated
  (two keepers per club, one starts), and no live field corrects it. The real defect is bounded and
  narrow: an all-zero trailing window (a player rested through the May dead rubbers) is mapped by the
  shrinkage to the out-of-side floor (~0.037), and the blend `p_play = 0.7 * prior + 0.3 * recent`
  then trusts that *actively wrong* recent at 0.3, capping a nailed player at a ceiling of
  **~0.71** (goalkeepers ~0.635). Vicario (prior 0.816, live status available) reads **0.576** --
  ~0.24 below his prior and ~0.14 below the measured cross-season nailed average of **~0.78**. It is
  narrow (one player above a `prior >= 0.8` bar, ~six high-appearance returners) and conservative
  (under- not over-prediction), so it is **not fixed before GW1**: the 0.7/0.3 blend is
  measured-optimal on average and re-weighting the boundary-rest case is a modelling change needing
  its own validation window, and return-from-rest belongs in the availability overlay. See
  `docs/phase4-season-boundary-appearance-underprediction.md`.
- **Stage A predicts about 2.86 goals per fixture regardless of the season it is in.** Measured
  directly on 2025-26: `E[goals]` 2.869 over GW10-28 and 2.849 over GW29-38 -- a 0.7% move --
  while the actual rate moved 2.712 to 2.576, a 5.0% move. Season rates over the archive are
  2.729 / 2.732 / **3.147** / 2.845 / **2.645** (pooled 2.820), a 0.50 spread against a season-mean
  standard error near 0.087, so **the league scoring level is genuinely non-stationary and Stage A
  does not track it**. The consequence is a persistent composer bias in one direction for a whole
  season: +5.8% over GW10-28, +10.6% over GW29-38. Do not fix this by fitting `lambda` to the
  season in progress. **That "fix it by weighting the current season" route has now been measured
  and does not work** -- it is worth -0.01% at the Stage A grain and +0.00% CRPS at the composer
  grain, because the level trades goals accuracy against clean-sheet accuracy one for one.
- **A level bias is nearly invisible to a proper score, so do not expect one to find it.** A
  Poisson log score charges about `(dlambda)^2 / 2*lambda` for a level error, so at the Stage A
  team-match rate of `lambda ~ 1.4` a **4% level error costs ~0.1%** of log score. Five seasons of
  Stage A evaluation never surfaced a 4-8% level miss for this reason. Aggregate bias has to be
  measured as bias, against realised totals, and by position -- never inferred from a score that
  looks healthy.
- **The composer's remaining bias is positional, not global, and it is mis-allocated attacking
  output.** With the unmodelled negatives added back: GK +5.9%/+3.5%, DEF +5.3%/+3.7%,
  MID +2.4%/+4.0%, FWD **-3.1%/-4.1%** over 2025-26 GW10-28 / GW29-38 -- forwards low and
  everything else high, in both windows. Measured as expected *counts* against realised counts,
  **forwards are allocated 38-40% too few assists in both windows** (model share 7-8% against an
  actual 11-15%), **defenders +29%/+61% too many goals** and +12%/+28% too many assists, and
  **goalkeepers 1.0-1.6 goals against an actual zero**. A defender's goal scores 6 against a
  forward's 4, so this inflates the total and mis-ranks positions at once. It is consistent with
  the already-measured constant that the defender attacking signal is **xA, not xG** (persistence
  0.784 against 0.319): a trailing xG share is near-noise for defenders, and one converted
  set-piece keeps a defender's share inflated afterwards.
- **Do not attribute the positional bias to the clean sheet, and do not "fix" the Poisson zero.**
  Both were tested and rejected. The clean sheet runs -0.4% on GW29-38 while GK/DEF are still
  +3.5%/+3.7% there. The Stage A Poisson zero looks +7.4% too high pooled (0.2659 predicted against
  0.2475) but splits by season as 1.021 / 0.993 / **1.292** / 1.084 / 1.020 -- the whole effect is
  2023-24, the outlier scoring season where the level miss shows up as an apparent shape defect.
  Train z = +2.72, 2025-26 holdout z = **+0.32**. Third pooled-figure-is-one-season trap in this
  repository, after xG coverage and home advantage: **always split a pooled anomaly by season
  before acting on it.**
- **Binomial thinning over-states the bin-2 clean sheet by about a third, and it is worth ~15
  points.** Conditional on the team conceding exactly one goal (746 rows), a 60-89 minute GK/DEF
  keeps the clean sheet **0.1408** of the time against thinning's **0.1870** -- a player withdrawn
  in that window is disproportionately one whose side had already conceded, so the goal falls
  inside his window more often than independent timing implies. Do not compare raw `P(clean sheet)`
  across minutes bins to measure this (0.2495 at 60-89 against 0.2713 at 90); those are different
  populations, whose teams concede 1.49 against 1.336 per match, and the composer already handles
  that through each fixture's own rate. Thinning remains right on the conceded *mean* (0.417
  against 0.412).
- **A newcomer's launch price predicts whether he plays; two-season-old statistics do not.**
  Measured over 473 players with no archive row in either of the two preceding seasons
  (2023-24..2025-26), the correlation between launch price and the appearance rate of a player's
  first five gameweeks is GK **0.619**, MID 0.508, FWD 0.473, DEF 0.250, and the pooled ladder is
  monotone: 4.0-4.5m appears 0.180, 4.5-5.0m 0.301, 5.0-5.5m 0.488, 5.5-6.0m 0.654, 6.0-6.5m
  0.787. All 35 newcomer goalkeepers priced at or below 4.0m appeared **0.000** of the time. A
  season t-2 term, by contrast, adds nothing to appearance once t-1 is known -- the partial
  correlation is DEF -0.020, MID +0.083, FWD -0.083, and only GK +0.268 -- so a
  `0.2*t-2 + 0.3*t-1 + 0.5*last-5` blend loses to the shipped `0.7*prior + 0.3*recent` in every
  position group. It *does* help per-90 RATES (xG/90 partial +0.411 for midfielders), which is
  the split the minutes/rate separation already asks for. See
  `docs/phase4-newcomer-priors-and-style-audit.md`.
- **Price is absolute and cannot see the incumbent, and that gap is worth a cap.** Among newcomers
  whose club fields an established same-position player (prior-season appearance >= 0.70), those
  priced BELOW him appear **0.284** of the time (n=201) against 0.508 when priced level (n=75) and
  0.863 when priced above him (n=25). The 0.284 reproduces at 0.283 on the 2025-26 rows alone.
  `models/price_starter_prior.BEHIND_INCUMBENT_CAP` caps exactly that group; it never raises
  anyone.
- **Opponent playing style adds nothing beyond opponent strength, and the audit is closed.** Under
  a deliberately generous setup -- style indices built from the FULL season and scored in-sample --
  every team-grain correlation with the strength model's residual sits inside |t| < 0.85 over 3,040
  team-match rows, including both style-by-style interactions. Absorbing opponents concede 1.808
  goals against 1.154 for controlling ones and the strength model absorbs the whole of it
  (residuals -0.025 against +0.011). At player grain the split-half reliability of "this player
  suits that style" is 0.016 (DEF), 0.053 (MID) and 0.198 (FWD) within position, against a 0.44
  benchmark for card-proneness. Do not ingest an external style feed on this evidence; if it is
  ever re-opened, run the same kill-test on the new feed BEFORE wiring anything into a model.
- **Standard deviation grows as the square root of expected points, so a Sharpe ratio is just
  `sqrt(EV)` and ranks nothing new.** Measured on the composer's own GW1 distributions,
  `sd / sqrt(EV)` is flat at 1.86, 1.72, 1.70 and 1.74 for EV of 1, 2, 3 and 4. Spearman between a
  Sharpe rank and an EV rank is **0.919**, and points-per-million reaches **0.981**. An EV-versus-sd
  scatter collapses onto a parabola. Risk has to be measured on an axis that is not collinear with
  the mean -- `P(haul)` against `P(blank)`, or ownership-relative active return -- or it is
  measuring the mean twice.
- **Expected points are summable across gameweeks; probabilities are not.** A gameweek row is the
  convolution over that gameweek's fixtures, so summing `expected_points` over a horizon is exact
  and handles double and blank gameweeks with no special case. Summing a probability does not:
  measured on one player over GW1-3, `P(>= 6 points)` is **0.9033** convolved correctly and
  **1.0585** if the per-gameweek values are added -- 17% high, and above 1.0, which is impossible.
  Any multi-gameweek probability must be precomputed from the convolved distribution, never
  derived by a consumer from per-gameweek values. Cost is not a reason to avoid it: convolving all
  599 players over five cumulative horizons takes **0.16 s** in pure Python, and the resulting
  payload is 305 KB of JSON (about 76 KB gzipped) against 819 KB for the raw distributions.
- **Team shots on target faced is measurable from the archive, and its implied save rate
  corroborates the league constant.** Summing `saves + goals_conceded` over a club's goalkeeper
  appearances in a fixture gives a measured team-level shots-on-target-allowed with **100%
  coverage in all five seasons** (mean 4.16 to 4.92 per team-match, sd ~2.4). Its implied league
  save rate is **0.6726 pooled** (0.667 to 0.677 per season) against the independently measured
  67.3% +/- 0.4pp -- so the proxy's semantics are corroborated rather than assumed. This is what
  makes a saves upgrade evaluable with no external data at all.
- **A realised correlation between two outcomes is NOT an upper bound on the predictable
  relationship between them, and this repository has now been caught by that twice.**
  `corr(team shots on target allowed, goals allowed)` is **0.621** over 3,800 team-matches, which
  looks like V1's saves identity (which implicitly assumes 1.0) discarding 61% of the variance.
  Measured on 2025-26's 767 goalkeeper appearances, that variance is almost entirely
  unpredictable: `corr(V1 implied shots faced, actual)` is **0.310**, `corr(V2 directly predicted
  shots faced, actual)` is **0.279** -- V1's rearrangement of its own goal rate is the BETTER
  predictor -- and the two predictions agree with each other at **0.764**, far more than either
  agrees with reality. Both carry under half the spread of the outcome (sd 1.14 and 0.93 against
  2.16). Compare the Stage A recency audit, where a level correction that fixed the level almost
  exactly was worth -0.01%. Do not re-open a modelling question on a realised statistic alone;
  measure the PREDICTIONS against each other and against the outcome first.
- **The V2 blend learns to distrust a signal it cannot see, and the fold record proves it.**
  Across 181 folds the inner-holdout weight on xG rises monotonically with coverage: xG cleared
  the coverage floor in 0 of 30 folds in 2021-22, 6 of 37 in 2022-23 -- where the holdout chose a
  weight of exactly **0.000** -- then all 38 folds in each later season at mean weights 0.362,
  0.579 and 0.645. A candidate whose signal is absent in early seasons is therefore identical to
  its own floor there, so its pooled lift averages over seasons in which it could not differ.
  **Fourth pooled-figure trap in this repository**, after xG coverage, home advantage and the
  Stage A Poisson zero: always split by season before discussing a number.
- **Goalkeeper saves distributions are under-dispersed in both V1 and V2**, at PIT-80 coverage
  0.7604 and 0.7626 against a nominal 0.80 over 3,686 goalkeeper appearances. That is a separate
  defect from where the shot volume comes from, and neither candidate addressed it. Both models
  also truncate at 10 saves; 5 of 3,846 goalkeeper appearances (0.13%) exceed it, identically for
  both, so the comparison is fair but neither can score an 11-save match.
- **Defensive-contribution counts are roughly twice as dispersed as a Poisson, and that
  understates every threshold probability.** Measured over 2025-26 appearances of 60+ minutes,
  variance/mean is **1.88 (DEF, n=3,026), 2.12 (MID, n=3,265), 1.61 (FWD, n=765)** against a
  Poisson's 1.0. The consequence is directional and large: at the same mean, a Poisson gives
  `P(DC >= threshold)` of 0.2180 against an actual **0.2697** for defenders, 0.1019 against
  **0.1792** for midfielders (a 76% under-statement), and 0.0011 against **0.0118** for
  forwards. Any model that reaches a DC threshold probability by evaluating a Poisson at a
  predicted mean will under-predict, worst for midfielders -- which is exactly the slice
  ordering measured for V2 DC. Estimating the threshold probability directly as a frequency,
  as `defensive_contribution_v1` does, avoids this entirely at the cost of resolution.
- **A model can rank far better while scoring worse, and Brier will not tell you which.**
  V2 DC beats V1 on AUC 0.7755 -> 0.8801 overall (forwards 0.630 -> 0.955) and on Brier by
  3.5%, while LOSING mean log score by 2.18% -- because it under-predicts by a factor of 2.5
  (mean predicted 0.0559 against an observed 0.1387). A log score charges `-log(p)` on every
  event at an understated `p`; a bounded quadratic barely notices; AUC is invariant to any
  monotone transform and so sees only the ordering. Report all three, and read a disagreement
  between them as a calibration statement rather than a tie.

## Priorities for upcoming work

The deadline record is closed to reinterpretation. The post-deadline dashboard sequence in
`DEV-ROADMAP.md` has completed through the optional evidence-bound language renderer: contracts,
player/team deep analytics, exact player/team forecast monitoring, and deterministic/optional
summaries landed in that order. The finalized outcome attachment and full schema-v7 republish are
complete. P2.5's historical schema-v8 amendment remains the base; the schema-v9 player-match
identity amendment requires its own atomic republish and in-browser visual verification. Do
not start a new model candidate or tune a known bias as part of this UI work. The numbered items
below remain binding model-history and research guardrails; they are not permission to displace the
active delivery order.

1. Keep `trailing_goals_attack_defence` as the Stage A model. Do not promote any failed
   candidate (V1, V2) and do not reinterpret one after seeing its outer result. Candidate V3
   is development-only **and its single historical development result is INVALIDATED** (one
   leakage defect plus specification/fitting and provenance defects): its number is void for
   comparison, is kept only as an audit record, and must not be tuned again.
2. Candidate V3 was pre-registered and development-evaluated under a separately
   named, committed policy (`dynamic_team_goals_v3`, amendment 1.4) with regression tests, but
   that result is invalidated (see item 1 and `docs/phase1-candidate-v3-invalidation.md`), so
   its boundary selections (slowest learning rate in 153/181 folds, strongest summer
   shrinkage in 92/181) are **void diagnostics**, not evidence. A leakage-safe successor needs
   its own named policy (Candidate V4, amendment 1.5), not a post-hoc tweak of V3. Candidate V4
   has now had its single development evaluation (1.4945, +0.39% lift, not promoted; see
   `docs/phase1-candidate-v4-development.md`) and is left as committed — do not retune its grid,
   priors, estimator, fallback, or thresholds after seeing that result.
3. Any further change to `config/phase1_evaluation.yaml` bumps `contract_version` and adds an
   `amendments:` record; the loader rejects a bump without one. State how many candidates had
   been evaluated. A pre-registered gate may not be amended after a candidate is judged.
   Amendment 1.1 resolved the calibration gate; the deferred stronger check is a PIT
   uniformity test, which remains an owner decision.
4. Fit the team model only after its entry gates pass; do not weaken promotion thresholds after
   observing candidate results. The bar is `trailing_goals_attack_defence` at mean log score
   1.5003 over 181 folds and 3,640 predictions; a candidate needs **1.4853** or better to
   clear the 1% lift gate, and must not lose to that baseline in any reported season.
5. The exact Stage B baselines, metrics, and player-grain `(season, code, fixture)` walk-forward
   harness are implemented and offline-tested under the frozen version 1.0 policy. Additive
   amendment 1.1 pre-registers Candidate V1 `shrunk_trailing_5_player_minutes_v1` without changing
   any version 1.0 comparison rule. The baseline-only full-archive run is **complete as a
   baseline-only development and calibration record** (corrected run, 2026-07-29): 181 folds by
   season 30/37/38/38/38, 133,964
   eligible predictions, zero exclusions, zero leakage, 27/27 runner assertions passed
   (`assertions_all_passed = true`), and a full independent reconciliation with zero validation
   failures (four overall reports, all 20 season-baseline rows, 48 reliability curves / 480 buckets,
   with per-season and per-curve aggregates reconciling to overall). The position prior
   `position_minutes_frequency` is lowest at mean log score 1.04916 (a future 1% aggregate lift
   would need <= about 1.03867) but leads only on mean log score; `trailing_5_player_minutes` leads
   on RPS and both Brier margins, overall and in every season, so no baseline dominates. It is a
   development number under two unversioned historical proxies (target roster, first-kickoff
   cutoff), so real-deadline knowledge-time validity is unproven. The runner assertions assert
   read-only integrity, contract identity, population, and calibration shape only; they do not
   exercise a candidate gate. See `docs/phase2-stage-b-baseline-development.md` and
   `docs/phase2-stage-b-candidate-v1-design.md`. Candidate V1's closed-form estimator, true
   six-observed-gameweek inner walk-forward, dedicated development runner, provenance rechecks, and
   deterministic offline tests are implemented, and Candidate V1 has been development-evaluated
   once on the archive (mean log score 0.74198, +29.28% over the comparator; improves on the best
   baseline value of every metric except the within-position Spearman-p60 starter ranking, where it
   regresses 0.69090 vs 0.70851; all nine development diagnostics pass under contract v1.1; see
   `docs/phase2-stage-b-candidate-v1-development.md`). It is **development-only and not promoted**:
   the historical target roster and first-kickoff cutoff are unversioned proxies, so real-deadline
   knowledge-time validity is unproven, and a second historical evaluation is not permitted. The
   population, target-roster knowledge-time policy, bin shape, baseline definitions, metrics,
   scoring/calibration definitions remain frozen; the historical number is not an upper bound, and a
   gate may never be amended to re-judge a candidate after it is judged. Additive amendment 1.2
   (contract v1.2) tightens the gate for **future** candidates only — best-per-metric guardrails
   (each RPS/Brier guardrail vs the best baseline value of its own metric) plus a new
   `maximum_spearman_p60_relative_regression: 0.0` starter-ranking gate (candidate must rank starters
   at least as well as the best baseline; group-constant candidates fail). It evaluates nothing,
   changes no v1.0/1.1 comparison policy, and does not re-judge V1 (V1 would additionally fail the
   new Spearman gate under 1.2, which does not change its development-only verdict). Additive
   amendment 1.3 (contract v1.3) pre-registers Candidate V2
   `recency_weighted_trailing_player_minutes_v2` (recency-weighted V1; reduces to V1 at decay = 1.0)
   without changing any comparison rule; it is judged by the 1.2 gate. V2 and its development runner
   are implemented and offline-tested, and V2 has now been run **once** as a clean historical
   development run (2026-07-30, against a pristine rebuilt archive): mean log score 0.72625, the best
   of the five models on all four bounded scored metrics (log/RPS/Brier-any/Brier-60+) and an
   improvement on Candidate V1 on all five, but it **fails the v1.2 starter-ranking gate**
   (`maximum_spearman_p60_relative_regression: 0.0`; aggregate Spearman-p60 0.70071 vs the best
   baseline 0.70851, −1.10%; nine of ten diagnostics pass). Recency (`decay < 1.0`) was genuinely
   selected in all 175 selectable folds (modal decay = 0.7, alpha = 1.0). It is development-only and
   not promoted — like V1 it cannot be promoted on historical data (unversioned proxies), the reason
   stated even though four of five scored criteria pass; see
   `docs/phase2-stage-b-candidate-v2-development.md`. V2 is left as committed and is not retuned.
   Additive amendment 1.4 (contract v1.4) pre-registers Candidate V3
   `concentration_adaptive_shrinkage_player_minutes_v3` — V2 with a concentration-adaptive shrinkage
   strength `alpha_eff = alpha*(1 - lambda*C)` (`C` the normalised Herfindahl concentration of the
   weighted trailing history; reduces exactly to V2 at lambda = 0), selected jointly with
   `(decay, alpha)` on the same nested walk-forward, judged by the 1.2 gate unchanged. It is
   diagnosed from V2's by-position evidence (V2's only gate failure is almost entirely goalkeepers,
   0.8153 vs `last_observed` 0.8650). The inner selector still optimises pooled mean log score, NOT
   the ranking metric V3 targets, so the candidate cannot be gamed toward the gate — a pre-registered
   risk recorded in the design doc. V3 and its provenance-guarded development runner are implemented
   and deterministically offline-tested, and V3 has now been run **once** as a clean historical
   development run (2026-07-30, pristine rebuilt archive, four baselines reproduced bit-for-bit):
   mean log score 0.71205, the best of the five models on all four proper scores, but it **fails the
   v1.2 starter-ranking gate** (aggregate Spearman-p60 0.69726 vs the best baseline 0.70851, −1.59%,
   worse than V2). λ > 0 was selected in all 175 selectable folds (modal λ = 0.75), so the
   adaptation was genuinely chosen, but goalkeeper ranking barely moved (0.8153 → 0.8156): the
   hypothesis is refuted — sharpening a concentrated distribution improves every proper score while
   reducing rank resolution. It is development-only and not promoted (unversioned proxies); the
   transferred-player slice also worsens (−23.99% vs comparator, worse than V2's −16.48%). See
   `docs/phase2-stage-b-candidate-v3-development.md`. V3 is left as committed and is not retuned; a
   ranking-targeted successor needs a different structure (e.g. a crisp last-observed component),
   not more shrinkage tuning.
6. Keep archive and live rebuild/capture failure-path tests aligned as schema roles evolve.
7. Phase 3 Stage C attacking Candidate V1 `xg_informed_trailing_player_goals_v1` is
   **development-only and reclassified as a historical xG-signal probe, not production Stage C
   architecture** (independent player Poisson marginals; no Stage A team-goal or Stage B minutes
   input; no team-goal-total allocation or conservation; zero-minute history conflates
   availability/minutes with attack rate; no destination-team/opponent/venue context or transfer
   rescaling). Its single historical development result (mean log score 0.137813, +3.99% over
   `trailing_player_goal_rate_poisson`) is development-only and not a promotion verdict, and is
   **not retuned or rejudged**: the `poisson_pmf` zero-rate-floor audit correction is
   forward-looking, and the historical record stays pinned to its original commit SHA. The valid
   conclusion is narrow — xG beats recent goals where xG is measured on this archive — and
   end-to-end Stage C is unvalidated. The team-coupled successors (Candidate V2 refuted, V3 the
   best attacking candidate but development-only) are now pre-registered and evaluated under
   amendments 1.2/1.3; both are left as committed and are not retuned. The exposure-weighted goals
   V4 and assists V2 successors have each had their single authorized development run (V4 -0.44% vs
   baseline and level with V3; V2 +1.85% vs baseline but -0.11% against the incumbent V1). Both are
   left as committed, are **not retuned**, and may not be re-run or re-judged. A ranking- or
   accuracy-targeted successor needs its own named policy and amendment, not a post-hoc tweak of
   either, and do not extend V1 into that role.
8. The prospective forecasting path (`jobs/prospective_points_v1.py`) and Stage D composer are
   development-only forward tooling, not gated candidates. Two tracks improve them: a
   **prospective-forecast track** using live-snapshot fields (prices `now_cost`, penalty/set-piece
   order, per-player xG, ownership) that improves the GW-horizon board directly with **no historical
   gate**, all measured before wiring; and a heavier **historical track** (new pre-registered Stage
   A/B/C candidates) needed only to claim measured lift. Shipped on the prospective track so far:
   penalty/set-piece premium, xG-share (embedding the penalty premium) and coupled xA-share for
   assists, the season-boundary appearance correction, the **equal-weighted trailing-5
   appearance window** replacing the recency-weighted estimate at the boundary, and the
   **shrunk trailing-5 minute-bin estimate** (`models/minutes_shrinkage.py`) replacing the raw
   `counts / n`, which took PIT-80 from 0.74538 to 0.79985 against a nominal 0.80. Its `alpha` was
   selected on 2021-22..2024-25 with 2025-26 held out and **must not be re-tuned against GW29-38**;
   the residual +2.0% appearance over-prediction on the target-roster population needs a fresh
   out-of-sample window, not a re-fit. Latest is the (owner rule, 2026-08-17)
   **trailing-history eligibility rule**: every per-player trailing signal (minutes window,
   prior-season appearance rate, xG/xA share signals, ICT bonus proxies) reads only rows from
   the most recent archived season or rows recorded at the player's CURRENT club — older rows at
   a former club are dropped and such a player is a flagged cold start. Measured instance that
   forced it: a 2023-24 ever-present whose 2026-27 club he joined from outside the PL read as a
   0.93-ever-present nailed starter with a 22% creator share (19.7 GW1-5 xP, 22nd of 587); under
   the rule he is a cold start at 14.75 (95th). The rule is applied by the prospective job only;
   the frozen Phase 4 EV backtest adapter keeps the unfiltered semantics of its immutable run.
   A whole-composer
   recency audit is complete: appearance was the only recency-weighted signal (now fixed); xG-share,
   xA-share, the DC hit rate, and the pooled GK save rate are equal-weighted or league-pooled and
   were confirmed correct as-is. All three composer repairs have now been confirmed on a second,
   disjoint window (2025-26 GW10-28, 191 fixtures, 14,959 rows): PIT-80 lands at **0.79878** against
   the nominal 0.80 there, so the calibration repair generalises, and the appearance residual is
   confirmed persistent at +2.6%. That same run makes the **Stage A team-goals recency/time-decay
   audit the next accuracy item on evidence**: Stage A expects ~2.86 goals per fixture in both
   windows while reality delivers 2.712 and 2.576, so the goals residual is a season-level miss
   rather than the 99-fixture fluke previously recorded (see
   `docs/phase4-composer-out-of-window-validation.md`). **That audit has since been run and closed
   negative** -- blending the league level toward the season to date is worth -0.01% at the Stage A
   grain and +0.00% CRPS at the composer grain, because lowering the level trades goals accuracy
   against clean-sheet accuracy one for one; do not re-open it (`docs/phase4-stage-a-recency-audit.md`).
   What the audit surfaced instead is the **next accuracy item on evidence**: the composer's bias is
   **positional, not global**, and stable across both windows: GK +5.9%/+3.5%, DEF +5.3%/+3.7%,
   MID +2.4%/+4.0%, FWD **-3.1%/-4.1%** (GW10-28 / GW29-38, unmodelled negatives added back so the
   comparison is like for like). **The clean-sheet attribution first recorded for it is retracted**
   -- the clean sheet runs -0.4% on GW29-38 while GK/DEF are still +3.5%/+3.7% there, so it cannot
   be the cause. Three explanations were tested and rejected: bin-2 clean-sheet thinning is real
   but worth ~15 points (conditional on the team conceding once, a 60-89 player keeps the clean
   sheet 0.1408 of the time against thinning's 0.1870, because a defender withdrawn then is
   disproportionately one whose side had already conceded); the Stage A Poisson zero looked +7.4%
   too high pooled but **the whole effect is 2023-24** (train z = +2.72, 2025-26 holdout
   z = **+0.32**), so no zero correction ships; and `P(60+)` is calibrated to +1.9%. **The
   confirmed defect is positional mis-allocation of attacking output**: forwards get **38-40% too
   few assists in both windows** (model share 7-8% against an actual 11-15%), defenders get
   **+29%/+61% too many goals** and +12%/+28% too many assists, and goalkeepers are allocated
   1.0-1.6 goals against an actual zero. A defender's goal scores 6 against a forward's 4, so this
   mis-ranks positions and inflates the total at once, and it connects to the measured constant
   that the defender attacking signal is xA, not xG. See `docs/phase4-composer-positional-bias.md`.
   The price-informed
   starter prior in the appearance layer is now **built** (`models/price_starter_prior.py`,
   cold starts only, held-out MAE 0.3835 -> 0.3086, t = -5.57); what remains open there is the
   ownership term, whose confirmation window is 2026/27 GW2 onward. The Stage E squad
   optimiser and its stable prospective-points input artifact are now implemented
   **development-only**. The fixed-squad ILP is exact; the multi-GW transfer search is bounded and
   makes no global-optimality claim. The confirmed no-transfer pruning defect is fixed: the current
   squad is always reserved in every successor set, with dense and end-to-end regression coverage.
   The immutable optimizer artifact is implemented with independent Git/worktree, squad-config,
   search-policy, solver, and decision provenance plus concurrent no-clobber publication. Use it for
   both deadline paths and complete the sequential runbook rehearsal before the owner decision.
   Apply the next-round
   availability overlay to GW1 only in the decision view; any later-GW reuse is an explicit scenario
   assumption until measured. State that future prices and selling values are static/unknown. The
   contract-1.2 Stage D EV
   walk-forward backtest has had its one archive run (`results/ev_backtest_2025_26_gw29_38.json`);
   it is immutable and is not re-run. Its result -- the V1 comparator outscoring the V3/coupled
   primary on every scored metric, the primary winning only aggregate calibration -- is a
   development diagnostic and explicitly **not** grounds to change the prospective default.
   Diagnosing it is legitimate follow-up work; reinterpreting it as a promotion verdict is not.
   Prospective changes must stay point-in-time safe and must not silently re-run or re-judge any
   frozen historical evaluation.
9. The append-only player-gameweek/player-fixture/team-fixture prediction ledger, reciprocal team-
   outcome attachment, player-outcome ingestion, BI semantic contract version 6, the ten
   established dashboard files at schema version 9, the two separate provisional files at schema
   version 1, atomic static dashboard read models, and dashboard are implemented development-only.
   Player monitoring scores a gameweek only when the official gameweek and every forecast fixture
   leg are final, so a partial double gameweek produces zero scored player observations. Team attack
   CRPS uses the team's exact stored goals-for PMF; defence CRPS uses the opponent's exact stored PMF,
   never a distribution reconstructed from lambda. The current nine read-only analytic/decision
   routes are separate from Plan Builder and Squad Draft. Plan Builder supports both fresh custom
   squads and a private, immutable manager-team capture path for transfer planning. Squad Draft
   supports manual selection plus an explicitly imported private manager capture, ignores the
   standard budget while retaining roster shape and club caps, and never relabels that capture as
   optimizer output. Retain both player-fixture and player-gameweek predictions for every pre-deadline run,
   never overwrite a vintage, and join actual outcomes only after finalisation.
   The decision layer supports exact cumulative player endpoints from the run's fixed start: xP,
   inclusive `P(points <= 2)`, and inclusive `P(points >= 2/4/6/10/15)`. Expected points may be
   summed; probabilities must be convolved in the Python emitter under the versioned independent-
   gameweek assumption and are raw/unadjusted for the next-round availability overlay. A shifted
   start or venue filter suppresses the probability display rather than conditioning it. The bulk
   wire payload uses a versioned positional field dictionary and six-decimal emitter quantization
   only after full-precision validation; exact zero/one probability boundaries stay exact. It never
   carries raw PMFs; any future CCDF uses a small precomputed lazy shard. The decision layer also
   supports fixture difficulty split into overall, attack, and defence; player form (minutes,
   starts, xG, xA, goals, assists, bonus/BPS, DC, points); direct-value player/team Pareto
   analytics; separately published player/team prediction-versus-actual observations and
   calibration; and optimiser-plan audits. Deterministic summaries on all eleven routes and the
   optional evidence-bound renderer on the seven public analytical routes are implemented
   development-only. Preserve the primitive measures and publish any composite
   difficulty score only with a versioned formula and direction. Export a pivot-friendly star schema
   atomically; BI consumers never query the mutable production DuckDB.
   Analytics may call the nondominated set an efficient frontier and let a user tighten the chart's
   horizontal viewport or display only those members, but classification stays over the complete
   filtered eligible set and the exact table/insight packet stays unchanged. This is direct-value
   Pareto geometry, not a Markowitz mean-variance or Sharpe portfolio frontier; any constrained
   portfolio analysis needs backend-published joint dependence plus the FPL squad rules.
   Past-vs-future observed form is the latest snapshot at static export and may post-date an older
   selected forecast. Label it as non-vintage-aligned reporting context and show each row's
   `(season, as_at_gw)` anchor; never describe it as state known at the forecast `as_of` or use it
   as point-in-time model evidence.

10. The V2 football-first architecture is implemented **development-only** and promotes nothing.
    `trailing_goals_attack_defence` remains the Stage A model and `gk_saves_v1` remains the
    composer's saves component. Both V2 candidates failed their pre-registered gates and are left
    as committed: **do not retune either**, and do not re-run or re-judge
    `results/v2_team_environment_development.json`. A successor needs its own named policy and
    its own amendment, not a post-hoc tweak. The V2 team engine is deliberately NOT wired into
    `jobs/prospective_points_v1.py`; `jobs/prospective_environment_v2.py` produces the football
    forecast for analysis instead, so no decision path consumes an ungated candidate.
11. Real `pl_sdp` data now exists. The first isolated successor
    `retrospective_real_sot_team_environment_v1` has completed its single clean outer evaluation
    and is **INCONCLUSIVE**, not promoted: on 2,280 team-sides / 114 folds, REAL SOT improves mean
    log score only 0.0374% beyond the exact goals+xG control (1.489436 to 1.488879), versus the
    frozen 1% bar. CRPS improves 0.0833% and PIT-80 is unchanged, but log score regresses slightly
    in 2024-25 and 2025-26. Zero SOT weight was selected in 72/114 folds; the main effect is mild
    prediction shrinkage. The result does not justify a territory/box-touch rung. The separate
    validation-only `RetrospectiveBackfillView` retains original September 2026 capture identities
    and applies `source_match_kickoff < prediction_as_of`; it is not a mode of `PointInTimeView`.
    Production, prospective, dashboard, optimizer, and promotion evidence continue to require
    `known_at <= as_of`. See `docs/v2-real-sot-development.md`. Never rerun or reinterpret this
    result, zero-fill absent SOT, or describe retrospective evidence as historical deadline proof.

12. The V2 defensive-contribution candidate `team_environment_share_dc_threshold_v2` has had
    its single development evaluation (`docs/v2-dc-development.md`,
    `results/v2_dc_development.json`) and is **not promoted**: it misses the primary metric by
    -2.18%. Its pre-registered mechanism test nonetheless PASSES -- the transferred-player
    slice improves +11.42% log, +12.46% Brier, AUC 0.770 -> 0.923 -- so the failure is located
    in the Poisson threshold conversion, not in the team-environment allocation. Leave it as
    committed and **do not swap the count distribution after the fact**: an over-dispersed
    successor needs its own named candidate and its own amendment, and its dispersion parameter
    must be fitted inside each fold rather than taken from the measured constant above, which
    was measured on the evaluation population and would be leakage.

## Sub-agent coordination and handoff

- Give each sub-agent a bounded, non-overlapping scope and name the files it may edit.
- A review-only sub-agent must not edit files. An implementation sub-agent must not commit,
  discard, or rewrite another agent's changes.
- Shared schema/config changes need one owner; other agents should report proposed impacts
  instead of editing the same files concurrently.
- Report findings in severity order with file and line evidence. Distinguish confirmed defects,
  design gaps, and optional improvements.
- Handoffs must list changed files, checks run and their results, unresolved assumptions, and
  any data or network-dependent validation that was not possible.

## Skill routing

Use the smallest relevant skill when it materially helps. Repository-specific skills are:

- `$guard-fpl-point-in-time` at `.claude/skills/guard-fpl-point-in-time/SKILL.md` for feature and
  backtest leakage.
- `$verify-fpl-scoring-rules` at `.claude/skills/verify-fpl-scoring-rules/SKILL.md` for scoring config,
  payload verification, and replay coverage.
- `$validate-fpl-walk-forward` at `.claude/skills/validate-fpl-walk-forward/SKILL.md` for Phase 1+
  model evaluation and promotion gates.
- `$audit-fpl-live-snapshots` at `.claude/skills/audit-fpl-live-snapshots/SKILL.md` for live capture,
  rollover, freshness, atomicity, and snapshot ingestion.

Installed general-purpose skills that complement them are:

- `data-analytics:analyze-data-quality` for source drift, null semantics, anomaly policy, grain,
  completeness, and crosswalk work.
- `data-analytics:validate-data` before promoting a ruleset, data pipeline, or model result as
  ready to share or use.
- `data-analytics:jupyter-notebooks` for reproducible model experiments or exploratory SQL/Python
  that should become an auditable notebook.
- `data-analytics:design-kpis` for phase gates, model success criteria, operational freshness,
  and dashboard KPIs.
- `data-analytics:create-data-context` for the prediction-ledger/BI semantic layer, canonical
  grains, metric ownership, and source-of-truth documentation.
- `data-analytics:metric-diagnostics` for explaining changes in model or data-quality metrics.
- `data-analytics:visualize-data` for calibration, reliability, distribution, and backtest
  figures.
- `data-analytics:build-report` for a durable model-validation or season-review report.
- `data-analytics:build-dashboard` only when implementing or materially revising the dashboard.
- `github:gh-fix-ci` when diagnosing or repairing failing GitHub Actions checks after CI exists.

Skills do not override the repository invariants, offline-test policy, or explicit user scope.
