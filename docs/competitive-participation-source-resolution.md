# Competitive participation: additive source resolution

This 2026-09-07 investigation explains a retained source contradiction; it does **not**
rerun, repair or relabel the failed participation pilot. No database, model or default was
changed. The prior pilot remains 12/13 valid interpretations against its frozen 100% gate.

## Independent official evidence

For Palace–Millwall on 16 September 2025, Palace's official team-news article explicitly
identifies Max Crocombe's warm-up injury and Steven Benda as his replacement. It lists the
final starting eleven and bench for both clubs. The official post-match report independently
within the same club confirms Benda's involvement from the first minute and the final XI.
These are two editorial accounts from one club, not two independent publishing organisations.
The official match page's URL contains the exact SDP match identifier `2603048`.

- [Official Palace team news](https://www.cpfc.co.uk/news/first-team/team-news-palace-make-four-changes-for-millwall-cup-clash/)
- [Official Palace match report](https://www.cpfc.co.uk/news/match-reports/live-blog-report-highlights-crystal-palace-millwall-september-2025/)
- [Official exact match page](https://www.cpfc.co.uk/matches/men/elc/2025-26/crystal-palace-vs-millwall-2025-09-16/2603048/)

All three returned HTTP 200 to the local environment. A supplementary Southwark News
manager-interview page returned HTTP 403; its refusal was retained, not bypassed. The
resolution does not depend on that page, and the more specific suggested toe injury is
not needed or licensed from its blocked local response.

Editorial names corroborate the football interpretation manually; they do not create a
name-based provider/FPL join. Player identifiers below come directly from the retained SDP
roster, and future FPL mapping remains exact, season-qualified `opta_code` only.

## Retained provider evidence

| Evidence | Palace, team 31 | Millwall, team 103 |
| --- | --- | --- |
| Raw roster | 20 unique players | 21 unique players |
| Non-`Substitute` position labels | 11 | 12 |
| Explicit formation XI | 11 unique roster-known IDs | 11 unique roster-known IDs |
| Explicit formation bench | 9 disjoint roster-known IDs | 9 disjoint roster-known IDs |
| Roster outside formation XI/bench | None | Crocombe, `108801` |
| Formation goalkeeper | Benitez, `121709` | Benda, `428971` |

Both formation XIs and benches agree with the official team-news account. All retained
substitutions, scorers, assists and cards refer to the formation XI/bench. No goalkeeper
substitution or event for Crocombe explains an in-match appearance. The independently
documented pre-kickoff replacement explains why a non-substitute position label survives
for a player absent from the final formation.

The evidence supports a **new, explicitly versioned formation-precedence interpretation**,
not a special-case edit for these two goalkeepers. `players[].position` is a broad provider
label, not a universally reliable `started` boolean. Explicit formation membership is
empirically corroborated as the observed XI here; no published universal provider contract
was found. Neither source establishes an accurate tactical role or measured elapsed minutes.

A read-only structural inspection of all 26 retained pilot team sides found:

- 24 explicit formations; all have 11 unique roster-known XI IDs, a disjoint known bench,
  reciprocal side IDs and no event actor outside the formation roster.
- 23/24 explicit formation XIs equal the position-derived XI. The sole mismatch is Millwall.
  All 24 explicit formation benches equal the position-derived bench.
- Both sides of Dynamo–Palace `2602203` have no `formation.lineup`. Therefore an unconditional
  formation requirement would wrongly reject an otherwise valid original-pilot fixture.
  Any V2 must explicitly retain the validated V1 position fallback when formation is absent,
  while never using fallback to hide an invalid or contradictory *present* formation.

The old official Premier League bundle also includes a position-derived formation helper
marked `isFallback`. This corroborates the existence of a fallback concept, not a fully traced
public UI precedence contract; it is not the sole authority for the proposed interpretation.

## Required V2 boundaries

Before any revised collection/interpretation run, freeze a new identity, config and tests:

1. Validate both sides, exact provider team IDs, 11 unique XI IDs, roster membership and
   disjoint unique bench IDs. Missing formation may use the unchanged validated V1 fallback;
   malformed or contradictory present formation must fail closed.
2. Treat explicit formation as the XI/bench selector, retaining all original raw fields and
   hashes. Keep source-position labels and selected membership separately in provenance.
3. Retain every roster-only player. Absence from formation alone does not prove withdrawal,
   non-appearance or zero minutes. Unknown participation/exposure stays NULL. A confirmed
   withdrawal requires its own source evidence, as in this independently corroborated case.
4. Validate event participation against the selected roster and active-player sequence.
   Bench cards are discipline, not appearances; second yellows terminate participation only
   for a player who is active. Contradictory event participation must not be discarded.
5. Keep nominal event-duration distinct from FPL minutes and physical elapsed time. Shootouts
   do not imply extra time. Unknown end time prevents falsely precise rest-hour features.
6. Retain actual capture/interpretation knowledge times. These September 2026 discoveries
   cannot become historical September 2025 deadline knowledge.
7. Quarantine unresolved fixture/workload scope explicitly; do not halt unrelated scientific
   phases or claim complete workload coverage for the affected player or club.

No V2 interpretation result exists in this source-resolution document. The source evidence
licenses a bounded implementation and validation proposal, not automatic workload/model use.

## Durable evidence

New persistent directory:
`D:\Personal\fpl-operations\verification\competitive-participation-source-resolution-20260907T075630Z`

`capture-report.json` retains all four requests/responses, URLs, UTC capture times, relevant
headers, exact raw body paths, byte counts and SHA256. There were no retries or new SDP
requests. Official source captures were acquired at 07:57:10–07:57:13 UTC on 2026-09-07.

| Source body | SHA256 |
| --- | --- |
| Official match report | `5c6369d10949650d409a0fec0eff458fcc5916c2c1b5030d0279bffe0eac2885` |
| Official exact match page | `56cb5af209b606ebcda5a7ac4f26b759252fe99fa2bd85427eab9bb4850e533e` |
| Official team news | `91c3ff1966b74fbc8018b15068b63156fbff024a4a436ec8eea787ba23863324` |

`source-resolution.json`, SHA256
`2fbf2695f0fcf8e1170b863d42ad3432882961c1fdfc5ab33d0b6f88f7a155e3`, retains
all 26 structural comparisons, exact provider IDs, source confidence and interpretation
boundaries. Its unconditional formation-check aggregate is false because the two Conference
sides have no formation; this is reported explicitly above, not concealed as full coverage.

All 39 original pilot raw bodies were rehashed successfully. The original pilot result
remains SHA256 `f34b0c978b6de9454bbd1bb52cb2d2faabee6347b8baa16403bca773b56bf411`;
its independent audit remains `84568a52959f87151c6419ac6c85985d868179e959edde32453abfd8fe5409a2`.
The original pilot directory, artifacts, parser and thresholds were untouched.
