# Current V2 GW1-3 frozen diagnostic: INVALID

**The formal audit produced no forecasts or scores.** It stopped during input
metadata publication because the audit harness failed its canonical byte-replay
guard. This is an audit-serialization defect, not evidence of a Player Model defect.
The single claimed run is preserved as **INVALIDATED_BY_IMPLEMENTATION_BUG**.
Neither lane was evaluated. No model repair, harness repair, retry or replacement
audit was performed after the failure.

## Phase A completed and pushed first

Initial HEAD was `35417a32d39dd165fa99a3f3d09f8215ed3eadd6`. The handoff contained
nine legitimate staged scouting files and no unpushed commits. Those changes were
preserved, reviewed and completed; no reset, discarded work or stash was used.
The valid scope was a separate immutable JSON/CSV descriptive scouting export.
Final source checks tightened raw/manifest, season, identity and missing-value
handling. The isolation fixture used distinct synthetic utilities after an existing
equal-utility optimizer tie issue was reproduced independently; no optimizer changed.

Implementation commit: `dad1f87f63f131db13b568194d987d46f7ea4aa4`.
**PHASE_A_END_SHA: `17cfa2267ce4d7c89f96842220f40471b81152d2`**, pushed to V2 and
verified clean/synchronized before Phase B. Remote main had advanced externally;
this task did not change local main or publish to remote main.

The [scouting report](player-attacking-usage-scouting-2026-09-08.md) and
`results/player_attacking_usage_scouting_verification_2026-09-08.json` retain the full
Phase A evidence. Current GW1-3 coverage is 583 outfield players, 1,682 measured
xG/xA rows and 869 positive-minute rows. There are 232 players with >=90 minutes,
165 with >=180, and none yet with >=360/450/900. Exposure is 418 VERY_LOW and 165 LOW;
218 players have no observed history. Four defenders meet the fixed descriptive
watchlist rule, all with LOW exposure.

Long/recent profiles, fixed 360-minute recency, 450-minute shrinkage, equal xG/xA
position percentiles, deltas and exposure remain descriptive. Cold starts display
NULL/UNKNOWN. No usage field enters predictions, xP, PMFs, FixtureEnvironment,
captaincy, transfers or optimizer utility. The frozen V1 verdict remains REFUTED.

The real before/after GW4-5 production comparison used identical frozen inputs and
2,000 draws, with 654 players. Both primary and shadow retained exact record bytes:
1,308 player-GW, 1,308 player-fixture and 40 team-side rows each. PMFs, xP, bonus,
selectors, GK/workload provenance, XI/bench/captains and transfer decisions matched.
Whole artifacts retain truthful differing Git provenance; they are not falsely
claimed byte-identical. Optimizer decision SHA256:
`89afd1edd6a44ab332bd542c0eab6c1b1e3fcd757d48b105fcc5a6de781e9c14`.

## Freeze, comparator and input reconstruction

Model/config freeze is the Phase A end commit above. Preregistration SHA:
**`0a7c7640288ae785003075fbcec1c63772f6e203`**.
The [preregistration](player-model-gw1-3-preregistration-2026-09-08.md) and YAML pin
339 pre-existing files, runtime, source database, cutoffs, exact component path,
seeds/draws, metrics, two evidence lanes and stop rules. Their bytes remain unchanged.

The required incumbent is the existing recursive shadow: **the same current player
components with `trailing_goals_attack_defence` as the team environment**. It is not
a newly assembled older full-player baseline. The planned execution preserved
`v3` goals, `seasonal` appearance, `auto` shares, `coupled` assists, 2,000 draws,
seed 202627 and the existing points/BPS composition. No new parameter search was
introduced; existing history-only estimation would have remained unchanged.

| GW | Official cutoff UTC | Registry known_at UTC | Input players | Fixtures | Prior live rows |
|---|---|---|---:|---:|---:|
| 1 | 2026-08-21 17:30 | 2026-08-21 06:41:56 | 599 | 10 | 0 |
| 2 | 2026-08-28 17:30 | 2026-08-27 17:19:42 | 616 | 10 | 610 |
| 3 | 2026-09-04 17:30 | 2026-09-04 11:05:54.219177 | 652 | 10 | 1,236 |

These are reconstructed input counts, **not scored populations**. All target fixtures
were future at their cutoff. Retained bootstrap witnesses establish the deadlines;
the exact selected FPL capture IDs, raw hashes and prior-history times are retained
in the preregistration and failed run's immutable `historical-inputs.json`.
All 20 archive source CSVs reconcile to July/August capture receipts and unchanged
prior marts. Every consumed prior fixture was completed. That evidence supports
prior inputs at these 2026/27 deadlines, not historical 2021-26 PIT replay.

The SDP model artifact was known September 7, after all three deadlines. Exact
production policy therefore requires `SDP_MISSING_FALLBACK` in Lane A. No workload
evidence existed at these cutoffs; GK H was also unavailable and remains shadow-only.
This establishes expected fallback policy, **not an executed equality assertion**.
Actual SDP-primary/fallback forecast counts are NULL because inference never ran.

Lane B was designed to retain true September SDP/crosswalk/model timestamps while
counterfactually making pre-target completed football evidence available. Its
schema/identity/health and whole-GW exclusions remain frozen. It was not executed.
Both lanes are now **UNAVAILABLE: formal harness invalidated before inference**.

## Failure record and independent reproduction

Command, run identity and original receipts:

```text
python -m fpl.jobs.evaluate_player_model_gw1_3
audit_id: player_model_gw1_3_20260908_v1
started_at: 2026-09-08T10:22:36.372830+00:00
failed_at: 2026-09-08T10:22:37.016689+00:00
stage: input_preflight
error: canonical artifact replay changed bytes
output: D:/Personal/fpl-operations/verification/player-model-gw1-3-audit-20260908T095300Z/formal-v1
```

The shared Git-common-directory claim remains reserved and `resume_permitted=false`.
Only `run-start.json`, `historical-inputs.json` and `invalid-run.json` exist. There
are zero forecast artifacts, component sidecars, outcome files or scored results.
The original failure receipt uses the runner's broad implementation-or-input status;
the additive verification identifies the specific implementation defect without
rewriting that receipt.

The bug is in the new audit `canonical`/`_write_json` transport. Python sorts integer
fixture keys numerically before encoding them as JSON object keys. JSON decodes
those keys as strings, whose next sorted encoding uses lexical order. For example:

```text
initial: {"fixture_gameweeks":{"1":1,"2":1,"10":1}}
replay:  {"fixture_gameweeks":{"1":1,"10":1,"2":1}}
```

The data values agree but the required bytes do not. Publication correctly refused
to continue. Synthetic transaction tests covered missing/changed files and whole
population ordering but missed this integer-key representation. A new post-failure
regression records the exact defect and write-once behavior; it does not repair the
frozen implementation. This failure is **new and task-owned**, not an inherited
Windows/environment problem.

| Original receipt | SHA256 |
|---|---|
| run-start.json | `0896457593cace3ba2cb6961bc5e682584efaaa78abbd1e093e583ea4b9e4e0b` |
| historical-inputs.json | `15b90fb00cd857fc02ef1d54b1f60bcf95343256652c916064f55010fcfa86b8` |
| invalid-run.json | `a0690b4bf7a1627278b38cbe95cf1ed4bddf5b5aa8b7727d8036c8a9b86867ee` |

## Scorecard: unavailable, never zero-filled

| GW | Scored rows | V2/incumbent CRPS | Log score | xP MAE | Bias | Spearman | Top/captain actuals |
|---|---:|---|---|---|---|---|---|
| 1 | 0 | NULL / NULL | NULL | NULL | NULL | NULL | NULL |
| 2 | 0 | NULL / NULL | NULL | NULL | NULL | NULL | NULL |
| 3 | 0 | NULL / NULL | NULL | NULL | NULL | NULL | NULL |
| Pooled | 0 | NULL / NULL | NULL | NULL | NULL | NULL | NULL |

All GK/DEF/MID/FWD slices, top10/25/50, captain1/3/5, paired GW direction and uncertainty
are unavailable. Minutes, goals, assists, CS, conceded, saves, DC and bonus/BPS
scorecards are also NULL. The top25 forensic miss audit did not run; there is no
dominant player-model failure classification. Zero scored rows describes execution
status, not missing player evidence or zero football outcomes.

The planned proper-score support limitation remains explicit: points are folded into
0-34 per fixture, with signed actual points retained separately for MAE/bias. The
minutes contract provides a bin-representative expected-minutes proxy and P(any)/P60,
not an exact P(start). No unavailable metric is substituted with another quantity.

## Answers and evidence boundary

The retained inputs support safe cutoff reconstruction, but this run does **not**
establish a valid full replay. It cannot answer absolute xP quality, PMF calibration,
whether V2 beats incumbent, GW directions, ranking utility, worst position, minutes
dominance, goal/assist/CS/save/DC/bonus calibration, largest misses or actual SDP value.
No observed Player Model failure or improvement can be inferred from a serializer
failure. Expected strict fallback equality was not turned into a fake scorecard.

No target outcomes were read by the formal scoring code and no target statistics
entered features: the run stopped before inference. Synthetic cutoff/GW/DGW, identity,
observer, seed, class-B counterfactual and fallback tests passed, but they do not
replace the missing real replay. Model and source hashes still match all 339 pins,
including Phase A scouting and frozen V1 science. Immutable source DB remains
`538560454f551a48eeaf015c318f7dea0fc6a34fccc56ee7f0e2b117ef7330d6`.

Even a completed Lane A would be a retrospective frozen diagnostic because model
development followed GW1-3. Lane B would additionally be a source-availability
counterfactual. Neither can supply prospective promotion evidence.

## Verification and resource decision

Phase A: 77 new tests in final groups; 148 related source/PIT/arithmetic regressions;
81 dashboard passes with four inherited Windows symlink skips; 16 selected BI passes.
Source strict mypy and changed-file formatting passed. Real forecast/optimizer
noninterference passed as detailed above.

Phase B before the run: 143 focused tests across final groups (the combined 141-test
run plus two added promoted-source tests), 164 relevant production/SDP/player/scouting
regressions, repository Ruff, strict mypy on 220 source files, and formatting of all
11 changed Python files passed. These checks did not catch the formal serialization
defect. The additive failure regression is reported separately in the verification
artifact. No repeated retry of known unrelated environment failures occurred.

Inherited limitations remain: Windows directory-symlink skips, legacy imported test
fixture type errors under unrestricted test-body mypy, pre-existing global formatting
issues, equal-utility synthetic optimizer tie ambiguity and PuLP deprecation warnings.
They are distinct from the new formal audit failure.

**Diagnostic verdict: INVALID.**

**Does this GW1-3 evidence justify another Player Model feature/research branch now?
NO.** No model performance evidence was produced. Keep production frozen and continue
the existing GW4-8 prospective scorecard. Completing this retrospective audit would
first require a serializer-only harness repair and a new explicitly preregistered
audit identity; neither is implemented here. No minutes/attack/role/OOP successor,
retuning, production adjustment or reinterpretation of frozen results is justified
by this failed run.

Phase A remains complete. Phase B's scientific measurement objective remains unmet;
this commit records the required invalidation rather than claiming completion of a
scorecard. All work stays on V2; main/default remain untouched and no PR is opened.

## Changed-file inventory and closing verification

Two independent read-only reviews reproduced the transport defect, confirmed the
absence of forecasts/outcomes/scores and matched all 339 frozen files plus all eight
preregistered implementation fingerprints. No failure receipt was changed.

The combined Phase A/B delivery changes 28 files:

- `.gitattributes`
- `README.md`
- `config/player_model_gw1_3_audit.yaml`
- `docs/player-attacking-usage-scouting-2026-09-08.md`
- `docs/player-model-gw1-3-preregistration-2026-09-08.md`
- `docs/player-model-gw1-3-scorecard-2026-09-08.md`
- `results/player_attacking_usage_scouting_verification_2026-09-08.json`
- `results/player_model_gw1_3_retrospective_sdp_2026-09-08.json`
- `results/player_model_gw1_3_strict_2026-09-08.json`
- `results/player_model_gw1_3_verification_2026-09-08.json`
- `src/fpl/features/player_attacking_usage.py`
- `src/fpl/jobs/build_player_attacking_usage.py`
- `src/fpl/jobs/evaluate_player_model_gw1_3.py`
- `src/fpl/publish/player_attacking_usage.py`
- `src/fpl/validate/player_model_gw1_3_audit.py`
- `src/fpl/validate/player_model_gw1_3_metrics.py`
- `src/fpl/validate/player_model_gw1_3_replay.py`
- `src/fpl/validate/player_model_gw1_3_sources.py`
- `src/fpl/validate/sdp_counterfactual.py`
- `tests/test_player_attacking_usage.py`
- `tests/test_player_attacking_usage_export.py`
- `tests/test_player_attacking_usage_isolation.py`
- `tests/test_player_model_gw1_3_audit.py`
- `tests/test_player_model_gw1_3_invalidation.py`
- `tests/test_player_model_gw1_3_metrics.py`
- `tests/test_player_model_gw1_3_replay.py`
- `tests/test_player_model_gw1_3_sources.py`
- `tests/test_sdp_counterfactual.py`
