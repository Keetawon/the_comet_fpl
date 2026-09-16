# Workspace and host paths

The owner authorized simplifying navigation and reconnecting existing services.
This change adds one entry point and three shortcuts; Python source, model/config
files, scientific evidence, forecasts and dashboard data are preserved.

## Open and run

Open `D:/Personal/workspace/the_comet_fpl/.worktrees/v2/THE-COMET.code-workspace`.
The workspace hides generated files in the editor; they remain on disk. Use its
**Run Task** menu or run these commands from the checkout:

```powershell
./scripts/comet.ps1 start
./scripts/comet.ps1 refresh
./scripts/comet.ps1 status
```

`start` launches the existing dashboard preview and optimizer, hidden with logs
under `D:/Personal/fpl-operations/services`. URLs are local-only:
<http://127.0.0.1:4173/> and <http://127.0.0.1:8765/>. It selects the latest registered
primary using the pipeline's existing hash check. An unrelated or stale process
on either port fails closed; the shortcut does not kill it. Repeated startup leaves
matching services running. A newly registered forecast requires an explicit idle
optimizer restart; the command does not hot-swap a running job.

`refresh` invokes the existing full capture/export/build pipeline with explicit
operational paths and its existing writer locks/backups. It can reuse or create
an optimizer plan under the unchanged procedure. It does not generate forecasts.
`status` reads capture health and the primary task's last/next execution.
`start -WhatIf` and `refresh -WhatIf` are safe host smoke checks: imports and primary
identity are validated but services/capture are not launched. An editable Python
install pointing to another checkout fails before a database action.

## What lives where

| Path | Meaning |
|---|---|
| `.worktrees/v2` | New logical entry, junction to the existing V2 checkout |
| `.worktrees/sdp_test` | Preserved physical V2 worktree; still registered in Git |
| Repository root | Existing main checkout, not the active V2 command directory |
| `../the_comet_fpl-fbref-ingest` | Separate pre-existing worktree, untouched |
| `D:/Personal/fpl-operations/.venv` | Existing Python environment for operations |
| `D:/Personal/fpl-operations/data` | Explicit operational databases |
| `D:/Personal/fpl-operations/predictions` | Immutable registered forecast vintages |
| `D:/Personal/fpl-operations/dashboard-runs` | Capture/publication receipts and backups |
| `D:/Personal/fpl-operations/dashboard-plans` | Existing reusable platform plans |
| `D:/Personal/fpl-operations/plan-server` | Preserved private optimizer state |

Windows refused the physical worktree rename with `Permission denied`. No partial
move occurred. A junction provides the new entry without interrupting IDE handles
or invalidating existing paths. Python/editable installs may print the resolved
physical `sdp_test` path; this is expected and was verified to be the same checkout.
Tools that reject junction paths should edit through `sdp_test`. The source tree
was not rearranged; import paths and historical references remain intact.

Private optimizer state moved from the main checkout's
`data/plan-server/refresh-20260903T021900Z` to the operations path. All 45 files were
SHA256-verified before/after; a junction at the former path preserves old callers.
Historical filenames in that directory retain their original meanings. The
launcher supplies an explicit current forecast instead of relying on those names.

Both existing Scheduled Tasks now use `v2` as WorkingDirectory. The primary task's
dashboard public output uses `v2/dashboard/public`. All triggers, principals and
settings remain identical to their pre-change XML. The legacy task still uses its
separate `operational.duckdb`; it was not merged into the primary task.
The four-hour/sign-in policy is unchanged. Tasks were briefly disabled for path
maintenance around 11:00 Bangkok and re-enabled; no 11:00 firing is claimed.
At verification the next primary run was 15:00 and the last task result was 0.
The separate legacy task was Ready but its preceding result was 1; that existing
failure is not reported as healthy and was not repaired by this path-only task.

An old IDE-launched optimizer still referenced GW3–7 and the main environment.
After confirming it was idle, only its launch shell and Python processes were
stopped. The IDE was left running. The replacement uses the operational environment,
V2 checkout and retained registered GW5–9 primary hash
`ef208e71e341043993e5d380542b4cfb135c98b97bf4cc0df853cefcf97cc751`.
No forecast was regenerated. Use the new task/shortcut instead of replaying the
old IDE terminal command.

## Verification and rollback

Local migration evidence is retained in
`data/artifacts/workspace-reorganization-20260916/`: task XML before/after, protected
file hashes, private-state hashes, service observations and browser screenshots.
These are local operational receipts, not public dashboard assets.

Restore task actions only after checking the task is idle and inspecting its
current XML for intervening changes. The `primary-before.xml` / `legacy-before.xml`
files describe the pre-migration actions; keep the current schedule/settings if
they changed later. The physical checkout still exists, so old source paths need
no rollback. Never recursively delete either junction as a cleanup shortcut.

The launcher was parsed by PowerShell, exercised with both dry-run actions,
started both services and repeated startup without duplicate listeners. Capture
health was healthy at 2026-09-16T04:09:40Z (about 40 minutes old), with 36 valid
current SDP matches and four provider-incomplete matches; path organization does
not reinterpret missing data. Current exports remain GW4-complete, forecast GW5–9.
Desktop/mobile browser regression covered Next GW, Optimizer audit and both
prediction-versus-actual routes, with no local request, console or runtime errors.
No UI source or published export was changed by this task.

Verification: 91 existing refresh/plan-server tests passed; Ruff and strict mypy
passed on those two Python entrypoints. PowerShell parsing, workspace JSON parsing,
documentation links and `git diff --check` passed. Pytest reported existing PuLP
deprecation warnings and a sandbox cache-write warning. Mypy initially encountered
the same sandbox write restriction; the owner-context check with a separate cache
completed successfully. No Python or TypeScript source changed.

SHA256 comparison preserved all 874 pre-recorded source/config/result/snapshot/test
files, all ten operational forecast artifacts and all sixteen public JSON exports.
The historical README body is retained intact in its expandable section. Main
remained at `ede17377216807ca2635879d1153e268dcd04fe6`. No model inference, research
evaluation, production deployment, merge or destructive cleanup was performed.
