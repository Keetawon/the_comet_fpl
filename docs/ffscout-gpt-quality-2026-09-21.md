# FFScout GPT check after billing: API usable, publication held

The owner reported funding OpenAI billing and authorized continuing the private
retained-post check. Starting branch/HEAD: `codex/match-preview`, `fc0a215` (clean).
No X request, FPL import, forecast run, scheduler change or publication occurred.

## Execution and review

The same five source posts were used: three club updates and two promotional
teasers, captured previously on September 20. Original source publication dates
remain September 18-20. Nothing here establishes current player availability.

`ffscout-gpt-private-20260921T020130Z` returned HTTP 200 and valid bilingual JSON
for all five posts, without retries. Cache replay made zero requests and returned
identical records. The first response arrived in 3.687 seconds. Billing/429 no
longer blocked these requests; the actual account balance was not inspected.

API success was **not** a quality pass. Review found:

- Fulham's possible return became “Likely” in an English headline, while an old
  source's “today” remained unanchored in both languages.
- A Joao Pedro/Sangare article teaser became an unsupported account of discussions,
  fan/player reactions and future-selection implications. Its linked article was
  never fetched and cannot be evidence for those additions.
- Thai name rendering and FPL-transfer-versus-real-transfer wording need care.

The bounded repair tightens the news prompt's attribution, certainty, time and
unseen-link rules. A `has_substantive_update` flag is now required in provider
JSON. Promotional/non-substantive X summaries are withheld from public exports;
legacy cached summaries lacking this check default false and also remain private.
The public feed schema and official FPL text path are unchanged. This is an AI
classification, not a factual verifier or player-identity resolver.

`ffscout-gpt-private-20260921T020532Z` tested the same five posts with the new
prompt, same pinned `gpt-4o-mini-2024-07-18`, same existing budget ledger and no
retries. All five again returned HTTP 200 and valid JSON; cache replay passed.
Both teasers were correctly withheld. Nevertheless:

| Sample | Review of revised output |
|---|---|
| Fulham | Still fails: unanchored “today”, changed assessment timing/wording |
| Everton | Meaning acceptable: GW5 exclusion and uncertainty preserved; Latin-name style ignored |
| Manchester City | False negative: concrete squad update incorrectly marked non-substantive |
| Injury/article teaser | Correctly excluded; unseen details must remain unavailable |
| GW6 transfer-video promotion | Correctly excluded |

**Publication quality is not cleared.** No third paid iteration was attempted.
The two private test sources received new append-only `unapproved` status receipts
at `2026-09-21T02:07:23Z` with the explicit private-quality reason. This prevents
the test store from being accidentally exported as cleared news. Export verification
returned zero stories. Original observations, summaries and previous receipts were
retained unchanged. A source timestamp was not refreshed by summarizing its text.

## Evidence and budget

The private SQLite store contains 20 original observations and 10 versioned
summaries (five per prompt). Source/raw hashes are unchanged; integrity passes.
The new prompt SHA256 is
`c74542f0fb7cc4c4bb836ddf13032687ccd2055553e7fd3eb4703bd188ca532b`.

OpenAI reserved $0.005386 + $0.006308 for these two checks; total including prior
failed attempts is $0.016002, below the unchanged $0.02 test ceiling. X reservations
remain $0.10. These are local upper-bound reservations, **not billed costs**.

Private receipts under `D:/Personal/fpl-operations/news/`, SHA256:

```text
020130Z-result: 389214d22ccaa4fbbe5c61585535dcece0fea846b8432847709f9e41863b59be
020532Z-result: 8330f266ff844889efe41ccfa129d709b1a8a0439ad4106b93e21a5ff4922a9f
020723Z-review: f1b8901fc8d3cd078909899ed714c35f08b9afab93f6482da70940b5734e3084
```

92 offline tests pass: 81 news capture/environment/publisher tests and 11 relevant
dashboard/refresh/R2 news integration tests. Ruff, changed-file formatting and
strict mypy on three changed source modules pass. The first local test invocation
had a missing temporary-parent directory; it was corrected before successful runs
(not an inherited repository failure). No real news was added to offline fixtures.

Model/features/optimizer/config/results/AGENTS are unchanged from the starting
commit. Work is retained locally; no push, merge, deployment or new public assets.
Automatic news capture remains disabled. Besides the documented quality failures,
source reuse and edited/deleted-post reconciliation remain activation prerequisites.
