# Public dashboard deployment

The supported zero-cost hosted shape is a **static GitHub Pages site** plus one immutable,
sanitized dashboard-data ZIP attached to a GitHub Release. The mutable DuckDB, forecast jobs,
optimizer, and local plan server are never deployed.

## What the hosted site can do

- Summary, fixtures, players, platform Next-GW suggestion, forecast-versus-actual, and optimizer
  audit read one validated static JSON generation.
- Squad Draft remains browser-local. A friend's selections stay in that browser's local storage.
- Plan Builder can review rules, but the hosted build does not probe or expose the Python/PuLP
  service. Exact solves remain a trusted-machine workflow.

GitHub Pages is public. Anyone with the URL can download every JSON file in the deployed site.
The public package therefore removes every `user_custom` plan, converts workstation-specific
provenance paths to their safe repository-relative form, rejects secret-like fields and absolute
local paths, rebuilds all manifest hashes, and re-runs `validate_dashboard_json`. The canonical
internal generation is read-only input and is never rewritten by packaging.

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

```powershell
uv run python -m fpl.jobs.package_public_dashboard `
  --input dashboard/public/data `
  --output $env:TEMP\the-comet-public-data `
  --archive $env:TEMP\dashboard-public-data.zip
```

The command prints a single JSON record containing the asset name, asset SHA-256, byte size, and
sanitized manifest content SHA-256. Inspect its output directory if desired; it must contain
exactly the seven read-model JSON files plus `manifest.json`.

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

- Refresh: create a new sanitized release under a new tag, then commit a new exact pin. Do not use
  `latest`, an Actions artifact with an expiry, or a mutable URL.
- Rollback: restore a previously reviewed release pin and commit it. CI re-verifies the old asset
  before publishing it.
- If the pin is intentionally removed, restore all nullable fields and set `status` back to
  `unpublished`; the workflow will stop deploying.

The current roughly 43 MiB static generation, including the roughly 40 MiB `players.json`, is
within GitHub Pages' 1 GiB published-site limit and GitHub Releases' 2 GiB per-asset limit. Standard
GitHub-hosted runners are free for public repositories. See the official
[Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits),
[Release limits](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases),
and [custom Pages workflow](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
documentation.
