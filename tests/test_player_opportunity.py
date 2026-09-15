"""Hand-computable, outcome-free opportunity mechanics; no retained-data fits."""

from dataclasses import asdict, fields, replace
from datetime import timedelta

import pytest

from fpl.config import (
    load_phase2_evaluation,
    load_phase3_evaluation,
    load_phase3_stage_c_assists_evaluation,
)
from fpl.models.attacking_baselines import poisson_pmf
from fpl.models.points_composition import conditional_rate
from fpl.validate import player_opportunity as model
from fpl.validate.minutes_baselines import MinuteBins
from tests import test_player_workload_minutes as fixture


def row(gw, code, *, signal=None, minutes=90, component="goals", missing_role=False):
    context = fixture.inputs(gw, code, role="Defender" if code == 1 else "Forward")
    roles = model.role_contexts(context.role_batch)
    return model.OpportunityHistoryRow(
        context.control.target,
        minutes,
        (0.09 if code == 1 else 0.9) if signal is None else signal,
        "expected_goals" if component == "goals" else "expected_assists",
        f"synthetic-archive-{component}-{gw}-{code}",
        None if missing_role else roles[model._target_key(context.control.target)],
    )


def history(component="goals"):
    return [row(gw, code, component=component) for gw in range(1, 9) for code in (1, 2)]


def fit(rows=None, component="goals", clubs=None):
    return model.fit_opportunity(
        history(component) if rows is None else rows,
        component=component,
        season="2025-26",
        gw=10,
        as_of=fixture.inputs().control.target.as_of,
        bins=MinuteBins.from_config(load_phase2_evaluation()),
        current_club=clubs or {1: 101, 2: 101},
    )


def target(code, *, rate=0.3, scale=0.6):
    source = fixture.inputs(code=code, role="Defender" if code == 1 else "Forward")
    role = model.role_contexts(source.role_batch)[model._target_key(source.control.target)]
    return model.OpportunityInput(
        source.control,
        poisson_pmf(conditional_rate(rate, 0.75, cap=scale)),
        rate,
        scale,
        role,
    )


def test_hand_computable_role_prior_player_prior_and_pool_budget():
    fitted = fit()
    assert fitted.prior_gameweeks == 8
    assert fitted.role_prior_rows == 16
    assert fitted.pooled_rate_per_minute == pytest.approx(0.0055)
    assert fitted.role_signal_sums == pytest.approx((0, 0.72, 0, 7.2))
    assert fitted.role_exposure_sums == (0, 720, 0, 720)
    assert fitted.soft_role_rates_per_minute == pytest.approx((0.0055, 0.0035, 0.0055, 0.0075))
    assert fitted.bin_means == (0, 30, 75, 90)
    prediction = model.predict_opportunity_batch(fitted, [target(1), target(2)])
    expected_rates = ((0.45 + 90 * 0.0035) / 540, (4.5 + 90 * 0.0075) / 540)
    assert [p.posterior_rate_per_minute for p in prediction] == pytest.approx(expected_rates)
    assert [p.expected_minutes for p in prediction] == [48.75, 48.75]
    assert prediction[0].unconditional_rate == pytest.approx(
        0.6 * expected_rates[0] / sum(expected_rates)
    )
    assert sum(p.unconditional_rate for p in prediction) == pytest.approx(0.6)
    assert all(p.correction_applied and p.pool_incumbent_budget == 0.6 for p in prediction)


def test_conditional_cap_is_inherited_and_loss_of_post_cap_mean_is_explicit():
    result = model.predict_opportunity_batch(fit(), [target(1), target(2)])
    assert result[1].conditional_cap_bound
    assert result[1].conditional_rate == 0.6
    assert result[1].conditional_pmf == poisson_pmf(0.6)
    assert sum(0.75 * p.conditional_rate for p in result) < 0.6
    # The pre-cap allocation budget remains conserved; no realised-count claim.
    assert sum(p.unconditional_rate for p in result) == pytest.approx(0.6)


@pytest.mark.parametrize("component", ["goals", "assists"])
def test_two_separate_candidates_share_only_the_registered_structure(component):
    result = model.predict_opportunity_batch(fit(component=component), [target(1), target(2)])
    assert all(p.identity == model.NAMES[component] for p in result)
    assert all(p.promotion_permitted is False for p in result)
    for p in result:
        assert len(p.conditional_pmf) == 11 and sum(p.conditional_pmf) == pytest.approx(1)


def test_xg_xa_source_identities_cannot_be_mixed():
    with pytest.raises(ValueError, match="cannot mix"):
        fit([*history(), row(9, 1, component="assists")])


def test_missing_recent_signal_is_not_filled_and_last_five_cap_is_exact():
    rows = history()
    rows.extend(replace(row(gw, 1), signal=None) for gw in range(9, 14))
    later = fixture.inputs(gw=15).control.target.as_of
    fitted = model.fit_opportunity(
        rows,
        component="goals",
        season="2025-26",
        gw=15,
        as_of=later,
        bins=MinuteBins.from_config(load_phase2_evaluation()),
        current_club={1: 101, 2: 101},
    )
    assert next(p for p in fitted.player_windows if p[0] == 1) == (1, 0, 0, 0)
    assert rows[-1].signal is None


def test_null_row_contributes_neither_signal_nor_minutes_but_uses_last_five_slot():
    rows = history()
    rows[-2] = replace(rows[-2], signal=None)
    fitted = fit(rows)
    player = next(p for p in fitted.player_windows if p[0] == 1)
    assert player == pytest.approx((1, 0.36, 360, 4))
    assert fitted.role_exposure_sums[1] == 630


@pytest.mark.parametrize("reason", ["cold", "role", "signal", "team", "no_play"])
def test_ineligible_player_pmf_and_rate_remain_exact_while_other_pool_can_change(reason):
    rows = history() + [row(gw, 3) for gw in range(1, 9)]
    fitted = fit(rows, clubs={1: 101, 2: 101, 3: 101})
    protected = target(3)
    if reason == "cold":
        protected = replace(
            protected,
            control=replace(protected.control, cold_start=True, price_proxy_dependent=True),
        )
    elif reason == "role":
        protected = replace(protected, role_context=None)
    elif reason == "signal":
        fitted = replace(
            fitted,
            player_windows=tuple((3, 0, 0, 0) if r[0] == 3 else r for r in fitted.player_windows),
        )
    elif reason == "team":
        # Entire uninformative side keeps its exact independent incumbent PMFs.
        protected = replace(protected, team_scale=None, unconditional_incumbent_rate=None)
        inputs = [
            replace(target(c), team_scale=None, unconditional_incumbent_rate=None) for c in (1, 2)
        ] + [protected]
        result = model.predict_opportunity_batch(fitted, inputs)
        assert all(not r.correction_applied for r in result)
        assert result[-1].conditional_pmf is protected.conditional_incumbent_pmf
        return
    else:
        protected = replace(
            protected,
            control=replace(protected.control, probabilities=(1, 0, 0, 0)),
            conditional_incumbent_pmf=poisson_pmf(0.3),
        )
    # Same unchanged team scale =0.9; eligible original budget=.6, protected budget=.3.
    inputs = [replace(target(c, scale=0.9)) for c in (1, 2)]
    protected = replace(protected, team_scale=0.9)
    result = model.predict_opportunity_batch(fitted, [*inputs, protected])
    assert result[-1].conditional_pmf is protected.conditional_incumbent_pmf
    assert result[-1].unconditional_rate == protected.unconditional_incumbent_rate
    assert not result[-1].correction_applied
    assert result[0].correction_applied and result[1].correction_applied
    assert sum(r.unconditional_rate for r in result) == pytest.approx(0.9)
    assert all(r.team_price_proxy_codes == ((3,) if reason == "cold" else ()) for r in result)


def test_no_supported_role_prior_and_disabled_correction_return_exact_incumbent():
    fitted = fit([replace(r, role_context=None) for r in history()])
    assert fitted.soft_role_rates_per_minute is None and not fitted.enabled
    inputs = [target(1), target(2)]
    for zero in (fitted, replace(fit(), enabled=False)):
        result = model.predict_opportunity_batch(zero, inputs)
        assert all(
            p.conditional_pmf is r.conditional_incumbent_pmf
            for p, r in zip(result, inputs, strict=True)
        )


def test_original_eight_gameweek_fit_minimum_not_new_eight_200_rule():
    assert fit().enabled  # 16rows sufficient;900min prior is the chosen shrinkage.
    assert not fit(history()[:-2]).enabled
    assert model.MINIMUM_PRIOR_GAMEWEEKS == 8


def test_future_truncation_whole_gw_exclusion_and_order_are_exact():
    original = fit()
    same_gw = row(10, 1)
    same_gw = replace(
        same_gw,
        target=replace(
            same_gw.target,
            kickoff=original.as_of - timedelta(days=1),
            as_of=original.as_of - timedelta(days=2),
        ),
    )
    result = fit([*reversed(history()), row(11, 1), same_gw])
    assert result == original


@pytest.mark.parametrize(("seconds", "count"), [(3600, 0), (21600, 0), (21601, 1)])
def test_historical_label_strict_six_hour_margin(seconds, count):
    prior = row(9, 1, missing_role=True)
    prior = replace(
        prior, target=replace(prior.target, kickoff=fit().as_of - timedelta(seconds=seconds))
    )
    assert fit([prior]).prior_rows == count


def test_upstream_role_future_or_wrong_target_or_conditionality_is_rejected():
    original = history()
    context = original[-1].role_context
    for changed in (
        replace(context.prediction, maximum_prior_event=original[-1].target.as_of),
        replace(context.prediction, target=replace(context.prediction.target, code=999)),
        replace(context.prediction, conditionality="actual_appearance_role"),
    ):
        altered = replace(original[-1], role_context=replace(context, prediction=changed))
        with pytest.raises(ValueError, match=r"future|identity|conditionality"):
            fit([*original[:-1], altered])


def test_original_transfer_and_season_frontier_eligibility_are_preserved():
    rows = [replace(r, role_context=None) for r in history()]
    old = replace(
        rows[0], target=replace(rows[0].target, season="2024-25", fixture=777, team_code=999)
    )
    recent_foreign = replace(rows[-2], target=replace(rows[-2].target, team_code=999))
    rows[-2] = recent_foreign
    fitted = fit([old, *rows])
    assert next(r for r in fitted.player_windows if r[0] == 1) == pytest.approx((1, 0.45, 450, 5))
    # Latest2025 season at former club is eligible; older2024 former club is not.
    assert fitted.role_prior_rows == 0


def test_independent_target_batch_order_and_dgw_legs_do_not_update_fit():
    fitted = fit()
    inputs = [target(1), target(2)]
    second = []
    for r in inputs:
        t = replace(
            r.control.target, fixture=999, kickoff=r.control.target.kickoff + timedelta(days=2)
        )
        role = replace(r.role_context, prediction=replace(r.role_context.prediction, target=t))
        second.append(replace(r, control=replace(r.control, target=t), role_context=role))
    original = asdict(fitted)
    result = model.predict_opportunity_batch(fitted, [*inputs, *second])
    reversed_result = model.predict_opportunity_batch(fitted, list(reversed([*inputs, *second])))
    assert result == tuple(reversed(reversed_result))
    assert result[0].conditional_pmf == result[2].conditional_pmf
    assert asdict(fitted) == original


def test_tampered_incumbent_pmf_fails_before_candidate_allocation():
    bad = replace(target(1), conditional_incumbent_pmf=poisson_pmf(1.0))
    with pytest.raises(ValueError, match="exactly reproduce"):
        model.predict_opportunity_batch(fit(), [bad, target(2)])


def test_marginal_pmf_is_one_appearance_gate_not_unconditional_poisson():
    conditional = poisson_pmf(0.4)
    minutes = (0.25, 0.25, 0.25, 0.25)
    pmf = model.marginal_pmf(conditional, minutes)
    assert pmf[0] == 0.25 + 0.75 * conditional[0]
    assert pmf[1:] == tuple(0.75 * p for p in conditional[1:])
    assert sum(pmf) == pytest.approx(1)
    assert pmf != poisson_pmf(0.3)


def test_no_outcome_field_in_current_prediction_inputs_and_gates_stay181():
    assert {f.name for f in fields(model.OpportunityInput)} == {
        "control",
        "conditional_incumbent_pmf",
        "unconditional_incumbent_rate",
        "team_scale",
        "role_context",
    }
    assert load_phase3_evaluation().promotion.minimum_fold_count == 181
    assert load_phase3_stage_c_assists_evaluation().promotion.minimum_fold_count == 181
    assert model.MINIMUM_GATE_FOLDS == 181 > 114 > 38
