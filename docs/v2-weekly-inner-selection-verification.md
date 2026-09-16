# Weekly inner-selection verification

Date: 2026-09-06. Offline implementation gate before formal archive scoring.
Runtime: Python 3.14.7, Ruff 0.16.0, mypy 2.3.0, using the existing local runtime
at `C:\Users\keetawatw\AppData\Local\Temp\the_comet_fpl_runtime\Scripts` and
`PYTHONPATH` set to this V2 worktree's `src`. No dependency or runtime migration.

## Existing-code baseline

The existing suite was run separately from the two new test modules, which were being
implemented concurrently:

```powershell
python -m pytest -q --ignore=tests/test_weekly_inner_selection.py --ignore=tests/test_dev_v2_weekly_inner.py
ruff check --no-cache src tests
ruff format --check .
mypy src
# From dashboard:
npm test
npm run build
npm run lint
```

- Python: **2,185 passed, 14 failed, 4 skipped** in 391.05 seconds. All failures
  reproduce the documented Windows directory-symlink privilege issue (`WinError 1314`)
  at `src/fpl/publish/export.py:2367`. The skips are privilege-dependent publication tests.
  Warnings: 5,194 existing PuLP deprecations and two sandbox pytest-cache write warnings.
- Ruff lint: passed, including both new source modules.
- Strict mypy: passed, **139 source files**, including both new source modules.
- Format: **11 pre-existing offenders**, 316 already formatted. No unrelated formatting
  changes were made; the new files pass their targeted format check.
- Dashboard: **312 tests passed in 38 files**; build passed (existing large-chunk warning);
  lint passed with nine existing React export warnings. No dashboard source changed.

The full repository gate is **not unqualified green**. These pre-existing/environmental
failures remain visible, not silently repaired as part of a model-selection experiment.

### Exact failing tests

All are in `tests/test_bi_export.py`:

```text
test_export_writes_complete_contract_and_preserves_nulls
test_team_fixture_ease_indices_are_directed_and_keep_raw_lambdas
test_append_only_player_and_team_outcomes_export_as_separate_vintage_free_facts
test_low_coverage_and_non_positive_denominators_publish_real_nulls
test_official_fdr_is_separate_and_cannot_change_ease_indices
test_genuinely_unavailable_official_fdr_stays_null
test_zero_recorded_runs_is_a_complete_export
test_legacy_v1_vintage_with_no_fixture_rows_is_still_complete
test_export_rejects_season_scoped_referential_integrity_violation
test_source_schema_drift_cleans_temporary_export_and_keeps_previous_publish
test_exports_are_byte_deterministic_except_manifest_created_at
test_concurrent_writer_is_refused_without_clobbering
test_live_season_dimensions_are_sourced_from_the_snapshot_registry
test_archive_database_exports_the_complete_contract
```

### Existing format offenders

```text
src/fpl/insights/contracts.py
src/fpl/insights/evidence.py
src/fpl/publish/contract.py
src/fpl/publish/dashboard_json.py
src/fpl/publish/export.py
tests/test_bi_export.py
tests/test_bi_semantic_contract.py
tests/test_dashboard_json.py
tests/test_insights.py
tests/test_public_dashboard.py
tests/test_snapshot_workflows.py
```

## Experiment-specific checks

Focused command:

```powershell
python -m pytest -q tests/test_weekly_inner_selection.py tests/test_dev_v2_weekly_inner.py tests/test_football_engine_v2.py tests/test_dev_v2_real_sot.py tests/test_dev_v2_corroborated_sot.py
```

**156 passed, zero failed/skipped** in 37.21 seconds, including **80 new tests**
(25 selector + 55 runner) and 76 unchanged regression tests. The non-overlapping union
with the existing-suite baseline is **2,265 passed, 14 environmental failures, 4 skipped**;
this is a partitioned full-suite gate, not a claim of a single all-green pytest invocation.
Both new modules and both new test files pass targeted Ruff lint/format checks.

The new offline tests cover staged weekly selection, event and same-GW/DGW isolation,
NULL preservation, no SDP feature influence, fixed priors/grid, deterministic tie order,
fold-local scales, truncation equivalence, unchanged legacy source/results, exact control
reproduction and refusal, fixture-PMF reconciliation, unequal-GW cluster uncertainty,
clean provenance and fail-closed one-run orchestration. No real candidate is scored by tests.

Independent review confirmed the single-change boundary and control-before-candidate
ordering. Its reporting suggestion was implemented before scoring: retained inner batches
now contain measured event-time and target-GW-overlap counts, checked before publication.

## Post-run read-only reconciliation

The single formal evaluation finished at clean preregistration commit `507c3d2`; no model was
retuned or run again. An independent reader recomputed **264 overall/slice/fold metric blocks**
from **4,560 retained PMFs**, verified **2,280 unique sides / 1,140 reciprocal fixtures / 114 GWs**
and all targets against the read-only archive, reconciled parameter distributions/transitions/
entropies, **1,368 inner-stage batch guards**, paired losses and the row-weighted GW-cluster SE,
and checked every recorded source/config/database/frozen-result/claim hash. **31,265 checks,
zero discrepancies.** The result and its preregistration remain unchanged.
