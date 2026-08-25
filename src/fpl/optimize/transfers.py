"""Deterministic bounded dynamic programme for gameweek transfer planning."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from itertools import combinations, product

from fpl.optimize.rules import POSITIONS, SquadRules
from fpl.optimize.squad import (
    ArtifactIndex,
    OptimizationError,
    SquadSolution,
    WeekSelection,
    bench_appearance_satisfied,
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
    bank_before_tenths: int | None = None
    bank_after_tenths: int | None = None


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


@dataclass(frozen=True, slots=True)
class OwnedPlayerFinancials:
    """The frozen purchase/selling basis for one player already owned by a manager."""

    code: int
    purchase_price_tenths: int
    selling_price_tenths: int

    def __post_init__(self) -> None:
        if self.code <= 0:
            raise ValueError("owned player code must be positive")
        if self.purchase_price_tenths < 0 or self.selling_price_tenths < 0:
            raise ValueError("owned player prices must be non-negative")


@dataclass(frozen=True, slots=True)
class ManagerFinancialState:
    """Cash, remaining free transfers, and per-player sale bases at the planning deadline."""

    bank_tenths: int
    free_transfers_available: int
    owned_players: tuple[OwnedPlayerFinancials, ...]

    def __post_init__(self) -> None:
        if self.bank_tenths < 0:
            raise ValueError("manager bank_tenths must be non-negative")
        if self.free_transfers_available < 0:
            raise ValueError("manager free_transfers_available must be non-negative")
        codes = tuple(player.code for player in self.owned_players)
        if len(set(codes)) != len(codes):
            raise ValueError("manager owned player financials must contain distinct codes")


@dataclass(frozen=True, slots=True)
class _ManagerPath:
    weeks: tuple[TransferWeek, ...]
    squad: tuple[int, ...]
    banked_free_transfers: int
    bank_tenths: int
    sale_prices: tuple[tuple[int, int], ...]
    expected_points: float
    hit_points: int
    objective_value: float

    @property
    def ranking_key(
        self,
    ) -> tuple[
        float,
        int,
        int,
        tuple[tuple[int, ...], ...],
        tuple[tuple[int, int], ...],
    ]:
        return (
            -self.objective_value,
            self.hit_points,
            -self.bank_tenths,
            tuple(week.squad for week in self.weeks),
            self.sale_prices,
        )


def _candidate_pool(
    index: ArtifactIndex,
    rules: SquadRules,
    initial_squad: tuple[int, ...],
    risk_lambda: float,
    excluded_codes: frozenset[int] = frozenset(),
    *,
    allow_initial_excluded: bool = False,
) -> tuple[int, ...]:
    if excluded_codes.intersection(initial_squad) and not allow_initial_excluded:
        raise OptimizationError("the initial squad contains an excluded player")
    pool = set(initial_squad)
    for position in POSITIONS:
        eligible = [
            code
            for code in index.selectable_codes()
            if code not in excluded_codes and index.first_by_code[code].position == position
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
    locked_codes: frozenset[int] = frozenset(),
    excluded_codes: frozenset[int] = frozenset(),
    *,
    enforce_budget: bool = True,
    proposal_is_eligible: Callable[[tuple[int, ...]], bool] | None = None,
) -> tuple[tuple[int, ...], ...]:
    """Return the strongest legal same-position swaps within the configured bound.

    Locked players never appear in an outgoing swap, so every successor keeps them.
    """
    current = set(squad)
    candidates_by_position = {
        position: tuple(
            code
            for code in candidate_pool
            if code not in current
            and code not in excluded_codes
            and index.first_by_code[code].position == position
        )
        for position in POSITIONS
    }
    scored: dict[tuple[int, ...], float] = {squad: 0.0}
    max_depth = min(rules.search.maximum_planned_transfers_per_gameweek, len(squad))
    for depth in range(1, max_depth + 1):
        for outgoing in combinations(squad, depth):
            if locked_codes.intersection(outgoing):
                continue
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
                    validate_squad(index, rules, proposal, enforce_budget=enforce_budget)
                except OptimizationError:  # proposal violates budget or club constraints
                    continue
                if proposal_is_eligible is not None and not proposal_is_eligible(proposal):
                    continue
                improvement = sum(
                    row_utility(index.rows[(code, gw)], risk_lambda) for code in incoming
                ) - sum(row_utility(index.rows[(code, gw)], risk_lambda) for code in outgoing)
                scored[proposal] = improvement
    ordered = sorted(scored, key=lambda item: (-scored[item], item))
    kept = list(ordered[: rules.search.transition_limit_per_state])
    # Always reserve the no-transfer (hold) action. It is seeded at improvement 0.0, so it sorts
    # below every positive-improvement swap and is truncated away whenever more than
    # transition_limit_per_state proposals improve -- which is routine for a 15-man squad against a
    # large pool. Holding is frequently optimal (bank a free transfer, avoid a -4 hit), so the
    # search must always be able to represent it. The successor set may now be limit + 1; the single
    # caller iterates it and a returned current squad maps to a zero-transfer, zero-hit week.
    if squad not in kept:
        kept.append(squad)
    return tuple(kept)


def _transfer_delta(
    old_squad: tuple[int, ...], new_squad: tuple[int, ...]
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    old = set(old_squad)
    new = set(new_squad)
    return tuple(sorted(new - old)), tuple(sorted(old - new))


def _manager_proposal_is_affordable(
    index: ArtifactIndex,
    old_squad: tuple[int, ...],
    bank_tenths: int,
    sale_price_rows: tuple[tuple[int, int], ...],
    proposal: tuple[int, ...],
) -> bool:
    incoming, outgoing = _transfer_delta(old_squad, proposal)
    sale_prices = dict(sale_price_rows)
    proceeds = sum(sale_prices[code] for code in outgoing)
    purchases = 0
    for code in incoming:
        now_cost = index.first_by_code[code].now_cost
        if now_cost is None:
            return False
        purchases += now_cost
    return bank_tenths + proceeds >= purchases


def plan_transfers(
    artifact_index: ArtifactIndex,
    rules: SquadRules,
    initial_solution: SquadSolution,
    *,
    risk_lambda: float = 0.0,
    min_bench_appearance: float = 0.0,
    locked_codes: tuple[int, ...] = (),
    excluded_codes: tuple[int, ...] = (),
    initial_banked_free_transfers: int = 0,
    manager_financial_state: ManagerFinancialState | None = None,
) -> TransferPlan:
    """Plan transfers over the artifact horizon with bounded deterministic DP/beam search.

    ``min_bench_appearance`` (0.0 = disabled, the default) rejects any successor squad whose
    lineup for the planned gameweek benches a gated player below the appearance gate -- the
    same gate :func:`fpl.optimize.squad.optimize_initial_squad` applies to squad selection,
    kept hold of across the transfer path so a later transfer cannot reintroduce a bench
    player who never plays. Locked players share the goalkeeper's exemption (owner rule,
    2026-08-18): the must-keep instruction outranks the rotation heuristic. ``locked_codes``
    are never transferred out. `excluded_codes` are absent from the initial squad, transfer
    candidate pool, and every successor squad. For a manager's existing squad (whose season has
    already
    burned or banked transfers), ``initial_banked_free_transfers`` seeds the free-transfer
    state; 0 is the fresh-season start the initial-squad path always uses.
    """
    if not math.isfinite(risk_lambda) or risk_lambda < 0.0:
        raise ValueError("risk_lambda must be finite and non-negative")
    if not math.isfinite(min_bench_appearance) or not 0.0 <= min_bench_appearance <= 1.0:
        raise ValueError("min_bench_appearance must be finite and within [0, 1]")
    if not 0 <= initial_banked_free_transfers <= rules.transfers.free_transfer_bank_cap:
        raise ValueError("initial_banked_free_transfers must be within [0, free_transfer_bank_cap]")
    if manager_financial_state is not None and initial_banked_free_transfers != 0:
        raise ValueError(
            "initial_banked_free_transfers and manager_financial_state are mutually exclusive"
        )
    locked = frozenset(locked_codes)
    excluded = frozenset(excluded_codes)
    overlap = sorted(locked.intersection(excluded))
    if overlap:
        raise OptimizationError("players cannot be both locked and excluded")
    initial_squad = tuple(sorted(initial_solution.codes))
    if not locked <= set(initial_squad):
        raise OptimizationError(
            f"locked codes are not in the initial squad: {sorted(locked - set(initial_squad))}"
        )
    if manager_financial_state is None and excluded.intersection(initial_squad):
        raise OptimizationError("excluded codes are in the initial squad")
    selectable = set(artifact_index.selectable_codes())
    unselectable = sorted(excluded - selectable)
    if unselectable:
        raise OptimizationError(
            f"excluded codes are not selectable players in the artifact: {unselectable}"
        )
    if manager_financial_state is not None:
        return _plan_manager_transfers(
            artifact_index,
            rules,
            initial_solution,
            manager_financial_state,
            risk_lambda=risk_lambda,
            min_bench_appearance=min_bench_appearance,
            locked_codes=locked,
            excluded_codes=excluded,
        )
    validate_squad(artifact_index, rules, initial_squad)
    candidate_pool = _candidate_pool(
        artifact_index, rules, initial_squad, risk_lambda, excluded_codes=excluded
    )
    first_gw = artifact_index.gws[0]
    first_lineup = exact_lineup(artifact_index, rules, initial_squad, first_gw, risk_lambda)
    if not bench_appearance_satisfied(
        artifact_index, first_lineup, min_bench_appearance, locked_codes=locked
    ):
        raise OptimizationError(
            "initial squad lineup violates min_bench_appearance before transfer planning"
        )
    first_week = TransferWeek(
        gw=first_gw,
        squad=initial_squad,
        transfers_in=(),
        transfers_out=(),
        free_transfers_before=initial_banked_free_transfers,
        free_transfers_after=initial_banked_free_transfers,
        hit_points=0,
        lineup=first_lineup,
    )
    states: dict[tuple[tuple[int, ...], int], _Path] = {
        (initial_squad, initial_banked_free_transfers): _Path(
            weeks=(first_week,),
            squad=initial_squad,
            banked_free_transfers=initial_banked_free_transfers,
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
                locked_codes=locked,
            )
            for squad in successors:
                incoming, outgoing = _transfer_delta(path.squad, squad)
                transfers = len(incoming)
                hit = max(0, transfers - available) * rules.transfers.hit_cost_points
                banked = max(0, available - transfers)
                lineup = exact_lineup(artifact_index, rules, squad, gw, risk_lambda)
                if not bench_appearance_satisfied(
                    artifact_index, lineup, min_bench_appearance, locked_codes=locked
                ):
                    continue
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


def _plan_manager_transfers(
    artifact_index: ArtifactIndex,
    rules: SquadRules,
    initial_solution: SquadSolution,
    financials: ManagerFinancialState,
    *,
    risk_lambda: float,
    min_bench_appearance: float,
    locked_codes: frozenset[int],
    excluded_codes: frozenset[int],
) -> TransferPlan:
    """Plan every forecast week from an imported squad using FPL cash/selling-value accounting."""
    if financials.free_transfers_available > rules.transfers.free_transfer_bank_cap:
        raise ValueError(
            "manager free_transfers_available exceeds the configured free-transfer bank cap"
        )
    initial_squad = tuple(sorted(initial_solution.codes))
    validate_squad(artifact_index, rules, initial_squad, enforce_budget=False)
    owned_by_code = {player.code: player for player in financials.owned_players}
    if set(owned_by_code) != set(initial_squad):
        missing = sorted(set(initial_squad) - set(owned_by_code))
        extra = sorted(set(owned_by_code) - set(initial_squad))
        raise OptimizationError(
            "manager financial records must exactly cover the imported squad "
            f"(missing={missing}, extra={extra})"
        )
    for code, player in owned_by_code.items():
        now_cost = artifact_index.first_by_code[code].now_cost
        if now_cost is None:
            raise OptimizationError(f"owned code {code} has no deadline-known price")
        if player.selling_price_tenths > now_cost:
            raise OptimizationError(
                f"owned code {code} selling price exceeds its frozen current price"
            )

    candidate_pool = _candidate_pool(
        artifact_index,
        rules,
        initial_squad,
        risk_lambda,
        excluded_codes=excluded_codes,
        allow_initial_excluded=True,
    )
    initial_sale_prices = tuple(
        sorted((code, player.selling_price_tenths) for code, player in owned_by_code.items())
    )
    states: dict[tuple[tuple[int, ...], int, int, tuple[tuple[int, int], ...]], _ManagerPath] = {
        (
            initial_squad,
            financials.free_transfers_available,
            financials.bank_tenths,
            initial_sale_prices,
        ): _ManagerPath(
            weeks=(),
            squad=initial_squad,
            banked_free_transfers=financials.free_transfers_available,
            bank_tenths=financials.bank_tenths,
            sale_prices=initial_sale_prices,
            expected_points=0.0,
            hit_points=0,
            objective_value=0.0,
        )
    }

    for offset, gw in enumerate(artifact_index.gws):
        next_states: dict[
            tuple[tuple[int, ...], int, int, tuple[tuple[int, int], ...]], _ManagerPath
        ] = {}
        for path in sorted(states.values(), key=lambda item: item.ranking_key):
            available = (
                path.banked_free_transfers
                if offset == 0
                else min(
                    rules.transfers.free_transfer_bank_cap,
                    path.banked_free_transfers
                    + rules.transfers.free_per_gameweek_after_first_deadline,
                )
            )
            path_sale_prices = dict(path.sale_prices)
            successors = _successor_squads(
                artifact_index,
                rules,
                path.squad,
                candidate_pool,
                gw,
                risk_lambda,
                locked_codes=locked_codes,
                excluded_codes=excluded_codes,
                enforce_budget=False,
                proposal_is_eligible=partial(
                    _manager_proposal_is_affordable,
                    artifact_index,
                    path.squad,
                    path.bank_tenths,
                    path.sale_prices,
                ),
            )
            for squad in successors:
                # Excluding an owned player means "sell at the first actionable deadline".
                # Non-owned exclusions are already absent and can never enter the pool.
                if excluded_codes.intersection(squad):
                    continue
                incoming, outgoing = _transfer_delta(path.squad, squad)
                transfers = len(incoming)
                sale_prices = path_sale_prices.copy()
                bank_after = path.bank_tenths + sum(sale_prices[code] for code in outgoing)
                incoming_cost = 0
                for code in incoming:
                    now_cost = artifact_index.first_by_code[code].now_cost
                    if now_cost is None:
                        raise OptimizationError(
                            f"transfer target {code} has no deadline-known price"
                        )
                    incoming_cost += now_cost
                bank_after -= incoming_cost
                if bank_after < 0:
                    continue
                for code in outgoing:
                    del sale_prices[code]
                for code in incoming:
                    now_cost = artifact_index.first_by_code[code].now_cost
                    if now_cost is None:
                        raise AssertionError("incoming price was checked above")
                    # Future prices are frozen, so a newly bought player can later be sold for
                    # exactly this purchase/current price in the scenario path.
                    sale_prices[code] = now_cost
                sale_price_tuple = tuple(sorted(sale_prices.items()))
                hit = max(0, transfers - available) * rules.transfers.hit_cost_points
                banked = max(0, available - transfers)
                lineup = exact_lineup(
                    artifact_index,
                    rules,
                    squad,
                    gw,
                    risk_lambda,
                    enforce_budget=False,
                )
                if not bench_appearance_satisfied(
                    artifact_index,
                    lineup,
                    min_bench_appearance,
                    locked_codes=locked_codes,
                ):
                    continue
                week = TransferWeek(
                    gw=gw,
                    squad=squad,
                    transfers_in=incoming,
                    transfers_out=outgoing,
                    free_transfers_before=available,
                    free_transfers_after=banked,
                    hit_points=hit,
                    lineup=lineup,
                    bank_before_tenths=path.bank_tenths,
                    bank_after_tenths=bank_after,
                )
                candidate = _ManagerPath(
                    weeks=(*path.weeks, week),
                    squad=squad,
                    banked_free_transfers=banked,
                    bank_tenths=bank_after,
                    sale_prices=sale_price_tuple,
                    expected_points=path.expected_points + lineup.expected_points,
                    hit_points=path.hit_points + hit,
                    objective_value=path.objective_value + lineup.objective_value - hit,
                )
                key = (squad, banked, bank_after, sale_price_tuple)
                incumbent = next_states.get(key)
                if incumbent is None or candidate.ranking_key < incumbent.ranking_key:
                    next_states[key] = candidate
        states = {
            (
                path.squad,
                path.banked_free_transfers,
                path.bank_tenths,
                path.sale_prices,
            ): path
            for path in sorted(next_states.values(), key=lambda item: item.ranking_key)[
                : rules.search.beam_width
            ]
        }
        if not states:
            detail = (
                " after forcing owned exclusions out"
                if excluded_codes.intersection(initial_squad)
                else ""
            )
            raise RuntimeError(
                "bounded manager transfer search found no legal affordable state "
                f"for GW{gw}{detail}"
            )

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
