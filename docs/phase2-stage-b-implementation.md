# Phase 2 Stage B (player minutes) harness — implementation decision record

**Status: implementation record for the Stage B walk-forward harness. No model has been fit and
no candidate has been judged.** A **baseline-only** full-archive run has now been completed
(2026-07-29) under contract `1.0`; it is a **headline/provisional development baseline**, not a
promotion verdict — see [`phase2-stage-b-baseline-development.md`](phase2-stage-b-baseline-development.md).
This document pins the owner decisions the harness (`src/fpl/validate/minutes_harness.py`) bakes in.
It does **not** change `config/phase2_evaluation.yaml`: the contract stays at version `1.0`
because **zero Stage B candidates precede these decisions**, and the frozen baseline names,
metrics, gates, and dimensions are unchanged. The machine-readable contract and
`docs/phase2-evaluation-contract.md` remain the single source of truth; this file explains the
implementation choices that follow from them, not new policy.

The historical number this harness will eventually produce is a development number on the local
archive. It is **not** an upper bound of any kind. Calling it one would misrepresent a
seen-archive development result as a ceiling on future performance.

## Scope of this slice

This slice implements the **player-grain `(season, code, fixture)` walk-forward harness** under
contract 1.0 and the **four frozen baselines' fold-local fit/predict loop**. It:

- enumerates observed `(season, gw)` folds from `mart_fact_player_fixture` (minutes-not-null);
- builds a fold-local `TeamCodeMap` from `mart_dim_team` only;
- queries training history and prediction targets, splitting the minutes label from the exact
  nine-column `TargetRow` before any baseline sees a row;
- validates inputs (`validate_minutes_inputs`), fits and refits all four baselines inside every
  fold, and predicts every eligible target on identical rows;
- derives fold-local, point-in-time-safe `transfer_status`, `player_history_cohort`, and
  cold-start flags from prior history only;
- scores every baseline with `score_minutes_predictions` under the contract, sliced across all
  six frozen reporting dimensions, and returns a frozen result.

It does **not** fit a candidate, execute a promotion gate, run a Monte Carlo, or touch live
registry/availability. Candidate and gate execution are **explicitly deferred**: the harness
returns baselines-only and no Stage B model is fitted. A separate, separately-named change will
add candidate/gate evaluation once a candidate exists.

## Pinned owner decisions

These decisions resolve implementation ambiguity in the contract. Each is fixed here, in code,
and in tests **before any result exists**, so a later candidate cannot reinterpret one after
seeing its score.

### 1. `transfer_status` is fold-local and point-in-time-safe

A target row is classified by comparing its club to the player's **most recent PRIOR
player-fixture row's club**, never to `mart_dim_player.team_id`, `mart_dim_player_stint`, or any
row at/after the cutoff. Both clubs are resolved from the **fact row's season-qualified
`team_id`** to the stable `team_code` through the fold-local `TeamCodeMap` (never a bare
`team_id` join across seasons). The three values are exactly:

- `no_prior_player_fixture` — the `code` has no prior history row before the cutoff;
- `same_team_code_as_last_observed_fixture` — the target `team_code` equals the most recent
  prior row's `team_code`;
- `changed_team_code_since_last_observed_fixture` — they differ (a transfer, or a `team_id`
  reuse that resolves to a different club).

`changed` therefore catches both a genuine transfer and the team-id-recurrence failure mode
(id 10 is club 1410 one season and club 2020 the next): the comparison is in `team_code`, so a
reused id that maps to a different club is correctly reported as a change.

### 2. `player_history_cohort` and cold start

Each target is placed in exactly one history cohort, derived from its `code`'s prior rows only:

- `no_prior_player_fixture` — no prior row;
- `prior_player_fixtures_no_positive_minutes` — prior rows exist but none has `minutes > 0`;
- `prior_positive_minutes` — at least one prior row has `minutes > 0`.

`cold_start = True` for the first two cohorts and `False` for `prior_positive_minutes`. This is
a per-row, baseline-independent flag: a cold-start row is one whose player-level signal is
unavailable, and the same flag is reported for every baseline on that row. It matches the
contract's `cold_start_policy: every_eligible_row_receives_fallback_distribution` — the row is
never dropped, only reported.

### 3. Uncertainty

`uncertainty` is the **standard error of the row log scores**, the same meaning Phase 1 carries
(`mean_log_score_standard_error` on `MinutesScoreReport`). It is reported wherever a scored
population is.

### 4. The p60 ranking observation

`spearman_p60_within_position_gameweek` ranks the predicted `P(minutes >= 60)` margin against the
**binary observation `observed minutes >= 60`**, within a `(season, gw, position)` group. The
rank group key is `f"{season}-{gw}-{position}"`. (The scoring slice already turns the observed
bin into the `>= 60` binary; the harness supplies the group key.)

### 5. Reliability buckets are always emitted in full

Every reliability curve carries **all ten buckets**, including empty ones, and an empty bucket
carries `n = 0` with `mean_predicted = observed_rate = None` (never a fabricated zero). This is
already enforced by the metrics slice; the harness does not truncate or filter buckets.

### 6. A completed team fixture (for the team baseline)

A distinct history fixture for the team baseline is a **distinct `(season, fixture)` with an
eligible (non-NULL minutes) player row whose `kickoff_time < as_of`**. The team baseline selects
the club's five most recent such distinct fixtures and then takes all prior eligible player rows
at the target position in those fixtures. (Implemented in `minutes_baselines.py`; restated here so
"completed fixture" is not silently re-derived.)

### 7. Target roster is an acknowledged unversioned proxy

The historical target roster is the **archive proxy projected from the target rows** — an
acknowledged unversioned-at-real-deadline limitation, identical in kind to the schedule-cutoff
limitation. The model-facing `TargetRow` is the **exact nine-column safe projection**
(`{season, gw, fixture, kickoff_time, code, position, team_id, opponent_team_id, was_home}`);
the `minutes` label is held **separately** and never reaches a baseline through the target
record. Live registry/availability selection (`known_at <= as_of`) remains out of scope here and
is a prospective concern.

### 8. No invented terminal fallback

There is **no invented uniform terminal fallback**. If the all-position prior is empty (no
eligible history rows at all), `PositionPrior.distribution_for` **fails closed** rather than
inventing a uniform distribution. This is the only legitimate behaviour in a fold that somehow
has no training data: it is a configuration error, not a prediction.

## Walk-forward construction

- **Observed gameweeks** are enumerated from `SELECT DISTINCT (season, gw)` on
  `mart_fact_player_fixture` where `minutes IS NOT NULL`, ordered by season then gw. The harness
  never assumes `range(1, 39)`; 2022-23 has no GW7.
- **Expanding warmup** of `minimum_observed_gameweeks` (pinned to 8) is counted **across
  seasons**, not within them — the same fix Phase 1 made. Only the earliest season loses
  gameweeks; every later season starts scoring from its GW1. Counting within a season would drop
  every season's cold-start opening, which is exactly the regime the minutes fallback exists for.
- **`as_of`** is the **first kickoff across every player row** in the predicted gameweek,
  including a row whose outcome is NULL — the latest proxy that still excludes every outcome
  from that gameweek under a strict `kickoff_time < as_of`. Eligibility remains
  `minutes IS NOT NULL`; it cannot move the cutoff later. The cutoff is
  timezone-aware UTC (read through the Arrow/Polars path, never DuckDB's pytz-dependent
  TIMESTAMPTZ conversion).
- **Leakage assertion**: `assert_no_minutes_leakage` requires that **no predicted-GW player row
  has `kickoff_time < as_of`**. Because `as_of` is the GW's minimum kickoff, this holds by
  construction; the assertion exists to fail loudly if a fold is ever mis-built.
- **Archive expectation (confirmed by the baseline run)**: 189 observed gameweeks minus 8
  warmup = **181 folds** (by season 30/37/38/38/38), 133,964 eligible predictions, zero
  exclusions, zero leakage failures. The headline development bar and the post-processing caveat
  are recorded in
  [`phase2-stage-b-baseline-development.md`](phase2-stage-b-baseline-development.md).

## Training and target queries

- **Training**: every `mart_fact_player_fixture` row with `minutes IS NOT NULL` and
  `kickoff_time < as_of` — **including zero-minute rows** (the single most load-bearing mass).
  Ordered deterministically (`kickoff_time, season, fixture, code`).
- **Target**: every row of the predicted observed gameweek with `minutes IS NOT NULL`, ordered
  deterministically (`kickoff_time, fixture, code`). Double-gameweek fixtures are **separate**
  rows at distinct `fixture` values and stay separate.
- **Identity**: positions are converted through `Position.from_archive_label` (canonicalises
  `GKP` and rejects the manager element); `code` is the stable cross-season key; grain is exactly
  `(season, code, fixture)`.
- The minutes label is split from the nine-field `TargetRow` **before** the baselines see rows;
  `validate_minutes_inputs` then checks grain uniqueness, the strict cutoff, NULL/range minutes,
  valid `Position`, and that every `(season, team_id)` resolves to a `team_code`.

## Result shape

`run_minutes_harness` returns a frozen `MinutesHarnessResult` carrying: `overall` and the six
slice dimensions (`by_fold`, `by_season`, `by_position`, `by_home_away`, `by_transfer_status`,
`by_player_history_cohort`); `folds_by_season`; the required baseline set; eligibility and
prediction coverage, with eligibility counted independently when folds are generated;
`leakage_failures = 0`; and `best_baseline()` (lowest mean log score among
the required baselines). Every slice is scored with `score_minutes_predictions`, so each carries
the required counts, uncertainty, and calibration diagnostics.

`run_minutes_harness(con, *, config=None, seasons=None)` supports optional evaluation-season
filtering that **restricts folds only, never the prior training history** behind them. It is
baselines-only; candidate/gate execution is deferred.
