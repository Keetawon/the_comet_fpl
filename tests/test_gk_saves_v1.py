"""Deterministic, offline tests for the Stage D v2 goalkeeper saves component.

No network, no database. The estimator derives a fold-local league save rate from GK appearances and
maps a fixture's expected team-conceded rate to a saves count distribution.
"""

from __future__ import annotations

import math

from fpl.models.gk_saves_v1 import (
    LEAGUE_SAVE_RATE,
    MAX_SAVE_RATE,
    MIN_SAVE_RATE,
    GkSavesHistoryRow,
    GkSavesV1,
)
from fpl.types import Position


def _gk(saves: int | None, conceded: int | None, minutes: int = 90) -> GkSavesHistoryRow:
    return GkSavesHistoryRow(
        position=Position.GK, minutes=minutes, saves=saves, goals_conceded=conceded
    )


def test_save_rate_derived_from_gk_shots_on_target() -> None:
    # 6 saves, 3 conceded -> 6 / (6 + 3) = 0.6667, inside the clamp band.
    model = GkSavesV1()
    model.fit([_gk(4, 2), _gk(2, 1)])
    assert math.isclose(model.save_rate, 6 / 9, rel_tol=1e-12)


def test_no_gk_history_falls_back_to_league_constant() -> None:
    model = GkSavesV1()
    # Only outfielders in history -> no GK shots-on-target -> fallback league constant.
    model.fit(
        [
            GkSavesHistoryRow(position=Position.DEF, minutes=90, saves=0, goals_conceded=1),
            GkSavesHistoryRow(position=Position.MID, minutes=90, saves=0, goals_conceded=2),
        ]
    )
    assert model.save_rate == LEAGUE_SAVE_RATE


def test_null_saves_or_conceded_are_skipped_not_zeroed() -> None:
    # A NULL row must not contribute a fabricated zero. Only the (5 saves, 5 conceded) row counts.
    model = GkSavesV1()
    model.fit([_gk(None, 1), _gk(5, None), _gk(5, 5)])
    assert math.isclose(model.save_rate, 0.5, rel_tol=1e-12)


def test_zero_minute_gk_rows_are_not_appearances() -> None:
    model = GkSavesV1()
    model.fit([_gk(0, 0, minutes=0), _gk(7, 3)])
    assert math.isclose(model.save_rate, 7 / 10, rel_tol=1e-12)


def test_save_rate_is_clamped_to_band() -> None:
    high = GkSavesV1()
    high.fit([_gk(99, 0)])  # rate 1.0 -> clamped down
    assert high.save_rate == MAX_SAVE_RATE
    low = GkSavesV1()
    low.fit([_gk(0, 99)])  # rate 0.0 -> clamped up
    assert low.save_rate == MIN_SAVE_RATE


def test_non_goalkeeper_gets_point_mass_on_zero_saves() -> None:
    model = GkSavesV1()
    model.fit([_gk(6, 3)])
    for position in (Position.DEF, Position.MID, Position.FWD):
        dist = model.predict(position, lambda_conceded=1.5)
        assert dist[0] == 1.0
        assert sum(dist) == 1.0


def test_goalkeeper_saves_distribution_scales_with_conceded_rate() -> None:
    model = GkSavesV1()
    model.fit([_gk(6, 3)])  # save_rate 2/3 -> k = (2/3)/(1/3) = 2.0
    assert math.isclose(model.saves_per_conceded, 2.0, rel_tol=1e-12)
    # Expected saves = k * lambda_conceded. For lambda 1.5 the Poisson mean is 3.0.
    dist = model.predict(Position.GK, lambda_conceded=1.5)
    assert abs(sum(dist) - 1.0) < 1e-9
    mean = sum(index * mass for index, mass in enumerate(dist))
    assert abs(mean - 3.0) < 0.05
    # A higher conceded rate shifts mass to more saves (higher mean).
    dist_high = model.predict(Position.GK, lambda_conceded=2.5)
    mean_high = sum(index * mass for index, mass in enumerate(dist_high))
    assert mean_high > mean


def test_zero_conceded_rate_gives_near_zero_saves() -> None:
    model = GkSavesV1()
    model.fit([_gk(6, 3)])
    dist = model.predict(Position.GK, lambda_conceded=0.0)
    assert dist[0] == 1.0
