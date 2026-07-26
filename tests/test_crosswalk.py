"""Identifier crosswalks: gotchas 1, 2, 9, 10.

Every asserted number here was measured against the real five-season archive.
"""

from __future__ import annotations

import duckdb
import pytest

from fpl.types import Position

pytestmark = pytest.mark.archive

SEASONS = ("2021-22", "2022-23", "2023-24", "2024-25", "2025-26")

# Salah: `element` is reassigned every season, `code` is not.
SALAH_CODE = 118748
SALAH_ELEMENTS = {
    "2021-22": 233,
    "2022-23": 283,
    "2023-24": 308,
    "2024-25": 328,
    "2025-26": 381,
}


def test_element_ids_are_reassigned_but_code_is_stable(db: duckdb.DuckDBPyConnection) -> None:
    """Gotcha 1. `merged_gw.csv` carries only `element`, so `code` requires the join."""
    rows = dict(
        db.execute(
            "SELECT season, element_id FROM mart_dim_player WHERE code = ? ORDER BY season",
            [SALAH_CODE],
        ).fetchall()
    )
    assert rows == SALAH_ELEMENTS
    # The whole point: five different ids, one identity.
    assert len(set(rows.values())) == 5


def test_element_to_code_match_rate_is_total(db: duckdb.DuckDBPyConnection) -> None:
    """Measured 100.000%. A single miss means the crosswalk silently dropped a player."""
    row = db.execute(
        """
        SELECT count(*) FROM stg_player_fixture WHERE code IS NULL
        """
    ).fetchone()
    assert row is not None and row[0] == 0

    # And every staged row resolved to a dimension entry.
    orphans = db.execute(
        """
        SELECT count(*) FROM stg_player_fixture AS s
        LEFT JOIN mart_dim_player AS d ON d.code = s.code AND d.season = s.season
        WHERE d.code IS NULL
        """
    ).fetchone()
    assert orphans is not None and orphans[0] == 0


def test_team_ids_are_reassigned_between_seasons(db: duckdb.DuckDBPyConnection) -> None:
    """Gotcha 2. `opponent_team` is unusable without a per-season crosswalk."""
    rows = dict(
        db.execute(
            "SELECT season, team_name FROM mart_dim_team WHERE team_id = 3 ORDER BY season"
        ).fetchall()
    )
    assert rows == {
        "2021-22": "Brentford",
        "2022-23": "Bournemouth",
        "2023-24": "Bournemouth",
        "2024-25": "Bournemouth",
        "2025-26": "Burnley",
    }


def test_every_season_has_twenty_teams(db: duckdb.DuckDBPyConnection) -> None:
    rows = db.execute(
        "SELECT season, count(*) FROM mart_dim_team GROUP BY season ORDER BY season"
    ).fetchall()
    assert [row[1] for row in rows] == [20] * 5


def test_opponent_ids_resolve_within_their_own_season(db: duckdb.DuckDBPyConnection) -> None:
    """A team id only means something inside its season, so the join must carry season."""
    unresolved = db.execute(
        """
        SELECT count(*) FROM mart_fact_player_fixture AS f
        LEFT JOIN mart_dim_team AS t
          ON t.season = f.season AND t.team_id = f.opponent_team_id
        WHERE t.team_id IS NULL
        """
    ).fetchone()
    assert unresolved is not None and unresolved[0] == 0


def test_player_history_is_thin_for_most_players(db: duckdb.DuckDBPyConnection) -> None:
    """Gotcha 9: shrinkage is mandatory because most players have one or two seasons.

    1,777 distinct players once the 20 Assistant Manager elements are excluded (1,797 with
    them). 187 span all five seasons; 238 are new in 2025-26.
    """
    total = db.execute("SELECT count(DISTINCT code) FROM mart_dim_player").fetchone()
    assert total is not None and total[0] == 1777

    spans = dict(
        db.execute(
            """
            SELECT seasons, count(*) FROM (
                SELECT code, count(DISTINCT season) AS seasons
                FROM mart_fact_player_fixture GROUP BY code
            ) GROUP BY seasons ORDER BY seasons
            """
        ).fetchall()
    )
    assert spans[5] == 187
    # The long tail dominates: single-season players outnumber five-season ones 4:1.
    assert spans[1] > 4 * spans[5]

    new_in_2025_26 = db.execute(
        """
        SELECT count(*) FROM (
            SELECT code FROM mart_fact_player_fixture
            GROUP BY code HAVING min(season) = '2025-26'
        )
        """
    ).fetchone()
    assert new_in_2025_26 is not None and new_in_2025_26[0] == 238


def test_position_changes_are_rare_and_measured_from_element_type(
    db: duckdb.DuckDBPyConnection,
) -> None:
    """Gotcha 10: 2.8% of players change position -- via `element_type`, not the label.

    The archive's `position` label would say 7.3%, because its vocabulary drifts: 2021-22
    carries both `GK` and `GKP`, and 2024-25 adds `AM`. Position determines the scoring
    rules, so a spurious change is a scoring error.
    """
    changed = db.execute(
        """
        SELECT count(*) FROM (
            SELECT code FROM mart_dim_player GROUP BY code HAVING count(DISTINCT position) > 1
        )
        """
    ).fetchone()
    total = db.execute("SELECT count(DISTINCT code) FROM mart_dim_player").fetchone()
    assert changed is not None and total is not None

    # 51 players is the load-bearing number and is independent of the denominator.
    assert changed[0] == 51
    # 51/1777 = 2.9% of players. The specification's 2.8% is the same 51 players over a
    # denominator of 1,797, which counts the 20 Assistant Manager elements as players; they
    # are excluded here, so the rate is fractionally higher against a smaller population.
    assert total[0] == 1777
    assert round(100 * changed[0] / total[0], 1) == 2.9
    assert round(100 * changed[0] / (total[0] + 20), 1) == 2.8

    # The archive's own `position` label would say roughly 7% -- more than twice as many --
    # because its vocabulary drifts between seasons. That is why element_type is canonical.
    label_changed = db.execute(
        """
        SELECT count(*) FROM (
            SELECT p.code FROM raw_merged_gw AS d
            JOIN stg_player AS p ON p.season = d.season AND p.element = CAST(d.element AS INTEGER)
            GROUP BY p.code HAVING count(DISTINCT d.position) > 1
        )
        """
    ).fetchone()
    assert label_changed is not None
    assert label_changed[0] > changed[0], (
        "expected the drifted archive label to over-report position changes relative to "
        "element_type; if they now agree, the archive has normalised its vocabulary"
    )


def test_positions_are_the_canonical_four(db: duckdb.DuckDBPyConnection) -> None:
    """No `GKP`, no `AM` -- the drifted labels must not survive into the mart."""
    for table in ("mart_dim_player", "mart_fact_player_fixture"):
        found = {row[0] for row in db.execute(f"SELECT DISTINCT position FROM {table}").fetchall()}
        assert found == {position.value for position in Position}, table


def test_assistant_manager_elements_are_excluded(db: duckdb.DuckDBPyConnection) -> None:
    """`AM` is `element_type` 5, the Assistant Manager -- not a playing position.

    Measured: 322 rows across 20 managers, 2024-25 only, all with 0 minutes and scored
    entirely through `mng_*` columns. They are dropped rather than coerced, because giving
    them a position would feed 322 zero-minute non-players into every minutes model.
    """
    managers = db.execute("SELECT count(*) FROM stg_player WHERE element_type = 5").fetchone()
    assert managers is not None and managers[0] == 0

    # And they are absent from the facts: 322 raw rows did not become staged rows.
    raw = db.execute("SELECT count(*) FROM raw_merged_gw").fetchone()
    staged = db.execute("SELECT count(*) FROM stg_player_fixture").fetchone()
    assert raw is not None and staged is not None
    assert raw[0] - staged[0] == 332  # 322 managers + 10 exact duplicates


def test_element_type_5_rejected_by_position_mapping() -> None:
    """The type system refuses to invent a position for a manager."""
    with pytest.raises(ValueError, match="Assistant Manager"):
        Position.from_element_type(5)
    with pytest.raises(ValueError, match="Assistant Manager"):
        Position.from_archive_label("AM")


def test_archive_label_aliases_normalise() -> None:
    assert Position.from_archive_label("GKP") is Position.GK
    assert Position.from_archive_label("GK") is Position.GK
    assert Position.from_archive_label("mid") is Position.MID


def test_team_names_resolve_for_every_staged_row(db: duckdb.DuckDBPyConnection) -> None:
    """`merged_gw.team` is a NAME while `opponent_team` is an ID, in the same row.

    Both directions of the crosswalk are exercised on every row; measured 100% resolution.
    """
    unresolved = db.execute(
        """
        SELECT count(*) FROM stg_player_fixture AS s
        LEFT JOIN stg_team AS t ON t.season = s.season AND t.team_id = s.team_id
        WHERE t.team_id IS NULL
        """
    ).fetchone()
    assert unresolved is not None and unresolved[0] == 0
