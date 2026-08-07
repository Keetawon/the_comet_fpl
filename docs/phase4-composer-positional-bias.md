# The composer's positional bias: three refuted explanations and one confirmed defect

Read-only investigation. No contract loaded, no gate metric scored, nothing promoted, nothing
written to `results/`. `trailing_goals_attack_defence` and every Stage C candidate are untouched.

## The finding this started from, and the correction it needs

`docs/phase4-stage-a-recency-audit.md` recorded that the composer's bias is positional rather
than global, and attributed it to the clean sheet: "GK and DEF are the clean-sheet positions and
the clean sheet is the component over-predicting by +5.7%, so this is one finding."

**That attribution is wrong and is retracted here.** It was measured on one window. On the other,
the clean sheet runs **−0.4%** while GK and DEF are still over by +3.5% and +3.7%. The clean
sheet cannot be the cause of a bias that persists when the clean sheet is accurate.

The positional bias itself is real and stable. Measured on both windows against actual points
with the unmodelled negative components added back (they fall unevenly by position, so the raw
comparison is not like for like):

| position | GW10-28 (191 fx) | GW29-38 (99 fx) |
|---|---:|---:|
| GK | +5.9% | +3.5% |
| DEF | +5.3% | +3.7% |
| MID | +2.4% | +4.0% |
| FWD | **−3.1%** | **−4.1%** |

Forwards run 3-4% low in both windows while every other position runs high. The spread between
forwards and the rest is 6-9 percentage points, in the same direction, on two disjoint windows.

## Three explanations, tested and rejected

### 1. Binomial thinning inflates the bin-2 clean sheet — real, but ~15 points

Archive semantics verified exact first: over 2025-26 GK/DEF rows `clean_sheets = 1` coincides
with `minutes >= 60 AND goals_conceded = 0` for all 1,015 rows, zero mismatches either way.

The right test is conditional on the team's actual full-match conceded count, because comparing
raw `P(clean sheet)` across minutes bins compares different populations -- bin-2 players' teams
concede more (1.49 full-match equivalent against 1.336 for bin 3), which the composer already
handles through each fixture's own rate.

Conditional on the team conceding exactly one goal (n = 746, the dominant non-zero cell), a
60-89 minute player keeps the clean sheet **0.1408** of the time; binomial thinning at exposure
0.813 predicts **0.1870**. So thinning does over-predict, by about a third, in that cell. The
mechanism is selection in the substitution: a defender withdrawn between 60 and 89 minutes is
disproportionately one whose side had *already* conceded, so the goal falls inside his window
more often than independent timing implies.

But the size is small. At a typical `lambda_conceded` of 1.4 the thinned clean-sheet probability
is 0.320 against a correctly weighted 0.307 -- about 4% relative, on the 14% of GK/DEF rows that
land in bin 2, worth roughly 15 of the 139 excess clean-sheet points. **Real, recorded, not the
explanation.**

### 2. Stage A's Poisson has too many zeros — refuted out of sample

Pooled over 3,600 team-match predictions the Poisson zero looked clearly too high: predicted
`P(0)` 0.2659 against a realised 0.2475, **+7.4%**, and worst in the low-rate bands (+17.8% at
`lambda ≈ 1.1`) which is exactly where a manager picks a defender for a clean sheet.

Split by season it collapses:

| season | Poisson `P(0)` | actual | ratio |
|---|---:|---:|---:|
| 2021-22 | 0.2826 | 0.2768 | 1.021 |
| 2022-23 | 0.2703 | 0.2724 | 0.993 |
| 2023-24 | 0.2669 | 0.2066 | **1.292** |
| 2024-25 | 0.2538 | 0.2342 | 1.084 |
| 2025-26 | 0.2603 | 0.2553 | 1.020 |

**The whole effect is 2023-24**, the archive's outlier scoring season at 3.147 goals per fixture,
where Stage A's pooled anchor under-predicted goals and therefore over-predicted zeros. That is
the level miss already documented, showing up as an apparent shape defect. Train
(2021-22..2024-25) gives z = **+2.72**; the 2025-26 holdout gives z = **+0.32**.

**Not confirmable out of sample. No zero correction should ship.** This is the second time in
this investigation that a pooled figure has been an artifact of one season, after the xG-coverage
pattern already recorded in `AGENTS.md`.

### 3. P(60+) is over-predicted — real, but +1.9%

On GW10-28 with the shrunk minutes estimator, predicted `P(60+)` averages 0.268 against a
realised 0.263, and `P(90)` 0.188 against 0.184. By position, `P(play)` error is GK +0.002,
DEF +0.010, MID +0.019, FWD −0.003. The minutes layer is close to calibrated and cannot produce
a 6-9 point positional spread.

## The confirmed defect: goals and assists are allocated to the wrong positions

Expected **counts** by position against realised counts -- counts rather than points, so the
position-specific point values cannot hide the allocation.

### Goals

| position | GW10-28 model | actual | error | GW29-38 model | actual | error |
|---|---:|---:|---:|---:|---:|---:|
| GK | 1.6 | **0** | — | 1.0 | **0** | — |
| DEF | 93.8 | 73 | **+29%** | 53.0 | 33 | **+61%** |
| MID | 289.1 | 280 | +3% | 134.9 | 126 | +7% |
| FWD | 163.5 | 165 | −1% | 93.1 | 96 | −3% |
| total | 548.0 | 518 | +6% | 282.0 | 255 | +11% |

### Assists

| position | GW10-28 model | actual | error | GW29-38 model | actual | error |
|---|---:|---:|---:|---:|---:|---:|
| GK | 2.2 | 2 | +10% | 1.4 | 2 | −30% |
| DEF | 135.5 | 121 | **+12%** | 70.3 | 55 | **+28%** |
| MID | 323.1 | 306 | +6% | 162.2 | 144 | +13% |
| FWD | 33.2 | 54 | **−38%** | 21.2 | 35 | **−40%** |
| total | 494.1 | 483 | +2% | 255.0 | 236 | +8% |

Three things here, in order of size.

**Forwards are allocated 38-40% too few assists, in both windows.** The model gives forwards 7-8%
of all assists; reality gives them 11-15%. This is the single most stable and largest positional
error in the composer, and it is most of why forwards are under-valued.

**Defenders are allocated 29-61% too many goals and 12-28% too many assists.** A defender's goal
scores 6 points against a forward's 4, so mis-allocating goals toward defenders inflates the
total *and* mis-ranks positions at the same time. This connects to an already-measured constant:
`AGENTS.md` records that the defender attacking signal is **xA, not xG** (persistence 0.784
against 0.319), so a trailing xG share is close to noise for defenders -- and a defender who
converted one set-piece chance keeps an inflated share of his club's goals afterwards.

**Goalkeepers are allocated 1.0-1.6 goals against an actual zero.** Tiny in points, but it is a
pure specification leak: the allocation has no notion that goalkeepers do not score, so any
non-zero trailing share -- or the cold-start equal-share fallback -- hands them attacking mass.

Note the totals are over-predicted in both windows (+6%/+11% goals, +2%/+8% assists) and this is
the separate, already-documented Stage A level miss. The allocation defect is what remains after
that: forwards are under-allocated *even though the total is too high*, which is only possible if
the shares are wrong.

## What this licenses

A named, separately designed change to how the composer allocates team attacking output across
positions. It is prospective-track work -- the composer's consumption of Stage C is not under a
historical gate -- but it is a real modelling change and needs its own design rather than a tweak,
with at minimum:

- a position-aware share estimator that uses **xA for defenders**, per the measured persistence
- a structural zero for goalkeeper goals
- validation on both windows, since this investigation was misled twice by a single window

It does **not** license re-running, re-tuning, or re-judging any Stage C candidate. V3 remains the
committed minutes-gated allocation and its development result stands as recorded.
