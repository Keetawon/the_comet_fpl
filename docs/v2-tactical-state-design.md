# Tactical state V1: preregistration

Owner-authorized 2026-09-07. No candidate goal performance has been inspected. This is a new
structural experiment, not an amendment/reinterpretation of the frozen SOT ladder.
Candidate: `retrospective_tactical_matchup_team_environment_v1`. Development only.

## Coverage and metric licence

Read the [coverage-only audit](v2-tactical-metric-audit.md) and its hash-pinned JSON.
Before model scoring, require >=95% of completed historical team sides to have all five
dimensions on BOTH fixture sides, plus a full earlier PL season for training. The audit
selects **2023-24 and 2025-26**, 760 sides each, 76 observed-GW folds, 1,520 predictions.
2021-22 and 2022-23 paired coverage is 94.2105%; 2024-25 is 94.7368%; 2026-27 is incomplete.
The omission-driven exclusion is conservative and potentially unrepresentative; report it.
Every target goal side in each selected season is scored, including sides missing tactical
target measurements. Earlier/ineligible seasons can supply genuinely prior measured training
observations. Selection never uses goal-model performance or discards difficult target rows.

| Dimension (higher means) | Exact measurement | Confidence / limitation |
|---|---|---|
| Attack precision (greater on-target share) | `ontargetScoringAtt / totalScoringAtt` | SOT independently corroborated; denominator provider-labelled total attempts. NOT Opta UI shooting accuracy, finishing talent or xG. |
| Dangerous territory (more box touches) | `log1p(touchesInOppBox)` | Provider-labelled box-touch volume, not a count of entries. |
| Control (more possession) | `possessionPercentage / 100` | Provider-labelled possession share, not proven tactical intent. |
| Directness (more forward passing) | `fwdPass / totalPass` | Directional pass propensity, not attack speed or sequence length. |
| Defensive suppression (fewer attempts faced) | `-log1p(opponent totalScoringAtt)` | Exact reciprocal opponent side, not intrinsic defensive quality. |

This additive **validation-only** licence does not set global `verified_semantics` flags,
broaden the frozen SOT reader, or expose a retrospective option in production PIT. SDP xG/xGOT,
big chances, entries, pressing, blocks, duels and all other fields are excluded from V1 fitting.
No raw NULL is converted to zero or to a team average; zero denominator yields NULL. No
corroborated omitted-zero interpretation is added in this candidate.

## State and time

Select the earliest successful complete whole stats payload by `(fetched_at, payload_id)`
before looking at any metric. Retain provider, match ID, capture ID, SHA and original known_at.
Source event time must precede the prediction cutoff. September-2026 capture may postdate a
historical cutoff ONLY under `retrospective_backfill_development`, never deadline evidence.

For each club's actual last FIVE PL matches **in the current season**, newest to oldest,
use fixed weights `1,.707,.5,.354,.25`. An unmeasured match consumes its chronological slot;
normalize only over measured values inside those five slots, never reach farther back.
Per dimension, pool recent EWMA toward the expanding strictly-prior league measured mean:
`alpha=n/(n+2)`, `state=alpha*recent+(1-alpha)*prior`. No current-season recent history gives
the labelled league-prior state estimate; raw recent remains NULL, count zero. No league
measurement at all gives NULL and a downstream incumbent/persistence fallback. These are
explicit estimates, not filled provider observations.

Reset recent state at every season boundary; no offseason team-state carryover or club fixed
effects. The prior can use older league observations. Promoted and returning clubs use the
same rule and permanent `team_code`. League venue is represented by a ridge-penalized home
indicator in the style forecaster, pooled across teams; no team-specific venue effect or
separate last-five-home/away window.

Cutoff is first kickoff of each observed season/GW. Predict its entire fixture batch from one
pre-GW state. Delayed/DGW legs remain together for prediction and enter subsequent training
only after their actual kickoff, never simply when their earlier GW was predicted. Archive
final roster/kickoff remain historical proxies; event causality is not deadline knowledge.
