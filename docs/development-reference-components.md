# Current components: isolated retrospective reference

`retrospective_current_component_proxy_v1` reproduces the current prospective
component **arithmetic**, consuming the already-retained current minutes-selector
reference. It is not a newly fitted candidate, a historical live forecast, a
promotion or a result of the full-points synthesis. There is no CLI/output writer.

The explicit evidence class remains `retrospective_archive_price_proxy_development`.
The archive target roster, first-target-GW-kickoff cutoff and price-sensitive cold
starts have the limitations documented in
[the price amendment](retrospective-current-minutes-proxy-v1.md). Neither this
adapter nor a later consumer may relabel those inputs deadline-known.

## Input integrity and time boundary

`read_minutes_control_cache(directory, db=..., root=...)` accepts only the completed
manifest with SHA256
`5b813d58b71bad97a5c81774aaf70c0bca5f4e0e3bcd518e6f26e0acfea19bac`, produced from
clean `eea2381c8395af0b136782c515d0e34181cc462c`. It checks the committed retained
manifest, separate provenance file, all source pins, explicit original database
hash/no-WAL state, all114 fold hashes, exact season/GW keys and all86,755 rows.
Counts remain29,725/27,283/29,747 over2023-24/2024-25/2025-26, with821 direct
price-proxy rows. This implementation does not rerun the minutes model.

Every cache row must retain the exact outcome-free `TargetRow` projection, a
four-bin normalized minutes PMF agreeing with its selector provenance, stable
team identity, original consulted-price lineage and non-promotable evidence class.
No duplicates, target-before-cutoff rows, same-GW club/position contradictions,
unpaired fixture sides or later prior events are accepted. All fixture legs are
retained. The archive order is explicitly `(fixture, code)`.

`build_reference_components(con, fold)` requires that its connection points to the
validated database path. Only explicitly synthetic in-memory tests omit the path.
The caller must acquire and retain a read-only connection before validating the
cache and keep that lease throughout a reference run, then recheck database/source
hashes before publication. The cache reader itself is not a database backup or a
long-running writer lock. `component_source_fingerprints(root)` lists the additional
transitive source/config pins that later provenance-guarded runners must freeze.

Only archive observations with `kickoff_time < as_of` reach component helpers.
Any prior row belonging to the target season/GW rejects the batch before fitting;
all target fixtures therefore share the same pre-GW state. Target goals, minutes,
xG/xA, ICT, BPS, cards and match results are never predictor inputs. Historical
archive capture-time validity is not asserted. This separate validation module
does not weaken `PointInTimeView` or add a prospective escape flag.

## Exact current calculation

| Component | Unchanged implementation |
|---|---|
| Minutes | Final seasonal/current-selector four-bin PMF from the validated cache; never refit V3 |
| Team | `prospective_team_scored` / `TrailingGoalsAttackDefence`; opponent PMF is conceded PMF |
| Player goals | Current-club eligible appeared xG (pre-xG: threat), equal-weight last5, original cold pooled prior, minutes-gated team-share allocator |
| Player assists | Analogous xA/creativity share, team rate multiplied by **fold-local** `league_assist_rate`, not V2's unrelated0.75 default |
| Saves | `GkSavesV1` fitted on prior measured GK appearances; fallback0.673 and clamp0.50..0.85 unchanged |
| DC | `DefensiveContributionV1`, alpha5/window5 and ruleset position thresholds unchanged |
| BPS residual | Existing fold-local residual fit; prior10/window10/ridge1/sigma floor2, source defaults retained |

The goal and assist team allocations are unconditional. The exact existing
`conditional_rate` conversion is applied once before the composer gates on minutes;
it is not double-gated. The uninformative Stage A independent-player fallback remains
available. Missing individual xG/xA is retained as NULL in diagnostics, with the
existing resolved cold prior recorded separately. This is not provider zero filling.
The prior goals/assists `COALESCE` behavior is inherited from the current comparator,
not a new interpretation of SDP nulls.

`trailing_ict(current_club=...)` is deliberately reused exactly: it averages all
eligible rows with both ICT fields measured, including measured DNPs. It is **not**
changed to an appeared-only trailing-five estimate. The old `run_points_fold_v3`
target-ICT proxy is not used. The source `component_engine_v2` is not this comparator.

The final composer is the unchanged joint `compose_fixture_full_points`: both clubs'
entire declared rosters, seed202627 hashed with season/fixture,2,000 draws, support
0..34 and `MEASURED_CONCEDED_EXPOSURE=(0,.344,.813,1)`. Each player's component draw
also supplies their BPS; fixture bonus competition is joint. The existing nonnegative
clipping/tail-folding convention is preserved. No separate CS model or availability
multiplier is introduced; availability remains a reporting overlay outside the PMF.

## Retained diagnostics and proxy dependence

The return object keeps each `FixturePlayer` with every input PMF, residual mean/sigma,
exact target identity, nullable and resolved attack/assist signals, unconditional
allocated rates, team PMFs, Stage A fallback flags, all fold estimator parameters,
residual scaling/coefficients and source cache provenance. These are input diagnostics,
not candidate performance. No downstream tactical/player feature is selected here.

Three dependence levels are separate:

- direct cold-player price dependence on their own minutes;
- same-club price-dependent codes participating in coupled attack/assist allocation;
- any fixture price-dependent code participating in joint bonus competition.

The latter two are conservative computational lineage, not a claim that every output
numerically changes. A non-proxy player's own minutes can therefore have proxy-dependent
goals or full points. All raw consulted-price records remain available in the originating
row's immutable selector provenance. A later experiment must carry the same reference
and proxy evidence in both arms and retain the mandated sensitivity slices.

## Synthetic reproduction proof and limitations

Tests invoke the **actual** `predict_prospective_points` defaults on an in-memory
database populated through the real live capture loader with explicitly synthetic2026
bootstrap/fixtures. They spy on, then delegate to, the unchanged joint composer.
The unchanged fitted V3 model is reused to independently calculate strict current
selector outputs from known synthetic registry/price evidence. No historical bootstrap
is fabricated and no historical model evaluation is rerun.

The adapter must match every captured `FixturePlayer` exactly, including minutes,
goals, assists, saves, DC, conceded PMF and residual mean/sigma. Full35-bin PMFs and
expected bonus must then match exactly with the same seed/options. The proof includes
two DGW legs, all positions, a cold newcomer, NULL signals, all-zero signals and
empty-team-history defaults. The actual incumbent refuses an entirely empty prior
minutes history; that existing refusal is tested and is not "repaired" here.
Extra tests cover future truncation, same-GW rejection,
identity/PMF corruption, raw-NULL preservation and propagated price dependence.

The live registry query does not promise an outer SQL order; the original allocator
uses ordinary floating-point sums before the composer sorts codes. Synthetic proof
therefore preserves the actual returned registry order. The archive reference declares
its canonical order explicitly; it does not claim arbitrary live-registry permutations
are bit-identical. No production ordering or mathematics is silently changed.

A real archive component/full-points run still requires a separately clean committed
contract, source/database pre/postflight guards, complete fixed population, write-once
output and comparator checks. This module/test work alone reports no model performance
and licenses no default or optimizer update.
