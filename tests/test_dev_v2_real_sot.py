"""Runner-level guards for the write-once retrospective real-SOT experiment."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import polars as pl
import pytest

from fpl.config import load_v2_real_sot_retrospective_evaluation, repo_root
from fpl.features.pit import PointInTimeView
from fpl.storage.db import initialise
from fpl.validate import dev_v2_real_sot as runner
from fpl.validate.retrospective_sdp import RetrospectiveBackfillView

START = datetime(2023, 8, 12, 14, 0, tzinfo=UTC)
CAPTURED = datetime(2026, 9, 5, tzinfo=UTC)


def _seed_season(con: duckdb.DuckDBPyConnection, *, weeks: int = 9, sot: bool = True) -> None:
    for team_id, team_code, name in ((1, 101, "Home"), (2, 202, "Away")):
        con.execute(
            """
            INSERT INTO mart_dim_team (season, team_id, team_code, team_name, short_name)
            VALUES ('2023-24', ?, ?, ?, ?)
            """,
            [team_id, team_code, name, name[:3].upper()],
        )
    for week in range(1, weeks + 1):
        fixture = 1000 + week
        match_id = 9000 + week
        kickoff = START + timedelta(days=7 * (week - 1))
        home_code, away_code = (101, 202) if week % 2 else (202, 101)
        for team_id, team_code, opponent_id, opponent_code, was_home, goals, xg in (
            (
                1 if home_code == 101 else 2,
                home_code,
                2 if home_code == 101 else 1,
                away_code,
                True,
                2 if home_code == 101 else 1,
                1.6,
            ),
            (
                2 if away_code == 202 else 1,
                away_code,
                1 if away_code == 202 else 2,
                home_code,
                False,
                1 if away_code == 202 else 2,
                0.9,
            ),
        ):
            con.execute(
                """
                INSERT INTO mart_fact_team_match_stats_v2 (
                    season, gw, fixture, pulse_id, kickoff_time, team_id, team_code,
                    opponent_team_id, opponent_team_code, was_home, provider, known_at,
                    goals, goals_allowed, expected_goals, expected_goals_allowed,
                    expected_goals_conceded_measured
                ) VALUES ('2023-24', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'fpl_archive', ?,
                          ?, ?, ?, ?, ?)
                """,
                [
                    week,
                    fixture,
                    7000 + week,
                    kickoff,
                    team_id,
                    team_code,
                    opponent_id,
                    opponent_code,
                    was_home,
                    kickoff,
                    goals,
                    3 - goals,
                    xg,
                    2.5 - xg,
                    2.5 - xg,
                ],
            )
        con.execute(
            """
            INSERT INTO stg_pl_sdp_fixture_crosswalk (
                season, fixture, sdp_match_id, match_method, pulse_id,
                corroborated_kickoff, corroborated_teams, corroborated_score, resolved_at
            ) VALUES ('2023-24', ?, ?, 'kickoff_teams_score', ?, TRUE, TRUE, TRUE, ?)
            """,
            [fixture, match_id, 7000 + week, CAPTURED],
        )
        payload_id = f"capture-{week:02d}"
        con.execute(
            """
            INSERT INTO raw_pl_sdp_payload (
                payload_id, provider, endpoint, request_path, params_json, season,
                sdp_match_id, fetched_at, status_code, payload, sha256, byte_count
            ) VALUES (?, 'pl_sdp', 'match_stats', '/stats', '{}', '2023-24', ?, ?,
                      200, '{}', ?, 2)
            """,
            [payload_id, match_id, CAPTURED + timedelta(seconds=week), "a" * 64],
        )
        for side, team_code, value in (
            ("home", home_code, float(week + 2)),
            ("away", away_code, float(week + 1)),
        ):
            con.execute(
                """
                INSERT INTO stg_pl_sdp_team_match_stats (
                    sdp_match_id, side, payload_id, known_at, sdp_team_id, team_name,
                    stats_json, metric_count, mapped_count
                ) VALUES (?, ?, ?, ?, ?, ?, '{}', 2, 1)
                """,
                [match_id, side, payload_id, CAPTURED + timedelta(seconds=week), team_code, side],
            )
            con.execute(
                """
                INSERT INTO stg_pl_sdp_team_match_metric (
                    sdp_match_id, side, payload_id, provider_field, local_field,
                    value_numeric, value_text
                ) VALUES (?, ?, ?, 'totalScoringAtt', NULL, ?, NULL)
                """,
                [match_id, side, payload_id, value + 4.0],
            )
            con.execute(
                """
                INSERT INTO stg_pl_sdp_team_match_metric (
                    sdp_match_id, side, payload_id, provider_field, local_field,
                    value_numeric, value_text
                ) VALUES (?, ?, ?, 'ontargetScoringAtt', 'shots_on_target', ?, NULL)
                """,
                [match_id, side, payload_id, value if sot else None],
            )


def _add_second_target_fixture(con: duckdb.DuckDBPyConnection) -> None:
    kickoff = START + timedelta(days=8 * 7, hours=1)
    for team_id, team_code, name in ((3, 303, "Third"), (4, 404, "Fourth")):
        con.execute(
            """
            INSERT INTO mart_dim_team (season, team_id, team_code, team_name, short_name)
            VALUES ('2023-24', ?, ?, ?, ?)
            """,
            [team_id, team_code, name, name[:3].upper()],
        )
    for team_id, team_code, opponent_id, opponent_code, was_home, goals, xg in (
        (3, 303, 4, 404, True, 0, 0.7),
        (4, 404, 3, 303, False, 1, 1.1),
    ):
        con.execute(
            """
            INSERT INTO mart_fact_team_match_stats_v2 (
                season, gw, fixture, pulse_id, kickoff_time, team_id, team_code,
                opponent_team_id, opponent_team_code, was_home, provider, known_at,
                goals, goals_allowed, expected_goals, expected_goals_allowed,
                expected_goals_conceded_measured
            ) VALUES ('2023-24', 9, 2009, 8009, ?, ?, ?, ?, ?, ?, 'fpl_archive', ?,
                      ?, ?, ?, ?, ?)
            """,
            [
                kickoff,
                team_id,
                team_code,
                opponent_id,
                opponent_code,
                was_home,
                kickoff,
                goals,
                1 - goals,
                xg,
                1.8 - xg,
                1.8 - xg,
            ],
        )


@pytest.fixture
def con() -> duckdb.DuckDBPyConnection:
    connection = initialise(":memory:")
    _seed_season(connection)
    yield connection
    connection.close()


def test_formal_runner_predicts_target_gameweek_as_one_pre_gameweek_batch(
    con: duckdb.DuckDBPyConnection,
) -> None:
    _add_second_target_fixture(con)
    contract = load_v2_real_sot_retrospective_evaluation()
    blocks, slices, folds, guards = runner.run_walk_forward(con, contract)

    assert len(folds) == 1
    assert folds[0]["season"] == "2023-24" and folds[0]["gw"] == 9
    assert folds[0]["retrospective_rows"] == 16  # GW9's two sides are excluded.
    assert folds[0]["retrospective_sot_non_null"] == 16
    assert guards == {
        "event_time_violations": 0,
        "same_gameweek_overlap": 0,
        "identity_violations": 0,
    }
    assert {name: len(rows) for name, rows in blocks.items()} == {
        contract.baseline: 4,
        contract.control.name: 4,
        contract.candidate.name: 4,
    }
    assert {row.key.split(":")[1] for row in blocks[contract.candidate.name]} == {"1009", "2009"}
    assert set(slices) == {row.key for row in blocks[contract.candidate.name]}
    assert {row.sot_history_band for row in slices.values()} == {"0", "6+"}
    assert all(
        sum(prediction.distribution) == pytest.approx(1.0, abs=1e-9)
        for rows in blocks.values()
        for prediction in rows
    )


def test_walk_forward_is_deterministic(con: duckdb.DuckDBPyConnection) -> None:
    contract = load_v2_real_sot_retrospective_evaluation()
    first = runner.run_walk_forward(con, contract)
    second = runner.run_walk_forward(con, contract)
    assert first == second


def test_post_cutoff_extremes_cannot_change_fold_local_sot_fit_or_predictions() -> None:
    before = initialise(":memory:")
    after = initialise(":memory:")
    try:
        _seed_season(before, weeks=9)
        _seed_season(after, weeks=10)
        after.execute(
            """
            UPDATE mart_fact_team_match_stats_v2
            SET goals = 90, goals_allowed = 80, expected_goals = 70,
                expected_goals_allowed = 60, expected_goals_conceded_measured = 60
            WHERE season = '2023-24' AND gw = 10
            """
        )
        after.execute(
            """
            UPDATE stg_pl_sdp_team_match_metric
            SET value_numeric = 9999
            WHERE sdp_match_id = 9010 AND provider_field = 'ontargetScoringAtt'
            """
        )
        contract = load_v2_real_sot_retrospective_evaluation()
        before_blocks, _, before_folds, _ = runner.run_walk_forward(before, contract)
        after_blocks, _, after_folds, _ = runner.run_walk_forward(after, contract)

        assert before_folds[0]["candidate_parameters"] == after_folds[0]["candidate_parameters"]
        assert before_folds[0]["candidate_signal_fit"] == after_folds[0]["candidate_signal_fit"]
        sot_fit = before_folds[0]["candidate_signal_fit"]["shots_on_target"]
        assert sot_fit["goal_scale"] == pytest.approx(0.25)
        for name in (contract.baseline, contract.control.name, contract.candidate.name):
            expected = [row for row in before_blocks[name] if ":1009:" in row.key]
            actual = [row for row in after_blocks[name] if ":1009:" in row.key]
            assert actual == expected
    finally:
        before.close()
        after.close()


def test_coverage_eligibility_is_derived_only_from_frozen_joint_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seasons = ("2022-23", "2023-24", "2024-25")
    available = {"2022-23": 18, "2023-24": 19, "2024-25": 20}
    archive_rows: list[dict[str, object]] = []
    history_rows: list[dict[str, object]] = []
    for season_index, season in enumerate(seasons):
        for index in range(20):
            fixture = season_index * 100 + index
            kickoff = START + timedelta(days=fixture)
            archive_rows.append(
                {
                    "season": season,
                    "fixture": fixture,
                    "team_code": 100 + index,
                    "kickoff_time": kickoff,
                    "goals": 1,
                    "expected_goals": 1.0,
                    "shots_on_target": None,
                }
            )
            history_rows.append(
                {
                    "season": season,
                    "fixture": fixture,
                    "team_code": 100 + index,
                    "kickoff_time": kickoff,
                    "shots_on_target": 3 if index < available[season] else None,
                    "sdp_match_id": 10_000 + fixture,
                    "capture_id": f"capture-{fixture}",
                    "source_known_at": CAPTURED + timedelta(seconds=fixture),
                    "payload_sha256": f"{fixture:064x}",
                }
            )
    archive = pl.DataFrame(archive_rows)
    history = pl.DataFrame(history_rows)
    monkeypatch.setattr(runner, "load_team_frame", lambda *_args, **_kwargs: archive)
    monkeypatch.setattr(
        RetrospectiveBackfillView,
        "observed_real_sot",
        lambda _self, *, seasons=None: history,
    )
    contract = load_v2_real_sot_retrospective_evaluation()
    population = contract.population.model_copy(update={"eligible_seasons": ("2023-24", "2024-25")})
    contract = contract.model_copy(update={"population": population})
    memory = initialise(":memory:")
    try:
        report, _ = runner.build_coverage_evidence(memory, contract)
    finally:
        memory.close()

    assert report["eligible_seasons"] == ["2023-24", "2024-25"]
    measured = report["seasons"]
    assert measured["2022-23"]["joint_coverage"] == 0.9
    assert measured["2022-23"]["eligible"] is False
    assert measured["2023-24"]["joint_coverage"] == 0.95
    assert measured["2023-24"]["eligible"] is True


def test_unavailable_sot_reduces_candidate_to_control() -> None:
    con = initialise(":memory:")
    try:
        _seed_season(con, sot=False)
        contract = load_v2_real_sot_retrospective_evaluation()
        blocks, _, folds, _ = runner.run_walk_forward(con, contract)
        control = blocks[contract.control.name]
        candidate = blocks[contract.candidate.name]
        assert [row.distribution for row in candidate] == [row.distribution for row in control]
        assert folds[0]["candidate_parameters"]["rejected_shots_on_target"] == "no measured rows"
    finally:
        con.close()


def test_sot_history_bins_are_frozen() -> None:
    labels = ("0", "1-2", "3-5", "6+")
    assert [runner._sot_history_band(value, labels) for value in (0, 1, 2, 3, 5, 6, 50)] == [
        "0",
        "1-2",
        "1-2",
        "3-5",
        "3-5",
        "6+",
        "6+",
    ]


def test_singleton_slice_is_strict_json_serialisable() -> None:
    from fpl.validate.metrics import poisson_pmf
    from fpl.validate.v2_environment_harness import Prediction

    block = runner._score_block(
        "singleton",
        [
            Prediction(
                season="2023-24",
                gw=1,
                key="one",
                distribution=poisson_pmf(1.0),
                observed=1,
                was_home=True,
            )
        ],
        seed=1,
    )
    assert block["spearman_within_gameweek"] is None
    assert runner._json_bytes(block)


def test_dirty_worktree_is_a_hard_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "_git", lambda _repo, *_args: " M candidate.py")
    with pytest.raises(runner.RetrospectiveEvaluationError, match="dirty worktree"):
        runner.require_clean_worktree(Path("."))


def test_formal_result_is_write_once(tmp_path: Path) -> None:
    (tmp_path / runner.RESULT_FILE).write_text("already scored", encoding="utf-8")
    with pytest.raises(runner.RetrospectiveEvaluationError, match="write-once"):
        runner.run_formal_evaluation(
            db_path=tmp_path / "missing.duckdb",
            results_dir=tmp_path,
            contract_path=tmp_path / "missing.yaml",
        )


@pytest.mark.parametrize(
    ("changed", "message"),
    [
        ("config", "config changed"),
        ("database", "database changed"),
        ("coverage", "coverage report changed"),
        ("manifest", "capture manifest changed"),
        ("source", "source changed"),
    ],
)
def test_final_snapshot_rejects_mutation_before_result_emission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed: str,
    message: str,
) -> None:
    paths = {
        name: tmp_path / filename
        for name, filename in (
            ("config", "contract.yaml"),
            ("database", "archive.duckdb"),
            ("coverage", "coverage.json"),
            ("manifest", "manifest.json"),
            ("source", "candidate.py"),
        )
    }
    for name, path in paths.items():
        path.write_text(name, encoding="utf-8")
    snapshot = runner.ProvenanceSnapshot(
        head="frozen-head",
        config_sha256=runner.file_sha256(paths["config"]),
        database_sha256=runner.file_sha256(paths["database"]),
        coverage_report_sha256=runner.file_sha256(paths["coverage"]),
        capture_manifest_sha256=runner.file_sha256(paths["manifest"]),
        source_sha256={"candidate.py": runner.file_sha256(paths["source"])},
        frozen_v2_result_sha256="frozen-result",
        started_at_utc="2026-09-05T00:00:00+00:00",
    )
    monkeypatch.setattr(runner, "require_clean_worktree", lambda _root: None)
    monkeypatch.setattr(runner, "_git", lambda _root, *_args: "frozen-head")
    paths[changed].write_text("mutated", encoding="utf-8")

    with pytest.raises(runner.RetrospectiveEvaluationError, match=message):
        runner._verify_snapshot(
            snapshot,
            root=tmp_path,
            db_path=paths["database"],
            config_path=paths["config"],
            coverage_path=paths["coverage"],
            manifest_path=paths["manifest"],
        )


def test_retrospective_capability_is_not_available_to_production_modules() -> None:
    assert not issubclass(RetrospectiveBackfillView, PointInTimeView)
    production = repo_root() / "src" / "fpl"
    offenders = []
    for path in production.rglob("*.py"):
        if "validate" in path.relative_to(production).parts:
            continue
        if "retrospective_sdp" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(repo_root())))
    assert offenders == []


def test_frozen_previous_v2_result_is_byte_immutable() -> None:
    result = repo_root() / "results" / runner.FROZEN_V2_RESULT
    assert runner.file_sha256(result) == runner.FROZEN_V2_RESULT_SHA256
