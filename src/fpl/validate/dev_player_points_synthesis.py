"""One clean, write-once full-points development synthesis; no component fits."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
import traceback
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import yaml

from fpl.config import load_scoring_rules, repo_root
from fpl.jobs.competitive_participation_pilot import file_sha256, git_clean_head, publish_json
from fpl.storage.db import connect
from fpl.types import Position
from fpl.validate.current_component_reference_cache import load_component_reference_cache
from fpl.validate.development_program_provenance import reserve_program_claim
from fpl.validate.development_reference_components import (
    DevelopmentReferenceComponents,
    compose_reference_fixture,
)
from fpl.validate.player_points_inputs import load_saves_projection
from fpl.validate.player_points_metrics import summarize_points
from fpl.validate.player_points_synthesis import (
    NAME,
    build_composer_context,
    compose_synthesis_fixture,
)
from fpl.validate.player_role_cache import load_role_cache
from fpl.validate.points_harness import TARGET_RULESET
from fpl.validate.points_harness_v3 import _LABEL_COMPONENT_COLUMNS, full_points
from fpl.validate.v2_environment_harness import promoted_team_codes

CONFIG = "config/player_points_synthesis_evaluation.yaml"
CONFIG_SHA256 = "32f4fb23282e2081897060701446252fb40a75cf450e363b25937f5c58fb7047"
BRANCH = "claude/comet-fpl-v2-architecture-mqrj8f"
EVIDENCE_CLASS = "retrospective_competitive_backfill_and_archive_price_proxy_development"
logger = logging.getLogger(__name__)


def read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_bytes()))


def bind_projection_sources(provenance: dict[str, Any], sources: dict[str, str]) -> dict[str, Any]:
    current = {path: file_sha256(Path(path)) for path in sources}
    if current != sources:
        raise ValueError("saved projection source/provenance changed")
    return {**provenance, "projection_source_sha256": current}


def load_contract(root: Path) -> dict[str, Any]:
    if file_sha256(root / CONFIG) != CONFIG_SHA256:
        raise ValueError("synthesis preregistration missing or changed")
    config = cast(dict[str, Any], yaml.safe_load((root / CONFIG).read_bytes()))
    if (
        config["candidate"] != NAME
        or config["registration_status"] != "REGISTERED"
        or config["evidence_class"] != EVIDENCE_CLASS
        or config["accepted_replacements"] != ["saves"]
        or config["promotion_permitted"] is not False
    ):
        raise ValueError("exact registered development-only synthesis required")
    return config


def retained_folds(result_path: Path) -> tuple[dict[str, Any], ...]:
    result = read_json(result_path)
    if result["completed"] is not True:
        raise ValueError("completed immutable upstream result required")
    seen: set[str] = set()
    rows = []
    for item in result["folds"]:
        name = item["file"]
        path = (result_path.parent / name).resolve()
        if path.parent != result_path.parent.resolve() or name in seen:
            raise ValueError("upstream fold path/identity duplicate")
        seen.add(name)
        if file_sha256(path) != item["sha256"]:
            raise ValueError("upstream fold content changed")
        rows.append(read_json(path))
    return tuple(rows)


def acceptance(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    """Mechanically use passed successor, otherwise incumbent; no cherry-picking."""
    accepted = []
    receipts = {}
    for component, item in config["component_results"].items():
        path = root / item["file"]
        if file_sha256(path) != item["sha256"]:
            raise ValueError("frozen component decision evidence changed")
        result = read_json(path)
        if result["completed"] is not True:
            raise ValueError("every component must have a retained complete result")
        verdict = result["verdict"]
        passed = verdict in ("SUPPORTED", "SUPPORTED_FOR_DEVELOPMENT")
        explicit = result.get("development_synthesis_eligible", result.get("synthesis_eligible"))
        if explicit is not None:
            passed = passed and explicit is True
        gates = result.get("gate", result.get("gates"))
        if passed and gates is not None:
            passed = all(value is True for value in gates.values())
        if passed:
            accepted.append(component)
        receipts[component] = {
            "result_sha256": item["sha256"],
            "verdict": verdict,
            "accepted": passed,
            "used": item["candidate"] if passed else item["incumbent"],
        }
    if sorted(accepted) != config["accepted_replacements"]:
        raise ValueError("mechanical component acceptance differs; do not score a changed stack")
    return receipts


def snapshot(root: Path, db: Path, inputs: dict[str, Path]) -> dict[str, Any]:
    head = git_clean_head(root)
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=root, text=True
    ).strip()
    config = load_contract(root)
    if branch != BRANCH or Path(str(db) + ".wal").exists():
        raise ValueError("clean exact V2 branch and preserved database without WAL required")
    if file_sha256(db) != config["database_sha256"]:
        raise ValueError("synthesis database differs from frozen reference")
    external = {}
    for key, pin in config["external_inputs"].items():
        path = inputs[key]
        if file_sha256(path) != pin:
            raise ValueError(f"external input changed: {key}")
        external[str(path.resolve())] = pin
        receipt = read_json(path)
        for item in receipt.get("folds", []) if isinstance(receipt, dict) else []:
            filename = item.get("file")
            if filename is None:
                continue
            child = (path.parent / filename).resolve()
            if child.parent != path.parent.resolve() or file_sha256(child) != item["sha256"]:
                raise ValueError("external input fold path/hash differs")
            external[str(child)] = item["sha256"]
    sources = sorted(
        {
            *root.glob("src/**/*.py"),
            *root.glob("tests/**/*.py"),
            *root.glob("config/*.yaml"),
            *root.glob("docs/*.md"),
            *root.glob("results/*.json"),
            root / "AGENTS.md",
            root / "DEV-ROADMAP.md",
            root / "README.md",
        }
    )
    return {
        "git_head": head,
        "branch": branch,
        "clean_worktree": True,
        "candidate": NAME,
        "evidence_class": EVIDENCE_CLASS,
        "database_path": str(db.resolve()),
        "database_sha256": config["database_sha256"],
        "config_sha256": CONFIG_SHA256,
        "source_sha256": {p.relative_to(root).as_posix(): file_sha256(p) for p in sources},
        "external_source_sha256": external,
        "seed": config["seed"],
        "component_acceptance": acceptance(root, config),
        "component_fits": 0,
        "historical_deadline_validity": False,
        "known_at_rewritten": False,
        "promotion_permitted": False,
    }


def target_labels(
    db: Path, references: tuple[DevelopmentReferenceComponents, ...], config: dict[str, Any]
) -> tuple[dict[tuple[str, int, int], dict[str, Any]], set[int]]:
    keys = {
        (r.target.season, r.target.gw, r.target.fixture, r.target.code)
        for f in references
        for r in f.rows
    }
    identity = hashlib.sha256(json.dumps(sorted(keys), separators=(",", ":")).encode()).hexdigest()
    if identity != config["target_identity_sha256"]:
        raise ValueError("coverage-only nominated fixture/player identities changed")
    with connect(db, read_only=True) as con:
        rows = (
            con.execute(
                "SELECT season,gw,fixture,code,position,"
                + ",".join(_LABEL_COMPONENT_COLUMNS)
                + " FROM mart_fact_player_fixture WHERE season='2025-26' AND minutes IS NOT NULL"
                + " AND position IN ('GK','DEF','MID','FWD') ORDER BY gw,fixture,code"
            )
            .pl()
            .to_dicts()
        )
        promoted = set(promoted_team_codes(con)["2025-26"])
    if (
        len(rows) != len(keys)
        or {(r["season"], r["gw"], r["fixture"], r["code"]) for r in rows} != keys
    ):
        raise ValueError("target population differs from independently fixed reference")
    labels = {}
    rules = load_scoring_rules(TARGET_RULESET)
    for row in rows:
        if any(row[c] is None for c in _LABEL_COMPONENT_COLUMNS):
            raise ValueError("full points requires every measured label; missing is not zero")
        signed, bonus = full_points(row, Position(row["position"]), rules)
        labels[row["season"], row["fixture"], row["code"]] = {
            "signed_target": signed,
            "scored_target": min(34, max(0, signed)),
            "realised_bonus": bonus,
            "observed_minutes": row["minutes"],
            "target_components": {c: row[c] for c in _LABEL_COMPONENT_COLUMNS},
        }
    return labels, promoted


def decision(scores: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    block = scores["overall"]
    old, new = block["incumbent"], block["candidate"]
    lift = (old["mean_log_score"] - new["mean_log_score"]) / old["mean_log_score"]
    gate = {
        "primary_one_percent": lift >= config["minimum_log_lift"],
        "crps_no_regression": new["mean_crps"] <= old["mean_crps"],
        "pit80": new["pit_interval_80_absolute_error"] <= config["maximum_pit80_error"],
        "major_position_log_guard": all(
            s["candidate"]["mean_log_score"]
            <= s["incumbent"]["mean_log_score"] * (1 + config["maximum_position_log_regression"])
            for key, s in scores["slices"].items()
            if key.startswith("position:") and s["rows"]
        ),
        "ranking_guard": new["spearman_within_gameweek"] is not None
        and old["spearman_within_gameweek"] is not None
        and new["spearman_within_gameweek"]
        >= old["spearman_within_gameweek"]
        - abs(old["spearman_within_gameweek"]) * config["maximum_ranking_regression"],
        "same_population": block["rows"] == config["expected_rows"],
        "zero_temporal_violations": True,
    }
    return {
        "gate": gate,
        "relative_log_lift": lift,
        "verdict": "SUPPORTED"
        if all(gate.values())
        else "REFUTED"
        if lift <= -config["refutation_relative_regression"]
        else "INCONCLUSIVE",
        "development_only": True,
        "promotion_permitted": False,
        "cross_season_robustness": "unavailable_one_eligible_season",
    }


def run(*, root: Path, db: Path, inputs: dict[str, Path], output: Path) -> dict[str, Any]:
    if output.resolve().is_relative_to(root.resolve()):
        raise ValueError("synthesis output must remain external to the worktree")
    if output.exists() or output.is_symlink():
        raise FileExistsError("new external write-once synthesis output required")
    config = load_contract(root)
    provenance = snapshot(root, db, inputs)
    references = tuple(
        f
        for f in load_component_reference_cache(
            inputs["component_manifest"].parent,
            root=root,
            db=db,
            minutes_cache=inputs["minutes_manifest"].parent,
            expected_manifest_sha256=config["external_inputs"]["component_manifest"],
        )
        if f.season == "2025-26"
    )
    if (
        len(references) != config["expected_folds"]
        or sum(len(f.rows) for f in references) != config["expected_rows"]
    ):
        raise ValueError("exact full-points coverage cohort required")
    labels, promoted = target_labels(db, references, config)
    roles = load_role_cache(inputs["roles"], root=root)
    role_by_key = {
        (p.target.season, p.target.fixture, p.target.code): p
        for batch in roles.values()
        for p in batch.predictions
    }
    workload = {
        (r["season"], r["fixture"], r["code"]): r
        for fold in retained_folds(inputs["workload"])
        for r in fold["rows"]
    }
    projection = load_saves_projection(inputs["saves"], inputs["chance"])
    provenance = bind_projection_sources(provenance, projection.source_files)
    # Prevalidate EVERY current roster keeper, not the appeared-keeper scored cohort.
    projected = {
        (f.season, fixture): projection.project(f, fixture)
        for f in references
        for fixture in sorted({r.target.fixture for r in f.rows})
    }
    direct_proxies = sum(r.direct_price_proxy for f in references for r in f.rows)
    if (
        len(projected) != config["expected_fixtures"]
        or direct_proxies != config["expected_direct_proxy_rows"]
    ):
        raise ValueError("nominated fixture/proxy counts changed")
    context = build_composer_context()
    output.mkdir(parents=True, exist_ok=False)
    folds: list[dict[str, Any]] = []
    control_folds: list[dict[str, Any]] = []
    claim: Path | None = None
    started = datetime.now(UTC).isoformat()
    try:
        controls = {}
        for f in references:
            retained = []
            for fixture in sorted({r.target.fixture for r in f.rows}):
                original = compose_reference_fixture(f, fixture)
                current = compose_synthesis_fixture(f, fixture, context)
                if original != current:
                    raise ValueError("zero-correction current composer PMF reproduction failed")
                for composed in current:
                    key = f.season, fixture, composed.code
                    if key in controls:
                        raise ValueError("duplicate current full-points player identity")
                    controls[key] = composed
                    retained.append({"fixture": fixture, **asdict(composed)})
            control_name = f"control-{f.season}-gw{f.gw:02d}.json"
            publish_json(output / control_name, {"rows": retained})
            control_folds.append(
                {
                    "file": control_name,
                    "sha256": file_sha256(output / control_name),
                    "rows": len(retained),
                    "season": f.season,
                    "gw": f.gw,
                }
            )
            logger.info("synthesis CURRENT exact reproduction GW%s (%s/38)", f.gw, f.gw)
        if set(controls) != set(labels):
            raise ValueError("current full-points fixture identity differs")
        if (
            bind_projection_sources(snapshot(root, db, inputs), projection.source_files)
            != provenance
        ):
            raise ValueError("source drift before synthesis claim")
        reproduction = {
            "rows": len(controls),
            "folds": len(references),
            "fixtures": len(projected),
            "maximum_pmf_difference": 0.0,
            "direct_price_proxy_rows": direct_proxies,
            "all_composed_fields_exact": True,
            "reference": "retrospective_proxy_implementation_of_current_joint_composer",
        }
        publish_json(output / "comparator_reproduction.json", reproduction)
        reproduction_sha256 = file_sha256(output / "comparator_reproduction.json")
        claim = reserve_program_claim(root, NAME, provenance)
        retained_rows = []
        for f in references:
            rows = []
            for fixture in sorted({r.target.fixture for r in f.rows}):
                predictions = {
                    r.code: r
                    for r in compose_synthesis_fixture(
                        f, fixture, context, saves_replacements=projected[f.season, fixture]
                    )
                }
                expected = {r.target.code for r in f.rows if r.target.fixture == fixture}
                if set(predictions) != expected:
                    raise ValueError("synthesis complete reciprocal roster identity differs")
                for r in f.rows:
                    t = r.target
                    if t.fixture != fixture:
                        continue
                    key = t.season, t.fixture, t.code
                    role, work = role_by_key[key], workload[key]
                    if (
                        role.target.as_of != f.as_of
                        or datetime.fromisoformat(work["as_of"]) != f.as_of
                    ):
                        raise ValueError("diagnostic source cutoff differs from same-GW reference")
                    minutes = work["feature_evidence"]["witnessed_nominal_minutes_lower_bound"]
                    row = {
                        "season": t.season,
                        "gw": t.gw,
                        "fixture": fixture,
                        "code": t.code,
                        "team_code": r.team_code,
                        "position": t.position.value,
                        "was_home": t.was_home,
                        "cutoff": f.as_of.isoformat(),
                        "kickoff": t.kickoff_time.isoformat(),
                        "cold_start": r.cold_start,
                        "direct_price_proxy": r.direct_price_proxy,
                        "team_price_proxy": bool(r.team_price_proxy_codes),
                        "fixture_price_proxy": bool(r.fixture_price_proxy_codes),
                        "promoted_team": r.team_code in promoted,
                        "rotation_risk": sum(r.player.components.minutes[2:]) < 0.75,
                        "role_confidence": "unavailable"
                        if not role.recent_measured_starts
                        else "high"
                        if max(role.probabilities) >= 0.75
                        else "low",
                        "workload_scope": "unavailable"
                        if minutes is None or minutes <= 0
                        else "witnessed_over90m_7d"
                        if minutes > 90
                        else "witnessed_up_to90m_7d",
                        "incumbent_pmf": controls[key].distribution,
                        "candidate_pmf": predictions[t.code].distribution,
                        "incumbent_composed": asdict(controls[key]),
                        "candidate_composed": asdict(predictions[t.code]),
                        "conditional_saves_pmf": projected[f.season, fixture].get(t.code),
                        "same_gw_rows_used": 0,
                        **labels[key],
                    }
                    rows.append(row)
            name = f"{f.season}-gw{f.gw:02d}.json"
            publish_json(output / name, {"rows": rows, "cutoff": f.as_of.isoformat()})
            folds.append(
                {
                    "season": f.season,
                    "gw": f.gw,
                    "rows": len(rows),
                    "file": name,
                    "sha256": file_sha256(output / name),
                }
            )
            retained_rows.extend(rows)
            logger.info("synthesis candidate GW%s: %s rows (%s/38)", f.gw, len(rows), len(folds))
        scores = summarize_points(retained_rows, seed=config["seed"])
        if (
            bind_projection_sources(snapshot(root, db, inputs), projection.source_files)
            != provenance
        ):
            raise ValueError("postflight source/HEAD/input drift")
        if any(file_sha256(output / f["file"]) != f["sha256"] for f in [*folds, *control_folds]):
            raise ValueError("synthesis fold output changed before publication")
        if file_sha256(output / "comparator_reproduction.json") != reproduction_sha256:
            raise ValueError("comparator reproduction receipt changed before publication")
        result = {
            "candidate": NAME,
            "completed": True,
            "evidence_class": EVIDENCE_CLASS,
            "started_at_utc": started,
            "finished_at_utc": datetime.now(UTC).isoformat(),
            "provenance": provenance,
            "claim": str(claim),
            "folds": folds,
            "control_folds": control_folds,
            "comparator_reproduction": reproduction,
            "comparator_reproduction_sha256": reproduction_sha256,
            "component_fits": 0,
            "saves_projection_provenance": projection.provenance,
            "saves_projection_reproduction": projection.reproduction,
            **scores,
            **decision(scores, config),
        }
        publish_json(output / "result.json", result)
        return result
    except BaseException as error:
        publish_json(
            output / "failure.json",
            {
                "candidate": NAME,
                "completed": False,
                "error_class": type(error).__name__,
                "error": str(error),
                "traceback": traceback.format_exc(),
                "claim": str(claim) if claim else None,
                "completed_folds": folds,
                "retry_permitted": False,
            },
        )
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument(
        "--inputs",
        required=True,
        type=Path,
        help="JSON mapping of preregistered source names to exact retained paths",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = run(
        root=repo_root(),
        db=args.db,
        output=args.output,
        inputs={k: Path(v) for k, v in read_json(args.inputs).items()},
    )
    print(json.dumps({"candidate": NAME, "verdict": result["verdict"]}))


if __name__ == "__main__":
    main()
