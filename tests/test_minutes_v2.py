"""Deterministic, network-free tests for Stage B Candidate V2 (recency-weighted minutes).

V2 is V1 with a geometric recency weight on the same trailing-5 window. The defining property is
the nesting: at ``decay = 1.0`` V2 is bit-identical to V1, so it is a strict generalisation and the
comparison is honest. These tests pin that property, the recency sensitivity that motivates V2, and
the shared leakage-safe behaviour V2 inherits from V1's scaffolding.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta, tzinfo

import pytest

from fpl.config import load_phase2_evaluation
from fpl.models.minutes_v1 import ShrunkTrailing5PlayerMinutesV1
from fpl.models.minutes_v2 import RecencyWeightedTrailingPlayerMinutesV2, fit_minutes_v2
from fpl.types import Position
from fpl.validate.minutes_baselines import HistoryRow, TargetRow

START = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
ALPHA_GRID = (1.0, 2.0, 5.0, 10.0, 20.0)
DECAY_GRID = (1.0, 0.9, 0.7, 0.5, 0.3)


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


def _fit(rows: list[HistoryRow], *, as_of_day: int = 100) -> RecencyWeightedTrailingPlayerMinutesV2:
    return fit_minutes_v2(rows, as_of=START + timedelta(days=as_of_day))


def _v1_fit(rows: list[HistoryRow], *, as_of_day: int = 100) -> ShrunkTrailing5PlayerMinutesV1:
    return ShrunkTrailing5PlayerMinutesV1().fit(rows, as_of=START + timedelta(days=as_of_day))


def _sixteen_gws(minutes_pattern) -> list[HistoryRow]:
    return [
        _history(gw=gw, fixture=gw, day=gw, minutes=minutes_pattern[gw % len(minutes_pattern)])
        for gw in range(1, 17)
    ]


# --------------------------------------------------------------------------------------
# The nesting property: decay = 1.0 is bit-identical to V1
# --------------------------------------------------------------------------------------


def test_decay_one_is_bit_identical_to_v1_across_the_alpha_grid() -> None:
    rows = _sixteen_gws((0, 1, 60, 90))
    v1 = _v1_fit(rows)
    v2 = _fit(rows)
    assert v1._state is not None and v2._state is not None
    # Same history -> same shared fold-local state.
    assert v1._state.prior == v2._state.prior
    assert v1._state.by_code == v2._state.by_code
    target = _target()
    for alpha in ALPHA_GRID:
        v1_dist = v1._distribution(v1._state, target, alpha=alpha)
        v2_dist = v2._distribution_weighted(v2._state, target, alpha=alpha, decay=1.0)
        assert v1_dist == v2_dist, f"nesting broken at alpha={alpha}"


def test_decay_one_prediction_equals_v1_prediction() -> None:
    # Enough observed gameweeks to exercise the nested selection; the decay=1.0 grid column scores
    # exactly as V1's grid, so V2 must select decay=1.0 and match V1's prediction.
    rows = _sixteen_gws((0, 1, 60, 90))
    assert _fit(rows).predict(_target()) == _v1_fit(rows).predict(_target())


# --------------------------------------------------------------------------------------
# Recency sensitivity (the hypothesis V2 exists to test)
# --------------------------------------------------------------------------------------


def test_recency_distinguishes_a_dropped_starter_from_a_breaking_sub() -> None:
    """Same bin counts, opposite recency. Under decay<1 these predict differently; under
    decay=1.0 they are identical (V1 cannot tell them apart). Exactly five rows so the trailing-5
    window keeps every row and the two histories share bin counts {0:2, 90:3}."""
    dropped = [  # 90,90,90,0,0 -- a starter losing his place (the 0s are recent)
        _history(gw=1, fixture=1, day=1, minutes=90),
        _history(gw=2, fixture=2, day=2, minutes=90),
        _history(gw=3, fixture=3, day=3, minutes=90),
        _history(gw=4, fixture=4, day=4, minutes=0),
        _history(gw=5, fixture=5, day=5, minutes=0),
    ]
    breaking = [  # 0,0,90,90,90 -- a substitute breaking in (the 90s are recent)
        _history(gw=1, fixture=1, day=1, minutes=0),
        _history(gw=2, fixture=2, day=2, minutes=0),
        _history(gw=3, fixture=3, day=3, minutes=90),
        _history(gw=4, fixture=4, day=4, minutes=90),
        _history(gw=5, fixture=5, day=5, minutes=90),
    ]
    alpha = 5.0
    target = _target()
    dropped_state = _fit(dropped)._state
    breaking_state = _fit(breaking)._state
    assert dropped_state is not None and breaking_state is not None
    model = RecencyWeightedTrailingPlayerMinutesV2()
    # decay = 1.0: identical counts -> identical prediction (V1 cannot tell them apart).
    assert model._distribution_weighted(
        dropped_state, target, alpha=alpha, decay=1.0
    ) == model._distribution_weighted(breaking_state, target, alpha=alpha, decay=1.0)
    # decay < 1.0: the recent 0s (dropped) vs recent 90s (breaking) diverge.
    assert model._distribution_weighted(
        dropped_state, target, alpha=alpha, decay=0.5
    ) != model._distribution_weighted(breaking_state, target, alpha=alpha, decay=0.5)
    # And the divergence is in the expected direction: the breaking sub gets MORE 90-mass.
    assert (
        model._distribution_weighted(breaking_state, target, alpha=alpha, decay=0.5)[3]
        > (model._distribution_weighted(dropped_state, target, alpha=alpha, decay=0.5)[3])
    )


def test_zero_minutes_are_retained_and_weighted() -> None:
    rows = [_history(gw=gw, fixture=gw, day=gw, minutes=0 if gw == 5 else 90) for gw in range(1, 6)]
    v2 = _fit(rows)
    dist = v2.predict(_target())
    # q and the weighted counts both contain the zero, so mass on bin 0 stays positive.
    assert dist[0] > 0.0
    assert sum(dist) == pytest.approx(1.0)


# --------------------------------------------------------------------------------------
# Cold start, fallback, and the closed form
# --------------------------------------------------------------------------------------


def test_cold_start_is_exact_position_prior() -> None:
    rows = [
        _history(gw=1, fixture=1, day=1, code=2002, minutes=0),
        _history(gw=2, fixture=2, day=2, code=2002, minutes=90),
    ]
    # An unseen code -> W == 0 -> exactly the position prior q.
    assert _fit(rows).predict(_target(code=9999)) == (0.5, 0.0, 0.0, 0.5)


def test_fewer_than_fourteen_observed_gameweeks_uses_frozen_fallback() -> None:
    rows = [_history(gw=gw, fixture=gw, day=gw, minutes=90) for gw in range(1, 14)]
    model = _fit(rows)
    meta = model.metadata_v2()
    assert meta.used_inner_holdout is False
    assert meta.param_scores == ()
    assert model.selected_decay == 1.0  # fallback (== V1)
    assert model.selected_alpha == 5.0  # fallback
    assert model.parameters()["selected_decay"] == 1.0


def test_joint_selection_runs_and_picks_from_the_grid() -> None:
    # Missing GW7 is intentional. 14 observed gameweeks exercise the nested joint holdout.
    gameweeks = [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15]
    rows = [
        _history(gw=gw, fixture=index, day=index, minutes=90)
        for index, gw in enumerate(gameweeks, start=1)
    ]
    meta = _fit(rows).metadata_v2()
    assert meta.used_inner_holdout is True
    assert meta.inner_training_observed_gameweeks == 8
    assert meta.inner_holdout_gameweeks == tuple(("2024-25", gw) for gw in (10, 11, 12, 13, 14, 15))
    # 5 decay x 5 alpha = 25 grid points scored; each scored the 6 holdout gameweeks.
    assert len(meta.param_scores) == 25
    assert {score.predictions for score in meta.param_scores} == {6}
    assert all(s.decay in DECAY_GRID and s.alpha in ALPHA_GRID for s in meta.param_scores)


def test_joint_tie_break_prefers_largest_decay_then_smallest_alpha() -> None:
    # Every row is 90 minutes -> every (decay, alpha) predicts a one-hot at bin 3 with log score 0.
    rows = [_history(gw=gw, fixture=gw, day=gw, minutes=90) for gw in range(1, 15)]
    model = _fit(rows)
    assert {s.pooled_mean_log_score for s in model.metadata_v2().param_scores} == {0.0}
    assert model.selected_decay == 1.0  # largest decay (closest to V1)
    assert model.selected_alpha == 1.0  # then smallest alpha


def test_final_state_is_refit_on_all_outer_history_after_selection() -> None:
    # Eight inner-training weeks are all zero; the six holdout weeks are all 90. The final state
    # must include the holdout weeks, so the 90-bin dominates (a state refit on inner-training
    # alone would predict all zeros). V2 selects its own (decay, alpha), so the exact mass differs
    # from V1; what matters is that the holdout 90s entered the final state.
    rows = [
        _history(gw=gw, fixture=gw, day=gw, minutes=0 if gw <= 8 else 90) for gw in range(1, 15)
    ]
    model = _fit(rows)
    assert model.metadata_v2().used_inner_holdout is True
    dist = model.predict(_target())
    assert dist[3] == max(dist)  # 90-bin is the dominant bin
    assert dist[3] > dist[0]  # more 90-mass than 0-mass -> holdout 90s are in the state


# --------------------------------------------------------------------------------------
# Inherited leakage-safe behaviour (exercised through the V2 surface)
# --------------------------------------------------------------------------------------


def test_input_order_does_not_change_prediction_or_metadata() -> None:
    rows = _sixteen_gws((0, 1, 60, 90))
    shuffled = list(rows)
    random.Random(202627).shuffle(shuffled)
    first = _fit(rows, as_of_day=100)
    second = _fit(shuffled, as_of_day=100)
    assert first.predict(_target()) == second.predict(_target())
    assert first.metadata_v2() == second.metadata_v2()


def test_full_history_projection_equals_physically_truncated_history() -> None:
    past = _sixteen_gws((0, 1, 60, 90))
    future = _history(gw=20, fixture=20, day=150, minutes=0)
    cutoff = START + timedelta(days=100)
    projected = [row for row in [*past, future] if row.kickoff_time < cutoff]
    full = RecencyWeightedTrailingPlayerMinutesV2().fit(projected, as_of=cutoff)
    trunc = RecencyWeightedTrailingPlayerMinutesV2().fit(past, as_of=cutoff)
    assert full.predict(_target()) == trunc.predict(_target())
    assert full.metadata_v2() == trunc.metadata_v2()


def test_double_gameweek_targets_share_pre_gameweek_state_and_remain_separate() -> None:
    rows = _sixteen_gws((0, 1, 60, 90))
    model = _fit(rows)
    first = _target(gw=20, fixture=901, code=1001)
    second = _target(gw=20, fixture=902, code=1001)
    predictions = model.predict([second, first])
    assert len(predictions) == 2
    assert predictions[0] == predictions[1]  # same pre-gameweek state, same distribution


def test_predict_rejects_a_labelled_history_row() -> None:
    model = _fit(_sixteen_gws((0, 1, 60, 90)))
    with pytest.raises(TypeError, match="label-free"):
        model.predict(_history(gw=1, fixture=1, day=1, minutes=90))


def test_fit_rejects_future_or_equal_history_and_null_label() -> None:
    at_cutoff = _history(gw=1, fixture=2, day=100, minutes=90)
    with pytest.raises(ValueError, match="not observed before cutoff"):
        _fit([at_cutoff], as_of_day=100)
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


class _NoOffsetTimezone(tzinfo):
    def utcoffset(self, dt: datetime | None) -> None:
        return None

    def dst(self, dt: datetime | None) -> None:
        return None


def test_naive_cutoffs_and_targets_are_rejected() -> None:
    rows = [_history(gw=1, fixture=1, day=1, minutes=90)]
    with pytest.raises(ValueError, match="timezone-aware"):
        RecencyWeightedTrailingPlayerMinutesV2().fit(rows, as_of=datetime(2025, 2, 1, 12, 0))
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


def test_predictions_before_fit_and_empty_fit_fail_closed() -> None:
    with pytest.raises(RuntimeError, match="fitted"):
        RecencyWeightedTrailingPlayerMinutesV2().predict(_target())
    with pytest.raises(ValueError, match="at least one"):
        _fit([])


def test_candidate_identity_and_grids_come_from_frozen_contract() -> None:
    config = load_phase2_evaluation()
    model = RecencyWeightedTrailingPlayerMinutesV2(config=config)
    assert model.name == "recency_weighted_trailing_player_minutes_v2"
    assert config.stage_b_candidate_v2.decay_grid == DECAY_GRID
    assert config.stage_b_candidate_v2.prior_strength_grid == ALPHA_GRID
    assert config.stage_b_candidate_v2.reduces_to_v1_when_decay_is_one is True
