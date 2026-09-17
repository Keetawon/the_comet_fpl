# R2 dashboard publication readiness

**Status: repository implementation prepared; remote activation pending,
September 17, 2026.** The optional uploader, frontend generation resolver, workflow
variable, and local credential-setup helper are implemented. They have not been
connected to a verified public R2 generation. No dashboard upload, R2 custom-domain
connection, credential setup, repository-variable activation, or scheduled R2
publication is recorded as completed here.

The owner's screenshots confirm **R2 is active** and that the dedicated
**`the-comet-dashboard`** bucket exists with Standard storage, 0 B and public
access disabled. Creation is **visually confirmed, not API-verified**; access,
credentials, domain configuration and publication remain pending. Do not
repurpose the unrelated `buildog-files` bucket shown in the earlier screenshot.

The existing `The Comet FPL - SDP primary V2` task now runs **every two hours** at
01:00, 03:00, ... 23:00 Bangkok and retains its two-minute sign-in trigger.
Its action, account, retries, locks, backups, and settings were preserved. The
verification record is [current player availability](current-player-availability-2026-09-17.md),
with the operational summary in [SDP operations](sdp-primary-operations.md).
This timing change does not enable public uploads or run the pipeline while the
owner's PC is off.

## Measured publication gap

Before this change, `refresh_dashboard` captured and built only a local generation
and preview. Its new `--r2-config` option adds publication after a successful local
refresh; omitting that option preserves local-only behavior. The public workflow
currently downloads the immutable release pinned by `dashboard/public-data-release.json`,
verifies and sanitizes it, and deploys it with GitHub Pages. A faster local schedule
alone therefore cannot update the hosted data.

The existing Cloudflare configuration is the isolated
`the-comet-manager-import` Worker at `manager-api.thecometfpl.com`. Its Wrangler
configuration has no R2 binding. R2 publication uses the S3-compatible API and a
bucket custom domain, so it requires no change to that Worker.

Read-only checks using the already installed Wrangler **4.133.0** found valid
OAuth credentials for the existing account. The granted scopes cover user/account
inspection, Worker script/route management, and zone inspection. An R2 bucket list
request failed with Cloudflare **authentication error 10000**. Existing credentials
therefore did not establish access to R2. At that time activation was unverified;
the subsequent owner screenshot establishes activation, without granting CLI
access. Authentication failure was never evidence that R2 was inactive or empty.
No token or account identifier is recorded here.

A subsequent proposal to reauthorize Wrangler with the broad `workers:write`
OAuth scope was rejected by automatic approval review. That scope expansion was
not completed and must not be retried or bypassed as part of this readiness work.
The narrower setup below lets the owner configure R2 and supply only the storage
capability needed by the implemented uploader.

## Implemented boundary

- `src/fpl/publish/r2_dashboard.py` revalidates the completed generation against
  its receipt's dashboard-manifest and companion-file hashes, reruns observed
  freshness reconciliation and the existing public sanitizer, and regenerates
  publication status against the sanitized manifest.
- It uploads exactly thirteen dashboard JSON files and three SDP JSON files as
  gzip objects, verifies stored bytes, metadata, decoded hashes and sizes, and
  conditionally updates `current.json` last. The inventory binds every companion
  into the generation hash. Existing immutable objects cannot be overwritten.
- `fpl.jobs.publish_r2_dashboard` publishes a retained generation under the existing
  refresh lock. `refresh_dashboard --r2-config` adds that same operation after local
  completion. Public failure remains separately recorded and returns a failing
  process exit code even when the local refresh succeeded. An unconfirmed pointer
  write is reported as `UNKNOWN`; it is not described as a successful publication
  or blindly rolled back.
- `dashboard/src/data/publicData.ts` resolves one generation per page session for
  main data, SDP statistics, competitive schedule, and publication status. Invalid
  configured pointers fail closed. An unset or blank pointer preserves existing
  `VITE_DATA_BASE` and `VITE_SDP_DATA_BASE` behavior. The uploader verifies byte
  hashes; the frontend validates pointer structure, paths, and file membership.
- The optional `public-data` dependency extra supplies the S3 SDK. Its explicit
  `comet-r2` file profile does not fall back to unrelated ambient credentials.
  SDK exception messages and credentials are not included in publication receipts.

## Owner setup with access restricted to R2

1. Open **Storage & databases > R2 > Overview** in the existing account. The
   screenshot already confirms activation; no additional subscription purchase is
   required for these instructions. R2 remains metered beyond its included usage.
   See [R2 getting started](https://developers.cloudflare.com/r2/get-started/).
2. Open the owner-confirmed **`the-comet-dashboard`** bucket for sanitized generations.
   Record its non-secret bucket name and account endpoint in local operational
   configuration. Keep raw captures and private artifacts out of this bucket.
3. In the bucket settings, connect **`data.thecometfpl.com`** as the custom domain
   and verify that its status and HTTPS certificate become active. The domain's
   zone must belong to the same Cloudflare account as the bucket. Keep `r2.dev`
   disabled; it is a development endpoint. The existing website and manager-import
   Worker have separate purposes. See [public bucket custom domains](https://developers.cloudflare.com/r2/buckets/public-buckets/).
4. Under the bucket's **Settings > CORS Policy**, save the dashboard JSON below.
   This permits browser reads; it does not make downloadable data private. Verify
   with a request carrying an allowed `Origin` header after the first upload.
   See [R2 CORS configuration](https://developers.cloudflare.com/r2/buckets/cors/).
5. In R2 API token management, create an **Object Read & Write** token and choose
   **Apply to specific buckets only: `the-comet-dashboard`**. Store its
   access key and secret only in protected local operational credential storage,
   outside Git, and make them available to the scheduled process without printing
   them. Never paste credentials into chat, command arguments, browser storage,
   `VITE_*`, static JSON, URLs, logs, or receipts. The uploader must use the
   **S3-compatible API**: bucket-scoped object permissions are not supported by the
   Cloudflare management REST API. Bucket creation, domain, and CORS configuration
   remain owner setup; they do not require granting the uploader account-wide
   storage administration. See [R2 authentication and token permissions](https://developers.cloudflare.com/r2/api/tokens/).

Use this JSON in the **Cloudflare dashboard CORS editor**. Its array format and
capitalized field names differ from Wrangler's `rules`/`allowed` file format:

```json
[
  {
    "AllowedOrigins": [
      "https://www.thecometfpl.com",
      "https://thecometfpl.com",
      "https://keetawon.github.io"
    ],
    "AllowedMethods": ["GET", "HEAD"]
  }
]
```

The owner can report the bucket name and completed local setup without sharing
any credential value. Account-wide admin tokens and broad Worker OAuth access
are not required for the upload process.

## Local credential setup and first publication

Run these commands from the operational checkout. They are instructions for the
remaining activation, not a record of execution. The optional SDK extra **was
installed in the permanent operational Python during this session**; no reinstall
is needed now. For a future environment setup, use the locked project and preserve
unrelated installed packages:

```powershell
$previousProjectEnvironment = $env:UV_PROJECT_ENVIRONMENT
try {
  $env:UV_PROJECT_ENVIRONMENT = 'D:/Personal/fpl-operations/.venv'
  uv sync --frozen --extra public-data --no-dev --inexact
} finally {
  $env:UV_PROJECT_ENVIRONMENT = $previousProjectEnvironment
}
```

In an interactive owner PowerShell terminal, run the helper with the **S3 API
endpoint shown in Cloudflare**. The endpoint is non-secret. The two following
prompts accept the Access Key ID and Secret Access Key as hidden input; do not put
either value in the command line or chat:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/configure_r2_publication.ps1 `
  -EndpointUrl 'https://<account-id>.r2.cloudflarestorage.com' `
  -Bucket 'the-comet-dashboard' `
  -PublicBaseUrl 'https://data.thecometfpl.com'
```

The helper creates a **new** `D:/Personal/fpl-operations/r2` directory with
owner-only inherited permissions, an SDK `credentials` file, and a non-secret
`publication.json`. It rejects existing directories, Git checkout ancestors,
symlinks/junctions, and unsuitable URLs. It never uploads data or changes the
scheduled task. If that directory already exists, inspect it and choose a new
dedicated `-Directory`; do not delete existing credentials to force setup.
The shown `-ExecutionPolicy Bypass` applies only to that PowerShell process; it
does not change machine policy. A `-WhatIf` invocation was verified successfully
without creating credentials or modifying the scheduled task.

Select one completed `dashboard-*/generation` retained by a successful local
refresh. Do not select by filename recency alone: inspect its generation receipt
and the enclosing refresh receipt. The standalone CLI was checked with `--help`:

```powershell
& D:/Personal/fpl-operations/.venv/Scripts/python.exe -m fpl.jobs.publish_r2_dashboard `
  --generation 'D:/Personal/fpl-operations/dashboard-runs/<completed-dashboard-run>/generation' `
  --r2-config D:/Personal/fpl-operations/r2/publication.json `
  --runs D:/Personal/fpl-operations/dashboard-runs
```

Use the same `--runs` directory as the existing refresh task so both operations
share its lock. The command prints the path to its non-secret publication receipt.
Require `status: "COMPLETE"`; inspect `FAILED` or `UNKNOWN` without deleting locks
or overwriting remote objects manually.

After successful publication, check HTTPS and the exact allowed origin without
disabling certificate verification:

```powershell
curl.exe --fail --silent --show-error --head `
  --header 'Origin: https://www.thecometfpl.com' `
  https://data.thecometfpl.com/current.json
```

Require an exact `Access-Control-Allow-Origin` and `Cache-Control: no-store`.
Read the pointer, fetch its immutable data and SDP paths, and compare the served
manifest and publication-status identity with the publication receipt. Check all
configured site origins in a real browser. If CORS is changed after caching began,
refresh the affected cached content as described in the official CORS guide.

## Hosted cutover and scheduled publication still pending

Only after the upload, domain, CORS, and hosted browser checks pass, set the GitHub
Actions repository **variable**, not a secret, as follows:

```powershell
gh variable set PUBLIC_DASHBOARD_DATA_POINTER `
  --repo Keetawon/the_comet_fpl `
  --body 'https://data.thecometfpl.com/current.json'
```

Deploy the reviewed frontend through the existing Pages workflow. It maps that
variable to `VITE_PUBLIC_DATA_POINTER`; changing the repository variable alone
does not change already built assets. Until this verified cutover, the hosted
site continues reading its pinned Pages release. Clearing the variable and
rebuilding restores that release path; an active R2 pointer never silently falls
back to bundled data. No CSP was found in the inspected repository files; check
deployed response headers and any Cloudflare rules during cutover.

After the first remote generation is verified, append this optional argument to
the **existing task action**, preserving its two-hour and sign-in triggers and
all other settings:

```text
--r2-config "D:/Personal/fpl-operations/r2/publication.json"
```

Do not rerun the registration helper to overwrite the existing task. The equivalent
manual command, confirmed against the current refresh CLI, is:

```powershell
& D:/Personal/fpl-operations/.venv/Scripts/python.exe -m fpl.jobs.refresh_dashboard `
  --db D:/Personal/fpl-operations/data/sdp-primary-v2.duckdb `
  --runs D:/Personal/fpl-operations/dashboard-runs `
  --forecast-dir D:/Personal/fpl-operations/predictions `
  --preview-public dashboard/public `
  --plan-store D:/Personal/fpl-operations/dashboard-plans `
  --r2-config D:/Personal/fpl-operations/r2/publication.json
```

Observe a subsequent scheduled receipt and its public generation before claiming
automatic two-hour public updates. The owner must remain signed in and the host
must be able to run and reach the sources and R2.

## Minimal publication contract

Once activated, R2 serves completed static read models. Ingestion, the mutable DuckDB,
forecasting, and optimizer execution remain on the existing operational host.
Moving the output to R2 does not execute a refresh while that host is off and does
not repair stale field semantics. Forecast vintages and their original as-of
times remain distinct from refreshed observations.

For each successful local refresh:

1. Take the immutable completed generation from that refresh, rather than a
   mutable preview directory. Run the existing `package_public_dashboard`
   sanitizer and validator. Preserve its exact read-model allowlist and removal
   of private/custom plan data; never upload `dashboard/public` recursively.
2. Validate `sdp_stats.json` and `competitive_schedule.json` from the same
   generation. Regenerate `publication_status.json` against the **sanitized**
   dashboard manifest so its `data_manifest_sha256` matches the public files.
   Apply the public privacy boundary to every additional exported file. Publish
   no databases, raw provider responses, private manager captures, credentials,
   workstation paths, or unsanitized operational receipts.
3. Build a canonical file inventory and derive a generation hash that binds the
   sanitized dashboard manifest **and all companion files**. The dashboard
   manifest hash alone cannot identify a generation when only SDP or schedule
   content changes. Use a new immutable prefix such as
   `generations/<generation-sha>/data/` and `generations/<generation-sha>/sdp/`.
4. Upload only inventoried files, with their content type and encoding recorded,
   then read back and verify their expected hashes and sizes. Reuse an existing
   prefix only if its entire inventory matches exactly. A failed or partial upload
   must leave the currently published generation unchanged.
5. Replace one small `current.json` pointer **last**, after the complete generation
   passes verification. Bind it to the inventory and use a validated relative
   generation path. Serve the pointer with `Cache-Control: no-store` and ensure
   no CDN rule overrides that policy. Immutable generation files may use long
   cache lifetimes. Retain the prior pointer for rollback and serialize publication
   through the existing single-host refresh lock.

R2 object operations are strongly consistent, but CDN caches can continue serving
overwritten objects. Immutable prefixes plus a final pointer update avoid a
partially replaced multi-file generation; they do not create a bucket-wide
transaction. See [R2 consistency and caching](https://developers.cloudflare.com/r2/reference/consistency/).

The browser must resolve the pointer **once per page session** and retain the same
generation for every request. Main read models, SDP statistics, competitive
schedule, and publication status must all share that selection. Resolve a new
generation on a full reload; do not update individual files underneath an open
session. Pointer or required-file validation failures must be visible, without
mixing files from another generation.

## Verification and retained limitations

Recorded local checks passed: **73 focused backend tests**, **583 dashboard
tests**, and the production frontend build. The credential helper's `-WhatIf`
check also passed. These are scoped checks, not a new full-repository gate claim.
Focused coverage is in `tests/test_r2_dashboard.py` and
`dashboard/src/data/publicData.test.ts`; it exercises publication failures,
immutable objects, pointer conditions, source receipt binding, privacy checks,
session pinning, path validation, and legacy URL behavior. Offline tests cannot
prove the owner's credentials, live CORS, domain certificate, deployed response
headers, first upload, or subsequent scheduled publication. Those checks remain
part of the pending activation above.

The real SDP companion initially failed the generic privacy scanner on its existing
public `owner_confirmation_recorded_at` provenance key. The R2 adapter now validates
the strict SDP schema, substitutes only that exact timestamp key in a temporary
privacy-check copy, and scans all values and remaining keys normally. Published
provenance is unchanged; unknown private keys and values still fail. The first
offline attempt was retained and uploaded nothing. This does not weaken the shared
public-package sanitizer.

The corrected offline preparation passed on the actual completed September 17
generation: exactly 16 public files, 203,936,558 decoded bytes and 16,785,584 gzip
bytes, generation `674fb2aa1d7937039382f86c94a814ed939a38ced6ac9c46f36008456c36b927`.
The retained verification is `data/artifacts/availability-20260917/r2-validation-02/`.
This used no credentials or network and does not establish remote publication.

The current generation is roughly 200 MB before compression. At twelve new
generations per day, indefinite retention would quickly exceed a small storage
allowance. Gzip JSON objects with correct `Content-Encoding: gzip` can reduce
storage and transfer while preserving decoded JSON and its manifest hashes;
verification must account for both stored encoding and decoded content. Establish
retention deliberately, preserving the active generation and any promised rollback
window. Do not introduce automatic deletion during readiness work.

R2 Standard currently includes **10 GB-month**, **1 million Class A operations**,
and **10 million Class B operations** monthly, with free egress. Those allowances
are not a permanent zero-cost guarantee. See [R2 pricing](https://developers.cloudflare.com/r2/pricing/)
and [object upload metadata](https://developers.cloudflare.com/r2/objects/upload-objects/).
