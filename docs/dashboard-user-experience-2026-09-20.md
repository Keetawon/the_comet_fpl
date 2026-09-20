# Player-facing dashboard refresh

## Owner follow-up: whole-number goal summary (2026-09-20)

The read-only shared text now formats the existing published goal averages as
`ALP 2–1 BET`, labelled **Rounded goal averages** / **ปัดค่าเฉลี่ยประตู**.
Each value is rounded directly to the nearest integer, with 0.5 rounded up.
Missing, nonfinite or negative values remain `—`; measured zero stays zero.
The copied text explains that these are rounded means, not exact-score picks or
win probabilities. Match-card decimals, observed xG/xGA/SOT precision, source dates,
copy/share behavior and all underlying forecast data remain unchanged. This narrow
owner-authorized display change supersedes the earlier textbox precision only.

Local UI work from `5b9400796817b54d0f86ef112d952003101b93b3` on
`codex/match-preview`. The owner requested Score Prediction, read-only social text,
a clearer News feed and a more useful Summary. No push, merge, deployment, live
ingestion, provider activation, forecast regeneration or model research is included.

## Score Prediction

- Sidebar uses the requested name; existing `#gw-analysis` links still work.
- Match cards show direct published expected-goal means and team clean-sheet
  probabilities, home/away, kickoff and selected GW. Three compact highlights show
  fixture coverage and the leading published goal/clean-sheet values in that view.
- Means are explicitly not integer score picks. No approved exact-score editorial
  article is currently connected. The owner's sample was a style example, not
  validated forecasts; it is not published as real evidence.
- The Thai/English analysis textbox is read-only. Copy, device Share, LINE,
  copy-for-Facebook and UTF-8 text download use exactly the displayed text. Readers
  edit the copy in their own app. The old editor, reason and review controls are
  removed; no browser edits or manager information are stored or sent to a provider.
- Existing deterministic briefing composition and source/coverage boundaries stay
  unchanged. Optional statistics must finish loading before the shared text is
  exposed. If unavailable, a facts-only briefing remains with the limitation.
  DEMO forecast identity independently labels the copied text even without SDP.
- Forecast date stays visible. Full identifiers, vintage selection and methodology
  remain available in Sources & how to read this. Observed captures may be newer
  than a forecast; the text retains that distinction.

## News and Summary

News uses chronological, attributed cards with Thai/English, search, club filters,
topic counts and reset. Headline, summary, source and publication date remain close
together. Topic colours describe categories, not estimated severity. Source coverage
and unavailable translation remain explicit. DEMO stories cannot be shared as news.
Provider setup and AI model identifiers live in expandable source details.

Summary puts current FPL availability before the unchanged raw-xP Top 15, with
observed midweek participation alongside. It provides direct links to Players,
Score Prediction and News, readable fixture-watch sections and three latest stories.
Kickoff is not relabelled as an official deadline. Local optimizer scenarios are
collapsed and keep their own dates; hosted access rules do not change.

## Whole-dashboard content review

| Surface | Treatment |
| --- | --- |
| Sidebar | Replace static-JSON/DuckDB explanation with a short user-facing footer. |
| Shared insight panel | Hide the unusable hosted AI button; retain facts, put long caveats/provider identity in details. No hosted provider call. |
| Players | Remove redundant technical table explanation and hidden analytics link; retain selected observed range, prices, availability and forecast context. |
| Fixture matrix | Shorter form intro; detailed aggregation contract remains expandable. Preserve dates, counts and provisional labels. |
| Player/team prediction vs actual | Keep selected comparison role, cutoff, scored coverage and development boundary visible; move component modes/full record IDs into details. Scoring unchanged. |
| Squad Draft | Short what-if description; forecast date and import limitations stay visible. Rules provenance is expandable. No import or draft arithmetic change. |
| Team SDP statistics | Existing expandable methodology is appropriate. Keep SDP/FPL/correction source labels and measured coverage, not cosmetic completeness. |
| Competition calendar | Keep cup dates, international windows, rest limitations and existing expandable provenance. |
| Hidden deep analytics | Keep exact selected scope/probability meaning/cold-start limitations; do not re-enable routes. |
| Local Next GW / Plan Builder | Plan dates, frozen price scope, constraints and scenario distinctions are useful, so retained. |
| Optimizer audit | Technical diagnostics are the purpose of this local page; retained. |

No model, PMF, xP, price, availability calculation, optimizer input, news capture,
public-export sanitizer, numeric insight contract or source data was changed.
The review relocates unnecessary implementation detail; it does not erase evidence
needed to understand the displayed values.

## Verification and local review

Preview: `http://127.0.0.1:4177/#gw-analysis` (this computer only). It deliberately
uses synthetic DEMO clubs, fixtures, news and workload for UI testing, not a current
football report. The existing Vite preview server serves the local hosted-static
build. No public site was updated.

Chrome visual checks covered desktop and 390×844 mobile for all three pages,
Score Prediction dark contrast, read-only text, Thai/English, GW change with both
DGW legs, missing goal/CS values, Copy and Facebook copy-first feedback, News topic
empty/reset, source details and navigation. No social post was sent. Device-native
share sheets are covered by unit tests, not a real mobile-device posting test.
No page-wide horizontal overflow was observed at 390 px; the wide Top 15 table
retains its intentional internal horizontal scroll.

Screenshots are local ignored review artifacts in
`data/artifacts/match-preview-20260919/`:

- `score-prediction-desktop.png`, `score-prediction-mobile.png`
- `score-prediction-briefing.png`, `score-prediction-briefing-mobile.png`
- `score-prediction-dark.png`
- `news-desktop.png`, `news-mobile.png`
- `summary-desktop.png`, `summary-mobile.png`

One dynamic-chunk error occurred when rebuilding underneath an already open preview.
Reloading the completed build restored the page; subsequent inspected navigation
and console had no new errors. This does not claim a production deployment test.

Application/Node/Worker TypeScript checks, changed-file oxlint, hosted build and
`git diff --check` pass. The first broad frontend run passed 723 tests and had one
5-second manager-filter timeout under parallel load; that test passed separately
without modification. Final run with `--maxWorkers=2`: **726 tests passed in
71 files**, without changing a timeout or skipping tests.

Frozen verification: **167 source/config/result hashes and 10 stored forecast hashes
match** the operational recovery receipts from 2026-09-18. `src/fpl`, `config`,
`results` and `AGENTS.md` have no change against the starting commit. The operational
worktree stays clean; unrelated owner files and other worktrees are preserved.
