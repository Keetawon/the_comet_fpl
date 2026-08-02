# Phase 4 — Stage D v3 FULL-points composition (match-level joint draw + bonus): development record

> **DEVELOPMENT ONLY — EXPLORATORY. NOT A PROMOTION VERDICT.**
> This extends Stage D v2 from a per-player **non-bonus** composer to a **match-level joint**
> composer that adds **bonus**, producing a full-points xP distribution. There is **no comparator
> baseline in the run** and **no pre-registered Stage D promotion contract**; nothing here promotes
> any model or changes any frozen Stage A/B/C contract. The numbers are development diagnostics under
> the same unversioned historical proxies (target roster, first-kickoff cutoff) every stage carries,
> plus the Stage-D limitations below. Real-deadline knowledge-time validity is unproven.
>
> **v3 scores a DIFFERENT label than v2.** v2 scores realised **non-bonus** points; v3 scores
> realised **full** points (non-bonus **+** bonus). The two numbers are therefore **not a
> like-for-like delta** — v3 is a full-points quality read, not "v2 got better/worse".

## Why the composer had to become joint

Bonus is a **within-match rank**: FPL awards 3/2/1 to the top-three BPS players in each fixture. That
breaks per-player independence in two ways the v2 composer could not represent:

1. **Cross-player coupling.** Only one player can be a fixture's 3-point winner in a given world; a
   defender's bonus depends on whether *someone else* got a hat-trick.
2. **Own-scoring ↔ own-bonus coupling.** The same drawn haul that scores fantasy points also scores
   BPS and thus bonus. A player's own points and own bonus are positively correlated *within a
   world*, which a convolution of independent marginals destroys.

v3 fixes both by drawing a **whole fixture jointly** (`compose_fixture_full_points` in
`src/fpl/models/points_composition.py`). For each of *N* seeded Monte-Carlo worlds:

1. Every appeared player's components are drawn once from the **identical** fold-local distributions
   v2 already builds (minutes V3, goals V1, assists V1, team goals-conceded from the promoted Stage A
   model, GK saves V1, DC V1).
2. From those **same** drawn components each player gets both (a) their **non-bonus points** (via the
   unchanged `PointsLookup` + the v2 saves/DC extras) and (b) their **BPS** =
   `exact_part(drawn components)` + a fold-local residual draw.
3. The fixture's appeared players' BPS are **ranked** and 3/2/1 awarded with the exact FPL tie-break
   (`bonus = 3` if 0 strictly-greater BPS, `2` if 1, `1` if 2, else `0` — identical to
   `bps_bonus.award_bonus`).
4. Each player's **full points this world** = non-bonus points + bonus, folded to be non-negative and
   clamped to the support.

Because non-bonus points and BPS come from the **same** drawn components, the own-scoring ↔ own-bonus
correlation is captured **for free** — that is the whole reason to go joint rather than convolving an
independent bonus marginal. A regression test (`test_own_scoring_and_own_bonus_are_coupled_in_the_same_draw`)
pins this: a player who draws goals carries the bonus in the same world, and **no** probability mass
lands on the decoupled "scored but no bonus" outcome.

### Reuse, not reinvention

- The **BPS exact part** is `bps_bonus.exact_bps`, evaluated once per drawn cell into a
  `BpsExactLookup` (analogous to `PointsLookup`) and indexed in the hot loop — the same verified
  2026/27 BPS values (goals by position, assists, GK/DEF clean-sheet BPS) the standalone BPS study
  uses.
- The **empirical residual** is the standalone simulator's fold-local, point-in-time
  `ResidualModel` (`fit_residual_model` / `predict_mean`): a per-position ridge line on standardised
  `influence`/`creativity` plus the player's shrunk trailing residual profile. The drawn BPS is
  `exact_part + residual_mean + N(0, residual_sigma)` rounded to an integer.
- The **award** is `bps_bonus.award_bonus`'s exact tie-break reduction (a test pins the composer's
  award equals `award_bonus` on a fixture).

The v2 **per-player** path (`compose_points_distribution`) is untouched and reproduces bit-for-bit;
every existing v2/v1 composer test still passes.

## Support

Full-points support is **0..34**: v2's 0..30 non-bonus support plus the maximum 3 bonus points, with
1 of headroom, tail folded into the final bin. The maximum realised full points under 2026/27 rules
across the archive is **26**, so no realised observation is ever clamped.

## Correctness

- **R1:** no component uses `total_points`; the label is the recomputed non-bonus points
  (`decompose_points(...).total − bonus` under 2026/27 rules) **plus** the realised recorded `bonus`
  scoring component — i.e. the full recomputed total, never the cross-season recorded `total_points`
  (which is not even a column of the mart).
- **NULL ≠ 0:** `defensive_contribution` and `clearances_blocks_interceptions` are selected RAW and
  NULL rows carry no signal (never a fabricated zero); `saves`/`goals_conceded` NULLs are skipped by
  the saves estimator.
- **Point-in-time:** every component history and the BPS-residual training set are `kickoff_time <
  as_of`; the leakage assertion holds. The residual's own-row guard is preserved — a player's own
  realised BPS/bonus for the predicted row is never a model input (only prior rows form the trailing
  residual).
- **Season-scoped identity:** team resolution is `(season, team_id) → team_code`; player key `code`.
- **Reproducibility:** all Polars aggregations pin order; each fixture is one joint draw with an
  explicit per-`(season, fixture)` seed and a fixed player/uniform draw order, so the same inputs
  reproduce every player's pmf bit-for-bit. A determinism test pins this.

## Documented Stage-D-v3 limitations

- **Cross-player component independence remains.** v3 draws each player's *components* independently;
  the **only** joint coupling it adds is the within-match **bonus rank**. There is still **no
  team-goal-total conservation** (a v2 limitation carried forward).
- **BPS-residual proxy caveat.** The residual's `influence`/`creativity` correction reads the **target
  row's realised ICT values**, exactly as the standalone development BPS study does. This is a
  development-only proxy (ICT is a match outcome), recorded honestly here; it is *not* a
  real-deadline-safe input. The own realised BPS/bonus is still never read.
- **Penalties, own goals, and cards remain unmodelled** on the prediction side; the label includes
  them.
- **Defensive contribution is prospective-only** (2025-26 data).
- **Negative composed points** fold to 0 on the TOTAL, after saves, DC, and bonus.
- **No-xG 2021-22** is reported separately and kept out of the headline.

## Result

_Single clean provenance-guarded archive dev run: Monte-Carlo 2000 draws, full-points support
0..34 (v2's 0..30 non-bonus plus up to 3 bonus, 1 headroom), 181 folds, 133,964 predictions,
**0 Stage A join fallbacks**. Independent recompute reproduces the overall/headline mean log
scores (diff < 1e-15) and the by-season / by-position prediction counts each sum to 133,964._

| slice | mean log | CRPS | PIT-80 | MAE | n |
|---|---|---|---|---|---|
| **overall (all seasons)** | 1.0988 | 0.6511 | 0.808 | 0.998 | 133,964 |
| **headline (xG-present, excl 2021-22)** | 1.0835 | 0.6409 | 0.807 | 0.978 | 113,260 |
| 2021-22 *(no-xG, excluded from headline)* | 1.1824 | 0.7072 | 0.811 | 1.103 | 20,704 |
| 2022-23 | 1.1374 | 0.6727 | 0.804 | 1.025 | 26,505 |
| 2023-24 | 1.0386 | 0.6101 | 0.808 | 0.943 | 29,725 |
| 2024-25 | 1.0941 | 0.6440 | 0.808 | 0.976 | 27,283 |
| 2025-26 | 1.0706 | 0.6404 | 0.808 | 0.975 | 29,747 |
| GK | 0.6967 | 0.4211 | 0.833 | 0.730 | 14,890 |
| DEF | 1.0807 | 0.6757 | 0.816 | 1.102 | 44,678 |
| MID | 1.1928 | 0.6644 | 0.797 | 0.967 | 58,386 |
| FWD | 1.1806 | 0.7481 | 0.795 | 1.069 | 16,010 |

**Reading — development-only, exploratory; not a promotion verdict.**

- This is the FULL-points xP (appearance + goals + assists + clean sheet + conceded + saves + DC +
  **bonus**), scored against realised full `total_points` (recomputed non-bonus, R1-safe, plus the
  realised `bonus` component). It is **not like-for-like** with the v2 non-bonus number (1.0683
  headline) — v2 scored non-bonus xP against non-bonus points; v3 adds bonus on both sides.
- **Calibration holds with bonus added:** PIT-80 0.795–0.833 across slices against the nominal
  0.80, so the joint match-level bonus simulation does not blow up the distribution.
- **Goalkeeper stays the best-calibrated position** (log 0.6967, PIT-80 0.833) — saves + clean
  sheet + bonus are all modelled, and GK points have low spread.
- **Attackers (FWD 1.1806, MID 1.1928) carry the most residual** — high-variance returns plus the
  bonus rank adding variance where it is hardest to place.
- **0 Stage A fallbacks** confirms the `team_code` join covered every fixture.
- Bonus is added by **joint per-fixture Monte-Carlo**: each world draws every player's components
  once, computes both non-bonus points and BPS from that same draw, ranks the fixture, and awards
  3/2/1 — so a player's own bonus is correlated with their own scoring, and only one player wins
  the fixture's 3 in each world. The BPS exact part uses the drawn components; the hidden-Opta
  residual (~3.5% of bonus) is a fold-local point-in-time Gaussian, unchanged from the standalone
  BPS study. The v2 per-player non-bonus path is retained and reproduces bit-for-bit.

## How to reproduce

```bash
# Build/verify the archive first (single-writer; run DuckDB jobs sequentially). The influence ICT
# column must be present (it is a BPS proxy the residual reads).
uv run python -m fpl.jobs.build_db

# The single authorized clean development run (refuses a dirty worktree; fingerprints BOTH
# points_composition.py and bps_bonus.py as model sources; writes the JSON only after the postflight
# provenance check passes).
uv run python -m fpl.validate.dev_points_composition_v3 \
  --save-json docs/results/phase4-stage-d-points-composition-v3-development.json
```
