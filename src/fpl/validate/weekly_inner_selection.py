"""Development-only goals+xG selector with weekly inner refits.

The legacy engine and every production caller remain unchanged. Selection is still staged:
goals choose decay/prior, then goals+xG choose the blend. Only the inner refit schedule differs.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import polars as pl

from fpl.features.pit import AsOf
from fpl.models.football_engine_v2 import (
    FittedSignal,
    MultiSignalTeamEngine,
    SignalSpec,
    simplex_grid,
)
from fpl.models.team_goals import fit_ratings

NAME = "retrospective_goals_xg_weekly_inner_selection_v1"
SIGNALS = (SignalSpec("goals", "goals"), SignalSpec("expected_goals", "expected_goals"))
Priors = tuple[dict[int, float], dict[int, float]]


@dataclass(frozen=True)
class InnerBatch:
    season: str
    gw: int
    cutoff: datetime
    training: pl.DataFrame
    target: pl.DataFrame

    def as_report(self) -> dict[str, Any]:
        latest = self.training["kickoff_time"].max()
        assert latest is None or isinstance(latest, datetime)
        return {
            "season": self.season,
            "gw": self.gw,
            "as_of": self.cutoff.isoformat(),
            "training_rows": self.training.height,
            "training_latest_kickoff": latest.isoformat() if latest is not None else None,
            "target_rows": self.target.height,
            "scored_rows": self.target["goals"].is_not_null().sum(),
            "event_time_violations": self.training.filter(
                pl.col("kickoff_time") >= self.cutoff
            ).height,
            "target_gameweek_overlap": self.training.filter(
                (pl.col("season") == self.season) & (pl.col("gw") == self.gw)
            ).height,
        }


def _signal_fits(
    engine: MultiSignalTeamEngine,
    inner: pl.DataFrame,
    names: Sequence[str],
    priors: Priors,
    half_life: float | None,
    prior_matches: float,
) -> dict[str, FittedSignal]:
    """The legacy inner signal fit, with no full-window scale or rating reuse."""
    latest = inner["kickoff_time"].max()
    if not isinstance(latest, datetime):
        return {}
    fitted: dict[str, FittedSignal] = {}
    for name in names:
        spec = engine.fitted_signals[name].spec
        rows = inner.drop_nulls([spec.column])
        if rows.is_empty():
            continue
        fitted[name] = FittedSignal(
            spec=spec,
            ratings=fit_ratings(
                engine._weighted_fixtures(rows, spec.column, latest, half_life),
                prior_attack=priors[0],
                prior_defence=priors[1],
                prior_matches=prior_matches,
                rate_floor=engine._rate_floor,
            ),
            rows=rows.height,
            coverage=rows.height / inner.height,
            goal_scale=engine._goal_scale(rows, spec.column),
        )
    return fitted


class WeeklyRefitTeamEngine(MultiSignalTeamEngine):
    """A separate validation-only capability; its football signals cannot be extended.

    ``fit`` retains the base class's prior-only frame contract. The development runner uses
    ``fit_as_of`` to enforce the outer event-time boundary explicitly. Neither changes or
    weakens PointInTimeView, and neither provides a prospective evidence class.
    """

    name = NAME
    evidence_class = "retrospective_archive_development"

    def __init__(
        self,
        *,
        half_life_days: Sequence[float | None] = (40.0, 80.0, 160.0, 320.0, 640.0, None),
        prior_matches: Sequence[float] = (2.0, 4.0, 8.0, 16.0, 32.0),
        minimum_team_matches: int = 3,
        inner_holdout_gameweeks: int = 6,
        minimum_inner_training_gameweeks: int = 10,
        weight_step: float = 0.25,
        minimum_signal_coverage: float = 0.25,
        promoted_attack_prior: float = 0.719,
        promoted_defence_prior: float = 1.309,
        rate_floor: float = 0.05,
        maximum_goals: int = 10,
    ) -> None:
        super().__init__(
            signals=SIGNALS,
            half_life_days=half_life_days,
            prior_matches=prior_matches,
            minimum_team_matches=minimum_team_matches,
            inner_holdout_gameweeks=inner_holdout_gameweeks,
            minimum_inner_training_gameweeks=minimum_inner_training_gameweeks,
            weight_step=weight_step,
            minimum_signal_coverage=minimum_signal_coverage,
            promoted_attack_prior=promoted_attack_prior,
            promoted_defence_prior=promoted_defence_prior,
            rate_floor=rate_floor,
            maximum_goals=maximum_goals,
        )
        self._selector_diagnostics: dict[str, Any] = {}

    @property
    def selector_diagnostics(self) -> dict[str, Any]:
        return copy.deepcopy(self._selector_diagnostics)

    def fit_as_of(self, frame: pl.DataFrame, as_of: AsOf) -> None:
        """Discard outer-target/future events before selection and fitting."""
        if not isinstance(as_of, AsOf):
            raise TypeError("as_of must be an AsOf")
        self._selector_diagnostics = {}
        self.fit(frame.filter(pl.col("kickoff_time") < as_of.ts))

    def _inner_batches(self, frame: pl.DataFrame) -> list[InnerBatch]:
        split = self._inner_split(frame)
        if split is None:
            return []
        _, holdout = split
        keys = (
            holdout.group_by(["season", "gw"], maintain_order=True)
            .agg(pl.col("kickoff_time").min().alias("cutoff"))
            .sort(["cutoff", "season", "gw"])
        )
        batches: list[InnerBatch] = []
        for row in keys.iter_rows(named=True):
            season, gw, cutoff = str(row["season"]), int(row["gw"]), row["cutoff"]
            same_gw = (pl.col("season") == season) & (pl.col("gw") == gw)
            # A postponed leg of H1 may occur after H2 starts. Never absorb a whole GW
            # merely because it was scored: rebuild from actual event-time eligibility.
            training = frame.filter((pl.col("kickoff_time") < cutoff) & ~same_gw)
            target = holdout.filter(same_gw)
            batches.append(InnerBatch(season, gw, cutoff, training, target))
        return batches

    def _select_decay_and_prior(
        self, frame: pl.DataFrame, priors: Priors
    ) -> tuple[float | None, float]:
        fallback: tuple[float | None, float] = (160.0, 8.0)
        self._selector_diagnostics = {"decay_prior": {"selected_score": None, "batches": []}}
        if "goals" not in frame.columns:
            return fallback
        split = self._inner_split(frame)
        if split is None or any(part.drop_nulls(["goals"]).is_empty() for part in split):
            return fallback
        batches = self._inner_batches(frame)
        best, best_score = fallback, math.inf
        for half_life in self._half_lives:
            weighted = []
            for batch in batches:
                inner = batch.training.drop_nulls(["goals"])
                latest = inner["kickoff_time"].max()
                assert isinstance(latest, datetime)
                weighted.append(self._weighted_fixtures(inner, "goals", latest, half_life))
            for prior in self._prior_matches:
                total, count = 0.0, 0
                for batch, fixtures in zip(batches, weighted, strict=True):
                    target = batch.target.drop_nulls(["goals"])
                    ratings = fit_ratings(
                        fixtures,
                        prior_attack=priors[0],
                        prior_defence=priors[1],
                        prior_matches=prior,
                        rate_floor=self._rate_floor,
                    )
                    total += target.height * self._holdout_log_score(
                        target, self._single_signal_rate(ratings)
                    )
                    count += target.height
                score = total / count
                # Fixed configured half-life order, then prior order. Exact equality keeps
                # the first candidate, just as the legacy strict comparison does.
                if score < best_score:
                    best, best_score = (half_life, prior), score
        self._selector_diagnostics["decay_prior"] = {
            "selected_score": best_score,
            "batches": [batch.as_report() for batch in batches],
            "half_life_order": list(self._half_lives),
            "prior_matches_order": list(self._prior_matches),
        }
        return best

    def _select_weights(
        self,
        frame: pl.DataFrame,
        priors: Priors,
        half_life: float | None,
        prior_matches: float,
    ) -> dict[str, float]:
        self._selector_diagnostics["weights"] = {"selected_score": None, "batches": []}
        blendable = sorted(self._fitted)
        if not blendable:
            return {}
        if len(blendable) == 1:
            return {blendable[0]: 1.0}
        fallback = dict.fromkeys(blendable, 1.0 / len(blendable))
        split = self._inner_split(frame)
        if split is None:
            return fallback
        inner, holdout = split
        if inner.is_empty() or holdout.drop_nulls(["goals"]).is_empty():
            return fallback
        batches = self._inner_batches(frame)
        # Preserve the legacy candidate weight dimensions: signals measured in the initial
        # inner window, not a licence inferred from later holdout coverage.
        available = [
            name for name in blendable if inner[self._fitted[name].spec.column].drop_nulls().len()
        ]
        if not available:
            return fallback
        if len(available) == 1:
            return {available[0]: 1.0}
        fitted = [
            _signal_fits(self, batch.training, available, priors, half_life, prior_matches)
            for batch in batches
        ]
        best_weights = dict.fromkeys(available, 1.0 / len(available))
        best_score = math.inf
        for point in simplex_grid(len(available), step=self._weight_step):
            weights = dict(zip(available, point, strict=True))
            total, count = 0.0, 0
            for batch, inner_fits in zip(batches, fitted, strict=True):
                target = batch.target.drop_nulls(["goals"])
                total += target.height * self._holdout_log_score(
                    target, self._blended_rate_of(weights, inner_fits)
                )
                count += target.height
            score = total / count
            if score < best_score:
                best_weights, best_score = weights, score
        self._selector_diagnostics["weights"] = {
            "selected_score": best_score,
            "signal_order": available,
            "batches": [
                {
                    **batch.as_report(),
                    "signal_scales": {name: signal.goal_scale for name, signal in fits.items()},
                }
                for batch, fits in zip(batches, fitted, strict=True)
            ],
        }
        return best_weights


def frozen_selected_inner_scores(
    engine: MultiSignalTeamEngine, frame: pl.DataFrame
) -> dict[str, float | None]:
    """Read-only diagnostic of the legacy selector's already-chosen setting, not a search."""
    scores: dict[str, float | None] = {"decay_prior": None, "weights": None}
    if "goals" not in frame.columns:
        return scores
    usable = frame.drop_nulls(["team_code", "opponent_team_code", "kickoff_time"]).sort(
        ["kickoff_time", "season", "fixture", "team_code"]
    )
    split = engine._inner_split(usable)
    if split is None:
        return scores
    inner, holdout = split
    target = holdout.drop_nulls(["goals"])
    goals = inner.drop_nulls(["goals"])
    if goals.is_empty() or target.is_empty():
        return scores
    policy, priors = engine.parameters, engine._priors()
    latest = goals["kickoff_time"].max()
    assert isinstance(latest, datetime)
    ratings = fit_ratings(
        engine._weighted_fixtures(goals, "goals", latest, policy.half_life_days),
        prior_attack=priors[0],
        prior_defence=priors[1],
        prior_matches=policy.prior_matches,
        rate_floor=engine._rate_floor,
    )
    scores["decay_prior"] = engine._holdout_log_score(target, engine._single_signal_rate(ratings))
    if len(engine.fitted_signals) > 1:
        fits = _signal_fits(
            engine,
            inner,
            sorted(engine.fitted_signals),
            priors,
            policy.half_life_days,
            policy.prior_matches,
        )
        if len(fits) > 1:
            scores["weights"] = engine._holdout_log_score(
                target, engine._blended_rate_of(policy.weights, fits)
            )
    return scores
