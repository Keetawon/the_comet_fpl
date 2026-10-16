"""Threshold, double-gameweek, fitting and delayed-label contracts."""

import math
from datetime import UTC, datetime, timedelta

import pytest

from fpl.models.goal_involvement import (
    EventRow,
    binary_log_loss,
    fit_event_model,
    fixture_low_counts,
    gameweek_probability,
)
from fpl.validate.goal_involvement import Fold, eligible_folds, prepare_fold


def test_one_shared_appearance_gate():
    assert fixture_low_counts((0.5, 0, 0, 0.5), (0, 1), (0, 1)) == (0.5, 0)
    assert gameweek_probability([(0.5, 0)]) == 0.5


def test_dgw_one_in_each_counts_as_two_and_blank_is_zero():
    assert gameweek_probability([(0, 1)]) == 0
    assert gameweek_probability([(0, 1), (0, 1)]) == 1
    assert gameweek_probability([]) == 0
    assert gameweek_probability([(0.8, 0.2), (0.8, 0.2)]) == pytest.approx(0.04)


@pytest.mark.parametrize("bad", [(float("nan"), 0), (-0.1, 0), (0.8, 0.3)])
def test_invalid_probability_fails(bad):
    with pytest.raises(ValueError, match="invalid fixture"):
        gameweek_probability([bad])


def test_complete_delayed_labels_required():
    cutoff = datetime(2025, 1, 10, tzinfo=UTC)
    complete = Fold(
        "complete", "2024-25", 1, cutoff - timedelta(days=7), cutoff - timedelta(hours=1), ()
    )
    delayed = Fold("delayed", "2024-25", 2, cutoff - timedelta(days=6), cutoff, ())
    future = Fold(
        "future", "2024-25", 3, cutoff + timedelta(days=1), cutoff + timedelta(days=2), ()
    )
    assert eligible_folds([future, delayed, complete], cutoff) == [complete]


def test_logistic_solver_reduces_loss_and_fits_positions():
    rows = [
        EventRow(pos, 0.1, int(i < events))
        for pos, events in (("MID", 30), ("FWD", 50))
        for i in range(100)
    ]
    fitted = fit_event_model(rows, ridge=1, fit_slope=True)
    assert fitted.gradient_max < 1e-6
    assert fitted.rows == 200 and fitted.events == 80
    assert fitted.predict("FWD", 0.1) > fitted.predict("MID", 0.1) > 0.1
    before = sum(binary_log_loss(r.baseline, r.outcome) for r in rows)
    after = sum(binary_log_loss(fitted.predict(r.position, r.baseline), r.outcome) for r in rows)
    assert after < before


def test_intercept_only_matches_penalized_binomial_equation():
    rows = [EventRow("MID", 0.1, int(i < 30)) for i in range(100)]
    fitted = fit_event_model(rows, ridge=10, fit_slope=False)
    assert fitted.slope_delta == 0
    assert 100 * fitted.predict("MID", 0.1) - 30 + 10 * fitted.intercepts[2] == pytest.approx(
        0, abs=1e-6
    )
    assert fitted.intercepts[0] == 0


def test_extreme_event_rates_finite_and_deterministic():
    rows = [EventRow("GK", 0, 0)] * 100
    one = fit_event_model(rows, ridge=100, fit_slope=True)
    assert one == fit_event_model(rows, ridge=100, fit_slope=True)
    assert math.isfinite(binary_log_loss(0, 1))
    assert 0 <= one.predict("GK", 0) <= 1


def test_flagged_fallback_is_conditional_and_missing_leg_is_rejected():
    identity = {"season": "2021-22", "gw": 9, "fixture": 82, "code": 123, "position": "MID"}
    raw = {
        "season": "2021-22",
        "gw": 9,
        "cutoff": "2021-10-22T19:00:00+00:00",
        "labels_available": "2021-10-24T18:30:00+00:00",
        "records": [
            {
                **identity,
                "cold": True,
                "minutes_pmf": [0.8, 0, 0, 0.2],
                "components": {c: {"fallback": "unmeasured_prior"} for c in ("goals", "assists")},
            }
        ],
        "labels": [{**identity, "goals": 1, "assists": 1}],
    }
    saved = [
        {
            **identity,
            "p_play": 0.2,
            "components": {
                c: {"actual": 1, "arms": {"candidate": [0, 1]}} for c in ("goals", "assists")
            },
        }
    ]
    assert prepare_fold(raw, saved).rows[0]["baseline"] == pytest.approx(0.2)
    raw["labels"] = []
    with pytest.raises(ValueError, match="unique, complete and paired"):
        prepare_fold(raw, saved)
