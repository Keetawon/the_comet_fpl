# Competitive participation pilot: Arsenal and Crystal Palace

This is a bounded **data-only** pilot, not a model evaluation. Its contract is
`config/competitive_participation_pilot.yaml`. Freeze that config, the implementation and its
tests in a clean commit **before new pilot collection**. Retain the Git SHA and config/source
hashes in a new timestamped report; neither earlier probes nor frozen evaluations are overwritten.
No full-season participation backfill, tactical-role inference, forecasts or model fitting is
licensed here.

## Population and stopping bounds

Select competitive fixtures involving Arsenal (`team_code=3`) or Crystal Palace (`31`), season
2025-26 / provider season 2025, with UTC kickoff in `[2025-09-13, 2025-10-06)`. Competition IDs
8 (PL), 1 (FA Cup), 2 (League Cup), 5 (UCL), 6 (UEL) and 1125 (Conference) were discovered from
official provider evidence, not guessed; see `competitive-workload-source-audit.md`. Friendlies
and every other competition are excluded. A match involving both selected clubs is captured once.

The retained deterministic PL crosswalk identifies these eight required matches:

| Club | PL match IDs |
| --- | --- |
| Arsenal | 2561926, 2561936, 2561952, 2561956 |
| Crystal Palace | 2561929, 2561943, 2561948, 2561960 |

Retained European anchors are UCL 2601789 (Athletic-Arsenal, September 16) and Conference
2602203 (Dynamo-Palace, October 2). They are **not** an exhaustive competitive fixture list.
Discover the complete bounded window before declaring coverage, using only verified query
parameters or bounded sequential pagination. Retain raw metadata pages even when they include
outside-window records, but fetch lineups/events only for selected matches. A proved empty window
for a competition is valid; an unsupported filter, incomplete pagination or an assumed sort order
is not proof of absence. Compare the PL inventory to the eight retained crosswalk matches exactly.

Stop with a coverage blocker if discovery or selected fixtures exceed 100 distinct provider
requests or 24 matches; do not silently truncate. Each HTTP attempt remains subject to the existing
`config/sources.yaml` SDP pacing, timeout and bounded-retry policy. Failed retries are recorded and
do not disappear from request counts. No aggressive parallel requests or default schedule changes.

## Identity, versions and evidence time

Keep provider competition, season, match, team and player IDs as separate identities. Resolve a
selected-club player only through a unique season-qualified FPL `opta_code` equal to
`p{provider_player_id}`, retaining the FPL permanent `code`, registry provenance and anchor method.
Do not fall through to names, `element_id`, shirt number or fuzzy matching. An unresolved person
retains their provider identity with NULL FPL code and an explicit error; they cannot enter an
FPL-keyed feature. Opponents outside the FPL registry are retained by provider identity, not forced
into invented FPL identities.

Require unique lineup IDs within a side, no player on both sides, matching lineup/event/fixture
team IDs, and every required event actor in the correct roster. The fixture owns club membership.
Corroborate selected clubs with prior FPL fixture facts where available, never with an end-season
or current player-club assignment. An unavailable corroborating fact is reported as unavailable,
not fabricated. A conflicting prior fact is unresolved unless explicit, temporally valid transfer
evidence resolves it. Example already observed: Guéhi `209036` plays for Palace before the October
2025 European fixture, although his end-season FPL player dimension assigns Manchester City.

Retain exact received raw bytes, request/HTTP metadata, actual capture timestamp and SHA256 for
every response, including errors and revisions. For the frozen pilot derivation, select the first
successful structurally valid response per endpoint **in this pilot**, ordered by actual capture
time, request sequence and SHA as a final deterministic tie-break. Retain later responses without
substituting a version because it matches FPL better. Record every chosen endpoint payload and
the combined version identity; bundle `known_at` is the maximum of fixture metadata, lineups,
events and the identity evidence used. Earlier probe files are independent diagnostic anchors,
not silently substituted for missing new pilot captures.

This September 2026 capture of 2025 events is retrospective development evidence. Never rewrite
`known_at` or weaken strict PIT. Future strict workload observations require both `known_at <=
cutoff` and proof the match ended before cutoff: a corroborated explicit end timestamp, or a
completed-match capture already retained before cutoff. Kickoff alone does not prove completion;
the last substitution/card timestamp is only a lower bound on match end. Without an independently
verified end timestamp, **exact hours of rest stay unavailable**. A completed capture can prove
eligibility conservatively but is not the actual whistle time.

## Participation and nominal duration semantics

Keep `started`, `on_bench`, `appeared`, provider position, formation and discipline separate.
Exactly 11 non-`Substitute` lineup players start each valid side; bench size is not fixed. Broad
provider positions or a missing formation do not license inferred roles. A complete lineup plus
validated events can establish an unused substitute; a missing endpoint cannot establish DNP.

There is no direct player-minutes field in the retained samples. Derive an explicitly named
**nominal-period-clock duration**, never alias it to FPL `minutes` or physical elapsed time:

1. Parse raw `time` only as an unsigned decimal integer and retain its raw value, period and
   aware event timestamp. Unknown formats/time zones/periods are unresolved. A required field event
   timestamp must be no earlier than kickoff and no later than its actual capture; separately
   retained pre-kickoff bench discipline cannot be used as field participation. The period's minimum
   nominal minute is 0, 45, 90 or 105; an earlier displayed minute is inconsistent. Clip a valid
   minute only at that period's endpoint: 45, 90, 105 or 120 respectively. This excludes stoppage
   time by definition, without altering the retained raw event.
2. Start the XI at nominal minute zero. Process events in aware timestamp order, with equal-time
   actor changes checked as one batch rather than arbitrary input order. For a substitution the
   off-player must be active and the on-player an eligible inactive roster player. Close/open
   intervals atomically; contradictory same-time actor changes, repeated events or impossible
   state transitions invalidate the required reconstruction rather than being silently dropped.
   A player substituted on and later off has their actual interval retained. Re-entry after an
   earlier exit is not permitted in these competitions.
3. A `Red` or `SecondYellow` closes an interval **only when the identified player is active**.
   Cards to bench or already-off players remain separate discipline, do not create an appearance
   and do not terminate another player's interval. A bench dismissal makes that player ineligible
   to enter later. An unknown/null potential dismissal actor makes that side's durations unavailable;
   it cannot be assumed to describe a staff member. Unknown non-dismissal actors remain explicitly
   unattributed. Keep the first yellow and subsequent second yellow separately; do not count two
   dismissals. A duplicate/conflicting dismissal record is unresolved.
4. Accept completed matches only with `period=FullTime`, known `resultType` (`NormalResult` or
   `PenaltyShootout`), consistent reciprocal scores and a past aware kickoff. Contradictory states
   remain unresolved even for old fixtures. Parse final match `clock` as an unsigned integer.
   Regulation closes at nominal 90 only when final clock is 90..119 and no event has an explicit
   extra-time period. Close at nominal 120 only when final clock is >=120 and at least one timed
   event explicitly has `ExtraFirstHalf` or `ExtraSecondHalf`. Neither a shootout nor a high clock
   alone proves extra time. Missing clock, a smaller completed clock, an extra-time event with
   final clock <120, or final clock >=120 without extra-time event evidence leaves durations
   unavailable. This intentionally does not force silent 90/120 inference for under-evidenced
   matches. Shootout events add no minutes or
   field appearances. Any new status vocabulary requires a documented contract amendment, not
   an inferred match-completion rule.
5. Sum non-overlapping valid intervals. A substitute entering in second-half stoppage time has
   `appeared=true` even if clipping yields a nominal duration of zero. Never infer appearance from
   `duration > 0`. Unknown duration remains NULL; average filling and zero filling are forbidden.

Retained PL 2645195 is an independent validation example outside this pilot window: starters
agree 40/40 and appearances 31/31, but nine outgoing starters' displayed intervals exceed FPL
minutes by one (Rice off at 68 versus FPL 67). Do not subtract one or otherwise repair raw values
to force agreement. Keep the two measures and their differences. The Conference anchor supplies
a real second-yellow case (Sosa `218364`, minute 76); the UCL anchor includes stoppage-time entries
and an opponent entering at 61 then leaving at 81. Missing formations remain missing.

## Frozen validation and reporting

These are data-quality gates, not accuracy claims about a fitted model:

- Discover 100% of the bounded selected fixture inventory, reconcile all eight PL IDs, and obtain
  complete lineups and events for 100% of selected completed matches. Report pending, unavailable,
  inconsistent and unresolved responses separately. Zero exit status is not a completeness witness.
- Require exact FPL identity for 100% of selected-club lineup players; no unresolved required
  identity/status or raw-hash failures. Structural roster/actor checks apply to both provider sides.
- On the eight PL matches, require 100% selected-club starter and appearance agreement with the
  retained FPL fixture facts. Validate the union of provider roster and FPL appeared/started players,
  so a missing provider participant cannot vanish from the comparison denominator. FPL's wider
  zero-minute roster does not imply those players were on the match bench.
- Compare durations over the union of selected-club players who appeared by SDP events/lineup or
  have positive FPL minutes. Require 100% measured duration coverage, at least 95% with absolute
  difference <=2 minutes, and mean absolute difference <=1 minute. Missing paired data fails
  coverage; do not discard it to improve agreement. Report signed differences, quantiles, maximum,
  per-match/per-club counts and every exception. Never tune the derivation from these results.
- Report non-PL reconstruction completeness and every unavailable duration separately. A missing
  formation does not fail the participation pilot, but blocks any claim of complete formation or
  role evidence. Passing PL agreement does not validate unknown extra-time conventions elsewhere.

Retain fixture/side/player-grain output, original and normalized times, interval endpoints,
discipline context, FPL comparison values, identity methods, selected payload hashes, missingness
reasons and capture lineage. Report coverage by competition, club and endpoint including empty
inventories. Record all request attempts, failures, byte hashes, implementation/config SHA256,
clean Git SHA, UTC run time and any read-only reference database hash. Use a new timestamped
directory and an explicit operational destination for any authorized writes; never switch the
default database or overwrite frozen artifacts. A pass licenses only this participation data path;
it does not establish workload predictive value, a Player Role Engine or production readiness.
