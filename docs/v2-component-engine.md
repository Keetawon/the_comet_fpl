# V2 component engine

Module: `src/fpl/models/component_engine_v2.py`

The join between the football half of V2 and the FPL half. It is an **adapter, not a rewrite**:
`models/points_composition.py` already accepts exactly the right input — minutes, goals,
assists, goals conceded, saves and a DC probability per player-fixture — so V2 plugs in at that
boundary with no change to the composer, the prospective artifact contract, or the optimizer.
That is why "optimizer compatibility" is not a piece of work: it is a consequence of the
contract already being in the right place.

## Component by component

| component | V1 | V2 | changed? |
| --- | --- | --- | --- |
| minutes | Stage B trailing bins with Dirichlet shrinkage | identical | no |
| goals | Stage A lambda x trailing xG share, minutes-gated | environment `expected_goals` x the same share | scale only |
| assists | Stage A lambda x trailing xA share | environment `expected_goals` x the same share | scale only |
| goals conceded | opponent's Stage A distribution | the opponent's environment distribution | source only |
| saves | `k * lambda_conceded`, an identity | `save_rate * predicted shots on target faced` | **yes** |
| DC | per-player trailing threshold hit rate | team defensive-action environment x role share x minutes | **yes** |
| bonus | joint within-match BPS simulation | identical | no |

Only two components change substantively. Keeping the attacking allocation identical is
deliberate: swapping the team scale AND the allocation at once would make any measured
difference unattributable, which is the same discipline the ablation ladder enforces upstream.

## Minutes is not touched, and that is a decision

SDP data says nothing about who a manager picks. V1's minutes work — the Dirichlet shrinkage
that took composer PIT-80 from 0.745 to 0.800, the equal-weighted season-boundary window, the
price-informed newcomer prior — remains valid and is carried forward unchanged. A V2 minutes
model is not required merely because a new data source exists.

## Conservation

The composer draws the minutes bin first and scores a bin-0 draw as exactly zero, so the rates
it receives must be **conditional on appearance**. The allocation produces unconditional rates
that conserve the team total, and `conditional_rate` divides `p_play` back out before handing
them over.

Getting this wrong is not hypothetical: applying the appearance gate twice was measured to
destroy **11.11%** of all goal and assist mass (537.05 allocated against 477.40 realised) before
it was found. `conserved_team_goals` re-derives the roster's realised expectation and
`test_the_adapter_conserves_the_teams_expected_goals` asserts it returns the team's expected
goals, so the defect cannot reappear silently.

## Defensive contribution: why the share travels and the scale does not

The repository's measured rule is explicit: defensive contribution is a property of the team
system (team hit rates range 0.333 to 0.146), so a transferred player's DC expectation must be
rescaled to the destination club, never carried over. V1's per-player trailing hit rate does
precisely what that forbids — a midfielder leaving a low-block side for a dominant one keeps a
rate earned in a system that gave him twice the defending to do.

V2 splits it the way the minutes/rate separation already splits playing time from event rate:

```
expected DC  =  team defensive-action environment   (from the fixture, so it is the NEW club)
              x player role share                   (dimensionless, so it travels)
              x minutes exposure
```

Shrinkage is toward the **position** mean, not a pooled mean: a defender and a forward make very
different shares of the same team's defending.

Minutes exposure uses the measured MINUTES shares (0.254 / 0.837 / 1.000 by bin), deliberately
**not** the measured goals-conceded exposure (0.344 / 0.813 / 0.999). That curve is steeper
because a substitute enters a game already going badly and late goals are more frequent — an
effect specific to conceding. Borrowing it here would import a constant measured for a different
quantity.

## Coverage governs everything

`defensive_contribution` exists in exactly one archived season (2025-26); every earlier row is
NULL, which is unmeasured and never zero. With no measured DC in a fold's training window the
model contributes nothing, exactly as V1 does. Likewise, a fixture for which the engine has no
defensive-action environment yields probability 0.0 with `used_environment=False` recorded,
rather than an invented environment.

## Status

Implemented and tested; **not wired into the prospective default**, because the V2 team
environment did not clear its pre-registered gate. See `docs/v2-team-engine-development.md`.
