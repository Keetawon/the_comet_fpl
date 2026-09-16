"""In-memory integration test for the Stage C candidate factory wiring.

No disk database, no network. Builds a tiny ``mart_fact_player_fixture`` in an in-memory DuckDB and
runs the real harness with a Candidate V1 factory, asserting the candidate is scored on identical
rows, the path split is tallied, and the candidate reduces to the baseline where xG is absent.
"""

from __future__ import annotations

import duckdb

from fpl.config import load_phase3_evaluation
from fpl.models.attacking_v1 import (
    PATH_FALLBACK_V1,
    PATH_XG_INFORMED,
    XgInformedTrailingPlayerGoalsV1,
)
from fpl.validate.attacking_harness import run_attacking_harness


def _make_db(xg_from_gw: int) -> duckdb.DuckDBPyConnection:
    """A tiny archive: one season, GW1..GW10, ~4 players/gw. xG is NULL before ``xg_from_gw``."""
    con = duckdb.connect(":memory:")
    con.execute(
        """
        CREATE TABLE mart_fact_player_fixture (
            season VARCHAR, gw INTEGER, fixture INTEGER, kickoff_time TIMESTAMP,
            code INTEGER, position VARCHAR, team_id INTEGER, opponent_team_id INTEGER,
            was_home BOOLEAN, minutes INTEGER, goals_scored INTEGER, expected_goals DOUBLE
        )
        """
    )
    rows = []
    # Two FWD codes (111 has xG-relevant history), plus a MID and a DEF for positional means.
    for gw in range(1, 11):
        day = 1 + gw
        kick = f"2023-08-{day:02d}T15:00:00"
        xg = None if gw < xg_from_gw else round(0.1 * gw, 3)
        rows.append(("2023-24", gw, gw, kick, 111, "FWD", 1, 2, True, 90, gw % 3, xg))
        rows.append(("2023-24", gw, gw, kick, 112, "FWD", 1, 2, False, 90, gw % 4, xg))
        rows.append(("2023-24", gw, gw, kick, 211, "MID", 3, 4, True, 90, gw % 2, xg))
        rows.append(("2023-24", gw, gw, kick, 311, "DEF", 5, 6, False, 90, 0, xg))
    con.executemany(
        "INSERT INTO mart_fact_player_fixture VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    return con


def _factory(history):  # type: ignore[no-untyped-def]
    model = XgInformedTrailingPlayerGoalsV1(alpha=5.0, finishing_keep=0.05)
    model.fit(list(history))
    return model


def test_candidate_scored_on_identical_rows_with_path_split() -> None:
    load_phase3_evaluation.cache_clear()
    config = load_phase3_evaluation()
    con = _make_db(xg_from_gw=1)  # xG measured everywhere
    try:
        result = run_attacking_harness(con, config=config, candidate_factory=_factory)
    finally:
        con.close()

    assert result.leakage_failures == 0
    # minimum_observed_gameweeks=8 over one 10-GW season => scoring folds GW9, GW10.
    assert sum(result.folds_by_season.values()) == 2
    assert "xg_informed_trailing_player_goals_v1" in result.overall
    # Candidate and both baselines scored the same number of rows.
    counts = {name: rep.predictions for name, rep in result.overall.items()}
    assert len(set(counts.values())) == 1
    # xG measured everywhere in this fixture => every non-cold prediction is xG-informed.
    paths = result.candidate_path_counts["xg_informed_trailing_player_goals_v1"]
    assert paths.get(PATH_XG_INFORMED, 0) + paths.get(PATH_FALLBACK_V1, 0) > 0
    assert PATH_XG_INFORMED in paths


def test_candidate_reduces_to_baseline_when_no_xg_in_fold() -> None:
    """When no prior row carries xG, every prediction falls back / cold-starts (never xG)."""
    load_phase3_evaluation.cache_clear()
    config = load_phase3_evaluation()
    con = _make_db(xg_from_gw=99)  # xG NULL everywhere
    try:
        result = run_attacking_harness(con, config=config, candidate_factory=_factory)
    finally:
        con.close()

    cand_name = "xg_informed_trailing_player_goals_v1"
    paths = result.candidate_path_counts[cand_name]
    assert paths.get(PATH_XG_INFORMED, 0) == 0
    # And the candidate's overall log score equals the trailing baseline's, bit-for-bit.
    cand = result.overall[cand_name]
    base = result.overall["trailing_player_goal_rate_poisson"]
    assert cand.mean_log_score == base.mean_log_score
    assert cand.mean_ranked_probability_score == base.mean_ranked_probability_score
