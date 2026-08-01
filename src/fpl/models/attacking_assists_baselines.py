"""Stage C attacking assists baselines frozen by `config/phase3_stage_c_assists_evaluation.yaml`.

A clean mirror of ``fpl.models.attacking_baselines`` (the goals component) for the assists
label. The label is FPL assists (the FPL definition, not Opta); the grain is
``(season, code, fixture)``; the distribution is a Poisson count over assists 0..10. This
module implements the two pre-registered Stage C attacking assists baselines:

1. ``positional_assist_rate_poisson``: Fold-local empirical mean assists per appearance for the
   target position, formatted as a Poisson count distribution.
2. ``trailing_player_assist_rate_poisson``: Empirical assist rate from up to the five most recent
   prior player-fixture rows for stable ``code``, shrunk to the fold-local positional mean rate,
   formatted as a Poisson count distribution.

Invariants (shared with the goals baselines):
- Player identity: stable ``code``. ``element_id`` is season-scoped and reassigned yearly.
- Target record: nine safe proxy columns, label outside model-facing projection.
- Strict point-in-time: training rows use ``kickoff_time < as_of`` (enforced by the harness).
- NULL ``expected_assists`` / ``creativity`` means unmeasured and is never zero-filled; the v1.0
  baselines ignore them and Candidate V1 reads them.

The Poisson machinery (``poisson_pmf``, which truncates at the goals module's ``MAX_GOALS = 10``)
and the label-free ``TargetRowProjection`` are reused unchanged from the goals baselines -- the
count-distribution math is identical for goals and assists.
"""

from __future__ import annotations

from collections.abc import Sequence

from fpl.models.attacking_baselines import (
    GoalCountDistribution,
    TargetRowProjection,
    poisson_pmf,
)
from fpl.types import Position


class AssistHistoryRow:
    """One prior player-fixture appearance for the assists baselines / Candidate V1.

    ``expected_assists`` (xA) and ``creativity`` are NULL where unmeasured. xA shares the goals-xG
    measured-coverage profile (NULL in 2021-22, partial in 2022-23, 100% in 2023-24+);
    ``creativity`` (the FPL-native creative index) is measured 100% every season and is the xA
    fallback. ``minutes`` is carried so Candidate V1 can restrict its per-appearance signal to
    APPEARED rows (minutes > 0, R6); the v1.0 baselines ignore it. ``expected_assists`` /
    ``creativity`` default to None so the v1.0 baseline construction keeps working.
    """

    __slots__ = (
        "assists",
        "code",
        "creativity",
        "expected_assists",
        "fixture",
        "gw",
        "kickoff_time",
        "minutes",
        "position",
        "season",
    )

    def __init__(
        self,
        season: str,
        gw: int,
        fixture: int,
        kickoff_time: str,
        code: int,
        position: Position,
        assists: int,
        minutes: int,
        expected_assists: float | None = None,
        creativity: float | None = None,
    ) -> None:
        self.season = season
        self.gw = gw
        self.fixture = fixture
        self.kickoff_time = kickoff_time
        self.code = code
        self.position = position
        self.assists = assists
        self.minutes = minutes
        self.expected_assists = expected_assists
        self.creativity = creativity


class PositionalAssistRateBaseline:
    """Baseline 1: positional_assist_rate_poisson.

    Fold-local empirical mean assists per appearance for each position.
    """

    def __init__(self, fallback_rate: float = 0.03) -> None:
        self._position_rates: dict[Position, float] = {}
        self._overall_rate: float = fallback_rate

    def fit(self, history: Sequence[AssistHistoryRow]) -> None:
        pos_assists: dict[Position, int] = {}
        pos_apps: dict[Position, int] = {}
        total_assists = 0
        total_apps = 0

        for row in history:
            pos_assists[row.position] = pos_assists.get(row.position, 0) + row.assists
            pos_apps[row.position] = pos_apps.get(row.position, 0) + 1
            total_assists += row.assists
            total_apps += 1

        self._overall_rate = (total_assists / total_apps) if total_apps > 0 else 0.03
        self._position_rates = {
            pos: (pos_assists[pos] / pos_apps[pos])
            if pos_apps.get(pos, 0) > 0
            else self._overall_rate
            for pos in Position
        }

    def get_rate(self, position: Position) -> float:
        return self._position_rates.get(position, self._overall_rate)

    def predict(self, target: TargetRowProjection) -> GoalCountDistribution:
        rate = self.get_rate(target.position)
        return poisson_pmf(rate)


class TrailingPlayerAssistRateBaseline:
    """Baseline 2: trailing_player_assist_rate_poisson.

    Player's own recent assist rate over up to 5 prior player-fixture rows, shrunk toward the
    fold-local positional mean rate with shrinkage alpha = 5.0 (mirrors the goals trailing
    baseline exactly).
    """

    def __init__(self, alpha: float = 5.0) -> None:
        self.alpha = alpha
        self._positional_baseline = PositionalAssistRateBaseline()
        self._player_history: dict[int, list[AssistHistoryRow]] = {}

    def fit(self, history: Sequence[AssistHistoryRow]) -> None:
        self._positional_baseline.fit(history)
        self._player_history = {}
        for row in history:
            self._player_history.setdefault(row.code, []).append(row)

    def predict(self, target: TargetRowProjection) -> GoalCountDistribution:
        pos_rate = self._positional_baseline.get_rate(target.position)
        player_rows = self._player_history.get(target.code, [])
        if not player_rows:
            return poisson_pmf(pos_rate)

        recent_rows = player_rows[-5:]
        n = len(recent_rows)
        sum_assists = sum(r.assists for r in recent_rows)
        shrunk_rate = (sum_assists + self.alpha * pos_rate) / (n + self.alpha)
        return poisson_pmf(shrunk_rate)
