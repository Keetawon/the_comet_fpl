# Dashboard publication, 2026-09-20

The owner authorized commit, push and production publication after reviewing the
new desktop/mobile themes and real-data preview. This supersedes the local-only
delivery status in the earlier UI reports; it does not activate news providers.

## Release boundary

Source work is preserved on `codex/match-preview` at
`ec20bbf`. The production branch starts at current main `0ba6d86` and applies only
the reviewed dashboard patch and its documentation. The original branch also
contains operational retention, recovery, rest and disabled news backend work;
those backend changes are deliberately outside this frontend release.

Main's dashboard tree and the source branch's common ancestor have the identical
Git tree `30c80434b28f1b1d890247a7ade371167b1546f2`. The patch applies cleanly.
All newer main snapshots are retained. No local worktree was reset or replaced.

Delivered: responsive day/night artwork, desktop sidebar collapse, mobile drawer
and bottom navigation, corrected first-click theme switching, clearer Summary
with 15 next-GW players, optional published rest/news panels, and standalone
Score Prediction with readonly bilingual copy/share text. Goal averages in that
text round to integers (0.5 up); the cards retain published decimal estimates.
Missing values remain unavailable. Rounded means are labelled and never described
as exact-score picks. No model, forecast, price, PMF or optimizer input changes.

## Checks before publication

- Isolated release frontend: **750 tests / 71 files passed**; rounded briefing
  focus: **48 tests / 3 files passed**.
- App, Node and Worker TypeScript checks pass. Hosted build passes with the existing
  public R2 pointer and Manager ID Worker URL. Full oxlint has zero errors and nine
  existing Fast Refresh export warnings.
- Chrome real-data preview confirms Thai and English integer text, while Brentford
  and Chelsea cards retain 1.55/1.52 and the share text shows BRE 2–2 CHE.
  Earlier desktop/mobile navigation, theme and overflow evidence is recorded in
  `dashboard-responsive-themes-2026-09-20.md`. Emulation is not a physical-phone test.
- The release has no changes under `src/`, `config/`, `results/`, `snapshots/`,
  `.github/`, `AGENTS.md`, the public release pin, package manifests or lockfiles.
  Existing model/research and forecast hashes are not rewritten. No audit,
  forecast, ingestion or optimizer job was run to prepare this release.
- Main CI was already failing in Python formatting: run `35241644135` reports
  ten files needing formatting. Those Python files remain byte-identical in this
  frontend release. This is not an all-green repository CI claim; no gate or
  workflow is disabled to hide that baseline failure.

## Data and publication

Use the existing GitHub Pages main-push workflow. Preserve repository variables
`PUBLIC_DASHBOARD_DATA_POINTER=https://data.thecometfpl.com/current.json` and
`PUBLIC_MANAGER_IMPORT_URL=https://manager-api.thecometfpl.com/manager-team`.
Only tracked frontend files are published. Local `.env.local`, copied preview data,
databases, manager inputs and test/demo feeds are excluded.

The real preview used public generation
`dd0885bcde4ead50bc2815ae613fffc9d4be4db17146e82264f24a6b20e25432`:
20 clubs, 46 ended matches across GW1–5, GW5 still partial. The selected forecast
remains dated 2026-09-14 03:39 UTC, GW5–9. New observed data does not replace that
forecast vintage. News is not present in this generation and displays unpublished;
the hosted frontend does not call X, OpenAI or another news provider.

The final Pages deployment and served-site checks are recorded on the release PR.
Rollback: revert this frontend release through a normal reviewed Git commit/PR and
let the existing Pages workflow republish. Keep the public data pointer, immutable
forecast artifacts and captured outcomes unchanged. No force push is necessary.
