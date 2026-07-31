"""Stage B Candidate V3: concentration-adaptive-shrinkage trailing-player minutes.

Implements the pre-registered ``concentration_adaptive_shrinkage_player_minutes_v3`` policy. It is
Candidate V2 with exactly ONE change: the shrinkage strength adapts to how concentrated the
player's own recency-weighted trailing history is. With V2's geometric weights ``w_k`` and
``W = sum_k w_k``, the weighted bin shares ``s_k = w_k / W`` give a normalised Herfindahl
concentration

    C = (sum_k s_k**2 - 1/n_bins) / (1 - 1/n_bins)   in [0, 1]

(``C = 1`` when all weighted mass is in one bin, ``C = 0`` when the four shares are equal), the
effective prior strength is ``alpha_eff = alpha * (1 - lambda*C)`` (clamped at 0), and

    p_k(decay, alpha, lambda) = (w_k + alpha_eff*q_k) / (W + alpha_eff).

``q`` is the same fold-local raw current-position prior V1/V2 use. At ``lambda = 0`` every
``alpha_eff`` equals ``alpha`` and the prediction is **bit-identical to V2** -- V3 is a strict
generalisation and the comparison is honest. The motivation, diagnosed from V2's committed
evidence, is that V2 failed the v1.2 starter-ranking gate almost entirely on goalkeepers, whose
near-deterministic (concentrated) histories are blurred by a uniform shrinkage; shrinking less
where the history is already concentrated sharpens both the log score and the ranking on exactly
those rows. ``decay``, ``alpha`` and ``lambda`` are selected jointly by the SAME
six-observed-gameweek nested walk-forward V1/V2 use (pooled inner mean log score), with a
deterministic tie-break biased toward the null (V2): smallest ``lambda`` first, then largest
``decay``, then smallest ``alpha``.

This module has no database, SQL, Polars, randomness, or archive dependency. It subclasses V2 to
reuse its leakage-safe history/target validation, prediction dispatch, and the shared
position-prior / history / inner-holdout machinery. The only deltas are the concentration-adaptive
distribution (``_distribution_adaptive``) and the joint ``(decay, alpha, lambda)`` selection
(``_select_params_v3``). It deliberately does not override V2's ``_distribution_weighted`` or
``metadata_v2``: V3 carries its own policy/metadata (``_policy_v3`` / ``_metadata_v3``) and exposes
the nested-selection record as :meth:`metadata_v3`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from fpl.config import (
    Phase2EvaluationConfig,
    Phase2StageBCandidateV3Policy,
    load_phase2_evaluation,
)
from fpl.models.minutes_v1 import (
    _as_target,
    _as_utc,
    _build_inner_holdout_plan,
    _fit_state,
    _FittedState,
)
from fpl.models.minutes_v2 import RecencyWeightedTrailingPlayerMinutesV2
from fpl.validate.minutes_baselines import (
    HistoryRow,
    MinuteBins,
    MinutesDistribution,
    TargetRow,
)


@dataclass(frozen=True, slots=True)
class ParamScoreV3:
    """One deterministic inner-grid result for a ``(decay, alpha, lambda)`` triple."""

    decay: float
    alpha: float
    adaptation: float
    pooled_mean_log_score: float
    predictions: int


@dataclass(frozen=True, slots=True)
class MinutesV3Metadata:
    """Fold-local joint ``(decay, alpha, lambda)`` selection provenance for the runner."""

    selected_decay: float
    selected_alpha: float
    selected_adaptation: float
    used_inner_holdout: bool
    inner_holdout_gameweeks: tuple[tuple[str, int], ...]
    inner_training_observed_gameweeks: int
    param_scores: tuple[ParamScoreV3, ...]


class ConcentrationAdaptiveShrinkagePlayerMinutesV3(RecencyWeightedTrailingPlayerMinutesV2):
    """The pre-registered Stage B Candidate V3 estimator (concentration-adaptive V2).

    Subclasses V2 for its leakage-safe validation and prediction dispatch only. V3 holds its own
    policy (``_policy_v3``) and metadata (``_metadata_v3``) and never reads V2's ``_policy_v2`` /
    ``_metadata_v2``; the inherited V2 ``_distribution_weighted`` / ``_select_params`` /
    ``metadata_v2`` are not used on a V3 instance (V3 scores through ``_distribution_adaptive`` and
    ``_select_params_v3`` and reports via :meth:`metadata_v3`).
    """

    def __init__(
        self,
        policy: Phase2StageBCandidateV3Policy | None = None,
        *,
        config: Phase2EvaluationConfig | None = None,
    ) -> None:
        resolved = config or load_phase2_evaluation()
        self._policy_v3 = policy or resolved.stage_b_candidate_v3
        self._bins = MinuteBins.from_config(resolved)
        self._log_floor = resolved.scoring_calibration.log_probability_floor
        self.name = self._policy_v3.name
        self._as_of: datetime | None = None
        self._state: _FittedState | None = None
        self._metadata_v3 = MinutesV3Metadata(
            selected_decay=self._policy_v3.insufficient_inner_history_fallback_decay,
            selected_alpha=self._policy_v3.insufficient_inner_history_fallback_alpha,
            selected_adaptation=self._policy_v3.insufficient_inner_history_fallback_lambda,
            used_inner_holdout=False,
            inner_holdout_gameweeks=(),
            inner_training_observed_gameweeks=0,
            param_scores=(),
        )

    @property
    def selected_decay(self) -> float:
        return self._metadata_v3.selected_decay

    @property
    def selected_alpha(self) -> float:
        return self._metadata_v3.selected_alpha

    @property
    def selected_adaptation(self) -> float:
        return self._metadata_v3.selected_adaptation

    def metadata_v3(self) -> MinutesV3Metadata:
        """Complete deterministic joint-selection record."""
        return self._metadata_v3

    def fit(
        self, history: Sequence[HistoryRow], *, as_of: datetime
    ) -> ConcentrationAdaptiveShrinkagePlayerMinutesV3:
        """Fit one outer fold and select ``(decay, alpha, lambda)`` from prior gameweeks."""
        as_of_utc = _as_utc(as_of, "as_of")
        rows = self._validate_history(history, as_of=as_of_utc)  # inherited (V1 via V2)
        if not rows:
            raise ValueError("Candidate V3 requires at least one eligible prior minutes row")
        self._metadata_v3 = self._select_params_v3(rows)
        self._state = _fit_state(rows, self._bins)
        self._as_of = as_of_utc
        return self

    def parameters(self) -> dict[str, float | int | bool | str]:
        """Stable scalar provenance for serialization (mirrors V2's keys plus selected lambda)."""
        return {
            "name": self.name,
            "selected_decay": self._metadata_v3.selected_decay,
            "selected_alpha": self._metadata_v3.selected_alpha,
            "selected_lambda": self._metadata_v3.selected_adaptation,
            "history_window": self._policy_v3.history_window,
            "inner_holdout_observed_gameweeks": len(self._metadata_v3.inner_holdout_gameweeks),
            "inner_training_observed_gameweeks": (
                self._metadata_v3.inner_training_observed_gameweeks
            ),
            "used_inner_holdout": self._metadata_v3.used_inner_holdout,
            "inner_objective": self._policy_v3.inner_objective,
        }

    def _distribution_adaptive(
        self,
        state: _FittedState,
        target: TargetRow,
        *,
        alpha: float,
        decay: float,
        adaptation: float,
    ) -> MinutesDistribution:
        """The concentration-adaptive closed form. Reduces to V2 when ``adaptation == 0``."""
        q = state.prior.distribution_for(target.position)
        recent = state.by_code.get(target.code, ())[: self._policy_v3.history_window]
        if not recent:
            # W == 0 branch: no prior history -> exactly q, identical to V1/V2.
            return q

        n_bins = self._bins.n_bins()
        weighted = [0.0] * n_bins
        for i, row in enumerate(recent):  # i = 0 newest -> weight decay**0 = 1.0
            weighted[self._bins.index_of(row.minutes)] += decay**i
        w_total = math.fsum(weighted)
        if w_total == 0.0:
            return q

        # Normalised Herfindahl concentration of the weighted shares: C = 1 when all mass is in
        # one bin, C = 0 when the shares are uniform. alpha_eff shrinks less as C rises.
        herfindahl = math.fsum((mass / w_total) ** 2 for mass in weighted)
        uniform = 1.0 / n_bins
        concentration = (herfindahl - uniform) / (1.0 - uniform)
        alpha_eff = max(0.0, alpha * (1.0 - adaptation * concentration))

        denominator = w_total + alpha_eff
        values = tuple(
            (mass + alpha_eff * prior) / denominator
            for mass, prior in zip(weighted, q, strict=True)
        )
        # The contract pins four bins; the runtime bins object cross-checks that invariant.
        return (values[0], values[1], values[2], values[3])

    def _predict_one(self, target: TargetRow) -> MinutesDistribution:
        self._validate_target(target)  # inherited (V1 via V2)
        if self._state is None:
            raise RuntimeError("Candidate V3 must be fitted before prediction")
        return self._distribution_adaptive(
            self._state,
            target,
            alpha=self._metadata_v3.selected_alpha,
            decay=self._metadata_v3.selected_decay,
            adaptation=self._metadata_v3.selected_adaptation,
        )

    def _select_params_v3(self, history: Sequence[HistoryRow]) -> MinutesV3Metadata:
        """Joint ``(decay, alpha, lambda)`` selection by the shared nested inner walk-forward."""
        plan = _build_inner_holdout_plan(
            history,
            holdout_count=self._policy_v3.inner_holdout_observed_gameweeks,
            minimum_earlier=self._policy_v3.minimum_earlier_observed_gameweeks,
            fit_state=lambda rows: _fit_state(rows, self._bins),
        )
        fallback_decay = self._policy_v3.insufficient_inner_history_fallback_decay
        fallback_alpha = self._policy_v3.insufficient_inner_history_fallback_alpha
        fallback_lambda = self._policy_v3.insufficient_inner_history_fallback_lambda
        if not plan.used_inner_holdout:
            return MinutesV3Metadata(
                selected_decay=fallback_decay,
                selected_alpha=fallback_alpha,
                selected_adaptation=fallback_lambda,
                used_inner_holdout=False,
                inner_holdout_gameweeks=(),
                inner_training_observed_gameweeks=plan.training_observed_gameweeks,
                param_scores=(),
            )

        scores: list[ParamScoreV3] = []
        for decay in self._policy_v3.decay_grid:
            for alpha in self._policy_v3.prior_strength_grid:
                for adaptation in self._policy_v3.adaptation_grid:
                    log_scores: list[float] = []
                    for batch, state in plan.batches:
                        for labelled in batch:
                            target = _as_target(labelled)
                            distribution = self._distribution_adaptive(
                                state, target, alpha=alpha, decay=decay, adaptation=adaptation
                            )
                            observed = self._bins.index_of(labelled.minutes)
                            log_scores.append(
                                -math.log(max(distribution[observed], self._log_floor))
                            )
                    scores.append(
                        ParamScoreV3(
                            decay=decay,
                            alpha=alpha,
                            adaptation=adaptation,
                            pooled_mean_log_score=math.fsum(log_scores) / len(log_scores),
                            predictions=len(log_scores),
                        )
                    )

        # Tie-break: smallest pooled log score; then SMALLEST lambda (closest to V2); then LARGEST
        # decay; then smallest alpha. Bias toward the null (V2) on ties.
        best = min(
            scores,
            key=lambda score: (
                score.pooled_mean_log_score,
                score.adaptation,
                -score.decay,
                score.alpha,
            ),
        )
        return MinutesV3Metadata(
            selected_decay=best.decay,
            selected_alpha=best.alpha,
            selected_adaptation=best.adaptation,
            used_inner_holdout=True,
            inner_holdout_gameweeks=plan.holdout_keys,
            inner_training_observed_gameweeks=plan.training_observed_gameweeks,
            param_scores=tuple(scores),
        )


def fit_minutes_v3(
    history: Sequence[HistoryRow],
    *,
    as_of: datetime,
    config: Phase2EvaluationConfig | None = None,
) -> ConcentrationAdaptiveShrinkagePlayerMinutesV3:
    """Convenience constructor for one fitted Candidate V3 outer fold."""
    return ConcentrationAdaptiveShrinkagePlayerMinutesV3(config=config).fit(history, as_of=as_of)
