# Phase 3 Stage C: defensive-actions backfill — A-path investigation (negative result)

**Status: audit record. A-path (GitHub-hosted mirror) is NOT satisfiable; no code, config, or
data was produced. B-path (local FBref pull, committed as a vendored dump) is the recommended
route.** This record exists so the negative result is not re-investigated from scratch.

## Why a backfill is needed at all

FPL began recording defensive actions only in 2025-26. Verified against
`mart_fact_player_fixture`: `tackles`, `recoveries`, and `clearances_blocks_interceptions` are
0% non-null for 2021-22..2024-25 and 100% only in 2025-26. Defensive contribution (DC) is a
2026-27 scoring element, so a backtestable DC component needs the raw per-match actions for the
four earlier seasons from an **external** source. The rebuild formula and the identity
crosswalk are already built and tested (`src/fpl/transform/defensive_actions.py`,
`src/fpl/transform/external_identity.py`, `src/fpl/jobs/validate_dc_overlap.py`); only the data
is missing.

## A-path precondition and why it fails

A-path required an **egress-reachable, GitHub-hosted** dataset carrying per-player-per-match PL
defensive actions — all five fields (tackles, interceptions, blocks, clearances, recoveries) —
for 2021-22..2025-26.

Egress (verified, real requests from this environment):

| host | result | usable |
|---|---|---|
| `raw.githubusercontent.com` | HTTP 200 | yes |
| `fbref.com` | blocked (000 / proxy 403 CONNECT) | no |
| `understat.com` | unreachable here, and irrelevant | no |

Two facts close the path:

1. **Understat carries no defensive actions** — it is shot-level xG/xA only, so it cannot
   supply tackles/interceptions/blocks/clearances/recoveries regardless of reachability.
2. **No committed GitHub mirror has the required granularity.** A thorough search (targeted web
   searches, stars-ranked GitHub repository searches, and direct recursive tree inspection of
   the most plausible data repos) found only: (a) scrape *code* with no committed data, (b)
   season-level Standard-stats CSVs with no defense/misc columns, (c) match-level *team*
   aggregates with no per-player rows, or (d) match scores. Representative rejections:
   `chmartin/FBref_EPL` (season-level Standard only, stale ~2021), `mert-byrktr/Scrape-EPL-Data`
   (per-team match level, no per-player defense), `eddwebster/football_analytics` (5,707 CSVs,
   none defense/misc match-logs), `footballcsv/england` (scores only), `parth1902/scrape-FBref-data`
   (notebook, no data).

**Structural reason it does not exist:** FBref's per-match player data is split across match-log
tables keyed per player/season/stat-type, and `recoveries` specifically lives in FBref's
**Miscellaneous Stats** table — the least-mirrored of its tables. Tkl/Int/Blocks/Clr live in the
**Defense** table. A usable backfill needs BOTH tables joined per (player, match). The only tools
that expose that granularity (`soccerdata`, `worldfootballR`, assorted notebooks) scrape
`fbref.com` live, which is blocked here, and none has committed five PL seasons of the joined
output.

## Two flags carried forward to B-path

1. **Recoveries is the binding field.** A source with Defense but not Misc is insufficient. Pull
   both FBref tables and join per (player, match).
2. **Definitional alignment is unproven and may still fail.** FBref's defensive definitions are
   Opta-derived but not guaranteed identical to FPL's Opta fields (e.g. FBref Blocks counts
   shot+pass+dribble blocks). The 2025-26 overlap gate (>= 99.5% exact DC agreement +
   >= 98% identity match) exists to catch exactly this. It is a real test; B-path data can fail
   it too, in which case DC stays **prospective-only from FPL alone** (design option 2a in
   `phase3-stage-c-design.md`).

## B-path (recommended)

1. Locally, where `fbref.com` is reachable, pull PL 2021-22..2025-26 with `soccerdata` (Python)
   or `worldfootballR::fb_player_match_logs()` (R) — both the **defense** and **misc** match
   logs.
2. Map each row to the canonical columns of `ExternalDefensiveActions` (season,
   external_player_id, player_name, team_name, match_date, tackles, interceptions, blocks,
   clearances, recoveries) and commit a clearly-labelled vendored dump with a provenance manifest
   (source URLs, pull date, tool version). FBref's non-commercial/attribution terms apply; treat
   the data as an unverified assumption until the gate passes.
3. The already-built, source-neutral machinery then does the work unchanged: `combine_cbi` +
   `ExternalDefensiveActions` (adapter), `build_identity_crosswalk` (roster join),
   `check_dc_reconstruction` + `validate_dc_overlap` (the 2025-26 gate). The only new code is a
   local-CSV reader in place of an HTTP client.
4. The gate decides. Pass -> backfill 2021-22..2024-25 and DC becomes backtestable. Fail -> DC
   stays prospective-only from FPL.

## Note on the unblocked alternative

The **attacking-goals** Stage C slice (the proposed first slice) needs no external data — it uses
FPL goals and xG-where-measured. It can proceed while the defensive backfill waits on a local
FBref pull, so the A-path dead end does not stall Stage C.
