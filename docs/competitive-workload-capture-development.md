# Competitive workload: retained acquisition and safe interpretation boundary

The bounded 2025-26 capture is complete. This is data evidence, not a model result,
deadline-knowledge proof or a claim that every lineup/event is interpretable.

| Competition | Selected matches |
|---|---:|
| Premier League | 380 |
| FA Cup | 43 |
| League Cup | 38 |
| Champions League | 69 |
| Europa League | 29 |
| Conference League | 15 |
| Total | 574 |

All twenty PL clubs are covered in this explicitly selected six-competition catalogue.
Friendlies are excluded. It is not a complete worldwide player registration/workload history.
The thirteen original pilot matches supply 26 unchanged endpoint captures; **1,122 new
sequential requests all returned HTTP 200**, bringing retained lineup/event endpoints to
1,148. Provider pacing remained at least 1.5 seconds between attempts. No database was opened
and no model fitted by acquisition. Completion: **2026-09-07T08:56:21 UTC**.

Exact result: `results/competitive_workload_raw_capture_2025.json`, SHA256
`d24f10c864fcfd7ff22433f34df163c35fe399a54a9f54d1f9ee6a5796ade47c`.
Persistent raw/receipt/capture directory:
`D:/Personal/fpl-operations/verification/competitive-workload-2025-20260907T083100Z`.
Every HTTP body, URL/params, original capture/client-known times and content hash is retained.
The operator directory name is not a fabricated timestamp. Prior captures were copied byte for
byte with original knowledge times, not relabelled as newly collected.

Acquisition began from clean `eea2381`. Unrelated implementation/result commits proceeded
while the polite network run was active; its ending HEAD/status are retained honestly.
Every acquisition-source/config/input fingerprint passed postflight unchanged. This is **not**
an outer model evaluation run from a dirty checkout and must not be represented as one.

## Operational staging, before its first execution

`python -m fpl.jobs.stage_competitive_workload` requires explicit source, new operational DB,
capture, passed V2 pilot and new report paths. It must run from clean V2 history. The source
DuckDB is pinned and read-leased, with no unresolved WAL; a separate verified temporary copy
is published atomically without clobbering an existing destination, then written under the
existing writer lock/transaction/checkpoint safeguards. The default database path is unchanged.

New `dev_competitive_*` tables retain exact raw bytes, whole capture/interpretation versions,
nullable player participation, permanent-code crosswalks and coverage/error reports. They are
outside the production schema and strict feature-table allowlist. Repeated interpretation
preserves the first interpretation time and verifies semantic identity; a changed payload is
a separate version, never a second match in rolling history. No frozen DB or result is rebuilt.

PL fixture/club identity uses the measured crosswalk, never `pulse_id == matchId`. Player
identity uses exact season-qualified Opta anchors. Foreign/unmapped identities and malformed
participation remain explicit; no name matching, arbitrary XI deletion or minutes fabrication.
The frozen V2 formation precedence is reused without changing the original failed pilot.

Historical registry continuity is **not proved** by first/last observed archive rows. Therefore
exact player workload totals and exact last-appearance rest remain NULL. A separate explicitly
retrospective observed-participation interface supplies only measured positive congestion
lower bounds over 72h/7d/14d, with all source/gap identities. No appearance witness means
unavailable, not rested zero. Last witnessed kickoff age is at most an upper bound on actual
kickoff-based rest if later appearances could be missing; it is not whistle-based recovery.

Only completed prior source matches may enter. All target-GW PL legs are excluded together,
and any known event/end timestamp reaching the cutoff rejects the fixture. Without a verified
final-whistle timestamp, an additional conservative **six-hour kickoff margin** is required.
This is a development eligibility proxy, not evidence of exact completion time, a provider
publication SLA, or permission to weaken prospective `known_at <= as_of`. Exact whistle rest
stays unavailable. The same temporal boundary applies to later coarse role history.

## Next data acceptance

Before a role/workload candidate is scored, audit the complete staged pilot expansion against
independent PL/FPL identities, starts, appearances and measured minutes. Keep invalid fixtures,
unmapped players, extra-time/bench ambiguities and every remaining coverage gap visible.
HTTP success and a successful transaction do not license all interpreted data automatically.
Define eligible population from coverage before formal model scoring.

For durable future capture, reuse the permanent local Python environment and external storage,
the database writer lock, append-only receipts, consistent backups, sequential bounded retries,
staging and a recent-revision pass. Freshness must compare expected completed fixtures with
complete retained versions, not merely job exit status. A hosted runner needs persistent remote
artifact/storage transfer; its temporary DuckDB is not durable. No new schedule is activated here.
