"""Hand-computable scored-card outcomes; no archive candidate evaluation."""

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from fpl.config import load_scoring_rules
from fpl.models.disciplinary_development import (
    NONE,
    ConditionalDisciplinary,
    DisciplinaryObservation,
    DisciplinaryParameters,
    ExposurePooledDisciplinary,
    scored_card_points,
    scored_card_state,
)
from fpl.types import Position

NOW = datetime(2025, 9, 12, tzinfo=UTC)
PRIOR = NOW - timedelta(days=7)


def row(**changes: object) -> DisciplinaryObservation:
    base = DisciplinaryObservation("2025-26", 3, 1, 100, Position.DEF, PRIOR, 90, 1, 0)
    return replace(base, **changes)  # type: ignore[arg-type]


def fit(history: list[DisciplinaryObservation]) -> ExposurePooledDisciplinary:
    return ExposurePooledDisciplinary().fit(history, as_of=NOW, excluded_target_gw=("2025-26", 4))


@pytest.mark.parametrize(("yellow", "red", "state"), [(0, 0, 0), (1, 0, 1), (0, 1, 2)])
def test_scored_encoding(yellow: int, red: int, state: int) -> None:
    assert scored_card_state(yellow, red) == state


@pytest.mark.parametrize(("yellow", "red"), [(None, 0), (0, None), (None, None)])
def test_null_not_zero(yellow: int | None, red: int | None) -> None:
    assert scored_card_state(yellow, red) is None


@pytest.mark.parametrize(("yellow", "red"), [(1, 1), (2, 1), (-1, 0), (0, 2)])
def test_unlicensed_joint_target_fails(yellow: int, red: int) -> None:
    with pytest.raises(ValueError, match="re-audit"):
        scored_card_state(yellow, red)


def test_points_only_loaded_rules() -> None:
    rules = load_scoring_rules("2026_27")
    changed = rules.model_copy(update={"yellow_cards": -7, "red_cards": -11})
    assert [scored_card_points(s, changed) for s in (0, 1, 2)] == [0, -7, -11]
    with pytest.raises(ValueError, match="unsupported"):
        scored_card_points(3, changed)


def test_hand_computable_pooling_and_competing_risks() -> None:
    model = fit([row()])
    # One 90-minute appearance, one yellow: league (1+.5)/180, red .5/180.
    league_y, league_r = 1.5 / 180, 0.5 / 180
    position_y = (1 + 4500 * league_y) / 4590
    position_r = 4500 * league_r / 4590
    assert model.position_rates[Position.DEF] == (position_y, position_r)
    y = (1 + 4500 * position_y) / 4590
    r = 45000 * position_r / 45090
    any_card = -math.expm1(-(y + r) * 90)
    expected = (1 - any_card, any_card * y / (y + r), any_card * r / (y + r))
    assert model.predict(100, Position.DEF).by_minutes_bin[3] == expected


def test_bin_exposure_is_fold_local_not_target_minutes() -> None:
    model = fit([row(minutes=20), row(fixture=2, minutes=70), row(fixture=3, minutes=90)])
    assert model.bin_exposure == (0.0, 20.0, 70.0, 90.0)
    assert (
        model.predict(100, Position.DEF).by_minutes_bin[1][0]
        > model.predict(100, Position.DEF).by_minutes_bin[3][0]
    )


def test_future_and_same_gw_truncation_equivalence_including_dgw() -> None:
    prior = [row()]
    target_early_leg = row(fixture=2, gw=4, kickoff=NOW - timedelta(days=1), red=1, yellow=0)
    target_late_leg = row(fixture=3, gw=4, kickoff=NOW + timedelta(days=7))
    future = row(fixture=4, gw=5, kickoff=NOW + timedelta(days=8))
    late_prior_gw = row(fixture=5, gw=2, kickoff=NOW + timedelta(days=9))
    extended = fit([*prior, target_early_leg, target_late_leg, future, late_prior_gw])
    baseline = fit(prior)
    assert extended.predict(100, Position.DEF) == baseline.predict(100, Position.DEF)
    assert extended.maximum_source_kickoff == PRIOR
    assert extended.bin_exposure == baseline.bin_exposure


def test_nonappearance_exact_none_and_appearance_not_double_gated() -> None:
    conditional = fit([row()]).predict(100, Position.DEF)
    assert conditional.marginal((1, 0, 0, 0)) == NONE
    played = conditional.by_minutes_bin[3]
    marginal = conditional.marginal((0.5, 0, 0, 0.5))
    assert marginal == (0.5 + 0.5 * played[0], 0.5 * played[1], 0.5 * played[2])


def test_bench_card_label_retained_but_not_trained_as_zero_exposure() -> None:
    original = row(minutes=0)
    model = fit([row(), replace(original, fixture=2)])
    assert original.yellow == 1
    assert scored_card_state(original.yellow, original.red) == 1
    assert model.excluded_zero_minute_cards == 1
    assert model.predict(100, Position.DEF) == fit([row()]).predict(100, Position.DEF)


def test_missing_history_and_measured_zero_are_distinct() -> None:
    missing = fit([row(minutes=None), row(fixture=2, yellow=None)])
    assert missing.maximum_source_kickoff is None
    measured = fit([row(yellow=0)])
    assert measured.maximum_source_kickoff == PRIOR
    assert missing.predict(100, Position.DEF) != measured.predict(100, Position.DEF)


def test_strong_red_pooling_shrinks_player_more_than_yellow() -> None:
    model = fit([row(), row(fixture=2, yellow=0, red=1)])
    params = model.parameters
    assert params.player_red_prior_minutes == 10 * params.player_yellow_prior_minutes
    assert model.predict(999, Position.DEF) == model.predict(999, Position.DEF, position_only=True)


def test_season_boundary_keeps_prior_identity_not_future_season() -> None:
    old = row(season="2024-25", gw=38, fixture=380)
    next_season = row(season="2026-27", gw=1, kickoff=NOW + timedelta(days=365))
    assert fit([old, next_season]).predict(100, Position.DEF) == fit([old]).predict(
        100, Position.DEF
    )


def test_stable_code_and_current_position_pooling_no_name_identity() -> None:
    model = fit([row()])
    assert model.predict(100, Position.MID) == model.predict(200, Position.MID)
    assert model.predict(100, Position.DEF) != model.predict(200, Position.DEF)


def test_deterministic_input_order_and_normalised_support() -> None:
    history = [row(), row(code=101, minutes=12, yellow=0)]
    first, second = fit(history), fit(list(reversed(history)))
    for position in Position:
        prediction = first.predict(100, position)
        assert prediction == second.predict(100, position)
        for pmf in prediction.by_minutes_bin:
            assert sum(pmf) == pytest.approx(1.0, abs=1e-15)
            assert all(0 <= value <= 1 for value in pmf)


def test_duplicate_naive_cutoff_and_invalid_minutes_fail() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        fit([row(), row()])
    with pytest.raises(ValueError, match="timezone-aware"):
        fit([row(kickoff=PRIOR.replace(tzinfo=None))])
    with pytest.raises(ValueError, match="invalid observed"):
        fit([row(minutes=-1)])
    with pytest.raises(ValueError, match="fit prior"):
        ExposurePooledDisciplinary().predict(100, Position.DEF)


def test_invalid_pmf_and_parameters_fail() -> None:
    with pytest.raises(ValueError, match="nonappearance"):
        ConditionalDisciplinary(((0.9, 0.1, 0), NONE, NONE, NONE))
    with pytest.raises(ValueError, match="mass"):
        ConditionalDisciplinary((NONE, (0.2, 0.2, 0.2), NONE, NONE))
    with pytest.raises(ValueError, match="pooling"):
        DisciplinaryParameters(player_red_prior_minutes=0)
    with pytest.raises(ValueError, match="four-bin"):
        fit([]).predict(100, Position.DEF).marginal((0.1, 0.1, 0.1, 0.1))


@pytest.mark.parametrize("bad", [True, 1.0, float("nan"), "1"])
def test_no_integer_aliases_or_usable_stale_model_after_failed_refit(bad: object) -> None:
    with pytest.raises(ValueError, match="nullable integers"):
        scored_card_state(bad, 0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unsupported"):
        scored_card_points(bad, load_scoring_rules("2026_27"))  # type: ignore[arg-type]
    model = fit([row()])
    with pytest.raises(ValueError, match="invalid observed"):
        model.fit([row(minutes=bad)], as_of=NOW, excluded_target_gw=("2025-26", 4))
    with pytest.raises(ValueError, match="fit prior"):
        model.predict(100, Position.DEF)
