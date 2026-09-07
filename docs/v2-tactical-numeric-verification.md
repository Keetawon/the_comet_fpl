# Numerical amendment verification (2026-09-07)

Prerequisite checks before the single formal amended fit. The full repository gate is
**not entirely green**; no unrelated environment/UI/format repair is hidden in this change.

Permanent interpreter: `D:\Personal\fpl-operations\.venv\Scripts\python.exe`, Python 3.12.14.
Worktree: `D:\Personal\workspace\the_comet_fpl\.worktrees\sdp_test`.
New logs: `D:\Personal\fpl-operations\verification\tactical-numeric-20260907`.

| Check | Result |
| --- | --- |
| Existing full Python partition | 2,496 passed / 15 failed / 4 skipped, 719.41 s |
| Isolated unchanged manager-route diagnostic | 5 passed, 3.55 s; does not erase first failure |
| Final new amendment tests | 74 passed, 3.36 s |
| Affected tactical/PIT/retrospective tests | 229 passed, 71.50 s; includes 44 of the 74 new tests |
| Unique new + affected Python checks | 259 passed (229 + 30 runner tests), no failures/skips |
| Final Ruff lint src/tests | Pass |
| Final strict mypy src | Pass, 149 source files |
| Format, eight new/changed Python files | Pass |
| Full format check | 11 unchanged files fail / 351 already formatted |
| Dashboard tests, maxWorkers=1 | 312 passed / 38 files, 183.21 s |
| Dashboard build | Pass; existing >500 kB bundle warning |
| Dashboard lint | Pass; nine existing fast-refresh warnings |

The full Python collection started at clean `464c86f`; implementation appeared while it
was running, so it is existing-suite prerequisite evidence, not a clean final-source run.
New tests were not in that collection. The separate final affected partition covers all
changed behavior, including the default legacy selector/solver plumbing. Do not add test
counts across overlapping runs or relabel this as a wholly green full suite.

## Exact remaining failures

Fourteen `tests/test_bi_export.py` cases fail at the unchanged Windows `os.symlink` call,
`src/fpl/publish/export.py:2367`, `WinError 1314` (required privilege not held):

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

The fifteenth failure is
`test_plan_server.py::TestHttpSurface::test_manager_routes_require_same_machine_authorization[/manager-team/capture-body1]`:
localhost `ConnectionAbortedError: WinError 10053` while reading a response. The same unchanged
five-parameter test passes in isolation. No tactical call or source edit is involved.
Four skips are the pre-existing Windows symlink-privilege dashboard-export skips.

Unchanged full-format failures: `src/fpl/insights/contracts.py`, `evidence.py`;
`src/fpl/publish/contract.py`, `dashboard_json.py`, `export.py`;
`tests/test_bi_export.py`, `test_bi_semantic_contract.py`, `test_dashboard_json.py`,
`test_insights.py`, `test_public_dashboard.py`, `test_snapshot_workflows.py`.

## Commands and logs

```text
python -m pytest -q --ignore tests/test_tactical_numeric_solver.py --ignore tests/test_dev_v2_tactical_numeric.py --basetemp <logs>/pytest-existing-temp
python -m pytest tests/test_dev_v2_tactical_numeric.py tests/test_tactical_numeric_solver.py tests/test_tactical_numeric_integration.py -q --basetemp <logs>/new-final-temp-2
python -m pytest tests/test_tactical_numeric_solver.py tests/test_tactical_numeric_integration.py tests/test_tactical_math.py tests/test_tactical_matchup.py tests/test_dev_v2_tactical_matchup.py tests/test_tactical_state.py tests/test_point_in_time.py tests/test_pl_sdp_revision_pit.py tests/test_retrospective_sdp.py -q --basetemp <logs>/affected-temp-3
python -m ruff check src tests
python -m ruff format --check .
python -m mypy src
npm test -- --maxWorkers=1
npm run build
npm run lint
```

Logs: `pytest-existing.log`, `plan-server-recheck.log`, `new-final-tests-2.log`,
`affected-tests-3.log`, `ruff-final.log`, `ruff-format-final.log`, `mypy-final.log`,
`dashboard-test.log`, `dashboard-build.log`, `dashboard-lint.log`.
Full Python log SHA256: `107f4c5c31e0b60553b64bf7d293916b49bcf0f7b355c151770f67d7f8c73075`.

During implementation, an initial test-file selection referenced a nonexistent audit test
(no tests ran), and a subsequent affected run had eight test-double signature failures
after adding the explicit candidate label keyword. The sole existing-test change accepts
that optional label in its mocked scorer; its eight gate cases/expectations are unchanged.
The corrected affected run above passes. A new test's initial module import was corrected
before its passing runs. These were pre-preregistration implementation checks, not formal
candidate runs, and involved no real historical model fitting.

The new solver has 39 synthetic tests, including independent Decimal-80 objective-increment
checks and a legacy false-convergence example; the runner has 30 synthetic tests and the
loop integration has five. Independent review found no blocking invariant/numerical issue.
The precise old real-fold failure remains unconfirmed; no replay recovered that matrix.

Research database hash remains
`0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8`;
the root database remains
`b886977a4603a9c8b6dea2e0ed6652d2b4864a71fc707b54201ac8fb1656f2ce`.
No prior result/config, original solver, prospective/PIT source or default was modified.
