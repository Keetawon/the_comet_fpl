# Immediate reviewed news and FFScout coverage repair

The owner superseded the five-hour roundup rule: every reviewed published update
must be visible immediately, without waiting for the deadline or all conferences.
This change affects reporting only, with no model, forecast or optimizer changes.

## Coverage

The [linked FFScout post](https://x.com/FFScout/status/2108468585559384365)
is Friday's timetable for 15 managers, not evidence that every conference finished.
The complete bounded capture at **2026-10-09 17:57:21 UTC** contains 44 posts over
48 hours, including individual reports for all **20 clubs**: 15 on Friday and
five on Thursday. Duplicate Sunderland and Everton posts were retained privately;
the later report for each club was selected for this edition. Promotions, the
timetables and the repeated short Haaland headline were not published as extra
club reports. Coverage here means reports captured, not independent confirmation
of conference completion or each player's fitness.

Missing reports were caused by three capture limits: only ten search results,
ignored pagination and shortened `text` instead of long-form `note_tweet.text`.
The old keyword query also excluded some reports without fitness keywords.
Man City's short post had been captured, but its draft failed factual review;
Brighton was outside the ten-post batch.

Capture now requests full text and follows bounded pagination. The configured
FFScout source uses an overlapping 48-hour window, at most two pages of 50 posts,
and a fixed end time. This repairs coverage behind an already-advanced cursor.
An incomplete page/window commits no observations and advances no cursor. Cost
reservations and the existing monthly caps remain enforced. The new query has
the explicit source identity `ffscout_press_conferences_v2`; the previous source
is withdrawn from publication, with its evidence preserved.

Twenty GPT drafts were retained. Several still inferred unsupported availability,
completed a broken sentence, or mistranslated names. The published revisions were
written and checked against the complete captured posts by Codex in EN and TH.
Their provenance is `Codex-source-reviewed-editorial`, with a retained editorial
instruction hash and exact append-only review receipts. This is agent review,
not independent human verification or the original GPT-4o-mini output. No raw X
posts, private store, prompts or credentials were uploaded.

Publication at **2026-10-09 18:08:03 UTC / October 10 01:08 Bangkok** contains
20 source-linked club summaries, including
[Brighton](https://x.com/FFScout/status/2108498273572958546),
[Man City](https://x.com/FFScout/status/2108499056695656710) and
[Aston Villa](https://x.com/FFScout/status/2108557134216499679).
The independently verified HTTPS body hash is
`4e931b50fe1766d69d690f971d3f901b9559d6e1b5dbc137b0b1d763c52e40d8`.
The forecast pointer remains
`29b2ce3ae80633d2fb958ad8903267e4f8b817a4d30c07d6305830ea851f28b8`.

## Display and automation

The production roundup and local preview show updates immediately. Deadline
metadata is context only; an old edition gets an age warning rather than being
hidden at 24 hours or at the deadline. The existing seven-day X expiry still
applies. Schema-v2 `opens_at` remains validated as legacy transport metadata for
existing editions, but it no longer controls display. A schema-v1 feed without
deadline metadata can also populate the roundup. Source timestamps and links
remain visible on the individual cards.

The page reloads the independent news feed every 15 minutes. Fresh loads see the
latest publication immediately. This is not a new unattended X schedule: capture
and exact summary review remain required before publication. Official FPL's
hourly cloud refresh is a separate service. The checked-in capture profile stays
disabled until explicitly configured with private credentials and source approval.

## Operations storage audit (read-only)

`D:\Personal\fpl-operations` occupied **68.367 GiB** at the initial inventory.
An SDP cycle started during this work; do not treat that inventory as its final
size or remove active cycle files. No operations files were deleted in this audit.

The following abandoned temporary files total **486,438,833 bytes (0.453 GiB)**:

| Path relative to `fpl-operations` | Bytes | Evidence |
| --- | ---: | --- |
| `dashboard-runs/dashboard-20260922T080009Z-6e0f3c19/recovery.duckdb.gz.tmp-48a0185fd9a042eebfdf4e472b3679fe` | 480,495,653 | Complete archive and receipt exist. Re-read archive hash and decompressed source hash both match. Keep both archive and receipt. |
| `dashboard-runs/dashboard-20260922T100004Z-b6ae3459/generation/.dashboard-public-data.zip.zchsos_q.tmp` | 5,943,180 | Abandoned packaging temporary; original process is absent and interrupted-cycle review is retained. |
| `dashboard-runs/dashboard-20261006T100008Z-2fb0b6f8/generation/.dashboard-public-data.zip.z9ju3smp.tmp` | 0 | Same interrupted-cycle evidence; empty packaging temporary. |

Three older partial derived `generation` directories (September 22, October 6
and October 7) total about **1.389 GiB**, including the ZIP temporary above.
These are further cleanup candidates, not yet approved by a completed reference
and replay audit. Do not double-count the ZIP temporary or delete their parent
run directories. Two legacy uncompressed `runs/*/before.duckdb` copies total
about 2.64 GiB; consider verified compression, not deletion, after checking pins.

Keep the active `data` databases, the two latest uncompressed recovery and forecast
replay copies, published artifacts, raw snapshots and compressed evidence. In
particular, the roughly 17.90 GiB of compressed recovery copies and 9.31 GiB
`verification` directory are not disposable caches. Existing scientific/replay
pins and the documented September 17 storage incident still apply.

The private inventory is under
`data/artifacts/news-production-20261009/operations-inventory.json` in the root
workspace. Archive verification reproduced source SHA-256
`4cef6a625e4750915a628a44d28f79b5eacafff330de20da53febae4a850db6e`
from the retained September 22 gzip before classifying its abandoned temporary.

## Validation

- Focused Python capture/store/publication suite: **69 passed**.
- Dashboard suite: **795 passed**; build and lint passed (existing lint warnings).
- Repository Ruff passed; strict mypy passed all 244 source files. Both changed
  Python files pass formatting; ten unrelated existing global format failures remain.
- An initial full Python attempt hit access denied in Windows' default temporary
  directory. It was stopped and restarted with a writable workspace temp root.
  The completed run gives **4,383 passed, 156 skipped, 64 failed and 22 errors**
  in 861.90 seconds. Comparing failing test IDs with the earlier October 9 run
  finds **no new failing cases and no news failures**. The broader gate remains
  non-green; frozen reference and Windows failures were not reinterpreted or
  repaired as part of this reporting change. Logs are in
  `data/artifacts/news-production-20261009/pytest-coverage-workspace-full.log`.
- Commit `e9a1b7b` was pushed to `origin/main`. Pages deployment
  [37971781604](https://github.com/Keetawon/the_comet_fpl/actions/runs/37971781604)
  completed successfully at **2026-10-09 18:17:38 UTC**. The live browser showed
  20 stories, including Brighton, Man City and Aston Villa, and an open roundup
  in both EN and TH before the former five-hour boundary. No five-hour opening
  message remains. The production news tab was left open in Thai.
- The exact temporary-file audit and deployment verification are retained in
  `operations-cleanup-candidates.json` and `coverage-release-verification.json`
  beside the test logs. No operations files were removed. Older partial exports
  include interrupted cycles that automatic retention intentionally skips.

All raw and generated news evidence remains in the private operations news store.
The protected SDP and local-news-notes worktrees were not edited.
