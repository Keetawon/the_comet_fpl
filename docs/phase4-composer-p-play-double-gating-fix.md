# Stage D composer: the P(play) double-gating defect and its repair

Status: **fixed forward**. This is a correctness repair to development-only tooling, not a
candidate, not a promotion, and not a re-judgement of any frozen evaluation.

## The defect

The minutes-gated Stage C allocation
(`fpl.models.attacking_v3.allocate_minutes_gated_rates`) returns

```
rate_i = lambda_team * share_i * p_play_i / sum_j(share_j * p_play_j)
```

whose defining property — the whole reason the team-coupled architecture exists — is conservation:
`sum_i rate_i == lambda_team`. That is an **unconditional** expectation. It already prices in the
chance that a player does not feature.

`compose_fixture_full_points` then draws the minutes bin and scores a bin-0 draw as exactly zero.
So the composer realises

```
E[goals_i] = p_play_i * rate_i
```

and `P(play)` has been applied **twice**. The roster no longer conserves `lambda_team`; it delivers
a strictly smaller total whenever anyone might be absent.

Four call sites carried it — goals and assists, in both
`fpl.validate.ev_backtest_adapter` and `fpl.jobs.prospective_points_v1`.

## Measured impact

Measured over the GW29-38 backtest horizon (8,224 player-fixture rows, primary V3 architecture):

| | goal + assist mass |
|---|---:|
| allocated by Stage C (conserves `lambda_team`) | 537.05 |
| realised by the composer | 477.40 |
| **destroyed by the second gate** | **59.65 (11.11%)** |

Mean `p_play` on rows carrying attacking mass: MID 0.798, DEF 0.804, FWD 0.822, GK 0.743.

## The repair

`fpl.models.points_composition.conditional_rate(unconditional, p_play, *, cap)` divides `p_play`
back out, so the composer realises `p_play_i * (rate_i / p_play_i) == rate_i` and the roster
conserves `lambda_team` again. `ComponentDistributions.goals` and `.assists` are now documented as
**conditional on appearance**, which is what the composer always required of them.

### Why the cap is not decoration

Substituting the allocation gives

```
rate_i / p_play_i == lambda_team * share_i / sum_j(share_j * p_play_j)
```

An **individual** player's `p_play` cancels — it appears in both the numerator and the roster
denominator — so one rotation risk among nailed team-mates is harmless. The **denominator** does
not cancel. If an entire roster is unlikely to feature, `sum_j(share_j * p_play_j)` collapses and
the conditional rate diverges: a uniform `p_play` of `1e-6` over three equal shares turns a
`lambda_team` of 1.6 into 533,333.

The limit is not meaningless — conditional on an unlikely player being the one who turns out, they
really would be carrying the entire attack — but no single player can be expected to outscore their
own team, so the result is capped at the fixture's `lambda_team` (`lambda_assist` on the assists
path). On a real roster the cap is inert; `test_the_cap_is_inert_on_a_realistic_roster` pins that.

`p_play <= 0` returns the input unchanged. The only path that reaches it is the fallback taken when
a roster's weighted shares sum to zero — nobody is expected to play at all — where the composer
scores every draw as zero regardless.

## Tests

Seven tests in `tests/test_points_composition_v3.py`. Five fail if `conditional_rate` is reverted
to the identity, confirming they bind on the defect rather than on the fix:

- `test_conditional_rate_inverts_the_composer_appearance_gate`
- `test_one_rotation_risk_among_nailed_team_mates_does_not_inflate_the_rate`
- `test_a_whole_roster_of_absentees_is_capped_at_the_team_rate`
- `test_corrected_roster_conserves_the_stage_a_team_goal_total`
- `test_the_composer_realises_the_unconditional_rate_end_to_end` — drives the real composer and
  inverts the points pmf back to the delivered goal mass, so it measures the composer rather than a
  reimplementation of it.

## What this does to the frozen backtest — and what it does not

`results/ev_backtest_2025_26_gw29_38.json` is immutable. It is **not** re-run, amended, or
re-judged, and it reproduces only at its pinned commit `8af5760`. The clean Git HEAD recorded in
that artifact remains its authoritative code identity; HEAD after this repair is a different
identity and makes no claim on it.

A read-only defect-impact diagnostic (no contract loaded, no metric scored, no gate consulted,
nothing written to `results/`) measured what the repair changes on the same 8,224 rows:

| | frozen (defective) | corrected |
|---|---:|---:|
| EV total | 9101.41 | 9339.92 |
| actual total | 8955 | 8955 |
| EV/actual | 1.0163 | 1.0430 |
| signed bias | +146.4 | +384.9 |

**The frozen run's one clear win was two errors cancelling.** Aggregate calibration of 1.0163 was
reported as the primary architecture's single advantage over the V1 comparator; it was the 11%
attacking-mass loss offsetting an over-prediction elsewhere. Repairing the defect removes the
offset and exposes the bias. That is the correct outcome — a composer that does not deliver its
own architecture's conservation property is wrong whichever direction the error points — but it
means the calibration advantage recorded in `AGENTS.md` and `README.md` should be read as
**unexplained cancellation, not evidence for the coupled architecture**.

## Where the remaining bias actually lives

A component-level decomposition on the same rows, with `P(play)` now applied once (model side
computed analytically from the same component distributions the composer draws; bonus taken from
the composer's own simulated `expected_bonus`):

| component | model | actual | diff | rel |
|---|---:|---:|---:|---:|
| appearance | 5033.9 | 5031.0 | +2.9 | +0.1% |
| goals | 1366.6 | 1212.0 | +154.6 | +12.8% |
| assists | 765.0 | 708.0 | +57.0 | +8.1% |
| clean sheet | 1246.8 | 1341.0 | −94.2 | −7.0% |
| goals-conceded penalty | −581.7 | −406.0 | −175.7 | +43.3% |
| saves | 128.8 | 128.0 | +0.8 | +0.6% |
| defensive contribution | 731.2 | 726.0 | +5.2 | +0.7% |
| bonus | 631.7 | 632.0 | −0.3 | −0.0% |
| **total (modelled components)** | **9322.3** | **9372.0** | **−49.7** | **−0.5%** |

Read the last row first. Across the components the composer actually models, it is accurate to
**−0.5%**. The `+4.3%` headline bias is not a modelling error at all: actual modelled components
total 9372 while actual *full* points total 8955, and the 417-point difference is the **unmodelled
negative components** — yellow and red cards, own goals, missed penalties — which the composer
holds at zero and reality subtracts. That gap is already documented in `points_composition.py`;
this quantifies it for the first time.

Three findings inside that near-zero total are worth separating, because they are not the same kind
of thing:

1. **The goals-conceded penalty is a genuine specification defect (−175.7 points, the largest single
   gap).** FPL charges a GK/DEF for goals conceded *while they were on the pitch*. The composer
   charges every appearing player the full-match team-conceded distribution regardless of the drawn
   minutes bin. Measured over GW29-38: GK/DEF rows playing 1-59 minutes conceded 105 goals across
   229 rows (0.459/row), against 1.280/row for 90-minute players — roughly a third the exposure,
   charged in full. This is fixable and is the next repair.

2. **Clean sheets under-predict by 7.0%, which is the same defect seen from the other side.** Too
   much conceded mass away from zero.

3. **Goals over-predicting by 12.8% is most likely regime, not miscalibration, and should not be
   "fixed".** GW29-38 ran at 2.576 goals per fixture, the lowest window in the archive (season
   averages 2.729 / 2.732 / 3.147 / 2.845 / 2.645). Stage A predicts near the pooled historical
   mean of about 2.9. On 99 fixtures the standard error of the mean is about 0.171, so the window
   sits roughly 1.9 standard errors low — within ordinary variation. Tuning Stage A down to match a
   99-fixture sample would be fitting noise, and would repeat the mistake `AGENTS.md` already
   records for home advantage. The position mix of allocated goals (a DEF goal scores 6, a FWD goal
   4) is a separate and untested contributor to this figure.
