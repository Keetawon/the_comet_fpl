# Phase 4 Stage D — Prospective EV Walk-forward Backtest Design

**Status: pre-registration, development-only. Never executed.** The Prospective Expected Value (EV)
Walk-forward Backtest is pre-registered under `config/phase4_ev_backtest_evaluation.yaml`
(contract v1.2). No run has been performed, no archive run has occurred, no result artifact exists,
and no EV number — primary or comparator — has been observed. Both amendments below were therefore
made *before* first execution, and both record
`candidates_evaluated_before_amendment: 0`.

## Amendment 1.2 — the BPS residual parameters are pre-registered

Bonus is simulated jointly per fixture from the predicted BPS residual mean and sigma, so the six
inputs to `fit_residual_model` move every full-points distribution the backtest scores. Under
contract 1.1 the adapter constructed `BpsSimConfig()` and inherited its dataclass defaults, which
were written into the run record only *after* the run finished — making them an output of the
evaluation rather than an input to it. A reader could not distinguish a value chosen before
execution from one changed after seeing a result, which is the distinction pre-registration exists
to make.

| Parameter | Frozen value | Role in the fit |
| --- | --- | --- |
| `trailing_window` | 10 | Length of the per-player residual history the prediction shrinks toward |
| `prior_strength` | 10.0 | Shrinkage of a player's trailing residual mean toward the positional line |
| `ridge_lambda` | 1.0 | Ridge penalty on the per-position influence/creativity regression |
| `sigma_floor` | 2.0 | Lower bound on the residual noise scale used in the BPS draw |
| `sd_floor` | 1.0e-6 | Guard against a degenerate predictor standard deviation |
| `minimum_position_rows` | 30 | Rows a position needs before it gets its own line instead of the pooled fallback |

The six numbers are exactly the `BpsSimConfig` defaults that were already in force, so this
pre-registers what the code did rather than retuning it. Nothing else changed.

They are now *threaded*, not duplicated: `dev_ev_backtest` builds a `BpsResidualParameters` from
the contract and passes it into `generate_forecasts_for_fold`, which passes it straight to
`fit_residual_model`. `BpsSimConfig` is no longer imported by the adapter at all, so there is no
path back to inheriting a default, and `BpsResidualParameters` deliberately declares no defaults of
its own. The applied values are written to the run record under
`bps_residual_parameters_applied`. Guarded by valid-but-wrong mutation tests on all six fields,
plus a wiring test that swaps the contract to values nothing else in the codebase holds and asserts
`fit_residual_model` receives them — the pre-registered values coincide with the old defaults, so a
test that merely asserted "the fit saw 10/10.0/1.0/2.0/1e-6/30" would pass against the defaults it
replaced.

## Amendment 1.1 — component identities corrected before first execution

Contract 1.0 froze two component names that existed nowhere in the repository and that
misdescribed the models they claimed to pin:

| Contract 1.0 | Actual constant | Why 1.0 was wrong |
| --- | --- | --- |
| `league_constant_save_rate_v1` | `gk_saves_poisson_from_team_conceded_v1` | The save rate is fitted **fold-locally** from the training window; the measured league constant is only the cold-start fallback. |
| `team_rescaled_dc_v1` | `trailing_dc_threshold_hit_bernoulli_v1` | The DC component applies **no destination-team rescaling** — it shrinks a player's trailing hit rate toward a fold-local **position** rate. The 1.0 name asserted exactly the property `AGENTS.md` requires and the code does not implement. |

Zero evaluations had been executed when this was corrected, so it is a pre-registration repair
before first execution, not an amendment of a judged gate. Two inline architectures that carry no
model `NAME` constant were also named (`components.assists_architecture`,
`components.bps_simulation`) so the contract states what runs rather than leaving it implicit.

The recurrence guard is that identities are now checked against the code in two places:
`tests/test_phase4_ev_backtest_evaluation.py` compares each frozen name to the implementation
constant and to what `default_component_suite()` installs, and `dev_ev_backtest` re-checks the same
equalities at runtime and refuses to start on a mismatch.

## The contract governs the run

Every frozen value is threaded into the code that acts on it, rather than duplicated as a default:
`support.max_fixture_points`, `primary_architecture.seasonal_appearance_min_rows`,
`monte_carlo.{draws,seed}`, and `scoring_calibration.{randomized_pit_band,randomized_pit_seed}` are
passed from `main` down to the adapter and the scorer, and `scoring_calibration.log_probability_floor`
is asserted against `fpl.validate.metrics.PROBABILITY_FLOOR`. A pre-registered value that is only
duplicated cannot detect drift, which is the entire reason for pre-registering it. The run records
what it actually applied under `contract_policy_applied`.

`prior_season_blend_weight: 0.0` and `historical_availability_multiplier: 1.0` state an **absence**:
the adapter implements neither a prior-season appearance blend nor an availability overlay. The
horizon is mid-season on both counts (the production blend weight is 0.0 outside August–November,
and a historical backtest has no live availability feed). The runner asserts both identity values so
the record cannot claim a policy that no code applies.

The six BPS residual parameters were the last values that were not pre-registered; amendment 1.2
closes that gap (see above), so every value that materially shapes a scored distribution is now
frozen in the contract and threaded into the code that acts on it.

## Deterministic ICT reduction

`prospective_points_v1.trailing_ict` supplies the influence/creativity proxies the BPS residual is
predicted from, so it feeds a pre-registered evaluation and must be bit-reproducible.

It previously computed `avg(influence)` under a DuckDB `GROUP BY`. That partitions the scan across
threads and combines the partial sums in completion order, and float addition is not associative,
so the exact value depended on the thread count: measured on this archive, **628 of 1,777 codes**
returned a different exact mean at 1 thread versus 8. This is the same class of defect the
repository already measured for Polars `group_by` without `maintain_order`, recorded in
`AGENTS.md`'s measured constants.

Adding `ORDER BY` after the `GROUP BY` does **not** fix it — that sorts the aggregation's output
and cannot control the order the addends were combined in. The reduction itself had to change:

1. Rows are read under a total order on `(code, kickoff_time, season, fixture)` — `(season,
   fixture)` is unique within a code at player-fixture grain, so the ordering is total, not merely
   stable-looking.
2. Each code's influence and creativity are summed in Python with `math.fsum`, which is correctly
   rounded and therefore returns the same value for *any* permutation of its input, and divided by
   an integer count.

Both halves are deliberate: either alone fixes today's defect, and together the result stays
reproducible if one is later changed. The population and NULL semantics are byte-for-byte the
previous ones — `minutes IS NOT NULL`, `kickoff_time < as_of`, `influence IS NOT NULL`,
`creativity IS NOT NULL` — so a NULL is skipped rather than read as zero, and a measured
zero-minute row still counts. No target-row ICT is read and no model semantics changed.

The regression test asserts **exact dictionary equality** across DuckDB thread counts 1, 2, 4 and 8
— not `pytest.approx`, which would accept precisely the drift being guarded against. Its fixture
(50 codes × 4,000 rows) is sized to reproduce the defect: verified to return a different exact mean
for 38 of 50 codes under the old implementation, and a smaller table does not split the aggregate
at all, so it would pass against the defect.

This backtest evaluates how accurately the **current prospective point-in-time forecasting
architecture** ranks players and models points distributions over the final ten observed gameweeks
(GW29–38) of the 2025–26 season.

## Derived Horizon Anchors

- **Season**: 2025–26
- **Gameweeks**: GW29–38 (10 observed gameweeks)
- **Derived Fixtures**: 99
- **Derived Target Rows**: 8,224 player-fixture rows

## Model Architectures

1. **Primary Architecture** (`prospective_v3_coupled_seasonal_bonus`):
   - Stage A: `trailing_goals_attack_defence` baseline
   - Stage B: `Minutes V3` (`concentration_adaptive_shrinkage_player_minutes_v3`)
   - Stage C Attacking: Goals V3 (`minutes_gated_coupled_team_share_attacking_goals_v3`) + Coupled Assists
   - Saves: `gk_saves_poisson_from_team_conceded_v1` (fold-local save rate, not a league constant)
   - Defensive contribution: `trailing_dc_threshold_hit_bernoulli_v1` (shrunk to a fold-local
     **position** hit rate; no destination-team rescaling)
   - Appearance: `seasonal` (trailing-5 `minutes IS NOT NULL` with $n \ge 3$ threshold; prior-season blend weight = 0.0)
   - Rules: `scoring_2026_27`
   - Bonus: Joint per-fixture BPS Monte Carlo simulation (2,000 draws, seed 202627)
   - Support: `0..34` per fixture (`DEFAULT_MAX_POINTS_FULL`)
2. **Diagnostic Comparator** (`prospective_v1_independent_seasonal_bonus`):
   - Attacking V1 (`xg_informed_trailing_player_goals_v1`) + Assists V1 (`xa_informed_trailing_player_assists_v1`)
   - Co-scored on 100% identical target fixture population; NOT a promotion gate.

## Target Leakage & BPS ICT Parity

- Trailing ICT (`influence` and `creativity`) is extracted strictly before `as_of` (`kickoff_time < as_of`)
  over rows where `minutes IS NOT NULL AND influence IS NOT NULL AND creativity IS NOT NULL`
  (including 0-minute rows where ICT is measured), matching production `prospective_points_v1.py:trailing_ict`
  exactly.
- No `threat` and no per-minute conversion.
- Target-row outcomes and recorded points are NEVER read by prediction components. Labels are
  loaded only after every gameweek's forecasts are complete, and the label key set must equal the
  target key set exactly.
- `mart_target_completeness` is checked for season 2025-26 under ruleset `2026_27` before the run
  and recorded in the output. Replayed points silently understate a player whenever the season did
  not measure a component the ruleset needs; an incomplete or absent completeness row stops the run
  rather than producing a number whose meaning depends on unstated coverage.
- Both architectures fail closed where a Stage A team-goal distribution is missing. Falling back to
  V1 rates inside the primary would score the comparator's architecture under the primary's name.

## Forecast Grain & DGW PMF Convolution

- **Fixture Grain**: Proper scores (Log Score, CRPS, Randomized PIT-80) evaluated directly at `(season, code, fixture)` grain over 0..34 support.
- **Weekly DGW Convolution**: For Double Gameweeks, fixture PMFs are convolved without truncation over support `0 .. (34 * fixture_count_for_player_gw)`. Weekly EV is the exact sum of fixture EVs.
- **Cumulative Ranking**: Weekly player-GW rows are aggregated by player `code` across all 10 gameweeks for Spearman correlation evaluation. A transferred player's cumulative row carries the club he finished the horizon at (`team_code` from his last gameweek); inside a double gameweek the weekly row carries the first fixture's club.

## Two grains, and one tie policy

The **overall** report scores at fixture grain `(season, code, fixture)` — the contract's scored
population. The per-gameweek `gw_calibration` block scores at **player-GW** grain, because that is
the grain a weekly decision is made at. The two do not reconcile by averaging: a double-gameweek
player is one row there and two here, and each gameweek draws its own PIT randomisation. Only
`ev_total`/`actual_total` sum across both, since weekly EV is the exact sum of fixture EVs. The run
record labels both grains explicitly.

Every ranking output reads one oracle ordering, `(actual_points DESC, code ASC)` — NDCG, capture
ratio, overlap, the displayed `actual_rank`, and `in_both_top_20` — so `top_20_overlap` is always
exactly the fraction of detail rows flagged `in_both_top_20`. Predicted EV is deliberately absent
from that key. Actual-point ties are ordinary at both grains, and an EV tiebreak inside a tie would
hand the higher-EV player the better actual rank and the oracle slot, flattering the model in the
very table a reader checks it against.

## Provenance

Clean Git HEAD is the **authoritative code identity**: the runner refuses to start on a dirty
worktree and re-checks both the worktree and the HEAD SHA after the run, which together pin every
tracked file. The per-file SHA-256 hashes are a narrower, *diagnostic* layer on top of it — they
catch a mid-run edit, which leaves HEAD untouched and the worktree clean at both ends. They
therefore span every module that determines what the architecture computes (adapter, harness,
runner, composer, BPS simulator, minutes/goals/assists/saves/DC models, metrics, Stage A
baselines, prospective job), not only the newly added files: a mid-run edit to the minutes model
invalidates a run exactly as much as one to the adapter. Each drift path — database, contract YAML,
scoring YAML, and every hashed source file individually — has its own regression test.

`os.rename` is atomic but **not** no-clobber on POSIX; the immutability guarantee comes from the
existence checks either side of the write, which is a bounded guarantee for a single-process
development runner and would not survive a concurrent writer.

`results/` is not in `.gitignore`, so a completed run leaves the worktree dirty until the artifact
is committed — and the provenance preflight will refuse the next run until it is.

## Known Composer Defect Disclaimer

The runner carries the known composer conditionality defect (Stage C V3 rates already include
$P(\text{play})$ and the composer gates events again through sampled minutes). This depresses EV
totals and distorts rank resolution between starters and cameos. The results serve as a development
diagnostic of the current prospective architecture and CANNOT authorize production deployment.
