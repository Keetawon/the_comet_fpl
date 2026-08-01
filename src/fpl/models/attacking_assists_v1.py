"""Stage C assists Candidate V1: xA-informed trailing player assists.

Pre-registered in ``config/phase3_stage_c_assists_evaluation.yaml`` amendment 1.1 as
``xa_informed_trailing_player_assists_v1``. This is the v1.0 ``trailing_player_assist_rate_poisson``
baseline with its recent ASSISTS signal replaced by recent ``expected_assists`` (xA) where xA is
measured (per row, NULL filled by ``creativity`` rescaled to the assist-rate scale) and the assist
residual (assists - xA) shrunk almost fully to the positional mean; where xA is unmeasured it falls
back to the EXACT v1.0 trailing-player baseline.

Two windows are kept (see the design record):
- ``recent_all`` -- the up to five most recent prior rows over ALL rows (including zero-minute),
  the SAME window the v1.0 trailing baseline uses. Used only by the fallback path, so it is
  bit-identical to the baseline.
- ``recent_appeared`` -- the up to five most recent prior APPEARED rows (``minutes > 0``). Used by
  the xA signal (R6: availability never dilutes the per-appearance rate).

Invariants (shared with the v1.0 baselines):
- Player identity: stable ``code``. ``element_id`` is season-scoped and reassigned yearly.
- Strict point-in-time: training rows use ``kickoff_time < as_of`` (enforced by the harness).
- NULL ``expected_assists`` means unmeasured and is never zero-filled; a NULL-xA row on the xA path
  is filled by rescaled ``creativity`` (100% covered). NULL ``creativity`` does not occur.

This is a FIXED closed-form estimator: there is no parameter grid and no inner walk-forward. The two
constants (``alpha``, ``finishing_keep``) are pinned in the contract; changing either fails to load.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from fpl.models.attacking_assists_baselines import (
    AssistHistoryRow,
    PositionalAssistRateBaseline,
)
from fpl.models.attacking_baselines import GoalCountDistribution, TargetRowProjection, poisson_pmf
from fpl.types import Position

# Frozen contract constants (config/phase3_stage_c_assists_evaluation.yaml stage_c_assists_
# candidate_v1). Mirrored here as the construction defaults; the contract pins them and the runner
# reads them from the loaded config, so a config that disagrees fails to load before this runs.
ALPHA: float = 5.0
FINISHING_KEEP: float = 0.05

# Path labels reported per target for development diagnostics (never a gate).
PATH_XA_INFORMED = "xa_informed"
PATH_FALLBACK_V1 = "fallback_v1"
PATH_COLD_START = "cold_start"

NAME = "xa_informed_trailing_player_assists_v1"


@dataclass(frozen=True, slots=True)
class AssistCandidateRate:
    """The estimated assist rate for one target plus the estimator path that produced it."""

    rate: float
    path: str


class XaInformedTrailingPlayerAssistsV1:
    """Fold-local xA-informed trailing player assist-rate estimator.

    Fitted on one fold's prior history (``kickoff_time < as_of``) and predicting that fold's target
    gameweek. The positional assist mean reuses :class:`PositionalAssistRateBaseline` (fitted on all
    rows) so the fallback path is bit-identical to the v1.0 ``trailing_player_assist_rate_poisson``
    baseline. The xA signal is restricted to appeared rows (``minutes > 0``), separating appearance
    from per-appearance rate (R6).
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
        self._positional = PositionalAssistRateBaseline()
        # Mean expected_assists per appearance at each position, over xA-measured APPEARED prior
        # rows. A position absent here has no measured-xA appeared prior row, so pos_xa is undefined
        # and the xA path is blocked for targets at that position.
        self._positional_xa: dict[Position, float] = {}
        # creativity -> assist-rate rescale, per position: pos_a / mean_creativity over appeared
        # rows.
        self._creativity_factor: dict[Position, float] = {}
        # Per-code histories in the chronological order `history` arrives in (the harness sorts
        # ascending by kickoff_time, season, fixture, code, so the last window elements are the most
        # recent -- exactly the v1.0 trailing baseline's recency order).
        self._player_all: dict[int, list[AssistHistoryRow]] = {}
        self._player_appeared: dict[int, list[AssistHistoryRow]] = {}

    def fit(self, history: Sequence[AssistHistoryRow]) -> None:
        # pos_a: identical to the v1.0 positional baseline (same class, same history, all rows).
        self._positional.fit(history)

        xa_sum: dict[Position, float] = {}
        xa_apps: dict[Position, int] = {}
        creativity_sum: dict[Position, float] = {}
        creativity_apps: dict[Position, int] = {}
        self._player_all = {}
        self._player_appeared = {}
        for row in history:
            self._player_all.setdefault(row.code, []).append(row)
            if row.minutes <= 0:
                continue
            # Appeared rows (minutes > 0) feed the xA signal and the creativity rescale (R6).
            self._player_appeared.setdefault(row.code, []).append(row)
            pos = row.position
            if row.expected_assists is not None:
                xa_sum[pos] = xa_sum.get(pos, 0.0) + row.expected_assists
                xa_apps[pos] = xa_apps.get(pos, 0) + 1
            if row.creativity is not None:
                creativity_sum[pos] = creativity_sum.get(pos, 0.0) + row.creativity
                creativity_apps[pos] = creativity_apps.get(pos, 0) + 1

        self._positional_xa = {
            pos: xa_sum[pos] / xa_apps[pos] for pos in xa_apps if xa_apps[pos] > 0
        }
        self._creativity_factor = {}
        for pos in Position:
            pos_a = self._positional.get_rate(pos)
            n_creativity = creativity_apps.get(pos, 0)
            mean_creativity = (
                creativity_sum.get(pos, 0.0) / n_creativity if n_creativity > 0 else 0.0
            )
            self._creativity_factor[pos] = pos_a / mean_creativity if mean_creativity > 0.0 else 0.0

    def _rate(self, target: TargetRowProjection) -> AssistCandidateRate:
        pos = target.position
        pos_a = self._positional.get_rate(pos)

        # The baseline window (all rows incl zero-minute) -- used by the fallback for bit-identity.
        recent_all = self._player_all.get(target.code, [])[-5:]
        # The xA signal window (appeared rows only, R6).
        recent_appeared = self._player_appeared.get(target.code, [])[-5:]
        measured_appeared = [row for row in recent_appeared if row.expected_assists is not None]
        pos_xa = self._positional_xa.get(pos)

        # xA path: appeared rows exist, at least one carries measured xA, and pos_xa is defined.
        if recent_appeared and measured_appeared and pos_xa is not None:
            factor = self._creativity_factor.get(pos, 0.0)
            n = len(recent_appeared)
            sum_xa = 0.0
            sum_assists = 0
            for row in recent_appeared:
                if row.expected_assists is not None:
                    sum_xa += row.expected_assists
                else:
                    # NULL xA filled by rescaled creativity (creativity is 100% covered).
                    sum_xa += factor * (row.creativity or 0.0)
                sum_assists += row.assists
            shrunk_xa = (sum_xa + self.alpha * pos_xa) / (n + self.alpha)
            player_residual = (sum_assists - sum_xa) / n
            positional_residual = pos_a - pos_xa
            residual_term = (
                self.finishing_keep * player_residual
                + (1.0 - self.finishing_keep) * positional_residual
            )
            return AssistCandidateRate(max(0.0, shrunk_xa + residual_term), PATH_XA_INFORMED)

        # Fallback / cold-start: the EXACT v1.0 trailing-assist baseline rate over the all-rows
        # window. Bit-identical wherever xA is absent (all of 2021-22, early 2022-23, and any player
        # whose trailing appeared rows predate xA coverage).
        if not recent_all:
            return AssistCandidateRate(pos_a, PATH_COLD_START)
        sum_assists_all = sum(row.assists for row in recent_all)
        n_all = len(recent_all)
        return AssistCandidateRate(
            (sum_assists_all + self.alpha * pos_a) / (n_all + self.alpha), PATH_FALLBACK_V1
        )

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
