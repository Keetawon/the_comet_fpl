"""Contract tests for the price-informed newcomer appearance prior.

Deterministic and offline. The fitted constants are pinned here on purpose: they were selected
on 2023-24/2024-25 with 2025-26 held out, and a silent refit would invalidate that discipline
without any test noticing.
"""

from __future__ import annotations

import math
from itertools import pairwise

import pytest

from fpl.models.price_starter_prior import (
    BEHIND_INCUMBENT_CAP,
    INCUMBENT_APPEARANCE_THRESHOLD,
    PRICE_PRIOR_CAP,
    PRICE_PRIOR_COEFFICIENTS,
    PRICE_PRIOR_PIVOT,
    apply_price_starter_prior,
    price_starter_probability,
)
from fpl.types import Position

# Reproduced from the fit; see the module docstring for provenance.
FITTED = {
    Position.GK: {40: 0.040, 45: 0.347, 50: 0.850},
    Position.DEF: {35: 0.145, 40: 0.315, 45: 0.554, 50: 0.770},
    Position.MID: {40: 0.105, 45: 0.222, 50: 0.410},
    Position.FWD: {40: 0.243, 50: 0.395, 65: 0.655},
}


@pytest.mark.parametrize("position", list(FITTED))
def test_matches_the_fitted_curve(position: Position) -> None:
    for price, expected in FITTED[position].items():
        assert price_starter_probability(price, position) == pytest.approx(expected, abs=5e-4)


def test_missing_or_nonsense_price_declines_to_answer() -> None:
    """The caller must fall back to the existing prior rather than receive an invented number."""
    for price in (None, 0, -1):
        assert price_starter_probability(price, Position.MID) is None


@pytest.mark.parametrize("position", list(FITTED))
def test_probability_is_monotone_in_price(position: Position) -> None:
    values = [price_starter_probability(p, position) for p in range(35, 151)]
    assert all(v is not None for v in values)
    for earlier, later in pairwise(values):
        assert earlier is not None and later is not None
        assert later >= earlier - 1e-12


@pytest.mark.parametrize("position", list(FITTED))
def test_cap_holds_at_both_extremes(position: Position) -> None:
    """A newcomer may never be given more confidence than a proven ever-present (0.897)."""
    low, high = PRICE_PRIOR_CAP
    floor_value = price_starter_probability(1, position)
    ceiling_value = price_starter_probability(2000, position)
    assert floor_value == pytest.approx(low)
    assert ceiling_value == pytest.approx(high)
    assert high < 0.897


def test_goalkeeper_separates_the_backup_from_the_signed_first_choice() -> None:
    """Every one of 35 measured newcomer keepers at or below 4.0m appeared 0.000 of the time."""
    backup = price_starter_probability(40, Position.GK)
    first_choice = price_starter_probability(50, Position.GK)
    assert backup is not None and first_choice is not None
    assert backup < 0.10
    assert first_choice > 0.70
    # The constant prior this replaces sat at 0.2496 for both.
    assert backup < 0.2496 < first_choice


def test_reshape_preserves_the_conditional_minute_shape() -> None:
    minutes = (0.6, 0.1, 0.1, 0.2)
    reshaped = apply_price_starter_prior(minutes, price=50, position=Position.MID)
    assert sum(reshaped) == pytest.approx(1.0)
    expected = price_starter_probability(50, Position.MID)
    assert expected is not None
    assert 1.0 - reshaped[0] == pytest.approx(expected)
    # The split *between* playing bins is untouched; only the play/no-play split moves.
    before = [minutes[i] / sum(minutes[1:]) for i in (1, 2, 3)]
    after = [reshaped[i] / sum(reshaped[1:]) for i in (1, 2, 3)]
    assert after == pytest.approx(before)


def test_reshape_without_a_price_is_the_identity() -> None:
    minutes = (0.6, 0.1, 0.1, 0.2)
    assert apply_price_starter_prior(minutes, price=None, position=Position.MID) == minutes


def test_reshape_handles_a_distribution_with_no_playing_mass() -> None:
    """Degenerate input must still produce a valid distribution, not a divide-by-zero."""
    reshaped = apply_price_starter_prior((1.0, 0.0, 0.0, 0.0), price=55, position=Position.DEF)
    assert sum(reshaped) == pytest.approx(1.0)
    assert all(mass >= 0.0 for mass in reshaped)
    expected = price_starter_probability(55, Position.DEF)
    assert expected is not None
    assert 1.0 - reshaped[0] == pytest.approx(expected)


def test_reshaped_distribution_stays_a_distribution_across_the_price_range() -> None:
    minutes = (0.55, 0.15, 0.10, 0.20)
    for position in FITTED:
        for price in range(35, 151, 5):
            reshaped = apply_price_starter_prior(minutes, price=price, position=position)
            assert sum(reshaped) == pytest.approx(1.0)
            assert all(0.0 <= mass <= 1.0 for mass in reshaped)


def test_constants_are_pinned() -> None:
    """A refit must be a deliberate, reviewed change, never a silent one."""
    assert PRICE_PRIOR_PIVOT == 47.0
    assert PRICE_PRIOR_CAP == (0.04, 0.85)
    assert set(PRICE_PRIOR_COEFFICIENTS) == {
        Position.GK,
        Position.DEF,
        Position.MID,
        Position.FWD,
    }
    assert PRICE_PRIOR_COEFFICIENTS[Position.GK] == (1.36703, 0.99990)
    assert PRICE_PRIOR_COEFFICIENTS[Position.DEF] == (0.61236, 0.19870)
    assert PRICE_PRIOR_COEFFICIENTS[Position.MID] == (-0.89655, 0.17736)
    assert PRICE_PRIOR_COEFFICIENTS[Position.FWD] == (-0.64023, 0.07122)
    for intercept, slope in PRICE_PRIOR_COEFFICIENTS.values():
        assert math.isfinite(intercept) and math.isfinite(slope)
        # The unpenalised GK fit reached 3.87 and behaved as a step function.
        assert 0.0 < slope < 1.5


def test_incumbent_cap_only_ever_lowers() -> None:
    """The cap is a ceiling, never a floor: a newcomer already rated below it is untouched."""
    for position in FITTED:
        for price in range(35, 151, 5):
            plain = price_starter_probability(price, position)
            capped = price_starter_probability(price, position, behind_established_incumbent=True)
            assert plain is not None and capped is not None
            assert capped <= plain + 1e-12
            assert capped <= BEHIND_INCUMBENT_CAP + 1e-12
            if plain <= BEHIND_INCUMBENT_CAP:
                assert capped == pytest.approx(plain)


def test_incumbent_cap_fixes_the_case_that_motivated_it() -> None:
    """A 5.0m newcomer keeper behind a dearer established incumbent was reading 0.85."""
    uncapped = price_starter_probability(50, Position.GK)
    capped = price_starter_probability(50, Position.GK, behind_established_incumbent=True)
    assert uncapped is not None and capped is not None
    assert uncapped > 0.80
    assert capped == pytest.approx(BEHIND_INCUMBENT_CAP)


def test_incumbent_cap_is_off_by_default() -> None:
    """Nothing changes for a caller that does not pass the flag."""
    for position in FITTED:
        for price in (40, 50, 65):
            assert price_starter_probability(price, position) == price_starter_probability(
                price, position, behind_established_incumbent=False
            )


def test_reshape_passes_the_incumbent_flag_through() -> None:
    minutes = (0.5, 0.1, 0.1, 0.3)
    reshaped = apply_price_starter_prior(
        minutes, price=60, position=Position.DEF, behind_established_incumbent=True
    )
    assert sum(reshaped) == pytest.approx(1.0)
    assert 1.0 - reshaped[0] == pytest.approx(BEHIND_INCUMBENT_CAP)
    # conditional minute shape still preserved
    before = [minutes[i] / sum(minutes[1:]) for i in (1, 2, 3)]
    after = [reshaped[i] / sum(reshaped[1:]) for i in (1, 2, 3)]
    assert after == pytest.approx(before)


def test_incumbent_constants_are_pinned() -> None:
    """0.284 is measured (201 historical rows, and 0.283 on the 2025-26 subset), not tuned."""
    assert BEHIND_INCUMBENT_CAP == 0.284
    assert INCUMBENT_APPEARANCE_THRESHOLD == 0.70
    low, high = PRICE_PRIOR_CAP
    assert low < BEHIND_INCUMBENT_CAP < high
