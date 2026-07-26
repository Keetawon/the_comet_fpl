# Vendored API payloads

Used by `daily_snapshot --dry-run` and by every client test, so that **no test requires
network access**.

| File | Contents |
|---|---|
| `bootstrap_static_sample.json` | `bootstrap-static` response |
| `fixtures_sample.json` | `fixtures` response |

## Status: `bootstrap_static_sample.json` is a SYNTHETIC PLACEHOLDER

It carries a `_PLACEHOLDER` key saying so, and `verify_rules` refuses to mark any field
confirmed while that key is present.

What is faithful in it:

- the response **structure**, so the pydantic models are exercised properly;
- the **2026/27 gameweek calendar** — 38 events with GW1's deadline at the specified
  `2026-08-21T17:30:00Z`;
- **teams and elements** are real 2025-26 archive rows (a 56-player cross-section covering
  every `element_type`), so field types, nullability and the `code` values are real;
- the deliberate **season skew**: `fixtures_sample.json` holds the real, completed 2025-26
  fixtures, mirroring the actual API state on 2026-07-26 where `/api/fixtures/` still
  returned last season while `bootstrap-static` had rolled over. `--dry-run` therefore
  exercises the skew detection for real rather than against a contrived case.

What is **not** verified:

- `game_config.scoring` is transcribed from the specification, not captured. Its key
  layout is a best guess at the real payload's shape. **No scoring value in
  `config/scoring_2026_27.yaml` may be treated as confirmed until a real capture has been
  verified.**

## Replacing it with a real capture

```bash
curl -s https://fantasy.premierleague.com/api/bootstrap-static/ \
  > tests/fixtures/bootstrap_static_sample.json
curl -s https://fantasy.premierleague.com/api/fixtures/ \
  > tests/fixtures/fixtures_sample.json

# Verify the 2026/27 rules against the real game_config.scoring and rewrite the
# `verification` block with whatever the payload actually confirms.
uv run python -m fpl.jobs.verify_rules --ruleset 2026_27 \
  --payload tests/fixtures/bootstrap_static_sample.json --write
```

`verify_rules` reports three outcomes per field, and only the first marks a field
confirmed:

- **confirmed** — the payload carries the field and the value agrees;
- **unconfirmed** — the payload has no key matching it, under any known layout;
- **MISMATCH** — the payload carries the field and disagrees. This exits non-zero and
  never rewrites the config: a rule change upstream needs a human decision, not an
  automatic overwrite.

`goals_scored.GK` stays in `unverified` regardless of what any payload says. A payload
confirms the number FPL publishes; it cannot confirm the calculator handles it, and no
goalkeeper scored in the validation data — 0 GK goals across 29,747 rows of 2025-26 — so
no replay can exercise that branch.

Payloads are committed rather than downloaded on demand because a test that needs the
network is a test that fails in CI for reasons unrelated to the code.
