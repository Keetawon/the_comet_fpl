---
name: guard-fpl-point-in-time
description: Review or implement FPL features, datasets, schedules, and walk-forward backtests without temporal, target, identity, or knowledge-time leakage. Use for changes under src/fpl/features, feature-readable marts, AsOf/FeatureSource APIs, historical schedule handling, training-set construction, or any review asking whether information was available at prediction time.
---

# Guard FPL Point-in-Time

Prevent the model from using information that was unavailable at the prediction cutoff.

## Inspect the contract

Read these repository files before acting:

- `AGENTS.md`
- `README.md`, especially R1 and R4
- `src/fpl/features/pit.py`
- `src/fpl/storage/db.py`
- `tests/test_point_in_time.py`
- Relevant schema, transform, feature, and test files

## Classify leakage

Check all four classes independently:

1. **Target leakage:** Features must not read `mart_target_*`, recorded `total_points`, or
   target-derived columns.
2. **Event-time leakage:** Observed match outcomes must satisfy `kickoff_time < as_of`.
3. **Knowledge-time leakage:** Schedule changes, availability, prices, forecasts, and API fields
   must be versioned by `known_at`/`captured_at` and selected as known at `as_of`. Kickoff time
   alone is not sufficient.
4. **Identity leakage:** Never interpret a bare team ID across seasons. Require a
   season-qualified key or verified stable identity.

## Review or implementation workflow

1. Trace data from source to the returned feature and name the timestamp that governs each
   field's availability.
2. Keep feature code behind `FeatureSource` and `PointInTimeView`. Do not import DuckDB, issue
   caller SQL, accept a raw connection, or expose the private connection.
3. Restrict future schedule projections to fields known before kickoff.
4. Treat empty filter lists deliberately; return an empty typed result or an explicit false
   predicate rather than generating `IN ()`.
5. Add tests for the exact failure mode:
   - target-table denial;
   - full-database versus physically truncated equivalence;
   - schedule projection safety;
   - timezone-aware cutoff enforcement;
   - season-qualified team filtering;
   - version selection by knowledge time when versioned data is involved.
6. Run:

```powershell
.\.venv\Scripts\pytest.exe tests\test_point_in_time.py -q
.\.venv\Scripts\ruff.exe check src tests
.\.venv\Scripts\mypy.exe src
```

## Handoff

State the prediction cutoff, data availability rule, identity grain, tests run, and any field
whose historical knowledge time remains unproven. Distinguish a confirmed leak from a design
gap or defense-in-depth improvement.
