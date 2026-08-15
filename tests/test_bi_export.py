"""P1.4 contract tests for the atomic, read-only BI Parquet boundary."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

import pyarrow.parquet as pq
import pytest

from fpl.artifacts.optimizer_plan import (
    ForecastInputProvenance,
    InitialSquadRecord,
    OptimizerProvenance,
    PlayerRef,
    PositionRuleRecord,
    SearchPolicy,
    SolverIdentity,
    SquadMemberRecord,
    SquadRulesProvenance,
    SquadRulesSnapshot,
    TransferPlanRecord,
    TransferWeekRecord,
    build_optimizer_plan_artifact,
    write_optimizer_artifact_atomic,
)
from fpl.artifacts.prospective_points import (
    ContractIdentity,
    ForecastArtifactManifest,
    ForecastArtifactRow,
    ForecastPlayerFixtureRow,
    ForecastTeamFixtureRow,
    LiveInputProvenance,
    ProspectivePointsArtifact,
    artifact_bytes,
)
from fpl.publish.contract import SEMANTIC_CONTRACT_V1
from fpl.publish.export import (
    EASE_INDEX_FORMULA_VERSION,
    BiExportConcurrentWriterError,
    BiExportFreshnessError,
    BiExportSourceError,
    BiExportValidationError,
    OptimizerPlanResolutionError,
    export_bi,
    validate_bi_export,
)
from fpl.storage.db import connect, default_db_path, initialise
from fpl.storage.ledger import record_forecast

SEASON = "2026-27"
AS_OF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
KNOWN_AT = AS_OF - timedelta(hours=2)
KICKOFF = datetime(2026, 8, 22, 14, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _positions() -> tuple[str, ...]:
    return ("GK", "GK", *("DEF",) * 5, *("MID",) * 5, *("FWD",) * 3)


def _forecast_artifact() -> ProspectivePointsArtifact:
    rows = tuple(
        ForecastArtifactRow(
            season=SEASON,
            gw=1,
            code=code,
            web_name=f"P{code}",
            position=position,  # type: ignore[arg-type]
            team_id=1,
            team_code=101,
            now_cost=50,
            selected_by_percent=None if code == 1 else 10.0,
            availability_status="a",
            chance_of_playing=None if code == 1 else 75.0,
            availability_multiplier=1.0,
            fixture_ids=(100,),
            kickoff_times=(KICKOFF,),
            expected_points=1.0,
            availability_adjusted_expected_points=1.0,
            expected_bonus=0.0,
            distribution=(0.0, 1.0),
            cold_start_player=False,
            stage_a_league_average_team=False,
            attacking_signal_cold_start=False,
            assist_signal_cold_start=False,
            transferred_no_rescale=False,
        )
        for code, position in enumerate(_positions(), start=1)
    )
    player_fixture_rows = tuple(
        ForecastPlayerFixtureRow(
            season=SEASON,
            gw=1,
            fixture=100,
            code=row.code,
            kickoff_time=KICKOFF,
            position=row.position,
            team_id=1,
            team_code=101,
            opponent_team_id=2,
            was_home=True,
            expected_points=1.0,
            expected_bonus=0.0,
            distribution=(0.0, 1.0),
            stage_a_league_average_team=False,
        )
        for row in rows
    )
    team_fixture_rows = (
        ForecastTeamFixtureRow(
            season=SEASON,
            gw=1,
            fixture=100,
            kickoff_time=KICKOFF,
            team_id=1,
            team_code=101,
            opponent_team_id=2,
            was_home=True,
            lambda_for=2.0,
            lambda_against=0.0,
            probability_clean_sheet=1.0,
            goals_for_distribution=(0.0, 0.0, 1.0),
            stage_a_league_average_team=False,
        ),
        ForecastTeamFixtureRow(
            season=SEASON,
            gw=1,
            fixture=100,
            kickoff_time=KICKOFF,
            team_id=2,
            team_code=102,
            opponent_team_id=1,
            was_home=False,
            lambda_for=0.0,
            lambda_against=2.0,
            probability_clean_sheet=0.0,
            goals_for_distribution=(1.0,),
            stage_a_league_average_team=False,
        ),
    )
    manifest = ForecastArtifactManifest(
        schema_version=2,
        as_of=AS_OF,
        season=SEASON,
        gw_from=1,
        gw_to=1,
        row_count=len(rows),
        player_fixture_row_count=len(player_fixture_rows),
        team_fixture_row_count=len(team_fixture_rows),
        roster_size=len(rows),
        fixture_count=1,
        monte_carlo_draws=100,
        base_seed=11,
        fixture_points_support_max=20,
        freshness_cold_start=True,
        commit_sha="forecast-commit",
        database_sha256=HASH_A,
        contracts={"synthetic": ContractIdentity(name="synthetic", version="1", sha256=HASH_A)},
        component_modes={"mode": "synthetic"},
        live_inputs=LiveInputProvenance(
            bootstrap_capture_id="bootstrap-1",
            bootstrap_known_at=KNOWN_AT,
            bootstrap_payload_sha256=HASH_A,
            schedule_capture_ids=("schedule-1",),
        ),
    )
    return ProspectivePointsArtifact(
        manifest=manifest,
        rows=rows,
        player_fixture_rows=player_fixture_rows,
        team_fixture_rows=team_fixture_rows,
    )


def _seed_database(path: Path, *, record: bool) -> tuple[ProspectivePointsArtifact, str | None]:
    artifact = _forecast_artifact()
    con = initialise(path)
    try:
        con.executemany(
            """
            INSERT INTO mart_dim_team (season, team_id, team_code, team_name, short_name, pulse_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [(SEASON, 1, 101, "Alpha", "ALP", 1001), (SEASON, 2, 102, "Beta", "BET", 1002)],
        )
        con.executemany(
            """
            INSERT INTO mart_dim_player (
                code, season, element_id, web_name, position, team_id, opta_code
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (code, SEASON, 1_000 + code, f"P{code}", position, 1, None)
                for code, position in enumerate(_positions(), start=1)
            ],
        )
        con.executemany(
            """
            INSERT INTO mart_dim_player_stint (
                season, code, team_id, stint_index, first_gw, last_gw,
                first_kickoff, last_kickoff, appearances, minutes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [(SEASON, code, 1, 1, 1, 1, KICKOFF, KICKOFF, 1, 90) for code in range(1, 16)],
        )
        con.execute(
            """
            INSERT INTO stg_fixture (
                season, fixture, pulse_id, gw, kickoff_time, team_h, team_a, finished
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [SEASON, 100, 9001, 1, KICKOFF, 1, 2, True],
        )
        con.executemany(
            """
            INSERT INTO mart_fact_team_match (
                season, gw, fixture, kickoff_time, team_id, opponent_team_id, was_home, fdr
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (SEASON, 1, 100, KICKOFF, 1, 2, True, 2),
                (SEASON, 1, 100, KICKOFF, 2, 1, False, 4),
            ],
        )
        con.execute(
            """
            INSERT INTO mart_fact_player_fixture (
                season, gw, fixture, kickoff_time, code, position, team_id, opponent_team_id,
                was_home, minutes, starts, goals_scored, assists, clean_sheets, goals_conceded,
                saves, penalties_saved, penalties_missed, own_goals, yellow_cards, red_cards,
                bonus, bps, expected_goals, expected_assists, expected_goals_conceded,
                defensive_contribution, threat, creativity, influence
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?
            )
            """,
            [
                SEASON,
                1,
                100,
                KICKOFF,
                1,
                "GK",
                1,
                2,
                True,
                90,
                1,
                0,
                0,
                1,
                0,
                3,
                0,
                0,
                0,
                0,
                0,
                1,
                20,
                None,
                0.2,
                None,
                None,
                10.0,
                11.0,
                12.0,
            ],
        )
        con.execute(
            """
            INSERT INTO mart_target_player_fixture (
                season, gw, fixture, kickoff_time, code, position,
                total_points_as_recorded, points_under_rules_2026_27
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [SEASON, 1, 100, KICKOFF, 1, "GK", 6, 7],
        )
        con.execute(
            """
            INSERT INTO mart_fact_player_form (
                season, gw, code, "window", rostered_fixtures, appearances, starts,
                did_not_play, minutes, goals_scored, assists, bonus, bps,
                defensive_contribution, expected_goals, expected_assists,
                expected_goals_per_90, expected_assists_per_90, points_under_rules_2026_27
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                SEASON,
                1,
                1,
                "last_3",
                1,
                1,
                1,
                0,
                90,
                0,
                0,
                1,
                20,
                None,
                None,
                0.2,
                None,
                0.2,
                7,
            ],
        )
        return artifact, record_forecast(con, artifact) if record else None
    finally:
        con.close()


_ELEMENT_TYPE = {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}


def _seed_live_database(path: Path) -> tuple[ProspectivePointsArtifact, str]:
    """Seed ONLY the live snapshot registry for the forecast season -- no marts for it.

    This is the real deadline shape: the archive marts cover completed seasons only, so the
    2026-27 forecast's players, clubs, fixtures and gameweeks must resolve through the live-season
    dimension rows the exporter unions in from the versioned live staging.
    """
    artifact = _forecast_artifact()
    con = initialise(path)
    try:
        con.executemany(
            """
            INSERT INTO stg_live_team_version (
                season, team_id, team_code, known_at, capture_id, team_name, short_name, pulse_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (SEASON, 1, 101, KNOWN_AT, "cap-live", "Alpha", "ALP", 1001),
                (SEASON, 2, 102, KNOWN_AT, "cap-live", "Beta", "BET", 1002),
            ],
        )
        con.executemany(
            """
            INSERT INTO stg_live_player_version (
                season, element, code, known_at, capture_id, web_name, element_type, position,
                team_id, now_cost, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    SEASON,
                    code,
                    code,
                    KNOWN_AT,
                    "cap-live",
                    f"P{code}",
                    _ELEMENT_TYPE[pos],
                    pos,
                    1,
                    50,
                    "a",
                )
                for code, pos in enumerate(_positions(), start=1)
            ],
        )
        con.execute(
            """
            INSERT INTO stg_live_fixture_version (
                season, fixture, known_at, capture_id, gw, kickoff_time, team_h, team_a,
                team_h_difficulty, team_a_difficulty, finished
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [SEASON, 100, KNOWN_AT, "cap-live", 1, KICKOFF, 1, 2, 3, 3, False],
        )
        con.executemany(
            """
            INSERT INTO mart_team_fixture_live (
                season, gw, fixture, kickoff_time, team_id, opponent_team_id, was_home,
                fdr, known_at, capture_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (SEASON, 1, 100, KICKOFF, 1, 2, True, 5, KNOWN_AT - timedelta(hours=1), "old"),
                (SEASON, 1, 100, KICKOFF, 2, 1, False, 5, KNOWN_AT - timedelta(hours=1), "old"),
                (SEASON, 1, 100, KICKOFF, 1, 2, True, 2, KNOWN_AT, "cap-live"),
                (SEASON, 1, 100, KICKOFF, 2, 1, False, 4, KNOWN_AT, "cap-live"),
            ],
        )
        return artifact, record_forecast(con, artifact)
    finally:
        con.close()


def _optimizer_artifact(artifact: ProspectivePointsArtifact, *, forecast_sha256: str | None = None):
    positions = _positions()
    members = tuple(
        SquadMemberRecord(
            code=code,
            web_name=f"P{code}",
            position=position,  # type: ignore[arg-type]
            team_id=1,
            team_code=101,
            now_cost=50,
            selected_by_percent=None,
        )
        for code, position in enumerate(positions, start=1)
    )
    refs = {
        member.code: PlayerRef(code=member.code, web_name=member.web_name) for member in members
    }
    rules = SquadRulesSnapshot(
        contract_version="synthetic-1",
        season=SEASON,
        squad_size=15,
        budget_tenths=1_000,
        maximum_per_club=15,
        positions=(
            PositionRuleRecord(position="GK", squad=2, minimum_starters=1, maximum_starters=1),
            PositionRuleRecord(position="DEF", squad=5, minimum_starters=3, maximum_starters=5),
            PositionRuleRecord(position="MID", squad=5, minimum_starters=2, maximum_starters=5),
            PositionRuleRecord(position="FWD", squad=3, minimum_starters=1, maximum_starters=3),
        ),
        lineup_starters=11,
        captain_multiplier=2,
        goalkeeper_bench_slots=1,
        outfield_bench_slots=3,
    )
    total_cost = sum(member.now_cost for member in members)
    week = TransferWeekRecord(
        gw=1,
        transfers_in=(),
        transfers_out=(),
        free_transfers_before=0,
        free_transfers_after=0,
        hit_points=0,
        squad_cost_tenths=total_cost,
        squad_after_transfers=members,
        starting_xi=tuple(refs[code] for code in (1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15)),
        captain=refs[13],
        vice_captain=refs[14],
        bench_goalkeeper=refs[2],
        bench_order=(refs[6], refs[7], refs[12]),
        expected_points=50.0,
        objective_value=50.0,
    )
    plan = TransferPlanRecord(
        expected_points_before_hits=50.0,
        hit_points=0,
        expected_points_after_hits=50.0,
        objective_value_after_hits=50.0,
        candidate_pool_size=15,
        weeks=(week,),
    )
    provenance = OptimizerProvenance(
        optimizer_commit_sha="optimizer-commit",
        forecast=ForecastInputProvenance(
            path="forecast.jsonl",
            sha256=forecast_sha256 or hashlib.sha256(artifact_bytes(artifact)).hexdigest(),
            forecast_schema="fpl.prospective-points",
            forecast_schema_version=2,
            as_of=artifact.manifest.as_of,
            season=artifact.manifest.season,
            gw_from=artifact.manifest.gw_from,
            gw_to=artifact.manifest.gw_to,
            commit_sha=artifact.manifest.commit_sha,
        ),
        squad_rules=SquadRulesProvenance(
            path="rules.yaml", contract_version=rules.contract_version, sha256=HASH_B
        ),
    )
    return build_optimizer_plan_artifact(
        provenance=provenance,
        search_policy=SearchPolicy(
            candidate_pool_per_position=15,
            transfer_depth=1,
            transition_limit_per_state=1,
            beam_width=1,
            free_transfer_per_gameweek=1,
            free_transfer_bank_cap=2,
            hit_cost_points=4,
            maximum_transfers_per_gameweek=1,
            risk_lambda=0.0,
            search_method="synthetic",
            optimality_scope="synthetic",
        ),
        solver=SolverIdentity(
            name="synthetic",
            package="synthetic",
            package_version="1",
            binary_version="1",
            options=(),
            seed=0,
            status="Optimal",
        ),
        rules=rules,
        initial_squad=InitialSquadRecord(
            cost_tenths=total_cost, solver_status="Optimal", members=members
        ),
        plan=plan,
        assumptions=("synthetic P1.4 decision",),
    )


def _write_optimizer_plan(path: Path, artifact: ProspectivePointsArtifact) -> Path:
    write_optimizer_artifact_atomic(path, _optimizer_artifact(artifact))
    return path


def _table_paths(output_dir: Path) -> tuple[Path, ...]:
    return tuple(output_dir / f"{table.name}.parquet" for table in SEMANTIC_CONTRACT_V1.tables)


def test_export_writes_complete_contract_and_preserves_nulls(tmp_path: Path) -> None:
    database = tmp_path / "synthetic.duckdb"
    artifact, run_id = _seed_database(database, record=True)
    assert run_id is not None
    plan_path = _write_optimizer_plan(tmp_path / "plan.json", artifact)

    output = tmp_path / "published"
    result = export_bi(
        database,
        output,
        optimizer_plan_paths=(plan_path,),
        created_at=datetime(2026, 8, 25, tzinfo=UTC),
    )
    manifest = validate_bi_export(output)

    assert output.is_symlink()
    assert set(result.tables) == {table.name for table in SEMANTIC_CONTRACT_V1.tables}
    assert manifest["exported_run_ids"] == [run_id]
    assert manifest["source_known_at"] == {
        "minimum": KNOWN_AT.isoformat(),
        "maximum": KNOWN_AT.isoformat(),
    }
    for path in _table_paths(output):
        entry = manifest["tables"][path.stem]
        assert entry["row_count"] == pq.read_table(path).num_rows
        assert entry["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()

    actual = pq.read_table(output / "fact_player_fixture_actual.parquet")
    assert actual.column("expected_goals").to_pylist() == [None]
    assert actual.column("total_points_as_recorded").to_pylist() == [6]
    assert actual.column("points_under_rules_2026_27").to_pylist() == [7]
    fixture_forecast = pq.read_table(output / "fact_forecast_player_fixture.parquet")
    assert fixture_forecast.column("expected_minutes").to_pylist() == [None] * 15
    optimizer = pq.read_table(output / "fact_optimizer_plan.parquet")
    assert optimizer.num_rows == 15
    assert set(optimizer.column("forecast_run_id").to_pylist()) == {run_id}
    assert optimizer.column("transferred_out").to_pylist() == [False] * 15


def test_team_fixture_ease_indices_are_directed_and_keep_raw_lambdas(tmp_path: Path) -> None:
    database = tmp_path / "ease.duckdb"
    _seed_database(database, record=True)

    output = export_bi(database, tmp_path / "published").output_dir
    team = pq.read_table(output / "fact_forecast_team_fixture.parquet")

    assert team.column("team_id").to_pylist() == [1, 2]
    assert team.column("lambda_for").to_pylist() == pytest.approx([2.0, 0.0])
    assert team.column("lambda_against").to_pylist() == pytest.approx([0.0, 2.0])
    assert team.column("league_average_team_lambda").to_pylist() == pytest.approx([1.0, 1.0])
    assert team.column("attack_ease_index").to_pylist() == pytest.approx([200.0, 0.0])
    assert team.column("defence_ease_index").to_pylist() == [None, 50.0]
    assert team.column("overall_ease_index").to_pylist() == [None, 0.0]
    assert team.column("ease_index_formula_version").to_pylist() == [
        EASE_INDEX_FORMULA_VERSION,
        EASE_INDEX_FORMULA_VERSION,
    ]
    assert team.column("official_fdr").to_pylist() == [2, 4]


def test_low_coverage_and_non_positive_denominators_publish_real_nulls(tmp_path: Path) -> None:
    low_coverage_db = tmp_path / "low-coverage.duckdb"
    _seed_database(low_coverage_db, record=True)
    con = connect(low_coverage_db)
    try:
        con.execute("DELETE FROM ledger_prediction_team_fixture WHERE team_id = 2")
    finally:
        con.close()
    low_output = export_bi(low_coverage_db, tmp_path / "low-published").output_dir
    low = pq.read_table(low_output / "fact_forecast_team_fixture.parquet")

    for name in (
        "league_average_team_lambda",
        "attack_ease_index",
        "defence_ease_index",
        "overall_ease_index",
    ):
        assert low.column(name).to_pylist() == [None]
        assert low.column(name).null_count == 1
    assert low.column("ease_index_formula_version").to_pylist() == [EASE_INDEX_FORMULA_VERSION]

    non_positive_db = tmp_path / "non-positive.duckdb"
    _seed_database(non_positive_db, record=True)
    con = connect(non_positive_db)
    try:
        con.execute("UPDATE ledger_prediction_team_fixture SET lambda_for = 0, lambda_against = 0")
    finally:
        con.close()
    zero_output = export_bi(non_positive_db, tmp_path / "zero-published").output_dir
    zero = pq.read_table(zero_output / "fact_forecast_team_fixture.parquet")
    for name in (
        "league_average_team_lambda",
        "attack_ease_index",
        "defence_ease_index",
        "overall_ease_index",
    ):
        assert zero.column(name).to_pylist() == [None, None]
        assert zero.column(name).null_count == 2


def test_official_fdr_is_separate_and_cannot_change_ease_indices(tmp_path: Path) -> None:
    database = tmp_path / "fdr-separate.duckdb"
    _seed_database(database, record=True)
    first = export_bi(database, tmp_path / "first-fdr").output_dir
    first_team = pq.read_table(first / "fact_forecast_team_fixture.parquet")
    ease_columns = (
        "league_average_team_lambda",
        "attack_ease_index",
        "defence_ease_index",
        "overall_ease_index",
    )
    first_ease = {name: first_team.column(name).to_pylist() for name in ease_columns}

    con = connect(database)
    try:
        con.execute("UPDATE mart_fact_team_match SET fdr = 5 - fdr")
    finally:
        con.close()
    second = export_bi(database, tmp_path / "second-fdr").output_dir
    second_team = pq.read_table(second / "fact_forecast_team_fixture.parquet")

    assert first_team.column("official_fdr").to_pylist() == [2, 4]
    assert second_team.column("official_fdr").to_pylist() == [3, 1]
    assert {name: second_team.column(name).to_pylist() for name in ease_columns} == first_ease


def test_genuinely_unavailable_official_fdr_stays_null(tmp_path: Path) -> None:
    database = tmp_path / "missing-fdr.duckdb"
    _seed_database(database, record=True)
    con = connect(database)
    try:
        con.execute("UPDATE mart_fact_team_match SET fdr = NULL WHERE team_id = 2")
    finally:
        con.close()

    output = export_bi(database, tmp_path / "published").output_dir
    team = pq.read_table(output / "fact_forecast_team_fixture.parquet")
    assert team.column("official_fdr").to_pylist() == [2, None]
    assert team.column("official_fdr").null_count == 1


def test_zero_recorded_runs_is_a_complete_export(tmp_path: Path) -> None:
    database = tmp_path / "fresh.duckdb"
    _seed_database(database, record=False)

    output = tmp_path / "published"
    manifest = export_bi(database, output, created_at=datetime(2026, 8, 25, tzinfo=UTC))
    checked = validate_bi_export(output)

    assert manifest.exported_run_ids == ()
    assert checked["freshness"]["status"] == "complete_no_recorded_forecast_runs"
    for table_name in (
        "dim_forecast_run",
        "fact_forecast_player_gameweek",
        "fact_forecast_player_fixture",
        "fact_forecast_team_fixture",
        "fact_optimizer_plan",
    ):
        assert checked["tables"][table_name]["row_count"] == 0


def test_legacy_v1_vintage_with_no_fixture_rows_is_still_complete(tmp_path: Path) -> None:
    database = tmp_path / "legacy-vintage.duckdb"
    artifact, _ = _seed_database(database, record=False)
    legacy = ProspectivePointsArtifact(
        manifest=artifact.manifest.model_copy(
            update={
                "schema_version": 1,
                "player_fixture_row_count": None,
                "team_fixture_row_count": None,
            }
        ),
        rows=artifact.rows,
    )
    con = connect(database)
    try:
        run_id = record_forecast(con, legacy)
    finally:
        con.close()

    manifest = validate_bi_export(export_bi(database, tmp_path / "published").output_dir)
    assert manifest["exported_run_ids"] == [run_id]
    assert manifest["tables"]["fact_forecast_player_gameweek"]["row_count"] == 15
    assert manifest["tables"]["fact_forecast_player_fixture"]["row_count"] == 0
    assert manifest["tables"]["fact_forecast_team_fixture"]["row_count"] == 0


def test_export_rejects_season_scoped_referential_integrity_violation(tmp_path: Path) -> None:
    database = tmp_path / "invalid-ri.duckdb"
    _, run_id = _seed_database(database, record=True)
    assert run_id is not None
    output = tmp_path / "published"
    export_bi(database, output, created_at=datetime(2026, 8, 25, tzinfo=UTC))
    previous_manifest = (output / "manifest.json").read_bytes()
    con = connect(database)
    try:
        con.execute(
            """
            UPDATE ledger_prediction_player_fixture
            SET team_id = 99
            WHERE run_id = ? AND season = ? AND fixture = 100 AND code = 1
            """,
            [run_id, SEASON],
        )
    finally:
        con.close()

    with pytest.raises(BiExportValidationError, match="referential-integrity"):
        export_bi(database, output, created_at=datetime(2026, 8, 26, tzinfo=UTC))

    assert (output / "manifest.json").read_bytes() == previous_manifest
    assert not list(tmp_path.glob(".published.*.tmp"))


def test_source_schema_drift_cleans_temporary_export_and_keeps_previous_publish(
    tmp_path: Path,
) -> None:
    database = tmp_path / "schema-drift.duckdb"
    _seed_database(database, record=False)
    output = tmp_path / "published"
    export_bi(database, output, created_at=datetime(2026, 8, 25, tzinfo=UTC))
    previous_manifest = (output / "manifest.json").read_bytes()

    con = connect(database)
    try:
        con.execute("ALTER TABLE mart_fact_player_fixture DROP COLUMN expected_goals")
    finally:
        con.close()

    with pytest.raises(BiExportSourceError, match="missing column"):
        export_bi(database, output, created_at=datetime(2026, 8, 26, tzinfo=UTC))

    assert (output / "manifest.json").read_bytes() == previous_manifest
    assert not list(tmp_path.glob(".published.*.tmp"))


def test_export_rejects_stale_forecast_provenance_without_publishing(tmp_path: Path) -> None:
    database = tmp_path / "stale.duckdb"
    _seed_database(database, record=True)

    with pytest.raises(BiExportFreshnessError, match="exceeding"):
        export_bi(
            database,
            tmp_path / "published",
            maximum_source_age=timedelta(hours=1),
        )
    assert not (tmp_path / "published").exists()
    assert not list(tmp_path.glob(".published.*.tmp"))


def test_optimizer_plan_must_resolve_to_an_exported_forecast_run(tmp_path: Path) -> None:
    database = tmp_path / "unresolved-plan.duckdb"
    artifact, _ = _seed_database(database, record=True)
    plan_path = tmp_path / "plan.json"
    write_optimizer_artifact_atomic(
        plan_path, _optimizer_artifact(artifact, forecast_sha256=HASH_C)
    )

    with pytest.raises(OptimizerPlanResolutionError, match="resolves to 0"):
        export_bi(database, tmp_path / "published", optimizer_plan_paths=(plan_path,))


def test_exports_are_byte_deterministic_except_manifest_created_at(tmp_path: Path) -> None:
    database = tmp_path / "repeatable.duckdb"
    artifact, _ = _seed_database(database, record=True)
    plan_path = _write_optimizer_plan(tmp_path / "plan.json", artifact)
    first = tmp_path / "first"
    second = tmp_path / "second"
    export_bi(
        database,
        first,
        optimizer_plan_paths=(plan_path,),
        created_at=datetime(2026, 8, 25, tzinfo=UTC),
    )
    export_bi(
        database,
        second,
        optimizer_plan_paths=(plan_path,),
        created_at=datetime(2026, 8, 26, tzinfo=UTC),
    )

    for table in SEMANTIC_CONTRACT_V1.tables:
        assert (first / f"{table.name}.parquet").read_bytes() == (
            second / f"{table.name}.parquet"
        ).read_bytes()
    first_manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
    second_manifest = json.loads((second / "manifest.json").read_text(encoding="utf-8"))
    assert first_manifest.pop("created_at") != second_manifest.pop("created_at")
    assert first_manifest == second_manifest


def test_concurrent_writer_is_refused_without_clobbering(tmp_path: Path) -> None:
    database = tmp_path / "concurrent.duckdb"
    _seed_database(database, record=False)
    output = tmp_path / "published"
    staged = Event()
    release = Event()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            export_bi,
            database,
            output,
            created_at=datetime(2026, 8, 25, tzinfo=UTC),
            before_publish=lambda: (staged.set(), release.wait(timeout=10)),
        )
        assert staged.wait(timeout=10)
        with pytest.raises(BiExportConcurrentWriterError, match="another writer"):
            export_bi(database, output, created_at=datetime(2026, 8, 26, tzinfo=UTC))
        release.set()
        future.result(timeout=10)

    assert validate_bi_export(output)["tables"]["dim_forecast_run"]["row_count"] == 0


def test_unmanaged_existing_directory_is_never_clobbered(tmp_path: Path) -> None:
    database = tmp_path / "unmanaged-target.duckdb"
    _seed_database(database, record=False)
    output = tmp_path / "published"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("operator-owned", encoding="utf-8")

    with pytest.raises(BiExportConcurrentWriterError, match="unmanaged"):
        export_bi(database, output)

    assert marker.read_text(encoding="utf-8") == "operator-owned"


def test_non_finite_source_float_is_rejected_before_publish(tmp_path: Path) -> None:
    database = tmp_path / "nan.duckdb"
    _seed_database(database, record=False)
    con = connect(database)
    try:
        con.execute("UPDATE mart_fact_player_fixture SET expected_assists = CAST('NaN' AS DOUBLE)")
    finally:
        con.close()

    with pytest.raises(BiExportValidationError, match="non-finite"):
        export_bi(database, tmp_path / "published")


def test_live_season_dimensions_are_sourced_from_the_snapshot_registry(tmp_path: Path) -> None:
    """A real deadline forecast is for the upcoming season, which the archive marts never cover.

    With no marts for the forecast season, referential integrity can only hold if the exporter
    unions the live-season players, clubs, fixtures and gameweeks in from the versioned live
    staging. Export success is exactly that proof.
    """
    database = tmp_path / "live-season.duckdb"
    _, run_id = _seed_live_database(database)

    output = tmp_path / "published"
    export_bi(database, output, created_at=datetime(2026, 8, 25, tzinfo=UTC))
    manifest = validate_bi_export(output)

    assert manifest["exported_run_ids"] == [run_id]
    assert manifest["tables"]["fact_forecast_player_gameweek"]["row_count"] == 15

    player_season = pq.read_table(output / "dim_player_season.parquet")
    assert player_season.num_rows == 15
    assert set(player_season.column("season").to_pylist()) == {SEASON}

    player = pq.read_table(output / "dim_player.parquet")
    assert set(player.column("code").to_pylist()) == set(range(1, 16))

    team_season = pq.read_table(output / "dim_team_season.parquet")
    assert set(
        zip(
            team_season.column("season").to_pylist(),
            team_season.column("team_id").to_pylist(),
            strict=True,
        )
    ) == {(SEASON, 1), (SEASON, 2)}
    assert set(team_season.column("team_code").to_pylist()) == {101, 102}

    fixture = pq.read_table(output / "dim_fixture.parquet")
    assert fixture.column("home_team_code").to_pylist() == [101]
    assert fixture.column("away_team_code").to_pylist() == [102]

    gameweek = pq.read_table(output / "dim_gameweek.parquet")
    assert (gameweek.column("season").to_pylist(), gameweek.column("gw").to_pylist()) == (
        [SEASON],
        [1],
    )
    team_fixture = pq.read_table(output / "fact_forecast_team_fixture.parquet")
    assert team_fixture.column("official_fdr").to_pylist() == [2, 4]


@pytest.mark.archive
def test_archive_database_exports_the_complete_contract(tmp_path: Path) -> None:
    """Real-build smoke test: all source owners can satisfy the frozen 14-table boundary."""
    result = export_bi(default_db_path(), tmp_path / "archive-export")
    manifest = validate_bi_export(result.output_dir)

    assert set(manifest["tables"]) == {table.name for table in SEMANTIC_CONTRACT_V1.tables}
    assert len(_table_paths(result.output_dir)) == 14
    team_fixture = pq.read_table(result.output_dir / "fact_forecast_team_fixture.parquet")
    assert {
        "lambda_for",
        "lambda_against",
        "league_average_team_lambda",
        "attack_ease_index",
        "defence_ease_index",
        "overall_ease_index",
        "ease_index_formula_version",
        "official_fdr",
    } <= set(team_fixture.column_names)
    assert team_fixture.column("ease_index_formula_version").null_count == 0
