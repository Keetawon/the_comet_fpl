# Phase 4 — Stage D v2 points composition (saves + defensive contribution): development record

> **DEVELOPMENT ONLY — EXPLORATORY. NOT A PROMOTION VERDICT.**
> This extends the merged Stage D v1 composer with two additive scoring components. There is **no
> comparator baseline in the run** and **no pre-registered Stage D promotion contract**; nothing here
> promotes any model or changes any frozen Stage A/B/C contract. The numbers are development
> diagnostics under the same unversioned historical proxies (target roster, first-kickoff cutoff)
> every stage carries, plus the Stage-D-v2 limitations below. Real-deadline knowledge-time validity is
> unproven. **Defensive contribution is prospective-only** (its data exists only for 2025-26), so it
> carries no cross-season historical-lift claim.

## What Stage D v2 adds

Stage D v1 composes the fitted Stage A/B/C component distributions (minutes V3, goals V1, assists V1,
team goals-conceded from the promoted Stage A model) into a per-player-fixture non-bonus points
distribution by a seeded Monte-Carlo draw plus the exact scoring calculator. v2 keeps that suite
unchanged and adds **two more independent components**, because FPL scoring is additive across
components:

| new component | model | backtestable? |
|---|---|---|
| **goalkeeper saves** | `gk_saves_poisson_from_team_conceded_v1` | **yes** — `saves` is 100% present all five seasons |
| **defensive contribution** | `trailing_dc_threshold_hit_bernoulli_v1` | **prospective-only** — DC data exists only in 2025-26 |

### Goalkeeper saves — principled, history-free

The repository's measured constants license a form with **no per-keeper saves history**: the GK save
rate is a **league constant ≈ 67.3% ± 0.4pp**, individual deviation is almost all noise, and
`saves + goals_conceded` is the shots-on-target-faced proxy, which is a **team-defence** property. So
for a goalkeeper,

```
saves ~ Poisson(k · λ_conceded),   k = save_rate / (1 − save_rate),
```

where `λ_conceded` is the **expected value of the fixture's Stage A team-conceded distribution** (the
opponent's scored-goals distribution the harness already builds per fixture, resolved through
`team_code`). `save_rate` is derived **fold-locally, point-in-time** as `Σ saves / Σ (saves +
goals_conceded)` over GK appearances (`kickoff_time < as_of`), clamped to `[0.50, 0.85]`, falling
back to the measured `0.673` only if a fold has no GK data. It is derived, never read from config.
`λ_conceded` is wired explicitly in the harness (a per-fixture team quantity the generic per-player
predictor protocol does not carry). Saves points = `saves // 3` (`config/scoring_2026_27.yaml`),
goalkeepers only. Non-goalkeepers get a point mass on zero saves.

Observed fold-local `save_rate` range across the 181 folds: **[0.6671, 0.6834]** — tightly around the
measured league constant, as the constant predicts.

### Defensive contribution — prospective-only Bernoulli

`defensive_contribution` and its raw inputs exist in **exactly one season, 2025-26** (0% earlier). The
composer only needs the threshold hit, so DC is modelled as a per-player Bernoulli
`p_hit = P(DC_count ≥ threshold[position])` (thresholds DEF 10 / MID 12 / FWD 12; DC points = 2; GK
absent from the threshold map, so GK `p_hit = 0`). `p_hit` is the player's shrunk empirical hit rate
over its trailing DC-measured appearances,

```
p_hit = (hits + α · pos_p) / (n + α),   α = 5, window 5,
```

shrunk toward the fold-local position hit rate `pos_p`. **NULL DC is never read as zero** (R: NULL ≠
0): a NULL-DC row (every row before 2025-26) is skipped and carries no signal, so in a fold with no
DC-measured position prior every `p_hit` is **0** and DC contributes nothing. DC therefore fires only
inside 2025-26. **DC coverage in this run:** 37 folds had DC history (exactly the 2025-26 folds);
24,822 target rows received a strictly positive `p_hit`.

> **Minutes-independence approximation (v2 limitation).** `p_hit` is estimated over appearances
> (`minutes > 0`), not conditioned on the minutes bin the composer later draws. A 90-minute shift is
> far likelier to reach the threshold than a short cameo, so applying one `p_hit` across all played
> bins is an approximation, recorded here.

### Composer: additive, no dimensional blow-up

The base 5-dimensional `PointsLookup` is unchanged. When saves or DC are present the composer draws
**two more uniforms** in a fixed appended order (saves, DC), computes `saves_pts` and `dc_pts`, and
sums them onto the base **before** folding negatives to 0 and clamping — so a goalkeeper's `−1`
concede penalty **nets against its save points on the TOTAL** rather than being folded prematurely.
When **neither** v2 component is present the two extra uniforms are **not** drawn, so **v1 is
reproduced bit-for-bit** (an offline test asserts this, and every v1 composer test still passes
unchanged).

## Correctness

- **R1:** no component uses `total_points`; the label is `decompose_points(...).total − bonus` under
  the 2026/27 rules. The realised label already includes saves and DC — v2 closes the prediction-side
  gap for those two.
- **NULL ≠ 0:** `defensive_contribution` is selected RAW (never coalesced) and NULL rows are dropped
  from DC history; `saves` / `goals_conceded` NULLs are skipped by the saves estimator.
- **Point-in-time:** every component's history is `kickoff_time < as_of`; the leakage assertion holds.
- **Season-scoped identity:** team resolution is `(season, team_id) → team_code`; player key `code`.
- **Reproducibility:** all Polars aggregations pin order; the composer draws in a fixed order with an
  explicit per-`(season, code, fixture)` seed. Determinism and v1 bit-for-bit tests pin this.

## Documented Stage-D-v2 limitations

- **Component independence / no team-coupling** (unchanged from v1).
- **Bonus, penalties, own goals, and cards remain unmodelled** on the prediction side; the label still
  includes them. v2 adds only saves + DC.
- **Defensive contribution is prospective-only** (2025-26 data), with the minutes-independence
  approximation above.
- **Saves** use no per-keeper history (the league-constant finding licenses deriving them from the
  team-conceded rate), and the saves count is truncated at 10 (negligible tail for a ~2.9-save mean).
- **Negative composed points** fold to 0 on the TOTAL, after saves and DC are added.
- **No-xG 2021-22** is reported separately and kept out of the headline.

## Result

_Single clean historical development run at commit `0960c48`, Monte-Carlo 2000 draws, points support
0..30. 181 folds (30/37/38/38/38 by season), 133,964 predictions, **0 Stage A join fallbacks**. The
reconciliation JSON is at `docs/results/phase4-stage-d-points-composition-v2-development.json`
(schema `stage_d_points_composition_v2_development/v1`); an independent recompute reproduces the
overall and headline mean log/CRPS as the prediction-weighted mean of the per-season reports to
`0.0e+00`, and the by-season / by-position prediction counts each sum to 133,964 exactly._

| slice | mean log | CRPS | PIT-80 | MAE | n |
|---|---|---|---|---|---|
| **overall (all seasons)** | 1.0808 | 0.5899 | 0.801 | 0.909 | 133,964 |
| **headline (xG-present, excl 2021-22)** | 1.0683 | 0.5807 | 0.799 | 0.891 | 113,260 |
| 2021-22 *(no-xG, excluded from headline)* | 1.1489 | 0.6403 | 0.803 | 1.009 | 20,704 |
| 2022-23 | 1.1161 | 0.6056 | 0.796 | 0.927 | 26,505 |
| 2023-24 | 1.0228 | 0.5524 | 0.801 | 0.858 | 29,725 |
| 2024-25 | 1.0723 | 0.5830 | 0.797 | 0.887 | 27,283 |
| 2025-26 | 1.0675 | 0.5847 | 0.798 | 0.897 | 29,747 |
| FWD | 1.1248 | 0.6231 | 0.793 | 0.901 | 16,010 |
| DEF | 1.0660 | 0.6286 | 0.804 | 1.024 | 44,678 |
| MID | 1.1833 | 0.6044 | 0.795 | 0.888 | 58,386 |
| GK | 0.6758 | 0.3814 | 0.820 | 0.662 | 14,890 |

### v1 → v2 before / after (same suite + saves + DC)

| slice | v1 mean log | v2 mean log | Δ |
|---|---|---|---|
| **overall** | 1.3106 | **1.0808** | −0.2298 |
| **headline (xG present)** | 1.3019 | **1.0683** | −0.2336 |
| 2021-22 (no-xG) | 1.3583 | 1.1489 | −0.2094 |
| 2022-23 | 1.3219 | 1.1161 | −0.2058 |
| 2023-24 | 1.2119 | 1.0228 | −0.1891 |
| 2024-25 | 1.2735 | 1.0723 | −0.2012 |
| **2025-26 (DC season)** | 1.4002 | **1.0675** | **−0.3327** |
| FWD | 1.1104 | 1.1248 | +0.0144 |
| DEF | 1.1505 | 1.0660 | −0.0845 |
| MID | 1.2119 | 1.1833 | −0.0286 |
| **GK** | **2.3936** | **0.6758** | **−1.7178** |

**Reading — development-only, exploratory; not a promotion verdict and not an upper bound.**

- **Goalkeeper is the dominant fix: log 2.3936 → 0.6758.** v1's GK score was badly miscalibrated
  precisely because saves — the bulk of GK scoring — were held at 0. Modelling `saves ~ Poisson(k ·
  λ_conceded)` from the league-constant save rate closes almost all of that gap; GK is now the
  *best*-scoring position, and its PIT-80 (0.820) is the only slice materially above nominal, a mild
  over-dispersion to note rather than a defect. GK log score improves by 1.72, which alone drives most
  of the headline move (GK is 11% of rows).
- **2025-26 improves most among seasons (1.4002 → 1.0675, −0.33).** It is the worst v1 season *and*
  the DC-scoring season: v1 left both saves and DC unmodelled on the prediction side while the label
  included them, and v2 closes both. The DC contribution is genuinely exercised (24,822 targets with
  `p_hit > 0`), though the saves fix is the larger part.
- **Every season and outfield DEF/MID improves**; **FWD regresses very slightly (+0.0144).** Forwards
  earn no saves and rarely reach the DC threshold (12), so the added DC draw can only *add* expected
  points where forwards almost never score them — a small over-prediction. This is a diagnostic for a
  minutes-conditioned DC successor, not a reason to retune v2.
- **Calibration stays sound** (overall PIT-80 0.801) and **CRPS is flat-to-slightly-better** (0.5959 →
  0.5899 overall); the gain is concentrated in the log score, i.e. in getting the *shape* right where
  v1 was missing mass (GK saves, DC).
- **0 Stage A fallbacks** — the `team_code` conceded join covered every fixture, so every `λ_conceded`
  feeding the saves component is a real Stage A prediction, not a league-mean substitute.

Penalties, own goals, cards, and bonus remain unmodelled; the composer still composes players
independently. Those are the next Stage-D increments, not this one.

## How to reproduce

```bash
# Build/verify the archive first (single-writer; run DuckDB jobs sequentially).
uv run python -m fpl.jobs.build_db

# The single authorized clean development run (refuses a dirty worktree; writes the JSON only
# after the postflight provenance check passes).
uv run python -m fpl.validate.dev_points_composition_v2 \
  --save-json docs/results/phase4-stage-d-points-composition-v2-development.json
```
