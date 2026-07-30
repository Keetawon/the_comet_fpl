# Repository agent instructions

These instructions apply to the entire repository and to every agent or sub-agent working in
it. More specific `AGENTS.md` files may add local guidance, but they must not weaken the data
correctness rules below.

## Mission and current state

This project predicts a full Fantasy Premier League (FPL) points distribution per player and
gameweek. It is a Python 3.12 data and modelling codebase built around DuckDB, Polars, Pydantic,
HTTPX, YAML configuration, pytest, Ruff, and strict mypy.

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
`docs/phase2-stage-b-candidate-v2-development.md`.
The official 2026/27 payload confirms 17 scoring fields; captured official rule sources confirm
the seven thresholds/units absent from it. Two replay edge cases remain explicitly unexercised.
Do not describe the ruleset as fully validated while either remains under
`verification.unverified`.

Full archive rebuilds are failure-atomic: `build_db` rebuilds a sibling DuckDB, preserves
existing live snapshot state, refuses to overwrite a concurrently changed target, and promotes
with one atomic replacement only after success.

`README.md` is the best current overview. Treat `docs/phase0-design.md` as a mixed historical
design/as-built audit: its opening status and pre-implementation decisions are stale. The
publish boundary is a design contract and is not implemented.

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
- `src/fpl/storage/`: DuckDB connection policy and schema.
- `src/fpl/transform/`: raw-to-staging crosswalks, validation, facts, and targets.
- `src/fpl/features/`: point-in-time-safe read API and, later, feature construction.
- `src/fpl/validate/`: walk-forward folds, proper scoring rules, Stage A baselines, harness.
  It reads outcomes, which the feature layer may not -- scoring a prediction needs the label.
- `src/fpl/models/`: scoring, the Stage A team-goals models, and the offline-tested Stage B
  Candidate V1 estimator.
- `src/fpl/jobs/`: thin orchestration/CLI entry points.
- `tests/`: executable data contracts; vendored API fixtures keep tests offline.
- `docs/`: design records and the future static publish contract.

Keep network clients, transformation logic, feature access, statistical models, orchestration,
and presentation contracts separated. Jobs should coordinate domain functions rather than
accumulating business logic. Nothing downstream of the future `publish` boundary may query
DuckDB.

## Working protocol

1. Read `README.md`, the relevant config, implementation, and tests before changing a
   contract. Inspect `git status --short` and preserve unrelated or user-owned changes.
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

## Priorities for upcoming work

Unless the user sets another priority, address prerequisites before model sophistication:

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
6. Keep archive and live rebuild/capture failure-path tests aligned as schema roles evolve.

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
- `data-analytics:metric-diagnostics` for explaining changes in model or data-quality metrics.
- `data-analytics:visualize-data` for calibration, reliability, distribution, and backtest
  figures.
- `data-analytics:build-report` for a durable model-validation or season-review report.
- `data-analytics:build-dashboard` only when implementing or materially revising the dashboard.
- `github:gh-fix-ci` when diagnosing or repairing failing GitHub Actions checks after CI exists.

Skills do not override the repository invariants, offline-test policy, or explicit user scope.
