# One retained CURRENT component reference

`retrospective_current_component_proxy_cache_v1` is a write-once cache of the
already-specified `retrospective_current_component_proxy_v1` comparator, not a new
candidate, an evaluation of previous candidates, or a points forecast.

On the exact114-fold /86,755-row current minutes proxy universe, call the unchanged
`build_reference_components` once per pre-GW cutoff. This fits its current historical
goal/assist, saves/DC/BPS and team reference components; it **never refits minutes**,
fits a challenger, or performs the2,000-draw full-points simulation. Complete typed
`DevelopmentReferenceComponents` objects are retained: both fixture sides, all player
component PMFs, residual means/sigmas, nullable/resolved signals, unconditional rates,
team PMFs, original minutes and direct/team/fixture price-proxy lineage, fold-local
parameters and diagnostic/source JSON. No target outcome enters these predictor DTOs.

The only input minutes manifest is the existing pinned114-fold /86,755-row /821-direct-
proxy reference. A real cache run requires a clean exact V2 branch, original database
hash, no WAL and an original read-only lease throughout hashing/fits/publication.
The common-Git exclusive cache claim survives failure; no resume, overwrite or second
run under the same cache identity. Reports are in a new explicit external directory.

Every completed GW is fsynced through the existing write-once JSON publisher and gets
a content SHA. Each full object is decoded back through explicit dataclass/enum/tuple
validation and compared exactly before publication. No pickle/eval is used. A failure
retains its traceback, completed-fold receipts and original provenance, without claiming
a completed cache. Source/HEAD/database checks repeat before the final manifest.

Reusable manifests pin the transitive comparator files from
`component_source_fingerprints`, this cache source/document and all original minutes
source/database evidence. Unrelated later candidate configs or results are not
comparator dependencies; adding their preregistrations does not invalidate the cache.
The original generation HEAD is still retained. Future mathematical/default component
changes do invalidate it. Each downstream candidate independently requires clean full
provenance and pins the completed cache manifest SHA before its own once-only run.

`load_component_reference_cache(directory,root=...,db=...,minutes_cache=...,
expected_manifest_sha256=...)` verifies the full manifest/provenance, all114 hashes,
complete roster/count/price lineage and sources, then reconstructs typed original
components. Missing/extra target fields, changed player identity/position, nonfinite or
non-normalized PMFs, changed minutes and an enabled disciplinary component fail closed.
This does not generate an historical live registry or change any default consumer.

All downstream evidence remains retrospective archive/price-proxy development-only.
The goals/assists experiments consume the same reference; future full-points synthesis
can reuse its exact joint-composer inputs without fitting those components again.
