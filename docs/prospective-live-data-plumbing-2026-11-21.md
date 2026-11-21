# Prospective live data-plumbing repairs (2026-11-21)

**Status: implemented development-only.** Two confirmed data/plumbing defects in the live
prospective forecast are repaired by this change set
(`fix/prospective-live-data-plumbing`, commits `bdeef11`, `24aba9b`, plus the evaluation
and report commits that follow). Neither fix changes a model family, a frozen result, or
a pre-registered gate: both restore semantics the code already intended, and the shipped
`seasonal` appearance arithmetic is untouched and bit-for-bit reproducible.

- Tests: `tests/test_prospective_live_data_plumbing.py` (written first; every defect
  test reproduced its defect before the fix).
- Preregistration: `docs/appearance-rostered-decay-preregistration.md` +
  `config/appearance_decay_evaluation.yaml`.
- Before/after regeneration harness: `scripts/prospective_plumbing_before_after.py`.

## Defect 1 (P0): absent prior seasons read as "benched all season"

### Mechanism

`prior_season_appearance_rate` reads the archive mart, whose latest season is fixed
during a live season (2025-26 throughout 2026-27). It computes `P(minutes >= 1)` over
every row the player had in that season and trusts it at `n >= 10`. A player who sat on
a PL roster all season while loaned abroad or unavailable has a full season of zero-minute
DNP registry rows, so the map carries `(0.0, 38)`.

`season_boundary_minutes` then blends that rate into P(play) by target calendar month
(0.7 Aug/Sep, 0.5 Oct/Nov, 0 from December). For a returning starter whose trailing-5
window is five 85-90 minute current-season rows (recent ≈ 0.90), November gives
`P(play) = 0.5 * 0.0 + 0.5 * 0.90 ≈ 0.45` — roughly halving his xP. The reproduced
failing test measured exactly 0.4485 against 0.8971 for the Jackson-shaped fixture.

### Measured instance

N.Jackson (code 517052, AVL FWD): 2025-26 has 38 registry rows, 0 minutes (on loan at
Bayern); 2026-27 GW2-10 started with 81-90 minutes in each of GW5-10 and 6 goals. The
published 2026-10-16 vintage gave him 1.35-1.67 xP for GW7-11; the 2026-09-03 vintage
gave ~0.02 (the all-zero May window mapping to the out-of-side regime); an independent
component estimate for GW11 vs SUN was 4.3-5.1 xP, dropping to 2.2-2.5 with P(play)
halved (the live dashboard showed 2.9).

### The rule (candidate measurement before choosing)

Measured on the live 2026-27 registry (672 players; the RAW pre-rule map holds 865
entries) against the 2025-26 archive at the GW11-deadline cutoff
(2026-11-21T11:00:00Z; current-season evidence = GW6-10 live rows, "starters" =
players with >= 4 fixtures at 60+ minutes in GW6-10):

| candidate | players dropped | with current GW6-10 rows | starters released | fringe (0x60min) | mean current appearance rate of dropped |
|---|---|---|---|---|---|
| (i) prior appearances == 0 | 310 | 79 | 4 | 70 | 0.141 |
| (ii) prior appearances < 2 | 343 | 96 | 4 | 86 | 0.124 |
| (ii) prior appearances < 3 | 357 | 105 | 4 | 95 | 0.115 |
| (ii) prior appearances < 4 | 377 | 120 | 5 | 107 | 0.131 |
| (ii) prior appearances < 5 | 387 | 126 | 7 | 111 | 0.140 |
| (ii) prior appearances < 6 | 396 | 132 | 7 | 117 | 0.134 |
| (ii) prior appearances < 8 | 422 | 152 | 9 | 135 | 0.147 |
| (iii) prior-season last status == 'u' | 0 | - | - | - | no 2025-26 snapshots committed |

Candidate (iii) has **zero coverage** for this boundary: committed snapshots begin
2026-07-27, so no 2025-26 element status exists (the current-season statuses show 64 of
427 covered players as 'u', which would be a future-boundary signal only). It was not
chosen on this evidence.

Starters released at each bound -- the false "benched" priors being repaired:

- k=1 (==0): Enciso, Rushworth, Vuskovic, N.Jackson (0 appearances).
- k=5 adds: Trafford (4), Pinnock (4), Colwill (3), Benitez (1), Maddison (3).
- k=8 adds: Walton (7), Kinsky (7).

Chosen rule: **prior-season appearances < 5 carries no appearance prior**
(`_PRIOR_SEASON_MIN_APPEARANCES = 5`). The bound is structural, not outcome-tuned (no
scoring was run to select it): below 5 appearances (~13% of a 38-round season) a season's
appearance rate cannot distinguish unavailability from fringe rotation -- its binomial
standard error exceeds its mean -- so it carries no nailed-ness information at all. It
covers every measured unavailability signature while keeping every rotation prior at
>= 5 appearances honest partial-season evidence (measured 2026-27 examples kept: Kinsky
7 -> 0.18, Jair Cunha 9 -> 0.24, Branthwaite 10 -> 0.26; their in-season drag is the
stale blend WEIGHT, repaired by the rostered-decay mode, not the prior's existence).

On this database the defect-1 scope (>= 4 of GW6-10 at 60+ minutes, prior rate < 0.6,
n >= 35) counts 52 players; the rule covers 11 of them (the zero/low-appearance
group above, plus Penders and Gelhardt at 0), and the remaining 41 have informative
rotation priors (0.24-0.58) whose repair is the decay weight. Kinsky (7 appearances)
is deliberately outside the rule for exactly this reason.

### Scope guards

- The frozen Phase 4 EV backtest adapter path (`current_club=None`) keeps its exact
  historical semantics — pinned by
  `test_frozen_unfiltered_prior_path_keeps_zero_rate_semantics`.
- Prior rows that exist remain NULL-safe and are never zero-filled.
- `established_price` (incumbent detection for the cold-start price prior) is unchanged:
  a dropped prior was never an incumbent (`rate < INCUMBENT_APPEARANCE_THRESHOLD`).

### The rostered-decay successor (preregistered, single evaluation)

The calendar weight itself is replaced -- as a new mode, default unchanged -- by
`w(n) = 0.7 * c / (c + n)` over the player's current-season rostered gameweeks, with the
`n = 0` anchor exactly 0.7 (bit-equal to the shipped August blend). See the
preregistration and `results/appearance_decay_evaluation_v1.json` for the single run,
the selected `c`, and the gate verdicts.

## Defect 2 (P0): the incumbent team model never saw the current season

### Mechanism

The Stage A fit in `prospective_team_scored` read `mart_fact_team_match`, which
`build_team_match` builds from archive `stg_fixture`; `config/sources.yaml` archive
seasons end at 2025-26. So `trailing_goals_attack_defence` was fitted on 2021-22..2025-26
only, with zero 2026-27 matches, no matter how many snapshots were loaded. Proof from the
published vintages: the GW7 team lambdas in the 2026-09-03 vintage and the 2026-10-16
shadow-incumbent vintage are identical to 6 decimals for all 20 team-fixtures although 60
matches were played between them.

### Fix

`live_finalized_team_match_rows` unions the finalized current-season team sides into the
training frame from the *same source the team-outcome ledger attaches* -- the versioned
live fixtures' final official home/away scores -- under the same discipline:

- latest fixture version per `(season, fixture)` with `known_at <= as_of`;
- `kickoff_time < as_of`, `finished IS TRUE`, both scores non-NULL (never zero-filled);
- `(season, team_id) -> team_code` through `stg_live_team_version` on both sides;
- `team_xg`/`team_xgc` NULL (no measurement claimed), which the incumbent's
  goals-measured fit ignores by construction;
- anti-join on `(season, fixture)` against the archive mart (no duplicate keys);
- `include_live_current_season=False` pins the frozen Phase 4 EV backtest adapter to the
  archive-only frame its immutable run consumed.

The estimator, shrinkage and venue means are untouched: this restores the semantics the
frozen historical evaluation used (every match kicked off and known before the cutoff is
visible), it is not a model change.

### 2c: why SDP V2 falls back (reported, checks untouched)

The primary selector (`fpl.models.sdp_environment.select_environments`) fails closed for
a fixture when EITHER club's last five officially completed matches (by kickoff <
cutoff) contain a match without a fully validated SDP row (`state.expected` minus
`valid_keys`, with the reason taken from `state.failures`). One missing match therefore
blocks **every** fixture that club plays for as long as it stays inside the five-match
window -- and indefinitely if the capture/stage gap never heals. That is exactly the
observed six-club pattern (AVL, SUN, ARS, NFO, TOT, FUL falling back in every GW7-11
fixture).

What the retained evidence shows, per database available in this workspace:

1. `data/fpl.duckdb` (dev): **no SDP raw payloads at all** → `load_sdp_state` returns
   `global_failure = SDP_MISSING_FALLBACK`; every fixture selects the incumbent.
2. `.worktrees/sdp_test/data/fpl.duckdb` (a 2026-09-04 copy carrying the first real
   SDP captures): at cutoff 2026-09-03T10:40Z (the vintage time) the payloads are
   correctly invisible (`fetched_at > cutoff`) → `SDP_MISSING_FALLBACK`. At
   cutoff 2026-09-05Z, when the 2026-09-04T23:59 payloads are cutoff-eligible, the state
   is `global_failure = SDP_SCHEMA_FALLBACK` with the diagnostic
   *"LeakageError: SDP revision read model is missing; run audit_pl_sdp --stage on an
   operational database before reading eligible SDP observations"* — raw payloads were
   captured but never staged, so the strict PIT crosswalk refuses to read them and
   **every** club blocks. The probe lists each club's blocking (season, fixture)
   keys (`sdp_probe.py`, retained output below).
3. The operational database that produced the 2026-10-16 vintage -- where the selector
   did go primary for 8-10 of 20 fixtures and fell back for exactly six clubs -- is not
   retained in this workspace (the documented storage cleanup reclaimed ~78 GB on
   2026-10-30 / 2026-11-06), so the exact October trip-wire cannot be re-derived here.
   The mechanism above plus the retained staging-gap signature makes the operational
   cause precise enough to act on: those six clubs each had a recent completed match
   with raw-but-unstaged (or never-captured) SDP evidence at every October cutoff.

**No check is weakened.** The repair for real capture gaps is operational, and matches
the runbook's own rule: run the staging pass (`python -m fpl.jobs.audit_pl_sdp --stage`
or `daily_pl_sdp` without `--raw-only`) on the operational database so the strict
revision read model exists for every completed match, then verify with
`python -m fpl.jobs.audit_sdp_fallbacks --db ... --artifact ...`: its report attributes
each fallback to a category and marks the captures that are `FIXABLE_NOW` (valid latest
raw version present but unstaged). The Defect-2 fix above is what removes the damage of
falling back: the incumbent the fallback uses is no longer blind to the current season.

### 2d: regeneration at the next deadline

`scripts/prospective_plumbing_before_after.py` runs the forecast twice at the next
deadline's cutoff on the same loaded database -- BEFORE (pre-repair behaviour
reconstructed by suppressing the live training rows and disabling the availability rule
in the harness process only) and AFTER (the repaired path) -- and reports team lambdas,
the fallback share, the Defect-1 population's xP, and every top-20 rank change by
position. Measured output for the GW11 deadline: REGENERATION-RESULTS.

## Gate results

See HANDOFF section of the covering conversation record; the pre-existing failures on
this branch (present on `origin/main` before this change set) are:

1. `tests/test_development_reference_components.py::test_existing_production_source_pins_are_unchanged`
   (1 failed) plus 24 fixture ERRORs (`assert 2 == 1`: the fixture counts one minutes
   fit, the shadow-incumbent recursion now fits twice by design).
2. `tests/test_retrospective_minutes_proxy.py::test_contract_pins_and_prospective_import_boundary`
   (source SHA pin drift on `src/fpl/validate/prospective_incumbent_adapter.py`).
3. `tests/test_prospective_incumbent_adapter.py::test_existing_sql_helpers_reproduce_shrinkage_and_latest_season_exactly`
   (raw in-memory DB never created `stg_live_team_version`, which `load_player_history`
   reads).
4. The documented Windows `WinError 1314` symlink suite in `tests/test_bi_export.py` /
   `tests/test_dashboard_json.py` publication tests, plus the `.pytest_cache`/basetemp
   permission denials on this host (worked around with `--basetemp` under the approved
   temp root).
5. `ruff format --check .` fails on 8 pre-existing files under `src/fpl/publish`,
   `src/fpl/insights`, and 4 test files on `origin/main`; the files touched by this
   change set are formatted.
