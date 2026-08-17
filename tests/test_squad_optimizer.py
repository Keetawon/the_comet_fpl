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
    OptimizationError,
    SquadMember,
    SquadSolution,
    appearance_lower_bound,
    bench_appearance_satisfied,
    exact_lineup,
    optimize_initial_squad,
)
from fpl.optimize.transfers import _successor_squads, plan_transfers

HASH = "a" * 64


@dataclass(frozen=True, slots=True)
class _Player:
    code: int
    position: str
    points: tuple[float, ...]
    cost: int = 40
    team_id: int | None = None
    availability_multiplier: float = 1.0
    selected_by_percent: float | None = None


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
            adjusted = player.availability_multiplier * expected
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
                    selected_by_percent=player.selected_by_percent,
                    availability_status="a",
                    chance_of_playing=None,
                    availability_multiplier=player.availability_multiplier,
                    fixture_ids=(gw * 1000 + player.code,),
                    kickoff_times=(datetime(2026, 8, 21 + gw, tzinfo=UTC),),
                    expected_points=expected,
                    availability_adjusted_expected_points=adjusted,
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


# --------------------------------------------------------------------------------------
# Bench appearance gate (min_bench_appearance)
# --------------------------------------------------------------------------------------


def test_appearance_lower_bound_is_the_zero_points_tail_scaled_by_overlay() -> None:
    index = ArtifactIndex.build(_artifact(_base_players()), load_squad_rules())
    never = index.rows[(15, 1)]  # 0 expected points -> all mass at zero -> bound 0
    starter = index.rows[(10, 1)]  # mean 9 -> no mass at zero -> bound 1
    assert appearance_lower_bound(never) == 0.0
    assert appearance_lower_bound(starter) == 1.0
    doubtful = starter.model_copy(
        update={
            "availability_multiplier": 0.5,
            "availability_adjusted_expected_points": starter.expected_points * 0.5,
        }
    )
    assert appearance_lower_bound(doubtful) == pytest.approx(0.5)


def test_min_bench_appearance_keeps_outfield_bench_slots_playable() -> None:
    fodder = {3, 15, 25, 33}  # one 0-point player per position, made cheaper than everyone
    players = tuple(
        replace(player, cost=30) if player.code in fodder else player for player in _base_players()
    )
    artifact = _artifact(players)
    rules = load_squad_rules()

    ungated = optimize_initial_squad(artifact, rules)
    ungated_index = ArtifactIndex.build(artifact, rules)
    # Without the gate the min-price tie-break benches at least one never-playing filler.
    assert any(
        appearance_lower_bound(ungated_index.rows[(code, ungated.weeks[0].gw)]) == 0.0
        for code in ungated.weeks[0].bench_order
    )

    gated = optimize_initial_squad(artifact, rules, min_bench_appearance=0.5)
    index = ArtifactIndex.build(artifact, rules)
    for week in gated.weeks:
        assert all(
            appearance_lower_bound(index.rows[(code, week.gw)]) >= 0.5 for code in week.bench_order
        )
    # The never-playing outfielders are gone; the exempt bench goalkeeper (code 3, bound 0)
    # is still selected and still benches -- a backup keeper cannot clear any gate.
    assert not ({15, 25, 33} & set(gated.codes))
    assert 3 in gated.codes
    assert gated.weeks[0].bench_goalkeeper == 3
    assert appearance_lower_bound(index.rows[(3, 1)]) == 0.0
    assert bench_appearance_satisfied(index, gated.weeks[0], 0.5)
    assert gated.squad_cost_tenths > ungated.squad_cost_tenths  # playable bench costs more


def test_min_bench_appearance_above_every_outfielder_is_infeasible() -> None:
    starts = {"GK": 1, "DEF": 10, "MID": 20, "FWD": 30}
    counts = {"GK": 3, "DEF": 6, "MID": 6, "FWD": 4}
    players: list[_Player] = []
    for position, count in counts.items():
        for offset in range(count):
            points = ((10.0, 5.0, 0.0)[offset],) if position == "GK" else (0.5,)
            players.append(
                _Player(code=starts[position] + offset, position=position, points=points)
            )
    # Every outfielder's appearance bound is 0.5, so a 0.9 gate leaves no legal bench.
    with pytest.raises(OptimizationError, match=r"min_bench_appearance=0\.9"):
        optimize_initial_squad(
            _artifact(tuple(players)), load_squad_rules(), min_bench_appearance=0.9
        )


@pytest.mark.parametrize("value", [-0.1, 1.5])
def test_min_bench_appearance_rejects_out_of_range_thresholds(value: float) -> None:
    with pytest.raises(ValueError, match="min_bench_appearance"):
        optimize_initial_squad(
            _artifact(_base_players()), load_squad_rules(), min_bench_appearance=value
        )


def test_bench_tie_break_never_suggests_a_zero_availability_player() -> None:
    """The cheapest keeper is ruled out by the overlay (injured, multiplier 0).

    Bench points are outside the objective, so the min-price tie-break would otherwise love a
    cheap injured filler. He must rank behind every available player at any price: the bench
    goalkeeper slot goes to the available backup even though the injured one is cheaper, and
    the primary-objective XI is unchanged.
    """
    players = tuple(
        replace(player, cost=30, availability_multiplier=0.0)
        if player.code == 3
        else replace(player, cost=45, availability_multiplier=0.75)
        if player.code == 2
        else player
        for player in _base_players()
    )
    artifact = _artifact(players)
    rules = load_squad_rules()
    solution = optimize_initial_squad(artifact, rules)
    assert 3 not in solution.codes
    assert solution.weeks[0].bench_goalkeeper == 2
    baseline = optimize_initial_squad(_artifact(_base_players()), rules)
    assert solution.weeks[0].starting_xi == baseline.weeks[0].starting_xi


def test_equally_priced_fillers_prefer_the_most_selected_players() -> None:
    """Owner rule: cheap bench filler must be crowd-vetted, not an alphabetical obscurity.

    The bench-goalkeeper slot is exactly one deterministic filler slot (one GK starts, one
    benches), so two same-price candidates differ only in ownership. Among them the
    tie-break takes the highest-ownership player -- but price still dominates: a cheaper
    unpopular filler beats a costlier popular one, because saving budget for the XI is the
    tie-break's purpose.
    """
    popular = _Player(code=5, position="GK", points=(0.0,), selected_by_percent=30.0)
    obscure = _Player(code=6, position="GK", points=(0.0,), selected_by_percent=0.1)
    base = tuple(player for player in _base_players() if player.code != 3)
    rules = load_squad_rules()

    same_price = optimize_initial_squad(_artifact((*base, popular, obscure)), rules)
    assert same_price.weeks[0].bench_goalkeeper == 5  # 30% owned beats 0.1%

    cheaper = _Player(code=7, position="GK", points=(0.0,), cost=39, selected_by_percent=0.0)
    price_first = optimize_initial_squad(_artifact((*base, popular, obscure, cheaper)), rules)
    assert price_first.weeks[0].bench_goalkeeper == 7  # price beats popularity
    assert price_first.squad_cost_tenths < same_price.squad_cost_tenths


# --------------------------------------------------------------------------------------
# Locked must-keep players
# --------------------------------------------------------------------------------------


def test_locked_players_are_pinned_and_compose_with_the_bench_gate() -> None:
    fodder = {3, 15, 25, 33}
    players = tuple(
        replace(player, cost=30) if player.code in fodder else player for player in _base_players()
    )
    artifact = _artifact(players)
    rules = load_squad_rules()

    gated = optimize_initial_squad(artifact, rules, min_bench_appearance=0.5)
    assert 15 not in set(gated.codes)  # the never-playing cheap DEF is dropped by the gate

    locked = optimize_initial_squad(artifact, rules, min_bench_appearance=0.5, locked_codes=(15,))
    assert 15 in set(locked.codes)
    # The policies compose rather than override: a locked never-playing player cannot bench
    # below the gate, so he must START every planned gameweek.
    for week in locked.weeks:
        assert 15 in week.starting_xi
    index = ArtifactIndex.build(artifact, rules)
    assert bench_appearance_satisfied(index, locked.weeks[0], 0.5)
    assert locked.locked_codes == (15,)


def test_locked_codes_must_be_selectable_players() -> None:
    with pytest.raises(OptimizationError, match="not selectable"):
        optimize_initial_squad(_artifact(_base_players()), load_squad_rules(), locked_codes=(9999,))


def test_locked_players_are_never_transferred_out() -> None:
    # 32 is uniquely weak at GW2 and a better FWD candidate exists, so the open plan ships
    # him out; locking him keeps him for the whole horizon while the plan adapts.
    players: list[_Player] = []
    for player in _base_players(horizon=2):
        if player.code not in set(_INITIAL_SQUAD):
            continue
        gw2 = 1.0 if player.code == 32 else 5.0
        players.append(replace(player, points=(player.points[0], gw2)))
    players.append(_Player(code=35, position="FWD", points=(0.0, 8.0)))
    artifact = _artifact(tuple(players))
    rules = load_squad_rules()
    index, initial = _manual_solution(artifact, rules, _INITIAL_SQUAD)

    open_plan = plan_transfers(index, rules, initial)
    assert any(32 in week.transfers_out for week in open_plan.weeks)

    locked_plan = plan_transfers(index, rules, initial, locked_codes=(32,))
    assert not any(32 in week.transfers_out for week in locked_plan.weeks)


def test_plan_transfers_locks_must_be_in_the_initial_squad() -> None:
    artifact = _transfer_artifact(5.0)
    rules = load_squad_rules()
    index, initial = _manual_solution(artifact, rules, _INITIAL_SQUAD)
    with pytest.raises(OptimizationError, match="not in the initial squad"):
        plan_transfers(index, rules, initial, locked_codes=(15,))


def test_plan_transfers_seeds_banked_free_transfers_from_a_manager_season() -> None:
    artifact = _transfer_artifact(5.0)
    rules = load_squad_rules()
    index, initial = _manual_solution(artifact, rules, _INITIAL_SQUAD)
    # With no banked transfer the same plan pays a -4 hit for its second transfer.
    from_scratch = plan_transfers(index, rules, initial)
    assert from_scratch.weeks[1].hit_points == 4
    assert from_scratch.weeks[0].free_transfers_before == 0
    # A manager carrying one banked free transfer makes both moves free.
    banked = plan_transfers(index, rules, initial, initial_banked_free_transfers=1)
    assert banked.weeks[0].free_transfers_before == 1
    assert banked.weeks[1].hit_points == 0
    assert banked.hit_points == 0


def test_plan_transfers_rejects_banked_free_transfers_above_the_cap() -> None:
    artifact = _transfer_artifact(5.0)
    rules = load_squad_rules()
    index, initial = _manual_solution(artifact, rules, _INITIAL_SQUAD)
    cap = rules.transfers.free_transfer_bank_cap
    with pytest.raises(ValueError, match="initial_banked_free_transfers"):
        plan_transfers(index, rules, initial, initial_banked_free_transfers=cap + 1)


def test_plan_transfers_holds_the_gate_across_the_horizon() -> None:
    artifact = _transfer_artifact(5.0)
    rules = load_squad_rules()
    index, initial = _manual_solution(artifact, rules, _INITIAL_SQUAD)
    plan = plan_transfers(index, rules, initial, min_bench_appearance=0.5)
    for week in plan.weeks:
        assert bench_appearance_satisfied(index, week.lineup, 0.5)


def test_plan_transfers_rejects_states_that_bench_below_the_gate() -> None:
    # The captain collapses to a 0.25-mean GW2: every GW2 lineup benches him, the only FWD
    # replacement (33) also benches below the gate, and holding benches him too -- so the
    # search finds no legal state and says so instead of silently relaxing the gate.
    players: list[_Player] = []
    for player in _base_players(horizon=2):
        if player.code not in set(_INITIAL_SQUAD):
            continue
        gw2 = 0.25 if player.code == 30 else 5.0
        players.append(replace(player, points=(player.points[0], gw2)))
    artifact = _artifact(tuple(players))
    rules = load_squad_rules()
    index, initial = _manual_solution(artifact, rules, _INITIAL_SQUAD)
    with pytest.raises(RuntimeError, match="no legal state"):
        plan_transfers(index, rules, initial, min_bench_appearance=0.5)


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


_INITIAL_SQUAD = (1, 2, 10, 11, 12, 13, 14, 20, 21, 22, 23, 24, 30, 31, 32)


def _with_search(rules: SquadRules, **overrides: int) -> SquadRules:
    """Override the bounded-search limits on a frozen rules object for a focused test."""
    return rules.model_copy(update={"search": rules.search.model_copy(update=overrides)})


def _successor_fixture(
    n_def_upgrades: int, upgrade_points: float = 20.0
) -> tuple[ArtifactIndex, SquadRules, tuple[int, ...]]:
    """15-man squad plus `n_def_upgrades` DEF alternatives on distinct clubs.

    At the default `upgrade_points` every alternative beats every squad defender, so any single
    swap of a squad DEF for an alternative has positive immediate improvement -- far more positive
    proposals than a small transition limit can keep, which is exactly what truncated the
    no-transfer action away.
    """
    squad_players = tuple(p for p in _base_players() if p.code in set(_INITIAL_SQUAD))
    upgrades = tuple(
        _Player(code=4000 + i, position="DEF", points=(upgrade_points,), team_id=4000 + i)
        for i in range(n_def_upgrades)
    )
    artifact = _artifact(squad_players + upgrades)
    rules = load_squad_rules()
    index = ArtifactIndex.build(artifact, rules)
    pool = tuple(sorted(u.code for u in upgrades))
    return index, rules, pool


def test_successor_set_reserves_the_no_transfer_action_under_positive_pressure() -> None:
    """The current squad must survive truncation even when every retained proposal improves.

    Failing-test-first: before the fix the current squad is seeded at improvement 0.0, sorts below
    every positive-improvement swap, and is truncated at transition_limit_per_state, so it is
    absent from the successor set. Asserting it is PRESENT fails pre-fix and passes post-fix.
    """
    index, rules, pool = _successor_fixture(n_def_upgrades=5)
    rules = _with_search(
        rules, transition_limit_per_state=1, maximum_planned_transfers_per_gameweek=1
    )
    successors = _successor_squads(index, rules, _INITIAL_SQUAD, pool, 1, 0.0)
    assert len(successors) >= 2  # the single best swap plus the reserved hold
    assert _INITIAL_SQUAD in successors


@pytest.mark.parametrize("max_depth", [1, 2])
@pytest.mark.parametrize("transition_limit", [1, 3])
@pytest.mark.parametrize("n_upgrades", [2, 5])
def test_no_transfer_action_is_reserved_across_depths_and_limits(
    max_depth: int, transition_limit: int, n_upgrades: int
) -> None:
    index, rules, pool = _successor_fixture(n_def_upgrades=n_upgrades)
    rules = _with_search(
        rules,
        transition_limit_per_state=transition_limit,
        maximum_planned_transfers_per_gameweek=max_depth,
    )
    successors = _successor_squads(index, rules, _INITIAL_SQUAD, pool, 1, 0.0)
    assert _INITIAL_SQUAD in successors


def test_no_transfer_action_is_reserved_when_it_is_already_the_best_proposal() -> None:
    """When no swap improves, hold sorts at the top and must still be present.

    This case passes before and after the fix -- the control showing the reservation does not
    depend on truncation happening, only that hold is never dropped.
    """
    index, rules, pool = _successor_fixture(n_def_upgrades=3, upgrade_points=0.0)
    rules = _with_search(
        rules, transition_limit_per_state=1, maximum_planned_transfers_per_gameweek=1
    )
    successors = _successor_squads(index, rules, _INITIAL_SQUAD, pool, 1, 0.0)
    assert _INITIAL_SQUAD in successors


def _hold_artifact() -> ProspectivePointsArtifact:
    """Initial squad flat at 5.0 in GW2, plus three DEF upgrades each worth only +0.5."""
    players: list[_Player] = []
    for player in _base_players(horizon=2):
        if player.code not in set(_INITIAL_SQUAD):
            continue
        players.append(replace(player, points=(player.points[0], 5.0)))
    for i in range(3):
        players.append(_Player(code=4000 + i, position="DEF", points=(0.0, 5.5), team_id=4000 + i))
    return _artifact(tuple(players))


def test_planner_holds_when_every_transfer_costs_an_unrepaid_hit() -> None:
    """With no free transfer available, a small upgrade cannot repay its hit, so the plan holds.

    free_per_gameweek is set to 0 so every GW2 transfer costs a 4-point hit; the DEF upgrades gain
    only +0.5 each, far short of the hit. transition_limit_per_state=1 means the pre-fix successor
    set truncated the no-transfer action away and FORCED a losing -4 churn. Post-fix the plan holds:
    zero transfers, zero hit.
    """
    artifact = _hold_artifact()
    rules = _with_search(load_squad_rules(), transition_limit_per_state=1)
    rules = rules.model_copy(
        update={
            "transfers": rules.transfers.model_copy(
                update={"free_per_gameweek_after_first_deadline": 0}
            )
        }
    )
    index, initial = _manual_solution(artifact, rules, _INITIAL_SQUAD)
    plan = plan_transfers(index, rules, initial)
    assert plan.weeks[1].transfers_in == ()
    assert plan.weeks[1].hit_points == 0


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
