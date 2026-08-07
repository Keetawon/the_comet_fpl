"""Deterministic bounded dynamic programme for gameweek transfer planning."""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations, product

from fpl.optimize.rules import POSITIONS, SquadRules
from fpl.optimize.squad import (
    ArtifactIndex,
    OptimizationError,
    SquadSolution,
    WeekSelection,
    exact_lineup,
    row_utility,
    validate_squad,
)


@dataclass(frozen=True, slots=True)
class TransferWeek:
    gw: int
    squad: tuple[int, ...]
    transfers_in: tuple[int, ...]
    transfers_out: tuple[int, ...]
    free_transfers_before: int
    free_transfers_after: int
    hit_points: int
    lineup: WeekSelection


@dataclass(frozen=True, slots=True)
class TransferPlan:
    weeks: tuple[TransferWeek, ...]
    expected_points_before_hits: float
    hit_points: int
    expected_points_after_hits: float
    objective_value_after_hits: float
    risk_lambda: float
    candidate_pool: tuple[int, ...]
    search_method: str = "bounded deterministic dynamic programme with beam pruning"
    optimality_scope: str = (
        "exact lineups within visited states; transfer path is not globally exact outside the "
        "configured candidate pool, transfer-depth, transition, and beam bounds"
    )


@dataclass(frozen=True, slots=True)
class _Path:
    weeks: tuple[TransferWeek, ...]
    squad: tuple[int, ...]
    banked_free_transfers: int
    expected_points: float
    hit_points: int
    objective_value: float

    @property
    def ranking_key(self) -> tuple[float, int, tuple[tuple[int, ...], ...]]:
        return (
            -self.objective_value,
            self.hit_points,
            tuple(week.squad for week in self.weeks),
        )


def _candidate_pool(
    index: ArtifactIndex,
    rules: SquadRules,
    initial_squad: tuple[int, ...],
    risk_lambda: float,
) -> tuple[int, ...]:
    pool = set(initial_squad)
    for position in POSITIONS:
        eligible = [
            code
            for code in index.selectable_codes()
            if index.first_by_code[code].position == position
        ]
        eligible.sort(
            key=lambda code: (
                -sum(row_utility(index.rows[(code, gw)], risk_lambda) for gw in index.gws),
                code,
            )
        )
        pool.update(eligible[: rules.search.candidate_pool_per_position])
    return tuple(sorted(pool))


def _successor_squads(
    index: ArtifactIndex,
    rules: SquadRules,
    squad: tuple[int, ...],
    candidate_pool: tuple[int, ...],
    gw: int,
    risk_lambda: float,
) -> tuple[tuple[int, ...], ...]:
    """Return the strongest legal same-position swaps within the configured bound."""
    current = set(squad)
    candidates_by_position = {
        position: tuple(
            code
            for code in candidate_pool
            if code not in current and index.first_by_code[code].position == position
        )
        for position in POSITIONS
    }
    scored: dict[tuple[int, ...], float] = {squad: 0.0}
    max_depth = min(rules.search.maximum_planned_transfers_per_gameweek, len(squad))
    for depth in range(1, max_depth + 1):
        for outgoing in combinations(squad, depth):
            incoming_options = [
                candidates_by_position[index.first_by_code[code].position] for code in outgoing
            ]
            if any(not options for options in incoming_options):
                continue
            for incoming in product(*incoming_options):
                if len(set(incoming)) != depth:
                    continue
                proposal = tuple(sorted((current - set(outgoing)) | set(incoming)))
                if proposal in scored:
                    continue
                try:
                    validate_squad(index, rules, proposal)
                except OptimizationError:  # proposal violates budget or club constraints
                    continue
                improvement = sum(
                    row_utility(index.rows[(code, gw)], risk_lambda) for code in incoming
                ) - sum(row_utility(index.rows[(code, gw)], risk_lambda) for code in outgoing)
                scored[proposal] = improvement
    ordered = sorted(scored, key=lambda item: (-scored[item], item))
    limit = rules.search.transition_limit_per_state
    kept = ordered[:limit]
    # Reserve the no-transfer action. The current squad is seeded at improvement 0.0, so every
    # positive-improvement swap ranks above it; with a full candidate pool there are far more than
    # `limit` such swaps and truncation drops the hold action, forcing a transfer every gameweek.
    # Holding must always be representable -- it is the only way to bank a free transfer or avoid a
    # points hit. Appending is consistent with the (-improvement, item) ordering because hold only
    # misses the cut when every retained proposal has strictly positive improvement, so 0.0 sorts
    # after all of them.
    if squad not in kept:
        kept.append(squad)
    return tuple(kept)


def _transfer_delta(
    old_squad: tuple[int, ...], new_squad: tuple[int, ...]
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    old = set(old_squad)
    new = set(new_squad)
    return tuple(sorted(new - old)), tuple(sorted(old - new))


def plan_transfers(
    artifact_index: ArtifactIndex,
    rules: SquadRules,
    initial_solution: SquadSolution,
    *,
    risk_lambda: float = 0.0,
) -> TransferPlan:
    """Plan transfers over the artifact horizon with bounded deterministic DP/beam search."""
    if not math.isfinite(risk_lambda) or risk_lambda < 0.0:
        raise ValueError("risk_lambda must be finite and non-negative")
    initial_squad = tuple(sorted(initial_solution.codes))
    validate_squad(artifact_index, rules, initial_squad)
    candidate_pool = _candidate_pool(artifact_index, rules, initial_squad, risk_lambda)
    first_gw = artifact_index.gws[0]
    first_lineup = exact_lineup(artifact_index, rules, initial_squad, first_gw, risk_lambda)
    first_week = TransferWeek(
        gw=first_gw,
        squad=initial_squad,
        transfers_in=(),
        transfers_out=(),
        free_transfers_before=0,
        free_transfers_after=0,
        hit_points=0,
        lineup=first_lineup,
    )
    states: dict[tuple[tuple[int, ...], int], _Path] = {
        (initial_squad, 0): _Path(
            weeks=(first_week,),
            squad=initial_squad,
            banked_free_transfers=0,
            expected_points=first_lineup.expected_points,
            hit_points=0,
            objective_value=first_lineup.objective_value,
        )
    }

    for gw in artifact_index.gws[1:]:
        next_states: dict[tuple[tuple[int, ...], int], _Path] = {}
        for path in sorted(states.values(), key=lambda item: item.ranking_key):
            available = min(
                rules.transfers.free_transfer_bank_cap,
                path.banked_free_transfers + rules.transfers.free_per_gameweek_after_first_deadline,
            )
            successors = _successor_squads(
                artifact_index,
                rules,
                path.squad,
                candidate_pool,
                gw,
                risk_lambda,
            )
            for squad in successors:
                incoming, outgoing = _transfer_delta(path.squad, squad)
                transfers = len(incoming)
                hit = max(0, transfers - available) * rules.transfers.hit_cost_points
                banked = max(0, available - transfers)
                lineup = exact_lineup(artifact_index, rules, squad, gw, risk_lambda)
                week = TransferWeek(
                    gw=gw,
                    squad=squad,
                    transfers_in=incoming,
                    transfers_out=outgoing,
                    free_transfers_before=available,
                    free_transfers_after=banked,
                    hit_points=hit,
                    lineup=lineup,
                )
                candidate = _Path(
                    weeks=(*path.weeks, week),
                    squad=squad,
                    banked_free_transfers=banked,
                    expected_points=path.expected_points + lineup.expected_points,
                    hit_points=path.hit_points + hit,
                    objective_value=path.objective_value + lineup.objective_value - hit,
                )
                key = (squad, banked)
                incumbent = next_states.get(key)
                if incumbent is None or candidate.ranking_key < incumbent.ranking_key:
                    next_states[key] = candidate
        states = {
            (path.squad, path.banked_free_transfers): path
            for path in sorted(next_states.values(), key=lambda item: item.ranking_key)[
                : rules.search.beam_width
            ]
        }
        if not states:
            raise RuntimeError(f"bounded transfer search found no legal state for GW{gw}")

    best = min(states.values(), key=lambda item: item.ranking_key)
    return TransferPlan(
        weeks=best.weeks,
        expected_points_before_hits=best.expected_points,
        hit_points=best.hit_points,
        expected_points_after_hits=best.expected_points - best.hit_points,
        objective_value_after_hits=best.objective_value,
        risk_lambda=risk_lambda,
        candidate_pool=candidate_pool,
    )
