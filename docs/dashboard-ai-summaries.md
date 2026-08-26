# Evidence-bound dashboard insight summaries

Status: pre-implementation contract, frozen 2026-08-26. The language model is an optional renderer,
not an analytical authority or autonomous agent.

## Product rule

Every dashboard route gets an immediate deterministic insight panel. Public analytical routes may
also show an explicit **Explain with AI** action when a trusted local provider is configured.
Nothing calls a remote model automatically on page load or filter changes. Changing vintage or
scope immediately rebuilds the deterministic facts and marks prior AI prose stale.

Remote v1 scope is limited to Summary, Fixture matrix, Players, Player analytics, Team analytics,
Player prediction vs actual, and Team prediction vs actual. Next-GW plans, Optimizer audit, Plan
Builder, Squad Draft, manager imports, squads, bank, purchase/selling values, capture identifiers,
and custom-plan state remain deterministic-only. They still have a summary panel; their data is
never sent to a third-party model.

AI output is labelled "AI-generated - verify cited metrics". It may prioritize and explain facts;
it may not calculate a metric, probability, trend, causal claim, recommendation, or model verdict.
Canonical numbers remain rendered from the local fact packet, not copied back from model prose.

## Z.AI use

Z.AI can implement the first provider through its general Open Platform API, whose documented
OpenAI-compatible base URL is `https://api.z.ai/api/paas/v4/`. The coding-tools endpoint is not the
dashboard endpoint. Z.AI's subscription terms state that GLM Coding Plan quota is for supported
coding tools and may not be used as general application/API quota without a separate agreement;
therefore a large Coding Plan balance does not by itself authorize dashboard calls. Use a general
Open Platform API key/balance and confirm the current account terms.

The API key exists only in the trusted Python process environment. It is never put in Vite source,
`VITE_*`, static JSON, a URL, browser storage, logs, cache records, or Git. The hosted dashboard is
static and therefore keeps deterministic summaries until a separately authenticated, rate-limited
server proxy is deployed. Direct browser-to-provider calls are forbidden.

The adapter is provider-neutral. Suggested environment variables are
`FPL_INSIGHTS_PROVIDER=zai_glm`, `FPL_INSIGHTS_API_KEY`, `FPL_INSIGHTS_MODEL`, and an optional
server-owned HTTPS base URL. The request cannot choose a key, provider, model, base URL, system
prompt, or free-form user prompt.

## Browser-to-server contract

`POST /insights/summary` accepts an exact-key, Pydantic-validated
`fpl.insight-summary-request` version 1:

- a public-page enum;
- manifest content hash, run id, season, and `as_of`;
- a bounded typed display scope;
- at most 24 unique facts with safe stable ids, kind, a statement of at most 240 characters, and
  source read-model names;
- at most eight explicit caveats;
- at most 16 KiB total body.

There is no arbitrary chat field. Facts are limited to already-published scalars, allowed sums,
ranks/frontiers, null/coverage counts, and caveats. Requests containing manager/private identifiers,
financial state, squads, filesystem paths, authorization material, or control characters fail
closed.

The success response identifies schema/version, source (`provider` or `cache`), provider, model,
prompt version, cache key, and generation time. It contains a short headline and at most four
plain-text insight items. Every item cites one or more allowlisted input fact ids; unknown or missing
citations fail validation. React renders text, never provider HTML or executable Markdown.

`GET /insights/status` may expose only enabled state, provider, model, and prompt version. It never
returns credentials or a server base URL. Disabled, timed-out, rate-limited, malformed, or failed
provider calls return a stable safe error code and the UI keeps the deterministic summary.

## Provider controls

- Use the general chat-completions API with structured JSON output where the configured model
  supports it. HTTPX and Pydantic are already project dependencies; no provider SDK is required.
- The fixed system prompt treats facts as untrusted data, uses cited facts only, performs no new
  arithmetic, distinguishes past form/future forecast/finalized actual, and repeats
  development-only caveats.
- Use bounded connect/write/read/pool timeouts, a hard overall deadline, one retry only for transport
  failures or 429/502/503/504, a capped response body, no redirects, a small rate limit, and
  single-flight by cache key. Never retry authentication or malformed output.
- Cache key is SHA-256 over the canonical request plus provider identity, model, and prompt version.
  Cache only validated response/provenance under the ignored plan-server base; never cache keys,
  raw provider bodies, request facts, or failures.
- Do not log request bodies or upstream bodies. The insight service must not acquire the optimizer
  run lock and must work independently of solver readiness.

## Deterministic summaries

The deterministic path is authoritative and network-free. Each page-specific pure TypeScript fact
builder returns concise source-linked facts and caveats from its visible scope. It follows all null,
vintage, horizon, probability, form/forecast, and outcome-finality semantics. Empty pages explain
why there is no evidence instead of producing generic prose.

## Acceptance

- Contract tests reject extra keys, invalid pages, duplicate/unknown fact ids, oversized payloads,
  private content, arbitrary prompts, and invalid citations.
- Provider tests use an injected fake transport and cover auth secrecy, retry policy, timeouts,
  response limits, malformed JSON, caching, concurrency, rate limiting, and safe errors.
- Server tests cover same-origin/approved-LAN-token protection and prove insight work does not take
  the optimizer lock.
- Frontend tests prove hosted mode makes no provider request, explicit opt-in is required, filter
  changes invalidate stale prose, failure preserves deterministic facts, and returned markup is
  inert text.
- Every route has a deterministic panel; only the allowlisted public analytical routes can invoke
  the remote renderer.
