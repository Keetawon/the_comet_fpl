# Corroborated-zero SOT: pre-evaluation verification

Date: 2026-09-06 (Asia/Bangkok). Starting branch HEAD:
`58f7b4e01a403aa806d25141f931fec42be842b4`.
Branch: `claude/comet-fpl-v2-architecture-mqrj8f`. No new formal evaluation had run when this
record was prepared; the implementation and preregistration are committed before that run.

The existing Windows environment is
`C:/Users/keetawatw/AppData/Local/Temp/the_comet_fpl_runtime/Scripts/python.exe`:
Python 3.14.7, Ruff 0.16.0, mypy 2.3.0. This is not a claim that the separate Python 3.12 CI gate
ran. The shared pytest temporary root was access-denied, so subsequent tests used fresh,
uniquely named temporary directories under the ignored worktree `.pytest_cache/`. No application
code or test assertion was changed to bypass an environmental restriction.

| Check | Exact result |
|---|---|
| New audit and successor tests | 56 passed, 0 failed (8.41 seconds) |
| SDP / retrospective / PIT / engine / SOT regression set | 241 passed, 0 failed (29.76 seconds) |
| Full `pytest -q --tb=short` | 2,185 passed, 14 failed, 4 skipped, 5,194 warnings (304.23 seconds) |
| `ruff check src tests` | Passed |
| `ruff format --check .` | Failed: 11 untouched files; 308 already formatted |
| Format check on all four new Python files | Passed |
| `mypy src` | Passed: 137 source files |
| Dashboard `npm test` | 312 tests passed in 38 files |
| Dashboard `npm run build` | Passed; existing large-chunk warning |
| Dashboard `npm run lint` | Passed; nine existing Fast Refresh warnings |
| Coverage-only raw revalidation | 1,900 payloads verified; selected seasons unchanged |

The dashboard dependencies were restored with `npm ci --no-audit --no-fund` from this branch's
lockfile. The main worktree's dependency tree and lockfile were not substituted or modified.

## Environmental and pre-existing failures are not called green

All 14 pytest failures are in `tests/test_bi_export.py`, at the unchanged
`src/fpl/publish/export.py` directory-symlink publication call (`os.symlink`, line 2367), with
`OSError: [WinError 1314] A required privilege is not held by the client`:

- `test_export_writes_complete_contract_and_preserves_nulls`
- `test_team_fixture_ease_indices_are_directed_and_keep_raw_lambdas`
- `test_append_only_player_and_team_outcomes_export_as_separate_vintage_free_facts`
- `test_low_coverage_and_non_positive_denominators_publish_real_nulls`
- `test_official_fdr_is_separate_and_cannot_change_ease_indices`
- `test_genuinely_unavailable_official_fdr_stays_null`
- `test_zero_recorded_runs_is_a_complete_export`
- `test_legacy_v1_vintage_with_no_fixture_rows_is_still_complete`
- `test_export_rejects_season_scoped_referential_integrity_violation`
- `test_source_schema_drift_cleans_temporary_export_and_keeps_previous_publish`
- `test_exports_are_byte_deterministic_except_manifest_created_at`
- `test_concurrent_writer_is_refused_without_clobbering`
- `test_live_season_dimensions_are_sourced_from_the_snapshot_registry`
- `test_archive_database_exports_the_complete_contract`

The four existing `REQUIRES_SYMLINK` skips in `tests/test_dashboard_json.py` are:

- `test_publication_is_reproducible_and_validates`
- `test_concurrent_writer_is_refused_and_unmanaged_targets_are_never_clobbered`
- `test_tampered_source_leaves_the_published_endpoint_intact`
- `test_archive_parquet_export_feeds_valid_read_models`

All cite the same missing directory-symlink privilege. The 5,194 full-suite warnings are existing
PuLP deprecation warnings. No publication or optimizer code was changed by this task.

Ruff's 11 format offenders also remain untouched:

`src/fpl/insights/contracts.py`, `src/fpl/insights/evidence.py`,
`src/fpl/publish/contract.py`, `src/fpl/publish/dashboard_json.py`,
`src/fpl/publish/export.py`, `tests/test_bi_export.py`, `tests/test_bi_semantic_contract.py`,
`tests/test_dashboard_json.py`, `tests/test_insights.py`, `tests/test_public_dashboard.py`,
`tests/test_snapshot_workflows.py`.

Thus the relevant model/data gates pass, but the full repository gate is **not unqualified
green**. A symlink-capable Windows shell/Developer Mode or the established Linux environment is
needed to exercise publication successfully; unrelated formatting requires its own cleanup.
Neither is a reason to weaken the SOT evidence boundary or rewrite frozen source artifacts.

## Guard evidence

Tests establish exact toy-data equivalence with the old baseline/control and unchanged SOT
candidate when no interpretation is supplied; these tests do not rerun a real frozen evaluation.
They also establish zero-vs-NULL separation, raw content and team identity checks, earliest-version
selection, target-GW and future-stat exclusion, physical truncation equivalence, fold-local
scaling, fallback, deterministic normalized PMFs, exact retained-score reconciliation, no
production imports, frozen source/result hashes, dirty-worktree refusal and write-once output.

Read-only revalidation agrees byte-for-byte with every recorded audit field. The old first-SOT
result, old V2 result, all eight prior evaluator/model source hashes and the archive database
remain unchanged. The new runner rechecks these identities and clean provenance around its one
formal outer run. This verification record is not itself a performance result.
