"""Synthetic source/PIT/count proofs; never refit a frozen opportunity candidate."""

import json
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from fpl.models.attacking_baselines import poisson_pmf
from fpl.types import Position
from fpl.validate import dev_player_saves_opportunity as runner
from fpl.validate.player_saves_opportunity import (
    OosShotForecast,
    ShotObservation,
    fit_precision,
    predict_saves,
)

AS_OF = datetime(2025, 9, 1, tzinfo=UTC)
OLD = AS_OF - timedelta(days=7)
KNOWN = datetime(2026, 9, 7, tzinfo=UTC)
CONTROL = poisson_pmf(3)


def observations(n=160):
    return tuple(
        ShotObservation("2025-26", 1, i + 1, 10, OLD, 10, 4, str(i), "a" * 64, KNOWN)
        for i in range(n)
    )


def forecast():
    return OosShotForecast(
        "2025-26", 2, 999, 10, 20, AS_OF, AS_OF + timedelta(days=1), 15.0, OLD, "b" * 64
    )


def test_hand_computable_decomposition_and_same_poisson_support():
    p = fit_precision(observations(), as_of=AS_OF, excluded_gw=("2025-26", 2))
    assert p.fraction == 0.4 and p.shots == 1600 and p.sot == 640
    result = predict_saves(forecast(), p, save_fraction=0.5, incumbent=CONTROL)
    assert result.expected_sot_faced == 6 and result.rate == 3
    assert result.probabilities == CONTROL and not result.fallback
    assert sum(result.probabilities) == pytest.approx(1, abs=1e-14)


def test_last_capture_time_preserved_but_future_event_excluded():
    past = observations()
    forbidden = [
        replace(past[0], fixture=998, kickoff=AS_OF + timedelta(days=2), sot=10),
        replace(past[0], fixture=997, kickoff=AS_OF - timedelta(days=2), gw=2, sot=10),
    ]
    assert fit_precision(
        past + tuple(forbidden), as_of=AS_OF, excluded_gw=("2025-26", 2)
    ) == fit_precision(past, as_of=AS_OF, excluded_gw=("2025-26", 2))
    assert all(r.known_at > AS_OF for r in past)


@pytest.mark.parametrize("hours", [0, 1, 6])
def test_unproved_completion_six_hour_boundary(hours):
    records = tuple(replace(r, kickoff=AS_OF - timedelta(hours=hours)) for r in observations())
    assert fit_precision(records, as_of=AS_OF, excluded_gw=("2025-26", 2)).fraction is None


def test_null_never_zero_filled_and_whole_version_not_counted_twice():
    data = observations()
    p = fit_precision(
        (*data[:159], replace(data[-1], sot=None)), as_of=AS_OF, excluded_gw=("2025-26", 2)
    )
    assert p.measured_sides == 159 and p.fraction is None and p.sot == 636
    assert (
        predict_saves(forecast(), p, save_fraction=0.673, incumbent=CONTROL).probabilities
        is CONTROL
    )
    with pytest.raises(ValueError, match="duplicate"):
        fit_precision((*data, data[0]), as_of=AS_OF, excluded_gw=("2025-26", 2))


def test_explicit_zero_is_real_zero_opportunity_not_missing():
    p = fit_precision(
        tuple(replace(r, sot=0) for r in observations()), as_of=AS_OF, excluded_gw=("2025-26", 2)
    )
    result = predict_saves(forecast(), p, save_fraction=0.673, incumbent=CONTROL)
    assert result.probabilities == (1.0,) + (0.0,) * 10 and not result.fallback
    regular = fit_precision(observations(), as_of=AS_OF, excluded_gw=("2025-26", 2))
    assert (
        predict_saves(
            replace(forecast(), predicted_shots=0), regular, save_fraction=0.673, incumbent=CONTROL
        ).rate
        == 0
    )


def test_unknown_shot_forecast_uses_exact_original_object():
    p = fit_precision(observations(), as_of=AS_OF, excluded_gw=("2025-26", 2))
    assert (
        predict_saves(
            replace(forecast(), predicted_shots=None), p, save_fraction=0.5, incumbent=CONTROL
        ).probabilities
        is CONTROL
    )


@pytest.mark.parametrize("fraction", [float("nan"), float("inf"), -float("inf"), -0.01, 1.01])
@pytest.mark.parametrize("shots", [15.0, None])
def test_invalid_external_precision_fails_even_before_missing_volume_fallback(fraction, shots):
    p = fit_precision(observations(), as_of=AS_OF, excluded_gw=("2025-26", 2))
    with pytest.raises(ValueError, match="invalid pooled shot precision"):
        predict_saves(
            replace(forecast(), predicted_shots=shots),
            replace(p, fraction=fraction),
            save_fraction=0.5,
            incumbent=CONTROL,
        )


@pytest.mark.parametrize("error", [-1e-10, 1e-10])
def test_incumbent_mass_uses_absolute_not_relative_tolerance(error):
    p = fit_precision(observations(), as_of=AS_OF, excluded_gw=("2025-26", 2))
    wrong = (CONTROL[0] + error, *CONTROL[1:])
    with pytest.raises(ValueError, match="unchanged incumbent"):
        predict_saves(forecast(), p, save_fraction=0.5, incumbent=wrong)


@pytest.mark.parametrize(
    "changes",
    [
        {"gw": 3},
        {"as_of": AS_OF + timedelta(days=1)},
        {"defending_team_code": 10},
        {"kickoff": AS_OF - timedelta(days=1)},
        {"maximum_upstream_training_event": AS_OF},
        {"maximum_upstream_training_event": AS_OF - timedelta(hours=6)},
        {"predicted_shots": -1.0},
        {"predicted_shots": float("nan")},
    ],
)
def test_wrong_opponent_target_clock_future_upstream_or_invalid_mean_fail(changes):
    p = fit_precision(observations(), as_of=AS_OF, excluded_gw=("2025-26", 2))
    with pytest.raises(ValueError, match=r"identity differs|leakage|invalid predicted"):
        predict_saves(replace(forecast(), **changes), p, save_fraction=0.673, incumbent=CONTROL)


def test_same_gw_dgw_legs_get_identical_fit_and_season_history_is_prior_only():
    past = tuple(replace(r, season="2024-25") for r in observations())
    p = fit_precision(past, as_of=AS_OF, excluded_gw=("2025-26", 2))
    first = predict_saves(forecast(), p, save_fraction=0.5, incumbent=CONTROL)
    second = predict_saves(
        replace(forecast(), fixture=1000, kickoff=AS_OF + timedelta(days=4)),
        p,
        save_fraction=0.5,
        incumbent=CONTROL,
    )
    assert first == second


@pytest.mark.parametrize(("shots", "sot"), [(3, 4), (-1, 0), (3, -1), (3, True)])
def test_count_semantics_fail_closed(shots, sot):
    with pytest.raises(ValueError, match="invalid measured"):
        fit_precision(
            (replace(observations()[0], shots=shots, sot=sot),),
            as_of=AS_OF,
            excluded_gw=("2025-26", 2),
        )


def test_dirty_guard_precedes_any_database_or_model_access(monkeypatch):
    def dirty(_root):
        raise ValueError("dirty worktree")

    monkeypatch.setattr(runner, "git_clean_head", dirty)
    with pytest.raises(ValueError, match="dirty"):
        runner.snapshot(Path("nowhere"), Path("missing.duckdb"))


def test_write_once_refusal_precedes_any_fit(tmp_path):
    with pytest.raises(FileExistsError):
        runner.run(tmp_path, Path("missing.duckdb"), tmp_path, tmp_path)


def test_actual_preregistered_contract_bytes_load():
    root = Path(__file__).resolve().parents[1]
    if runner.CONFIG_SHA256.startswith("UNREGISTERED"):
        pytest.fail("final contract must be pinned before formal run")
    assert runner.load_contract(root)["candidate"] == runner.NAME


@pytest.mark.parametrize("factory_drift", [False, True])
def test_keeper_comparator_metadata_and_exact_refusal_precede_candidate_claim(
    tmp_path, monkeypatch, factory_drift
):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "results").mkdir()
    (root / "coverage.json").write_text('{"eligible_rows": 1, "coverage_passed": true}')
    (root / runner.chance_reference.CONFIG).write_text("synthetic: true")
    (root / runner.CHANCE).write_text('{"historical_fit_provenance": []}')
    target = SimpleNamespace(season="2025-26", gw=2, fixture=999, code=1, position=Position.GK)
    cached = SimpleNamespace(target=target, team_code=20)
    fold = SimpleNamespace(season="2025-26", gw=2, as_of=AS_OF, rows=[cached])
    players = [
        {
            "season": "2025-26",
            "gw": 1,
            "fixture": 1,
            "code": 1,
            "kickoff_time": OLD,
            "minutes": 90,
            "saves": 3,
            "goals_conceded": 1,
        },
        {
            "season": "2025-26",
            "gw": 2,
            "fixture": 999,
            "code": 1,
            "kickoff_time": AS_OF,
            "minutes": 90,
            "saves": 2,
            "goals_conceded": 0,
        },
    ]
    reproduction = {"historical_rows": 3800}
    monkeypatch.setattr(runner, "snapshot", lambda *a: {"synthetic": True})
    monkeypatch.setattr(runner, "load_contract", lambda *a: {"coverage_report": "coverage.json"})
    monkeypatch.setattr(
        runner, "read_minutes_control_cache", lambda *a, **k: SimpleNamespace(folds=[fold])
    )
    monkeypatch.setattr(runner, "connect", lambda *a, **k: nullcontext(None))
    monkeypatch.setattr(
        runner,
        "load_source",
        lambda *a: ([], {"2025-26:999:20": {"opponent_team_code": 10}}, players),
    )
    monkeypatch.setattr(
        runner, "coverage", lambda *a: json.loads((root / "coverage.json").read_bytes())
    )
    monkeypatch.setattr(runner.chance_reference, "_load_upstream", lambda *a: {})
    monkeypatch.setattr(
        runner.chance_reference,
        "reproduce_incumbent",
        lambda *a: ({"2025-26:999:10": (1.0, poisson_pmf(1))}, reproduction),
    )
    if factory_drift:
        monkeypatch.setattr(
            runner,
            "default_component_suite",
            lambda: SimpleNamespace(
                fit_saves=lambda _: SimpleNamespace(predict=lambda *a: CONTROL)
            ),
        )

    def claim(*args):
        assert reproduction["keeper_comparator"] == {
            "identity": "gk_saves_poisson_from_team_conceded_v1",
            "compared_rows": 1,
            "folds": 1,
            "maximum_absolute_pmf_difference": 0.0,
            "absolute_tolerance": 0.0,
            "actual_component_suite_factory_checked": True,
            "reciprocal_current_team_pmf_expectation_used": True,
        }
        raise RuntimeError("stop synthetic test before any candidate claim")

    monkeypatch.setattr(runner, "reserve_program_claim", claim)
    error = ValueError if factory_drift else RuntimeError
    match = "factory/direct comparator differ" if factory_drift else "stop synthetic"
    with pytest.raises(error, match=match):
        runner.run(root, tmp_path / "fake.duckdb", tmp_path, tmp_path / "output")
    assert not (tmp_path / "output").exists()
