"""Stage C Candidate V1: xG-informed trailing player goals.

Pre-registered in ``config/phase3_evaluation.yaml`` amendment 1.1 as
``xg_informed_trailing_player_goals_v1``. This is the v1.0 ``trailing_player_goal_rate_poisson``
baseline with its recent GOALS signal replaced by recent ``expected_goals`` (xG) where xG is
measured and finishing shrunk almost fully to the positional mean; where xG is unmeasured it falls
back to the EXACT v1.0 trailing-player baseline.

Invariants (shared with the v1.0 baselines):
- Player identity: stable ``code``. ``element_id`` is season-scoped and reassigned yearly.
- Strict point-in-time: training rows use ``kickoff_time < as_of`` (enforced by the harness).
- NULL ``expected_goals`` means unmeasured and is never zero-filled.

This is a FIXED closed-form estimator: there is no parameter grid and no inner walk-forward. The two
constants (``alpha``, ``finishing_keep``) are pinned in the contract; changing either fails to load.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from fpl.models.attacking_baselines import (
    GoalCountDistribution,
    PlayerHistoryRow,
    PositionalGoalRateBaseline,
    TargetRowProjection,
    poisson_pmf,
)
from fpl.types import Position

# Frozen contract constants (config/phase3_evaluation.yaml stage_c_candidate_v1). Mirrored here as
# the defaults the estimator is constructed with; the contract pins them and the runner reads them
# from the loaded config, so a config that disagrees with these fails to load before this code runs.
ALPHA: float = 5.0
FINISHING_KEEP: float = 0.05

# Path labels reported per target for development diagnostics (never a gate).
PATH_XG_INFORMED = "xg_informed"
PATH_FALLBACK_V1 = "fallback_v1"
PATH_COLD_START = "cold_start"

NAME = "xg_informed_trailing_player_goals_v1"


@dataclass(frozen=True, slots=True)
class CandidateRate:
    """The estimated goal rate for one target plus the estimator path that produced it."""

    rate: float
    path: str


class XgInformedTrailingPlayerGoalsV1:
    """Fold-local xG-informed trailing player goal-rate estimator.

    Fitted on one fold's prior history (``kickoff_time < as_of``) and predicting that fold's target
    gameweek. The positional goal mean reuses :class:`PositionalGoalRateBaseline` so the fallback
    path is bit-identical to the v1.0 ``trailing_player_goal_rate_poisson`` baseline.
    """

    name: str = NAME

    def __init__(
        self,
        *,
        alpha: float = ALPHA,
        finishing_keep: float = FINISHING_KEEP,
    ) -> None:
        self.alpha = alpha
        self.finishing_keep = finishing_keep
        self._positional = PositionalGoalRateBaseline()
        # Mean expected_goals per appearance at each position, over xG-measured prior rows only.
        # A position absent from this dict has no measured-xG prior row and so has an undefined
        # pos_x, which forces the fallback path for targets at that position.
        self._positional_xg: dict[Position, float] = {}
        self._player_history: dict[int, list[PlayerHistoryRow]] = {}

    def fit(self, history: Sequence[PlayerHistoryRow]) -> None:
        # pos_g: identical to the v1.0 positional baseline (same class, same history).
        self._positional.fit(history)

        # pos_x: fold-local positional mean xG over xG-measured rows only. NULL is unmeasured and is
        # skipped, never zero-filled -- mixing NULL-as-zero would invent xG for 2021-22 / early
        # 2022-23 and silently switch those rows onto the xG path.
        xg_sum: dict[Position, float] = {}
        xg_apps: dict[Position, int] = {}
        for row in history:
            if row.expected_goals is None:
                continue
            xg_sum[row.position] = xg_sum.get(row.position, 0.0) + row.expected_goals
            xg_apps[row.position] = xg_apps.get(row.position, 0) + 1
        self._positional_xg = {
            pos: xg_sum[pos] / xg_apps[pos] for pos in xg_apps if xg_apps[pos] > 0
        }

        # Player history grouped by code, in the chronological order `history` arrives in. The
        # harness sorts history ascending by (kickoff_time, season, fixture, code), so the last
        # window elements are the most recent -- exactly the v1.0 trailing baseline's recency order.
        self._player_history = {}
        for row in history:
            self._player_history.setdefault(row.code, []).append(row)

    def _rate(self, target: TargetRowProjection) -> CandidateRate:
        pos_g = self._positional.get_rate(target.position)
        rows = self._player_history.get(target.code, [])
        recent = rows[-5:]
        n = len(recent)

        # Cold start: no prior player-fixture row. Identical to the v1.0 trailing baseline fallback.
        if n == 0:
            return CandidateRate(pos_g, PATH_COLD_START)

        pos_x = self._positional_xg.get(target.position)
        measured = [row for row in recent if row.expected_goals is not None]

        # Fallback: xG unmeasured on every trailing row, or no positional xG mean yet. This is the
        # EXACT v1.0 trailing shrunk-goals rate (same alpha, same pos_g), so the candidate reduces
        # to the baseline bit-for-bit wherever xG is absent (all of 2021-22, early 2022-23).
        if pos_x is None or not measured:
            sum_goals = sum(row.goals for row in recent)
            rate = (sum_goals + self.alpha * pos_g) / (n + self.alpha)
            return CandidateRate(rate, PATH_FALLBACK_V1)

        # xG-informed path.
        m = len(measured)
        sum_x = 0.0
        sum_goals_measured = 0
        for row in measured:
            assert row.expected_goals is not None  # `measured` holds only xG-measured rows
            sum_x += row.expected_goals
            sum_goals_measured += row.goals
        shrunk_xg = (sum_x + self.alpha * pos_x) / (m + self.alpha)
        player_finishing = (sum_goals_measured - sum_x) / m
        positional_finishing = pos_g - pos_x
        finishing_term = (
            self.finishing_keep * player_finishing
            + (1.0 - self.finishing_keep) * positional_finishing
        )
        rate = max(0.0, shrunk_xg + finishing_term)
        return CandidateRate(rate, PATH_XG_INFORMED)

    def predict(self, target: TargetRowProjection) -> GoalCountDistribution:
        return poisson_pmf(self._rate(target).rate)

    def path_for(self, target: TargetRowProjection) -> str:
        """The estimator path taken for one target (development diagnostic, never a gate)."""
        return self._rate(target).path

    def parameters(self) -> Mapping[str, float | int | bool | str]:
        return {
            "alpha": self.alpha,
            "finishing_keep": self.finishing_keep,
        }
