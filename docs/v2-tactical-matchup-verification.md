# Tactical Matchup V1 verification record

Local Windows, 2026-09-07. Permanent Python:
`D:\Personal\fpl-operations\.venv\Scripts\python.exe` (3.12.14).
Worktree: `D:\Personal\workspace\the_comet_fpl\.worktrees\sdp_test`.
Logs: `D:\Personal\fpl-operations\verification\tactical-20260907`.

## Before formal evaluation

No real tactical estimator was fitted or scored during implementation/audit/testing.
Tests use synthetic observations; the real database was opened read-only for coverage,
source/version and state-reader inspection. Independent source review found no blocking
event-time, same-GW, stacking, population or provider-version defect. The frozen historical
schedule has no source match starting less than three hours before another GW cutoff;
kickoff remains an explicitly documented historical completion/availability proxy.

Executed from the V2 worktree with the permanent Python:

```text
python -m pytest -q --ignore-glob tests/test_tactical_*.py --ignore tests/test_dev_v2_tactical_matchup.py --basetemp D:\Personal\fpl-operations\verification\tactical-20260907\full-temp
python -m pytest tests/test_tactical_math.py tests/test_tactical_state.py tests/test_tactical_matchup.py tests/test_dev_v2_tactical_matchup.py -q --basetemp D:\Personal\fpl-operations\verification\tactical-20260907\new-final-temp
python -m ruff check src tests
python -m ruff format --check src tests
python -m mypy src
```

The existing-suite partition: **2,359 passed, 14 failed, 4 skipped**, 510.22 seconds.
All 14 failures are unchanged `tests/test_bi_export.py` export tests reaching
`src/fpl/publish/export.py:2367`, Windows `WinError 1314` on `os.symlink` without the required
privilege. No tactical code enters that path. The four skipped tests are existing Windows
symlink-environment skips. These are retained environmental failures, not a green full gate.
See `pytest-existing.log` for exact test names and traces.

The disjoint new-test partition: **138 passed**, 3.77 seconds (`pytest-new.log`).
Combined complete Python test population: **2,497 passed, 14 failed, 4 skipped**.
Do not double-count the earlier 66-test state/reader subset or agent-local checks.

Ruff lint passes (`ruff-final.log`). Strict mypy passes all **147 source files**
(`mypy-final.log`). The complete format check reports **11 unchanged files** needing
formatting, 248 already formatted (`format-final.log`):

- `src/fpl/insights/contracts.py`, `src/fpl/insights/evidence.py`;
- `src/fpl/publish/contract.py`, `src/fpl/publish/dashboard_json.py`, `src/fpl/publish/export.py`;
- `tests/test_bi_export.py`, `tests/test_bi_semantic_contract.py`, `tests/test_dashboard_json.py`,
  `tests/test_insights.py`, `tests/test_public_dashboard.py`, `tests/test_snapshot_workflows.py`.

All new tactical files are formatted. These pre-existing frontend/publishing formatting
differences were not silently repaired in a model experiment.

The implementation adds only validation modules/tests and additive contracts/evidence.
No existing model, production reader, provider metric dictionary, optimizer, dashboard,
workflow or frozen result is edited. Research database SHA256 remains
`0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8`.
The original root database and operational daily database are not used or written.

The formal runner requires clean committed provenance, reproduces the incumbent against
retained PMFs and the actual prospective helper, and only then reserves an exclusive durable
claim. A disappointing result or a failure after that claim cannot authorize another run.

## Dashboard gate (unchanged UI)

Node 24.19.0, npm 11.17.0, actual `dashboard/package.json` scripts:

- `npm test`: **308 passed, 4 failed**, 35/38 files passed. Three existing interactive
  tests exceeded their 5-second timeouts (PlanBuilderPage, PlayersPage, UserDraftPage),
  followed by a PlayersPage checkbox lookup failure.
- The three failed files run once with `--maxWorkers=1` and unchanged timeout: **70/70
  passed**, 3/3 files. Failures did not reproduce serially; do not erase the initial failure
  record or count this subset as additional full-suite passes.
- `npm run build`: passed, 2,064 modules, existing >500 kB bundle warning.
- `npm run lint`: passed with nine existing React fast-refresh warnings.

Logs are `dashboard-test.log`, `dashboard-failed-files-serial.log`, `dashboard-build.log`,
and `dashboard-lint.log` in the same external verification directory. No dashboard source
was changed. Full repository gate is explicitly **not entirely green**; relevant new model
tests, source lint and strict typing are green. No environmental failure is silently fixed.

Two new tactical JSON evidence paths have byte-preserving Git attributes so Windows automatic
newline conversion cannot change their committed fingerprints. Prior artifacts are untouched.

## Sole attempted formal execution and independent failure check

The run at clean SHA `672a36d9d6fc446bb7492eb89eebd63f15bee860` exited1 during historical
batch123/189 (2024-25GW10), after exact incumbent reproduction. See the development report;
this is not a successful model evaluation. `formal-once.log` SHA256:
`319534fd65bbb7803042b898a3663948de23ff672b67f2d38f84f120a6c93bca`.

Independent read-only `independent-failure-verification.json` (external log directory)
confirmed one claim/start, no normal publication, unchanged implementation/config/database,
18 preserved prior result artifacts, exact incumbent NLL/CRPS and reciprocal CS arithmetic.
It checked absence BEFORE the additive execution-failure marker was written. Current
handoff docs were correctly reported as dirty; this was not relabelled successful runner
postflight. The unchanged local claim SHA256 is
`ef89aa2b510d35ea34fadc18db18999e22ba366c322dbc9f76c73d8f3a6c1733`.

No real-data replay or solver fix followed. The fixed result path now contains an explicit
incomplete execution-failure record, with null candidate metrics, so the existing write-once
guard also blocks fresh-checkout restarts. Its JSON, source/config/log fingerprints and local
paths were checked without invoking the formal runner again. No successful prediction,
stacking-trace reconciliation or paired uncertainty is claimed for the interrupted candidate.
