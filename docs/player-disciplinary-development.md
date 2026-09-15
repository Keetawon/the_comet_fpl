# Disciplinary V1: one retained retrospective development run

**INCONCLUSIVE; not eligible for development synthesis; no promotion.**
`retrospective_exposure_pooled_disciplinary_v1` was evaluated once from clean
`54d9ffee89e161f6a57f4e35d4b93b4de2893b54`. It improves aggregate joint and yellow
scores, but fails the preregistered red log-loss and red Brier non-regression guards.
The joint candidate is retained intact: no yellow-only selection, red-rate retune or rerun.

## What was compared

The exact current composer supplies no card component. Its zero-risk card forecast is the
incumbent, but beating that degenerate forecast cannot establish useful personal tendencies.
The scientifically informative additional control uses only fold-local position/exposure
hazards. Candidate and control share identical four-bin minutes PMFs from
`retrospective_current_minutes_proxy_v1`, source exposure and categorical scored-card support.
The candidate adds strongly pooled player/position tendencies, not role, tactics or workload.

All 86,755 player-fixture rows and 114 gameweeks in 2023-24 through 2025-26 are retained,
including the **821 price-proxy-dependent cold rows**. This is a retrospective proxy
implementation of current selector mathematics, not exact historical deadline reproduction.
The remaining 85,934 rows do not consult the cold-price proxy. No target-match observed
minutes, role, cards or lineup enters a predictor. Historical training excludes the entire
target GW and requires kickoff plus six hours strictly before the cutoff.

## Proper scores

Lower is better. Relative improvements below compare the candidate with the informative control.

| Metric | Zero-card incumbent | Position/exposure control | Candidate | Relative improvement |
|---|---:|---:|---:|---:|
| Joint NLL | 1.502340229 | 0.185183364 | 0.183069516 | +1.1415% |
| Yellow log loss | 1.453292022 | 0.173583979 | 0.171472630 | +1.2163% |
| Yellow Brier | 0.052596392 | 0.046917416 | 0.046532093 | +0.8213% |
| Red log loss | 0.049048208 | 0.011812452 | 0.011827158 | -0.1245% |
| Red Brier | 0.001775114 | 0.001768091 | 0.001768281 | -0.0107% |

Joint NLL improves in every season:

| Season | Rows | Control | Candidate |
|---|---:|---:|---:|
| 2023-24 | 29,725 | 0.188044000 | 0.185984947 |
| 2024-25 | 27,283 | 0.198379431 | 0.195915892 |
| 2025-26 | 29,747 | 0.170221833 | 0.168373955 |

The paired candidate-minus-control joint loss is -0.002113849, GW-clustered SE 0.000182921,
normal 95% interval [-0.002472374, -0.001755323] across 114 season-qualified clusters.
This interval is not additionally adjusted for serial dependence between gameweeks.
Yellow mean probability is 0.048590 vs observed 0.052596; red 0.001487 vs 0.001775.
Both absolute calibration-bias guards pass. Red average precision slightly worsens from
0.005280 to 0.005025; it is diagnostic, never a substitute for a proper score.

## Proxy sensitivity and limitations

Excluding the 821 proxy-dependent rows **diagnostically** leaves joint lift +1.1501%,
so the gain is not created by those rows. On the proxy rows alone, joint NLL is actually
slightly worse: control 0.141524460 vs candidate 0.141576331. Their cold-start status and
complete price lineage remain in each fold artifact. The nominated population is unchanged.
Position, venue, early/later, observed exposure and all cold/established slices are retained.

This predicts FPL-encoded none/yellow/red scoring outcomes, not physically exclusive card
events. The original source audit's ten zero-minute card rows remain labels; on-pitch-only
prediction intentionally cannot model bench bookings. No rare state is erased to improve
scores. A probability floor applies to scoring, never to the retained PMF. Role/tactical/
workload effects were not fitted and cannot be attributed from this result.

The optional composer field remains absent in all defaults. It adds card points using only
loaded rules and an independent seeded stream when explicitly supplied, preserving every
legacy component/bonus draw. The failed candidate is **not** enabled in synthesis, production,
optimizer or dashboard. Existing BPS residuals and count support remain unchanged.

## Immutable evidence and independent verification

Config SHA256: `698572ded8ca4477482baca215717a88e229add0f319d285080df29b6ce32b6f`.
Database SHA256: `0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8`.
Minutes reference manifest: `5b813d58b71bad97a5c81774aaf70c0bca5f4e0e3bcd518e6f26e0acfea19bac`.
Result `results/player_disciplinary_development.json`, SHA256
`e2348f5ae4dddc623a4c55a5d9d0864cd61d6ba691929ade52b6b49993de3b3b`, is a byte-identical copy.
Full conditional and marginal PMFs, observed outcomes and selector provenance remain in
114 hash-pinned fold files under
`D:/Personal/fpl-operations/verification/disciplinary-development-20260907T094700Z`.
The directory name is an operator identifier. Actual prediction execution began
2026-09-07T09:46:36.005650Z and the last fold completed at 09:47:51.289067Z; summary and
clean postflight checks followed before publication. The exclusive claim is shared through
Git's common directory, so another linked worktree cannot repeat this candidate.

Independent verification performs **5,214,137 checks, zero failures**, maximum floating
difference 1.93e-15. It verifies all 500 code/config/test/evidence fingerprints, original
database, complete target/cache/price lineage, all PMFs, every slice, calibration bucket,
tie-grouped AP, uncertainty and gate. It performs no fitting or rerunning. Retained audit:
`results/player_disciplinary_independent_audit.json`, SHA256
`1eac52fc8e58061355f4dab6e0a2474218b0b90ca3099562546784a1b53f1d49`.
Its external original and read-only script are under
`D:/Personal/fpl-operations/verification/disciplinary-independent-20260907T095000Z`.

Pre-run relevant gate: 359 tests pass; global Ruff and strict mypy pass; 14 changed Python files
pass format. The previously measured Windows symlink failures and 11 inherited formatting
failures remain explicit in `results/football_program_pre_v3_stage_gate.json`; this does
not declare the full repository gate green. Original databases, Phase A and all older
experiments remain untouched. Continue independent authorized workstreams, not this candidate.
