# Prospective points artifact

Status: implemented, development-only. The artifact is a reliable transport contract, not a
claim that the component forecasts have been prospectively validated at real deadlines.

This file is one immutable forecast snapshot, not yet a multi-run prediction ledger. The next
production layer must retain every pre-deadline artifact/run identity rather than replacing an older
forecast, and must join actuals only after fixture finalisation. BI and model-monitoring consumers
need both player-fixture and player-gameweek grains; the current public artifact exposes the latter.

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

`stage_a_league_average_team` is `true` when this prediction used a league-average (1.0x) Stage A
rating for the player's own team OR the fixture opponent. The fitted Stage A model resolves every
club's attack and the opponent's defence multiplicatively and falls back to the 1.0x multiplier for
any `team_code` absent from its fitted ratings, so a club with no archive history -- a promoted
side -- runs on the league-average rating: the player's own team drives his goals via `lambda_team`
and the opponent drives conceded goals / clean sheets. The promoted-team prior
(attack 0.719x / defence 1.309x) is deliberately **not** applied on this path; using it is separate,
separately-variance-carrying open modelling work. (An earlier wording, "team unresolvable",
described only the never-occurring case where a bootstrap `team_id` maps to no `team_code` at all,
which never fires for the 20 league clubs.)

JSON `null` is preserved. It is never converted to zero. The distribution must be non-negative,
finite, sum to one within `1e-9`, and reconcile to `expected_points`. Availability is a separate
reported overlay: it changes the adjusted expectation but never the stored distribution.

The current multiplier comes from the deadline bootstrap's
`chance_of_playing_next_round`/status and is repeated on every gameweek row in the horizon. That
next-round-to-horizon assumption is not prospectively validated. It must be replaced by a measured
per-GW availability policy or explicitly excluded from later-GW decision utility before operational
use; the raw distribution remains unchanged either way.

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

Before this contract is accepted as an external BI source, harden the reader to assert UTC-aware
timestamps, `bootstrap_known_at <= as_of`, exactly `roster_size` stable codes in every gameweek,
and the required contract/component identity keys. The current saved artifact satisfies those
conditions; the remaining work is fail-closed validation for malformed future inputs.
