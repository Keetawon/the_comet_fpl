# Adapting external research to this system

Source: a literature review on form, stabilisation, team ratings and position-specific FPL
scoring. This document records which of its recommendations **our data can actually serve**,
which it **cannot**, and — where we could check — whether our measurements **agree**.

Every number in the "measured here" column was computed against `data/fpl.duckdb` on the
five-season archive, not taken from the review. Where the two disagree, the measurement wins
and the reason is given.

---

## 1. Where our data contradicts the review

These three would cause real damage if adopted as written.

### 1.1 Home advantage: do NOT set it from the last 1–2 seasons

The review recommends "set home advantage from recent data only (~0.15–0.25 goals), it has
collapsed". Measured here:

| Season | gap (goals) | gap (PPG) |
|---|---|---|
| 2021-22 | 0.208 | 0.268 |
| 2022-23 | 0.416 | 0.592 |
| 2023-24 | 0.321 | 0.411 |
| **2024-25** | **0.092** | **0.182** |
| **2025-26** | **0.303** | **0.379** |
| pooled | **0.268** | — |

2024-25 reproduces the review's "~0.18 PPG" almost exactly — and then 2025-26 rebounded to
0.303 goals. There is no monotone decline; the series is noisy.

The standard error of a one-season home-advantage estimate is roughly
`sqrt(2 * var(goals) / 380) ≈ 0.09` goals — **the same magnitude as the entire claimed
collapse**. A single season cannot distinguish a real structural change from noise.

Had we followed the review at the start of 2025-26 (using 2024-25's 0.092) we would have
under-stated home advantage by a factor of three.

**Adopt instead:** pool all seasons with mild exponential decay. This is the same argument the
project already applies to team-strength windows — a 5-match average has a Poisson standard
error exceeding the between-team spread — applied to home advantage.

### 1.2 Promoted teams: the review's defensive penalty is roughly double ours

| | Review | Measured here (n=12 team-seasons) |
|---|---|---|
| xG vs league | −33.5% | **−28.4%** |
| xGC/xGA vs league | **+46.5%** | **+24.9%** |
| goals for | — | −28.1% |
| goals against | — | +30.9% |

Direction confirmed, magnitude not. Using +46.5% would over-penalise promoted defences by
nearly a factor of two, which propagates directly into clean-sheet probabilities — the single
largest defender-points term after appearance.

**Adopt instead:** −28% attack / +25% defence, re-estimated each preseason. Note n=12 is small
(four seasons × three promoted clubs; 2021-22 is the baseline season and contributes none).

### 1.3 Form autocorrelation: the review's figure is inflated by availability

The review cites a community estimate that a player's last-six-game average explains ~16% of
current points (r≈0.4). Measured here, **conditioned on `minutes > 0`**:

```
n = 53,512    r = 0.215    R² = 0.046
```

Under 5%, not 16%. The difference is that the unconditioned figure includes players who did
not play — for whom both the trailing average and the current score are ~0. That correlation
measures **availability, not form**.

This *strengthens* the review's own thesis rather than weakening it: once you know a player
started, their recent points tell you almost nothing about this week. It is also a direct
empirical confirmation of R6 — the apparent autocorrelation in fantasy points is minutes, and
conflating the two is exactly what R6 exists to prevent.

---

## 2. Where our data confirms the review

### 2.1 Finishing does not persist — shrink it to nothing

Season-to-season persistence, players with 900+ minutes in both seasons, **measured within
position** (a pooled figure is meaningless here — see the caveat below):

| Position | n | xG/90 | xA/90 | goals/90 | **finishing (G−xG)/90** |
|---|---|---|---|---|---|
| FWD | 49 | **0.571** | 0.505 | 0.510 | **0.138** |
| MID | 248 | 0.740 | 0.760 | 0.573 | **0.060** |
| DEF | 209 | 0.319 | **0.784** | 0.150 | **−0.103** |
| GK | 47 | −0.035 | 0.252 | n/a | −0.035 |

FWD xG/90 r = 0.571 matches the review's ~0.6. Finishing is ≈0 at every position, matching its
~0.12. **Shrink finishing essentially fully to the positional mean.**

> **Caveat that matters.** Pooling all positions gives xG/90 r = 0.871, which looks like a
> spectacular result and is an artefact: the between-player variance is dominated by position
> (a centre-back's xG/90 is ~0.02, a striker's ~0.9), not by skill. Any persistence figure
> quoted without conditioning on position is measuring the position, not the player.

**New finding not in the review:** for defenders, **xA persists 2.5× better than xG**
(0.784 vs 0.319). A defender's xG is mostly set-piece noise. Stage C should carry xA as the
attacking signal for DEF, not xG.

### 2.2 Goalkeeper save% is a league constant — shrink hard

`saves / (saves + goals_conceded)` for goalkeepers with 60+ minutes:

| Season | implied save% |
|---|---|
| 2021-22 | 0.677 |
| 2022-23 | 0.675 |
| 2023-24 | 0.669 |
| 2024-25 | 0.677 |
| 2025-26 | 0.669 |

**67.3% ± 0.4pp across five seasons.** The review says shrink toward ~69%; use 67.3%, ours.

Stability this tight means an individual keeper's deviation is almost entirely noise, which is
the review's point and it holds here.

It also establishes that **`saves + goals_conceded` is a usable proxy for shots on target
faced** — we have no shots data at all, and this recovers ~163 per team-season, consistent
with the review's ~100–150 per keeper.

---

## 3. What we cannot serve at all

FBref lost its Opta licence on 2026-01-20 and deleted the advanced data including history, so
these are not "not yet" — they are unavailable.

| The review asks for | Status |
|---|---|
| shots, shots on target | **none.** Not in the FPL API; FBref gone |
| CBIT split into clearances / blocks / interceptions | only the **combined** `clearances_blocks_interceptions`, and only from **2025-26** |
| aerial duels, crosses, final-third touches, progressive carries | **none** — the review's FB/CB classifier is not implementable as specified |
| Championship xG/xGA for a promoted-team prior | **none** — pooled historical promoted-team performance is the only route |
| manager-change dates | **none** — new-manager bounce cannot be modelled; Phase 5 conditional at best |
| BPS component breakdown | only total `bps`. BPS can be simulated, but fitted only from the events we hold |
| touch maps to validate sub-position labels | **none** |
| PSxG − GA for keeper shot-stopping | **none** — use expected shots faced × shrunk save rate |

---

## 4. Two changes worth making

### 4.1 Full-back vs centre-back is separable with columns we already have

The review's recommended classifier needs aerials and crosses, which we lack. A two-feature
split on **CBI/90 vs xA/90** separates cleanly (2025-26, 1200+ minutes):

| Top CBI/90 | CBI/90 | xA/90 | | Top xA/90 | CBI/90 | xA/90 |
|---|---|---|---|---|---|---|
| Danso | 10.0 | 0.017 | | De Cuyper | 2.7 | 0.262 |
| Fofana | 9.8 | 0.031 | | Digne | 3.8 | 0.160 |
| Ballard | 9.7 | 0.026 | | Muñoz | 4.7 | 0.148 |
| Botman | 9.6 | 0.042 | | R. James | 3.7 | 0.147 |
| Keane | 9.2 | 0.017 | | Pedro Porro | 4.6 | 0.141 |

Centre-backs sit at 9.2–10.0 CBI/90, full-backs at 2.7–4.8 — a clean 2× gap with no overlap in
these samples. Tackles/90 separates in the same direction but weakly (FB 1.4–2.7, CB 1.0–1.7).

**Senesi appears in both lists** (CBI 9.8, xA 0.129) — a genuinely ball-playing centre-back. So
this must be a **continuous score, not a binary label**; forcing a hard class would mis-handle
exactly the players whose valuation is least obvious.

Limits: available 2025-26 onward only, and this is an eyeball of two top-8 lists, not a
validated classifier. It needs a labelled evaluation before Stage C depends on it.

### 4.2 Promote `threat` from `raw_` to the fact tables

The review's central claim is that **shot volume stabilises faster than xG** and should carry
the attacking prior. We have no shot counts — but `threat` (Opta's shot-volume-and-quality
index) is already landed in `raw_merged_gw` and was excluded from the mart in Phase 0 only
because it was not in the original feature list.

Measured season-to-season persistence:

| Position | threat/90 | xG/90 | difference |
|---|---|---|---|
| DEF | **0.557** | 0.319 | **+0.238** |
| MID | **0.828** | 0.740 | +0.088 |
| FWD | **0.625** | 0.571 | +0.054 |

`corr(threat, xG)` per match is 0.71–0.78 — it measures the same thing, **more stably**, at
every outfield position. That is the review's claim, confirmed on the only proxy we have.

**Recommended change**, deliberately *not* half-implemented (see §6):

- add `threat` and `creativity` (the xA-side analogue) to `stg_player_fixture` and
  `mart_fact_player_fixture`;
- add them to the same live tables, and declare them on `ElementHistory` in
  `ingest/fpl_api.py` — the element-summary payload carries them;
- they are components, not points, so the feature-readable contract is unaffected;
- `expected_goal_involvements` stays excluded — verified to be exactly `xG + xA` (679
  mismatches in 104,779 rows, all rounding), so it carries no information the split lacks.

---

## 5. Why xG and xA stay separate

Recorded here because it was asked directly, and because merging them is a tempting
simplification.

**The scoring function needs the split.** A goal is worth a different multiple of an assist at
every position:

| Position | 1 goal = n assists |
|---|---|
| GK | 3.33 |
| DEF | **2.00** |
| MID | 1.67 |
| FWD | 1.33 |

A defender with xGI = 3.0 is worth 18 attacking points if it is all xG and 9 if it is all xA.
**Same number, double the points.** Collapsing to xGI discards precisely the information
`calculate_points` consumes.

**They need different shrinkage.** For defenders xA persists at 0.784 and xG at 0.319 (§2.1).
One combined statistic forces one shrinkage constant onto two quantities that stabilise at very
different rates, over-shrinking the reliable half and under-shrinking the noisy half
simultaneously.

**A goal has two players attached.** Stage D draws team goals, then allocates a scorer *and* an
assister. A "goal involvement" is not an event that can be allocated to one player — it is a
pair. Allocating xGI multinomially would double-count a single team goal as two independent
events.

**Splitting costs nothing.** xGI is recoverable from the split; the split is not recoverable
from xGI. Keeping both components is strictly more informative at zero storage cost.

xGI remains useful as a **display** metric on the dashboard, downstream of the model.

---

## 6. What was deliberately not done here

The `threat`/`creativity` promotion in §4.2 is **specified but not implemented**. Implementing
it on the archive path alone would create a column populated for five historical seasons and
NULL for every current-season row, because the live loader's `ElementHistory` does not declare
those fields. That is the null-versus-zero trap this project already has three tests guarding
against, arriving through a new door: a model would train on a feature that silently vanishes
in production.

It should land as one change covering both paths, with the schema-drift tests extended to
assert the column is populated in both the archive and live tables.

---

## 7. Effect on the phase plan

| Stage | Change |
|---|---|
| **Schema** | promote `threat` + `creativity` (§4.2), both paths, one change |
| **A** | Dixon-Coles with rho ≈ −0.13 as a starting value, re-fit; fit time-decay `xi` by out-of-sample score rather than adopting 0.0065; home advantage **pooled with decay, not recent-only** (§1.1); promoted prior **−28% / +25%** (§1.2) |
| **B** | congestion through minutes rather than a per-90 penalty — `rest_days` supports this; European fixtures still unavailable |
| **C** | finishing shrunk to ≈0 (§2.1); **DEF attacking signal is xA, not xG**; FB/CB as a continuous score (§4.1); GK via expected shots faced × 67.3% (§2.2); DC as a threshold-hit rate with wide uncertainty |
| **D** | simulate all 22 players' BPS and rank — already the design |
| **Evaluation** | the review proposes RMSE < 2.0. Our contract uses log score and CRPS, which are proper scoring rules for a distribution and strictly better founded. **Keep them primary**; RMSE may be reported as a secondary comparison against published work only |

**Unverified claim to check, not adopt:** the review states 2026/27 BPS changes (reduced
DC/bonus double-dipping, a BPS point for goalkeepers saving a big chance, shifts toward
attacking midfielders). Seven fields in `config/scoring_2026_27.yaml` are already
`unverified` because the live `game_config.scoring` does not publish them. These BPS claims
must be checked against a captured payload before any of them reaches the config.
