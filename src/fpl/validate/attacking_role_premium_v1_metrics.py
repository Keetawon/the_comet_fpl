"""Frozen conditional rate metrics; no feature construction or source access."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from fpl.features.attacking_role_premium_v1 import UsagePrediction
from fpl.validate.metrics import _average_ranks, _pearson


@dataclass(frozen=True)
class ScoredUsage:
    prediction: UsagePrediction
    minutes: int
    xg: float
    xa: float

    def __post_init__(self) -> None:
        if self.minutes < 0 or any(not math.isfinite(v) or v < 0 for v in (self.xg, self.xa)):
            raise ValueError("invalid target exposure/opportunity")

    def observed(self, component: str) -> float:
        if self.minutes <= 0:
            raise ValueError("zero-minute observations do not have per-90 targets")
        if component not in {"xg", "xa", "xgi"}:
            raise ValueError("unknown opportunity target")
        value = self.xg if component == "xg" else self.xa
        if component == "xgi":
            value = self.xg + self.xa
        return 90.0 * value / self.minutes


def average(values: Sequence[float]) -> float | None:
    return math.fsum(values) / len(values) if values else None


def percentile(values: Sequence[float], probability: float) -> float | None:
    if not 0 <= probability <= 1:
        raise ValueError("quantile probability outside [0,1]")
    if not values:
        return None
    ordered = sorted(values)
    at = (len(ordered) - 1) * probability
    left = math.floor(at)
    return ordered[left] + (at - left) * (ordered[math.ceil(at)] - ordered[left])


def spearman(left: Sequence[float], right: Sequence[float]) -> float | None:
    return _pearson(_average_ranks(left), _average_ranks(right)) if len(left) >= 2 else None


def predicted(row: ScoredUsage, arm: str, component: str) -> float:
    return float(getattr(row.prediction, f"{arm}_{component}90"))


def relative_lift(control: float | None, candidate: float | None) -> float | None:
    if control is None or candidate is None or control == 0:
        return None
    return (control - candidate) / control


def positive_shift(prediction: UsagePrediction) -> bool:
    return (
        prediction.candidate_xgi90 >= prediction.control_xgi90 * 1.25
        and prediction.recent_shift_xgi90 >= 0.05
        and prediction.recent_window_minutes >= 180
    )


def history_bucket(minutes: float) -> str:
    for boundary, label in (
        (0, "0"),
        (89, "1-89"),
        (269, "90-269"),
        (449, "270-449"),
        (899, "450-899"),
    ):
        if minutes <= boundary:
            return label
    return "900+"


def comparison(rows: Sequence[ScoredUsage]) -> dict[str, Any]:
    """Caller chooses exposure slice after predictions have been frozen."""
    if any(r.minutes <= 0 for r in rows):
        raise ValueError("conditional rate metrics require strictly positive target minutes")
    report: dict[str, Any] = {"rows": len(rows), "control": {}, "candidate": {}}
    for component in ("xg", "xa", "xgi"):
        observed = [r.observed(component) for r in rows]
        for arm in ("control", "candidate"):
            values = [predicted(r, arm, component) for r in rows]
            errors = [x - y for x, y in zip(values, observed, strict=True)]
            report[arm][component] = {
                "mae": average([abs(e) for e in errors]),
                "mean_error": average(errors),
                "mean_prediction": average(values),
                "mean_observation": average(observed),
                "spearman": spearman(values, observed),
            }
    report["relative_mae_lift"] = {
        component: relative_lift(
            report["control"][component]["mae"], report["candidate"][component]["mae"]
        )
        for component in ("xg", "xa", "xgi")
    }
    groups: dict[tuple[int, str], list[ScoredUsage]] = defaultdict(list)
    for row in rows:
        groups[(row.prediction.target.gameweek, row.prediction.target.fpl_position)].append(row)
    for arm in ("control", "candidate"):
        ranks: list[float] = []
        top: list[ScoredUsage] = []
        for group in groups.values():
            correlation = spearman(
                [predicted(r, arm, "xgi") for r in group], [r.observed("xgi") for r in group]
            )
            if correlation is not None:
                ranks.append(correlation)
            top.extend(
                sorted(
                    group,
                    key=lambda r: (
                        -predicted(r, arm, "xgi"),
                        r.prediction.target.player_code,
                        r.prediction.target.fixture_id,
                    ),
                )[: math.ceil(0.1 * len(group))]
            )
        top_mean = average([r.observed("xgi") for r in top])
        all_mean = report[arm]["xgi"]["mean_observation"]
        report[arm]["conditional_position_gw_ranking"] = {
            "mean_spearman": average(ranks),
            "scoreable_groups": len(ranks),
            "top_decile_rows": len(top),
            "top_decile_mean_xgi90": top_mean,
            "relative_future_xgi90_lift": None
            if not all_mean or top_mean is None
            else top_mean / all_mean - 1.0,
        }
    premiums = [r.prediction.attacking_role_premium_v1 for r in rows]
    report["premium_quantiles"] = {
        str(p): percentile(premiums, p) for p in (0.0, 0.1, 0.5, 0.75, 0.9, 0.975, 1.0)
    }
    report["positive_shift_rows"] = sum(positive_shift(r.prediction) for r in rows)
    return report


def blocked_bootstrap(rows: Sequence[ScoredUsage], *, draws: int, seed: int) -> dict[str, Any]:
    groups: dict[int, list[ScoredUsage]] = defaultdict(list)
    for row in rows:
        groups[row.prediction.target.gameweek].append(row)
    blocks = [
        (
            len(group),
            math.fsum(abs(predicted(r, "control", "xgi") - r.observed("xgi")) for r in group),
            math.fsum(abs(predicted(r, "candidate", "xgi") - r.observed("xgi")) for r in group),
        )
        for _, group in sorted(groups.items())
    ]
    if not blocks or draws <= 0:
        raise ValueError("GW bootstrap requires observations and positive draws")
    rng = random.Random(seed)
    absolute: list[float] = []
    relative: list[float] = []
    for _ in range(draws):
        chosen = [blocks[rng.randrange(len(blocks))] for _ in blocks]
        n = sum(b[0] for b in chosen)
        control = math.fsum(b[1] for b in chosen)
        candidate = math.fsum(b[2] for b in chosen)
        absolute.append((control - candidate) / n)
        if control > 0:
            relative.append((control - candidate) / control)
    return {
        "draws": draws,
        "seed": seed,
        "gw_blocks": len(blocks),
        "absolute_mae_improvement_ci95": [percentile(absolute, 0.025), percentile(absolute, 0.975)],
        "relative_mae_improvement_ci95": [percentile(relative, 0.025), percentile(relative, 0.975)],
        "defined_relative_draws": len(relative),
        "policy": "paired whole-GW resampling; pooled player-row weighting retained",
    }


def verdict(
    primary: dict[str, Any],
    positions: dict[str, Any],
    uncertainty: dict[str, Any],
    gates: dict[str, Any],
    *,
    pit_valid: bool,
) -> dict[str, Any]:
    lift = primary["relative_mae_lift"]
    checks: dict[str, bool] = {
        "causal_and_pit_valid": pit_valid,
        "xgi_materiality": lift["xgi"] is not None and lift["xgi"] >= gates["minimum_xgi_mae_lift"],
        "xg_guardrail": lift["xg"] is not None
        and lift["xg"] >= -gates["maximum_component_regression"],
        "xa_guardrail": lift["xa"] is not None
        and lift["xa"] >= -gates["maximum_component_regression"],
        "def_nonnegative": positions["DEF"]["relative_mae_lift"]["xgi"] is not None
        and positions["DEF"]["relative_mae_lift"]["xgi"] >= 0,
    }
    for name, group in {"pooled": primary, **positions}.items():
        if name != "pooled" and group["rows"] < gates["minimum_guardrail_position_rows"]:
            checks[f"{name}_adequate_for_guardrail"] = False
            continue
        c = group["control"]["xgi"]["mean_error"]
        v = group["candidate"]["xgi"]["mean_error"]
        checks[f"{name}_calibration"] = (
            c is not None
            and v is not None
            and abs(v) - abs(c) <= gates["maximum_absolute_bias_increase"]
        )
        if name != "pooled":
            pos_lift = group["relative_mae_lift"]["xgi"]
            checks[f"{name}_catastrophic_guardrail"] = (
                pos_lift is not None and pos_lift >= -gates["maximum_position_mae_regression"]
            )
    interval = uncertainty["relative_mae_improvement_ci95"]
    checks["uncertainty_supports_direction"] = interval[0] is not None and interval[0] > 0
    checks["all_bootstrap_relative_draws_defined"] = (
        uncertainty["defined_relative_draws"] == uncertainty["draws"]
    )
    if not pit_valid:
        decision = "INVALID"
    elif all(checks.values()):
        decision = "SUPPORTED"
    elif (
        lift["xgi"] is not None
        and lift["xgi"] <= -gates["minimum_xgi_mae_lift"]
        and interval[1] is not None
        and interval[1] < 0
    ):
        decision = "REFUTED"
    else:
        decision = "INCONCLUSIVE"
    return {"verdict": decision, "checks": checks}


def diagnostics(rows: Sequence[ScoredUsage], *, primary_minutes: int) -> dict[str, Any]:
    primary = [r for r in rows if r.minutes >= primary_minutes]
    groups: dict[str, dict[str, list[ScoredUsage]]] = {
        "position": defaultdict(list),
        "history_minutes": defaultdict(list),
        "season_third": defaultdict(list),
        "gameweek": defaultdict(list),
        "prior_appearance": defaultdict(list),
        "venue": defaultdict(list),
    }
    for row in primary:
        p = row.prediction
        groups["position"][p.target.fpl_position].append(row)
        groups["history_minutes"][history_bucket(p.historical_minutes)].append(row)
        third = (
            "early_gw1_13"
            if p.target.gameweek <= 13
            else "middle_gw14_26"
            if p.target.gameweek <= 26
            else "late_gw27_38"
        )
        groups["season_third"][third].append(row)
        groups["gameweek"][str(p.target.gameweek)].append(row)
        group = (
            "unknown_prior_appearance"
            if p.historical_appearances is None or p.historical_meaningful_appearances is None
            else "no_prior_appearance"
            if p.historical_appearances == 0
            else "one_prior_meaningful_appearance"
            if p.historical_meaningful_appearances == 1
            else "established_history"
            if p.historical_meaningful_appearances >= 2
            else "only_short_prior_appearances"
        )
        groups["prior_appearance"][group].append(row)
        groups["venue"][p.target.venue].append(row)
    shifts = [r for r in primary if positive_shift(r.prediction)]
    others = [r for r in primary if not positive_shift(r.prediction)]
    persistence = [
        r.observed("xgi") >= 1.25 * r.prediction.control_xgi90
        and r.observed("xgi") - r.prediction.control_xgi90 >= 0.05
        for r in shifts
    ]
    high = {
        str(threshold): [
            r
            for r in primary
            if r.prediction.target.fpl_position == "DEF"
            and r.prediction.attacking_role_premium_v1 >= threshold
        ]
        for threshold in (0.9, 0.975)
    }
    return {
        "slices": {
            name: {key: comparison(group) for key, group in sorted(values.items())}
            for name, values in groups.items()
        },
        "all_playing_time": comparison([r for r in rows if r.minutes > 0]),
        "short_appearances_1_44": comparison([r for r in rows if 0 < r.minutes < primary_minutes]),
        "zero_minute_targets": sum(r.minutes == 0 for r in rows),
        "regime_shift": {
            "positive": comparison(shifts),
            "non_shift": comparison(others),
            "persistence_rate": average([float(value) for value in persistence]),
            "mean_reversion_target_minus_candidate": average(
                [r.observed("xgi") - r.prediction.candidate_xgi90 for r in shifts]
            ),
            "by_position": {
                position: sum(r.prediction.target.fpl_position == position for r in shifts)
                for position in ("DEF", "MID", "FWD")
            },
        },
        "high_premium_def": {
            key: {
                "comparison": comparison(group),
                "mean_historical_minutes": average(
                    [r.prediction.historical_minutes for r in group]
                ),
                "mean_recent_shift_xgi90": average(
                    [r.prediction.recent_shift_xgi90 for r in group]
                ),
            }
            for key, group in high.items()
        },
    }
