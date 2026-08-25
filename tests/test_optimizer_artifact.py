"""Offline contract tests for the durable, provenance-bearing optimizer artifact.

These pin the artifact schema and provenance completeness, the deterministic ``run_id`` derivation
(stable for identical inputs, sensitive to every behaviour-defining input, insensitive to
relocatable paths), immutable no-clobber and atomic-failure behaviour, strict-JSON /
non-finite rejection, and the job's fail-closed provenance discovery. No network or database access
and no live forecast pipeline is used: the forecast input is a small synthetic artifact.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from fpl.artifacts.optimizer_plan import (
    ForecastInputProvenance,
    ManagerPlanContext,
    OptimizerArtifactError,
    OptimizerArtifactExistsError,
    OptimizerPlanArtifact,
    OptimizerProvenance,
    OwnedPlayerValueRecord,
    SearchPolicy,
    SolverIdentity,
    SquadRulesProvenance,
    TransferPlanRecord,
    build_optimizer_plan_artifact,
    derive_optimizer_decision_sha256,
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
from fpl.ingest.manager_team import (
    ManagerCaptureCompleteness,
    ManagerCaptureProvenance,
    ManagerSquadPlayer,
    ManagerTeamCapture,
    ManagerTransferReplayRules,
    derive_manager_capture_id,
    manager_capture_bytes,
    manager_capture_sha256,
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
from fpl.optimize.squad import OptimizationError

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
        "FWD": (10.0, 7.0, 4.0, 0.0),
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
            season="2026-27",
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


def _run_id(
    provenance: OptimizerProvenance | None = None,
    policy: SearchPolicy | None = None,
    solver: SolverIdentity | None = None,
    decision_sha256: str = HASH_C,
) -> str:
    return derive_optimizer_run_id(
        provenance or _provenance(),
        policy or _policy(),
        solver or _solver(),
        decision_sha256,
    )


# --------------------------------------------------------------------------------------
# run_id derivation
# --------------------------------------------------------------------------------------


def test_run_id_is_stable_for_identical_behaviour_defining_inputs() -> None:
    first = _run_id()
    second = _run_id()
    assert first == second
    assert len(first) == 64


def test_explicit_platform_origin_preserves_legacy_run_id() -> None:
    assert _run_id(policy=_policy(plan_origin=None)) == _run_id(
        policy=_policy(plan_origin="platform")
    )


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
    base = _run_id()
    assert _run_id(provenance=_provenance(**changed)) != base


@pytest.mark.parametrize(
    "changed",
    [
        {"risk_lambda": 0.5},
        {"min_bench_appearance": 0.25},
        {"locked_codes": (30,)},
        {"excluded_codes": (31,)},
        {"plan_origin": "user_custom"},
        {"candidate_pool_per_position": 8},
        {"transfer_depth": 1},
        {"transition_limit_per_state": 100},
        {"beam_width": 20},
        {"free_transfer_per_gameweek": 2},
        {"free_transfer_bank_cap": 3},
        {"hit_cost_points": 8},
        {"maximum_transfers_per_gameweek": 15},
        {"search_method": "different"},
        {"optimality_scope": "different"},
    ],
)
def test_changed_search_policy_changes_run_id(changed: dict[str, object]) -> None:
    base = _run_id()
    assert _run_id(policy=_policy(**changed)) != base


def test_changed_solver_name_or_options_changes_run_id() -> None:
    base = _run_id()
    for changed in (
        {"name": "OTHER"},
        {"package": "other"},
        {"package_version": "9"},
        {"binary_version": "9"},
        {"options": ()},
        {"seed": 1},
        {"status": "Infeasible"},
    ):
        assert _run_id(solver=_solver(**changed)) != base


def test_run_id_ignores_only_relocatable_paths() -> None:
    base = _run_id()
    # File paths are recorded but never part of the identity.
    assert _run_id(provenance=_provenance(forecast_path="/tmp/x")) == base
    assert _run_id(provenance=_provenance(rules_path="/tmp/r")) == base


def test_changed_decision_hash_changes_run_id() -> None:
    assert _run_id(decision_sha256=HASH) != _run_id(decision_sha256=HASH_B)


# --------------------------------------------------------------------------------------
# schema, provenance completeness, and round-trip
# --------------------------------------------------------------------------------------


def _build(horizon: int = 2, *, optimizer_commit: str = "optcommit") -> OptimizerPlanArtifact:
    artifact = _artifact(horizon)
    rules = load_squad_rules()
    initial, index, plan, names = _solve(artifact, rules, 0.0)
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
        index=index,
        provenance=provenance,
        rules=rules,
        risk_lambda=0.0,
        solver_package_version="3.3.2",
        solver_binary_version="2.10.3",
    )


def _manager_build() -> OptimizerPlanArtifact:
    """Turn the stable v1 fixture into a small imported-team transfer decision."""
    base = _build()
    manager_provenance = base.provenance.model_copy(
        update={
            "forecast": base.provenance.forecast.model_copy(
                update={"selectable_player_registry_sha256": HASH}
            )
        }
    )
    outgoing = base.initial_squad.members[-1]
    incoming = outgoing.model_copy(
        update={
            "code": 999,
            "web_name": "P999",
            "team_id": 999,
            "team_code": 999,
            "now_cost": outgoing.now_cost + 10,
        }
    )
    plan_payload = base.plan.model_dump(mode="json")

    def replace_ref(ref: dict[str, object]) -> None:
        if ref["code"] == outgoing.code:
            ref["code"] = incoming.code
            ref["web_name"] = incoming.web_name

    for offset, week in enumerate(plan_payload["weeks"]):
        week["squad_after_transfers"] = [
            incoming.model_dump(mode="json") if member["code"] == outgoing.code else member
            for member in week["squad_after_transfers"]
        ]
        week["squad_after_transfers"].sort(key=lambda member: member["code"])
        week["squad_cost_tenths"] += 10
        for ref in week["starting_xi"]:
            replace_ref(ref)
        replace_ref(week["captain"])
        replace_ref(week["vice_captain"])
        replace_ref(week["bench_goalkeeper"])
        for ref in week["bench_order"]:
            replace_ref(ref)
        week["bank_before_tenths"] = 10 if offset == 0 else 0
        week["bank_after_tenths"] = 0
        if offset == 0:
            week["transfers_out"] = [{"code": outgoing.code, "web_name": outgoing.web_name}]
            week["transfers_in"] = [{"code": incoming.code, "web_name": incoming.web_name}]
            week["free_transfers_before"] = 0
            week["free_transfers_after"] = 0
            week["hit_points"] = 4
        else:
            week["transfers_out"] = []
            week["transfers_in"] = []
            week["free_transfers_before"] = 1
            week["free_transfers_after"] = 1
            week["hit_points"] = 0
    plan_payload["hit_points"] = 4
    plan_payload["expected_points_after_hits"] -= 4.0
    plan_payload["objective_value_after_hits"] -= 4.0
    plan = TransferPlanRecord.model_validate(plan_payload)

    initial = base.initial_squad.model_copy(update={"solver_status": "Imported"})
    solver = base.solver.model_copy(update={"status": "Imported"})
    policy = base.search_policy.model_copy(
        update={
            "plan_mode": "manager",
            "initial_free_transfers": 0,
            "plan_origin": "user_custom",
            "excluded_codes": (outgoing.code,),
        }
    )
    # An imported team's current market value may exceed its original budget; cash legality is
    # instead checked from bank plus the outgoing player's selling value.
    rules = base.rules.model_copy(update={"budget_tenths": base.initial_squad.cost_tenths - 10})
    manager = ManagerPlanContext(
        capture_id="manager-" + HASH,
        capture_sha256=HASH_B,
        selectable_player_registry_sha256=HASH,
        captured_at=AS_OF,
        manager_id=123456,
        picks_event=1,
        planning_gw=1,
        bank_tenths=10,
        initial_free_transfers=0,
        free_transfers_source="replayed_public_history",
        existing_hit_points=4,
        owned_players=tuple(
            OwnedPlayerValueRecord(
                code=member.code,
                purchase_price_tenths=member.now_cost,
                selling_price_tenths=member.now_cost,
            )
            for member in base.initial_squad.members
        ),
    )
    return build_optimizer_plan_artifact(
        provenance=manager_provenance,
        search_policy=policy,
        solver=solver,
        rules=rules,
        initial_squad=initial,
        plan=plan,
        assumptions=base.assumptions,
        manager_context=manager,
    )


def test_schema_v1_identity_and_canonical_bytes_remain_pinned() -> None:
    artifact = _build()
    assert artifact.schema_version == 1
    assert artifact.run_id == "799c094f5bfab76e74d7e86e1d89f636e992a2037d0b99a5d7ef502bd3919876"
    assert (
        artifact.decision_sha256
        == "6b9f33efd034def324f4147968291abde7404e3f76eca571256d0e05556568c5"
    )
    import hashlib

    assert (
        hashlib.sha256(optimizer_artifact_bytes(artifact)).hexdigest()
        == "1a7655f77f043d3c77455b10211904d535913a88591da83f862e96e6238ba6a6"
    )


def test_manager_v2_validates_first_week_hit_cash_and_over_budget_market_value() -> None:
    artifact = _manager_build()
    first, second = artifact.plan.weeks
    assert artifact.schema_version == 2
    assert artifact.search_policy.plan_mode == "manager"
    assert artifact.initial_squad.cost_tenths > artifact.rules.budget_tenths
    assert len(first.transfers_in) == len(first.transfers_out) == 1
    assert (first.free_transfers_before, first.free_transfers_after, first.hit_points) == (0, 0, 4)
    assert (first.bank_before_tenths, first.bank_after_tenths) == (10, 0)
    assert (second.free_transfers_before, second.free_transfers_after) == (1, 1)
    assert artifact.manager_context is not None
    assert artifact.manager_context.existing_hit_points == 4
    # The already-incurred hit is recorded as sunk; only the newly planned hit enters the total.
    assert artifact.plan.hit_points == 4


def test_manager_v2_canonical_round_trip(tmp_path: Path) -> None:
    artifact = _manager_build()
    path = tmp_path / "manager-plan.json"
    write_optimizer_artifact_atomic(path, artifact)
    assert read_optimizer_artifact(path) == artifact
    assert b'"schema_version": 2' in path.read_bytes()
    assert b'"manager_context"' in path.read_bytes()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda payload: payload["plan"]["weeks"][0].__setitem__("hit_points", 0),
            "hit cost",
        ),
        (
            lambda payload: payload["plan"]["weeks"][0].__setitem__("bank_after_tenths", 1),
            "bank-after",
        ),
        (
            lambda payload: payload["manager_context"]["owned_players"][-1].__setitem__(
                "selling_price_tenths", 41
            ),
            "selling price",
        ),
        (
            lambda payload: payload["search_policy"].__setitem__("initial_free_transfers", 1),
            "initial free transfers",
        ),
    ],
)
def test_manager_v2_rejects_financial_or_transfer_tampering(
    mutate: Callable[[dict[str, object]], None],
    message: str,
) -> None:
    payload = _manager_build().model_dump(mode="json", by_alias=True)
    mutate(payload)
    with pytest.raises(ValidationError, match=message):
        OptimizerPlanArtifact.model_validate(payload)


def test_manager_v2_allows_owned_exclude_only_until_first_transfer() -> None:
    artifact = _manager_build()
    excluded = artifact.search_policy.excluded_codes[0]
    assert excluded in {member.code for member in artifact.initial_squad.members}
    assert all(
        excluded not in {member.code for member in week.squad_after_transfers}
        for week in artifact.plan.weeks
    )

    owned_still_present = artifact.initial_squad.members[0].code
    bad_owned = artifact.model_dump(mode="json", by_alias=True)
    bad_owned["search_policy"]["excluded_codes"] = [owned_still_present]
    with pytest.raises(ValidationError, match="contains an excluded player"):
        OptimizerPlanArtifact.model_validate(bad_owned)

    incoming = artifact.plan.weeks[0].transfers_in[0].code
    bad_non_owned = artifact.model_dump(mode="json", by_alias=True)
    bad_non_owned["search_policy"]["excluded_codes"] = [incoming]
    with pytest.raises(ValidationError, match="contains an excluded player"):
        OptimizerPlanArtifact.model_validate(bad_non_owned)


def test_manager_context_and_mode_bind_decision_and_run_identity() -> None:
    artifact = _manager_build()
    assert artifact.manager_context is not None
    changed_context = artifact.manager_context.model_copy(update={"manager_id": 654321})
    changed_decision = derive_optimizer_decision_sha256(
        artifact.rules,
        artifact.initial_squad,
        artifact.plan,
        artifact.assumptions,
        manager_context=changed_context,
    )
    assert changed_decision != artifact.decision_sha256
    assert (
        derive_optimizer_run_id(
            artifact.provenance,
            artifact.search_policy,
            artifact.solver,
            changed_decision,
            manager_context=changed_context,
        )
        != artifact.run_id
    )


def test_artifact_carries_complete_schema_and_provenance() -> None:
    artifact = _build()
    assert artifact.artifact_schema == "fpl.optimizer-plan"
    assert artifact.schema_version == 1
    assert artifact.status == "development_only_not_a_validated_production_recommendation"
    assert len(artifact.run_id) == 64
    assert len(artifact.decision_sha256) == 64

    provenance = artifact.provenance
    assert provenance.optimizer_commit_sha == "optcommit"
    assert provenance.optimizer_worktree_clean is True
    assert provenance.forecast.sha256 == HASH
    assert provenance.forecast.commit_sha == "forecastcommit"
    assert provenance.forecast.forecast_schema == "fpl.prospective-points"
    assert provenance.forecast.season == "2026-27"
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
    assert policy.excluded_codes == ()
    assert policy.plan_origin == "platform"

    assert artifact.solver.name == "PULP_CBC_CMD"
    assert artifact.solver.options == ("randomSeed 0",)
    assert artifact.solver.seed == 0
    assert artifact.solver.status == "Optimal"
    assert artifact.solver.package_version == "3.3.2"
    assert artifact.solver.binary_version == "2.10.3"

    assert artifact.rules.squad_size == 15
    assert artifact.rules.contract_version == provenance.squad_rules.contract_version
    assert artifact.rules.lineup_starters == 11
    assert tuple(rule.position for rule in artifact.rules.positions) == (
        "GK",
        "DEF",
        "MID",
        "FWD",
    )

    assert len(artifact.initial_squad.members) == 15
    assert [m.code for m in artifact.initial_squad.members] == sorted(
        m.code for m in artifact.initial_squad.members
    )
    assert len(artifact.plan.weeks) == 2
    assert artifact.plan.weeks[0].captain.code == 30  # the top forward
    assert len(artifact.plan.weeks[0].starting_xi) == 11
    assert len(artifact.plan.weeks[0].squad_after_transfers) == 15

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


def test_legacy_artifact_without_plan_origin_reads_as_unknown(tmp_path: Path) -> None:
    artifact = _build()
    legacy_policy = artifact.search_policy.model_copy(update={"plan_origin": None})
    legacy_run_id = derive_optimizer_run_id(
        artifact.provenance, legacy_policy, artifact.solver, artifact.decision_sha256
    )
    assert legacy_run_id == artifact.run_id
    legacy = artifact.model_copy(update={"search_policy": legacy_policy, "run_id": legacy_run_id})
    payload = legacy.model_dump(mode="json")
    payload["search_policy"].pop("plan_origin")
    path = tmp_path / "legacy-plan.json"
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    parsed = read_optimizer_artifact(path)
    assert parsed.run_id == artifact.run_id
    assert parsed.search_policy.plan_origin is None


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
            season="2026-27",
            gw_from=1,
            gw_to=5,
            commit_sha="",
        )
    with pytest.raises(ValidationError, match="sha256"):
        SquadRulesProvenance(path="r", contract_version="1.0", sha256="not-a-hash")
    with pytest.raises(ValidationError, match="forecast path"):
        _provenance(forecast_path="")
    with pytest.raises(ValidationError, match="squad-rules path"):
        _provenance(rules_path="")


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


def test_artifact_independently_rejects_lock_and_exclusion_policy_violations() -> None:
    artifact = _build()
    selected = artifact.initial_squad.members[0].code
    missing = max(member.code for member in artifact.initial_squad.members) + 10_000

    excluded = artifact.model_dump(mode="json", by_alias=True)
    excluded["search_policy"]["excluded_codes"] = [selected]
    with pytest.raises(ValidationError, match="contains an excluded player"):
        OptimizerPlanArtifact.model_validate(excluded)

    locked = artifact.model_dump(mode="json", by_alias=True)
    locked["search_policy"]["locked_codes"] = [missing]
    with pytest.raises(ValidationError, match="omits a locked player"):
        OptimizerPlanArtifact.model_validate(locked)


def test_valid_alternative_decision_is_rejected_when_decision_hash_is_stale() -> None:
    artifact = _build()
    tampered = artifact.model_dump(mode="json", by_alias=True)
    week = tampered["plan"]["weeks"][0]
    week["captain"], week["vice_captain"] = week["vice_captain"], week["captain"]
    with pytest.raises(ValidationError, match="decision_sha256"):
        OptimizerPlanArtifact.model_validate(tampered)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("captain", {"code": 999999, "web_name": None}, "outside"),
        ("starting_xi", (), "wrong number"),
    ],
)
def test_illegal_weekly_decision_is_rejected(
    field: str,
    value: object,
    message: str,
) -> None:
    artifact = _build()
    tampered = artifact.model_dump(mode="json", by_alias=True)
    tampered["plan"]["weeks"][0][field] = value
    with pytest.raises(ValidationError, match=message):
        OptimizerPlanArtifact.model_validate(tampered)


def test_plan_aggregate_must_reconcile_to_weekly_records() -> None:
    artifact = _build()
    tampered = artifact.model_dump(mode="json", by_alias=True)
    tampered["plan"]["expected_points_before_hits"] += 1.0
    with pytest.raises(ValidationError, match="reconcile"):
        OptimizerPlanArtifact.model_validate(tampered)


def test_embedded_rules_must_match_provenance_contract() -> None:
    artifact = _build()
    tampered = artifact.model_dump(mode="json", by_alias=True)
    tampered["rules"]["contract_version"] = "different"
    with pytest.raises(ValidationError, match="contract versions disagree"):
        OptimizerPlanArtifact.model_validate(tampered)


def test_reader_rejects_over_budget_and_wrong_position_squads() -> None:
    artifact = _build()
    over_budget = artifact.model_dump(mode="json", by_alias=True)
    over_budget["initial_squad"]["members"][0]["now_cost"] += 1000
    over_budget["initial_squad"]["cost_tenths"] += 1000
    with pytest.raises(ValidationError, match="budget"):
        OptimizerPlanArtifact.model_validate(over_budget)

    wrong_positions = artifact.model_dump(mode="json", by_alias=True)
    wrong_positions["initial_squad"]["members"][0]["position"] = "DEF"
    with pytest.raises(ValidationError, match="position composition"):
        OptimizerPlanArtifact.model_validate(wrong_positions)


def test_reader_rejects_club_cap_and_illegal_formation() -> None:
    artifact = _build()
    club_cap = artifact.model_dump(mode="json", by_alias=True)
    for member in club_cap["initial_squad"]["members"][:4]:
        member["team_id"] = 999
    with pytest.raises(ValidationError, match="club cap"):
        OptimizerPlanArtifact.model_validate(club_cap)

    formation = artifact.model_dump(mode="json", by_alias=True)
    week = formation["plan"]["weeks"][0]
    members = {member["code"]: member for member in week["squad_after_transfers"]}
    defender = next(ref for ref in week["starting_xi"] if members[ref["code"]]["position"] == "DEF")
    week["starting_xi"].remove(defender)
    week["starting_xi"].append(week["bench_goalkeeper"])
    week["starting_xi"].sort(key=lambda ref: ref["code"])
    with pytest.raises(ValidationError, match="illegal GK starter count"):
        OptimizerPlanArtifact.model_validate(formation)


def test_reader_rejects_invalid_transfer_delta_and_free_transfer_state() -> None:
    artifact = _build()
    invalid_delta = artifact.model_dump(mode="json", by_alias=True)
    week = invalid_delta["plan"]["weeks"][1]
    members = week["squad_after_transfers"]
    week["transfers_out"] = [{"code": members[0]["code"], "web_name": members[0]["web_name"]}]
    week["transfers_in"] = [{"code": members[1]["code"], "web_name": members[1]["web_name"]}]
    with pytest.raises(ValidationError, match="existing squad member"):
        OptimizerPlanArtifact.model_validate(invalid_delta)

    invalid_free_state = artifact.model_dump(mode="json", by_alias=True)
    invalid_free_state["plan"]["weeks"][1]["free_transfers_before"] += 1
    with pytest.raises(ValidationError, match="free-transfer state"):
        OptimizerPlanArtifact.model_validate(invalid_free_state)


def test_non_finite_floats_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _policy(risk_lambda=float("nan"))
    with pytest.raises(ValidationError):
        _policy(risk_lambda=float("inf"))


def test_build_matches_self_validation() -> None:
    artifact = _build()
    assert artifact.run_id == derive_optimizer_run_id(
        artifact.provenance,
        artifact.search_policy,
        artifact.solver,
        artifact.decision_sha256,
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

    def fail_link(_source: str | Path, _target: str | Path) -> None:
        raise OSError("simulated promotion failure")

    monkeypatch.setattr(os, "link", fail_link)
    with pytest.raises(OSError, match="simulated promotion"):
        write_optimizer_artifact_atomic(path, _build())
    assert not path.exists()
    assert list(tmp_path.glob(".plan.json.*.tmp")) == []


def test_concurrent_writers_have_exactly_one_no_clobber_winner(tmp_path: Path) -> None:
    path = tmp_path / "plan.json"
    artifact = _build()

    def write() -> str:
        try:
            return write_optimizer_artifact_atomic(path, artifact)
        except OptimizerArtifactExistsError:
            return "exists"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(lambda _index: write(), range(2)))
    assert outcomes.count("exists") == 1
    assert sum(outcome != "exists" for outcome in outcomes) == 1
    assert read_optimizer_artifact(path) == artifact


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


def _manager_forecast(horizon: int = 2) -> ProspectivePointsArtifact:
    """A GW2+ forecast whose current 15 can be worth more than a fresh 100.0 budget."""
    base = _artifact(horizon)
    rows = tuple(
        row.model_copy(
            update={
                "gw": row.gw + 1,
                "now_cost": 70,
                "kickoff_times": tuple(
                    kickoff + timedelta(days=1) for kickoff in row.kickoff_times
                ),
            }
        )
        for row in base.rows
    )
    return ProspectivePointsArtifact(
        manifest=base.manifest.model_copy(
            update={
                "gw_from": 2,
                "gw_to": horizon + 1,
                "live_inputs": base.manifest.live_inputs.model_copy(
                    update={"selectable_player_registry_sha256": HASH}
                ),
            }
        ),
        rows=rows,
    )


def _manager_capture(artifact: ProspectivePointsArtifact) -> ManagerTeamCapture:
    """Build and revalidate a complete canonical capture matching the manager forecast."""
    first_rows = {row.code: row for row in artifact.rows if row.gw == artifact.manifest.gw_from}
    # Keep the weak FWD 33 and omit the strong FWD 30. The manager path should recommend the
    # one affordable same-position replacement immediately in GW2.
    current_codes = tuple(sorted(code for code in first_rows if code != 30))
    squad = tuple(
        ManagerSquadPlayer(
            element=code,
            code=code,
            web_name=first_rows[code].web_name or f"P{code}",
            position=first_rows[code].position,
            team_id=first_rows[code].team_id,
            now_cost=70,
            purchase_price=50,
            selling_price=60,
        )
        for code in current_codes
    )
    provenance = ManagerCaptureProvenance(
        current_bootstrap_sha256=HASH,
        selectable_player_registry_sha256=HASH,
        entry_sha256=HASH_B,
        latest_picks_sha256=HASH_C,
        start_picks_sha256=HASH,
        transfers_sha256=HASH_B,
        history_sha256=HASH_C,
        deadline_snapshot_capture_id="synthetic-deadline",
        deadline_snapshot_captured_at=AS_OF - timedelta(hours=1),
        deadline_snapshot_relative_path="snapshots/daily/synthetic",
        deadline_snapshot_manifest_sha256=HASH,
        deadline_snapshot_bootstrap_archive_sha256=HASH_B,
        deadline_snapshot_bootstrap_payload_sha256=HASH_C,
    )
    pending = ManagerTeamCapture(
        capture_id="pending",
        captured_at=AS_OF + timedelta(days=2),
        season=artifact.manifest.season,
        manager_id=42,
        manager_name="Synthetic Manager",
        player_first_name="Fixture",
        player_last_name="Owner",
        started_event=1,
        picks_event=1,
        planning_event=2,
        squad=squad,
        bank_tenths=10,
        squad_selling_value_tenths=900,
        available_budget_tenths=910,
        free_transfers_available=1,
        existing_hit_points=4,
        historical_hit_points=0,
        post_picks_transfer_count=2,
        chips=(),
        transfer_rules=ManagerTransferReplayRules(),
        completeness=ManagerCaptureCompleteness(
            latest_free_hit_picks_comparable_to_permanent_squad=True
        ),
        provenance=provenance,
    )
    payload = pending.model_dump(mode="json", by_alias=True)
    payload["capture_id"] = derive_manager_capture_id(pending)
    capture = ManagerTeamCapture.model_validate(payload)
    # This also re-derives the identity and proves the fixture is serializable at the real boundary.
    assert manager_capture_bytes(capture)
    return capture


def _write_manager_inputs(tmp_path: Path) -> tuple[Path, Path, ManagerTeamCapture]:
    artifact = _manager_forecast()
    forecast = tmp_path / "manager-forecast.jsonl"
    write_artifact_atomic(forecast, artifact)
    capture = _manager_capture(artifact)
    capture_path = tmp_path / "manager-capture.json"
    capture_path.write_bytes(manager_capture_bytes(capture))
    return forecast, capture_path, capture


def test_manager_producer_imports_current_fifteen_and_plans_first_gw_finances(
    tmp_path: Path,
) -> None:
    forecast = _manager_forecast()
    capture = _manager_capture(forecast)
    rules = load_squad_rules()

    initial, index, plan, names = _solve(
        forecast,
        rules,
        0.0,
        manager_capture=capture,
        free_transfers_override=0,
    )

    assert {member.code for member in initial.members} == {player.code for player in capture.squad}
    assert initial.squad_cost_tenths == 1050 > rules.squad.budget_tenths
    first, second = plan.weeks
    assert first.gw == forecast.manifest.gw_from
    assert (first.transfers_out, first.transfers_in) == ((33,), (30,))
    assert (first.free_transfers_before, first.free_transfers_after, first.hit_points) == (0, 0, 4)
    assert (first.bank_before_tenths, first.bank_after_tenths) == (10, 0)
    assert (
        second.free_transfers_before,
        second.free_transfers_after,
        second.hit_points,
    ) == (1, 1, 0)
    assert (second.bank_before_tenths, second.bank_after_tenths) == (0, 0)
    assert plan.hit_points == 4

    provenance = OptimizerProvenance(
        optimizer_commit_sha="producer-test",
        forecast=build_forecast_provenance(forecast, "manager-forecast.jsonl", HASH),
        squad_rules=SquadRulesProvenance(
            path="squad_2026_27.yaml",
            contract_version=rules.contract_version,
            sha256=HASH_B,
        ),
    )
    context = optimize_squad._manager_plan_context(capture, free_transfers_override=0)
    artifact = assemble_optimizer_artifact(
        initial=initial,
        plan=plan,
        names=names,
        index=index,
        provenance=provenance,
        rules=rules,
        risk_lambda=0.0,
        plan_origin="user_custom",
        manager_context=context,
        solver_package_version="3.3.2",
        solver_binary_version="2.10.3",
    )
    assert artifact.schema_version == 2
    assert artifact.manager_context is not None
    assert artifact.manager_context.capture_id == capture.capture_id
    assert artifact.manager_context.capture_sha256 == manager_capture_sha256(capture)
    assert artifact.manager_context.bank_tenths == 10
    assert artifact.manager_context.initial_free_transfers == 0
    assert artifact.manager_context.free_transfers_override == 0
    assert artifact.manager_context.existing_hit_points == 4
    first_artifact_week = artifact.plan.weeks[0]
    assert (
        first_artifact_week.bank_before_tenths,
        first_artifact_week.bank_after_tenths,
    ) == (10, 0)

    output = tmp_path / "assembled-manager-plan.json"
    write_optimizer_artifact_atomic(output, artifact)
    assert read_optimizer_artifact(output) == artifact


def test_manager_solve_requires_exact_registry_binding_and_bounded_repairs() -> None:
    forecast = _manager_forecast()
    capture = _manager_capture(forecast)
    rules = load_squad_rules()

    mismatched = capture.model_copy(
        update={
            "provenance": capture.provenance.model_copy(
                update={"selectable_player_registry_sha256": HASH_B}
            )
        }
    )
    with pytest.raises(OptimizationError, match="registries disagree"):
        _solve(forecast, rules, 0.0, manager_capture=mismatched)

    unbound = ProspectivePointsArtifact(
        manifest=forecast.manifest.model_copy(
            update={
                "live_inputs": forecast.manifest.live_inputs.model_copy(
                    update={"selectable_player_registry_sha256": None}
                )
            }
        ),
        rows=forecast.rows,
        player_fixture_rows=forecast.player_fixture_rows,
        team_fixture_rows=forecast.team_fixture_rows,
    )
    with pytest.raises(OptimizationError, match="registry binding"):
        _solve(unbound, rules, 0.0, manager_capture=capture)

    forced = tuple(player.code for player in capture.squad[:3])
    with pytest.raises(OptimizationError, match="force 3 first-week transfers"):
        _solve(
            forecast,
            rules,
            0.0,
            excluded_codes=forced,
            manager_capture=capture,
        )


def _mock_clean_output(
    monkeypatch: pytest.MonkeyPatch,
    *,
    head: str = "cafebabe" * 5,
) -> None:
    monkeypatch.setattr(optimize_squad, "_git_worktree_clean", lambda _repo: True)
    monkeypatch.setattr(optimize_squad, "_git_head", lambda _repo: head)
    monkeypatch.setattr(optimize_squad, "_pulp_package_version", lambda: "3.3.2")
    monkeypatch.setattr(optimize_squad, "_cbc_binary_version", lambda: "2.10.3")


def test_manager_cli_binds_exact_capture_bytes_and_writes_schema_v2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    forecast, capture_path, capture = _write_manager_inputs(tmp_path)
    output = tmp_path / "manager-plan.json"
    _mock_clean_output(monkeypatch)

    assert (
        main(
            [
                str(forecast),
                "--manager-capture",
                str(capture_path),
                "--free-transfers-override",
                "0",
                "--plan-origin",
                "user_custom",
                "--output",
                str(output),
            ]
        )
        == 0
    )

    artifact = read_optimizer_artifact(output)
    assert artifact.schema_version == 2
    assert artifact.manager_context is not None
    assert artifact.manager_context.capture_id == capture.capture_id
    assert artifact.manager_context.capture_sha256 == manager_capture_sha256(capture)
    assert artifact.manager_context.free_transfers_override == 0
    assert artifact.plan.weeks[0].transfers_out[0].code == 33
    assert artifact.plan.weeks[0].transfers_in[0].code == 30
    assert (
        artifact.plan.weeks[0].bank_before_tenths,
        artifact.plan.weeks[0].bank_after_tenths,
        artifact.plan.weeks[0].hit_points,
    ) == (10, 0, 4)
    report = json.loads(capsys.readouterr().out)
    assert report["manager"]["capture_sha256"] == manager_capture_sha256(capture)
    assert report["manager"]["free_transfers_available"] == 0
    assert report["manager"]["free_transfers_override"] == 0
    assert report["manager"]["existing_hit_points"] == 4


def test_manager_cli_rejects_capture_byte_mutation_during_solve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    forecast, capture_path, _capture = _write_manager_inputs(tmp_path)
    output = tmp_path / "manager-plan.json"
    _mock_clean_output(monkeypatch)
    real_solve = optimize_squad._solve

    def drifting_solve(*args: object, **kwargs: object) -> object:
        result = real_solve(*args, **kwargs)  # type: ignore[arg-type]
        capture_path.write_bytes(capture_path.read_bytes() + b"\n")
        return result

    monkeypatch.setattr(optimize_squad, "_solve", drifting_solve)
    assert (
        main(
            [
                str(forecast),
                "--manager-capture",
                str(capture_path),
                "--plan-origin",
                "user_custom",
                "--output",
                str(output),
            ]
        )
        == 1
    )
    assert capsys.readouterr().out == ""
    assert not output.exists()
    assert list(tmp_path.glob(".manager-plan.json.*.tmp")) == []


def test_job_output_refuses_dirty_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    forecast = _write_forecast(tmp_path)
    out = tmp_path / "plan.json"
    monkeypatch.setattr(optimize_squad, "_git_worktree_clean", lambda _repo: False)
    monkeypatch.setattr(optimize_squad, "_git_head", lambda _repo: "deadbeef")
    assert main([str(forecast), "--output", str(out)]) == 1
    assert not out.exists()
    assert capsys.readouterr().out == ""


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
    _mock_clean_output(monkeypatch)
    assert main([str(forecast), "--output", str(out)]) == 0
    plan = read_optimizer_artifact(out)
    assert plan.provenance.optimizer_commit_sha == "cafebabe" * 5
    assert plan.provenance.forecast.commit_sha == "forecastcommit"
    assert plan.provenance.squad_rules.contract_version == "1.0"
    assert len(plan.initial_squad.members) == 15


def test_job_records_min_bench_appearance_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate is provenance: recorded, assumption-documented, and identity-binding.

    Every synthetic outfielder here has appearance bound 1.0, so a 0.25 gate never binds:
    the decision content is unchanged and only the policy-bound run identity moves.
    """
    forecast = _write_forecast(tmp_path)
    default_out = tmp_path / "plan_default.json"
    gated_out = tmp_path / "plan_gated.json"
    _mock_clean_output(monkeypatch)
    assert main([str(forecast), "--output", str(default_out)]) == 0
    assert main([str(forecast), "--min-bench-appearance", "0.25", "--output", str(gated_out)]) == 0
    default_plan = read_optimizer_artifact(default_out)
    gated_plan = read_optimizer_artifact(gated_out)
    assert default_plan.search_policy.min_bench_appearance == 0.0
    assert gated_plan.search_policy.min_bench_appearance == 0.25
    # The gate never binds on this population (every outfielder's bound is 1.0), so the
    # selected 15 and every weekly XI are identical; the decision hash still moves because
    # the decision records its own assumptions, which document the active gate.
    assert gated_plan.initial_squad == default_plan.initial_squad
    assert gated_plan.plan.weeks == default_plan.plan.weeks
    assert gated_plan.decision_sha256 != default_plan.decision_sha256
    assert gated_plan.run_id != default_plan.run_id
    assert any("min_bench_appearance=0.25" in line for line in gated_plan.assumptions)
    assert not any("min_bench_appearance" in line for line in default_plan.assumptions)


def test_job_records_locked_players_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Locked must-keep players are provenance: policy-recorded and assumption-documented."""
    forecast = _write_forecast(tmp_path)
    out = tmp_path / "plan_locked.json"
    _mock_clean_output(monkeypatch)
    assert main([str(forecast), "--lock", "30", "--output", str(out)]) == 0
    plan = read_optimizer_artifact(out)
    assert plan.search_policy.locked_codes == (30,)
    assert any("locked players: P30 (30)" in line for line in plan.assumptions)


def test_job_records_exclusions_and_user_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    forecast = _write_forecast(tmp_path)
    out = tmp_path / "plan_excluded.json"
    _mock_clean_output(monkeypatch)
    assert (
        main(
            [
                str(forecast),
                "--exclude",
                "33",
                "--plan-origin",
                "user_custom",
                "--output",
                str(out),
            ]
        )
        == 0
    )
    plan = read_optimizer_artifact(out)
    assert plan.search_policy.excluded_codes == (33,)
    assert plan.search_policy.plan_origin == "user_custom"
    assert all(
        33 not in {member.code for member in week.squad_after_transfers} for week in plan.plan.weeks
    )
    assert any("excluded players: P33 (33)" in line for line in plan.assumptions)


def test_job_rejects_more_than_five_locks_and_unknown_codes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    forecast = _write_forecast(tmp_path)
    _mock_clean_output(monkeypatch)
    many = [arg for code in (1, 2, 3, 10, 20, 30) for arg in ("--lock", str(code))]
    assert main([str(forecast), *many, "--output", str(tmp_path / "a.json")]) == 1
    assert main([str(forecast), "--lock", "9999", "--output", str(tmp_path / "b.json")]) == 1
    assert not (tmp_path / "a.json").exists()
    assert not (tmp_path / "b.json").exists()
    assert capsys.readouterr().out == ""


def test_job_rejects_invalid_exclusions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    forecast = _write_forecast(tmp_path)
    _mock_clean_output(monkeypatch)
    many = [arg for code in range(100, 116) for arg in ("--exclude", str(code))]
    assert main([str(forecast), *many, "--output", str(tmp_path / "a.json")]) == 1
    assert main([str(forecast), "--exclude", "9999", "--output", str(tmp_path / "b.json")]) == 1
    assert (
        main(
            [
                str(forecast),
                "--lock",
                "30",
                "--exclude",
                "30",
                "--output",
                str(tmp_path / "c.json"),
            ]
        )
        == 1
    )
    assert capsys.readouterr().out == ""


def test_job_output_is_no_clobber(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    forecast = _write_forecast(tmp_path)
    out = tmp_path / "plan.json"
    _mock_clean_output(monkeypatch, head="abad1dea" * 5)
    assert main([str(forecast), "--output", str(out)]) == 0
    original = out.read_bytes()
    assert main([str(forecast), "--output", str(out)]) == 1
    assert out.read_bytes() == original


def test_job_refuses_incomplete_solver_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    forecast = _write_forecast(tmp_path)
    out = tmp_path / "plan.json"
    _mock_clean_output(monkeypatch)
    monkeypatch.setattr(optimize_squad, "_cbc_binary_version", lambda: None)
    assert main([str(forecast), "--output", str(out)]) == 1
    assert not out.exists()


def test_pulp_version_falls_back_to_imported_module_when_metadata_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pulp

    def missing(_name: str) -> str:
        raise optimize_squad.importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(optimize_squad.importlib.metadata, "version", missing)
    monkeypatch.setattr(pulp, "__version__", "3.3.2")
    assert optimize_squad._pulp_package_version() == "3.3.2"


def test_pulp_version_refuses_conflicting_metadata_and_module_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pulp

    monkeypatch.setattr(optimize_squad.importlib.metadata, "version", lambda _name: "3.3.2")
    monkeypatch.setattr(pulp, "__version__", "9.9.9")
    assert optimize_squad._pulp_package_version() is None


def test_cbc_version_retries_and_accepts_only_an_explicit_version_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pulp

    class Solver:
        path = "cbc.exe"

    outcomes = iter(
        (
            OSError("transient launch failure"),
            optimize_squad.subprocess.CompletedProcess(
                args=["cbc.exe", "-version"],
                returncode=0,
                stdout="Welcome to CBC\nVersion: 2.10.3\n",
                stderr="",
            ),
        )
    )
    calls: list[dict[str, object]] = []

    def run(*_args: object, **_kwargs: object) -> object:
        calls.append(_kwargs)
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(pulp, "PULP_CBC_CMD", lambda **_kwargs: Solver())
    monkeypatch.setattr(optimize_squad.subprocess, "run", run)
    assert optimize_squad._cbc_binary_version() == "2.10.3"
    assert calls and all(call["stdin"] is optimize_squad.subprocess.DEVNULL for call in calls)


def test_solver_versions_never_returns_a_partial_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(optimize_squad, "_pulp_package_version", lambda: "3.3.2")
    monkeypatch.setattr(optimize_squad, "_cbc_binary_version", lambda: None)
    assert optimize_squad._solver_versions() is None


def test_job_removes_output_when_forecast_drifts_during_solve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    forecast = _write_forecast(tmp_path)
    out = tmp_path / "plan.json"
    _mock_clean_output(monkeypatch)
    real_solve = optimize_squad._solve

    def drifting_solve(*args: object, **kwargs: object) -> object:
        result = real_solve(*args, **kwargs)  # type: ignore[arg-type]
        forecast.write_bytes(forecast.read_bytes() + b"\n")
        return result

    monkeypatch.setattr(optimize_squad, "_solve", drifting_solve)
    assert main([str(forecast), "--output", str(out)]) == 1
    assert not out.exists()
    assert list(tmp_path.glob(".plan.json.*.tmp")) == []


def test_job_removes_output_when_rules_drift_during_solve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    forecast = _write_forecast(tmp_path)
    rules_path = tmp_path / "squad.yaml"
    rules_path.write_bytes((Path("config") / "squad_2026_27.yaml").read_bytes())
    out = tmp_path / "plan.json"
    _mock_clean_output(monkeypatch)
    real_solve = optimize_squad._solve

    def drifting_solve(*args: object, **kwargs: object) -> object:
        result = real_solve(*args, **kwargs)  # type: ignore[arg-type]
        rules_path.write_bytes(rules_path.read_bytes() + b"\n")
        return result

    monkeypatch.setattr(optimize_squad, "_solve", drifting_solve)
    assert main([str(forecast), "--rules", str(rules_path), "--output", str(out)]) == 1
    assert not out.exists()


def test_job_refuses_git_head_drift_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    forecast = _write_forecast(tmp_path)
    out = tmp_path / "plan.json"
    monkeypatch.setattr(optimize_squad, "_git_worktree_clean", lambda _repo: True)
    heads = iter(("a" * 40, "a" * 40, "b" * 40))
    monkeypatch.setattr(optimize_squad, "_git_head", lambda _repo: next(heads, "b" * 40))
    monkeypatch.setattr(optimize_squad, "_pulp_package_version", lambda: "3.3.2")
    monkeypatch.setattr(optimize_squad, "_cbc_binary_version", lambda: "2.10.3")
    assert main([str(forecast), "--output", str(out)]) == 1
    assert not out.exists()


def test_job_removes_published_output_on_postflight_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    forecast = _write_forecast(tmp_path)
    out = tmp_path / "plan.json"
    _mock_clean_output(monkeypatch)
    real_write = optimize_squad.write_optimizer_artifact_atomic

    def publish_then_drift(
        path: Path,
        artifact: OptimizerPlanArtifact,
        *,
        pre_publish: Callable[[], None] | None = None,
    ) -> str:
        digest = real_write(path, artifact, pre_publish=pre_publish)
        forecast.write_bytes(forecast.read_bytes() + b"\n")
        return digest

    monkeypatch.setattr(optimize_squad, "write_optimizer_artifact_atomic", publish_then_drift)
    assert main([str(forecast), "--output", str(out)]) == 1
    assert not out.exists()
    assert list(tmp_path.glob(".plan.json.*.tmp")) == []


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
