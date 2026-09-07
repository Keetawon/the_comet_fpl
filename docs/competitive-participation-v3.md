# Straight-red source interpretation amendment V3

This is a bounded data-interpretation amendment, not a model experiment. The original V2 parser,
13-match pilot, and first 574-match operational staging result remain immutable. Nominal-period
minutes, formation precedence, identities, nullable actors, and all event/state guards are unchanged.

Before implementing or testing the V3 normalization, the read-only audit in
`results/competitive_straight_red_source_audit.json` retained every relevant raw card and input
hash. The 574 bundles contain 47 `StraightRed` events in 46 matches. In the Premier League,
32 events occur across 31 matches; all 30 with identifiable players resolve through the exact
season-qualified FPL Opta/fixture crosswalk and have recorded FPL `red_cards = 1` (30/30).
Two events have NULL actors: Wolves–Brighton 2561964 and Leeds–Manchester City 2562170. They stay
unattributed. This evidence does not identify a coach/staff member or authorize guessing a player.

The corroborated meaning is **dismissal**. FPL's aggregate red-card field does not independently
prove a published provider taxonomy distinguishing straight red from second yellow. Applying the
same enum meaning to this provider's cup/Europe payloads is explicitly development-only; those
competitions do not have a separate FPL player-fixture overlap witness.

The separate `competitive_participation_straight_red_v3` wrapper privately maps only the exact
string `StraightRed` to the existing `Red` dismissal state transition, delegates unchanged V2,
and restores every raw card/event plus an explicit alias log. It does not mutate provider bytes,
rewrite capture times, alter nominal-minute clipping, replace missing actor IDs, remove duplicate
events, or broaden position labels. Unknown dismissal actors remain unknown; failures masked by
the old enum rejection can still emerge. The number of recovered whole matches must be measured.

V3 restaging must use a new operational copy of the first workload DB. Every V2 receipt, version,
and row is preserved, while new V3 interpretation/version rows append beside it. No provider
requests or model fits are permitted. The clean source/config/pilot/audit/database fingerprints
must be recorded before writing. Coverage and PL identity/minute reconciliation reuse the same
audit definitions. A new write-once report retains failures without overwriting the V2 result.
