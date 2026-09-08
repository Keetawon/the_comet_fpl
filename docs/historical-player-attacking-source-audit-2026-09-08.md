# Historical player attacking sources and bounded acquisition, 2026-09-08

This is a development-only data and availability investigation. It creates no attacking-usage
score, model, fitted parameter, predictive result, or production integration. The frozen
Attacking Role Premium feasibility verdict remains **D: INSUFFICIENT DATA** for its original
retained population. Newly investigated external evidence does not rewrite that result.

## Source decision and limits

**Verdict B: HISTORICAL PIT SOURCE PARTIAL.** The existing approved Vaastav FPL archive has a
usable 2023/24 sequence of immutable, contemporaneously dated source commits. This investigation
accepts that sequence as **ARCHIVED_AS_OF (class B)**, with the qualifications below. It does not
relabel our July/September 2026 downloads as historical captures or establish strict class-A
original publication-time evidence. It creates no historical THE COMET forecast.

The archive discarded official FPL event deadline timestamps. Its fixture schedule can witness
that a whole subsequent gameweek was still in the future at an archived snapshot cutoff. That
supports a separately preregistered **snapshot-cutoff** study. Exact historical FPL deadline replay
is not established. No kickoff-minus-90-minutes or gameweek-end timestamp is invented.

The source acceptance relies jointly on the historical collection code, an incremental commit
sequence, parent/child file comparison, exact content and fixture identity, and historical
metadata. A Git timestamp alone is not the acceptance rule. Neither an independently attested
original GitHub push time nor a proof that all upstream history was never rewritten is available.
The audited sequence shows no evidence of such rewriting; this is bounded evidence, not a
cryptographic publication-time guarantee. Downstream work must retain that qualification.

## Local inventory before network access

The source investigation first read the retained archive, manifests, Git history, current
player-history captures, and SDP payloads. There is no retained upstream clone with older local
capture receipts. The twenty downloaded archive files use mutable upstream `master` URLs.
Twelve local ingestion receipts agree on their content hashes, but date only from July/August
2026. The earliest project Git snapshot found is July 27, 2026. These files remain retrospective
relative to historical deadlines and can supply priors after their real capture time.

| Source | Resolution / population | Timing and identity | Permitted use |
|---|---|---|---|
| Retained FPL archive, 2021/22-2025/26 | Player-fixture/GW, 123,297 normalized outfield rows | Exact season-qualified element-to-permanent-code mapping; July/August 2026 receipts | Class C for historical cutoffs; later priors |
| Retained content-addressed FPL captures | 56 captures, all 2026/27; 47 daily and 9 player-history captures in the inspected snapshot | Actual capture timestamps, payload hashes, source fixtures and registries | Class D after availability |
| Upstream 2023/24 versioned archive | 38 merged-GW-changing commits and matching registry/fixture/team files | Dated full commit/tree identities, actual raw acquisition receipts | Audited class B; selected bounded season |
| Upstream 2024/25 archive history | 37 relevant commits, including a January 2026 correction | Historical sequence mixed with a later correction | Candidate only; not acquired as a population |
| Upstream 2025/26 archive history | 12 relevant commits; sparse/bulk updates | Later imports and stopped regular collection | Not selected for a sequential historical population |
| SDP retained detailed match stats | 1,931 raw team-stat records / 3,862 team sides | Immutable current receipts; team grain | No player allocation and no historical availability inference |
| SDP retained lineups/events | Competitive membership/exposure, goals/cards/substitutions | Stable provider identity where available | Workload / structural observations; not a complete player attacking-stat feed |
| Bounded SDP player-season probe | One source-determined retained player; season aggregate | Current response time only, no player-fixture sequence | Endpoint/field investigation only |

Local historical row and field coverage is separated from upstream timestamp evidence:

| Season | Raw rows, all positions | Normalized outfield rows | Measured outfield xG/xA rows |
|---|---:|---:|---:|
| 2021/22 | 25,447 | 22,537 | 0 |
| 2022/23 | 26,505 | 23,714 | 16,092 |
| 2023/24 | 29,725 | 26,312 | 26,312 |
| 2024/25 | 27,605 | 24,414 | 24,414 |
| 2025/26 | 29,757 | 26,320 | 26,320 |

Raw counts include 322 manager rows in 2024/25 and ten exact duplicates in 2025/26, which the
existing normalizer excludes. Minutes, recorded points, goals, assists, influence, creativity,
threat and ICT are present across the archive. In 2021/22 xG/xA and starts headers are absent.
In 2022/23 expected-stat headers exist but the GW1-15 zero prefix is unmeasured under the frozen
`config/data_quality.yaml` rule; GW7 has no rows. These are different missingness mechanisms.
The backfill preserves the rule and never manufactures earlier measurement. xGI is redundant
with xG+xA. ICT components are provider indices, not shots, key passes or box-touch counts.
`modified` is a Boolean and supplies no timestamp.

## External source audit and raw evidence

The already approved source is [Vaastav's Fantasy-Premier-League archive](https://github.com/vaastav/Fantasy-Premier-League).
Its current documentation describes FPL API collection, warns that regular weekly collection
ceased after 2024/25, and identifies older contributions/backfills. Source code is MIT-licensed;
the repository separately attributes data ownership to FPL/Understat. This is not a grant of
third-party data rights by THE COMET. Attribution and original receipts are retained.

The audit froze a maximum of 24 GitHub requests / 32 MiB before probing and used 22 requests.
It retained raw response bytes, URL, HTTP status, headers/content type, actual UTC capture time,
SHA256, and request/response receipts. Full API commit-list responses are retained, not merely
filenames copied from a web page. The source audit JSON inventories every receipt and hash.

The first 2023/24 observation witness is
[`be15e285f106d1becc6f24c0c470ec9ada8c935a`](https://github.com/vaastav/Fantasy-Premier-League/commit/be15e285f106d1becc6f24c0c470ec9ada8c935a),
August 16, 2023 at 02:35:27 UTC. It has 658 all-position GW1 rows, an exact 663-player registry,
380 fixture records and twenty teams. The same snapshot places GW2's first kickoff at
August 18, 18:45 UTC. The pinned collector obtains numeric FPL element IDs, source historical
position, fixture sides and `element-summary` history. It does not retain event deadlines.
Its `xP` field has a separate look-ahead warning and is excluded entirely from this contract.

The GW2 commit `2749a5964950b3b34992cebde0351ac9e09fb54f`, August 23 at 13:08:45 UTC, has
1,253 rows: 595 added, zero previous rows changed or removed. Its immediate parent's merged file
is byte-identical to the GW1 file. A fixed midseason GW20 commit,
`15783a5630abadb309ff4c3edbb3dc32e6a2b426`, January 3, 2024 at 08:57:32 UTC, has 14,487 rows;
all 1,253 earlier rows still agree. This supports incremental historical collection rather than
an inference from a season folder name. All three samples reconcile stats to the same-commit
registry code and position. GW1 has full four-file reconciliation. GW2 stats, registry and
fixtures reconcile, with team labels checked against an earlier same-season team dimension;
its same-commit teams file is not yet captured. GW20 fixture/team checks await the bounded
acquisition. End-of-snapshot registry club is never substituted for fixture club.

All 38 selected source commits fall between August 16, 2023 and May 27, 2024. Two author/committer
dates differ by 12 and 17 seconds: the contract uses the later date. A late GW26 import is
explicitly dated March 20, 2024 at 17:01:19 UTC (`288c341ae1f28b260786e862b8917c865d953815`).
Those rows become available on that date, not when GW26 was played. Other unavailable history
likewise remains absent at earlier cutoffs.

## Frozen bounded acquisition

`config/historical_player_attacking_backfill.yaml` freezes the following before execution:

- One source and one season: Vaastav/FPL, 2023/24, source GW1-38, DEF/MID/FWD only.
- Exactly 38 explicitly named commits; four exact paths per commit: merged GW CSV, player
  registry, fixtures and teams. 152 URLs total, nine already captured in the source audit.
- At most 304 attempts, one retry per request, 192 MiB total response bytes and at least
  1.5 seconds between requests. No additional provider, season or source expansion.
- Exact element-to-code identity, source-season position, fixture-time clubs, NULL optional
  fields, strict duplicate rejection, and immutable raw and normalized source versions.
- Class B historical availability is the later audited author/committer date. Real capture
  time remains 2026. Every accepted snapshot is bound to the frozen source-audit SHA256.
- One acquisition claim in the shared Git directory. A failed run retains its identity and
  raw evidence. It cannot silently restart. Offline replay is separate and cannot fetch.

Planning estimates from the existing retrospective table are 26,312 outfield observations,
765 players and up to 37 target GWs (GW2-38). These are estimates, not promised PIT coverage.
The frozen practical sufficiency screen requires at least 24 chronological target GWs,
10,000 outfield target rows, 300 distinct players, 100 players with five prior starts,
50 with ten prior starts, all three positions, and 95% measured xG/xA target coverage.
These are data-adequacy checks, not score, model, significance or promotion thresholds.
Actual snapshot availability and whole-GW roster evidence may reduce those counts.
The planning-only GW2-38 table has 25,730 targets: DEF 9,394; MID 12,569; FWD 3,767.
Distinct players with at least three/five/ten earlier-GW starts are 399/374/308, respectively.
These estimates use the existing retrospective archive and are not historical availability claims.

A source snapshot cutoff is usable for coverage only if its complete schedule witnesses the
whole target GW in the future, all actual target kickoffs are later, and target players have
exact pre-cutoff registry identity and historical position. Coverage uses the latest retained observed version for target labels and the earliest eligible
version for prior history; it calculates no predictive performance. Target rows are labels only. Every
leg of the target GW is excluded from history, including double-GW earlier legs. A future study
must separately preregister its cutoffs, population and models; this acquisition scores nothing.

## Additive observation and availability contract

`HistoricalPlayerAttackingObservation` retains season, GW, fixture and kickoff; permanent player
code and source element; historical FPL position; permanent fixture team/opponent codes and venue;
minutes/starts; nullable attacking opportunity fields and descriptive outcomes; raw source
identity and SHA256; source, capture and permitted availability timestamps; evidence class; and
all four source hashes, collector-version witness and normalization version.

- `observed_match_time` is the recorded fixture kickoff, not a publication time.
- `source_known_at` is the audited archived version time for class B. Class C without proof
  has NULL historical source time. No event date or current capture becomes an earlier timestamp.
- `capture_known_at` is when THE COMET actually received the required raw bundle (latest component
  receipt). Reusing a retained raw file retains its original receipt time.
- `available_at` follows the explicit evidence class: audited source time for A/B; actual capture
  for retrospective/prior use. A class-C row cannot pass the historical evidence gate.
- Historical eligibility also requires `known_at <= as_of`, kickoff before `as_of`, and exclusion
  of every target-GW leg. Unknown fields stay NULL; a measured source zero remains a real zero.

The source version is the full commit SHA. All raw versions survive. Unchanged football rows do
not bloat the normalized history; first or changed row versions are appended. Future history
selection uses the **earliest eligible observed value**, not a later corrected version. Registry
and fixture files stay attached to their own snapshot; later season positions/clubs cannot leak
backward. Cross-season joining is permitted only on permanent code; this acquisition itself
contains just one season. Contradictory element/code mappings fail closed.

The local archive has 51 permanent codes that change FPL position across seasons and 1,248
fixture rows whose club differs from the end-of-season registry. There are 120 player-season
transfer groups (242 club stints). These observations show why current position/club cannot be
used retrospectively. The contract resolves the club from the exact fixture and does not invent
transfer announcement dates. A future target roster must come from a pre-cutoff snapshot.

## Player-level SDP gap and current prospective capture

The retained official Premier League JavaScript identifies a player-season stats endpoint and a
match timeline endpoint. A separate, frozen two-request probe used the first source-ordered
retained player (a goalkeeper), not a named attacking case study. Player-season stats returned
66 numeric fields, including expected assists, key passes/attempt assists and open-play passing
or crossing categories, but only a season aggregate: no match-row history or historical
publication timestamp. The timeline response was an empty array. This small sample does not
prove that outfield shot fields do not exist; it does not establish a usable historical feed.
No larger endpoint scrape was launched.

Team-level shots, SOT and box touches cannot be allocated to players. The retained lineup/event
payloads supply membership, substitutions and scoring events, not complete shot/box/creation
opportunity denominators. A penalty goal marker is not a complete open-play/set-piece
classification for shots, xG or xA. Clean opportunity decomposition remains unavailable.

The latest inspected complete prospective FPL capture is
`1bfb3d92-6d5e-48bf-a665-1f489dc6c1da` (September 8, 2026 at 03:37:39.610696 UTC): 654 element
summaries and 1,890 all-position player-fixture rows over thirty matches. Minutes, starts,
xG/xA/xGI and ICT components are retained with real times. Shots/SOT/box touches/key passes are
not present. The existing daily player-history workflow (07:30 UTC), provisional capture
(01:00/05:00 UTC), and independently callable pre-deadline full-history refresh already capture
the available FPL fields. No production code or capture semantics needed changing in this task.

The current-stream revision audit compares 11,180 history versions over 1,890 keys and 9,290
consecutive pairs: zero observed xG/xA/xGI/minutes/starts/goals/assists revisions in this short
sample. In contrast, 307 keys have an ICT-component revision (286 influence, 279 creativity,
190 threat and 300 ICT). Absence of xG revisions here is not proof of provider immutability.
Historical snapshot revision counts are reported separately with the acquisition manifest.

Continue retaining complete versioned FPL element-summary, bootstrap and fixtures captures with
actual timestamps. Player-season SDP aggregates are not a substitute for fixture-grain evidence.
Any future additional player-event collector needs an independently established endpoint,
identity, field definition and raw-availability contract before use.

## Execution and verification record

The scope and importer were frozen from a clean worktree in commit
`728aa174e686f23261a20b2dcf10c63f9d414f5b`, following starting SHA
`266a71f29767562005aa3d518d6501bcfa4f4ba1`. The one authorized acquisition started at
2026-09-08 07:43:09 UTC; its last network response was captured at 07:46:43 UTC and normalization
completed at 07:48:06 UTC. It made 143 fresh requests, reused nine audited raw files, received
only HTTP 200 responses, needed zero retries and retained 117,379,472 response bytes.
All 152 source files and their immutable receipts remain available locally.

The run contains **26,312 unique outfield player-fixture observations / 765 players** across
2023/24 GW1-38: DEF 9,611; MID 12,847; FWD 3,854. All observations map to exact stable player
codes and historical positions (100%; zero contradictions). The complete cross-snapshot registry
contains 865 stable player identities, including keepers and players without an outfield row.
Every row has measured xG/xA; shots, SOT, key passes and box touches are NULL for all rows.
No ratios with retrospectively contaminated team denominators are constructed. Compatible
complete player/team observation and availability witnesses would be required for any later share.

An independent implementation checked all **152 raw hashes and 549,219 cumulative raw
player-fixture appearances across versions**, reconciled every emitted normalized row, and
retained 304 deterministic seed-0 raw examples. There were zero normalized row revisions across
these archived merged-GW snapshots. The collector appends historical GW observations; unchanged
archive rows therefore do not establish that the underlying provider never revised its values.
The current prospective revision findings above remain a separate observation.

The frozen practical screen passes all seven checks:

| Measured data adequacy | Actual |
|---|---:|
| Target GWs with an eligible whole-future-GW archived snapshot | 36 |
| Eligible player-fixture target labels | 24,947 |
| Unique eligible players | 763 |
| DEF / MID / FWD targets | 9,106 / 12,185 / 3,656 |
| Players with at least 3 / 5 / 10 witnessed prior starts | 399 / 374 / 308 |
| Target rows with at least 3 / 5 / 10 witnessed prior starts | 11,110 / 9,273 / 5,961 |
| Paired xG/xA target measurement | 100% |
| Target rows without any eligible prior observation | 25 |

The 37 considered target GWs are GW2-38. GW17 has no archived snapshot that witnesses its exact
whole eventual fixture population as still future: its 607 target labels are excluded from this
coverage population. The specific mismatch is fixture 162 Bournemouth-Luton: the December 11
snapshot still schedules it in GW17, while the first snapshot with the final nine-fixture
population is dated December 21, after GW17 began on December 15. The fixture subsequently
appears in GW28. The separate immutable attribution receipt has SHA256
`1f6b491677c3a7a1463735fb1bbdaeba6ee5703b8c9411a2a4aafcc486ca6919`.
Another 165 rows have no exact pre-cutoff registry entry and eleven have a
pre-cutoff club mismatch. No position mismatches were found. The reconciliation is
25,730 planning targets - 607 schedule-excluded - 165 registry-excluded - 11 club-excluded =
24,947. These are valid exclusions, not repaired or zero-filled history. The eligible count is
over retained observed target labels; it is not a claim that an entire prospective player roster
was forecast historically.

The earliest usable historical snapshot cutoff is **2023-08-16 02:35:27 UTC**, for 2023/24 GW2:
522 eligible player targets, first target kickoff August 18 at 18:45 UTC. This is class-B
archived-as-of availability. **No exact official historical FPL deadline or independently attested
original public push time has been established.** Passing this data screen authorizes no model
claim; the next study must explicitly accept and preregister the qualified cutoff convention.

Offline replay made zero source requests and reproduced all 45,119,871 normalized bytes exactly.
The original and replay manifest identities differ only as separate execution receipts; source
capture times and normalized prediction-independent observations remain unchanged.

| Artifact | SHA256 |
|---|---|
| Frozen source audit | `1d42aeb5481b0b224d68bb498e2350c7a9fc54c2b06656c3fdb96f915db29952` |
| Frozen acquisition config | `2403c87e9de6e284801b97b450f5841606177f03ee30593fbd3de642c444f72a` |
| Original acquisition manifest | `56da2a8c52f96c2d7d4b68586d86d9eeee3fc4011ae17235ddcf940b58dcf03c` |
| Normalized observations JSONL | `0d699021537dc7e636f0dfb8e4484f98fc57263663806631c5c8e075b0c5cefc` |
| Independent raw/coverage audit | `146a7209c412e20fbebb63c3c8377097d95b1cd711baf5cf465cb78da4edb409` |
| Offline replay manifest | `a24ccab0317a621510b044167b34d386ebadcb7bfb14ba6cdc9c8c3e201589e3` |

The Git-tracked original acquisition manifest and independent audit are exact byte copies of
their immutable local receipts. Raw source files and normalized data live under the persistent
operator evidence root:
`D:/Personal/fpl-operations/verification/historical-player-attacking-20260908T070723Z/`.
Retain this whole root, including earlier audit-probe directories used by nine cached receipts;
the original `backfill-v1/source-index.json` resolves each exact file. The independent audit
script and source-scope review receipt are retained there with their hashes. No operational DB
was written.

The acquisition command (already run once; do not repeat its reserved identity) was:

```powershell
python -m fpl.jobs.backfill_historical_player_attacking `
  --config config/historical_player_attacking_backfill.yaml `
  --output-dir D:/Personal/fpl-operations/verification/historical-player-attacking-20260908T070723Z/backfill-v1
```

The supported no-network reproduction command uses a new output directory:

```powershell
python -m fpl.jobs.backfill_historical_player_attacking `
  --config config/historical_player_attacking_backfill.yaml `
  --replay D:/Personal/fpl-operations/verification/historical-player-attacking-20260908T070723Z/backfill-v1 `
  --output-dir D:/Personal/fpl-operations/verification/historical-player-attacking-20260908T070723Z/offline-replay-v1
```

The displayed replay directory is also already occupied by its immutable verified receipt;
choose another fresh directory for any subsequent offline replay. The replay requires identical
frozen parser/config/source-audit inputs and a clean V2 worktree.

Validation: **65 focused pytest tests passed; 142 relevant broader regressions passed**. Global
Ruff passed; strict mypy passed for 207 source files; changed-file formatting passed for all four
new Python files. Focused tests cover historical position and transfer clubs, exact identities,
NULL versus measured zero, availability/evidence classes, whole-GW exclusion, first-version and
future-truncation invariance, raw hashes, duplicates/reversions, frozen scope, bounded retries,
exclusive claims and deterministic offline replay. The broader run covers prior feasibility,
PIT, live snapshots, quality rules, archive building/attacking ingestion, SDP selection and
competitive participation. JUnit receipts and exact commands are retained under the evidence root.

All 159 pre-existing research/config/model/production file fingerprints remain unchanged,
including the prior feasibility result SHA256
`65b950bfb95c965f4c776964f4b18074fa60aa74e4b7224b355ef969e0e31ed7`.
No source under existing models, features, optimizer, storage or production jobs was changed.
No model was designed, fitted, tuned, evaluated or promoted; frozen scientific verdicts and the
SDP primary/incumbent fallback decisions are untouched.

The complete repository suite and global formatting were not rerun. Previously documented Windows
symlink failures and eleven unrelated global-format failures remain inherited limitations; they
are not represented as a passing full-repository check. New pytest basetemp directories avoided
the inherited default Windows temporary-directory permission issue without permission changes.

## Answers to the requested source questions

| Question | Finding |
|---|---|
| 1. Sources investigated? | Retained five-season FPL archive, local captures/manifests/Git history, upstream 2023/24-2025/26 commit histories, retained SDP match/lineup/event payloads, and two source-evidenced SDP endpoint probes. |
| 2. True player/GW snapshots? | Immutable upstream merged-GW plus same-commit registry/fixture/team bundles; current complete FPL element-summary captures. SDP probe is season aggregate only. |
| 3. Defensible historical times? | Audited 2023/24 class-B commit sequence; actual THE COMET historical capture and original public push timestamps are not established. |
| 4. Bulk retrospective sources? | Own five-season downloads are July/August 2026 captures. The 2025/26 upstream sequence is sparse/bulk; 2024/25 includes a later correction. 2023/24 has a late GW26 import kept at its true March source time. |
| 5. Earliest strict historical season? | No class-A claim. Qualified class B starts with 2023/24 GW1 observations on August 16, usable for the GW2 snapshot-cutoff population. |
| 6. Chronological targets? | 36 eligible archived-snapshot target GWs, GW2-38 excluding GW17; 24,947 player-fixture targets. |
| 7. Attacking fields? | xG, xA, xGI; minutes/starts and descriptive goals/assists/points/ICT components. |
| 8. Historical xG/xA? | All acquired 2023/24 rows measured; retained 2022/23 begins measured coverage at GW16; no 2021/22 field. |
| 9. Shots/SOT? | Not in the acquired player-match source. Team-level SDP values are not allocated to players. |
| 10. Box touches? | Not available at player-match grain in the selected evidence. |
| 11. Key passes/chances created? | Not in the historical player-match sample. A currently probed SDP season aggregate is insufficient. |
| 12. Open play versus set pieces? | No complete player opportunity decomposition established; no decomposition invented from xG or goal events. |
| 13. Deterministic player identity? | Yes: 100% of normalized rows map via exact same-snapshot numeric element to permanent code; zero contradictions. |
| 14. Historical position? | Yes for every acquired row, from same-season/source position and registry; no 2026/27 position projection. |
| 15. PIT-safe transfers? | Fixture-side membership is preserved; future targets require the pre-cutoff registry club. Eleven mismatches remain excluded; no inferred transfer announcement date. |
| 16. Revision risk? | Zero archive row revisions observed across 38 snapshots; source collector behavior and sparse publication limit inference. Current FPL captures show ICT revisions. All raw versions remain retained. |
| 17. Enough data? | The frozen practical data screen passes for a qualified xG/xA archived-snapshot study. Predictive usefulness is untested; exact historical deadline replay remains unproven. |
| 18. Backfill executed? | Yes, once, after clean scope commit; offline replay only afterward. |
| 19. Exact population? | One source, 2023/24 GW1-38, DEF/MID/FWD, 38 pinned commits, four fixed files each, 26,312 unique rows / 765 players. |
| 20. Why not broader? | Additional seasons/endpoints were outside the frozen scope; stronger publication/deadline and player-event evidence was not established. |
| 21. Prospective capture? | Retain complete immutable FPL element-summary/registry/fixtures with actual timestamps through existing daily and pre-deadline jobs. Preserve revisions and NULLs; certify any new fixture-level SDP player feed separately. |

## Next task

Design the smallest scientifically defensible Attacking Role Premium experiment supported by
these fields and seasons. It must explicitly use the audited archived-snapshot cutoffs, preserve
the class-B qualification, and remain separate from exact FPL-deadline or production claims.
Do not implement or evaluate that modeling task in this data-acquisition session.
