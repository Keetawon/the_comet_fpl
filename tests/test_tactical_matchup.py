"""Offline causal tests for the single prequential tactical procedure."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from fpl.validate.metrics import Distribution, poisson_pmf
from fpl.validate.tactical_matchup import (
    INNER_GAMEWEEKS,
    MINIMUM_FIT_ROWS,
    MINIMUM_INNER_HISTORY,
    PENALTIES,
    matchup_features,
    observation_key,
    run_tactical_walk_forward,
    select_penalty,
)
from fpl.validate.tactical_state import TacticalObservation


def _pair(
    gw: int,
    fixture: int,
    *,
    day: int | None = None,
    teams: tuple[int, int] = (1, 2),
    season: str = "2023-24",
) -> list[TacticalObservation]:
    kickoff = datetime(2023, 8, 1, tzinfo=UTC) + timedelta(days=gw * 7 if day is None else day)
    goals = fixture % 3, (fixture + 1) % 3
    return [
        TacticalObservation(
            season=season,
            gw=gw,
            fixture=fixture,
            team_code=teams[side],
            opponent_team_code=teams[1 - side],
            was_home=side == 0,
            kickoff=kickoff,
            goals=goals[side],
            goals_allowed=goals[1 - side],
            values=(0.25 + side * 0.1, 2.0 + fixture % 4 / 10, 0.4 + side / 5, 0.3, -2.0),
            sdp_match_id=100000 + fixture,
            capture_id=f"capture-{fixture}",
            source_known_at=datetime(2026, 9, 5, tzinfo=UTC),
            payload_sha256=f"sha-{fixture}",
        )
        for side in (0, 1)
    ]


def _cache(observations: list[TacticalObservation]) -> dict[str, tuple[float, Distribution]]:
    return {observation_key(row): (1.4, poisson_pmf(1.4)) for row in observations}


def _run(observations: list[TacticalObservation]) -> dict:
    return run_tactical_walk_forward(observations, _cache(observations), ("2023-24",))


def test_exact_three_interactions_and_opponent_direction() -> None:
    own, opponent = (0.2, 3.0, 0.6, 0.4, -2.0), (0.3, 2.0, 0.4, 0.5, -3.0)
    values = matchup_features(own, opponent, interactions=True)
    assert values is not None
    assert values[:10] == [*own, *opponent]
    assert values[10:] == pytest.approx([-0.6, -9.0, 0.16])
    assert matchup_features(own, opponent, interactions=False) == [*own, *opponent]
    assert matchup_features((None, *own[1:]), opponent, interactions=True) is None


def test_predeclared_grid_and_thresholds() -> None:
    assert PENALTIES == (None, 10.0, 1.0, 0.1)
    assert MINIMUM_FIT_ROWS == 160
    assert INNER_GAMEWEEKS == 6
    assert MINIMUM_INNER_HISTORY == 10


def test_deterministic_ties_favour_disabled_then_stronger_penalty() -> None:
    assert select_penalty([1.0, 1.0, 1.0, 1.0]) is None
    assert select_penalty([2.0, 1.0, 1.0 - 5e-13, 1.0]) == 10.0
    assert select_penalty([2.0, 1.0, 1.0 - 2e-12, 1.0]) == 1.0
    # Numerical ties are defined against the global minimum, not an incidental
    # chain of pairwise near-ties that could skip stronger regularisation.
    assert select_penalty([1.0, 1.0 - 8e-13, 1.0 - 1.2e-12, 2.0]) == 10.0
    with pytest.raises(ValueError, match="four finite"):
        select_penalty([1.0])


def test_initial_missing_state_falls_back_without_filling_observation() -> None:
    observations = [replace(row, values=(None,) * 5) for row in _pair(1, 1)]
    result = _run(observations)
    for row in result["rows"]:
        assert row["actual_state"] == (None,) * 5
        assert row["predicted_state"] == (None,) * 5
        assert row["goal_matchup_features"] is None
        assert row["incumbent_fallback"]
        assert row["distributions"]["candidate"] == row["distributions"]["incumbent"]
        assert row["state_cold_start"]


def test_same_gameweek_all_fixtures_have_one_unmodified_state() -> None:
    observations = [*_pair(1, 1), *_pair(2, 2), *_pair(2, 3, day=18), *_pair(3, 4)]
    result = _run(observations)
    for team in (1, 2):
        legs = [row for row in result["rows"] if row["gw"] == 2 and row["team_code"] == team]
        assert len(legs) == 2
        assert legs[0]["current_state"] == legs[1]["current_state"]
        assert legs[0]["recent_counts"] == legs[1]["recent_counts"] == (1,) * 5
        assert legs[0]["as_of"] == legs[1]["as_of"]
        assert legs[0]["state_source_keys_sha256"] == legs[1]["state_source_keys_sha256"]


def test_delayed_dgw_leg_not_absorbed_before_actual_kickoff() -> None:
    observations = [*_pair(1, 1), *_pair(2, 2), *_pair(2, 3, day=30), *_pair(3, 4)]
    changed = [
        replace(row, values=(0.95, 10.0, 0.95, 0.95, -5.0)) if row.fixture == 3 else row
        for row in observations
    ]
    first, second = _run(observations), _run(changed)
    old = [row for row in first["rows"] if row["gw"] == 3]
    new = [row for row in second["rows"] if row["gw"] == 3]
    assert old == new
    assert old[0]["recent_counts"] == (2,) * 5
    assert first["folds"][2]["prior_completed_rows"] == 4


def test_earlier_target_cannot_read_its_own_tactical_measurements_or_goals() -> None:
    observations = [*_pair(1, 1), *_pair(2, 2), *_pair(3, 3)]
    changed = [
        replace(row, values=(0.99, 9.0, 0.99, 0.99, -5.0), goals=7, goals_allowed=7)
        if row.gw == 2
        else row
        for row in observations
    ]
    first, second = _run(observations), _run(changed)
    old = [row for row in first["rows"] if row["gw"] == 2]
    new = [row for row in second["rows"] if row["gw"] == 2]
    for before, after in zip(old, new, strict=True):
        for field in (
            "style_predictors",
            "predicted_state",
            "distributions",
            "current_state",
            "goal_matchup_features",
            "as_of",
        ):
            assert before[field] == after[field]
        assert before["actual_state"] != after["actual_state"]


def test_future_truncation_equivalence() -> None:
    observations = [row for gw in range(1, 7) for row in _pair(gw, gw)]
    full = _run(observations)
    truncated = _run([row for row in observations if row.gw <= 3])
    assert [row for row in full["rows"] if row["gw"] <= 3] == truncated["rows"]
    assert full["folds"][:3] == truncated["folds"]


def test_reciprocal_clean_sheet_is_exact_opponent_pmf_zero_mass() -> None:
    result = _run([*_pair(1, 1), *_pair(2, 2)])
    keyed = {row["key"]: row for row in result["rows"]}
    for row in result["rows"]:
        opponent = keyed[f"{row['season']}:{row['fixture']}:{row['opponent_team_code']}"]
        assert row["observed_clean_sheet"] == (opponent["observed_goals"] == 0)
        for name, probability in row["clean_sheet_probabilities"].items():
            assert probability == opponent["distributions"][name][0]
            assert sum(row["distributions"][name]) == pytest.approx(1.0)


def test_actual_fitted_style_and_goal_layers_are_sequential_out_of_sample() -> None:
    # 20 sides/GW: first GW has no predictors; GW10 has >=160 genuine earlier
    # complete training rows. This is synthetic only, exercising real fit thresholds.
    observations = [
        row
        for gw in range(1, 12)
        for fixture in range(10)
        for row in _pair(gw, gw * 10 + fixture, teams=(fixture * 2 + 1, fixture * 2 + 2))
    ]
    result = _run(observations)
    final = result["folds"][-1]
    assert final["style_fits"]["attack_precision"]["mode"] == "ridge_delta"
    assert final["goal_fits"]["1.0"]["mode"] == "poisson_offset"
    for fold in result["historical_folds"]:
        cutoff = fold["as_of"]
        for fit in [*fold["style_fits"].values(), *fold["goal_fits"].values()]:
            if fit["maximum_training_event"] is not None:
                assert fit["maximum_training_event"] < cutoff
                assert fit["maximum_training_prediction_cutoff"] < cutoff
        assert fold["same_gameweek_violations"] == 0
        assert fold["stacking_in_sample_rows"] == 0
    # Every underlying prequential prediction remains exactly the original
    # prefix's prediction, not an in-sample re-prediction by the later fitted model.
    prefix = _run([row for row in observations if row.gw <= 9])
    assert result["history_rows"][:180] == prefix["history_rows"]
    # Exercise the non-fallback ridge/Poisson paths: changing a target batch's
    # post-match style AND goals cannot alter that same batch's predictions.
    changed = [
        replace(row, values=(0.99, 9.0, 0.99, 0.99, -5.0), goals=7, goals_allowed=7)
        if row.gw == 11
        else row
        for row in observations
    ]
    altered = _run(changed)
    assert result["folds"][-1] == altered["folds"][-1]
    for before, after in zip(result["rows"][-20:], altered["rows"][-20:], strict=True):
        for field in (
            "predicted_state",
            "style_predictors",
            "goal_matchup_features",
            "per_penalty_distributions",
            "prior_style_error",
            "distributions",
        ):
            assert before[field] == after[field]
        assert before["actual_state"] != after["actual_state"]
    json.dumps(result, allow_nan=False)


def test_repeat_input_determinism_and_prior_only_error_risk() -> None:
    observations = [row for gw in range(1, 18) for row in _pair(gw, gw)]
    first = _run(observations)
    assert first == _run(list(reversed(observations)))
    final = first["folds"][-1]
    assert final["selection"]["mode"] == "cached_prequential_weekly_refit"
    assert final["selection"]["holdout_gameweeks"] == [("2023-24", gw) for gw in range(11, 17)]
    assert final["selection"]["scored_rows"] == 12
    assert final["chosen_penalty"] is None  # all insufficient-fit models equal incumbent
    assert first["rows"][0]["style_error_risk"] == "unknown"


def test_fail_closed_on_missing_incumbent_or_reciprocal_side() -> None:
    observations = _pair(1, 1)
    with pytest.raises(ValueError, match="missing incumbent"):
        run_tactical_walk_forward(observations, {}, ("2023-24",))
    with pytest.raises(ValueError, match="non-reciprocal"):
        _run(observations[:1])
    with pytest.raises(ValueError, match="duplicate"):
        _run(observations * 2)
