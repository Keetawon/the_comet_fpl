# Preregistration: SDP zero-SOT / xGOT health repair, prospective evaluation (`sdp_health_repair_prospective_v1`)

**Status at commit: preregistered, NOT scored.** This document is committed on 2026-11-28,
before the repaired code produces any pre-deadline pair and before any GW13 outcome exists
(GW13 deadline 2026-12-01T18:30:00Z). The repair itself is a data-plumbing correction, not a
model change: no frozen parameter, frozen source file, threshold or historical verdict changes,
and nothing here re-judges the INCONCLUSIVE Phase A result. This is a descriptive prospective
read-out under the owner-directed SDP adoption; it defines **review flags**, not promotion or
demotion gates, and no outcome of it changes a default automatically.

## The repair being evaluated (context, not evidence)

Before the repair, 7 of 111 completed 2026-27 matches failed SDP production health for
reasons the raw payload itself contradicts:

1. **Six provider-omitted zero-SOT sides** (`SDP_INCOMPLETE_FALLBACK`: fixtures 7, 19, 20, 28,
   61, 65). PL SDP omits `ontargetScoringAtt` when it is zero (match 2645286 proves this: its
   first capture omitted the field, the later dense capture carried `0.0`). The repair accepts
   the omission as `0` only when the same payload proves it: `shotOffTarget + blockedScoringAtt
   == totalScoringAtt`, every own goal/on-target field zero, official score zero, and the
   opponent's conceded/xGOT-conceded/save fields zero. Over all 91 omitted-SOT sides in six
   seasons this accepts the 86 provable zeros and rejects the 5 contradictory Opta records.
2. **One false xGOT bound** (`SDP_SCHEMA_FALLBACK`: fixture 87, LIV 0-1 ARS). Opta's SOT counts
   goals and keeper saves only, while xGOT also values on-target shots blocked by outfielders.
   The bound now allows `min(blockedScoringAtt, attIboxTarget + attOboxTarget)` such shots, only
   under an exact shot partition.

An omitted `attemptsIbox` is likewise accepted as `0` only when `attemptsObox ==
totalScoringAtt` and every inside-box/penalty sub-count is zero.

Measured at the 2026-11-28T01:55:12Z cutoff (GW13-17, 50 fixtures): `SDP_PRIMARY` 48/100 sides
before, 100/100 after. That is a coverage fact, not an accuracy result.

## Question

On prospectively recorded, deadline-verified pairs, is the repaired SDP-primary team-goal
distribution closer to the official outcome than (A) the incumbent shadow, and (B) on the
fixtures the repair changed, than the pre-repair published distribution?

## Population (pre-registered)

* **Source:** rows of `ledger_sdp_evidence_pair` (see `docs/sdp-prospective-evidence.md`),
  season 2026-27. Every included pair already passed the registry's fail-closed checks:
  `created_at <=` every included official deadline, clean worktree, manifest parity,
  identical membership, consumed SDP sources witnessed by `load_sdp_state`.
* **Repaired pairs only:** the primary manifest `commit_sha` must have the repair commit
  `4061fd7` (`fix(sdp): accept payload-proven zero SOT/inside-box counts ...`) as an ancestor.
  Earlier pairs are excluded (reported as context only).
* **Target gameweeks:** GW13 through GW20 inclusive.
* **One vintage per target GW:** for target gameweek `g`, the pair with `gw_from == g` and the
  latest `created_at` that is still `<=` GW `g`'s official deadline. Only that pair's fixtures
  in gameweek `g` are scored, so every fixture is scored exactly once from its nearest
  pre-deadline commitment. A gameweek with no qualifying pair is reported missing, never
  imputed.
* **Outcomes:** official signed team scores attached by the existing authoritative jobs
  (`attach_outcomes`), only when the gameweek is officially final. Postponed, abandoned or
  unattached fixtures are excluded and listed.

## Arms

* **Primary:** the pair's primary artifact `goals_for_distribution` (SDP V2 with incumbent
  fallback).
* **Shadow:** the pair's incumbent-shadow artifact `goals_for_distribution`
  (`trailing_goals_attack_defence`).
* **Pre-repair reference (subset B only):** the selector re-derived read-only at commit
  `70e1ac3` (the operational head immediately before the repair) against the same retained
  forecast-source database copy and cutoff. For a fixture that commit would have sent to a
  fallback, the pre-repair published distribution equals the shadow distribution; for a
  fixture it would also have sent to `SDP_PRIMARY`, the fixture is not in subset B.

## Metrics (pre-registered)

Per team side (two per fixture):

* **Primary metric:** goal negative log-likelihood, `-ln P(observed goals)` under the stored
  PMF, probabilities floored at `1e-12`. Lower is better.
* **Secondary:** clean-sheet Brier score from the opponent's `P(0)`; ranked probability score
  over the stored goal support.

Reported as the mean per arm and the paired mean difference `primary - shadow`, with a 95%
paired bootstrap interval resampling **fixtures** (both sides together), 10,000 draws,
seed `20261128`.

Subsets, each reported separately:

* **(A) All scored sides.**
* **(B) Repair-affected sides:** both sides of every fixture whose pre-repair re-derivation is
  not `SDP_PRIMARY`.
* **(C) Previously cold-start clubs:** sides of HUL and SUN (descriptive only).

## Review flags (not gates)

The read-out may be produced at any time, but no conclusion is written before **at least five
scored target gameweeks**. At or after that point:

* If the (A) paired NLL interval lies entirely above 0, flag the SDP primary for owner review.
* If the (B) paired NLL interval lies entirely above 0, flag the repair for owner review.

A flag opens a review; it does not roll back, retune or switch the default. An interval that
spans 0 is reported as "no detectable difference", not as evidence of equivalence.

## Frozen for the duration

The corroboration rules in `src/fpl/storage/sdp_runtime.py` (`corroborated_zero_sot`,
`corroborated_zero_ibox`, `blocked_target_allowance`), the frozen SDP model and selector, and
the incumbent are not edited between this commit and the read-out. Any change restarts the
window under a new preregistration. There is one read-out per window and no metric shopping:
metrics, subsets, interval method and seed are fixed above.

## Known limitations (stated)

* Eight gameweeks is about 80 fixtures; small paired differences will not be detectable.
* Subset B depends on a read-only re-derivation with old code. If that re-derivation cannot be
  reproduced exactly from the retained source copy, subset B is reported as unavailable rather
  than approximated.
* Pairs share players, fixtures and gameweek-level shocks; the fixture bootstrap does not model
  within-gameweek correlation.
