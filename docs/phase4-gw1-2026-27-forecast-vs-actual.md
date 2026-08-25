# 2026/27 GW1: prospective forecast versus recorded outcome

Status: **development measurement only**. It re-runs no frozen evaluation, judges no promotion
gate, and is not grounds to change any component default. Record:
`results/gw1_2026_27_forecast_vs_actual_development.json`.

Produced at HEAD `7a3f5da94e02d508dc757c1cea193bd9974c2fa0` on a clean worktree.

**Superseded for the accuracy numbers, not for the verdict (2026-08-25).** Every figure below
describes the composer as it stood at that commit. The appearance layer has since gained a
price-informed prior for cold starts and a club-relative cap, which move these same 359 rows to
MAE 1.7236, mean log score 1.7451 and CRPS 1.1536. The comparison that this document exists to
make -- fourteen component architectures scored against each other -- is unaffected, because all
fourteen were produced by the same code on the same day. Do not quote the accuracy numbers here as
current; see `docs/phase4-newcomer-priors-and-style-audit.md` section 6 for the later ones.

## What was measured

Every component-mode combination the prospective job exposes was forecast at the real GW1
deadline (`as_of = 2026-08-21T17:30:00Z`) and scored against the recorded GW1 outcome on
identical rows:

- `--attacking` v3 / v1
- `--assists` coupled / v1
- `--appearance` seasonal / model
- `--share-signal` auto / xg / threat

That is 24 artifacts and **14 distinct models**: `auto` resolves to `expected_goals` on this
data, so `auto` and `xg` are byte-identical everywhere, and with `attacking=v1, assists=v1` the
share signal is inert entirely. With `attacking=v1, assists=coupled` the manifest reports
`share_signal_kind: not_applicable` while `threat` still changes the result, because the coupled
assist path consumes the signal. The label is misleading there; the behaviour is real.

Point-in-time safety holds: every run records `bootstrap_known_at = 2026-08-21T06:41:56Z`, before
the deadline. The post-deadline 08-22 and 08-23 captures are present in the database and are
excluded by the `as_of` filter, which is what makes this a genuine deadline vintage rather than a
hindsight fit.

## Coverage limit, stated first

**Only 6 of the 10 GW1 fixtures are measurable.** The last committed snapshot was captured at
`2026-08-23T06:37:15Z`, before fixtures 7-10 kicked off. No later snapshot is committed and the
live API is unreachable from the build environment, so the missing four cannot be recovered here.

The 6 covered fixtures are `finished_provisional` with bonus applied, but none carries
`finished = TRUE`. The repository's outcome-attachment contract would therefore still reject
them, and **nothing here was written to the prediction ledger**.

Population: **359 player-gameweek rows** across the 12 clubs that played, including every rostered
player who did not appear (actual 0). Identical rows for all 14 models; zero unmatched codes.

## The ruleset replays live football exactly

`config/scoring_2026_27.yaml` reproduces the recorded FPL points of **all 364 covered player-fixture
rows** from their components: recorded total 599, replayed total 599, **zero mismatches**. This is
the first confirmation of the 2026/27 ruleset against real matches rather than against the payload
and captured rule sources. It does not clear the two edge cases still under
`verification.unverified`.

## Result: no model is distinguishable from any other

| # | attack | assists | appearance | signal | EV | EV/act | MAE | log | CRPS | PIT80 | rho |
|---|--------|---------|------------|--------|------|--------|------|-------|-------|-------|------|
| 1 | v3 | coupled | model | threat | 549.0 | 0.916 | 1.74 | 1.645 | 1.176 | 0.747 | 0.416 |
| 2 | v3 | coupled | model | auto/xg | 547.4 | 0.914 | 1.74 | 1.655 | 1.180 | 0.755 | 0.417 |
| 3 | v1 | coupled | model | threat | 509.4 | 0.850 | 1.68 | 1.701 | 1.171 | 0.733 | 0.419 |
| 7 | v3 | coupled | seasonal | threat | 578.7 | 0.966 | 1.77 | 1.773 | 1.176 | 0.747 | 0.402 |
| 8 | **v3** | **coupled** | **seasonal** | **auto/xg** | **577.2** | **0.964** | **1.77** | **1.777** | **1.180** | **0.747** | **0.404** |
| 14 | v1 | v1 | seasonal | auto/all | 518.9 | 0.866 | 1.69 | 1.902 | 1.175 | 0.724 | 0.411 |

Row 8 is the shipped production default; the full 14-row table is in the JSON record.

Paired tests on the 359 common rows:

| comparison | mean diff | se | t | verdict |
|------------|-----------|-----|---|---------|
| log, seasonal - model | +0.1212 | 0.0927 | +1.31 | not significant |
| CRPS, seasonal - model | -0.0000 | 0.0148 | -0.00 | no difference at all |
| log, default - V1/V1 diagnostic | -0.1253 | 0.0828 | -1.51 | not significant |
| CRPS, default - V1/V1 diagnostic | +0.0046 | 0.0099 | +0.47 | not significant |

The actual total itself carries a standard error of **53.4 points on 599** (8.9%), so the default's
EV/actual of 0.964 has a band of [0.885, 1.058] — it contains 1.0, and it overlaps every other
model. CRPS spans 1.170 to 1.186 across all fourteen, a 1.4% spread.

**One gameweek cannot rank these architectures, and this one does not.**

### The ranking metrics are worse than uninformative here

Top-20 lift over the field ranges from -10% to +83% across the fourteen. For the default it is
+52.8%, with a bootstrap 95% CI of **[-15.6%, +120.7%]** — 136 percentage points wide, because it
is computed from 20 players. Ordering models by it produces a ranking that contradicts the log
score ordering completely. Do not use it to choose a model; it is reported only to show its own
width.

The underlying signal is nonetheless real and worth stating separately: the default's predicted
top-20 averaged **2.55** actual points against a field average of **1.67**, and within-gameweek
rank correlation is 0.40-0.42 for every model. Exact top-20 overlap was 1 of 20, because the
actual top of a single gameweek is dominated by unforecastable high-BPS defensive returns
(Mendy 15, Ajayi 14, Sangaré 14).

## What is informative

### Stage A's documented level bias reproduced live

| measure | predicted | actual | ratio |
|---------|-----------|--------|-------|
| goals per fixture | 2.785 | 2.333 | 1.194 |
| clean sheets (12 team-slots) | 3.16 | 5 | 0.632 |

Goals over-predicted by 19%, clean sheets under-predicted by 37% — the same one-for-one trade
recorded in `docs/phase4-stage-a-recency-audit.md`, now visible on live data. It propagates
straight into the positional split of the default: FWD 1.213, MID 0.977, GK 0.976, **DEF 0.887**.
Note this is the *opposite* sign to the historical positional bias (forwards low, defenders high),
which is itself a reason to distrust six fixtures. Six fixtures decide nothing and no tuning
follows from this.

### Every model is under-dispersed at the season boundary

PIT-80 coverage runs **0.724 to 0.763** against a nominal 0.80, for all fourteen models. The
minutes-shrinkage repair measured 0.79985 on 2025-26 GW29-38 and 0.79878 on GW10-28, so the
boundary regime is materially narrower than mid-season. The quintile calibration of the default
shows where:

| quintile (by predicted EV) | n | predicted | actual | ratio |
|---|---|---|---|---|
| 1 (highest) | 71 | 3.56 | 2.92 | 1.221 |
| 2 | 72 | 2.16 | 1.97 | 1.093 |
| 3 | 72 | 1.40 | 1.97 | 0.709 |
| 4 | 72 | 0.84 | 0.82 | 1.020 |
| 5 (lowest) | 72 | 0.12 | 0.68 | **0.171** |

The bottom quintile is the live appearance-underprediction already recorded in
`docs/phase4-season-boundary-appearance-underprediction.md`: 72 players given essentially no chance
of scoring returned 0.68 points each. The composer's appearance layer predicted 177.2 scoring
players against 186 actual appearances under `seasonal`, and only 162.5 under `model`.

### The aggregate-calibration ordering and the log-score ordering disagree

`appearance=model` wins mean log score (1.645-1.721) while `seasonal` wins aggregate calibration
(0.964 against 0.914). These are consistent: 173 of the 359 players did not appear, so a model
that concentrates more mass on zero collects log score on half the population while being further
from the realised total. This is the resolution-versus-reliability trade already recorded for the
assists V1/V2 comparison, and it is why the aggregate ratio must be read beside the score rather
than under it. The shipped `seasonal` default is the best-calibrated of the fourteen; on this
sample that is consistent with, not proof of, the choice.

## What this does not support

- No component default changes. `attacking=v3`, `assists=coupled`, `appearance=seasonal`,
  `share-signal=auto` stand.
- No Stage A, B or C candidate is re-judged, retuned, or promoted.
- Nothing is written to the prediction ledger, because no covered fixture is finalised.
- The four missing fixtures must be measured before any GW1 conclusion is treated as complete.

## Reproducing

```bash
python -m fpl.jobs.build_db
python -m fpl.jobs.load_snapshots snapshots/daily/*/*/
python -m fpl.jobs.prospective_points_v1 --gw-from 1 --gw-to 1 \
  --attacking v3 --assists coupled --appearance seasonal --share-signal auto \
  --output <artifact>.jsonl
```

Outcomes are read from the checksum-verified committed snapshot
`snapshots/daily/2026-08-23/2026-08-23T063715Z` and replayed through
`fpl.models.scoring.decompose_points` under `scoring_2026_27`.
