"""Cross-season identity: stable club keys and within-season transfer stints.

Two identifiers in this data look stable and are not. `element` is reassigned every season
(covered in test_crosswalk.py) and so is `team_id`. This module covers the team side and the
consequence nobody expects: a player can turn out for two or three clubs inside one season,
so "which team is this player on" is a question with a *time* in it.
"""

from __future__ import annotations

import duckdb
import pytest

pytestmark = pytest.mark.archive

# Measured across the five-season archive.
TOTAL_STINTS = 4127
TOTAL_PLAYER_SEASONS = 4005
TRANSFERS_WITHIN_SEASON = TOTAL_STINTS - TOTAL_PLAYER_SEASONS  # 122


# --------------------------------------------------------------------------------------
# Club identity
# --------------------------------------------------------------------------------------


def test_team_id_is_not_stable_across_seasons(db: duckdb.DuckDBPyConnection) -> None:
    """A bare `team_id` means nothing outside its season.

    The dangerous case is not simply that ids move -- it is that they *return*. id 10 is
    Leeds, Leicester, Fulham, Ipswich, then Fulham again. A cross-season join on team_id
    therefore appears to work for Fulham and silently yields a two-season history with
    Ipswich sitting in the middle of it.
    """
    worst = db.execute(
        """
        SELECT team_id, count(DISTINCT team_name) AS clubs
        FROM mart_dim_team GROUP BY team_id
        ORDER BY clubs DESC, team_id LIMIT 1
        """
    ).fetchone()
    assert worst is not None
    assert worst[1] >= 3, "expected at least one team_id reused by three or more clubs"

    repeats = db.execute(
        """
        SELECT count(*) FROM (
            SELECT team_id, team_name FROM mart_dim_team
            GROUP BY team_id, team_name HAVING count(*) > 1
        )
        """
    ).fetchone()
    assert repeats is not None and repeats[0] > 0, (
        "expected at least one club to hold the same team_id in two non-consecutive seasons "
        "-- that is the case a naive cross-season join gets wrong without erroring"
    )


def test_team_code_is_the_stable_club_key(db: duckdb.DuckDBPyConnection) -> None:
    """`team_code` is 1:1 with the club across every season.

    This is the club-level analogue of a player's `code`, and the only key permitted for
    following a club between seasons -- Dixon-Coles time decay crosses the season boundary,
    and promoted-team priors pool across seasons.
    """
    row = db.execute(
        """
        SELECT count(*), count(team_code),
               count(DISTINCT team_code), count(DISTINCT team_name)
        FROM mart_dim_team
        """
    ).fetchone()
    assert row is not None
    total, present, codes, names = row
    assert total == 100  # 20 clubs x 5 seasons
    assert present == total, "team_code must be populated for every season-team"
    assert codes == names, f"{codes} team_codes for {names} club names -- not 1:1"


def test_team_code_survives_a_team_id_change(db: duckdb.DuckDBPyConnection) -> None:
    """Fulham holds team_id 9, 10, 9, 10 across four seasons under one team_code."""
    rows = db.execute(
        """
        SELECT season, team_id, team_code FROM mart_dim_team
        WHERE team_name = 'Fulham' ORDER BY season
        """
    ).fetchall()
    assert len(rows) >= 3
    assert len({row[2] for row in rows}) == 1, "Fulham should have exactly one team_code"
    assert len({row[1] for row in rows}) > 1, "Fulham's team_id should change between seasons"


# --------------------------------------------------------------------------------------
# Within-season transfers
# --------------------------------------------------------------------------------------


def test_stints_capture_within_season_transfers(db: duckdb.DuckDBPyConnection) -> None:
    row = db.execute(
        """
        SELECT count(*), count(DISTINCT (season, code)) FROM mart_dim_player_stint
        """
    ).fetchone()
    assert row is not None
    stints, player_seasons = row
    assert stints == TOTAL_STINTS
    assert player_seasons == TOTAL_PLAYER_SEASONS
    assert stints - player_seasons == TRANSFERS_WITHIN_SEASON


def test_eze_is_split_across_two_clubs(db: duckdb.DuckDBPyConnection) -> None:
    """The case that prompted this table.

    Eze played two matches for Crystal Palace and thirty-six for Arsenal in 2025-26. Reading
    his club from `mart_dim_player` returns Arsenal for all thirty-eight, which attributes
    Arsenal's attacking scale and Arsenal's defensive-contribution environment to two Palace
    matches.
    """
    rows = db.execute(
        """
        SELECT s.stint_index, t.short_name, s.first_gw, s.last_gw, s.appearances
        FROM mart_dim_player_stint AS s
        JOIN mart_dim_team AS t ON t.season = s.season AND t.team_id = s.team_id
        JOIN mart_dim_player AS d ON d.season = s.season AND d.code = s.code
        WHERE s.season = '2025-26' AND d.web_name = 'Eze'
        ORDER BY s.stint_index
        """
    ).fetchall()
    assert [(r[1], r[2], r[3], r[4]) for r in rows] == [
        ("CRY", 1, 2, 2),
        ("ARS", 3, 38, 36),
    ]


def test_a_player_can_have_three_clubs_in_one_season(db: duckdb.DuckDBPyConnection) -> None:
    """Two stints is not the worst case, so nothing may assume a binary before/after."""
    rows = db.execute(
        """
        SELECT d.web_name, count(*) AS stints
        FROM mart_dim_player_stint AS s
        JOIN mart_dim_player AS d ON d.season = s.season AND d.code = s.code
        GROUP BY s.season, s.code, d.web_name HAVING count(*) >= 3
        ORDER BY stints DESC, d.web_name
        """
    ).fetchall()
    assert rows, "expected at least one player with three clubs in a single season"
    assert max(row[1] for row in rows) >= 3


def test_stint_indices_are_contiguous_and_chronological(
    db: duckdb.DuckDBPyConnection,
) -> None:
    bad = db.execute(
        """
        SELECT count(*) FROM (
            SELECT season, code,
                   count(*) AS n,
                   max(stint_index) AS highest,
                   min(stint_index) AS lowest
            FROM mart_dim_player_stint GROUP BY season, code
            HAVING max(stint_index) <> count(*) OR min(stint_index) <> 1
        )
        """
    ).fetchone()
    assert bad is not None and bad[0] == 0

    # A later stint index must start later in time.
    out_of_order = db.execute(
        """
        SELECT count(*) FROM mart_dim_player_stint AS a
        JOIN mart_dim_player_stint AS b
          ON b.season = a.season AND b.code = a.code AND b.stint_index = a.stint_index + 1
        WHERE b.first_kickoff < a.first_kickoff
        """
    ).fetchone()
    assert out_of_order is not None and out_of_order[0] == 0


def test_every_fact_row_belongs_to_a_stint(db: duckdb.DuckDBPyConnection) -> None:
    """The stint table must cover the facts exactly -- no orphans, no invented spells."""
    orphans = db.execute(
        """
        SELECT count(*) FROM mart_fact_player_fixture AS f
        LEFT JOIN mart_dim_player_stint AS s
          ON s.season = f.season AND s.code = f.code AND s.team_id = f.team_id
        WHERE s.code IS NULL
        """
    ).fetchone()
    assert orphans is not None and orphans[0] == 0

    totals = db.execute(
        """
        SELECT
          (SELECT sum(appearances) FROM mart_dim_player_stint),
          (SELECT count(*) FROM mart_fact_player_fixture)
        """
    ).fetchone()
    assert totals is not None
    assert totals[0] == totals[1], "stint appearances must sum to the fact row count"


def test_stint_team_is_valid_for_its_season(db: duckdb.DuckDBPyConnection) -> None:
    unresolved = db.execute(
        """
        SELECT count(*) FROM mart_dim_player_stint AS s
        LEFT JOIN mart_dim_team AS t ON t.season = s.season AND t.team_id = s.team_id
        WHERE t.team_id IS NULL
        """
    ).fetchone()
    assert unresolved is not None and unresolved[0] == 0


def test_dim_player_team_disagrees_with_reality_for_movers(
    db: duckdb.DuckDBPyConnection,
) -> None:
    """Pins *why* the stint table exists, so nobody deletes it as redundant.

    `mart_dim_player.team_id` records the club a player finished the season at. For players
    who moved it is therefore right for the final spell and wrong for every earlier one.
    """
    row = db.execute(
        """
        WITH movers AS (
            SELECT season, code FROM mart_dim_player_stint
            GROUP BY season, code HAVING count(*) > 1
        )
        SELECT count(*),
               sum(CASE WHEN d.team_id = s.team_id THEN 1 ELSE 0 END)
        FROM movers AS m
        JOIN mart_dim_player_stint AS s ON s.season = m.season AND s.code = m.code
        JOIN mart_dim_player AS d ON d.season = m.season AND d.code = m.code
        """
    ).fetchone()
    assert row is not None
    stints, agreeing = row
    assert stints > agreeing, (
        "mart_dim_player.team_id appears to match every stint, which would mean transfers "
        "are no longer represented -- check the dimension build before trusting this"
    )


# --------------------------------------------------------------------------------------
# The Opta indices promoted for Stage C
# --------------------------------------------------------------------------------------


def test_threat_and_creativity_are_present_in_every_season(
    db: duckdb.DuckDBPyConnection,
) -> None:
    """Unlike xG, these exist for 2021-22, which adds a season of attacking signal.

    `threat` is the closest available proxy for shot volume -- there is no shot count in any
    source available to this project -- and it out-persists xG at every outfield position.
    """
    rows = db.execute(
        """
        SELECT season, count(*), count(threat), count(creativity)
        FROM mart_fact_player_fixture GROUP BY season ORDER BY season
        """
    ).fetchall()
    assert len(rows) == 5
    for season, total, threat, creativity in rows:
        assert threat == total, f"{season}: threat missing on {total - threat} row(s)"
        assert creativity == total, f"{season}: creativity missing"


def test_threat_is_not_a_disguised_zero_column(db: duckdb.DuckDBPyConnection) -> None:
    """The 2022-23 expected_* defect was a column of literal zeros. Check this is not one."""
    rows = db.execute(
        """
        SELECT season, sum(threat), sum(creativity)
        FROM mart_fact_player_fixture GROUP BY season ORDER BY season
        """
    ).fetchall()
    for season, threat_sum, creativity_sum in rows:
        assert threat_sum > 1000, f"{season}: threat sums to {threat_sum}, suspiciously low"
        assert creativity_sum > 1000, f"{season}: creativity sums to {creativity_sum}"


def test_opta_indices_are_components_not_points(db: duckdb.DuckDBPyConnection) -> None:
    """They join the component table, so the no-points rule still has to hold."""
    offending = db.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'mart_fact_player_fixture' AND lower(column_name) LIKE '%points%'
        """
    ).fetchall()
    assert offending == []
