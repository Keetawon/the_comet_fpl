"""Pure prequential tactical matchup experiment; no data access or formal-run entry.

Every historical style prediction is made before its complete GW batch and is
never overwritten by a later fit. Goal fitting consumes only those OOS records
whose actual event has occurred. Cached per-penalty forecasts are consequently
the same forecasts an inner weekly refit would have made.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections import defaultdict
from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Literal

from fpl.validate.metrics import Distribution, log_score
from fpl.validate.tactical_math import (
    PoissonOffsetModel,
    RidgeModel,
    adjusted_pmf,
    fit_poisson_offset,
    fit_ridge,
)
from fpl.validate.tactical_state import DIMENSIONS, StateEstimate, TacticalObservation
from fpl.validate.tactical_state import current_state as estimate_state

logger = logging.getLogger(__name__)
PENALTIES: tuple[float | None, ...] = (None, 10.0, 1.0, 0.1)
MINIMUM_FIT_ROWS = 160
STYLE_PENALTY = 1.0
INNER_GAMEWEEKS = 6
MINIMUM_INNER_HISTORY = 10
TIE_TOLERANCE = 1e-12
RECENT_DIAGNOSTIC = "recent_state_only_no_interactions"
PREDICTED_DIAGNOSTIC = "predicted_state_no_interactions"
type Vector = tuple[float | None, ...]
type GoalKind = Literal["goal_x", "recent_x", "predicted_x"]
type GoalFitter = Callable[[list[list[float]], list[int], list[float], float], PoissonOffsetModel]


def observation_key(row: TacticalObservation) -> str:
    return f"{row.season}:{row.fixture}:{row.team_code}"


def _hash(keys: Sequence[str]) -> str:
    return hashlib.sha256(json.dumps(sorted(keys), separators=(",", ":")).encode()).hexdigest()


def _complete(values: Sequence[float | None]) -> list[float] | None:
    return (
        [float(value) for value in values if value is not None]
        if all(value is not None for value in values)
        else None
    )


def _clip_state(dimension: int, value: float) -> float:
    if dimension in (0, 2, 3):
        return max(0.0, min(1.0, value))
    return max(0.0, value) if dimension == 1 else min(0.0, value)


def matchup_features(own: Vector, opponent: Vector, *, interactions: bool) -> list[float] | None:
    values = _complete((*own, *opponent))
    if values is None:
        return None
    if len(values) != 10:
        raise ValueError("matchup needs five predicted dimensions per side")
    if interactions:
        values.extend((values[0] * values[9], values[1] * values[9], values[3] * values[7]))
    return values


def select_penalty(scores: Sequence[float]) -> float | None:
    """Fixed ordering; numerical ties favour disabled, then stronger shrinkage."""
    if len(scores) != len(PENALTIES) or any(not math.isfinite(value) for value in scores):
        raise ValueError("exactly four finite inner scores are required")
    minimum = min(scores)
    return next(
        penalty
        for penalty, score in zip(PENALTIES, scores, strict=True)
        if score <= minimum + TIE_TOLERANCE
    )


@dataclass(slots=True)
class _Record:
    observation: TacticalObservation
    row: dict[str, Any]
    style_x: list[float] | None
    goal_x: list[float] | None
    recent_x: list[float] | None
    predicted_x: list[float] | None
    pmfs: dict[float | None, Distribution]
    standardized_error: Vector


def _provenance(records: Sequence[_Record]) -> dict[str, Any]:
    return {
        "training_rows": len(records),
        "training_keys_sha256": _hash([observation_key(row.observation) for row in records]),
        "maximum_training_event": max(row.observation.kickoff for row in records).isoformat()
        if records
        else None,
        "maximum_training_prediction_cutoff": max(
            (str(row.row["as_of"]) for row in records), default=None
        ),
    }


def _stacking_violations(records: Sequence[_Record]) -> int:
    violations = 0
    for record in records:
        prediction_cutoff = datetime.fromisoformat(str(record.row["as_of"]))
        violations += int(prediction_cutoff > record.observation.kickoff)
        for name in ("maximum_state_source_event", "maximum_style_training_event"):
            timestamp = record.row.get(name)
            if timestamp is not None:
                violations += int(datetime.fromisoformat(str(timestamp)) >= prediction_cutoff)
    return violations


def _fit_time_violations(diagnostics: Sequence[dict[str, Any]], cutoff: datetime) -> int:
    return sum(
        int(datetime.fromisoformat(str(timestamp)) >= cutoff)
        for fit in diagnostics
        for field in ("maximum_training_event", "maximum_training_prediction_cutoff")
        if (timestamp := fit[field]) is not None
    )


def _style_fits(
    prior: Sequence[_Record],
) -> tuple[list[RidgeModel | None], dict[str, Any]]:
    models: list[RidgeModel | None] = []
    diagnostics: dict[str, Any] = {}
    for dimension, name in enumerate(DIMENSIONS):
        rows: list[_Record] = []
        x: list[list[float]] = []
        y: list[list[float]] = []
        for record in prior:
            target = record.observation.values[dimension]
            if record.style_x is not None and target is not None:
                rows.append(record)
                x.append(record.style_x)
                y.append([target - record.style_x[dimension]])
        model = fit_ridge(x, y, STYLE_PENALTY) if len(rows) >= MINIMUM_FIT_ROWS else None
        models.append(model)
        diagnostics[name] = {
            **_provenance(rows),
            "mode": "ridge_delta" if model is not None else "persistence",
            "model": asdict(model) if model is not None else None,
        }
    return models, diagnostics


def _goal_fit(
    prior: Sequence[_Record],
    incumbent: dict[str, tuple[float, Distribution]],
    penalty: float,
    kind: GoalKind,
    *,
    goal_fitter: GoalFitter = fit_poisson_offset,
    context: str = "",
) -> tuple[PoissonOffsetModel | None, dict[str, Any]]:
    rows = [record for record in prior if getattr(record, kind) is not None]
    x: list[list[float]] = [getattr(record, kind) for record in rows]
    goals = [record.observation.goals for record in rows]
    rates = [incumbent[observation_key(record.observation)][0] for record in rows]
    model = None
    if len(rows) >= MINIMUM_FIT_ROWS:
        fit_identity = hashlib.sha256(
            json.dumps([x, goals, rates, penalty], separators=(",", ":")).encode()
        ).hexdigest()
        fit_context = (
            f"{context} kind={kind} penalty={penalty} rows={len(rows)} input_sha256={fit_identity}"
        )
        logger.info("Tactical goal fit: %s", fit_context)
        try:
            model = goal_fitter(x, goals, rates, penalty)
        except Exception as error:
            error.add_note(fit_context)
            raise
    if model is not None and not model.converged:
        raise ValueError(f"Poisson tactical correction did not converge: {kind}, penalty={penalty}")
    return model, {
        **_provenance(rows),
        "mode": "poisson_offset" if model is not None else "incumbent_insufficient_history",
        "model": asdict(model) if model is not None else None,
    }


def _selection(prior: Sequence[_Record]) -> tuple[float | None, dict[str, Any]]:
    gameweeks: dict[tuple[str, int], str] = {}
    for record in prior:
        observation = record.observation
        gameweeks[observation.season, observation.gw] = str(record.row["as_of"])
    ordered = sorted(gameweeks, key=lambda key: (gameweeks[key], *key))
    if len(ordered) < MINIMUM_INNER_HISTORY + INNER_GAMEWEEKS:
        return None, {
            "mode": "disabled_insufficient_inner_history",
            "available_gameweeks": len(ordered),
            "holdout_gameweeks": [],
            "scores": [],
            "scored_rows": 0,
        }
    holdout = ordered[-INNER_GAMEWEEKS:]
    eligible = [
        record for record in prior if (record.observation.season, record.observation.gw) in holdout
    ]
    scores = [
        math.fsum(log_score(record.pmfs[penalty], record.observation.goals) for record in eligible)
        / len(eligible)
        for penalty in PENALTIES
    ]
    chosen = select_penalty(scores)
    return chosen, {
        "mode": "cached_prequential_weekly_refit",
        "available_gameweeks": len(ordered),
        "holdout_gameweeks": holdout,
        "scores": [
            {"penalty": penalty, "mean_log_score": value}
            for penalty, value in zip(PENALTIES, scores, strict=True)
        ],
        "scored_rows": len(eligible),
        **_provenance(eligible),
    }


def _prior_scale(prior: Sequence[TacticalObservation]) -> tuple[float | None, ...]:
    scales: list[float | None] = []
    for dimension in range(5):
        values = [row.values[dimension] for row in prior if row.values[dimension] is not None]
        measured = [float(value) for value in values if value is not None]
        if len(measured) < 2:
            scales.append(None)
        else:
            average = math.fsum(measured) / len(measured)
            scale = math.sqrt(
                math.fsum((value - average) ** 2 for value in measured) / len(measured)
            )
            scales.append(scale if scale > 0 else None)
    return tuple(scales)


def _risk(prior: Sequence[_Record], team_code: int) -> tuple[str, float | None]:
    latest = sorted(
        (row for row in prior if row.observation.team_code == team_code),
        key=lambda row: (row.observation.kickoff, row.observation.fixture),
        reverse=True,
    )[:5]
    errors = [
        math.fsum(measured) / len(measured)
        for row in latest
        if (measured := [value for value in row.standardized_error if value is not None])
    ]
    if not errors:
        return "unknown", None
    average = math.fsum(errors) / len(errors)
    return ("high" if average > 1 else "low"), average


def _prediction(
    own: StateEstimate, opponent: StateEstimate, was_home: bool, models: list[RidgeModel | None]
) -> tuple[list[float] | None, Vector, Vector, Vector]:
    x = _complete((*own.values, *opponent.values, float(was_home)))
    predicted: list[float | None] = []
    venue: list[float | None] = []
    opposition: list[float | None] = []
    for dimension, model in enumerate(models):
        recent = own.values[dimension]
        if x is None or model is None:
            predicted.append(recent)
            venue.append(0.0 if recent is not None else None)
            opposition.append(0.0 if recent is not None else None)
        else:
            scaled = model.scaler.transform(x)
            delta = model.predict(x)[0]
            predicted.append(_clip_state(dimension, x[dimension] + delta))
            venue.append(model.coefficients[0][11] * scaled[10])
            opposition.append(
                math.fsum(model.coefficients[0][j + 1] * scaled[j] for j in range(5, 10))
            )
    return x, tuple(predicted), tuple(venue), tuple(opposition)


def _validate(
    observations: Sequence[TacticalObservation], incumbent: dict[str, tuple[float, Distribution]]
) -> None:
    keyed = {row.key: row for row in observations}
    if len(keyed) != len(observations):
        raise ValueError("duplicate tactical observation identity")
    for row in observations:
        opponent = keyed.get((row.season, row.fixture, row.opponent_team_code))
        if (
            opponent is None
            or opponent.opponent_team_code != row.team_code
            or opponent.was_home == row.was_home
            or opponent.kickoff != row.kickoff
            or opponent.gw != row.gw
            or opponent.goals != row.goals_allowed
            or opponent.goals_allowed != row.goals
        ):
            raise ValueError(f"non-reciprocal fixture sides: {row.key}")
        key = observation_key(row)
        if key not in incumbent:
            raise ValueError(f"missing incumbent prediction: {key}")
        rate, pmf = incumbent[key]
        adjusted_pmf(rate, pmf, 0.0)


def run_tactical_walk_forward(
    observations: list[TacticalObservation],
    incumbent: dict[str, tuple[float, Distribution]],
    eligible_seasons: tuple[str, ...],
    *,
    goal_fitter: GoalFitter = fit_poisson_offset,
    checkpoint: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run one pure prequential pass, with no scoring-derived feature decisions."""
    _validate(observations, incumbent)
    batches: dict[tuple[str, int], list[TacticalObservation]] = defaultdict(list)
    for observation in observations:
        batches[observation.season, observation.gw].append(observation)
    ordered = sorted(batches, key=lambda key: (min(row.kickoff for row in batches[key]), *key))
    eligible = [key for key in ordered if key[0] in eligible_seasons]
    if not eligible:
        raise ValueError("no eligible tactical gameweeks")
    last = ordered.index(eligible[-1])
    ordered = ordered[: last + 1]
    history: list[_Record] = []
    folds: list[dict[str, Any]] = []
    historical_folds: list[dict[str, Any]] = []
    outer_rows: list[dict[str, Any]] = []
    for index, (season, gw) in enumerate(ordered, 1):
        batch = sorted(
            batches[season, gw], key=lambda row: (row.kickoff, row.fixture, row.team_code)
        )
        cutoff = min(row.kickoff for row in batch)
        prior = [row for row in history if row.observation.kickoff < cutoff]
        visible = [
            row
            for row in observations
            if row.kickoff < cutoff and (row.season, row.gw) != (season, gw)
        ]
        event_violations = sum(row.observation.kickoff >= cutoff for row in prior)
        gameweek_violations = sum(
            (row.observation.season, row.observation.gw) == (season, gw) for row in prior
        )
        stacking_violations = _stacking_violations(prior)
        if event_violations or gameweek_violations or stacking_violations:
            raise ValueError("event, target GW, or in-sample stacking entered tactical history")
        logger.info("Tactical prequential GW %s/%s: %s GW%s", index, len(ordered), season, gw)
        fit_context = f"season={season} gw={gw} cutoff={cutoff.isoformat()}"
        style_models, style_diagnostics = _style_fits(prior)
        goal_models: dict[float, PoissonOffsetModel | None] = {}
        goal_diagnostics: dict[str, Any] = {}
        for penalty in PENALTIES[1:]:
            assert penalty is not None
            goal_models[penalty], goal_diagnostics[str(penalty)] = _goal_fit(
                prior, incumbent, penalty, "goal_x", goal_fitter=goal_fitter, context=fit_context
            )
        chosen, selection = _selection(prior)
        diagnostic_models: dict[str, PoissonOffsetModel | None] = {}
        diagnostic_fits: dict[str, Any] = {}
        if season in eligible_seasons and chosen is not None:
            diagnostic_kinds: tuple[tuple[str, GoalKind], ...] = (
                (RECENT_DIAGNOSTIC, "recent_x"),
                (PREDICTED_DIAGNOSTIC, "predicted_x"),
            )
            for name, kind in diagnostic_kinds:
                diagnostic_models[name], diagnostic_fits[name] = _goal_fit(
                    prior, incumbent, chosen, kind, goal_fitter=goal_fitter, context=fit_context
                )
        fit_time_violations = _fit_time_violations(
            [*style_diagnostics.values(), *goal_diagnostics.values(), *diagnostic_fits.values()],
            cutoff,
        )
        if fit_time_violations:
            raise ValueError("tactical model fit contains a future event or prediction")
        states = {
            team: estimate_state(observations, team, season, cutoff, gw)
            for team in sorted({row.team_code for row in batch})
        }
        scales = _prior_scale(visible)
        source_keys = sorted({key for state in states.values() for key in state.source_keys})
        target_source_overlap = len(set(source_keys) & {row.key for row in batch})
        if target_source_overlap:
            raise ValueError("target fixture entered current-state source rows")
        style_training_events = [
            fit["maximum_training_event"]
            for fit in style_diagnostics.values()
            if fit["maximum_training_event"] is not None
        ]
        source_report = {
            "state_source_keys_sha256": _hash(
                [f"{s}:{fixture}:{team}" for s, fixture, team in source_keys]
            ),
            "state_source_rows": len(source_keys),
            "maximum_state_source_event": max(row.kickoff for row in visible).isoformat()
            if visible
            else None,
            "maximum_style_training_event": max(style_training_events, default=None),
        }
        pending: dict[str, _Record] = {}
        for observation in batch:
            own = states[observation.team_code]
            opponent_state = states[observation.opponent_team_code]
            x, predicted, venue, opposition = _prediction(
                own, opponent_state, observation.was_home, style_models
            )
            actual = observation.values
            standardized = tuple(
                ((target - forecast) / scale) ** 2
                if target is not None and forecast is not None and scale is not None
                else None
                for target, forecast, scale in zip(actual, predicted, scales, strict=True)
            )
            persistence_error = tuple(
                ((target - recent) / scale) ** 2
                if target is not None and recent is not None and scale is not None
                else None
                for target, recent, scale in zip(actual, own.values, scales, strict=True)
            )
            risk, prior_error = _risk(prior, observation.team_code)
            key = observation_key(observation)
            rate, pmf = incumbent[key]
            row: dict[str, Any] = {
                "key": key,
                "outer_scored": season in eligible_seasons,
                "diagnostic_arms_evaluated": season in eligible_seasons,
                "season": season,
                "gw": gw,
                "fixture": observation.fixture,
                "team_code": observation.team_code,
                "opponent_team_code": observation.opponent_team_code,
                "was_home": observation.was_home,
                "kickoff_time": observation.kickoff.isoformat(),
                "as_of": cutoff.isoformat(),
                "observed_goals": observation.goals,
                "goals_allowed": observation.goals_allowed,
                "incumbent_latent_rate": rate,
                "current_state": own.values,
                "opponent_state": opponent_state.values,
                "recent_raw": own.recent_raw,
                "opponent_recent_raw": opponent_state.recent_raw,
                "recent_counts": own.counts,
                "opponent_counts": opponent_state.counts,
                "state_prior": own.prior,
                "actual_state": actual,
                "predicted_state": predicted,
                "persistence_prediction": own.values,
                "style_predictors": x,
                "style_standardized_squared_error": standardized,
                "persistence_standardized_squared_error": persistence_error,
                "prior_style_target_sd": scales,
                "style_venue_contribution": venue,
                "style_opponent_contribution": opposition,
                "state_cold_start": min((*own.counts, *opponent_state.counts)) == 0,
                "high_confidence": min((*own.counts, *opponent_state.counts)) >= 3,
                "style_error_risk": risk,
                "prior_style_error": prior_error,
                "chosen_penalty": chosen,
                "source_capture_id": observation.capture_id,
                "source_known_at": observation.source_known_at.isoformat()
                if observation.source_known_at
                else None,
                "payload_sha256": observation.payload_sha256,
                "sdp_match_id": observation.sdp_match_id,
                "evidence_class": observation.evidence_class,
                "provider": observation.provider,
                **source_report,
            }
            pending[key] = _Record(observation, row, x, None, None, None, {None: pmf}, standardized)
        for record in pending.values():
            row = record.row
            opponent = pending[
                f"{season}:{record.observation.fixture}:{record.observation.opponent_team_code}"
            ]
            record.predicted_x = matchup_features(
                row["predicted_state"], opponent.row["predicted_state"], interactions=False
            )
            record.goal_x = matchup_features(
                row["predicted_state"], opponent.row["predicted_state"], interactions=True
            )
            record.recent_x = matchup_features(
                row["current_state"], row["opponent_state"], interactions=False
            )
            rate, pmf = incumbent[observation_key(record.observation)]
            raw_corrections: dict[str, float] = {}
            for penalty, model in goal_models.items():
                correction = (
                    model.correction(record.goal_x)
                    if model is not None and record.goal_x is not None
                    else 0.0
                )
                record.pmfs[penalty] = adjusted_pmf(rate, pmf, correction)
                raw_corrections[str(penalty)] = (
                    model.raw_correction(record.goal_x)
                    if model is not None and record.goal_x is not None
                    else 0.0
                )
            distributions = {"incumbent": pmf, "candidate": record.pmfs[chosen]}
            for name, predictors in (
                (RECENT_DIAGNOSTIC, record.recent_x),
                (PREDICTED_DIAGNOSTIC, record.predicted_x),
            ):
                model = diagnostic_models.get(name)
                correction = (
                    model.correction(predictors)
                    if model is not None and predictors is not None
                    else 0.0
                )
                distributions[name] = adjusted_pmf(rate, pmf, correction)
            row.update(
                {
                    "distributions": distributions,
                    "goal_matchup_features": record.goal_x,
                    "predicted_opponent_state": opponent.row["predicted_state"],
                    "per_penalty_distributions": {
                        "disabled" if penalty is None else str(penalty): values
                        for penalty, values in record.pmfs.items()
                    },
                    "raw_corrections": raw_corrections,
                    "tactical_log_correction": max(-0.5, min(0.5, raw_corrections[str(chosen)]))
                    if chosen is not None
                    else 0.0,
                    "incumbent_fallback": chosen is None
                    or record.goal_x is None
                    or goal_models.get(chosen) is None,
                }
            )
        for record in pending.values():
            opponent = pending[
                f"{season}:{record.observation.fixture}:{record.observation.opponent_team_code}"
            ]
            record.row["clean_sheet_probabilities"] = {
                name: pmf[0] for name, pmf in opponent.row["distributions"].items()
            }
            record.row["observed_clean_sheet"] = record.observation.goals_allowed == 0
        report = {
            "season": season,
            "gw": gw,
            "as_of": cutoff.isoformat(),
            "target_rows": len(batch),
            "prior_completed_rows": len(prior),
            "style_fits": style_diagnostics,
            "goal_fits": goal_diagnostics,
            "diagnostic_goal_fits": diagnostic_fits,
            "selection": selection,
            "chosen_penalty": chosen,
            "prior_style_target_sd": scales,
            "event_time_violations": event_violations,
            "same_gameweek_violations": gameweek_violations,
            "stacking_in_sample_rows": stacking_violations,
            "fit_time_violations": fit_time_violations,
            "target_fixture_source_overlap": target_source_overlap,
            **source_report,
        }
        historical_folds.append(report)
        if season in eligible_seasons:
            folds.append(report)
            outer_rows.extend(record.row for record in pending.values())
        # Absorb only after ALL predictions in the batch; delayed legs are still filtered
        # on their actual kickoff before they can contribute to any subsequent fit.
        history.extend(pending.values())
        if checkpoint is not None:
            # A logging consumer cannot mutate predictions or the next batch's training state.
            checkpoint(deepcopy({"fold": report, "rows": [r.row for r in pending.values()]}))
    return {
        "rows": outer_rows,
        "folds": folds,
        "history_rows": [record.row for record in history],
        "historical_folds": historical_folds,
    }
