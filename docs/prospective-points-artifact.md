# Prospective points artifact

Status: implemented, development-only. The artifact is a reliable transport contract, not a
claim that the component forecasts have been prospectively validated at real deadlines.

## Purpose and format

`fpl.jobs.prospective_points_v1` emits a versioned JSON Lines file when `--output` is supplied.
The optimizer and any future publish layer consume this file and never query DuckDB. JSONL was
chosen over Parquet because the small file contains nested probability vectors and genuine nullable
live fields; canonical standard-library serialization is transparent, diffable, and exactly
reproducible without another storage dependency.

The writer creates a temporary file beside the destination, flushes and fsyncs it, then uses one
atomic replacement. A failed replacement leaves the previous artifact intact.

## Grain and ordering

Line one is a manifest. Every later line is one forecast at grain `(season, gw, code)`, ordered by
that key. `code` is the permanent player identity; season-scoped `element_id` is intentionally not
exported as a tracking key. The file contains the complete live player roster for every gameweek in
the requested horizon, including players with no fixture. A blank gameweek is the exact point mass
`[1.0]` at zero points. Double-gameweek fixture distributions are convolved in ascending fixture
order.

## Manifest contract (`schema_version = 1`)

The manifest contains:

- `schema = "fpl.prospective-points"`, `schema_version`, and the explicit development-only status;
- `as_of`, `season`, `gw_from`, `gw_to`, row/roster/fixture counts, seed, draw count, and fixture
  support limit;
- Git commit, an enforced clean-worktree flag, and database SHA-256 identities;
- scoring, Stage B, and Stage C contract names, versions, and SHA-256 identities;
- component modes and names, including appearance, attacking, assist, and share-signal modes;
- the selected bootstrap capture ID, its `known_at` and payload SHA-256, plus the selected schedule
  capture IDs; and
- whether the freshness assessment was a valid season-start cold start.

## Forecast-row contract

Each forecast row contains:

- identity/context: `season`, `gw`, stable `code`, nullable `web_name`, `position`, season-scoped
  `team_id`, and cross-season `team_code`;
- deadline-known live metadata: nullable `now_cost`, nullable `selected_by_percent`, availability
  `status`, nullable `chance_of_playing`, and `availability_multiplier`;
- sorted `fixture_ids` and matching `kickoff_times`;
- the raw full-points probability vector `distribution`, its `expected_points`, and
  `expected_bonus`;
- `availability_adjusted_expected_points`; and
- cold-start, league-average-team, attacking-signal, assist-signal, and transfer flags already
  tracked by the forecaster.

JSON `null` is preserved. It is never converted to zero. The distribution must be non-negative,
finite, sum to one within `1e-9`, and reconcile to `expected_points`. Availability is a separate
reported overlay: it changes the adjusted expectation but never the stored distribution.

An abbreviated row looks like this:

```json
{"record_type":"forecast","season":"2026-27","gw":1,"code":12345,"position":"MID","now_cost":75,"selected_by_percent":null,"availability_multiplier":1.0,"expected_points":4.62,"availability_adjusted_expected_points":4.62,"distribution":[0.08,0.12,0.17],"cold_start_player":false}
```

The real row includes every field above and a probability vector whose full mass sums to one.

## Reproducible run recipe

Run jobs sequentially because DuckDB is single-writer:

```powershell
git fetch origin main -q
git checkout -B main origin/main -q
git reset --hard origin/main -q
.\.venv\Scripts\python.exe -m fpl.jobs.build_db
.\.venv\Scripts\python.exe -m fpl.jobs.load_snapshots snapshots/daily/*/*
.\.venv\Scripts\python.exe -m fpl.jobs.prospective_points_v1 --output D:/tmp/prospective-points-2026-27-gw1-5.jsonl
```

The default cutoff is the 2026/27 GW1 deadline (`2026-08-21T17:30:00Z`) and the default horizon is
GW1-5. Before a GW1 deadline, no current-season result is expected, so the freshness gate correctly
passes as a cold start. At later deadlines it refuses output when the most recently completed
current-season gameweek lacks player-history rows captured with `known_at <= as_of`. Bootstrap and
schedule metadata are independently selected only from captures known by the same cutoff.

Two identical runs from the same Git commit, database, configuration, live captures, arguments, and
seed must produce identical bytes and therefore the same SHA-256. Artifact emission refuses a dirty
worktree because a commit SHA alone cannot reproduce uncommitted source. Put generated output
outside the repository (as in the recipe) so it does not itself dirty the checkout.
