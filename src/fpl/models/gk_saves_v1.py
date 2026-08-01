"""Stage D v2 component: goalkeeper saves, derived from the team-conceded rate.

The repository's measured constants (see ``AGENTS.md`` / ``README.md``) license a principled,
history-free form for this component:

* The goalkeeper save rate is a **league constant ~= 67.3% +/- 0.4pp** over five seasons, so an
  individual keeper's deviation from it is almost all noise -- there is no per-keeper saves skill to
  carry forward.
* ``saves + goals_conceded`` is the only available proxy for shots on target faced, and shots faced
  are a property of the **team defensive system**, not of the keeper.

So for a goalkeeper we model

    saves ~ Poisson(k * lambda_conceded),   k = save_rate / (1 - save_rate),

where ``lambda_conceded`` is the expected value of the fixture's Stage A team-conceded distribution
(the opponent's scored-goals distribution, already computed per fixture by the points harness). If a
fraction ``s`` of shots on target faced are saved and ``lambda_conceded`` are conceded (not saved),
the expected shots on target faced is ``lambda_conceded / (1 - s)`` and expected saves is
``s * lambda_conceded / (1 - s) = k * lambda_conceded`` with ``k = s / (1 - s)``. That is the whole
model: no per-keeper saves history is introduced, exactly because the league-constant finding says
individual deviation is noise.

``save_rate`` is fitted **fold-locally and point-in-time** from the training window
(``kickoff_time < as_of``) as ``sum(saves) / sum(saves + goals_conceded)`` over goalkeeper
appearances, clamped to a sane band and falling back to the measured league constant only when the
window carries no goalkeeper data. It is derived, never read from config.

This module is pure: no database, SQL, Polars, or config-file read. It receives already-fitted
history rows and returns a count distribution. ``lambda_conceded`` is supplied explicitly by the
caller because it is a per-fixture team quantity, not something a generic per-player predictor
protocol carries.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from fpl.models.attacking_baselines import (
    MAX_GOALS,
    GoalCountDistribution,
    poisson_pmf,
)
from fpl.types import Position

NAME = "gk_saves_poisson_from_team_conceded_v1"

# Measured league goalkeeper save rate: 67.3% +/- 0.4pp over five seasons (AGENTS.md). Used ONLY as
# the cold-start fallback when a fold's training window carries no goalkeeper appearances; the live
# value is derived fold-locally.
LEAGUE_SAVE_RATE: float = 0.673

# Clamp band for the fold-local estimate. The measured rate is 67.3% with a 0.4pp standard error, so
# a fold estimate outside [0.50, 0.85] is a small-sample artefact, not a real signal; clamping keeps
# ``k = save_rate / (1 - save_rate)`` finite and bounded.
MIN_SAVE_RATE: float = 0.50
MAX_SAVE_RATE: float = 0.85

# A point mass on zero saves (length MAX_GOALS + 1), returned for non-goalkeepers.
_ZERO_SAVES: GoalCountDistribution = (1.0,) + (0.0,) * MAX_GOALS


@dataclass(frozen=True, slots=True)
class GkSavesHistoryRow:
    """One prior player-fixture row, as far as the saves component reads it.

    ``saves`` and ``goals_conceded`` are ``None`` only if unmeasured; a NULL is never read as zero
    (R: NULL != 0). Non-goalkeeper rows are ignored by the estimator.
    """

    position: Position
    minutes: int
    saves: int | None
    goals_conceded: int | None


class GkSavesV1:
    """Fold-local goalkeeper saves estimator: ``saves ~ Poisson(k * lambda_conceded)`` for a GK.

    ``fit`` derives the league save rate from the fold's goalkeeper appearances; ``predict`` maps a
    fixture's expected team-conceded rate to a saves count distribution. A non-goalkeeper always
    returns a point mass on zero saves, so it contributes no saves points.
    """

    name: str = NAME

    def __init__(
        self,
        *,
        default_save_rate: float = LEAGUE_SAVE_RATE,
        min_save_rate: float = MIN_SAVE_RATE,
        max_save_rate: float = MAX_SAVE_RATE,
        max_saves: int = MAX_GOALS,
    ) -> None:
        self._min_save_rate = min_save_rate
        self._max_save_rate = max_save_rate
        self._max_saves = max_saves
        self._save_rate = self._clamp(default_save_rate)

    def _clamp(self, rate: float) -> float:
        return min(max(rate, self._min_save_rate), self._max_save_rate)

    def fit(self, history: Sequence[GkSavesHistoryRow]) -> None:
        """Derive ``save_rate = sum(saves) / sum(saves + conceded)`` over GK appearances.

        Point-in-time: ``history`` is the fold's prior rows only. A goalkeeper appearance requires
        ``minutes > 0`` and both ``saves`` and ``goals_conceded`` measured (a NULL is skipped, never
        zero-filled). With no eligible goalkeeper data the rate stays at the measured league
        constant.
        """
        total_saves = 0
        total_shots_on_target = 0
        for row in history:
            if row.position is not Position.GK:
                continue
            if row.minutes <= 0:
                continue
            if row.saves is None or row.goals_conceded is None:
                continue
            total_saves += row.saves
            total_shots_on_target += row.saves + row.goals_conceded
        if total_shots_on_target > 0:
            self._save_rate = self._clamp(total_saves / total_shots_on_target)

    @property
    def save_rate(self) -> float:
        return self._save_rate

    @property
    def saves_per_conceded(self) -> float:
        """``k = save_rate / (1 - save_rate)``: expected saves per expected goal conceded."""
        return self._save_rate / (1.0 - self._save_rate)

    def predict(self, position: Position, lambda_conceded: float) -> GoalCountDistribution:
        """Saves count distribution for one player-fixture.

        For a goalkeeper: ``Poisson(k * lambda_conceded)`` truncated at ``max_saves``. For any other
        position: a point mass on zero (a non-goalkeeper scores no saves points).
        """
        if position is not Position.GK:
            return _ZERO_SAVES
        rate = self.saves_per_conceded * max(lambda_conceded, 0.0)
        return poisson_pmf(rate, max_goals=self._max_saves)

    def parameters(self) -> Mapping[str, float]:
        return {
            "save_rate": self._save_rate,
            "saves_per_conceded_k": self.saves_per_conceded,
        }
