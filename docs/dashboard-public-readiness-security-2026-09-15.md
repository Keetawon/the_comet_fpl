# Dashboard support button, lean loading and security review

Date: 2026-09-15. Starting code: `eddf9b345cb002736abbea71bcbb68d343f3475d` on
`claude/comet-fpl-v2-architecture-mqrj8f`. This is application/readiness work, not model work.

## Delivered behavior

The sidebar has a **Buy Me a Coffee** button on desktop and mobile. The owner has no support
account yet, so it opens an accessible coming-soon notice. It cannot take a payment, has no
fabricated destination, and adds no third-party widget, tracker, SDK or request. The real owner
account URL is required before replacing the notice with an external support link.

Hosted builds use the existing `VITE_HOSTED_STATIC=true` switch. They expose analytical pages,
hide Next GW suggestion, Optimizer audit, Plan builder and Squad draft, and reject direct hash
navigation to those routes. Summary also hides formal/custom optimizer cards. Local builds retain
all these tools. A central guard prevents every plan-server client call in hosted mode. Unknown
hashes, including inherited JavaScript property names, now resolve safely to Summary.

Each page loads its JavaScript on demand, using React's existing lazy/Suspense API. Existing
read-model caching, forecast vintage selection, scalar values and data envelopes are unchanged.
A failed lazy chunk has a recoverable reload notice; the navigation shell remains usable.
The local entry module decreases from **940,735 bytes to 264,937 bytes** (about
72% smaller); the hosted entry is 268,549 bytes. These are entry-module sizes,
not total page-download reductions: shared/page chunks and data still load as required.
The current local `players.json` is 122,619,623 bytes and remains a significant transfer/parse
cost. This task does not shard, truncate, rewrite or republish that immutable generation.

`shadcn` remains installed because `index.css` imports its Tailwind stylesheet. It belongs in
build/dev dependencies; it is not a runtime server. We did not copy its 629-line stylesheet or
remove needed variants to make the dependency count look smaller.

## Security findings and bounded repairs

| Finding | Change and evidence |
|---|---|
| Local HTTP server trusted loopback peers without checking HTTP Host | Exact same-machine literal/localhost Host validation, with no untrusted hostname DNS resolution. A rebinding hostname is rejected even on an Origin-less GET. GET, POST and OPTIONS regression tests exercise this boundary. |
| Origin validation checked the hostname but accepted malformed origin shapes | Require HTTP(S), a valid port, no userinfo/path/query/fragment, then the existing same-machine address policy. |
| Non-insight POST bodies had no read timeout and ambiguous framing was accepted | Reuse one bounded reader for every POST: application/json, exactly one Content-Length, no Transfer-Encoding, byte limit, five-second read timeout, exact body length. Bad/short bodies fail before pipeline invocation. |
| Sensitive local status/capture responses could be cached | JSON responses include `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`. |
| Hosted UI still offered local decision tools | Guard navigation, Summary cards and the shared client boundary; tests and browser evidence confirm zero local-server requests in hosted mode. |
| Eager page imports loaded all tool/page code immediately | Lazy page imports; unknown/prototype hash properties no longer pass the route lookup. |
| Dependency advisories | Vitest 4.1.10 to 4.1.11, plus compatible locked patches for fast-uri 3.1.8, Hono 4.13.8, js-yaml 4.3.2 and qs 6.16.0. No forced major upgrades, lifecycle install scripts, Python dependency changes or model changes. |

The [Vitest maintainer advisory](https://github.com/vitest-dev/vitest/security/advisories/GHSA-82fw-gwwq-j7x9)
describes a development-server file-read issue with specific exposure prerequisites; 4.1.11 is
the patched version. This review does not claim that this application was exploited. npm audit
initially reported **18 affected package entries: nine high and nine moderate**, including
transitive dependency propagation. The installed, updated lockfile reports **zero**. That count
is not a count of 18 independently exploitable application vulnerabilities.

OSV's batch API found no listed advisory for the **31 registry packages pinned in `uv.lock`**.
These are point-in-time advisory checks, not a proof that the dependencies have no unknown defects.

## Review coverage and limits

Inventory: 1,447 tracked files, including 233 Python source files and 129 frontend TS/TSX files
before this change. Manual review focused on routing, local HTTP authorization/body handling,
insight boundaries, CSV export escaping, public-data sanitization and the deployment workflow.
The public sanitizer already rejects private fields/secret-like content, strips custom plans,
validates schema/hash identity and publishes a separate generation without mutating the source.
Existing tests exercise mutation rejection, private-field rejection and atomic publication.
Reviewed CSV paths already escape quotes and guard leading formula markers; React rendering does
not use an application `dangerouslySetInnerHTML`/eval path in the reviewed dashboard source.

A tracked-text scan found no matching private-key header, GitHub token, AWS access-key ID or live
Stripe-secret pattern. It scanned UTF-8 files up to 3 MB, outputting only path/line/type on a match.
It was not an entropy scan, Git-history scan, inspection of untracked credentials or penetration
test of a deployed server. Frozen model implementation was deliberately not rewritten or retested
as a new scientific candidate.

Remaining operational boundaries:

- The Python plan server is a trusted local tool, not an Internet application server. Its loopback
  token bypass remains intentional. Do not put it behind a public reverse proxy or open its port;
  a reverse proxy can make remote traffic appear loopback. No public optimizer was deployed.
- Hiding routes is not file authorization. All assets on a static site are downloadable. The
  unchanged schema still includes reviewed formal plan metadata for vintage identity. Continue
  using the sanitizer; never upload a local export, DuckDB, manager capture, `.env` or raw evidence
  directory directly. The hosted-mode review preview uses local data and is loopback-only.
- Public release packaging, existing release pins and deployment permissions are unchanged. No
  Supabase migration, cloud account, credential, scheduled runtime or production deployment was
  created. Repository approval/deployment remains through the existing flow.
- The already-running optimizer process was not restarted by this review. The HTTP repair takes
  effect when that host's existing plan-server launcher is restarted from the new commit.
- Large static data remains a performance limitation. Any later data-sharding change needs its
  own compatible public-generation contract; changing frozen serialization here would be unsafe.

## Verification

Evidence is retained locally under `data/artifacts/public-readiness-20260915/`; no operational data
or browser profile is committed. `before.json` pins 185 model/config/result/dependency files plus
13 dashboard data documents. **184 of 185 pinned files and all 13 data documents match exactly**.
The only intentional change within that pin set is the frontend `dashboard/package-lock.json`.

The browser plugin was discovered and attempted: `getForUrl` returned `No browser is available`,
and its documented discovery returned `[]`. After reading its troubleshooting guidance, verification
used an isolated local headless Chrome profile and CDP on loopback. It never accessed the owner's
browser profile or sessions. Desktop 1440x1000 and mobile 390x844 checks covered both local and hosted
builds, actual support-button interaction, Escape/close, viewport containment, route isolation and
Summary card suppression. Four screenshots were captured and inspected. Browser exceptions,
failed network requests, HTTP errors and hosted calls to port 8765 were all zero.

Preview URLs on the existing host only:

- Local tools: `http://127.0.0.1:4173/`
- Hosted-mode review: `http://127.0.0.1:4174/`

These loopback URLs are not Internet previews. Screenshots: `coffee-hosted-desktop.png`,
`coffee-hosted-mobile.png`, `coffee-local-desktop.png`, `coffee-local-mobile.png` in the evidence
directory, with final-build verification retained separately in `browser-final/`.
The temporary browser is closed after verification; previews remain running.

Checks completed:

- Frontend full suite: 449 passed across 50 files; subsequent Summary/load-recovery additions:
  15 focused passes, including the updated App routes. Local and hosted builds and TypeScript pass.
- Python HTTP/public-export focus: 106 passed. Additional Origin-shape tests: 13 passed
  (eight new cases plus five existing origin/token checks). Synthetic inputs only.
- Ruff `check src tests`: passes. Strict mypy: no issues in 233 source files.
- Changed Python file formatting: passes. Full format check retains 11 unchanged pre-existing
  failures in insights, publish and their tests; no unrelated formatting cleanup was performed.
- Frontend lint exits zero with nine pre-existing Fast Refresh export warnings. An initial lint
  also scanned an intermediate generated hosted build; moving that build into the ignored evidence
  directory restored the intended source-only lint scope.
- The first Python focus attempt hit access denial on the inherited system pytest temp directory
  (22 passed, 84 setup errors). A fresh task-owned `--basetemp` resolved that setup problem without
  deleting or changing the old directory.

Full Python regression ran once in 1,242.96 seconds: **4,387 passed, 18 failed, four skipped,
17 setup errors** (5,505 warnings). This is not an all-green repository result. Attribution:

- 14 `test_bi_export.py` failures: Windows `WinError 1314` when creating directory symlinks.
- Three audit identity/byte-guard failures: historical verification still pins an older
  `AGENTS.md` digest (`54f8ed3f...`). The starting commit already differs: its Git/LF digest is
  `d508dfb1...`, or `a25b27bd...` after CRLF conversion. The public-scope addendum does not repair,
  bypass or rewrite that old verification. Original audit results remain intact.
- One `test_prospective_incumbent_adapter.py` failure: its synthetic database lacks
  `stg_live_team_version`, now required by the existing player-history loader.
- 17 `test_development_reference_components.py` setup errors: the synthetic capture fixture
  asserts exactly one minutes-model instance, while the existing component path constructs two.

The relevant model/history implementation and these test files are unchanged from the starting
commit. These stale test-contract issues are not described as Windows failures or repaired by
changing the frozen model. No second full-suite run or historical audit was performed. Scoped
HTTP, frontend and public-export tests pass as reported above.

At review time the branch was synchronized with its remote and was 105 commits ahead / 22 behind
the freshly fetched `origin/main`, before this task's commit. Local `main` remained
`ede17377216807ca2635879d1153e268dcd04fe6`. This work does not authorize merging that broad branch.

No forecasts were regenerated, no historical audit was rerun, and no outcomes were used for tuning.
The Player Model, optimizer algorithms, parameters and frozen research remain unchanged.
