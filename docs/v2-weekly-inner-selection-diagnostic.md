# Weekly inner selection: pre-implementation diagnostic

Date: 2026-09-06. Read-only source diagnosis; no candidate predictions scored.

Starting V2 HEAD and verified remote HEAD were both
`449c9dbd72cb3dcc9c52ae153a995b8bcdb2b852`. The normal snapshot-only merge of
`origin/main` (`b03cc8d`, `1030469`) produced clean HEAD
`8c4d5f0c59b5c9b199668dfc51ea043ebc37ec57`. It added twelve provisional snapshot
files and changed no existing source, configuration, database or result.

## Confirmed mismatch

- `MultiSignalTeamEngine._inner_split` selects the last six observed `(season, gw)`
  keys, ordered by first kickoff; the initial training boundary is the first of those
  kickoffs. It does not assume contiguous GW numbers.
- `_select_decay_and_prior` fits goals ratings once per configured decay/prior pair
  on that initial training window and scores the entire holdout from that frozen fit.
- `_select_weights` similarly fits every available signal and its goals scaling once
  on that initial window, then scores every weight vector on the frozen holdout fit.
- `dev_v2_real_sot.run_walk_forward` and `v2_environment_harness.run_team_environment`
  instead rebuild prior history and refit before every outer GW. Every fixture leg in
  the target GW is predicted without a within-batch update.

The mismatch exists and licenses the owner-requested procedural experiment. It does
not establish why early-season performance was weak or promise an improvement.

## Boundaries for the additive candidate

Preserve the existing staged search: decay/prior selection on **goals only**, then
blend selection on goals plus **existing archive xG**. Joint optimization would be a
second change. Keep the legacy model source byte-identical; use a separate
validation-only selector implementation.

Use the same six holdout keys, but before each inner GW derive training from the
original outer-history frame with `kickoff_time < inner_GW_first_kickoff`. Score the
whole target GW from that state. Do not append an entire prior GW blindly: a delayed
fixture leg may occur after another GW starts. Previously delayed non-holdout legs
may enter once their event time permits, exactly as in the outer loop.

Preserve the latest-training-kickoff decay reference, minimum-history/fallback rules,
signal-availability rules, rating estimator, rate floor, Poisson output and all grids.
Preserve the inherited promoted-prior context bound to the **outer prediction
season**, including across an inner summer boundary. Thus this isolates the refit
schedule, not a redesign of season/prior semantics; historical roster/deadline and
fixed-prior development caveats remain. No strict prospective capability changes.

Aggregate inner loss by scored team-fixture row, not by equally weighted GW means.
Pin exact-equality ties to configured half-life order, then configured prior order;
blend weights use alphabetical signal order and the existing lexicographic simplex.
Retain both stages' selected inner scores separately.

No formal candidate may run until tests, the new preregistration and implementation
are committed cleanly, and the unchanged control reproduces the frozen population,
PMFs and scores within the preregistered strict tolerance.
