# Local News page simulation — 2026-09-21

Owner-requested visual preview of the proposed FFScout press-conference feed.
This implements no capture schedule, paid request, automated team identification,
source approval or news publication. The example date, six club timetable rows
and three bilingual stories are explicitly invented. No player is identified.

Open the Vite development server at:
`http://127.0.0.1:4177/#news?preview=press-conferences&lang=th`.
This is local to the owner computer, not a public or phone-accessible URL.
The normal `#news` route still reads the published feed.

The preview reuses the News page's filters, language controls, cards and themes.
The compact timetable distinguishes a received recap, an awaited recap and a
scheduled conference. It supports UK/Thai times and collapse/expand. Club filters
apply to both the timetable and stories, including clubs with no recap yet.
On mobile, stories precede the timetable. No update implies no fitness conclusion.

Every page and story labels the simulation. Source and sharing links are disabled
for synthetic stories, so the invented source record URLs cannot be followed or
shared. The preview is dynamically imported only behind `import.meta.env.DEV`;
its synthetic data is absent from production JavaScript and public JSON exports.
The browser does not load the real news feed in this mode or contact X/GPT.
Real news storage, public data, models and frozen forecasts remain unchanged.

## All-team roundup

The top read-only text box consolidates every club in the sample into one bilingual
message. News-card filters never narrow the roundup. Clubs without a recap are
listed explicitly; lack of news is not a fitness conclusion. Copy copies the whole
message, including its synthetic-news label. Clipboard denial selects the text for
manual copying. External sharing remains disabled for this invented news.

The timing selector demonstrates three fixed scenarios: collecting, all conferences
finished, and exactly three hours before the example deadline. The earlier qualifying
trigger releases the message. Conference completion is explicit sample evidence;
passing a timetable START time never establishes completion. Stories and translations
known after the selected edition are excluded. Recap coverage can remain partial
even after all conferences finish. The example covers six clubs, not all 20 PL clubs.

This is an executable UI simulation, not an activated automatic publication job.
Real release orchestration still needs the retained official deadline, the complete
expected conference list and explicit completion evidence, plus source-approved
summaries in the published generation. No such evidence is fabricated by the UI.

## Verification

- 46 offline News tests pass, including nine simulation integration tests.
- TypeScript and production build pass; no fixture markers in production assets.
- Targeted Oxlint and Git whitespace check pass.
- Actual Chrome verification: desktop and 390 × 844 mobile; Thai/English;
  pending-club filter, reset, UK/Thai timetable conversion, light/dark themes.
- Roundup follow-up: desktop/mobile rendering, collecting and T-minus-three-hour
  states, and visible copy-success feedback checked in Chrome. Exact copied payload
  and clipboard-denied selection fallback are covered by the offline tests.
- Mobile document width 390, main client/scroll width 375: no page overflow.
- Screenshots were captured in the review session. Final browser console contained
  no errors/warnings after resolving a preview-only shared-font path restriction.

This machine uses shared worktree `node_modules`. The local preview's ignored
`data/artifacts/news-preview-2026-09-21/vite.preview.config.mjs` narrowly allows
that font directory's real path. It changes no production Vite configuration.
Tests/build need access to the existing shared Vite/TypeScript caches; the initial
sandbox-denied cache writes were environmental, not test failures.

News collection/publication and social sharing of real summaries remain separate
from this local design review. No push or deployment was performed.
