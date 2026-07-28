# Candidate V3 design: a sequential dynamic team-goals model

**Status: development-only pre-registration.** This candidate is pre-registered for a
single *historical development* evaluation, not for promotion. The historical archive
(2021-22 through 2025-26) is **development evidence**, not a fresh holdout — V1 and V2
were already evaluated against it, so outcomes there have influenced this design.
Prospective 2026/27 data is reserved as the untouched confirmation set and is **not**
consumed here. No result in this document or in the development report is a promotion
verdict. The required Stage A baseline remains `trailing_goals_attack_defence`.

The machine-readable policy lives in `config/phase1_evaluation.yaml` under
`stage_a_candidate_v3` (amendment 1.4). The model is implemented in
`src/fpl/models/dynamic_team_goals.py`. Nothing about V2, the baselines, the outer
rows, the lift threshold, the CRPS rule, the calibration tolerance, the coverage
requirement, the fold requirement, or the leakage requirement changes.

## 1. Falsifiable hypothesis

Candidate V2 estimates batch attack and defence strength over an **expanding window**
by re-solving a global weighted-Poisson maximum likelihood (iterative proportional
fitting) on every fold, with a single exponential half-life. Its state is a snapshot:
the whole history is re-fitted at once, and the only way "recent form" is distinguished
from "underlying strength" is one decay knob chosen on an inner holdout. It missed the
promotion gate (1.4939 vs the 1.5003 best baseline, +0.4284% against the required 1%),
and the diagnosis in `AGENTS.md` is structural rather than parametric: its edge is
cross-season history and xG, **not** functional form, and it loses in exactly the
seasons/phases where that information is absent or thin.

**Hypothesis.** Team strength is a slowly time-varying latent quantity, not a fixed
parameter. Estimating it **sequentially** — carrying each club's strength forward as a
state that a single match can move, with explicit regression to the mean between
matches and an explicit summer shrinkage between seasons — should track changing
strength more honestly than a batch re-fit governed by one half-life, while still
retaining useful cross-season information through the retention factor. If the
hypothesis is wrong, the development log score will not beat the trailing-goals
baseline by a material margin, and that is the honest answer we will record.

This is a **different structural model**, not a post-hoc widening of V2's grids. V2
searches half-life and prior-strength on a batch IPF fit; V3 has no half-life and no
batch fit at all. Its knobs name distinct dynamic mechanisms (adaptation speed,
within-season memory, summer shrinkage), selected in-fold as before.

## 2. Model: a mean-reverting online Poisson filter in log space

Strengths are maintained in log space and combine multiplicatively with the venue
means, exactly as in V2 and the baselines (`attack × opponent defence` correlates 0.439
with goals here; the subtractive form manages 0.070):

```
λ(home, away) = μ_home · exp(α_home + β_away)
λ(away, home) = μ_away · exp(α_away + β_home)
```

`α_c` is club `c`'s log attack, `β_c` its log defence (positive = leakier). `μ_home`
and `μ_away` are the league mean goals scored at each venue, estimated once from the
fold's training window. Home advantage is a pooled league constant (measured 0.268
goals, never taken from one season), so the venue means are **not** dynamic — only the
per-club strengths are. This keeps the hypothesis focused on team strength.

### 2.1 Update order (the point-in-time core)

Matches are processed in **chronological order**. For each match, **both sides' rates
are computed from the pre-match state before either side is updated**:

```
# predict from current state — no same-match leakage
λ_home = clip(μ_home · exp(α_home + β_away), rate_floor)
λ_away = clip(μ_away · exp(α_away + β_home), rate_floor)

# residuals against the measured target (scaled xG where measured, else recorded goals)
r_home = m_home − λ_home
r_away = m_away − λ_away

# mean-revert (retain φ), then absorb one gradient-ascent step on the Poisson log-likelihood
α_home ← clip(φ · α_home + κ · r_home)
β_away ← clip(φ · β_away + κ · r_home)
α_away ← clip(φ · α_away + κ · r_away)
β_home ← clip(φ · β_home + κ · r_away)
```

`κ` is the learning rate; `φ` is the per-match retention (mean reversion toward 0, the
league mean). The gradient is the Poisson score `(y − λ)`; stepping in its direction is
log-likelihood ascent. The two sides of one match see only each other's pre-match state,
so a match's outcome cannot leak into its own prediction. Clubs not involved in a match
keep their state unchanged until they next play, so retention is **per appearance**.

Only the sum `α_team + β_opponent` ever enters a prediction, so the additive split
between a club's attack level and defence level is unidentified — and harmlessly so,
because predictions are invariant to the `(α + c, β − c)` shift. Mean reversion
(`φ < 1`) and a log-strength cap keep strengths bounded; no re-centring pass is needed.

### 2.2 Explicit between-season retention/shrinkage

At the first match of a new season, **before** it is processed, every club already in
the state is shrunk toward the mean:

```
for each club c in state:
    if c is promoted in the new season:   α_c, β_c ← promoted prior   # fresh cold start
    else:                                  α_c ← s · α_c ; β_c ← s · β_c
```

`s` is the **season retention** factor. The summer is a structural break (squad churn,
transfers, new managers), so shrinking more over the summer than over an equivalent run
of mid-season matches is a structural choice, not a tuning dodge. A club newly promoted
into the season — whether never seen before or relegated and returned — is reset to the
promoted prior at the boundary. Returning established clubs retain `s` of their
strength, which is the "useful cross-season information" the hypothesis wants to keep.

### 2.3 Prediction and the marginal

At fold prediction time the filter has replayed the entire training window
(`kickoff_time < as_of`) chronologically; the resulting state predicts the fold's
gameweek. The prediction is an **exact Poisson marginal** `poisson_pmf(λ)` — analytically
scored, no Monte Carlo (Monte Carlo belongs to the later player-points simulation, not
Stage A).

### 2.4 Cold start and promoted priors

A club with fewer than `minimum_team_matches` (6) prior appearances uses the declared
prior instead of its dynamic strength, and the prediction is reported as a cold start:

```
α_used = α_c        if matches(c) ≥ 6
       = log(prior) if c promoted in the prediction season
       = 0.0        otherwise                                   # neutral, exp(0)=1
```

symmetrically for the opponent's defence. Promoted status is season-scoped through
`team_code`: a club promoted in 2022-23 does **not** inherit the prior in 2024-25. The
prior values are the measured constants 0.719 (attack) / 1.309 (defence), carried as
declared config exactly as V2 carries them.

## 3. Point-in-time argument

The filter reads only the fold's `TrainingWindow`, which the harness has already
restricted to `kickoff_time < as_of`. Four leakage classes are addressed:

- **Target leakage.** No `mart_target_*` table, no `total_points`, no recorded-points
  column is read. The target is goals (and xG where measured), as for V2.
- **Event-time leakage.** Every training match satisfies `kickoff_time < as_of`; the
  fold's own gameweek is invisible (the harness asserts this per fold). Sequential
  processing cannot reach a future match because none is in the window.
- **Knowledge-time leakage.** The archive carries no authoritative deadline or
  schedule-version history, so the cutoff is the first kickoff of the predicted
  gameweek — the latest proxy that excludes every outcome in it. This is explicitly a
  proxy, not a claim that schedule or availability fields were known at the real
  deadline. No live/versioned fact is consumed.
- **Identity leakage.** Clubs are keyed on stable `team_code`, never season-scoped
  `team_id`. Matches are paired by the season-qualified key `(season, fixture)`.

Within-fold honesty: the learning rate, retention, season retention, and the xG-to-goals
scale are all fitted inside the fold on an inner observed-gameweek holdout, never on the
predicted gameweek and never on pooled outer results. The seed is the contract's
`202627`, used only for the randomized PIT.

## 4. Inner holdout and parameter selection

The inner holdout reuses V2's methodology: the last 6 **observed** gameweeks of the
training window are held out, requiring at least 12 observed gameweeks of inner training
history; otherwise the declared fallback is used and the fold is reported as such. For
each triple `(κ, φ, s)` in the grid, the inner training matches are replayed
chronologically to the state at the holdout boundary, the holdout gameweeks are
predicted, and the mean log score is computed. The triple with the lowest holdout mean
log score is selected (ties broken by grid order, deterministically); the full training
window is then replayed with the selected triple to produce the fold's predictions.
CRPS and calibration are reported as guardrails, not selection targets.

## 5. Proposed grid and rationale

Three knobs, each naming a distinct dynamic mechanism. The grid is fixed before any
development score is examined.

| Knob | Grid | Rationale |
|---|---|---|
| `learning_rate` κ | {0.05, 0.10, 0.20} | How strongly one match moves a club's strength. 0.05 ≈ slow (≈20 matches to track a shift); 0.20 reactive. |
| `retention` φ | {0.985, 0.995, 1.0} | Per-appearance persistence (within-season memory). 0.985⁻³⁸ ≈ half-life ~1.2 seasons; 1.0 = no forgetting. |
| `season_retention` s | {0.5, 0.75, 1.0} | Explicit summer shrinkage. 0.5 = lose half over the break (squad-churn aware); 1.0 = no extra summer shrinkage. |

Fallback (insufficient inner history): κ = 0.10, φ = 0.995, s = 0.75 (the grid
midpoints). The grid is 3 × 3 × 3 = 27 combinations, each a single chronological pass —
lighter than V2's 30 combinations of 60-sweep IPF fits. Boundary selections (a fallback,
or any grid edge chosen often) are recorded as diagnostics for a future structural
hypothesis, **not** as authorisation to widen this grid after seeing the result.

Fixed policy: rate floor 0.05 (as V2); log-strength cap 2.0 (exp ≈ 7.4 / 0.135) as a
safety against pathological drift; promoted priors 0.719 / 1.309; six-match cold start;
xG used where measured and scaled to goals inside the fold.

## 6. Development versus prospective confirmation

This evaluation is **historical development only**. Its purposes are (a) to test whether
the structural hypothesis is worth a future promotion attempt, and (b) to expose the
model's regime behaviour, parameter selections, and failure modes. Because the archive
has already shaped V1, V2, and now V3, a good historical number is necessary but **not
sufficient** evidence: it is overfit-by-construction to a fixed, already-seen set of
seasons. A genuine promotion attempt would require a separately pre-registered candidate
evaluated against prospective 2026/27 data as it accrues, under the unchanged promotion
gate. No 2026/27 outcome is read or predicted here.

## 7. Failure conditions and simpler alternatives

The development result will be recorded honestly. Expected failure modes:

- **No material lift over the trailing-goals baseline.** If the sequential filter does
  not beat a simple trailing ratio, the hypothesis (sequential adaptation helps) is
  falsified for this archive and the answer is another documented non-promotion. This is
  the most likely outcome given V1 and V2 both narrowly missed.
- **Drift or miscalibration at the grid edges.** If `retention = 1.0` or
  `season_retention = 1.0` is selected often and calibration degrades, that is evidence
  the no-forgetting regime is unstable, recorded as a diagnostic — not fixed by widening
  the grid after the fact.
- **Worse in 2021-22 / early-season regimes.** As with V1/V2, a model reliant on
  cross-season history and xG has little to work with in 2021-22 (no prior season, no
  xG). Regressing there is expected and is reported per season.

Simpler alternatives considered, and why this is still the minimal honest test:

- **Widening V2's half-life/prior grid.** Rejected by the task and by the contract: V2
  selected its 2-match prior boundary in 72/181 folds, and responding to that by widening
  the grid is exactly the post-hoc tuning a pre-registered gate exists to prevent.
- **A second batch IPF candidate with a different decay family.** The diagnosis says
  V2's weakness is not functional form; another batch fit would re-test the same
  structure.
- **A full Kalman-filter / state-space Poisson with estimated process noise.** Stronger
  in principle, but it needs an optimiser or conjugate approximations and extra
  hyperparameters (process and observation variance), adding dependency surface and
  tuning degrees of freedom for a development probe. The gradient-plus-retention filter
  is the minimal closed-form realisation of "sequential, mean-reverting, retaining" and
  needs no new dependency.

If the development result is poor, the model is left as committed and the verdict is
recorded; it is not tuned again after seeing the full result.
