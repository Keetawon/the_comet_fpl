# Bounded 2025 competitive workload raw capture

This NEW data-only contract continues from the failed-interpretation pilot without changing
that frozen pilot. It acquires bytes, not valid participation labels, learned roles or models.
No database is opened, no schedule activated and no prospective/default source is switched.

## Evidence-controlled inventory

The 13 retained metadata pages exhaust the observed cursor chains for provider season2025 in
six competitions. SHA-pinned source is `results/competitive_participation_pilot_development.json`
and its persistent original response files. There are1,127 unique catalogue records. The20 club
provider IDs are derived from all380 PL matches, not guessed or automatically treated as FPL codes.

| Competition | Catalogue | Selected matches involving a 2025-26 PL club |
|---|---:|---:|
| PL8 |380|380|
| FA Cup1 |123|43|
| League Cup2 |93|38|
| UCL5 |189|69|
| UEL6 |189|29|
| Conference1125 |153|15|
| Total |1,127|574|

Exact record/selected-ID/PL-ID hashes are fixed in `config/competitive_workload_capture.yaml`.
Verify every retained raw hash, byte count, HTTPS provider URL, season/competition and cursor
chain before collection. Duplicate identities or incomplete catalogue termination fail closed.
This is the COMPLETE SELECTED INVENTORY AT THE RETAINED VINTAGE, not a guarantee that this
provider lists every fixture ever played. It excludes friendlies and every competition outside
the six named ones. Previous clubs outside the selected20 and international participation are
not captured. Do not label that gap zero workload or claim complete physical recovery history.

## Reuse and bounds

Copy the original39 request/response records and raw bodies into a separate `inputs` directory,
preserving source names, hashes and capture timestamps. The13 prior lineup/event pairs include
the malformed Palace-Millwall match2603048. Reuse those26 endpoint payloads exactly; do not
replace a revision because it looks easier to interpret. Preserve their original provenance.
The remaining561 matches require1,122 distinct endpoint requests. Fetch chronologically by UTC
kickoff then match ID, lineups then events, using one client and one global response recorder.
There are no new metadata, player-stat, team-stat or competition-discovery requests.

Use the existing source timeout30s, spacing>=1.5s and at most4 retries per endpoint, exponential
backoff and bounded Retry-After. Every attempt/error/response is retained. At1.5s the request-start
spacing alone costs about28.1minutes, before latency/retries. This is an estimate, not an SLA.
Stop immediately on the client's egress-policy exception or after5 consecutive failed endpoint
calls; preserve all completed bytes and list every remaining endpoint. The1,122 distinct-request
cap excludes the existing bounded retries (at most5 attempts per endpoint). No parallel fetching.

Output must be a NEW explicitly named external persistent directory, outside the repository
and outside the original retained directory. Fsync/exclusive publication prevents overwrite.
There is no in-place resume: a future continuation must inventory retained evidence explicitly
and must not refetch completed endpoints blindly. Raw observations are data, not one-shot model
evaluations; this capture does not reserve or consume any modeling candidate.
Require a clean committed V2 implementation at startup. During raw collection, independent new
work elsewhere may proceed: postflight requires capture-relevant source/config/input hashes to
remain unchanged, but merely reports ending Git HEAD/status rather than demanding global
cleanliness. This is data acquisition, not clean-provenance model evaluation.

## Capture is not interpretation

All574 selected metadata records have a kickoff. Their raw completed statuses comprise535
NormalResult,15 PenaltyShootout,21 Aggregate and3 AfterExtraTime. The current pilot interpreter
does NOT license the last24; nevertheless their raw endpoints belong in this capture. Do not
convert Aggregate to a draw, infer90/120 minutes or alter the historical status predicate here.
The26 sampled lineup sides include two missing Conference formations; season-wide formation
coverage remains unmeasured until collection and an independent data-only interpretation audit.

Neither an HTTP200 nor parseable JSON proves a complete lineup, valid durations, formation,
stable player identity or forecast-ready workload. The result reports received endpoint coverage
and failures only, with `participation_validated=false`. Missing/ambiguous participation makes
affected future workload windows unknown; it does not invalidate unrelated club/windows or
authorize missing-as-zero. For example, match2603048 lies in Palace's next one/two/three PL
kickoff windows of7/14/21days respectively. Exact rest hours remain unlicensed without a reliable
match-end timestamp. Later acquisition retains real capture time, never historical known-at.

Before any role/minutes evaluation: audit formation labels, minutes semantics, historical club
membership/transfers, unique provider-player/FPL-code anchors and full window coverage, then
preregister eligibility based only on coverage. Historical FPL Opta anchors are complete for
2024-25 (784/784) and2025-26 (841/841), but absent in2023-24 (0/865); a cross-season identity
bridge requires its own explicit evidence, not names. The authorized historical price proxy does
not repair those separate identity/participation gaps. No scoring occurs in this job.

## Invocation and retained outputs

After a clean reviewed commit, the owner may run:

```powershell
& 'D:\Personal\fpl-operations\.venv\Scripts\python.exe' -m fpl.jobs.capture_competitive_workload `
  --retained 'D:\Personal\fpl-operations\verification\competitive-participation-20260907T070000Z' `
  --results 'D:\Personal\fpl-operations\verification\competitive-workload-2025-NEW-RUN-ID'
```

`provenance.json` pins Git/config/source/input hashes; `inventory.json` retains all574 selected
records; `inputs/` holds exact prior bytes; `responses/` holds every new attempt and response;
`capture-{match_id}.json` records received endpoint identities after each match; `result.json`
retains the endpoint-by-endpoint final status and summary, including partial/failed execution.
There is no model training, participation transform, default database mutation or production
readiness claim. Tests use mock transport/synthetic payloads, never a live provider.
