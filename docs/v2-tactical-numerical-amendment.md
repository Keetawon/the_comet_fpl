# Tactical Matchup V1 numerical-method amendment 1

Preregistered on 2026-09-07, before any amended real-data candidate fit. The owner's
"ok go on" authorizes the numerical-only continuation recommended after the retained
Tactical V1 execution failure. This is NOT permission to replay the consumed V1 identity.

Candidate: `retrospective_tactical_matchup_team_environment_v1_numeric1`.
Evidence class: `retrospective_backfill_development`; production promotion prohibited.
Starting local/remote SHA: `464c86fd24fca210cb3c75af367ebd5ab721173d`.
Remote fetch confirmed no main-only commits, so no additional merge is needed.

## Immutable parent and precise scope

The complete statistical contract is inherited without overrides from
[`v2_tactical_matchup_evaluation.yaml`](../config/v2_tactical_matchup_evaluation.yaml),
SHA256 `a640ff31f6d1701df12ee9ba3267636ea2856a49cd1496ef68d658b60317c781`.
The new config pins that hash, the parent evaluation SHA
`672a36d9d6fc446bb7492eb89eebd63f15bee860`, and the retained execution-failure artifact
SHA256 `726e513660045f0e34cce9909d7e8e4ac9c0a3999d8a23630866550159bdd8ed`.
The parent claim, failure record, original solver and previous evaluations remain intact.

The sole change is how the SAME penalized Poisson offset objective is solved numerically.
The old solver remains the default of the old research interface. The amendment explicitly
injects the separately named fitter into primary and both fixed diagnostic goal layers.
No production or strict PointInTimeView call receives this fitter or retrospective data.

Unchanged:

- Five dimensions: SOT/shots precision, log1p box touches, possession share, forward-pass
  share, and negative log1p opponent shots; the same six raw fields and semantic caveats.
- Last-five current-season slots, weights `1,.707,.5,.354,.25`, measured-only normalization,
  `n/(n+2)` shrinkage to strictly prior league evidence; raw NULL is not zero/average filled.
- One pooled venue indicator; fixed ridge-delta style penalty 1; minimum 160 fitting rows.
- Strictly sequential OOS style predictions feeding goal fits; target-GW batch isolation,
  actual-event eligibility for postponed/DGW legs, fold-local scaling and original known_at.
- Own/opponent five-dimensional predictions plus precisely three original interactions.
- Exact incumbent `trailing_goals_attack_defence` latent rate as log offset; original
  Poisson support 0..10, floor .05, +/- .5 correction clip and reciprocal PMF-zero CS.
- Ordered penalty choices disabled, 10, 1, .1; cached weekly prequential inner scores on
  six prior observed GWs after ten earlier GWs; global-minimum tie tolerance 1e-12.
- Recent-only/no-interaction and predicted-only/no-interaction diagnostics reuse the
  primary selected penalty; neither is independently selected or eligible for promotion.
- Coverage-selected 2023-24/2025-26, all 760 fixtures/1,520 sides/76 outer folds. Coverage
  is not recalculated into a different population; audit must reproduce the frozen report.
- Seed 20260904, original metrics/slices and BOTH 1% materiality requirements (goal NLL
  and CS Brier), zero CRPS/full-season regressions, PIT-80 error <= .05, zero leakage.

No new feature, season, model family, parameter grid, calibration rule, target or gate.
No target performance has been inspected to design this amendment. The failed real matrix
was not retained, and is not replayed. A synthetic failure mode can support a numerical
repair but cannot establish the precise cause of the original 2024-25 GW10 exception.

## Frozen numerical policy

Use existing Python binary64 arithmetic and linear algebra; no new dependency. Minimize

`L(beta) = mean(exp(log_offset + X beta) - goals*(log_offset + X beta))
           + penalty * ||beta||^2 / 2`.

The intercept is penalized exactly as before. Zero initialization, training-only scaler,
exact Newton gradient/Hessian and Cholesky solve are retained. Maximum 40 Newton updates,
30 backtracking trials per update, halving fractions, Armijo constant 1e-4, and all fitted
log-rates within [-20,20] remain bounded. There is no nonconvergence-to-incumbent fallback.

For the actual representable coefficient increment `delta = proposed_beta - beta`, compute
the algebraically identical objective difference without subtracting two full objectives:

`delta_L = gradient dot delta
         + mean(rate * (expm1(X delta) - X delta))
         + penalty * ||delta||^2 / 2`.

For `|X delta| <= 1e-3`, evaluate the exponential remainder using its fixed degree-six
Taylor polynomial (omitted absolute term < 2e-25). Otherwise use `expm1(t)-t`.
Accept only a nonzero representable step with negative Armijo bound and
`delta_L <= 1e-4 * gradient dot delta`. No positive objective slack is allowed.

Convergence requires BOTH:

1. Final gradient infinity norm <= `1e-9 + roundoff_allowance`, where allowance is
   `64 * binary64_epsilon * max_j(mean(|X_j|*(rate+goal)) + penalty*|beta_j|)`.
2. UNDAMPED Newton-step infinity norm <= `1e-9 * (1 + ||beta||_infinity)`.

A small accepted step by itself never proves convergence. Recompute derivatives at the
final coefficients, including after the last permitted update. Retain objective, gradient,
undamped step, Newton decrement, coefficient/scaler identity, tolerances and accepted
fractions in every successful fit. Failure retains the same state and all attempted trials.
Finite-precision coefficients need not be bit-identical to the old solver; the objective
and scientific procedure are identical, not necessarily its former termination point.

## Guards, diagnostics and one authorized attempt

The new runner rejects a dirty worktree, wrong branch/database/config/audit/reference hash,
existing amendment result/claim/checkpoint directory, or a database WAL. It reads the frozen
research database only. It reproduces the incumbent against retained PMFs AND the actual
prospective helper before reserving the new exclusive claim (1e-12, identities and counts
exact). Clean provenance is checked again before fitting and before successful publication.

The claim stores full Git/config/source/database provenance. Every completed historical GW
is durably checkpointed with identity, PMFs, state predictions and fit diagnostics, marked
incomplete until the entire run validates. Checkpoints cannot be consumed as a resume cache
or scored selectively. Each goal-layer fit logs GW/cutoff/layer/penalty/row count/input hash BEFORE
fitting, and preserves that context on exception. Checkpoint consumers receive isolated
copies, never mutable fitting state.

After a claimed failure, publish a write-once incomplete failure record with exception
traceback/notes/numerical state, claim and checkpoint evidence; no fabricated aggregate
metrics or partial performance verdict. No automatic retry, rerun, new penalty or tuning.
Successful output retains every outer PMF and historical OOS style prediction, all fit
diagnostics and the unchanged gate. Read-only interpretation follows, never post-result
feature selection. Clean design/config/implementation/tests must be committed first.

New invocation, ONCE after the clean preregistration commit:

```powershell
& 'D:\Personal\fpl-operations\.venv\Scripts\python.exe' -u -m fpl.validate.dev_v2_tactical_numeric --db 'D:\Personal\workspace\the_comet_fpl\.worktrees\sdp_test\data\fpl.duckdb'
```

The old `dev_v2_tactical_matchup` invocation remains consumed. A completed amendment still
uses only SUPPORTED / INCONCLUSIVE / REFUTED, always development-only, never PROMOTED.
