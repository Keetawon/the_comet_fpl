# Match previews: R3-A development

This local-only first slice adds **Fixtures → Match previews**. It presents a GW
overview and individual matches using already published team forecasts, alongside
separately dated observed form, witnessed midweek football and attributed news.
It does not implement R3-B, create forecasts, change a component, or activate AI.

## Forecast and identity contract

The selected forecast vintage is authoritative. Two reciprocal directed rows from
`fixture_matrix.json` must agree on run, season, fixture, GW, kickoff and forecast
cutoff, with opposite home/away sides and permanent club codes. Duplicate or
inconsistent fixtures are excluded with a reason. DGW legs remain separate.
Missing values remain unavailable; observed/model zero is shown as zero only when
actually published. Inputs are not mutated.

Only direct published expected goals and clean-sheet probabilities are displayed.
Expected goals are forecast means, not observed xG and not a predicted scoreline.
No W/D/L, correct-score, BTTS or over/under probabilities are reconstructed in the
browser. No team or player ranks are fed back into any model or optimizer.
The existing All competitions / Weekly / 10 GWs default remains unchanged.
The preview defaults to the first actual GW key in the selected forecast and labels
every GW as recorded. `summary.next_gameweek` is forecast-anchored, not verified
live gameweek state, so it is deliberately not used to claim a GW is upcoming.

## Independently timed context

- **Form:** published FPL observed form in the selected season, with actual match
  counts, provisional count and separate xG/xGC measurement denominators. Legacy
  archive forms are not presented as current form. This is latest-at-export
  context; it may be newer than the selected forecast cutoff.
- **Rest:** only the exact next fixture, GW, venue, kickoff, club and stable player
  code may match an R1 report. Another DGW leg cannot reuse that report. A future
  report or a next fixture that has started is not current pre-match rest evidence.
  Unknown stays unknown; missing rows do not imply rest or fitness. Nominal SDP
  workload minutes are not FPL minutes. Kickoff gaps are not recovery estimates.
- **News:** exact season and explicitly linked club, plus exact stable player/club
  membership for player-specific news. Unmapped stories remain on News. A story
  is related club news, not an assertion about a fixture or its starting XI. Thai
  uses the published translation; missing translation shows English with a label.
  Feed generation and first-known timestamps remain separate from forecast time.

All consumers use the existing pinned-generation public resolver, never DuckDB.
Missing optional player/rest/news files leave the team forecast view usable. No
manager ID, private squad, bank or plan data participates in this view.

## AI boundary

This slice works without an API key or a provider call. It is labelled as a
deterministic preview, not AI analysis. R2's source-digest prose is attributed news;
it does not become a canonical forecast claim.

The existing insight service allows server-built facts and provider-selected fact
IDs only. Its scope cannot identify a single fixture, and its source allowlist
does not cover the independent R1/R2 sidecars. Calling it with a broad Fixtures
selector would misrepresent the visible match. Optional match-specific rendering
therefore remains unimplemented until an exact-fixture, hash-bound evidence
contract exists. No parallel service, provider adapter or dependency was added.

## Local review

The implementation is isolated in `.worktrees/match_preview`, branch
`codex/match-preview`, based on local public-news commit
`97ceb025105d5a503d9ec417a5d825dfd4bd8092`. Main, the operational worktree,
scheduler, retained predictions and the live website are not changed.

Open `http://127.0.0.1:4177/#fixtures` on this computer, then select **Match previews**.
The running preview uses explicitly synthetic DEMO clubs, fixtures, news and rest
records. It is local UI evidence, not a newly generated football forecast. No live
or private operational data was copied into this preview. The built preview process
is 12072 at delivery; it uses loopback only. No server startup registration changed.

If the preview stops, from this worktree's `dashboard` directory:

```powershell
node node_modules/vite/bin/vite.js preview --configLoader runner --host 127.0.0.1 --port 4177 --strictPort
```

The ignored synthetic setup and screenshots are under
`data/artifacts/match-preview-20260919/`. They are not committed or publishable
source evidence. Real deployment would consume the ordinary published generation;
missing optional sidecars show explicit unavailable states. This delivery neither
publishes the build nor activates the R2 capture.

## Verification record

- 105 frontend tests across seven files pass: preview joins/component, Fixture
  Matrix integration, existing insight panel, R1 rest, pinned public resolver and
  R2 news. Includes DGW separation, duplicate/transfer identity, future/stale report
  rejection, no mutation, nulls, reset, bilingual fallback and no AI requests.
- 135 Python regressions pass: insights, rest summary and public news publication.
  No Python source or test was changed in this delivery.
- Strict mypy passes all 247 source files; global Ruff passes. Global Ruff format
  still flags the same 10 untouched legacy files recorded by the preceding R2
  delivery. No unrelated formatting was applied.
- App, Node-config and Worker TypeScript checks, changed-file oxlint and static
  Vite build pass. The linked dependency directory blocks writing incremental
  `.tsbuildinfo` and default Vite configuration temp files in this sandbox; checks
  used `--incremental false` and `--configLoader runner`, respectively, without
  weakening type checks or changing runtime code. The initial dev server's linked
  font path was outside Vite's serving allowlist; the final static build correctly
  bundles that font and is the preview left running.
- Browser: actual desktop screenshot saved as `desktop.png`; GW/club selection,
  reset, separate DGW legs, missing quantities/form, rest evidence, English/Thai
  and distinct source times verified on the rendered static build. Console
  warnings/errors: none observed after reload. Desktop width/scroll width both
  1646 px; mobile viewport and scroll width both 390 px, and mobile controls work.
  Mobile screenshot capture remains blocked by a 5000 ms
  `Page.captureScreenshot` timeout, so mobile visual QA is not claimed complete.
  The viewport override was reset. Desktop capture succeeds via `cua.getScreenshot`;
  the separate `tab.screenshot` path timed out.
- Review caught and repaired a forecast-start GW being called upcoming and silently
  hidden rejected news joins. All preview GWs are now explicitly recorded forecast
  GWs, and an expandable list explains rejected linked news.
- Operational frozen pins: 167/167 files unchanged; retained forecasts: 10/10
  unchanged. Git content under `src/`, `config/`, `results/` and `AGENTS.md` is
  unchanged from `97ceb02`. Main and the operational branch remain at their
  previous commits; existing owner scratch/manual-note work is preserved.

The preceding R2 full pytest gate at this exact unchanged Python base recorded
4,515 passed, 156 skipped, 64 failed and 22 errors, including Windows symlink
privileges and stale provenance pins. It was not repeated for this frontend-only
slice; this report does not claim a green full repository suite. See
`docs/public-news-development-2026-09-19.md` for its retained log and limitations.

Work remains local per the owner's instruction. No push, merge, deployment,
provider request, model fitting or historical evaluation occurred.
