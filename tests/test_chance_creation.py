"""Hand-computable synthetic tests; no historical candidate fitting or scoring."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from fpl.validate import chance_creation as chance
from fpl.validate.metrics import poisson_pmf
from fpl.validate.tactical_numeric_solver import fit_poisson_offset_stable


def _rows(gameweeks: int = 4) -> list[chance.ChanceObservation]:
    rows = []
    for gw in range(1, gameweeks + 1):
        kickoff = datetime(2025, 1, 1, tzinfo=UTC) + timedelta(days=7 * gw)
        for team, other, home in ((1, 2, True), (2, 1, False)):
            rows.append(
                chance.ChanceObservation(
                    season="2025-26",
                    gw=gw,
                    fixture=gw,
                    team_code=team,
                    opponent_team_code=other,
                    was_home=home,
                    kickoff=kickoff,
                    as_of=kickoff,
                    goals=1,
                    shots=10,
                    expected_goals=2.0,
                    predicted_state=(0.3, 1.0, 0.5, 0.3, -2.0),
                    predicted_opponent_state=(0.3, 1.0, 0.5, 0.3, -2.0),
                    incumbent_rate=1.0,
                    opponent_incumbent_rate=1.0,
                    incumbent_pmf=poisson_pmf(1.0),
                    maximum_state_source_event=kickoff - timedelta(days=1),
                    maximum_style_training_event=kickoff - timedelta(days=1),
                )
            )
    return rows


@pytest.fixture
def small_history(monkeypatch: pytest.MonkeyPatch) -> None:
    # Lower counts ONLY on synthetic data to expose every transition by GW3.
    monkeypatch.setattr(chance, "MINIMUM_FIT_ROWS", 2)
    monkeypatch.setattr(chance, "MINIMUM_CONVERSION_ROWS", 2)


def test_contract_pins_are_fixed() -> None:
    assert chance.RIDGE == 1.0
    assert chance.MINIMUM_FIT_ROWS == chance.MINIMUM_CONVERSION_ROWS == 160
    assert chance.CONVERSION_PRIOR_EXPOSURE == 20.0
    assert chance.QUALITY_FLOOR == 1e-6
    assert chance.QUALITY_CEILING == 1.0
    assert chance.RATE_FLOOR == 0.05
    assert chance.MAX_GOALS == 10


def test_fractional_intercept_optimum_is_hand_computable() -> None:
    # exp(-.25+beta)-1.25+beta=0 has beta=.25, curvature=2.
    model = chance.fit_fractional_poisson_mean([[], []], [1.25, 1.25], [math.exp(-0.25)] * 2, 1.0)
    assert model.coefficients == pytest.approx((0.25,), abs=1e-9)
    assert model.objective == pytest.approx(1.03125)
    assert model.predict_mean([], math.exp(-0.25)) == pytest.approx(1.0)
    assert model.predict_mean([], 2 * math.exp(-0.25)) == pytest.approx(2.0)
    assert model.final_gradient == pytest.approx((0.0,), abs=1e-9)
    assert model.diagnostics[-1].gradient_infinity_norm <= model.diagnostics[-1].gradient_tolerance
    assert model.diagnostics[-1].newton_step_infinity_norm <= model.diagnostics[-1].step_tolerance
    json.dumps(asdict(model), allow_nan=False)


def test_integer_targets_reproduce_existing_numeric_optimum() -> None:
    x, y, offsets = [[-1.0], [1.0]], [0, 3], [1.2, 1.0]
    old = fit_poisson_offset_stable(x, y, offsets, 1.0)
    new = chance.fit_fractional_poisson_mean(x, [float(v) for v in y], offsets, 1.0)
    assert new.coefficients == old.coefficients
    assert new.scaler == old.scaler
    assert new.objective == old.objective
    assert new.diagnostics == old.diagnostics


def test_fractional_labels_and_zero_are_not_rounded_or_imputed() -> None:
    targets = [0.0, 0.25, 0.0, 0.5]
    model = chance.fit_fractional_poisson_mean([[0.0]] * 4, targets, [1.0] * 4, 1.0)
    zero = chance.fit_fractional_poisson_mean([[0.0]] * 4, [0.0] * 4, [1.0] * 4, 1.0)
    assert model.coefficients != zero.coefficients
    assert targets == [0.0, 0.25, 0.0, 0.5]
    assert model.coefficients[1] == 0.0


def test_exposure_quasi_likelihood_gradient_independently() -> None:
    x = [[-1.0], [1.0]]
    targets, offsets = [0.25, 1.75], [2.0, 8.0]
    model = chance.fit_fractional_poisson_mean(x, targets, offsets, 1.0)

    def objective(beta: list[float]) -> float:
        eta = [math.log(o) + beta[0] + row[0] * beta[1] for row, o in zip(x, offsets, strict=True)]
        return (
            sum(math.exp(e) - y * e for e, y in zip(eta, targets, strict=True)) / 2
            + sum(b * b for b in beta) / 2
        )

    for j in range(2):
        plus, minus = list(model.coefficients), list(model.coefficients)
        plus[j] += 1e-5
        minus[j] -= 1e-5
        assert (objective(plus) - objective(minus)) / 2e-5 == pytest.approx(
            model.final_gradient[j], abs=1e-9
        )
        assert objective(plus) > model.objective
        assert objective(minus) > model.objective


@pytest.mark.parametrize("target", [-1.0, math.nan, math.inf, -math.inf, True])
def test_invalid_fractional_target_fails_closed(target: float) -> None:
    with pytest.raises(ValueError, match="targets"):
        chance.fit_fractional_poisson_mean([[]], [target], [1.0], 1.0)


@pytest.mark.parametrize("offset", [0.0, -1.0, math.nan, math.inf, True, math.exp(21)])
def test_invalid_exposure_fails_closed(offset: float) -> None:
    with pytest.raises(ValueError, match="offset"):
        chance.fit_fractional_poisson_mean([[]], [0.25], [offset], 1.0)


@pytest.mark.parametrize("penalty", [0.0, -1.0, math.nan, math.inf])
def test_invalid_penalty_fails_closed(penalty: float) -> None:
    with pytest.raises(ValueError, match="penalty"):
        chance.fit_fractional_poisson_mean([[]], [0.25], [1.0], penalty)


def test_bad_shape_and_nonfinite_predictors_fail_closed() -> None:
    with pytest.raises(ValueError, match="empty"):
        chance.fit_fractional_poisson_mean([], [], [], 1.0)
    with pytest.raises(ValueError, match="width"):
        chance.fit_fractional_poisson_mean([[1.0], []], [0.2, 0.3], [1.0, 1.0], 1.0)
    with pytest.raises(ValueError, match="finite"):
        chance.fit_fractional_poisson_mean([[math.nan]], [0.2], [1.0], 1.0)
    with pytest.raises(ValueError, match="match"):
        chance.fit_fractional_poisson_mean([[]], [], [1.0], 1.0)


def test_bounded_failure_retains_numeric_certificate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chance, "MAX_ITERATIONS", 0)
    with pytest.raises(chance.ChanceMeanFitError, match="iteration limit") as error:
        chance.fit_fractional_poisson_mean([[]], [0.25], [1.0], 1.0)
    assert error.value.state["solver"] == chance.SOLVER_ID
    assert error.value.state["gradient"] == (0.75,)
    assert error.value.state["iteration"] == 0
    assert error.value.state["newton_decrement_squared"] > 0
    json.dumps(error.value.state, allow_nan=False)


def test_bounded_backtracking_failure_is_not_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chance, "MAX_BACKTRACKS", 0)
    with pytest.raises(chance.ChanceMeanFitError, match="backtracking") as error:
        chance.fit_fractional_poisson_mean([[]], [0.25], [1.0], 1.0)
    assert error.value.state["backtracking"] == []


def test_predictor_has_only_13_prematch_fields() -> None:
    row = _rows(1)[0]
    x = chance.predictors(row)
    assert x is not None and len(x) == 13
    assert x[-3:] == [1.0, 0.0, 0.0]
    assert chance.predictors(replace(row, shots=99, expected_goals=22.2, goals=9)) == x
    assert chance.predictors(replace(row, predicted_state=(None, 1.0, 0.5, 0.3, -2.0))) is None


def test_insufficient_history_returns_exact_incumbent_object() -> None:
    inputs = _rows(2)
    output = chance.run_chance_walk_forward(inputs, ("2025-26",))
    for original, row in zip(inputs, output["rows"], strict=True):
        assert row["distributions"]["candidate"] is original.incumbent_pmf
        assert row["incumbent_fallback"]
        assert row["evidence_class"] == "retrospective_backfill_development"


@pytest.mark.usefixtures("small_history")
def test_hand_computable_volume_quality_conversion_chain() -> None:
    output = chance.run_chance_walk_forward(_rows(3), ("2025-26",))
    gw2, gw3 = output["rows"][2], output["rows"][4]
    assert gw2["predicted_shots"] == pytest.approx(10.0)
    assert gw2["predicted_quality"] == pytest.approx(0.2)
    assert gw2["predicted_xg"] == pytest.approx(2.0)
    assert gw2["conversion"] is None
    assert gw2["incumbent_fallback"]
    # Only the two GW2 OOS chance predictions are calibration exposures.
    assert gw3["conversion"] == pytest.approx((2 + 20) / (4 + 20))
    assert gw3["candidate_latent_rate"] == pytest.approx(2 * 22 / 24)
    assert not gw3["incumbent_fallback"]
    attribution = gw3["log_rate_attribution"]
    assert sum(
        attribution[k] for k in ("volume", "quality", "conversion", "floor_adjustment")
    ) == pytest.approx(math.log(gw3["candidate_latent_rate"]))
    assert sum(gw3["distributions"]["candidate"]) == pytest.approx(1.0)
    assert len(gw3["distributions"]["candidate"]) == 11


@pytest.mark.usefixtures("small_history")
def test_same_gw_targets_cannot_affect_any_prediction_but_next_gw_can() -> None:
    inputs = _rows(4)
    first = chance.run_chance_walk_forward(inputs, ("2025-26",))
    changed = [
        replace(r, shots=30, expected_goals=4.0, goals=4) if r.gw == 2 else r for r in inputs
    ]
    second = chance.run_chance_walk_forward(changed, ("2025-26",))
    for a, b in zip(first["rows"], second["rows"], strict=True):
        if a["gw"] <= 2:
            for key in ("distributions", "predicted_shots", "predicted_quality", "conversion"):
                assert a[key] == b[key]
    assert first["rows"][4]["predicted_shots"] != second["rows"][4]["predicted_shots"]
    assert first["historical_folds"][1]["stage_fits"]["volume"]["training_rows"] == 2
    assert first["historical_folds"][2]["stage_fits"]["volume"]["training_rows"] == 4


@pytest.mark.usefixtures("small_history")
def test_future_truncation_and_determinism() -> None:
    full = chance.run_chance_walk_forward(_rows(5), ("2025-26",))
    short = chance.run_chance_walk_forward(_rows(3), ("2025-26",))
    assert full["rows"][:6] == short["rows"]
    assert full["historical_folds"][:3] == short["historical_folds"]
    assert short == chance.run_chance_walk_forward(_rows(3), ("2025-26",))


@pytest.mark.usefixtures("small_history")
def test_delayed_dgw_leg_is_batched_and_excluded_until_event() -> None:
    inputs = _rows(4)
    gw1 = inputs[0].as_of
    delayed = [
        replace(r, fixture=100, gw=1, as_of=gw1, kickoff=gw1 + timedelta(days=10))
        for r in inputs[:2]
    ]
    out = chance.run_chance_walk_forward(inputs + delayed, ("2025-26",))
    fold1, fold2, fold3 = out["historical_folds"][:3]
    assert fold1["target_rows"] == 4
    assert fold2["stage_fits"]["volume"]["training_rows"] == 2
    assert fold3["stage_fits"]["volume"]["training_rows"] == 6
    delayed_predictions = [r for r in out["history_rows"] if r["fixture"] == 100]
    assert all(
        r["as_of"] == gw1.isoformat() and r["predicted_shots"] is None for r in delayed_predictions
    )


@pytest.mark.usefixtures("small_history")
def test_zero_shots_and_missing_shots_have_different_training_population() -> None:
    zero_rows = [replace(r, shots=0, expected_goals=0.0) if r.gw == 1 else r for r in _rows(3)]
    null_rows = [replace(r, shots=None, expected_goals=None) if r.gw == 1 else r for r in _rows(3)]
    zero = chance.run_chance_walk_forward(zero_rows, ("2025-26",))
    missing = chance.run_chance_walk_forward(null_rows, ("2025-26",))
    assert zero["rows"][0]["observed_shots"] == 0
    assert missing["rows"][0]["observed_shots"] is None
    assert zero["folds"][1]["stage_fits"]["volume"]["training_rows"] == 2
    assert missing["folds"][1]["stage_fits"]["volume"]["training_rows"] == 0
    assert zero["folds"][1]["stage_fits"]["quality"]["training_rows"] == 0


@pytest.mark.usefixtures("small_history")
def test_null_tactical_forecast_uses_incumbent_without_imputation() -> None:
    inputs = [
        replace(r, predicted_state=(None,) * 5, predicted_opponent_state=(None,) * 5)
        if r.gw == 3
        else r
        for r in _rows(4)
    ]
    out = chance.run_chance_walk_forward(inputs, ("2025-26",))
    assert out["rows"][4]["predictors"] is None
    assert out["rows"][4]["incumbent_fallback"]
    assert out["folds"][3]["stage_fits"]["volume"]["training_rows"] == 4


@pytest.mark.usefixtures("small_history")
def test_no_future_normalization_and_season_boundary_preserves_codes() -> None:
    inputs = _rows(4)
    inputs = [replace(r, season="2026-27", gw=r.gw - 2) if r.gw > 2 else r for r in inputs]
    out = chance.run_chance_walk_forward(inputs, ("2025-26", "2026-27"))
    assert {r["team_code"] for r in out["rows"]} == {1, 2}
    model = out["folds"][2]["stage_fits"]["volume"]["model"]
    assert model["scaler"]["means"] == pytest.approx(
        (0.3, 1, 0.5, 0.3, -2, 0.3, 1, 0.5, 0.3, -2, 0.5, 0, 0)
    )
    assert model["training_rows"] == 4


@pytest.mark.usefixtures("small_history")
def test_cs_is_exact_opponent_pmf_zero() -> None:
    out = chance.run_chance_walk_forward(_rows(4), ("2025-26",))
    by = {r["key"]: r for r in out["rows"]}
    for row in out["rows"]:
        other = by[f"{row['season']}:{row['fixture']}:{row['opponent_team_code']}"]
        for arm in ("candidate", "incumbent"):
            assert row["clean_sheet_probabilities"][arm] == other["distributions"][arm][0]


@pytest.mark.parametrize(
    "kind", ["as_of", "source", "fit", "naive", "duplicate", "mirror", "xg", "zero_exposure", "pmf"]
)
def test_invalid_history_fails_closed(kind: str) -> None:
    rows = _rows(1)
    first = rows[0]
    changes: dict[str, dict[str, Any]] = {
        "as_of": {"as_of": first.kickoff + timedelta(seconds=1)},
        "source": {"maximum_state_source_event": first.as_of},
        "fit": {"maximum_style_training_event": first.as_of},
        "naive": {"kickoff": first.kickoff.replace(tzinfo=None)},
        "mirror": {"opponent_team_code": 999},
        "xg": {"expected_goals": -1.0},
        "zero_exposure": {"shots": 0},
        "pmf": {"incumbent_pmf": (0.1,) * 11},
    }
    if kind == "duplicate":
        rows.append(first)
    else:
        rows[0] = replace(first, **changes[kind])
    with pytest.raises(
        ValueError, match=r"required|future|aware|reciprocal|nonnegative|contradictory"
    ):
        chance.run_chance_walk_forward(rows, ("2025-26",))


@pytest.mark.usefixtures("small_history")
def test_target_event_cannot_enter_same_batch_style_fit() -> None:
    rows = _rows(3)
    rows[3] = replace(rows[3], maximum_style_training_event=rows[2].kickoff)
    with pytest.raises(ValueError, match="future"):
        chance.run_chance_walk_forward(rows, ("2025-26",))


@pytest.mark.usefixtures("small_history")
def test_checkpoint_cannot_mutate_training_state() -> None:
    expected = chance.run_chance_walk_forward(_rows(3), ("2025-26",))

    def malicious(report: dict[str, Any]) -> None:
        for row in report["rows"]:
            row["predicted_xg"] = 999999

    actual = chance.run_chance_walk_forward(_rows(3), ("2025-26",), checkpoint=malicious)
    assert expected == actual


@pytest.mark.usefixtures("small_history")
def test_stage_failure_propagates_with_fold_context(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise chance.ChanceMeanFitError("synthetic failure", {"iteration": 0})

    monkeypatch.setattr(chance, "fit_fractional_poisson_mean", fail)
    with pytest.raises(chance.ChanceMeanFitError) as error:
        chance.run_chance_walk_forward(_rows(2), ("2025-26",))
    assert any("stage=volume" in note for note in error.value.__notes__)
    assert any("gw=2" in note for note in error.value.__notes__)


def test_diagnostic_quality_is_exposure_weighted_without_zero_fill() -> None:
    rows = [
        {
            "predicted_shots": 10.0,
            "observed_shots": 10,
            "predicted_xg": 2.0,
            "observed_archive_xg": 1.0,
            "predicted_quality": 0.2,
        },
        {
            "predicted_shots": 20.0,
            "observed_shots": 20,
            "predicted_xg": 2.0,
            "observed_archive_xg": 4.0,
            "predicted_quality": 0.1,
        },
        {
            "predicted_shots": 10.0,
            "observed_shots": None,
            "predicted_xg": 2.0,
            "observed_archive_xg": None,
            "predicted_quality": 0.2,
        },
    ]
    report = chance.chance_target_metrics(rows)
    assert report["volume"]["rows"] == 2
    assert report["volume"]["mae"] == 0.0
    assert report["quality"]["shot_exposure"] == 30
    assert report["quality"]["exposure_weighted_mae"] == pytest.approx(0.1)
    assert report["xg"]["mae"] == pytest.approx(1.5)


@pytest.mark.parametrize(
    ("targets", "offsets"),
    [
        ([0.0, 0.0], [math.exp(20), math.exp(20)]),
        ([1e8, 1e8], [1.0, 1.0]),
        ([0.125, 0.375], [math.exp(-20), math.exp(-20)]),
        ([0.0, 50.125], [0.01, 30.0]),
    ],
)
def test_synthetic_extreme_offsets_targets_certify_bounded_convergence(
    targets: list[float], offsets: list[float]
) -> None:
    fit = chance.fit_fractional_poisson_mean([[-1.0], [1.0]], targets, offsets, 1.0)
    assert fit == chance.fit_fractional_poisson_mean([[-1.0], [1.0]], targets, offsets, 1.0)
    assert fit.iterations <= 40
    assert len(fit.diagnostics) == fit.iterations + 1
    final = fit.diagnostics[-1]
    assert final.gradient_infinity_norm <= final.gradient_tolerance
    assert final.newton_step_infinity_norm <= final.step_tolerance
    for step in fit.diagnostics[:-1]:
        assert step.accepted_fraction is not None
        assert 0 < step.accepted_fraction <= 1
        assert 1 <= step.backtracking_trials <= 30
        assert step.objective_difference is not None and step.armijo_bound is not None
        assert step.objective_difference <= step.armijo_bound < 0
        assert -20 <= step.eta_minimum <= step.eta_maximum <= 20
    json.dumps(asdict(fit), allow_nan=False)


def test_collinear_large_scale_synthetic_features_remain_fold_local_and_regularized() -> None:
    x = [[1e12 + i * 100, 1e12 + i * 100, 7.0] for i in range(20)]
    y = [0.125 * (i % 7) for i in range(20)]
    fit = chance.fit_fractional_poisson_mean(x, y, [0.5] * 20, 1.0)
    assert fit.coefficients[1] == pytest.approx(fit.coefficients[2], abs=1e-14)
    assert fit.coefficients[3] == 0.0
    assert fit.scaler.means == (1e12 + 950, 1e12 + 950, 7.0)
    assert fit.scaler.scales[2] == 1.0
    assert fit.diagnostics[-1].gradient_infinity_norm <= fit.diagnostics[-1].gradient_tolerance


@pytest.mark.usefixtures("small_history")
def test_conversion_cannot_see_target_gw_or_delayed_future_goal() -> None:
    rows = _rows(4)
    first = chance.run_chance_walk_forward(rows, ("2025-26",))
    changed = [replace(r, goals=9) if r.gw == 3 else r for r in rows]
    second = chance.run_chance_walk_forward(changed, ("2025-26",))
    assert first["rows"][4]["conversion"] == second["rows"][4]["conversion"]
    assert first["rows"][6]["conversion"] != second["rows"][6]["conversion"]
    assert (
        first["folds"][2]["conversion_fit"]["maximum_training_event"] < first["folds"][2]["as_of"]
    )


@pytest.mark.usefixtures("small_history")
def test_new_team_without_measured_style_keeps_exact_default_fallback() -> None:
    rows = _rows(3)
    new = []
    for row in rows:
        if row.gw == 3:
            if row.team_code == 1:
                row = replace(row, team_code=99, predicted_state=(None,) * 5)
            else:
                row = replace(row, opponent_team_code=99, predicted_opponent_state=(None,) * 5)
        new.append(row)
    result = chance.run_chance_walk_forward(new, ("2025-26",))
    newcomer = next(row for row in result["rows"] if row["team_code"] == 99)
    assert newcomer["incumbent_fallback"]
    assert newcomer["distributions"]["candidate"] is new[4].incumbent_pmf
