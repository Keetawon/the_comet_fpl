"""Offline procedural controls: no real archive model is fitted by this module."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import polars as pl
import pytest

from fpl.config import repo_root
from fpl.features.pit import AsOf
from fpl.models import football_engine_v2 as legacy
from fpl.models.team_goals import Fixture, TeamRatings
from fpl.validate import weekly_inner_selection as weekly
from fpl.validate.weekly_inner_selection import (
    SIGNALS,
    WeeklyRefitTeamEngine,
    frozen_selected_inner_scores,
)

START = datetime(2025, 8, 1, tzinfo=UTC)


def _frame(weeks: int = 8) -> pl.DataFrame:
    rows: list[dict[str, Any]] = []
    for week in range(1, weeks + 1):
        for team, opponent, home in ((3, 8, True), (8, 3, False)):
            goals = (week + int(home)) % 4
            rows.append(
                {
                    "season": "2025-26",
                    "gw": week,
                    "fixture": week,
                    "kickoff_time": START + timedelta(days=7 * week),
                    "team_code": team,
                    "opponent_team_code": opponent,
                    "was_home": home,
                    "goals": goals,
                    "expected_goals": float(goals + 1),
                }
            )
    return pl.DataFrame(rows)


def _engine(**kwargs: Any) -> WeeklyRefitTeamEngine:
    options: dict[str, Any] = {
        "half_life_days": (40.0, None),
        "prior_matches": (2.0, 8.0),
        "inner_holdout_gameweeks": 3,
        "minimum_inner_training_gameweeks": 2,
        "minimum_team_matches": 0,
    }
    options.update(kwargs)
    return WeeklyRefitTeamEngine(**options)


def _constant_ratings(fixtures: Sequence[Fixture], **kwargs: Any) -> TeamRatings:
    return TeamRatings(home=1.0, away=1.0)


def test_separate_development_identity_and_fixed_signals() -> None:
    engine = WeeklyRefitTeamEngine()
    assert engine.name == "retrospective_goals_xg_weekly_inner_selection_v1"
    assert engine.evidence_class == "retrospective_archive_development"
    assert engine._signals == SIGNALS
    with pytest.raises(TypeError, match="signals"):
        WeeklyRefitTeamEngine(signals=legacy.DEFAULT_SIGNALS)  # type: ignore[call-arg]


def test_legacy_model_is_byte_frozen_and_fit_is_inherited() -> None:
    path = repo_root() / "src/fpl/models/football_engine_v2.py"
    # Normalize checkout line endings only: Git can check out CRLF or LF on Windows.
    content = path.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(content).hexdigest() == (
        "ace9c6a0f0e90dfe7834533a4b6a731703b11ddbe7299e42af85a683632eeb19"
    )
    assert WeeklyRefitTeamEngine.fit is legacy.MultiSignalTeamEngine.fit


def test_default_hyperparameter_policy_matches_legacy_exactly() -> None:
    original, candidate = legacy.MultiSignalTeamEngine(signals=SIGNALS), WeeklyRefitTeamEngine()
    for key in (
        "_half_lives",
        "_prior_matches",
        "_minimum_team_matches",
        "_inner_holdout_gameweeks",
        "_minimum_inner_training_gameweeks",
        "_weight_step",
        "_minimum_signal_coverage",
        "_promoted_attack_prior",
        "_promoted_defence_prior",
        "_rate_floor",
        "_maximum_goals",
    ):
        assert getattr(candidate, key) == getattr(original, key)


def test_same_holdout_keys_as_legacy_and_first_gw_cannot_see_itself() -> None:
    frame, engine = _frame(), _engine()
    split = engine._inner_split(frame)
    assert split is not None
    batches = engine._inner_batches(frame)
    assert [(batch.season, batch.gw) for batch in batches] == [
        ("2025-26", 6),
        ("2025-26", 7),
        ("2025-26", 8),
    ]
    assert batches[0].training.equals(split[0])
    assert sum(batch.target.height for batch in batches) == split[1].height
    for batch in batches:
        assert batch.training["kickoff_time"].max() < batch.cutoff
        assert batch.training.filter(
            (pl.col("season") == batch.season) & (pl.col("gw") == batch.gw)
        ).is_empty()


def test_gw_observations_only_enter_next_pre_gw_fit() -> None:
    batches = _engine()._inner_batches(_frame())
    first, second = batches[:2]
    assert first.training["fixture"].unique().to_list() == [1, 2, 3, 4, 5]
    assert second.training["fixture"].unique().to_list() == [1, 2, 3, 4, 5, 6]
    assert set(second.target["fixture"]) == {7}


def test_dgw_legs_share_batch_but_delayed_leg_is_not_absorbed_early() -> None:
    frame = _frame()
    delayed = frame.filter(pl.col("gw") == 6).with_columns(
        pl.lit(106, dtype=pl.Int64).alias("fixture"),
        pl.col("kickoff_time") + timedelta(days=9),
    )
    batches = _engine()._inner_batches(pl.concat([frame, delayed]).sort("kickoff_time"))
    first, second, third = batches
    assert set(first.target["fixture"]) == {6, 106}
    assert set(first.target["team_code"]) == {3, 8}
    assert 106 not in first.training["fixture"]
    assert 106 not in second.training["fixture"]
    assert 106 in third.training["fixture"]


def test_delayed_earlier_nonholdout_gw_enters_when_event_time_allows() -> None:
    frame = _frame()
    delayed = frame.filter(pl.col("gw") == 2).with_columns(
        pl.lit(102, dtype=pl.Int64).alias("fixture"),
        pl.lit(START + timedelta(days=46)).alias("kickoff_time"),
    )
    first, second, _ = _engine()._inner_batches(pl.concat([frame, delayed]).sort("kickoff_time"))
    assert 102 not in first.training["fixture"]
    assert 102 in second.training["fixture"]


def test_observed_gws_are_ordered_by_actual_cutoff_not_numeric_gw() -> None:
    frame = _frame().with_columns(
        pl.when(pl.col("gw") == 7).then(pl.lit(22)).otherwise(pl.col("gw")).alias("gw")
    )
    assert [batch.gw for batch in _engine()._inner_batches(frame)] == [6, 22, 8]


def test_outer_future_truncation_equivalence_and_target_gw_exclusion() -> None:
    frame, cutoff = _frame(12), AsOf(START + timedelta(days=7 * 9))
    left, right = _engine(), _engine()
    left.fit_as_of(frame, cutoff)
    right.fit_as_of(frame.filter(pl.col("kickoff_time") < cutoff.ts), cutoff)
    assert left.parameters == right.parameters
    assert left.selector_diagnostics == right.selector_diagnostics
    assert left.goal_rate(3, 8, True) == right.goal_rate(3, 8, True)
    assert [batch["gw"] for batch in left.selector_diagnostics["weights"]["batches"]] == [6, 7, 8]


def test_as_of_requires_explicit_typed_timezone_boundary() -> None:
    with pytest.raises(TypeError, match="AsOf"):
        _engine().fit_as_of(_frame(), START)  # type: ignore[arg-type]


def test_same_inputs_and_reversed_row_order_have_identical_output() -> None:
    left, right = _engine(), _engine()
    left.fit(_frame())
    right.fit(_frame().reverse())
    assert left.parameters == right.parameters
    assert left.selector_diagnostics == right.selector_diagnostics
    environment = left.predict_environment(
        season="2025-26", fixture=99, home_team_code=3, away_team_code=8, gw=9
    )
    assert environment == right.predict_environment(
        season="2025-26", fixture=99, home_team_code=3, away_team_code=8, gw=9
    )
    for side in (environment.home, environment.away):
        assert math.fsum(side.goal_distribution) == pytest.approx(1.0, abs=1e-14)
        assert min(side.goal_distribution) >= 0.0


def test_unused_sdp_or_player_columns_cannot_change_the_candidate() -> None:
    left, right = _engine(), _engine()
    frame = _frame()
    left.fit(frame)
    right.fit(
        frame.with_columns(
            pl.lit(999999.0).alias("shots_on_target"),
            pl.lit(0.0).alias("expected_goals_on_target"),
            pl.lit(100000.0).alias("possession"),
            pl.lit(-999999.0).alias("touches_in_opposition_box"),
        )
    )
    assert left.parameters == right.parameters
    assert left.goal_rate(3, 8, True) == right.goal_rate(3, 8, True)
    assert set(right.fitted_signals) == {"goals", "expected_goals"}


def test_null_xg_remains_null_and_falls_back_to_goals() -> None:
    frame = _frame().with_columns(pl.lit(None, dtype=pl.Float64).alias("expected_goals"))
    engine = _engine()
    engine.fit(frame)
    assert engine.parameters.weights == {"goals": 1.0}
    assert set(engine.fitted_signals) == {"goals"}
    assert frame["expected_goals"].null_count() == frame.height
    assert engine.selector_diagnostics["weights"]["selected_score"] is None


def test_no_holdout_retains_original_fallback_and_equal_weights() -> None:
    candidate = _engine()
    candidate.fit(_frame(2))
    assert candidate.parameters.half_life_days == 160.0
    assert candidate.parameters.prior_matches == 8.0
    assert candidate.parameters.weights == {"expected_goals": 0.5, "goals": 0.5}
    assert candidate.selector_diagnostics["decay_prior"]["selected_score"] is None


def test_all_null_holdout_targets_retain_fallback() -> None:
    frame = _frame().with_columns(
        pl.when(pl.col("gw") >= 6).then(None).otherwise(pl.col("goals")).alias("goals")
    )
    engine = _engine()
    assert engine._select_decay_and_prior(frame, ({}, {})) == (160.0, 8.0)


def test_ties_follow_configured_grid_order_and_fixed_simplex_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(weekly, "fit_ratings", _constant_ratings)
    engine = _engine(half_life_days=(None, 40.0), prior_matches=(8.0, 2.0))
    frame = _frame().with_columns(pl.col("goals").cast(pl.Float64).alias("expected_goals"))
    engine.fit(frame)
    assert engine.parameters.half_life_days is None
    assert engine.parameters.prior_matches == 8.0
    assert engine.parameters.weights == {"expected_goals": 0.0, "goals": 1.0}
    assert engine.selector_diagnostics["weights"]["signal_order"] == ["expected_goals", "goals"]


def test_weekly_calls_fit_once_per_setting_per_complete_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[tuple[str, int] | None, ...]] = []

    def record(fixtures: Sequence[Fixture], **kwargs: Any) -> TeamRatings:
        seen.append(tuple(fixture.match_key for fixture in fixtures))
        return _constant_ratings(fixtures, **kwargs)

    monkeypatch.setattr(weekly, "fit_ratings", record)
    engine = _engine(half_life_days=(None,), prior_matches=(2.0,))
    engine._select_decay_and_prior(_frame(), ({}, {}))
    assert len(seen) == 3
    assert [len(keys) for keys in seen] == [10, 12, 14]
    assert [max(key[1] for key in keys if key is not None) for keys in seen] == [5, 6, 7]


def test_outer_prediction_season_promoted_priors_preserved_across_inner_seasons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[dict[int, float], dict[int, float]]] = []

    def record(fixtures: Sequence[Fixture], **kwargs: Any) -> TeamRatings:
        seen.append((kwargs["prior_attack"], kwargs["prior_defence"]))
        return _constant_ratings(fixtures, **kwargs)

    monkeypatch.setattr(weekly, "fit_ratings", record)
    engine = _engine(half_life_days=(None,), prior_matches=(2.0,))
    engine.set_promoted({"2024-25": frozenset({8}), "2025-26": frozenset({3})})
    engine.set_prediction_season("2025-26")
    frame = _frame().with_columns(
        pl.when(pl.col("gw") <= 6)
        .then(pl.lit("2024-25"))
        .otherwise(pl.col("season"))
        .alias("season")
    )
    engine.fit(frame)
    assert seen
    assert all(priors == ({3: 0.719}, {3: 1.309}) for priors in seen)
    assert engine._prediction_season == "2025-26"
    assert set(engine.fitted_signals["goals"].ratings.matches) == {3, 8}


def test_signal_scales_refit_inside_each_inner_training_window_only() -> None:
    frame = _frame().with_columns(
        pl.when(pl.col("gw") == 6)
        .then(1000.0)
        .otherwise(pl.col("expected_goals"))
        .alias("expected_goals")
    )
    engine = _engine()
    engine.fit(frame)
    scales = engine.selector_diagnostics["weights"]["batches"]
    for batch in scales:
        prior = frame.filter(pl.col("kickoff_time") < datetime.fromisoformat(batch["as_of"]))
        expected = prior["goals"].mean() / prior["expected_goals"].mean()
        assert batch["signal_scales"]["expected_goals"] == pytest.approx(expected)
    assert scales[0]["signal_scales"]["expected_goals"] > 0.5
    assert scales[1]["signal_scales"]["expected_goals"] < 0.02


def test_inner_loss_is_row_weighted_not_mean_of_gameweek_means(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(weekly, "fit_ratings", _constant_ratings)
    frame = _frame()
    extra = frame.filter(pl.col("gw") == 8).with_columns(
        pl.lit(108, dtype=pl.Int64).alias("fixture")
    )
    frame = pl.concat([frame, extra])
    engine = _engine(half_life_days=(None,), prior_matches=(2.0,))
    engine._select_decay_and_prior(frame, ({}, {}))
    batches = engine._inner_batches(frame)
    expected = sum(
        batch.target.height * engine._holdout_log_score(batch.target, lambda _: 1.0)
        for batch in batches
    ) / sum(batch.target.height for batch in batches)
    assert engine.selector_diagnostics["decay_prior"]["selected_score"] == expected


def test_hand_computable_frozen_vs_weekly_parameter_difference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unit-test the schedule using a one-rate Gamma-Poisson fit, not archive performance.

    Prior mean=1. Initial observation=1 makes both prior strengths predict 1; the frozen
    selector ties and keeps strength 16 first. Once H1=4 is observed, weak strength 2 predicts
    H2 at (1+4+2)/(2+2)=1.75 versus strength 16's 21/18. H2=4 favors 1.75, so weekly selects 2.
    """

    def one_rate(fixtures: Sequence[Fixture], **kwargs: Any) -> TeamRatings:
        prior = kwargs["prior_matches"]
        rate = (sum(fixture.measure for fixture in fixtures) + prior) / (len(fixtures) + prior)
        return TeamRatings(home=rate, away=rate)

    monkeypatch.setattr(weekly, "fit_ratings", one_rate)
    monkeypatch.setattr(legacy, "fit_ratings", one_rate)
    frame = (
        _frame(3)
        .filter(pl.col("was_home"))
        .with_columns(pl.when(pl.col("gw") == 1).then(1).otherwise(4).alias("goals"))
    )
    policy = {
        "half_life_days": (None,),
        "prior_matches": (16.0, 2.0),
        "minimum_team_matches": 0,
        "inner_holdout_gameweeks": 2,
        "minimum_inner_training_gameweeks": 1,
    }
    old = legacy.MultiSignalTeamEngine(signals=SIGNALS, **policy)
    new = WeeklyRefitTeamEngine(**policy)
    assert old._select_decay_and_prior(frame, ({}, {})) == (None, 16.0)
    assert new._select_decay_and_prior(frame, ({}, {})) == (None, 2.0)
    hand_loss = ((1.0 + math.lgamma(5)) + (1.75 - 4 * math.log(1.75) + math.lgamma(5))) / 2
    assert new.selector_diagnostics["decay_prior"]["selected_score"] == pytest.approx(hand_loss)


def test_frozen_chosen_scores_do_not_mutate_or_reselect_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = _frame()
    control = legacy.MultiSignalTeamEngine(
        signals=SIGNALS,
        half_life_days=(40.0, None),
        prior_matches=(2.0, 8.0),
        inner_holdout_gameweeks=3,
        minimum_inner_training_gameweeks=2,
    )
    control.fit(frame)
    before = control.parameters.as_report()

    def no_selection(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("diagnostic must not rerun selection")

    monkeypatch.setattr(control, "_select_decay_and_prior", no_selection)
    monkeypatch.setattr(control, "_select_weights", no_selection)
    scores = frozen_selected_inner_scores(control, frame)
    assert scores["decay_prior"] is not None and scores["weights"] is not None
    assert control.parameters.as_report() == before
    assert scores == frozen_selected_inner_scores(control, frame.reverse())


def test_selector_diagnostics_are_independent_copies() -> None:
    engine = _engine()
    engine.fit(_frame())
    report = engine.selector_diagnostics
    report["decay_prior"]["batches"].clear()
    assert len(engine.selector_diagnostics["decay_prior"]["batches"]) == 3


def test_retained_inner_guard_counts_are_measured_and_zero_for_safe_batches() -> None:
    engine = _engine()
    engine.fit(_frame())
    for stage in engine.selector_diagnostics.values():
        for batch in stage["batches"]:
            assert batch["event_time_violations"] == 0
            assert batch["target_gameweek_overlap"] == 0
            assert datetime.fromisoformat(batch["training_latest_kickoff"]) < (
                datetime.fromisoformat(batch["as_of"])
            )


def test_inner_guard_reports_count_unsafe_rows_instead_of_hardcoding_zero() -> None:
    frame = _frame()
    safe = _engine()._inner_batches(frame)[0]
    # Deliberately malformed diagnostic object, not a selector-created batch.
    contaminated = weekly.InnerBatch(
        safe.season, safe.gw, safe.cutoff, pl.concat([safe.training, safe.target]), safe.target
    )
    report = contaminated.as_report()
    assert report["event_time_violations"] == safe.target.height
    assert report["target_gameweek_overlap"] == safe.target.height
