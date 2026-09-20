# Standalone GW Analysis: social text

The owner clarified that R3-A should deliver a shareable text post for a whole GW,
not more fixture cards inside the calendar. This supersedes the first UI at
`815cdcc`. **Fixture Matrix and All competitions are restored to their previous
layout.** The separate `#gw-analysis` route appears as **GW Analysis** in the menu.

The main output is a Thai/English text draft. Select the recorded forecast and
one of its exact published GW keys, then copy the whole text, open native sharing,
send it to LINE, prepare it for pasting on Facebook, or download UTF-8 `.txt`.
There is no automatic social post or provider request. Facebook does not reliably
support prefilled user post text: the UI explicitly copies the text and offers a
separate share link with a paste instruction. Long LINE URLs use copy/native
sharing instead of truncating a post.

## What can appear in the automatic draft

- Direct expected-goal means from the existing reciprocal team-fixture forecast.
  They are labelled as means, not integer scoreline picks.
- Observed SDP context from the same season, strictly earlier GWs and kickoffs
  before the earliest target fixture. Each metric carries its measured fixture
  denominator and its source. Missing data remains missing.
- The recorded forecast cutoff and observed-stat capture/export time separately.
  Later corrections or captures never become historically known forecast inputs.
- Actual fixture coverage. A complete GW claim requires the exact expected fixture
  identities; an absent schedule or excluded forecast side cannot imply ten games.

The owner's sample post is a style example, not validated GW5 evidence. It is not
loaded as a real forecast. The published browser contract contains no correct-score
or match-winner distribution, so the automatic draft never turns means into 2–2
picks or describes a winner as most confident. No confidence statistic is
reconstructed from lambdas or clean-sheet probabilities.

The established display corrections/assumptions/FPL supplements remain unchanged
in the SDP dashboard. In this first social composer, any metric depending on one
of those overrides is omitted with an explicit shared-text explanation. This keeps
an owner-confirmed display zero from being described as a raw provider measurement.

## Editorial separation

The optional editor modifies only a browser-memory copy of the draft. An edit
requires a reason and explicit owner review before sharing. It carries the actual
edit timestamp, review disclosure and an editorial disclaimer in the shared text.
Any text or reason change revokes the review. Proposed integer scorelines belong
only in this separately labelled editorial copy; they do not become model output.
The footer retains the selected forecast record/cutoff, season/GW and statistics
publication date even when the owner replaces the entire body. A changed source
context also requires a fresh review. Reset restores the current published draft.
Reset or changing language/GW/vintage
discards those edits visibly; nothing is persisted to model storage, a public
sidecar, or browser storage. Download/copy can retain the disclosed draft for the
owner. No numerical forecast, availability, optimizer or monitoring value changes.

AI editorial generation is not connected. The page is useful without an API key,
but it is not advertised as an AI-authored score prediction. R3-B research remains
out of scope. The existing numerical insight service and its fact-ID boundary are
not weakened to manufacture narrative or probabilities.

## Delivery record

- Starting commit: `815cdcc87dcfc06a641918da4a2e4f62f523b540`, branch
  `codex/match-preview`. No push, merge or deployment.
- Focused frontend verification: **120 tests passed in 8 files**, covering the
  composer, sharing, page/editor, navigation, restored Fixtures and SDP helpers.
  Application, Node and Worker TypeScript checks pass; changed-file oxlint and
  the hosted static build pass. No new dependency or Python change.
- Broader frontend run: **719 passed, 1 failed**. The unchanged
  `NextGwPage.test.tsx:138` still expects two `Players to watch` headings after
  the earlier Summary Top-15 change (`da655b8`). Neither that test nor Summary
  implementation was modified here. This stale assertion is not repaired as
  part of this UI correction. A completely green full suite is not claimed.
- Chrome preview at `http://127.0.0.1:4177/#gw-analysis` uses **synthetic DEMO
  fixtures/statistics only**, explicitly labelled in the copied text. Browser
  interactions verified Thai/English, GW5/GW6 with both DGW legs, NULL display,
  edit reason/review gating, revoked review on change, reset, and Facebook copy
  feedback without posting. Fixtures still defaults to All competitions/Weekly.
- At a 390 px mobile viewport, rendered DOM width and document scroll width both
  equal 390 px. The temporary override was reset. This is a DOM/layout check,
  not screenshot-based visual acceptance. Both `getScreenshot()` and
  `getAXStateAndScreenshot()` failed with `Timed out after 5000ms waiting for CDP
  command Page.captureScreenshot`; no new screenshot is claimed or substituted
  with the obsolete embedded-card image. No new console errors occurred after
  the required reload; one stale asset error from the previous build cleared on
  reload. External social posting and native device share sheets were not used.
- **167 frozen source/config/result hashes and 10 forecast artifact hashes**
  still match the operational recovery receipts. Production checkout is clean;
  root owner scratch files are preserved. Model, optimizer, forecast generation,
  public publication and database content remain unchanged.

The local preview URL is accessible only on this machine while its existing
Vite preview process runs. It is not a public deployment or live football report.
