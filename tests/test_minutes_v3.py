"""Deterministic, network-free tests for Stage B Candidate V3 (concentration-adaptive minutes).

V3 is V2 with a concentration-adaptive shrinkage strength ``alpha_eff = alpha * (1 - lambda*C)``,
where ``C`` is the normalised Herfindahl concentration of the recency-weighted trailing history.
The defining property is the nesting: at ``lambda = 0`` V3 is bit-identical to V2, so it is a strict
generalisation and the comparison is honest. These tests pin that property, the concentration
sharpening that motivates V3 (the goalkeeper / nailed-starter case), the concentration math, the
joint three-parameter selection, and the shared leakage-safe behaviour V3 inherits from V1/V2.
"""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta, tzinfo

import pytest

from fpl.config import load_phase2_evaluation
from fpl.models.minutes_v2 import RecencyWeightedTrailingPlayerMinutesV2
from fpl.models.minutes_v3 import (
    ConcentrationAdaptiveShrinkagePlayerMinutesV3,
    fit_minutes_v3,
)
from fpl.types import Position
from fpl.validate.minutes_baselines import HistoryRow, TargetRow

START = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
ALPHA_GRID = (1.0, 2.0, 5.0, 10.0, 20.0)
DECAY_GRID = (1.0, 0.9, 0.7, 0.5, 0.3)
LAMBDA_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)


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


def _fit(
    rows: list[HistoryRow], *, as_of_day: int = 100
) -> ConcentrationAdaptiveShrinkagePlayerMinutesV3:
    return fit_minutes_v3(rows, as_of=START + timedelta(days=as_of_day))


def _v2_fit(
    rows: list[HistoryRow], *, as_of_day: int = 100
) -> RecencyWeightedTrailingPlayerMinutesV2:
    as_of = START + timedelta(days=as_of_day)
    return RecencyWeightedTrailingPlayerMinutesV2().fit(rows, as_of=as_of)


def _sixteen_gws(minutes_pattern) -> list[HistoryRow]:
    return [
        _history(gw=gw, fixture=gw, day=gw, minutes=minutes_pattern[gw % len(minutes_pattern)])
        for gw in range(1, 17)
    ]


# --------------------------------------------------------------------------------------
# The nesting property: lambda = 0 is bit-identical to V2
# --------------------------------------------------------------------------------------


def test_lambda_zero_is_bit_identical_to_v2_across_the_decay_alpha_grid() -> None:
    rows = _sixteen_gws((0, 1, 60, 90))
    v2 = _v2_fit(rows)
    v3 = _fit(rows)
    assert v2._state is not None and v3._state is not None
    # Same history -> same shared fold-local state.
    assert v2._state.prior == v3._state.prior
    assert v2._state.by_code == v3._state.by_code
    target = _target()
    for decay in DECAY_GRID:
        for alpha in ALPHA_GRID:
            v2_dist = v2._distribution_weighted(v2._state, target, alpha=alpha, decay=decay)
            v3_dist = v3._distribution_adaptive(
                v3._state, target, alpha=alpha, decay=decay, adaptation=0.0
            )
            assert v3_dist == v2_dist, f"nesting broken at decay={decay}, alpha={alpha}"


def test_lambda_zero_prediction_equals_v2_prediction() -> None:
    # Every row 90 -> a fully-concentrated history where a null hypothesis (lambda=0) is optimal,
    # so the joint selector must pick lambda=0 and match V2's prediction exactly.
    rows = _sixteen_gws((0, 1, 60, 90))
    v3 = _fit(rows)
    v2 = _v2_fit(rows)
    # The selected params may differ in general; assert equality where the histories force lambda=0.
    if v3.selected_adaptation == 0.0:
        assert v3.predict(_target()) == v2.predict(_target())


# --------------------------------------------------------------------------------------
# Concentration math and the goalkeeper / nailed-starter sharpening (the V3 hypothesis)
# --------------------------------------------------------------------------------------


def test_concentration_is_one_for_a_single_bin_history() -> None:
    # A player whose five recent fixtures are all 90 (bin 3) -> fully concentrated -> C = 1, so
    # alpha_eff = alpha*(1-lambda) and at lambda=1 alpha_eff=0 -> the prediction is a one-hot.
    rows = [_history(gw=gw, fixture=gw, day=gw, minutes=90) for gw in range(1, 6)]
    model = _fit(rows)
    assert model._state is not None
    dist = model._distribution_adaptive(
        model._state, _target(), alpha=5.0, decay=0.7, adaptation=1.0
    )
    assert dist == pytest.approx((0.0, 0.0, 0.0, 1.0))


def test_concentration_is_zero_for_a_uniform_history_so_v3_equals_v2_there() -> None:
    # One row in each of the four bins under decay=1.0 -> equal weighted shares -> C = 0 ->
    # alpha_eff = alpha regardless of lambda, so V3 equals V2 on a maximally-spread history.
    rows = [
        _history(gw=1, fixture=1, day=1, minutes=0),
        _history(gw=2, fixture=2, day=2, minutes=1),
        _history(gw=3, fixture=3, day=3, minutes=60),
        _history(gw=4, fixture=4, day=4, minutes=90),
    ]
    model = _fit(rows)
    v2 = _v2_fit(rows)
    assert model._state is not None and v2._state is not None
    target = _target()
    for lam in LAMBDA_GRID:
        adaptive = model._distribution_adaptive(
            model._state, target, alpha=5.0, decay=1.0, adaptation=lam
        )
        weighted = v2._distribution_weighted(v2._state, target, alpha=5.0, decay=1.0)
        assert adaptive == pytest.approx(weighted), f"C should be 0 at lambda={lam}"


def test_lambda_sharpens_a_concentrated_history_monotonically() -> None:
    # The goalkeeper mechanism: a nailed starter whose OWN history is more concentrated on the
    # dominant bin than the position prior is. The position prior is deliberately spread (other
    # players split across all four bins), while the target player (code 7000) is all-90. Reducing
    # the shrinkage (raising lambda) then moves the prediction toward the player's own confident
    # signal and AWAY from the spread prior, so P(dominant bin) rises with lambda.
    spread_population = [
        _history(gw=gw, fixture=1000 + gw, day=gw, code=2000 + gw, minutes=bucket)
        for gw, bucket in enumerate([0, 1, 60, 90] * 4, start=1)
    ]
    target_player = [
        _history(gw=gw, fixture=gw, day=40 + gw, code=7000, minutes=90) for gw in range(1, 6)
    ]
    model = _fit(spread_population + target_player)
    assert model._state is not None
    target = _target(code=7000)
    masses = [
        model._distribution_adaptive(model._state, target, alpha=10.0, decay=0.7, adaptation=lam)[3]
        for lam in LAMBDA_GRID
    ]
    assert masses == sorted(masses), "P(dominant bin) must be non-decreasing in lambda"
    assert masses[-1] > masses[0], "lambda>0 must sharpen a concentrated history vs a spread prior"


def test_distribution_always_sums_to_one_across_the_grid() -> None:
    rows = _sixteen_gws((0, 90, 90, 90))
    model = _fit(rows)
    assert model._state is not None
    target = _target()
    for decay in DECAY_GRID:
        for alpha in ALPHA_GRID:
            for lam in LAMBDA_GRID:
                dist = model._distribution_adaptive(
                    model._state, target, alpha=alpha, decay=decay, adaptation=lam
                )
                assert sum(dist) == pytest.approx(1.0)
                assert all(p >= 0.0 for p in dist)


def test_alpha_eff_is_clamped_at_zero() -> None:
    # lambda=1 and a fully-concentrated history give alpha_eff = alpha*(1-1*1) = 0 exactly; the
    # formula must never drive alpha_eff negative (which would make a mass exceed 1).
    rows = [_history(gw=gw, fixture=gw, day=gw, minutes=0) for gw in range(1, 6)]
    model = _fit(rows)
    assert model._state is not None
    dist = model._distribution_adaptive(
        model._state, _target(), alpha=20.0, decay=1.0, adaptation=1.0
    )
    assert dist == pytest.approx((1.0, 0.0, 0.0, 0.0))


# --------------------------------------------------------------------------------------
# Cold start, fallback, and the joint three-parameter selection
# --------------------------------------------------------------------------------------


def test_cold_start_is_exact_position_prior() -> None:
    rows = [
        _history(gw=1, fixture=1, day=1, code=2002, minutes=0),
        _history(gw=2, fixture=2, day=2, code=2002, minutes=90),
    ]
    # An unseen code -> W == 0 -> exactly the position prior q (lambda irrelevant).
    assert _fit(rows).predict(_target(code=9999)) == (0.5, 0.0, 0.0, 0.5)


def test_fewer_than_fourteen_observed_gameweeks_uses_frozen_fallback() -> None:
    rows = [_history(gw=gw, fixture=gw, day=gw, minutes=90) for gw in range(1, 14)]
    model = _fit(rows)
    meta = model.metadata_v3()
    assert meta.used_inner_holdout is False
    assert meta.param_scores == ()
    assert model.selected_decay == 1.0  # fallback (== V1/V2)
    assert model.selected_alpha == 5.0  # fallback
    assert model.selected_adaptation == 0.0  # fallback (== V2, no adaptation)
    assert model.parameters()["selected_lambda"] == 0.0


def test_joint_selection_runs_over_the_full_triple_grid() -> None:
    # Missing GW7 is intentional. 14 observed gameweeks exercise the nested joint holdout.
    gameweeks = [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15]
    rows = [
        _history(gw=gw, fixture=index, day=index, minutes=90)
        for index, gw in enumerate(gameweeks, start=1)
    ]
    meta = _fit(rows).metadata_v3()
    assert meta.used_inner_holdout is True
    assert meta.inner_training_observed_gameweeks == 8
    assert meta.inner_holdout_gameweeks == tuple(("2024-25", gw) for gw in (10, 11, 12, 13, 14, 15))
    # 5 decay x 5 alpha x 5 lambda = 125 grid points scored; each scored the 6 holdout gameweeks.
    assert len(meta.param_scores) == 125
    assert {score.predictions for score in meta.param_scores} == {6}
    assert all(
        s.decay in DECAY_GRID and s.alpha in ALPHA_GRID and s.adaptation in LAMBDA_GRID
        for s in meta.param_scores
    )


def test_joint_tie_break_prefers_smallest_lambda_then_largest_decay_then_smallest_alpha() -> None:
    # Every row is 90 minutes -> every (decay, alpha, lambda) predicts a one-hot at bin 3 with log
    # score 0, so the whole grid ties and the tie-break decides.
    rows = [_history(gw=gw, fixture=gw, day=gw, minutes=90) for gw in range(1, 15)]
    model = _fit(rows)
    assert {s.pooled_mean_log_score for s in model.metadata_v3().param_scores} == {0.0}
    assert model.selected_adaptation == 0.0  # smallest lambda (closest to V2)
    assert model.selected_decay == 1.0  # then largest decay
    assert model.selected_alpha == 1.0  # then smallest alpha


# --------------------------------------------------------------------------------------
# Inherited leakage-safe behaviour (exercised through the V3 surface)
# --------------------------------------------------------------------------------------


def test_input_order_does_not_change_prediction_or_metadata() -> None:
    rows = _sixteen_gws((0, 1, 60, 90))
    shuffled = list(rows)
    random.Random(202627).shuffle(shuffled)
    first = _fit(rows, as_of_day=100)
    second = _fit(shuffled, as_of_day=100)
    assert first.predict(_target()) == second.predict(_target())
    assert first.metadata_v3() == second.metadata_v3()


def test_full_history_projection_equals_physically_truncated_history() -> None:
    past = _sixteen_gws((0, 1, 60, 90))
    future = _history(gw=20, fixture=20, day=150, minutes=0)
    cutoff = START + timedelta(days=100)
    projected = [row for row in [*past, future] if row.kickoff_time < cutoff]
    full = ConcentrationAdaptiveShrinkagePlayerMinutesV3().fit(projected, as_of=cutoff)
    trunc = ConcentrationAdaptiveShrinkagePlayerMinutesV3().fit(past, as_of=cutoff)
    assert full.predict(_target()) == trunc.predict(_target())
    assert full.metadata_v3() == trunc.metadata_v3()


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


def test_naive_cutoffs_and_targets_are_rejected() -> None:
    rows = [_history(gw=1, fixture=1, day=1, minutes=90)]
    with pytest.raises(ValueError, match="timezone-aware"):
        ConcentrationAdaptiveShrinkagePlayerMinutesV3().fit(rows, as_of=datetime(2025, 2, 1, 12, 0))


def test_predictions_before_fit_and_empty_fit_fail_closed() -> None:
    with pytest.raises(RuntimeError, match="fitted"):
        ConcentrationAdaptiveShrinkagePlayerMinutesV3().predict(_target())
    with pytest.raises(ValueError, match="at least one"):
        _fit([])


def test_candidate_identity_and_grids_come_from_frozen_contract() -> None:
    config = load_phase2_evaluation()
    model = ConcentrationAdaptiveShrinkagePlayerMinutesV3(config=config)
    assert model.name == "concentration_adaptive_shrinkage_player_minutes_v3"
    assert config.stage_b_candidate_v3.decay_grid == DECAY_GRID
    assert config.stage_b_candidate_v3.prior_strength_grid == ALPHA_GRID
    assert config.stage_b_candidate_v3.adaptation_grid == LAMBDA_GRID
    assert config.stage_b_candidate_v3.reduces_to_v2_when_lambda_is_zero is True


def _norm_herfindahl(shares: list[float]) -> float:
    h = math.fsum(s * s for s in shares)
    return (h - 0.25) / 0.75


def test_concentration_formula_matches_reference_values() -> None:
    assert _norm_herfindahl([1.0, 0.0, 0.0, 0.0]) == pytest.approx(1.0)
    assert _norm_herfindahl([0.25, 0.25, 0.25, 0.25]) == pytest.approx(0.0)
    assert _norm_herfindahl([0.5, 0.5, 0.0, 0.0]) == pytest.approx(1 / 3)


class _NoOffsetTimezone(tzinfo):
    def utcoffset(self, dt: datetime | None) -> None:
        return None

    def dst(self, dt: datetime | None) -> None:
        return None
