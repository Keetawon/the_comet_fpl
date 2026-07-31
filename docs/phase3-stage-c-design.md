# Phase 3 Stage C design: player event components

**Status: design / pre-registration PROPOSAL, for review before any contract is frozen or any
model is fit.** This is the mandated first step of a new stage — define the target decomposition,
population, grain, baselines, metrics, walk-forward, and gate before fitting — exactly as Phase 1
(Stage A) and Phase 2 (Stage B) began. Nothing here is implemented or evaluated. The frozen
`config/phase3_evaluation.yaml` contract and its typed loader come *after* this design is agreed.

Stage C converts the Stage A team-goal distribution and the Stage B player-minutes distribution
into each player's **scoring event components** for a fixture. Stage D (later) aggregates those
components through the season's scoring rules into a full points distribution. Stage C does **not**
model FPL points directly.

## Non-negotiable framing (R1 and the correctness rules)

- **Never model or target recorded `total_points`.** Stage C models the underlying *components*
  (goals, assists, clean-sheet indicator, saves, cards, DC, bonus/BPS inputs). Stage D applies the
  target season's `config/scoring_<ruleset>.yaml` to the modeled components. A scoring-rule change
  is a config + replay change, never a model retrain.
- **Model distributions, not expected values.** Each component is a distribution (e.g. a player's
  goal count is a small-count distribution; clean sheet is a Bernoulli), because bonus, captaincy,
  and the eventual optimiser need the whole shape, not a mean.
- **Point-in-time and identity rules carry over unchanged.** Grain `(season, code, fixture)`;
  cross-season player identity is `code`, club identity is `team_code`; `element_id`/`team_id`
  never joined bare across seasons; NULL never zero-filled; assistant managers excluded; features
  point-in-time correct under `kickoff_time < as_of`; the minutes model stays separate from
  per-minute rate models (R6 — Stage C rates are *per-minute or per-appearance*, combined with the
  Stage B minutes distribution, never a single joint blob).

## What the data allows — measured coverage (this archive)

The signals available to Stage C are not uniform across the five seasons. Measured on
`mart_fact_player_fixture` (138,707 rows):

| signal | 2021-22 | 2022-23 | 2023-24 | 2024-25 | 2025-26 | backtestable? |
|---|---:|---:|---:|---:|---:|---|
| goals_scored, assists, clean_sheets, goals_conceded, saves, cards, bonus, bps | 100% | 100% | 100% | 100% | 100% | yes, all five seasons |
| threat, creativity | 100% | 100% | 100% | 100% | 100% | yes |
| expected_goals / expected_assists / expected_goals_conceded (xG/xA/xGC) | **0%** | **68%** | 100% | 100% | 100% | **partial** — absent 2021-22, 64–68% in 2022-23 |
| **defensive_contribution (DC)** | **0%** | **0%** | **0%** | **0%** | **100%** | **NO** — exists in exactly one season |

Two coverage facts shape the whole stage:

1. **xG/xA are absent in 2021-22 and partial in 2022-23** — the same gap Stage A found. An
   xG-based attacking model degenerates to a non-xG fallback in 2021-22, so xG-vs-goals must be
   judged *within the seasons that measure xG*, never on a pooled five-season figure (which reads
   xG's absence as a result). `threat`/`creativity` are the all-season fallback signals.

2. **DC is present in exactly one season (2025-26)** — yet it is a **2026/27 scoring element**
   (defenders/midfielders earn points for defensive contributions). This is the Stage-C analogue of
   the availability problem in Stage B: **the DC component cannot be walk-forward-validated on
   history** — four of five seasons carry no DC label at all. It must be a **separately named,
   single-season-development / prospective-only component** that may **not** claim historical lift,
   exactly like the availability adjustment was carved out of the minutes model. Its underlying
   inputs (`tackles`, `recoveries`, `clearances_blocks_interceptions`) *are* present earlier, so a
   proxy DC target can be *reconstructed* for earlier seasons — but whether that reconstruction
   matches the official DC definition is unverified and must be treated as an assumption, not a
   fact.

## Component decomposition (proposed)

Stage C is a set of separately-registered component models on the same eligible rows, each a
distribution, each conditioned on the upstream Stage A / Stage B outputs. The proposed components,
their target-season point drivers, their signals, and the measured constant that anchors each prior:

| component | distribution | conditioned on | primary signal | anchoring measured constant |
|---|---|---|---|---|
| **Attacking — goals** | player goal count | team goals (Stage A), minutes (Stage B) | xG share (where measured) else threat share | finishing (goals−xG) does **not** persist → shrink almost fully to the positional mean; attacking *share* travels with a transferred player, team *scale* does not |
| **Attacking — assists** | player assist count | team goals, minutes | xA share (where measured) else creativity share | for defenders the attacking signal is **xA, not xG** (persistence 0.784 vs 0.319) |
| **Clean sheet / goals conceded** | Bernoulli (CS) + conceded count | team goals-conceded (Stage A), minutes ≥ 60 (Stage B) | team defensive system | defence is a **team-system property**, not a player one; rescale to the club, never carry a transferred player's CS rate over |
| **Saves (GK)** | save count | shots-on-target faced (proxy: saves + goals_conceded), minutes | `saves + goals_conceded` proxy | GK save rate is a **league constant 67.3% ± 0.4pp** — individual deviation is almost all noise |
| **Cards** | Bernoulli (yellow), rare (red) | minutes, positional/role base rate | base rates | (to be measured; likely low-signal, near a positional constant) |
| **DC (defensive contribution)** | count vs the position threshold | minutes, role | tackles + recoveries + CBI | **single-season-development / prospective-only** — see coverage note; no historical-lift claim |
| **Bonus / BPS** | small-count (0–3 bonus) | the modeled BPS inputs | bps components | derived last, from the other components; ordering within a fixture matters |

Team strength enters **multiplicatively** (`atk × def_opponent`), per the measured constant
(correlation 0.439 multiplicative vs 0.070 subtractive). Shares must sum correctly: the players'
modeled goal (assist) probabilities on a team are coupled by the team-goal total from Stage A —
the component model distributes the team's goals among its players, it does not predict each
player independently and hope they add up.

## Proposed pre-registration (to be frozen after review)

- **Grain / population:** `(season, code, fixture)`, the same eligible registered-player population
  as Stage B (non-NULL minutes, zero-minute rows retained — a player who did not play contributes
  a degenerate all-zero component, which is real information for the optimiser).
- **Walk-forward:** the same 181-fold expanding-window structure over observed gameweeks
  (30/37/38/38/38), cutoff = first kickoff of the predicted gameweek. Each component is fitted
  fold-locally. xG-dependent components are judged **within xG-covered seasons** and separately on
  the non-xG fallback; the pooled five-season number is reported but is not the judging figure for
  an xG component.
- **Baselines (per component, proposed):** a positional base-rate baseline (the component's mean
  for the player's position, fold-local) and a trailing-player baseline (the player's own recent
  rate), mirroring Stage B's baseline pair. Each component is scored on its own proper metric.
- **Metrics:** proper scoring per component — log score / RPS for the count distributions, Brier
  for the Bernoulli components — plus calibration (reliability, PIT where applicable), reported the
  same way Stage B reports them. A **points-level** check (components → Stage D scoring → predicted
  points distribution vs realised points, mean log score / CRPS) is the integrative metric, but it
  is a Stage D concern; Stage C gates each component on its own distribution.
- **Gate (proposed, per component):** a fixed relative-lift gate over the best component baseline,
  with no calibration regression — the same shape as Stage A/B, thresholds to be set in the frozen
  contract. The DC component has **no historical gate** (uninvalidatable on history); it is
  prospective-only.

## Knowledge-time honesty (carried forward)

- The historical roster/position/club is an **unversioned archive proxy**, exactly as in Stage B;
  a historical Stage C number is a development number, not a real-deadline validity claim.
- **DC and any availability-derived feature are prospective-only** — no historical-lift claim.
- xG's absence in 2021-22 and partial 2022-23 is a data gap, never quoted as a result.

## Proposed first implementable slice (smallest useful, highest leverage)

**The attacking-goals component**, because it is the largest points driver, its research is already
done (shares travel / finishing doesn't persist / multiplicative strength / xG-where-measured), it
is fully backtestable on 2023-24 onward, and it exercises the hardest new mechanic — distributing a
team-goal total from Stage A among its players as coupled shares. Its baselines (positional goal
rate; trailing player goal/xG share) and its proper-score gate would be frozen first, then the
component implemented and development-evaluated under the same one-authorized-run discipline as
every prior candidate.

Everything above is a proposal. On agreement it becomes the frozen `config/phase3_evaluation.yaml`
(contract version 1.0) plus this document's as-built counterpart, before any component is fit.
