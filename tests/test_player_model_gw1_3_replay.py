"""Synthetic-only exact inference observation; never a retained GW forecast."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, replace
from datetime import UTC, datetime

import duckdb
import pytest

from fpl.artifacts.prospective_points import artifact_bytes
from fpl.config import repo_root
from fpl.jobs import prospective_points_v1 as job
from fpl.models import sdp_environment
from fpl.storage.db import initialise
from fpl.storage.sdp_runtime import SdpState
from fpl.validate import player_model_gw1_3_replay as replay
from fpl.validate.player_model_gw1_3_replay import replay_gameweek

from .test_prospective_points_v1 import (
    AS_OF,
    _fixture,
    _load_registry,
    _player,
    _seed_dim_team,
    _seed_history,
    _teams,
)
from .test_sdp_counterfactual import inputs, state


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    path = tmp_path / "synthetic.duckdb"
    con = initialise(path)
    _load_registry(
        con,
        _teams(1, 2),
        [_player(11, 1001, 1, 1), _player(12, 1002, 4, 2), _player(13, 1003, 1, 2)],
        [_fixture(501, 1, 2)],
    )
    _seed_dim_team(con)
    _seed_history(
        con,
        players=[(1001, "GK", 1, 2, True), (1002, "FWD", 2, 1, False), (1003, "GK", 2, 1, False)],
    )
    con.close()
    # Only this synthetic fixture claims synthetic Git provenance. The observer
    # itself delegates to the unchanged job and never overrides real Git state.
    monkeypatch.setattr(job, "_git_head", lambda _: "a" * 40)
    monkeypatch.setattr(job, "_git_worktree_clean", lambda _: True)
    con = duckdb.connect(str(path), read_only=True)
    con.execute("SET TimeZone='UTC'")
    try:
        yield (
            con,
            {
                "repo": repo_root(),
                "db_path": path,
                "season": "2026-27",
                "gw": 1,
                "cutoff": AS_OF,
                "fixture_gameweeks": {501: 1},
            },
        )
    finally:
        con.close()


def baseline(con, args):
    return job.predict_prospective_points(
        con,
        repo=args["repo"],
        db_path=args["db_path"],
        as_of=args["cutoff"],
        season=args["season"],
        gw_from=args["gw"],
        gw_to=args["gw"],
        attacking="v3",
        appearance="seasonal",
        share_signal="auto",
        assists="coupled",
        draws=2000,
        base_seed=202627,
        max_points=34,
        football_environment_primary="sdp_v2",
    )


def frozen_prior():
    rows = [
        replace(
            row,
            season="2025-26",
            gw=37,
            team_code=101 if row.was_home else 102,
            opponent_team_code=102 if row.was_home else 101,
            kickoff=datetime(2026, 5, 15, tzinfo=UTC),
        )
        for row in state().rows
    ]
    return inputs(SdpState(rows=rows))


def test_exact_pipeline_artifact_and_component_observation(synthetic):
    con, args = synthetic
    original_compose = job.compose_fixture_full_points
    original_selector = sdp_environment.select_environments
    expected = baseline(con, args)
    actual = replay_gameweek(con, **args)
    assert job.compose_fixture_full_points is original_compose
    assert sdp_environment.select_environments is original_selector
    assert actual["current"]["artifact_bytes"] == artifact_bytes(
        job.build_prospective_artifact(expected)
    )
    assert expected.shadow_incumbent is not None
    assert actual["incumbent"]["artifact_bytes"] == artifact_bytes(
        job.build_prospective_artifact(expected.shadow_incumbent)
    )
    by_key = {(row.fixture, row.code): row for row in expected.records}
    for row in actual["current"]["predictions"]:
        expected_row = by_key[row["fixture"], row["code"]]
        assert {key: row[key] for key in asdict(expected_row)} == {
            **asdict(expected_row),
            "kickoff_time": expected_row.kickoff_time.isoformat(),
        }
        assert row["opponent_team_code"] == (102 if row["was_home"] else 101)
        assert row["web_name"] == f"P{row['code']}"
        assert row["selector"] == "SDP_MISSING_FALLBACK"
        assert row["components"]["disciplinary"] is None
        assert len(row["components"]["minutes"]) == 4
        assert sum(row["components"]["minutes"]) == pytest.approx(1)
        assert 0 <= row["components"]["probability_any_bonus"] <= 1
        assert row["probability_any_bonus"] == row["components"]["probability_any_bonus"]
    assert actual["current"]["predictions"] == actual["incumbent"]["predictions"]
    assert actual["pair_invariants"]["fallback_player_fixtures"] == 3
    for lane in ("current", "incumbent"):
        provenance = actual[lane]["provenance"]
        assert provenance["commit_sha"] == "a" * 40
        assert provenance["worktree_clean"] is True
        fit = provenance["minutes_fit_observation"]
        assert fit["history_rows"] == 42
        assert fit["parameters"]["name"] == "concentration_adaptive_shrinkage_player_minutes_v3"
        assert fit["selection"] == "unchanged_existing_fit_minutes_v3_on_prior_history"
    assert actual["incumbent"]["provenance"]["execution_football_environment"] == "disabled"


def test_counterfactual_only_changes_current_environment_and_keeps_true_knowledge(synthetic):
    con, args = synthetic
    strict = replay_gameweek(con, **args)
    frozen = frozen_prior()
    actual = replay_gameweek(con, **args, counterfactual_inputs=frozen)
    assert actual["incumbent"]["artifact_bytes"] == strict["incumbent"]["artifact_bytes"]
    assert actual["pair_invariants"]["fallback_player_fixtures"] == 0
    assert actual["current"]["artifact_bytes"] != strict["current"]["artifact_bytes"]
    assert {row["selector"] for row in actual["current"]["predictions"]} == {"SDP_PRIMARY"}
    assert {row["selector"] for row in actual["incumbent"]["predictions"]} == {"SDP_PRIMARY"}
    provenance = actual["current"]["provenance"]["football_environment"]
    assert provenance["cutoff"] == AS_OF.isoformat()
    assert provenance["model_known_at"] == frozen.model.payload["known_at"]
    assert datetime.fromisoformat(provenance["model_known_at"]) > AS_OF
    assert provenance["counterfactual"]["later_known_source_versions"] > 0
    assert (
        provenance["source_versions"][0]["known_at"] == frozen.state.rows[0].provenance["known_at"]
    )


def test_replay_is_byte_identical_and_never_writes_source(synthetic):
    con, args = synthetic
    before = hashlib.sha256(args["db_path"].read_bytes()).hexdigest()
    first = replay_gameweek(con, **args)
    second = replay_gameweek(con, **args)
    assert first == second
    assert hashlib.sha256(args["db_path"].read_bytes()).hexdigest() == before


def test_dirty_git_is_not_relabelled_clean(synthetic, monkeypatch):
    con, args = synthetic
    monkeypatch.setattr(job, "_git_worktree_clean", lambda _: False)
    with pytest.raises(ValueError, match="requires a clean Git worktree"):
        replay_gameweek(con, **args)


def test_observer_restores_bindings_when_original_composer_raises(synthetic, monkeypatch):
    con, args = synthetic
    original_selector = sdp_environment.select_environments

    def broken(*args, **kwargs):
        raise RuntimeError("synthetic composer failure")

    monkeypatch.setattr(job, "compose_fixture_full_points", broken)
    with pytest.raises(RuntimeError, match="synthetic composer failure"):
        replay_gameweek(con, **args, counterfactual_inputs=frozen_prior())
    assert job.compose_fixture_full_points is broken
    assert sdp_environment.select_environments is original_selector


def test_composer_input_mutation_invalidates(synthetic, monkeypatch):
    con, args = synthetic
    original = job.compose_fixture_full_points

    def mutating(players, *args, **kwargs):
        result = original(players, *args, **kwargs)
        object.__setattr__(players[0], "residual_mean", 98765.0)
        return result

    monkeypatch.setattr(job, "compose_fixture_full_points", mutating)
    with pytest.raises(ValueError, match="INVALIDATED_BY_IMPLEMENTATION_BUG: composer mutated"):
        replay_gameweek(con, **args)
    assert job.compose_fixture_full_points is mutating


def test_fallback_component_difference_invalidates_even_if_points_unchanged(synthetic, monkeypatch):
    con, args = synthetic
    original = job.compose_fixture_full_points
    calls = 0

    def inconsistent(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == 2:
            result[0] = replace(result[0], probability_any_bonus=0.123456)
        return result

    monkeypatch.setattr(job, "compose_fixture_full_points", inconsistent)
    with pytest.raises(ValueError, match="INVALIDATED_BY_IMPLEMENTATION_BUG: fallback"):
        replay_gameweek(con, **args)


def test_missing_composed_identity_invalidates(synthetic, monkeypatch):
    con, args = synthetic
    original = job.compose_fixture_full_points

    def incomplete(*args, **kwargs):
        return original(*args, **kwargs)[:-1]

    monkeypatch.setattr(job, "compose_fixture_full_points", incomplete)
    with pytest.raises(
        ValueError, match="INVALIDATED_BY_IMPLEMENTATION_BUG: composer result player"
    ):
        replay_gameweek(con, **args)


def test_whole_gw_missing_fixture_rejected(synthetic):
    con, args = synthetic
    args["fixture_gameweeks"] = {501: 1, 502: 1}
    with pytest.raises(ValueError, match="incomplete paired fixture compositions"):
        replay_gameweek(con, **args)


@pytest.mark.parametrize("bad", [{501: 4}, {True: 1}, {501: True}])
def test_fixture_identity_bounds(synthetic, bad):
    con, args = synthetic
    args["fixture_gameweeks"] = bad
    with pytest.raises(ValueError, match="INVALIDATED_BY_IMPLEMENTATION_BUG"):
        replay_gameweek(con, **args)


def test_minutes_observer_rejects_target_history_before_existing_fit(synthetic, monkeypatch):
    con, args = synthetic
    original = job.predict_prospective_points
    original_suite = replay.default_component_suite()
    fit_calls = 0

    def tracked_fit(history, as_of):
        nonlocal fit_calls
        fit_calls += 1
        return original_suite.fit_minutes(history, as_of)

    monkeypatch.setattr(
        replay, "default_component_suite", lambda: replace(original_suite, fit_minutes=tracked_fit)
    )

    def injected(con, **kwargs):
        from fpl.types import Position
        from fpl.validate.minutes_baselines import HistoryRow

        row = HistoryRow("2026-27", 1, 501, AS_OF, 1001, Position.GK, 1, 2, True, 90)
        kwargs["suite"].fit_minutes((row,), AS_OF)
        return original(con, **kwargs)

    monkeypatch.setattr(job, "predict_prospective_points", injected)
    with pytest.raises(ValueError, match="target/future minutes entered fit history"):
        replay_gameweek(con, **args)
    assert fit_calls == 0
