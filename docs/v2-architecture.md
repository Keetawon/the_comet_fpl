# The Comet FPL V2 — football-first prediction engine

Status: implemented (development-only), 2026-09-04
Supersedes nothing. V1 remains committed, runnable, and evidentially intact.

## Why V2 exists

V1 is an FPL model that grew football features. Its Stage A predicts a team goal rate; every
later stage consumes that single scalar. Three measured defects in `AGENTS.md` share one root
cause -- there is no *football environment* between the team model and the FPL components:

* **Goalkeeper saves are a deterministic function of goals conceded.** V1 models
  `saves ~ Poisson(k * lambda_conceded)` with `k = s/(1-s)` from the league-constant save rate.
  Shots on target faced is therefore not a random variable at all; it is `lambda_conceded/(1-s)`.
  Two clubs conceding the same expected goals from wildly different shot volumes are
  indistinguishable, and the saves distribution is under-dispersed by construction.
* **Defensive contribution is a per-player trailing hit rate.** The measured constant says DC is
  a property of the *team system* (team hit rates 0.333 to 0.146), yet V1 has no team
  defensive-action environment to allocate from, so a transferred player carries his old club's
  DC rate.
* **Attacking output is mis-allocated by position** (forwards 38-40% too few assists, defenders
  +29%/+61% too many goals, goalkeepers allocated 1.0-1.6 goals against an actual zero). The
  allocation runs on a trailing xG share with no territorial or chance-quality context.

V2 inserts the missing layer:

```
Premier League / FPL data
        v
  Football data layer      provider-tagged team-match football metrics
        v
  Football engine          joint attack/defence ratings, one per signal
        v
  Fixture environment      a typed bundle of per-fixture football predictions
        v
  FPL component engine     minutes, goals, assists, saves, DC, bonus
        v
  Full points distribution
        v
  Decision / optimizer
```

The contract between the football half and the FPL half is `FixtureEnvironment`
(`src/fpl/artifacts/fixture_environment.py`). Components receive it; they never query a table.

## What is deliberately NOT changed

* No V1 module is deleted or rewritten. `models/team_goals.py`, every `dev_*` runner, every
  frozen `results/*.json`, every candidate document and every ledger row is untouched.
* No frozen evaluation is re-run, amended, or re-judged.
* No prospective default changes. `--engine v1` remains the default everywhere; V2 is opt-in
  behind an explicit flag until it clears its own pre-registered gate.
* Recorded `total_points` is still never a feature or a cross-season target.

## Provider-agnostic football data layer

The central design decision. `mart_fact_team_match_stats_v2` is **not** "the SDP table". It is
*the team-match football metric fact*, at one club x one fixture, carrying a `provider` column.
Two providers ship:

| provider | source | availability | metrics |
| --- | --- | --- | --- |
| `fpl_archive` | derived from `mart_fact_player_fixture` / `mart_fact_team_match` already in this repo | every season, always | goals, xG, xGC, BPS, shots-on-target-faced proxy, defensive actions where measured |
| `pl_sdp` | Premier League SDP JSON backend | requires network capture | the full Opta metric set: xGOT, SOT, box touches, big chances, possession, territory, duels, press regains |

Consequences that matter:

1. **V2 does not require SDP to run.** The football engine is signal-agnostic: a signal absent
   from a selected provider simply does not participate. This is how the frozen archive-only
   evaluation ran before any SDP byte was captured.
2. **Reconciliation is structural, not a script.** Two providers on the same grain make
   "SDP xG vs summed player xG" a query, and disagreement is retained rather than reconciled away.
3. **Nothing is zero-filled.** A metric a provider does not carry is NULL, and NULL means
   unmeasured everywhere downstream, exactly as R-rules require.

The shots-on-target-faced proxy deserves a note, because it is what makes GK Saves V2 measurable
without SDP. For a goalkeeper appearance the archive records `saves` and `goals_conceded`, and
`saves + goals_conceded` is the count of on-target shots the keeper dealt with. Summed over a
club's goalkeeper rows in a fixture it is a *measured* team-level "shots on target allowed",
available from 2021-22. It is recorded as `shots_on_target_allowed_proxy`, kept separate from
SDP's `shots_on_target_allowed`, and never silently substituted for it.

## Schema

```
raw_pl_sdp_payload            append-only; exact provider bytes, sha256, endpoint, params, fetched_at
        v
stg_pl_sdp_match              typed match identity: sdp_match_id, season label, matchweek, kickoff, sides, score
stg_pl_sdp_team_match_stats   one team side per match: typed high-value columns + raw stats JSON
stg_pl_sdp_team_match_metric  tall store: (sdp_match_id, side, provider_field) -> value. Nothing is dropped.
stg_pl_sdp_fixture_crosswalk  sdp_match_id <-> (season, fixture), with the match method and evidence
        v
mart_fact_team_match_stats_v2      one club x one fixture x provider; typed metrics + opponent mirrors
mart_fact_team_tactical_form_v2    rolling windows per team_code (3/5/10/season), latest SDP version
```

The hybrid staging schema (typed columns + raw JSON + tall metric rows) is the answer to an
undocumented provider: a new upstream field lands in the tall store and is reported by the audit
job, without a migration and without being lost. A field is promoted to a typed column only after
its semantics are recorded in `config/pl_sdp_metrics.yaml`.

## Identity

`pulse_id` already exists on `stg_fixture` / `mart_fact_team_match`. Whether it equals the SDP
`matchId` is **measured, not assumed**, by `fpl.jobs.audit_pl_sdp`, which writes
`results/pl_sdp_identity_audit.json`. Resolution order:

1. exact `pulse_id == sdp_match_id`, then corroborated on season, kickoff date, and both clubs;
2. otherwise candidates by season and kickoff, narrowed by teams and then score when multiple;
   the selected candidate's Home/Away team codes are always corroborated before acceptance;
3. ambiguity, contradiction, or a corroboration failure **fails closed** and is reported. There is
   no fuzzy name matching anywhere.

Club identity crosses the boundary on `team_code`, never `team_id`. Player identity, where the
lineups endpoint is used, crosses on FPL `code` via `opta_code`, never `element_id`.

## Point-in-time

The V2 marts are added to `FEATURE_READABLE_TABLES` and every post-match metric column is added to
`OUTCOME_COLUMNS`, so `PointInTimeView.observed_*` hard-filters them on `kickoff_time < as_of` and,
whenever present, `known_at <= as_of`; `schedule()` cannot project them. Tactical rows carry the
maximum source `known_at` in their rolling window. The latest-value team-match mart cannot recover
an older provider version after a restatement, so an early read fails closed rather than falling
back. The evaluation harness separately rejects `provider='pl_sdp'`. These guards prevent leakage,
but do **not** make a September 2026 historical backfill valid inside earlier walk-forward folds. A
version-preserving as-of mart/reader is required before such an evaluation.

## Football engine

`models/football_engine_v2.py` generalises the V1 Stage A fit. V1 fits one multiplicative
attack/defence/venue decomposition to a single measure (xG rescaled onto goals). V2 fits **one
such rating system per signal**, on the same schedule-adjusted, time-decayed, prior-shrunk
estimator, and then blends the signal-specific goal-rate predictions with weights chosen on a
fold-local inner holdout.

That single change buys three things at once:

* an ablation ladder that is a *nested sequence of the same model*, so a lift is attributable to
  the signal rather than to a change of functional form;
* the environment for free -- the SOT rating system's prediction *is* expected shots on target,
  which is what GK Saves V2 needs, and likewise for box touches and defensive actions;
* graceful degradation -- with only `goals` and `xg` present the blend reduces to V1's behaviour.

Candidate ladder (pre-registered in `config/v2_team_environment_evaluation.yaml`):

| candidate | signals |
| --- | --- |
| A | goals |
| B | goals + xG |
| C | goals + xG + shots on target |
| D | goals + xG + SOT + box touches / big chances |

## Component engine

* **Minutes** is unchanged. V1's research remains valid and SDP does not bear on it.
* **Goals / assists** consume `FixtureEnvironment.expected_goals_*` exactly as V1 consumed the
  Stage A lambda, so the existing team-coupled allocation is reused rather than rebuilt.
* **GK saves V2** replaces `k * lambda_conceded` with `saves ~ Binomial-thinned Poisson` over the
  *predicted shots on target faced*, times the league save rate. Where SOT is unavailable it falls
  back to the V1 identity, so it is never worse-informed than V1.
* **DC V2** allocates a predicted team defensive-action environment across the roster by role
  share and minutes, instead of carrying a per-player hit rate across a transfer.
* **Bonus** keeps V1's joint within-match BPS simulation; the environment enters only as context.

## Evaluation

New contracts, none of which touch a V1 config:

* `config/v2_team_environment_evaluation.yaml`
* `config/v2_gk_saves_evaluation.yaml`

Same discipline as Phase 1: pre-registered before the candidate runs, walk-forward by observed
gameweek, hyperparameters chosen inside the fold, proper scores, per-season and per-regime splits,
and a contract version that cannot be bumped without an amendment record.

## Milestones

| milestone | content | state |
| --- | --- | --- |
| A | SDP source, raw capture, identity audit | implemented |
| B | typed staging, V2 team-match mart, coverage report | implemented |
| C | kickoff/knowledge-time-safe V2 access; SDP version-as-of evaluation | guards implemented / reader pending |
| D | `FixtureEnvironment` + V2 football engine | implemented |
| E | GK saves V2 | implemented |
| F | V2 team-coupled components (DC environment) | implemented |
| G | composer integration | implemented |
| H | V2 prospective forecast artifact | implemented |
| I | optimizer compatibility | implemented (unchanged input contract) |
| J | dashboard / analytics exposure | deferred, see DEV-ROADMAP.md |

## Known limitations

* The owner machine completed the first real SDP capture on 2026-09-05. It observed 246 provider
  fields and populated `pl_sdp` with 1,921 matches / 3,842 team sides; see
  `docs/pl-sdp-real-provider-validation-2026-09-05.md`. Only the three mappings independently
  corroborated by the reconciliation report are marked semantically verified. Unmatched or
  unverified fields remain losslessly retained in the tall metric store.
* All existing measured V2 results remain from `fpl_archive`. Historical SDP payloads were first
  known in September 2026. Immediate feature reads now filter provider knowledge time and the
  historical evaluation loader rejects SDP, but no version-preserving provider reader exists for
  old folds. A genuine SOT or territory walk-forward evaluation therefore remains unlicensed until
  an additive point-in-time contract and version-preserving reader exist.
* V2 is development-only. It has not been promoted, and the prospective default is unchanged.
