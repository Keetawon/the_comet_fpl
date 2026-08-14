# Decision comparison artifact

Status: implemented, development-only. It transports a decision comparison; it does not certify that
either decision is a validated production recommendation.

DEV-ROADMAP P0.3 requires the GW1 deadline pack to show, side by side, what the frozen default
architecture and the V1/V1 diagnostic comparator each decided and where they disagree.
`src/fpl/artifacts/decision_comparison.py` is that report as a durable artifact, and
`fpl.jobs.compare_decisions` is its thin entry point.

## Input boundary

The comparison reads exactly four already-frozen files and nothing else:

- the default prospective-points JSONL and its optimizer plan JSON;
- the diagnostic prospective-points JSONL and its optimizer plan JSON.

It has no DuckDB dependency, no outcome access, and no model or solver call. It re-derives nothing
about football: every number is either copied from an artifact or is arithmetic over artifact rows.

The ledger `run_id` of each forecast is **re-derived**, not looked up, using
`fpl.storage.ledger.derive_run_id` over that forecast's own manifest and canonical bytes -- exactly
the derivation `fpl.jobs.record_forecast` performs. That keeps the comparison offline while still
naming the ledger vintage each path was recorded as.

## It is a decision aid, not a promotion test

Two properties are structural rather than advisory.

**It never ranks the architectures.** Each path's expected points are that model's own self-estimate
on its own scale. In the first retained rehearsal the default path reported 322.79 expected points
over GW1-5 and the diagnostic 249.46; that difference measures the two models' calibration against
each other, not which squad is better, and reading it as a verdict would be a category error. The
artifact therefore carries the non-comparability caveat inline, and the captain question -- the one
comparison an owner actually needs -- is answered by **cross-evaluation**: each model scores *both*
captains, so every reported gap is computed inside a single model.

**It fails closed when a comparison would be meaningless.** `build_decision_comparison` refuses
rather than reports when:

- the two forecasts disagree on `as_of`, season, horizon, row/roster/fixture counts, draws, seed,
  forecast commit, database hash, live captures, or frozen contracts;
- the two forecasts declare the *same* `component_modes` (there is nothing to compare);
- a plan names a forecast content hash other than the one it was paired with; or
- a plan's first-gameweek expected points do not reconcile, to `1e-6`, with
  `sum(XI availability-adjusted xP) + (captain_multiplier - 1) * captain xP` recomputed from that
  forecast's own rows.

The last check is the strongest: it independently re-proves that each optimizer artifact really
corresponds to the forecast it claims, using the forecast's own numbers.

## Contract

- **Schema.** `schema = "fpl.decision-comparison"`, `schema_version = 1`, and an explicit
  development-only `status`. Canonical JSON (sorted keys, `allow_nan=False`); every float field
  rejects non-finite values at construction.
- **`comparison_id`.** SHA-256 over the shared knowledge-time identity (`as_of`, season, horizon,
  forecast commit, database hash, seed) plus, for each path, its forecast hash, ledger `run_id`,
  optimizer `run_id`, decision hash, optimizer artifact hash, and component modes. It excludes
  relocatable paths and wall-clock time, so the same two vintages always compare to the same id, and
  it is re-derived and checked on read.
- **Shared inputs, stored once.** The fields both paths must share are recorded a single time, so the
  artifact cannot represent a comparison whose two halves disagree about their own inputs.
- **Per path.** The 15-player squad with each player's price, ownership, first-gameweek
  availability-adjusted xP, availability status and multiplier, lineup role (XI, bench goalkeeper, or
  ordered outfield bench slot), captain/vice marks, and degradation flags; cost against budget; mean
  ownership; first-gameweek and horizon expected points; total hit points; the per-gameweek transfer
  scenario with free-transfer state; and both the roster-wide flagged row counts and the selected
  players carrying each flag.
- **Difference.** Common, default-only and diagnostic-only codes, squad and XI overlap counts, and
  captain/vice agreement -- all re-checked against the two squads on read, so a falsified summary is
  rejected even when its `comparison_id` was recomputed over the lie.
- **Caveats.** The non-comparability of absolute EV, the GW1-only availability overlay, frozen
  prices, the bench/autosub objective simplification, the bounded-search optimality scope, and the
  inherited development-only component status are recorded in the artifact itself.
- **Atomicity and immutability.** Same discipline as the optimizer artifact: a flushed and fsynced
  sibling temporary file is promoted with one atomic create-if-absent hard link, so concurrent
  writers have exactly one winner and an existing destination is never overwritten.

## Run

```powershell
.\.venv\Scripts\python.exe -m fpl.jobs.compare_decisions `
  --default-forecast D:/tmp/gw1/prospective-default.jsonl `
  --default-plan     D:/tmp/gw1/optimizer-plan-default.json `
  --diagnostic-forecast D:/tmp/gw1/prospective-v1v1.jsonl `
  --diagnostic-plan     D:/tmp/gw1/optimizer-plan-v1v1.json `
  --output D:/tmp/gw1/decision-comparison.json `
  --report D:/tmp/gw1/decision-comparison.md
```

The Markdown decision aid always goes to stdout. `--output` additionally writes the immutable JSON
artifact and `--report` the rendered Markdown; both refuse to overwrite an existing file, and a
malformed or non-comparable input exits non-zero with a message rather than a traceback, writing
nothing. Step 12 of `docs/gw1-deadline-runbook.md` is the operational context.

`tests/test_decision_comparison.py` pins the derivation, every fail-closed rule, the deterministic
`comparison_id`, immutable no-clobber and atomic-failure behaviour, concurrent single-winner
publication, reader-side tamper rejection, the report's required P0.3 content, and the CLI. Its two
synthetic forecasts are optimised for real by the Stage E solver and are built to genuinely disagree
on squad, lineup and captain, so the comparison paths are exercised rather than asserted.
