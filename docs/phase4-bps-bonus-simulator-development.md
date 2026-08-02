# Phase 4 — Hybrid BPS / bonus match-simulator (development-only)

> **DEVELOPMENT ONLY — NOT A PROMOTION RESULT.** This is an exploratory accuracy study that
> answers one decision-gating question: **how accurately can we predict who wins FPL bonus
> (3/2/1)?** It is not a pre-registered contract, has no promotion gate, and is **not integrated
> into the Stage D points composer**. The exact part is computed from *recorded* match components,
> which deliberately isolates BPS-reconstruction accuracy (the hidden-Opta residual) from
> component-prediction error, which Stages A–C validate separately. A production integration would
> feed *predicted* component distributions in place of the recorded ones.

## Headline

Over the full five-season archive (181 walk-forward folds, 1,820 fixtures, 54,070 appeared
player-fixture bonus predictions, 0 leakage failures, 0 reconciliation failures):

| metric | value |
|---|---|
| **Expected share of realised bonus points assigned to the right players** | **70.4%** |
| Hard-podium share (predicted top-3 awarded 3/2/1) | 70.9% |
| **Top-1 hit rate** (predicted best player is the actual 3-point winner) | **70.7%** |
| Top-3 overlap (predicted top-3 ∩ actual recipients, / 3) | 77.5% |
| Exact-podium rate (predicted 3/2/1 all correct and in order) | 17.4% |
| Mean log score on the bonus (0–3) distribution | 0.2122 |
| Mean RPS on the bonus (0–3) distribution | 0.0757 |

So the honest answer is: **this hybrid reconstructs the 3-point bonus winner about 71% of the
time and places roughly 70% of all realised bonus points on the right players** — short of the
~80–90% the ~96%-computable framing might suggest, and the [Caveats](#caveats-and-honest-scope)
below explain why. The provenance record is in
[`docs/results/phase4-bps-bonus-simulator-development.json`](results/phase4-bps-bonus-simulator-development.json).

## Why a hybrid is plausible, and its ceiling

FPL bonus goes to the top-three players by BPS in each match. BPS is an Opta-driven per-player
score whose full formula depends on inputs this repository does not hold (key passes, big chances,
crosses, pass-completion %, fouls, dribbles, the CBI inside/outside split, saves inside/outside the
box, big-chance saves) — and the primary Opta source (FBref) is blocked. So BPS cannot be
reconstructed exactly.

But an archive measurement (reproduced by this runner) shows that of all awarded bonus points:

- **75.5%** go to players with a **goal or assist**,
- **20.9%** go to players with a **clean sheet** (and no goal/assist),
- **3.53%** go to players with **neither** — the pure hidden-Opta residual.

The first two are events this project already models, so a hybrid of an exact-computable part plus
an empirical residual is plausible. The **3.53%** hidden-Opta share is the irreducible ceiling for
*which player earns bonus* only in the loosest sense — see the caveats: the residual also has to
resolve the **ordering** among several goal-scorers/clean-sheet-keepers in the same match, which
is where most of the lost accuracy is.

## The model

`simulated BPS = exact part + empirical residual`, per player-fixture; the fixture's players are
then ranked jointly by Monte-Carlo to produce each player's bonus (0–3) marginal distribution.

### Exact part — verified BPS values only (`src/fpl/models/bps_bonus.py::exact_bps`)

Only BPS values **verified against an official Premier League source** are used, and they live in
`config/scoring_2026_27.yaml` under a new `bps:` block with a `verification:` record. `calculate_points`
never reads this block.

| BPS component | value (2026/27) | source |
|---|---|---|
| Goal — GK / DEF | +12 | PL BPS explainer (base values) |
| Goal — MID | +18 | PL BPS explainer |
| Goal — FWD | +24 | PL BPS explainer |
| Penalty goal | +12 (flat) | PL BPS explainer |
| Assist | +9 | PL BPS explainer |
| Clean sheet — GK / DEF (60+ min) | +12 | PL BPS explainer |
| Penalty save | +7 (was 8) | PL 2026/27 BPS-changes article |
| CBI (clearances+blocks+interceptions) | +1 per 3 (was per 2) | PL 2026/27 BPS-changes article |

The official pages returned HTTP 403 to the build environment's fetcher, so a reproducible
`sha256` byte capture could not be taken; `verification.sources[].capture_status` records that gap
honestly rather than fabricating a hash. No unverified BPS value was promoted to config.

### Folded into the residual — documented gaps (not guessed)

Recorded in `config/scoring_2026_27.yaml` under `bps.verification.residual_gaps`:

- **Minutes/appearance tiers**, **cards**, **own goals**, **penalties missed**, **goals
  conceded** — not byte-verifiable in this environment, so left to the residual rather than
  hard-coded from memory.
- **Saves** — 2026/27 removed the outside-box save metric and added a big-chance-save metric, so
  BPS scores **inside-box saves +1 each** plus hidden big-chance saves. The data has neither the
  inside/outside location nor the big-chance flag, so saves are **not a uniform per-save value**
  and are left to the residual. This is exactly the "if you cannot pin it, fold saves into the
  residual" instruction.
- **Penalty-goal delta** — a penalty goal is a flat +12 in the BPS, but the archive has no
  penalties-scored flag, so all goals take their positional value and the delta folds in.
- **CBI before 2025-26** — unmeasured (NULL, never zero-filled); its contribution folds in on
  those rows.
- **Hidden Opta** — key passes, big chances, crosses, pass-completion %, fouls, dribbles, tackles
  won, recoveries, errors, dispossessions, offsides (~3.5% of awarded bonus).

### Empirical residual — fold-local and point-in-time

`residual = bps − exact_part`, fit only on prior appeared rows (`kickoff_time < as_of`). For each
position it is `positional_mean + player_role + ridge_line(influence, creativity)`:

- **player role** — the player's trailing-window (last 10 appeared rows) mean residual, shrunk to
  the positional mean (prior strength 10). Captures habitual role-based hidden BPS (a keeper's
  saves, a holding midfielder's ball-winning).
- **ridge line** — a fold-local ridge regression of the centred residual on standardised
  `influence` and `creativity` (the all-round/creative BPS proxies). Captures a *this-match*
  unusually-high involvement.
- **noise** — per-position residual RMSE (floored at 2 BPS) drives the Monte-Carlo spread, which
  is the only source of bonus uncertainty given the recorded box score.

Fitting uses **incremental sufficient statistics** so each expanding-window fold refits in O(1)
per position; a test asserts the incremental fit equals the batch fit bit-for-bit.

### Bonus award — the exact FPL tie-break (`award_bonus`)

Bonus is a within-match rank. The FPL tie rules (tie for 1st → 3,3,…,1; tie for 2nd → 3,2,2; tie
for 3rd → 3,2,1,1) all reduce to a single formula: **a player's bonus depends only on how many
players have strictly greater BPS** — 3 if none, 2 if exactly one, 1 if exactly two, else 0.
Validated against the archive: this reproduces recorded bonus in **56,271 of 56,272** appeared
player-rows (1,899 of 1,900 matches). The one exception (2021-22 fixture 8) is FPL's finer-grained
internal BPS breaking a displayed tie at 28, which the public data cannot see.

### Fixture simulation

Per fixture, each appeared player's BPS is drawn `exact_part + predicted_residual + N(0, σ)` and
rounded to an integer (integer draws exercise the tie-break realistically); over 500 seeded draws
the players are ranked jointly and awarded 3/2/1; the award frequency is the player's bonus
marginal. The RNG is seeded per fixture from a fixed base and players are processed in a fixed
order, so the whole run is reproducible.

## Results

Full record: [`docs/results/phase4-bps-bonus-simulator-development.json`](results/phase4-bps-bonus-simulator-development.json).

### Overall and by season

| slice | preds | fixtures | log score | RPS | assigned | hard | top-1 | top-3 ovl | podium |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **overall** | 54,070 | 1,820 | 0.21218 | 0.07565 | **0.7044** | 0.7086 | **0.7066** | 0.7751 | 0.1736 |
| 2021-22 | 8,283 | 300 | 0.23317 | 0.08249 | 0.7032 | 0.7015 | 0.6967 | 0.7744 | 0.1433 |
| 2022-23 | 11,345 | 380 | 0.20853 | 0.07576 | 0.7022 | 0.6992 | 0.7105 | 0.7746 | 0.1895 |
| 2023-24 | 11,384 | 380 | 0.20599 | 0.07087 | 0.7199 | 0.7282 | 0.7395 | 0.7860 | 0.2026 |
| 2024-25 | 11,566 | 380 | 0.20376 | 0.07187 | 0.7119 | 0.7180 | 0.6816 | 0.7833 | 0.1816 |
| 2025-26 | 11,492 | 380 | 0.21524 | 0.07918 | 0.6843 | 0.6948 | 0.7026 | 0.7570 | 0.1447 |

Accuracy is stable across seasons (top-1 68–74%, assigned 68–72%). It is *not* systematically
better in 2025-26 despite CBI being measured only then — CBI is a small BPS term and the
attacking/clean-sheet drivers dominate.

### By position (record-grain metrics only)

Fixture-level rank metrics are **omitted** per position: a position is not a complete fixture, so
ranking goalkeepers only against goalkeepers would be meaningless. The record-grain metrics are
valid:

| position | preds | log score | RPS | assigned |
|---|---:|---:|---:|---:|
| GK | 3,686 | 0.28400 | 0.09696 | 0.6430 |
| DEF | 18,184 | 0.23876 | 0.08797 | 0.6156 |
| MID | 25,483 | 0.18354 | 0.06233 | 0.7418 |
| FWD | 6,717 | 0.20943 | 0.08118 | 0.7737 |

The model captures **attacking** bonus best (FWD/MID assigned 74–77%) and **defensive/GK** bonus
worst (GK/DEF 62–64%) — consistent with the hidden-Opta residual being concentrated in defensive
and goalkeeping actions (saves, big-chance saves, CBI, recoveries) the exact part cannot see.

## Caveats and honest scope

1. **The exact part uses recorded components, not predictions.** This is intentional — it isolates
   BPS-reconstruction accuracy from Stage A–C component-prediction error — but it means the ~71%
   is an **upper-ish bound on the BPS-reconstruction step given a perfect box score**, not an
   end-to-end bonus-prediction accuracy. Feeding predicted goals/assists/minutes/clean-sheets would
   lower it.
2. **The ~3.53% hidden-Opta share is not the accuracy ceiling for the *winner*.** Most lost
   accuracy is in **ordering** players who all scored/kept a clean sheet in the same match: which
   of two goal-scorers, or a scorer vs a two-assist creator, tops the BPS depends heavily on the
   hidden Opta (pass volume, tackles, CBI), so even with the box score the top-1 winner is
   genuinely uncertain ~29% of the time.
3. **Historical `bps` was computed under prior-season BPS rules.** The residual is trained on
   realised `bps` values denominated in each season's then-current BPS, a known approximation
   (the 2026/27 tweaks are marginal). We validate on the **rank outcome** (realised bonus), not on
   BPS values, so this approximation affects only the residual's calibration, not the target.
4. **Development-only proxies.** Like the other phases, the historical run uses the archive as
   development evidence, not a fresh holdout; there is no promotion gate here.

## Governance note

Using `influence`/`creativity` as BPS proxies is **legitimate** and is **not** the earlier
ICT-substitution-into-a-goals-model defect. Two reasons: (a) BPS is itself an Opta-index construct,
so ICT indices are natural, in-domain proxies for its hidden components; and (b) the simulator is
validated against **realised bonus**, the true rank outcome, not against a fabricated target. No
new dependency was added. The `bps:` config block carries only values verified against official
Premier League sources, with every unverifiable/absent component named under
`bps.verification.residual_gaps`.

## Reproduce

```bash
python -m fpl.validate.dev_bps_bonus_simulator            # full archive, development only
python -m fpl.validate.dev_bps_bonus_simulator --season 2025-26
```

The runner refuses a dirty worktree, records the clean commit SHA, the scoring-config fingerprint,
the `bps_bonus` model-source fingerprint, the database fingerprint, the seed, and UTC start/end,
and re-verifies all of them after the database is closed; if anything moved during the run the
result is suppressed as INVALID/UNPUBLISHABLE.
