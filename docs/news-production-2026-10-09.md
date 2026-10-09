# Reviewed production news and workspace retention

**October 10 owner amendment:** the five-hour display rule below is superseded.
Reviewed updates now appear immediately; the repaired complete-text capture
publishes 20 club reports. See
[`news-coverage-and-storage-2026-10-10.md`](news-coverage-and-storage-2026-10-10.md).
The remainder of this document records the earlier release and its verification.

The owner authorized publishing current news, the five-hour deadline preference,
safe disk cleanup, and committing/pushing the work. This is reporting only:
no forecast, football model, optimizer or SDP default changes.

## Production news

The previous production page requested `sdp/news_feed.json` from the forecast
generation, whose inventory did not contain it. News now has an independent
`https://data.thecometfpl.com/news/current.json` publication, like the existing
independent official FPL reporting feed. The browser accepts that endpoint only
when the exact existing production data pointer is configured. Local legacy
generation loading remains supported; a failed live request has no stale bundled
fallback. The immutable forecast pointer is never rewritten by news publication.

The publisher validates the public schema and sanitizer, writes a content-addressed
edition, verifies its bytes, then uses an ETag conditional write for current.
Replay of the same edition is a no-op; concurrent writers and timestamp rollback
fail closed. Raw X posts, SQLite storage and credentials stay private. No new
dependencies, provider browser requests or model inputs were added.

Source: **Fantasy Football Scout, @FFScout**, using the bounded `team_news`
query in `fpl.ingest.public_news`. A restart after more than seven days previously
sent an expired `since_id` and received HTTP 400. The cursor now considers only
observations inside the recent-search window. Existing raw evidence remains
append-only. Default capture stays disabled in the checked-in configuration;
local credentials are read only from the capture process/private environment file.

October 9 capture: ten posts, eight substantive candidates and two promotions.
English and Thai were checked against the retained source text. Four summaries
passed: Brentford, Ipswich, Hull and Aston Villa. Six were withheld (promotions,
translation errors or unsupported details in incomplete source sentences).
This is a partial selected-source edition, not complete league coverage.

Publication now requires an append-only factual review of the **exact** summary
hash, at an actual review time. New model/prompt versions do not inherit approval.
Withdrawal takes effect on the next publication. X stories older than seven days
are omitted by the publisher and the production reader. Older samples cannot
silently reappear after source reactivation. The news page refreshes every fifteen
minutes and retains source/capture/publication timestamps.

Schema v2 adds the actual official future GW deadline, schedule capture time and
source hash. The roundup opens **five hours before that deadline** and closes at
the deadline; an edition over 24 hours old cannot populate it. Individual reviewed
stories are visible immediately. Tests cover both exact boundaries. The earlier
all-conferences-finished path remains a development preview: there is no verified
all-club completion collector, so production does not invent that signal.

**Automation limit:** this release publishes reviewed reports, not unattended AI
output. Automatic X capture/publication is not scheduled by this change. The
five-hour rule controls the roundup display; it is not a claim that another X
capture will automatically occur at that time. FDR/injury cloud reporting and the
existing desktop forecast schedule are separate. A reliable
unattended news workflow still needs a factual-review process and edited/deleted
post reconciliation; valid JSON alone failed the real bilingual quality check.

Private capture: `python -m fpl.jobs.capture_public_news --config <private-yaml>
--store <private-news.sqlite3> --output <new-receipt.json>`.
After reviewing retained summaries through `NewsStore.review_summary`, publish:
`python -m fpl.jobs.publish_public_news --store <private-news.sqlite3>
--r2-config <private-publication.json> --output <new-private-edition-directory>`.
Keep the source explicitly approved only while public reuse is authorized.
Use `--allow-empty` for an explicit withdrawal of the whole public edition.

The October 9 production check also found the separate hourly official FPL
workflow **disabled_manually**, with no `production-fpl` GitHub environment and
no previous workflow runs. Its live endpoint was still dated October 5. A local
execution of the existing publisher refreshed all 667 players and 760 fixture
sides at **2026-10-09 17:27:44 UTC**, with verified publication. The owner then
explicitly approved the credential transfer. The main-only `production-fpl`
environment is now configured and the hourly workflow enabled. First cloud run
`37967569068` succeeded, publishing a new verified capture at **17:37:39 UTC**.
This is a verified manual dispatch of the enabled hourly workflow; the next
cron-triggered run has not yet been observed. See the activation addendum in
`docs/hourly-official-fpl-reporting-2026-10-05.md`.

## Storage cleanup

Removed **11,148,776,856 bytes (10.383 GiB)** of completed pytest temporary
databases, after checking exact paths, tracked-file absence, no reparse targets
and no active test process. Audit receipts and test logs remain. The manifest and
completion receipt are local under
`data/artifacts/workspace-cleanup-20261009/`.

Resumed the interrupted October 8 operational retention under its existing lock
and idle-database checks. The old 5,704,790,016-byte recovery database compressed
to 1,031,485,156 bytes. Decompression reproduced its original SHA-256 before the
uncompressed original was retired. Another 999,703,229 bytes of derived generation
files were removed by the existing retention policy. Total reclaimed across these
actions: **16,821,784,945 bytes (15.667 GiB)**, before new test/build files.

Keep the latest operational model data and **two** recent uncompressed replay/
recovery copies. Older required copies remain losslessly compressed. Historical
forecasts, immutable snapshots, formal research results, source receipts and
replay evidence cannot be replaced with only the newest model: scoring and audit
depend on them. Protected SDP/news worktrees and pending user changes are intact.

Pytest now retains only the latest failed temporary run. Keep audit logs outside
the temporary database tree; do not use permanent evidence directories as
`--basetemp`. That explicit pytest option bypasses automatic retention. Local
worktrees and disposable temporary paths are ignored, not deleted or staged.

## Verification and deployment

- News capture/store/publication tests: **66 passed**, including expired cursors,
  exact append-only review, denied unreviewed publication, conditional writes,
  readback failure, timestamp rollback and deadline schedule validation.
- Dashboard: **793 passed**; build and lint passed (nine pre-existing lint warnings).
  The final focused UI rerun passed 71 tests. Pages deployment
  [37967528722](https://github.com/Keetawon/the_comet_fpl/actions/runs/37967528722)
  passed all quality/build/deployment jobs at `7303219`.
- Production browser verification: four source-linked real stories in EN and TH,
  correct GW6 opening time **October 10 05:00 UTC / 12:00 Bangkok**, and official
  FPL capture **October 10 00:37:39 Bangkok** from the successful cloud job.
- The reviewed news HTTPS body hash is
  `219e60c23c85cbfd35e486259bb553b0780a392e5446787897e40de532abf9b3`.
  Its production CORS and no-store caching were independently verified. The main
  forecast generation remains `29b2ce3ae80633d2fb958ad8903267e4f8b817a4d30c07d6305830ea851f28b8`.
- Full repository Ruff passed; strict mypy passed all 244 source files. All eight
  changed/new Python files pass formatting. Global format still reports ten
  unrelated pre-existing files.
- The full Python gate completed: **4,379 passed, 156 skipped, 65 failed,
  22 errors**. This is **not a green full gate**. The failures remain outside the
  news test files, in the broader frozen-input/reference/Windows paths also
  recorded in the October 5 repair. Full logs and exit codes are retained under
  `data/artifacts/news-production-20261009/`; no scientific result was rerun or
  reinterpreted to make the gate pass.

The SDP V2 checkout remains clean at `999a29c`; the active local-news-notes edits
and pre-existing root scratch work remain intact. All changes for this delivery
were committed and pushed to `origin/main`, without merging the V2 model branch.
