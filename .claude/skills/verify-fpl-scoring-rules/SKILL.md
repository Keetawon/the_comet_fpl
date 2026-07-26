---
name: verify-fpl-scoring-rules
description: Verify, add, or review season-versioned Fantasy Premier League scoring configuration and replay coverage. Use for config/scoring_*.yaml changes, FPL bootstrap scoring payloads, verify_rules work, PointsBreakdown or calculate_points changes, new seasons, rule mismatches, or claims that scoring values are confirmed.
---

# Verify FPL Scoring Rules

Keep every scoring constant versioned, traceable, and exercised independently from model code.

## Read first

- `AGENTS.md`
- `README.md`, especially R1 and R2
- The target `config/scoring_<ruleset>.yaml`
- `src/fpl/config.py`
- `src/fpl/models/scoring.py`
- `src/fpl/jobs/verify_rules.py`
- `tests/test_config.py` and `tests/test_scoring.py`
- `tests/fixtures/README.md` when using a vendored payload

## Verification workflow

1. Identify the season, ruleset ID, payload source, capture time, and SHA-256.
2. Reject synthetic or placeholder payloads as confirmation evidence. They may validate shape
   only.
3. Run verification without `--write` first:

```powershell
.\.venv\Scripts\python.exe -m fpl.jobs.verify_rules --ruleset <ruleset> --payload <payload>
```

4. Classify every checked field as:
   - confirmed by the payload;
   - unconfirmed because the payload has no interpretable field;
   - mismatch requiring a human-reviewed rules decision;
   - replay-exercised by historical rows.
5. Never resolve a mismatch by silently copying upstream values. Update configuration only
   after reviewing the rule meaning, then use `--write` when the requested task authorizes it.
6. Keep constants out of Python. Adding a season must add a configuration file and target
   column through the existing configuration-driven path.
7. Preserve component NULLs when the archive did not measure a rule input. Do not turn
   unmeasured data into a valid-looking zero-point target.
8. Add named edge-case tests for every changed branch and replay the widest available season
   coverage.

## Validate

```powershell
.\.venv\Scripts\pytest.exe tests\test_config.py tests\test_scoring.py -q
.\.venv\Scripts\ruff.exe check src tests
.\.venv\Scripts\mypy.exe src
```

## Handoff

Report confirmed, unconfirmed, mismatched, and replay-unexercised fields separately. Include
payload provenance and never call a ruleset verified while any release-critical field remains
synthetic or unresolved.
