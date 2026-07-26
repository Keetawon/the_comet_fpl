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
    team_name  VARCHAR NOT NULL,
    short_name VARCHAR NOT NULL,
    pulse_id   INTEGER,
    PRIMARY KEY (season, team_id)
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
