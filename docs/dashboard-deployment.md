# Public dashboard deployment

The supported zero-cost hosted shape is a **static GitHub Pages site** plus one immutable,
sanitized dashboard-data ZIP attached to a GitHub Release. The mutable DuckDB, forecast jobs,
optimizer, and local plan server are never deployed.

## What the hosted site can do

- Summary, fixtures, players, SDP team statistics, and separate player/team
  prediction-versus-actual read one validated static JSON generation.
- Player/team deep analytics remain static: they filter, sum published expectations, and draw
  presentation geometry over that same generation.
- Hosted builds (`VITE_HOSTED_STATIC=true`) hide Next GW suggestion, Optimizer audit,
  Plan Builder, and Squad Draft, including direct hash navigation. Summary hides optimizer
  squad cards. The local build retains these tools; exact solves remain a trusted-machine workflow.
  Every local-server client request also fails closed in hosted mode.
- Buy Me a Coffee opens the owner-provided `https://buymeacoffee.com/thecomet` in a new tab
  with `noopener noreferrer`. Payment handling stays on that external site; there is no embedded
  payment widget or third-party script in the Dashboard.
- Every route includes its implemented network-free deterministic insight summary. The seven public
  renderer-eligible routes are Summary, Fixture matrix, Players, Player analytics, Team analytics,
  Player prediction vs actual, and Team prediction vs actual. Next GW suggestion, Optimizer audit,
  Plan Builder, and Squad Draft remain local deterministic-only surfaces.
- The hosted build never contains a Z.AI or other provider credential and makes zero insight-status
  or provider-summary calls. Optional AI-selected explanation is explicit opt-in through the protected local Plan
  Server only; it stays unavailable in the static hosted build. No key belongs in `VITE_*`, static
  JSON, a URL, browser storage, logs, cache records, Git, or the release ZIP.

GitHub Pages is public. Anyone with the URL can download every JSON file in the deployed site.
The public package therefore removes every `user_custom` plan, converts workstation-specific
provenance paths to their safe repository-relative form, rejects secret-like fields and absolute
local paths, rebuilds all manifest hashes, and re-runs `validate_dashboard_json`. The canonical
internal generation is read-only input and is never rewritten by packaging.

Hiding a page is not access control for downloadable files. The unchanged public-generation
contract still carries reviewed formal plan metadata for vintage identity. Never publish a local
`dashboard/public/data` directory directly: use the existing sanitized release workflow.
See [public-readiness security review](dashboard-public-readiness-security-2026-09-15.md).

## One-time setup

1. Keep `dashboard/public-data-release.json` at `status: "unpublished"` while preparing the first
   release. In that state pushes safely skip deployment and a manual deployment fails visibly.
2. In GitHub repository settings, select **Pages -> Build and deployment -> GitHub Actions**.
   This can instead be configured through the GitHub Pages REST API with administrator approval.
3. No hosting secret is required. The workflow uses the repository's short-lived `GITHUB_TOKEN`
   with `contents: read`, `pages: write`, and `id-token: write`.

## Publish one immutable data generation

Start only from a dashboard generation that already passes the normal publish contract. Package a
copy outside the Git repository. Both output paths must be new; the packager deliberately refuses
to overwrite a previous directory or archive:

The local atomic publisher swaps a directory symlink. On Windows, Developer Mode or an elevated
shell is required; `WinError 1314` at that final OS call means the environment lacks symlink
privilege, not that the already-validated read models failed. Do not call the formal publish gate
green until it is rerun in a symlink-capable environment.

```powershell
uv run python -m fpl.jobs.package_public_dashboard `
  --input dashboard/public/data `
  --output $env:TEMP\the-comet-public-data `
  --archive $env:TEMP\dashboard-public-data.zip
```

The command prints a single JSON record containing the asset name, asset SHA-256, byte size, and
sanitized manifest content SHA-256. Inspect its output directory if desired; it must contain
exactly the twelve read-model JSON files (`fixture_matrix.json`, `players.json`,
`player_actuals.json`, `team_actuals.json`, `player_provisional_actuals.json`,
`team_provisional_actuals.json`, `player_horizons.json`, `next_gw.json`, `summary.json`,
`player_forecast_vs_actual.json`, `team_forecast_vs_actual.json`, and `optimizer_audit.json`) plus
`manifest.json`.

The two provisional files retain their explicit schema-v1 envelopes and `captured_at`; they are
available only to Players and Fixture Matrix and never become monitoring outcomes. Their inclusion
keeps the sanitized generation and its manifest complete. It does not publish that generation:
the owner must still inspect the ZIP, create the immutable release, and commit the exact pin below.

Create a new release and tag for that exact generation. Never replace an existing tag or asset:

```powershell
gh release create dashboard-data-<manifest-prefix> `
  $env:TEMP\dashboard-public-data.zip `
  --repo Keetawon/the_comet_fpl `
  --target <exact-generating-commit> `
  --title "Dashboard data <manifest-prefix>" `
  --notes "Sanitized immutable dashboard read models."
```

Then replace the unpublished values in `dashboard/public-data-release.json` with the exact output:

```json
{
  "asset_name": "dashboard-public-data.zip",
  "asset_sha256": "<64 lowercase hex characters>",
  "asset_size_bytes": 12345678,
  "manifest_content_sha256": "<64 lowercase hex characters>",
  "release_tag": "dashboard-data-<manifest-prefix>",
  "repository": "Keetawon/the_comet_fpl",
  "schema": "fpl.dashboard-public-release-pin",
  "schema_version": 1,
  "status": "published"
}
```

Commit that pin with the dashboard code. A push to `main` now downloads only the named release
asset, verifies its pinned SHA-256 and exact ZIP members, validates the read-model manifest, runs
the dashboard tests and lint, builds with the Pages base path and hosted-mode guard, revalidates
the copied build data, and deploys the artifact. `workflow_dispatch` provides an explicit retry.
Dashboard tests, lint, and a normal build run even while the pin is `unpublished`; only the
asset-dependent hosted build and deploy are skipped.

## Refresh and rollback

- The local four-hour/sign-in `refresh_dashboard` task refreshes local data and the preview;
  it does **not** upload a release, change this public pin, or deploy Pages. Public deployment
  remains a reviewed release + pin on `main`. A domain is not required: the existing
  `https://keetawon.github.io/the_comet_fpl/` URL remains usable.
- Include the validated `sdp_stats.json` and `competitive_schedule.json` from the **same completed
  generation** as separate assets on the same release. Pin them as `sdp_asset` and
  `competitive_schedule_asset`, each with `name`, `sha256` and `size_bytes`. They do not belong in
  the ZIP's exact root-file allowlist. Missing companions deliberately show unavailable views.
- After downloading and verifying the companions, CI reuses `publication_status` to derive the
  small freshness receipt from the pinned public manifest and SDP gameweek metadata. This binds
  dates to the deployed generation, separates observation freshness from forecast as-of, and
  requires no database, capture, inference, or optimizer execution.
- Refresh: create a new sanitized release under a new tag, then commit a new exact pin. Do not use
  `latest`, an Actions artifact with an expiry, or a mutable URL.
- Rollback: restore a previously reviewed release pin and commit it. CI re-verifies the old asset
  before publishing it.
- If the pin is intentionally removed, restore all nullable fields and set `status` back to
  `unpublished`; the workflow will stop deploying.

The September 16 review generation is about 189 MB uncompressed, including a roughly 123 MB
`players.json`; the sanitized ZIP is 14,890,953 bytes. This is within GitHub Pages' 1 GiB
published-site limit and GitHub Releases' 2 GiB per-asset limit, but a large player download
still affects first-load performance. Moving the files to object storage alone would not fix that.
Standard
GitHub-hosted runners are free for public repositories. See the official
[Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits),
[Release limits](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases),
and [custom Pages workflow](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
documentation.
