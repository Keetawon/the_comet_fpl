# Current club form publication repair

The reported Fixture Matrix discrepancy was a publication bug, not a lack of
promoted-club match data. The September 15 export contained all 80 current club
fixture sides across GW1–4, but its `form` objects came from the archive-only
`fact_team_form` mart. Arsenal was anchored at 2025-26 GW38, Ipswich at 2024-25
GW38, and Hull/Coventry had no archive form. Those values were not current form.
Summary's club watchlists and Team Analytics shared that same object.

The shared JSON publisher now derives all four club form windows from its own
validated `team_actuals` and `team_provisional_actuals` records. It joins on season
and permanent club code, orders ended fixtures by kickoff and fixture ID, counts
each DGW leg once, and prefers finalized evidence on an exactly matching identity.
Duplicate identities fail. A short current season stays short; an empty season
remains unavailable instead of silently using an old season. Expanded-history
controls may still explicitly cross the season boundary; they are a different view.

Each window includes exact fixture IDs, GW range, provisional count, and separate
xG/xGC measurement counts. Rates divide by measured matches, including observed
zeros; absent values stay NULL. These are FPL source-row aggregates, not SDP
estimates or forecast inputs. UI labels expose the season and observation depth;
legacy packages explicitly say Archived. Team Analytics disables optional AI
explanations for provisional past-form views while keeping local facts usable.

The normal `build_sdp_dashboard` freshness gate now compares every emitted club
form against the same published match logs. A stale or changed aggregate stops
installation, even if fixture identities and generation timestamps look current.
The existing capture → normalize → export → validate → install command remains
the entry point; no new scheduler, database or parallel refresh path was added.

The repair was applied locally using the retained September 15 `bi-retained`
snapshot and existing export/package/install functions. There was no new source
capture or inference. Current source time remains 2026-09-15 01:55:41.948067 UTC
for provisional FPL observations. All 20 clubs have three finalized matches plus
one provisional GW4 match:

| Club | Matches | W-D-L | Goals for-against |
|---|---:|---|---|
| Arsenal | 4 | 4-0-0 | 8-1 |
| Hull City | 4 | 2-2-0 | 5-2 |
| Coventry City | 4 | 0-0-4 | 0-10 |
| Ipswich Town | 4 | 2-0-2 | 7-10 |

Publication reconciliation covers 560 club/vintage rows and 80 current club
fixture sides. Every team forecast field outside `form` is identical. Eleven
other JSON documents, including players/xP/horizons, monitoring and optimizer
plans, remain byte-identical. The SDP sidecar remains SHA256
`24db05500a2ce494a31fcde288ba3b0cf2ff892d4ac2acce2c119dce468d915a`.
Of 404 protected pre-refresh fingerprints, 402 remain identical after the final
documentation update; the two intended changes are the dashboard JSON publisher
and the additive `AGENTS.md` reporting instruction. Model/configuration, historical audit
results and original prediction artifacts remain unchanged.

Verification: 117 Python tests passed, four existing Windows publication/symlink
tests skipped; 191 frontend page/loader/analytics tests passed. Ruff checks, strict
mypy on the three affected publishing modules, TypeScript/build and frontend lint
passed. The four new/small Python files pass formatting. The two existing large
publisher/test files retain formatting failures also reproduced on their unedited
HEAD contents. Existing nine Fast Refresh warnings and bundle-size warning remain.

The in-app browser reported `No browser is available`. Isolated installed Chrome
verified all 20 displayed club rows at desktop/mobile widths against the emitted
form, Last 3 selection, expanded table, Summary and Team Analytics. No JavaScript
exceptions or local data/asset failures occurred. One external player image was
blocked by Chrome (`ERR_BLOCKED_BY_ORB`). Local screenshots and verification
receipts are retained in `data/artifacts/current-team-form-20260915/`.

Local preview: `http://127.0.0.1:4173/#fixtures`; reload existing tabs to clear the
session data cache. This is not a production deployment. The new package is
`data/artifacts/current-team-form-20260915/dashboard-public-data.zip`, SHA256
`1216d2f2b9e69acd4524031bbaf38ff78b3c3cf27122bdd8689478716e63fd54`.
It remains separate from the original generation. Main and default branch are untouched.
