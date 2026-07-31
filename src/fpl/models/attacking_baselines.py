"""Stage C attacking goals baselines frozen by `config/phase3_evaluation.yaml`.

This module implements the two pre-registered Stage C attacking goals baselines:
1. `positional_goal_rate_poisson`: Fold-local empirical mean goals per appearance
   for the target position, formatted as a Poisson count distribution.
2. `trailing_player_goal_rate_poisson`: Empirical goal rate from up to the five most
   recent prior player-fixture rows for stable `code`, shrunk to the fold-local
   positional mean rate, formatted as a Poisson count distribution.

Invariants:
- Player identity: stable `code`. `element_id` is season-scoped and reassigned yearly.
- Target record: nine safe proxy columns, label outside model-facing projection.
- Strict point-in-time: training rows use `kickoff_time < as_of`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from fpl.types import Position

# Count distribution over goals 0..10 (length 11 tuple, summing to 1.0)
type GoalCountDistribution = tuple[float, ...]

MAX_GOALS = 10
_PROBABILITY_FLOOR = 1e-12


def poisson_pmf(rate: float, max_goals: int = MAX_GOALS) -> GoalCountDistribution:
    """A Poisson distribution truncated at `max_goals`, with tail folded into the end."""
    if rate < 0:
        raise ValueError(f"rate must be non-negative, got {rate}")
    rate = max(rate, 1e-9)
    masses = []
    log_rate = math.log(rate)
    for goals in range(max_goals):
        log_p = -rate + goals * log_rate - math.lgamma(goals + 1)
        masses.append(math.exp(log_p))
    masses.append(max(0.0, 1.0 - sum(masses)))
    total = sum(masses)
    return tuple(m / total for m in masses)


@dataclass(frozen=True, slots=True)
class PlayerHistoryRow:
    season: str
    gw: int
    fixture: int
    kickoff_time: str
    code: int
    position: Position
    goals: int
    # `expected_goals` (xG) is NULL where unmeasured (all of 2021-22, GW1-15 of 2022-23). The v1.0
    # baselines ignore it; Candidate V1 reads it. Defaulted so existing positional constructions
    # (7 args) keep working.
    expected_goals: float | None = None


@dataclass(frozen=True, slots=True)
class TargetRowProjection:
    season: str
    gw: int
    fixture: int
    kickoff_time: str
    code: int
    position: Position
    team_id: int
    opponent_team_id: int
    was_home: bool


class PositionalGoalRateBaseline:
    """Baseline 1: positional_goal_rate_poisson.

    Fold-local empirical mean goals per appearance for each position.
    """

    def __init__(self, fallback_rate: float = 0.10) -> None:
        self._position_rates: dict[Position, float] = {}
        self._overall_rate: float = fallback_rate

    def fit(self, history: Sequence[PlayerHistoryRow]) -> None:
        pos_goals: dict[Position, int] = {}
        pos_apps: dict[Position, int] = {}
        total_goals = 0
        total_apps = 0

        for row in history:
            pos_goals[row.position] = pos_goals.get(row.position, 0) + row.goals
            pos_apps[row.position] = pos_apps.get(row.position, 0) + 1
            total_goals += row.goals
            total_apps += 1

        self._overall_rate = (total_goals / total_apps) if total_apps > 0 else 0.10
        self._position_rates = {
            pos: (pos_goals[pos] / pos_apps[pos])
            if pos_apps.get(pos, 0) > 0
            else self._overall_rate
            for pos in Position
        }

    def get_rate(self, position: Position) -> float:
        return self._position_rates.get(position, self._overall_rate)

    def predict(self, target: TargetRowProjection) -> GoalCountDistribution:
        rate = self.get_rate(target.position)
        return poisson_pmf(rate)


class TrailingPlayerGoalRateBaseline:
    """Baseline 2: trailing_player_goal_rate_poisson.

    Player's own recent goal rate over up to 5 prior player-fixture rows,
    shrunk toward the fold-local positional mean rate with shrinkage alpha = 5.0.
    """

    def __init__(self, alpha: float = 5.0) -> None:
        self.alpha = alpha
        self._positional_baseline = PositionalGoalRateBaseline()
        self._player_history: dict[int, list[PlayerHistoryRow]] = {}

    def fit(self, history: Sequence[PlayerHistoryRow]) -> None:
        self._positional_baseline.fit(history)
        self._player_history = {}
        # Group history by code
        for row in history:
            if row.code not in self._player_history:
                self._player_history[row.code] = []
            self._player_history[row.code].append(row)

    def predict(self, target: TargetRowProjection) -> GoalCountDistribution:
        pos_rate = self._positional_baseline.get_rate(target.position)
        player_rows = self._player_history.get(target.code, [])
        if not player_rows:
            return poisson_pmf(pos_rate)

        # Take up to 5 most recent prior rows
        recent_rows = player_rows[-5:]
        n = len(recent_rows)
        sum_goals = sum(r.goals for r in recent_rows)
        # Shrink to positional mean
        shrunk_rate = (sum_goals + self.alpha * pos_rate) / (n + self.alpha)
        return poisson_pmf(shrunk_rate)
