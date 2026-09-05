"""The V2 football layer: provider separation, mirrors, NULL semantics, and point-in-time.

The provider column is the design point of `mart_fact_team_match_stats_v2`, so most of these
tests are about keeping two providers on one grain without letting either contaminate the
other -- which is what makes reconciliation possible and what stops a proxy silently standing
in for a direct measurement.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from fpl.config import load_sdp_metrics
from fpl.features.pit import OUTCOME_COLUMNS, SCHEDULE_COLUMNS, AsOf, FeatureSource, PointInTimeView
from fpl.storage.db import (
    FEATURE_READABLE_TABLES,
    FORBIDDEN_FEATURE_COLUMN_SUBSTRING,
    initialise,
    sdp_metric_columns,
    table_columns,
)
from fpl.transform import football_v2
from fpl.transform.pl_sdp import SdpIdentityError
from fpl.validate.v2_environment_harness import load_team_frame

KICKOFF = datetime(2025, 8, 16, 14, 0, tzinfo=UTC)


@pytest.fixture
def con(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    connection = initialise(tmp_path / "v2.duckdb")
    yield connection
    connection.close()


def _seed(connection: duckdb.DuckDBPyConnection, *, matches: int = 3) -> None:
    """A tiny two-club season: `matches` fixtures, alternating venue, hand-computable."""
    for team_id, team_code, name in ((1, 3, "Arsenal"), (4, 8, "Chelsea")):
        connection.execute(
            "INSERT INTO mart_dim_team (season, team_id, team_code, team_name, short_name) "
            "VALUES ('2025-26', ?, ?, ?, ?)",
            [team_id, team_code, name, name[:3].upper()],
        )
    for index in range(matches):
        fixture = 100 + index
        kickoff = KICKOFF + timedelta(days=7 * index)
        home, away = (1, 4) if index % 2 == 0 else (4, 1)
        for team_id, opponent, was_home, goals_for, goals_against in (
            (home, away, True, 2, 1),
            (away, home, False, 1, 2),
        ):
            connection.execute(
                """
                INSERT INTO mart_fact_team_match (
                    season, gw, fixture, pulse_id, kickoff_time, team_id, opponent_team_id,
                    was_home, goals_for, goals_against, team_xg, team_xgc, team_bps
                ) VALUES ('2025-26', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    index + 1,
                    fixture,
                    900000 + fixture,
                    kickoff,
                    team_id,
                    opponent,
                    was_home,
                    goals_for,
                    goals_against,
                    1.5 if was_home else 0.9,
                    0.9 if was_home else 1.5,
                    60,
                ],
            )
            # One goalkeeper per club per fixture: saves + goals conceded IS the on-target
            # shots he faced, which is what the archive-derived proxy measures.
            connection.execute(
                """
                INSERT INTO mart_fact_player_fixture (
                    season, gw, fixture, kickoff_time, code, position, team_id,
                    opponent_team_id, was_home, minutes, saves, goals_conceded,
                    tackles, recoveries, clearances_blocks_interceptions,
                    yellow_cards, red_cards
                ) VALUES ('2025-26', ?, ?, ?, ?, 'GK', ?, ?, ?, 90, ?, ?, 1, 2, 3, 0, 0)
                """,
                [
                    index + 1,
                    fixture,
                    kickoff,
                    1000 + team_id,
                    team_id,
                    opponent,
                    was_home,
                    4 if was_home else 6,
                    goals_against,
                ],
            )


# -- schema ------------------------------------------------------------------------------


def test_metric_columns_are_generated_from_the_dictionary(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """Adding a metric must be a config change, not a schema migration."""
    expected = set(sdp_metric_columns(include_mirrors=True))
    present = set(table_columns(con, "mart_fact_team_match_stats_v2"))
    assert expected <= present


def test_every_v2_metric_column_is_an_outcome() -> None:
    """A new post-match column must not silently default to 'safe to read from the future'.

    This is the test the explicit list in `features.pit` exists for: registering a metric in
    the dictionary without registering it as an outcome fails here rather than becoming a
    leak nobody notices.
    """
    dictionary = load_sdp_metrics()
    for metric in dictionary.all_fields():
        assert metric.local_field in OUTCOME_COLUMNS, metric.local_field
        assert f"{metric.local_field}_per_match" in OUTCOME_COLUMNS
    for mirror in dictionary.mirror_fields().values():
        assert mirror in OUTCOME_COLUMNS, mirror


def test_no_v2_metric_column_is_a_schedule_column() -> None:
    """`schedule()` may see the future, so nothing post-match may be in its projection."""
    assert not (set(sdp_metric_columns(include_mirrors=True)) & set(SCHEDULE_COLUMNS))


# -- the archive provider -----------------------------------------------------------------


def test_archive_provider_populates_both_sides_of_every_fixture(
    con: duckdb.DuckDBPyConnection,
) -> None:
    _seed(con)
    rows = football_v2.build_team_match_stats_archive(con)
    assert rows == 6
    per_fixture = con.execute(
        "SELECT fixture, count(*) FROM mart_fact_team_match_stats_v2 GROUP BY fixture"
    ).fetchall()
    assert all(count == 2 for _, count in per_fixture)


def test_shots_on_target_proxy_is_saves_plus_conceded(con: duckdb.DuckDBPyConnection) -> None:
    """The measurement this whole V2 saves upgrade rests on, checked by hand."""
    _seed(con, matches=1)
    football_v2.build_team_match_stats_archive(con)
    row = con.execute(
        """
        SELECT shots_on_target_allowed_proxy, saves
        FROM mart_fact_team_match_stats_v2 WHERE was_home ORDER BY fixture
        """
    ).fetchone()
    # Home keeper made 4 saves and conceded 1: he faced 5 on-target shots.
    assert row == (5, 4)


def test_opponent_mirrors_come_from_the_other_side(con: duckdb.DuckDBPyConnection) -> None:
    _seed(con, matches=1)
    football_v2.build_team_match_stats_archive(con)
    row = con.execute(
        """
        SELECT goals, goals_allowed, expected_goals, expected_goals_allowed
        FROM mart_fact_team_match_stats_v2 WHERE was_home
        """
    ).fetchone()
    assert row == (2, 1, 1.5, 0.9)


def test_unmeasured_metrics_stay_null_and_are_never_zero_filled(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """A metric the archive cannot supply is unmeasured, which is not the same as zero."""
    _seed(con, matches=1)
    football_v2.build_team_match_stats_archive(con)
    row = con.execute(
        """
        SELECT shots, shots_on_target, expected_goals_on_target, touches_in_opposition_box,
               possession
        FROM mart_fact_team_match_stats_v2 LIMIT 1
        """
    ).fetchone()
    assert row == (None, None, None, None, None)


def test_a_club_with_no_recorded_goalkeeper_gets_null_not_zero(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """No keeper row means the shots faced are unknown, not that none were faced."""
    _seed(con, matches=1)
    con.execute("DELETE FROM mart_fact_player_fixture WHERE was_home")
    football_v2.build_team_match_stats_archive(con)
    row = con.execute(
        "SELECT shots_on_target_allowed_proxy FROM mart_fact_team_match_stats_v2 WHERE was_home"
    ).fetchone()
    assert row == (None,)


def test_the_two_expected_goals_conceded_measurements_stay_separate(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """Same concept, different sources: forcing them to agree would destroy the comparison."""
    _seed(con, matches=1)
    football_v2.build_team_match_stats_archive(con)
    row = con.execute(
        """
        SELECT expected_goals_allowed, expected_goals_conceded_measured
        FROM mart_fact_team_match_stats_v2 WHERE was_home
        """
    ).fetchone()
    assert row == (0.9, 0.9)
    columns = table_columns(con, "mart_fact_team_match_stats_v2")
    assert "expected_goals_allowed" in columns and "expected_goals_conceded_measured" in columns


def test_rebuilding_is_idempotent(con: duckdb.DuckDBPyConnection) -> None:
    _seed(con)
    first = football_v2.build_team_match_stats_archive(con)
    second = football_v2.build_team_match_stats_archive(con)
    assert first == second == 6


def test_the_layer_degrades_rather_than_failing_on_a_legacy_database(
    tmp_path: Path,
) -> None:
    """V2 is optional: a rebuild must not fail because its sources are not yet in shape."""
    connection = duckdb.connect(str(tmp_path / "legacy.duckdb"))
    try:
        connection.execute("CREATE TABLE mart_dim_team (legacy_marker INTEGER)")
        counts = football_v2.build_all(connection)
        assert counts.skipped_reason is not None
        assert counts.team_match_stats_rows == 0
    finally:
        connection.close()


# -- the live SDP provider ---------------------------------------------------------------


def test_current_live_fixture_anchors_sdp_team_stats_and_tactical_form(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """The archive team mart stops at completed seasons; live fixtures must anchor SDP rows."""
    season = "2026-27"
    fixture = 201
    match_id = 2645195
    capture_id = "live-capture"
    known_at = datetime(2026, 8, 20, 6, tzinfo=UTC)
    kickoff = datetime(2026, 8, 21, 20, tzinfo=UTC)
    stats_known_at = datetime(2026, 8, 22, 1, tzinfo=UTC)

    con.executemany(
        """
        INSERT INTO stg_live_team_version (
            season, team_id, team_code, known_at, capture_id, team_name, short_name, pulse_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (season, 1, 3, known_at, capture_id, "Arsenal", "ARS", 1),
            (season, 4, 8, known_at, capture_id, "Chelsea", "CHE", 4),
        ],
    )
    con.executemany(
        """
        INSERT INTO mart_team_fixture_live (
            season, gw, fixture, pulse_id, kickoff_time, team_id, opponent_team_id,
            was_home, known_at, capture_id
        ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (season, fixture, match_id, kickoff, 1, 4, True, known_at, capture_id),
            (season, fixture, match_id, kickoff, 4, 1, False, known_at, capture_id),
        ],
    )
    con.execute(
        """
        INSERT INTO stg_pl_sdp_fixture_crosswalk (
            season, fixture, sdp_match_id, match_method, pulse_id,
            corroborated_kickoff, corroborated_teams, corroborated_score, resolved_at
        ) VALUES (?, ?, ?, 'pulse_id', ?, TRUE, TRUE, TRUE, ?)
        """,
        [season, fixture, match_id, match_id, stats_known_at],
    )
    con.executemany(
        """
        INSERT INTO stg_pl_sdp_team_match_stats (
            sdp_match_id, side, payload_id, known_at, sdp_team_id, team_name,
            stats_json, metric_count, mapped_count, expected_goals, shots, shots_on_target
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 3, 3, ?, ?, ?)
        """,
        [
            (
                match_id,
                "home",
                "stats-home",
                stats_known_at,
                3,
                "Arsenal",
                '{"expectedGoals": 1.8, "totalScoringAtt": 12, "ontargetScoringAtt": 6}',
                1.8,
                12,
                6,
            ),
            (
                match_id,
                "away",
                "stats-away",
                stats_known_at,
                8,
                "Chelsea",
                '{"expectedGoals": 0.7, "totalScoringAtt": 8, "ontargetScoringAtt": 2}',
                0.7,
                8,
                2,
            ),
        ],
    )

    assert con.execute("SELECT count(*) FROM mart_fact_team_match").fetchone() == (0,)
    assert football_v2.build_team_match_stats_sdp(con) == 2
    home = con.execute(
        """
        SELECT season, gw, fixture, team_id, team_code, opponent_team_id,
               opponent_team_code, expected_goals, expected_goals_allowed,
               shots, shots_on_target
        FROM mart_fact_team_match_stats_v2
        WHERE provider = 'pl_sdp' AND was_home
        """
    ).fetchone()
    assert home == (season, 1, fixture, 1, 3, 4, 8, 1.8, 0.7, 12, 6)

    assert football_v2.build_team_tactical_form(con) == 8
    form = con.execute(
        """
        SELECT matches, expected_goals_per_match, shot_accuracy
        FROM mart_fact_team_tactical_form_v2
        WHERE season = ? AND team_code = 3 AND provider = 'pl_sdp'
          AND gw = 1 AND "window" = 'season_to_date'
        """,
        [season],
    ).fetchone()
    assert form == pytest.approx((1, 1.8, 0.5))


@pytest.mark.parametrize(("home_stats_team_id", "away_stats_team_id"), [(8, 3), (None, 8)])
def test_sdp_mart_fails_closed_on_swapped_or_missing_stats_team_id(
    con: duckdb.DuckDBPyConnection,
    home_stats_team_id: int | None,
    away_stats_team_id: int,
) -> None:
    _seed(con, matches=1)
    match_id = 2645195
    con.execute(
        """
        INSERT INTO stg_pl_sdp_fixture_crosswalk (
            season, fixture, sdp_match_id, match_method, pulse_id,
            corroborated_kickoff, corroborated_teams, corroborated_score, resolved_at
        ) VALUES ('2025-26', 100, ?, 'identity_fallback', NULL, TRUE, TRUE, TRUE, ?)
        """,
        [match_id, KICKOFF],
    )
    con.executemany(
        """
        INSERT INTO stg_pl_sdp_team_match_stats (
            sdp_match_id, side, payload_id, known_at, sdp_team_id,
            stats_json, metric_count, mapped_count
        ) VALUES (?, ?, ?, ?, ?, '{}', 0, 0)
        """,
        [
            (match_id, "home", "stats-home", KICKOFF, home_stats_team_id),
            (match_id, "away", "stats-away", KICKOFF, away_stats_team_id),
        ],
    )

    with pytest.raises(SdpIdentityError, match="stats teamId"):
        football_v2.build_team_match_stats_sdp(con)

    assert con.execute(
        "SELECT count(*) FROM mart_fact_team_match_stats_v2 WHERE provider = 'pl_sdp'"
    ).fetchone() == (0,)


def test_sdp_mart_fails_closed_when_a_resolved_match_has_only_one_stats_side(
    con: duckdb.DuckDBPyConnection,
) -> None:
    _seed(con, matches=1)
    match_id = 2645195
    con.execute(
        """
        INSERT INTO stg_pl_sdp_fixture_crosswalk (
            season, fixture, sdp_match_id, match_method, pulse_id,
            corroborated_kickoff, corroborated_teams, corroborated_score, resolved_at
        ) VALUES ('2025-26', 100, ?, 'identity_fallback', NULL, TRUE, TRUE, TRUE, ?)
        """,
        [match_id, KICKOFF],
    )
    con.execute(
        """
        INSERT INTO stg_pl_sdp_team_match_stats (
            sdp_match_id, side, payload_id, known_at, sdp_team_id,
            stats_json, metric_count, mapped_count
        ) VALUES (?, 'home', 'stats-home', ?, 3, '{}', 0, 0)
        """,
        [match_id, KICKOFF],
    )

    with pytest.raises(SdpIdentityError, match="would emit 1 team rows across 1 sides"):
        football_v2.build_team_match_stats_sdp(con)

    assert con.execute(
        "SELECT count(*) FROM mart_fact_team_match_stats_v2 WHERE provider = 'pl_sdp'"
    ).fetchone() == (0,)


# -- tactical form -------------------------------------------------------------------------


def test_tactical_form_is_keyed_on_the_cross_season_club_identity(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """`team_id` is reassigned yearly; a rolling window built on it splices two clubs."""
    _seed(con)
    football_v2.build_team_match_stats_archive(con)
    football_v2.build_team_tactical_form(con)
    columns = table_columns(con, "mart_fact_team_tactical_form_v2")
    assert "team_code" in columns
    assert "team_id" not in columns


def test_tactical_form_rolling_mean_is_hand_computable(
    con: duckdb.DuckDBPyConnection,
) -> None:
    _seed(con, matches=3)
    football_v2.build_team_match_stats_archive(con)
    football_v2.build_team_tactical_form(con)
    # Arsenal (team_code 3) plays home, away, home -> goals 2, 1, 2 -> season mean 5/3.
    row = con.execute(
        """
        SELECT matches, goals_per_match FROM mart_fact_team_tactical_form_v2
        WHERE team_code = 3 AND "window" = 'season_to_date' AND gw = 3
        """
    ).fetchone()
    assert row is not None
    assert row[0] == 3
    assert row[1] == pytest.approx(5 / 3)


def test_tactical_form_window_lengths_are_respected(con: duckdb.DuckDBPyConnection) -> None:
    _seed(con, matches=5)
    football_v2.build_team_match_stats_archive(con)
    football_v2.build_team_tactical_form(con)
    row = con.execute(
        """
        SELECT matches FROM mart_fact_team_tactical_form_v2
        WHERE team_code = 3 AND "window" = 'last_3' AND gw = 5
        """
    ).fetchone()
    assert row == (3,)


def test_a_derived_index_is_null_when_its_inputs_are_unmeasured(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """The archive carries no SDP passing data, so pass accuracy is unknown, not zero."""
    _seed(con)
    football_v2.build_team_match_stats_archive(con)
    football_v2.build_team_tactical_form(con)
    row = con.execute(
        """
        SELECT pass_accuracy, shot_accuracy FROM mart_fact_team_tactical_form_v2 LIMIT 1
        """
    ).fetchone()
    assert row == (None, None)


def _seed_incomplete_tactical_inputs(con: duckdb.DuckDBPyConnection) -> None:
    con.executemany(
        """
        INSERT INTO mart_fact_team_match_stats_v2 (
            season, gw, fixture, sdp_match_id, kickoff_time,
            team_id, team_code, opponent_team_id, opponent_team_code, was_home,
            provider, known_at, shots, shots_on_target,
            tackles, interceptions, clearances, blocks, recoveries
        ) VALUES (
            '2025-26', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pl_sdp', ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        [
            (1, 100, 900100, KICKOFF, 1, 3, 4, 8, True, KICKOFF, 10, 5, 2, 3, 4, 5, 6),
            (1, 100, 900100, KICKOFF, 4, 8, 1, 3, False, KICKOFF, 8, 2, 2, 2, 2, 2, 2),
            (
                2,
                101,
                900101,
                KICKOFF + timedelta(days=7),
                1,
                3,
                4,
                8,
                False,
                KICKOFF + timedelta(days=7),
                20,
                None,
                100,
                None,
                100,
                100,
                100,
            ),
            (
                2,
                101,
                900101,
                KICKOFF + timedelta(days=7),
                4,
                8,
                1,
                3,
                True,
                KICKOFF + timedelta(days=7),
                7,
                3,
                3,
                3,
                3,
                3,
                3,
            ),
        ],
    )


def test_ratio_excludes_a_match_with_an_unmeasured_numerator(
    con: duckdb.DuckDBPyConnection,
) -> None:
    _seed_incomplete_tactical_inputs(con)
    football_v2.build_team_tactical_form(con)

    raw = con.execute(
        """
        SELECT shots, shots_on_target FROM mart_fact_team_match_stats_v2
        WHERE provider = 'pl_sdp' AND fixture = 101 AND team_code = 3
        """
    ).fetchone()
    ratio = con.execute(
        """
        SELECT shot_accuracy FROM mart_fact_team_tactical_form_v2
        WHERE provider = 'pl_sdp' AND team_code = 3 AND gw = 2
          AND "window" = 'season_to_date'
        """
    ).fetchone()

    assert raw == (20, None)
    assert ratio == pytest.approx((0.5,))


def test_composite_index_excludes_an_incomplete_match_from_its_exposure(
    con: duckdb.DuckDBPyConnection,
) -> None:
    _seed_incomplete_tactical_inputs(con)
    football_v2.build_team_tactical_form(con)

    raw = con.execute(
        """
        SELECT tackles, interceptions FROM mart_fact_team_match_stats_v2
        WHERE provider = 'pl_sdp' AND fixture = 101 AND team_code = 3
        """
    ).fetchone()
    index = con.execute(
        """
        SELECT defensive_volume FROM mart_fact_team_tactical_form_v2
        WHERE provider = 'pl_sdp' AND team_code = 3 AND gw = 2
          AND "window" = 'season_to_date'
        """
    ).fetchone()

    assert raw == (100, None)
    assert index == pytest.approx((20.0,))


# -- point-in-time -------------------------------------------------------------------------


def test_observed_football_excludes_rows_at_or_after_as_of(
    tmp_path: Path, con: duckdb.DuckDBPyConnection
) -> None:
    _seed(con, matches=3)
    football_v2.build_team_match_stats_archive(con)
    football_v2.build_team_tactical_form(con)
    path = tmp_path / "v2.duckdb"
    con.close()
    cutoff = KICKOFF + timedelta(days=7)
    with FeatureSource.open(path) as source:
        view = PointInTimeView(source, AsOf(cutoff))
        frame = view.observed_team_football(columns=["fixture", "kickoff_time", "goals"])
        assert frame.height == 2, "only the first fixture kicked off before the cutoff"
        assert frame["kickoff_time"].max() < cutoff


def test_tactical_form_is_filtered_on_its_anchor_kickoff(
    tmp_path: Path, con: duckdb.DuckDBPyConnection
) -> None:
    """The anchor kickoff is the instant the whole window became knowable."""
    _seed(con, matches=3)
    football_v2.build_team_match_stats_archive(con)
    football_v2.build_team_tactical_form(con)
    path = tmp_path / "v2.duckdb"
    con.close()
    cutoff = KICKOFF + timedelta(days=7)
    with FeatureSource.open(path) as source:
        view = PointInTimeView(source, AsOf(cutoff))
        frame = view.observed_team_tactical_form(
            windows=["season_to_date"], columns=["gw", "as_at_kickoff", "goals_per_match"]
        )
        assert frame.height == 2
        assert set(frame["gw"].to_list()) == {1}


def test_observed_football_excludes_provider_rows_not_known_at_as_of(
    tmp_path: Path, con: duckdb.DuckDBPyConnection
) -> None:
    _seed(con, matches=1)
    football_v2.build_team_match_stats_archive(con)
    cutoff = KICKOFF + timedelta(days=1)
    con.execute(
        "UPDATE mart_fact_team_match_stats_v2 SET known_at = ?",
        [cutoff + timedelta(seconds=1)],
    )
    path = tmp_path / "v2.duckdb"
    con.close()
    with FeatureSource.open(path) as source:
        view = PointInTimeView(source, AsOf(cutoff))
        assert view.observed_team_football(columns=["fixture"]).is_empty()


def test_tactical_form_known_at_is_the_latest_capture_in_its_window(
    tmp_path: Path, con: duckdb.DuckDBPyConnection
) -> None:
    _seed(con, matches=2)
    football_v2.build_team_match_stats_archive(con)
    revision_known_at = KICKOFF + timedelta(days=30)
    con.execute(
        "UPDATE mart_fact_team_match_stats_v2 SET known_at = ? WHERE fixture = 100",
        [revision_known_at],
    )
    football_v2.build_team_tactical_form(con)
    row = con.execute(
        """
        SELECT epoch_us(known_at) FROM mart_fact_team_tactical_form_v2
        WHERE provider = 'fpl_archive' AND team_code = 3 AND gw = 2 AND "window" = 'last_3'
        """
    ).fetchone()
    assert row == (int(revision_known_at.timestamp() * 1_000_000),)

    cutoff = KICKOFF + timedelta(days=14)
    path = tmp_path / "v2.duckdb"
    con.close()
    with FeatureSource.open(path) as source:
        view = PointInTimeView(source, AsOf(cutoff))
        frame = view.observed_team_tactical_form(team_codes=[3], windows=["last_3"], columns=["gw"])
        assert frame.is_empty()


def test_historical_sdp_evaluation_reader_fails_closed(
    con: duckdb.DuckDBPyConnection,
) -> None:
    with pytest.raises(RuntimeError, match="version-preserving provider-known-at fold reader"):
        load_team_frame(con, provider="pl_sdp")


def test_no_feature_readable_v2_column_names_points(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """R1 restated at the V2 boundary: the feature layer sees components, never points.

    Both V2 marts are feature-readable, so the repository's standing guard has to hold on them
    too. `bps` is FPL's bonus-point-system score and is deliberately named without the
    substring, because it is a component of the bonus model rather than a points total.
    """
    for table in ("mart_fact_team_match_stats_v2", "mart_fact_team_tactical_form_v2"):
        offending = [
            column
            for column in table_columns(con, table)
            if FORBIDDEN_FEATURE_COLUMN_SUBSTRING in column
        ]
        assert offending == [], f"{table} exposes {offending} to the feature layer"


def test_both_v2_marts_are_declared_feature_readable() -> None:
    """A model that cannot read them is a model that reaches around the capability."""
    assert "mart_fact_team_match_stats_v2" in FEATURE_READABLE_TABLES
    assert "mart_fact_team_tactical_form_v2" in FEATURE_READABLE_TABLES
