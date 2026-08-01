"""Deterministic, offline tests for the Stage D v2 defensive-contribution component.

No network, no database. The estimator returns a per-player Bernoulli hit probability
``P(DC >= threshold)``, prospective-only (no DC history -> 0), shrunk toward a fold-local position
rate. Thresholds are the real 2026/27 values (DEF 10, MID 12, FWD 12).
"""

from __future__ import annotations

import math

from fpl.config import load_scoring_rules
from fpl.models.defensive_contribution_v1 import DcHistoryRow, DefensiveContributionV1
from fpl.types import Position

THRESHOLDS = load_scoring_rules("2026_27").defensive_contribution.thresholds


def _row(code: int, position: Position, dc: int | None, minutes: int = 90) -> DcHistoryRow:
    return DcHistoryRow(code=code, position=position, minutes=minutes, defensive_contribution=dc)


def test_no_history_gives_zero_hit_probability() -> None:
    # Empty history (the pre-2025-26 case): the position prior is undefined, so p_hit is 0.
    model = DefensiveContributionV1(THRESHOLDS)
    model.fit([])
    assert model.predict(code=1, position=Position.DEF) == 0.0
    assert model.predict(code=1, position=Position.MID) == 0.0


def test_null_dc_rows_never_become_zero_hits() -> None:
    # All-NULL DC history (unmeasured season) must not create a fabricated 0-hit position prior.
    model = DefensiveContributionV1(THRESHOLDS)
    model.fit([_row(1, Position.DEF, None), _row(2, Position.DEF, None)])
    assert model.position_hit_rate(Position.DEF) is None
    assert model.predict(code=1, position=Position.DEF) == 0.0


def test_goalkeeper_never_earns_dc() -> None:
    # GK is absent from the threshold map (gotcha 7); a GK always gets p_hit = 0 even with a
    # position prior present for outfielders.
    model = DefensiveContributionV1(THRESHOLDS)
    model.fit([_row(1, Position.DEF, 12), _row(2, Position.DEF, 3)])
    assert model.predict(code=999, position=Position.GK) == 0.0


def test_position_prior_is_the_fold_local_hit_rate() -> None:
    # DEF threshold 10. Three DEF appearances: 12 (hit), 3 (miss), 11 (hit) -> position rate 2/3.
    model = DefensiveContributionV1(THRESHOLDS, alpha=5.0, window=5)
    model.fit([_row(1, Position.DEF, 12), _row(2, Position.DEF, 3), _row(3, Position.DEF, 11)])
    assert math.isclose(model.position_hit_rate(Position.DEF), 2 / 3, rel_tol=1e-12)
    # A player with no personal DC history shrinks entirely to the position prior.
    assert math.isclose(model.predict(code=404, position=Position.DEF), 2 / 3, rel_tol=1e-12)


def test_player_history_shrinks_toward_position_prior() -> None:
    # Position prior 2/3 (as above). Player 1 has two personal hits (12, 11). With alpha 5:
    # p_hit = (2 + 5 * 2/3) / (2 + 5) = (2 + 10/3) / 7.
    model = DefensiveContributionV1(THRESHOLDS, alpha=5.0, window=5)
    model.fit([_row(1, Position.DEF, 12), _row(2, Position.DEF, 3), _row(1, Position.DEF, 11)])
    pos_prior = model.position_hit_rate(Position.DEF)
    assert pos_prior is not None
    # Player 1 appears twice, both hits -> n = 2, hits = 2.
    expected = (2 + 5.0 * pos_prior) / (2 + 5.0)
    assert math.isclose(model.predict(code=1, position=Position.DEF), expected, rel_tol=1e-12)
    # A hit probability is always a proper probability in [0, 1].
    assert 0.0 <= model.predict(code=1, position=Position.DEF) <= 1.0


def test_threshold_is_position_specific() -> None:
    # A DC count of 11 is a hit for DEF (threshold 10) but a miss for MID (threshold 12).
    assert THRESHOLDS[Position.DEF] == 10
    assert THRESHOLDS[Position.MID] == 12
    model = DefensiveContributionV1(THRESHOLDS)
    model.fit([_row(1, Position.DEF, 11), _row(2, Position.MID, 11)])
    assert model.position_hit_rate(Position.DEF) == 1.0
    assert model.position_hit_rate(Position.MID) == 0.0


def test_zero_minute_dc_rows_are_not_appearances() -> None:
    # A 0-minute DC row is not an appearance and must not enter the position rate.
    model = DefensiveContributionV1(THRESHOLDS)
    model.fit([_row(1, Position.DEF, 0, minutes=0), _row(2, Position.DEF, 12)])
    assert model.position_hit_rate(Position.DEF) == 1.0


def test_window_limits_trailing_history() -> None:
    # window = 2: only the two most recent appearances count. Older hits fall out.
    model = DefensiveContributionV1(THRESHOLDS, alpha=0.0, window=2)
    # Player 1: [miss, hit, hit] in arrival order -> trailing 2 = [hit, hit] -> p_hit = 1 (alpha 0).
    model.fit(
        [
            _row(1, Position.DEF, 3),
            _row(9, Position.DEF, 12),
            _row(1, Position.DEF, 12),
            _row(1, Position.DEF, 11),
        ]
    )
    assert model.predict(code=1, position=Position.DEF) == 1.0
