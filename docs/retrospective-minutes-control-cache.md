# Shared retrospective minutes-selector reference

This is a baseline-only, reusable prequential cache, not a rerun/rejudgment of the frozen
Stage B Candidate V3 experiment. The comparator identity is
`retrospective_current_minutes_proxy_v1`, governed by its separate owner-authorized price
amendment. No new model candidate is scored by this job.

The nominated reference includes all 86,755 non-null-minutes archive player-fixture rows
in 2023-24 through 2025-26, in 114 observed-GW folds. Target roster/current club and the
first-kickoff cutoff retain their explicit historical proxy status. The expected direct
price dependence is 821 rows, but runtime reconciliation must actually reproduce it.

For each fold, fit the unchanged current raw V3 once on all prior non-null-minute rows.
Use the **actual prospective** last-club, equal-weight trailing-five shrinkage, and prior
appearance helpers with the exact target roster's stable current-club map. Then invoke
the explicit retrospective price boundary, loading target-GW archive prices lazily only
when needed by a cold row. Established rows never consume their own archive price.
Both legs of a DGW share one history cutoff; required prices must agree across the legs.
Their final PMFs may differ across a calendar-month boundary because the unchanged seasonal
adjustment uses each fixture's month, not the cutoff month.
No model receives target minutes, starts, goals or a current-match tactical observation.

The V3 search is unchanged: 5 decay × 5 alpha × 5 adaptation settings and six prior inner
GWs, one selected fit per outer GW. This is 114 incumbent fits, not a fit per player or
downstream component. The prior full 181-fold execution took about 17 minutes on its
recorded environment; expect minutes rather than seconds, not a runtime guarantee.
Later experiments reuse the distributions, source hashes and cutoff-specific lineage.
They must not refit/relabel a changed comparator after seeing a candidate result.

Require a clean committed start/end, the pinned reference DB opened read-only with no
WAL, unchanged source and frozen-result hashes, and a new external output directory.
Each completed GW is published once with full raw-V3 and selected minutes distributions,
parameter/inner-score provenance, target identities, history frontier and original price
lineage. A failure retains completed checkpoints and a failure report, never a complete
manifest. An existing output cannot be overwritten or silently resumed.

This cache is neither a real-deadline registry reconstruction nor a production input.
Formal downstream contracts still need their own comparator verification, selected
population, matched proxy inputs, proxy/cold/established sensitivity, exclusive run claim
and single scoring. No full-points Monte Carlo or candidate performance is produced here.
