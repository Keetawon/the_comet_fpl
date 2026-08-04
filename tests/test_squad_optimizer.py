"""Offline, hand-computable contracts for Stage E squad and transfer optimisation."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fpl.artifacts.prospective_points import (
    ContractIdentity,
    ForecastArtifactManifest,
    ForecastArtifactRow,
    LiveInputProvenance,
    ProspectivePointsArtifact,
    write_artifact_atomic,
)
from fpl.jobs.optimize_squad import main
from fpl.optimize.rules import SquadRules, load_squad_rules
from fpl.optimize.squad import (
    ArtifactIndex,
    SquadMember,
    SquadSolution,
    exact_lineup,
    optimize_initial_squad,
)
from fpl.optimize.transfers import plan_transfers

HASH = "a" * 64


@dataclass(frozen=True, slots=True)
class _Player:
    code: int
    position: str
    points: tuple[float, ...]
    cost: int = 40
    team_id: int | None = None


def _distribution(mean: float) -> tuple[float, ...]:
    lower = math.floor(mean)
    fraction = mean - lower
    if fraction == 0.0:
        return (*((0.0,) * lower), 1.0)
    return (*((0.0,) * lower), 1.0 - fraction, fraction)


def _artifact(players: tuple[_Player, ...]) -> ProspectivePointsArtifact:
    horizon = len(players[0].points)
    assert all(len(player.points) == horizon for player in players)
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
                    team_id=player.team_id or player.code,
                    team_code=player.team_id or player.code,
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
    contract = ContractIdentity(name="synthetic", version="1", sha256=HASH)
    manifest = ForecastArtifactManifest(
        as_of=datetime(2026, 8, 21, 17, 30, tzinfo=UTC),
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
        commit_sha="test",
        database_sha256=HASH,
        contracts={"synthetic": contract},
        component_modes={"test": "synthetic"},
        live_inputs=LiveInputProvenance(
            bootstrap_capture_id="synthetic",
            bootstrap_known_at=datetime(2026, 8, 1, tzinfo=UTC),
            bootstrap_payload_sha256=HASH,
            schedule_capture_ids=("synthetic",),
        ),
    )
    return ProspectivePointsArtifact(manifest=manifest, rows=tuple(rows))


def _base_players(horizon: int = 1) -> tuple[_Player, ...]:
    values = {
        "GK": (10, 1, 0),
        "DEF": (9, 8, 7, 6, 5, 0),
        "MID": (12, 11, 10, 9, 8, 0),
        "FWD": (13, 6, 5, 0),
    }
    starts = {"GK": 1, "DEF": 10, "MID": 20, "FWD": 30}
    return tuple(
        _Player(
            code=starts[position] + offset,
            position=position,
            points=(score,) * horizon,
        )
        for position, scores in values.items()
        for offset, score in enumerate(scores)
    )


def _manual_solution(
    artifact: ProspectivePointsArtifact,
    rules: SquadRules,
    codes: tuple[int, ...],
) -> tuple[ArtifactIndex, SquadSolution]:
    index = ArtifactIndex.build(artifact, rules)
    weeks = tuple(exact_lineup(index, rules, codes, gw, 0.0) for gw in index.gws)
    members = tuple(
        SquadMember(
            code=code,
            web_name=index.first_by_code[code].web_name,
            position=index.first_by_code[code].position,
            team_id=index.first_by_code[code].team_id,
            team_code=index.first_by_code[code].team_code,
            now_cost=index.first_by_code[code].now_cost or 0,
            selected_by_percent=None,
        )
        for code in codes
    )
    return index, SquadSolution(
        members=members,
        squad_cost_tenths=sum(member.now_cost for member in members),
        weeks=weeks,
        expected_points=sum(week.expected_points for week in weeks),
        objective_value=sum(week.objective_value for week in weeks),
        risk_lambda=0.0,
        solver_status="manual-test-fixture",
    )


def test_verified_rules_match_captured_official_2026_27_values() -> None:
    rules = load_squad_rules()
    assert rules.squad.size == 15
    assert rules.squad.budget_tenths == 1000
    assert rules.squad.maximum_per_club == 3
    assert {name: rule.squad for name, rule in rules.squad.positions.items()} == {
        "GK": 2,
        "DEF": 5,
        "MID": 5,
        "FWD": 3,
    }
    assert rules.squad.positions["MID"].minimum_starters == 2
    assert rules.transfers.free_transfer_bank_cap == 5
    assert rules.transfers.hit_cost_points == 4


def test_exact_optimizer_selects_hand_computable_squad_lineup_and_captain() -> None:
    forced_squad = tuple(player for player in _base_players() if player.code not in {3, 15, 25, 33})
    artifact = _artifact(forced_squad)
    solution = optimize_initial_squad(artifact, load_squad_rules())
    repeated = optimize_initial_squad(artifact, load_squad_rules())
    assert repeated == solution
    assert solution.codes == (1, 2, 10, 11, 12, 13, 14, 20, 21, 22, 23, 24, 30, 31, 32)
    assert solution.squad_cost_tenths == 600
    assert solution.weeks[0].captain == 30
    assert len(solution.weeks[0].starting_xi) == 11
    assert solution.solver_status == "Optimal"


def test_budget_constraint_binds_and_excludes_unaffordable_best_player() -> None:
    players = tuple(
        replace(player, cost=100 if player.code == 30 else 40) for player in _base_players()
    )
    rules = load_squad_rules()
    tight_rules = rules.model_copy(
        update={"squad": rules.squad.model_copy(update={"budget_tenths": 600})}
    )
    solution = optimize_initial_squad(_artifact(players), tight_rules)
    assert solution.squad_cost_tenths == 600
    assert 30 not in solution.codes
    assert 33 in solution.codes


def test_club_cap_binds_across_positions() -> None:
    same_club = {1, 10, 20, 30}
    players = tuple(
        replace(player, team_id=99 if player.code in same_club else player.code)
        for player in _base_players()
    )
    solution = optimize_initial_squad(_artifact(players), load_squad_rules())
    selected_same_club = same_club.intersection(solution.codes)
    assert len(selected_same_club) == 3
    assert 10 not in selected_same_club


def _transfer_artifact(second_mid_gain: float) -> ProspectivePointsArtifact:
    initial_codes = {1, 2, 10, 11, 12, 13, 14, 20, 21, 22, 23, 24, 30, 31, 32}
    players: list[_Player] = []
    for player in _base_players(horizon=2):
        if player.code not in initial_codes:
            continue
        gw2 = 20.0 if player.code == 30 else 5.0
        players.append(replace(player, points=(player.points[0], gw2)))
    players.append(_Player(code=15, position="DEF", points=(0.0, 11.0)))
    players.append(_Player(code=25, position="MID", points=(0.0, 5.0 + second_mid_gain)))
    return _artifact(tuple(players))


@pytest.mark.parametrize(
    ("second_mid_gain", "expected_transfers", "expected_hit"),
    [(5.0, 2, 4), (3.0, 1, 0)],
)
def test_transfer_planner_takes_hit_only_when_incremental_gain_repays_it(
    second_mid_gain: float,
    expected_transfers: int,
    expected_hit: int,
) -> None:
    artifact = _transfer_artifact(second_mid_gain)
    rules = load_squad_rules()
    initial_codes = (1, 2, 10, 11, 12, 13, 14, 20, 21, 22, 23, 24, 30, 31, 32)
    index, initial = _manual_solution(artifact, rules, initial_codes)
    plan = plan_transfers(index, rules, initial)
    gw2 = plan.weeks[1]
    assert len(gw2.transfers_in) == expected_transfers
    assert gw2.hit_points == expected_hit
    assert 15 in gw2.transfers_in
    assert (25 in gw2.transfers_in) is (expected_transfers == 2)


def test_distributional_risk_penalty_can_change_a_pick_without_claiming_lift() -> None:
    players = list(_base_players())
    players = [player for player in players if player.code not in {30, 33}]
    players.extend(
        (
            _Player(code=30, position="FWD", points=(10.0,)),
            _Player(code=33, position="FWD", points=(9.0,)),
        )
    )
    players = [
        replace(player, points=(15.0,))
        if player.code == 31
        else replace(player, points=(14.0,))
        if player.code == 32
        else player
        for player in players
    ]
    artifact = _artifact(tuple(players))
    rows = list(artifact.rows)
    risky_index = next(index for index, row in enumerate(rows) if row.code == 30)
    rows[risky_index] = rows[risky_index].model_copy(
        update={"distribution": (0.5, *((0.0,) * 19), 0.5)}
    )
    artifact = ProspectivePointsArtifact(manifest=artifact.manifest, rows=tuple(rows))

    mean_solution = optimize_initial_squad(artifact, load_squad_rules(), risk_lambda=0.0)
    risk_solution = optimize_initial_squad(artifact, load_squad_rules(), risk_lambda=0.5)
    assert 30 in mean_solution.codes and 33 not in mean_solution.codes
    assert 33 in risk_solution.codes and 30 not in risk_solution.codes


def test_cli_consumes_only_artifact_and_emits_machine_readable_plan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    forced_squad = tuple(player for player in _base_players() if player.code not in {3, 15, 25, 33})
    path = tmp_path / "forecast.jsonl"
    write_artifact_atomic(path, _artifact(forced_squad))
    assert main([str(path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["artifact"]["schema"] == "fpl.prospective-points"
    assert len(report["initial_squad"]["members"]) == 15
    assert report["plan"]["weeks"][0]["captain"]["code"] == 30
