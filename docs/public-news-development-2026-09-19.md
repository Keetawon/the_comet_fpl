# Public Premier League news: development delivery

The owner requested an attributed public news feed covering injuries, suspensions,
transfers, squad updates and manager comments, with Thai/English selection and
sharing. This supersedes the proposed manual-only R2 scope; the separate local
manual-note work is preserved and is not part of this delivery.

**Development only.** No API key, paid request, scheduler change, operational DB
write, R2 upload or production deployment was made. Start: `da655b8`, isolated
branch `codex/public-news`; the operational V2 worktree remains untouched.

## Delivered path

1. `capture_public_news` imports a checksum-verified retained FPL bootstrap and/or
   requests one bounded recent-search page per approved X account.
2. A separate private SQLite file retains raw observations, actual knowledge times,
   summaries, status receipts and conservative monthly budget reservations.
3. Optional pinned GPT-4o-mini produces short attributed English/Thai digests.
4. `build_sdp_dashboard --news-store` / `refresh_dashboard --news-store` reads the
   retained store and adds `sdp/news_feed.json` to the existing immutable generation.
5. The existing R2 publisher verifies its receipt hash, public schema and sanitizer;
   the client resolves it from the same pinned generation as other dashboard data.
6. `#news` displays the full feed; Summary displays the latest three. Optional news
   failure leaves football data usable. No provider call originates in the browser.

The page includes language, club, category and text filters; reset; attribution;
source and capture times; translation-pending and missing-data states; source
coverage; LINE/Facebook/native sharing and copy links. Shared links contain only a
public story identity and language, never a Manager ID or current private URL.
Old story links explicitly report when their version is no longer in the current
bounded feed. There is no permanent article archive or social preview-image service.

## Correctness and scope

- FPL player identity uses the retained season registry's permanent `code`; exact
  team codes are retained. Assistant managers are excluded. X mentions never become
  player IDs through names. Optional X club identity must be explicitly configured.
- Source publication, first knowledge, source capture and summary generation are
  distinct. An unchanged observation preserves its original time; A→B→A creates
  a new observation. The identical A summary may be reused with its original time.
- A cleared FPL news field creates a clearing record; it does not leave a stale
  injury headline. Importing an older snapshot cannot move state backwards.
  A rejected batch rolls back entirely.
- FPL `news_added` is the FPL update time, not an inferred club article publication.
  Importing retained data or translating it does not claim a new source capture.
- FPL news is an existing official status/news excerpt, not complete press-conference
  coverage. No full club/media articles are scraped. X is selected-source coverage,
  one page per account, with truncation reported; this is not an exhaustive archive.
- News prose is a separate owner-requested source digest, not the numerical
  insight renderer. GPT receives only bounded public source text, name and source
  publication time. It receives no forecasts, manager squad, bank, plans or notes.
  The prompt preserves uncertainty and attribution, prohibits invented facts,
  predicted lineups, probabilities and recommendations. Structured validation is
  not proof of factual fidelity: a small live bilingual quality check remains due.
- News cannot change availability, prices, xP, PMFs, model inputs, optimizer inputs
  or monitoring. Models, scientific artifacts and retained forecasts are unchanged.
- Raw X posts stay private; only validated digests with source permalinks enter the
  feed. Withdrawal of source reuse approval suppresses cached digests in subsequent
  exports. Account removal alone is not a deletion workflow: retain its config
  entry with `reuse_approved: false` to record withdrawal, then republish.
- X historical edits/deletions are not reconciled by this bounded recent-search
  adapter. Review source/API reuse, display and deletion obligations before enabling
  an account. `reuse_approved` records that review; it is not a license by itself.

## Cost and secret boundary

`config/public_news.yaml` defaults to `enabled: false`, no X accounts. Credentials
are process environment variables `X_BEARER_TOKEN` and `OPENAI_API_KEY`, never
configuration values, `VITE_*`, public JSON, logs or Git. Do not paste keys in chat.

The pinned adapter uses `gpt-4o-mini-2024-07-18`, Responses structured output,
`store: false`, no tools and at most 900 output tokens. This disables response
application storage; it is not a promise about all provider retention.

Local UTC-month ceilings are $3 for X and $0.50 for GPT. Every attempt reserves a
worst-case amount transactionally before the request, including retries. No refund
is inferred after ambiguous failures. At 10 maximum posts, X reserves $0.05 per
attempt even for an empty result, so $3 allows **at most 60 attempts**, not guaranteed
600 stories or continuous two-hour coverage across many accounts. GPT reserves a
UTF-8 input upper bound plus fixed overhead/output allowance. The ledger must not
be replaced to reset the cap; it only controls this job, not other account usage.
No automatic top-up, alternate paid source or paid-model fallback exists.

Pricing assumptions checked against official documentation on 2026-09-19:
[X pricing](https://docs.x.com/x-api/getting-started/pricing),
[GPT-4o-mini](https://developers.openai.com/api/docs/models/gpt-4o-mini),
[structured output](https://developers.openai.com/api/docs/guides/structured-outputs).
Recheck prices and permitted use before activation.

## Commands and activation boundary

From this worktree, offline development requires no key:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
$python = 'D:/Personal/fpl-operations/.venv/Scripts/python.exe'
& $python -m fpl.jobs.capture_public_news `
  --config config/public_news.yaml `
  --store data/news/news.sqlite3 `
  --output data/news/capture-unique-id.json
```

The disabled run writes an honest disabled receipt. Each output path is write-once.
To import existing official evidence without network access, additionally pass
`--fpl-snapshot <retained-snapshot-directory> --season 2026-27`; use the manifest's
actual season and keep `enabled: false`. Its original snapshot must pass checksums.
The private store must stay outside any dashboard/public/dist directory.

Once keys are available, review a small source allowlist and reuse permissions,
configure lower budgets if desired, then explicitly enable capture for a bounded
live quality/transport check. FPL-only translation does not require an X key.
Only afterwards wire this optional capture ahead of the established refresh and
pass `--news-store <private-store>` to that existing refresh. There is no second
scheduler. This delivery deliberately leaves the current two-hour task unchanged.
News failure must never prevent its existing FPL/SDP refresh.

The public-sidecar publisher never uploads the SQLite store, raw posts, credentials
or private receipts. A `demo: true` feed is rejected by R2 before any upload.

## Verification record

- 129 focused Python tests: capture, publisher, dashboard generation, refresh and R2.
- 208 broader regressions: public sanitizer, availability, rest, scouting/forecast
  isolation, SDP primary/fallback and deterministic insights; all pass (PuLP warnings).
- 91 frontend checks: parser, cards, sharing, same-generation resolver, Sidebar,
  App and Summary. TypeScript/worker TypeScript, Vite build and scoped oxlint pass.
- Full repository gate completed once in 18m30s: **4,515 passed, 156 skipped,
  64 failed, 22 errors**. Failures include Windows symlink privilege `WinError 1314`,
  old frozen byte/hash pins (including checkout EOL differences), duplicate model
  discovery assumptions and an untouched adapter fixture missing
  `stg_live_team_version`. No new-news test failed. These broader failures were
  not repaired or all independently rerun on a pristine baseline in this delivery;
  the full suite is not claimed green. Local log:
  `data/artifacts/public-news-20260919/full-pytest.txt`.
- Strict mypy passes 247 source files; global `ruff check src tests` and changed
  Python formatting pass. Global formatting still reports 10 untouched legacy files
  in insights/publication and their tests; no unrelated reformat was performed.
- 184 tracked protected files (models, features, optimizer, configs, artifacts and
  AGENTS) match start-commit Git content. Operational frozen-file pins: 167/167
  byte-identical; retained forecast pins: 10/10 byte-identical. New worktree EOL
  conversion was accounted for separately, not mistaken for a model change.
- Disabled capture CLI executed: `network_enabled=false`, one disabled X status;
  sanitized empty feed emitted successfully. No paid calls or live summaries tested.
- Browser interactions on `http://127.0.0.1:4176/#news`: category/club filtering,
  text search, empty state, reset, Thai/English, translation-pending, source coverage
  and disabled demo sharing verified. Console warnings/errors: none observed.
- Screenshot capture is **blocked**, not passed: both `tab.screenshot` and
  `cua`'s `getScreenshot` timed out at `CDP Page.captureScreenshot` (5000 ms).
  Viewport set to 390×844 returned successfully but DOM remained 1280 px wide;
  mobile visual verification therefore remains unverified. Override was reset.
  No fabricated screenshot is supplied. Share transport is covered by offline tests;
  no real social post was sent.

The local preview uses three explicitly synthetic stories and cannot be published.
It is accessible on the owner's computer only while the preview process is running.
Production remains unchanged until a later reviewed activation/publication.

Implementation commit: `1d3390e`. Automatic approval review rejected a normal push
to `origin/codex/public-news`, including after checking the owner-named GitHub
remote and the code-only file list. No workaround was attempted. Local commits
are retained; pushing this branch awaits the owner's explicit confirmation.
