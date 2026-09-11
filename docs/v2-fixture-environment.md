# `FixtureEnvironment` — the contract between football and fantasy

Module: `src/fpl/artifacts/fixture_environment.py`

## Why it exists

V1 hands downstream a single scalar per side: the team's expected goals. Every FPL component
then reconstructs whatever football context it needs from that one number, and three of the
repository's recorded defects are downstream of exactly that.

The clearest is goalkeeper saves. With only `lambda_conceded` available, shots on target faced
can only be `lambda_conceded / (1 - save_rate)` — an identity, not a prediction. Measured on
this archive, `corr(team shots on target allowed, goals allowed) = 0.621` over 3,800
team-matches, so the identity treats a 0.62 relationship as if it were 1.0.

A `FixtureEnvironment` carries the football prediction as a bundle instead.

## Shape

```
FixtureEnvironment
  season, fixture, gw, kickoff_time, rho, engine
  home: TeamEnvironment   (was_home=True,  enforced)
  away: TeamEnvironment   (was_home=False, enforced)

TeamEnvironment
  team_code                      cross-season club identity, never team_id
  goal_distribution              the pmf, not a mean
  expected_goals                 validated against the pmf's own mean
  expected_goals_against
  expected_shots_on_target       / _against
  expected_shots                 / _against
  expected_goals_on_target_value / _against
  expected_box_touches           / _against
  expected_big_chances           / _against
  expected_defensive_actions
  cold_start                     did a rating fall back to its prior
  signal_coverage                which signals actually contributed
```

## Three load-bearing properties

**Every non-goal field is `float | None`.** `None` means the engine had no signal for it, which
is the normal case for a season the provider does not cover. A component receiving `None` must
fall back explicitly; reading it as zero would claim a team faces no shots at all. This is the
`NULL != 0` rule applied at the model boundary rather than only at the data boundary.

**`goal_distribution` is a distribution.** Clean sheets, the goals-conceded penalty and the
bonus simulation all need mass, not expectation. `clean_sheet_probability` is the zero mass of
the OPPONENT's distribution, read directly rather than rebuilt from a `lambda_against` scalar —
so the two can never disagree, and whatever shape the engine predicted survives.

**It validates itself.** A pmf that does not sum to one is refused; `expected_goals` that
disagrees with its own distribution is refused; mislabelled home/away sides are refused; a
fixture whose two sides carry the same `team_code` is refused. Each of these would otherwise be
a silent mispricing rather than an error.

## Direction

`*_against` is what a club is predicted to FACE. It is not the opponent's `*_for`: it is the
opponent's attacking rate evaluated against THIS club's defence at THIS venue. The engine
obtains it by reading the same fitted rating system with the sides swapped, which is why the
two are automatically consistent and why the against-side costs no extra model. Both directions
are carried because a component usually needs one specific direction, and deriving the wrong one
is silent.

## What consumers may do

* read a field, and fall back explicitly when it is `None`;
* read `goal_distribution` and `goals_conceded_distribution`, which are full pmfs;
* read `clean_sheet_probability`.

They may not sum probabilities across fixtures, rebuild a distribution from a mean, or treat an
absent signal as zero. `summarise_coverage` exists so a result can always state its own
denominator: a V2 run in which most rows fell back has not tested V2, and must be able to say so.
