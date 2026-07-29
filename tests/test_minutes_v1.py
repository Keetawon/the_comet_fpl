"""Deterministic, network-free tests for Stage B Candidate V1."""

from __future__ import annotations

import random
from dataclasses import fields
from datetime import UTC, datetime, timedelta, tzinfo

import pytest

from fpl.config import load_phase2_evaluation
from fpl.models.minutes_v1 import (
    ShrunkTrailing5PlayerMinutesV1,
    fit_minutes_v1,
)
from fpl.types import Position
from fpl.validate.minutes_baselines import HistoryRow, TargetRow

START = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)


def _history(
    *,
    season: str = "2024-25",
    gw: int,
    fixture: int,
    day: int,
    code: int = 1001,
    position: Position = Position.DEF,
    minutes: int,
) -> HistoryRow:
    return HistoryRow(
        season=season,
        gw=gw,
        fixture=fixture,
        kickoff_time=START + timedelta(days=day),
        code=code,
        position=position,
        team_id=1,
        opponent_team_id=2,
        was_home=True,
        minutes=minutes,
    )


def _target(
    *,
    season: str = "2025-26",
    gw: int = 1,
    fixture: int = 900,
    day: int = 200,
    code: int = 1001,
    position: Position = Position.DEF,
) -> TargetRow:
    return TargetRow(
        season=season,
        gw=gw,
        fixture=fixture,
        kickoff_time=START + timedelta(days=day),
        code=code,
        position=position,
        team_id=3,
        opponent_team_id=4,
        was_home=False,
    )


def _simple_history() -> list[HistoryRow]:
    return [
        _history(gw=1, fixture=1, day=1, minutes=0),
        _history(gw=2, fixture=2, day=2, minutes=60),
        _history(gw=3, fixture=3, day=3, minutes=90),
        _history(gw=4, fixture=4, day=4, minutes=90),
        _history(gw=5, fixture=5, day=5, minutes=90),
        _history(gw=6, fixture=6, day=6, minutes=1),
    ]


def _fit(rows: list[HistoryRow], *, as_of_day: int = 100) -> ShrunkTrailing5PlayerMinutesV1:
    return fit_minutes_v1(rows, as_of=START + timedelta(days=as_of_day))


def test_exact_formula_uses_recent_five_and_position_prior() -> None:
    model = _fit(_simple_history())
    # Full DEF prior q=(1,1,1,3)/6. Recent five omit the oldest zero:
    # c=(0,1,1,3), n=5. Fallback alpha=5 before fourteen observed GWs.
    distribution = model.predict(_target())
    assert model.selected_alpha == 5.0
    assert distribution == pytest.approx(
        (
            (0.0 + 5.0 / 6.0) / 10.0,
            (1.0 + 5.0 / 6.0) / 10.0,
            (1.0 + 5.0 / 6.0) / 10.0,
            (3.0 + 15.0 / 6.0) / 10.0,
        )
    )
    assert sum(distribution) == pytest.approx(1.0)


def test_zero_minutes_are_retained_in_player_counts() -> None:
    rows = [_history(gw=gw, fixture=gw, day=gw, minutes=0 if gw == 5 else 90) for gw in range(1, 6)]
    distribution = _fit(rows).predict(_target())
    # q and c both contain the zero, so shrinkage preserves one-fifth zero mass.
    assert distribution == pytest.approx((0.2, 0.0, 0.0, 0.8))


def test_cold_start_is_exact_position_prior_without_round_trip_change() -> None:
    rows = [
        _history(gw=1, fixture=1, day=1, code=2002, minutes=0),
        _history(gw=2, fixture=2, day=2, code=2002, minutes=90),
    ]
    model = _fit(rows)
    assert model.predict(_target(code=9999)) == (0.5, 0.0, 0.0, 0.5)


def test_missing_position_falls_back_to_unsmoothed_all_position_prior() -> None:
    rows = [
        _history(gw=1, fixture=1, day=1, position=Position.DEF, minutes=0),
        _history(gw=2, fixture=2, day=2, position=Position.DEF, minutes=90),
    ]
    assert _fit(rows).predict(_target(position=Position.FWD, code=9999)) == (
        0.5,
        0.0,
        0.0,
        0.5,
    )


def test_player_history_tracks_stable_code_across_seasons() -> None:
    rows = [
        _history(season="2024-25", gw=38, fixture=1, day=1, code=1001, minutes=0),
        _history(season="2025-26", gw=1, fixture=2, day=2, code=1001, minutes=90),
        _history(season="2025-26", gw=1, fixture=3, day=2, code=9999, minutes=60),
    ]
    distribution = _fit(rows).predict(_target(code=1001))
    # The code=9999 row affects q but cannot enter code=1001's player counts.
    q = (1 / 3, 0.0, 1 / 3, 1 / 3)
    expected = (
        (1 + 5 * q[0]) / 7,
        0.0,
        (0 + 5 * q[2]) / 7,
        (1 + 5 * q[3]) / 7,
    )
    assert distribution == pytest.approx(expected)


def test_input_order_does_not_change_prediction_or_metadata() -> None:
    rows = [
        _history(gw=gw, fixture=gw, day=gw, minutes=(0, 1, 60, 90)[gw % 4]) for gw in range(1, 17)
    ]
    shuffled = list(rows)
    random.Random(202627).shuffle(shuffled)
    first = _fit(rows, as_of_day=100)
    second = _fit(shuffled, as_of_day=100)
    assert first.predict(_target()) == second.predict(_target())
    assert first.metadata() == second.metadata()


def test_recency_tie_breaks_by_season_then_fixture_descending() -> None:
    same_day = 5
    rows = [
        _history(season="2024-25", gw=1, fixture=1, day=same_day, minutes=0),
        _history(season="2025-26", gw=1, fixture=1, day=same_day, minutes=60),
        _history(season="2025-26", gw=1, fixture=2, day=same_day, minutes=90),
        _history(gw=2, fixture=10, day=4, minutes=0),
        _history(gw=3, fixture=11, day=3, minutes=0),
        _history(gw=4, fixture=12, day=2, minutes=0),
    ]
    # Recent five drop the oldest of the four zero rows. q=(4,0,1,1)/6,
    # c=(3,0,1,1), proving the tied 2025-26 fixtures win before the older season.
    expected = ((3 + 5 * 4 / 6) / 10, 0.0, (1 + 5 / 6) / 10, (1 + 5 / 6) / 10)
    assert _fit(rows).predict(_target()) == pytest.approx(expected)


def test_predict_boundary_rejects_labelled_history_row() -> None:
    row = _simple_history()[0]
    model = _fit(_simple_history())
    with pytest.raises(TypeError, match="label-free"):
        model.predict(row)
    assert "minutes" not in {field.name for field in fields(TargetRow)}


@pytest.mark.parametrize("day", [100, 101])
def test_fit_rejects_null_label_and_future_or_equal_history(day: int) -> None:
    valid = _history(gw=1, fixture=1, day=1, minutes=90)
    null_row = HistoryRow(
        season=valid.season,
        gw=valid.gw,
        fixture=valid.fixture,
        kickoff_time=valid.kickoff_time,
        code=valid.code,
        position=valid.position,
        team_id=valid.team_id,
        opponent_team_id=valid.opponent_team_id,
        was_home=valid.was_home,
        minutes=None,  # type: ignore[arg-type]
    )
    with pytest.raises(TypeError, match="non-null int"):
        _fit([null_row])
    at_cutoff = _history(gw=1, fixture=2, day=day, minutes=90)
    with pytest.raises(ValueError, match="not observed before cutoff"):
        _fit([at_cutoff])


class _NoOffsetTimezone(tzinfo):
    def utcoffset(self, dt: datetime | None) -> None:
        return None

    def dst(self, dt: datetime | None) -> None:
        return None


def test_naive_cutoffs_and_targets_are_rejected() -> None:
    rows = [_history(gw=1, fixture=1, day=1, minutes=90)]
    with pytest.raises(ValueError, match="timezone-aware"):
        ShrunkTrailing5PlayerMinutesV1().fit(rows, as_of=datetime(2025, 2, 1, 12, 0))
    model = _fit(rows)
    naive = _target()
    naive = TargetRow(
        season=naive.season,
        gw=naive.gw,
        fixture=naive.fixture,
        kickoff_time=datetime(2025, 8, 1, 12, 0),
        code=naive.code,
        position=naive.position,
        team_id=naive.team_id,
        opponent_team_id=naive.opponent_team_id,
        was_home=naive.was_home,
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        model.predict(naive)

    unusable_timezone = _target()
    unusable_timezone = TargetRow(
        season=unusable_timezone.season,
        gw=unusable_timezone.gw,
        fixture=unusable_timezone.fixture,
        kickoff_time=datetime(2025, 8, 1, 12, 0, tzinfo=_NoOffsetTimezone()),
        code=unusable_timezone.code,
        position=unusable_timezone.position,
        team_id=unusable_timezone.team_id,
        opponent_team_id=unusable_timezone.opponent_team_id,
        was_home=unusable_timezone.was_home,
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        model.predict(unusable_timezone)


def test_full_history_projection_equals_physically_truncated_history() -> None:
    past = _simple_history()
    future = _history(gw=20, fixture=20, day=150, minutes=0)
    full_source = [*past, future]
    cutoff = START + timedelta(days=100)
    projected = [row for row in full_source if row.kickoff_time < cutoff]
    full_view_model = ShrunkTrailing5PlayerMinutesV1().fit(projected, as_of=cutoff)
    truncated_model = ShrunkTrailing5PlayerMinutesV1().fit(past, as_of=cutoff)
    assert full_view_model.predict(_target()) == truncated_model.predict(_target())
    assert full_view_model.metadata() == truncated_model.metadata()


def test_fewer_than_fourteen_observed_gameweeks_uses_frozen_fallback() -> None:
    rows = [_history(gw=gw, fixture=gw, day=gw, minutes=90) for gw in range(1, 14)]
    model = _fit(rows)
    assert model.parameters()["selected_alpha"] == 5.0
    assert model.parameters()["used_inner_holdout"] is False
    assert model.metadata().inner_holdout_gameweeks == ()
    assert model.metadata().alpha_scores == ()


def test_six_observed_gameweeks_are_selected_without_assuming_contiguous_values() -> None:
    # Missing GW7 is intentional. The last six OBSERVED keys are 10..15.
    gameweeks = [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15]
    rows = [
        _history(gw=gw, fixture=index, day=index, minutes=90)
        for index, gw in enumerate(gameweeks, start=1)
    ]
    model = _fit(rows)
    assert model.metadata().used_inner_holdout is True
    assert model.metadata().inner_training_observed_gameweeks == 8
    assert model.metadata().inner_holdout_gameweeks == tuple(
        ("2024-25", gw) for gw in (10, 11, 12, 13, 14, 15)
    )
    assert {score.predictions for score in model.metadata().alpha_scores} == {6}


def test_exact_alpha_tie_selects_smallest_grid_value() -> None:
    # Every row is 90 minutes, making q, c and every alpha prediction exactly one-hot.
    rows = [_history(gw=gw, fixture=gw, day=gw, minutes=90) for gw in range(1, 15)]
    model = _fit(rows)
    assert [score.pooled_mean_log_score for score in model.metadata().alpha_scores] == [0.0] * 5
    assert model.selected_alpha == 1.0


def test_final_state_is_refit_on_all_outer_history_after_selection() -> None:
    # Eight inner-training weeks are all zero; the six holdout weeks are all 90. If the final
    # state accidentally retained only inner-training history, it would predict zero minutes.
    rows = [
        _history(gw=gw, fixture=gw, day=gw, minutes=0 if gw <= 8 else 90) for gw in range(1, 15)
    ]
    model = _fit(rows)
    assert model.metadata().used_inner_holdout is True
    q_90 = 6 / 14
    expected_90 = (5 + model.selected_alpha * q_90) / (5 + model.selected_alpha)
    assert model.predict(_target())[3] == pytest.approx(expected_90)
    assert model.predict(_target())[3] > 0.8


def test_nested_selection_is_pooled_by_prediction_not_mean_of_gameweeks() -> None:
    rows: list[HistoryRow] = []
    fixture = 0
    for gw in range(1, 15):
        # Unequal batch sizes make pooled scoring observable in metadata.
        count = 1 if gw < 14 else 3
        for offset in range(count):
            fixture += 1
            rows.append(
                _history(
                    gw=gw,
                    fixture=fixture,
                    day=gw,
                    code=1000 + offset,
                    minutes=0 if gw % 2 else 90,
                )
            )
    model = _fit(rows)
    expected_predictions = sum(1 if gw < 14 else 3 for gw in range(9, 15))
    assert {score.predictions for score in model.metadata().alpha_scores} == {expected_predictions}


def test_double_gameweek_targets_share_pre_gameweek_state_and_remain_separate() -> None:
    rows = [_history(gw=gw, fixture=gw, day=gw, minutes=90) for gw in range(1, 15)]
    model = _fit(rows)
    first = _target(gw=20, fixture=901, code=1001)
    second = _target(gw=20, fixture=902, code=1001)
    predictions = model.predict([second, first])
    assert len(predictions) == 2
    assert predictions[0] == predictions[1]


def test_inner_double_gameweek_is_a_batch_not_within_gameweek_training() -> None:
    rows = [_history(gw=gw, fixture=gw, day=gw, minutes=90) for gw in range(1, 14)]
    # The 14th observed GW has two fixtures for the same player with conflicting labels.
    rows.extend(
        [
            _history(gw=14, fixture=1401, day=14, code=1001, minutes=0),
            _history(gw=14, fixture=1402, day=15, code=1001, minutes=90),
        ]
    )
    original = _fit(rows)
    swapped = [
        (
            HistoryRow(
                season=row.season,
                gw=row.gw,
                fixture=row.fixture,
                kickoff_time=row.kickoff_time,
                code=row.code,
                position=row.position,
                team_id=row.team_id,
                opponent_team_id=row.opponent_team_id,
                was_home=row.was_home,
                minutes=90 if row.fixture == 1401 else 0,
            )
            if row.fixture in {1401, 1402}
            else row
        )
        for row in rows
    ]
    alternate = _fit(swapped)
    # Swapping labels between the two same-GW fixtures leaves the pooled grid scores unchanged.
    assert original.metadata().alpha_scores == alternate.metadata().alpha_scores


def test_model_does_not_use_team_opponent_or_home_away_features() -> None:
    model = _fit(_simple_history())
    target = _target()
    changed_context = TargetRow(
        season=target.season,
        gw=target.gw,
        fixture=target.fixture + 1,
        kickoff_time=target.kickoff_time,
        code=target.code,
        position=target.position,
        team_id=999,
        opponent_team_id=777,
        was_home=not target.was_home,
    )
    assert model.predict(target) == model.predict(changed_context)


def test_predictions_before_fit_and_empty_fit_fail_closed() -> None:
    with pytest.raises(RuntimeError, match="fitted"):
        ShrunkTrailing5PlayerMinutesV1().predict(_target())
    with pytest.raises(ValueError, match="at least one"):
        _fit([])


def test_candidate_identity_and_grid_come_from_frozen_contract() -> None:
    config = load_phase2_evaluation()
    model = ShrunkTrailing5PlayerMinutesV1(config=config)
    assert model.name == "shrunk_trailing_5_player_minutes_v1"
    assert config.stage_b_candidate_v1.prior_strength_grid == (
        1.0,
        2.0,
        5.0,
        10.0,
        20.0,
    )
