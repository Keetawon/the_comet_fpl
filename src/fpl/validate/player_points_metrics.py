"""Read-only paired scores on the preserved 0..34 full-points support.

This module neither fits nor selects a model and makes no temporal-validity claim.
The runner owns provenance, source cutoffs, fixed population and all decision gates.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any, cast

from fpl.validate.metrics import (
    PROBABILITY_FLOOR,
    log_score,
    score_predictions,
    spearman_within_groups,
)

ARMS = ("incumbent", "candidate")
FLAGS = (
    "was_home",
    "cold_start",
    "direct_price_proxy",
    "team_price_proxy",
    "fixture_price_proxy",
    "promoted_team",
    "rotation_risk",
)
ROLES = ("high", "low", "unavailable")
WORKLOAD = ("witnessed_over90m_7d", "witnessed_up_to90m_7d", "unavailable")
FIXED_SLICES = (
    *("position:" + position for position in ("GK", "DEF", "MID", "FWD")),
    "GW1-6",
    "GW7+",
    "home",
    "away",
    "cold_start",
    "established",
    "direct_price_proxy",
    "non_proxy",
    "team_price_proxy",
    "no_team_price_proxy",
    "fixture_price_proxy",
    "no_fixture_price_proxy",
    "promoted",
    "established_team",
    "rotation_risk",
    "no_rotation_risk",
    *("role_confidence:" + role for role in ROLES),
    *("workload_scope:" + scope for scope in WORKLOAD),
)


def _validate(rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise ValueError("nonempty fixed points population required")
    if PROBABILITY_FLOOR != 1e-12:
        raise ValueError("existing points log-probability floor changed")
    seen = set()
    fixture_gameweeks: dict[tuple[str, int], int] = {}
    required = {
        "season",
        "gw",
        "fixture",
        "code",
        "position",
        "signed_target",
        "scored_target",
        "incumbent_pmf",
        "candidate_pmf",
        "role_confidence",
        "workload_scope",
        *FLAGS,
    }
    for row in rows:
        if not required <= row.keys():
            raise ValueError("incomplete points scoring row")
        key = tuple(row[k] for k in ("season", "fixture", "code"))
        if (
            not isinstance(row["season"], str)
            or not row["season"]
            or any(type(row[k]) is not int or row[k] <= 0 for k in ("gw", "fixture", "code"))
            or key in seen
            or row["position"] not in ("GK", "DEF", "MID", "FWD")
        ):
            raise ValueError("unique stable player-fixture scoring identity required")
        seen.add(key)
        fixture_key = (row["season"], row["fixture"])
        if fixture_gameweeks.setdefault(fixture_key, row["gw"]) != row["gw"]:
            raise ValueError("each season-qualified fixture requires one gameweek")
        if (
            any(type(row[k]) is not bool for k in FLAGS)
            or row["role_confidence"] not in ROLES
            or row["workload_scope"] not in WORKLOAD
        ):
            raise ValueError("typed fixed scoring slice labels required")
        if (
            type(row["signed_target"]) is not int
            or type(row["scored_target"]) is not int
            or row["scored_target"] != min(34, max(0, row["signed_target"]))
        ):
            raise ValueError("retain integer signed target and its exact 0..34 coarsening")
        for arm in ARMS:
            pmf = row[arm + "_pmf"]
            if (
                not isinstance(pmf, (tuple, list))
                or len(pmf) != 35
                or any(
                    type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1
                    for p in pmf
                )
                or not math.isclose(math.fsum(pmf), 1, rel_tol=0, abs_tol=1e-12)
            ):
                raise ValueError("full finite normalized 35-mass points PMF required")


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None  # Undefined rank correlation remains unavailable, never fabricated as zero.
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _arm_scores(rows: Sequence[Mapping[str, Any]], arm: str, seed: int) -> dict[str, Any]:
    pmfs = [tuple(r[arm + "_pmf"]) for r in rows]
    targets = [r["scored_target"] for r in rows]
    metrics = asdict(
        score_predictions(
            arm,
            pmfs,
            targets,
            seed=seed,
            cold_starts=[r["cold_start"] for r in rows],
            rank_groups=[f"{r['season']}:{r['gw']}" for r in rows],
        )
    )
    pit = metrics.pop("pit_values")  # PMFs/seed reproduce these; retain aggregate diagnostics.
    expected = [sum(i * p for i, p in enumerate(pmf)) for pmf in pmfs]
    n = len(rows)
    metrics.update(
        {
            "mean_xp": math.fsum(expected) / n,
            "mean_log_score_standard_error": metrics["mean_log_score_standard_error"]
            if n > 1
            else None,
            "pit_interval_80_absolute_error": abs(metrics["pit_interval_80_coverage"] - 0.8),
            "pit_histogram": [sum(min(int(p * 10), 9) == b for p in pit) for b in range(10)],
            "mean_error": math.fsum(p - y for p, y in zip(expected, targets, strict=True)) / n,
            "signed_target_mean_error": math.fsum(
                p - r["signed_target"] for p, r in zip(expected, rows, strict=True)
            )
            / n,
            "signed_target_mae": math.fsum(
                abs(p - r["signed_target"]) for p, r in zip(expected, rows, strict=True)
            )
            / n,
            "spearman_within_gameweek_position": spearman_within_groups(
                expected,
                targets,
                [f"{r['season']}:{r['gw']}:{r['position']}" for r in rows],
            ),
            "zero_target_bin_count": sum(p[y] == 0 for p, y in zip(pmfs, targets, strict=True)),
            "log_floor_hit_count": sum(
                p[y] < PROBABILITY_FLOOR for p, y in zip(pmfs, targets, strict=True)
            ),
        }
    )
    events = {}
    for label, indices, outcomes in (
        ("blank_le2", range(3), [int(y <= 2) for y in targets]),
        ("points_ge5", range(5, 35), [int(y >= 5) for y in targets]),
        ("points_ge10", range(10, 35), [int(y >= 10) for y in targets]),
    ):
        # Only cap a derived endpoint's possible floating-point overshoot of one.
        probabilities = [min(1.0, math.fsum(p[i] for i in indices)) for p in pmfs]
        reliability = []
        for b in range(10):
            pairs = [
                (p, y)
                for p, y in zip(probabilities, outcomes, strict=True)
                if min(int(p * 10), 9) == b
            ]
            reliability.append(
                {
                    "lower": b / 10,
                    "upper": (b + 1) / 10,
                    "rows": len(pairs),
                    "predicted": math.fsum(p for p, _ in pairs) / len(pairs) if pairs else None,
                    "observed": sum(y for _, y in pairs) / len(pairs) if pairs else None,
                }
            )
        events[label] = {
            "brier": math.fsum((p - y) ** 2 for p, y in zip(probabilities, outcomes, strict=True))
            / n,
            "mean_probability": math.fsum(probabilities) / n,
            "observed_rate": sum(outcomes) / n,
            "reliability": reliability,
        }
    metrics["events"] = events
    return metrics


def _block(rows: Sequence[Mapping[str, Any]], seed: int) -> dict[str, Any]:
    return {"rows": len(rows), **{a: _arm_scores(rows, a, seed) if rows else None for a in ARMS}}


def _tags(row: Mapping[str, Any]) -> tuple[str, ...]:
    return (
        "season:" + row["season"],
        f"gameweek:{row['season']}:{row['gw']}",
        "position:" + row["position"],
        "GW1-6" if row["gw"] <= 6 else "GW7+",
        "home" if row["was_home"] else "away",
        "cold_start" if row["cold_start"] else "established",
        "direct_price_proxy" if row["direct_price_proxy"] else "non_proxy",
        "team_price_proxy" if row["team_price_proxy"] else "no_team_price_proxy",
        "fixture_price_proxy" if row["fixture_price_proxy"] else "no_fixture_price_proxy",
        "promoted" if row["promoted_team"] else "established_team",
        "rotation_risk" if row["rotation_risk"] else "no_rotation_risk",
        "role_confidence:" + row["role_confidence"],
        "workload_scope:" + row["workload_scope"],
    )


def _paired(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_gw: defaultdict[tuple[str, int], list[float]] = defaultdict(list)
    fixtures: defaultdict[tuple[str, int, int], list[dict[str, Any]]] = defaultdict(list)
    losses = []
    for row in rows:
        old, new = (log_score(tuple(row[a + "_pmf"]), row["scored_target"]) for a in ARMS)
        loss = {k: row[k] for k in ("season", "gw", "fixture", "code")}
        loss.update({"incumbent_loss": old, "candidate_loss": new, "difference": new - old})
        losses.append(loss)
        by_gw[row["season"], row["gw"]].append(new - old)
        fixtures[row["season"], row["gw"], row["fixture"]].append(loss)
    n, groups = len(rows), len(by_gw)
    mean = math.fsum(r["difference"] for r in losses) / n
    se = (
        math.sqrt(
            groups
            / (groups - 1)
            * math.fsum((math.fsum(v) - len(v) * mean) ** 2 for v in by_gw.values())
        )
        / n
        if groups > 1
        else None
    )
    return {
        "score": "negative_log_probability",
        "paired_mean": mean,
        "gw_clustered_standard_error": se,
        "clusters": groups,
        "normal_95_interval": [mean - 1.96 * se, mean + 1.96 * se] if se is not None else None,
        "serial_dependence_adjusted": False,
        "negative_favours": "candidate",
        "row_losses": losses,
        "fixture_losses": [
            {
                "season": key[0],
                "gw": key[1],
                "fixture": key[2],
                "rows": len(values),
                "incumbent_loss": math.fsum(r["incumbent_loss"] for r in values) / len(values),
                "candidate_loss": math.fsum(r["candidate_loss"] for r in values) / len(values),
                "difference": math.fsum(r["difference"] for r in values) / len(values),
            }
            for key, values in sorted(fixtures.items())
        ],
    }


def summarize_points(rows: Sequence[Mapping[str, Any]], *, seed: int = 202627) -> dict[str, Any]:
    """Paired metrics only; no decision gate, hidden exclusions or model selection.

    Arm PMFs are top-level ``incumbent_pmf`` / ``candidate_pmf``. Input order is
    canonicalized before seeded PIT so a retained-row permutation changes no score.
    """
    _validate(rows)
    if type(seed) is not int:
        raise ValueError("explicit integer scoring seed required")
    ordered = sorted(rows, key=lambda r: (r["season"], r["gw"], r["fixture"], r["code"]))
    groups: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(
        list, {label: [] for label in FIXED_SLICES}
    )
    for row in ordered:
        for label in _tags(row):
            groups[label].append(row)
    groups["direct_proxy_exclusion_diagnostic_only"] = [
        r for r in ordered if not r["direct_price_proxy"]
    ]
    return cast(
        dict[str, Any],
        _json_safe(
            {
                "overall": _block(ordered, seed),
                "slices": {label: _block(values, seed) for label, values in sorted(groups.items())},
                "paired_vs_incumbent": _paired(ordered),
                "seed": seed,
                "log_probability_floor": PROBABILITY_FLOOR,
                "signed_targets_below_zero": sum(r["signed_target"] < 0 for r in ordered),
                "signed_targets_above_34": sum(r["signed_target"] > 34 for r in ordered),
                "primary_population_changed_by_proxy_diagnostic": False,
            }
        ),
    )
