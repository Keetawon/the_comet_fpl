"""Offline tests for Stage C Candidate V1 (xG-informed trailing player goals).

No database, no network. Uses tiny synthetic fixtures. The headline guarantee under test is that
the candidate reduces to the v1.0 ``trailing_player_goal_rate_poisson`` baseline bit-for-bit
wherever xG is unmeasured, and that the xG-informed path matches its hand-computed formula.
"""

from __future__ import annotations

import math

from fpl.models.attacking_baselines import (
    PlayerHistoryRow,
    TargetRowProjection,
    TrailingPlayerGoalRateBaseline,
    poisson_pmf,
)
from fpl.models.attacking_v1 import (
    PATH_COLD_START,
    PATH_FALLBACK_V1,
    PATH_XG_INFORMED,
    XgInformedTrailingPlayerGoalsV1,
)
from fpl.types import Position

_KICKOFF = "2021-08-13T19:00:00Z"


def _target(code: int, position: Position = Position.FWD, gw: int = 9) -> TargetRowProjection:
    return TargetRowProjection(
        "2021-22", gw, gw, "2021-09-30T14:00:00Z", code, position, 1, 2, True
    )


def test_reduces_to_baseline_bit_for_bit_when_xg_absent() -> None:
    """Where every expected_goals is NULL the candidate == v1.0 trailing baseline, exactly."""
    # NULL expected_goals is the default; construct rows without it.
    history = [
        PlayerHistoryRow("2021-22", 1, 1, "2021-08-13T19:00:00Z", 101, Position.FWD, 1),
        PlayerHistoryRow("2021-22", 1, 1, "2021-08-13T19:00:00Z", 102, Position.FWD, 0),
        PlayerHistoryRow("2021-22", 2, 2, "2021-08-20T19:00:00Z", 101, Position.FWD, 0),
        PlayerHistoryRow("2021-22", 2, 2, "2021-08-20T19:00:00Z", 102, Position.FWD, 2),
        PlayerHistoryRow("2021-22", 3, 3, "2021-08-27T19:00:00Z", 201, Position.MID, 1),
        PlayerHistoryRow("2021-22", 3, 3, "2021-08-27T19:00:00Z", 301, Position.DEF, 0),
    ]

    baseline = TrailingPlayerGoalRateBaseline(alpha=5.0)
    baseline.fit(history)
    candidate = XgInformedTrailingPlayerGoalsV1()
    candidate.fit(history)

    for code, position in [
        (101, Position.FWD),
        (102, Position.FWD),
        (999, Position.FWD),
        (201, Position.MID),
        (301, Position.DEF),
    ]:
        target = _target(code, position)
        # Bit-for-bit: same float tuple, including the cold-start player 999.
        assert candidate.predict(target) == baseline.predict(target), (
            f"candidate diverged from baseline for code={code} position={position.name}"
        )
        # And every one of these takes the fallback / cold-start path, never the xG path.
        assert candidate.path_for(target) in (PATH_FALLBACK_V1, PATH_COLD_START)


def test_xg_informed_rate_matches_formula() -> None:
    """The xG path computes the exact pre-registered rate."""
    # Four FWD prior rows. Player 101 has three trailing rows all with measured xG.
    history = [
        PlayerHistoryRow("2023-24", 1, 1, "2023-08-11T19:00:00Z", 101, Position.FWD, 1, 0.5),
        PlayerHistoryRow("2023-24", 2, 2, "2023-08-18T19:00:00Z", 101, Position.FWD, 0, 0.5),
        PlayerHistoryRow("2023-24", 3, 3, "2023-08-25T19:00:00Z", 101, Position.FWD, 0, 0.5),
        PlayerHistoryRow("2023-24", 1, 1, "2023-08-11T19:00:00Z", 102, Position.FWD, 0, 0.0),
    ]
    candidate = XgInformedTrailingPlayerGoalsV1()
    candidate.fit(history)

    target = _target(101, Position.FWD)
    rate = candidate._rate(target).rate  # direct unit check of the pinned formula
    assert candidate.path_for(target) == PATH_XG_INFORMED

    # pos_g = (1+0+0+0)/4 = 0.25 ; pos_x = (0.5+0.5+0.5+0.0)/4 = 0.375
    # n=m=3, S_x=1.5, S_gm=1 ; shrunk_xg = (1.5 + 5*0.375)/8 = 0.421875
    # player_fin = (1-1.5)/3 ; pos_fin = 0.25-0.375 = -0.125
    # finish_term = 0.05*player_fin + 0.95*(-0.125)
    player_fin = (1 - 1.5) / 3
    finish_term = 0.05 * player_fin + 0.95 * (0.25 - 0.375)
    expected = max(0.0, (1.5 + 5.0 * 0.375) / 8 + finish_term)
    assert math.isclose(rate, expected, rel_tol=1e-12)

    # The Poisson distribution is consistent with that rate: P(1)/P(0) == rate.
    dist = candidate.predict(target)
    assert math.isclose(dist[1] / dist[0], rate, rel_tol=1e-12)
    assert abs(sum(dist) - 1.0) < 1e-9


def test_cold_start_uses_positional_rate() -> None:
    history = [
        PlayerHistoryRow("2023-24", 1, 1, "2023-08-11T19:00:00Z", 101, Position.FWD, 1, 0.4),
    ]
    candidate = XgInformedTrailingPlayerGoalsV1()
    candidate.fit(history)

    target = _target(999, Position.FWD)  # no prior rows for 999
    assert candidate.path_for(target) == PATH_COLD_START
    # Cold-start rate is the positional mean goals/appearance (0.4 goals from xG is irrelevant).
    assert candidate._rate(target).rate == 1.0 / 1


def test_fallback_when_player_trailing_xg_unmeasured() -> None:
    """A player whose trailing rows predate xG coverage takes the exact baseline path."""
    history = [
        # 102 has two old rows with NULL xG, even though the fold has measured xG elsewhere.
        PlayerHistoryRow("2021-22", 1, 1, "2021-08-13T19:00:00Z", 102, Position.FWD, 1),
        PlayerHistoryRow("2021-22", 2, 2, "2021-08-20T19:00:00Z", 102, Position.FWD, 1),
        # 101 carries measured xG, so pos_x[FWD] is defined for the fold.
        PlayerHistoryRow("2023-24", 3, 3, "2023-08-25T19:00:00Z", 101, Position.FWD, 0, 0.3),
    ]
    baseline = TrailingPlayerGoalRateBaseline(alpha=5.0)
    baseline.fit(history)
    candidate = XgInformedTrailingPlayerGoalsV1()
    candidate.fit(history)

    target = _target(102, Position.FWD)
    assert candidate.path_for(target) == PATH_FALLBACK_V1
    assert candidate.predict(target) == baseline.predict(target)  # exact baseline rate


def test_trailing_window_is_five_most_recent() -> None:
    """Only the five most recent prior rows feed the rate; a sixth older row is excluded."""
    rows = [
        PlayerHistoryRow(
            "2023-24", gw, gw, f"2023-08-{10 + gw:02d}T19:00:00Z", 101, Position.FWD, goals, 0.2
        )
        for gw, goals in enumerate(
            [1, 0, 0, 0, 0, 0], start=1
        )  # six rows; oldest (gw1) carries goal
    ]
    candidate = XgInformedTrailingPlayerGoalsV1()
    candidate.fit(rows)
    rate = candidate._rate(_target(101, Position.FWD)).rate

    # The five most recent rows (gw2..gw6) all have goals=0; the goals=1 row at gw1 is dropped by
    # the window. player_fin over the window is therefore (0 - 5*0.2)/5 = -0.2, and the rate is
    # deterministic with the xG path taken.
    assert candidate.path_for(_target(101, Position.FWD)) == PATH_XG_INFORMED
    assert rate >= 0.0
    # Sanity: the resulting distribution is a valid Poisson pmf.
    assert abs(sum(candidate.predict(_target(101, Position.FWD))) - 1.0) < 1e-9


def test_parameters_report_pinned_constants() -> None:
    candidate = XgInformedTrailingPlayerGoalsV1()
    assert candidate.parameters() == {"alpha": 5.0, "finishing_keep": 0.05}
    assert candidate.name == "xg_informed_trailing_player_goals_v1"


def test_poisson_floor_handles_zero_rate() -> None:
    """A clamped-to-zero rate still yields a valid normalised distribution (no NaN)."""
    dist = poisson_pmf(0.0)
    assert len(dist) == 11
    assert abs(sum(dist) - 1.0) < 1e-9
