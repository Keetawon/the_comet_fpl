"""Frozen-audit scoring only: no fitting, source loading or production mutation.

The caller freezes predictions and validates source finality before supplying outcomes.
Signed official points remain distinct from the composer's coarsened points target.
Component residuals are descriptive arithmetic, never causal attributions.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from itertools import product
from statistics import median
from typing import Any

from fpl.artifacts.prospective_points import _convolve
from fpl.config import ScoringRules, load_scoring_rules
from fpl.models.points_composition import MEASURED_CONCEDED_EXPOSURE, thin_count_distribution
from fpl.types import Position
from fpl.validate.metrics import PROBABILITY_FLOOR, crps, log_score, spearman_within_groups

type Row = dict[str, Any]

IDENTITY = (
    "season",
    "gw",
    "fixture",
    "code",
    "position",
    "team_code",
    "opponent_team_code",
    "was_home",
    "kickoff_time",
)
POINT_SUPPORT_MAX = 34
MINUTE_REPRESENTATIVES = (0, 59, 89, 90)
TOP_K = (10, 25, 50)
CAPTAIN_K = (1, 3, 5)
COMPONENT_CATEGORIES = (
    "MINUTES",
    "GOALS",
    "ASSISTS",
    "CLEAN_SHEET",
    "GOALS_CONCEDED",
    "SAVES",
    "DC",
    "BONUS",
)


def _mean(values: Sequence[float]) -> float | None:
    return math.fsum(values) / len(values) if values else None


def _number(
    value: Any, *, minimum: float | None = None, maximum: float | None = None
) -> float | None:
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        return None
    return float(value)


def _count(value: Any, *, signed: bool = False) -> int | None:
    return value if type(value) is int and (signed or value >= 0) else None


def _pmf(value: Any, *, length: int | None = None) -> tuple[float, ...] | None:
    if value is None:
        return None
    if (
        not isinstance(value, (list, tuple))
        or not value
        or (length is not None and len(value) != length)
    ):
        raise ValueError("invalid prediction PMF support")
    if any(_number(p, minimum=0, maximum=1) is None for p in value):
        raise ValueError("prediction PMF must contain finite probabilities")
    if not math.isclose(math.fsum(value), 1, rel_tol=0, abs_tol=1e-9):
        raise ValueError("prediction PMF must sum to one")
    return tuple(float(p) for p in value)


def _expected(pmf: Sequence[float]) -> float:
    return math.fsum(i * p for i, p in enumerate(pmf))


def _key(row: Row) -> tuple[str, int, int]:
    if not isinstance(row.get("season"), str) or not row["season"]:
        raise ValueError("season-qualified prediction/outcome identity required")
    if any(type(row.get(k)) is not int or row[k] <= 0 for k in ("gw", "fixture", "code")):
        raise ValueError("positive gameweek/fixture/stable-code identity required")
    return row["season"], row["fixture"], row["code"]


def _instant(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.astimezone(UTC).isoformat() if parsed.tzinfo is not None else None


def _validate_prediction(row: Row) -> None:
    _key(row)
    if row["gw"] not in (1, 2, 3) or row.get("position") not in tuple(Position):
        raise ValueError("GW1-3 outfield/goalkeeper prediction required")
    if any(type(row.get(k)) is not int or row[k] <= 0 for k in ("team_code", "opponent_team_code")):
        raise ValueError("exact team identities required")
    if row["team_code"] == row["opponent_team_code"] or _instant(row.get("kickoff_time")) is None:
        raise ValueError("valid fixture side and aware kickoff required")
    if any(
        type(row.get(k)) is not bool
        for k in ("was_home", "cold_start_player", "transferred_no_rescale")
    ):
        raise ValueError("explicit typed forecast flags required")
    if row.get("promoted_team") is not None and type(row["promoted_team"]) is not bool:
        raise ValueError("promoted-team evidence must be an explicit boolean or NULL")
    if not isinstance(row.get("selector"), str) or not row["selector"]:
        raise ValueError("explicit selector required")
    pmf = _pmf(row.get("distribution"), length=POINT_SUPPORT_MAX + 1)
    xp = _number(row.get("expected_points"), minimum=0)
    if pmf is None or xp is None or not math.isclose(xp, _expected(pmf), rel_tol=0, abs_tol=1e-9):
        raise ValueError("forecast xP must equal its complete points PMF mean")
    if _number(row.get("availability_multiplier"), minimum=0, maximum=1) is None:
        raise ValueError("explicit valid availability multiplier required")
    if not isinstance(row.get("components"), dict):
        raise ValueError("explicit component dictionary required; absent values remain NULL")


def _calibration(pairs: Sequence[tuple[float, int]]) -> Row:
    buckets = []
    for i in range(10):
        selected = [(p, y) for p, y in pairs if min(int(p * 10), 9) == i]
        buckets.append(
            {
                "lower": i / 10,
                "upper": (i + 1) / 10,
                "rows": len(selected),
                "predicted": _mean([p for p, _ in selected]),
                "observed": _mean([float(y) for _, y in selected]),
            }
        )
    return {
        "rows": len(pairs),
        "brier": _mean([(p - y) ** 2 for p, y in pairs]),
        "mean_probability": _mean([p for p, _ in pairs]),
        "observed_rate": _mean([float(y) for _, y in pairs]),
        "bins": buckets,
    }


def _continuous(pairs: Sequence[tuple[float, float]], eligible: int) -> Row:
    errors = [p - y for p, y in pairs]
    mse = _mean([e * e for e in errors])
    return {
        "rows": len(pairs),
        "unavailable_rows": eligible - len(pairs),
        "mean_predicted": _mean([p for p, _ in pairs]),
        "mean_observed": _mean([y for _, y in pairs]),
        "mae": _mean([abs(e) for e in errors]),
        "bias_predicted_minus_observed": _mean(errors),
        "rmse": math.sqrt(mse) if mse is not None else None,
    }


def _points(rows: Sequence[Row]) -> Row:
    signed_pairs = [(r["expected_points"], float(r["signed_target"])) for r in rows]
    rank = (
        spearman_within_groups(
            [r["expected_points"] for r in rows],
            [r["signed_target"] for r in rows],
            [f"{r['season']}:{r['gw']}" for r in rows],
        )
        if rows
        else None
    )
    events = {}
    for label, threshold, below in (
        ("blank_le2", 2, True),
        ("points_ge5", 5, False),
        ("points_ge10", 10, False),
    ):
        pairs = []
        for row in rows:
            probability = min(
                1.0,
                math.fsum(
                    p
                    for i, p in enumerate(row["distribution"])
                    if (i <= threshold if below else i >= threshold)
                ),
            )
            actual = int(
                row["scored_target"] <= threshold if below else row["scored_target"] >= threshold
            )
            pairs.append((probability, actual))
        events[label] = _calibration(pairs)
    return {
        "rows": len(rows),
        "signed_points": _continuous(signed_pairs, len(rows)),
        "mean_log_score": _mean([r["log_score"] for r in rows]),
        "mean_crps": _mean([r["crps"] for r in rows]),
        "spearman_within_gameweek_signed": rank
        if rank is not None and math.isfinite(rank)
        else None,
        "zero_target_bin_count": sum(r["distribution"][r["scored_target"]] == 0 for r in rows),
        "log_floor_hit_count": sum(
            r["distribution"][r["scored_target"]] < PROBABILITY_FLOOR for r in rows
        ),
        "signed_targets_below_zero": sum(r["signed_target"] < 0 for r in rows),
        "signed_targets_above_support": sum(
            r["signed_target"] >= len(r["distribution"]) for r in rows
        ),
        "target_changed_by_coarsening": sum(r["signed_target"] != r["scored_target"] for r in rows),
        "events_on_coarsened_target": events,
    }


def _point_slices(rows: Sequence[Row]) -> Row:
    slices: dict[str, dict[str, list[Row]]] = {}
    for dimension, field in (
        ("gameweek", "gw"),
        ("position", "position"),
        ("selector", "selector"),
        ("cold_start", "cold_start_player"),
        ("transfer", "transferred_no_rescale"),
        ("promoted", "promoted_team"),
        ("venue", "venue"),
    ):
        grouped: defaultdict[str, list[Row]] = defaultdict(list)
        for row in rows:
            label = (
                f"{row['season']}:{row['gw']}"
                if dimension == "gameweek"
                else "UNAVAILABLE"
                if row[field] is None
                else str(row[field])
            )
            grouped[label].append(row)
        slices[dimension] = dict(grouped)
    return {
        "overall": _points(rows),
        "slices": {
            name: {key: _points(group) for key, group in sorted(groups.items())}
            for name, groups in slices.items()
        },
    }


def _component_row(prediction: Row, outcome: Row, rules: ScoringRules) -> Row:
    position = Position(prediction["position"])
    source = prediction["components"]
    minutes_pmf = _pmf(source.get("minutes"), length=4)
    p_any = 1 - minutes_pmf[0] if minutes_pmf is not None else None
    p60 = math.fsum(minutes_pmf[2:]) if minutes_pmf is not None else None
    minutes = _count(outcome.get("minutes"))
    if minutes is not None and minutes > 120:
        minutes = None
    starts = _count(outcome.get("starts"))
    if starts not in (0, 1):
        starts = None
    counts: Row = {}
    predicted: Row = {
        "minutes_scoring_proxy": math.fsum(
            p * m for p, m in zip(minutes_pmf, MINUTE_REPRESENTATIVES, strict=True)
        )
        if minutes_pmf
        else None,
        "appearance": p_any,
        "minutes_60_plus": p60,
        "starts": None,
    }
    actual: Row = {
        "minutes_scoring_proxy": minutes,
        "appearance": int(minutes > 0) if minutes is not None else None,
        "minutes_60_plus": int(minutes >= 60) if minutes is not None else None,
        "starts": starts,
    }
    residual: Row = dict.fromkeys(COMPONENT_CATEGORIES)
    if minutes is not None and p_any is not None and p60 is not None:
        expected_appearance = (
            rules.appearance.short_play_points * (p_any - p60)
            + rules.appearance.long_play_points * p60
        )
        observed_appearance = (
            0
            if minutes == 0
            else rules.appearance.long_play_points
            if minutes >= rules.appearance.long_play_minutes
            else rules.appearance.short_play_points
        )
        residual["MINUTES"] = observed_appearance - expected_appearance
    for name, field, coefficient in (
        ("goals", "goals_scored", rules.goals_scored[position]),
        ("assists", "assists", rules.assists),
        ("saves", "saves", 1),
    ):
        if name == "saves" and position not in rules.saves.positions:
            continue
        conditional = _pmf(source.get(name))
        unconditional = (
            None
            if conditional is None or p_any is None
            else (1 - p_any + p_any * conditional[0], *(p_any * p for p in conditional[1:]))
        )
        observed = _count(outcome.get(field))
        counts[name] = {"distribution": unconditional, "observed": observed}
        predicted[name] = _expected(unconditional) if unconditional is not None else None
        actual[name] = observed
        predicted[f"{name}_any"] = 1 - unconditional[0] if unconditional is not None else None
        actual[f"{name}_any"] = int(observed > 0) if observed is not None else None
        if unconditional is not None and observed is not None:
            if name == "saves":
                expected_points = math.fsum(
                    p * (i // rules.saves.unit) * rules.saves.points_per_unit
                    for i, p in enumerate(unconditional)
                )
                observed_points = (observed // rules.saves.unit) * rules.saves.points_per_unit
                residual["SAVES"] = observed_points - expected_points
            else:
                residual[name.upper()] = coefficient * (observed - _expected(unconditional))
    conceded = _pmf(source.get("team_goals_conceded"))
    team_actual = _count(outcome.get("team_goals_conceded"))
    predicted["team_clean_sheet"] = conceded[0] if conceded is not None else None
    actual["team_clean_sheet"] = int(team_actual == 0) if team_actual is not None else None
    player_cs = None
    if conceded is not None and minutes_pmf is not None:
        thinned = [
            thin_count_distribution(conceded, exposure) for exposure in MEASURED_CONCEDED_EXPOSURE
        ]
        player_cs = math.fsum(minutes_pmf[i] * thinned[i][0] for i in (2, 3))
        conceded_actual = _count(outcome.get("goals_conceded"))
        if position in rules.goals_conceded.positions and conceded_actual is not None:
            expected_penalty = math.fsum(
                minutes_pmf[b]
                * math.fsum(
                    p * (i // rules.goals_conceded.unit) * rules.goals_conceded.points_per_unit
                    for i, p in enumerate(thinned[b])
                )
                for b in (1, 2, 3)
            )
            residual["GOALS_CONCEDED"] = (
                conceded_actual // rules.goals_conceded.unit
            ) * rules.goals_conceded.points_per_unit - expected_penalty
    cs = _count(outcome.get("clean_sheets"))
    if cs not in (0, 1):
        cs = None
    actual_cs = int(minutes >= 60 and cs > 0) if minutes is not None and cs is not None else None
    predicted["player_60plus_clean_sheet"] = player_cs
    actual["player_60plus_clean_sheet"] = actual_cs
    if player_cs is not None and actual_cs is not None:
        residual["CLEAN_SHEET"] = rules.clean_sheets.points.get(position, 0) * (
            actual_cs - player_cs
        )
    threshold = rules.defensive_contribution.thresholds.get(position)
    if threshold is not None:
        conditional_dc = _number(source.get("dc_hit_probability"), minimum=0, maximum=1)
        p_dc = conditional_dc * p_any if conditional_dc is not None and p_any is not None else None
        dc = _count(outcome.get("defensive_contribution"))
        actual_dc = int(dc >= threshold) if dc is not None else None
        predicted["dc_award"] = p_dc
        actual["dc_award"] = actual_dc
        if p_dc is not None and actual_dc is not None:
            residual["DC"] = rules.defensive_contribution.points * (actual_dc - p_dc)
    bonus = _count(outcome.get("bonus"))
    if bonus is not None and bonus > 3:
        bonus = None
    expected_bonus = _number(prediction.get("expected_bonus"), minimum=0, maximum=3)
    predicted["bonus"] = expected_bonus
    actual["bonus"] = bonus
    predicted["any_bonus"] = _number(source.get("probability_any_bonus"), minimum=0, maximum=1)
    actual["any_bonus"] = int(bonus > 0) if bonus is not None else None
    if expected_bonus is not None and bonus is not None:
        residual["BONUS"] = bonus - expected_bonus
    return {
        "predicted": predicted,
        "actual": actual,
        "counts": counts,
        "point_residuals": residual,
        "season": prediction["season"],
        "gw": prediction["gw"],
        "fixture": prediction["fixture"],
        "code": prediction["code"],
        "team_code": prediction["team_code"],
        "position": prediction["position"],
        "cold_start_player": prediction["cold_start_player"],
        "transferred_no_rescale": prediction["transferred_no_rescale"],
        "promoted_team": prediction.get("promoted_team"),
        "official_team_goals_conceded": team_actual,
    }


def _component_summary(rows: Sequence[Row]) -> Row:
    numeric = {}
    for name in ("minutes_scoring_proxy", "goals", "assists", "saves", "bonus"):
        eligible = [r for r in rows if name in r["predicted"]]
        pairs = [
            (r["predicted"][name], float(r["actual"][name]))
            for r in eligible
            if r["predicted"][name] is not None and r["actual"][name] is not None
        ]
        numeric[name] = _continuous(pairs, len(eligible))
        if name in ("goals", "assists", "saves"):
            counts = [
                r["counts"][name]
                for r in eligible
                if name in r["counts"]
                and r["counts"][name]["distribution"] is not None
                and r["counts"][name]["observed"] is not None
            ]
            numeric[name].update(
                {
                    "mean_log_score": _mean(
                        [log_score(r["distribution"], r["observed"]) for r in counts]
                    ),
                    "mean_crps": _mean([crps(r["distribution"], r["observed"]) for r in counts]),
                    "observations_above_count_support": sum(
                        r["observed"] >= len(r["distribution"]) for r in counts
                    ),
                }
            )
    margins = {}
    for name in (
        "appearance",
        "minutes_60_plus",
        "player_60plus_clean_sheet",
        "dc_award",
        "any_bonus",
        "goals_any",
        "assists_any",
        "saves_any",
    ):
        eligible = [r for r in rows if name in r["predicted"]]
        binary_pairs = [
            (r["predicted"][name], r["actual"][name])
            for r in eligible
            if r["predicted"][name] is not None and r["actual"][name] is not None
        ]
        margins[name] = {
            **_calibration(binary_pairs),
            "unavailable_rows": len(eligible) - len(binary_pairs),
        }
    team_groups: defaultdict[tuple[str, int, int], list[Row]] = defaultdict(list)
    for row in rows:
        team_groups[row["season"], row["fixture"], row["team_code"]].append(row)
    team_pairs = []
    for group in team_groups.values():
        probabilities = {
            r["predicted"]["team_clean_sheet"]
            for r in group
            if r["predicted"]["team_clean_sheet"] is not None
        }
        outcomes = {
            r["actual"]["team_clean_sheet"]
            for r in group
            if r["actual"]["team_clean_sheet"] is not None
        }
        official_counts = {
            r["official_team_goals_conceded"]
            for r in group
            if r["official_team_goals_conceded"] is not None
        }
        if len(probabilities) > 1 or len(outcomes) > 1 or len(official_counts) > 1:
            raise ValueError("contradictory team clean-sheet probability or official outcome")
        if probabilities and outcomes:
            team_pairs.append((next(iter(probabilities)), next(iter(outcomes))))
    margins["team_clean_sheet"] = {
        **_calibration(team_pairs),
        "eligible_team_fixture_sides": len(team_groups),
        "unavailable_rows": len(team_groups) - len(team_pairs),
    }
    false_nailed = [
        r
        for r in rows
        if r["predicted"]["minutes_60_plus"] is not None
        and r["actual"]["minutes_60_plus"] is not None
        and r["predicted"]["minutes_60_plus"] >= 0.8
    ]
    missed = [
        r
        for r in rows
        if r["predicted"]["appearance"] is not None
        and r["actual"]["starts"] is not None
        and r["predicted"]["appearance"] < 0.2
    ]
    return {
        "rows": len(rows),
        "numeric": numeric,
        "binary": margins,
        "starts": {
            "prediction": None,
            "status": "UNAVAILABLE_NO_START_MODEL",
            "observed_rows": sum(r["actual"]["starts"] is not None for r in rows),
            "observed_starts": sum(r["actual"]["starts"] == 1 for r in rows),
        },
        "false_nailed": {
            "eligible_rows": len(false_nailed),
            "count": sum(r["actual"]["minutes_60_plus"] == 0 for r in false_nailed),
        },
        "missed_starters": {
            "eligible_rows": len(missed),
            "count": sum(r["actual"]["starts"] == 1 for r in missed),
        },
        "unavailable_models": [
            "start_probability",
            "raw_dc_action_pmf",
            "player_shots",
            "player_xg",
            "player_xa",
            "cards",
            "penalties",
            "own_goals",
            "bonus_full_pmf",
        ],
    }


def _rankings(rows: Sequence[Row]) -> list[Row]:
    groups: defaultdict[tuple[str, int], list[Row]] = defaultdict(list)
    for row in rows:
        groups[row["season"], row["gw"]].append(row)
    reports = []
    for (season, gw), group in sorted(groups.items()):
        predicted = sorted(group, key=lambda r: (-r["expected_points"], r["code"]))
        actual = sorted(group, key=lambda r: (-r["signed_target"], r["code"]))

        def at_k(k: int, predicted: list[Row] = predicted, actual: list[Row] = actual) -> Row:
            selected, best = predicted[:k], actual[:k]
            codes, actual_codes = {r["code"] for r in selected}, {r["code"] for r in best}
            return {
                "requested_k": k,
                "effective_k": len(selected),
                "selected_codes": [r["code"] for r in selected],
                "actual_top_codes": [r["code"] for r in best],
                "overlap_count": len(codes & actual_codes),
                "overlap_fraction": len(codes & actual_codes) / len(selected),
                "mean_realized_points": _mean([float(r["signed_target"]) for r in selected]),
                "median_realized_points": median(r["signed_target"] for r in selected),
                "hit_rate_ge5": sum(r["signed_target"] >= 5 for r in selected) / len(selected),
                "hit_rate_ge10": sum(r["signed_target"] >= 10 for r in selected) / len(selected),
                "regret_total_points": sum(r["signed_target"] for r in best)
                - sum(r["signed_target"] for r in selected),
            }

        reports.append(
            {
                "season": season,
                "gw": gw,
                "rows": len(group),
                "top_k": [at_k(k) for k in TOP_K],
                "captain_shortlists": [at_k(k) for k in CAPTAIN_K],
            }
        )
    return reports


def _with_losses(row: Row) -> Row:
    return {
        **row,
        "log_score": log_score(row["distribution"], row["scored_target"]),
        "crps": crps(row["distribution"], row["scored_target"]),
        "signed_absolute_error": abs(row["expected_points"] - row["signed_target"]),
    }


def _misses(rows: Sequence[Row]) -> list[Row]:
    reports = []
    for row in sorted(
        rows, key=lambda r: (-r["signed_absolute_error"], r["season"], r["gw"], r["code"])
    )[:25]:
        residuals = row["point_residuals"]
        observed = {name: value for name, value in residuals.items() if value is not None}
        remainder = row["signed_target"] - row["expected_points"] - math.fsum(observed.values())
        comparable = {**observed, "UNEXPLAINED": remainder}
        largest = max(abs(value) for value in comparable.values())
        tied = sorted(name for name, value in comparable.items() if abs(value) == largest)
        category = (
            "UNEXPLAINED"
            if not observed or largest == 0
            else tied[0]
            if len(tied) == 1
            else "MULTIPLE"
        )
        reports.append(
            {
                "season": row["season"],
                "gw": row["gw"],
                "code": row["code"],
                "position": row["position"],
                "web_name": row["web_name"],
                "fixture_ids": row["fixture_ids"],
                "expected_points": row["expected_points"],
                "signed_target": row["signed_target"],
                "absolute_error": row["signed_absolute_error"],
                "category": category,
                "tied_categories": tied if len(tied) > 1 else [],
                "component_point_residuals_observed_minus_expected": residuals,
                "unexplained_remainder": remainder,
                "unavailable_components": [k for k, v in residuals.items() if v is None],
                "interpretation": "NONCAUSAL_COMPONENT_RESIDUAL_DIAGNOSTIC",
                "fixture_details": row["fixture_details"],
            }
        )
    return reports


def score_predictions(predictions: Sequence[Row], outcomes: Sequence[Row]) -> Row:
    """Score one frozen arm; preserve all exclusions and never infer missing outcomes."""
    if PROBABILITY_FLOOR != 1e-12:
        raise ValueError("frozen log-probability floor changed")
    rules = load_scoring_rules("2026_27")
    predicted_keys = [_key(row) for row in predictions]
    outcome_keys = [_key(row) for row in outcomes]
    if len(set(predicted_keys)) != len(predicted_keys) or len(set(outcome_keys)) != len(
        outcome_keys
    ):
        raise ValueError("duplicate player-fixture prediction/outcome identity")
    by_outcome = dict(zip(outcome_keys, outcomes, strict=True))
    exclusions: list[Row] = []
    fixture_rows: list[Row] = []
    components: list[Row] = []
    all_gameweeks: defaultdict[tuple[str, int, int], list[Row]] = defaultdict(list)
    for prediction in sorted(
        predictions, key=lambda r: (r["season"], r["gw"], r["fixture"], r["code"])
    ):
        _validate_prediction(prediction)
        key = _key(prediction)
        all_gameweeks[prediction["season"], prediction["gw"], prediction["code"]].append(prediction)
        outcome = by_outcome.get(key)
        mismatch = (
            []
            if outcome is None
            else [
                field
                for field in IDENTITY
                if (
                    _instant(prediction.get(field)) != _instant(outcome.get(field))
                    if field == "kickoff_time"
                    else type(prediction.get(field)) is not type(outcome.get(field))
                    or prediction.get(field) != outcome.get(field)
                )
            ]
        )
        if outcome is None or mismatch:
            exclusions.append(
                {
                    "key": list(key),
                    "reason": "MISSING_OUTCOME" if outcome is None else "IDENTITY_MISMATCH",
                    "fields": mismatch,
                }
            )
            continue
        component = _component_row(prediction, outcome, rules)
        components.append(component)
        target = _count(outcome.get("total_points_as_recorded"), signed=True)
        if target is None:
            exclusions.append(
                {
                    "key": list(key),
                    "reason": "MISSING_OR_INVALID_POINTS_OUTCOME",
                    "fields": ["total_points_as_recorded"],
                }
            )
            continue
        fixture_rows.append(
            _with_losses(
                {
                    **{k: prediction[k] for k in IDENTITY},
                    "expected_points": prediction["expected_points"],
                    "distribution": tuple(prediction["distribution"]),
                    "signed_target": target,
                    "scored_target": min(POINT_SUPPORT_MAX, max(0, target)),
                    "selector": prediction["selector"],
                    "cold_start_player": prediction["cold_start_player"],
                    "transferred_no_rescale": prediction["transferred_no_rescale"],
                    "promoted_team": prediction.get("promoted_team"),
                    "web_name": prediction.get("web_name"),
                    "venue": "home" if prediction["was_home"] else "away",
                    "point_residuals": component["point_residuals"],
                    "fixture_detail": {
                        **{k: prediction[k] for k in IDENTITY},
                        "web_name": prediction.get("web_name"),
                        "expected_points": prediction["expected_points"],
                        "actual_signed_points": target,
                        "predicted_components": component["predicted"],
                        "observed_components": component["actual"],
                        "appearance_gated_count_distributions": component["counts"],
                        "observed_raw_dc": _count(outcome.get("defensive_contribution")),
                        "observed_raw_bps": _count(outcome.get("bps"), signed=True),
                        "team_environment": prediction.get("team_environment"),
                        "opponent_environment": prediction.get("opponent_environment"),
                        "availability_status": prediction.get("availability_status"),
                        "availability_multiplier": prediction["availability_multiplier"],
                        "cold_start_player": prediction["cold_start_player"],
                        "transferred_no_rescale": prediction["transferred_no_rescale"],
                        "promoted_team": prediction.get("promoted_team"),
                        "selector": prediction["selector"],
                        "fallback_reason": prediction.get("fallback_reason"),
                        "bps_residual_mean": prediction.get("residual_mean"),
                        "bps_residual_sigma": prediction.get("residual_sigma"),
                    },
                }
            )
        )
    scored_by_key = {_key(row): row for row in fixture_rows}
    gameweek_rows: list[Row] = []
    gameweek_exclusions = []
    for key, targets in sorted(all_gameweeks.items()):
        legs = [scored_by_key[_key(row)] for row in targets if _key(row) in scored_by_key]
        if len(legs) != len(targets):
            gameweek_exclusions.append(
                {
                    "key": list(key),
                    "reason": "INCOMPLETE_FIXTURE_LEGS",
                    "expected_legs": len(targets),
                    "scored_legs": len(legs),
                }
            )
            continue
        if len({row["position"] for row in legs}) != 1:
            gameweek_exclusions.append(
                {"key": list(key), "reason": "CONTRADICTORY_REGISTERED_POSITION"}
            )
            continue
        distribution: tuple[float, ...] = (1.0,)
        for row in legs:
            distribution = _convolve(distribution, row["distribution"])
        selectors, venues = {r["selector"] for r in legs}, {r["venue"] for r in legs}
        gameweek_rows.append(
            _with_losses(
                {
                    "season": key[0],
                    "gw": key[1],
                    "code": key[2],
                    "position": legs[0]["position"],
                    "fixture_ids": [r["fixture"] for r in legs],
                    "fixture_details": [r["fixture_detail"] for r in legs],
                    "web_name": legs[0]["web_name"]
                    if all(r["web_name"] == legs[0]["web_name"] for r in legs)
                    else None,
                    "distribution": distribution,
                    "expected_points": _expected(distribution),
                    "signed_target": sum(r["signed_target"] for r in legs),
                    "scored_target": sum(r["scored_target"] for r in legs),
                    "selector": next(iter(selectors)) if len(selectors) == 1 else "MIXED",
                    "venue": next(iter(venues)) if len(venues) == 1 else "mixed",
                    "cold_start_player": any(r["cold_start_player"] for r in legs),
                    "transferred_no_rescale": any(r["transferred_no_rescale"] for r in legs),
                    "promoted_team": legs[0]["promoted_team"]
                    if all(r["promoted_team"] == legs[0]["promoted_team"] for r in legs)
                    else None,
                    "point_residuals": {
                        name: math.fsum(r["point_residuals"][name] for r in legs)
                        if all(r["point_residuals"][name] is not None for r in legs)
                        else None
                        for name in COMPONENT_CATEGORIES
                    },
                }
            )
        )
    component_positions = {
        p: _component_summary([r for r in components if r["position"] == p])
        for p in ("GK", "DEF", "MID", "FWD")
    }
    return {
        "schema": "fpl.player-model-gw1-3-metrics/v1",
        "policy": {
            "points_target": (
                "official total_points_as_recorded; signed retained; fixture proper scores "
                "clamp 0..34; GW target sums per-leg coarsening"
            ),
            "log_probability_floor": PROBABILITY_FLOOR,
            "ranking": (
                "within GW raw xP versus signed outcomes; equal weights; "
                "deterministic stable-code ties; no availability adjustment"
            ),
            "top_k": list(TOP_K),
            "captain_k": list(CAPTAIN_K),
            "calibration_bins": 10,
            "minutes_mean": (
                "scoring-representative proxy using 0,59,89,90; "
                "not a physical-minute expectation or P(start)"
            ),
            "count_components": (
                "appearance-gated marginals; missing remains NULL; "
                "count upper tails coarsened by existing scorer"
            ),
            "team_cs": (
                "deduplicated official fixture-team outcome only; "
                "player conceded counts never proxy full-team outcomes"
            ),
            "component_residuals": (
                "observed minus analytic expected component points; UNEXPLAINED includes "
                "missing/unmodeled components, Monte Carlo and points-support coarsening; "
                "largest absolute residual including remainder; exact ties MULTIPLE; no causality"
            ),
            "finality": (
                "upstream frozen caller must establish completed official fixtures "
                "and whole-GW finality"
            ),
        },
        "coverage": {
            "prediction_rows": len(predictions),
            "outcome_rows": len(outcomes),
            "scored_fixture_rows": len(fixture_rows),
            "scored_player_gameweeks": len(gameweek_rows),
            "exclusion_counts": dict(sorted(Counter(r["reason"] for r in exclusions).items())),
            "fixture_exclusions": exclusions,
            "gameweek_exclusions": gameweek_exclusions,
            "extra_outcome_keys": [
                list(k) for k in sorted(set(outcome_keys) - set(predicted_keys))
            ],
        },
        "fixture_points": _point_slices(fixture_rows),
        "player_gameweek_points": _point_slices(gameweek_rows),
        "fixture_components": {
            "overall": _component_summary(components),
            "by_position": component_positions,
            "by_gameweek": {
                f"{s}:{g}": _component_summary(
                    [r for r in components if (r["season"], r["gw"]) == (s, g)]
                )
                for s, g in sorted({(r["season"], r["gw"]) for r in components})
            },
            "by_evidence_scope": {
                dimension: {
                    "UNAVAILABLE" if value is None else str(value): _component_summary(
                        [r for r in components if r[field] is value]
                    )
                    for value in (False, True, None)
                }
                for dimension, field in (
                    ("cold_start", "cold_start_player"),
                    ("transfer", "transferred_no_rescale"),
                    ("promoted", "promoted_team"),
                )
            },
        },
        "within_gw_rankings": _rankings(gameweek_rows),
        "top25_absolute_xp_misses": _misses(gameweek_rows),
        "fixture_row_scores": [
            {
                k: v
                for k, v in r.items()
                if k not in ("distribution", "point_residuals", "fixture_detail")
            }
            for r in fixture_rows
        ],
        "player_gameweek_row_scores": [
            {
                k: v
                for k, v in r.items()
                if k not in ("distribution", "point_residuals", "fixture_details")
            }
            for r in gameweek_rows
        ],
    }


PAIRED_LOSSES = ("log_score", "crps", "signed_absolute_error")


def _paired_summary(rows: Sequence[Row]) -> Row:
    return {
        "rows": len(rows),
        "metrics": {
            metric: {
                "current_mean": _mean([r["current"][metric] for r in rows]),
                "incumbent_mean": _mean([r["incumbent"][metric] for r in rows]),
                "difference_current_minus_incumbent": _mean(
                    [r["difference"][metric] for r in rows]
                ),
            }
            for metric in PAIRED_LOSSES
        },
    }


def _quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * probability
    lower, upper = math.floor(index), math.ceil(index)
    return ordered[lower] + (index - lower) * (ordered[upper] - ordered[lower])


def _three_gw_uncertainty(rows: Sequence[Row]) -> Row:
    groups: defaultdict[tuple[str, int], list[Row]] = defaultdict(list)
    for row in rows:
        groups[row["season"], row["gw"]].append(row)
    labels = sorted(groups)
    if len(labels) != 3 or len({s for s, _ in labels}) != 1 or [g for _, g in labels] != [1, 2, 3]:
        return {
            "status": "UNAVAILABLE_REQUIRES_ALL_THREE_GAMEWEEKS",
            "gameweeks": [list(key) for key in labels],
            "draws": [],
            "intervals_95": dict.fromkeys(PAIRED_LOSSES),
        }
    totals = {
        label: {
            metric: math.fsum(r["difference"][metric] for r in groups[label])
            for metric in PAIRED_LOSSES
        }
        for label in labels
    }
    draws: list[Row] = []
    for sampled in product(labels, repeat=3):
        size = sum(len(groups[label]) for label in sampled)
        draws.append(
            {
                "sampled_gameweeks": [g for _, g in sampled],
                "rows_with_multiplicity": size,
                "difference": {
                    metric: math.fsum(totals[label][metric] for label in sampled) / size
                    for metric in PAIRED_LOSSES
                },
            }
        )
    return {
        "status": "DESCRIPTIVE_ONLY_THREE_INDEPENDENT_GAMEWEEK_BLOCKS",
        "gameweeks": [list(key) for key in labels],
        "draws": draws,
        "intervals_95": {
            metric: [_quantile([r["difference"][metric] for r in draws], p) for p in (0.025, 0.975)]
            for metric in PAIRED_LOSSES
        },
    }


def _paired_grain(current: Sequence[Row], incumbent: Sequence[Row], *, fixture: bool) -> Row:
    fields = ("season", "fixture", "code") if fixture else ("season", "gw", "code")
    previous = {tuple(row[k] for k in fields): row for row in incumbent}
    if set(previous) != {tuple(row[k] for k in fields) for row in current}:
        raise ValueError("paired score populations must agree exactly")
    paired = []
    for row in current:
        other = previous[tuple(row[k] for k in fields)]
        if any(row[field] != other[field] for field in ("gw", "signed_target", "scored_target")):
            raise ValueError("paired target labels must agree exactly")
        paired.append(
            {
                **{field: row[field] for field in fields},
                "gw": row["gw"],
                "selector": row["selector"],
                "current": {m: row[m] for m in PAIRED_LOSSES},
                "incumbent": {m: other[m] for m in PAIRED_LOSSES},
                "difference": {m: row[m] - other[m] for m in PAIRED_LOSSES},
            }
        )
    selector_groups: defaultdict[str, list[Row]] = defaultdict(list)
    reason_groups: defaultdict[str, list[Row]] = defaultdict(list)
    for row in paired:
        reason_groups[row["selector"]].append(row)
        selector = (
            "SDP_PRIMARY"
            if row["selector"] == "SDP_PRIMARY"
            else "MIXED"
            if row["selector"] == "MIXED"
            else "FALLBACK"
        )
        selector_groups[selector].append(row)
    return {
        "pooled": _paired_summary(paired),
        "by_gameweek": {
            f"{s}:{g}": _paired_summary([r for r in paired if (r["season"], r["gw"]) == (s, g)])
            for s, g in sorted({(r["season"], r["gw"]) for r in paired})
        },
        "by_selector": {
            key: _paired_summary(group) for key, group in sorted(selector_groups.items())
        },
        "by_selector_reason": {
            key: _paired_summary(group) for key, group in sorted(reason_groups.items())
        },
        "uncertainty": _three_gw_uncertainty(paired),
        "row_differences": paired,
    }


def paired_comparison(
    current_predictions: Sequence[Row],
    incumbent_predictions: Sequence[Row],
    outcomes: Sequence[Row],
) -> Row:
    """Compare the frozen arms on exactly shared identities and observed populations."""
    current_keys = [_key(row) for row in current_predictions]
    incumbent_keys = [_key(row) for row in incumbent_predictions]
    if (
        len(set(current_keys)) != len(current_keys)
        or len(set(incumbent_keys)) != len(incumbent_keys)
        or set(current_keys) != set(incumbent_keys)
    ):
        raise ValueError("paired forecast populations must be exactly equal and unique")
    old = dict(zip(incumbent_keys, incumbent_predictions, strict=True))
    aligned = [(row, old[_key(row)]) for row in current_predictions]
    shared_fields = (
        *IDENTITY,
        "availability_status",
        "availability_multiplier",
        "cold_start_player",
        "transferred_no_rescale",
    )
    for current, incumbent in aligned:
        if any(current.get(field) != incumbent.get(field) for field in shared_fields):
            raise ValueError("paired forecast identity and non-environment context must agree")
    current_result = score_predictions(current_predictions, outcomes)
    incumbent_result = score_predictions(incumbent_predictions, outcomes)
    if current_result["coverage"] != incumbent_result["coverage"]:
        raise ValueError("paired scoring exclusions must agree exactly")
    fixture = _paired_grain(
        current_result["fixture_row_scores"], incumbent_result["fixture_row_scores"], fixture=True
    )
    gameweek = _paired_grain(
        current_result["player_gameweek_row_scores"],
        incumbent_result["player_gameweek_row_scores"],
        fixture=False,
    )
    equality = {
        "points_distribution": all(
            tuple(a["distribution"]) == tuple(b["distribution"]) for a, b in aligned
        ),
        "expected_points": all(a["expected_points"] == b["expected_points"] for a, b in aligned),
        "expected_bonus": all(
            a.get("expected_bonus") == b.get("expected_bonus") for a, b in aligned
        ),
        "component_inputs": all(a["components"] == b["components"] for a, b in aligned),
        "all_scored_losses": all(
            value == 0
            for grain in (fixture, gameweek)
            for row in grain["row_differences"]
            for value in row["difference"].values()
        ),
    }
    return {
        "schema": "fpl.player-model-gw1-3-paired-metrics/v1",
        "policy": {
            "difference": "current minus incumbent; negative loss difference favors current",
            "population": "exact shared forecast identities, context, outcomes and exclusions",
            "uncertainty": (
                "all 27 ordered three-GW block resamples; pooled row-weighted loss differences; "
                "linear-interpolated 2.5/97.5 percentiles; "
                "descriptive only with three GWs; no verdict"
            ),
            "selector": "current-arm selector; non-primary fixture rows grouped as FALLBACK",
        },
        "coverage": current_result["coverage"],
        "numerical_equality": all(equality.values()),
        "equality_details": equality,
        "fixture": fixture,
        "player_gameweek": gameweek,
    }
