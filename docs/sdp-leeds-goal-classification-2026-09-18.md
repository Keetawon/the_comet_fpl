# Leeds goal-origin evidence, 18 September 2026

The remaining Leeds goal in the 4-1 home win over Newcastle is now corroborated
as a set-piece goal by the official Leeds match report. This is a new display
interpretation of unchanged source evidence, not a provider correction or a
forecast change.

## Exact fixture and source check

The fixture is 2026-27 GW4, official fixture 40, SDP match 2645230, permanent
club codes Leeds 2 and Newcastle 4, kickoff 2026-09-14 19:00 UTC. The provider's
match endpoint independently confirmed those identities and the 4-1 score.

At 2026-09-18 04:21:19.775627 UTC a read-only request to
`/api/v3/matches/2645230/stats` returned the same 7,426 bytes, SHA256
`9ce926e841da8e00b261d5b7c52638b701035e63b9084ea2e10099deb52afad0`,
already retained from 2026-09-17 02:30:24.531275 UTC. Leeds has four goals,
two explicit `goalsOpenplay`, zero `attPenGoal`, zero `attFreekickGoal`, and
one opponent own goal from Newcastle's explicit `ownGoals`. Those fields
alone still leave one unclassified origin. An unchanged response does not
advance the retained source knowledge time.

The events endpoint, checked at 04:21:35.443531 UTC, returned SHA256
`8928ffef532fd475172b23e2c1ea5aec501955c395ecd9427c79f62b84c9a9c3`.
It labels the Leeds goals as Own (player 547719, minute 32), Goal (177815,
minutes 34 and 46), and Goal (435997, minute 59). It has no restart-origin
qualifiers, so those event labels do not close the accounting gap.

## New corroboration

The [official Leeds report](https://www.leedsunited.com/en/news/whites-dismantle-magpies-in-memorable-elland-road-encounter)
identifies the exact date, venue, opponents, 4-1 result and Okafor's goal at 59
minutes. Describing that goal, it states: "A set-piece was headed to the edge
of the area" before his finish. This supports a set-piece origin independently
of the arithmetic remainder. The own goal remains a separate category.

One Leeds-side row is added to `config/sdp_goal_pattern_display_audit.json`
using its existing per-row `audited_at` support. Its review time is
2026-09-18 04:24:12 UTC. All 78 earlier rows and the manifest's original audit
and source-cutoff timestamps remain unchanged. The new row is bound to the
exact fixture, side and raw SHA above; a source revision invalidates it.

| Scope | Open play | Confirmed set piece | Opponent own goal | Unclassified |
|---|---:|---:|---:|---:|
| Leeds, fixture 40 | 2 | 1 | 1 | 0 |
| Newcastle, fixture 40 | 1 | 0 | 0 | 0 |
| Leeds, GW1-4 | 3 | 3 | 1 | 0 |
| Newcastle, GW1-4 | 5 | 2 | 0 | 0 |

Leeds' complete descriptive set-piece total becomes 1 for this fixture and 3
for GW1-4. Raw `sdp.set_piece_goals` remains NULL; the displayed count comes
from the separately labelled evidence receipt. No omitted field is zero-filled,
and provider core health, player records and model inputs are unchanged.

The [Premier League's 16 September accreditation decision](https://www.premierleague.com/es/news/4720022/calvert-lewin-awarded-second-goal-after-leeds-appeal)
separately explains why the 34th-minute scorer is now Calvert-Lewin in SDP,
while FPL retains the closed-gameweek allocation. It expressly says the appeal
came too late to alter FPL points. This audit does not revise those points.

## Public generation checked before the change

`https://data.thecometfpl.com/current.json` pointed to generation
`e6f8ecc84495fc543d5ed97a4510c31d860a85a3398a5728da845978e97a3a7d`,
published 2026-09-17 15:19:55.698086 UTC. Its SDP sidecar was fetched at
2026-09-18 04:24:06.369040 UTC and verified against the pointer's byte count
18,994,848 and SHA256
`a44c9f1eebcd1dd5aa37828bfd355d52e7a62cb0fdc9010c3397163373c6a65f`.
It has interpretation cutoff 2026-09-17 15:13:29.591252 UTC and still shows
Leeds' one unknown goal. A new validated export and public publication are
required to expose this audit; editing the manifest alone does not publish it.

## Verification

All 12 focused goal-pattern tests pass. The new regression checks the counts,
separate source/review times, unchanged raw NULL, unchanged source object, and
loss of the manual audit on a different raw hash. The existing automatic
accounting then restores the unknown remainder rather than inheriting the manual
classification. Changed-file Ruff and format checks pass with caching disabled
after the existing cache directory denied temporary-file creation.

A direct check against the retained fixture-40 export validates the new receipt
and verifies unchanged source time/hash, FPL goals and raw SDP cells. Comparison
against Git HEAD confirms identical global metadata and all 78 earlier rows,
with exactly one appended row. No production code, database, capture, forecast,
model configuration or previously published artifact was modified by this audit.
