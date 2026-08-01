"""In-memory integration test for the Stage C attacking assists harness.

No disk database, no network. Builds a tiny ``mart_fact_player_fixture`` in an in-memory DuckDB
(with assists / expected_assists / creativity columns) and runs the real harness baseline-only,
asserting the two assists baselines are scored on identical rows and the fold/population
machinery mirrors the goals harness.
"""

from __future__ import annotations

import duckdb

from fpl.config import load_phase3_stage_c_assists_evaluation
from fpl.validate.attacking_assists_harness import run_assists_harness


def _make_assists_db(xa_from_gw: int) -> duckdb.DuckDBPyConnection:
    """A tiny archive: one season, GW1..GW10, ~4 players/gw. xA is NULL before ``xa_from_gw``."""
    con = duckdb.connect(":memory:")
    con.execute(
        """
        CREATE TABLE mart_fact_player_fixture (
            season VARCHAR, gw INTEGER, fixture INTEGER, kickoff_time TIMESTAMP,
            code INTEGER, position VARCHAR, team_id INTEGER, opponent_team_id INTEGER,
            was_home BOOLEAN, minutes INTEGER, assists INTEGER,
            expected_assists DOUBLE, creativity DOUBLE
        )
        """
    )
    rows = []
    for gw in range(1, 11):
        day = 1 + gw
        kick = f"2023-08-{day:02d}T15:00:00"
        xa = None if gw < xa_from_gw else round(0.05 * gw, 3)
        creativity = round(2.0 * gw, 3)  # creativity is 100% covered
        rows.append(("2023-24", gw, gw, kick, 111, "FWD", 1, 2, True, 90, gw % 3, xa, creativity))
        rows.append(("2023-24", gw, gw, kick, 112, "FWD", 1, 2, False, 90, gw % 4, xa, creativity))
        rows.append(("2023-24", gw, gw, kick, 211, "MID", 3, 4, True, 90, gw % 2, xa, creativity))
        rows.append(("2023-24", gw, gw, kick, 311, "DEF", 5, 6, False, 90, 0, xa, creativity))
    con.executemany(
        "INSERT INTO mart_fact_player_fixture VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    return con


def test_assists_baselines_score_identical_rows_and_population() -> None:
    load_phase3_stage_c_assists_evaluation.cache_clear()
    config = load_phase3_stage_c_assists_evaluation()
    con = _make_assists_db(xa_from_gw=1)  # xA measured everywhere (baselines ignore it)
    try:
        result = run_assists_harness(con, config=config)
    finally:
        con.close()

    assert result.leakage_failures == 0
    # minimum_observed_gameweeks=8 over one 10-GW season => scoring folds GW9, GW10.
    assert sum(result.folds_by_season.values()) == 2
    # Baseline-only path: no candidate.
    assert result.candidate_names == ()
    # Both baselines scored the same number of rows.
    counts = {name: rep.predictions for name, rep in result.overall.items()}
    assert len(set(counts.values())) == 1
    # The comparator is the best required baseline by mean log score.
    assert result.best_baseline_name in {
        "positional_assist_rate_poisson",
        "trailing_player_assist_rate_poisson",
    }


def test_assists_harness_xa_absent_is_handled_by_baselines() -> None:
    """Where xA is NULL everywhere the baselines still score every eligible row (they ignore xA)."""
    load_phase3_stage_c_assists_evaluation.cache_clear()
    config = load_phase3_stage_c_assists_evaluation()
    con = _make_assists_db(xa_from_gw=99)  # xA NULL everywhere
    try:
        result = run_assists_harness(con, config=config)
    finally:
        con.close()

    assert result.leakage_failures == 0
    assert result.total_predictions > 0
    # Full coverage: every eligible row scored by both baselines.
    for name in result.baseline_names:
        assert result.overall[name].predictions == result.total_predictions
