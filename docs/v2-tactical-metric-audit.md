# Tactical Matchup V1: pre-model metric and coverage audit

Status: **coverage-only, retrospective-development evidence**. No tactical forecaster or
goal model was fitted or scored to choose these fields or seasons. This is a new additive
audit, not a rewrite of the September 5 provider inventory or any previous experiment.

## Source and version identity

Read-only database:
`D:\Personal\workspace\the_comet_fpl\.worktrees\sdp_test\data\fpl.duckdb`.
SHA-256 before and after: `0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8`.

The unchanged retrospective selector chooses the earliest successfully captured **complete
whole match-stats payload**, ordered by `(fetched_at, payload_id)`, before checking any
candidate field. All 1,921 selected payloads were reparsed from retained raw text; every raw
byte count and SHA matched. They contain 3,842 reciprocal team sides: 760 in each of five
completed historical seasons plus 42 current-season sides. Selection requires the measured
crosswalk's kickoff and team corroboration; current source-timing gaps remain visible via
`score_corroborated` in the manifest. Historical model observations require the stronger
archive/crosswalk checks of the separate retrospective reader.

The exhaustive new artifact is `results/v2_tactical_metric_audit.json`: **245 numeric fields**,
42 mapped and 203 unmapped, plus the text-only `fastestPlayer`. For every numeric field it
retains the exact raw key, local mapping, confidence, direction/caveat, season availability,
measured/zero/missing counts and percentages, opponent and joint reciprocal availability,
and min/max. Every selected capture's ID, actual knowledge time, SHA and fixture identity
are retained; manifest SHA is
`f12a915d14e2f8d3c8ca718b242b91c41c3d3c6d3546383d319c7692f878835d`.

These are capture-denominator coverage percentages, not percentages of all scheduled future
fixtures. No database, raw value, dictionary flag or old artifact was modified. Captures are
from September 2026, so this does not prove real-deadline historical availability.

## Semantics and bounded development licence

Independent corroboration remains limited to exact `goals`, `expectedGoals`, and
`ontargetScoringAtt`. Every other field remains provider-labelled or unverified: an exact
spelling, a familiar concept and a successful invariant do **not** independently validate
all its numeric values. No global `verified_semantics` flag changes.

The official [Opta event definitions](https://www.statsperform.com/opta-event-definitions/)
support these distinctions: SOT includes last-line blocks, ordinary blocked attempts differ;
passes exclude crosses/keeper throws/throw-ins; direction is an event qualifier, not sequence
speed; touches aggregate touch events. The [PL clarification page](https://www.premierleague.com/en/stats/clarification)
provides the provider's stats context, not a public schema for every SDP key.

Only the following five narrow dimensions/six raw keys are licensed for this development
candidate. Their names describe measured proxies, not permanent club archetypes.

| Dimension | Local input / exact provider key | Frozen observed-state formula | Confidence and direction |
| --- | --- | --- | --- |
| Attack precision | `shots_on_target` / `ontargetScoringAtt`; `shots` / `totalScoringAtt` | SOT / shots when both measured and shots > 0 | SOT independently corroborated; shot total provider-labelled. Higher on-target fraction, **not** xG/chance quality or the Opta UI shooting-accuracy formula |
| Dangerous territory | `touches_in_opposition_box` / `touchesInOppBox` | `log1p(box_touches)` | Provider-labelled event-count proxy. Higher opposition-box activity, not unique attacks or entries |
| Control | `possession` / `possessionPercentage` | possession / 100 | Provider-labelled share; higher possession, not a verified tracking-time measurement |
| Directness | `forward_passes` / `fwdPass`; `passes` / `totalPass` | forward passes / passes when both measured and passes > 0 | Provider-labelled directional propensity; higher forward share, **not** speed, pass length or chance quality |
| Defensive suppression | reciprocal opponent `shots` / `totalScoringAtt` | `-log1p(opponent_shots)` | Exact opposing side of the same fixture. Higher value means fewer attempts allowed, not independently identified defensive depth |

The ratio denominator includes blocked attempts, unlike Opta's published shooting-accuracy
definition. We therefore deliberately call it **attack precision**, not that UI metric.

Selected-season input coverage (each denominator is 760 sides):

| Local field | Raw key | 2023-24 measured / missing / zero | 2025-26 measured / missing / zero | Reciprocal joint coverage 2023-24 / 2025-26 |
| --- | --- | --- | --- | --- |
| shots_on_target | ontargetScoringAtt | 754 / 6 / 0 (99.21% measured) | 744 / 16 / 0 (97.89%) | 98.42% / 95.79% |
| shots | totalScoringAtt | 760 / 0 / 0 | 760 / 0 / 0 | 100% / 100% |
| touches_in_opposition_box | touchesInOppBox | 760 / 0 / 0 | 760 / 0 / 0 | 100% / 100% |
| possession | possessionPercentage | 760 / 0 / 0 | 760 / 0 / 0 | 100% / 100% |
| forward_passes | fwdPass | 760 / 0 / 0 | 760 / 0 / 0 | 100% / 100% |
| passes | totalPass | 760 / 0 / 0 | 760 / 0 / 0 | 100% / 100% |

No selected raw metric contains an explicit zero in these seasons. SOT omission can be
outcome-dependent: the earlier zero-corroboration audit provides evidence for omitted zeros.
This V1 deliberately does **not** import that interpretation or average-fill omissions.
Missing observations remain missing, consume their chronological recent-match slots, and
reduce confidence. Consequently precision estimates conditional on measured SOT can be
upward biased; disclose this limitation, not a claim of fully random missingness.

## Exclusions decided without model performance

| Family | Measured source evidence | V1 decision |
| --- | --- | --- |
| SDP xG / xGOT | xG counts 6, 4, 6, 340, 760 across 2021-22..2025-26; xGOT similarly sparse | No multi-season 95% support; do not replace existing FPL xG or add xGOT |
| Big chances created/scored/missed | Created only 534..622 / 760; still fewer scored/missed | Omission and scope complexity; exclude, never add those fields to invent total big chances |
| Final-third / penalty-area entries | Both 760/760 each historical season | Exact entry and deduplication definitions not independently corroborated; one box-touch dimension is sufficient for bounded V1 |
| Accurate/backward/long passing | Broad complete coverage | Retain audit only; avoid redundant dimensions and calling a pass share territorial dominance |
| Blocks | 701..720 / 760 | Dictionary says excludes blocked shots, but Opta Block describes outfield shot blocking. Semantic conflict is flagged; do not silently repair/use it here |
| Tackles / regains / recoveries | Broad coverage; high-third regains 729..743 / 760 | Challenge/regain counts do not identify pressure intensity or defensive depth; exclude press/workload dimensions V1 |
| Interceptions / clearances | Near/fully complete | Contextual event volume alone is not proof of suppression; exclude extra workload interactions |
| Duels / aerials | Four counts all 760/760 each historical season | Broad but unnecessary for these five dimensions; no automated pairwise expansion |
| All 203 unmapped numeric keys | Fully enumerated with coverage in JSON | Not licensed for fitting merely because retained or highly covered |

## Coverage-only season eligibility

Frozen rule: **>=95% joint availability of all six required raw fields on BOTH fixture
sides**, complete historical season (760 completed archive goal targets), and at least one
earlier full PL season for warmup. Zero ratio denominators are unavailable, not zero.

| Season | Own joint | Both-side joint | Outer eligibility |
| --- | ---: | ---: | --- |
| 2021-22 | 738/760, 97.11% | 716/760, 94.21% | No: below joint bar and no previous full season |
| 2022-23 | 738/760, 97.11% | 716/760, 94.21% | No: below joint bar |
| 2023-24 | 754/760, 99.21% | 748/760, 98.42% | **Yes** |
| 2024-25 | 740/760, 97.37% | 720/760, 94.74% | No: below joint bar |
| 2025-26 | 744/760, 97.89% | 728/760, 95.79% | **Yes** |
| 2026-27 | 39/42, 92.86% | 36/42, 85.71% | No: incomplete current season and below joint bar |

The two selected seasons give **1,520 scored team sides / 760 fixtures / 76 observed GW
folds**. Score every archive goal target in those seasons, including rows without target
tactical observations: predictions use prior state and the preregistered fallback. Missing
style targets affect only measured style-diagnostic/training denominators, not goal-score
population. Outer-ineligible earlier seasons may supply strictly prior measured training
observations. Excluding 2022-23/2024-25 is a coverage decision, never an outcome-score decision.

Two nonconsecutive seasons limit generalisation. A pass would remain retrospective
development-only, not permission to alter prospective/default consumers.

## Reproduction and checks

```powershell
& D:\Personal\fpl-operations\.venv\Scripts\python.exe -m fpl.validate.tactical_metric_audit `
  --db D:\Personal\workspace\the_comet_fpl\.worktrees\sdp_test\data\fpl.duckdb `
  --output results/v2_tactical_metric_audit.json
```

The command refuses an existing output and rechecks the database hash after its read-only
audit. The retained report was finalized after coverage-rule and formatting edits to its
new, uncommitted draft; neither run fitted/scored any model. Hand-computable self-checks
assert missing versus explicit zero, reciprocal counts, >=95% boundary, first-season
warmup exclusion and incomplete-season exclusion. Focused Ruff and strict mypy pass.
The older dictionary/inventory/coverage reports are untouched.
