"""Retained provider revisions and fixture metadata reach the model read model intact."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import duckdb
import pytest

from fpl.storage.db import initialise
from fpl.transform.football_versions import build_team_match_versions
from fpl.transform.pl_sdp import SdpIdentityError

KICKOFF = datetime(2026, 8, 21, 19, tzinfo=UTC)
CAPTURED = KICKOFF + timedelta(hours=3)
TABLE = "mart_fact_team_match_stats_v2_version"


@pytest.fixture
def con() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = initialise(":memory:")
    connection.execute(
        """INSERT INTO stg_pl_sdp_fixture_crosswalk
           (season, fixture, sdp_match_id, match_method, corroborated_teams, resolved_at)
           VALUES ('2026-27', 1, 2645195, 'identity_fallback', TRUE, ?)""",
        [CAPTURED],
    )
    yield connection
    connection.close()


def metadata(
    con: duckdb.DuckDBPyConnection,
    identifier: str = "fixture-v1",
    known_at: datetime = KICKOFF - timedelta(days=1),
    gw: int = 1,
) -> None:
    for team_id, team_code, opponent, home in ((1, 3, 4, True), (4, 8, 1, False)):
        con.execute(
            """INSERT INTO stg_live_team_version
               (season, team_id, team_code, known_at, capture_id, team_name, short_name)
               VALUES ('2026-27', ?, ?, ?, ?, 'Synthetic team', 'SYN')""",
            [team_id, team_code, known_at, identifier],
        )
        con.execute(
            """INSERT INTO mart_team_fixture_live
               (season, gw, fixture, pulse_id, kickoff_time, team_id, opponent_team_id,
                was_home, known_at, capture_id)
               VALUES ('2026-27', ?, 1, 99999, ?, ?, ?, ?, ?, ?)""",
            [gw, KICKOFF, team_id, opponent, home, known_at, identifier],
        )


def stats(
    con: duckdb.DuckDBPyConnection,
    identifier: str = "stats-v1",
    known_at: datetime = CAPTURED,
    values: tuple[int | None, int | None] = (5, 7),
) -> None:
    for side, team, value in ("home", 3, values[0]), ("away", 8, values[1]):
        con.execute(
            """INSERT INTO stg_pl_sdp_team_match_stats
               (sdp_match_id, side, payload_id, known_at, sdp_team_id, stats_json,
                metric_count, mapped_count, shots_on_target)
               VALUES (2645195, ?, ?, ?, ?, ?, 2, 2, ?)""",
            [
                side,
                identifier,
                known_at,
                team,
                json.dumps({"ontargetScoringAtt": value, "totalScoringAtt": 10}),
                value,
            ],
        )


def test_retains_all_payload_and_metadata_versions_and_same_payload_mirrors(
    con: duckdb.DuckDBPyConnection,
) -> None:
    metadata(con)
    stats(con)
    assert build_team_match_versions(con) == 2
    original = con.execute(f"SELECT * FROM {TABLE} ORDER BY team_id").to_arrow_table()
    metadata(con, "fixture-v2", CAPTURED + timedelta(days=1), gw=2)
    stats(con, "stats-v2", CAPTURED + timedelta(days=2), values=(6, 8))
    assert build_team_match_versions(con) == 8
    assert build_team_match_versions(con) == 8
    assert (
        con.execute(
            f"SELECT * FROM {TABLE} WHERE capture_id = 'stats-v1' "
            "AND metadata_capture_id = 'fixture-v1' ORDER BY team_id"
        )
        .to_arrow_table()
        .equals(original)
    )
    assert con.execute(
        f"SELECT capture_id, shots_on_target, shots_on_target_allowed FROM {TABLE} "
        "WHERE was_home AND metadata_capture_id = 'fixture-v1' ORDER BY capture_id"
    ).fetchall() == [("stats-v1", 5, 7), ("stats-v2", 6, 8)]
    assert con.execute(
        f"SELECT count(*) FROM {TABLE} "
        "WHERE known_at <> greatest(source_known_at, metadata_known_at)"
    ).fetchone() == (0,)


def test_null_metric_is_not_zero_and_zero_is_complete(con: duckdb.DuckDBPyConnection) -> None:
    metadata(con)
    stats(con, values=(None, 0))
    assert build_team_match_versions(con) == 2
    assert con.execute(
        f"SELECT shots_on_target, shots_on_target_allowed, possession FROM {TABLE} WHERE was_home"
    ).fetchone() == (None, 0, None)


@pytest.mark.parametrize("missing_registry", [True, False])
def test_incomplete_later_metadata_never_displaces_complete_older_capture(
    con: duckdb.DuckDBPyConnection,
    missing_registry: bool,
) -> None:
    metadata(con)
    stats(con)
    assert build_team_match_versions(con) == 2
    original = con.execute(f"SELECT * FROM {TABLE} ORDER BY team_id").to_arrow_table()
    metadata(con, "incomplete-metadata", CAPTURED + timedelta(days=1), gw=2)
    if missing_registry:
        con.execute("DELETE FROM stg_live_team_version WHERE capture_id = 'incomplete-metadata'")
    else:
        con.execute(
            "UPDATE stg_live_team_version SET team_code = NULL "
            "WHERE capture_id = 'incomplete-metadata' AND team_id = 1"
        )
    assert build_team_match_versions(con) == 2
    assert con.execute(f"SELECT * FROM {TABLE} ORDER BY team_id").to_arrow_table().equals(original)
    assert con.execute(
        "SELECT count(*) FROM mart_team_fixture_live WHERE capture_id = 'incomplete-metadata'"
    ).fetchone() == (2,)


def test_all_metadata_without_exact_registry_fails_closed(con: duckdb.DuckDBPyConnection) -> None:
    metadata(con)
    stats(con)
    con.execute("DELETE FROM stg_live_team_version WHERE team_id = 1")
    with pytest.raises(SdpIdentityError, match="no fixture metadata"):
        build_team_match_versions(con)
    assert con.execute(f"SELECT count(*) FROM {TABLE}").fetchone() == (0,)


def test_nonnull_wrong_metadata_code_still_fails_closed(con: duckdb.DuckDBPyConnection) -> None:
    metadata(con)
    stats(con)
    con.execute("UPDATE stg_live_team_version SET team_code = 99 WHERE team_id = 1")
    with pytest.raises(SdpIdentityError, match="teamId"):
        build_team_match_versions(con)
    assert con.execute(f"SELECT count(*) FROM {TABLE}").fetchone() == (0,)


@pytest.mark.parametrize("bad_json", ["{}", '{"x": null}', '{"x": true}', '{"x": "NaN"}'])
def test_incomplete_revision_does_not_become_a_valid_fact(
    con: duckdb.DuckDBPyConnection,
    bad_json: str,
) -> None:
    metadata(con)
    stats(con)
    stats(con, "incomplete", CAPTURED + timedelta(days=1))
    con.execute(
        "UPDATE stg_pl_sdp_team_match_stats SET stats_json = ? "
        "WHERE payload_id = 'incomplete' AND side = 'away'",
        [bad_json],
    )
    assert build_team_match_versions(con) == 2
    assert con.execute(f"SELECT DISTINCT capture_id FROM {TABLE}").fetchall() == [("stats-v1",)]


def test_never_pairs_sides_from_different_captures(con: duckdb.DuckDBPyConnection) -> None:
    metadata(con)
    stats(con)
    con.execute("UPDATE stg_pl_sdp_team_match_stats SET payload_id = side")
    assert build_team_match_versions(con) == 0


def test_complete_payload_without_metadata_fails_closed(con: duckdb.DuckDBPyConnection) -> None:
    stats(con)
    with pytest.raises(SdpIdentityError, match="no fixture metadata"):
        build_team_match_versions(con)


def test_identity_error_precedes_any_version_write(con: duckdb.DuckDBPyConnection) -> None:
    metadata(con)
    stats(con)
    con.execute("UPDATE stg_pl_sdp_team_match_stats SET sdp_team_id = 8 WHERE side = 'home'")
    with pytest.raises(SdpIdentityError, match="teamId"):
        build_team_match_versions(con)
    assert con.execute(f"SELECT count(*) FROM {TABLE}").fetchone() == (0,)


def test_raw_provenance_is_retained_and_validated(con: duckdb.DuckDBPyConnection) -> None:
    metadata(con)
    stats(con)
    con.execute(
        """INSERT INTO raw_pl_sdp_payload
           (payload_id, provider, endpoint, request_path, params_json, season, sdp_match_id,
            fetched_at, status_code, payload, sha256, byte_count)
           VALUES ('stats-v1', 'pl_sdp', 'match_stats', '/api/v3/matches/2645195/stats',
                   '{}', '2026-27', 2645195, ?, 200, '{}', 'synthetic-hash', 2)""",
        [CAPTURED],
    )
    assert build_team_match_versions(con) == 2
    assert con.execute(f"SELECT DISTINCT payload_sha256 FROM {TABLE}").fetchall() == [
        ("synthetic-hash",)
    ]
    con.execute("UPDATE raw_pl_sdp_payload SET fetched_at = fetched_at + INTERVAL '1 day'")
    with pytest.raises(SdpIdentityError, match="provenance mismatch"):
        build_team_match_versions(con)
    assert con.execute(f"SELECT count(*) FROM {TABLE}").fetchone() == (2,)


def test_unversioned_archive_anchor_keeps_existing_proxy(con: duckdb.DuckDBPyConnection) -> None:
    stats(con)
    for team_id, team_code, opponent, home in ((1, 3, 4, True), (4, 8, 1, False)):
        con.execute(
            "INSERT INTO mart_dim_team (season, team_id, team_code, team_name, short_name) "
            "VALUES ('2026-27', ?, ?, 'Synthetic team', 'SYN')",
            [team_id, team_code],
        )
        con.execute(
            """INSERT INTO mart_fact_team_match
               (season, gw, fixture, kickoff_time, team_id, opponent_team_id, was_home)
               VALUES ('2026-27', 1, 1, ?, ?, ?, ?)""",
            [KICKOFF, team_id, opponent, home],
        )
    assert build_team_match_versions(con) == 2
    assert con.execute(
        f"SELECT count(*) FROM {TABLE} WHERE metadata_capture_id = 'archive' "
        "AND metadata_known_at = kickoff_time AND payload_sha256 IS NULL"
    ).fetchone() == (2,)
