"""Stage B Candidate V2: recency-weighted trailing-player minutes.

Implements the pre-registered ``recency_weighted_trailing_player_minutes_v2`` policy. It is
Candidate V1 with exactly ONE change: a geometric recency weight on the same trailing-5 window.
For the ``i``-th most-recent row (``i = 0`` newest) the weight is ``decay ** i``; the weighted bin
mass is ``w_k = sum of decay**i over the trailing rows in bin k``; ``W = sum_k w_k``; and

    p_k(decay, alpha) = (w_k + alpha * q_k) / (W + alpha)

``q`` is the same fold-local raw current-position prior V1 uses. At ``decay = 1.0`` every weight is
1, ``w_k = c_k`` and ``W = n``, so the prediction is **bit-identical to V1** -- V2 is a strict
generalisation and the comparison is honest. ``decay`` and ``alpha`` are selected jointly by the
SAME six-observed-gameweek nested walk-forward V1 uses (pooled inner mean log score), with a
deterministic tie-break biased toward the null (V1): largest ``decay`` first, then smallest
``alpha``.

This module has no database, SQL, Polars, randomness, or archive dependency. It subclasses V1 to
reuse its leakage-safe history/target validation and prediction dispatch, and the shared
position-prior / history / inner-holdout machinery already factored into ``minutes_v1``. The only
deltas are the weighted distribution (``_distribution_weighted``) and the joint ``(decay, alpha)``
selection (``_select_params``). It deliberately does not override V1's ``_distribution`` or
``metadata``: V2 carries its own policy/metadata (``_policy_v2`` / ``_metadata_v2``) and exposes
the nested-selection record as :meth:`metadata_v2`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from fpl.config import (
    Phase2EvaluationConfig,
    Phase2StageBCandidateV2Policy,
    load_phase2_evaluation,
)
from fpl.models.minutes_v1 import (
    ShrunkTrailing5PlayerMinutesV1,
    _as_target,
    _as_utc,
    _build_inner_holdout_plan,
    _fit_state,
    _FittedState,
)
from fpl.validate.minutes_baselines import (
    HistoryRow,
    MinuteBins,
    MinutesDistribution,
    TargetRow,
)

# Internal helpers shared with V1 (same package; the underscore names are the contract between
# the two candidate estimators and the shared walk-forward machinery in minutes_v1).


@dataclass(frozen=True, slots=True)
class ParamScore:
    """One deterministic inner-grid result for a ``(decay, alpha)`` pair."""

    decay: float
    alpha: float
    pooled_mean_log_score: float
    predictions: int


@dataclass(frozen=True, slots=True)
class MinutesV2Metadata:
    """Fold-local joint ``(decay, alpha)`` selection provenance for the future runner."""

    selected_decay: float
    selected_alpha: float
    used_inner_holdout: bool
    inner_holdout_gameweeks: tuple[tuple[str, int], ...]
    inner_training_observed_gameweeks: int
    param_scores: tuple[ParamScore, ...]


class RecencyWeightedTrailingPlayerMinutesV2(ShrunkTrailing5PlayerMinutesV1):
    """The pre-registered Stage B Candidate V2 estimator (recency-weighted V1).

    Subclasses V1 for its leakage-safe validation and prediction dispatch only. V2 holds its own
    policy (``_policy_v2``) and metadata (``_metadata_v2``) and never reads V1's ``_policy`` /
    ``_metadata``; the inherited V1 ``_distribution`` / ``_select_alpha`` / ``metadata`` are not
    used on a V2 instance (V2 scores through ``_distribution_weighted`` and ``_select_params`` and
    reports via :meth:`metadata_v2`).
    """

    def __init__(
        self,
        policy: Phase2StageBCandidateV2Policy | None = None,
        *,
        config: Phase2EvaluationConfig | None = None,
    ) -> None:
        resolved = config or load_phase2_evaluation()
        self._policy_v2 = policy or resolved.stage_b_candidate_v2
        self._bins = MinuteBins.from_config(resolved)
        self._log_floor = resolved.scoring_calibration.log_probability_floor
        self.name = self._policy_v2.name
        self._as_of: datetime | None = None
        self._state: _FittedState | None = None
        self._metadata_v2 = MinutesV2Metadata(
            selected_decay=self._policy_v2.insufficient_inner_history_fallback_decay,
            selected_alpha=self._policy_v2.insufficient_inner_history_fallback_alpha,
            used_inner_holdout=False,
            inner_holdout_gameweeks=(),
            inner_training_observed_gameweeks=0,
            param_scores=(),
        )

    @property
    def selected_decay(self) -> float:
        return self._metadata_v2.selected_decay

    @property
    def selected_alpha(self) -> float:
        return self._metadata_v2.selected_alpha

    def metadata_v2(self) -> MinutesV2Metadata:
        """Complete deterministic joint-selection record."""
        return self._metadata_v2

    def fit(
        self, history: Sequence[HistoryRow], *, as_of: datetime
    ) -> RecencyWeightedTrailingPlayerMinutesV2:
        """Fit one outer fold and select ``(decay, alpha)`` from prior observed gameweeks."""
        as_of_utc = _as_utc(as_of, "as_of")
        rows = self._validate_history(history, as_of=as_of_utc)  # inherited from V1
        if not rows:
            raise ValueError("Candidate V2 requires at least one eligible prior minutes row")
        self._metadata_v2 = self._select_params(rows)
        self._state = _fit_state(rows, self._bins)
        self._as_of = as_of_utc
        return self

    def parameters(self) -> dict[str, float | int | bool | str]:
        """Stable scalar provenance for serialization (mirrors V1's keys plus selected decay)."""
        return {
            "name": self.name,
            "selected_decay": self._metadata_v2.selected_decay,
            "selected_alpha": self._metadata_v2.selected_alpha,
            "history_window": self._policy_v2.history_window,
            "inner_holdout_observed_gameweeks": len(self._metadata_v2.inner_holdout_gameweeks),
            "inner_training_observed_gameweeks": (
                self._metadata_v2.inner_training_observed_gameweeks
            ),
            "used_inner_holdout": self._metadata_v2.used_inner_holdout,
            "inner_objective": self._policy_v2.inner_objective,
        }

    def _distribution_weighted(
        self, state: _FittedState, target: TargetRow, *, alpha: float, decay: float
    ) -> MinutesDistribution:
        """The recency-weighted closed form. Reduces exactly to V1 when ``decay == 1.0``."""
        q = state.prior.distribution_for(target.position)
        recent = state.by_code.get(target.code, ())[: self._policy_v2.history_window]
        if not recent:
            # W == 0 branch: no prior history -> exactly q, identical to V1's n == 0 branch.
            return q

        weighted = [0.0] * self._bins.n_bins()
        for i, row in enumerate(recent):  # i = 0 newest -> weight decay**0 = 1.0
            weighted[self._bins.index_of(row.minutes)] += decay**i
        w_total = math.fsum(weighted)
        if w_total == 0.0:
            return q
        denominator = w_total + alpha
        values = tuple(
            (mass + alpha * prior) / denominator for mass, prior in zip(weighted, q, strict=True)
        )
        # The contract pins four bins; the runtime bins object cross-checks that invariant.
        return (values[0], values[1], values[2], values[3])

    def _predict_one(self, target: TargetRow) -> MinutesDistribution:
        self._validate_target(target)  # inherited from V1
        if self._state is None:
            raise RuntimeError("Candidate V2 must be fitted before prediction")
        return self._distribution_weighted(
            self._state,
            target,
            alpha=self._metadata_v2.selected_alpha,
            decay=self._metadata_v2.selected_decay,
        )

    def _select_params(self, history: Sequence[HistoryRow]) -> MinutesV2Metadata:
        """Joint ``(decay, alpha)`` selection by the shared nested inner walk-forward."""
        plan = _build_inner_holdout_plan(
            history,
            holdout_count=self._policy_v2.inner_holdout_observed_gameweeks,
            minimum_earlier=self._policy_v2.minimum_earlier_observed_gameweeks,
            fit_state=lambda rows: _fit_state(rows, self._bins),
        )
        fallback_decay = self._policy_v2.insufficient_inner_history_fallback_decay
        fallback_alpha = self._policy_v2.insufficient_inner_history_fallback_alpha
        if not plan.used_inner_holdout:
            return MinutesV2Metadata(
                selected_decay=fallback_decay,
                selected_alpha=fallback_alpha,
                used_inner_holdout=False,
                inner_holdout_gameweeks=(),
                inner_training_observed_gameweeks=plan.training_observed_gameweeks,
                param_scores=(),
            )

        scores: list[ParamScore] = []
        for decay in self._policy_v2.decay_grid:
            for alpha in self._policy_v2.prior_strength_grid:
                log_scores: list[float] = []
                for batch, state in plan.batches:
                    for labelled in batch:
                        target = _as_target(labelled)
                        distribution = self._distribution_weighted(
                            state, target, alpha=alpha, decay=decay
                        )
                        observed = self._bins.index_of(labelled.minutes)
                        log_scores.append(-math.log(max(distribution[observed], self._log_floor)))
                scores.append(
                    ParamScore(
                        decay=decay,
                        alpha=alpha,
                        pooled_mean_log_score=math.fsum(log_scores) / len(log_scores),
                        predictions=len(log_scores),
                    )
                )

        # Tie-break: smallest pooled log score; then LARGEST decay (closest to no-decay / V1);
        # then smallest alpha. Bias toward the null (V1) on ties.
        best = min(
            scores,
            key=lambda score: (score.pooled_mean_log_score, -score.decay, score.alpha),
        )
        return MinutesV2Metadata(
            selected_decay=best.decay,
            selected_alpha=best.alpha,
            used_inner_holdout=True,
            inner_holdout_gameweeks=plan.holdout_keys,
            inner_training_observed_gameweeks=plan.training_observed_gameweeks,
            param_scores=tuple(scores),
        )


def fit_minutes_v2(
    history: Sequence[HistoryRow],
    *,
    as_of: datetime,
    config: Phase2EvaluationConfig | None = None,
) -> RecencyWeightedTrailingPlayerMinutesV2:
    """Convenience constructor for one fitted Candidate V2 outer fold."""
    return RecencyWeightedTrailingPlayerMinutesV2(config=config).fit(history, as_of=as_of)
