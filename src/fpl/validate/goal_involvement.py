"""One-shot nested development run over frozen earlier-fitted component forecasts."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import random
import subprocess
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fpl.models.goal_involvement import (
    EventFit,
    EventRow,
    binary_log_loss,
    fit_event_model,
    fixture_low_counts,
    gameweek_probability,
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write("\n")


@dataclass(frozen=True)
class Fold:
    name: str
    season: str
    gw: int
    cutoff: datetime
    available: datetime
    rows: tuple[dict[str, Any], ...]


def eligible_folds(folds: list[Fold], cutoff: datetime) -> list[Fold]:
    if cutoff.tzinfo is None:
        raise ValueError("aware cutoff required")
    return sorted(
        [f for f in folds if f.available < cutoff and f.cutoff < cutoff],
        key=lambda f: (f.cutoff, f.name),
    )


def prepare_fold(raw: dict[str, Any], predictions: list[dict[str, Any]]) -> Fold:
    records = {(r["fixture"], r["code"]): r for r in raw["records"]}
    labels = {(r["fixture"], r["code"]): r for r in raw["labels"]}
    predicted = {(r["fixture"], r["code"]): r for r in predictions}
    if (
        len(records) != len(raw["records"])
        or len(labels) != len(raw["labels"])
        or len(predicted) != len(predictions)
        or records.keys() != labels.keys()
        or records.keys() != predicted.keys()
    ):
        raise ValueError("fixture labels/predictions must be unique, complete and paired")
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for key, row in records.items():
        scored, label = predicted[key], labels[key]
        if any(scored[k] != row[k] for k in ("season", "gw", "fixture", "code", "position")):
            raise ValueError("component forecast identity mismatch")
        play = 1 - row["minutes_pmf"][0]
        if not math.isclose(play, scored["p_play"], abs_tol=1e-12):
            raise ValueError("appearance identity mismatch")
        conditional = []
        for component in ("goals", "assists"):
            arm = scored["components"][component]
            if label[component] is None or label[component] != arm["actual"]:
                raise ValueError("missing or mismatched component label")
            pmf = arm["arms"]["candidate"]
            conditional.append(
                tuple(pmf)
                if row["components"][component]["fallback"] is not None
                else (max(0, (pmf[0] - (1 - play)) / play), *(p / play for p in pmf[1:]))
                if play > 0
                else (1.0, 0.0)
            )
        groups[row["code"]].append(
            {
                "position": row["position"],
                "fixture": row["fixture"],
                "low": fixture_low_counts(row["minutes_pmf"], *conditional),
                "goals_assists": label["goals"] + label["assists"],
                "cold": row["cold"],
                "play": play,
            }
        )
    rows = []
    for code, legs in sorted(groups.items()):
        if len({r["position"] for r in legs}) != 1:
            raise ValueError("ambiguous within-gameweek position")
        rows.append(
            {
                "code": code,
                "position": legs[0]["position"],
                "fixtures": sorted(r["fixture"] for r in legs),
                "baseline": gameweek_probability([r["low"] for r in legs]),
                "outcome": int(sum(r["goals_assists"] for r in legs) >= 2),
                "cold": any(r["cold"] for r in legs),
                "structural_zero": all(r["play"] == 0 for r in legs),
            }
        )
    cutoff, available = (
        datetime.fromisoformat(raw["cutoff"]),
        datetime.fromisoformat(raw["labels_available"]),
    )
    if cutoff.tzinfo is None or available.tzinfo is None or available <= cutoff:
        raise ValueError("invalid complete-GW label boundary")
    return Fold(
        f"{raw['season']}-gw{raw['gw']}", raw["season"], raw["gw"], cutoff, available, tuple(rows)
    )


def metrics(rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    n = len(rows)
    buckets: list[dict[str, Any]] = []
    for index in range(10):
        selected = [r for r in rows if min(9, int(r[arm] * 10)) == index]
        buckets.append(
            {
                "lower": index / 10,
                "count": len(selected),
                "predicted": sum(r[arm] for r in selected) / len(selected) if selected else None,
                "observed": sum(r["outcome"] for r in selected) / len(selected)
                if selected
                else None,
            }
        )
    ranking: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        ranking[row["fold"], row["position"]].append(row)
    aucs = []
    for group in ranking.values():
        yes = sum(r["outcome"] for r in group)
        no = len(group) - yes
        if not yes or not no:
            continue
        tied: dict[float, list[int]] = defaultdict(lambda: [0, 0])
        for row in group:
            tied[row[arm]][row["outcome"]] += 1
        below = wins = 0.0
        for zeros, ones in (tied[p] for p in sorted(tied)):
            wins += ones * (below + zeros / 2)
            below += zeros
        aucs.append(wins / (yes * no))
    return {
        "rows": n,
        "events": sum(r["outcome"] for r in rows),
        "log_loss": math.fsum(binary_log_loss(r[arm], r["outcome"]) for r in rows) / n,
        "brier": math.fsum((r[arm] - r["outcome"]) ** 2 for r in rows) / n,
        "calibration_error": abs(sum(r[arm] - r["outcome"] for r in rows)) / n,
        "ece": sum(b["count"] * abs(b["predicted"] - b["observed"]) for b in buckets if b["count"])
        / n,
        "reliability": buckets,
        "mean_within_position_gw_auc": sum(aucs) / len(aucs) if aucs else None,
        "auc_groups": len(aucs),
    }


def run(*, cache: Path, frozen: Path, output: Path, config_path: Path) -> None:
    root = config_path.parent.parent
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True)
    if status.strip():
        raise ValueError("commit the preregistration, implementation and tests before fitting")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    manifest_path = cache / "manifest.json"
    if sha(manifest_path) != config["input_manifest_sha256"]:
        raise ValueError("prepared manifest hash mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    folds = []
    fixture_rows = 0
    for entry in manifest["folds"]:
        if not entry["scored"]:
            continue
        source = cache / entry["file"]
        saved = frozen / "folds" / entry["file"]
        if (
            sha(source) != entry["sha256"]
            or sha(saved) != config["prediction_files"][entry["file"]]
        ):
            raise ValueError("frozen fold bytes changed")
        raw = json.loads(gzip.decompress(source.read_bytes()))
        predictions = json.loads(gzip.decompress(saved.read_bytes()))
        folds.append(prepare_fold(raw, predictions))
        fixture_rows += len(predictions)
    folds.sort(key=lambda f: (f.cutoff, f.name))
    if len(folds) != 181 or fixture_rows != 133964:
        raise ValueError("registered full-archive population changed")
    output.mkdir(parents=True, exist_ok=False)
    write(
        output / "claim.json",
        {
            "started_at": datetime.now(UTC).isoformat(),
            "head": head,
            "config_sha256": sha(config_path),
            "input_manifest_sha256": sha(manifest_path),
            "fixture_rows": fixture_rows,
            "folds": len(folds),
        },
    )
    try:
        _fit_run(folds, output, config, head)
        if (
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            != head
            or subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=root, text=True
            ).strip()
        ):
            raise ValueError("source provenance changed during formal training")
        write(
            output / "complete.json",
            {
                "head": head,
                "config_sha256": sha(config_path),
                "result_sha256": sha(output / "result.json"),
                "completed_at": datetime.now(UTC).isoformat(),
            },
        )
    except BaseException as error:
        write(
            output / "failure.json",
            {
                "at": datetime.now(UTC).isoformat(),
                "type": type(error).__name__,
                "error": str(error),
            },
        )
        raise


def _fit_run(folds: list[Fold], output: Path, config: dict[str, Any], head: str) -> None:
    grid = [
        (f"r{ridge:g}_{'slope' if slope else 'intercept'}", ridge, slope)
        for ridge in config["ridge"]
        for slope in (False, True)
    ]
    names = ["off", *(name for name, _, _ in grid)]
    histories: dict[str, dict[str, float]] = {}
    predictions_all: list[dict[str, Any]] = []
    final = Fold(
        "final",
        "2026-27",
        1,
        datetime.fromisoformat(config["final_cutoff"]),
        datetime.fromisoformat(config["final_cutoff"]),
        (),
    )
    for index, fold in enumerate([*folds, final]):
        past = eligible_folds(folds, fold.cutoff)
        training = [
            EventRow(r["position"], r["baseline"], r["outcome"]) for f in past for r in f.rows
        ]
        inner = past[-6:]
        fits: dict[str, EventFit] = {}
        enough = len(past) >= 12 and sum(r.outcome for r in training) >= 20
        if enough:
            fits = {
                name: fit_event_model(training, ridge=ridge, fit_slope=slope)
                for name, ridge, slope in grid
            }
        inner_losses = (
            {
                name: math.fsum(histories[f.name][name] for f in inner)
                / sum(len(f.rows) for f in inner)
                for name in names
            }
            if inner
            else {}
        )
        selected = "off"
        if enough and len(inner) == 6:
            for name in names[1:]:
                if inner_losses[name] < inner_losses[selected] - 1e-12:
                    selected = name
        audit = {
            "fold": fold.name,
            "cutoff": fold.cutoff.isoformat(),
            "available": fold.available.isoformat(),
            "past_folds": [f.name for f in past],
            "inner_folds": [f.name for f in inner],
            "training_rows": len(training),
            "selected": selected,
            "inner_losses": inner_losses,
            "fits": {name: asdict(fit) for name, fit in fits.items()},
            "warmup": not enough,
        }
        write(output / f"{fold.name}-fit.json", audit)
        if fold is final:
            write(
                output / "fitted_parameters.json",
                {
                    "model": config["name"],
                    "source_head": head,
                    "cutoff": final.cutoff.isoformat(),
                    "selected": selected,
                    "fit": asdict(fits[selected]) if selected in fits else None,
                    "audit": audit,
                },
            )
            break
        position_history: dict[str, list[int]] = defaultdict(list)
        player_history: dict[int, list[int]] = defaultdict(list)
        for old in past:
            for row in old.rows:
                position_history[row["position"]].append(row["outcome"])
                player_history[row["code"]].append(row["outcome"])
        predicted = []
        losses: dict[str, list[float]] = {name: [] for name in names}
        for row in fold.rows:
            base = row["baseline"]
            by_model = {"off": base}
            for name, _, _ in grid:
                by_model[name] = (
                    fits[name].predict(row["position"], base)
                    if name in fits and not row["structural_zero"]
                    else base
                )
            for name in names:
                losses[name].append(binary_log_loss(by_model[name], row["outcome"]))
            history = position_history[row["position"]]
            position = (sum(history) + 0.5) / (len(history) + 50)
            recent = player_history[row["code"]][-10:]
            predicted.append(
                {
                    **row,
                    "fold": fold.name,
                    "season": fold.season,
                    "gw": fold.gw,
                    "candidate": by_model[selected],
                    "position_prior": position,
                    "trailing": (sum(recent) + 10 * position) / (len(recent) + 10),
                }
            )
        histories[fold.name] = {name: math.fsum(values) for name, values in losses.items()}
        with gzip.open(output / f"{fold.name}-predictions.json.gz", "xb") as handle:
            handle.write(json.dumps(predicted, separators=(",", ":"), allow_nan=False).encode())
        predictions_all.extend(predicted)
        print(f"{index + 1}/181 {fold.name}: {len(predicted)} player-GWs, {selected}", flush=True)
    arms = ("baseline", "candidate", "position_prior", "trailing")
    covered = [r for r in predictions_all if r["season"] in config["covered_seasons"]]
    seasons = {
        season: {
            arm: metrics([r for r in predictions_all if r["season"] == season], arm) for arm in arms
        }
        for season in sorted({r["season"] for r in predictions_all})
    }
    summary = {arm: metrics(covered, arm) for arm in arms}
    baseline, candidate = summary["baseline"], summary["candidate"]
    lift = 1 - candidate["log_loss"] / baseline["log_loss"]
    gates = {
        "covered_log_lift": lift >= 0.01,
        "covered_brier": candidate["brier"] <= baseline["brier"],
        "season_regression": all(
            v["candidate"]["log_loss"] <= v["baseline"]["log_loss"] * 1.02 for v in seasons.values()
        ),
        "calibration": candidate["calibration_error"] <= baseline["calibration_error"] + 0.002,
        "full_coverage": len(folds) == 181,
    }
    cluster = []
    for name in sorted({r["fold"] for r in covered}):
        group = [r for r in covered if r["fold"] == name]
        cluster.append(
            tuple(
                math.fsum(binary_log_loss(r[arm], r["outcome"]) for r in group)
                for arm in ("baseline", "candidate")
            )
        )
    rng = random.Random(202627)
    lifts = []
    for _ in range(2000):
        sample = [cluster[rng.randrange(len(cluster))] for _ in cluster]
        lifts.append(1 - sum(c for _, c in sample) / sum(b for b, _ in sample))
    lifts.sort()
    result = {
        "schema": "fpl.goal-involvement-event-development",
        "version": 1,
        "folds": len(folds),
        "player_gameweeks": len(predictions_all),
        "overall": {arm: metrics(predictions_all, arm) for arm in arms},
        "covered": summary,
        "seasons": seasons,
        "positions": {
            pos: {arm: metrics([r for r in covered if r["position"] == pos], arm) for arm in arms}
            for pos in ("GK", "DEF", "MID", "FWD")
        },
        "cohorts": {
            key: {arm: metrics(group, arm) for arm in arms}
            for key, group in (
                ("cold", [r for r in covered if r["cold"]]),
                ("double_or_more", [r for r in covered if len(r["fixtures"]) > 1]),
            )
            if group
        },
        "log_lift": lift,
        "gw_bootstrap_95": [lifts[49], lifts[1949]],
        "gates": gates,
        "serving": "trained_event" if all(gates.values()) else "component_baseline",
        "scientific_status": "retrospective_development_not_deadline_validated",
        "completed_at": datetime.now(UTC).isoformat(),
    }
    write(output / "result.json", result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    run(cache=args.cache, frozen=args.frozen, output=args.output, config_path=args.config)


if __name__ == "__main__":
    main()
