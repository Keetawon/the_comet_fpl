"""Synthetic only: separate claims, controls first, reference identity and no retries."""

import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from fpl.models.attacking_baselines import poisson_pmf
from fpl.models.points_composition import ComponentDistributions, FixturePlayer, conditional_rate
from fpl.types import Position
from fpl.validate import dev_player_opportunity as runner
from fpl.validate.development_reference_components import (
    DevelopmentReferenceComponents,
    ReferenceMinutesRow,
    ReferencePlayerComponents,
    ValidatedMinutesControlCache,
    ValidatedMinutesControlFold,
)
from fpl.validate.minutes_baselines import TargetRow

SOURCE_ROOT = Path(__file__).resolve().parents[1]
CONFIG = SOURCE_ROOT / "config/player_opportunity_evaluation.yaml"


def contract():
    result = yaml.safe_load(CONFIG.read_bytes())
    result.update(
        expected_folds=2, expected_rows=4, expected_direct_proxy_rows=0, season_rows={"2025-26": 4}
    )
    return result


def sample(gw):
    cutoff = datetime(2025, 9, 1, tzinfo=UTC) + timedelta(days=gw * 7)
    targets = [
        TargetRow("2025-26", gw, gw, cutoff, code, Position.MID, 1, 2, True) for code in (1, 2)
    ]
    minutes = (0.1, 0.2, 0.3, 0.4)
    metadata = json.dumps({"maximum_prior_kickoff": None})
    fold = ValidatedMinutesControlFold(
        "2025-26",
        gw,
        cutoff,
        tuple(ReferenceMinutesRow(t, 100, minutes, False, False, "{}") for t in targets),
        "a" * 64,
        "b" * 64,
        "c" * 64,
        metadata,
    )
    team_pmf = poisson_pmf(0.36)
    team_scale = sum(k * p for k, p in enumerate(team_pmf))
    players = []
    for t in targets:
        goals = poisson_pmf(conditional_rate(team_scale / 2, 0.9, cap=team_scale))
        assists = poisson_pmf(conditional_rate(team_scale / 4, 0.9, cap=team_scale * 0.5))
        component = ComponentDistributions(Position.MID, minutes, goals, assists, poisson_pmf(1))
        players.append(
            ReferencePlayerComponents(
                t,
                100,
                FixturePlayer(t.code, component, 0, 2),
                False,
                False,
                (),
                (),
                "{}",
                0.2,
                0.1,
                0.2,
                0.1,
                team_scale / 2,
                team_scale / 4,
                False,
            )
        )
    reference = DevelopmentReferenceComponents(
        "2025-26",
        gw,
        cutoff,
        tuple(players),
        ((gw, 100, team_pmf),),
        json.dumps({"assist_conversion": 0.5}),
        "{}",
    )
    archive = [
        {
            "season": t.season,
            "gw": gw,
            "fixture": gw,
            "kickoff_time": cutoff,
            "as_of": cutoff,
            "code": t.code,
            "position": t.position.value,
            "team_id": 1,
            "opponent_team_id": 2,
            "was_home": True,
            "team_code": 100,
            "minutes": 90,
            "goals_scored": t.code - 1,
            "assists": t.code - 1,
            "expected_goals": 0.2,
            "expected_assists": 0.1,
        }
        for t in targets
    ]
    return fold, reference, archive


def test_contract_pins_fixed_parameters_and_both_original_181fold_gates(monkeypatch):
    monkeypatch.setattr(runner, "CONFIG", str(CONFIG))
    for component in ("goals", "assists"):
        value = runner.load_contract(SOURCE_ROOT, component)
        assert value["minimum_gate_folds"] == 181
        assert value["candidate_identity"][component] == runner.NAMES[component]
        assert value["role_prior_minutes"] == 900
        assert value["player_prior_minutes"] == 90


def test_unregistered_guard_blocks_before_reference_files_or_claim(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "git_clean_head", lambda root: "a" * 40)
    monkeypatch.setattr(runner.subprocess, "check_output", lambda *a, **k: runner.BRANCH)
    unregistered = contract()
    unregistered["registration_status"] = "PENDING_REFERENCE_CACHE"
    monkeypatch.setattr(runner, "load_contract", lambda *a: unregistered)
    with pytest.raises(ValueError, match="UNREGISTERED"):
        runner.snapshot(tmp_path, tmp_path / "none", "goals", tmp_path, tmp_path / "none")


def test_config_hash_drift_is_rejected_before_any_model(tmp_path, monkeypatch):
    altered = tmp_path / "altered.yaml"
    altered.write_bytes(CONFIG.read_bytes() + b"\n")
    monkeypatch.setattr(runner, "CONFIG", str(altered))
    with pytest.raises(ValueError, match="fingerprint"):
        runner.load_contract(SOURCE_ROOT, "goals")


@pytest.mark.parametrize("component", ["goals", "assists"])
def test_exact_full_control_reproduction_and_measured_target_coverage(component):
    values = [sample(gw) for gw in (1, 2)]
    cache = ValidatedMinutesControlCache(tuple(v[0] for v in values), "{}")
    report = runner.validate_controls(
        cache,
        [v[1] for v in values],
        [row for v in values for row in v[2]],
        component=component,
        contract=contract(),
    )
    assert report["rows"] == 4
    assert report["folds"] == 2
    assert report["conditional_pmf_maximum_difference"] == 0
    assert report["signal_and_target_coverage"] == 1


@pytest.mark.parametrize(
    "change",
    ["missing_target", "missing_signal", "team", "GW", "code", "PMF", "minutes", "duplicate"],
)
def test_control_contradictions_fail_closed_before_candidate(change):
    values = [sample(gw) for gw in (1, 2)]
    cache = ValidatedMinutesControlCache(tuple(v[0] for v in values), "{}")
    refs = [v[1] for v in values]
    rows = [row for v in values for row in v[2]]
    if change == "missing_target":
        rows[0]["goals_scored"] = None
    elif change == "missing_signal":
        rows[0]["expected_goals"] = None
    elif change == "team":
        rows[0]["team_code"] = 999
    elif change == "GW":
        rows[0]["gw"] = 99
    elif change == "code":
        rows[0]["code"] = 999
    elif change == "duplicate":
        refs[1] = refs[0]
    else:
        old = refs[0].rows[0]
        parts = replace(
            old.player.components,
            **(
                {"goals": poisson_pmf(0.4)}
                if change == "PMF"
                else {"minutes": (1.0, 0.0, 0.0, 0.0)}
            ),
        )
        altered = replace(old, player=replace(old.player, components=parts))
        refs[0] = replace(refs[0], rows=(altered, refs[0].rows[1]))
    with pytest.raises(ValueError, match=r"coverage|identity|PMF|minutes|cutoff"):
        runner.validate_controls(cache, refs, rows, component="goals", contract=contract())


@pytest.mark.parametrize("component", ["goals", "assists"])
def test_required_baselines_preserve_whole_gw_cutoff_and_future_truncation(component):
    first = sample(1)
    second = sample(2)
    future = sample(3)
    original = runner.baseline_predictions(first[2], second[1], component)
    expanded = runner.baseline_predictions(first[2] + second[2] + future[2], second[1], component)
    assert original == expanded
    assert all(sum(pmf) == pytest.approx(1) for pair in original.values() for pmf in pair)


def test_history_preserves_null_signals_and_keeps_labels_outside_predictors():
    _, _, rows = sample(1)
    rows[0]["expected_goals"] = None
    history = runner.prepare_history(rows, {}, component="goals", database_sha256="a" * 64)
    assert history[0].signal is None
    assert not hasattr(history[0].target, "goals_scored")
    assert history[0].role_context is None


@pytest.fixture
def isolated_run(tmp_path, monkeypatch):
    values = [sample(gw) for gw in (1, 2)]
    minutes = ValidatedMinutesControlCache(tuple(v[0] for v in values), "{}")
    refs = tuple(v[1] for v in values)
    archive = [row for v in values for row in v[2]]

    @contextmanager
    def connect(*args, **kwargs):
        assert kwargs == {"read_only": True}
        yield object()

    monkeypatch.setattr(runner, "connect", connect)
    monkeypatch.setattr(runner, "snapshot", lambda *args: {"unchanged": True})
    monkeypatch.setattr(runner, "load_contract", lambda *args: contract())
    monkeypatch.setattr(runner, "read_minutes_control_cache", lambda *args, **kwargs: minutes)
    monkeypatch.setattr(runner, "load_component_reference_cache", lambda *args, **kwargs: refs)
    monkeypatch.setattr(runner, "load_role_cache", lambda *args, **kwargs: {})
    monkeypatch.setattr(runner, "load_archive", lambda *args: archive)
    calls = []

    def reserve(root, name, provenance):
        calls.append(name)
        path = tmp_path / f"{name}.claim.json"
        runner.publish_json(path, provenance)
        return path

    monkeypatch.setattr(runner, "reserve_program_claim", reserve)
    args = {
        "root": tmp_path / "repo",
        "db": tmp_path / "source.duckdb",
        "minutes_cache": tmp_path / "minutes",
        "component_cache": tmp_path / "components",
        "role_result": tmp_path / "roles.json",
        "output": tmp_path / "result",
        "component": "goals",
    }
    return args, calls, values


@pytest.mark.parametrize("component", ["goals", "assists"])
def test_full_synthetic_run_preserves_pmf_fallback_and_independent_claim(isolated_run, component):
    args, calls, _ = isolated_run
    args["component"] = component
    result = runner.run(**args)
    assert calls == [runner.NAMES[component]]
    assert result["completed"]
    assert result["verdict"] == "INELIGIBLE"
    assert result["row_count"] == 4
    assert result["fold_count"] == 2
    assert result["development_synthesis_eligible"] is False
    assert result["promotion_permitted"] is False
    assert result["relative_log_lift_vs_current"] == 0
    for receipt in result["folds"]:
        path = args["output"] / receipt["file"]
        assert runner.file_sha256(path) == receipt["sha256"]
        for row in json.loads(path.read_bytes())["rows"]:
            assert row["candidate"] == row["current"]
            assert row["conditional_candidate"] == row["conditional_current"]
            assert row["observed"]["count"] in (0, 1)
            assert row["role_probabilities"] is None
            assert sum(row["candidate"]) == pytest.approx(1)


def test_dirty_guard_never_consumes_claim(isolated_run, monkeypatch):
    args, calls, _ = isolated_run

    def dirty(*args):
        raise ValueError("dirty worktree")

    monkeypatch.setattr(runner, "snapshot", dirty)
    with pytest.raises(ValueError, match="dirty"):
        runner.run(**args)
    assert not calls
    assert not args["output"].exists()


def test_control_failure_prevents_candidate_fit_and_claim(isolated_run, monkeypatch):
    args, calls, _ = isolated_run

    def bad(*args, **kwargs):
        raise ValueError("comparator failed")

    def forbidden(*args, **kwargs):
        raise AssertionError("candidate cannot be fitted")

    monkeypatch.setattr(runner, "validate_controls", bad)
    monkeypatch.setattr(runner, "fit_opportunity", forbidden)
    with pytest.raises(ValueError, match="comparator failed"):
        runner.run(**args)
    assert not calls
    assert not args["output"].exists()


def test_failed_second_batch_retains_first_claim_and_never_resumes(isolated_run, monkeypatch):
    args, calls, _ = isolated_run
    original = runner.fit_opportunity

    def fit(history, **kwargs):
        if kwargs["gw"] == 2:
            raise ValueError("synthetic fitting failure")
        return original(history, **kwargs)

    monkeypatch.setattr(runner, "fit_opportunity", fit)
    with pytest.raises(ValueError, match="synthetic fitting failure"):
        runner.run(**args)
    failure = json.loads((args["output"] / "failure.json").read_bytes())
    assert len(failure["completed_folds"]) == 1
    assert len(calls) == 1
    assert failure["claim_preserved"]
    assert not failure["retry_permitted"]
    assert not (args["output"] / "result.json").exists()
    with pytest.raises(ValueError, match="write-once"):
        runner.run(**args)


def test_postflight_external_cache_corruption_prevents_success(isolated_run, monkeypatch):
    args, _, values = isolated_run
    calls = 0

    def read(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("external fold content SHA changed")
        return ValidatedMinutesControlCache(tuple(v[0] for v in values), "{}")

    monkeypatch.setattr(runner, "read_minutes_control_cache", read)
    with pytest.raises(ValueError, match="external fold content SHA"):
        runner.run(**args)
    assert not (args["output"] / "result.json").exists()
    assert len(json.loads((args["output"] / "failure.json").read_bytes())["completed_folds"]) == 2


@pytest.mark.parametrize("source", ["component", "role"])
def test_postflight_other_external_sources_cannot_change(isolated_run, monkeypatch, source):
    args, _, values = isolated_run
    calls = 0

    def read(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError(f"external {source} fold hash changed")
        return tuple(v[1] for v in values) if source == "component" else {}

    name = "load_component_reference_cache" if source == "component" else "load_role_cache"
    monkeypatch.setattr(runner, name, read)
    with pytest.raises(ValueError, match="fold hash changed"):
        runner.run(**args)
    assert calls == 2
    assert not (args["output"] / "result.json").exists()


def test_completed_checkpoint_tamper_is_detected_before_result(isolated_run, monkeypatch):
    args, _, _ = isolated_run
    original = runner.summarize

    def score(rows, contract, candidate):
        # Only the synthetic test's own newly generated checkpoint is changed.
        path = args["output"] / "2025-26-gw01.json"
        path.write_bytes(path.read_bytes() + b" ")
        return original(rows, contract, candidate)

    monkeypatch.setattr(runner, "summarize", score)
    with pytest.raises(ValueError, match="completed output fold content changed"):
        runner.run(**args)
    assert not (args["output"] / "result.json").exists()


def test_source_drift_after_all_predictions_refuses_result(isolated_run, monkeypatch):
    args, _, _ = isolated_run
    calls = 0

    def snapshot(*args):
        nonlocal calls
        calls += 1
        return {"head": "old" if calls <= 2 else "changed"}

    monkeypatch.setattr(runner, "snapshot", snapshot)
    with pytest.raises(ValueError, match="postflight source"):
        runner.run(**args)
    assert len(json.loads((args["output"] / "failure.json").read_bytes())["completed_folds"]) == 2


def test_formal_fit_starts_only_after_every_control_is_verified(isolated_run, monkeypatch):
    args, calls, _ = isolated_run
    verified = False
    original_validate = runner.validate_controls
    original_fit = runner.fit_opportunity

    def validate(*args, **kwargs):
        nonlocal verified
        result = original_validate(*args, **kwargs)
        verified = True
        return result

    def fit(history, **kwargs):
        assert verified
        assert calls == [runner.NAMES["goals"]]
        return original_fit(history, **kwargs)

    monkeypatch.setattr(runner, "validate_controls", validate)
    monkeypatch.setattr(runner, "fit_opportunity", fit)
    result = runner.run(**args)
    assert result["completed"]


def test_real_archive_rows_are_not_needed_for_orchestration(isolated_run):
    args, _, _ = isolated_run
    result = runner.run(**args)
    assert result["row_count"] == 4
    first = json.loads((args["output"] / "2025-26-gw01.json").read_bytes())["rows"][0]
    assert set(first["opportunity"]["target"]) == {
        "season",
        "gw",
        "fixture",
        "code",
        "team_code",
        "kickoff",
        "as_of",
        "identity_source",
    }
    assert first["kickoff"] == first["as_of"]
    assert first["opportunity"]["target"]["team_code"] == 100
    assert not first["oos_role_forecast_present"]
    assert result["finished_at_utc"] >= result["started_at_utc"]
