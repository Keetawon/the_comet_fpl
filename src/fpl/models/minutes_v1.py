"""Stage B Candidate V1: trailing-player minutes shrunk to a position prior.

The model implements the pre-registered ``shrunk_trailing_5_player_minutes_v1`` policy.  It is
deliberately small and closed form:

    p_k(alpha) = (c_k + alpha * q_k) / (n + alpha)

``c_k`` counts the stable player's up to five most recent prior player-fixture outcomes and
``q_k`` is the fold-local raw current-position prior.  The only selected parameter is ``alpha``.
Selection uses a true six-observed-gameweek inner walk-forward and pooled log score.

This module has no database, SQL, Polars, randomness, or archive dependency.  The validation
layer owns outcome access; the public prediction boundary accepts only the label-free
``TargetRow`` shape.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import overload

from fpl.config import (
    Phase2EvaluationConfig,
    Phase2StageBCandidateV1Policy,
    load_phase2_evaluation,
)
from fpl.types import Position
from fpl.validate.minutes_baselines import (
    HistoryRow,
    MinuteBins,
    MinutesDistribution,
    PositionPrior,
    TargetRow,
)


@dataclass(frozen=True, slots=True)
class AlphaScore:
    """One deterministic inner-grid result."""

    alpha: float
    pooled_mean_log_score: float
    predictions: int


@dataclass(frozen=True, slots=True)
class MinutesV1Metadata:
    """Fold-local parameter-selection provenance exposed to the future runner."""

    selected_alpha: float
    used_inner_holdout: bool
    inner_holdout_gameweeks: tuple[tuple[str, int], ...]
    inner_training_observed_gameweeks: int
    alpha_scores: tuple[AlphaScore, ...]


@dataclass(frozen=True, slots=True)
class _FittedState:
    """Only the fold-local structures needed for a closed-form prediction."""

    prior: PositionPrior
    by_code: dict[int, tuple[HistoryRow, ...]]


def _as_utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{label} must be a timezone-aware datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware, got a naive datetime")
    return value.astimezone(UTC)


def _row_key(row: TargetRow) -> tuple[str, int, int]:
    return (row.season, row.code, row.fixture)


def _recency_key(row: HistoryRow) -> tuple[datetime, str, int]:
    return (row.kickoff_time.astimezone(UTC), row.season, row.fixture)


def _target_order(row: TargetRow) -> tuple[datetime, str, int, int, int]:
    return (
        row.kickoff_time.astimezone(UTC),
        row.season,
        row.gw,
        row.fixture,
        row.code,
    )


def _as_target(row: HistoryRow) -> TargetRow:
    """Project a labelled training row onto the exact model-facing target shape."""
    return TargetRow(
        season=row.season,
        gw=row.gw,
        fixture=row.fixture,
        kickoff_time=row.kickoff_time,
        code=row.code,
        position=row.position,
        team_id=row.team_id,
        opponent_team_id=row.opponent_team_id,
        was_home=row.was_home,
    )


class ShrunkTrailing5PlayerMinutesV1:
    """The pre-registered Stage B Candidate V1 estimator.

    ``fit`` receives only prior eligible player-fixture outcomes and an outer prediction
    cutoff.  It first performs the frozen nested alpha selection when at least fourteen
    observed gameweeks are available, then refits the position prior and player histories on
    the complete outer history.  ``predict`` accepts one target or a sequence of targets.
    """

    def __init__(
        self,
        policy: Phase2StageBCandidateV1Policy | None = None,
        *,
        config: Phase2EvaluationConfig | None = None,
    ) -> None:
        resolved = config or load_phase2_evaluation()
        self._policy = policy or resolved.stage_b_candidate_v1
        self._bins = MinuteBins.from_config(resolved)
        self._log_floor = resolved.scoring_calibration.log_probability_floor
        self.name = self._policy.name
        self._as_of: datetime | None = None
        self._state: _FittedState | None = None
        self._metadata = MinutesV1Metadata(
            selected_alpha=self._policy.insufficient_inner_history_fallback_alpha,
            used_inner_holdout=False,
            inner_holdout_gameweeks=(),
            inner_training_observed_gameweeks=0,
            alpha_scores=(),
        )

    @property
    def selected_alpha(self) -> float:
        return self._metadata.selected_alpha

    def fit(
        self, history: Sequence[HistoryRow], *, as_of: datetime
    ) -> ShrunkTrailing5PlayerMinutesV1:
        """Fit one outer fold and select alpha strictly from its prior observed gameweeks."""
        as_of_utc = _as_utc(as_of, "as_of")
        rows = self._validate_history(history, as_of=as_of_utc)
        if not rows:
            raise ValueError("Candidate V1 requires at least one eligible prior minutes row")

        self._metadata = self._select_alpha(rows)
        self._state = self._fit_state(rows)
        self._as_of = as_of_utc
        return self

    @overload
    def predict(self, target: TargetRow) -> MinutesDistribution: ...

    @overload
    def predict(self, target: Sequence[TargetRow]) -> tuple[MinutesDistribution, ...]: ...

    def predict(
        self, target: TargetRow | Sequence[TargetRow]
    ) -> MinutesDistribution | tuple[MinutesDistribution, ...]:
        """Predict one label-free target or an aligned sequence of targets."""
        if type(target) is TargetRow:
            return self._predict_one(target)
        if isinstance(target, HistoryRow):
            raise TypeError(
                "predict accepts label-free TargetRow inputs; HistoryRow carries minutes"
            )
        if not isinstance(target, Sequence):
            raise TypeError("predict expects a TargetRow or a sequence of TargetRow objects")
        return tuple(self._predict_one(row) for row in target)

    def parameters(self) -> dict[str, float | int | bool | str]:
        """Stable scalar provenance for result-table serialization."""
        return {
            "name": self.name,
            "selected_alpha": self._metadata.selected_alpha,
            "history_window": self._policy.history_window,
            "inner_holdout_observed_gameweeks": len(self._metadata.inner_holdout_gameweeks),
            "inner_training_observed_gameweeks": (self._metadata.inner_training_observed_gameweeks),
            "used_inner_holdout": self._metadata.used_inner_holdout,
            "inner_objective": self._policy.inner_objective,
        }

    def metadata(self) -> MinutesV1Metadata:
        """Complete deterministic nested-selection record."""
        return self._metadata

    def _validate_history(
        self, history: Sequence[HistoryRow], *, as_of: datetime
    ) -> tuple[HistoryRow, ...]:
        seen: set[tuple[str, int, int]] = set()
        validated: list[HistoryRow] = []
        for row in history:
            if type(row) is not HistoryRow:
                raise TypeError("fit history must contain HistoryRow objects")
            key = _row_key(row)
            if key in seen:
                raise ValueError(
                    f"duplicate history grain {key}; expected unique (season, code, fixture)"
                )
            seen.add(key)
            kickoff = _as_utc(row.kickoff_time, "history kickoff_time")
            if kickoff >= as_of:
                raise ValueError(
                    f"history row {key} is not observed before cutoff: "
                    f"{row.kickoff_time!r} >= {as_of!r}"
                )
            if isinstance(row.code, bool) or not isinstance(row.code, int):
                raise TypeError(f"stable player code must be a non-bool int for history row {key}")
            if not isinstance(row.position, Position):
                raise TypeError(f"position must be a Position for history row {key}")
            if isinstance(row.minutes, bool) or not isinstance(row.minutes, int):
                raise TypeError(f"minutes must be a non-null int for history row {key}")
            self._bins.index_of(row.minutes)
            validated.append(row)
        return tuple(validated)

    def _validate_target(self, target: TargetRow) -> None:
        if type(target) is not TargetRow:
            raise TypeError(
                "predict accepts label-free TargetRow inputs; HistoryRow carries minutes"
            )
        if self._as_of is None:
            raise RuntimeError("Candidate V1 must be fitted before prediction")
        kickoff = _as_utc(target.kickoff_time, "target kickoff_time")
        if kickoff < self._as_of:
            raise ValueError(
                f"target row {_row_key(target)} is already observed before fitted cutoff"
            )
        if isinstance(target.code, bool) or not isinstance(target.code, int):
            raise TypeError("target stable player code must be a non-bool int")
        if not isinstance(target.position, Position):
            raise TypeError("target position must be a Position")

    def _fit_state(self, history: Sequence[HistoryRow]) -> _FittedState:
        ordered = sorted(history, key=_recency_key, reverse=True)
        by_code: dict[int, list[HistoryRow]] = {}
        for row in ordered:
            by_code.setdefault(row.code, []).append(row)
        return _FittedState(
            prior=PositionPrior.from_history(history, self._bins),
            by_code={code: tuple(rows) for code, rows in by_code.items()},
        )

    def _distribution(
        self, state: _FittedState, target: TargetRow, *, alpha: float
    ) -> MinutesDistribution:
        q = state.prior.distribution_for(target.position)
        recent = state.by_code.get(target.code, ())[: self._policy.history_window]
        if not recent:
            return q

        counts = [0] * self._bins.n_bins()
        for row in recent:
            counts[self._bins.index_of(row.minutes)] += 1
        n = sum(counts)
        denominator = n + alpha
        values = tuple(
            (count + alpha * prior) / denominator for count, prior in zip(counts, q, strict=True)
        )
        # The contract pins four bins; the runtime bins object cross-checks that invariant.
        return (values[0], values[1], values[2], values[3])

    def _predict_one(self, target: TargetRow) -> MinutesDistribution:
        self._validate_target(target)
        if self._state is None:
            raise RuntimeError("Candidate V1 must be fitted before prediction")
        return self._distribution(self._state, target, alpha=self._metadata.selected_alpha)

    def _observed_gameweeks(self, history: Sequence[HistoryRow]) -> tuple[tuple[str, int], ...]:
        first_kickoff: dict[tuple[str, int], datetime] = {}
        for row in history:
            key = (row.season, row.gw)
            kickoff = row.kickoff_time.astimezone(UTC)
            current = first_kickoff.get(key)
            if current is None or kickoff < current:
                first_kickoff[key] = kickoff
        return tuple(
            key
            for key, _ in sorted(
                first_kickoff.items(),
                key=lambda item: (item[1], item[0][0], item[0][1]),
            )
        )

    def _select_alpha(self, history: Sequence[HistoryRow]) -> MinutesV1Metadata:
        gameweeks = self._observed_gameweeks(history)
        holdout_count = self._policy.inner_holdout_observed_gameweeks
        minimum_earlier = self._policy.minimum_earlier_observed_gameweeks
        required = holdout_count + minimum_earlier
        fallback = self._policy.insufficient_inner_history_fallback_alpha
        if len(gameweeks) < required:
            return MinutesV1Metadata(
                selected_alpha=fallback,
                used_inner_holdout=False,
                inner_holdout_gameweeks=(),
                inner_training_observed_gameweeks=max(len(gameweeks) - holdout_count, 0),
                alpha_scores=(),
            )

        holdout_keys = gameweeks[-holdout_count:]
        training_keys = frozenset(gameweeks[:-holdout_count])
        batches = {
            key: tuple(
                sorted(
                    (row for row in history if (row.season, row.gw) == key),
                    key=_target_order,
                )
            )
            for key in holdout_keys
        }

        # Candidate state is raw history and therefore independent of alpha. Build each
        # pre-gameweek snapshot once, after adding only rows whose outcomes were available at
        # that gameweek's first kickoff. Every alpha is then scored against the same snapshots.
        completed_keys = set(training_keys)
        walk_forward: list[tuple[tuple[HistoryRow, ...], _FittedState]] = []
        for key in holdout_keys:
            batch = batches[key]
            batch_as_of = min(row.kickoff_time.astimezone(UTC) for row in batch)
            available = tuple(
                row
                for row in history
                if (row.season, row.gw) in completed_keys
                and row.kickoff_time.astimezone(UTC) < batch_as_of
            )
            if not available:
                raise ValueError(f"empty inner training history before holdout gameweek {key}")
            walk_forward.append((batch, self._fit_state(available)))
            completed_keys.add(key)

        scores: list[AlphaScore] = []
        for alpha in self._policy.prior_strength_grid:
            log_scores: list[float] = []
            for batch, state in walk_forward:
                # Predict the complete gameweek from one pre-gameweek state.  The label is
                # retained separately and never reaches _distribution through TargetRow.
                for labelled in batch:
                    target = _as_target(labelled)
                    distribution = self._distribution(state, target, alpha=alpha)
                    observed = self._bins.index_of(labelled.minutes)
                    log_scores.append(-math.log(max(distribution[observed], self._log_floor)))
            scores.append(
                AlphaScore(
                    alpha=alpha,
                    pooled_mean_log_score=math.fsum(log_scores) / len(log_scores),
                    predictions=len(log_scores),
                )
            )

        best = min(scores, key=lambda score: (score.pooled_mean_log_score, score.alpha))
        return MinutesV1Metadata(
            selected_alpha=best.alpha,
            used_inner_holdout=True,
            inner_holdout_gameweeks=holdout_keys,
            inner_training_observed_gameweeks=len(training_keys),
            alpha_scores=tuple(scores),
        )


def fit_minutes_v1(
    history: Sequence[HistoryRow],
    *,
    as_of: datetime,
    config: Phase2EvaluationConfig | None = None,
) -> ShrunkTrailing5PlayerMinutesV1:
    """Convenience constructor for one fitted Candidate V1 outer fold."""
    return ShrunkTrailing5PlayerMinutesV1(config=config).fit(history, as_of=as_of)
