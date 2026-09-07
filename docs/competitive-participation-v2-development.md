# Participation V2: source-resolved offline pilot

Completed on 2026-09-07 at clean preregistration
`eea2381c8395af0b136782c515d0e34181cc462c`. This is data interpretation, not a model evaluation.
The [original failed pilot](competitive-participation-pilot-development.md) remains immutable.
The [new interpretation](competitive-participation-v2.md) follows independently corroborated
formation membership; it does not lower the original threshold or hardcode a player exception.

Result: `results/competitive_participation_v2_development.json`, SHA256
`fb9a9ef9d1a55b4a4c867aacbf7d89e1e880e0a64bd251bb2e318f14192c15ab`.

| Check | Retained result |
|---|---:|
| Same nominated fixtures / reciprocal sides | 13 / 26 |
| Raw roster records retained | 535 |
| Arsenal/Palace exact player identities | 266 / 266 |
| PL starter and appearance agreement | 160 / 160 |
| Appeared PL duration comparisons | 121 |
| Nominal duration minus FPL minutes | 93 zero; 26 +1; 2 -1 |
| Mean absolute duration difference | 28/121 = 0.231405 minutes |
| Selected-club unknown exposure | 0 |
| Other-club unknown exposure | 1, retained as NULL |

All unchanged PL tolerances pass. Millwall's unassigned Crocombe roster record remains present:
started, bench membership, appearance and nominal minutes are NULL, not a fabricated DNP.
Accordingly `all_fixture_roster_exposure_known=false`; this pilot does not claim every player's
participation is usable. The independently resolved XI is distinct from the generic roster label.

Independent raw/identity/pair verification performed 4,157 checks. Its first supplemental audit
additionally required a prior-club observation for every mapped player and therefore failed on
three absent priors. That stronger requirement was never part of the frozen V2 contract. Both
the first audit and the subsequent policy reconciliation are retained: codes448104,651426,660392
have exact Opta identities and current PL club corroboration, but no prior-club witness. Those
priors remain NULL; no contradiction was concealed and the pilot was not rerun.

Persistent execution directory:
`D:\Personal\fpl-operations\verification\competitive-participation-v2-20260907T083000Z`.
All39 original raw bodies,137 input files, original capture times, original failed result and
reference DB hashes were independently checked. No network or database writes occurred here.
The frozen research DB remains SHA256
`0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8`.

This permits a bounded operational participation ingestion, not invented registration intervals.
Historical stint first/last observations do not prove continuous registration. Exact total
competitive workload and true rest must remain unavailable without that evidence; separately
labelled witnessed participation bounds may be developed without inferring rested zeros.

The independently classified broad gate is retained in
`results/football_evidence_amendment_gate_20260907.json`: 2,946 passed,14 inherited WinError1314
symlink failures,4 related skips. The13 new provenance-guard tests added after collection passed
separately (23 cache tests total): combined distinct coverage is2,959 passed, not a green full gate.
Ruff check passes; strict mypy passes162 sources. Format retains11 unrelated pre-existing files;
new code is formatted. No dashboard, optimizer or prospective defaults changed.
