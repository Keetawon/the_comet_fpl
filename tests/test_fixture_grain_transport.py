"""Offline tests for the P1.2 fixture-grain forecast transport (artifact schema version 2).

The point of transporting fixture-grain rows is that a convolved gameweek distribution cannot be
inverted, so the two grains must be carried together AND provably consistent. Most of these tests
therefore attack the mapping: they perturb one grain and assert the artifact refuses to serialise or
parse. Double gameweeks are exercised explicitly, because they are the reason the fixture grain is
the real one.

Schema-version-1 back-compat is covered too: the frozen pre-P1.2 vintages must still read.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from fpl.artifacts.prospective_points import (
    ArtifactError,
    ArtifactFixtureInput,
    ArtifactPlayerInput,
    ContractIdentity,
    ForecastArtifactManifest,
    ForecastPlayerFixtureRow,
    ForecastTeamFixtureRow,
    LiveInputProvenance,
    ProspectivePointsArtifact,
    artifact_bytes,
    build_artifact_rows,
    read_artifact_bytes,
)
from fpl.storage.db import initialise
from fpl.storage.ledger import DuplicateRunError, record_forecast

HASH = "a" * 64
AS_OF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
KICKOFF_1 = datetime(2026, 8, 22, 14, 0, tzinfo=UTC)
KICKOFF_2 = datetime(2026, 8, 25, 19, 0, tzinfo=UTC)

# Two players, one gameweek. Player 11 plays a DOUBLE gameweek (fixtures 1 and 2); player 22 plays
# only fixture 1. So the convolution has real work to do for exactly one of them.
PLAYER_A, PLAYER_B = 11, 22
TEAM_A, TEAM_B = 5, 6


def _dist(*mass: float) -> tuple[float, ...]:
    total = sum(mass)
    assert math.isclose(total, 1.0, abs_tol=1e-12), total
    return tuple(mass)


D_A1 = _dist(0.5, 0.3, 0.2)  # mean 0.7
D_A2 = _dist(0.6, 0.4)  # mean 0.4
D_B1 = _dist(0.2, 0.8)  # mean 0.8
GOALS = _dist(0.3, 0.4, 0.3)  # mean 1.0


def _players() -> tuple[ArtifactPlayerInput, ...]:
    return tuple(
        ArtifactPlayerInput(
            code=code,
            web_name=f"P{code}",
            position="MID",
            team_id=TEAM_A,
            team_code=100 + TEAM_A,
            now_cost=50,
            selected_by_percent=1.0,
            availability_status="a",
            chance_of_playing=None,
            availability_multiplier=1.0,
            cold_start_player=False,
            attacking_signal_cold_start=False,
            assist_signal_cold_start=False,
            transferred_no_rescale=False,
        )
        for code in (PLAYER_A, PLAYER_B)
    )


def _fixture_inputs() -> tuple[ArtifactFixtureInput, ...]:
    return (
        ArtifactFixtureInput(
            season="2026-27",
            gw=1,
            fixture=1,
            kickoff_time=KICKOFF_1,
            code=PLAYER_A,
            expected_bonus=0.1,
            distribution=D_A1,
            stage_a_league_average_team=False,
        ),
        ArtifactFixtureInput(
            season="2026-27",
            gw=1,
            fixture=2,
            kickoff_time=KICKOFF_2,
            code=PLAYER_A,
            expected_bonus=0.2,
            distribution=D_A2,
            stage_a_league_average_team=True,
        ),
        ArtifactFixtureInput(
            season="2026-27",
            gw=1,
            fixture=1,
            kickoff_time=KICKOFF_1,
            code=PLAYER_B,
            expected_bonus=0.3,
            distribution=D_B1,
            stage_a_league_average_team=False,
        ),
    )


def _player_fixture_rows(**overrides: Any) -> tuple[ForecastPlayerFixtureRow, ...]:
    base = [
        {
            "gw": 1,
            "fixture": 1,
            "code": PLAYER_A,
            "kickoff_time": KICKOFF_1,
            "expected_points": 0.7,
            "expected_bonus": 0.1,
            "distribution": D_A1,
            "stage_a_league_average_team": False,
        },
        {
            "gw": 1,
            "fixture": 1,
            "code": PLAYER_B,
            "kickoff_time": KICKOFF_1,
            "expected_points": 0.8,
            "expected_bonus": 0.3,
            "distribution": D_B1,
            "stage_a_league_average_team": False,
        },
        {
            "gw": 1,
            "fixture": 2,
            "code": PLAYER_A,
            "kickoff_time": KICKOFF_2,
            "expected_points": 0.4,
            "expected_bonus": 0.2,
            "distribution": D_A2,
            "stage_a_league_average_team": True,
        },
    ]
    rows = []
    for entry in base:
        entry.update(overrides.get(f"{entry['fixture']}:{entry['code']}", {}))
        rows.append(
            ForecastPlayerFixtureRow(
                season="2026-27",
                position="MID",
                team_id=TEAM_A,
                team_code=100 + TEAM_A,
                opponent_team_id=TEAM_B,
                was_home=True,
                **entry,
            )
        )
    return tuple(rows)


def _team_fixture_rows(fixtures: tuple[int, ...] = (1, 2)) -> tuple[ForecastTeamFixtureRow, ...]:
    rows = []
    for fixture in fixtures:
        for team_id, opponent in ((TEAM_A, TEAM_B), (TEAM_B, TEAM_A)):
            rows.append(
                ForecastTeamFixtureRow(
                    season="2026-27",
                    gw=1,
                    fixture=fixture,
                    kickoff_time=KICKOFF_1 if fixture == 1 else KICKOFF_2,
                    team_id=team_id,
                    team_code=100 + team_id,
                    opponent_team_id=opponent,
                    was_home=team_id == TEAM_A,
                    lambda_for=1.0,
                    lambda_against=1.0,
                    probability_clean_sheet=0.3,
                    goals_for_distribution=GOALS,
                    stage_a_league_average_team=False,
                )
            )
    return tuple(sorted(rows, key=lambda row: (row.season, row.fixture, row.team_id)))


def _manifest(**overrides: Any) -> ForecastArtifactManifest:
    base: dict[str, Any] = {
        "schema_version": 2,
        "as_of": AS_OF,
        "season": "2026-27",
        "gw_from": 1,
        "gw_to": 1,
        "row_count": 2,
        "player_fixture_row_count": 3,
        "team_fixture_row_count": 4,
        "roster_size": 2,
        "fixture_count": 2,
        "monte_carlo_draws": 100,
        "base_seed": 1,
        "fixture_points_support_max": 10,
        "freshness_cold_start": False,
        "commit_sha": "commit",
        "database_sha256": HASH,
        "contracts": {"c": ContractIdentity(name="c", version="1", sha256=HASH)},
        "component_modes": {"attacking_mode": "v3"},
        "live_inputs": LiveInputProvenance(
            bootstrap_capture_id="cap",
            bootstrap_known_at=datetime(2026, 8, 13, tzinfo=UTC),
            bootstrap_payload_sha256=HASH,
            schedule_capture_ids=("cap",),
        ),
    }
    base.update(overrides)
    return ForecastArtifactManifest(**base)


def _gameweek_rows():
    return build_artifact_rows(
        season="2026-27", gw_from=1, gw_to=1, players=_players(), fixtures=_fixture_inputs()
    )


def _artifact(**overrides: Any) -> ProspectivePointsArtifact:
    kwargs: dict[str, Any] = {
        "manifest": _manifest(),
        "rows": _gameweek_rows(),
        "player_fixture_rows": _player_fixture_rows(),
        "team_fixture_rows": _team_fixture_rows(),
    }
    kwargs.update(overrides)
    return ProspectivePointsArtifact(**kwargs)


# --------------------------------------------------------------------------------------
# The transport itself
# --------------------------------------------------------------------------------------


def test_artifact_carries_all_three_grains_and_round_trips() -> None:
    artifact = _artifact()
    restored = read_artifact_bytes(artifact_bytes(artifact))
    assert restored.manifest.schema_version == 2
    assert restored.rows == artifact.rows
    assert restored.player_fixture_rows == artifact.player_fixture_rows
    assert restored.team_fixture_rows == artifact.team_fixture_rows


def test_double_gameweek_convolves_into_one_gameweek_row() -> None:
    """The reason the fixture grain is the real one."""
    artifact = _artifact()
    by_code = {row.code: row for row in artifact.rows}
    doubled = by_code[PLAYER_A]
    assert doubled.fixture_ids == (1, 2)
    assert doubled.kickoff_times == (KICKOFF_1, KICKOFF_2)
    # mean of a sum is the sum of means, and bonus adds
    assert doubled.expected_points == pytest.approx(0.7 + 0.4)
    assert doubled.expected_bonus == pytest.approx(0.1 + 0.2)
    # the flag is the OR across the player's fixtures
    assert doubled.stage_a_league_average_team is True
    single = by_code[PLAYER_B]
    assert single.fixture_ids == (1,)
    assert single.expected_points == pytest.approx(0.8)
    assert single.stage_a_league_average_team is False


def test_record_types_partition_the_file() -> None:
    lines = artifact_bytes(_artifact()).decode().splitlines()
    kinds = [json.loads(line)["record_type"] for line in lines]
    assert kinds[0] == "manifest"
    assert kinds.count("forecast") == 2
    assert kinds.count("player_fixture") == 3
    assert kinds.count("team_fixture") == 4


def test_team_fixture_rows_carry_the_difficulty_primitives() -> None:
    row = _team_fixture_rows()[0]
    assert row.lambda_for == pytest.approx(1.0)
    assert row.lambda_against == pytest.approx(1.0)
    assert 0.0 <= row.probability_clean_sheet <= 1.0
    assert row.goals_for_distribution == GOALS


# --------------------------------------------------------------------------------------
# Schema-version-1 back-compat
# --------------------------------------------------------------------------------------


def test_version_1_artifact_still_reads_and_carries_no_fixture_rows() -> None:
    legacy = ProspectivePointsArtifact(
        manifest=_manifest(
            schema_version=1, player_fixture_row_count=None, team_fixture_row_count=None
        ),
        rows=_gameweek_rows(),
    )
    restored = read_artifact_bytes(artifact_bytes(legacy))
    assert restored.manifest.schema_version == 1
    assert restored.player_fixture_rows == ()
    assert restored.team_fixture_rows == ()


def test_version_1_manifest_may_not_declare_fixture_counts() -> None:
    with pytest.raises(ValueError, match="carries no fixture-grain rows"):
        _manifest(schema_version=1, team_fixture_row_count=None)


def test_version_2_manifest_must_declare_both_counts() -> None:
    with pytest.raises(ValueError, match="must declare"):
        _manifest(player_fixture_row_count=None)


def test_version_1_artifact_may_not_carry_fixture_rows() -> None:
    artifact = ProspectivePointsArtifact(
        manifest=_manifest(
            schema_version=1, player_fixture_row_count=None, team_fixture_row_count=None
        ),
        rows=_gameweek_rows(),
        player_fixture_rows=_player_fixture_rows(),
    )
    with pytest.raises(ArtifactError, match="version 1 cannot carry fixture-grain rows"):
        artifact_bytes(artifact)


# --------------------------------------------------------------------------------------
# The mapping invariant: the gameweek row IS the convolution of its fixture rows
# --------------------------------------------------------------------------------------


def test_declared_counts_must_match_the_rows_present() -> None:
    for override in ({"player_fixture_row_count": 2}, {"team_fixture_row_count": 3}):
        with pytest.raises(ArtifactError, match="actual"):
            artifact_bytes(_artifact(manifest=_manifest(**override)))


def test_a_perturbed_fixture_distribution_breaks_the_mapping() -> None:
    """A fixture row that is internally consistent but no longer convolves to its gameweek row.

    The row's own mean is corrected alongside the distribution, so this gets past the row-level
    reconciliation and is caught only by the cross-grain mapping check.
    """
    tampered = _player_fixture_rows(
        **{"1:11": {"distribution": _dist(0.4, 0.4, 0.2), "expected_points": 0.8}}
    )
    with pytest.raises(ArtifactError, match=r"convolve|convolution"):
        artifact_bytes(_artifact(player_fixture_rows=tampered))


def test_a_perturbed_fixture_bonus_breaks_the_mapping() -> None:
    tampered = _player_fixture_rows(**{"2:11": {"expected_bonus": 0.9}})
    with pytest.raises(ArtifactError, match="expected bonus disagrees"):
        artifact_bytes(_artifact(player_fixture_rows=tampered))


def test_a_dropped_fixture_row_breaks_the_mapping() -> None:
    """Silently losing one leg of a double gameweek must not read as a complete artifact."""
    rows = tuple(row for row in _player_fixture_rows() if row.fixture != 2)
    with pytest.raises(ArtifactError, match="names fixtures"):
        artifact_bytes(
            _artifact(manifest=_manifest(player_fixture_row_count=2), player_fixture_rows=rows)
        )


def test_a_fixture_row_without_a_gameweek_row_is_rejected() -> None:
    orphan = ForecastPlayerFixtureRow(
        season="2026-27",
        gw=1,
        fixture=3,
        code=999,
        kickoff_time=KICKOFF_1,
        position="MID",
        team_id=TEAM_A,
        team_code=100 + TEAM_A,
        opponent_team_id=TEAM_B,
        was_home=True,
        expected_points=0.0,
        expected_bonus=0.0,
        distribution=_dist(1.0),
        stage_a_league_average_team=False,
    )
    rows = tuple(sorted((*_player_fixture_rows(), orphan), key=lambda r: (r.fixture, r.code)))
    with pytest.raises(ArtifactError, match="no player-gameweek row"):
        artifact_bytes(
            _artifact(manifest=_manifest(player_fixture_row_count=4), player_fixture_rows=rows)
        )


def test_a_flipped_stage_a_flag_breaks_the_mapping() -> None:
    tampered = _player_fixture_rows(**{"2:11": {"stage_a_league_average_team": False}})
    with pytest.raises(ArtifactError, match="stage_a fallback flag disagrees"):
        artifact_bytes(_artifact(player_fixture_rows=tampered))


def test_fixture_rows_must_be_canonically_ordered_and_unique() -> None:
    rows = _player_fixture_rows()
    with pytest.raises(ArtifactError, match="canonical"):
        artifact_bytes(_artifact(player_fixture_rows=tuple(reversed(rows))))
    with pytest.raises(ArtifactError, match="duplicate"):
        artifact_bytes(
            _artifact(
                manifest=_manifest(player_fixture_row_count=4),
                player_fixture_rows=tuple(
                    sorted((*rows, rows[0]), key=lambda r: (r.fixture, r.code))
                ),
            )
        )


def test_both_sides_of_every_fixture_must_be_published() -> None:
    one_sided = tuple(row for row in _team_fixture_rows() if row.team_id == TEAM_A)
    with pytest.raises(ArtifactError, match="a fixture has two sides"):
        artifact_bytes(
            _artifact(manifest=_manifest(team_fixture_row_count=2), team_fixture_rows=one_sided)
        )


def test_row_level_reconciliation_is_enforced_at_construction() -> None:
    with pytest.raises(ValueError, match="does not match its distribution"):
        ForecastPlayerFixtureRow(
            season="2026-27",
            gw=1,
            fixture=1,
            code=PLAYER_A,
            kickoff_time=KICKOFF_1,
            position="MID",
            team_id=TEAM_A,
            team_code=None,
            opponent_team_id=TEAM_B,
            was_home=True,
            expected_points=99.0,
            expected_bonus=0.0,
            distribution=D_A1,
            stage_a_league_average_team=False,
        )
    with pytest.raises(ValueError, match="does not match its goals distribution"):
        ForecastTeamFixtureRow(
            season="2026-27",
            gw=1,
            fixture=1,
            kickoff_time=KICKOFF_1,
            team_id=TEAM_A,
            team_code=None,
            opponent_team_id=TEAM_B,
            was_home=True,
            lambda_for=99.0,
            lambda_against=1.0,
            probability_clean_sheet=0.3,
            goals_for_distribution=GOALS,
            stage_a_league_average_team=False,
        )


def test_a_fixture_cannot_have_the_same_team_on_both_sides() -> None:
    with pytest.raises(ValueError, match="same team on both sides"):
        ForecastTeamFixtureRow(
            season="2026-27",
            gw=1,
            fixture=1,
            kickoff_time=KICKOFF_1,
            team_id=TEAM_A,
            team_code=None,
            opponent_team_id=TEAM_A,
            was_home=True,
            lambda_for=1.0,
            lambda_against=1.0,
            probability_clean_sheet=0.3,
            goals_for_distribution=GOALS,
            stage_a_league_average_team=False,
        )


def test_unknown_record_type_is_rejected_on_read() -> None:
    lines = artifact_bytes(_artifact()).decode().splitlines()
    lines.append(json.dumps({"record_type": "something_else"}))
    with pytest.raises(ArtifactError, match="unknown artifact record_type"):
        read_artifact_bytes(("\n".join(lines) + "\n").encode())


# --------------------------------------------------------------------------------------
# Ledger
# --------------------------------------------------------------------------------------


def test_ledger_records_all_three_grains_in_one_transaction(tmp_path: Path) -> None:
    con = initialise(tmp_path / "ledger.duckdb")
    try:
        run_id = record_forecast(con, _artifact())
        counts = {
            table: con.execute(
                f"SELECT count(*) FROM {table} WHERE run_id = ?", [run_id]
            ).fetchone()
            for table in (
                "ledger_prediction_player_gameweek",
                "ledger_prediction_player_fixture",
                "ledger_prediction_team_fixture",
            )
        }
        assert counts["ledger_prediction_player_gameweek"][0] == 2
        assert counts["ledger_prediction_player_fixture"][0] == 3
        assert counts["ledger_prediction_team_fixture"][0] == 4
        # Append-only: the same vintage cannot be recorded twice, at any grain.
        with pytest.raises(DuplicateRunError):
            record_forecast(con, _artifact())
        assert (
            con.execute(
                "SELECT count(*) FROM ledger_prediction_player_fixture WHERE run_id = ?", [run_id]
            ).fetchone()[0]
            == 3
        )
    finally:
        con.close()


def test_ledger_accepts_a_version_1_vintage_with_no_fixture_rows(tmp_path: Path) -> None:
    legacy = ProspectivePointsArtifact(
        manifest=_manifest(
            schema_version=1, player_fixture_row_count=None, team_fixture_row_count=None
        ),
        rows=_gameweek_rows(),
    )
    con = initialise(tmp_path / "ledger.duckdb")
    try:
        run_id = record_forecast(con, legacy)
        assert (
            con.execute(
                "SELECT count(*) FROM ledger_prediction_player_fixture WHERE run_id = ?", [run_id]
            ).fetchone()[0]
            == 0
        )
        assert (
            con.execute(
                "SELECT count(*) FROM ledger_prediction_player_gameweek WHERE run_id = ?", [run_id]
            ).fetchone()[0]
            == 2
        )
    finally:
        con.close()


def test_ledger_fixture_rows_preserve_the_distribution(tmp_path: Path) -> None:
    con = initialise(tmp_path / "ledger.duckdb")
    try:
        run_id = record_forecast(con, _artifact())
        stored = con.execute(
            """
            SELECT distribution FROM ledger_prediction_player_fixture
            WHERE run_id = ? AND fixture = 1 AND code = ?
            """,
            [run_id, PLAYER_A],
        ).fetchone()
        assert stored is not None
        assert tuple(stored[0]) == pytest.approx(D_A1)
    finally:
        con.close()
