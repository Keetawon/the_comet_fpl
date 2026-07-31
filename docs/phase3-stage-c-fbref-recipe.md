# Stage C defensive-actions backfill — B-path FBref pull recipe

**Status: operator recipe.** fbref.com is blocked in the build environment, so this is the
exact local pull an operator runs *where FBref is reachable*, then commits as a vendored
dump. The pull's column mapping and the gate are implemented and tested against a synthetic
fixture; the real pull is exercised when the operator commits the dump. **FBref's exact
per-player match-log API varies by library version — verify the calls below against the
version you run. Treat the mapping as unverified until the 2025-26 overlap gate passes.**

## Why two FBref tables, joined

FBref splits per-match player stats into separate match-log tables keyed per
player/season/stat-type. The five canonical fields come from **two** of them:

| canonical field | FBref table | FBref column |
|---|---|---|
| `tackles` | **Defense** match log | `Tkl` (total tackles) |
| `interceptions` | **Defense** match log | `Int` |
| `blocks` | **Defense** match log | `Blocks` (FBref Blocks = shots blocked + passes blocked) |
| `clearances` | **Defense** match log | `Clr` |
| `recoveries` | **Miscellaneous Stats** match log | `Recov` |

**Recoveries is the binding field** (`docs/phase3-stage-c-a-path.md`): a pull with Defense
but not Misc is insufficient. Pull both and join per (player, match date). The 2025-26
overlap gate exists precisely to test whether FBref's definitions (e.g. FBref `Blocks` =
shot + pass blocks) match FPL's Opta fields — it is a real test, not a formality, and may
fail.

## Primary pull — worldfootballR (R)

`worldfootballR::fb_player_match_logs()` exposes the defense and misc match logs directly.
For each PL season 2021-22..2025-26, collect the player URLs from FBref's squad pages, then:

```r
library(worldfootballR)

seasons <- list(
  "2021-2022", "2022-2023", "2023-2024", "2024-2025", "2025-2026"
)
# player_urls: FBref /players/ URLs for every player who appeared in the season
# (worldfootballR helpers or the FBref standard squad table supply these).

pull <- function(player_urls, season_label) {
  defense <- fb_player_match_logs(player_urls, stat_type = "defense")
  misc    <- fb_player_match_logs(player_urls, stat_type = "misc")
  # Join per (Player, Date); defense carries Tkl/Blocks/Int/Clr, misc carries Recov.
  logs <- merge(
    defense[, c("Player", "PlayerURL", "Squad", "Date", "Tkl", "Blocks", "Int", "Clr")],
    misc[,    c("Player", "Date", "Recov")],
    by = c("Player", "Date"), all = FALSE
  )
  # Map to the canonical columns (see table below) and tag the FPL season label.
  logs$season <- season_label
  logs
}
```

The `PlayerURL` slug is the stable FBref player id — use it for `external_player_id`.

## Alternative pull — soccerdata (Python, version-dependent)

soccerdata's `FBref` reader exposes schedule, match sheets, and **season-aggregate** player
stats reliably; per-player **per-match** defense/misc match-log coverage has varied across
versions. If your version exposes match logs, prefer it; otherwise use worldfootballR above.
Verify the method against your installed version before trusting it:

```python
import soccerdata as sd

fbref = sd.FBref(leagues=["ENG-Premier League"], seasons=["2021-2022", ...])
# Confirm the per-player defense/misc match-log method exists in your version; soccerdata
# primarily ships season aggregates, not per-player-per-match defense/misc logs.
```

## Canonical-CSV column mapping

After the join, write one row per (player, match) with exactly these columns (the reader
enforces the exact set, `fpl.ingest.defensive_actions_csv`):

| canonical column | source |
|---|---|
| `season` | the season label you pulled, as FPL `YYYY-YY` (`"2025-26"`) |
| `external_player_id` | stable FBref player id (the `/players/<slug>/` slug) |
| `player_name` | FBref `Player` (full name; accents preserved) |
| `team_name` | FBref `Squad`/`Team` club string (e.g. `"Manchester United"`) |
| `match_date` | FBref `Date`, ISO `YYYY-MM-DD` |
| `tackles` | Defense `Tkl` |
| `interceptions` | Defense `Int` |
| `blocks` | Defense `Blocks` |
| `clearances` | Defense `Clr` |
| `recoveries` | Misc `Recov` |

Counts are non-negative integers. A blank cell means **unmeasured**: leave it blank (the
reader preserves it as None and skips the row, never zeroing it). Commit the file at the
`defensive_actions_dump.csv_path` from `config/sources.yaml` (default
`data/fbref_defensive_actions.csv`) and fill the `provenance` block (`pulled_on`, tool
version).

## Rate-limit / time caveat

FBref rate-limits aggressively (HTTP 429). Both libraries insert delays; do not disable them.
A full five-season pull is ~5 seasons x ~550 players x 2 tables — cache aggressively, make it
resume-friendly (write per-player, skip already-pulled), and expect it to run for hours. Run
it locally, not in the build environment.

## Attribution / licence

FBref data is free for **non-commercial use** and is StatsBomb-sourced; attribute FBref and
StatsBomb. Do not redistribute commercially. Until the overlap gate passes, the dump is an
unverified assumption, not confirmed facts.

## Then: commit and run the gate

```powershell
# Commit the dump under data/ (fill provenance.pulled_on in config/sources.yaml first).
.\.venv\Scripts\python.exe -m fpl.jobs.backfill_defensive_actions
# Or explicitly:
.\.venv\Scripts\python.exe -m fpl.jobs.backfill_defensive_actions `
  --csv data/fbref_defensive_actions.csv --database data/fpl.duckdb
```

The job resolves identities per season (reports match rate, method breakdown, ambiguous /
unmatched ids, and unresolved club strings), then on 2025-26 rebuilds DC from the external
actions and requires **>= 99.5% exact agreement** across DEF/MID/FWD scoring rows **and
>= 98% identity match rate**. It exits non-zero on failure and never emits a backfill. Pass
=> backfill 2021-22..2024-25 and DC becomes backtestable. Fail => DC stays prospective-only
from FPL alone (`docs/phase3-stage-c-design.md`, option 2a).
