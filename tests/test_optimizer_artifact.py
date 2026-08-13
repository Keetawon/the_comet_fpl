"""Offline contract tests for the durable, provenance-bearing optimizer artifact.

These pin the artifact schema and provenance completeness, the deterministic ``run_id`` derivation
(stable for identical inputs, sensitive to every behaviour-defining input, insensitive to paths and
environment-discovered versions), immutable no-clobber and atomic-failure behaviour, strict-JSON /
non-finite rejection, and the job's fail-closed provenance discovery. No network or database access
and no live forecast pipeline is used: the forecast input is a small synthetic artifact.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from fpl.artifacts.optimizer_plan import (
    ForecastInputProvenance,
    OptimizerArtifactError,
    OptimizerArtifactExistsError,
    OptimizerPlanArtifact,
    OptimizerProvenance,
    SearchPolicy,
    SolverIdentity,
    SquadRulesProvenance,
    derive_optimizer_run_id,
    optimizer_artifact_bytes,
    read_optimizer_artifact,
    write_optimizer_artifact_atomic,
)
from fpl.artifacts.prospective_points import (
    ContractIdentity,
    ForecastArtifactManifest,
    ForecastArtifactRow,
    LiveInputProvenance,
    ProspectivePointsArtifact,
    write_artifact_atomic,
)
from fpl.jobs import optimize_squad
from fpl.jobs.optimize_squad import (
    _initial_squad_record,
    _solve,
    assemble_optimizer_artifact,
    build_forecast_provenance,
    main,
)
from fpl.optimize.rules import load_squad_rules

HASH = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
AS_OF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)


# --------------------------------------------------------------------------------------
# Synthetic forecast input (a legal 15-player population, no live pipeline)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Player:
    code: int
    position: str
    points: tuple[float, ...]
    cost: int = 40


def _distribution(mean: float) -> tuple[float, ...]:
    lower = math.floor(mean)
    fraction = mean - lower
    if fraction == 0.0:
        return (*((0.0,) * lower), 1.0)
    return (*((0.0,) * lower), 1.0 - fraction, fraction)


def _squad_players(horizon: int) -> tuple[_Player, ...]:
    values = {
        "GK": (2.0, 1.0),
        "DEF": (6.0, 5.0, 4.0, 3.0, 2.0),
        "MID": (9.0, 8.0, 7.0, 6.0, 5.0),
        "FWD": (10.0, 7.0, 4.0),
    }
    starts = {"GK": 1, "DEF": 10, "MID": 20, "FWD": 30}
    return tuple(
        _Player(code=starts[position] + offset, position=position, points=(score,) * horizon)
        for position, scores in values.items()
        for offset, score in enumerate(scores)
    )


def _artifact(horizon: int = 2) -> ProspectivePointsArtifact:
    players = _squad_players(horizon)
    rows: list[ForecastArtifactRow] = []
    for gw in range(1, horizon + 1):
        for player in sorted(players, key=lambda item: item.code):
            expected = player.points[gw - 1]
            rows.append(
                ForecastArtifactRow(
                    season="2026-27",
                    gw=gw,
                    code=player.code,
                    web_name=f"P{player.code}",
                    position=player.position,
                    team_id=player.code,
                    team_code=player.code,
                    now_cost=player.cost,
                    selected_by_percent=None,
                    availability_status="a",
                    chance_of_playing=None,
                    availability_multiplier=1.0,
                    fixture_ids=(gw * 1000 + player.code,),
                    kickoff_times=(datetime(2026, 8, 21 + gw, tzinfo=UTC),),
                    expected_points=expected,
                    availability_adjusted_expected_points=expected,
                    expected_bonus=0.0,
                    distribution=_distribution(expected),
                    cold_start_player=False,
                    stage_a_league_average_team=False,
                    attacking_signal_cold_start=False,
                    assist_signal_cold_start=False,
                    transferred_no_rescale=False,
                )
            )
    manifest = ForecastArtifactManifest(
        as_of=AS_OF,
        season="2026-27",
        gw_from=1,
        gw_to=horizon,
        row_count=len(rows),
        roster_size=len(players),
        fixture_count=len(rows),
        monte_carlo_draws=100,
        base_seed=1,
        fixture_points_support_max=40,
        freshness_cold_start=True,
        commit_sha="forecastcommit",
        database_sha256=HASH,
        contracts={"synthetic": ContractIdentity(name="synthetic", version="1", sha256=HASH)},
        component_modes={"test": "synthetic"},
        live_inputs=LiveInputProvenance(
            bootstrap_capture_id="synthetic",
            bootstrap_known_at=datetime(2026, 8, 1, tzinfo=UTC),
            bootstrap_payload_sha256=HASH,
            schedule_capture_ids=("synthetic",),
        ),
    )
    return ProspectivePointsArtifact(manifest=manifest, rows=tuple(rows))


def _provenance(
    *,
    optimizer_commit: str = "optcommit",
    forecast_path: str = "forecast.jsonl",
    forecast_sha: str = HASH,
    forecast_commit: str = "forecastcommit",
    rules_path: str = "squad_2026_27.yaml",
    rules_sha: str = HASH_B,
    rules_version: str = "1.0",
) -> OptimizerProvenance:
    return OptimizerProvenance(
        optimizer_commit_sha=optimizer_commit,
        forecast=ForecastInputProvenance(
            path=forecast_path,
            sha256=forecast_sha,
            forecast_schema="fpl.prospective-points",
            forecast_schema_version=1,
            as_of=AS_OF,
            gw_from=1,
            gw_to=5,
            commit_sha=forecast_commit,
        ),
        squad_rules=SquadRulesProvenance(
            path=rules_path, contract_version=rules_version, sha256=rules_sha
        ),
    )


def _policy(**overrides: object) -> SearchPolicy:
    base: dict[str, object] = {
        "candidate_pool_per_position": 10,
        "transfer_depth": 2,
        "transition_limit_per_state": 200,
        "beam_width": 30,
        "free_transfer_per_gameweek": 1,
        "free_transfer_bank_cap": 5,
        "hit_cost_points": 4,
        "maximum_transfers_per_gameweek": 20,
        "risk_lambda": 0.0,
        "search_method": "bounded",
        "optimality_scope": "bounded",
    }
    base.update(overrides)
    return SearchPolicy(**base)  # type: ignore[arg-type]


def _solver(**overrides: object) -> SolverIdentity:
    base: dict[str, object] = {
        "name": "PULP_CBC_CMD",
        "package": "pulp",
        "package_version": "3.3.2",
        "binary_version": "2.10.3",
        "options": ("randomSeed 0",),
        "seed": 0,
        "status": "Optimal",
    }
    base.update(overrides)
    return SolverIdentity(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# run_id derivation
# --------------------------------------------------------------------------------------


def test_run_id_is_stable_for_identical_behaviour_defining_inputs() -> None:
    first = derive_optimizer_run_id(_provenance(), _policy(), _solver())
    second = derive_optimizer_run_id(_provenance(), _policy(), _solver())
    assert first == second
    assert len(first) == 64


@pytest.mark.parametrize(
    "changed",
    [
        {"optimizer_commit": "different"},
        {"forecast_sha": HASH_C},
        {"forecast_commit": "different"},
        {"rules_sha": HASH_C},
        {"rules_version": "9.9"},
    ],
)
def test_changed_provenance_changes_run_id(changed: dict[str, str]) -> None:
    base = derive_optimizer_run_id(_provenance(), _policy(), _solver())
    assert derive_optimizer_run_id(_provenance(**changed), _policy(), _solver()) != base


@pytest.mark.parametrize(
    "changed",
    [
        {"risk_lambda": 0.5},
        {"candidate_pool_per_position": 8},
        {"transfer_depth": 1},
        {"transition_limit_per_state": 100},
        {"beam_width": 20},
        {"free_transfer_per_gameweek": 2},
        {"free_transfer_bank_cap": 3},
        {"hit_cost_points": 8},
        {"maximum_transfers_per_gameweek": 15},
    ],
)
def test_changed_search_policy_changes_run_id(changed: dict[str, object]) -> None:
    base = derive_optimizer_run_id(_provenance(), _policy(), _solver())
    assert derive_optimizer_run_id(_provenance(), _policy(**changed), _solver()) != base


def test_changed_solver_name_or_options_changes_run_id() -> None:
    base = derive_optimizer_run_id(_provenance(), _policy(), _solver())
    assert derive_optimizer_run_id(_provenance(), _policy(), _solver(name="OTHER")) != base
    assert derive_optimizer_run_id(_provenance(), _policy(), _solver(options=())) != base
    assert derive_optimizer_run_id(_provenance(), _policy(), _solver(seed=1)) != base


def test_run_id_ignores_paths_and_environment_versions_and_status() -> None:
    base = derive_optimizer_run_id(_provenance(), _policy(), _solver())
    # File paths are recorded but never part of the identity.
    assert (
        derive_optimizer_run_id(_provenance(forecast_path="/tmp/x"), _policy(), _solver()) == base
    )
    assert derive_optimizer_run_id(_provenance(rules_path="/tmp/r"), _policy(), _solver()) == base
    # Environment-discovered solver versions and the solve status are recorded, not identity.
    assert derive_optimizer_run_id(_provenance(), _policy(), _solver(package_version=None)) == base
    assert derive_optimizer_run_id(_provenance(), _policy(), _solver(binary_version="9")) == base
    assert derive_optimizer_run_id(_provenance(), _policy(), _solver(status="Infeasible")) == base


# --------------------------------------------------------------------------------------
# schema, provenance completeness, and round-trip
# --------------------------------------------------------------------------------------


def _build(horizon: int = 2, *, optimizer_commit: str = "optcommit") -> OptimizerPlanArtifact:
    artifact = _artifact(horizon)
    rules = load_squad_rules()
    initial, _index, plan, names = _solve(artifact, rules, 0.0)
    provenance = OptimizerProvenance(
        optimizer_commit_sha=optimizer_commit,
        forecast=build_forecast_provenance(artifact, "forecast.jsonl", HASH),
        squad_rules=SquadRulesProvenance(
            path="squad_2026_27.yaml", contract_version=rules.contract_version, sha256=HASH_B
        ),
    )
    return assemble_optimizer_artifact(
        initial=initial,
        plan=plan,
        names=names,
        provenance=provenance,
        rules=rules,
        risk_lambda=0.0,
        solver_package_version="3.3.2",
        solver_binary_version="2.10.3",
    )


def test_artifact_carries_complete_schema_and_provenance() -> None:
    artifact = _build()
    assert artifact.artifact_schema == "fpl.optimizer-plan"
    assert artifact.schema_version == 1
    assert artifact.status == "development_only_not_a_validated_production_recommendation"
    assert len(artifact.run_id) == 64

    provenance = artifact.provenance
    assert provenance.optimizer_commit_sha == "optcommit"
    assert provenance.optimizer_worktree_clean is True
    assert provenance.forecast.sha256 == HASH
    assert provenance.forecast.commit_sha == "forecastcommit"
    assert provenance.forecast.forecast_schema == "fpl.prospective-points"
    assert (provenance.forecast.gw_from, provenance.forecast.gw_to) == (1, 2)
    assert provenance.squad_rules.contract_version == "1.0"
    assert provenance.squad_rules.sha256 == HASH_B

    policy = artifact.search_policy
    assert policy.candidate_pool_per_position == 10
    assert policy.transfer_depth == 2
    assert policy.transition_limit_per_state == 200
    assert policy.beam_width == 30
    assert policy.maximum_transfers_per_gameweek == 20
    assert policy.risk_lambda == 0.0

    assert artifact.solver.name == "PULP_CBC_CMD"
    assert artifact.solver.options == ("randomSeed 0",)
    assert artifact.solver.seed == 0
    assert artifact.solver.status == "Optimal"

    assert len(artifact.initial_squad.members) == 15
    assert [m.code for m in artifact.initial_squad.members] == sorted(
        m.code for m in artifact.initial_squad.members
    )
    assert len(artifact.plan.weeks) == 2
    assert artifact.plan.weeks[0].captain.code == 30  # the top forward
    assert len(artifact.plan.weeks[0].starting_xi) == 11

    joined = " ".join(artifact.assumptions).lower()
    for token in ("availability", "gw1", "price", "selling", "bench", "ownership"):
        assert token in joined


def test_serialised_bytes_are_deterministic_and_round_trip(tmp_path: Path) -> None:
    artifact = _build()
    assert optimizer_artifact_bytes(artifact) == optimizer_artifact_bytes(_build())
    path = tmp_path / "plan.json"
    digest = write_optimizer_artifact_atomic(path, artifact)
    parsed = read_optimizer_artifact(path)
    assert parsed == artifact
    assert parsed.run_id == artifact.run_id
    import hashlib

    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()


def test_two_runs_from_same_fixture_have_identical_decision_and_run_id() -> None:
    first = _build()
    second = _build()
    assert first.run_id == second.run_id
    assert first.initial_squad == second.initial_squad
    assert first.plan == second.plan
    assert optimizer_artifact_bytes(first) == optimizer_artifact_bytes(second)


def test_changed_optimizer_commit_changes_run_id_end_to_end() -> None:
    assert _build(optimizer_commit="one").run_id != _build(optimizer_commit="two").run_id


# --------------------------------------------------------------------------------------
# validation: incomplete provenance, tampering, and non-finite values fail closed
# --------------------------------------------------------------------------------------


def test_incomplete_or_malformed_provenance_is_rejected() -> None:
    with pytest.raises(ValidationError):
        OptimizerProvenance(
            optimizer_commit_sha="",
            forecast=_provenance().forecast,
            squad_rules=_provenance().squad_rules,
        )
    with pytest.raises(ValidationError, match="commit_sha"):
        ForecastInputProvenance(
            path="f",
            sha256=HASH,
            forecast_schema="fpl.prospective-points",
            forecast_schema_version=1,
            as_of=AS_OF,
            gw_from=1,
            gw_to=5,
            commit_sha="",
        )
    with pytest.raises(ValidationError, match="sha256"):
        SquadRulesProvenance(path="r", contract_version="1.0", sha256="not-a-hash")


def test_run_id_mismatch_is_rejected_on_construction_and_read(tmp_path: Path) -> None:
    artifact = _build()
    tampered = artifact.model_dump(mode="json", by_alias=True)
    tampered["run_id"] = HASH
    with pytest.raises(ValidationError, match="run_id"):
        OptimizerPlanArtifact.model_validate(tampered)

    import json

    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(OptimizerArtifactError, match="run_id"):
        read_optimizer_artifact(path)


def test_non_finite_floats_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _policy(risk_lambda=float("nan"))
    with pytest.raises(ValidationError):
        _policy(risk_lambda=float("inf"))


def test_build_matches_self_validation() -> None:
    artifact = _build()
    assert artifact.run_id == derive_optimizer_run_id(
        artifact.provenance, artifact.search_policy, artifact.solver
    )


# --------------------------------------------------------------------------------------
# atomic write: no-clobber and failure cleanup
# --------------------------------------------------------------------------------------


def test_no_clobber_refuses_to_overwrite_existing_artifact(tmp_path: Path) -> None:
    path = tmp_path / "plan.json"
    artifact = _build()
    write_optimizer_artifact_atomic(path, artifact)
    original = path.read_bytes()
    with pytest.raises(OptimizerArtifactExistsError, match="overwrite"):
        write_optimizer_artifact_atomic(path, artifact)
    assert path.read_bytes() == original


def test_atomic_write_failure_cleans_temp_and_leaves_no_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "plan.json"

    def fail_replace(_source: str | Path, _target: str | Path) -> None:
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated"):
        write_optimizer_artifact_atomic(path, _build())
    assert not path.exists()
    assert list(tmp_path.glob(".plan.json.*.tmp")) == []


def test_read_rejects_malformed_artifact(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(OptimizerArtifactError):
        read_optimizer_artifact(path)


# --------------------------------------------------------------------------------------
# job: fail-closed provenance discovery around --output
# --------------------------------------------------------------------------------------


def _write_forecast(tmp_path: Path, horizon: int = 2) -> Path:
    path = tmp_path / "forecast.jsonl"
    write_artifact_atomic(path, _artifact(horizon))
    return path


def test_job_output_refuses_dirty_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    forecast = _write_forecast(tmp_path)
    out = tmp_path / "plan.json"
    monkeypatch.setattr(optimize_squad, "_git_worktree_clean", lambda _repo: False)
    monkeypatch.setattr(optimize_squad, "_git_head", lambda _repo: "deadbeef")
    assert main([str(forecast), "--output", str(out)]) == 1
    assert not out.exists()
    # stdout report is still emitted before the fail-closed provenance check.
    assert capsys.readouterr().out.strip().startswith("{")


def test_job_output_refuses_unresolvable_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    forecast = _write_forecast(tmp_path)
    out = tmp_path / "plan.json"
    monkeypatch.setattr(optimize_squad, "_git_worktree_clean", lambda _repo: True)
    monkeypatch.setattr(optimize_squad, "_git_head", lambda _repo: None)
    assert main([str(forecast), "--output", str(out)]) == 1
    assert not out.exists()


def test_job_writes_artifact_on_clean_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    forecast = _write_forecast(tmp_path)
    out = tmp_path / "plan.json"
    monkeypatch.setattr(optimize_squad, "_git_worktree_clean", lambda _repo: True)
    monkeypatch.setattr(optimize_squad, "_git_head", lambda _repo: "cafebabe" * 5)
    assert main([str(forecast), "--output", str(out)]) == 0
    plan = read_optimizer_artifact(out)
    assert plan.provenance.optimizer_commit_sha == "cafebabe" * 5
    assert plan.provenance.forecast.commit_sha == "forecastcommit"
    assert plan.provenance.squad_rules.contract_version == "1.0"
    assert len(plan.initial_squad.members) == 15


def test_job_output_is_no_clobber(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    forecast = _write_forecast(tmp_path)
    out = tmp_path / "plan.json"
    monkeypatch.setattr(optimize_squad, "_git_worktree_clean", lambda _repo: True)
    monkeypatch.setattr(optimize_squad, "_git_head", lambda _repo: "abad1dea" * 5)
    assert main([str(forecast), "--output", str(out)]) == 0
    original = out.read_bytes()
    assert main([str(forecast), "--output", str(out)]) == 1
    assert out.read_bytes() == original


def test_forecast_provenance_records_hash_and_horizon() -> None:
    artifact = _artifact(3)
    provenance = build_forecast_provenance(artifact, "forecast.jsonl", HASH)
    assert provenance.sha256 == HASH
    assert (provenance.gw_from, provenance.gw_to) == (1, 3)
    assert provenance.commit_sha == "forecastcommit"


def test_initial_squad_record_is_sorted_and_priced() -> None:
    artifact = _artifact(1)
    rules = load_squad_rules()
    initial, _index, _plan, _names = _solve(artifact, rules, 0.0)
    record = _initial_squad_record(initial)
    codes = [member.code for member in record.members]
    assert codes == sorted(codes)
    assert record.cost_tenths == sum(member.now_cost for member in record.members)
