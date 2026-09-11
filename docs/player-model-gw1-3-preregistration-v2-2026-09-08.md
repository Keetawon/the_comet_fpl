# GW1-3 Player Model audit V2: serializer-only erratum

New identity: **`player_model_gw1_3_20260908_v2`**.

The original `player_model_gw1_3_20260908_v1` is permanently
**INVALIDATED_BY_IMPLEMENTATION_BUG**. It failed at input-metadata publication,
before inference, forecasts, outcome loading or scoring. Its three original receipts,
unavailable results, preregistration and INVALID report remain byte-identical.
Original preregistration: `0a7c7640288ae785003075fbcec1c63772f6e203`.
Original invalid closing commit: `c76af405df863b73ee118069da6fd022615f9c93`.

The model freeze remains **`17cfa2267ce4d7c89f96842220f40471b81152d2`**.
Serializer repair commit: **`1e5d93831a2c1564af6349389b6f0c523cd1818e`**, already
pushed cleanly before this preregistration. It adds only corrected audit transport,
tests and its documentation. It is not a new Player Model candidate.

## Exact transport change

The old serializer sorted integer keys numerically before JSON converted them into
strings. Decoding and sorting again changed the byte order, e.g. 1/2/10 became
1/10/2. The new `fpl.validate.audit_json.canonical` recursively normalizes string/
integer mapping keys to strings before sorting and rejects normalized collisions.
Unsupported key types and NaN/Infinity fail closed. Values, NULL, ISO timestamps,
UTF-8 encoding, ASCII escaping, compact separators and one trailing LF have fixed
semantics. No input object is mutated. The write-once publisher and byte-replay
verification are unchanged and are not weakened.

The old encoder remains intact for reproducing V1. The additive V2 launcher binds
only the corrected encoder, V2 identity/config/output references, the immutable
effective-config loader and execution-provenance file list around the **unchanged
original `run_audit` body**. Bindings are restored even if the run fails.

## Everything scientific is inherited unchanged

`config/player_model_gw1_3_audit_v2.yaml` references the exact original configuration
by path and SHA256. The effective configuration may differ in only `audit_id` and
`default_output_dir`. It does not duplicate or amend the original scientific values.
Original 339 model/science/config fingerprints, eight audit implementation pins,
original result/report hashes and three failed-run receipts are checked before use.
The new encoder and launcher are separately pinned in execution provenance.

The comparator remains the existing recursive incumbent shadow: identical current
player components with `trailing_goals_attack_defence` as team environment. Cutoffs
remain GW1 August 21, GW2 August 28 and GW3 September 4, each at **17:30 UTC**.
All original registry/schedule/history/source identities, populations, exclusions,
availability rules, 2,000 draws, seed 202627, component estimation and scoring rules
remain identical. No new parameter search, metric, feature or decision rule is added.
Attacking Usage scouting remains descriptive and cannot affect inference.

Lane A is the original strict input-availability replay. The September 7 SDP model
artifact cannot qualify at these cutoffs; actual fallback/equality must now be
executed and asserted, not assumed. Absolute player quality is still scored.

Lane B is the unchanged **RETROSPECTIVE DEVELOPMENT COUNTERFACTUAL**, using the
original actual evidence frontier `2026-09-08T09:53:00.642943+00:00`. True source
timestamps, pre-target completed football evidence, whole-GW isolation, identity,
health, population and fallback gates are unchanged. It cannot promote the model.

The complete [original preregistration](player-model-gw1-3-preregistration-2026-09-08.md)
still owns the primary coarsened-points CRPS, log floor, signed MAE/bias, ranking,
component/calibration, positional/cold/transfer/temporal slices, top-K/captain,
top25 forensic, paired uncertainty and PROMISING/MIXED/WORSE/INVALID definitions.
No performance was read before this erratum. The resource decision will use the
owner's explicit labels NO FREEZE or YES ONE BOUNDED REPAIR (one identified
component only), without implementing any repair or changing a scientific rule.
Only three retrospective model-development GWs exist; neither lane is prospective
promotion evidence.

## One-shot operation

Commit and push this erratum, identity config and launcher before executing once:

```powershell
D:/Personal/fpl-operations/.venv/Scripts/python.exe -m fpl.jobs.evaluate_player_model_gw1_3_v2
```

The new output is `formal-v2` beside the immutable `formal-v1` directory specified
by the original config. V2 reserves its own shared exclusive claim. All twelve
forecast artifacts and sidecars must be durably frozen before official outcomes
are loaded. Results and receipts are write-once. Any new implementation failure
stops this identity; preserve it and do not repair-and-rescore in this session.
If any non-serializer implementation change is needed, stop and report.

Serializer tests already cover integer/nested keys, collisions, insertion order,
separate processes, actual retained historical metadata, write-once behavior and
unchanged V1/model hashes. Identity tests prove the two-key effective-config delta
and scoped restoration. Relevant original audit/player/SDP/scouting regressions,
Ruff, strict mypy and changed-file formatting remain required. Preserve all known
inherited limitations separately. Push only V2; no main/default/PR/history changes.
