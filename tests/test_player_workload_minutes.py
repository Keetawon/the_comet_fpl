"""Pure synthetic offset/temporal proofs, never fit the retained historical archive."""

from dataclasses import asdict, fields, replace
from datetime import UTC, datetime, timedelta

import pytest
import yaml

from fpl.config import repo_root
from fpl.validate import player_workload_minutes as model
from fpl.validate.competitive_workload_view import (
    CompetitiveFixture,
    CompetitiveFixtureKey,
    CompetitiveMatchVersion,
    ObservedPlayerIdentity,
    RetrospectiveCompetitiveWorkloadView,
    WorkloadObservation,
)
from fpl.validate.player_role_history import RoleHistoryRow, RoleTarget, forecast_role_batch

ORIGIN = datetime(2025, 8, 1, tzinfo=UTC)
KNOWN = datetime(2026, 9, 7, tzinfo=UTC)


def inputs(gw=10, code=1, *, volume=90.0, role="Defender", hours=48, verified_end=False):
    cutoff = ORIGIN + timedelta(days=7 * gw)
    target = RoleTarget("2025-26", gw, gw, code, 101, cutoff, cutoff, "synthetic-roster")
    target_key = CompetitiveFixtureKey("pl_sdp", 8, "2025-26", 70000 + gw)
    excluded = frozenset({target_key})
    source_key = CompetitiveFixtureKey("pl_sdp", 5, "2025-26", 40000 + gw)
    kickoff = cutoff - timedelta(hours=hours)
    fixture = CompetitiveFixture(
        source_key, kickoff, frozenset({101, 102}), True, frozenset({3, 4}), ((3, 101), (4, 102))
    )
    version = CompetitiveMatchVersion(
        fixture,
        f"synthetic-{gw}-{code}",
        KNOWN,
        "synthetic-version",
        KNOWN,
        "a" * 64,
        True,
        (WorkloadObservation(10000 + code, code, 101, volume, volume != 0, True, (), 3),),
        False,
        None,
        kickoff + timedelta(hours=1) if verified_end else None,
    )
    view = RetrospectiveCompetitiveWorkloadView(
        interpretation_id="synthetic-version",
        fixtures=(fixture,),
        versions=(version,),
        catalogue_coverage=(),
        memberships=(),
    )
    workload = view.observed_participation_snapshot(
        identity=ObservedPlayerIdentity(code, 10000 + code, "exact-synthetic-opta", KNOWN),
        scope_team_codes=frozenset({101, 102}),
        as_of=cutoff,
        excluded_target_gw_fixtures=excluded,
    )
    role_history = [
        RoleHistoryRow(
            "2025-26",
            5,
            50000 + gw,
            None,
            code,
            101,
            cutoff - timedelta(days=4),
            True,
            True,
            role,
            10000 + code,
            f"p{10000 + code}",
            "exact-synthetic-opta",
            f"synthetic-role-{gw}-{code}",
            "b" * 64,
            KNOWN,
            KNOWN,
        )
    ]
    role_batch = forecast_role_batch(role_history, [target])
    control = model.PrequentialMinutesControl(
        target,
        (0.25, 0.25, 0.25, 0.25),
        cutoff - timedelta(days=1),
        "c" * 64,
        "d" * 64,
        False,
        False,
        '{"source":"synthetic-retained-selector"}',
    )
    return model.WorkloadMinutesInput(control, workload, role_batch, target_key, excluded)


def history(*, batches=8, rows_per_batch=25):
    return [
        model.WorkloadMinutesObservation(inputs(gw, code), 0)
        for gw in range(1, batches + 1)
        for code in range(1, rows_per_batch + 1)
    ]


@pytest.fixture(scope="module")
def fitted():
    target = inputs()
    fit = model.fit_minutes_correction(
        history(), season="2025-26", gw=10, as_of=target.control.target.as_of
    )
    return fit, target


def test_four_hand_computable_bounded_features():
    row = inputs()
    evidence = model.workload_role_features(row)
    assert evidence.features == (0.0, 0.5, 0.0, 0.0)
    assert evidence.witnessed_nominal_minutes_lower_bound == 90
    assert evidence.role_probabilities == (0, 1, 0, 0)
    assert evidence.completion_time_proxy is True
    assert "continuous_player_membership_unproved" in evidence.unknown_workload_reasons
    # Those unknowns remain; positive observed volume is not claimed to be exact/rested.
    assert row.workload.exact_player_rest_hours is None
    assert model.workload_role_features(inputs(volume=120)).features == (0, 2 / 3, 0, 0)


def test_volume_cap_is_feature_transform_not_source_imputation():
    row = inputs(volume=120)
    first = row.workload.selected_versions[0]
    second_fixture = replace(
        first.fixture,
        key=replace(first.fixture.key, match_id=99),
        kickoff=first.fixture.kickoff - timedelta(days=1),
    )
    second = replace(first, fixture=second_fixture, capture_id="another-capture")
    window = next(w for w in row.workload.windows if w.hours == 168)
    window = replace(
        window,
        nominal_minutes_lower_bound=240,
        witnessed_fixtures=(*window.witnessed_fixtures, second_fixture.key),
    )
    changed = replace(
        row,
        workload=replace(
            row.workload,
            selected_versions=(first, second),
            windows=tuple(window if w.hours == 168 else w for w in row.workload.windows),
        ),
    )
    evidence = model.workload_role_features(changed)
    assert evidence.features == (0, 1, 0, 0)
    assert evidence.witnessed_nominal_minutes_lower_bound == 240
    assert first.observations[0].nominal_minutes == 120


def test_hand_computable_offset_gradient_and_first_step():
    import math

    rows = [((0.0, 0.5, 0.0, 0.0), (0.25,) * 4, 0)]
    objective, gradient = model._objective_gradient(rows, model.ZERO_COEFFICIENTS)
    assert objective == pytest.approx(math.log(4))
    assert gradient == ((0, 0.125, 0, 0),) * 3
    beta = tuple(tuple(-model.STEP_SIZE * g for g in r) for r in gradient)
    pmf = model._probabilities(rows[0][1], rows[0][0], beta)
    assert pmf[0] == pytest.approx(1 / (1 + 3 * math.exp(-1 / 24)))
    assert pmf[0] > 0.25


def test_objective_gradient_matches_finite_differences():
    rows = [((0.1, 0.2, 0.3, 0.4), (0.1, 0.2, 0.3, 0.4), 1)]
    beta = ((0.2, -0.1, 0.3, -0.2), (0.1,) * 4, (-0.1,) * 4)
    _, gradient = model._objective_gradient(rows, beta)
    for k in range(3):
        for j in range(4):
            plus, minus = [list(r) for r in beta], [list(r) for r in beta]
            plus[k][j] += 1e-6
            minus[k][j] -= 1e-6
            left = model._objective_gradient(rows, tuple(tuple(r) for r in plus))[0]
            right = model._objective_gradient(rows, tuple(tuple(r) for r in minus))[0]
            assert gradient[k][j] == pytest.approx((left - right) / 2e-6, abs=1e-9)


def test_synthetic_witnessed_context_changes_pmf_with_fixed_converged_solver(fitted):
    fit, target = fitted
    assert fit.enabled and fit.eligible_rows == 200 and fit.eligible_batches == 8
    assert fit.final_gradient_inf <= model.GRADIENT_TOLERANCE
    assert fit.iterations < model.MAX_ITERATIONS
    assert all(
        b <= a + 1e-14 for a, b in zip(fit.objective_trace, fit.objective_trace[1:], strict=False)
    )
    prediction = model.predict_minutes_batch(fit, [target])[0]
    assert prediction.correction_applied
    assert prediction.probabilities[0] > target.control.probabilities[0]
    larger = model.predict_minutes_batch(fit, [inputs(volume=120)])[0]
    assert larger.probabilities[0] > prediction.probabilities[0]
    assert len(prediction.probabilities) == 4
    assert sum(prediction.probabilities) == pytest.approx(1, abs=1e-14)
    assert fit.promotion_permitted is False and fit.synthesis_eligible is False


@pytest.mark.parametrize(
    "reason", ["workload", "role", "identity", "cold", "support", "zero_volume", "role_cold"]
)
def test_missing_or_unlicensed_context_returns_exact_control_object(fitted, reason):
    fit, target = fitted
    if reason == "workload":
        target = replace(target, workload=None)
    elif reason == "role":
        target = replace(target, role_batch=None)
    elif reason == "identity":
        target = replace(target, target_provider_fixture=None)
    elif reason == "cold":
        target = replace(
            target, control=replace(target.control, cold_start=True, price_proxy_dependent=True)
        )
    elif reason == "support":
        target = replace(
            target, control=replace(target.control, probabilities=(0.0, 0.25, 0.25, 0.5))
        )
    elif reason == "zero_volume":
        target = inputs(volume=0)
    else:
        target = replace(target, role_batch=forecast_role_batch([], [target.control.target]))
    result = model.predict_minutes_batch(fit, [target])[0]
    assert result.probabilities is target.control.probabilities
    assert result.correction_applied is False
    assert result.fallback_reason is not None


def test_disabled_and_effectively_zero_correction_are_bit_exact(fitted):
    fit, target = fitted
    for zero in (replace(fit, enabled=False), replace(fit, coefficients=model.ZERO_COEFFICIENTS)):
        assert (
            model.predict_minutes_batch(zero, [target])[0].probabilities
            is target.control.probabilities
        )
    forward = inputs(role="Forward")  # No forward coefficient fitted in this synthetic sample.
    prediction = model.predict_minutes_batch(fit, [forward])[0]
    assert prediction.probabilities is forward.control.probabilities


@pytest.mark.parametrize(("batches", "rows"), [(7, 30), (8, 24)])
def test_both_minimum_history_requirements_are_mandatory(batches, rows):
    target = inputs()
    fit = model.fit_minutes_correction(
        history(batches=batches, rows_per_batch=rows),
        season="2025-26",
        gw=10,
        as_of=target.control.target.as_of,
    )
    assert fit.enabled is False
    assert fit.coefficients == model.ZERO_COEFFICIENTS
    assert (
        model.predict_minutes_batch(fit, [target])[0].probabilities is target.control.probabilities
    )


def test_no_eligible_features_has_no_fit_and_keeps_all_prior_counts():
    target = inputs()
    rows = [replace(r, predictors=replace(r.predictors, workload=None)) for r in history()]
    fit = model.fit_minutes_correction(
        rows, season="2025-26", gw=10, as_of=target.control.target.as_of
    )
    assert (fit.prior_rows, fit.eligible_rows, fit.eligible_batches) == (200, 0, 0)
    assert fit.objective_trace == ()
    assert fit.fallback_counts == (("positive_workload_unavailable", 200),)


def test_future_truncation_same_gw_exclusion_and_row_order_are_identical(fitted):
    fit, target = fitted
    same_gw = inputs(gw=10, code=501)
    early = replace(
        same_gw.control.target,
        kickoff=target.control.target.as_of - timedelta(hours=1),
        as_of=target.control.target.as_of - timedelta(days=1),
    )
    same_gw = replace(
        same_gw,
        control=replace(
            same_gw.control, target=early, maximum_prior_event=early.as_of - timedelta(days=1)
        ),
    )
    augmented = [
        *history(),
        model.WorkloadMinutesObservation(inputs(gw=11), 3),
        model.WorkloadMinutesObservation(same_gw, 3),
    ]
    result = model.fit_minutes_correction(
        list(reversed(augmented)), season="2025-26", gw=10, as_of=target.control.target.as_of
    )
    assert result == fit


def test_duplicate_training_player_fixture_rejected(fitted):
    _fit, target = fitted
    rows = history()
    with pytest.raises(ValueError, match="duplicate historical"):
        model.fit_minutes_correction(
            [*rows, rows[0]], season="2025-26", gw=10, as_of=target.control.target.as_of
        )


@pytest.mark.parametrize(
    "defect",
    [
        "role_future",
        "role_cutoff",
        "role_identity",
        "workload_future",
        "workload_total",
        "workload_identity",
        "exclusion",
    ],
)
def test_upstream_in_sample_future_identity_and_aggregate_errors_fail_closed(fitted, defect):
    _fit, target = fitted
    if defect.startswith("role"):
        role = target.role_batch.predictions[0]
        if defect == "role_future":
            role = replace(role, maximum_prior_event=target.control.target.as_of)
        elif defect == "role_identity":
            role = replace(role, target=replace(role.target, code=999))
        roles = replace(target.role_batch, predictions=(role,))
        if defect == "role_cutoff":
            roles = replace(roles, as_of=roles.as_of + timedelta(seconds=1))
        target = replace(target, role_batch=roles)
    elif defect == "workload_future":
        version = target.workload.selected_versions[0]
        version = replace(version, verified_end_at=target.control.target.as_of)
        target = replace(target, workload=replace(target.workload, selected_versions=(version,)))
    elif defect == "workload_total":
        target = replace(
            target,
            workload=replace(
                target.workload,
                windows=tuple(
                    replace(w, nominal_minutes_lower_bound=91) if w.hours == 168 else w
                    for w in target.workload.windows
                ),
            ),
        )
    elif defect == "workload_identity":
        target = replace(target, workload=replace(target.workload, code=999))
    else:
        target = replace(
            target, workload=replace(target.workload, excluded_target_gw_fixtures=frozenset())
        )
    with pytest.raises(ValueError, match=r"role|workload|cutoff|lower-bound|target|identity"):
        model.workload_role_features(target)


def test_no_clock_proxy_before_six_hours_but_verified_end_can_license_positive_witness():
    assert model.workload_role_features(inputs(hours=6)).features is None
    assert model.workload_role_features(inputs(hours=2, verified_end=True)).features == (
        0,
        0.5,
        0,
        0,
    )


def test_dgw_legs_use_one_fit_and_same_upstream_state(fitted):
    fit, first = fitted
    original_fit = asdict(fit)
    second_target = replace(
        first.control.target, fixture=999, kickoff=first.control.target.kickoff + timedelta(days=2)
    )
    second_key = replace(first.target_provider_fixture, match_id=99999)
    excluded = first.target_gw_provider_fixtures | {second_key}
    workload = replace(first.workload, excluded_target_gw_fixtures=excluded)
    roles = forecast_role_batch(
        first.role_batch.predictions[0].recent_sources, [first.control.target, second_target]
    )
    first = replace(
        first, workload=workload, role_batch=roles, target_gw_provider_fixtures=excluded
    )
    second = replace(
        first,
        control=replace(first.control, target=second_target),
        target_provider_fixture=second_key,
    )
    before = model.predict_minutes_batch(fit, [first, second])
    after = model.predict_minutes_batch(fit, [second, first])
    assert before == tuple(reversed(after))
    assert before[0].probabilities == before[1].probabilities
    assert asdict(fit) == original_fit  # Never absorb either target result.
    with pytest.raises(ValueError, match="same entire"):
        model.predict_minutes_batch(
            fit, [first, replace(second, target_gw_provider_fixtures=frozenset({second_key}))]
        )


def test_nonconvergence_is_failure_not_silent_baseline_or_retuning(monkeypatch):
    monkeypatch.setattr(model, "MAX_ITERATIONS", 0)
    with pytest.raises(ValueError, match="did not converge"):
        model.fit_minutes_correction(
            history(), season="2025-26", gw=10, as_of=inputs().control.target.as_of
        )


def test_predictor_interface_contains_no_target_minutes_or_role_label():
    assert {f.name for f in fields(model.WorkloadMinutesInput)} == {
        "control",
        "workload",
        "role_batch",
        "target_provider_fixture",
        "target_gw_provider_fixtures",
    }
    assert "observed_bin" not in {f.name for f in fields(model.PrequentialMinutesControl)}


def test_stage_b_181_fold_requirement_stays_unchanged():
    config = yaml.safe_load((repo_root() / "config/phase2_evaluation.yaml").read_bytes())
    assert config["promotion"]["minimum_fold_count"] == model.STAGE_B_MINIMUM_FOLDS == 181
    assert 38 < 114 < model.STAGE_B_MINIMUM_FOLDS


@pytest.mark.parametrize("label", [True, 1.0, -1, 4])
def test_observed_bin_is_an_exact_discrete_label(label):
    with pytest.raises(ValueError, match="fixed bins"):
        model.WorkloadMinutesObservation(inputs(), label)


def test_control_requires_immutable_probabilities_and_prior_only_fit():
    control = inputs().control
    with pytest.raises(ValueError, match="immutable"):
        replace(control, probabilities=list(control.probabilities))
    with pytest.raises(ValueError, match="target/future"):
        replace(control, maximum_prior_event=control.target.as_of)


@pytest.mark.parametrize("field", ["payload_sha256", "capture_id", "interpretation_id"])
def test_original_workload_capture_provenance_cannot_be_dropped(field):
    row = inputs()
    version = replace(row.workload.selected_versions[0], **{field: ""})
    row = replace(row, workload=replace(row.workload, selected_versions=(version,)))
    with pytest.raises(ValueError, match=r"SHA256|identity"):
        model.workload_role_features(row)


def test_bool_source_minutes_is_not_a_measured_one():
    row = inputs(volume=1)
    version = row.workload.selected_versions[0]
    version = replace(
        version, observations=(replace(version.observations[0], nominal_minutes=True),)
    )
    row = replace(row, workload=replace(row.workload, selected_versions=(version,)))
    with pytest.raises(ValueError, match="nominal source"):
        model.workload_role_features(row)


def test_cache_bridge_preserves_pmf_identity_and_complete_lineage():
    import json

    from fpl.types import Position
    from fpl.validate.development_reference_components import (
        ReferenceMinutesRow,
        ValidatedMinutesControlFold,
    )
    from fpl.validate.minutes_baselines import TargetRow

    original = inputs().control
    target = original.target
    cached = ReferenceMinutesRow(
        TargetRow(
            target.season,
            target.gw,
            target.fixture,
            target.kickoff,
            target.code,
            Position.DEF,
            1,
            2,
            True,
        ),
        target.team_code,
        original.probabilities,
        original.cold_start,
        original.price_proxy_dependent,
        original.selector_provenance_json,
    )
    fold = ValidatedMinutesControlFold(
        target.season,
        target.gw,
        target.as_of,
        (cached,),
        "e" * 64,
        original.manifest_sha256,
        original.fold_sha256,
        json.dumps({"maximum_prior_kickoff": original.maximum_prior_event.isoformat()}),
    )
    control = model.control_from_cache(fold, cached)
    assert control.probabilities is original.probabilities
    assert control.maximum_prior_event == original.maximum_prior_event
    assert control.selector_provenance_json == original.selector_provenance_json
    assert control.target.team_code == target.team_code
    assert (
        control.target.identity_source
        == f"minutes-cache:{original.manifest_sha256}:{original.fold_sha256}"
    )
    with pytest.raises(ValueError, match="does not belong"):
        model.control_from_cache(fold, replace(cached, team_code=999))


def test_same_gw_player_stable_club_contradiction_is_not_a_transfer(fitted):
    _fit, target = fitted
    first = history()[0]
    second = replace(
        first,
        predictors=replace(
            first.predictors,
            control=replace(
                first.predictors.control,
                target=replace(first.predictors.control.target, fixture=999, team_code=999),
            ),
        ),
    )
    with pytest.raises(ValueError, match="stable club identity"):
        model.fit_minutes_correction(
            [first, second], season="2025-26", gw=10, as_of=target.control.target.as_of
        )


@pytest.mark.parametrize(("seconds", "expected"), [(3600, 0), (21600, 0), (21601, 1)])
def test_historical_label_requires_strict_six_hour_completion_margin(seconds, expected):
    cutoff = inputs().control.target.as_of
    row = inputs(gw=9)
    row = replace(
        row,
        control=replace(
            row.control,
            target=replace(row.control.target, kickoff=cutoff - timedelta(seconds=seconds)),
        ),
    )
    row = replace(row, role_batch=None)  # This test isolates label eligibility, not features.
    fitted = model.fit_minutes_correction(
        [model.WorkloadMinutesObservation(row, 0)], season="2025-26", gw=10, as_of=cutoff
    )
    assert fitted.prior_rows == expected
