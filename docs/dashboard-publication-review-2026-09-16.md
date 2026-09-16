# Dashboard publication review, September 16

This prepares the existing GitHub Pages delivery. No domain, hosting migration, model change,
forecast regeneration, main-branch merge or live-site deployment is part of this preparation.

## Reviewed generation

- Source code at preparation start: `b7d4a665c925fdcc71750798944f7be8bc5d2420` on the existing V2 branch.
- Completed refresh: `dashboard-20260916T140011Z-ff337dc6`, finished
  `2026-09-16T14:40:40.014529Z`. Its retained `generation/public` is read-only input.
- FPL source: `2026-09-16T14:11:25.925948Z`; SDP source:
  `2026-09-16T14:34:44.919807Z`; export: `2026-09-16T14:36:22.050035Z`.
- Officially finalized through GW4: 40 fixtures **across GW1-4**, with 2,549 player-fixture
  observations and 80 current-season team sides. Detailed SDP player statistics remain unavailable;
  FPL enrichment stays explicitly labelled. Successful capture does not mean provider-core completeness.
- Forecast remains the September 14 GW5-9 vintage, artifact SHA256
  `ef208e71e341043993e5d380542b4cfb135c98b97bf4cc0df853cefcf97cc751`.
- Public manifest: `c5ceae2a3e3614ba4e7a9bf37619cfd972864fc7ee34d9dbc571b2698be8c21d`.
  Release: `dashboard-data-c5ceae2a3e36`. Exact asset hashes and sizes are in
  `dashboard/public-data-release.json`. The morning review package is retained separately;
  the scheduled evening capture completed during review and supplies this final release.

The public ZIP was re-sanitized independently and reproduced SHA256
`f66d95c2df3088f06d86cde9c02a2789a0c2a7a5b41a62f4442c04419307355f` byte-for-byte.
Both public companions passed their existing validators. Internal receipts, database files,
raw captures, local manager state and private plans are not release assets.
The three reviewed assets are uploaded at
<https://github.com/Keetawon/the_comet_fpl/releases/tag/dashboard-data-c5ceae2a3e36>.
Uploading this immutable release does not change the currently served Pages site.

## Bounded changes

The old public pin still referenced the September 3 release and omitted both statistics/schedule
companions. The new pin includes those companions. Deployment now invokes the existing public
freshness producer after validating downloads, so the live monitoring pages can distinguish
current observations from the original forecast date. No new publishing service was introduced.

Browser review exposed narrow-screen overflow in Players' actual-date selectors and shared
colour/vintage selectors. Responsive wrapping fixes those layouts without changing any selector
value, formula, table data or model input.

## Verification and access

Local hosted-mode preview: `http://127.0.0.1:4183/the_comet_fpl/`. This is accessible only on the
owner machine while its preview process is running; it is not a remotely shared preview.
It uses the real GitHub Pages base path and the pinned release files, separately from the local
Dashboard and optimizer. The browser plugin reported `No browser is available` and empty discovery;
verification uses installed Chrome in a separate headless test profile.

Evidence and actual screenshots are retained locally in
`data/artifacts/public-release-20260916/`. No screenshot or local receipt is an input to a forecast.
Verification: 33 focused Python publication/privacy/refresh tests; 44 frontend tests across
Players, publication status, route visibility and colour controls. Changed-test Ruff/format and
strict mypy pass (explicit `MYPYPATH=src` for the test module); TypeScript and hosted build pass.
Frontend lint has zero errors and nine existing Fast Refresh warnings. Ten browser page/viewport
combinations pass: SDP, Fixtures, Players and both forecast-versus-actual pages at desktop 1440x1000
and mobile 390x844, with no horizontal page overflow, console errors, uncaught exceptions or failed
local responses. Monitoring filters, table sorting/reset and finalized/pending vintages were checked.
Ten retained operational forecast hashes and 668 tracked source/config/results/snapshot hashes
are unchanged, as are tracked model/config/results/snapshot
files against preparation start. No full-repository-green claim is made.

## Publication decision

Existing draft PR: <https://github.com/Keetawon/the_comet_fpl/pull/7>.
At review start its branch was **116 ahead / 25 behind current remote main**; it includes the full
V2 architecture, research records, checkpoint, Dashboard and operations program. This is not a
Dashboard-only merge. GitHub reported mergeable, but its quality check failed on the existing
11-file format gate, before mypy/tests. These are separate review blockers, not changed scientific
results. This delivery does not clean up frozen or unrelated files to force that gate green.

The owner previously required separate approval before main merge and production publication.
After review and resolution of the required checks, the exact production action is to approve/merge
the existing PR normally; the existing Pages workflow then downloads this pinned release, verifies
hashes/privacy, tests/builds and deploys. Do not force-push or change the default branch.
Verify the served `/data/manifest.json` content hash and companion hashes after deployment.
Rollback is a normal commit restoring the previous reviewed code/pin; never replace release assets.

## Domain can follow the Dashboard

The existing GitHub URL requires no purchased domain. For a future R2 setup, Cloudflare Registrar
is a convenient option because the domain already uses Cloudflare DNS. Search for `thecometfpl.com`
in the owner's account; availability and the exact initial/renewal price must be checked at checkout.
No availability or ownership claim is made here.

Register one year with accurate contact details, verify the email and retain auto-renew if desired.
Cloudflare Registrar requires Cloudflare nameservers while the domain is registered there.
Registering a domain does not require buying hosting or changing the current Dashboard.
After purchase, verify ownership in GitHub, set the Pages custom domain, then configure DNS/HTTPS.
Use `www` for the site and, later, a separate `data` hostname for R2 if that integration is authorized.
No R2 credentials, bucket, paid service or automatic public-upload pipeline has been created here.

Official instructions:
- <https://developers.cloudflare.com/registrar/get-started/register-domain/>
- <https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site>
