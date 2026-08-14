"""Offline contract tests for the P0.3 default-versus-diagnostic decision comparison.

These pin the derivation (ledger id, squad roles, flags, cross-evaluated captains), the fail-closed
parity rules that stop a meaningless comparison, the plan-versus-forecast reconciliation, the
deterministic ``comparison_id``, immutable no-clobber and atomic behaviour, reader-side tamper
rejection, the rendered report's required P0.3 content, and the thin CLI. No network, no database,
and no live forecast pipeline: both forecasts are small synthetic artifacts optimised for real.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from fpl.artifacts.decision_comparison import (
    DECISION_COMPARISON_CAVEATS,
    FORECAST_FLAG_FIELDS,
    DecisionComparisonArtifact,
    DecisionComparisonError,
    DecisionComparisonExistsError,
    build_decision_comparison,
    decision_comparison_bytes,
    derive_comparison_id,
    read_decision_comparison,
    render_decision_comparison,
    write_decision_comparison_atomic,
)
from fpl.artifacts.optimizer_plan import (
    ForecastInputProvenance,
    OptimizerPlanArtifact,
    OptimizerProvenance,
    SquadRulesProvenance,
    TransferPlanRecord,
    TransferWeekRecord,
    build_optimizer_plan_artifact,
)
from fpl.artifacts.prospective_points import (
    ContractIdentity,
    ForecastArtifactManifest,
    ForecastArtifactRow,
    LiveInputProvenance,
    ProspectivePointsArtifact,
    artifact_bytes,
    write_artifact_atomic,
)
from fpl.jobs.compare_decisions import main
from fpl.jobs.optimize_squad import (
    _initial_squad_record,
    _plan_record_model,
    _rules_snapshot,
    _search_policy,
    _solve,
)
from fpl.optimize.rules import load_squad_rules
from fpl.storage.ledger import derive_run_id

HASH = "a" * 64
HASH_B = "b" * 64
AS_OF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
HORIZON = 2


# --------------------------------------------------------------------------------------
# Two synthetic forecasts over one 18-player pool. Only the point values differ, so the
# optimizer genuinely selects different squads, lineups and captains for each path.
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Player:
    code: int
    position: str
    cost: int


def _pool() -> tuple[_Player, ...]:
    counts = {"GK": 2, "DEF": 6, "MID": 6, "FWD": 4}
    starts = {"GK": 1, "DEF": 10, "MID": 20, "FWD": 30}
    return tuple(
        _Player(code=starts[position] + offset, position=position, cost=40)
        for position, total in counts.items()
        for offset in range(total)
    )


def _distribution(mean: float) -> tuple[float, ...]:
    lower = math.floor(mean)
    fraction = mean - lower
    if fraction == 0.0:
        return (*((0.0,) * lower), 1.0)
    return (*((0.0,) * lower), 1.0 - fraction, fraction)


def _forecast(
    points: dict[int, float],
    *,
    modes: dict[str, str],
    flagged: frozenset[int] = frozenset(),
    horizon: int = HORIZON,
    **manifest_overrides: Any,
) -> ProspectivePointsArtifact:
    players = _pool()
    season = str(manifest_overrides.get("season", "2026-27"))
    rows: list[ForecastArtifactRow] = []
    for gw in range(1, horizon + 1):
        for player in sorted(players, key=lambda item: item.code):
            expected = points[player.code]
            rows.append(
                ForecastArtifactRow(
                    season=season,
                    gw=gw,
                    code=player.code,
                    web_name=f"P{player.code}",
                    position=player.position,
                    team_id=player.code,
                    team_code=player.code,
                    now_cost=player.cost,
                    selected_by_percent=1.0 + (player.code % 7),
                    availability_status="a",
                    chance_of_playing=None,
                    availability_multiplier=1.0,
                    fixture_ids=(gw * 1000 + player.code,),
                    kickoff_times=(datetime(2026, 8, 21 + gw, tzinfo=UTC),),
                    expected_points=expected,
                    availability_adjusted_expected_points=expected,
                    expected_bonus=0.0,
                    distribution=_distribution(expected),
                    # A flagged player carries EVERY flag, so slot flag ordering is exercised
                    # rather than trivially satisfied by a single-element list.
                    cold_start_player=player.code in flagged,
                    stage_a_league_average_team=player.code in flagged,
                    attacking_signal_cold_start=player.code in flagged,
                    assist_signal_cold_start=player.code in flagged,
                    transferred_no_rescale=player.code in flagged,
                )
            )
    base: dict[str, Any] = {
        "as_of": AS_OF,
        "season": "2026-27",
        "gw_from": 1,
        "gw_to": horizon,
        "row_count": len(rows),
        "roster_size": len(players),
        "fixture_count": len(rows),
        "monte_carlo_draws": 100,
        "base_seed": 1,
        "fixture_points_support_max": 40,
        "freshness_cold_start": True,
        "commit_sha": "forecastcommit",
        "database_sha256": HASH,
        "contracts": {"synthetic": ContractIdentity(name="synthetic", version="1", sha256=HASH)},
        "component_modes": modes,
        "live_inputs": LiveInputProvenance(
            bootstrap_capture_id="synthetic",
            bootstrap_known_at=datetime(2026, 8, 1, tzinfo=UTC),
            bootstrap_payload_sha256=HASH,
            schedule_capture_ids=("synthetic",),
        ),
    }
    base.update(manifest_overrides)
    return ProspectivePointsArtifact(manifest=ForecastArtifactManifest(**base), rows=tuple(rows))


def _default_points() -> dict[int, float]:
    # FWD 30 is the standout; DEF 10-14 beat DEF 15; MID 20-23 beat MID 24-25.
    values = {1: 3.0, 2: 1.0}
    values.update({10 + i: 6.0 - i for i in range(6)})
    values.update({20 + i: 9.0 - i for i in range(6)})
    values.update({30 + i: 10.0 - 3 * i for i in range(4)})
    return values


def _diagnostic_points() -> dict[int, float]:
    # A different architecture: the cheap DEF 15 is now the best asset and the FWD collapses,
    # so the squad, XI and captain all move.
    values = {1: 1.0, 2: 3.0}
    values.update({10 + i: 1.0 + i for i in range(6)})
    values.update({20 + i: 4.0 + (i % 3) for i in range(6)})
    values.update({30 + i: 2.0 + i for i in range(4)})
    return values


DEFAULT_MODES = {"attacking_mode": "v3", "assists_mode": "coupled", "appearance_mode": "seasonal"}
DIAGNOSTIC_MODES = {"attacking_mode": "v1", "assists_mode": "v1", "appearance_mode": "seasonal"}


def _plan_for(artifact: ProspectivePointsArtifact, *, forecast_sha: str) -> OptimizerPlanArtifact:
    rules = load_squad_rules()
    initial, index, plan, names = _solve(artifact, rules, 0.0)
    provenance = OptimizerProvenance(
        optimizer_commit_sha="optcommit",
        forecast=ForecastInputProvenance(
            path="forecast.jsonl",
            sha256=forecast_sha,
            forecast_schema=artifact.manifest.artifact_schema,
            forecast_schema_version=artifact.manifest.schema_version,
            as_of=artifact.manifest.as_of,
            season=artifact.manifest.season,
            gw_from=artifact.manifest.gw_from,
            gw_to=artifact.manifest.gw_to,
            commit_sha=artifact.manifest.commit_sha,
        ),
        squad_rules=SquadRulesProvenance(
            path="squad_2026_27.yaml", contract_version=rules.contract_version, sha256=HASH_B
        ),
    )
    return build_optimizer_plan_artifact(
        provenance=provenance,
        search_policy=_search_policy(rules, plan, 0.0),
        solver=_solver_identity(initial.solver_status),
        rules=_rules_snapshot(rules),
        initial_squad=_initial_squad_record(initial),
        plan=_plan_record_model(plan, names, index),
        assumptions=("synthetic assumption",),
    )


def _solver_identity(status: str) -> Any:
    from fpl.artifacts.optimizer_plan import SolverIdentity
    from fpl.optimize.squad import CBC_RANDOM_SEED, CBC_SOLVER_OPTIONS

    return SolverIdentity(
        name="PULP_CBC_CMD",
        package="pulp",
        package_version="0.0.0",
        binary_version="0.0.0",
        options=CBC_SOLVER_OPTIONS,
        seed=CBC_RANDOM_SEED,
        status=status,
    )


def _sha(artifact: ProspectivePointsArtifact) -> str:
    return hashlib.sha256(artifact_bytes(artifact)).hexdigest()


@pytest.fixture(scope="module")
def paths() -> tuple[
    ProspectivePointsArtifact,
    OptimizerPlanArtifact,
    ProspectivePointsArtifact,
    OptimizerPlanArtifact,
]:
    # MID 24 is the weakest MID the default path still selects, so the flags land inside the squad.
    default = _forecast(_default_points(), modes=DEFAULT_MODES, flagged=frozenset({24}))
    diagnostic = _forecast(_diagnostic_points(), modes=DIAGNOSTIC_MODES)
    return (
        default,
        _plan_for(default, forecast_sha=_sha(default)),
        diagnostic,
        _plan_for(diagnostic, forecast_sha=_sha(diagnostic)),
    )


def _build(
    paths: tuple[
        ProspectivePointsArtifact,
        OptimizerPlanArtifact,
        ProspectivePointsArtifact,
        OptimizerPlanArtifact,
    ],
    **overrides: Any,
) -> DecisionComparisonArtifact:
    default_forecast, default_plan, diagnostic_forecast, diagnostic_plan = paths
    kwargs: dict[str, Any] = {
        "default_forecast": default_forecast,
        "default_plan": default_plan,
        "default_forecast_path": "default.jsonl",
        "default_plan_sha256": HASH,
        "diagnostic_forecast": diagnostic_forecast,
        "diagnostic_plan": diagnostic_plan,
        "diagnostic_forecast_path": "diagnostic.jsonl",
        "diagnostic_plan_sha256": HASH_B,
    }
    kwargs.update(overrides)
    return build_decision_comparison(**kwargs)


# --------------------------------------------------------------------------------------
# Derivation
# --------------------------------------------------------------------------------------


def test_comparison_carries_schema_status_and_both_run_identities(paths: Any) -> None:
    comparison = _build(paths)
    assert comparison.artifact_schema == "fpl.decision-comparison"
    assert comparison.schema_version == 1
    assert comparison.status == "development_only_decision_aid_not_a_promotion_test"
    assert comparison.caveats == DECISION_COMPARISON_CAVEATS
    assert comparison.default.provenance.role == "default"
    assert comparison.diagnostic.provenance.role == "diagnostic"
    for path, plan in (
        (comparison.default, paths[1]),
        (comparison.diagnostic, paths[3]),
    ):
        assert path.provenance.optimizer_run_id == plan.run_id
        assert path.provenance.optimizer_decision_sha256 == plan.decision_sha256
    assert comparison.default.provenance.component_modes == DEFAULT_MODES
    assert comparison.diagnostic.provenance.component_modes == DIAGNOSTIC_MODES


def test_ledger_run_id_matches_the_ledger_derivation(paths: Any) -> None:
    """The comparison recovers the ledger vintage id without touching DuckDB."""
    comparison = _build(paths)
    for artifact, path in ((paths[0], comparison.default), (paths[2], comparison.diagnostic)):
        expected = derive_run_id(artifact.manifest, _sha(artifact))
        assert path.provenance.ledger_run_id == expected
        assert path.provenance.forecast_sha256 == _sha(artifact)


def test_shared_inputs_are_recorded_once_and_knowledge_time_holds(paths: Any) -> None:
    shared = _build(paths).shared_inputs
    manifest = paths[0].manifest
    assert shared.as_of == manifest.as_of
    assert (shared.gw_from, shared.gw_to) == (manifest.gw_from, manifest.gw_to)
    assert shared.database_sha256 == manifest.database_sha256
    assert shared.row_count == shared.roster_size * (shared.gw_to - shared.gw_from + 1)
    assert shared.bootstrap_known_at <= shared.as_of


def test_squad_roles_partition_the_squad_and_name_captain_and_vice(paths: Any) -> None:
    for path in (_build(paths).default, _build(paths).diagnostic):
        assert len(path.squad) == 15
        assert len(path.starting_xi) == 11
        bench_gk = [slot for slot in path.squad if slot.role == "bench_goalkeeper"]
        bench_out = [slot for slot in path.squad if slot.role == "bench_outfield"]
        assert len(bench_gk) == 1 and bench_gk[0].position == "GK"
        assert sorted(slot.bench_order_index for slot in bench_out) == [1, 2, 3]
        assert path.captain in path.starting_xi
        assert path.vice_captain in path.starting_xi
        assert path.captain != path.vice_captain
        assert path.cost_tenths == sum(slot.now_cost for slot in path.squad)


def test_first_gameweek_expected_points_reconcile_to_the_forecast_rows(paths: Any) -> None:
    comparison = _build(paths)
    for artifact, path, plan in (
        (paths[0], comparison.default, paths[1]),
        (paths[2], comparison.diagnostic, paths[3]),
    ):
        rows = {row.code: row for row in artifact.rows if row.gw == artifact.manifest.gw_from}
        derived = sum(rows[code].availability_adjusted_expected_points for code in path.starting_xi)
        derived += (path.captain_multiplier - 1) * rows[
            path.captain
        ].availability_adjusted_expected_points
        assert path.first_gw_expected_points == pytest.approx(derived)
        assert path.first_gw_expected_points == pytest.approx(plan.plan.weeks[0].expected_points)


def test_paths_actually_disagree_so_the_fixture_exercises_a_real_comparison(paths: Any) -> None:
    comparison = _build(paths)
    assert comparison.difference.squad_overlap < 15
    assert comparison.difference.captain_agreement is False
    assert comparison.default.captain != comparison.diagnostic.captain


def test_difference_sets_match_the_two_squads(paths: Any) -> None:
    comparison = _build(paths)
    default_codes = {slot.code for slot in comparison.default.squad}
    diagnostic_codes = {slot.code for slot in comparison.diagnostic.squad}
    difference = comparison.difference
    assert set(difference.common_codes) == default_codes & diagnostic_codes
    assert set(difference.default_only_codes) == default_codes - diagnostic_codes
    assert set(difference.diagnostic_only_codes) == diagnostic_codes - default_codes
    assert difference.squad_overlap == len(difference.common_codes)
    assert set(difference.first_gw_xi_common_codes) <= set(difference.common_codes)


def test_captain_cross_evaluation_scores_both_captains_under_each_model(paths: Any) -> None:
    """The gap must never be taken across two different model scales."""
    comparison = _build(paths)
    default_rows = {row.code: row for row in paths[0].rows if row.gw == 1}
    diagnostic_rows = {row.code: row for row in paths[2].rows if row.gw == 1}
    own, other = comparison.default.captain, comparison.diagnostic.captain

    under_default, under_diagnostic = comparison.captain_cross_evaluation
    assert under_default.evaluating_role == "default"
    assert under_default.own_captain_code == own
    assert under_default.other_captain_code == other
    assert under_default.own_captain_expected_points == pytest.approx(
        default_rows[own].availability_adjusted_expected_points
    )
    assert under_default.other_captain_expected_points == pytest.approx(
        default_rows[other].availability_adjusted_expected_points
    )
    assert under_diagnostic.evaluating_role == "diagnostic"
    assert under_diagnostic.own_captain_expected_points == pytest.approx(
        diagnostic_rows[other].availability_adjusted_expected_points
    )
    # Each model prefers its own captain, and each gap is computed within one model only.
    assert under_default.gap > 0
    assert under_diagnostic.gap > 0
    assert under_default.gap_after_captain_multiplier == pytest.approx(
        under_default.gap * under_default.captain_multiplier
    )


def test_flags_are_reported_for_roster_and_for_selected_players(paths: Any) -> None:
    comparison = _build(paths)
    assert set(comparison.default.roster_flag_row_counts) == set(FORECAST_FLAG_FIELDS)
    assert set(comparison.default.squad_flagged_codes) == set(FORECAST_FLAG_FIELDS)
    # Player 25 carries every flag in the default forecast, on every gameweek.
    for flag in FORECAST_FLAG_FIELDS:
        assert comparison.default.roster_flag_row_counts[flag] == HORIZON
        assert comparison.diagnostic.roster_flag_row_counts[flag] == 0
    flagged_slots = [slot for slot in comparison.default.squad if slot.flags]
    assert flagged_slots, "the fixture must select at least one flagged player"
    for slot in flagged_slots:
        # A multi-flag slot pins the sorted ordering the schema requires.
        assert slot.flags == tuple(sorted(FORECAST_FLAG_FIELDS))
        for flag in FORECAST_FLAG_FIELDS:
            assert slot.code in comparison.default.squad_flagged_codes[flag]


def test_transfer_steps_cover_the_horizon_and_reconcile_hits(paths: Any) -> None:
    for path in (_build(paths).default, _build(paths).diagnostic):
        assert [step.gw for step in path.transfer_steps] == list(range(1, HORIZON + 1))
        assert path.total_hit_points == sum(step.hit_points for step in path.transfer_steps)
        assert path.transfer_steps[0].transfers_in == ()


# --------------------------------------------------------------------------------------
# Fail-closed: a comparison that would be meaningless is refused
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "override",
    [
        {"as_of": datetime(2026, 8, 21, 17, 29, tzinfo=UTC)},
        {"season": "2025-26"},
        {"database_sha256": HASH_B},
        {"base_seed": 2},
        {"monte_carlo_draws": 200},
        {"commit_sha": "otherforecastcommit"},
    ],
)
def test_mismatched_shared_inputs_refuse_the_comparison(
    paths: Any, override: dict[str, Any]
) -> None:
    """Parity is checked before anything else, so the existing plan is enough to prove it."""
    diagnostic = _forecast(_diagnostic_points(), modes=DIAGNOSTIC_MODES, **override)
    with pytest.raises(DecisionComparisonError, match="not comparable"):
        _build(paths, diagnostic_forecast=diagnostic)


def test_mismatched_horizon_refuses_the_comparison(paths: Any) -> None:
    """A longer diagnostic horizon is not the same decision problem."""
    diagnostic = _forecast(_diagnostic_points(), modes=DIAGNOSTIC_MODES, horizon=HORIZON + 1)
    with pytest.raises(DecisionComparisonError, match="not comparable"):
        _build(paths, diagnostic_forecast=diagnostic)


def test_different_live_captures_refuse_the_comparison(paths: Any) -> None:
    diagnostic = _forecast(
        _diagnostic_points(),
        modes=DIAGNOSTIC_MODES,
        live_inputs=LiveInputProvenance(
            bootstrap_capture_id="other",
            bootstrap_known_at=datetime(2026, 8, 2, tzinfo=UTC),
            bootstrap_payload_sha256=HASH_B,
            schedule_capture_ids=("other",),
        ),
    )
    with pytest.raises(DecisionComparisonError, match="different live captures"):
        _build(
            paths,
            diagnostic_forecast=diagnostic,
            diagnostic_plan=_plan_for(diagnostic, forecast_sha=_sha(diagnostic)),
        )


def test_different_frozen_contracts_refuse_the_comparison(paths: Any) -> None:
    diagnostic = _forecast(
        _diagnostic_points(),
        modes=DIAGNOSTIC_MODES,
        contracts={"synthetic": ContractIdentity(name="synthetic", version="2", sha256=HASH)},
    )
    with pytest.raises(DecisionComparisonError, match="different frozen contracts"):
        _build(
            paths,
            diagnostic_forecast=diagnostic,
            diagnostic_plan=_plan_for(diagnostic, forecast_sha=_sha(diagnostic)),
        )


def test_identical_architectures_refuse_the_comparison(paths: Any) -> None:
    same = _forecast(_diagnostic_points(), modes=DEFAULT_MODES)
    with pytest.raises(DecisionComparisonError, match="nothing to compare"):
        _build(
            paths,
            diagnostic_forecast=same,
            diagnostic_plan=_plan_for(same, forecast_sha=_sha(same)),
        )


def test_plan_paired_with_the_wrong_forecast_is_refused(paths: Any) -> None:
    with pytest.raises(DecisionComparisonError, match="not produced from"):
        _build(paths, default_plan=paths[3])


def test_plan_expected_points_that_do_not_reconcile_are_refused(paths: Any) -> None:
    """A plan whose own weekly EV disagrees with its forecast rows cannot be compared."""
    _, default_plan, _, _ = paths
    inflated_weeks = tuple(
        TransferWeekRecord(
            **{
                **week.model_dump(),
                "expected_points": week.expected_points + 1.0,
                "objective_value": week.objective_value + 1.0,
            }
        )
        for week in default_plan.plan.weeks
    )
    inflated_plan = TransferPlanRecord(
        expected_points_before_hits=sum(week.expected_points for week in inflated_weeks),
        hit_points=default_plan.plan.hit_points,
        expected_points_after_hits=sum(week.expected_points for week in inflated_weeks)
        - default_plan.plan.hit_points,
        objective_value_after_hits=sum(week.objective_value for week in inflated_weeks)
        - default_plan.plan.hit_points,
        candidate_pool_size=default_plan.plan.candidate_pool_size,
        weeks=inflated_weeks,
    )
    tampered = build_optimizer_plan_artifact(
        provenance=default_plan.provenance,
        search_policy=default_plan.search_policy,
        solver=default_plan.solver,
        rules=default_plan.rules,
        initial_squad=default_plan.initial_squad,
        plan=inflated_plan,
        assumptions=default_plan.assumptions,
    )
    with pytest.raises(DecisionComparisonError, match="do not reconcile"):
        _build(paths, default_plan=tampered)


# --------------------------------------------------------------------------------------
# Identity, serialisation, immutability
# --------------------------------------------------------------------------------------


def test_comparison_id_is_stable_and_bytes_are_deterministic(paths: Any) -> None:
    first, second = _build(paths), _build(paths)
    assert first.comparison_id == second.comparison_id
    assert decision_comparison_bytes(first) == decision_comparison_bytes(second)
    payload = json.loads(decision_comparison_bytes(first).decode())
    assert list(payload) == sorted(payload)


def test_comparison_id_ignores_relocatable_paths(paths: Any) -> None:
    moved = _build(paths, default_forecast_path="/elsewhere/default.jsonl")
    assert moved.comparison_id == _build(paths).comparison_id


@pytest.mark.parametrize(
    "override",
    [
        {"default_plan_sha256": HASH_B},
        {"diagnostic_plan_sha256": HASH},
    ],
)
def test_comparison_id_changes_with_either_path_identity(
    paths: Any, override: dict[str, Any]
) -> None:
    assert _build(paths, **override).comparison_id != _build(paths).comparison_id


def test_round_trip_through_reader(tmp_path: Path, paths: Any) -> None:
    comparison = _build(paths)
    destination = tmp_path / "comparison.json"
    digest = write_decision_comparison_atomic(destination, comparison)
    assert digest == hashlib.sha256(destination.read_bytes()).hexdigest()
    restored = read_decision_comparison(destination)
    assert restored == comparison


def test_no_clobber_refuses_to_overwrite(tmp_path: Path, paths: Any) -> None:
    comparison = _build(paths)
    destination = tmp_path / "comparison.json"
    write_decision_comparison_atomic(destination, comparison)
    before = destination.read_bytes()
    with pytest.raises(DecisionComparisonExistsError):
        write_decision_comparison_atomic(destination, comparison)
    assert destination.read_bytes() == before


def test_atomic_write_failure_leaves_no_partial_output(tmp_path: Path, paths: Any) -> None:
    destination = tmp_path / "comparison.json"

    def boom() -> None:
        raise RuntimeError("input drifted before publication")

    with pytest.raises(RuntimeError, match="drifted"):
        write_decision_comparison_atomic(destination, _build(paths), pre_publish=boom)
    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []


def test_concurrent_writers_have_exactly_one_winner(tmp_path: Path, paths: Any) -> None:
    comparison = _build(paths)
    destination = tmp_path / "comparison.json"
    outcomes: list[str] = []

    def attempt(_: int) -> str:
        try:
            write_decision_comparison_atomic(destination, comparison)
            return "won"
        except DecisionComparisonExistsError:
            return "refused"

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(attempt, range(8)))
    assert outcomes.count("won") == 1
    assert outcomes.count("refused") == 7
    assert [entry.name for entry in tmp_path.iterdir()] == ["comparison.json"]
    read_decision_comparison(destination)


# --------------------------------------------------------------------------------------
# Reader-side tamper rejection
# --------------------------------------------------------------------------------------


def _tampered(comparison: DecisionComparisonArtifact, mutate: Callable[[dict], None]) -> dict:
    payload = json.loads(decision_comparison_bytes(comparison).decode())
    mutate(payload)
    return payload


def test_bare_comparison_id_tamper_is_rejected(paths: Any) -> None:
    payload = _tampered(_build(paths), lambda body: body.__setitem__("comparison_id", HASH))
    with pytest.raises(ValidationError, match="comparison_id"):
        DecisionComparisonArtifact.model_validate(payload)


def _rehash(payload: dict) -> None:
    from fpl.artifacts.decision_comparison import PathDecision, SharedInputs

    payload["comparison_id"] = derive_comparison_id(
        SharedInputs.model_validate(payload["shared_inputs"]),
        PathDecision.model_validate(payload["default"]),
        PathDecision.model_validate(payload["diagnostic"]),
    )


def test_falsified_captain_agreement_is_rejected(paths: Any) -> None:
    def mutate(body: dict) -> None:
        body["difference"]["captain_agreement"] = not body["difference"]["captain_agreement"]
        _rehash(body)

    with pytest.raises(ValidationError, match="captain_agreement"):
        DecisionComparisonArtifact.model_validate(_tampered(_build(paths), mutate))


def test_falsified_difference_sets_are_rejected(paths: Any) -> None:
    """Emptying the shared set is caught even with the id recomputed over the lie."""

    def mutate(body: dict) -> None:
        body["difference"]["common_codes"] = []
        body["difference"]["squad_overlap"] = 0
        body["difference"]["first_gw_xi_common_codes"] = []
        body["difference"]["first_gw_xi_overlap"] = 0
        _rehash(body)

    with pytest.raises(ValidationError, match="common codes do not match"):
        DecisionComparisonArtifact.model_validate(_tampered(_build(paths), mutate))


def test_shared_starter_outside_the_shared_squad_is_rejected(paths: Any) -> None:
    def mutate(body: dict) -> None:
        body["difference"]["common_codes"] = []
        body["difference"]["squad_overlap"] = 0
        _rehash(body)

    with pytest.raises(ValidationError, match="shared starter"):
        DecisionComparisonArtifact.model_validate(_tampered(_build(paths), mutate))


def test_falsified_captain_gap_is_rejected(paths: Any) -> None:
    def mutate(body: dict) -> None:
        body["captain_cross_evaluation"][0]["gap"] += 5.0
        _rehash(body)

    with pytest.raises(ValidationError, match="captain gap"):
        DecisionComparisonArtifact.model_validate(_tampered(_build(paths), mutate))


def test_swapped_roles_are_rejected(paths: Any) -> None:
    def mutate(body: dict) -> None:
        body["default"]["provenance"]["role"] = "diagnostic"
        _rehash(body)

    with pytest.raises(ValidationError, match="role 'default'"):
        DecisionComparisonArtifact.model_validate(_tampered(_build(paths), mutate))


def test_non_finite_expected_points_are_rejected(paths: Any) -> None:
    def mutate(body: dict) -> None:
        body["default"]["first_gw_expected_points"] = float("nan")

    with pytest.raises(ValidationError):
        DecisionComparisonArtifact.model_validate(_tampered(_build(paths), mutate))


def test_reader_rejects_malformed_file(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(DecisionComparisonError):
        read_decision_comparison(broken)


# --------------------------------------------------------------------------------------
# Rendered report and CLI
# --------------------------------------------------------------------------------------


def test_report_contains_every_p0_3_required_element(paths: Any) -> None:
    comparison = _build(paths)
    report = render_decision_comparison(comparison)
    assert "GW1 decision comparison" in report
    assert comparison.comparison_id in report
    for path in (comparison.default, comparison.diagnostic):
        assert path.provenance.ledger_run_id in report
        assert path.provenance.optimizer_run_id in report
        assert path.provenance.optimizer_decision_sha256 in report
        assert f"{path.first_gw_expected_points:.2f}" in report
        assert f"{path.horizon_expected_points_after_hits:.2f}" in report
        for slot in path.squad:
            assert str(slot.code) in report
    assert "DISAGREE" in report  # the fixture's captains differ
    assert "Captain cross-evaluation" in report
    assert "frozen-price" in report
    assert "not a promotion test" in report
    assert "Transfer scenario" in report


def test_cli_writes_artifact_and_report_then_refuses_to_overwrite(
    tmp_path: Path, paths: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    default_forecast, _, diagnostic_forecast, _ = paths
    default_path = tmp_path / "default.jsonl"
    diagnostic_path = tmp_path / "diagnostic.jsonl"
    write_artifact_atomic(default_path, default_forecast)
    write_artifact_atomic(diagnostic_path, diagnostic_forecast)

    default_plan = tmp_path / "default-plan.json"
    diagnostic_plan = tmp_path / "diagnostic-plan.json"
    from fpl.artifacts.optimizer_plan import write_optimizer_artifact_atomic

    write_optimizer_artifact_atomic(
        default_plan, _plan_for(default_forecast, forecast_sha=_sha(default_forecast))
    )
    write_optimizer_artifact_atomic(
        diagnostic_plan, _plan_for(diagnostic_forecast, forecast_sha=_sha(diagnostic_forecast))
    )

    output = tmp_path / "comparison.json"
    report = tmp_path / "comparison.md"
    argv = [
        "--default-forecast",
        str(default_path),
        "--default-plan",
        str(default_plan),
        "--diagnostic-forecast",
        str(diagnostic_path),
        "--diagnostic-plan",
        str(diagnostic_plan),
        "--output",
        str(output),
        "--report",
        str(report),
    ]
    assert main(argv) == 0
    printed = capsys.readouterr().out
    assert "GW1 decision comparison" in printed
    restored = read_decision_comparison(output)
    assert report.read_text(encoding="utf-8") == render_decision_comparison(restored)

    # Immutable: a second identical invocation refuses rather than overwriting.
    assert main(argv) == 1
    assert read_decision_comparison(output) == restored


def test_cli_refuses_a_plan_that_does_not_match_its_forecast(tmp_path: Path, paths: Any) -> None:
    default_forecast, _, diagnostic_forecast, _ = paths
    default_path = tmp_path / "default.jsonl"
    diagnostic_path = tmp_path / "diagnostic.jsonl"
    write_artifact_atomic(default_path, default_forecast)
    write_artifact_atomic(diagnostic_path, diagnostic_forecast)
    from fpl.artifacts.optimizer_plan import write_optimizer_artifact_atomic

    swapped = tmp_path / "swapped-plan.json"
    write_optimizer_artifact_atomic(
        swapped, _plan_for(diagnostic_forecast, forecast_sha=_sha(diagnostic_forecast))
    )
    assert (
        main(
            [
                "--default-forecast",
                str(default_path),
                "--default-plan",
                str(swapped),
                "--diagnostic-forecast",
                str(diagnostic_path),
                "--diagnostic-plan",
                str(swapped),
            ]
        )
        == 1
    )
