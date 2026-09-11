# Shot accounting: bounded owner-confirmed display corrections

The September 9 owner follow-up confirms two additional descriptive zero values.
Confirmation was recorded at **2026-09-09T02:12:10Z** (09:12:10 Asia/Bangkok).
This is the actual recording time, not a backdated provider observation. The
three September 8 confirmation records and their timestamps remain unchanged.

## Off target is different from outside the penalty area

The retained match-stat payloads show:

| Fixture / team | Total attempts | Off target | Blocked | On target | Outside box |
|---|---:|---:|---:|---:|---:|
| 7: Brighton–Aston Villa / Aston Villa | 6 | 6 | omitted | omitted | 4 |
| 19: Sunderland–Fulham / Fulham | 11 | 3 | 8 | omitted | 4 |

`shotOffTarget` describes the outcome; `attemptsObox` describes shot origin.
Neither outside-box attempts nor a goalless score establishes zero SOT.
[Opta event definitions](https://www.statsperform.com/opta-event-definitions/)
distinguish off-target attempts from blocked attempts, classify last-line
goal-preventing blocks as on target, and define box location separately.
Accuracy denominators can exclude blocked attempts; do not apply this arithmetic
to an arbitrary field named “shots” without confirming its definition.

For the retained inclusive `totalScoringAtt` breakdown, nonnegative outcome
counts exhaust the total: Villa's six off-target attempts leave zero on-target
and zero blocked attempts; Fulham's three off-target plus eight blocked attempts
leave zero on-target attempts. Exact fixture/side/crosswalk, raw hash, observed
accounting fields, absent target field, target qualifiers and the existing FPL
opponent goalkeeper zero-save/90-minute proxy are checked before display.

This is match-specific corroboration of the owner's confirmation. It does **not**
prove that SDP generally serializes all zeros by omitting their fields. Other
missing statistics remain NULL. These values are not provider-verified zeros.

## Current correction inventory

| Fixture | Team | Display field | Value | Status / recorded confirmation |
|---|---|---|---:|---|
| 7 | Aston Villa | SOT | 0 | Owner-confirmed; September 8 |
| 7 | Aston Villa | Blocked attempts | 0 | Owner-confirmed; September 9 |
| 19 | Fulham | SOT | 0 | Owner-confirmed; September 9 |
| 20 | Aston Villa | SOT | 0 | Owner-confirmed; September 8 |
| 28 | Spurs | SOT | 0 | Owner-confirmed; September 8 |

Policy v2 adds exactly two records in
`config/sdp_dashboard_display_corrections.yaml`. Full source hashes and original
source times remain pinned there. Raw SDP values stay NULL; corrections live in
the separate `display_corrections` object. SOT mirrors only to the opponent's
SOT-allowed field. Blocked attacking attempts do not become the opponent's
defensive block count. A later explicit validated provider value takes precedence
without rewriting the original owner record.

Fulham is now display-resolved under the new owner confirmation. Its earlier
unresolved status in the dated September 8 report remains historically accurate.
The current population is **30 completed fixtures across GW1–3**, 60 team sides:
**26/30 provider core-valid**, four incomplete provider fixtures, and **five direct
display corrections across four fixtures**. Display corrections do not change
the production selector, evidence eligibility or fallback policy.

## Preview and verification

Retained generation:
`D:/Personal/fpl-operations/verification/shot-display-20260909/`.
Build cutoff: `2026-09-09T02:24:15.204239Z`. The scheduled writer had finished before
the operational database was opened read-only. No writer/lock/WAL was interrupted
or removed. No provider request or new forecast was made by this correction task.
Latest retained SDP capture is `2026-09-09T02:16:06.274587Z`; FPL player-history
capture remains `2026-09-08T13:35:11.208041Z`. Latest covered match kickoff remains
September 6 at 15:30Z. Player coverage remains 1,890 FPL rows and 401 SDP
participation rows; detailed player statistics retain their explicit FPL labels.

The previous cutoff was replayed against its retained operational snapshot:
all old sidecar bytes match SHA256
`78fd78e0b9c79e59d3662f2d4168151f866ac5d75bc4ec6bd0fe724456714bad`.
The current mutable crosswalk was rematerialized by the scheduled job at
`2026-09-09T02:13:41.599277Z`; it was not relabelled as earlier evidence. The retained
snapshot supplies the earlier crosswalk for that replay. No storage or model
policy was changed to make the replay pass.

The new sidecar SHA256 is
`2039bd761b56027429b4600c873e4b0b8f6f3e57490101d2965ac9662ef486b1`.
The local Vite preview serves those exact bytes at
<http://127.0.0.1:4173/#team-stat-sdp>. Tables, charts and CSV use the same
correction-aware metric reader. The actual served data passed the frontend parser,
and all five corrected cells passed raw-NULL/display-zero/CSV-provenance checks;
representative CSV files are retained alongside `served-verification.json`.
All base Dashboard JSON files, old plans and published forecast values are
byte-identical. No production site was deployed.

- Python: 47 focused tests and 38 primary/isolation/dashboard regressions passed.
- Frontend: 43 SDP contract/arithmetic/interaction tests passed; TypeScript/Vite
  build passed. Existing bundle-size and nine Fast Refresh warnings remain.
- Ruff passed; strict mypy passed for 228 source files; both changed Python files
  passed formatting. No unrelated global formatting or symlink repair was made.
- Independent reconciliation: **392/392 frozen files unchanged**, including model
  freeze `17cfa2267ce4d7c89f96842220f40471b81152d2`, GW4–8 forecasts and both GW1–3
  audit identities. Receipt SHA256:
  `fabdcc8232037cb18dfd49dcab45f243a6d85067a575ec931975dc6636468149`.
- Browser skill setup was attempted again: selection returned
  `No browser is available`; discovery returned `[]`. Screenshots and visual
  desktop/mobile verification remain unavailable, not passed. HTTP and data
  checks above are not visual QA.

The model remains frozen and GW4–8 remains the existing prospective checkpoint.
No historical audit, predictive experiment or optimizer run was performed, other
than synthetic isolation regression tests. Publication remains subject to the
existing broad draft PR review and owner approval of main integration.
