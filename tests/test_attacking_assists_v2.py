"""Offline tests for Stage C assists Candidate V2 (exposure-weighted xA team-share assists).

No network. Mirrors ``test_attacking_v4.py`` for the assists label against a tiny in-memory DuckDB
that carries the assists columns (``assists``, ``expected_assists``, ``goals_scored``). The shared
exposure primitives are covered in ``test_attacking_exposure.py``; here we exercise the Stage A
coupling, the fold-local assist rate, per-fixture underlying Poisson-rate conservation against
``lambda_team * assist_rate``, identical comparator/candidate rows, the position-specific cold-start
path, and the reduces-to-baseline fallback.
"""

from __future__ import annotations

import math
from collections import defaultdict

import duckdb

from fpl.config import load_phase2_evaluation, load_phase3_stage_c_assists_evaluation
from fpl.models.attacking_assists_v2 import (
    PATH_EXPOSURE_COLD_START,
    PATH_EXPOSURE_WEIGHTED,
    ExposureWeightedXaTeamShareAssistsV2,
)
from fpl.models.attacking_baselines import TargetRowProjection
from fpl.types import Position
from fpl.validate.attacking_assists_harness import run_assists_harness
from fpl.validate.minutes_baselines import MinuteBins

NAME = "exposure_weighted_xa_team_share_assists_v2"


def _build_assists_db(*, with_team_match: bool) -> duckdb.DuckDBPyConnection:
    """Tiny assists archive: 2023-24 GW1..GW10 with assists/xA/goals + team matches + codes."""
    con = duckdb.connect(":memory:")
    con.execute(
        """
        CREATE TABLE mart_fact_player_fixture (
            season VARCHAR, gw INTEGER, fixture INTEGER, kickoff_time TIMESTAMP,
            code INTEGER, position VARCHAR, team_id INTEGER, opponent_team_id INTEGER,
            was_home BOOLEAN, minutes INTEGER, goals_scored INTEGER, assists INTEGER,
            expected_assists DOUBLE, creativity DOUBLE
        )
        """
    )
    con.execute(
        """
        CREATE TABLE mart_fact_team_match (
            season VARCHAR, gw INTEGER, fixture INTEGER, kickoff_time TIMESTAMP,
            team_id INTEGER, opponent_team_id INTEGER, was_home BOOLEAN,
            goals_for INTEGER, goals_against INTEGER
        )
        """
    )
    con.execute(
        "CREATE TABLE mart_dim_team ("
        "season VARCHAR, team_id INTEGER, team_code INTEGER, name VARCHAR)"
    )
    for team_id, code in [(1, 11), (2, 22), (3, 33), (4, 44)]:
        con.execute("INSERT INTO mart_dim_team VALUES ('2023-24', ?, ?, 'club')", [team_id, code])
    rows = []
    for gw in range(1, 11):
        day = 1 + gw
        kick = f"2023-08-{day:02d}T15:00:00"
        xa = round(0.05 * gw, 3)  # xA measured everywhere (2023-24 covered)
        goals = gw % 4
        assists = gw % 3
        rows.append(("2023-24", gw, gw, kick, 111, "FWD", 1, 2, True, 90, goals, assists, xa, 10.0))
        rows.append(("2023-24", gw, gw, kick, 112, "FWD", 1, 2, True, 60, goals, assists, xa, 10.0))
        # 113 is a DNP prior row at minutes=0 for GW<=8 (must NOT dilute the appeared xA rate).
        rows.append(
            ("2023-24", gw, gw, kick, 113, "FWD", 1, 2, True, 0 if gw < 9 else 30, 0, 0, xa, 10.0)
        )
        rows.append(("2023-24", gw, gw, kick, 211, "MID", 3, 4, True, 90, goals, assists, xa, 10.0))
        rows.append(
            ("2023-24", gw, gw, kick, 311, "DEF", 4, 3, False, 90, goals, assists, xa, 10.0)
        )
    con.executemany(
        "INSERT INTO mart_fact_player_fixture VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    if with_team_match:
        matches = []
        for gw in range(1, 9):
            day = 1 + gw
            kick = f"2023-08-{day:02d}T15:00:00"
            gf = gw % 4
            matches.append(("2023-24", gw, gw, kick, 1, 2, True, gf, (gf + 1) % 4))
            matches.append(("2023-24", gw, gw, kick, 2, 1, False, (gf + 1) % 4, gf))
            matches.append(("2023-24", gw, gw, kick, 3, 4, True, gf, (gf + 2) % 4))
            matches.append(("2023-24", gw, gw, kick, 4, 3, False, (gf + 2) % 4, gf))
        con.executemany(
            "INSERT INTO mart_fact_team_match VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", matches
        )
    return con


def _v2_factory(history: object) -> ExposureWeightedXaTeamShareAssistsV2:
    config = load_phase3_stage_c_assists_evaluation()
    bins = MinuteBins.from_config(load_phase2_evaluation())
    policy = config.stage_c_assists_candidate_v2
    assert policy is not None
    model = ExposureWeightedXaTeamShareAssistsV2(
        alpha=policy.alpha,
        share_window=policy.history_window,
        bins=bins,
        prior_minutes=policy.prior_minutes,
    )
    model.fit(list(history))  # type: ignore[arg-type]
    return model


def test_candidate_v2_scored_on_identical_rows_with_exposure_paths() -> None:
    load_phase3_stage_c_assists_evaluation.cache_clear()
    config = load_phase3_stage_c_assists_evaluation()
    con = _build_assists_db(with_team_match=True)
    try:
        result = run_assists_harness(con, config=config, candidate_factory=_v2_factory)
    finally:
        con.close()

    assert result.leakage_failures == 0
    assert NAME in result.overall
    counts = {n: rep.predictions for n, rep in result.overall.items()}
    assert len(set(counts.values())) == 1  # identical eligible rows across all models
    paths = result.candidate_path_counts[NAME]
    assert paths.get("stage_a_uninformative_trailing", 0) == 0
    assert (paths.get(PATH_EXPOSURE_WEIGHTED, 0) + paths.get(PATH_EXPOSURE_COLD_START, 0)) > 0


def test_candidate_v2_reduces_to_baseline_when_stage_a_uninformative() -> None:
    load_phase3_stage_c_assists_evaluation.cache_clear()
    config = load_phase3_stage_c_assists_evaluation()
    con = _build_assists_db(with_team_match=False)
    try:
        result = run_assists_harness(con, config=config, candidate_factory=_v2_factory)
    finally:
        con.close()

    paths = result.candidate_path_counts[NAME]
    assert paths.get("stage_a_uninformative_trailing", 0) > 0
    cand = result.overall[NAME]
    base = result.overall["trailing_player_assist_rate_poisson"]
    assert cand.mean_log_score == base.mean_log_score


def test_candidate_v2_parameters_report_pinned_constants() -> None:
    config = load_phase3_stage_c_assists_evaluation()
    policy = config.stage_c_assists_candidate_v2
    assert policy is not None
    model = ExposureWeightedXaTeamShareAssistsV2(
        alpha=policy.alpha,
        share_window=policy.history_window,
        bins=MinuteBins.from_config(load_phase2_evaluation()),
        prior_minutes=policy.prior_minutes,
    )
    params = model.parameters()
    assert params["alpha"] == 5.0
    assert params["prior_minutes"] == 90.0
    assert params["signal"] == "expected_assists_only_no_fallback"
    assert params["team_assist_scale"] == "lambda_team_times_fold_local_assist_rate"
    assert model.name == NAME


def _gw9_targets(con: object) -> tuple[list[TargetRowProjection], str]:
    target_df = con.execute(  # type: ignore[attr-defined]
        """
        SELECT season, gw, fixture,
               strftime(kickoff_time, '%Y-%m-%dT%H:%M:%SZ') AS kickoff_time,
               code, position, team_id, opponent_team_id, was_home
        FROM mart_fact_player_fixture
        WHERE minutes IS NOT NULL AND season = '2023-24' AND gw = 9
        ORDER BY kickoff_time, fixture, code
        """
    ).pl()
    targets = [
        TargetRowProjection(
            season=r["season"],
            gw=r["gw"],
            fixture=r["fixture"],
            kickoff_time=r["kickoff_time"],
            code=r["code"],
            position=Position.from_archive_label(r["position"]),
            team_id=r["team_id"],
            opponent_team_id=r["opponent_team_id"],
            was_home=bool(r["was_home"]),
        )
        for r in target_df.iter_rows(named=True)
    ]
    as_of = con.execute(  # type: ignore[attr-defined]
        "SELECT strftime(MIN(kickoff_time), '%Y-%m-%dT%H:%M:%SZ') AS as_of "
        "FROM mart_fact_player_fixture WHERE minutes IS NOT NULL AND season = '2023-24' AND gw = 9"
    ).fetchone()[0]
    return targets, str(as_of)


def test_v2_underlying_poisson_rate_conservation_per_fixture() -> None:
    """For each roster, sum_i assist_lambda_i == lambda_team * fold_local_assist_rate."""
    load_phase3_stage_c_assists_evaluation.cache_clear()
    config = load_phase3_stage_c_assists_evaluation()
    bins = MinuteBins.from_config(load_phase2_evaluation())
    policy = config.stage_c_assists_candidate_v2
    assert policy is not None
    con = _build_assists_db(with_team_match=True)
    try:
        targets, as_of = _gw9_targets(con)
        model = ExposureWeightedXaTeamShareAssistsV2(
            alpha=policy.alpha,
            share_window=policy.history_window,
            bins=bins,
            prior_minutes=policy.prior_minutes,
        )
        model.fit([])
        model.prepare(targets=targets, con=con, as_of=as_of)  # type: ignore[arg-type]

        _, _, assist_rate, _, _ = model._fold_history(con, as_of)  # type: ignore[attr-defined]
        team_code_map = model._team_code_map(con, "2023-24")  # type: ignore[attr-defined]
        stage_a, informative = model._fit_stage_a(con, as_of)  # type: ignore[attr-defined]
        assert informative

        by_team: dict[tuple[int, int], list[TargetRowProjection]] = defaultdict(list)
        for target in targets:
            team_code = team_code_map.get(target.team_id, -1)
            by_team[(target.fixture, team_code)].append(target)

        for (fixture, team_code), roster in by_team.items():
            if team_code < 0:
                continue
            opponent_code = team_code_map.get(roster[0].opponent_team_id, team_code)
            lambda_team = float(
                stage_a.rate_for(
                    {
                        "team_code": team_code,
                        "opponent_team_code": opponent_code,
                        "was_home": roster[0].was_home,
                    }
                )
            )
            team_assist_lambda = lambda_team * assist_rate
            total = math.fsum(model._rates[(t.fixture, t.code)] for t in roster)  # type: ignore[attr-defined]
            assert math.isclose(total, team_assist_lambda, rel_tol=1e-9, abs_tol=1e-12), (
                f"fixture {fixture} team_code {team_code}: assist rates sum {total} != "
                f"team_assist_lambda {team_assist_lambda}"
            )
    finally:
        con.close()
