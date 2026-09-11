# V2 retrospective backfill policy

Status: development-only evidence policy, frozen before the first real-SDP SOT outer evaluation.

## Two evidence classes

The repository has two deliberately separate time boundaries.

`strict_prospective` is the only evidence class permitted in live forecasts, optimizer inputs,
dashboard predictions, production, or promotion evidence. An observation is visible only when:

```text
event_time < prediction_as_of
known_at <= prediction_as_of
```

`retrospective_backfill_development` exists only inside the validation package. It permits a
historical completed-match observation captured after a historical prediction cutoff when:

```text
source_match_kickoff < prediction_as_of
```

The original `known_at` remains attached to the row and may be later than `prediction_as_of`.
It is never rewritten or presented as historical deadline evidence. This class can test whether a
football signal is worth prospective collection; it cannot support production promotion by itself.

## Capability boundary

The retrospective reader is a separately named validation-only type. It is not a subclass or mode
of `PointInTimeView`, is not accepted by `FeatureSource`, and exposes no generic metric selector.
Production callers therefore cannot opt in with a boolean such as `retrospective=True`.

The strict reader remains unchanged: it continues to apply both the event-time and capture-time
predicates. The existing V2 mart reader also continues to refuse historical `pl_sdp` evaluation,
because that mart selects the latest version and cannot prove historical version identity.

## Canonical provider version

For each SDP match the retrospective reader selects the earliest successfully captured complete
match-stats payload, ordered by `(fetched_at, payload_id)`. A successful payload must be an HTTP
success staged as exactly one Home side and one Away side with identified teams and numeric stats.
This test is independent of SOT presence or value. Only after selecting the payload does the reader
left-join the exact verified provider field `ontargetScoringAtt`.

Consequences:

- a later provider restatement is not selected;
- an early complete payload with no SOT stays `NULL`, even if a later payload adds it;
- an incomplete early response may be skipped in favour of the earliest complete response;
- `capture_id` is the repository's content-addressed SDP `payload_id`;
- `source_known_at` is the raw `fetched_at` timestamp;
- `payload_sha256` and the deterministic version policy are retained in provenance.

The reader joins through the measured fixture crosswalk and asserts the provider team identity
against stable `team_code`. It uses completed prior matches only. A target gameweek is predicted as
one batch from the state before its first kickoff, so no result or SOT observation from one fixture
can update another fixture in that gameweek.

## Metric licence

This policy does not license the full SDP payload for modelling. The first experiment permits only:

```text
provider: pl_sdp
provider_field: ontargetScoringAtt
local_field: shots_on_target
```

The target remains recorded goals from the trusted archive team-match path. Expected goals remains
the existing archive/FPL-derived historical signal. SDP xG, xGOT, possession, passing, box touches,
pressing, defensive actions, and every other provider field are excluded.

## Interpretation

Passing a retrospective development gate means only that the signal hypothesis merits prospective
confirmation. Strict real-deadline evidence must later be collected under `known_at <= as_of`.
Neither this policy nor any result produced under it changes the prospective model default.
