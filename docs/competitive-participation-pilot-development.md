# Competitive participation pilot: retained, downstream blocked

This is data validation only. Pilot preregistration and implementation were committed at
`0beb0f51370cefdd441356b32e78b7f9f22b349d` before collection. No model fit, forecast, default
change, database write, schedule activation or full-season historical backfill was performed.

Scope: Arsenal(team3) and Crystal Palace(team31),2025-09-13 through2025-10-06 exclusive.
The six verified competition catalogues were read completely: PL380,FA Cup123,League Cup93,
UCL189,UEL189,Conference153 matches. Only13 relevant fixtures in the bounded club/time scope
had lineups/events requested: eight PL,two League Cup,two UCL,one Conference. FA Cup and UEL
have no selected-club fixture in this window, not a claim their providers are unavailable.
Friendlies are excluded.

## Real capture and independent agreement

All39requests returned HTTP200:13 metadata pages,13 lineups,13 events. Exact response bodies,
URLs/parameters, content hashes, response headers, request/capture times and per-match manifests
are retained. No retries, failed HTTP responses or rate-limit responses occurred. Sequential
global pacing used the configured1.5-second minimum; no concurrent scraping was used.
The 39 responses were each captured once; future versions must remain separate.

Capture coverage is13/13; **valid interpretations are12/13 (92.3077%)**, below the preregistered
100% requirement. The run completed and correctly returned failed acceptance, not a network error.
The parsed12 alone pass every identity/PL validation check, but are not silently substituted as
a new accepted population:

- Exact season-qualified `opta_code == p{provider_player_id}`:246/246 parsed-club roster rows.
  Independent checking includes all13 raw selected-club rosters:266/266 exact mappings, zero
  unmatched/ambiguous identities. The extra20 mapped Palace players do not repair the failed match.
- Eight PL matches:160/160 starter agreements and160/160 appearance agreements against FPL.
- 121 played-player nominal durations:93exact,26one minute higher,2one minute lower;
  all within one minute. MAE28/121=0.231404959minutes, inside the fixed≤1minute and≥95%
  within2minutes requirements. There were no duration repairs to match FPL.
- The two nominal0/FPL1 cases are late substitutes Mosquera(code500040,match2561936) and
  Devenny(code489706,match2561948); appeared remains true. Derived nominal participation
  minutes are neither provider-reported minutes nor verified physical elapsed minutes.

## Hard source contradiction: match2603048

League Cup,2025-09-16T19:00Z: Palace1–1Millwall, Palace win penalties4–2.
Millwall's raw `players` list has21entries, **12 marked non-substitutes**, including both
goalkeepers Max Crocombe(provider108801) and Steven Benda(provider428971). The formation
has11starters plus9bench players, names Benda as goalkeeper, and omits Crocombe entirely.
No goalkeeper substitution explains the discrepancy. The parser therefore rejects
`expected 11 starters, observed 12`.

This is not fuzzy-name failure, an unavailable FPL identity, or permission to pick whichever
roster looks convenient. Selecting formation over raw roster/position would introduce a new
withdrawn-player/source-precedence interpretation. Independent corroboration and an explicit
rule are required before this match can be licensed. The accepted-population threshold was not
lowered and the match was not silently dropped. Penalty shootout evidence does not imply120minutes.

Accordingly no workload mart, learned role layer, minutes successor or downstream player
experiment is licensed by this pilot. Formation/broad-position payloads are retained as potential
observed labels; they are not pre-deadline predicted roles. Historical acquisition remains
retrospective development evidence. Actual end times/rest-hour precision remain unavailable
unless separately corroborated; a kickoff-plus90minutes fabrication is not used.

## Paths and reproducibility

Original read-only reference:
`D:\Personal\workspace\the_comet_fpl\.worktrees\sdp_test\data\fpl.duckdb`,
SHA256`0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8`.
Before/after hashes are identical and no WAL exists. All10 pinned source/config hashes were
independently checked unchanged. No default or operational database now contains a new
participation mart: the refreshed raw evidence lives in the following persistent directory only.

`D:\Personal\fpl-operations\verification\competitive-participation-20260907T070000Z\`

Original `result.json` SHA256:
`f34b0c978b6de9454bbd1bb52cb2d2faabee6347b8baa16403bca773b56bf411`.
Independent audit SHA256:
`84568a52959f87151c6419ac6c85985d868179e959edde32453abfd8fe5409a2`.
Byte-identical report copies are retained in `results/competitive_participation_pilot_development.json`
and `results/competitive_participation_pilot_independent_audit.json`. Raw response bytes stay
in the named persistent directory; this is not a claim that a remote clone includes those bytes.

Actual command using the permanent Python environment:

```powershell
& 'D:\Personal\fpl-operations\.venv\Scripts\python.exe' -m fpl.jobs.competitive_participation_pilot `
  --db 'D:\Personal\workspace\the_comet_fpl\.worktrees\sdp_test\data\fpl.duckdb' `
  --results 'D:\Personal\fpl-operations\verification\competitive-participation-20260907T070000Z'
```

57 focused pilot tests passed before collection; included again in the final316-test focused
gate. Raw/event validation was independently recomputed without invoking the pilot parser.
No pilot re-fetch, interpretation change or result overwrite followed the failure. The independent
Phase A team evaluation proceeded separately; no participation data entered that experiment.
