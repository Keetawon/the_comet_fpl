# Broad starting-role history V1: fixed algorithm, not an evaluated model

Identity: `retrospective_broad_starting_role_transition_v1`.
Evidence class: `retrospective_competitive_role_development`.
This pure, deterministic development component has no database access, network, scoring,
production integration or promotion. Its algorithm is fixed before historical fitting;
the full-capture coverage audit must precede a separate formal evaluation registration.
There is no retained role-performance result yet.

## What the four labels mean

Only the exact raw provider labels `Goalkeeper`, `Defender`, `Midfielder`, and `Forward`
on independently interpreted `started=True` rows become GK/DEF/MID/FWD observations.
These are broad starting-position labels, **not** spatial/tactical role ground truth.
Formation validates membership upstream; target formation, coordinates, bench labels,
substitute `subPosition`, FPL season-end position, and actual target minutes are not inputs.
An unknown label or unknown starting status remains unmeasured, not a categorical zero.

The forecast is **P(broad role | hypothetical start)** for every player in the declared
target roster, including players who ultimately do not start or appear. It is not P(start),
P(appearance), a minutes prediction or a claim that the player belongs to the actual XI.
Only independently measured starting-role outcomes can later be scored for this conditional
task. That scored subset must never replace the full registered-player population of a
downstream minutes/points evaluation. Downstream models must marginalize these probabilities
and retain their out-of-sample provenance, not substitute the target's observed role.

## Prior state and one transition hypothesis

Within the latest **witnessed** club spell, take up to five most recent measured starting-role
observations. Newest-to-oldest weights are exactly `[1, .707, .500, .354, .250]`, normalized
over the measured observations present. They describe a mixture `q_recent`, not a hard role.

The fold-global prior `p_global` is the empirical frequency of all eligible earlier starting
labels. Only a completely empty role history uses the uniform four-category prior. No
additional smoothing or full-dataset normalization is introduced.

Count transitions between successive measured starts for each player within the same
observed club spell. Ordinary bench appearances/nonappearances are not starting-role targets
and do not create transitions. A possible/actual start with an unmeasured role breaks the
transition chain: the model must not pretend the two surrounding measured starts were
consecutive. Both endpoints must precede the target cutoff. Pool the 4×4 table across players:

`T[a,b] = (N[a,b] + 2 * p_global[b]) / (sum_b N[a,b] + 2)`.

With `n` measured recent starts, freeze `alpha = n/(n+2)` and predict:

`P(next role | hypothetical start) = alpha * (q_recent @ T) + (1-alpha) * p_global`.

At `n=0`, return the exact fold-global prior. The two fixed comparators are that prior and
`(onehot(last measured same-club role) + 2*p_global)/3`, falling back to the global prior
without a same-club role. No parameters, grids, hyperparameter selection or random seed are
needed by this count-based algorithm. Neither weak dimensions nor parameters may be changed
after its eventual formal result.

Retain a third, fixed diagnostic: recent-state persistence
`alpha*q_recent + (1-alpha)*p_global`, with the identical EWMA and shrinkage, but no
transition matrix. It is not a post-result threshold change. Beating the more strongly
shrunk last-role baseline alone does not isolate transition value; that attribution also
requires improvement over this matched persistence diagnostic.

## Club, season and temporal boundaries

Each observation requires a permanent FPL player code, the provider ID and exact
season-qualified Opta anchor, verified stable club code, source identity, capture ID,
payload SHA256, original capture time, and interpretation time. These declarations must be
constructed by the audited crosswalk; a matching name is never evidence. Foreign clubs or
players without the required stable mapping cannot be manufactured as usable history.

Club state resets when an earlier observed roster witness shows another club. Returning to
an old club does not recover an earlier spell across an intervening witnessed transfer.
A dated bench witness may establish the observed new club, but never invent a role target.
This does not establish continuous registration between observations: transfers involving
unobserved clubs or missing chronology remain unresolved. A target's declared club is only
the roster/schedule proxy, not authority to fill historical membership intervals. Same-club
history may carry across seasons; no future-season averages or positions are consulted.

Only completed source matches with `kickoff < as_of` enter the fold. An independently
verified match end, when available, must be strictly before cutoff. Otherwise require
`kickoff + 6 hours < as_of`, retaining `verified_end_at=NULL` and
`completion_time_proxy=True`. Every known retained event must also be strictly before
cutoff. Event/end timestamps before kickoff, or an event after a verified end, are rejected.
The six-hour bound is a conservative retrospective completion-eligibility proxy, not the
actual final whistle, a publication SLA, an exact rest interval, or prospective permission.
Source event/end values and the count of proxy-dependent history rows remain in provenance.
Every target-season/GW
PL observation is excluded as a whole even if its timestamp is inconsistent. PL source rows
require a verified FPL GW; cup/Europe rows carry no invented FPL GW. Every target fixture in
one GW is predicted from the same first-kickoff-proxy state. DGW legs remain separate. A
postponed old-GW fixture with kickoff after cutoff remains unavailable. Chronological batch
forecasts rebuild only from these prior events, never from current-GW observed starting XIs.

This separate capability deliberately permits later-captured historical observations. It
retains their original knowledge timestamps, the later-known count, source hash, maximum
prior event, and capture/interpretation maxima; none is rewritten to the historical cutoff.
It is not interchangeable with `PointInTimeView` and provides no prospective escape flag.
The caller must select one pinned earliest complete source version before construction;
duplicate revisions/player-fixture identities fail rather than becoming repeated matches.

## Audit and evaluation still required

The fixed algorithm config is `config/player_role_history_v1.yaml`. It is not the final
population/gate contract and explicitly authorizes zero formal evaluations. Before scoring,
audit the full retained capture for raw broad-label semantics, all-roster identities,
starting-label completeness, observed club chronology, and event-time-eligible history by
season/GW. Derive population eligibility from coverage alone and report missing labels.
The pre-score population rule is 2025-26's 380 PL fixtures, 38 complete-GW batches and
29,747 archive-roster forecasts, including DNPs and early uniform/prior fallbacks. The label
denominator is **all independently observed FPL starters**, not only the provider rows
that joined successfully. Its exact count must be measured, not assumed. At least 95% of
these starters must have valid, exact fixture/club/player/XI identities and a licensed raw
role label. An unknown or malformed fixture is a reported local exclusion; if season-wide
coverage fails the threshold, no formal role claim or scoring is authorized.

The new conditional-role gate requires at least 1% categorical negative-log-score lift
against the better of the two fixed baselines, no multinomial Brier regression against
the best baseline for that metric, full-season absolute class marginal bias at most .05,
and zero temporal violations. Retain class, venue, GW1-6/GW7+, and cold-start diagnostics.
This does not relax any existing Stage B/C minimum-fold or promotion requirement.
Then freeze exact folds/rows, proper categorical metrics/calibration, baselines, comparison
gates, source/config/database fingerprints, and one-run/clean-worktree controls in an additive
evaluation registration. No role fit, score, baseline win, role utility, or downstream Stage B/C
gate pass is inferred from successful source capture or these synthetic tests.

Offline tests hand-check the transition posterior, last-five kernel and shrinkage; preserve
unknown labels; exercise bench versus unknown-start transitions, transfer/returning-club
resets, same-club season carryover, late captures, duplicate revisions, future truncation,
GW/DGW/postponement isolation, full target-roster forecasting, and deterministic unit mass.
