"""The provisional completed-match observation queries, shared by every publisher.

These two queries are the only place the provisional eligibility contract is written.
A second implementation of it -- in a cloud republish path, say -- would be a second
contract, so callers take the exact text from here instead of restating the rules.

`finalized_fixture` is the anti-join that makes the preview-to-final handoff
fixture-atomic. The BI export supplies it from the archive marts and the append-only
ledgers; a republish that has no ledger supplies the published finalized read models,
which is strictly more conservative because a fixture the public already carries as
finalized can only be removed from the preview, never added to it.
"""

from __future__ import annotations

from typing import Final

_LATEST_PLAYER_HISTORY_CAPTURE: Final[str] = """
    SELECT season, capture_id, captured_at AS observed_at
    FROM snapshot_capture
    WHERE mode = 'player-history'
    QUALIFY row_number() OVER (
        PARTITION BY season ORDER BY captured_at DESC, capture_id DESC
    ) = 1
"""


def finalized_fixture_union(sources: list[str]) -> str:
    """Join the finalized-evidence sources exactly as the export has always joined them."""
    if not sources:
        raise ValueError("provisional eligibility requires at least one finalized-evidence source")
    return "\n            UNION\n            ".join(sources)


def provisional_observation_queries(finalized_fixture_sql: str) -> tuple[str, str]:
    """Return the player and team provisional observation queries, in that order."""
    provisional_player_observation = f"""
        WITH selected_capture AS ({_LATEST_PLAYER_HISTORY_CAPTURE}),
        finalized_fixture AS (
            {finalized_fixture_sql}
        ),
        completed_fixture AS (
            SELECT fixture.*, selected_capture.observed_at
            FROM stg_live_fixture_version AS fixture
            INNER JOIN selected_capture
              ON selected_capture.season = fixture.season
             AND selected_capture.capture_id = fixture.capture_id
            WHERE (fixture.finished_provisional IS TRUE OR fixture.finished IS TRUE)
              AND fixture.gw IS NOT NULL
              AND fixture.kickoff_time IS NOT NULL
              AND fixture.team_h_score IS NOT NULL
              AND fixture.team_a_score IS NOT NULL
              AND NOT EXISTS (
                    SELECT 1
                    FROM finalized_fixture AS final
                    WHERE final.season = fixture.season
                      AND final.fixture = fixture.fixture
              )
        )
        SELECT history.season, history.fixture, history.code, history.gw,
               history.kickoff_time, history.position, history.team_id, team.team_code,
               history.opponent_team_id, history.was_home, history.minutes, history.starts,
               history.goals_scored, history.assists, history.clean_sheets,
               history.goals_conceded, history.saves, history.penalties_saved,
               history.penalties_missed, history.own_goals, history.yellow_cards,
               history.red_cards, history.bonus, history.bps, history.expected_goals,
               history.expected_assists, history.expected_goals_conceded,
               history.defensive_contribution, history.threat, history.creativity,
               history.influence, history.total_points AS total_points_as_recorded,
               fixture.observed_at
        FROM stg_live_player_fixture_version AS history
        INNER JOIN completed_fixture AS fixture
          ON fixture.season = history.season
         AND fixture.fixture = history.fixture
         AND fixture.capture_id = history.capture_id
        LEFT JOIN stg_live_team_version AS team
          ON team.season = history.season
         AND team.team_id = history.team_id
         AND team.capture_id = history.capture_id
    """
    provisional_team_observation = f"""
        WITH selected_capture AS ({_LATEST_PLAYER_HISTORY_CAPTURE}),
        finalized_fixture AS (
            {finalized_fixture_sql}
        ),
        completed_fixture AS (
            SELECT fixture.*, selected_capture.observed_at
            FROM stg_live_fixture_version AS fixture
            INNER JOIN selected_capture
              ON selected_capture.season = fixture.season
             AND selected_capture.capture_id = fixture.capture_id
            WHERE (fixture.finished_provisional IS TRUE OR fixture.finished IS TRUE)
              AND fixture.gw IS NOT NULL
              AND fixture.kickoff_time IS NOT NULL
              AND fixture.team_h_score IS NOT NULL
              AND fixture.team_a_score IS NOT NULL
              AND NOT EXISTS (
                    SELECT 1
                    FROM finalized_fixture AS final
                    WHERE final.season = fixture.season
                      AND final.fixture = fixture.fixture
              )
        ), player_components AS (
            SELECT history.season, history.fixture, history.capture_id, history.team_id,
                   CASE
                       WHEN count(*) FILTER (WHERE history.minutes >= 1) > 0
                        AND count(history.expected_goals) FILTER (WHERE history.minutes >= 1)
                            = count(*) FILTER (WHERE history.minutes >= 1)
                       THEN sum(history.expected_goals) FILTER (WHERE history.minutes >= 1)
                   END AS team_xg,
                   CASE
                       WHEN count(*) FILTER (WHERE history.minutes >= 1) > 0
                        AND count(history.expected_goals_conceded)
                                FILTER (WHERE history.minutes >= 1)
                            = count(*) FILTER (WHERE history.minutes >= 1)
                       THEN max(history.expected_goals_conceded)
                                FILTER (WHERE history.minutes >= 1)
                   END AS team_xgc,
                   CASE
                       WHEN count(*) FILTER (WHERE history.minutes >= 1) > 0
                        AND count(history.bps) FILTER (WHERE history.minutes >= 1)
                            = count(*) FILTER (WHERE history.minutes >= 1)
                       THEN sum(history.bps) FILTER (WHERE history.minutes >= 1)
                   END AS team_bps,
                   CASE
                       WHEN count(*) FILTER (
                                WHERE history.position <> 'GK' AND history.minutes >= 1
                            ) > 0
                        AND count(history.defensive_contribution) FILTER (
                                WHERE history.position <> 'GK' AND history.minutes >= 1
                            ) = count(*) FILTER (
                                WHERE history.position <> 'GK' AND history.minutes >= 1
                            )
                       THEN sum(history.defensive_contribution) FILTER (
                                WHERE history.position <> 'GK' AND history.minutes >= 1
                            )
                   END AS defensive_contribution
            FROM stg_live_player_fixture_version AS history
            INNER JOIN selected_capture
              ON selected_capture.season = history.season
             AND selected_capture.capture_id = history.capture_id
            GROUP BY history.season, history.fixture, history.capture_id, history.team_id
        ), sides AS (
            SELECT fixture.season, fixture.fixture, fixture.team_h AS team_id,
                   fixture.team_a AS opponent_team_id, fixture.gw, fixture.kickoff_time,
                   TRUE AS was_home, fixture.team_h_score AS goals_for,
                   fixture.team_a_score AS goals_against, fixture.capture_id,
                   fixture.observed_at
            FROM completed_fixture AS fixture
            UNION ALL
            SELECT fixture.season, fixture.fixture, fixture.team_a AS team_id,
                   fixture.team_h AS opponent_team_id, fixture.gw, fixture.kickoff_time,
                   FALSE AS was_home, fixture.team_a_score AS goals_for,
                   fixture.team_h_score AS goals_against, fixture.capture_id,
                   fixture.observed_at
            FROM completed_fixture AS fixture
        )
        SELECT sides.season, sides.fixture, sides.team_id, team.team_code,
               sides.opponent_team_id, sides.gw, sides.kickoff_time, sides.was_home,
               sides.goals_for, sides.goals_against, components.team_xg,
               components.team_xgc, components.team_bps, components.defensive_contribution,
               sides.observed_at
        FROM sides
        LEFT JOIN stg_live_team_version AS team
          ON team.season = sides.season
         AND team.team_id = sides.team_id
         AND team.capture_id = sides.capture_id
        LEFT JOIN player_components AS components
          ON components.season = sides.season
         AND components.fixture = sides.fixture
         AND components.capture_id = sides.capture_id
         AND components.team_id = sides.team_id
    """
    return provisional_player_observation, provisional_team_observation


# The latest captured version of each club and fixture. The BI export selects live-season
# identity the same way; these are shared so a capture-only database and the full export
# cannot drift apart on what "the current club" or "this fixture" means.
LIVE_TEAM_LATEST: Final[str] = """
    SELECT season, team_id, team_code, team_name, short_name, pulse_id
    FROM stg_live_team_version
    WHERE team_code IS NOT NULL
    QUALIFY row_number() OVER (
        PARTITION BY season, team_id ORDER BY known_at DESC, capture_id DESC
    ) = 1
"""
LIVE_FIXTURE_LATEST: Final[str] = """
    SELECT season, fixture, gw, kickoff_time, team_h, team_a, finished,
           team_h_difficulty, team_a_difficulty
    FROM stg_live_fixture_version
    QUALIFY row_number() OVER (
        PARTITION BY season, fixture ORDER BY known_at DESC, capture_id DESC
    ) = 1
"""


def capture_identity_queries() -> tuple[str, str]:
    """Club and fixture identity for a database holding captures and nothing else.

    These are the live halves of the export's `dim_team_season` and `dim_fixture`, column
    for column, so the same contract projection applies to both. The fixture `pulse_id` is
    NULL for the same reason it is NULL there: the live payload does not carry it, and a
    missing identifier stays missing. A provisional observation only ever comes from the
    season of its own capture, so there is no archive season to union in and no
    cross-season precedence to decide.
    """
    team_season = f"SELECT * FROM ({LIVE_TEAM_LATEST})"
    dim_fixture = f"""
        SELECT lf.season, lf.fixture, lf.gw, lf.kickoff_time,
               lf.team_h AS home_team_id, lf.team_a AS away_team_id,
               home.team_code AS home_team_code, away.team_code AS away_team_code,
               lf.team_h_difficulty AS home_official_fdr,
               lf.team_a_difficulty AS away_official_fdr,
               CAST(NULL AS INTEGER) AS pulse_id, lf.finished
        FROM ({LIVE_FIXTURE_LATEST}) AS lf
        LEFT JOIN ({LIVE_TEAM_LATEST}) AS home
          ON home.season = lf.season AND home.team_id = lf.team_h
        LEFT JOIN ({LIVE_TEAM_LATEST}) AS away
          ON away.season = lf.season AND away.team_id = lf.team_a
    """
    return team_season, dim_fixture
