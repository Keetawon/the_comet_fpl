# Descriptive attacking-usage scouting

Attacking Usage Percentile describes how attacking a player's **observed xG/xA usage**
has been relative to the same registered FPL position. It helps find unusual attacking
profiles, particularly defenders. It is not a future-performance boost, a tactical role
or OOP prediction, a persistence estimate, or a transfer/captain recommendation.

The frozen Attacking Role Premium V1 verdict remains **C - REFUTED**. The recent-window
candidate's next-match xGI/90 MAE lift was **-1.854%**: DEF -0.522%, MID -2.838%,
FWD -0.764%; the positive-shift subset was -26.066%. Recent spikes mean-reverted and
did not improve prediction over longer-term history. No formal evaluation was rerun.
See the unchanged [formal development record](attacking-role-premium-v1-development-2026-09-08.md).

## Surface and commands

This additive reporting export follows the existing Python publisher/thin-job split.
It creates `player_attacking_usage.json`, `player_attacking_usage.csv`, `manifest.json`
and a short methodology `README.txt` in a **new immutable directory**. It requires no
symlink privileges. The JSON contains the complete current outfield roster, positional
leaderboards and the defender watchlist. The flat CSV can be sorted/filtered in an
existing scouting or BI workflow. No established dashboard schema or route is changed.

```powershell
python -m fpl.jobs.build_player_attacking_usage --db D:/Personal/fpl-operations/data/sdp-primary-v2.duckdb --output-dir D:/Personal/fpl-operations/scouting/usage-20260908 --as-of 2026-09-08T09:09:01.847981+00:00
```

Omit `--as-of` to use actual UTC now. The job reads retained evidence only and performs
no network requests, capture changes, operational DB writes or forecast generation.
Use a new output directory for every publication; an existing output is never replaced.

`--position DEF` filters the CSV. `--sort` accepts `recent_usage_percentile`,
`recent_xg_percentile`, `recent_xa_percentile`, `long_xgi90`, `recent_xgi90`,
`delta_xgi90` or `historical_minutes`. `--min-minutes` defaults to 180 for the CSV and
leaderboards; `--min-minutes 0` exposes low-exposure and unranked players for inspection.
These display choices never change the underlying positional percentiles. JSON always
retains all current outfield players. The separately named **High attacking-usage DEF**
watchlist uses the fixed rule DEF, composite >=0.90, and at least 180 observed minutes.

The existing complete `player-history` capture stream supplies this export. A daily
bootstrap-only capture cannot substitute for it. Continue the existing player-history
capture operation; this task changes neither its schedule nor its raw capture semantics.

## Descriptive contract and arithmetic

`PlayerAttackingUsageSnapshot` is a versioned reporting object, not a Player Stats input.
For each current stable player code it exposes season, current registered position and
club, cutoff, historical minutes/starts/appearances, measured minutes, both profiles,
profile status, peer counts and raw-source provenance.

The unchanged V1 pure arithmetic is reused without its target-GW predictor:

- Long profile: all eligible current-season paired-measured prior xG/xA and minutes.
- Recent profile: latest **360 witnessed minutes**, ordered by kickoff then fixture ID.
  The boundary appearance is fractionally weighted when needed. This is an allocation
  convention over a match total, not evidence of when within that match chances occurred.
- Both use the same current-season positional prior and **450-minute** shrinkage:
  `(90 * observed_stat + 450 * position_rate90) / (observed_minutes + 450)`.
  Priors pool only eligible paired-measured exposure from the current roster's same position.
- Within each profile, the xG and xA rates get same-position empirical midranks
  `(number_below + 0.5 * number_equal) / number_of_eligible_peers`.
  `long_usage_percentile` / `recent_usage_percentile` each equal **50% xG + 50% xA**.
  The composite is an average of two percentiles, not a second percentile transform.
- `long_xgi90` and `recent_xgi90` are exactly their xG90 + xA90 components.
  `delta_xg90`, `delta_xa90`, `delta_xgi90` and `delta_usage_percentile` expose recent
  minus long context. These are observed-profile comparisons, not future adjustments.

The shrinkage and weights are fixed descriptive conventions inherited from the refuted
study. They are not fitted or newly validated. Low-minute profiles are pulled strongly
toward the positional pool. No goals, assists, ICT, formation, team environment, price,
ownership or future-match data enter the calculation. Open-play and set-piece threat
cannot be cleanly separated from these xG/xA totals; a high score does not establish
advanced tactical positioning.

| Usage bucket | Composite range |
|---|---|
| NORMAL | <0.75 |
| ELEVATED | 0.75 to <0.90 |
| HIGH | 0.90 to <0.975 |
| EXTREME | >=0.975 |
| UNKNOWN | NULL |

| Observation depth | Historical minutes |
|---|---|
| VERY_LOW | <180 |
| LOW | 180 to <450 |
| MODERATE | 450 to <900 |
| ESTABLISHED | >=900 |
| UNKNOWN | Missing minute evidence |

Observation depth is **not a predictive confidence probability**. Zero-history/DNP-only
players retain NULL rates and percentiles, UNKNOWN usage and VERY_LOW exposure. A positional
prior is never presented as their observed profile. Missing xG/xA remains NULL. Missing
opportunity on a played row invalidates the affected profile; it still consumes the recent
window, so older statistics cannot silently replace it. Unknown minutes inside the recent
window invalidate that window. A gap older than an already complete 360 minutes can leave
the recent profile available while the long profile remains unavailable. `measured_minutes`
separately reports the known paired-stat exposure. JSON NULL becomes an empty CSV cell.

## Source and point-in-time boundary

Live output uses only the configured **2026/27 CURRENT_PROSPECTIVE** stream, never the
2023/24 Class-B experiment. The reader selects one latest whole `player-history` capture
with actual `captured_at <= as_of`, verifies its canonical raw-payload and manifest hashes,
and requires exactly one bootstrap, fixtures source and summary for every supported player.
It fails closed on missing history keys, season skew, duplicate identities, conflicting
season-local code/element/position mappings and malformed numeric data. Current registration
is taken from that same capture; previous-season positions are not substituted.

Only ended fixtures with `kickoff_time < as_of` and before source capture are admitted.
Provisional ended matches are explicitly marked in fixture provenance and may subsequently
be revised. Fixture-time club and opponent come from that fixture's sides and witnessed venue;
they are not overwritten with a transferred player's current club. No name matching occurs.

`source_known_at` and `available_at` retain actual capture knowledge, conservatively including
the peer-population inputs needed for percentiles. Snapshot IDs, every source hash, raw capture
manifest hash, per-player history hash and population-history hash bind the calculation.
`manifest.generated_at` is the actual publication time, separate from source availability.
An export generated today for an earlier retained cutoff is not relabeled as an artifact
that existed then. Later corrections select a new capture only for later eligible cutoffs.

## Current retained sample

At `2026-09-08T09:09:01.847981Z`, the latest complete source is capture
`1bfb3d92-6d5e-48bf-a665-1f489dc6c1da`, known at `2026-09-08T03:37:39.610696Z`.

| Measure | Count |
|---|---:|
| Completed/observed GWs | 1, 2, 3 |
| Outfield players | 583 |
| DEF / MID / FWD players | 214 / 291 / 78 |
| Player-fixture rows | 1,682 |
| Paired-measured xG/xA rows | 1,682 |
| Positive-minute rows | 869 |
| Players with >=90 / >=180 minutes | 232 / 165 |
| Players with >=360 / >=450 / >=900 minutes | 0 / 0 / 0 |
| VERY_LOW / LOW / MODERATE / ESTABLISHED | 418 / 165 / 0 / 0 |
| Zero-history/DNP-only players | 218 |
| Fixed-rule defender watchlist | 4 |

No player has more than 270 minutes, so long and recent profiles currently coincide.
The complete rule-selected defender watchlist is Castagne, Guehi, De Cuyper and Calafiori;
all have LOW observation depth. These are descriptive examples, not recommendations.

Example selected fields for stable code 465730 (rounded here; export preserves full precision):

```json
{
  "player_code": 465730,
  "fpl_position": "DEF",
  "historical_minutes": 243,
  "long_xgi90": 0.33024,
  "recent_xgi90": 0.33024,
  "recent_xg_percentile": 0.99632,
  "recent_xa_percentile": 0.91544,
  "recent_usage_percentile": 0.95588,
  "delta_xgi90": 0.0,
  "recent_usage_bucket": "HIGH",
  "exposure_bucket": "LOW"
}
```

Interpretation: high attacking usage for a registered defender, with limited observed
minutes. The export makes no claim that it will continue.

## Isolation and verification

Only additive feature/reporting/job/test files and this documentation are introduced.
No forecast, Player Stats, FixtureEnvironment, SDP selector, optimizer, capture or ledger
consumer imports this capability. The real production isolation receipt uses identical
retained inputs for GW4-5, 654 players, primary and incumbent shadow forecasts, and a default
optimizer run including a transfer. Final verification details are recorded in the additive
scouting verification result alongside this documentation.

The frozen formal result SHA256 remains
`de2bd6839de4ca246554010cad337445fc30faa9d89d408147d3dce41cec9e08`;
the cases SHA256 remains
`3ddf2f7c7b61862195b2b61ba89bfd8d6f2e54aece44c22dc951a21c18f3c3e4`.
The descriptive export ends this task. No attacking-role prediction successor is introduced.
