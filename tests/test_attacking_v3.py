"""Offline tests for Stage C Candidate V3 (minutes-gated coupled team share).

No network. The pure minutes-gating allocation is tested without a database; the Stage A + Stage B
coupling, conservation, reduces-to-V2-when-gating-off, and reduces-to-baseline wiring are exercised
against a tiny in-memory DuckDB (the same fixture the V2 tests use).
"""

from __future__ import annotations

import math

from fpl.config import load_phase2_evaluation, load_phase3_evaluation
from fpl.models.attacking_v2 import (
    _RosterEntry,
    allocate_coupled_rates,
)
from fpl.models.attacking_v3 import allocate_minutes_gated_rates
from fpl.validate.attacking_harness import run_attacking_harness
from fpl.validate.minutes_baselines import MinuteBins

# Reuse the V2 in-memory archive builder (player fixtures + team matches + team codes).
from tests.test_attacking_v2 import _build_db  # type: ignore[attr-defined]

# --------------------------------------------------------------------------------------
# Pure minutes-gating allocation
# --------------------------------------------------------------------------------------


def _roster() -> list[_RosterEntry]:
    return [
        _RosterEntry(1, 2.0, cold_start=False),
        _RosterEntry(2, 1.0, cold_start=False),
        _RosterEntry(3, 1.0, cold_start=True),
    ]


def test_reduces_to_v2_bit_for_bit_when_gating_off() -> None:
    """minutes_gating=False is exactly V2's allocate_coupled_rates."""
    roster = _roster()
    p_play = {1: 0.9, 2: 0.2, 3: 0.5}
    assert allocate_minutes_gated_rates(roster, p_play, 1.4, minutes_gating=False) == (
        allocate_coupled_rates(roster, 1.4)
    )


def test_gating_conserves_lambda_team() -> None:
    """Renormalised gated rates still sum to lambda_team."""
    roster = _roster()
    lam = 1.6
    rates = allocate_minutes_gated_rates(roster, {1: 0.9, 2: 0.2, 3: 0.5}, lam, minutes_gating=True)
    assert math.isclose(sum(r for r, _ in rates.values()), lam, rel_tol=1e-12)


def test_gating_lowers_a_low_pplay_player_relative_share() -> None:
    """A low-p_play player's rate drops relative to their V2 share; a high-p_play player rises."""
    roster = _roster()
    p_play = {1: 1.0, 2: 0.1, 3: 1.0}
    lam = 1.0
    v2 = allocate_coupled_rates(roster, lam)
    gated = allocate_minutes_gated_rates(roster, p_play, lam, minutes_gating=True)
    # Player 2 (p_play 0.1) gets less under gating; player 1 (p_play 1.0) gets more.
    assert gated[2][0] < v2[2][0]
    assert gated[1][0] > v2[1][0]
    # Conservation still holds.
    assert math.isclose(sum(r for r, _ in gated.values()), lam, rel_tol=1e-12)


def test_gating_with_all_pplay_one_equals_v2() -> None:
    """When every p_play is 1 the gated allocation matches V2."""
    roster = _roster()
    lam = 1.3
    gated = allocate_minutes_gated_rates(
        roster, dict.fromkeys((1, 2, 3), 1.0), lam, minutes_gating=True
    )
    v2 = allocate_coupled_rates(roster, lam)
    for code in (1, 2, 3):
        assert math.isclose(gated[code][0], v2[code][0], rel_tol=1e-12)


def test_gating_all_zero_pplay_falls_back_to_v2() -> None:
    """Everyone predicted not to appear => unweighted V2 allocation (team total kept at lambda)."""
    roster = _roster()
    lam = 0.8
    gated = allocate_minutes_gated_rates(roster, {1: 0.0, 2: 0.0, 3: 0.0}, lam, minutes_gating=True)
    assert gated == allocate_coupled_rates(roster, lam)


# --------------------------------------------------------------------------------------
# In-memory integration: wiring + reduces-to-baseline
# --------------------------------------------------------------------------------------


def _v3_factory(history: object):  # type: ignore[no-untyped-def]
    from fpl.models.attacking_v3 import MinutesGatedCoupledTeamShareAttackingGoalsV3

    config = load_phase3_evaluation()
    bins = MinuteBins.from_config(load_phase2_evaluation())
    model = MinutesGatedCoupledTeamShareAttackingGoalsV3(
        alpha=config.stage_c_candidate_v3.alpha,
        share_window=config.stage_c_candidate_v3.history_window,
        xg_covered_seasons=frozenset(config.xg_signal_policy.xg_covered_seasons),
        bins=bins,
        minutes_gating=True,
    )
    model.fit(list(history))  # type: ignore[arg-type]
    return model


def test_candidate_v3_scored_on_identical_rows_with_path_split() -> None:
    load_phase3_evaluation.cache_clear()
    config = load_phase3_evaluation()
    con = _build_db(with_team_match=True)
    try:
        result = run_attacking_harness(con, config=config, candidate_factory=_v3_factory)
    finally:
        con.close()

    assert result.leakage_failures == 0
    name = "minutes_gated_coupled_team_share_attacking_goals_v3"
    assert name in result.overall
    # All three models scored the same eligible rows.
    counts = {n: rep.predictions for n, rep in result.overall.items()}
    assert len(set(counts.values())) == 1
    # Stage A informative => coupled paths fire; no stage-A fallback.
    paths = result.candidate_path_counts[name]
    assert paths.get("stage_a_uninformative_trailing", 0) == 0
    coupled_paths = paths.get("stage_a_coupled_appeared", 0) + paths.get(
        "stage_a_coupled_cold_start", 0
    )
    assert coupled_paths > 0


def test_candidate_v3_reduces_to_baseline_when_stage_a_uninformative() -> None:
    """No team-match history => Stage A uninformative => V3 == v1.0 trailing baseline."""
    load_phase3_evaluation.cache_clear()
    config = load_phase3_evaluation()
    con = _build_db(with_team_match=False)
    try:
        result = run_attacking_harness(con, config=config, candidate_factory=_v3_factory)
    finally:
        con.close()

    name = "minutes_gated_coupled_team_share_attacking_goals_v3"
    paths = result.candidate_path_counts[name]
    assert paths.get("stage_a_uninformative_trailing", 0) > 0
    cand = result.overall[name]
    base = result.overall["trailing_player_goal_rate_poisson"]
    assert cand.mean_log_score == base.mean_log_score
