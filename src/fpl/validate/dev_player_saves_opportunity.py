"""One pinned OOS shot-opportunity saves experiment; audit-only never fits a model."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import traceback
from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import yaml

from fpl.config import repo_root
from fpl.features.pit import AsOf
from fpl.jobs.competitive_participation_pilot import file_sha256, git_clean_head, publish_json
from fpl.models.gk_saves_v1 import GkSavesHistoryRow, GkSavesV1
from fpl.storage.db import connect
from fpl.types import Position
from fpl.validate import dev_v2_chance_creation as chance_reference
from fpl.validate.development_program_provenance import reserve_program_claim
from fpl.validate.development_reference_components import read_minutes_control_cache
from fpl.validate.metrics import log_score, score_predictions
from fpl.validate.player_saves_opportunity import (
    EVIDENCE_CLASS,
    NAME,
    OosShotForecast,
    ShotObservation,
    fit_precision,
    predict_saves,
)
from fpl.validate.points_harness import default_component_suite
from fpl.validate.retrospective_sdp import RetrospectiveBackfillView

CONFIG = "config/player_saves_opportunity_evaluation.yaml"
CONFIG_SHA256 = "cf777d6b4dce3d5c43891ceefdda0b6f8936c8f177ffbbbc617b2bae20ffd900"
CHANCE = "results/v2_chance_creation_development.json"
CHANCE_SHA256 = "f4cc595384102112ba2c41f118396d4176a6f7000a6f3c1753b5edf1a1ae952f"
DATABASE_SHA256 = "0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8"
SEASONS = ("2023-24", "2024-25", "2025-26")
BRANCH = "claude/comet-fpl-v2-architecture-mqrj8f"
SEED = 20260907


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, default=str, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _time(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value)
    if timestamp.utcoffset() is None:
        raise ValueError("aware historical timestamp required")
    return timestamp


def load_source(
    con: duckdb.DuckDBPyConnection,
    root: Path,
) -> tuple[list[ShotObservation], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    if file_sha256(root / CHANCE) != CHANCE_SHA256:
        raise ValueError("frozen upstream opportunity evidence changed")
    artifact = json.loads((root / CHANCE).read_bytes())
    if not artifact["completed"] or not artifact["provenance"]["clean_worktree"]:
        raise ValueError("clean completed OOS upstream required")
    # Actual outcome fields are deliberately not included in forecast objects.
    records = artifact["historical_chance_predictions"]
    forecasts = {r["key"]: r for r in records}
    if len(forecasts) != 3800 or len(records) != 3800:
        raise ValueError("frozen opportunity population changed")
    fits = {(f["season"], f["gw"]): f for f in artifact["historical_fit_provenance"]}
    for row in records:
        cutoff = _time(row["as_of"])
        volume = fits[row["season"], row["gw"]]["stage_fits"]["volume"]
        events = [
            row[k] for k in ("maximum_state_source_event", "maximum_style_training_event") if row[k]
        ]
        if volume.get("maximum_training_event"):
            events.append(volume["maximum_training_event"])
        if any(_time(v) + timedelta(hours=6) >= cutoff for v in events):
            raise ValueError("frozen opportunity upstream violates completion cutoff")
        if _time(row["kickoff_time"]) < cutoff:
            raise ValueError("frozen opportunity target precedes its recorded cutoff")
    source = RetrospectiveBackfillView(
        con, AsOf(datetime(2026, 7, 1, tzinfo=UTC))
    ).observed_real_sot(seasons=("2021-22", "2022-23", *SEASONS))
    history = []
    for raw in source.to_dicts():
        key = f"{raw['season']}:{raw['fixture']}:{raw['team_code']}"
        retained = forecasts[key]
        if (
            retained["source_capture_id"] != raw["capture_id"]
            or retained["payload_sha256"] != raw["payload_sha256"]
            or retained["team_code"] != raw["team_code"]
            or retained["opponent_team_code"] != raw["opponent_team_code"]
            or _time(retained["kickoff_time"]) != raw["kickoff_time"]
        ):
            raise ValueError("shot/SOT same-version identity contradiction")
        shots = retained["observed_shots"]
        if shots is not None and (not math.isfinite(shots) or shots < 0 or shots != int(shots)):
            raise ValueError("invalid actual source shot count")
        sot = raw["shots_on_target"]
        if shots is not None and sot is not None and not 0 <= sot <= shots:
            raise ValueError("SOT cannot exceed corresponding complete shot total")
        history.append(
            ShotObservation(
                raw["season"],
                raw["gw"],
                raw["fixture"],
                raw["team_code"],
                raw["kickoff_time"],
                int(shots) if shots is not None else None,
                sot,
                raw["capture_id"],
                raw["payload_sha256"],
                raw["source_known_at"],
            )
        )
    if len(history) != 3800:
        raise ValueError("canonical team source coverage changed")
    players = (
        con.execute("""
        SELECT p.season,p.gw,p.fixture,p.code,p.position,p.kickoff_time,p.team_id,
               p.opponent_team_id,p.was_home,p.minutes,p.saves,p.goals_conceded,t.team_code
        FROM mart_fact_player_fixture p JOIN mart_dim_team t
          ON p.season=t.season AND p.team_id=t.team_id
        WHERE p.position='GK' ORDER BY p.kickoff_time,p.season,p.fixture,p.code
    """)
        .pl()
        .to_dicts()
    )
    if len({(r["season"], r["fixture"], r["code"]) for r in players}) != len(players):
        raise ValueError("duplicate stable keeper target")
    return history, forecasts, players


def coverage(
    history: list[ShotObservation],
    forecasts: dict[str, dict[str, Any]],
    players: list[dict[str, Any]],
) -> dict[str, Any]:
    seasons = {}
    cutoffs: dict[tuple[str, int], datetime] = {}
    for row in players:
        tag = row["season"], row["gw"]
        cutoffs[tag] = min(cutoffs.get(tag, row["kickoff_time"]), row["kickoff_time"])
    eligible: list[tuple[str, int, int, int]] = []
    for season in SEASONS:
        sides = [r for r in history if r.season == season]
        measured = [r for r in sides if r.shots is not None and r.sot is not None]
        targets = [
            r
            for r in players
            if r["season"] == season
            and r["minutes"] is not None
            and r["minutes"] > 0
            and r["saves"] is not None
            and r["goals_conceded"] is not None
        ]
        for row in targets:
            own = forecasts[f"{season}:{row['fixture']}:{row['team_code']}"]
            opposite = forecasts[f"{season}:{row['fixture']}:{own['opponent_team_code']}"]
            if (
                opposite["opponent_team_code"] != row["team_code"]
                or opposite["gw"] != row["gw"]
                or opposite["was_home"] == row["was_home"]
                or _time(opposite["kickoff_time"]) != row["kickoff_time"]
                or _time(opposite["as_of"]) != cutoffs[season, row["gw"]]
            ):
                raise ValueError("keeper/opponent reciprocal identity differs")
            if opposite["predicted_shots"] is None:
                raise ValueError("nominated target lacks frozen OOS shot prediction")
        eligible.extend((r["season"], r["gw"], r["fixture"], r["code"]) for r in targets)
        seasons[season] = {
            "team_sides": len(sides),
            "joint_shots_sot": len(measured),
            "joint_coverage": len(measured) / len(sides),
            "sot_missing": sum(r.sot is None for r in sides),
            "sot_explicit_zero": sum(r.sot == 0 for r in sides),
            "eligible_keeper_appearances": len(targets),
            "folds": len({r["gw"] for r in targets}),
        }
    return {
        "database_sha256": DATABASE_SHA256,
        "upstream_sha256": CHANCE_SHA256,
        "seasons": seasons,
        "eligible_rows": len(eligible),
        "target_identity_sha256": _hash(sorted(eligible)),
        "minimum_joint_coverage": 0.95,
        "coverage_passed": all(
            v["joint_coverage"] >= 0.95 and v["team_sides"] == 760 for v in seasons.values()
        ),
        "model_fitted": False,
        "candidate_scored": False,
    }


def load_contract(root: Path) -> dict[str, Any]:
    if file_sha256(root / CONFIG) != CONFIG_SHA256:
        raise ValueError("saves preregistration exact bytes not pinned")
    contract: dict[str, Any] = yaml.safe_load((root / CONFIG).read_bytes())
    if (
        contract["candidate"] != NAME
        or contract["evidence_class"] != EVIDENCE_CLASS
        or contract["database_sha256"] != DATABASE_SHA256
        or contract["seed"] != SEED
    ):
        raise ValueError("saves policy differs")
    if file_sha256(root / contract["coverage_report"]) != contract["coverage_sha256"]:
        raise ValueError("saves coverage source drift")
    return contract


def snapshot(root: Path, db: Path) -> dict[str, Any]:
    head = git_clean_head(root)
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=root, text=True
    ).strip()
    if branch != BRANCH or Path(str(db) + ".wal").exists() or file_sha256(db) != DATABASE_SHA256:
        raise ValueError("saves wrong branch/database/WAL")
    load_contract(root)
    files = sorted(
        {
            *root.glob("src/**/*.py"),
            *root.glob("tests/**/*.py"),
            *root.glob("config/*.yaml"),
            *root.glob("results/*.json"),
            *root.glob("docs/*.md"),
            root / "AGENTS.md",
            root / "DEV-ROADMAP.md",
            root / "README.md",
        }
    )
    return {
        "git_head": head,
        "clean_worktree": True,
        "candidate": NAME,
        "evidence_class": EVIDENCE_CLASS,
        "database_sha256": DATABASE_SHA256,
        "config_sha256": CONFIG_SHA256,
        "source_sha256": {p.relative_to(root).as_posix(): file_sha256(p) for p in files},
        "production_promotion": False,
        "seed": SEED,
        "known_at_rewritten": False,
    }


def _score(rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    if not rows:
        return {"predictions": 0}
    values = asdict(
        score_predictions(
            arm,
            [tuple(r["pmfs"][arm]) for r in rows],
            [r["saves"] for r in rows],
            seed=SEED,
            rank_groups=[f"{r['season']}:{r['gw']}" for r in rows],
            cold_starts=[r["cold_start"] for r in rows],
        )
    )
    values["mean_error"] = math.fsum(
        sum(i * p for i, p in enumerate(r["pmfs"][arm])) - r["saves"] for r in rows
    ) / len(rows)
    rates = [sum(i * p for i, p in enumerate(r["pmfs"][arm])) for r in rows]
    avg = math.fsum(rates) / len(rates)
    values["predicted_rate_sd"] = math.sqrt(math.fsum((v - avg) ** 2 for v in rates) / len(rates))
    return values


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    parts: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        tags = [
            "overall",
            row["season"],
            "home" if row["was_home"] else "away",
            "early_gw_1_6" if row["gw"] <= 6 else "later_gw_7_plus",
            "cold_start" if row["cold_start"] else "established",
            "price_proxy" if row["price_proxy_dependent"] else "non_proxy",
            "high_sot"
            if row["expected_sot_faced"] is not None and row["expected_sot_faced"] >= 4
            else "low_or_unavailable_sot",
        ]
        for tag in tags:
            parts[tag].append(row)
    scores = {
        tag: {arm: _score(part, arm) for arm in ("incumbent", "candidate")}
        for tag, part in sorted(parts.items())
    }
    old, new = (scores["overall"][arm] for arm in ("incumbent", "candidate"))
    lift = 1 - new["mean_log_score"] / old["mean_log_score"]
    gate = {
        "log_lift": lift >= 0.01,
        "crps": new["mean_crps"] <= old["mean_crps"],
        "pit80": abs(new["pit_interval_80_coverage"] - 0.8) <= 0.05,
        "every_season_one_percent": all(
            1 - scores[s]["candidate"]["mean_log_score"] / scores[s]["incumbent"]["mean_log_score"]
            >= 0.01
            for s in SEASONS
        ),
        "every_season_calibration_and_crps": all(
            scores[s]["candidate"]["mean_crps"] <= scores[s]["incumbent"]["mean_crps"]
            and abs(scores[s]["candidate"]["pit_interval_80_coverage"] - 0.8) <= 0.05
            for s in SEASONS
        ),
        "zero_leakage": True,
        "same_population": True,
    }
    paired: defaultdict[str, list[float]] = defaultdict(list)
    for row in rows:
        paired[f"{row['season']}:{row['gw']}"].append(
            log_score(tuple(row["pmfs"]["candidate"]), row["saves"])
            - log_score(tuple(row["pmfs"]["incumbent"]), row["saves"])
        )
    n, g = len(rows), len(paired)
    mean = math.fsum(v for vals in paired.values() for v in vals) / n
    se = (
        math.sqrt(
            g
            / (g - 1)
            * math.fsum((math.fsum(vals) - len(vals) * mean) ** 2 for vals in paired.values())
            / (n * n)
        )
        if g > 1
        else 0.0
    )
    shot_pairs = [r for r in rows if r["actual_sot_faced"] is not None]
    diagnostics = {}
    for label, field in [
        ("candidate", "expected_sot_faced"),
        ("incumbent_implied", "incumbent_implied_sot"),
    ]:
        pairs = [r for r in shot_pairs if r[field] is not None]
        diagnostics[label] = {
            "rows": len(pairs),
            "rmse": math.sqrt(
                math.fsum((r[field] - r["actual_sot_faced"]) ** 2 for r in pairs) / len(pairs)
            )
            if pairs
            else None,
        }
    return {
        "scores": scores,
        "gate": gate,
        "relative_log_lift": lift,
        "verdict": "SUPPORTED"
        if all(gate.values())
        else "REFUTED"
        if lift <= -0.01
        else "INCONCLUSIVE",
        "synthesis_eligible": all(gate.values()),
        "promotion_permitted": False,
        "paired": {
            "difference": mean,
            "gw_clustered_standard_error": se,
            "clusters": g,
            "normal_95_interval": [mean - 1.96 * se, mean + 1.96 * se],
        },
        "sot_diagnostics": diagnostics,
    }


def run(root: Path, db: Path, cache_dir: Path, output: Path) -> None:
    root, db, output = root.resolve(), db.resolve(), output.resolve()
    if output.exists():
        raise FileExistsError("write-once output exists")
    if output.is_relative_to(root):
        raise ValueError("new external output is required for clean provenance")
    before = snapshot(root, db)
    contract = load_contract(root)
    cache = read_minutes_control_cache(cache_dir, db=db, root=root)
    with connect(db, read_only=True) as con:
        history, forecasts, players = load_source(con, root)
        audit = coverage(history, forecasts, players)
        if not audit["coverage_passed"] or audit != json.loads(
            (root / contract["coverage_report"]).read_bytes()
        ):
            raise ValueError("coverage/population reproduction failed before claim")
        # Pure incumbent-only reproduction; never calls Phase A candidate fitting or runner.
        old_contract = yaml.safe_load((root / chance_reference.CONFIG).read_bytes())
        upstream = chance_reference._load_upstream(root, old_contract)
        team_pmfs, reproduction = chance_reference.reproduce_incumbent(con, old_contract, upstream)
    labels = {(r["season"], r["fixture"], r["code"]): r for r in players}
    chance_fits = {
        (f["season"], f["gw"]): f
        for f in json.loads((root / CHANCE).read_bytes())["historical_fit_provenance"]
    }
    shot_lookup = {(r.season, r.fixture, r.team_code): r for r in history}
    controls = {}
    by_fold = {}
    keeper_comparisons = 0
    maximum_keeper_difference = 0.0
    for fold in cache.folds:
        prior = [r for r in players if r["kickoff_time"] < fold.as_of]
        if any(
            r["kickoff_time"] + timedelta(hours=6) >= fold.as_of
            or (r["season"], r["gw"]) == (fold.season, fold.gw)
            for r in prior
        ):
            raise ValueError("current keeper reference history violates completion/GW guard")
        histories = [
            GkSavesHistoryRow(Position.GK, r["minutes"], r["saves"], r["goals_conceded"])
            for r in prior
            if r["minutes"] is not None
        ]
        direct = GkSavesV1()
        direct.fit(histories)
        actual = default_component_suite().fit_saves(histories)
        selected = []
        for row in fold.rows:
            t = row.target
            if t.position is not Position.GK:
                continue
            y = labels[(t.season, t.fixture, t.code)]
            if (
                y["minutes"] is None
                or y["minutes"] <= 0
                or y["saves"] is None
                or y["goals_conceded"] is None
            ):
                continue
            own = forecasts[f"{t.season}:{t.fixture}:{row.team_code}"]
            key = f"{t.season}:{t.fixture}:{own['opponent_team_code']}"
            goal_pmf = team_pmfs[key][1]
            rate = sum(i * p for i, p in enumerate(goal_pmf))
            pmf = direct.predict(Position.GK, rate)
            factory_pmf = actual.predict(Position.GK, rate)
            if pmf != factory_pmf:
                raise ValueError("current saves factory/direct comparator differ")
            maximum_keeper_difference = max(
                maximum_keeper_difference,
                max(abs(a - b) for a, b in zip(pmf, factory_pmf, strict=True)),
            )
            keeper_comparisons += 1
            controls[(t.season, t.fixture, t.code)] = (pmf, direct.save_rate, rate)
            selected.append((row, y, key))
        by_fold[(fold.season, fold.gw)] = selected
    if len(controls) != audit["eligible_rows"] or keeper_comparisons != len(controls):
        raise ValueError("keeper comparator population differs")
    reproduction["keeper_comparator"] = {
        "identity": "gk_saves_poisson_from_team_conceded_v1",
        "compared_rows": keeper_comparisons,
        "folds": len(by_fold),
        "maximum_absolute_pmf_difference": maximum_keeper_difference,
        "absolute_tolerance": 0.0,
        "actual_component_suite_factory_checked": True,
        "reciprocal_current_team_pmf_expectation_used": True,
    }
    if snapshot(root, db) != before:
        raise ValueError("source changed before claim")
    claim = reserve_program_claim(root, NAME, before)
    started_at = datetime.now(UTC).isoformat()
    output.mkdir(parents=True, exist_ok=False)
    rows, folds = [], []
    try:
        publish_json(output / "provenance.json", before)
        for fold in cache.folds:
            precision = fit_precision(history, as_of=fold.as_of, excluded_gw=(fold.season, fold.gw))
            current = []
            for ref, y, key in by_fold[(fold.season, fold.gw)]:
                source = forecasts[key]
                if _time(source["as_of"]) != fold.as_of:
                    raise ValueError("stored upstream cutoff cannot be rewritten")
                events = [
                    source[k]
                    for k in ("maximum_state_source_event", "maximum_style_training_event")
                    if source[k]
                ]
                volume_fit = chance_fits[fold.season, fold.gw]["stage_fits"]["volume"]
                if volume_fit.get("maximum_training_event"):
                    events.append(volume_fit["maximum_training_event"])
                maximum = max((_time(v) for v in events), default=None)
                forecast = OosShotForecast(
                    fold.season,
                    fold.gw,
                    ref.target.fixture,
                    source["team_code"],
                    ref.team_code,
                    fold.as_of,
                    ref.target.kickoff_time,
                    source["predicted_shots"],
                    maximum,
                    CHANCE_SHA256,
                )
                control, save_fraction, conceded = controls[
                    (fold.season, ref.target.fixture, ref.target.code)
                ]
                predicted = predict_saves(
                    forecast, precision, save_fraction=save_fraction, incumbent=control
                )
                opposite = shot_lookup[fold.season, ref.target.fixture, source["team_code"]]
                record = {
                    "season": fold.season,
                    "gw": fold.gw,
                    "fixture": ref.target.fixture,
                    "code": ref.target.code,
                    "team_code": ref.team_code,
                    "as_of": fold.as_of.isoformat(),
                    "kickoff": ref.target.kickoff_time.isoformat(),
                    "was_home": ref.target.was_home,
                    "saves": y["saves"],
                    "observed_minutes": y["minutes"],
                    "cold_start": ref.cold_start,
                    "price_proxy_dependent": ref.price_proxy_dependent,
                    "selector_provenance": json.loads(ref.selector_provenance_json),
                    "minutes_pmf": ref.minutes,
                    "upstream_key": key,
                    "upstream_hash": CHANCE_SHA256,
                    "maximum_upstream_training_event": maximum.isoformat() if maximum else None,
                    "pmfs": {"incumbent": control, "candidate": predicted.probabilities},
                    "expected_sot_faced": predicted.expected_sot_faced,
                    "actual_sot_faced": opposite.sot,
                    "original_capture": asdict(opposite),
                    "incumbent_implied_sot": conceded / (1 - save_fraction),
                    "save_fraction": save_fraction,
                    "candidate_rate": predicted.rate,
                    "fallback": predicted.fallback,
                }
                current.append(record)
            name = f"{fold.season}-gw{fold.gw:02d}.json"
            # Publish helper needs JSON-native timestamps, preserving original values exactly.
            body = json.loads(
                json.dumps({"rows": current, "precision": asdict(precision)}, default=str)
            )
            publish_json(output / name, body)
            folds.append({"file": name, "sha256": file_sha256(output / name), "rows": len(current)})
            rows.extend(body["rows"])
        summary = summarize(rows)
        if snapshot(root, db) != before:
            raise ValueError("saves clean source provenance changed during formal run")
        read_minutes_control_cache(cache_dir, db=db, root=root)
        publish_json(
            output / "result.json",
            {
                "completed": True,
                "provenance": before,
                "claim": str(claim),
                "coverage": audit,
                "comparator_reproduction": reproduction,
                "started_at_utc": started_at,
                "folds": folds,
                "rows": rows,
                **summary,
                "finished_at_utc": datetime.now(UTC).isoformat(),
            },
        )
    except Exception as error:
        publish_json(
            output / "failure.json",
            {
                "completed": False,
                "claim_consumed": True,
                "error": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
                "provenance": before,
                "retained_folds": folds,
            },
        )
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minutes-cache", type=Path)
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()
    root = repo_root()
    if Path(str(args.db) + ".wal").exists() or file_sha256(args.db) != DATABASE_SHA256:
        raise ValueError("source database differs")
    if args.audit_only:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with connect(args.db, read_only=True) as con:
            publish_json(args.output, coverage(*load_source(con, root)))
    elif args.minutes_cache is None:
        parser.error("--minutes-cache required for formal run")
    else:
        run(root, args.db, args.minutes_cache, args.output)


if __name__ == "__main__":
    main()
