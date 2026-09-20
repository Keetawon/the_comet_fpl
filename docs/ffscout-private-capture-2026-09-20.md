# FFScout-only private capture check

The owner funded X and authorized testing only `@FFScout`, without importing
Official FPL news again. No scheduler, public deployment, GPT call, forecast or
model change was authorized or performed in this check.

## Source configuration

`config/public_news.yaml` now selects only `ffscout_team_news_v1`, handle
`FFScout`, topic `team_news`. Automatic capture remains disabled and public reuse
is not marked approved. Credentials remain in the owner-only operations folder,
never the repository. No FPL snapshot argument is supplied.

The optional fixed topic appends account-scoped search terms for team news,
manager briefings, injuries, training, suspensions, lineups and transfers. It is
a collection filter, not a player-identity resolver, forecast or classifier.
There is no arbitrary query input. The default `all` query and its retained raw
source representation remain unchanged. Changing topic requires a new source ID
so a cursor from a broader query cannot skip previously unseen news.

## Private execution

Two one-page checks used the same append-only operations news store. Each allowed
10 posts, disabled summaries, set the OpenAI cap to zero, and shared a $0.10 X
reservation ceiling. The private configuration's source gate was reviewed only
for local transport inspection; it is not permission to publish or send text to
an LLM. Neither test configuration is connected to a scheduler or publisher.

- `ffscout-transport-20260920T160623Z`: the unfiltered account request returned
  10 posts, all live goal/assist/DC updates, demonstrating why account selection
  alone does not meet the owner's team-news objective.
- `ffscout-team-news-20260920T161150Z`: the scoped request returned 10 posts,
  including club fitness updates and press-conference links. Promotional video
  and guide links are still present; this is not an exclusively substantive feed.
- Both reported `ok` and `truncated: true`. One page is deliberately incomplete.
  There was no retry, pagination or additional paid request. Two attempts reserved
  $0.10 total; this is a local upper-bound reservation, not a verified X invoice.
- All retained raw hashes, post IDs and publication/capture ordering reconcile.
  Previous rows remain byte-identical. No FPL rows, inferred player IDs, summaries
  or OpenAI reservations were created. SQLite integrity passes.
- The selected news includes posts published September 18–20 but first captured
  September 20. This does not establish historical pre-deadline availability.

Private receipts/configs and `news.sqlite3` are in
`D:/Personal/fpl-operations/news/`. Receipt SHA256 values:

```text
transport: 8e71e1c337baa2322387eaf908523e797bb10e902aaac59d401d641d708ae4e7
team news: 3a9039c1fbcb88019ea912cbb0bb4b1049c1765eeedac825952fa832c08a3c6f
```

## Remaining activation boundary

Public source-reuse review, correction/deletion reconciliation, bilingual quality
review and scheduler/publication wiring are not completed by a successful API
test. The existing recent-search cursor does not backfill truncated history or
recheck older edited/deleted posts. The feed must not claim complete coverage.
Raw posts and credentials stay private. No paid capture should be repeated just
to reproduce this report, and the existing ledger must never be reset for budget.

## Verification

78 offline capture, dotenv and publisher tests pass. Focused tests check account
scope, keyword-query length, unsupported topics, default raw-byte compatibility,
separate cursors, unchanged FPL evidence and no GPT calls when summaries are off.
Ruff, changed-file formatting and strict mypy for the capture module pass.
Changes are confined to optional news ingestion/configuration/tests/documentation.
