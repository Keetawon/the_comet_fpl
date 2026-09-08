"""Synthetic frozen-audit arithmetic; no actual forecast/outcome data loaded."""

from __future__ import annotations

import copy
import json
import math
from typing import Any

import pytest

from fpl.validate.player_model_gw1_3_metrics import IDENTITY, paired_comparison, score_predictions

type Row = dict[str, Any]


def _prediction(**changes: Any) -> Row:
    result: Row = {
        "season": "2026-27",
        "gw": 1,
        "fixture": 100,
        "code": 1,
        "position": "DEF",
        "team_code": 10,
        "opponent_team_code": 20,
        "was_home": True,
        "kickoff_time": "2026-08-15T14:00:00+00:00",
        "selector": "SDP_MISSING_FALLBACK",
        "expected_points": 6.0,
        "expected_bonus": 0.0,
        "distribution": [float(i == 6) for i in range(35)],
        "availability_status": "a",
        "availability_multiplier": 1.0,
        "cold_start_player": False,
        "transferred_no_rescale": False,
        "components": {
            "minutes": [0.0, 0.0, 0.0, 1.0],
            "goals": [1.0, 0.0],
            "assists": [1.0, 0.0],
            "saves": None,
            "team_goals_conceded": [1.0, 0.0],
            "dc_hit_probability": 0.0,
            "probability_any_bonus": 0.0,
        },
    }
    result.update(changes)
    return result


def _points(values: dict[int, float], **changes: Any) -> Row:
    return _prediction(
        distribution=[values.get(i, 0.0) for i in range(35)],
        expected_points=math.fsum(i * p for i, p in values.items()),
        **changes,
    )


def _outcome(prediction: Row, **changes: Any) -> Row:
    return {
        **{key: prediction[key] for key in IDENTITY},
        "total_points_as_recorded": 6,
        "minutes": 90,
        "starts": 1,
        "goals_scored": 0,
        "assists": 0,
        "clean_sheets": 1,
        "goals_conceded": 0,
        "team_goals_scored": 1,
        "team_goals_conceded": 0,
        "saves": 0,
        "defensive_contribution": 0,
        "bonus": 0,
        "bps": 10,
        **changes,
    }


def test_hand_computable_points_and_calibration() -> None:
    prediction = _points({0: 0.5, 2: 0.5})
    result = score_predictions([prediction], [_outcome(prediction, total_points_as_recorded=2)])
    points = result["fixture_points"]["overall"]
    assert points["mean_log_score"] == math.log(2)
    assert points["mean_crps"] == 0.5
    assert points["signed_points"]["mae"] == 1
    assert points["signed_points"]["bias_predicted_minus_observed"] == -1
    assert points["events_on_coarsened_target"]["blank_le2"]["brier"] == 0
    assert points["events_on_coarsened_target"]["blank_le2"]["bins"][9]["rows"] == 1
    assert points["spearman_within_gameweek_signed"] is None
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(("actual", "mass", "error"), [(-3, 0, 3), (40, 34, 6)])
def test_signed_outcomes_remain_distinct_from_coarsened_scores(
    actual: int, mass: int, error: int
) -> None:
    prediction = _points({mass: 1.0})
    result = score_predictions(
        [prediction], [_outcome(prediction, total_points_as_recorded=actual)]
    )
    points = result["fixture_points"]["overall"]
    assert points["mean_log_score"] == points["mean_crps"] == 0
    assert points["signed_points"]["mae"] == error
    assert points["signed_targets_below_zero"] == int(actual < 0)
    assert points["signed_targets_above_support"] == int(actual > 34)
    assert points["target_changed_by_coarsening"] == 1


def test_monte_carlo_zero_bin_and_floor_are_explicit() -> None:
    prediction = _points({0: 1.0})
    result = score_predictions([prediction], [_outcome(prediction)])
    points = result["fixture_points"]["overall"]
    assert points["zero_target_bin_count"] == points["log_floor_hit_count"] == 1
    assert points["mean_log_score"] == -math.log(1e-12)
    prediction = _points({0: 1 - 1e-13, 6: 1e-13})
    points = score_predictions([prediction], [_outcome(prediction)])["fixture_points"]["overall"]
    assert points["zero_target_bin_count"] == 0 and points["log_floor_hit_count"] == 1


def test_double_gameweek_convolves_leg_targets_before_signed_comparison() -> None:
    first = _points({0: 1.0})
    second = _points({5: 1.0}, fixture=101, selector="SDP_PRIMARY", was_home=False)
    outcomes = [
        _outcome(first, total_points_as_recorded=-2),
        _outcome(second, total_points_as_recorded=5),
    ]
    result = score_predictions([second, first], outcomes)
    row = result["player_gameweek_row_scores"][0]
    assert row["fixture_ids"] == [100, 101]
    assert row["scored_target"] == 5 and row["signed_target"] == 3
    assert row["expected_points"] == 5 and row["crps"] == 0
    assert row["signed_absolute_error"] == 2
    assert row["selector"] == "MIXED" and row["venue"] == "mixed"
    incomplete = score_predictions([first, second], outcomes[:1])
    assert incomplete["coverage"]["scored_fixture_rows"] == 1
    assert incomplete["coverage"]["scored_player_gameweeks"] == 0
    assert incomplete["coverage"]["gameweek_exclusions"][0]["reason"] == "INCOMPLETE_FIXTURE_LEGS"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("gw", 2),
        ("position", "MID"),
        ("team_code", 11),
        ("opponent_team_code", 21),
        ("was_home", False),
        ("kickoff_time", "2026-08-15T15:00:00+00:00"),
    ],
)
def test_identity_mismatch_excluded_explicitly(field: str, value: Any) -> None:
    prediction = _prediction()
    outcome = _outcome(prediction, **{field: value})
    result = score_predictions([prediction], [outcome])
    assert result["coverage"]["scored_fixture_rows"] == 0
    assert result["fixture_components"]["overall"]["rows"] == 0
    exclusion = result["coverage"]["fixture_exclusions"][0]
    assert exclusion["reason"] == "IDENTITY_MISMATCH" and exclusion["fields"] == [field]


def test_same_instant_zone_is_valid_but_missing_identity_is_not() -> None:
    prediction = _prediction()
    outcome = _outcome(prediction, kickoff_time="2026-08-15T21:00:00+07:00")
    assert score_predictions([prediction], [outcome])["coverage"]["scored_fixture_rows"] == 1
    del outcome["team_code"]
    assert score_predictions([prediction], [outcome])["coverage"]["scored_fixture_rows"] == 0


def test_duplicate_identity_rejected_without_last_row_wins() -> None:
    prediction = _prediction()
    outcome = _outcome(prediction)
    with pytest.raises(ValueError, match="duplicate"):
        score_predictions([prediction, prediction], [outcome])
    with pytest.raises(ValueError, match="duplicate"):
        score_predictions([prediction], [outcome, outcome])


@pytest.mark.parametrize("value", [None, True, float("nan"), float("inf"), 2.5])
def test_missing_or_invalid_points_not_zero(value: Any) -> None:
    prediction = _prediction()
    result = score_predictions([prediction], [_outcome(prediction, total_points_as_recorded=value)])
    assert result["coverage"]["scored_fixture_rows"] == 0
    assert (
        result["coverage"]["fixture_exclusions"][0]["reason"] == "MISSING_OR_INVALID_POINTS_OUTCOME"
    )
    assert result["fixture_components"]["overall"]["rows"] == 1


def test_measured_zero_is_a_valid_outcome() -> None:
    prediction = _points({0: 1.0})
    result = score_predictions([prediction], [_outcome(prediction, total_points_as_recorded=0)])
    assert result["coverage"]["scored_fixture_rows"] == 1
    assert result["fixture_points"]["overall"]["mean_crps"] == 0


def test_missing_components_stay_unavailable_and_forensic_remainder_explicit() -> None:
    prediction = _prediction(components={}, expected_bonus=None)
    result = score_predictions([prediction], [_outcome(prediction)])
    components = result["fixture_components"]["overall"]
    for metric in components["numeric"].values():
        assert metric["rows"] == 0 and metric["mae"] is None
    for metric in components["binary"].values():
        assert metric["rows"] == 0 and metric["brier"] is None
    miss = result["top25_absolute_xp_misses"][0]
    assert miss["category"] == "UNEXPLAINED"
    assert all(
        v is None for v in miss["component_point_residuals_observed_minus_expected"].values()
    )
    assert "NO_START_MODEL" in components["starts"]["status"]


@pytest.mark.parametrize("value", [None, -1, True, float("nan"), float("inf"), 121, 1.5])
def test_unavailable_minutes_never_become_an_observed_dnp(value: Any) -> None:
    prediction = _prediction()
    result = score_predictions([prediction], [_outcome(prediction, minutes=value)])
    components = result["fixture_components"]["overall"]
    assert components["numeric"]["minutes_scoring_proxy"]["rows"] == 0
    assert components["binary"]["appearance"]["rows"] == 0
    assert components["binary"]["minutes_60_plus"]["rows"] == 0
    assert components["false_nailed"]["eligible_rows"] == 0


def test_appearance_gates_goals_and_saves_count_distributions() -> None:
    prediction = _prediction(position="GK")
    prediction["components"].update(minutes=[0.5, 0, 0, 0.5], goals=[0, 0, 1], saves=[0, 0, 0, 1])
    result = score_predictions([prediction], [_outcome(prediction, goals_scored=1, saves=3)])
    components = result["fixture_components"]["overall"]
    assert components["numeric"]["goals"]["mean_predicted"] == 1
    assert components["numeric"]["goals"]["mae"] == 0
    assert components["numeric"]["goals"]["mean_log_score"] == -math.log(1e-12)
    assert components["numeric"]["saves"]["mean_predicted"] == 1.5
    assert components["binary"]["appearance"]["brier"] == 0.25
    residuals = result["top25_absolute_xp_misses"][0][
        "component_point_residuals_observed_minus_expected"
    ]
    assert residuals["SAVES"] == 0.5


def test_minutes_proxy_is_explicit_and_start_probability_is_absent() -> None:
    prediction = _prediction()
    prediction["components"]["minutes"] = [0.1, 0.2, 0.3, 0.4]
    components = score_predictions([prediction], [_outcome(prediction, minutes=59)])[
        "fixture_components"
    ]["overall"]
    assert components["numeric"]["minutes_scoring_proxy"]["mean_predicted"] == pytest.approx(74.5)
    assert components["binary"]["appearance"]["mean_probability"] == pytest.approx(0.9)
    assert components["binary"]["minutes_60_plus"]["mean_probability"] == pytest.approx(0.7)
    assert components["starts"]["prediction"] is None
    assert components["starts"]["observed_starts"] == 1


def test_false_nailed_and_missed_starter_thresholds() -> None:
    first, second = _prediction(), _prediction(code=2)
    first["components"]["minutes"] = [0.2, 0, 0, 0.8]
    second["components"]["minutes"] = [0.9, 0, 0, 0.1]
    result = score_predictions(
        [first, second], [_outcome(first, minutes=59), _outcome(second, minutes=90, starts=1)]
    )["fixture_components"]["overall"]
    assert result["false_nailed"] == {"eligible_rows": 1, "count": 1}
    assert result["missed_starters"] == {"eligible_rows": 1, "count": 1}


def test_team_clean_sheet_deduplicates_and_never_uses_player_conceded_proxy() -> None:
    first, second = _prediction(), _prediction(code=2)
    outcomes = [
        _outcome(first, goals_conceded=0, team_goals_conceded=2),
        _outcome(second, goals_conceded=1, team_goals_conceded=2),
    ]
    result = score_predictions([first, second], outcomes)["fixture_components"]["overall"]
    team = result["binary"]["team_clean_sheet"]
    assert team["rows"] == team["eligible_team_fixture_sides"] == 1
    assert team["brier"] == 1 and team["observed_rate"] == 0
    for outcome in outcomes:
        outcome["team_goals_conceded"] = None
    team = score_predictions([first, second], outcomes)["fixture_components"]["overall"]["binary"][
        "team_clean_sheet"
    ]
    assert team["rows"] == 0 and team["brier"] is None


@pytest.mark.parametrize("contradiction", ["probability", "official_count"])
def test_team_identity_repeated_evidence_must_agree(contradiction: str) -> None:
    first, second = _prediction(), _prediction(code=2)
    outcomes = [_outcome(first, team_goals_conceded=1), _outcome(second, team_goals_conceded=1)]
    if contradiction == "probability":
        second["components"]["team_goals_conceded"] = [0, 1]
    else:
        outcomes[1]["team_goals_conceded"] = 2
    with pytest.raises(ValueError, match="contradictory team"):
        score_predictions([first, second], outcomes)


def test_player_clean_sheet_uses_sixty_plus_exposure_thinning() -> None:
    prediction = _prediction()
    prediction["components"].update(minutes=[0, 0, 1, 0], team_goals_conceded=[0, 1])
    components = score_predictions(
        [prediction], [_outcome(prediction, minutes=80, clean_sheets=1, team_goals_conceded=1)]
    )["fixture_components"]["overall"]["binary"]
    assert components["team_clean_sheet"]["mean_probability"] == 0
    assert components["player_60plus_clean_sheet"]["mean_probability"] == pytest.approx(0.187)
    assert components["player_60plus_clean_sheet"]["brier"] == pytest.approx(0.813**2)


@pytest.mark.parametrize(("position", "threshold"), [("DEF", 10), ("MID", 12), ("FWD", 12)])
def test_dc_uses_position_rules_and_preserves_missing(position: str, threshold: int) -> None:
    prediction = _prediction(position=position)
    prediction["components"]["dc_hit_probability"] = 0.25
    for observed, actual in ((threshold - 1, 0), (threshold, 1), (None, None)):
        metric = score_predictions(
            [prediction], [_outcome(prediction, defensive_contribution=observed)]
        )["fixture_components"]["overall"]["binary"]["dc_award"]
        assert metric["observed_rate"] == actual
        assert metric["brier"] == ((0.25 - actual) ** 2 if actual is not None else None)


def test_bonus_uses_stored_margins_without_inventing_a_pmf() -> None:
    prediction = _prediction(expected_bonus=1.5)
    prediction["components"]["probability_any_bonus"] = 0.75
    components = score_predictions([prediction], [_outcome(prediction, bonus=3)])[
        "fixture_components"
    ]["overall"]
    assert components["numeric"]["bonus"]["mae"] == 1.5
    assert components["binary"]["any_bonus"]["brier"] == 0.25**2
    assert "mean_log_score" not in components["numeric"]["bonus"]
    assert "bonus_full_pmf" in components["unavailable_models"]


def test_rankings_use_raw_xp_stable_ties_signed_outcomes_and_effective_k() -> None:
    predictions = [_points({6: 1}, code=code, availability_multiplier=0) for code in (3, 1, 2)]
    outcomes = [
        _outcome(p, total_points_as_recorded={1: -1, 2: 5, 3: 10}[p["code"]]) for p in predictions
    ]
    result = score_predictions(predictions, outcomes)
    ranking = result["within_gw_rankings"][0]
    captain = ranking["captain_shortlists"][0]
    assert captain["selected_codes"] == [1] and captain["actual_top_codes"] == [3]
    assert captain["regret_total_points"] == 11 and captain["overlap_count"] == 0
    assert captain["hit_rate_ge5"] == 0
    top = ranking["top_k"][0]
    assert top["requested_k"] == 10 and top["effective_k"] == 3
    assert top["hit_rate_ge5"] == pytest.approx(2 / 3)
    assert top["hit_rate_ge10"] == pytest.approx(1 / 3)
    assert top["regret_total_points"] == 0 and top["overlap_fraction"] == 1


def test_forensic_component_residuals_are_noncausal_with_ties_and_remainder() -> None:
    prediction = _prediction()
    result = score_predictions(
        [prediction], [_outcome(prediction, total_points_as_recorded=18, goals_scored=1, assists=2)]
    )
    miss = result["top25_absolute_xp_misses"][0]
    assert miss["category"] == "MULTIPLE"
    assert miss["tied_categories"] == ["ASSISTS", "GOALS"]
    assert miss["unexplained_remainder"] == 0
    assert miss["interpretation"] == "NONCAUSAL_COMPONENT_RESIDUAL_DIAGNOSTIC"
    result = score_predictions([prediction], [_outcome(prediction, total_points_as_recorded=-3)])
    assert result["top25_absolute_xp_misses"][0]["category"] == "UNEXPLAINED"


def test_component_outcomes_missing_are_excluded_per_field() -> None:
    prediction = _prediction()
    components = score_predictions(
        [prediction],
        [_outcome(prediction, goals_scored=None, bonus=None, defensive_contribution=None)],
    )["fixture_components"]["overall"]
    assert components["numeric"]["goals"]["rows"] == components["numeric"]["bonus"]["rows"] == 0
    assert components["numeric"]["assists"]["rows"] == 1
    assert components["binary"]["dc_award"]["rows"] == 0


def test_empty_result_is_explicit_and_serializable() -> None:
    result = score_predictions([], [])
    assert result["coverage"]["scored_fixture_rows"] == 0
    assert result["fixture_points"]["overall"]["mean_log_score"] is None
    assert result["within_gw_rankings"] == result["top25_absolute_xp_misses"] == []
    json.dumps(result, allow_nan=False)


def test_replay_permutation_and_inputs_immutable() -> None:
    predictions = [_prediction(code=code) for code in (1, 2, 3)]
    outcomes = [_outcome(p, total_points_as_recorded=p["code"]) for p in predictions]
    before = copy.deepcopy((predictions, outcomes))
    result = score_predictions(predictions, outcomes)
    assert result == score_predictions(list(reversed(predictions)), list(reversed(outcomes)))
    assert result == score_predictions(predictions, outcomes)
    assert (predictions, outcomes) == before


@pytest.mark.parametrize(
    "changes",
    [
        {"distribution": [1.0]},
        {"distribution": [float("nan")] + [0.0] * 34},
        {"distribution": [-0.1, 1.1] + [0.0] * 33},
        {"distribution": [True] + [0.0] * 34},
        {"expected_points": 5.0},
        {"availability_multiplier": None},
        {"cold_start_player": 1},
        {"kickoff_time": "2026-08-15T14:00:00"},
        {"gw": 4},
    ],
)
def test_invalid_prediction_contract_fails_closed(changes: Row) -> None:
    prediction = _prediction(**changes)
    with pytest.raises(ValueError, match=r"PMF|xP|availability|flags|kickoff|GW1-3"):
        score_predictions([prediction], [_outcome(prediction)])


def test_components_stay_fixture_grain_and_flags_follow_stored_forecast() -> None:
    first = _prediction(cold_start_player=True)
    second = _prediction(fixture=101, transferred_no_rescale=True)
    result = score_predictions([first, second], [_outcome(first), _outcome(second)])
    assert result["fixture_components"]["overall"]["rows"] == 2
    assert result["player_gameweek_points"]["slices"]["cold_start"]["True"]["rows"] == 1
    assert result["player_gameweek_points"]["slices"]["transfer"]["True"]["rows"] == 1


def test_double_gameweek_position_contradiction_excludes_whole_gameweek() -> None:
    first, second = _prediction(), _prediction(fixture=101, position="MID")
    result = score_predictions([first, second], [_outcome(first), _outcome(second)])
    assert result["coverage"]["scored_fixture_rows"] == 2
    assert result["coverage"]["scored_player_gameweeks"] == 0
    assert (
        result["coverage"]["gameweek_exclusions"][0]["reason"]
        == "CONTRADICTORY_REGISTERED_POSITION"
    )


def test_paired_identical_arms_exactly_zero_with_all_27_block_resamples() -> None:
    predictions = [_prediction(gw=gw, fixture=100 + gw) for gw in (1, 2, 3)]
    outcomes = [_outcome(p, total_points_as_recorded=p["gw"]) for p in predictions]
    result = paired_comparison(predictions, copy.deepcopy(predictions), outcomes)
    assert result["numerical_equality"] is True
    assert all(result["equality_details"].values())
    assert result["fixture"]["pooled"]["rows"] == 3
    uncertainty = result["fixture"]["uncertainty"]
    assert len(uncertainty["draws"]) == 27
    assert uncertainty["draws"][0]["sampled_gameweeks"] == [1, 1, 1]
    assert uncertainty["draws"][-1]["sampled_gameweeks"] == [3, 3, 3]
    assert all(interval == [0, 0] for interval in uncertainty["intervals_95"].values())


def test_paired_losses_sign_row_weighting_and_selector_population() -> None:
    current = [_points({0: 1}, gw=gw, fixture=100 + gw, selector="SDP_PRIMARY") for gw in (1, 2, 3)]
    current.append(_points({0: 1}, gw=3, fixture=103, code=2))
    incumbent = [_points({2: 1}, **{k: p[k] for k in ("gw", "fixture", "code")}) for p in current]
    outcomes = [_outcome(p, total_points_as_recorded=p["gw"] - 1) for p in current]
    result = paired_comparison(current, incumbent, outcomes)
    fixture = result["fixture"]
    assert result["numerical_equality"] is False
    assert (
        fixture["pooled"]["metrics"]["signed_absolute_error"]["difference_current_minus_incumbent"]
        == 0.5
    )
    assert fixture["by_selector"]["SDP_PRIMARY"]["rows"] == 3
    assert fixture["by_selector"]["FALLBACK"]["rows"] == 1
    draws = fixture["uncertainty"]["draws"]
    assert draws[0]["difference"]["signed_absolute_error"] == -2
    assert draws[-1]["difference"]["signed_absolute_error"] == 2
    # GW1 + GW1 + GW3 weights the two GW3 player rows separately: (-2 -2 +2 +2)/4.
    assert draws[2]["sampled_gameweeks"] == [1, 1, 3]
    assert draws[2]["rows_with_multiplicity"] == 4
    assert draws[2]["difference"]["signed_absolute_error"] == 0


def test_paired_arms_reject_population_or_shared_metadata_mismatch() -> None:
    prediction = _prediction()
    with pytest.raises(ValueError, match="populations"):
        paired_comparison([prediction], [], [])
    altered = _prediction(team_code=11)
    with pytest.raises(ValueError, match="identity"):
        paired_comparison([prediction], [altered], [])
    altered = _prediction(availability_multiplier=0.5)
    with pytest.raises(ValueError, match="context"):
        paired_comparison([prediction], [altered], [])


def test_paired_missing_outcome_is_excluded_identically_not_zero_filled() -> None:
    prediction = _prediction()
    result = paired_comparison([prediction], [prediction], [])
    assert result["fixture"]["pooled"]["rows"] == 0
    assert result["coverage"]["exclusion_counts"] == {"MISSING_OUTCOME": 1}
    assert result["fixture"]["uncertainty"]["intervals_95"]["crps"] is None
    json.dumps(result, allow_nan=False)


def test_forensic_details_retain_each_leg_context_and_measured_components() -> None:
    first = _prediction(
        web_name="Synthetic One",
        promoted_team=True,
        team_environment={"distribution": [0.25, 0.75]},
        opponent_environment={"distribution": [0.6, 0.4]},
        residual_mean=2.5,
        residual_sigma=0.5,
    )
    second = _prediction(fixture=101, web_name="Synthetic One", availability_status="d")
    report = score_predictions(
        [first, second], [_outcome(first, minutes=59, bps=12), _outcome(second, minutes=90)]
    )
    miss = report["top25_absolute_xp_misses"][0]
    assert miss["web_name"] == "Synthetic One" and miss["fixture_ids"] == [100, 101]
    first_detail, second_detail = miss["fixture_details"]
    assert first_detail["predicted_components"]["minutes_scoring_proxy"] == 90
    assert first_detail["observed_components"]["minutes_scoring_proxy"] == 59
    assert first_detail["observed_raw_bps"] == 12
    assert first_detail["bps_residual_mean"] == 2.5
    assert first_detail["team_environment"] == first["team_environment"]
    assert first_detail["opponent_environment"] == first["opponent_environment"]
    assert second_detail["availability_status"] == "d"
    assert second_detail["team_environment"] is None
    assert second_detail["promoted_team"] is None
    scopes = report["fixture_components"]["by_evidence_scope"]
    assert scopes["promoted"]["True"]["rows"] == scopes["promoted"]["UNAVAILABLE"]["rows"] == 1
    assert report["player_gameweek_points"]["slices"]["promoted"]["UNAVAILABLE"]["rows"] == 1


def test_goal_any_probability_uses_same_appearance_gate() -> None:
    prediction = _prediction()
    prediction["components"].update(minutes=[0.5, 0, 0, 0.5], goals=[0.25, 0.75])
    report = score_predictions([prediction], [_outcome(prediction, goals_scored=1)])
    metric = report["fixture_components"]["overall"]["binary"]["goals_any"]
    assert metric["mean_probability"] == 0.375
    assert metric["brier"] == 0.625**2


def test_unknown_promoted_evidence_is_not_established() -> None:
    prediction = _prediction()
    report = score_predictions([prediction], [_outcome(prediction)])
    assert report["fixture_points"]["slices"]["promoted"]["UNAVAILABLE"]["rows"] == 1
    assert report["fixture_components"]["by_evidence_scope"]["promoted"]["False"]["rows"] == 0
    prediction["promoted_team"] = 0
    with pytest.raises(ValueError, match="promoted-team evidence"):
        score_predictions([prediction], [_outcome(prediction)])
