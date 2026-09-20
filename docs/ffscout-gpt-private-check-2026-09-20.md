# FFScout private bilingual quality check: blocked by OpenAI 429

The owner authorized the next private GPT check after the FFScout capture check.
This is not public source-reuse approval or scheduler/deployment activation. It
uses retained source text only; no additional X request or FPL import occurred.

## Scope and executed attempts

Five retained `ffscout_team_news_v1` records were selected before execution:
three substantive club updates (Fulham, Everton, Manchester City) and two
promotional/article teasers. The latter test whether a summary invents details
absent from the post. IDs, source hashes and actual start times are pinned in
private write-once start receipts. All original publication/knowledge times stay
unchanged; September 18 news is not relabelled as a September 20 update.

The planned ceiling was $0.02 of monthly OpenAI reservations in the existing
private store, with no ledger reset. Each run stopped on its first failed story:

| Private run | Result | API attempts | Successful summaries |
|---|---|---:|---:|
| `ffscout-gpt-private-20260920T162256Z` | Transport unavailable under the original 5-second read timeout | 2 | 0 |
| `ffscout-gpt-private-20260920T162834Z` | HTTP 429 twice with the longer bounded read timeout | 2 | 0 |

An intervening unauthenticated GET of the OpenAI models endpoint returned the
expected HTTP 401 in 0.375 seconds. It submitted no news and requested no model
generation. This establishes connectivity, not authenticated generation access.
The second run observed HTTP 429 after 6.203 and 5.625 seconds. The earlier
5-second read setting could mask such responses as transport failures; the
original failures cannot themselves be assigned an HTTP status retrospectively.

No further paid attempts followed the repeated 429. The adapter did not retain
the provider's `error.code`, so the specific quota/rate/spend cause is **unknown**.
[Official OpenAI error documentation](https://developers.openai.com/api/docs/guides/error-codes)
distinguishes these conditions. Account credits and applicable project/organization
limits need checking before another test. X credits do not fund OpenAI requests.

## Bounded transport repair

Only optional news transport changed: OpenAI read timeout is now at most 20
seconds; X remains 5 seconds. Both attempts still share the existing 30-second
deadline, at most one retry, size bound and pre-request cost reservation. A retry
uses the remaining deadline rather than another full 20 seconds. Model snapshot,
prompt hash, output schema, token bound, source filter and monthly caps are unchanged.

Offline regressions verify separate provider read bounds and a simulated slow
first attempt leaving only 9 seconds for the retry, with both attempts reserved.
79 capture/environment/publisher tests pass; Ruff, changed-file formatting and
strict mypy of the capture module pass. Live bilingual fidelity, promotional
filtering and successful-summary cache replay remain **unverified**, since zero
summaries were produced. The private harness's cache assertion had no successful
record to exercise and is not evidence of a live cache-replay pass.

## Preserved evidence and remaining boundary

- Existing 20 raw observations and 2 capture status records hash-identical before
  and after both checks; SQLite integrity passes. No inferred player identities.
- Summaries remain empty. X reservations remain $0.10. OpenAI reservations total
  $0.004308 across four attempts. These are conservative local reservations, not
  an actual provider invoice or confirmation that failed calls were billed.
- No credentials, raw posts or private receipts enter Git/public exports. No
  scheduler, R2 data, dashboard generation, model, forecast or optimizer changed.
- Source correction/deletion reconciliation and public reuse review remain open
  as documented in the earlier capture report. The recent-search cursor only
  discovers newer matches; it does not revalidate old posts. Public activation
  remains disabled. No fabricated summary or manual substitute was published.

Receipts are under `D:/Personal/fpl-operations/news/`; SHA256:

```text
162256Z-start:  01c296fca0647c7369d05639501486bf1af168d7b87fd1caacf728a9d8330d0d
162256Z-result: e455f50d7d94560564e4f92dae9db9fb697d178d9e483eb0479d79e59c08912a
162834Z-start:  ad349b789983b86f77a43ed280132ee7a788e8b252c8e7def58d3adb699a814e
162834Z-result: 0e79cad95968652d3636c0805a5842c4aac05a20836263b8368d997b5a0c9577
```

Starting code: `926031e`. Additive repair/report remains local on
`codex/match-preview`; no push, merge or deployment was performed.
