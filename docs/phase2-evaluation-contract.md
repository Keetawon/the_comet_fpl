# Phase 2 evaluation contract (Stage B player minutes)

**Status: contract and typed loader implemented at version 1.2.** Version 1.0 froze the
population, baselines, metrics, calibration, and promotion gate before any candidate existed.
Additive amendment 1.1 pre-registers Candidate V1
`shrunk_trailing_5_player_minutes_v1`; it changes none of those version 1.0 policies. Amendment
1.2 tightens the guardrails and adds a starter-ranking gate for **future** candidates only — it
evaluates nothing, changes no version 1.0 / 1.1 population/baseline/metric/calibration policy, and
does not re-judge V1. Candidate V1 and its provenance-guarded development runner are implemented
and deterministically offline-tested. The runner has been executed **once** as a clean historical
development run; the result is recorded in
[`phase2-stage-b-candidate-v1-development.md`](phase2-stage-b-candidate-v1-development.md) and is
**development-only — not a promotion verdict or a gate execution** (the historical target roster
and first-kickoff cutoff are unversioned proxies). The machine-readable source is
`config/phase2_evaluation.yaml`, validated by `Phase2EvaluationConfig` in `src/fpl/config.py`
and loaded by `load_phase2_evaluation`, which cross-checks the 60-minute bin boundary against
the configured downstream ruleset at load time. This document explains the decisions; it does
not override that file. It is a pre-registration: the population, grain, identity policy, bin
shape, baselines, metrics, and gate values frozen here are what every later Stage B candidate
is judged against.

**The completed baseline-only historical number is a development number on the local archive.
It is NOT an upper bound of any kind.** Calling it one would misrepresent a seen-archive
development result as a ceiling on future performance.

## Scope

Phase 2 Stage B predicts a **four-bin probability distribution for player minutes** at stable
`(season, code, fixture)` grain. It does not predict team goals (Stage A), per-minute event
rates (a separate rate-model stage under R6), or FPL points (a later stage that applies the
target season's scoring rules). Stage B is a **closed-form marginal** over the four bins;
Monte Carlo is explicitly out of scope here and the minutes model stays separate from
per-minute event/rate models (repository rule R6).

Candidate V1 has been development-evaluated **once** on the archive (development-only, not
promoted; see
[`phase2-stage-b-candidate-v1-development.md`](phase2-stage-b-candidate-v1-development.md)).
No candidate has been **promoted** under this contract. The four Stage B
baselines, metrics, baselines-only walk-forward harness, Candidate V1 estimator, and separately
named Candidate V1 development runner are implemented and offline-tested. The corrected
baseline-only archive run is recorded in
`phase2-stage-b-baseline-development.md`.

## Amendment 1.1: Candidate V1 design only

Amendment 1.1 was recorded on 2026-07-29 with **zero candidates evaluated before the
amendment**. The completed version 1.0 run evaluated only the four required baselines and is not
a candidate evaluation. The amendment adds one required, separately named policy block and no
new tolerance or comparison rule.

Candidate V1 combines the two signals exposed by the baseline record. For bin `k`, its frozen
closed-form hypothesis is:

```text
p_k(alpha) = (c_k + alpha * q_k) / (n + alpha)
```

Here `c_k` is the player's bin count over up to five most recent prior player-fixture rows,
`n` is their total, and `q_k` is the fold-local raw current-position prior. Only `alpha` is
selected, from the exact grid `[1, 2, 5, 10, 20]`, by a six-observed-gameweek nested
walk-forward with at least eight earlier gameweeks; insufficient inner history uses `alpha =
5`. No player history returns exactly the position prior. There is no extra smoothing, no
availability feature, no fixture-specific feature, and no Monte Carlo.

The full formula, point-in-time argument, double-gameweek policy, frozen grid, test plan, and
future runner provenance requirements are in
[`phase2-stage-b-candidate-v1-design.md`](phase2-stage-b-candidate-v1-design.md). At registration,
the amendment authorized no evaluation and preceded implementation. The exact estimator and
separately named runner/provenance slice now exist with deterministic offline tests. One clean
historical development run may occur only after explicit authorization; none exists yet.

## Amendment 1.2: tighter guardrails + a starter-ranking gate (future candidates only)

Amendment 1.2 was recorded on 2026-07-30 with **one candidate evaluated before the amendment**
(Candidate V1, development-only). It changes no version 1.0 / 1.1 population, roster, bin,
baseline, metric, or calibration policy. It makes the promotion gate **strictly harder** for
candidates judged after it, in two ways, and adds nothing a candidate can hide behind:

1. **Best-per-metric guardrails.** Each bounded non-regression guardrail (RPS, Brier-any,
   Brier-60+) is compared against the **best (lowest) value of that metric across the required
   baselines**, not the single best-by-log-score baseline. Candidate V1's development run exposed
   that `position_minutes_frequency` is the best-by-log-score baseline yet the **worst** on RPS and
   both Brier margins, so the old single-comparator bar was the easiest possible. The primary
   mean-log-score lift and the per-season log no-regression rule still compare against the
   best-by-log-score baseline (unchanged). The semantics are pinned in the contract as
   `guardrail_comparison: best_baseline_per_metric`.
2. **New starter-ranking gate.** `maximum_spearman_p60_relative_regression: 0.0` (pinned): the
   candidate's aggregate `spearman_p60_within_position_gameweek` must be **>= the best (highest)
   baseline Spearman**. The minutes model's whole purpose is to rank who starts and plays 60+,
   which is exactly that metric. `position_minutes_frequency` emits undefined (null) Spearman
   (group-constant prediction) and is **excluded** from the baseline max; a candidate whose own
   Spearman is undefined **fails** the gate, because a group-constant prediction cannot rank
   starters.

**Why this is permitted after V1 was judged.** The rule forbids amending a gate *to change how an
already-judged candidate is treated*. This amendment does the opposite: it is strictly harder for
future candidates, V1's frozen verdict is untouched (it was never a promotion — the block is the
unversioned proxies, not any score), V1 is not re-run, and `candidates_evaluated_before_amendment`
is honestly recorded as 1. A separately written note in
[`phase2-stage-b-candidate-v1-development.md`](phase2-stage-b-candidate-v1-development.md) records
that V1 would additionally fail the new Spearman gate (0.69090 vs 0.70851, −2.49%) and be measured
against the harder `trailing_5_player_minutes` RPS/Brier bars under 1.2, without changing V1's own
verdict.

## Entity, grain, and player identity

The prediction entity is the **player**. The grain is `season_player_code_fixture` —
player-fixture, not player-gameweek — because double gameweeks are separate fixtures and the
source carries one row per fixture. Collapsing them would destroy the minutes signal.

**Player identity is the stable `code`.** `code` is 1:1 with the player's permanent identity
across all seasons. `element_id` (and the archive field `element`) is season-scoped and
reassigned yearly, so it is **forbidden for cross-season tracking**: across this archive
`element_id = 308` resolves to Almiron (2021-22), Aké (2022-23), Salah (2023-24), Ward
(2024-25), and Heath (2025-26). Joining a bare `element_id` across seasons merges five
different players into one history. `web_name` also drifts between seasons (for example Salah
to M.Salah). Cross-season player tracking MUST use `code`; the only permitted season-local
alternative is a season-qualified `(season, element_id)` key.

**Transfers are time-local.** A player can turn out for more than one club inside a season, so
"which team is this player on" is a question with a time in it. `mart_dim_player.team_id`
records only the club a player finished the season at (measured 242 transfer stints, of which
the dimension matches 120; three clubs in one season occurs). Resolve a transferred player's
club from the **fact row's `team_id`** or from `mart_dim_player_stint`, never from
`mart_dim_player.team_id`. A transferred player's attacking share travels with him while the
team scale does not, and defensive contribution is a property of the team system rather than
the player — a transferred player's DC expectation must be rescaled to the destination club.
(DC is not a Stage B metric, but the identity/transfer policy the minutes model inherits is
recorded here so it is not silently re-derived later.)

## Eligible population

The eligible population is the **registered FPL player population**: every
`mart_fact_player_fixture` row with a non-NULL `minutes` outcome for a club fixture,
**including registered nonparticipants at minutes=0**. The source carries the broader
registered FPL player pool — a median of 33–39 player rows per team-fixture (min 23, median
36, max 59) — of which only about 13.8–15.2 actually play (minutes > 0; min 11, median 15,
max 17). This is the registered FPL player population, **not a matchday-squad population**,
and the registered count strictly exceeds the appeared count for every team-fixture.
Zero-minute rows are **never filtered**: most registered rows do not play (the zero-minute
share ranges ~57–62% by season, so it is season-volatile and not pinned as a hard figure),
so dropping them would hide the single most load-bearing probability mass in the system.

Evidence (local archive): **138,707 unique `(season, code, fixture)` keys; zero NULL minutes;
per-team-fixture registered population min/median/max = 23/36/59 and appeared (minutes > 0) =
11/15/17; minutes range 0–90.** All current archive rows are ≤90. These figures are asserted
in `tests/test_facts.py::test_registered_player_population_strictly_exceeds_appeared`, which
is `archive`-marked and runs against the built database.

There is **no minimum player-history exclusion**. Every eligible row receives a prediction; a
row with no usable player history receives the declared fallback distribution and is reported
as a cold start, never dropped. Cold-start cohorts include (a) players with zero prior
player-fixture rows, and (b) players with zero prior positive-minute appearances.

## Walk-forward split and archive cutoff

Each fold predicts one **observed** gameweek. Gameweeks come from the facts rather than
`1..38`; 2022-23 has no GW7. The window expands after at least **eight** observed gameweeks.

The historical archive contains no authoritative FPL deadline history and no versioned
historical availability. Its cutoff is therefore the **first kickoff in the predicted
gameweek**: the latest available proxy that still excludes every outcome from that gameweek.
Observed outcomes must satisfy `kickoff_time < as_of`. This is a proxy, **not** a claim that a
postponement, availability field, or schedule state was known at the real deadline. Any live
fact used in a later walk-forward run must additionally satisfy `known_at <= as_of`.

Every transform and fallback is fitted within the fold. NULL remains unavailable, never zero.
The seed is fixed at `202627`.

## The four ordered minute bins

The output is a distribution over four **ordered** bins with frozen keys:

| key | minutes | meaning |
|---|---|---|
| `"0"` | `0..0` | did not play |
| `"1_59"` | `1..59` | partial appearance |
| `"60_89"` | `60..89` | long appearance (below full match) |
| `"90"` | `90..` (open-ended) | full match, folding 90-or-above |

The bin **numeric ranges are derived from the frozen KEY TEXT, never hardcoded separately in
Python.** The loader validates that the four keys are exactly `("0", "1_59", "60_89", "90")`
in order, and that each bin's `minutes_min`/`minutes_max` equal the range derived from its
key: a bare `"0"` is the point bin `(0, 0)`, a labeled key splits on `"_"` (`"1_59"` →
`(1, 59)`, `"60_89"` → `(60, 89)`), and a bare `"90"` is `(90, None)` — open-ended above.
Because the key is the single source of the range, contiguity and the open-ended tail are
structural consequences, and editing any boundary to disagree with its key fails to load.

### The 60-minute boundary is cross-checked against the scoring rules

The 60-minute lower boundary of the `"60_89"` bin is the FPL appearance / clean-sheet
threshold. Because it is a scoring constant, it is **read from this contract's bin definition
and cross-checked at load time** against BOTH independent fields of the configured
`downstream_points_ruleset` (`2026_27`):

- `appearance.long_play_minutes` (both rulesets: `60`)
- `clean_sheets.minimum_minutes` (both rulesets: `60`)

`load_phase2_evaluation` fails closed — raises and refuses to load — if:

1. the two scoring thresholds disagree with each other;
2. either threshold disagrees with the contract's bin boundary; or
3. the contract boundary exceeds 90 minutes (impossible today, pinned defensively).

This is why the boundary is never hardcoded in Python: a future ruleset whose threshold moved
to, say, 45 minutes would refuse to load against this contract until the bin shape is
deliberately re-registered. The loader exposes a `scoring_path` seam so an offline test can
inject a temporary scoring YAML with a mismatched threshold and assert the fail-closed
behaviour without a database.

## Target roster (knowledge-time)

The minutes model cannot discover **which players to predict** from `PointInTimeView.schedule()`
(a team-level schedule projection), and the archive does **not** version player registration,
position, or club at the real FPL deadline. The `target_roster` policy records this honestly:
the historical target roster is an **unversioned archive proxy projected from the target rows**
— analogous to the schedule-cutoff limitation, **not** a claim that membership, position, or
club were known at the real deadline. `historical_roster_status` is pinned to
`archive_proxy_unversioned_at_real_deadline`.

The exact proxy column set the roster may carry into the model is frozen:
`{season, gw, fixture, kickoff_time, code, position, team_id, opponent_team_id, was_home}` —
identity and schedule metadata only. The loader rejects additions and deletions to this set and
verifies it stays disjoint from the outcome columns. `code` is the stable cross-season player
key; `team_id` is season-qualified. `minutes` is the **label** and is kept **outside** the
model-facing projection (`minutes_role: label_outside_model_facing_projection`); the
season-scoped aliases `element_id` / `element` are absent.

Live / prospective Stage B work must instead select entities from a **versioned player
registry** whose `known_at <= as_of` **before the model sees entity / team / position**
(`live_prospective_registry`); the historical proxy cannot be reused there without forfeiting
any historical-lift claim. Any cross-season club identity resolves the target row's
**season-qualified `team_id`** to the **stable `team_code`** (`cross_season_team_identity`);
a bare `team_id` is never joined across seasons and `mart_dim_player.team_id` is never used.

## Historical feature policy

Only **reconstructable point-in-time** fields are permitted as historical features (see also
the target-roster policy above: the roster itself is an unversioned archive proxy, not a
proven-known-at-deadline input). Availability, status, and chance-of-playing information is
**unavailable** in the archive and therefore **excluded**. A future use of versioned live
availability would be a **separately named prospective candidate** and may not claim historical
lift. The historical score this contract produces is a **development number on the local
archive, not an upper bound**.

## Required baselines

Every baseline produces the **same four-bin distribution on the same eligible population**.
Each baseline's exact deterministic algorithm is frozen in the contract (identity, population,
order, window, smoothing, fallback, estimator); the implementations are a separate slice.
Probability estimates use the frozen estimator `raw_empirical_bin_frequency_count_divided_by_n`
— raw `count / n` over the four ordered bins with **no additive smoothing**; for `last_observed`
this is effectively a one-row empirical frequency (one-hot). A one-hot zero probability
**remains zero** and is handled only by the registered log-probability floor
(`scoring_calibration.log_probability_floor`). Where an order applies it is always
`kickoff_time` then `season` then `fixture`.

- **`position_minutes_frequency`** — identity: the target player's **current position**;
  population: **all prior eligible training rows at that position**; order: none (all rows);
  window: none; smoothing: none; fallback if that position has no rows = the **unsmoothed
  all-position prior rows**. This is the transparent positional floor and the cold-start
  fallback.
- **`last_observed_player_minutes`** — identity: stable **`code`**; population: the **most
  recent prior player-fixture row** (a one-hot distribution at that row's bin), ordered by
  `kickoff_time` then `season` then `fixture`; window: none; smoothing: none; fallback if no
  prior row = `position_minutes_frequency`.
- **`trailing_5_player_minutes`** — identity: stable **`code`**; population: the **up to five
  most recent prior player-fixture rows including zero-minute rows**, ordered by `kickoff_time`
  then `season` then `fixture`; window: pinned to **exactly 5**; smoothing: none; fallback if
  none = `position_minutes_frequency`.
- **`trailing_5_team_position_minutes`** — identity: resolve the target club from the target
  row's **season-qualified `team_id`** to the **stable `team_code`**; population: that club's
  **five most recent completed fixtures before cutoff**, then **all prior eligible player rows
  at the target position** in those fixtures, ordered by `kickoff_time` then `season` then
  `fixture`; window: pinned to **exactly 5** fixtures; smoothing: none; fallback if none =
  `position_minutes_frequency`. This baseline **never** uses `mart_dim_player.team_id` and
  **never** joins a bare `team_id` across seasons.

The baseline **set** is exact: the four names are required and no extra baseline may be added;
removing one fails to load. `ep_next` is **not** a Stage B baseline: it is FPL **points**, not
minutes. Predicting points is a later stage. It is recorded as excluded so it cannot be
silently added as a comparator.

## Metrics

| Class | Metric | Role |
|---|---|---|
| Primary | `mean_log_score` (direction `lower_is_better`) | The promotion metric |
| Proper distribution | `mean_log_score`, `mean_ranked_probability_score` | Ordered-bin proper scores (the existing generic discrete CRPS function may later compute the RPS; category-index distance is not "minutes") |
| Binary guardrails | `mean_brier_any_minutes`, `mean_brier_60_plus` | Per-margin Brier on the two product-relevant binary outcomes |
| Calibration | `randomized_pit`, `pit_interval_80_coverage`, `reliability_any_minutes`, `reliability_60_plus` | PIT uniformity and per-margin reliability |
| Ranking | `spearman_p60_within_position_gameweek` | Ranking where ranking is a product decision |

**Reliability buckets MUST carry a count `n` per bucket.** Reliability curves are
**report-only in v1.0**: there is no post-hoc tolerance on them and they gate nothing. This
mirrors the Phase 1 lesson (amendment 1.1) that a miscalibration measure must name the
quantity it measures.

## Scoring and calibration definitions

The exact scoring / calibration definitions are frozen in the `scoring_calibration` block and
enforced by the typed loader (the metric **functions** are implemented in a separate slice,
not by loading this contract):

- `log_probability_floor: 1e-12` — floor applied to every predicted probability before taking
  the log, so a one-hot zero never produces `-inf`. A baseline's zero probability remains zero
  and is salvaged only by this floor.
- `ranked_probability_score: sum_of_squared_ordered_category_cdf_errors_not_physical_minute_distance`
  — RPS is computed over the four ordered **categories** (bin indices), not as a physical
  minute distance. A 0→90 miss is not "90 units worse" than a 0→1 miss.
- `brier: squared_binary_probability_error`.
- `randomized_pit_band: (0.1, 0.9)` with `randomized_pit_seed: 202627` — the randomised-PIT
  band edges and the seed that makes the randomisation reproducible.
- `reliability_edges: 0.0..1.0 in 0.1 steps` (11 edges ⇒ 10 buckets), with
  `reliability_buckets: left_closed_right_open_except_final_bucket_right_closed` and a
  `reliability_bucket_n: true` count per bucket.

## Promotion gate

A candidate is judged against the **best eligible required Stage B baseline** on the **same
eligible predictions**, using the relative lift formula `(baseline - candidate) / abs(baseline)`.

| Gate | Value |
|---|---|
| `guardrail_comparison` | `best_baseline_per_metric` (amendment 1.2; each guardrail vs the best baseline value of its own metric) |
| `minimum_primary_relative_lift` | `0.01` (aggregate mean-log-score lift; pinned) |
| `maximum_ranked_probability_score_relative_regression` | `0.0` (**aggregate** guardrail only; vs the best-RPS baseline; no per-season RPS gate) |
| `maximum_brier_relative_regression_any_minutes` | `0.0` (**aggregate** guardrail only; vs the best-Brier-any baseline; no per-season Brier gate) |
| `maximum_brier_relative_regression_60_plus` | `0.0` (**aggregate** guardrail only; vs the best-Brier-60+ baseline; no per-season Brier gate) |
| `maximum_spearman_p60_relative_regression` | `0.0` (amendment 1.2; starter ranking vs the best baseline Spearman; group-constant candidates fail) |
| `pit_interval_80_maximum_absolute_error` | `0.05` (pinned) |
| `minimum_prediction_coverage` | `1.0` (pinned: every eligible row gets a prediction) |
| `minimum_fold_count` | `181` (pinned) |
| `require_no_season_mean_log_score_regression` | `true` (the **only** per-season non-regression rule; not a per-season 1% gate) |
| `require_zero_leakage_failures` | `true` |

RPS and Brier non-regression are **aggregate guardrails only**: they are evaluated on the full
prediction set and there is **no per-season RPS or per-season Brier gate**. Under amendment 1.2
each is measured against the best baseline value of its own metric (lower is better), and the new
Spearman-p60 starter-ranking gate is measured against the best baseline Spearman (higher is
better), excluding group-constant baselines. The sole per-season non-regression rule is
`require_no_season_mean_log_score_regression` (forbid regression; not a per-season 1% gate).
Aggregate lift is still judged by `minimum_primary_relative_lift`.
`minimum_prediction_coverage` is pinned to exactly `1.0` and the loader rejects any other value,
because every eligible row must receive a prediction. A failed gate is **non-promotion, never
threshold movement**: a candidate that misses the gate does not get to move the bar, and a gate
may not be amended after a candidate is judged. Reliability curves are report-only.

## Reporting dimensions and counts

Reported dimensions: `fold`, `season`, `position`, `home_away`, `transfer_status`,
`player_history_cohort`. Reported counts: `predictions`, `exclusions`, `cold_starts`,
`uncertainty`. `starts` may be reported **only where measured**: 2021-22 `starts` is entirely
NULL, so any `starts`-based slice must exclude that season rather than treat NULL as zero.

## What this contract does not do

- It contains **no Candidate V1 promotion verdict**. Candidate V1 has been development-evaluated
  once (development-only, not promoted; see
  [`phase2-stage-b-candidate-v1-development.md`](phase2-stage-b-candidate-v1-development.md)); no
  gate has been executed as a promotion judgement. The default harness remains baselines-only.
  `src/fpl/validate/dev_minutes_candidate_v1.py` is an explicit development-only opt-in path,
  implemented and provenance-tested.
- It runs **no Monte Carlo**. Stage B is a closed-form marginal and stays separate from
  per-minute event/rate models (R6).
- It does **not** use a hurdle model, availability feature, or fixture-specific Candidate V1
  input. A future use of versioned availability is a separately named prospective candidate.
- It does **not** claim the historical score is an upper bound.
- It does **not** use versioned live availability historically; that is a separately named
  prospective candidate.
