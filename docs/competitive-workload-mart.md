# Competitive workload: pure development read contract

This document specifies a future operational mart boundary, not an existing populated table.
`validate.competitive_workload_view` currently provides immutable typed inputs and a pure
in-memory retrospective query. It writes no database, fetches nothing, and fits no model.
Real operational data must not be inserted until the separately amended participation pilot
has passed its validation. No production/default/optimizer path is changed.

## Grain and retained identities

Keep fixture identity `(provider, competition_id, season, match_id)`, permanent player `code`,
provider player/team IDs, and stable `team_code` separately. Friendlies and unknown competition
IDs are rejected; the only supported SDP competition IDs are8,1,2,5,6,1125. A query defaults to
all six. A deliberately narrower requested competition set is explicit scoped evidence and must
not be described as all-competitive workload.

`CompetitiveMatchVersion` retains a WHOLE metadata/lineups/events interpretation: capture ID,
capture known time, interpretation identity and actual known time, content SHA256, completion
and endpoint completeness, maximum retained event time, nullable independently verified end time,
nullable extra-time status, all player observations and fixture errors. Player nominal duration,
starter status and appearance are separately nullable. Entering in stoppage time may legitimately
mean appeared=true with zero nominal minutes. A complete valid roster can prove nonselection;
an absent endpoint or unresolved required identity cannot prove DNP.

Foreign-opponent players need not have an FPL identity. Exact provider fixture-side mapping
distinguishes them from unresolved players on a scoped FPL club. No name/fuzzy matching is allowed.

## Version policy

The view requires one explicit frozen interpretation identity. Among its COMPLETE, provider-final captured
bundles for a fixture, select the earliest actual capture-known time, then capture ID, then
payload SHA256, independent of player/stat values. Incomplete or not-yet-final earlier bundles do not
win. A complete selected bundle with an interpretation error remains unknown; a later cleaner
version must not replace it opportunistically. Revisions are retained in the input store, not
summed as additional fixtures. No individual player's later version can leak into an earlier
whole-match bundle. An interpretation amendment is a new explicit evidence snapshot identity,
not an invisible overwrite or a fabricated earlier known time.

## Explicit retrospective event-time boundary

The authorized retrospective policy admits eventual provider-final matches with kickoff strictly
before the query cutoff and no match ID belonging to the excluded target-GW batch. It additionally
rejects a retained event timestamp OR a verified whistle at/after cutoff. A rejected fixture
remains in the expected inventory and makes the affected window unknown; it is not filtered away
into a zero. All time instants are aware and half-open window boundaries are fixed.

Historical final status with a later backfill is NOT proof that a match had ended at a real
deadline. Without a verified whistle, `completion_time_proxy=true` records that limitation even
when every retained event precedes cutoff. Missing maximum event time does not establish the
absence of later events. This deliberately weaker historical capability cannot license live or
in-progress source use. Strict prospective workload would separately need deadline-known capture
and conservative completion proof; no retrospective flag is added to `PointInTimeView`.

## Coverage must prove absence

Inputs include typed catalogue-discovery coverage intervals for each requested competition and
club, with source identity, actual known time, completeness and per-scope errors. A proved empty
catalogue interval can establish no fixture. A missing competition page, failed pagination,
pending fixture, unavailable complete capture or contradictory interpretation makes the relevant
72h/7d/14d window unavailable. Per-fixture errors retain their identities and reasons.

Player workload additionally requires explicit trusted membership intervals whose union covers
the WHOLE requested window, with exact stable clubs and retained sources. Do not infer intervals
from a first observed appearance, an end-season player registry, or the absence of another club.
Overlapping contradictory clubs fail closed. Genuine transfers preserve permanent-code history
across both clubs; missing coverage for the previous club is unknown, not a zero or a dropped
stint. An unverified newcomer registration interval cannot generate a false rested/zero row.

Catalogue completeness is an upstream evidence assertion, not inferred by this reader from its
match list. The future storage loader must reconcile each complete coverage witness to its
retained full discovered fixture inventory before constructing these inputs.

## Output definitions

For each `[cutoff-hours, cutoff)` window, hours72/168/336, publish:

- nominal-period-clock minutes, starts and appearances;
- Monday–Thursday UTC nominal minutes and appearances (a fixed midweek definition);
- appearances in matches with explicitly corroborated extra time;
- expected fixture identities, missingness reasons and the completion-time-proxy flag.

Missing numerical observations affect their own metric, not a fabricated source zero. A structural
coverage/identity/completion error makes all workload sums in the affected window unknown. Complete
coverage, trusted membership and a complete valid lineup proving nonselection can produce genuine
zero minutes/starts/appearances. Derived DNP is never inferred from a zero-duration appearance.

Rest fields have explicit units and semantics. `player_kickoff_rest_hours_proxy` is the interval
from the latest known appearance kickoff, global across clubs. `team_kickoff_rest_hours_proxy`
uses the current club's latest known competitive kickoff. Both require sufficient complete14-day
coverage and returnNULL if the latest relevant event lies outside that bounded scope or remains
unknown. Neither claims exact physical recovery time. Corresponding verified-whistle rest fields
stayNULL unless that exact last match has an independently verified end timestamp. Never infer a
whistle as kickoff+90/120minutes or from a last substitution/card. A lack of matches does not mean
zero rest; workload can be measured zero while rest remains unavailable beyond the bounded scope.

Snapshot output retains selected bundle versions, catalogue/membership source evidence, cutoff,
excluded target-GW IDs, evidence class `retrospective_competitive_workload_development`, fixed
version policy and promotion=false. This evidence must propagate through any later feature cache,
candidate, full-points composition and reporting ledger. No model evaluation or filled workload
mart is claimed by this implementation.
