# Evidence-bound dashboard insight summaries

Status: implemented development-only from the frozen 2026-08-26 contract. The language model is
an optional renderer, not an analytical authority or autonomous agent.

## Product rule

Every dashboard route gets an immediate deterministic insight panel. Public analytical routes may
also show an explicit **Explain with AI** action when a trusted local provider is configured.
Nothing calls a remote model automatically on page load or filter changes. Changing vintage or
scope immediately rebuilds the deterministic facts and marks prior AI-selected output stale.

Remote renderer scope is limited to Summary, Fixture matrix, Players, Player analytics, Team analytics,
Player prediction vs actual, and Team prediction vs actual. Next-GW plans, Optimizer audit, Plan
Builder, Squad Draft, manager imports, squads, bank, purchase/selling values, capture identifiers,
and custom-plan state remain deterministic-only. They still have a summary panel; their data is
never sent to a third-party model.

AI output is labelled "AI-selected - verify cited metrics". The provider may select and group
server-authored fact ids, but it never authors dashboard prose. Python renders the selected
canonical statements with their citations, so the optional step cannot introduce a new metric,
probability, causal claim, recommendation, or model verdict.

## Z.AI use

Z.AI can implement the first provider through its general Open Platform API, whose documented
OpenAI-compatible base URL is `https://api.z.ai/api/paas/v4/`. The coding-tools endpoint is not the
dashboard endpoint. Z.AI's subscription terms state that GLM Coding Plan quota is for supported
coding tools and may not be used as general application/API quota without a separate agreement;
therefore a large Coding Plan balance does not by itself authorize dashboard calls. Use a general
Open Platform API key/balance and confirm the current account terms.

The API key exists only in the trusted Python process environment. It is never put in Vite source,
`VITE_*`, static JSON, a URL, browser storage, logs, cache records, or Git. The hosted dashboard is
static, keeps deterministic summaries, makes no insight network call, and does not offer the
optional action. Local optional AI-selected output goes through the protected Plan Server. Direct
browser-to-provider calls are forbidden.

The adapter is provider-neutral. Its implemented server environment is
`FPL_INSIGHTS_PROVIDER=zai_glm`, `FPL_INSIGHTS_API_KEY`, `FPL_INSIGHTS_MODEL`, and optional
`FPL_INSIGHTS_BASE_URL` (defaulting to the general Open Platform URL above). A custom base URL must
be credential-free HTTPS. The request cannot choose a key, provider, model, base URL, system
prompt, or free-form user prompt. Missing, incomplete, or invalid configuration leaves the optional
renderer disabled while every deterministic panel continues to work.

For local PowerShell use, configure only the trusted server process, then start the normal Plan
Server. Replace the placeholder in the private shell or source the value from a local secret
manager; do not put this block with a real key in a script, `.env` file, terminal transcript, or
commit:

```powershell
$env:FPL_INSIGHTS_PROVIDER = "zai_glm"
$env:FPL_INSIGHTS_API_KEY = "<general-Open-Platform-API-key>"
$env:FPL_INSIGHTS_MODEL = "glm-4.7"
# Optional; omit to use https://api.z.ai/api/paas/v4/
$env:FPL_INSIGHTS_BASE_URL = "https://api.z.ai/api/paas/v4/"

.\.venv\Scripts\python.exe -m fpl.jobs.plan_server `
    --base <dev-latest-directory> `
    --forecast <current-prospective-points.jsonl> `
    --dashboard-data dashboard\public\data
```

Clear the process values after the server stops if the shell will be reused:

```powershell
Remove-Item Env:FPL_INSIGHTS_API_KEY, Env:FPL_INSIGHTS_PROVIDER, `
    Env:FPL_INSIGHTS_MODEL, Env:FPL_INSIGHTS_BASE_URL -ErrorAction SilentlyContinue
```

## Browser-to-server contract

The existing same-origin/approved-LAN-token Plan Server boundary protects both insight endpoints;
they are not provider-facing public APIs. `POST /insights/summary` accepts an exact-key,
Pydantic-validated
`fpl.insight-summary-request` version 2. The browser sends selectors only:

- a public-page enum;
- manifest content hash, run id, season, and `as_of`;
- a bounded, exact typed display scope containing only that page's public filters;
- at most 16 KiB total body.

Version 2 adds the paired `actual_gw_from` / `actual_gw_to` selectors for the Players route. They
are distinct from forecast `gw_from` / `gw_to`, must be supplied together in ascending order, and
must remain within the finalized current-season actual range published in `players.json`. Other
pages reject them. This prevents a visible actual-range change from reusing evidence resolved for
an unrelated forecast horizon.

There is no fact, caveat, chat, or arbitrary-text field. Extra keys fail closed. The server resolves
the selector against the explicitly configured dashboard-data directory, verifies the schema-v6
manifest content hash, every file hash, run/season/`as_of`, and a stable manifest before and after
the read, then constructs the bounded fact/caveat packet itself. A caller therefore cannot smuggle
manager/private state, financial state, credentials, paths, instructions, or invented values to the
provider. `--dashboard-data` defaults to `dashboard/public/data`; the server never discovers a
generation by glob.

The success response identifies schema/version, source (`provider` or `cache`), provider, model,
prompt version, cache key, and generation time. It contains a server-rendered headline and at most
four plain-text insight items. The provider response is only a bounded headline category plus
fact-id selections/relation enums. Unknown, duplicate, incomplete, non-`stop`, or malformed
selections fail validation; Python renders the verified source statements and exact citations.
React renders text, never provider HTML or executable Markdown.

`GET /insights/status` may expose only enabled state, provider, model, and prompt version. It never
returns credentials or a server base URL. Disabled, timed-out, rate-limited, malformed, or failed
provider calls return a stable safe error code and the UI keeps the deterministic summary.

## Provider controls

- Use the general chat-completions API with structured JSON output where the configured model
  supports it. HTTPX and Pydantic are already project dependencies; no provider SDK is required.
- The fixed system prompt asks only for fact-id selection/grouping. GLM thinking is disabled for
  this renderer. The provider does not return prose, arithmetic, or a model verdict.
- Use bounded connect/write/read/pool timeouts, an overall time budget with postflight rejection and
  bounded waiter time, one retry only for transport failures or 429/502/503/504, a capped response
  body, no redirects, a small rate limit, and single-flight by cache key. Never retry authentication
  or malformed output.
- Cache key is SHA-256 over the canonical server-resolved evidence plus provider identity, model,
  and prompt version.
  Cache only validated response/provenance under the ignored plan-server base; never cache keys,
  raw provider bodies, resolved evidence, selector requests, or failures. Cache hits revalidate
  citations, and one in-memory flight shares both success and failure with concurrent waiters even
  if the disk cache is unavailable.
- Do not log request bodies or upstream bodies. The insight service must not acquire the optimizer
  run lock and must work independently of solver readiness.

## Deterministic summaries

The deterministic path is authoritative and network-free. Each page-specific pure TypeScript fact
builder returns concise source-linked facts and caveats from its visible scope. It follows all null,
vintage, horizon, probability, form/forecast, and outcome-finality semantics. Empty pages explain
why there is no evidence instead of producing generic prose.

## Implemented acceptance

- Contract tests reject extra keys (including facts, caveats, private text, and arbitrary prompts),
  invalid pages/scopes, duplicate JSON keys, coercive numeric selectors, and oversized payloads.
- Evidence tests reject mismatched/tampered manifests, files, runs, seasons, timestamps, and scopes
  before any provider/cache call, and cover all seven server-side page builders.
- Provider tests use an injected fake transport and cover auth secrecy, retry policy, timeouts,
  response limits, malformed JSON, caching, concurrency, rate limiting, and safe errors.
- Server tests cover same-origin/approved-LAN-token protection and prove insight work does not take
  the optimizer lock.
- Frontend tests prove hosted mode makes no provider request, explicit opt-in is required, filter
  changes invalidate stale prose, failure preserves deterministic facts, and returned markup is
  inert text.
- Every one of the eleven routes has a deterministic panel. Only Summary, Fixture matrix, Players,
  Player analytics, Team analytics, Player prediction vs actual, and Team prediction vs actual can
  invoke the remote renderer. Next GW suggestion, Optimizer audit, Plan Builder, and Squad Draft are
  local deterministic-only routes.
