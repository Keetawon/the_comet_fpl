# SDP primary activation: operational verification, 2026-09-07

**Owner-directed architectural adoption. SDP-backed V2 is the primary football-environment
architecture. Historical experimental verdict remains INCONCLUSIVE under its frozen gate.
Incumbent retained as operational fallback and prospective shadow comparator.**

This is an operational implementation record, not a research evaluation. See the
[decision](sdp-primary-architecture-decision-2026-09-07.md) and [runbook](sdp-primary-operations.md).
No candidate was fitted, retuned or historically evaluated. The incumbent's normal prospective
component estimation and seeded composition still run as before.

## Checkout and frozen evidence

The requested repository root was a separate `main` worktree. Work took place entirely in the
existing clean V2 worktree `D:/Personal/workspace/the_comet_fpl/.worktrees/sdp_test`, on
`claude/comet-fpl-v2-architecture-mqrj8f`, starting at the exact requested
`a2f7e0c53f38ca680864dbe2923ffbc5f89256bf`. Its parent main worktree and pre-existing untracked
files were preserved. Local main remained `ede17377216807ca2635879d1153e268dcd04fe6`; remote
main/default HEAD remained `4a58f079057d79189bd31a782e5f3c860b3c097f` at verification.
No main merge, PR or default-branch change was performed or authorized.

All 67 previously tracked `results` files and 37 previously tracked configuration files remain
unchanged. The original tactical/chance source files and scientific gates remain unchanged.
The shared `config.py` is also unchanged: the new operational policy uses a separate module
over the same Pydantic/YAML conventions. The changed production wrapper's historical research
fingerprint is still checked against its original Git revision and original Windows bytes;
the frozen contract/result hashes are not updated to today's wrapper. The production import
guard permits only the adapter's exact pure inference imports, retaining the ban on retrospective
readers, fitting functions and development runners.

The frozen research DB remains SHA256
`0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8`.
Only the separate operational copy `D:/Personal/fpl-operations/data/sdp-primary-v2.duckdb`
was refreshed. Its forecast-bound SHA256 is
`b0803710312565d70015adedc5f223a9acc84c04e46578908157037a511437b5`.

## Live activation and exact replay

Implementation commit: `6fdc4acb7d357ecee39792ab8968e5baa82505f6`.
Final inference/publication commit: `1dc271b53aeb3aa21d7d4033d763d4a8a8684189`.
The latter fixes only ordering of H shadow provenance, with a registry-row-permutation regression
test. The initial primary and shadow files were retained. Every initial player and team PMF is
identical to the corrected vintage; the correction changes no numerical forecast.

The FPL freshness gate correctly found missing GW3 history. A full official refresh captured
654 player summaries and 657 endpoints in total. The clean pre-deadline command then refreshed
FPL again, refreshed recent SDP, normalized, checked health, captured workload, and generated
GW4-8 with the default 2,000 draws. Its `--skip-player-history` option avoided repeating the
just-completed complete sweep; the existing freshness gate still passed independently.

```powershell
python -m fpl.jobs.daily_snapshot --db D:/Personal/fpl-operations/data/sdp-primary-v2.duckdb --player-history
python -m fpl.jobs.pre_deadline_forecast --db D:/Personal/fpl-operations/data/sdp-primary-v2.duckdb --runs D:/Personal/fpl-operations/sdp-primary-runs --gw-from 4 --gw-to 8 --output D:/Personal/fpl-operations/predictions/sdp-primary-v2-20260907-gw4-8.jsonl --skip-player-history
```

The final `-r2` vintage and its replay use the same exact cutoff, refreshed DB, report, seed and
draws through the normal `prospective_points_v1` CLI. Both complete files reproduce **byte for
byte in separate Python processes**, including their provenance. The authoritative final files
are under `D:/Personal/fpl-operations/predictions/`:

| Artifact | SHA256 |
| --- | --- |
| `sdp-primary-v2-20260907-gw4-8-r2.jsonl` | `413e817eb965b328af3b4cd99102584bd4f8b51eb283c418c76e8f37ca7f0be9` |
| `sdp-primary-v2-20260907-gw4-8-r2.shadow-incumbent.jsonl` | `1f33c63fd95f923cae58e9c4d27c5762d3e7707a204163419383b3271daf6919` |

Cutoff: `2026-09-07T15:20:00.757039+00:00`. FPL snapshot known at
`2026-09-07T15:09:28.407423+00:00`. Population: 654 players, 50 fixtures, 3,270
player-gameweek rows, 3,270 player-fixture rows and 100 team-fixture rows, in each full artifact.

| Selection | Fixtures | Team predictions | Player-fixture predictions |
| --- | ---: | ---: | ---: |
| `SDP_PRIMARY` | 21 | 42 | 1,368 |
| `SDP_INCOMPLETE_FALLBACK` | 29 | 58 | 1,902 |

The 58% team-prediction fallback rate is reported, not hidden. Four recent matches lack core
fields, and their affected clubs fail the required recent-history gate. No missing field was
turned into zero to increase primary coverage. H has 355 shadow records, of which 164 have a
source-supported conditional PMF; the others retain NULL. H never enters production scoring.

The independent artifact-reader reconciliation checked both file schemas, hash binding, all
SDP/FPL/workload knowledge times against cutoff, exact opponent-PMF zero-mass clean sheets,
unchanged player component modes, and exact incumbent team **and player** output on every mixed
fallback fixture. It also checked byte-identical replay of both complete files.

## Capture and workload

The pre-deadline cycle finished at `2026-09-07T15:20:00.746604+00:00` with no capture failures:
30 expected completed EPL matches, 30 retained, 26 core-valid, zero schema-validation failures
and zero identity failures. Required field omissions are classified separately as incomplete.
Latest completed kickoff: `2026-09-06T15:30:00+00:00`. Capture success rate: 1.0; age since
successful capture at cycle completion: zero hours. Unchanged payloads retained their original
knowledge times despite successful refresh requests.

All six competition catalogues were reachable. Ten recent EPL lineup/event bundles were
captured and valid. FA Cup, League Cup, Champions League, Europa League and Conference League
had no eligible completed matches in this five-day window. Their workload normalization is
covered by offline tests; this run does not claim live cup-minute coverage that did not occur.
No cup tactical stats were requested or admitted to EPL state. Exact complete workload totals
and physical rest remain unavailable where their completeness/whistle evidence is absent;
positive witnessed exposure is explicitly a lower bound.

Windows task **The Comet FPL - SDP primary V2** is registered and Ready, daily at **07:00
Asia/Bangkok**, next run `2026-09-08T07:00:00+07:00`. It uses the persistent `pythonw.exe`, the
V2 checkout, the separate operational DB, and `daily_pl_sdp --workload` (five-day CLI default).
It requires the owner to be signed in. The existing **The Comet FPL - daily SDP** task was not
overwritten. Pre-deadline refresh remains available regardless of whether a daily run was missed.

## Tests and inherited limitations

| Check | Result |
| --- | --- |
| Broader suite, excluding `tests/test_bi_export.py`, implementation source | **3,610 passed, 4 skipped**, 520.53 seconds |
| Final focused suite after provenance-order correction | **91 passed**, 90.98 seconds |
| Tactical/corroborated-SOT/weekly-inner plus new production regression group | **183 passed** |
| Development-reference and retrospective-minutes source/history guards | **78 passed** |
| Ruff check, `src tests` | Pass |
| Strict mypy, `src` | Pass, **196 source files** |
| Format check, all 17 changed Python files | Pass |
| Global format check, `src tests` | **11 inherited unrelated files would be reformatted** |
| BI export module, checked separately | **27 passed, 14 failed**, inherited Windows `WinError 1314` symlink privilege |
| Real primary + full shadow + separate-process replay | All reconciliation checks pass; both files byte-identical |

The broader suite preceded the final ordering-only fix; the final focused suite adds an explicit
registry permutation and checks complete provenance equality. No repository-wide pass is claimed.
The default Windows pytest temporary directory also returned `WinError 5`; reported verification
runs use explicit writable basetemp directories under the operations verification directory.

Inherited formatting files: `src/fpl/insights/{contracts,evidence}.py`,
`src/fpl/publish/{contract,dashboard_json,export}.py`, and
`tests/test_{bi_export,bi_semantic_contract,dashboard_json,insights,public_dashboard,snapshot_workflows}.py`.
These were not reformatted as part of the architecture task. Existing PuLP deprecation warnings
remain in the broader test log.

Local receipts under `D:/Personal/fpl-operations/verification/`:

- `sdp-primary-live-reconciliation.json` and `verify_sdp_primary_artifacts.py`;
- `sdp-primary-scheduled-task.json`;
- `sdp-primary-broader-final-02.{log,xml}`;
- `sdp-primary-determinism-final-11.log`;
- `sdp-primary-bi-export-01.log` and `sdp-primary-format-global.log`;
- `sdp-primary-pre-deadline-01.log`, `sdp-primary-fpl-history-01.log`, and
  `sdp-primary-final-publication-and-replay-02.log`.

The full refresh receipt is in
`D:/Personal/fpl-operations/sdp-primary-runs/pre-deadline-20260907T150922.262300Z/`
under its unique cycle directory, together with its backup, inventory and normalization audits.
Its content and SHA256 are embedded in the forecast provenance.

## Files changed

The delivery changes 31 files, including this verification record:

- Policy and frozen inference copies: `.gitattributes`, `config/football_environment.yaml`,
  `config/sdp_v2_frozen_parameters.json`, `config/sdp_gk_shadow_parameters.json`.
- Documentation: `AGENTS.md`, `README.md`, `docs/pl-sdp-data-source.md`,
  `docs/pl-sdp-revision-pit-and-local-daily.md`, `docs/prospective-points-artifact.md`,
  `docs/v2-architecture.md`, `docs/sdp-primary-architecture-decision-2026-09-07.md`,
  `docs/sdp-primary-operations.md`, and this file.
- Runtime contracts and readers: `src/fpl/football_configuration.py`,
  `src/fpl/artifacts/fixture_environment.py`, `src/fpl/features/sdp_workload.py`,
  `src/fpl/storage/sdp_runtime.py`, `src/fpl/models/sdp_environment.py`.
- Jobs/schedule: `scripts/register_daily_pl_sdp.ps1`, `src/fpl/jobs/capture_pl_sdp.py`,
  `src/fpl/jobs/capture_sdp_workload.py`, `src/fpl/jobs/daily_pl_sdp.py`,
  `src/fpl/jobs/export_sdp_runtime_parameters.py`, `src/fpl/jobs/pre_deadline_forecast.py`,
  `src/fpl/jobs/prospective_points_v1.py`.
- Tests: `tests/frozen_source_checks.py`, `tests/test_sdp_primary.py`,
  `tests/test_sdp_production_workload.py`, `tests/test_dev_v2_tactical_matchup.py`,
  `tests/test_development_reference_components.py`, `tests/test_retrospective_minutes_proxy.py`.
