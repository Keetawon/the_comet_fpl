# Weekly-inner SOT verification

Date: 2026-09-07. Working branch: `claude/comet-fpl-v2-architecture-mqrj8f`.
Starting and independently verified remote HEAD: `9228892ba2abda80dd8dc8011c93302c6aad9710`.
Infrastructure commit: `adfa948` (revision-safe PIT and persistent local daily capture).
No main synchronization, merge, rebase, push or PR was performed.

## Pre-evaluation checks

Python: `D:/Personal/fpl-operations/.venv/Scripts/python.exe`, 3.12.14.
All commands run from the V2 worktree except dashboard checks, which use its `dashboard/`.
Database/source verification is read-only; no forecast or historical candidate was run here.

- Fresh infrastructure-focused checks: 80 passed (59.24s). A fixed test cutoff exposed a
  wall-clock-dependent synthetic capture; the test now pins its capture to synthetic `NOW`.
  No production capture-time behavior changed.
- New weekly-SOT synthetic checks: 46 passed (21.64s), including frozen control reproduction,
  differing reference/model cold labels, fold-local scaling, DGWs, earliest-version/null/
  identity/prospective boundaries, and claim/failure-order/write-once safeguards.
- Existing full-suite partition: **2,312 passed, 15 failed, 4 skipped**, 5,194 warnings,
  447.35s. Together with the 46 new tests the disjoint union is **2,358 passed, 15 failed,
  4 skipped**. Fourteen failures are unchanged `tests/test_bi_export.py` symlink operations
  (`WinError 1314`). One additional failure was
  `TestHttpSurface.test_manager_routes_require_same_machine_authorization[/manager-team/members-body2]`:
  Windows aborted the local HTTP connection (`WinError 10053`). A focused unchanged-code
  rerun of that entire authorization group passed **5 tests**, 67 deselected, in 3.19s.
  The latter is a transient host/network failure, not silently removed from the full-run
  record. No SDP/model failure occurred. Four publication skips also concern symlink privilege.
- Ruff lint: passed. Strict mypy: passed, 142 source files.
- Format check: 11 pre-existing offenders, 327 formatted files; no new-file format failure.
  Offenders are `src/fpl/insights/{contracts,evidence}.py`,
  `src/fpl/publish/{contract,dashboard_json,export}.py`, and
  `tests/{test_bi_export,test_bi_semantic_contract,test_dashboard_json,test_insights,`
  `test_public_dashboard,test_snapshot_workflows}.py`. They were not reformatted.
- Dashboard: 312 tests across 38 files passed; build and lint passed. Existing bundle-size
  and React fast-refresh export warnings remain. No frontend file changed.
- Independent source review found no blocking evidence-boundary/reproduction issue after
  runtime-version provenance was added. Formal confidence still requires actual control
  reproduction before candidate scoring.
- The pinned source audit reproduced all 1,900 raw payloads and the original coverage/
  interpretation record. Frozen DB SHA remained
  `0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8`.

The default Windows pytest temp directory was inaccessible (`WinError 5`), before test
execution. Fresh explicit test-only `--basetemp` directories avoid that ACL issue; no
unrelated temp directories or data were deleted. Existing symlink privilege failures must
still be reported separately; this is not an unqualified green repository gate.

## Commands and logs

With the Python executable above, full coverage is the union of these disjoint commands:

```powershell
python -m pytest -q --tb=short --ignore=tests/test_dev_v2_weekly_sot.py --basetemp D:/Personal/fpl-operations/verification/weekly-sot-fullgate-20260907-a
python -m pytest tests/test_dev_v2_weekly_sot.py -q --tb=short --basetemp D:/Personal/fpl-operations/verification/weekly-sot-newgate-20260907-a
python -m ruff check src tests
python -m ruff format --check .
python -m mypy src
# in dashboard/
npm.cmd test
npm.cmd run build
npm.cmd run lint
```

New logs under `D:/Personal/fpl-operations/verification/`:
`weekly-sot-20260907-{pytest,new-tests,ruff-final,format-final,mypy}.log` and
`weekly-sot-20260907-dashboard-{tests,build,lint}.log`. Earlier first-pass logs are retained.
The local HTTP recheck is `weekly-sot-20260907-http-recheck.log`; command:
`python -m pytest tests/test_plan_server.py -k test_manager_routes_require_same_machine_authorization -q --tb=short --basetemp D:/Personal/fpl-operations/verification/weekly-sot-http-recheck-20260907-a`.
The disjoint partition lets the unchanged full suite run while the new synthetic test file
receives final review; neither partition trains on the historical evaluation population.
