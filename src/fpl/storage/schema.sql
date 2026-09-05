-- FPL model storage schema. DuckDB, single file.
--
-- Layers:  raw_  (as landed, immutable)  ->  stg_  (typed, deduped, crosswalked)
--          ->  mart_  (modelling-ready)
--
-- The raw_ tables for archive CSVs are NOT declared here. They are created at ingest
-- time from the union of the column headers actually observed across seasons, every
-- column VARCHAR. Two reasons this is deliberate rather than lazy:
--
--   1. VARCHAR preserves the difference between "" and "0.0". That distinction is
--      load-bearing (gotcha 5, and the 2022-23 present-but-zero expected_* defect);
--      any cast at landing time is an irreversible interpretation.
--   2. The archive's schema drifts by season -- expected_* appear in 2022-23, the
--      defensive_contribution family in 2025-26, mng_* only in 2024-25. Deriving the
--      table from observed headers means a future archive column lands rather than
--      being silently dropped.
--
-- raw_source_columns records each file's real header, so the stg_ layer can tell
-- "column absent from source" apart from "column present but empty".

-- ====================================================================================
-- raw layer: provenance and immutability support
-- ====================================================================================

CREATE TABLE IF NOT EXISTS raw_source_columns (
    season       VARCHAR NOT NULL,
    source_table VARCHAR NOT NULL,
    column_name  VARCHAR NOT NULL,
    ordinal      INTEGER NOT NULL,
    PRIMARY KEY (season, source_table, column_name)
);

CREATE TABLE IF NOT EXISTS raw_ingest_log (
    ingested_at  TIMESTAMPTZ NOT NULL,
    season       VARCHAR NOT NULL,
    source_table VARCHAR NOT NULL,
    source_url   VARCHAR NOT NULL,
    row_count    BIGINT NOT NULL,
    sha256       VARCHAR NOT NULL,
    PRIMARY KEY (season, source_table, ingested_at)
);

-- R5: append-only snapshot of the live API. Never updated, never deleted.
-- Missing a week is unrecoverable, so this table only ever grows.
CREATE TABLE IF NOT EXISTS snapshot_bootstrap (
    captured_at TIMESTAMPTZ NOT NULL,
    gw          INTEGER,
    endpoint    VARCHAR NOT NULL,
    payload     JSON NOT NULL,
    sha256      VARCHAR NOT NULL,
    PRIMARY KEY (captured_at, endpoint)
);

-- Phase 0b capture contract. A capture header and all of its payload rows are committed
-- in one transaction. `parameter` carries the gameweek or element id without baking it
-- into the endpoint name, and the manifest makes file/DB snapshots independently
-- verifiable.
CREATE TABLE IF NOT EXISTS snapshot_capture (
    capture_id      VARCHAR PRIMARY KEY,
    captured_at    TIMESTAMPTZ NOT NULL,
    season          VARCHAR NOT NULL,
    gw              INTEGER,
    mode            VARCHAR NOT NULL,
    payload_count   INTEGER NOT NULL,
    manifest        JSON NOT NULL,
    manifest_sha256 VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshot_payload (
    capture_id VARCHAR NOT NULL,
    endpoint   VARCHAR NOT NULL,
    parameter  VARCHAR NOT NULL,
    payload    JSON NOT NULL,
    sha256     VARCHAR NOT NULL,
    byte_count BIGINT NOT NULL,
    row_count  BIGINT,
    PRIMARY KEY (capture_id, endpoint, parameter),
    FOREIGN KEY (capture_id) REFERENCES snapshot_capture(capture_id)
);

-- Gotcha 13: pre-season payloads contain glitches (a goalkeeper with 11 goals and 0
-- minutes). Range and consistency violations are recorded here, never silently
-- dropped and never silently repaired.
CREATE TABLE IF NOT EXISTS ingest_anomaly (
    detected_at TIMESTAMPTZ NOT NULL,
    check_id    VARCHAR NOT NULL,
    season      VARCHAR,
    element     INTEGER,
    fixture     INTEGER,
    column_name VARCHAR,
    observed    VARCHAR,
    detail      VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS build_metadata (
    key        VARCHAR PRIMARY KEY,
    value      VARCHAR NOT NULL,
    written_at TIMESTAMPTZ NOT NULL
);

-- ====================================================================================
-- stg layer: typed, deduped on (season, element, fixture), crosswalked to `code`
-- ====================================================================================

-- Recorded `total_points` lives HERE and only here.
--
-- It is denominated in whichever season's rules applied at the time, so it is not a
-- cross-season quantity and cannot be a model target (R1). Keeping it at the staging
-- layer makes that explicit: the full-season replay test validates ingest and the
-- calculator together, which is correctly a staging concern.
--
-- `xP` is dropped at this boundary and never appears downstream (gotcha 11).
CREATE TABLE IF NOT EXISTS stg_player_fixture (
    season                          VARCHAR NOT NULL,
    element                         INTEGER NOT NULL,
    code                            INTEGER NOT NULL,
    fixture                         INTEGER NOT NULL,
    gw                              INTEGER NOT NULL,
    kickoff_time                    TIMESTAMPTZ NOT NULL,
    position                        VARCHAR NOT NULL,
    team_id                         INTEGER NOT NULL,
    opponent_team_id                INTEGER NOT NULL,
    was_home                        BOOLEAN NOT NULL,
    minutes                         INTEGER,
    starts                          INTEGER,
    goals_scored                    INTEGER,
    assists                         INTEGER,
    clean_sheets                    INTEGER,
    goals_conceded                  INTEGER,
    saves                           INTEGER,
    penalties_saved                 INTEGER,
    penalties_missed                INTEGER,
    own_goals                       INTEGER,
    yellow_cards                    INTEGER,
    red_cards                       INTEGER,
    bonus                           INTEGER,
    bps                             INTEGER,
    expected_goals                  DOUBLE,
    expected_assists                DOUBLE,
    expected_goals_conceded         DOUBLE,
    -- Opta indices. `threat` is the closest available proxy for shot volume, which the
    -- literature says stabilises faster than xG -- and measured here it does: season-to-season
    -- persistence 0.557 vs 0.319 (DEF), 0.828 vs 0.740 (MID), 0.625 vs 0.571 (FWD).
    -- They are also present for 2021-22, which has no xG at all.
    threat                          DOUBLE,
    creativity                      DOUBLE,
    influence                       DOUBLE,
    defensive_contribution          INTEGER,
    tackles                         INTEGER,
    recoveries                      INTEGER,
    clearances_blocks_interceptions INTEGER,
    value                           INTEGER,
    selected                        INTEGER,
    transfers_in                    INTEGER,
    transfers_out                   INTEGER,
    total_points                    INTEGER,  -- as recorded, contemporaneous rules
    PRIMARY KEY (season, element, fixture)
);

CREATE TABLE IF NOT EXISTS stg_fixture (
    season            VARCHAR NOT NULL,
    fixture           INTEGER NOT NULL,
    pulse_id          INTEGER,
    gw                INTEGER,
    kickoff_time      TIMESTAMPTZ,
    team_h            INTEGER NOT NULL,
    team_a            INTEGER NOT NULL,
    team_h_score      INTEGER,
    team_a_score      INTEGER,
    team_h_difficulty INTEGER,
    team_a_difficulty INTEGER,
    finished          BOOLEAN,
    PRIMARY KEY (season, fixture)
);

CREATE TABLE IF NOT EXISTS stg_team (
    season     VARCHAR NOT NULL,
    team_id    INTEGER NOT NULL,
    team_name  VARCHAR NOT NULL,
    short_name VARCHAR NOT NULL,
    team_code  INTEGER,
    pulse_id   INTEGER,
    PRIMARY KEY (season, team_id)
);

CREATE TABLE IF NOT EXISTS stg_player (
    season       VARCHAR NOT NULL,
    element      INTEGER NOT NULL,
    code         INTEGER NOT NULL,
    opta_code    VARCHAR,
    web_name     VARCHAR,
    element_type INTEGER NOT NULL,
    position     VARCHAR NOT NULL,
    team_id      INTEGER,
    PRIMARY KEY (season, element)
);

-- Current-season rows are versioned by the time they became known. They deliberately
-- remain separate from the archive, which cannot truthfully reconstruct knowledge time.
CREATE TABLE IF NOT EXISTS stg_live_player_version (
    season       VARCHAR NOT NULL,
    element      INTEGER NOT NULL,
    code         INTEGER NOT NULL,
    known_at     TIMESTAMPTZ NOT NULL,
    capture_id   VARCHAR NOT NULL,
    web_name     VARCHAR,
    element_type INTEGER NOT NULL,
    position     VARCHAR NOT NULL,
    team_id      INTEGER NOT NULL,
    now_cost     INTEGER,
    status       VARCHAR,
    PRIMARY KEY (season, element, capture_id)
);

-- Versioned live club registry, flattened from the bootstrap-static `teams` payload. It is the
-- only point-in-time source of the live season's season-scoped `team_id -> team_code` mapping and
-- club names; the archive marts (mart_dim_team/stg_team) cover completed seasons only, so without
-- this the BI export cannot resolve a live-season forecast's clubs to their cross-season identity.
-- Identity/registration metadata only, no outcome column.
CREATE TABLE IF NOT EXISTS stg_live_team_version (
    season      VARCHAR NOT NULL,
    team_id     INTEGER NOT NULL,
    team_code   INTEGER,
    known_at    TIMESTAMPTZ NOT NULL,
    capture_id  VARCHAR NOT NULL,
    team_name   VARCHAR NOT NULL,
    short_name  VARCHAR NOT NULL,
    pulse_id    INTEGER,
    PRIMARY KEY (season, team_id, capture_id)
);

CREATE TABLE IF NOT EXISTS stg_live_fixture_version (
    season            VARCHAR NOT NULL,
    fixture           INTEGER NOT NULL,
    known_at          TIMESTAMPTZ NOT NULL,
    capture_id        VARCHAR NOT NULL,
    gw                INTEGER,
    kickoff_time      TIMESTAMPTZ,
    team_h            INTEGER NOT NULL,
    team_a            INTEGER NOT NULL,
    team_h_score      INTEGER,
    team_a_score      INTEGER,
    team_h_difficulty INTEGER,
    team_a_difficulty INTEGER,
    finished          BOOLEAN,
    finished_provisional BOOLEAN,
    PRIMARY KEY (season, fixture, capture_id)
);

CREATE TABLE IF NOT EXISTS stg_live_player_fixture_version (
    season                          VARCHAR NOT NULL,
    element                         INTEGER NOT NULL,
    code                            INTEGER NOT NULL,
    fixture                         INTEGER NOT NULL,
    pulse_id                        INTEGER,
    known_at                        TIMESTAMPTZ NOT NULL,
    capture_id                      VARCHAR NOT NULL,
    gw                              INTEGER NOT NULL,
    kickoff_time                    TIMESTAMPTZ NOT NULL,
    position                        VARCHAR NOT NULL,
    team_id                         INTEGER NOT NULL,
    opponent_team_id                INTEGER NOT NULL,
    was_home                        BOOLEAN NOT NULL,
    minutes                         INTEGER,
    starts                          INTEGER,
    goals_scored                    INTEGER,
    assists                         INTEGER,
    clean_sheets                    INTEGER,
    goals_conceded                  INTEGER,
    saves                           INTEGER,
    penalties_saved                 INTEGER,
    penalties_missed                INTEGER,
    own_goals                       INTEGER,
    yellow_cards                    INTEGER,
    red_cards                       INTEGER,
    bonus                           INTEGER,
    bps                             INTEGER,
    expected_goals                  DOUBLE,
    expected_assists                DOUBLE,
    expected_goals_conceded         DOUBLE,
    -- Opta indices. `threat` is the closest available proxy for shot volume, which the
    -- literature says stabilises faster than xG -- and measured here it does: season-to-season
    -- persistence 0.557 vs 0.319 (DEF), 0.828 vs 0.740 (MID), 0.625 vs 0.571 (FWD).
    -- They are also present for 2021-22, which has no xG at all.
    threat                          DOUBLE,
    creativity                      DOUBLE,
    influence                       DOUBLE,
    defensive_contribution          INTEGER,
    tackles                         INTEGER,
    recoveries                      INTEGER,
    clearances_blocks_interceptions INTEGER,
    value                           INTEGER,
    selected                        INTEGER,
    transfers_in                    INTEGER,
    transfers_out                   INTEGER,
    total_points                    INTEGER,
    PRIMARY KEY (season, element, fixture, capture_id)
);

-- ====================================================================================
-- mart layer
-- ====================================================================================

CREATE TABLE IF NOT EXISTS mart_dim_player (
    code       INTEGER NOT NULL,
    season     VARCHAR NOT NULL,
    element_id INTEGER NOT NULL,
    web_name   VARCHAR,
    position   VARCHAR NOT NULL,  -- from element_type; see types.Position
    team_id    INTEGER,
    opta_code  VARCHAR,
    PRIMARY KEY (code, season)
);

CREATE TABLE IF NOT EXISTS mart_dim_team (
    season     VARCHAR NOT NULL,
    team_id    INTEGER NOT NULL,
    -- STABLE ACROSS SEASONS. `team_id` is reassigned every year and is meaningless
    -- outside its season: id 10 is Leeds, then Leicester, then Fulham, then Ipswich, then
    -- Fulham again. That last repeat is the dangerous one -- a cross-season join on
    -- team_id "works" and silently produces a Fulham history with Ipswich in the middle.
    -- `team_code` is 1:1 with the club (27 codes, 27 names across five seasons) and is the
    -- only key that may be used to follow a club between seasons, e.g. for Dixon-Coles
    -- time decay across a season boundary or for pooling promoted-team priors.
    team_code  INTEGER,
    team_name  VARCHAR NOT NULL,
    short_name VARCHAR NOT NULL,
    pulse_id   INTEGER,
    PRIMARY KEY (season, team_id)
);

-- One row per club spell a player had inside a season.
--
-- `mart_dim_player.team_id` records only the club a player finished the season at, so it is
-- wrong for roughly half of all transfer stints: measured 242 stints across five seasons, of
-- which the dimension matches only 120. Eze played GW1-2 for Crystal Palace and GW3-38 for
-- Arsenal; Buonanotte had three clubs in 2025-26 alone. Any feature that resolves a player's
-- team through the dimension attributes the wrong team strength, the wrong fixture and the
-- wrong defensive-contribution environment to ~25 players per season, silently.
--
-- Features must resolve a player's club from the fact row or from this table, never from
-- mart_dim_player.
CREATE TABLE IF NOT EXISTS mart_dim_player_stint (
    season         VARCHAR NOT NULL,
    code           INTEGER NOT NULL,
    team_id        INTEGER NOT NULL,
    stint_index    INTEGER NOT NULL,  -- 1-based, ordered by first appearance
    first_gw       INTEGER NOT NULL,
    last_gw        INTEGER NOT NULL,
    first_kickoff  TIMESTAMPTZ NOT NULL,
    last_kickoff   TIMESTAMPTZ NOT NULL,
    appearances    INTEGER NOT NULL,
    minutes        INTEGER,
    PRIMARY KEY (season, code, team_id)
);

-- COMPONENTS ONLY. No points column of any kind, by design and by test.
--
-- This is the only table the feature builder may read (alongside mart_fact_team_match
-- and the dimensions). Enforced in code: features receive a FeatureSource capability
-- that cannot name a mart_target_* table, not a raw connection.
--
-- Expected row count after a correct build: 139,029.
CREATE TABLE IF NOT EXISTS mart_fact_player_fixture (
    season                          VARCHAR NOT NULL,
    gw                              INTEGER NOT NULL,
    fixture                         INTEGER NOT NULL,
    pulse_id                        INTEGER,
    kickoff_time                    TIMESTAMPTZ NOT NULL,
    code                            INTEGER NOT NULL,
    position                        VARCHAR NOT NULL,
    team_id                         INTEGER NOT NULL,
    opponent_team_id                INTEGER NOT NULL,
    was_home                        BOOLEAN NOT NULL,
    minutes                         INTEGER,
    starts                          INTEGER,
    goals_scored                    INTEGER,
    assists                         INTEGER,
    clean_sheets                    INTEGER,
    goals_conceded                  INTEGER,
    saves                           INTEGER,
    penalties_saved                 INTEGER,
    penalties_missed                INTEGER,
    own_goals                       INTEGER,
    yellow_cards                    INTEGER,
    red_cards                       INTEGER,
    bonus                           INTEGER,
    bps                             INTEGER,
    expected_goals                  DOUBLE,
    expected_assists                DOUBLE,
    expected_goals_conceded         DOUBLE,
    -- Opta indices. `threat` is the closest available proxy for shot volume, which the
    -- literature says stabilises faster than xG -- and measured here it does: season-to-season
    -- persistence 0.557 vs 0.319 (DEF), 0.828 vs 0.740 (MID), 0.625 vs 0.571 (FWD).
    -- They are also present for 2021-22, which has no xG at all.
    threat                          DOUBLE,
    creativity                      DOUBLE,
    influence                       DOUBLE,
    defensive_contribution          INTEGER,
    tackles                         INTEGER,
    recoveries                      INTEGER,
    clearances_blocks_interceptions INTEGER,
    value                           INTEGER,
    selected                        INTEGER,
    transfers_in                    INTEGER,
    transfers_out                   INTEGER,
    PRIMARY KEY (season, code, fixture)
);

-- Same component-only contract as the archive mart, with bitemporal capture metadata.
-- PointInTimeView chooses the newest version whose known_at is no later than `as_of`.
CREATE TABLE IF NOT EXISTS mart_fact_player_fixture_live (
    season                          VARCHAR NOT NULL,
    gw                              INTEGER NOT NULL,
    fixture                         INTEGER NOT NULL,
    pulse_id                        INTEGER,
    kickoff_time                    TIMESTAMPTZ NOT NULL,
    code                            INTEGER NOT NULL,
    position                        VARCHAR NOT NULL,
    team_id                         INTEGER NOT NULL,
    opponent_team_id                INTEGER NOT NULL,
    was_home                        BOOLEAN NOT NULL,
    minutes                         INTEGER,
    starts                          INTEGER,
    goals_scored                    INTEGER,
    assists                         INTEGER,
    clean_sheets                    INTEGER,
    goals_conceded                  INTEGER,
    saves                           INTEGER,
    penalties_saved                 INTEGER,
    penalties_missed                INTEGER,
    own_goals                       INTEGER,
    yellow_cards                    INTEGER,
    red_cards                       INTEGER,
    bonus                           INTEGER,
    bps                             INTEGER,
    expected_goals                  DOUBLE,
    expected_assists                DOUBLE,
    expected_goals_conceded         DOUBLE,
    -- Opta indices. `threat` is the closest available proxy for shot volume, which the
    -- literature says stabilises faster than xG -- and measured here it does: season-to-season
    -- persistence 0.557 vs 0.319 (DEF), 0.828 vs 0.740 (MID), 0.625 vs 0.571 (FWD).
    -- They are also present for 2021-22, which has no xG at all.
    threat                          DOUBLE,
    creativity                      DOUBLE,
    influence                       DOUBLE,
    defensive_contribution          INTEGER,
    tackles                         INTEGER,
    recoveries                      INTEGER,
    clearances_blocks_interceptions INTEGER,
    value                           INTEGER,
    selected                        INTEGER,
    transfers_in                    INTEGER,
    transfers_out                   INTEGER,
    known_at                        TIMESTAMPTZ NOT NULL,
    capture_id                      VARCHAR NOT NULL,
    PRIMARY KEY (season, code, fixture, capture_id)
);

CREATE TABLE IF NOT EXISTS mart_team_fixture_live (
    season           VARCHAR NOT NULL,
    gw               INTEGER,
    fixture          INTEGER NOT NULL,
    pulse_id         INTEGER,
    kickoff_time     TIMESTAMPTZ,
    team_id          INTEGER NOT NULL,
    opponent_team_id INTEGER NOT NULL,
    was_home         BOOLEAN NOT NULL,
    fdr               INTEGER,
    rest_days         INTEGER,
    known_at          TIMESTAMPTZ NOT NULL,
    capture_id        VARCHAR NOT NULL,
    PRIMARY KEY (season, team_id, fixture, capture_id)
);

-- Exactly 3,800 rows after a correct build (760 per season x 5).
CREATE TABLE IF NOT EXISTS mart_fact_team_match (
    season           VARCHAR NOT NULL,
    gw               INTEGER NOT NULL,
    fixture          INTEGER NOT NULL,
    pulse_id         INTEGER,
    kickoff_time     TIMESTAMPTZ NOT NULL,
    team_id          INTEGER NOT NULL,
    opponent_team_id INTEGER NOT NULL,
    was_home         BOOLEAN NOT NULL,
    goals_for        INTEGER,
    goals_against    INTEGER,
    -- Null-guarded aggregates. An all-NULL group yields NULL, not 0.0: SQL SUM()
    -- already does this, but the Polars equivalent does not, and getting it wrong
    -- silently re-introduces gotcha 5 (2021-22 has no xG at all).
    team_xg          DOUBLE,  -- SUM(player expected_goals)
    team_xgc         DOUBLE,  -- MAX(player expected_goals_conceded); validated 1.395 vs 1.375
    team_bps         INTEGER,
    rest_days        INTEGER,
    fdr              INTEGER, -- this team's FPL difficulty; Phase 1 naive-FDR baseline
    PRIMARY KEY (season, team_id, fixture)
);

-- TARGETS. Read only by the validation harness and the dashboard -- never by the
-- feature builder.
--
-- `points_under_rules_<ruleset>` columns are added idempotently by
-- storage.db.ensure_ruleset_columns() from the rulesets present in config/, because
-- the column set is a function of configuration (R2).
--
-- Why the recomputed column is the real point: recorded total_points is denominated in
-- whichever season's rules applied at the time, so it is not comparable across seasons
-- and cannot be a model target. Models predict, and backtests score against,
-- points_under_rules_2026_27. `total_points_as_recorded` is kept alongside purely to
-- benchmark against FPL's own ep_next, which was produced under contemporaneous rules.
CREATE TABLE IF NOT EXISTS mart_target_player_fixture (
    season                   VARCHAR NOT NULL,
    gw                       INTEGER NOT NULL,
    fixture                  INTEGER NOT NULL,
    kickoff_time             TIMESTAMPTZ NOT NULL,
    code                     INTEGER NOT NULL,
    position                 VARCHAR NOT NULL,
    total_points_as_recorded INTEGER,
    PRIMARY KEY (season, code, fixture)
);

-- DESCRIPTIVE OBSERVED player form for the BI semantic contract.  This stays outside the
-- feature layer: it reads realised component and target marts and must never become a model input.
--
-- Grain is one player / observed gameweek / reporting window.  A player-fixture row is the
-- "rostered" population; it is broader than appeared players, so the availability denominators
-- below deliberately include zero-minute rows.  Productivity fields are built separately from
-- appeared rows only in transform.facts.build_player_form().
CREATE TABLE IF NOT EXISTS mart_fact_player_form (
    season                       VARCHAR NOT NULL,
    gw                           INTEGER NOT NULL,
    code                         INTEGER NOT NULL,
    "window"                     VARCHAR NOT NULL,
    rostered_fixtures            INTEGER NOT NULL,
    appearances                  INTEGER NOT NULL,
    -- `starts` is unmeasured for every 2021-22 player-fixture row.  It must remain NULL for a
    -- window with incomplete starts coverage rather than being silently reported as zero.
    starts                       INTEGER,
    did_not_play                 INTEGER NOT NULL,
    minutes                      INTEGER NOT NULL,
    goals_scored                 INTEGER,
    assists                      INTEGER,
    bonus                        INTEGER,
    bps                          INTEGER,
    defensive_contribution       INTEGER,
    expected_goals               DOUBLE,
    expected_assists             DOUBLE,
    expected_goals_per_90        DOUBLE,
    expected_assists_per_90      DOUBLE,
    points_under_rules_2026_27   INTEGER,
    -- Observed defensive form is productivity, so these aggregates are NULL when the player
    -- made no appearance in the window.  xGC additionally remains NULL where the source did
    -- not measure it; it is never zero-filled.
    clean_sheets                 INTEGER,
    goals_conceded               INTEGER,
    saves                        INTEGER,
    expected_goals_conceded      DOUBLE,
    PRIMARY KEY (season, gw, code, "window"),
    CHECK ("window" IN ('last_3', 'last_5', 'last_10', 'season_to_date'))
);

-- DESCRIPTIVE OBSERVED team form for the BI semantic contract, the club-level counterpart of
-- mart_fact_player_form.  Same anchoring: observed gameweeks, window ends at the anchor gameweek
-- inclusive, the anchor gameweek's latest kickoff is the point-in-time cutoff, both legs of a
-- double gameweek count, and a blank gameweek never fabricates a match.
--
-- team_code, never team_id, is the key: club ids are reassigned every season.
CREATE TABLE IF NOT EXISTS mart_fact_team_form (
    season                  VARCHAR NOT NULL,
    gw                      INTEGER NOT NULL,
    team_code               INTEGER NOT NULL,
    "window"                VARCHAR NOT NULL,
    matches_played          INTEGER NOT NULL,
    -- Goal aggregates are NULL when any match in the window has an unmeasured score, rather
    -- than silently undercounting. xG/xGC are NULL when unmeasured (all of 2021-22), never 0.0.
    goals_for               INTEGER,
    goals_against           INTEGER,
    clean_sheets            INTEGER,
    wins                    INTEGER,
    draws                   INTEGER,
    losses                  INTEGER,
    team_xg                 DOUBLE,
    team_xgc                DOUBLE,
    goals_for_per_match     DOUBLE,
    goals_against_per_match DOUBLE,
    team_xg_per_match       DOUBLE,
    team_xgc_per_match      DOUBLE,
    PRIMARY KEY (season, gw, team_code, "window"),
    CHECK ("window" IN ('last_3', 'last_5', 'last_10', 'season_to_date'))
);

-- Which components each ruleset needs but the season did not measure. Without this,
-- points_under_rules_2026_27 silently understates defenders before 2025-26, when
-- defensive_contribution was not recorded at all.
CREATE TABLE IF NOT EXISTS mart_target_completeness (
    season             VARCHAR NOT NULL,
    ruleset_id         VARCHAR NOT NULL,
    missing_components VARCHAR NOT NULL,  -- comma-separated; '' means complete
    is_complete        BOOLEAN NOT NULL,
    row_count          BIGINT NOT NULL,
    PRIMARY KEY (season, ruleset_id)
);

-- ====================================================================================
-- V2 football data layer (see docs/v2-architecture.md)
-- ====================================================================================
--
-- Metric COLUMNS on the three metric-bearing tables below are NOT declared here. They are a
-- function of `config/pl_sdp_metrics.yaml` and are added idempotently by
-- storage.db.ensure_sdp_metric_columns(), exactly as the ruleset target columns are added
-- from the scoring configs. Declaring them statically would mean a metric-dictionary change
-- needed a schema migration, which is precisely the coupling an undocumented upstream makes
-- unaffordable.

-- RAW: exactly what the provider sent, append-only.
--
-- `payload_id` is content-addressed over (provider, endpoint, params, body hash), so:
--   * re-fetching unchanged data is an idempotent no-op -- the same row is re-derived;
--   * a provider RESTATEMENT lands as a NEW row rather than overwriting the original, which
--     is what makes `known_at` meaningful downstream. A statistic corrected three days after
--     a match must not retroactively change what was knowable on match night.
CREATE TABLE IF NOT EXISTS raw_pl_sdp_payload (
    payload_id   VARCHAR PRIMARY KEY,
    provider     VARCHAR NOT NULL,
    endpoint     VARCHAR NOT NULL,
    request_path VARCHAR NOT NULL,
    params_json  VARCHAR NOT NULL,
    season       VARCHAR,
    sdp_match_id BIGINT,
    fetched_at   TIMESTAMPTZ NOT NULL,
    status_code  INTEGER NOT NULL,
    payload      JSON NOT NULL,
    sha256       VARCHAR NOT NULL,
    byte_count   BIGINT NOT NULL
);

-- STAGING: typed match identity, versioned by the capture that produced it.
CREATE TABLE IF NOT EXISTS stg_pl_sdp_match (
    sdp_match_id     BIGINT NOT NULL,
    payload_id       VARCHAR NOT NULL,
    known_at         TIMESTAMPTZ NOT NULL,
    season           VARCHAR NOT NULL,
    sdp_season_id    INTEGER,
    matchweek        INTEGER,
    kickoff_time     TIMESTAMPTZ,
    home_team_name   VARCHAR,
    away_team_name   VARCHAR,
    home_sdp_team_id INTEGER,
    away_sdp_team_id INTEGER,
    home_score       INTEGER,
    away_score       INTEGER,
    status           VARCHAR,
    PRIMARY KEY (sdp_match_id, payload_id)
);

-- STAGING: one team side per match. Typed metric columns are generated; `stats_json` keeps
-- the provider's mapping verbatim beside them so nothing depends on the dictionary being
-- complete.
CREATE TABLE IF NOT EXISTS stg_pl_sdp_team_match_stats (
    sdp_match_id  BIGINT NOT NULL,
    side          VARCHAR NOT NULL,
    payload_id    VARCHAR NOT NULL,
    known_at      TIMESTAMPTZ NOT NULL,
    sdp_team_id   INTEGER,
    team_name     VARCHAR,
    stats_json    JSON NOT NULL,
    metric_count  INTEGER NOT NULL,
    mapped_count  INTEGER NOT NULL,
    PRIMARY KEY (sdp_match_id, side, payload_id)
);

-- STAGING: the tall metric store. Every provider field of every payload lands here whether
-- or not the dictionary claims it -- `local_field` is NULL for an unmapped field, and
-- `jobs.audit_pl_sdp` reports those so the dictionary can be extended by configuration.
-- This is what makes a wrong guess in the dictionary lossless rather than destructive.
CREATE TABLE IF NOT EXISTS stg_pl_sdp_team_match_metric (
    sdp_match_id   BIGINT NOT NULL,
    side           VARCHAR NOT NULL,
    payload_id     VARCHAR NOT NULL,
    provider_field VARCHAR NOT NULL,
    local_field    VARCHAR,
    value_numeric  DOUBLE,
    value_text     VARCHAR,
    PRIMARY KEY (sdp_match_id, side, payload_id, provider_field)
);

-- STAGING: the measured identity bridge between FPL fixtures and SDP matches.
--
-- Whether `pulse_id == sdp_match_id` is a QUESTION, not an assumption; this table records the
-- answer per fixture together with how it was reached and what corroborated it. The UNIQUE
-- constraint on sdp_match_id is load-bearing: one provider match must never be attributed to
-- two FPL fixtures, which is exactly what a silent fuzzy match would produce.
CREATE TABLE IF NOT EXISTS stg_pl_sdp_fixture_crosswalk (
    season                VARCHAR NOT NULL,
    fixture               INTEGER NOT NULL,
    sdp_match_id          BIGINT NOT NULL UNIQUE,
    match_method          VARCHAR NOT NULL,
    pulse_id              INTEGER,
    corroborated_kickoff  BOOLEAN,
    corroborated_teams    BOOLEAN,
    corroborated_score    BOOLEAN,
    resolved_at           TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (season, fixture)
);

-- MART: the V2 football fact. One club x one fixture x one provider.
--
-- `provider` is the point of the table. `fpl_archive` rows are derived from data already in
-- this repository and exist for every season; `pl_sdp` rows require a network capture. Both
-- occupy the same grain so they can be compared rather than merged, and a metric a provider
-- does not carry stays NULL rather than being filled from the other.
CREATE TABLE IF NOT EXISTS mart_fact_team_match_stats_v2 (
    season             VARCHAR NOT NULL,
    gw                 INTEGER,
    fixture            INTEGER NOT NULL,
    pulse_id           INTEGER,
    sdp_match_id       BIGINT,
    kickoff_time       TIMESTAMPTZ NOT NULL,
    team_id            INTEGER NOT NULL,
    team_code          INTEGER,
    opponent_team_id   INTEGER NOT NULL,
    opponent_team_code INTEGER,
    was_home           BOOLEAN NOT NULL,
    provider           VARCHAR NOT NULL,
    known_at           TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (season, fixture, team_id, provider)
);

-- MART: descriptive rolling team state, keyed on the cross-season club identity.
--
-- Raw rolling means are generated per metric with a `_per_match` suffix. The derived indices
-- declared below are RATIOS of those, and are named so the two can never be confused. They
-- are descriptive interpretations of play style, not objective truth and not model outputs;
-- `docs/v2-team-engine-design.md` records that an index only earns its way into a model by
-- improving a proper score.
--
-- Anchoring mirrors mart_fact_team_form exactly: observed gameweeks only, window ends at the
-- anchor gameweek inclusive, cutoff is the anchor gameweek's latest kickoff, both legs of a
-- double gameweek counted, no fabricated blank-gameweek row.
CREATE TABLE IF NOT EXISTS mart_fact_team_tactical_form_v2 (
    season                VARCHAR NOT NULL,
    gw                    INTEGER NOT NULL,
    team_code             INTEGER NOT NULL,
    provider              VARCHAR NOT NULL,
    -- Quoted because `window` is a DuckDB reserved word; kept as the name anyway so this
    -- table's window vocabulary matches mart_fact_player_form and mart_fact_team_form.
    "window"              VARCHAR NOT NULL,
    as_at_kickoff         TIMESTAMPTZ NOT NULL,
    known_at              TIMESTAMPTZ NOT NULL,
    matches               INTEGER NOT NULL,
    -- derived ratio indices; NULL whenever an input is unmeasured or a denominator is zero
    shot_accuracy         DOUBLE,
    shot_quality          DOUBLE,
    finishing_quality     DOUBLE,
    pass_accuracy         DOUBLE,
    forward_pass_ratio    DOUBLE,
    long_pass_ratio       DOUBLE,
    cross_accuracy        DOUBLE,
    tackle_success_rate   DOUBLE,
    duel_win_rate         DOUBLE,
    aerial_win_rate       DOUBLE,
    high_press_share      DOUBLE,
    low_block_share       DOUBLE,
    defensive_volume      DOUBLE,
    territorial_dominance DOUBLE,
    PRIMARY KEY (season, gw, team_code, provider, "window"),
    CHECK ("window" IN ('last_3', 'last_5', 'last_10', 'season_to_date'))
);

-- ====================================================================================
-- Additive migrations for databases cloned by the failure-atomic archive rebuild
-- ====================================================================================
-- `CREATE TABLE IF NOT EXISTS` does not evolve a table that already exists. Full rebuilds
-- intentionally clone the current database so irreplaceable live captures survive, which
-- means additive schema changes must also upgrade that clone before any layer is rebuilt.
-- Existing rows receive NULL: these fields were unmeasured or not materialized in the old schema
-- and must never be backfilled as zero. Rebuilding their owning layer derives measured values.
ALTER TABLE mart_fact_team_tactical_form_v2
    ADD COLUMN IF NOT EXISTS known_at TIMESTAMPTZ;
ALTER TABLE stg_player_fixture
    ADD COLUMN IF NOT EXISTS threat DOUBLE;
ALTER TABLE stg_player_fixture
    ADD COLUMN IF NOT EXISTS creativity DOUBLE;
ALTER TABLE stg_player_fixture
    ADD COLUMN IF NOT EXISTS influence DOUBLE;
ALTER TABLE stg_live_player_fixture_version
    ADD COLUMN IF NOT EXISTS threat DOUBLE;
ALTER TABLE stg_live_player_fixture_version
    ADD COLUMN IF NOT EXISTS creativity DOUBLE;
ALTER TABLE stg_live_player_fixture_version
    ADD COLUMN IF NOT EXISTS influence DOUBLE;
ALTER TABLE stg_live_fixture_version
    ADD COLUMN IF NOT EXISTS team_h_score INTEGER;
ALTER TABLE stg_live_fixture_version
    ADD COLUMN IF NOT EXISTS team_a_score INTEGER;
ALTER TABLE stg_live_fixture_version
    ADD COLUMN IF NOT EXISTS finished_provisional BOOLEAN;
ALTER TABLE mart_fact_player_fixture
    ADD COLUMN IF NOT EXISTS threat DOUBLE;
ALTER TABLE mart_fact_player_fixture
    ADD COLUMN IF NOT EXISTS creativity DOUBLE;
ALTER TABLE mart_fact_player_fixture
    ADD COLUMN IF NOT EXISTS influence DOUBLE;
ALTER TABLE mart_fact_player_fixture_live
    ADD COLUMN IF NOT EXISTS threat DOUBLE;
ALTER TABLE mart_fact_player_fixture_live
    ADD COLUMN IF NOT EXISTS creativity DOUBLE;
ALTER TABLE mart_fact_player_fixture_live
    ADD COLUMN IF NOT EXISTS influence DOUBLE;
ALTER TABLE mart_dim_team
    ADD COLUMN IF NOT EXISTS team_code INTEGER;
ALTER TABLE mart_fact_player_form
    ADD COLUMN IF NOT EXISTS clean_sheets INTEGER;
ALTER TABLE mart_fact_player_form
    ADD COLUMN IF NOT EXISTS goals_conceded INTEGER;
ALTER TABLE mart_fact_player_form
    ADD COLUMN IF NOT EXISTS saves INTEGER;
ALTER TABLE mart_fact_player_form
    ADD COLUMN IF NOT EXISTS expected_goals_conceded DOUBLE;
