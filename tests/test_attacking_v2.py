"""Offline tests for Stage C Candidate V2 (coupled team-share attacking goals).

No network. The pure allocation/signal logic is tested without a database (tiny synthetic inputs);
the Stage A coupling, share normalisation wiring, season-scoped team_code resolution, and the
reduces-to-baseline fallback are exercised against a tiny in-memory DuckDB.
"""

from __future__ import annotations

import math

import duckdb

from fpl.config import load_phase3_evaluation
from fpl.models.attacking_baselines import (
    PlayerHistoryRow,
    TargetRowProjection,
    TrailingPlayerGoalRateBaseline,
    poisson_pmf,
)
from fpl.models.attacking_v2 import (
    PATH_COLD_START_SHARE,
    PATH_COUPLED,
    PATH_EQUAL_SHARE,
    PATH_STAGE_A_FALLBACK,
    CoupledTeamShareAttackingGoalsV2,
    _RosterEntry,
    allocate_coupled_rates,
    mean_trailing_signal,
    season_signal_kind,
)
from fpl.types import Position
from fpl.validate.attacking_harness import run_attacking_harness

_XG_COVERED = frozenset({"2023-24", "2024-24", "2025-26"})


# --------------------------------------------------------------------------------------
# Pure allocation: Poisson thinning identity + share normalisation
# --------------------------------------------------------------------------------------


def test_poisson_thinning_identity_rates_sum_to_lambda() -> None:
    """sum_i rate_i == lambda_team (structural conservation on the coupled path)."""
    roster = [
        _RosterEntry(1, 1.0, cold_start=False),
        _RosterEntry(2, 3.0, cold_start=False),
        _RosterEntry(3, 0.5, cold_start=True),
    ]
    lam = 1.75
    rates = allocate_coupled_rates(roster, lam)
    assert math.isclose(sum(rate for rate, _ in rates.values()), lam, rel_tol=1e-12)
    # Shares are signal/total: total = 4.5; rate_i = lam * signal_i / total.
    total = 4.5
    assert math.isclose(rates[1][0], lam * 1.0 / total, rel_tol=1e-12)
    assert math.isclose(rates[2][0], lam * 3.0 / total, rel_tol=1e-12)
    assert rates[1][1] == PATH_COUPLED
    assert rates[2][1] == PATH_COUPLED
    assert rates[3][1] == PATH_COLD_START_SHARE  # cold-start fill, still coupled


def test_shares_normalise_to_one() -> None:
    roster = [_RosterEntry(c, float(c), cold_start=False) for c in (1, 2, 3, 4)]
    rates = allocate_coupled_rates(roster, 2.0)
    shares = [rate / 2.0 for rate, _ in rates.values()]
    assert math.isclose(sum(shares), 1.0, rel_tol=1e-12)


def test_equal_share_when_roster_signal_sum_is_zero() -> None:
    """A roster whose signals sum to zero takes equal shares (still conserving lambda_team)."""
    roster = [
        _RosterEntry(1, 0.0, cold_start=False),
        _RosterEntry(2, 0.0, cold_start=False),
        _RosterEntry(3, 0.0, cold_start=False),
    ]
    lam = 0.9
    rates = allocate_coupled_rates(roster, lam)
    assert all(path == PATH_EQUAL_SHARE for _, path in rates.values())
    # Equal shares => each rate = lam / 3, summing to lam.
    assert math.isclose(sum(rate for rate, _ in rates.values()), lam, rel_tol=1e-12)
    assert math.isclose(rates[1][0], lam / 3.0, rel_tol=1e-12)


def test_allocate_is_reproducible_for_the_same_input() -> None:
    """Identical input produces identical rates and paths (deterministic, pinned order)."""
    roster = [
        _RosterEntry(3, 2.0, cold_start=False),
        _RosterEntry(1, 1.0, cold_start=False),
        _RosterEntry(2, 0.0, cold_start=True),
    ]
    assert allocate_coupled_rates(roster, 1.3) == allocate_coupled_rates(list(roster), 1.3)


# --------------------------------------------------------------------------------------
# Appeared-rows signal: window, NULL handling, cold-start detection
# --------------------------------------------------------------------------------------


def test_mean_trailing_signal_window_null_skip_and_cold_start() -> None:
    rows = [(1.0, 0.2, 10.0), (2.0, None, 20.0), (3.0, 0.4, 30.0)]  # chronological by epoch
    # xG kind skips the NULL row: mean(0.2, 0.4) = 0.3 over the whole window.
    assert math.isclose(
        mean_trailing_signal(rows, kind="expected_goals", window=5), 0.3, rel_tol=1e-12
    )
    # threat kind never NULL here: mean(10, 20, 30) = 20.
    assert math.isclose(mean_trailing_signal(rows, kind="threat", window=5), 20.0)
    # window=1 keeps only the most recent row (epoch 3): xG = 0.4.
    assert math.isclose(
        mean_trailing_signal(rows, kind="expected_goals", window=1), 0.4, rel_tol=1e-12
    )
    # Every xG NULL => None (cold-start marker).
    assert (
        mean_trailing_signal([(1.0, None, 5.0), (2.0, None, 6.0)], kind="expected_goals", window=5)
        is None
    )
    assert mean_trailing_signal([], kind="threat", window=5) is None


def test_season_signal_kind_uses_xg_only_in_covered_seasons() -> None:
    assert season_signal_kind("2023-24", _XG_COVERED) == "expected_goals"
    assert season_signal_kind("2021-22", _XG_COVERED) == "threat"
    assert season_signal_kind("2022-23", _XG_COVERED) == "threat"  # not in covered list


# --------------------------------------------------------------------------------------
# Reduces-to-baseline: the stage-A-uninformative fallback is the exact v1.0 trailing rate
# --------------------------------------------------------------------------------------


def _history() -> list[PlayerHistoryRow]:
    return [
        PlayerHistoryRow("2023-24", 1, 1, "2023-08-11T19:00:00Z", 101, Position.FWD, 1, 0.5),
        PlayerHistoryRow("2023-24", 2, 2, "2023-08-18T19:00:00Z", 101, Position.FWD, 0, 0.5),
        PlayerHistoryRow("2023-24", 3, 3, "2023-08-25T19:00:00Z", 102, Position.FWD, 2, 0.0),
        PlayerHistoryRow("2023-24", 1, 1, "2023-08-11T19:00:00Z", 201, Position.MID, 0, 0.1),
    ]


def test_stage_a_uninformative_fallback_is_bit_identical_to_v1_baseline() -> None:
    """Where Stage A is uninformative every player takes the exact v1.0 trailing rate."""
    history = _history()
    baseline = TrailingPlayerGoalRateBaseline(alpha=5.0)
    baseline.fit(history)
    candidate = CoupledTeamShareAttackingGoalsV2(alpha=5.0, xg_covered_seasons=_XG_COVERED)
    candidate.fit(history)

    for code, position in [(101, Position.FWD), (102, Position.FWD), (999, Position.FWD)]:
        target = TargetRowProjection(
            "2023-24", 9, 9, "2023-09-30T14:00:00Z", code, position, 1, 2, True
        )
        # The candidate's fallback rate, formatted as a Poisson, equals the v1.0 baseline exactly.
        assert poisson_pmf(candidate._trailing_baseline_rate(code, position)) == baseline.predict(
            target
        ), f"fallback diverged from v1.0 baseline for code={code}"


def test_parameters_report_pinned_constants() -> None:
    candidate = CoupledTeamShareAttackingGoalsV2(alpha=5.0, xg_covered_seasons=_XG_COVERED)
    params = candidate.parameters()
    assert params["alpha"] == 5.0
    assert params["share_window"] == 5
    assert params["stage_a_model"] == "trailing_goals_attack_defence"
    assert candidate.name == "coupled_team_share_attacking_goals_v2"


# --------------------------------------------------------------------------------------
# In-memory integration: wiring, team_code identity, reduces-to-baseline
# --------------------------------------------------------------------------------------


def _build_db(*, with_team_match: bool) -> duckdb.DuckDBPyConnection:
    """A tiny archive: 2023-24 GW1..GW10 with player fixtures, team matches, and team codes."""
    con = duckdb.connect(":memory:")
    con.execute(
        """
        CREATE TABLE mart_fact_player_fixture (
            season VARCHAR, gw INTEGER, fixture INTEGER, kickoff_time TIMESTAMP,
            code INTEGER, position VARCHAR, team_id INTEGER, opponent_team_id INTEGER,
            was_home BOOLEAN, minutes INTEGER, goals_scored INTEGER,
            expected_goals DOUBLE, threat DOUBLE
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
    # Four clubs; team_code is NOT the team_id, and is the cross-season key.
    for team_id, code in [(1, 11), (2, 22), (3, 33), (4, 44)]:
        con.execute("INSERT INTO mart_dim_team VALUES ('2023-24', ?, ?, 'club')", [team_id, code])
    # Player fixtures: two FWDs on team 1, a MID on team 3, a DEF on team 4, across GW1..GW10.
    rows = []
    for gw in range(1, 11):
        day = 1 + gw
        kick = f"2023-08-{day:02d}T15:00:00"
        xg = round(0.1 * gw, 3)
        threat = round(10.0 * gw, 3)
        rows.append(("2023-24", gw, gw, kick, 111, "FWD", 1, 2, True, 90, gw % 3, xg, threat))
        rows.append(("2023-24", gw, gw, kick, 112, "FWD", 1, 2, True, 60, gw % 4, xg, threat))
        # 113 is a bench/DNP prior row at minutes=0 for GW<=8 (must NOT dilute the appeared rate).
        rows.append(
            ("2023-24", gw, gw, kick, 113, "FWD", 1, 2, True, 0 if gw < 9 else 30, 0, xg, threat)
        )
        rows.append(("2023-24", gw, gw, kick, 211, "MID", 3, 4, True, 90, gw % 2, xg, threat))
        rows.append(("2023-24", gw, gw, kick, 311, "DEF", 4, 3, False, 90, 0, xg, threat))
    con.executemany(
        "INSERT INTO mart_fact_player_fixture VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
    )
    if with_team_match:
        # Two fixtures per GW (1v2 and 3v4) so Stage A has schedule-adjusted history before GW9.
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


def _factory(history: object) -> CoupledTeamShareAttackingGoalsV2:
    config = load_phase3_evaluation()
    model = CoupledTeamShareAttackingGoalsV2(
        alpha=config.stage_c_candidate_v2.alpha,
        share_window=config.stage_c_candidate_v2.history_window,
        xg_covered_seasons=frozenset(config.xg_signal_policy.xg_covered_seasons),
    )
    model.fit(list(history))  # type: ignore[arg-type]
    return model


def test_candidate_coupled_scored_on_identical_rows_with_path_split() -> None:
    load_phase3_evaluation.cache_clear()
    config = load_phase3_evaluation()
    con = _build_db(with_team_match=True)
    try:
        result = run_attacking_harness(con, config=config, candidate_factory=_factory)
    finally:
        con.close()

    assert result.leakage_failures == 0
    # minimum_observed_gameweeks=8 over one 10-GW season => scoring folds GW9, GW10.
    assert sum(result.folds_by_season.values()) == 2
    name = "coupled_team_share_attacking_goals_v2"
    assert name in result.overall
    counts = {n: rep.predictions for n, rep in result.overall.items()}
    assert len(set(counts.values())) == 1  # identical eligible rows across all three models
    paths = result.candidate_path_counts[name]
    # Stage A is informative here => the coupled paths fire (no stage-A fallback).
    assert paths.get(PATH_STAGE_A_FALLBACK, 0) == 0
    assert (paths.get(PATH_COUPLED, 0) + paths.get(PATH_COLD_START_SHARE, 0)) > 0


def test_candidate_reduces_to_baseline_when_stage_a_uninformative() -> None:
    """No team-match history => Stage A uninformative => candidate == v1.0 trailing baseline."""
    load_phase3_evaluation.cache_clear()
    config = load_phase3_evaluation()
    con = _build_db(with_team_match=False)
    try:
        result = run_attacking_harness(con, config=config, candidate_factory=_factory)
    finally:
        con.close()

    name = "coupled_team_share_attacking_goals_v2"
    paths = result.candidate_path_counts[name]
    assert paths.get(PATH_STAGE_A_FALLBACK, 0) > 0  # every prediction took the fallback
    # The candidate's overall scores equal the trailing baseline's, bit-for-bit.
    cand = result.overall[name]
    base = result.overall["trailing_player_goal_rate_poisson"]
    assert cand.mean_log_score == base.mean_log_score
    assert cand.mean_ranked_probability_score == base.mean_ranked_probability_score


def test_team_code_map_is_season_scoped() -> None:
    """team_id resolves to team_code WITHIN the season; a reused id never pools across seasons."""
    con = _build_db(with_team_match=True)
    try:
        candidate = CoupledTeamShareAttackingGoalsV2(alpha=5.0, xg_covered_seasons=_XG_COVERED)
        mapping = candidate._team_code_map(con, "2023-24")
        # team_id 1 -> team_code 11 (not pooled with any other season's holder of id 1).
        assert mapping[1] == 11
        assert mapping[2] == 22
        assert set(mapping.values()) == {11, 22, 33, 44}
    finally:
        con.close()
