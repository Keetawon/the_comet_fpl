# Interrupted retention verification: missed publication source pins

The first real local-only verification of the September 17 retention change
found a defect after the Dashboard build completed. The refresh reused its
existing plan and forecast (`forecast_regenerated: false`), but its automatic
retention scanner inspected config/results/docs and forecast headers without
discovering ignored publication manifests under `data/artifacts`.

Three source database copies were deleted before process 36148 was stopped:

| Capture directory (under operational `dashboard-runs`) | Source SHA256 prefix | Bytes |
| --- | --- | ---: |
| `20260916T140011.154577Z-1fc29261` | `5da77aa5` | 2,462,855,168 |
| `20260917T021106.821076Z-1266a0bd` | `3527304f` | 2,570,072,064 |
| `20260917T040008.671786Z-eb919465` | `8fc46d82` | 2,689,871,872 |

Each file was `before.duckdb`. Five retained publication manifests pin their
exact source hashes. Their earlier duplicate peers had already been retired
while these copies were deliberately preserved. No surviving equal-hash copy
was found in the bounded workspace/operations search; one unrelated older export
directory was inaccessible. **Exact historical source bytes are not restored.**
The 7,722,799,104 bytes above must not be counted as certified safe cleanup.

All 72 recorded immutable-table multiset checks passed against the surviving
recovery (`517f39863b89de09aa829869ca877003edbf3810bbc458175694a828d444485e`).
Thus raw payloads, source versions, snapshots, forecast distributions and
append-only outcome/evidence ledger rows remain. This does not establish
byte-identical database replay or preservation of every mutable derived table.
Current database, previous recovery and new recovery were independently hashed
under read-only leases and matched. The published/frozen forecast files were not
regenerated. Do not describe this incident as “all source snapshots unchanged.”

The original `retention-20260917T091944Z-6cf58448.json` receipt remains in its
interrupted `RUNNING` state, with three completed removals and no pending removal.
The detailed incident evidence is retained at
`data/artifacts/availability-20260917/retention-publication-pin-incident-20260917.json`.
The completed local Dashboard build is separate from this interrupted retention;
no R2 upload or production deployment occurred in the verification cycle.

## Correction

Reference discovery now includes ignored publication/replay metadata and adjacent
operational verification metadata. Traversal raises on unreadable or linked
subtrees instead of silently omitting them. It includes all preserved legacy,
failed-publication and foreign-database generations, the latest two ordinary
managed generations, and the dependencies of older pinned generations.
Forecast hashes and exact run paths seed dependency discovery before retirement.

Retention's own proofs and retired-generation manifests do not create new pins.
A hash-only duplicate can retire only when its exact bytes survive in the
verified recovery; an exact source-path reference still protects the original.
This prevents repeated identical copies accumulating without weakening byte pins.
The repaired read-only scan found all three previously missed source identities.
Added regression cases cover those locations, unreadable evidence, transitive
pins, failed publications, and byte-identical versus path-bound duplicates.

The final eight-file regression suite passed **164 tests** (49 retention tests),
with Ruff, changed-file formatting and strict mypy passing. Independent source
review found no remaining P0/P1 in the corrected policy. At 09:35 UTC all 226
tracked/model/config/research baseline files and all 10 retained forecast files
still matched their original SHA256 values. Both capture-health reports reproduced
their pre-cleanup states exactly at the same check times. These are distinct from
the lost historical publication source snapshots documented above.

No model, configuration, forecast, scoring method, availability policy, or source
knowledge timestamp changed. This correction prevents further missed-reference
deletions; it cannot reverse the three deletions recorded above.

## Corrected operational verification

The corrected local-only refresh completed at 09:45 UTC with capture skipped,
the existing plan reused, and no forecast regenerated. Its retention receipt
`retention-20260917T094543Z-2805e0aa.json` completed at 09:46:43 UTC and retired
three session-created copies only after verifying their bytes were identical
to the surviving recovery. The independently verified publication source with
SHA256 `57da817269a8f5616fe0bcfad2e4865c93039b021613908965a0a9e3948491a3`
remains present. The final manual retirement of the previous ordinary recovery
at 09:49 UTC left one ordinary recovery, with protected source exceptions.

The interrupted cycle's lock was retired separately only after proving its
owning process had stopped and recording its original ownership and the reason.
Unresolved legacy operational database lock/WAL files were not removed. The
new successful retention receipt does not replace or repair the interrupted
receipt or its missing historical database copies.
