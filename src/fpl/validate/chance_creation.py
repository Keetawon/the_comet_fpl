"""Development-only prequential shot volume / xG-per-shot / conversion model.

Frozen out-of-sample style forecasts are inputs, never refitted here. The xG
estimator is a fractional-target Poisson quasi-likelihood MEAN model, not an xG
count distribution. Recorded goals alone receive the existing Poisson PMF.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import defaultdict
from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Any

from fpl.validate.metrics import Distribution, poisson_pmf
from fpl.validate.tactical_math import (
    Scaler,
    _cholesky_solve,
    _design,
    _dot,
    _finite,
    _penalty,
    fit_scaler,
)
from fpl.validate.tactical_numeric_solver import (
    ARMIJO,
    MAX_BACKTRACKS,
    MAX_ITERATIONS,
    ROUNDOFF_MULTIPLIER,
    TOLERANCE,
    NewtonDiagnostic,
    _objective_difference,
)

NAME = "retrospective_chance_creation_team_environment_v1"
EVIDENCE_CLASS = "retrospective_backfill_development"
SOLVER_ID = "fractional_poisson_mean_stable_difference_v1"
RIDGE = 1.0
MINIMUM_FIT_ROWS = 160
MINIMUM_CONVERSION_ROWS = 160
CONVERSION_PRIOR_EXPOSURE = 20.0
QUALITY_FLOOR = 1e-6
QUALITY_CEILING = 1.0
RATE_FLOOR = 0.05
MAX_GOALS = 10
type Vector = tuple[float | None, ...]


class ChanceMeanFitError(ValueError):
    """A failed numerical fit is evidence, never permission to use a fallback."""

    def __init__(self, reason: str, state: dict[str, Any]) -> None:
        self.state = {"solver": SOLVER_ID, "reason": reason, **state}
        super().__init__(f"{SOLVER_ID}: {reason}")


@dataclass(frozen=True, slots=True)
class FractionalPoissonMeanModel:
    scaler: Scaler
    coefficients: tuple[float, ...]
    penalty: float
    training_rows: int
    iterations: int
    objective: float
    final_gradient: tuple[float, ...]
    final_newton_step: tuple[float, ...]
    diagnostics: tuple[NewtonDiagnostic, ...]
    solver: str = SOLVER_ID
    converged: bool = True
    convergence_reason: str = "final_gradient_and_undamped_newton_step"

    def predict_mean(self, row: Sequence[float], offset: float) -> float:
        if not math.isfinite(offset) or offset <= 0:
            raise ValueError("prediction exposure/offset must be finite and positive")
        eta = math.log(offset) + _dot(_design(self.scaler, row), self.coefficients)
        if not math.isfinite(eta) or abs(eta) > 20:
            raise ValueError("prediction log mean outside fixed numerical safety bounds")
        return math.exp(eta)


def fit_fractional_poisson_mean(
    x: list[list[float]], targets: list[float], offsets: list[float], penalty: float
) -> FractionalPoissonMeanModel:
    """Minimise mean(exp(eta)-target*eta) + penalty*||beta||²/2.

    Finite nonnegative fractional labels (including exact zero) are accepted.
    Offsets are positive means/exposures, not their logarithms. The existing
    stable-difference numerical primitives/tolerances are reused unchanged;
    no goal-rate correction clipping applies to this separate architecture.
    """
    _penalty(penalty)
    if len(targets) != len(x) or len(offsets) != len(x):
        raise ValueError("targets and offsets must match predictor rows")
    if any(isinstance(y, bool) or not math.isfinite(y) or y < 0 for y in targets):
        raise ValueError("targets must be finite nonnegative measured values")
    if any(isinstance(o, bool) or not math.isfinite(o) or o <= 0 for o in offsets):
        raise ValueError("offsets must be finite and strictly positive")
    log_offsets = [math.log(o) for o in offsets]
    if any(abs(value) > 20 for value in log_offsets):
        raise ValueError("offset log mean outside fixed numerical safety bounds")
    scaler = fit_scaler(x)
    design = [_design(scaler, row) for row in x]
    count, width = len(x), len(design[0])
    beta = (0.0,) * width
    trace: list[NewtonDiagnostic] = []

    def levels(coefficients: Sequence[float]) -> list[float]:
        return [o + _dot(row, coefficients) for o, row in zip(log_offsets, design, strict=True)]

    for iteration in range(MAX_ITERATIONS + 1):
        eta = levels(beta)
        state: dict[str, Any] = {
            "penalty": penalty,
            "iteration": iteration,
            "training_rows": count,
            "design_width": width,
            "coefficients": beta,
            "eta_minimum": min(eta),
            "eta_maximum": max(eta),
            "trace": [asdict(item) for item in trace],
        }
        if any(not math.isfinite(value) or abs(value) > 20 for value in eta):
            raise ChanceMeanFitError("current eta outside safety bounds", state)
        rates = [math.exp(value) for value in eta]
        objective = (
            math.fsum(mu - y * e for mu, y, e in zip(rates, targets, eta, strict=True)) / count
            + penalty * _dot(beta, beta) / 2
        )
        gradient = tuple(
            math.fsum(row[j] * (mu - y) for row, mu, y in zip(design, rates, targets, strict=True))
            / count
            + penalty * beta[j]
            for j in range(width)
        )
        hessian = [
            [
                math.fsum(mu * row[i] * row[j] for row, mu in zip(design, rates, strict=True))
                / count
                + (penalty if i == j else 0)
                for j in range(width)
            ]
            for i in range(width)
        ]
        allowance = (
            ROUNDOFF_MULTIPLIER
            * sys.float_info.epsilon
            * max(
                math.fsum(
                    abs(row[j]) * (mu + y)
                    for row, mu, y in zip(design, rates, targets, strict=True)
                )
                / count
                + penalty * abs(beta[j])
                for j in range(width)
            )
        )
        gradient_norm = max(abs(value) for value in gradient)
        gradient_tolerance = TOLERANCE + allowance
        step_tolerance = TOLERANCE * (1 + max(abs(value) for value in beta))
        state.update(
            objective=objective,
            gradient=gradient,
            gradient_infinity_norm=gradient_norm,
            gradient_roundoff_allowance=allowance,
            gradient_tolerance=gradient_tolerance,
            step_tolerance=step_tolerance,
        )
        try:
            step = _cholesky_solve(hessian, gradient)
        except ValueError as exc:
            raise ChanceMeanFitError("Newton system solve failed", state) from exc
        step_norm, decrement = max(abs(v) for v in step), _dot(gradient, step)
        state.update(newton_step=step, newton_decrement_squared=decrement)
        if not math.isfinite(decrement) or decrement < 0:
            raise ChanceMeanFitError("Newton direction is not finite descent", state)
        diagnostic = NewtonDiagnostic(
            iteration,
            objective,
            gradient_norm,
            allowance,
            gradient_tolerance,
            step_norm,
            step_tolerance,
            decrement,
            min(eta),
            max(eta),
            None,
            0,
            None,
            None,
        )
        if gradient_norm <= gradient_tolerance and step_norm <= step_tolerance:
            trace.append(diagnostic)
            return FractionalPoissonMeanModel(
                scaler, beta, penalty, count, iteration, objective, gradient, step, tuple(trace)
            )
        if iteration == MAX_ITERATIONS:
            raise ChanceMeanFitError("bounded Newton iteration limit exhausted", state)
        if decrement == 0:
            raise ChanceMeanFitError("zero descent outside convergence tolerance", state)
        trials: list[dict[str, Any]] = []
        for backtrack in range(MAX_BACKTRACKS):
            fraction = 0.5**backtrack
            proposed = tuple(b - fraction * s for b, s in zip(beta, step, strict=True))
            delta = tuple(new - old for new, old in zip(proposed, beta, strict=True))
            next_eta = levels(proposed)
            safe = all(math.isfinite(e) and abs(e) <= 20 for e in next_eta)
            bound = ARMIJO * _dot(gradient, delta)
            difference = (
                _objective_difference(design, rates, gradient, delta, penalty) if safe else None
            )
            trials.append(
                {
                    "fraction": fraction,
                    "safe_eta": safe,
                    "objective_difference": difference,
                    "armijo_bound": bound,
                }
            )
            if (
                safe
                and proposed != beta
                and bound < 0
                and difference is not None
                and math.isfinite(difference)
                and difference <= bound
            ):
                trace.append(
                    replace(
                        diagnostic,
                        accepted_fraction=fraction,
                        backtracking_trials=backtrack + 1,
                        objective_difference=difference,
                        armijo_bound=bound,
                    )
                )
                beta = proposed
                break
        else:
            state["backtracking"] = trials
            raise ChanceMeanFitError("bounded backtracking found no safe descent", state)
    raise AssertionError("bounded Newton loop must return or fail")


@dataclass(frozen=True, slots=True)
class ChanceObservation:
    season: str
    gw: int
    fixture: int
    team_code: int
    opponent_team_code: int
    was_home: bool
    kickoff: datetime
    as_of: datetime
    goals: int
    shots: int | None
    expected_goals: float | None
    predicted_state: Vector
    predicted_opponent_state: Vector
    incumbent_rate: float
    opponent_incumbent_rate: float
    incumbent_pmf: Distribution
    maximum_state_source_event: datetime | None = None
    maximum_style_training_event: datetime | None = None

    @property
    def key(self) -> str:
        return f"{self.season}:{self.fixture}:{self.team_code}"


def predictors(row: ChanceObservation) -> list[float] | None:
    """Only pre-match fields; neither targets nor realised tactical errors enter."""
    values = (*row.predicted_state, *row.predicted_opponent_state)
    if any(value is None for value in values):
        return None
    return [
        *[float(value) for value in values if value is not None],
        float(row.was_home),
        math.log(row.incumbent_rate),
        math.log(row.opponent_incumbent_rate),
    ]


def _keys(rows: Sequence[ChanceObservation]) -> str:
    return hashlib.sha256(
        json.dumps(sorted(row.key for row in rows), separators=(",", ":")).encode()
    ).hexdigest()


def _provenance(rows: Sequence[ChanceObservation]) -> dict[str, Any]:
    return {
        "training_rows": len(rows),
        "training_keys_sha256": _keys(rows),
        "maximum_training_event": max(row.kickoff for row in rows).isoformat() if rows else None,
        "maximum_training_prediction_cutoff": max(row.as_of for row in rows).isoformat()
        if rows
        else None,
    }


def _validate(observations: Sequence[ChanceObservation]) -> None:
    keyed = {row.key: row for row in observations}
    if not observations or len(keyed) != len(observations):
        raise ValueError("nonempty unique chance-observation identities required")
    for row in observations:
        timestamps = (
            row.kickoff,
            row.as_of,
            row.maximum_state_source_event,
            row.maximum_style_training_event,
        )
        if any(t is not None and t.utcoffset() is None for t in timestamps):
            raise ValueError("chance timestamps must be timezone aware")
        if row.as_of > row.kickoff or any(t is not None and t >= row.as_of for t in timestamps[2:]):
            raise ValueError("style predictors contain same-match or future observations")
        if (
            isinstance(row.goals, bool)
            or not isinstance(row.goals, int)
            or row.goals < 0
            or (
                row.shots is not None
                and (isinstance(row.shots, bool) or not isinstance(row.shots, int) or row.shots < 0)
            )
        ):
            raise ValueError("goals/shots must be measured nonnegative integers")
        if row.expected_goals is not None and (
            isinstance(row.expected_goals, bool)
            or not math.isfinite(row.expected_goals)
            or row.expected_goals < 0
        ):
            raise ValueError("archive xG must be finite nonnegative or missing")
        if row.shots == 0 and row.expected_goals is not None and row.expected_goals > 0:
            raise ValueError("positive xG with zero shot exposure is contradictory")
        if len(row.predicted_state) != 5 or len(row.predicted_opponent_state) != 5:
            raise ValueError("exactly five fixed style dimensions per side required")
        _finite([v for v in (*row.predicted_state, *row.predicted_opponent_state) if v is not None])
        _finite((row.incumbent_rate, row.opponent_incumbent_rate, *row.incumbent_pmf))
        if (
            min(row.incumbent_rate, row.opponent_incumbent_rate) <= 0
            or len(row.incumbent_pmf) != MAX_GOALS + 1
            or min(row.incumbent_pmf) < 0
            or not math.isclose(math.fsum(row.incumbent_pmf), 1, rel_tol=0, abs_tol=1e-9)
        ):
            raise ValueError("positive incumbent rates and full 0..10 PMF required")
        other = keyed.get(f"{row.season}:{row.fixture}:{row.opponent_team_code}")
        if (
            other is None
            or other.opponent_team_code != row.team_code
            or other.was_home == row.was_home
            or other.gw != row.gw
            or other.kickoff != row.kickoff
            or other.as_of != row.as_of
            or other.predicted_state != row.predicted_opponent_state
            or other.incumbent_rate != row.opponent_incumbent_rate
        ):
            raise ValueError("fixture sides, styles and incumbent rates must be reciprocal")


def _fit_stages(
    prior: Sequence[ChanceObservation],
) -> tuple[
    FractionalPoissonMeanModel | None,
    FractionalPoissonMeanModel | None,
    float | None,
    float | None,
    dict[str, Any],
]:
    volume_rows = [r for r in prior if r.shots is not None and predictors(r) is not None]
    quality_rows = [r for r in volume_rows if r.shots and r.expected_goals is not None]
    volume_anchor = (
        math.fsum(float(r.shots) for r in volume_rows if r.shots is not None) / len(volume_rows)
        if volume_rows
        else None
    )
    exposure = math.fsum(float(r.shots) for r in quality_rows if r.shots is not None)
    quality_anchor = (
        math.fsum(float(r.expected_goals) for r in quality_rows if r.expected_goals is not None)
        / exposure
        if exposure
        else None
    )
    models: list[FractionalPoissonMeanModel | None] = []
    diagnostics: dict[str, Any] = {}
    for name, rows, anchor in (
        ("volume", volume_rows, volume_anchor),
        ("quality", quality_rows, quality_anchor),
    ):
        model = None
        if len(rows) >= MINIMUM_FIT_ROWS and anchor is not None and anchor > 0:
            x = [value for r in rows if (value := predictors(r)) is not None]
            if name == "volume":
                targets = [float(r.shots) for r in rows if r.shots is not None]
                offsets = [anchor] * len(rows)
            else:
                targets = [float(r.expected_goals) for r in rows if r.expected_goals is not None]
                offsets = [float(r.shots) * anchor for r in rows if r.shots is not None]
            try:
                model = fit_fractional_poisson_mean(x, targets, offsets, RIDGE)
            except Exception as error:
                error.add_note(f"chance_creation stage={name} rows={len(rows)} anchor={anchor}")
                raise
        models.append(model)
        diagnostics[name] = {
            **_provenance(rows),
            "anchor": anchor,
            "mode": "fitted" if model is not None else "insufficient_history_or_positive_anchor",
            "model": asdict(model) if model is not None else None,
        }
    return models[0], models[1], volume_anchor, quality_anchor, diagnostics


def pooled_conversion(
    earlier: Sequence[tuple[ChanceObservation, dict[str, Any]]],
) -> tuple[float | None, dict[str, Any]]:
    measured = [
        (r, p)
        for r, p in earlier
        if r.shots is not None
        and r.shots > 0
        and r.expected_goals is not None
        and p["predicted_xg"] is not None
    ]
    exposure = math.fsum(float(p["predicted_xg"]) for _, p in measured)
    goals = sum(r.goals for r, _ in measured)
    conversion = (
        (goals + CONVERSION_PRIOR_EXPOSURE) / (exposure + CONVERSION_PRIOR_EXPOSURE)
        if len(measured) >= MINIMUM_CONVERSION_ROWS
        else None
    )
    return conversion, {
        **_provenance([r for r, _ in measured]),
        "recorded_goals": goals,
        "oos_predicted_xg_exposure": exposure,
        "prior_exposure": CONVERSION_PRIOR_EXPOSURE,
        "prior_conversion": 1.0,
        "conversion": conversion,
    }


def run_chance_walk_forward(
    observations: Sequence[ChanceObservation],
    eligible_seasons: tuple[str, ...],
    *,
    checkpoint: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """One deterministic pass; complete GW batches precede observation absorption."""
    _validate(observations)
    batches: dict[tuple[str, int], list[ChanceObservation]] = defaultdict(list)
    for observation in observations:
        batches[observation.season, observation.gw].append(observation)
    ordered = sorted(batches, key=lambda k: (min(r.kickoff for r in batches[k]), *k))
    eligible = [key for key in ordered if key[0] in eligible_seasons]
    if not eligible:
        raise ValueError("no coverage-eligible chance gameweeks")
    ordered = ordered[: ordered.index(eligible[-1]) + 1]
    history: list[tuple[ChanceObservation, dict[str, Any]]] = []
    folds: list[dict[str, Any]] = []
    historical_folds: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for season, gw in ordered:
        batch = sorted(batches[season, gw], key=lambda r: (r.kickoff, r.fixture, r.team_code))
        cutoff = min(r.kickoff for r in batch)
        if any(r.as_of != cutoff for r in batch):
            raise ValueError("all fixtures in a GW must use its first-kickoff cutoff")
        prior = [
            (r, p) for r, p in history if r.kickoff < cutoff and (r.season, r.gw) != (season, gw)
        ]
        try:
            volume, quality, volume_anchor, quality_anchor, fits = _fit_stages(
                [r for r, _ in prior]
            )
        except Exception as error:
            error.add_note(f"chance_creation season={season} gw={gw} cutoff={cutoff.isoformat()}")
            raise
        conversion, conversion_report = pooled_conversion(prior)
        pending: list[tuple[ChanceObservation, dict[str, Any]]] = []
        for r in batch:
            x = predictors(r)
            shots_prediction = quality_raw = quality_prediction = predicted_xg = None
            if x is not None and volume is not None and volume_anchor is not None:
                shots_prediction = volume.predict_mean(x, volume_anchor)
            if x is not None and quality is not None and quality_anchor is not None:
                quality_raw = quality.predict_mean(x, quality_anchor)
                quality_prediction = max(QUALITY_FLOOR, min(QUALITY_CEILING, quality_raw))
            if shots_prediction is not None and quality_prediction is not None:
                predicted_xg = shots_prediction * quality_prediction
            raw_rate = (
                predicted_xg * conversion
                if predicted_xg is not None and conversion is not None
                else None
            )
            rate = max(RATE_FLOOR, raw_rate) if raw_rate is not None else r.incumbent_rate
            pmf = (
                poisson_pmf(rate, max_goals=MAX_GOALS) if raw_rate is not None else r.incumbent_pmf
            )
            row: dict[str, Any] = {
                "key": r.key,
                "season": season,
                "gw": gw,
                "fixture": r.fixture,
                "team_code": r.team_code,
                "opponent_team_code": r.opponent_team_code,
                "was_home": r.was_home,
                "as_of": cutoff.isoformat(),
                "kickoff_time": r.kickoff.isoformat(),
                "observed_goals": r.goals,
                "observed_shots": r.shots,
                "observed_archive_xg": r.expected_goals,
                "predictors": x,
                "predicted_state": r.predicted_state,
                "predicted_opponent_state": r.predicted_opponent_state,
                "maximum_state_source_event": r.maximum_state_source_event.isoformat()
                if r.maximum_state_source_event
                else None,
                "maximum_style_training_event": r.maximum_style_training_event.isoformat()
                if r.maximum_style_training_event
                else None,
                "predicted_shots": shots_prediction,
                "predicted_quality_raw": quality_raw,
                "predicted_quality": quality_prediction,
                "predicted_xg": predicted_xg,
                "conversion": conversion,
                "unfloored_goal_rate": raw_rate,
                "candidate_latent_rate": rate,
                "incumbent_latent_rate": r.incumbent_rate,
                "incumbent_fallback": raw_rate is None,
                "outer_scored": season in eligible_seasons,
                "evidence_class": EVIDENCE_CLASS,
                "distributions": {"incumbent": r.incumbent_pmf, "candidate": pmf},
                "log_rate_attribution": {
                    "volume": math.log(shots_prediction) if shots_prediction is not None else None,
                    "quality": math.log(quality_prediction)
                    if quality_prediction is not None
                    else None,
                    "conversion": math.log(conversion) if conversion is not None else None,
                    "floor_adjustment": math.log(rate / raw_rate) if raw_rate else None,
                    "relative_to_incumbent": math.log(rate / r.incumbent_rate),
                },
            }
            pending.append((r, row))
        keyed = {r.key: row for r, row in pending}
        targets = {r.key: r for r in batch}
        for r, row in pending:
            key = f"{season}:{r.fixture}:{r.opponent_team_code}"
            row["goals_allowed"] = targets[key].goals
            row["observed_clean_sheet"] = targets[key].goals == 0
            row["clean_sheet_probabilities"] = {
                arm: pmf[0] for arm, pmf in keyed[key]["distributions"].items()
            }
        report = {
            "season": season,
            "gw": gw,
            "as_of": cutoff.isoformat(),
            "target_rows": len(batch),
            "prior_completed_rows": len(prior),
            "stage_fits": fits,
            "conversion_fit": conversion_report,
            "fixed_ridge": RIDGE,
            "event_time_violations": 0,
            "same_gameweek_violations": 0,
            "stacking_in_sample_rows": 0,
        }
        historical_folds.append(report)
        if season in eligible_seasons:
            folds.append(report)
            rows.extend(row for _, row in pending)
        history.extend(pending)
        if checkpoint is not None:
            checkpoint(deepcopy({"fold": report, "rows": [row for _, row in pending]}))
    return {
        "rows": rows,
        "folds": folds,
        "history_rows": [row for _, row in history],
        "historical_folds": historical_folds,
    }


def chance_target_metrics(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Read-only stage diagnostics; fractional xG is never scored as an integer count."""
    report: dict[str, Any] = {}
    for name, prediction, actual in (
        ("volume", "predicted_shots", "observed_shots"),
        ("xg", "predicted_xg", "observed_archive_xg"),
    ):
        pairs = [
            (float(r[prediction]), float(r[actual]))
            for r in rows
            if r[prediction] is not None and r[actual] is not None
        ]
        report[name] = {
            "rows": len(pairs),
            "mae": math.fsum(abs(p - y) for p, y in pairs) / len(pairs) if pairs else None,
            "rmse": math.sqrt(math.fsum((p - y) ** 2 for p, y in pairs) / len(pairs))
            if pairs
            else None,
            "mean_error": math.fsum(p - y for p, y in pairs) / len(pairs) if pairs else None,
        }
    quality_pairs = [
        (float(r["predicted_quality"]), float(r["observed_archive_xg"]), float(r["observed_shots"]))
        for r in rows
        if r["predicted_quality"] is not None
        and r["observed_archive_xg"] is not None
        and r["observed_shots"] is not None
        and r["observed_shots"] > 0
    ]
    exposure = math.fsum(shots for _, _, shots in quality_pairs)
    report["quality"] = {
        "rows": len(quality_pairs),
        "shot_exposure": exposure,
        "exposure_weighted_mae": math.fsum(
            abs(p - xg / shots) * shots for p, xg, shots in quality_pairs
        )
        / exposure
        if exposure
        else None,
        "exposure_weighted_rmse": math.sqrt(
            math.fsum((p - xg / shots) ** 2 * shots for p, xg, shots in quality_pairs) / exposure
        )
        if exposure
        else None,
    }
    return report
