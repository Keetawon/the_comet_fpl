# Competitive participation V2: preregistered source interpretation

Identity: `competitive_participation_formation_precedence_v2`. This is an additive
data-interpretation capability, not a model or an override to the failed V1 pilot. The frozen
V1 parser, source payloads, timestamps, thresholds and result remain unchanged. A revised
pilot needs a new result identity, clean committed provenance and write-once output.

## Membership, not inferred player roles

Source resolution is documented in [the independent audit](competitive-participation-source-resolution.md).
Explicit `formation.lineup` identifies the starting eleven and `formation.subs` identifies
the bench after validation: exactly 11 unique XI IDs, unique disjoint bench IDs, every ID
present in the unique provider roster, and matching fixture/lineup/formation/event team IDs.
Raw player IDs must also be disjoint between fixture sides.

Absent, null or empty-object formation uses the unchanged validated V1 position fallback.
This is required by the retained Dynamo–Palace sample; malformed *present* formation must
never fall back. Neither membership path licenses tactical-role inference.

The wrapper passes an isolated membership adapter to the unchanged V1 interpreter. Bench
membership uses its temporary `Substitute` marker. A selected XI player with a stale
`Substitute` label requires a known provider `subPosition`, not an invented position. The
published raw record and provider position always come from the original unmodified payload.

Any roster entry outside the validated formation is retained as `unassigned_roster` with
`started`, `on_bench`, `appeared` and `nominal_minutes` all NULL. Absence is not proof of
withdrawal or zero exposure. The Palace–Millwall withdrawal is independently corroborated,
but there are no hardcoded fixture/player IDs in this algorithm. A future separately
versioned evidence annotation may express a confirmed withdrawal without altering raw data.

A substitution, goal or assist naming an unassigned player is a contradiction. Cards on an
unassigned roster entry remain separately labelled discipline and do not establish an
appearance. Bench cards and active/already-off second yellows retain the V1 distinctions.
Unknown dismissal actors retain V1's unavailable side duration. Unknown required IDs, event
periods/times, duplicate events and impossible active-player sequences still fail closed.

## Result types and nominal duration

The new accepted completed-result annotations are `Aggregate` and `AfterExtraTime`, in
addition to `NormalResult` and `PenaltyShootout`. They do not bypass `FullTime`, reciprocal
scores, kickoff, event-time or capture-time checks. They do not set minutes by themselves.

Three bounded real witnesses were acquired independently of the original pilot:

| Match | Provider result / clock | Explicit period evidence | Official corroboration |
| --- | --- | --- | --- |
| Arsenal–Chelsea `2614886` | `Aggregate`, 99 | Havertz goal at 97 in `SecondHalf`; no extra period | Arsenal reports 1–0 on the night, 4–2 aggregate |
| AEK Larnaca–Palace `2629009` | `Aggregate`, 126 | Sarr goal at 99 in `ExtraFirstHalf`; later extra-period substitutions | Palace reports 2–1 after extra time |
| West Ham–QPR `2611112` | `AfterExtraTime`, 122 | Castellanos goal at 98 in `ExtraFirstHalf`; later extra-period substitutions | West Ham reports an extra-half-hour win |

Primary sources:
[Arsenal report](https://www.arsenal.com/news/report-arsenal-1-0-chelsea-4-2-agg-adFAC9n0cN6b),
[Palace report](https://www.cpfc.co.uk/news/match-reports/live-blog-match-report-highlights-larnaca-crystal-palace-march-2026/),
[West Ham report](https://www.whufc.com/en/news/matchday-gallery-or-hammers-face-qpr-in-fa-cup).

All three SDP event requests and three official report requests returned HTTP 200. Exact
bytes, hashes, URLs, capture times and original metadata witnesses are retained in
`D:\Personal\fpl-operations\verification\competitive-participation-result-types-20260907T080304Z\capture-report.json`.
No match identifiers were guessed; all came from retained season-2025 metadata.

These cases establish why `Aggregate` is not synonymous with 90 minutes. Nominal duration
still requires V1's clock/period witnesses: clock at least 120 **and** an explicit extra-period
event for 120; clock 90–119 without an extra-period event for 90. An `AfterExtraTime` annotation
without corroborated 120-minute evidence yields NULL duration, never 90 by default. Unknown
or contradictory period evidence remains unavailable. Shootout result alone proves neither
extra time nor 120 minutes. Goals/assists must identify a known selected fixture roster player;
own-goal actor identity can belong to the opposite side and is not fuzzily reassigned.

Nominal intervals remain clipped period-clock durations, not provider-reported minutes,
FPL-rounded minutes or verified physical elapsed time. A late substitute can appear with
nominal zero minutes. Exact match end timestamp and precise rest hours remain unavailable.

## Provenance and downstream safety

`parse_participation_v2` requires explicit source `known_at` and separate
`interpretation_known_at`; it retains raw bundle `known_at` unchanged and emits `available_at`
as their maximum. Event capture cannot follow the complete source bundle. Callers must use
that complete availability boundary for strict prospective consumers, never the historical
kickoff as a substitute for capture time. This wrapper is not registered in `PointInTimeView`
or any production forecast/optimizer path.

Every source version remains independently retained by the collector. Unresolved fixture
evidence quarantines its dependent club/player workload scope, not unrelated program phases.
A missing match/identity/duration is never silently removed from expected-coverage denominators.
No average filling, historical timestamp rewriting, model scoring or production promotion is
part of this V2 source capability.

## Offline acceptance before a new pilot

Synthetic tests cover the double-starter/formation case without actual player IDs; source
immutability; missing versus invalid formation; unique reciprocal identities; unassigned
participation contradictions and retained off-field cards; inherited substitution/dismissal
semantics; late appearances; regulation/extra-time/aggregate/shootout distinctions; NULL
durations; explicit interpretation availability; and exact frozen V1 parser SHA256.
The revised runner must also preserve the original validation tolerances and complete fixture
coverage accounting. This document records no revised pilot pass or downstream model result.

The guarded offline runner is `python -m fpl.jobs.audit_competitive_participation_v2` with
explicit `--db`, `--retained`, `--source-resolution` and new external `--results` arguments.
It reuses the raw-only capture module's read-only retained-evidence verifier, never its
network collector. It reinterprets only the original 13 complete bundles; all 39 original
responses, source-resolution bodies, source files and original database are hash-checked.
It holds a read-only database connection throughout and verifies no WAL, clean Git and
unchanged hashes before publication. It reuses the frozen selected-club PL validation
tolerances while reporting every opposing-side unknown roster entry separately: a selected-
club pass is never described as globally complete all-player participation.
