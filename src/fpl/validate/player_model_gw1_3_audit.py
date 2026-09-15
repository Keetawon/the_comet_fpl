"""One-shot orchestration for a frozen retrospective diagnostic, never production.

Both lanes' complete forecast populations are durably frozen before this module
permits the official-outcome reader to run. No resume, replacement or model repair.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import subprocess
import traceback
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import yaml

from fpl.jobs.competitive_participation_pilot import file_sha256, publish_bytes
from fpl.validate.development_program_provenance import reserve_program_claim

CONFIG = "config/player_model_gw1_3_audit.yaml"
CONFIG_SHA256 = "2d3adaaf7e372ac2c44b4c38c18879ee15397af747468aa02ec6b80cd7943cba"
AUDIT_ID = "player_model_gw1_3_20260908_v1"
BRANCH = "claude/comet-fpl-v2-architecture-mqrj8f"
LANES = ("strict", "retrospective_sdp")
IMPLEMENTATION = (
    CONFIG,
    "src/fpl/validate/player_model_gw1_3_audit.py",
    "src/fpl/validate/player_model_gw1_3_metrics.py",
    "src/fpl/validate/player_model_gw1_3_replay.py",
    "src/fpl/validate/player_model_gw1_3_sources.py",
    "src/fpl/validate/sdp_counterfactual.py",
    "src/fpl/jobs/evaluate_player_model_gw1_3.py",
    "docs/player-model-gw1-3-preregistration-2026-09-08.md",
)


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"unsupported canonical type {type(value).__name__}")


def canonical(value: object) -> bytes:
    return (
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=_json_default
        )
        + "\n"
    ).encode()


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def runtime() -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("duckdb", "polars", "pydantic", "PyYAML", "pulp")
        },
    }


def load_contract(repo: Path) -> dict[str, Any]:
    path = repo / CONFIG
    if file_sha256(path) != CONFIG_SHA256:
        raise ValueError("audit config differs from its preregistered bytes")
    value = yaml.safe_load(path.read_bytes())
    if not isinstance(value, dict) or value.get("audit_id") != AUDIT_ID:
        raise ValueError("wrong audit identity")
    if value.get("status") != "RETROSPECTIVE_FROZEN_DIAGNOSTIC":
        raise ValueError("diagnostic evidence classification required")
    return dict(value)


def verify_freeze(repo: Path, contract: Mapping[str, Any]) -> dict[str, Any]:
    """Verify the actual clean execution commit and the separate Phase A model freeze."""
    if _git(repo, "status", "--porcelain") or _git(repo, "branch", "--show-current") != BRANCH:
        raise ValueError("audit requires clean authorized V2 branch")
    head = _git(repo, "rev-parse", "HEAD")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", contract["model_freeze_sha"], head],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    hashes = {name: file_sha256(repo / name) for name in contract["frozen_files_sha256"]}
    if hashes != contract["frozen_files_sha256"]:
        raise ValueError("frozen science/model/config or Phase A source changed")
    if file_sha256(repo / CONFIG) != CONFIG_SHA256:
        raise ValueError("preregistered audit configuration changed")
    db = Path(contract["default_source_database"])
    if file_sha256(db) != contract["source_database_sha256"]:
        raise ValueError("frozen database bytes changed")
    if runtime() != contract["runtime"]:
        raise ValueError("runtime differs from preregistration")
    implementation = {}
    for name in IMPLEMENTATION:
        if _git(repo, "hash-object", f"--path={name}", name) != _git(
            repo, "rev-parse", f"{head}:{name}"
        ):
            raise ValueError("audit implementation is not its clean committed blob")
        implementation[name] = file_sha256(repo / name)
    return {
        "model_freeze_sha": contract["model_freeze_sha"],
        "preregistration_sha": head,
        "branch": BRANCH,
        "frozen_files_sha256": hashes,
        "implementation_sha256": implementation,
        "database_sha256": contract["source_database_sha256"],
        "runtime": runtime(),
    }


def _write_json(path: Path, value: object) -> str:
    payload = canonical(value)
    publish_bytes(path, payload)
    if canonical(json.loads(path.read_bytes())) != payload:
        raise ValueError("canonical artifact replay changed bytes")
    return hashlib.sha256(payload).hexdigest()


def verify_prediction_freeze(output: Path, manifest: Mapping[str, Any]) -> None:
    """An outcome reader must never run on a partial/mutable forecast population."""
    if manifest.get("status") != "ALL_PREDICTIONS_FROZEN":
        raise ValueError("all predictions must precede official outcome access")
    expected = {
        (lane, gw, model)
        for lane in LANES
        for gw in (1, 2, 3)
        for model in ("current", "incumbent")
    }
    if {(r["lane"], r["gw"], r["model"]) for r in manifest["artifacts"]} != expected:
        raise ValueError("both models/lanes and every whole GW must be frozen")
    if len(manifest["artifacts"]) != len(expected):
        raise ValueError("duplicate forecast receipt")
    for row in manifest["artifacts"]:
        for field in ("forecast", "diagnostics"):
            filename = row[f"{field}_file"]
            if Path(filename).name != filename:
                raise ValueError("forecast receipt must identify a local immutable file")
            if file_sha256(output / filename) != row[f"{field}_sha256"]:
                raise ValueError("frozen prediction bytes changed")


def _verify_cutoff(info: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    if info["registry_count"] != expected["expected_players"]:
        raise ValueError("historical registry population differs from preregistration")
    if len(info["target_fixture_ids"]) != expected["expected_fixtures"]:
        raise ValueError("historical fixture population differs from preregistration")
    # Source helper supplies and validates the actual selected capture identities.
    if (
        info["registry_capture_ids"] != [expected["registry_capture_id"]]
        or info["bootstrap_capture_id"] != expected["registry_capture_id"]
    ):
        raise ValueError("historical registry source differs from preregistration")
    histories = [] if expected["history_capture_id"] is None else [expected["history_capture_id"]]
    if info["history_capture_ids"] != histories:
        raise ValueError("historical history source differs from preregistration")


def run_audit(repo: Path) -> dict[str, Any]:
    """Exactly one claimed formal run. Any failure preserves its identity and files."""
    # Lazy imports keep source/outcome operations visibly inside the guarded runner.
    from fpl.validate.player_model_gw1_3_metrics import paired_comparison, score_predictions
    from fpl.validate.player_model_gw1_3_replay import replay_gameweek
    from fpl.validate.player_model_gw1_3_sources import inspect_cutoff, load_official_outcomes
    from fpl.validate.sdp_counterfactual import load_counterfactual_inputs

    contract = load_contract(repo)
    frozen = verify_freeze(repo, contract)
    output = Path(contract["default_output_dir"])
    if output.exists():
        raise FileExistsError("formal run directory already exists; no resume or overwrite")
    claim = reserve_program_claim(repo, AUDIT_ID, frozen)
    output.mkdir(parents=True, exist_ok=False)
    started = datetime.now(UTC).isoformat()
    _write_json(output / "run-start.json", {"started_at": started, "claim": str(claim), **frozen})
    stage = "input_preflight"
    try:
        predictions: dict[str, dict[str, list[dict[str, Any]]]] = {
            lane: {model: [] for model in ("current", "incumbent")} for lane in LANES
        }
        receipts: list[dict[str, Any]] = []
        folds: list[dict[str, Any]] = []
        db = Path(contract["default_source_database"])
        with duckdb.connect(str(db), read_only=True) as con:
            infos = {}
            for fold in contract["cutoffs"]:
                info = inspect_cutoff(
                    con,
                    season=contract["season"],
                    gw=fold["gw"],
                    cutoff=datetime.fromisoformat(fold["as_of"]),
                )
                _verify_cutoff(info, fold)
                infos[fold["gw"]] = info
            _write_json(output / "historical-inputs.json", infos)
            counterfactual = load_counterfactual_inputs(
                con,
                repo=repo,
                db_path=db,
                season=contract["season"],
                evidence_as_of=datetime.fromisoformat(contract["evidence_as_of"]),
            )
            for lane in LANES:
                for fold in contract["cutoffs"]:
                    gw = fold["gw"]
                    stage = f"forecast_{lane}_gw{gw}"
                    print(f"{stage}: freezing current plus exact recursive incumbent", flush=True)
                    result = replay_gameweek(
                        con,
                        repo=repo,
                        db_path=db,
                        season=contract["season"],
                        gw=gw,
                        cutoff=datetime.fromisoformat(fold["as_of"]),
                        fixture_gameweeks=infos[gw]["fixture_gameweeks"],
                        counterfactual_inputs=counterfactual if lane != "strict" else None,
                    )
                    folds.append(
                        {"lane": lane, "gw": gw, "pair_invariants": result["pair_invariants"]}
                    )
                    for model in ("current", "incumbent"):
                        item = result[model]
                        promoted = infos[gw].get("promoted_team_codes")
                        for prediction in item["predictions"]:
                            prediction["promoted_team"] = (
                                prediction["team_code"] in promoted
                                if promoted is not None
                                else None
                            )
                        name = f"{lane}-gw{gw}-{model}"
                        forecast = name + ".jsonl"
                        publish_bytes(output / forecast, item["artifact_bytes"])
                        diagnostics = name + "-diagnostics.json"
                        diag_hash = _write_json(
                            output / diagnostics,
                            {
                                "predictions": item["predictions"],
                                "provenance": item["provenance"],
                            },
                        )
                        receipts.append(
                            {
                                "lane": lane,
                                "gw": gw,
                                "model": model,
                                "forecast_file": forecast,
                                "forecast_sha256": file_sha256(output / forecast),
                                "diagnostics_file": diagnostics,
                                "diagnostics_sha256": diag_hash,
                                "player_fixture_predictions": len(item["predictions"]),
                            }
                        )
                        predictions[lane][model].extend(item["predictions"])
            manifest = {
                "status": "ALL_PREDICTIONS_FROZEN",
                "frozen_at": datetime.now(UTC).isoformat(),
                "outcomes_accessed": False,
                "artifacts": receipts,
                "folds": folds,
                "provenance": frozen,
            }
            prediction_hash = _write_json(output / "prediction-freeze.json", manifest)
            verify_prediction_freeze(output, manifest)
            if verify_freeze(repo, contract) != frozen:
                raise ValueError("frozen source/code changed during inference")
            stage = "official_outcomes_after_all_predictions_frozen"
            print(stage, flush=True)
            outcomes = load_official_outcomes(
                con,
                season=contract["season"],
                capture_id=contract["outcome_capture_id"],
                gameweeks=(1, 2, 3),
            )
            outcome_hash = _write_json(output / "official-outcomes.json", outcomes)
        stage = "scoring_frozen_common_populations"
        summaries = {}
        for lane in LANES:
            lane_predictions = predictions[lane]
            result = {
                "schema_version": 1,
                "audit_id": AUDIT_ID,
                "lane": lane,
                "status": "COMPLETE",
                "evidence_class": "RETROSPECTIVE_FROZEN_DIAGNOSTIC",
                "input_evidence": "STRICT_ACTUAL_AVAILABILITY"
                if lane == "strict"
                else "RETROSPECTIVE_DEVELOPMENT_COUNTERFACTUAL",
                "not_prospective_validation": True,
                "provenance": frozen,
                "prediction_freeze_sha256": prediction_hash,
                "outcomes_sha256": outcome_hash,
                "current": score_predictions(lane_predictions["current"], outcomes),
                "incumbent": score_predictions(lane_predictions["incumbent"], outcomes),
                "paired": paired_comparison(
                    lane_predictions["current"], lane_predictions["incumbent"], outcomes
                ),
                "folds": [f for f in folds if f["lane"] == lane],
            }
            summaries[lane] = {
                "file": f"{lane}-result.json",
                "sha256": _write_json(output / f"{lane}-result.json", result),
            }
        verify_prediction_freeze(output, manifest)
        if verify_freeze(repo, contract) != frozen:
            raise ValueError("frozen source/model/config changed after scoring")
        completion = {
            "status": "COMPLETE",
            "audit_id": AUDIT_ID,
            "started_at": started,
            "completed_at": datetime.now(UTC).isoformat(),
            "results": summaries,
            "prediction_freeze_sha256": prediction_hash,
            "outcomes_sha256": outcome_hash,
            "frozen_model_and_source_hashes_unchanged": True,
            "formal_forecast_evaluations": 1,
            "verdict": "OWNER_REPORT_AFTER_FROZEN_DIAGNOSTICS",
        }
        _write_json(output / "completion.json", completion)
        print(json.dumps(completion, sort_keys=True), flush=True)
        return completion
    except Exception as error:
        _write_json(
            output / "invalid-run.json",
            {
                "audit_id": AUDIT_ID,
                "status": "INVALIDATED_BY_IMPLEMENTATION_OR_INPUT_FAILURE",
                "stage": stage,
                "error_type": type(error).__name__,
                "error": str(error),
                "traceback": traceback.format_exc(),
                "recorded_at": datetime.now(UTC).isoformat(),
                "preregistration": frozen,
                "resume_permitted": False,
            },
        )
        raise
