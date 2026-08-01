"""Stage D v2 component: defensive-contribution threshold hit probability (PROSPECTIVE-ONLY).

FPL's 2026/27 rules award **+2 points** when a player's ``defensive_contribution`` count reaches a
position threshold (DEF 10, MID 12, FWD 12; goalkeepers never earn it -- measured max 0). The
composer does not need the DC count distribution, only the probability the threshold is hit, so this
component models a single Bernoulli probability ``p_hit = P(DC_count >= threshold[position])`` per
player-fixture.

**Prospective-only, no cross-season historical-lift claim.** ``defensive_contribution`` and its raw
inputs exist in **exactly one season, 2025-26** (0% coverage in the four earlier seasons). A NULL DC
row (every row before 2025-26) is unmeasured and is never read as zero (R: NULL != 0); it simply
carries no DC signal. So in a fold whose training window has no measured DC (all folds before
2025-26) the fold-local position prior is undefined and every ``p_hit`` is 0 -- DC contributes
nothing there and is exercised only within 2025-26.

Estimator: a player's ``p_hit`` is the shrunk empirical hit rate over the player's trailing
DC-measured appearances,

    p_hit = (hits + alpha * pos_p) / (n + alpha),

where ``hits`` and ``n`` count the player's trailing DC-measured appearances with
``DC_count >= threshold`` and in total, ``pos_p`` is the fold-local position hit rate over all
DC-measured appearances at that position, and ``alpha`` shrinks a short personal history toward it.
When the position has no DC-measured appearance in the window (``pos_p`` undefined) ``p_hit`` is 0.
Goalkeepers always get 0.

**Minutes-independence approximation (v2 limitation).** ``p_hit`` is estimated over appearances
(``minutes > 0``), not conditioned on the minutes bin the composer later draws. A 90-minute shift is
far likelier to reach the threshold than a short cameo, so applying one ``p_hit`` across all played
bins is an approximation, recorded here and in the development doc as a Stage-D-v2 limitation.

This module is pure: no database, SQL, Polars, or config-file read. Thresholds are passed in from
the loaded scoring rules.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from fpl.types import Position

NAME = "trailing_dc_threshold_hit_bernoulli_v1"

# Shrinkage strength toward the fold-local position hit rate, and the trailing window length. Both
# mirror the other Stage-B/C trailing components (window 5, alpha 5.0); development choices, not a
# pre-registered contract.
DEFAULT_ALPHA: float = 5.0
DEFAULT_WINDOW: int = 5


@dataclass(frozen=True, slots=True)
class DcHistoryRow:
    """One prior player-fixture row, as far as the DC component reads it.

    ``defensive_contribution`` is ``None`` where unmeasured (every row before 2025-26); such rows
    are skipped when building history and never read as zero (R: NULL != 0).
    """

    code: int
    position: Position
    minutes: int
    defensive_contribution: int | None


class DefensiveContributionV1:
    """Fold-local, prospective-only DC threshold-hit Bernoulli estimator.

    ``fit`` builds the fold-local position hit rates and per-player trailing DC-measured history
    from the fold's prior rows; ``predict`` returns ``p_hit`` for one target player. Goalkeepers,
    and any position/player with no DC-measured history in the window, return 0.
    """

    name: str = NAME

    def __init__(
        self,
        thresholds: Mapping[Position, int],
        *,
        alpha: float = DEFAULT_ALPHA,
        window: int = DEFAULT_WINDOW,
    ) -> None:
        # Goalkeepers are absent from the rules' threshold map (gotcha 7), so they never earn DC.
        self._thresholds = dict(thresholds)
        self._alpha = alpha
        self._window = window
        self._position_hit_rate: dict[Position, float] = {}
        self._player_history: dict[int, list[DcHistoryRow]] = {}

    def _is_hit(self, position: Position, dc_count: int) -> bool:
        threshold = self._thresholds.get(position)
        return threshold is not None and dc_count >= threshold

    def fit(self, history: Sequence[DcHistoryRow]) -> None:
        """Fit fold-local position hit rates and per-player trailing DC history.

        Only DC-measured appearances (``minutes > 0`` and ``defensive_contribution`` not NULL) at a
        threshold-bearing position enter the estimate. History arrives in ascending recency order,
        so the last ``window`` rows per player are the most recent.
        """
        pos_hits: dict[Position, int] = {}
        pos_apps: dict[Position, int] = {}
        self._player_history = {}
        for row in history:
            if row.defensive_contribution is None:
                continue
            if row.minutes <= 0:
                continue
            if row.position not in self._thresholds:
                continue
            pos_apps[row.position] = pos_apps.get(row.position, 0) + 1
            if self._is_hit(row.position, row.defensive_contribution):
                pos_hits[row.position] = pos_hits.get(row.position, 0) + 1
            self._player_history.setdefault(row.code, []).append(row)
        self._position_hit_rate = {
            pos: pos_hits.get(pos, 0) / pos_apps[pos] for pos in pos_apps if pos_apps[pos] > 0
        }

    def position_hit_rate(self, position: Position) -> float | None:
        return self._position_hit_rate.get(position)

    def predict(self, code: int, position: Position) -> float:
        """``p_hit = P(DC_count >= threshold[position])`` for one target player-fixture.

        Returns 0 for goalkeepers, for positions with no threshold, and where the fold has no
        DC-measured history for the position (all folds before 2025-26).
        """
        pos_p = self._position_hit_rate.get(position)
        if pos_p is None:
            # No DC-measured appearance for this position in the window: no signal, no contribution.
            return 0.0
        rows = self._player_history.get(code, [])
        recent = rows[-self._window :]
        n = len(recent)
        hits = sum(1 for row in recent if self._is_hit(position, row.defensive_contribution or 0))
        return (hits + self._alpha * pos_p) / (n + self._alpha)

    def parameters(self) -> Mapping[str, float | int]:
        return {"alpha": self._alpha, "window": self._window}
