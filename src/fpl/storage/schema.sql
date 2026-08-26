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
-- Additive migrations for databases cloned by the failure-atomic archive rebuild
-- ====================================================================================
-- `CREATE TABLE IF NOT EXISTS` does not evolve a table that already exists. Full rebuilds
-- intentionally clone the current database so irreplaceable live captures survive, which
-- means additive schema changes must also upgrade that clone before any layer is rebuilt.
-- Existing rows receive NULL: these fields were unmeasured or not materialized in the old schema
-- and must never be backfilled as zero. Rebuilding their owning layer derives measured values.
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
