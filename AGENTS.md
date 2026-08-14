# Repository agent instructions

These instructions apply to the entire repository and to every agent or sub-agent working in
it. More specific `AGENTS.md` files may add local guidance, but they must not weaken the data
correctness rules below.

## Mission and current state

This project predicts a full Fantasy Premier League (FPL) points distribution per player and
gameweek. It is a Python 3.12 data and modelling codebase built around DuckDB, Polars, Pydantic,
HTTPX, YAML configuration, pytest, Ruff, and strict mypy.

### Active delivery objective (2026-08-13)

`DEV-ROADMAP.md` is the canonical near-term execution order through the 2026/27 GW1 deadline at
`2026-08-21T17:30:00Z` (`2026-08-22 00:30` Asia/Bangkok). It has two ordered owner goals:

1. deliver an auditable legal GW1 squad, XI, captain, vice-captain, and bench before the deadline;
2. then deliver the versioned BI semantic export and decision dashboard for fixture difficulty and
   player form.

Until the deadline, P0 in `DEV-ROADMAP.md` outranks new model research. Freeze the current
prospective defaults, do not tune individual players or reopen frozen evaluations, and complete the
optimizer artifact/provenance contract, deadline rehearsal, immutable forecast recording, and final
decision comparison first. This file remains authoritative for correctness, model history, and
working protocol; the roadmap owns delivery sequence and acceptance criteria.

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
bench, transfer, horizon, and aggregate legality. Two operational gaps remain:
`chance_of_playing_next_round` is repeated across the whole horizon, and future transfers use the
deadline's static prices with no price-change or selling-value model. The append-only prediction
ledger is implemented in `src/fpl/storage/ledger.py` and records immutable player-gameweek forecast
vintages from the JSONL artifact, with outcomes held separately. It still lacks player-fixture
forecast distributions, the finalized-outcome ingestion job, and the BI read/export layer. See
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
append-only player-gameweek prediction ledger is implemented development-only. Its player-fixture
forecast extension, finalized-outcome ingestion job, BI semantic export, static publish boundary,
and dashboard remain open. `DEV-ROADMAP.md` is the canonical delivery order for those items and the
GW1 decision pack; the prospective artifact and Stage E optimizer immediately upstream are
implemented development-only.

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

## Repository map and boundaries

- `config/`: sources, scoring rules, and declarative data-quality policy.
- `src/fpl/ingest/`: external archive/API boundaries and raw payload handling.
- `src/fpl/storage/`: DuckDB connection policy, schema, and append-only prediction ledger.
- `src/fpl/transform/`: raw-to-staging crosswalks, validation, facts, and targets.
- `src/fpl/features/`: point-in-time-safe read API and, later, feature construction.
- `src/fpl/validate/`: walk-forward folds, proper scoring rules, Stage A baselines, harness.
  It reads outcomes, which the feature layer may not -- scoring a prediction needs the label.
- `src/fpl/models/`: scoring, the Stage A team-goals models, Stage B minutes candidates, and
  Stage C attacking-goals baselines/probes.
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
   points and points replayed under `scoring_2026_27` must remain separately named.
10. Internal marts or a ledger may use DuckDB, but BI, dashboard, and public consumers receive an
    atomic read-only export (prefer pivot-friendly Parquet plus versioned application JSON). They
    never query the mutable production database.

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

## Priorities for upcoming work

Through the GW1 deadline, execute P0 in `DEV-ROADMAP.md` before every item below: durable optimizer
artifact/provenance, sequential deadline runbook, rehearsal, immutable primary and diagnostic
forecast recording, and the final decision comparison. Do not start a new model candidate or tune a
known bias before the owner has a safe GW1 team. After P0 is rehearsed, execute the roadmap's BI
semantic/export work before dashboard UI. The numbered items below remain binding model-history and
research guardrails; they are not permission to displace the active delivery order.

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
   appearance window** replacing the recency-weighted estimate at the boundary, and (latest) the
   **shrunk trailing-5 minute-bin estimate** (`models/minutes_shrinkage.py`) replacing the raw
   `counts / n`, which took PIT-80 from 0.74538 to 0.79985 against a nominal 0.80. Its `alpha` was
   selected on 2021-22..2024-25 with 2025-26 held out and **must not be re-tuned against GW29-38**;
   the residual +2.0% appearance over-prediction on the target-roster population needs a fresh
   out-of-sample window, not a re-fit. A whole-composer
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
   Also still open and
   measured-but-not-yet-built: a price-informed starter prior in the appearance layer. The Stage E squad
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
9. The append-only player-gameweek prediction ledger is implemented. Next extend its contract for
   **player-fixture forecasts**, build finalized-outcome ingestion, and build the **BI semantic
   export before dashboard UI**. Retain both player-fixture and player-gameweek predictions for
   every pre-deadline run, never overwrite a vintage, and join actual outcomes only after
   finalisation.
   The decision layer should support: upcoming 1/3/5-GW player EV and risk; fixture difficulty split
   into overall, attack, and defence; actual-versus-predicted player and team performance; player
   form (minutes, starts, xG, xA, goals, assists, bonus/BPS, DC, points); calibration by position and
   horizon; and optimiser-plan audits. Preserve the primitive measures and publish any composite
   difficulty score only with a versioned formula and direction. Export a pivot-friendly star schema
   atomically; BI consumers never query the mutable production DuckDB.

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
