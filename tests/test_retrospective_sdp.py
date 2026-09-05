"""The validation-only retrospective SDP boundary is explicit and deterministic."""

from __future__ import annotations

from datetime import UTC, datetime

import duckdb
import pytest

from fpl.features.pit import AsOf, FeatureSource, PointInTimeView
from fpl.storage.db import initialise
from fpl.transform.pl_sdp import SdpIdentityError
from fpl.validate.retrospective_sdp import (
    EVIDENCE_CLASS,
    VERSION_SELECTION_POLICY,
    RetrospectiveBackfillView,
)

KICKOFF = datetime(2024, 8, 17, 14, 0, tzinfo=UTC)
AS_OF = AsOf(datetime(2024, 8, 24, 14, 0, tzinfo=UTC))


@pytest.fixture
def con() -> duckdb.DuckDBPyConnection:
    connection = initialise(":memory:")
    yield connection
    connection.close()


def _archive_fixture(
    con: duckdb.DuckDBPyConnection,
    *,
    fixture: int = 1,
    match_id: int = 9001,
    kickoff: datetime = KICKOFF,
    pulse_id: int = 7001,
) -> None:
    for team_id, team_code, opponent_id, opponent_code, was_home, goals, conceded, xg in (
        (1, 101, 2, 202, True, 2, 1, 1.7),
        (2, 202, 1, 101, False, 1, 2, 0.8),
    ):
        con.execute(
            """
            INSERT INTO mart_fact_team_match_stats_v2 (
                season, gw, fixture, pulse_id, kickoff_time, team_id, team_code,
                opponent_team_id, opponent_team_code, was_home, provider, known_at,
                goals, goals_allowed, expected_goals, expected_goals_allowed
            ) VALUES ('2024-25', 1, ?, ?, ?, ?, ?, ?, ?, ?, 'fpl_archive', ?, ?, ?, ?, ?)
            """,
            [
                fixture,
                pulse_id,
                kickoff,
                team_id,
                team_code,
                opponent_id,
                opponent_code,
                was_home,
                kickoff,
                goals,
                conceded,
                xg,
                0.8 if was_home else 1.7,
            ],
        )
    con.execute(
        """
        INSERT INTO stg_pl_sdp_fixture_crosswalk (
            season, fixture, sdp_match_id, match_method, pulse_id,
            corroborated_kickoff, corroborated_teams, corroborated_score, resolved_at
        ) VALUES ('2024-25', ?, ?, 'kickoff_teams_score', ?, TRUE, TRUE, TRUE, ?)
        """,
        [fixture, match_id, pulse_id, datetime(2026, 9, 5, tzinfo=UTC)],
    )


def _raw_capture(
    con: duckdb.DuckDBPyConnection,
    *,
    payload_id: str,
    fetched_at: datetime,
    match_id: int = 9001,
    sides: tuple[tuple[str, int], ...] = (("home", 101), ("away", 202)),
    sot: tuple[float | None, ...] = (3.0, 4.0),
    alias_sot: tuple[float | None, ...] | None = None,
) -> None:
    con.execute(
        """
        INSERT INTO raw_pl_sdp_payload (
            payload_id, provider, endpoint, request_path, params_json, season,
            sdp_match_id, fetched_at, status_code, payload, sha256, byte_count
        ) VALUES (?, 'pl_sdp', 'match_stats', '/stats', '{}', '2024-25', ?, ?,
                  200, '{}', ?, 2)
        """,
        [payload_id, match_id, fetched_at, f"sha-{payload_id}"],
    )
    for index, (side, team_code) in enumerate(sides):
        con.execute(
            """
            INSERT INTO stg_pl_sdp_team_match_stats (
                sdp_match_id, side, payload_id, known_at, sdp_team_id, team_name,
                stats_json, metric_count, mapped_count
            ) VALUES (?, ?, ?, ?, ?, ?, '{}', 1, 1)
            """,
            [match_id, side, payload_id, fetched_at, team_code, side],
        )
        con.execute(
            """
            INSERT INTO stg_pl_sdp_team_match_metric (
                sdp_match_id, side, payload_id, provider_field, local_field,
                value_numeric, value_text
            ) VALUES (?, ?, ?, 'ontargetScoringAtt', 'shots_on_target', ?, NULL)
            """,
            [match_id, side, payload_id, sot[index]],
        )
        if alias_sot is not None:
            con.execute(
                """
                INSERT INTO stg_pl_sdp_team_match_metric (
                    sdp_match_id, side, payload_id, provider_field, local_field,
                    value_numeric, value_text
                ) VALUES (?, ?, ?, 'shotsOnTarget', 'shots_on_target', ?, NULL)
                """,
                [match_id, side, payload_id, alias_sot[index]],
            )


def test_later_known_history_is_retrospective_only(con: duckdb.DuckDBPyConnection) -> None:
    _archive_fixture(con)
    captured = datetime(2026, 9, 5, 1, 0, tzinfo=UTC)
    _raw_capture(con, payload_id="first", fetched_at=captured)
    con.execute(
        """
        INSERT INTO mart_fact_team_match_stats_v2 (
            season, gw, fixture, pulse_id, sdp_match_id, kickoff_time, team_id,
            team_code, opponent_team_id, opponent_team_code, was_home, provider,
            known_at, shots_on_target
        ) VALUES ('2024-25', 1, 1, 7001, 9001, ?, 1, 101, 2, 202, TRUE,
                  'pl_sdp', ?, 3)
        """,
        [KICKOFF, captured],
    )

    strict = PointInTimeView(FeatureSource(con), AS_OF).observed_team_football(providers=["pl_sdp"])
    retrospective = RetrospectiveBackfillView(con, AS_OF).observed_real_sot()

    assert strict.is_empty()
    assert retrospective.height == 2
    assert retrospective["source_known_at"].min() > AS_OF.ts
    assert retrospective["evidence_class"].unique().to_list() == [EVIDENCE_CLASS]
    assert retrospective["version_selection_policy"].unique().to_list() == [
        VERSION_SELECTION_POLICY
    ]
    assert RetrospectiveBackfillView.EVIDENCE_CLASS == EVIDENCE_CLASS
    assert RetrospectiveBackfillView.PROVIDER_FIELD == "ontargetScoringAtt"


def test_earliest_complete_payload_wins_and_incomplete_capture_is_skipped(
    con: duckdb.DuckDBPyConnection,
) -> None:
    _archive_fixture(con, pulse_id=123)  # Crosswalk, not pulse equality, owns identity.
    _raw_capture(
        con,
        payload_id="incomplete",
        fetched_at=datetime(2026, 9, 5, 0, 0, tzinfo=UTC),
        sides=(("home", 101),),
        sot=(88.0,),
    )
    _raw_capture(
        con,
        payload_id="duplicate-team",
        fetched_at=datetime(2026, 9, 5, 0, 30, tzinfo=UTC),
        sides=(("home", 101), ("away", 101)),
        sot=(89.0, 89.0),
    )
    _raw_capture(
        con,
        payload_id="first-complete",
        fetched_at=datetime(2026, 9, 5, 1, 0, tzinfo=UTC),
        sot=(3.0, 4.0),
    )
    _raw_capture(
        con,
        payload_id="later-revision",
        fetched_at=datetime(2026, 9, 5, 2, 0, tzinfo=UTC),
        sot=(93.0, 94.0),
    )

    frame = RetrospectiveBackfillView(con, AS_OF).observed_real_sot()

    assert frame["capture_id"].unique().to_list() == ["first-complete"]
    assert frame["shots_on_target"].to_list() == [3.0, 4.0]
    assert frame["pulse_id"].unique().to_list() == [123]
    assert frame["sdp_match_id"].unique().to_list() == [9001]


def test_exact_sot_field_null_is_not_filled_from_an_alias(
    con: duckdb.DuckDBPyConnection,
) -> None:
    _archive_fixture(con)
    _raw_capture(
        con,
        payload_id="exact-null",
        fetched_at=datetime(2026, 9, 5, tzinfo=UTC),
        sot=(None, None),
        alias_sot=(7.0, 8.0),
    )

    frame = RetrospectiveBackfillView(con, AS_OF).observed_real_sot()

    assert frame["shots_on_target"].null_count() == 2
    assert frame["provider_field"].unique().to_list() == ["ontargetScoringAtt"]


@pytest.mark.parametrize("invalid", [-1.0, 2.5])
def test_sot_must_be_a_non_negative_count(con: duckdb.DuckDBPyConnection, invalid: float) -> None:
    _archive_fixture(con)
    _raw_capture(
        con,
        payload_id="invalid-count",
        fetched_at=datetime(2026, 9, 5, tzinfo=UTC),
        sot=(invalid, 4.0),
    )

    with pytest.raises(ValueError, match="non-negative count"):
        RetrospectiveBackfillView(con, AS_OF).observed_real_sot()


def test_event_cutoff_and_future_database_truncation_are_invariant(
    con: duckdb.DuckDBPyConnection,
) -> None:
    _archive_fixture(con)
    _raw_capture(
        con,
        payload_id="past",
        fetched_at=datetime(2026, 9, 5, tzinfo=UTC),
    )
    view = RetrospectiveBackfillView(con, AS_OF)
    before = view.observed_real_sot()

    _archive_fixture(
        con,
        fixture=2,
        match_id=9002,
        kickoff=AS_OF.ts,
        pulse_id=7002,
    )
    _raw_capture(
        con,
        payload_id="future",
        fetched_at=datetime(2026, 9, 5, 3, 0, tzinfo=UTC),
        match_id=9002,
        sot=(99.0, 99.0),
    )

    after = view.observed_real_sot()
    assert before.equals(after)
    assert after["kickoff_time"].max() < AS_OF.ts


def test_provider_team_identity_mismatch_fails_closed(
    con: duckdb.DuckDBPyConnection,
) -> None:
    _archive_fixture(con)
    _raw_capture(
        con,
        payload_id="wrong-team",
        fetched_at=datetime(2026, 9, 5, tzinfo=UTC),
        sides=(("home", 999), ("away", 202)),
    )

    with pytest.raises(SdpIdentityError, match="disagrees with FPL permanent team_code"):
        RetrospectiveBackfillView(con, AS_OF).observed_real_sot()


def test_uncorroborated_crosswalk_fails_closed(con: duckdb.DuckDBPyConnection) -> None:
    _archive_fixture(con)
    _raw_capture(
        con,
        payload_id="capture",
        fetched_at=datetime(2026, 9, 5, tzinfo=UTC),
    )
    con.execute(
        """
        UPDATE stg_pl_sdp_fixture_crosswalk
        SET corroborated_score = FALSE
        WHERE season = '2024-25' AND fixture = 1
        """
    )

    with pytest.raises(SdpIdentityError, match="not fully corroborated"):
        RetrospectiveBackfillView(con, AS_OF).observed_real_sot()


def test_empty_season_selection_is_empty_and_deterministic(
    con: duckdb.DuckDBPyConnection,
) -> None:
    _archive_fixture(con)
    _raw_capture(
        con,
        payload_id="capture",
        fetched_at=datetime(2026, 9, 5, tzinfo=UTC),
    )
    view = RetrospectiveBackfillView(con, AS_OF)

    assert view.observed_real_sot(seasons=[]).is_empty()
    one = view.observed_real_sot(seasons=["2024-25"])
    two = view.observed_real_sot(seasons=["2024-25"])
    assert one.equals(two)
    assert one.select("team_code").to_series().to_list() == [101, 202]
