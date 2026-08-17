"""Exact initial squad, lineup, and captain selection from a forecast artifact."""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import product

import pulp

from fpl.artifacts.prospective_points import (
    ForecastArtifactRow,
    ProspectivePointsArtifact,
)
from fpl.optimize.rules import POSITIONS, PositionName, SquadRules

# The CBC invocation is pinned here so downstream provenance (the optimizer artifact) records the
# exact options and seed the solver actually ran under, and cannot silently drift from them. The
# ``randomSeed 0`` option fixes CBC's random seed; ``msg=False`` keeps it quiet.
CBC_SOLVER_OPTIONS: tuple[str, ...] = ("randomSeed 0",)
CBC_RANDOM_SEED = 0


class OptimizationError(RuntimeError):
    """The artifact or constraints cannot produce a valid optimal squad."""


@dataclass(frozen=True, slots=True)
class SquadMember:
    code: int
    web_name: str | None
    position: PositionName
    team_id: int
    team_code: int | None
    now_cost: int
    selected_by_percent: float | None


@dataclass(frozen=True, slots=True)
class WeekSelection:
    gw: int
    starting_xi: tuple[int, ...]
    captain: int
    vice_captain: int
    bench_goalkeeper: int
    bench_order: tuple[int, ...]
    expected_points: float
    objective_value: float


@dataclass(frozen=True, slots=True)
class SquadSolution:
    members: tuple[SquadMember, ...]
    squad_cost_tenths: int
    weeks: tuple[WeekSelection, ...]
    expected_points: float
    objective_value: float
    risk_lambda: float
    solver_status: str
    bench_policy: str = (
        "bench points and autosub probability excluded from the objective; zero-availability "
        "players rank last in the bench tie-break, and equally-priced fillers prefer the "
        "most-selected players"
    )
    min_bench_appearance: float = 0.0
    locked_codes: tuple[int, ...] = ()

    @property
    def codes(self) -> tuple[int, ...]:
        return tuple(member.code for member in self.members)


@dataclass(frozen=True, slots=True)
class ArtifactIndex:
    artifact: ProspectivePointsArtifact
    rows: dict[tuple[int, int], ForecastArtifactRow]
    first_by_code: dict[int, ForecastArtifactRow]
    gws: tuple[int, ...]

    @classmethod
    def build(cls, artifact: ProspectivePointsArtifact, rules: SquadRules) -> ArtifactIndex:
        if artifact.manifest.season != rules.season:
            raise OptimizationError(
                f"artifact season {artifact.manifest.season} != rules season {rules.season}"
            )
        rows = {(row.code, row.gw): row for row in artifact.rows}
        first_by_code: dict[int, ForecastArtifactRow] = {}
        for row in artifact.rows:
            first = first_by_code.setdefault(row.code, row)
            fields = (
                "position",
                "team_id",
                "team_code",
                "now_cost",
                "selected_by_percent",
            )
            if any(getattr(row, field) != getattr(first, field) for field in fields):
                raise OptimizationError(
                    f"player metadata changes inside artifact for code {row.code}"
                )
        gws = tuple(range(artifact.manifest.gw_from, artifact.manifest.gw_to + 1))
        if len(rows) != len(first_by_code) * len(gws):
            raise OptimizationError("artifact is not a complete player-by-gameweek population")
        return cls(artifact=artifact, rows=rows, first_by_code=first_by_code, gws=gws)

    def selectable_codes(self) -> tuple[int, ...]:
        return tuple(
            code for code, row in sorted(self.first_by_code.items()) if row.now_cost is not None
        )


def downside_deviation(row: ForecastArtifactRow) -> float:
    """Expected shortfall below the row's own raw mean, using the full distribution."""
    mean = row.expected_points
    return sum(max(mean - points, 0.0) * mass for points, mass in enumerate(row.distribution))


def row_utility(row: ForecastArtifactRow, risk_lambda: float) -> float:
    """Availability-adjusted mean less an optional distributional downside penalty."""
    if not math.isfinite(risk_lambda) or risk_lambda < 0.0:
        raise ValueError("risk_lambda must be finite and non-negative")
    downside = row.availability_multiplier * downside_deviation(row)
    return row.availability_adjusted_expected_points - risk_lambda * downside


def appearance_lower_bound(row: ForecastArtifactRow) -> float:
    """Conservative lower bound on the player appearing, from the stored distribution alone.

    A non-appearance lands entirely in the zero-points cell, so ``1 - P(0 points)`` bounds
    P(appears) from below -- a player can also appear and still score nothing, so this
    understates appearance probability, which is the safe direction for a minimum gate.
    The availability overlay multiplier is applied under the same scenario assumption the
    artifact already documents for the EV (the overlay is measured for the next gameweek).
    """
    return row.availability_multiplier * (1.0 - row.distribution[0])


def bench_appearance_satisfied(
    index: ArtifactIndex, lineup: WeekSelection, min_bench_appearance: float
) -> bool:
    """True when every outfield bench player of this lineup clears the appearance gate.

    The bench goalkeeper is exempt by design: a backup keeper plays only on an
    unforecastable starter injury or dismissal, so no meaningful threshold is attainable
    and gating it would make every squad illegal.
    """
    if min_bench_appearance <= 0.0:
        return True
    return all(
        appearance_lower_bound(index.rows[(code, lineup.gw)]) >= min_bench_appearance
        for code in lineup.bench_order
    )


def _member(index: ArtifactIndex, code: int) -> SquadMember:
    row = index.first_by_code[code]
    if row.now_cost is None:
        raise OptimizationError(f"selected code {code} has no deadline-known price")
    return SquadMember(
        code=code,
        web_name=row.web_name,
        position=row.position,
        team_id=row.team_id,
        team_code=row.team_code,
        now_cost=row.now_cost,
        selected_by_percent=row.selected_by_percent,
    )


def validate_squad(index: ArtifactIndex, rules: SquadRules, codes: tuple[int, ...]) -> None:
    if len(codes) != rules.squad.size or len(set(codes)) != len(codes):
        raise OptimizationError("squad must contain the configured number of distinct players")
    members = tuple(_member(index, code) for code in codes)
    if sum(member.now_cost for member in members) > rules.squad.budget_tenths:
        raise OptimizationError("squad exceeds the budget")
    for position in POSITIONS:
        actual = sum(member.position == position for member in members)
        if actual != rules.squad.positions[position].squad:
            raise OptimizationError(f"squad has {actual} {position}, expected configured count")
    club_counts: dict[int, int] = {}
    for member in members:
        club_counts[member.team_id] = club_counts.get(member.team_id, 0) + 1
    if any(count > rules.squad.maximum_per_club for count in club_counts.values()):
        raise OptimizationError("squad exceeds the per-club cap")


def _bench_and_vice(
    index: ArtifactIndex,
    rules: SquadRules,
    squad: tuple[int, ...],
    starters: tuple[int, ...],
    captain: int,
    gw: int,
) -> tuple[int, tuple[int, ...], int]:
    starter_set = set(starters)
    bench = [code for code in squad if code not in starter_set]
    goalkeepers = [code for code in bench if index.first_by_code[code].position == "GK"]
    outfield = [code for code in bench if index.first_by_code[code].position != "GK"]
    if (
        len(goalkeepers) != rules.lineup.goalkeeper_bench_slots
        or len(outfield) != rules.lineup.outfield_bench_slots
    ):
        raise OptimizationError(
            "lineup does not leave the configured goalkeeper and outfield substitutes"
        )
    outfield.sort(
        key=lambda code: (-index.rows[(code, gw)].availability_adjusted_expected_points, code)
    )
    vice_candidates = [code for code in starters if code != captain]
    vice = min(
        vice_candidates,
        key=lambda code: (-index.rows[(code, gw)].availability_adjusted_expected_points, code),
    )
    return goalkeepers[0], tuple(outfield), vice


def exact_lineup(
    index: ArtifactIndex,
    rules: SquadRules,
    squad: tuple[int, ...],
    gw: int,
    risk_lambda: float,
) -> WeekSelection:
    """Exact additive lineup/captain solution for a fixed legal 15-player squad."""
    validate_squad(index, rules, squad)
    by_position = {
        position: tuple(code for code in squad if index.first_by_code[code].position == position)
        for position in POSITIONS
    }
    ranges = [
        range(
            rules.squad.positions[position].minimum_starters,
            rules.squad.positions[position].maximum_starters + 1,
        )
        for position in POSITIONS
    ]
    best: tuple[float, tuple[int, ...], int] | None = None
    for counts in product(*ranges):
        if sum(counts) != rules.lineup.starters:
            continue
        starters: list[int] = []
        for position, count in zip(POSITIONS, counts, strict=True):
            ordered = sorted(
                by_position[position],
                key=lambda code: (-row_utility(index.rows[(code, gw)], risk_lambda), code),
            )
            starters.extend(ordered[:count])
        starter_tuple = tuple(sorted(starters))
        captain = min(
            starter_tuple,
            key=lambda code: (-row_utility(index.rows[(code, gw)], risk_lambda), code),
        )
        value = sum(row_utility(index.rows[(code, gw)], risk_lambda) for code in starter_tuple)
        value += (rules.lineup.captain_multiplier - 1) * row_utility(
            index.rows[(captain, gw)], risk_lambda
        )
        candidate = (value, starter_tuple, captain)
        if (
            best is None
            or candidate[0] > best[0] + 1e-12
            or (
                math.isclose(candidate[0], best[0], abs_tol=1e-12)
                and (candidate[1], candidate[2]) < (best[1], best[2])
            )
        ):
            best = candidate
    if best is None:
        raise OptimizationError("no valid starting formation exists")
    value, selected_starters, captain = best
    bench_gk, bench_order, vice = _bench_and_vice(
        index, rules, squad, selected_starters, captain, gw
    )
    expected = sum(
        index.rows[(code, gw)].availability_adjusted_expected_points for code in selected_starters
    )
    expected += (rules.lineup.captain_multiplier - 1) * index.rows[
        (captain, gw)
    ].availability_adjusted_expected_points
    return WeekSelection(
        gw=gw,
        starting_xi=selected_starters,
        captain=captain,
        vice_captain=vice,
        bench_goalkeeper=bench_gk,
        bench_order=bench_order,
        expected_points=expected,
        objective_value=value,
    )


def optimize_initial_squad(
    artifact: ProspectivePointsArtifact,
    rules: SquadRules,
    *,
    risk_lambda: float = 0.0,
    min_bench_appearance: float = 0.0,
    locked_codes: tuple[int, ...] = (),
) -> SquadSolution:
    """Solve the exact fixed-squad, rotating-XI horizon problem with CBC.

    ``min_bench_appearance`` (0.0 = disabled, the default and the historical behaviour)
    requires every OUTFIELD player benched in any planned gameweek to show an appearance
    lower bound of at least that fraction -- see :func:`appearance_lower_bound`. The bench
    goalkeeper is exempt (see :func:`bench_appearance_satisfied`).

    ``locked_codes`` are pinned into the squad: the owner's must-keep players. The optimizer
    assigns every remaining quota around them. A locked player still obeys the bench gate,
    so a locked below-threshold player must START every planned gameweek or the solve is
    infeasible -- the two policies compose rather than one silently overriding the other.
    """
    if not math.isfinite(min_bench_appearance) or not 0.0 <= min_bench_appearance <= 1.0:
        raise ValueError("min_bench_appearance must be finite and within [0, 1]")
    index = ArtifactIndex.build(artifact, rules)
    codes = index.selectable_codes()
    locked = tuple(sorted(set(locked_codes)))
    unselectable = [code for code in locked if code not in set(codes)]
    if unselectable:
        raise OptimizationError(
            f"locked codes are not selectable players in the artifact: {unselectable}"
        )
    prices = {code: _member(index, code).now_cost for code in codes}
    problem = pulp.LpProblem("stage_e_initial_squad", pulp.LpMaximize)
    squad_vars = {code: pulp.LpVariable(f"squad_{code}", cat=pulp.LpBinary) for code in codes}
    starter_vars = {
        (code, gw): pulp.LpVariable(f"start_{gw}_{code}", cat=pulp.LpBinary)
        for code in codes
        for gw in index.gws
    }
    captain_vars = {
        (code, gw): pulp.LpVariable(f"captain_{gw}_{code}", cat=pulp.LpBinary)
        for code in codes
        for gw in index.gws
    }

    problem += pulp.lpSum(squad_vars.values()) == rules.squad.size
    problem += (
        pulp.lpSum(squad_vars[code] * prices[code] for code in codes) <= rules.squad.budget_tenths
    )
    for position in POSITIONS:
        position_codes = [code for code in codes if index.first_by_code[code].position == position]
        problem += (
            pulp.lpSum(squad_vars[code] for code in position_codes)
            == rules.squad.positions[position].squad
        )
    for team_id in sorted({index.first_by_code[code].team_id for code in codes}):
        club_codes = [code for code in codes if index.first_by_code[code].team_id == team_id]
        problem += (
            pulp.lpSum(squad_vars[code] for code in club_codes) <= rules.squad.maximum_per_club
        )
    for code in locked:
        problem += squad_vars[code] == 1
    for gw in index.gws:
        problem += pulp.lpSum(starter_vars[(code, gw)] for code in codes) == rules.lineup.starters
        problem += pulp.lpSum(captain_vars[(code, gw)] for code in codes) == 1
        for code in codes:
            problem += starter_vars[(code, gw)] <= squad_vars[code]
            problem += captain_vars[(code, gw)] <= starter_vars[(code, gw)]
        for position in POSITIONS:
            position_starters = [
                starter_vars[(code, gw)]
                for code in codes
                if index.first_by_code[code].position == position
            ]
            position_rule = rules.squad.positions[position]
            problem += pulp.lpSum(position_starters) >= position_rule.minimum_starters
            problem += pulp.lpSum(position_starters) <= position_rule.maximum_starters
        # Bench appearance gate: squad_vars - starter_vars is exactly the benched indicator
        # (starter <= squad), so one linear constraint per (code, gw) enforces "benched in
        # this gameweek -> appearance lower bound >= threshold" with no extra variables.
        # Goalkeepers are exempt: the backup keeper cannot clear any meaningful threshold.
        if min_bench_appearance > 0.0:
            for code in codes:
                if index.first_by_code[code].position == "GK":
                    continue
                problem += appearance_lower_bound(
                    index.rows[(code, gw)]
                ) >= min_bench_appearance * (squad_vars[code] - starter_vars[(code, gw)])

    primary_objective = pulp.lpSum(
        row_utility(index.rows[(code, gw)], risk_lambda)
        * (
            starter_vars[(code, gw)]
            + (rules.lineup.captain_multiplier - 1) * captain_vars[(code, gw)]
        )
        for code in codes
        for gw in index.gws
    )
    problem += primary_objective
    # CBC's default is a deterministic single-process search. Passing ``threads=1`` activates
    # its threaded branch mode and deadlocks this bundled Windows build on the five-GW model.
    solver = pulp.PULP_CBC_CMD(msg=False, options=list(CBC_SOLVER_OPTIONS))
    status_code = problem.solve(solver)
    status = str(pulp.LpStatus[status_code])
    if status != "Optimal":
        hints: list[str] = []
        if status == "Infeasible" and min_bench_appearance > 0.0:
            hints.append(
                f"no legal squad satisfies min_bench_appearance={min_bench_appearance} -- "
                "lower the threshold"
            )
        if status == "Infeasible" and locked:
            hints.append(
                f"the locked players {locked} cannot all be kept in a legal squad "
                "(position quotas, club cap, budget, or the bench gate)"
            )
        hint = ("; " + "; ".join(hints)) if hints else ""
        raise OptimizationError(f"initial squad solve did not reach optimality: {status}{hint}")

    # Bench points are deliberately absent from the primary objective, which otherwise leaves
    # many equally optimal squad fillers. Resolve only those primary ties by minimum price and
    # then stable code rank so repeated solves emit the same complete 15-player squad -- with
    # one hard override: a player the availability overlay rules OUT (multiplier 0 in any
    # planned gameweek, e.g. injured with chance 0) ranks behind every available filler at any
    # price. Without this the cheapest zero-availability player is the tie-break's favourite
    # bench filler, and the plan suggests an injured player who can never come on.
    primary_optimum = float(pulp.value(primary_objective))
    problem += primary_objective >= primary_optimum - 1e-8
    # Owner rule (2026-08-17): among EQUALLY-PRICED fillers the tie-break prefers the
    # MOST-SELECTED players (deadline bootstrap ownership) -- crowd vetting that a cheap pick
    # is a real Premier League rotation option, not a never-playing squad player. Price still
    # dominates (a cheaper unpopular filler always beats a costlier popular one), because
    # saving budget for the starting XI is the tie-break's purpose. Unmeasured ownership
    # (null) carries no preference signal and sorts with 0% at its price -- a sort choice,
    # not a measured statistic; the stable code rank still breaks exact ties so repeated
    # solves stay reproducible.
    rank = {
        code: position
        for position, code in enumerate(
            sorted(
                codes,
                key=lambda item: (
                    prices[item],
                    -(index.first_by_code[item].selected_by_percent or 0.0),
                    item,
                ),
            ),
            start=1,
        )
    }
    price_scale = len(codes) * rules.squad.size + 1
    zero_availability = {
        code: any(index.rows[(code, gw)].availability_multiplier <= 0.0 for gw in index.gws)
        for code in codes
    }
    unavailable_penalty = (max(prices.values(), default=0) + 1) * price_scale + len(codes) + 1
    secondary_objective = pulp.lpSum(
        squad_vars[code]
        * (
            prices[code] * price_scale
            + rank[code]
            + (unavailable_penalty if zero_availability[code] else 0)
        )
        for code in codes
    )
    problem.sense = pulp.LpMinimize
    problem.setObjective(secondary_objective)
    tie_status_code = problem.solve(solver)
    tie_status = str(pulp.LpStatus[tie_status_code])
    if tie_status != "Optimal":
        raise OptimizationError(
            f"deterministic squad tie-break did not reach optimality: {tie_status}"
        )

    selected = tuple(sorted(code for code in codes if pulp.value(squad_vars[code]) > 0.5))
    validate_squad(index, rules, selected)
    weeks: list[WeekSelection] = []
    for gw in index.gws:
        starters = tuple(
            sorted(code for code in selected if pulp.value(starter_vars[(code, gw)]) > 0.5)
        )
        captain = next(code for code in selected if pulp.value(captain_vars[(code, gw)]) > 0.5)
        bench_gk, bench_order, vice = _bench_and_vice(index, rules, selected, starters, captain, gw)
        expected = sum(
            index.rows[(code, gw)].availability_adjusted_expected_points for code in starters
        )
        expected += (rules.lineup.captain_multiplier - 1) * index.rows[
            (captain, gw)
        ].availability_adjusted_expected_points
        objective = sum(row_utility(index.rows[(code, gw)], risk_lambda) for code in starters)
        objective += (rules.lineup.captain_multiplier - 1) * row_utility(
            index.rows[(captain, gw)], risk_lambda
        )
        weeks.append(
            WeekSelection(
                gw=gw,
                starting_xi=starters,
                captain=captain,
                vice_captain=vice,
                bench_goalkeeper=bench_gk,
                bench_order=bench_order,
                expected_points=expected,
                objective_value=objective,
            )
        )
    members = tuple(_member(index, code) for code in selected)
    return SquadSolution(
        members=members,
        squad_cost_tenths=sum(member.now_cost for member in members),
        weeks=tuple(weeks),
        expected_points=sum(week.expected_points for week in weeks),
        objective_value=sum(week.objective_value for week in weeks),
        risk_lambda=risk_lambda,
        solver_status=status,
        min_bench_appearance=min_bench_appearance,
        locked_codes=locked,
    )
