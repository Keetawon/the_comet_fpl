"""P1.3 finalized-outcome attachment at player-fixture grain.

All tests use a temporary DuckDB and synthetic mart rows.  No archive build or network access is
needed; the explicit two-fixture same-gameweek case protects the required double-gameweek grain.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fpl.jobs.attach_outcomes import main as attach_outcomes_cli
from fpl.storage.db import connect, initialise
from fpl.storage.ledger import DuplicateRunError, LedgerOutcome, attach_outcomes
from fpl.storage.outcomes import (
    DuplicateOutcomeSourceError,
    NullOutcomeError,
    OutcomeConflictError,
    UnfinalizedOutcomeError,
    attach_finalized_outcomes,
    select_finalized_outcomes,
)

SEASON = "2026-27"
AS_OF = datetime(2026, 8, 30, 12, tzinfo=UTC)
KICKOFF = AS_OF - timedelta(days=1)


def _con() -> object:
    return initialise(":memory:")


def _insert_fixture(
    con: object,
    *,
    fixture: int,
    gw: int = 1,
    finished: bool | None = True,
    kickoff_time: datetime = KICKOFF,
) -> None:
    con.execute(
        """
        INSERT INTO stg_fixture (season, fixture, gw, kickoff_time, team_h, team_a, finished)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [SEASON, fixture, gw, kickoff_time, 1, 2, finished],
    )


def _insert_target(
    con: object,
    *,
    code: int,
    fixture: int,
    gw: int = 1,
    recorded: int | None = 5,
    replayed: int | None = 6,
    kickoff_time: datetime = KICKOFF,
) -> None:
    con.execute(
        """
        INSERT INTO mart_target_player_fixture (
            season, gw, fixture, kickoff_time, code, position, total_points_as_recorded,
            points_under_rules_2026_27
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [SEASON, gw, fixture, kickoff_time, code, "MID", recorded, replayed],
    )


def test_happy_path_keeps_recorded_and_replayed_points_separate() -> None:
    con = _con()
    try:
        _insert_fixture(con, fixture=100)
        _insert_target(con, code=10, fixture=100, recorded=5, replayed=7)

        result = attach_finalized_outcomes(con, as_of=AS_OF)

        assert result.selected == 1
        assert result.attached == 1
        assert result.already_attached == 0
        row = con.execute(
            """
            SELECT total_points_as_recorded, points_under_rules_2026_27
            FROM ledger_outcome_player_fixture
            WHERE season = ? AND code = ? AND fixture = ?
            """,
            [SEASON, 10, 100],
        ).fetchone()
        assert row == (5, 7)
    finally:
        con.close()


def test_same_finalized_payload_is_an_idempotent_no_op() -> None:
    con = _con()
    try:
        _insert_fixture(con, fixture=100)
        _insert_target(con, code=10, fixture=100)

        first = attach_finalized_outcomes(con, as_of=AS_OF)
        second = attach_finalized_outcomes(con, as_of=AS_OF)

        assert (first.attached, first.already_attached) == (1, 0)
        assert (second.attached, second.already_attached) == (0, 1)
        assert con.execute("SELECT count(*) FROM ledger_outcome_player_fixture").fetchone() == (1,)
    finally:
        con.close()


def test_new_final_fixture_is_appended_without_touching_existing_outcome() -> None:
    con = _con()
    try:
        _insert_fixture(con, fixture=100)
        _insert_target(con, code=10, fixture=100, recorded=5, replayed=7)
        attach_finalized_outcomes(con, as_of=AS_OF)

        _insert_fixture(con, fixture=101, gw=2)
        _insert_target(con, code=10, fixture=101, gw=2, recorded=8, replayed=9)
        result = attach_finalized_outcomes(con, as_of=AS_OF)

        assert (result.selected, result.attached, result.already_attached) == (2, 1, 1)
        assert con.execute(
            """
            SELECT fixture, total_points_as_recorded, points_under_rules_2026_27
            FROM ledger_outcome_player_fixture
            WHERE season = ? AND code = ? ORDER BY fixture
            """,
            [SEASON, 10],
        ).fetchall() == [(100, 5, 7), (101, 8, 9)]
    finally:
        con.close()


def test_unfinalized_past_fixture_is_rejected() -> None:
    con = _con()
    try:
        _insert_fixture(con, fixture=100, finished=False)
        _insert_target(con, code=10, fixture=100)

        with pytest.raises(UnfinalizedOutcomeError, match="not finalized"):
            select_finalized_outcomes(con, as_of=AS_OF)
    finally:
        con.close()


def test_fixture_at_as_of_is_not_eligible_for_attachment() -> None:
    con = _con()
    try:
        _insert_fixture(con, fixture=100, kickoff_time=AS_OF)
        _insert_target(con, code=10, fixture=100, kickoff_time=AS_OF)

        result = attach_finalized_outcomes(con, as_of=AS_OF)

        assert (result.selected, result.attached, result.already_attached) == (0, 0, 0)
        assert con.execute("SELECT count(*) FROM ledger_outcome_player_fixture").fetchone() == (0,)
    finally:
        con.close()


@pytest.mark.parametrize(
    ("recorded", "replayed"),
    [(None, 6), (5, None)],
    ids=["recorded", "replayed"],
)
def test_null_points_are_rejected_not_coerced_to_zero(
    recorded: int | None, replayed: int | None
) -> None:
    con = _con()
    try:
        _insert_fixture(con, fixture=100)
        _insert_target(con, code=10, fixture=100, recorded=recorded, replayed=replayed)

        with pytest.raises(NullOutcomeError, match="NULL"):
            select_finalized_outcomes(con, as_of=AS_OF)
    finally:
        con.close()


def test_represented_finalized_key_with_different_values_fails_closed() -> None:
    con = _con()
    try:
        _insert_fixture(con, fixture=100)
        _insert_target(con, code=10, fixture=100, recorded=5, replayed=7)
        attach_finalized_outcomes(con, as_of=AS_OF)
        con.execute(
            """
            UPDATE mart_target_player_fixture
            SET total_points_as_recorded = 6, points_under_rules_2026_27 = 8
            WHERE season = ? AND code = ? AND fixture = ?
            """,
            [SEASON, 10, 100],
        )
        _insert_fixture(con, fixture=101, gw=2)
        _insert_target(con, code=20, fixture=101, gw=2, recorded=3, replayed=4)

        with pytest.raises(OutcomeConflictError, match="differs"):
            attach_finalized_outcomes(con, as_of=AS_OF)

        assert con.execute(
            """
            SELECT total_points_as_recorded, points_under_rules_2026_27
            FROM ledger_outcome_player_fixture
            WHERE season = ? AND code = ? AND fixture = ?
            """,
            [SEASON, 10, 100],
        ).fetchone() == (5, 7)
        assert con.execute(
            "SELECT count(*) FROM ledger_outcome_player_fixture WHERE fixture = 101"
        ).fetchone() == (0,)
    finally:
        con.close()


def test_duplicate_player_fixture_source_key_is_rejected() -> None:
    con = _con()
    try:
        con.execute("DROP TABLE mart_target_player_fixture")
        con.execute(
            """
            CREATE TABLE mart_target_player_fixture (
                season VARCHAR,
                gw INTEGER,
                fixture INTEGER,
                kickoff_time TIMESTAMPTZ,
                code INTEGER,
                position VARCHAR,
                total_points_as_recorded INTEGER,
                points_under_rules_2026_27 INTEGER
            )
            """
        )
        _insert_fixture(con, fixture=100)
        _insert_target(con, code=10, fixture=100)
        _insert_target(con, code=10, fixture=100)

        with pytest.raises(DuplicateOutcomeSourceError, match="duplicate"):
            select_finalized_outcomes(con, as_of=AS_OF)
    finally:
        con.close()


def test_outcome_batch_rolls_back_when_a_later_key_conflicts() -> None:
    con = connect(":memory:")
    try:
        attach_outcomes(
            con,
            [
                LedgerOutcome(
                    season=SEASON,
                    code=10,
                    fixture=100,
                    total_points_as_recorded=5,
                    points_under_rules_2026_27=7,
                )
            ],
        )

        with pytest.raises(DuplicateRunError):
            attach_outcomes(
                con,
                [
                    LedgerOutcome(
                        season=SEASON,
                        code=11,
                        fixture=101,
                        total_points_as_recorded=3,
                        points_under_rules_2026_27=4,
                    ),
                    LedgerOutcome(
                        season=SEASON,
                        code=10,
                        fixture=100,
                        total_points_as_recorded=5,
                        points_under_rules_2026_27=7,
                    ),
                ],
            )

        assert con.execute(
            "SELECT code, fixture FROM ledger_outcome_player_fixture ORDER BY code"
        ).fetchall() == [(10, 100)]
    finally:
        con.close()


def test_double_gameweek_keeps_two_fixture_keys_for_one_player() -> None:
    con = _con()
    try:
        _insert_fixture(con, fixture=100, gw=2, kickoff_time=KICKOFF - timedelta(hours=3))
        _insert_fixture(con, fixture=101, gw=2, kickoff_time=KICKOFF)
        _insert_target(
            con,
            code=10,
            fixture=100,
            gw=2,
            recorded=2,
            replayed=3,
            kickoff_time=KICKOFF - timedelta(hours=3),
        )
        _insert_target(con, code=10, fixture=101, gw=2, recorded=5, replayed=6)

        result = attach_finalized_outcomes(con, as_of=AS_OF)

        assert (result.selected, result.attached) == (2, 2)
        assert con.execute(
            "SELECT fixture FROM ledger_outcome_player_fixture WHERE code = 10 ORDER BY fixture"
        ).fetchall() == [(100,), (101,)]
    finally:
        con.close()


def test_cli_attaches_finalized_source_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "outcomes.duckdb"
    con = initialise(db_path)
    try:
        _insert_fixture(con, fixture=100)
        _insert_target(con, code=10, fixture=100)
    finally:
        con.close()

    assert attach_outcomes_cli(["--db", str(db_path), "--as-of", AS_OF.isoformat()]) == 0

    con = connect(db_path)
    try:
        assert con.execute("SELECT count(*) FROM ledger_outcome_player_fixture").fetchone() == (1,)
    finally:
        con.close()
