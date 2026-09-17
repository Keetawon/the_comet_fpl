# Goal patterns follow captured source revisions

The capture pipeline was running correctly. The display audit covered fixtures 1–39;
fixture 40 had no receipt. Revised raw hashes for fixture 36 correctly invalidated
its old receipt. The chart then hid a club's entire total when one receipt was missing.

Schema 8 retains exact source-bound manual audits. Other validated current-season
match sides now receive deterministic source accounting from the exact raw payload
used by the exporter. Explicit `goalsOpenplay`, `attPenGoal`, `attFreekickGoal`, and
the opponent's `ownGoals` are reconciled to both official scores. Whole-valued JSON
numbers are accepted; omitted, null, boolean, negative and fractional counts fail
closed. Unexplained goals stay **Unclassified**. They are never assumed open play
or set pieces. A complete set-piece total remains NULL while origins are unresolved.

Each new interpretation records its own time, actual source time and raw SHA256.
The next export reinterprets a changed source; it does not carry manual classifications
across raw revisions. Old captures, audits, exports and forecasts remain immutable.
The existing bounded revision capture window is unchanged: an old match outside that
window is not promised a new upstream check merely because its origin remains unknown.

The chart also retains known official goals if a complete receipt cannot be built.
It shows explicit open-play counts and a clearly marked unknown remainder, without
inventing measured set-piece or own-goal zeros. Table and CSV retain missing full
set-piece values, with fixture-specific provenance and reasons.

## Retained source check

Fixture 40, Leeds–Newcastle, 2026-09-14 19:00 UTC; raw stats captured
2026-09-17 02:30:24.531275 UTC, SHA256
`9ce926e841da8e00b261d5b7c52638b701035e63b9084ea2e10099deb52afad0`:

| Team | Official goals | Explicit open play | Opponent own goals | Unclassified | Full set-piece total |
|---|---:|---:|---:|---:|---:|
| Leeds | 4 | 2 | 1 | 1 | NULL |
| Newcastle | 1 | 1 | 0 | 0 | 0 |

Across GW1–4 each club has seven goals. Leeds has three open play, two previously
corroborated set pieces, one opponent own goal and one unclassified. Newcastle has
five open play and two corroborated set pieces. No external match report was newly
used to classify Leeds' remaining goal.

The corrected sidecar has 80/80 current team-side receipts (previously 76/80), with
79/80 fully classified. Provider core health is still **36/40 fixtures**, independent
of the four previously owner-corrected display fixtures. Raw team measurements,
player rows, coverage, source timestamps and existing correction records are unchanged.

## Operation and publication

On 17 September the existing task was verified enabled with `PT4H` and owner sign-in
`PT2M` triggers, zero missed runs, and the `.worktrees/v2` junction resolving to the
active checkout. The last completed refresh finished 09:57:56 Bangkok. The 11:00
cycle was running; no overlapping refresh or writer-lock removal was attempted.

Verification used the prior completed cycle's immutable `before-outcomes.duckdb`
backup. The corrected review export uses interpretation cutoff
`2026-09-17T04:08:34+00:00`; its newest captured source remains 02:52:12.731281 UTC.
This is a new display interpretation, not a new provider capture.

Corrected sidecar SHA256:
`ca03c19b6350d4bc55d7e77009a5fd05320d54652da1f17d07230bf11f07eb0c`.
Review files, previous export and real desktop/mobile screenshots are retained in
`data/artifacts/goal-refresh-20260917/`. The local preview was rebuilt. The public
site separately consumes `dashboard/public-data-release.json`; local refresh alone
does not upload a release or publish a branch to Pages. No public update is implied.

## Verification

- 73 Python goal/export tests passed; float-count regression subsequently passed all
  11 focused goal tests. Strict mypy and changed-file Ruff/format passed.
- 86 frontend parser, provenance, CSV, plot and page tests passed; TypeScript/build
  passed. Frontend lint retains nine existing Fast Refresh warnings.
- Isolated Chrome verified real local data, desktop/mobile goal bars, expansion and
  CSV download, with no runtime exception or failed network request. Browser plugin
  discovery returned no available browser; existing isolated Chrome was used.
- Missing origin, later correction, stale audit, exact source identity, truthful
  timestamps and deterministic transformation are covered. No model, optimizer,
  historical audit, configuration, prediction or raw capture was changed.
