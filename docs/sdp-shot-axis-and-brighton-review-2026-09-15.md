# Shot-axis controls and Brighton goal-origin follow-up

Descriptive dashboard work on the existing V2 branch, starting at
`8127a7dac331871d6e38f742a14fce6e35bfb756`. No inference, optimizer run, source
capture, model change or historical evaluation was performed.

## Chart controls

Attack and Defence default to SOT as a percentage of all shots, for and against
respectively. Each independently offers SOT/match and shots inside the box/match.
The Y axes remain xG/match and xGA/match. The existing orange/blue themes, team
labels, selection across four panels and goal-pattern fullscreen view remain.

Percentages divide matched shot totals, never average individual match
percentages. A missing numerator/denominator or zero denominator is unavailable;
an observed zero SOT with positive shots is 0%. The tooltip retains both shots
and SOT per match. SOT describes accuracy; box shots describe location. Neither
percentage nor xG alone communicates shot volume.

Conceded box shots use the exact reciprocal opponent team-match row from the full
published source, before team/venue display filtering. Season, fixture, sides,
venue, GW, kickoff and provider match identity must agree. Missing or duplicate
identities fail closed. The median X is the median of club coordinates on the
same complete-pair league cohort as Y, including when visible clubs are filtered.

The current Arsenal four-match example reconciles to 22 SOT / 54 shots = 40.7%,
5.5 SOT/match, 9 box shots/match. Against: 9 SOT / 36 shots = 25%, 2.25 SOT/match,
4 box shots/match. Existing correction/supplement markers remain visible.

## Brighton's previously unclassified goal

The affected row is 2026/27 GW2, fixture 16, Chelsea 4–3 Brighton on 30 August,
SDP match 2645207, Brighton permanent team code 36. The unknown origin was
**Malick Yalcouye's 35th-minute goal**, not a missing score or an own goal.

The previous audit confirmed the rebound but could not corroborate the move's
initial restart. That dated report remains unchanged. The new
[Sahadan live commentary](https://www.sahadan.com/en/match/chelsea-vs-brighton/40c1vmb9vw5uej4dtni094jro/commentary)
explicitly describes a quick throw from the right, Yalcouye passing to Kostoulas,
a saved shot and Yalcouye finishing the rebound. The
[Brighton match report](https://www.brightonandhovealbion.com/media-article/mft-match-report-chebha-pl--report)
corroborates the pass, saved shot and rebound. Chelsea's report names a different
player for the initial saved shot; the match-specific commentary agrees with
Brighton's own account. No claim of video verification is made.

Under the existing dashboard definition, which already includes throw-in phases,
this supports a corroborated set-piece origin. It is an audited interpretation,
not a newly supplied SDP set-piece total or a universal missing-as-zero rule.

| Brighton goals in fixture 16 | Origin |
|---|---|
| Yalcouye 35 | Quick-throw phase, rebound |
| Joao Pedro 63, own goal | Separate opponent-own-goal category, despite corner origin |
| Gross 90+6 | Long-throw phase, header |

The existing raw payload hashes to
`2c2fc6c34fed4bdfad64ca377728ee2aa1549e77e9bb9e6690d414c9ff9ea215`.
Brighton's raw `goals=3`, `goalsOpenplay=0`; Chelsea's `ownGoals=1`.
The display receipt changes confirmed set pieces 1→2, complete set pieces
NULL→2, unclassified 1→0. Raw fields, source version and source capture time
remain unchanged. Only this row receives the new review time
**2026-09-15T02:52:32Z**; unrelated receipts retain their original audit date.

Across Brighton's four matches: 13 goals = 7 open play + 4 set piece + 2 opponent
own goals + 0 unclassified. Set-piece average is 1 per match.

## Verification and delivery

The exported source cutoff stays `2026-09-15T02:09:35.777743+00:00`, covering 40
ended fixtures across GW1–GW4. Provider core validity remains 36/40, with four
owner-confirmed dashboard fixtures separately. The goal correction changes no
health/selector decision. Leeds/Newcastle fixture 40 still lacks goal-origin audit
receipts; this review does not assign its origins.

Exactly one team-match goal receipt differs in the new sidecar; all other fields,
player rows, source timestamps and coverage agree. Previous export retained in
`data/artifacts/sdp-axis-modes-20260915/previous-sdp-stats.json`. New export SHA256:
`24db05500a2ce494a31fcde288ba3b0cf2ff892d4ac2acce2c119dce468d915a`.

66 focused Python tests and 64 frontend tests pass. Changed Python Ruff/format
and strict mypy pass; dashboard type-check/build and lint pass. Existing nine
Fast Refresh warnings and the Vite chunk-size warning remain. A read-only DuckDB
inspection initially encountered missing optional `pytz` when converting a
timestamp; fetching it as its exact timestamp string resolved inspection without
installing packages or changing stored data.

The in-app browser had no available session. Installed Chrome with an isolated
headless profile verified 1440px desktop and 390px mobile rendering, all axis
modes, actual tooltips, home-only reciprocal lookup, updated Brighton goal bars
and an actual CSV download. No JavaScript exceptions, failed requests or horizontal
overflow. Browser evidence/screenshots are retained in the same ignored review
directory. All 404 protected model/config/research/forecast fingerprints match.

The existing local preview serves the update at
`http://127.0.0.1:4173/#team-stat-sdp`; reload an already-open page to load the new
sidecar. This is local delivery, not a production deployment or main-branch merge.
