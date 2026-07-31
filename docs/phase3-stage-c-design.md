# Phase 3 Stage C design: player event components

**Status: original design proposal, annotated after Stage C Increment 1 and the Candidate V1
audit.** Contract v1.0, the attacking-goals baselines, and the walk-forward harness are now
implemented; amendment 1.1 pre-registered Candidate V1, which has been evaluated once as
development-only evidence. The team-coupled architecture described here is **not yet implemented
or evaluated**. The attacking-goals *rate* has been probed once by a separately named
Candidate V1 (`xg_informed_trailing_player_goals_v1`, a development-only **historical xG-signal
probe, not this architecture** — independent player Poisson goal marginals with no Stage A
team-goal input, no Stage B minutes input, and no team-goal-total allocation or conservation; see
[`phase3-stage-c-attacking-candidate-v1-development.md`](phase3-stage-c-attacking-candidate-v1-development.md)).
Its only valid conclusion is narrow — **xG beats recent recorded goals where xG is measured on this
archive** — and the end-to-end team-coupled Stage C architecture (distributing a Stage A team-goal
total among coupled player shares, conditioned on Stage B minutes) remains **unvalidated**. The
frozen `config/phase3_evaluation.yaml` contract covers the implemented baseline/harness slice; it
does not make the proposed coupling architecture implemented.

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
| DC raw inputs: `tackles`, `recoveries`, `clearances_blocks_interceptions` | **0%** | **0%** | **0%** | **0%** | **100%** | **NO** — FPL never recorded them before 2025-26 (verified) |

Two coverage facts shape the whole stage:

1. **xG/xA are absent in 2021-22 and partial in 2022-23** — the same gap Stage A found. An
   xG-based attacking model degenerates to a non-xG fallback in 2021-22, so xG-vs-goals must be
   judged *within the seasons that measure xG*, never on a pooled five-season figure (which reads
   xG's absence as a result). `threat`/`creativity` are the all-season fallback signals.

2. **DC — and every raw defensive action feeding it — is present in exactly one season
   (2025-26)** — yet DC is a **2026/27 scoring element** (defenders/midfielders earn points for
   defensive contributions). Correction to an earlier draft of this design: the raw inputs
   `tackles`, `recoveries`, and `clearances_blocks_interceptions` are **not** present in earlier
   seasons — verified 0% non-null for 2021-22..2024-25 in `mart_fact_player_fixture`. The FPL
   archive simply never recorded defensive actions before 2025-26. **DC therefore cannot be
   reconstructed from FPL data alone**, and the component cannot be walk-forward-validated on FPL
   history — four of five seasons carry neither the DC label nor its inputs.

   There are two, non-exclusive ways to treat this:

   a. **Prospective-only from FPL alone.** A **separately named, single-season-development /
      prospective-only** DC component that may **not** claim historical lift, exactly like the
      availability adjustment carved out of the minutes model.

   b. **Backfill the defensive actions from an external per-match source** (e.g. FBref, which
      records tackles / interceptions / blocks / clearances per player per match back to 2017-18).
      This is the only path that makes DC backtestable across seasons. It is admissible **only if
      the external definition is proven to match FPL's**, and the archive gives us the exact test
      for that: **2025-26 is an overlap season carrying both FPL's own DC (and its raw inputs) and
      the external source's**. Reconstruct DC from the external actions on 2025-26 and require it
      to reproduce FPL's recorded DC before trusting the external backfill for 2021-22..2024-25.
      Until that agreement is demonstrated it is an assumption, not a fact. Identity is joined by
      **full name + club + season** (not `web_name`, which drifts), anchored/validated by
      `opta_code` where it exists — but note `opta_code` itself is only present for 2024-25 and
      2025-26, so it validates the recent join, not the seasons being backfilled.

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

> **Audit note (developed slice vs this proposal).** Candidate V1 as developed is narrower than this
> slice: it predicts independent player Poisson goal *marginals* from trailing xG/goals only and does
> **not** distribute a Stage A team-goal total among coupled shares, takes no Stage B minutes input,
> and applies no team/opponent/venue or transfer-rescaling context (it also conflates zero-minute
> player-fixture history with attack rate). So the team-coupling mechanic that this design makes the
> point of the first slice is **not yet exercised**; it is the unvalidated next step, to be
> pre-registered as a separately named candidate composing Stage A + Stage B.

The original proposal above led to the frozen v1.0 baseline/harness contract, but Candidate V1 did
not implement its team-coupled first slice. Any successor must be separately named and
pre-registered in a new additive amendment before implementation or evaluation.
