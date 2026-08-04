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
    bench_policy: str = "bench points and autosub probability excluded from the objective"

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
) -> SquadSolution:
    """Solve the exact fixed-squad, rotating-XI horizon problem with CBC."""
    index = ArtifactIndex.build(artifact, rules)
    codes = index.selectable_codes()
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
    solver = pulp.PULP_CBC_CMD(msg=False, options=["randomSeed 0"])
    status_code = problem.solve(solver)
    status = str(pulp.LpStatus[status_code])
    if status != "Optimal":
        raise OptimizationError(f"initial squad solve did not reach optimality: {status}")

    # Bench points are deliberately absent from the primary objective, which otherwise leaves
    # many equally optimal squad fillers. Resolve only those primary ties by minimum price and
    # then stable code rank so repeated solves emit the same complete 15-player squad.
    primary_optimum = float(pulp.value(primary_objective))
    problem += primary_objective >= primary_optimum - 1e-8
    rank = {code: index for index, code in enumerate(codes, start=1)}
    price_scale = len(codes) * rules.squad.size + 1
    secondary_objective = pulp.lpSum(
        squad_vars[code] * (prices[code] * price_scale + rank[code]) for code in codes
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
    )
