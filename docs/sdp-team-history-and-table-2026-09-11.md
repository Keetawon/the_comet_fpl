# SDP team history and compact comparison table ? 2026-09-11

Owner-requested descriptive dashboard repair. Starting commit: `65234556c32eb90cecec81e0d8d98dca9c5e8174` on `claude/comet-fpl-v2-architecture-mqrj8f`. No model, selector, optimizer, scientific result or forecast was changed.

## What changed

- The team comparison table uses compact desktop rows (28px controls plus 4px cell padding). Coarse-pointer targets remain 44px. Empty sparklines no longer add large padded paragraphs.
- Fullscreen content fills the wrapper?s available height. The table scrolls inside that height; opened comparisons and match logs share a bounded details region. The footer and fullscreen exit stay outside the table scroll area.
- Scatter points carry source-provided club abbreviations, full-name hover/focus details, and deterministic label offsets for nearby points. Leader lines retain the association without moving the observations. Labels stay within the plot; SDP chart provenance says Observed.
- Historical incomplete matches now expose individually measured SDP statistics through the existing descriptive export. Exact retained normalized fixture pairs bind both teams, provider match id, kickoff and raw capture hash; latest raw and metadata are rechecked. Current-match correction policy and all production core-health checks are unchanged.
- A coverage note explains that an incomplete core is different from an entirely missing match. Aggregates still require that metric on every selected match; we do not silently average only the convenient subset. Missing xG cannot place a team on the xG/xGA scatter.

## Retained source audit

All five historical seasons already had 380 retained match-stat payloads. No provider download or backfill was needed. Previously, one missing core statistic hid all other statistics from that fixture in historical exports. This was a descriptive export defect, not proof that capture failed.

Counts below are fixtures except the explicitly labelled team-side SOT column. Every historical season has 760 team sides. xG coverage refers only to these retained SDP payloads, not a claim about other possible archives.

| Season | Raw fixtures | Unchanged provider core-valid | xG fixtures before ? after | SOT measured team sides after | Shots / passing / possession after |
|---|---:|---:|---:|---:|---|
| 2021-22 | 380 | 3 | 3 ? 3 | 739 | 760 / 760 / 760 team sides |
| 2022-23 | 380 | 2 | 2 ? 2 | 738 | 760 / 760 / 760 team sides |
| 2023-24 | 380 | 3 | 3 ? 3 | 754 | 760 / 760 / 760 team sides |
| 2024-25 | 380 | 159 | 159 ? 170 | 740 | 760 / 760 / 760 team sides |
| 2025-26 | 380 | 363 | 363 ? 380 | 744 | 760 / 760 / 760 team sides |
| 2026-27 | 30 | 26 | 30 ? 30 | 56 | 60 / 60 / 60 team sides |

For 2025/26, all 20 clubs now have complete full-season xG/xGA and can appear in the scatter. The 17 incomplete fixtures below still have incomplete provider core evidence: 16 omit SOT and one omits shots inside the box. Their other measured statistics are displayed. No missing historical SOT or xG was converted to zero.

| Fixture | Home | Away | SDP match | Missing core field |
|---:|---|---|---:|---|
| 34 | BUR | LIV | 2561928 | `ontargetScoringAtt` |
| 35 | CRY | SUN | 2561929 | `ontargetScoringAtt` |
| 61 | ARS | WHU | 2561956 | `ontargetScoringAtt` |
| 74 | FUL | ARS | 2561968 | `ontargetScoringAtt` |
| 92 | BUR | ARS | 2561986 | `ontargetScoringAtt` |
| 103 | CHE | WOL | 2561997 | `ontargetScoringAtt` |
| 111 | ARS | TOT | 2562006 | `attemptsIbox` |
| 130 | WHU | LIV | 2562024 | `ontargetScoringAtt` |
| 173 | BUR | EVE | 2562067 | `ontargetScoringAtt` |
| 200 | WOL | WHU | 2562094 | `ontargetScoringAtt` |
| 201 | ARS | LIV | 2562096 | `ontargetScoringAtt` |
| 217 | NFO | ARS | 2562111 | `ontargetScoringAtt` |
| 238 | SUN | BUR | 2562132 | `ontargetScoringAtt` |
| 295 | CRY | LEE | 2562189 | `ontargetScoringAtt` |
| 322 | BRE | FUL | 2562216 | `ontargetScoringAtt` |
| 333 | BHA | CHE | 2562227 | `ontargetScoringAtt` |
| 361 | ARS | BUR | 2562256 | `ontargetScoringAtt` |

For older seasons, missing `expectedGoals` is present in the retained raw itself: 377 fixtures in 2021/22, 378 in 2022/23, 377 in 2023/24 and 210 in 2024/25. The 2024/25 season also has 11 xG-covered fixtures with omitted SOT. Full-season xG averages/scatter therefore remain unavailable for these incomplete histories; shots, passes and possession remain usable. Narrower selected ranges can show xG where coverage is complete.

Current 2026/27 stays at 30 fixtures across GW1?GW3: 26 provider core-valid plus four owner-confirmed dashboard-valid. The nine direct owner corrections retain their original evidence. The existing sparse-count assumption allowlist is reused, with separate markers/provenance; no new zero rule was introduced.

## Publication, timestamps and reconciliation

- The old public export is retained as `D:/Personal/fpl-operations/verification/sdp-table-history-20260911/sdp_stats_before.json`.
- New immutable export and receipts: the same directory contains `sdp_stats.json`, `export_receipt.json`, `coverage.json`, and `preservation_after.json`.
- Export as-of: `2026-09-11T09:14:28.063796+00:00`. Latest eligible SDP capture: `2026-09-11T02:00:25.273378+00:00`; FPL fixture enrichment: `2026-09-09T05:41:30.018462+00:00`. This export reused already captured operational data; it did not launch an ingestion job.
- An attempted reconstruction at the prior September 9 export cutoff correctly rejected the now-later staging crosswalk required by current-match owner corrections. No output was published from that attempt. The new export uses its actual current cutoff; no crosswalk or source timestamp was backdated.
- Every exported raw SDP shots, SOT and xG cell was reconciled to retained source content, including NULL. Current team/player statistical values and identities match the previous dashboard; current lineup receipt timestamps/version ids advance to the latest existing captures.
- A repeated read-only build at the same cutoff reproduced identical bytes. Python validation and the actual TypeScript parser accepted the new export. Actual frontend aggregation/CSV code confirms 20 usable shot-average teams in every checked season, and 20 full-season xG/xGA points for 2025/26.
- Previous sidecar SHA256: `314235c4fbba80cc1be3fa4bc0f8d80338163779358b610106b9f5a8ff73d36f`.
- New sidecar SHA256: `bcf74a478703fa6d9e65c91de382564c974d5bb4301f922f2285fe5d848eccd0`.
- Only the SDP public sidecar was replaced after preserving the prior version. The existing Vite build copies it into `dashboard/dist/sdp/sdp_stats.json`. HTTP checks confirm the served sidecar and compiled JS/CSS are byte-identical to the local validated build.
- Local preview: `http://127.0.0.1:4173/#team-stat-sdp`. Restarted the existing preview on port 4173 (PID 13668); logs are in the verification directory. This is local-only, not a production deployment.

## Verification and limitations

- Python: 76 tests passed across `test_sdp_stats.py`, `test_sdp_dashboard_validation.py`, and `test_build_sdp_dashboard.py`. New cases cover partial historical sources, future-known/contradictory/duplicate/hash-mismatched identity, preserved NULL, unchanged health/raw records and deterministic replay.
- Frontend: 41 tests passed across SDP page, scatter, fullscreen, SDP aggregation and team analysis. Sorting, comparisons, match logs, reset, CSV, missing-data states and labels are covered with synthetic observations.
- TypeScript and Vite build passed. Changed-file Ruff, formatting and strict mypy passed. Oxlint has no errors and the same nine inherited Fast Refresh warnings. Vite retains its existing large-chunk warning.
- Initial pytest setup hit the existing inaccessible Windows temporary-directory root; an initial replacement path also lacked its parent. Created a task-specific parent and used a fresh explicit `--basetemp`; the complete focused run then passed. No unrelated symlink/global-format work was attempted.
- Browser skill runtime was discovered and attempted: `agent.browsers.getForUrl(...)` returned `No browser is available`; the documented troubleshooting check `agent.browsers.list()` returned `[]`. Browser execution and screenshots are not available in this session. DOM tests and HTTP checks are not claimed as visual verification; actual desktop/mobile screenshot review remains outstanding.
- All 415 previously recorded protected hashes remain unchanged. The additional 191-file task-start inventory (model/config/results, forecast read models and prediction artifacts) also has zero changes. The operational DB was read-only throughout. Model parameters, frozen predictions and scientific evidence remain unchanged.
- Remote main advanced independently; fetched comparison before this commit is 86 ahead / 8 behind. Main and the default branch were not modified; no merge, rebase, force push or production publication was performed.
