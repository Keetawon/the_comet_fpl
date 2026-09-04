"""V2 goalkeeper saves: shots faced as a predicted quantity, not an identity.

V1 (`models/gk_saves_v1.py`, kept and unchanged) models

    saves ~ Poisson(k * lambda_conceded),   k = save_rate / (1 - save_rate)

which is exact ONLY if shots on target faced is `lambda_conceded / (1 - save_rate)`. That
makes shots faced a deterministic function of goals conceded. Measured on this archive, the
correlation between a team's shots on target allowed and its goals allowed is **0.621** over
3,800 team-matches, so the identity discards about 61% of the variance in shots faced. Two
clubs conceding the same expected goals from very different shot volumes are indistinguishable
to V1, and its saves distribution is under-dispersed by construction.

V2 asks the football engine instead:

    saves ~ Poisson(save_rate * expected_shots_on_target_faced)

Both models share the same fold-local league save rate, because the repository's measured
constant says an individual keeper's deviation from 67.3% +/- 0.4pp is almost all noise --
there is no per-keeper saves skill to carry, and V2 does not invent one. **The only thing that
changes is where the shot volume comes from.** That is deliberate: it makes the comparison a
clean test of one hypothesis rather than of two changes at once.

Falling back to the V1 identity whenever the engine has no shots-faced prediction is what
keeps V2 never worse-informed than V1. It is not a cosmetic safety net -- it is what lets the
same model run over seasons with and without shot data and have its coverage reported rather
than silently varying.

Pure module: no database, SQL, Polars or config read.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from fpl.models.attacking_baselines import MAX_GOALS, GoalCountDistribution, poisson_pmf
from fpl.models.gk_saves_v1 import (
    LEAGUE_SAVE_RATE,
    MAX_SAVE_RATE,
    MIN_SAVE_RATE,
    GkSavesHistoryRow,
)
from fpl.types import Position

NAME: Final[str] = "gk_saves_poisson_from_expected_shots_faced_v2"

_ZERO_SAVES: GoalCountDistribution = (1.0,) + (0.0,) * MAX_GOALS

# A predicted shots-faced value outside this band is a fit artefact, not football. The
# archive's measured team mean is 4.16-4.92 on-target shots faced per match with a standard
# deviation near 2.4, so the band is wide enough never to bind on a real prediction and tight
# enough to stop a degenerate rating from producing a 40-save distribution.
MIN_SHOTS_FACED: Final[float] = 0.25
MAX_SHOTS_FACED: Final[float] = 20.0


@dataclass(frozen=True, slots=True)
class SavesPrediction:
    """A saves distribution and the evidence path that produced it.

    `used_expected_shots` is the whole point of the report: a V2 run whose rows mostly fell
    back to the V1 identity has not tested the V2 hypothesis, and the evaluation must be able
    to say so rather than average the two together into an unattributable number.
    """

    distribution: GoalCountDistribution
    rate: float
    used_expected_shots: bool
    shots_faced: float | None


class GkSavesV2:
    """Fold-local saves estimator driven by the fixture's expected shots on target faced."""

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
        self._fitted_from_rows = 0

    def _clamp(self, rate: float) -> float:
        return min(max(rate, self._min_save_rate), self._max_save_rate)

    def fit(self, history: Sequence[GkSavesHistoryRow]) -> None:
        """Derive the league save rate from the fold's prior goalkeeper appearances.

        Identical to V1's estimator, on purpose. Sharing it means any measured difference
        between the two models is attributable to the shot-volume source and to nothing else.
        """
        total_saves = 0
        total_on_target = 0
        rows = 0
        for row in history:
            if row.position is not Position.GK or row.minutes <= 0:
                continue
            if row.saves is None or row.goals_conceded is None:
                continue
            total_saves += row.saves
            total_on_target += row.saves + row.goals_conceded
            rows += 1
        if total_on_target > 0:
            self._save_rate = self._clamp(total_saves / total_on_target)
            self._fitted_from_rows = rows

    @property
    def save_rate(self) -> float:
        return self._save_rate

    @property
    def saves_per_conceded(self) -> float:
        """`k = s / (1 - s)`: the V1 identity's expected saves per expected goal conceded."""
        return self._save_rate / (1.0 - self._save_rate)

    def implied_shots_faced(self, lambda_conceded: float) -> float:
        """What V1 assumes shots faced to be. The fallback, and the thing V2 replaces."""
        return max(lambda_conceded, 0.0) / (1.0 - self._save_rate)

    def predict_detail(
        self,
        position: Position,
        *,
        lambda_conceded: float,
        expected_shots_on_target_faced: float | None = None,
    ) -> SavesPrediction:
        """Saves distribution for one player-fixture, with its evidence path recorded.

        `expected_shots_on_target_faced` of `None` means the engine had no shots-faced signal
        for this fixture -- a coverage fact, not a zero. Reading it as zero would predict a
        goalkeeper faces no shots, which is never what an absent measurement means.
        """
        if position is not Position.GK:
            return SavesPrediction(_ZERO_SAVES, 0.0, False, None)

        if expected_shots_on_target_faced is None:
            shots = self.implied_shots_faced(lambda_conceded)
            used_engine = False
        else:
            shots = min(max(expected_shots_on_target_faced, MIN_SHOTS_FACED), MAX_SHOTS_FACED)
            used_engine = True
        rate = self._save_rate * shots
        return SavesPrediction(
            distribution=poisson_pmf(rate, max_goals=self._max_saves),
            rate=rate,
            used_expected_shots=used_engine,
            shots_faced=shots,
        )

    def predict(
        self,
        position: Position,
        lambda_conceded: float,
        *,
        expected_shots_on_target_faced: float | None = None,
    ) -> GoalCountDistribution:
        """The distribution alone, signature-compatible with `GkSavesV1.predict`."""
        return self.predict_detail(
            position,
            lambda_conceded=lambda_conceded,
            expected_shots_on_target_faced=expected_shots_on_target_faced,
        ).distribution

    def parameters(self) -> Mapping[str, float]:
        return {
            "save_rate": self._save_rate,
            "saves_per_conceded_k": self.saves_per_conceded,
            "fitted_from_goalkeeper_rows": float(self._fitted_from_rows),
        }
