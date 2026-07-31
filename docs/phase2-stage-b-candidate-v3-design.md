# Stage B Candidate V3 design: concentration-adaptive shrinkage

**Status: frozen pre-registration record. Candidate V3 has now had its single historical
development evaluation (2026-07-30) — development-only, NOT promoted (fails the v1.2
starter-ranking gate); see
[`phase2-stage-b-candidate-v3-development.md`](phase2-stage-b-candidate-v3-development.md).**
Candidate V3 is named `concentration_adaptive_shrinkage_player_minutes_v3` in
`config/phase2_evaluation.yaml` amendment 1.4. The exact estimator and joint three-parameter
selector are implemented in `src/fpl/models/minutes_v3.py` and covered by deterministic offline
tests (`tests/test_minutes_v3.py`, `tests/test_dev_minutes_candidate_v3.py`), with a separately
named development runner in `src/fpl/validate/dev_minutes_candidate_v3.py`. The pre-registered
formula and policy below are frozen and were **not** retuned after the result. The design section
below is the pre-registration written before the run.

Candidate V3 is **development-only**. The archive already shaped the hypothesis (see below), and
the historical target roster and first-kickoff cutoff remain unversioned proxies. A later
historical number can diagnose the model under those proxies; it cannot establish real-deadline
knowledge-time validity or promote a production model.

Amendment 1.4 adds this candidate policy only. The complete version 1.0 population, target-roster
policy, four bins, four baselines and their definitions, metrics, scoring/calibration definitions,
the version 1.2 promotion gate, reporting, seed, and Monte Carlo exclusion remain unchanged. V3 is
judged by the **v1.2 gate** (best-per-metric guardrails + the starter-ranking Spearman-p60 gate)
with no further gate change.

## The diagnosed problem

Candidate V2 (`recency_weighted_trailing_player_minutes_v2`) failed exactly one v1.2 gate: the
starter-ranking gate, `spearman_p60_within_position_gameweek` 0.70071 vs the best baseline
`last_observed_player_minutes` 0.70851 (−1.10%). A by-position decomposition of V2's committed
evidence (`docs/evidence/phase2-stage-b-candidate-v2-2026-07-30.json`, `harness.by_position`)
localises the failure almost entirely to goalkeepers:

| position | V2 Spearman | `last_observed` | V2 − last_obs | n |
|---|---:|---:|---:|---:|
| GK  | 0.8153 | 0.8650 | **−0.0496** | 14,890 |
| DEF | 0.6833 | 0.6818 | +0.0014 | 44,678 |
| MID | 0.6593 | 0.6382 | +0.0211 | 58,386 |
| FWD | 0.6449 | 0.6490 | −0.0041 | 16,010 |

On goalkeepers the ranking degrades monotonically with smoothing:
`last_observed` (1 fixture, no smoothing) 0.8650 > `trailing_5_player` (5 fixtures, no shrinkage)
0.8285 > V2 (5 fixtures + recency + shrinkage) 0.8153 > V1 0.8104. Goalkeeper minutes are
near-deterministic (the number-one keeper plays 90 every match, the backup 0), so shrinking a
concentrated history toward the position prior blurs the sharp starter/backup line. On midfielders
(heavy rotation) the same shrinkage *helps* ranking (+0.0211). One global shrinkage strength,
selected on log score, is therefore wrong for the goalkeeper ranking.

## Hypothesis

Make the shrinkage strength adapt to how concentrated the player's own recency-weighted history
is: shrink little when it is concentrated (a nailed starter or nailed non-player — the goalkeeper
case), shrink fully when it is spread (genuine rotation — the midfielder case). For a keeper who
plays 90 every match, less shrinkage moves the prediction toward the near-certain outcome, which
improves *both* the log score and the ranking on those rows, so the mechanism is coherent rather
than a trade-off. V3 reduces **exactly** to V2 when the adaptation is off, so it is a strict
generalisation and the comparison is honest.

## Exact frozen distribution

Everything is identical to V2 except the shrinkage strength. With the geometric recency weights
`w_k = sum of decay**i over the trailing rows in bin k` (`i = 0` newest), `W = sum_k w_k`, and the
weighted bin shares `s_k = w_k / W`:

```text
H         = sum_k s_k**2                        (Herfindahl; 1/n_bins .. 1)
C         = (H - 1/n_bins) / (1 - 1/n_bins)     (normalised to [0, 1]; C=1 one bin, C=0 uniform)
alpha_eff = max(0, alpha * (1 - lambda * C))
p_k       = (w_k + alpha_eff * q_k) / (W + alpha_eff)
```

- `n_bins = 4`, so `1/n_bins = 0.25` and `C = (H - 0.25) / 0.75`.
- `q` is the same fold-local raw `position_minutes_frequency` distribution V1/V2 use (with its
  all-position fallback).
- If `W = 0` (no prior history) the prediction is exactly `q`, identical to V1/V2; `lambda` is
  irrelevant there.
- At `lambda = 0`, `alpha_eff = alpha` and the prediction is **bit-identical to V2**.

## Frozen selection

`decay`, `alpha`, and `lambda` are selected **jointly** by the SAME six-observed-gameweek nested
walk-forward V1/V2 use (pooled inner mean log score — the inner objective is deliberately NOT the
ranking metric V3 targets, so the candidate cannot be gamed toward the gate). Grids:

```text
decay  in {1.0, 0.9, 0.7, 0.5, 0.3}     (1.0 == V2's no-decay column)
alpha  in {1.0, 2.0, 5.0, 10.0, 20.0}
lambda in {0.0, 0.25, 0.5, 0.75, 1.0}   (0.0 == V2, no adaptation)
```

125 grid points per fold. Deterministic tie-break biased toward the null (V2): on equal inner log
score pick the **smallest lambda** first (closest to V2), then the **largest decay**, then the
**smallest alpha**. When fewer than 14 prior observed gameweeks exist, the frozen fallback is
`(decay=1.0, alpha=5.0, lambda=0.0)` — i.e. V2's/V1's fallback with no adaptation.

Observed gameweeks only; 2022-23 GW7 stays absent. Every prior, transform, and grid score is
fitted strictly within the applicable inner or outer fold. Prediction grain remains
`(season, code, fixture)`; double-gameweek fixtures are never collapsed. Stable `code` is the only
cross-season player identity. NULL is never zero-filled. Availability/status, team, opponent, and
home/away are not V3 features.

## Design risk, recorded honestly

The inner selector optimises pooled mean log score, but the gate V3 targets is Spearman-p60. The
mechanism is coherent (less shrinkage on concentrated histories helps log score *and* ranking on
the same goalkeeper / nailed-starter rows), but the aggregate log-score signal for `lambda` is
weak because concentrated rows already score well, so the inner selection may pick small `lambda`.
That is a genuine, pre-registered risk. It is not to be papered over, and the inner objective is
not switched to a ranking metric to force a gate win.

## Evaluation and the unchanged gate

V3 is judged by the v1.2 gate exactly as V2 was: +1% aggregate mean-log-score lift over the best
log-score baseline; no regression on RPS / Brier-any / Brier-60+ against the **best baseline value
of each metric**; no Spearman-p60 regression against the best baseline (0.70851, group-constant
baselines excluded); PIT-80 |error| <= 0.05; full coverage; >= 181 folds; no per-season log
regression; zero leakage.

### The single authorised run (not executed here)

The one historical development evaluation is the owner's authorised action and is NOT run by this
slice. Command:

```text
python -m fpl.validate.dev_minutes_candidate_v3
```

**Precondition — a pristine historical archive.** The run must execute against a pristine
historical archive, rebuilt via the `build_db` job, on a clean worktree, exactly once. The working
DB may carry live-registry rows, so its whole-file fingerprint no longer matches the V1/V2-era
archive; comparability is confirmed by the four baselines reproducing their frozen V1/V2 values
**bit-for-bit** (same 181 folds, 133,964 eligible predictions, identical baseline log/RPS/Brier/
Spearman), not by a whole-file hash. If any baseline drifts, the run is invalid and must stop.

Like V1 and V2, V3 **cannot be promoted on historical data** — the unversioned roster/cutoff
proxies mean no historical number establishes real-deadline knowledge-time validity. A historical
run only diagnoses whether concentration-adaptive shrinkage recovers the goalkeeper/starter
ranking and clears the v1.2 gate as a development diagnostic. Per the pre-registration, V3 is left
as committed after any run and is not retuned.
