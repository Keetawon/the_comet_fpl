"""One claimed, offline development evaluation; replay and diagnostics are separate modes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import io
import json
import platform
import subprocess
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from fpl.config import repo_root
from fpl.features.attacking_role_premium_v1 import UsagePrediction, UsageTarget, predict_batch
from fpl.jobs.backfill_historical_player_attacking import retained_source
from fpl.jobs.competitive_participation_pilot import (
    file_sha256,
    git_clean_head,
    publish_bytes,
    publish_json,
)
from fpl.validate.attacking_role_premium_v1 import StudyPopulation, load_population, target_key
from fpl.validate.attacking_role_premium_v1_metrics import (
    ScoredUsage,
    blocked_bootstrap,
    comparison,
    diagnostics,
    verdict,
)
from fpl.validate.development_program_provenance import reserve_program_claim

CONFIG = "config/attacking_role_premium_v1.yaml"
CONFIG_SHA256 = "08589200d0285309fcfd0ef3620509d06f24c5b422e3dd629428d39657f040b7"
STUDY_ID = "attacking_role_premium_v1"


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"unsupported canonical value {type(value).__name__}")


def canonical(value: object) -> bytes:
    return (
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=_json_default
        )
        + "\n"
    ).encode()


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def _path(root: Path, value: str) -> Path:
    return root / value


def load_contract(root: Path, config: Path) -> dict[str, Any]:
    if file_sha256(config) != CONFIG_SHA256:
        raise ValueError("study config differs from the frozen preregistration")
    value = yaml.safe_load(config.read_bytes())
    if not isinstance(value, dict) or value.get("study_id") != STUDY_ID:
        raise ValueError("invalid study contract")
    if not value.get("development_only") or value.get("evidence_class") != "ARCHIVED_AS_OF":
        raise ValueError("study must retain its development archived-as-of classification")
    if config.resolve() != (root / CONFIG).resolve():
        raise ValueError("study config must be its tracked preregistered path")
    return dict(value)


def _raw_identity(root: Path, contract: Mapping[str, Any]) -> dict[str, str]:
    manifest = json.loads(_path(root, contract["inputs"]["manifest"]).read_bytes())
    hashes: dict[str, str] = {}
    for url, source in sorted(manifest["source_versions"].items()):
        if retained_source(url, source) != source:
            raise ValueError("raw source provenance changed")
        hashes[url] = source["sha256"]
    return hashes


def provenance(root: Path, config: Path, contract: Mapping[str, Any]) -> dict[str, Any]:
    """Pin actual tracked implementation, runtime, immutable artifacts and raw receipts."""
    head = git_clean_head(root)
    branch = _git(root, "branch", "--show-current")
    if branch != contract["expected_branch"]:
        raise ValueError("formal study requires its authorized V2 branch")
    if file_sha256(config) != CONFIG_SHA256:
        raise ValueError("frozen config changed")
    frozen = {path: file_sha256(root / path) for path in contract["frozen_inputs"]}
    if frozen != contract["frozen_inputs"]:
        raise ValueError("frozen input changed")
    observations = _path(root, contract["inputs"]["observations"])
    if file_sha256(observations) != contract["inputs"]["observations_sha256"]:
        raise ValueError("frozen observations changed")
    implementation: dict[str, str] = {}
    implementation_git_blobs: dict[str, str] = {}
    for path in contract["implementation_files"]:
        payload = (root / path).read_bytes()
        tracked = _git(root, "rev-parse", f"{head}:{path}")
        normalized = _git(root, "hash-object", f"--path={path}", path)
        if normalized != tracked:
            raise ValueError("implementation differs from the clean preregistered Git blob")
        implementation[path] = hashlib.sha256(payload).hexdigest()
        implementation_git_blobs[path] = tracked
    if "src/fpl/jobs/evaluate_attacking_role_premium_v1.py" not in implementation:
        raise ValueError("runner implementation pin is required")
    runtime = {
        "python": platform.python_version(),
        "packages": {
            name: importlib.metadata.version(name) for name in contract["runtime"]["packages"]
        },
    }
    if runtime != contract["runtime"]:
        raise ValueError("runtime differs from preregistered versions")
    return {
        "study_id": STUDY_ID,
        "preregistration_git_head": head,
        "branch": branch,
        "config_sha256": CONFIG_SHA256,
        "frozen_inputs_sha256": frozen,
        "observations_sha256": file_sha256(observations),
        "implementation_sha256": implementation,
        "implementation_git_blobs": implementation_git_blobs,
        "runtime": runtime,
        "raw_source_sha256": _raw_identity(root, contract),
    }


def _population(root: Path, contract: Mapping[str, Any]) -> StudyPopulation:
    inputs = contract["inputs"]
    result = load_population(
        _path(root, inputs["manifest"]),
        _path(root, inputs["availability_audit"]),
        _path(root, inputs["backfill_scope"]),
        _path(root, inputs["observations"]),
    )
    receipt, expected = result.receipt, contract["population"]
    positions = Counter(t.fpl_position for fold in result.folds for t in fold.targets)
    if (
        receipt["target_gameweeks"] != expected["target_gws"]
        or receipt["target_rows"] != expected["target_rows"]
        or receipt["unique_players"] != expected["players"]
        or dict(positions) != expected["positions"]
    ):
        raise ValueError("population differs from preregistered availability audit")
    if receipt["population_sha256"] != expected["target_identity_sha256"]:
        raise ValueError("population identity differs from preregistration")
    if receipt["paired_minutes_ge_45"] != expected["primary_minute_slice_rows"]:
        raise ValueError("primary conditional population differs from preregistration")
    return result


def _decode_prediction(value: dict[str, Any]) -> UsagePrediction:
    value = dict(value)
    target = dict(value.pop("target"))
    target["kickoff_time"] = datetime.fromisoformat(target["kickoff_time"])
    value["as_of"] = datetime.fromisoformat(value["as_of"])
    value["source_versions"] = tuple(tuple(source) for source in value["source_versions"])
    return UsagePrediction(target=UsageTarget(**target), **value)


def _evaluate(
    population: StudyPopulation,
    contract: Mapping[str, Any],
    output: Path,
    pinned: Mapping[str, Any],
    claim_bytes: bytes,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Publish a whole target batch before looking up any label in that batch."""
    all_prediction_bytes: list[bytes] = []
    label_bytes: list[bytes] = []
    scored: list[ScoredUsage] = []
    fold_receipts: list[dict[str, Any]] = []
    hashes: dict[str, str] = {}
    for fold in population.folds:
        predictions = predict_batch(population.history, fold.targets, as_of=fold.as_of)
        if (
            [p.target for p in predictions] != list(fold.targets)
            or any(p.as_of != fold.as_of for p in predictions)
            or len({target_key(p.target) for p in predictions}) != len(predictions)
        ):
            raise ValueError("prediction population/cutoff identity changed")
        payload = b"".join(canonical(asdict(p)) for p in predictions)
        filename = f"predictions-gw{fold.gameweek:02d}.jsonl"
        publish_bytes(output / filename, payload)
        digest = file_sha256(output / filename)
        hashes[filename] = digest
        events.append(
            {
                "event": "prediction_frozen",
                "gw": fold.gameweek,
                "at": datetime.now(UTC).isoformat(),
                "path": str(output / filename),
                "sha256": digest,
            }
        )
        fold_receipts.append(
            {
                "gw": fold.gameweek,
                "as_of": fold.as_of.isoformat(),
                "rows": len(predictions),
                "source_snapshot_id": fold.source_snapshot_id,
                "predictions_file": filename,
                "predictions_sha256": digest,
                "predictions_published_before_outcome_access": True,
            }
        )
        all_prediction_bytes.append(payload)
        for prediction in predictions:
            key = target_key(prediction.target)
            outcome = population.outcomes[key]
            if target_key(outcome) != key or outcome.gameweek != fold.gameweek:
                raise ValueError("outcome identity differs from frozen target")
            label_bytes.append(
                canonical(
                    {
                        "prediction_key": key,
                        "minutes": outcome.minutes,
                        "xg": outcome.xg,
                        "xa": outcome.xa,
                    }
                )
            )
            if outcome.minutes is not None and outcome.xg is not None and outcome.xa is not None:
                scored.append(ScoredUsage(prediction, outcome.minutes, outcome.xg, outcome.xa))
        events.append(
            {
                "event": "outcomes_attached",
                "gw": fold.gameweek,
                "at": datetime.now(UTC).isoformat(),
                "rows": len(predictions),
            }
        )
    publish_bytes(output / "predictions.jsonl", b"".join(all_prediction_bytes))
    publish_bytes(output / "scored.jsonl", b"".join(label_bytes))
    publish_json(output / "population.json", dict(population.receipt))
    for name in (
        "predictions.jsonl",
        "scored.jsonl",
        "population.json",
        "provenance.json",
        "claim.json",
    ):
        hashes[name] = file_sha256(output / name)
    minimum = int(contract["evaluation"]["primary_minimum_target_minutes"])
    primary_rows = [row for row in scored if row.minutes >= minimum]
    primary = comparison(primary_rows)
    positions = {
        position: comparison(
            [r for r in primary_rows if r.prediction.target.fpl_position == position]
        )
        for position in ("DEF", "MID", "FWD")
    }
    uncertainty = blocked_bootstrap(
        primary_rows,
        draws=int(contract["evaluation"]["bootstrap_draws"]),
        seed=int(contract["evaluation"]["bootstrap_seed"]),
    )
    return {
        "study_id": STUDY_ID,
        "development_only": True,
        "evidence_class": "ARCHIVED_AS_OF",
        "official_deadline_replay": False,
        "interpretation": contract["evaluation"]["interpretation"],
        "provenance": dict(pinned),
        "claim_sha256": hashlib.sha256(claim_bytes).hexdigest(),
        "population": dict(population.receipt),
        "folds": fold_receipts,
        "artifact_sha256": hashes,
        "primary_minimum_target_minutes": minimum,
        "complete_outcome_rows": len(scored),
        "unavailable_outcome_rows": len(label_bytes) - len(scored),
        "primary": primary,
        "positions": positions,
        "uncertainty": uncertainty,
        "decision": verdict(
            primary, positions, uncertainty, dict(contract["gates"]), pit_valid=True
        ),
    }


def _original(directory: Path) -> dict[str, Any]:
    if (directory / "failure.json").exists():
        raise ValueError("invalid run cannot become a replay or diagnostic source")
    result: dict[str, Any] = json.loads((directory / "formal-result.json").read_bytes())
    for name, digest in result["artifact_sha256"].items():
        if Path(name).name != name or file_sha256(directory / name) != digest:
            raise ValueError("frozen result artifact hash differs")
    if result["provenance"] != json.loads((directory / "provenance.json").read_bytes()):
        raise ValueError("original provenance changed")
    claim = json.loads((directory / "claim.json").read_bytes())
    if (
        claim["candidate"] != STUDY_ID
        or claim["provenance"] != result["provenance"]
        or file_sha256(directory / "claim.json") != result["claim_sha256"]
    ):
        raise ValueError("original scientific claim identity changed")
    return result


def _same_inputs(current: Mapping[str, Any], original: Mapping[str, Any]) -> None:
    keys = set(current) | set(original)
    if any(current.get(k) != original.get(k) for k in keys if k != "preregistration_git_head"):
        raise ValueError("replay input/runtime/implementation identity differs from original")


def run(
    root: Path,
    config: Path,
    output: Path,
    *,
    population_only: bool = False,
    replay: Path | None = None,
) -> dict[str, Any]:
    if population_only and replay is not None:
        raise ValueError("population-only and replay modes are exclusive")
    started = datetime.now(UTC).isoformat()
    contract = load_contract(root, config)
    pinned = provenance(root, config, contract)
    population = _population(root, contract)
    original = _original(replay) if replay is not None else None
    if original is not None:
        _same_inputs(pinned, original["provenance"])
        _git(
            root,
            "merge-base",
            "--is-ancestor",
            original["provenance"]["preregistration_git_head"],
            pinned["preregistration_git_head"],
        )
    output.mkdir(parents=True, exist_ok=False)
    claim: Path | None = None
    events: list[dict[str, Any]] = []
    try:
        if population_only:
            publish_json(output / "population.json", dict(population.receipt))
            if provenance(root, config, contract) != pinned:
                raise ValueError("inputs changed during population verification")
            return dict(population.receipt)
        if original is None:
            claim = reserve_program_claim(root, STUDY_ID, pinned)
            claim_bytes = claim.read_bytes()
            scientific_provenance = pinned
            publish_json(output / "provenance.json", pinned)
        else:
            assert replay is not None
            claim_bytes = (replay / "claim.json").read_bytes()
            scientific_provenance = original["provenance"]
            publish_bytes(output / "provenance.json", (replay / "provenance.json").read_bytes())
        publish_bytes(output / "claim.json", claim_bytes)
        result = _evaluate(population, contract, output, scientific_provenance, claim_bytes, events)
        if provenance(root, config, contract) != pinned:
            raise ValueError("inputs changed during formal evaluation")
        if original is not None:
            assert replay is not None
            for filename in result["artifact_sha256"]:
                if (output / filename).read_bytes() != (replay / filename).read_bytes():
                    raise ValueError("replay artifact is not byte-identical")
            if result != original:
                raise ValueError("replay scientific result is not identical")
        publish_json(output / "formal-result.json", result)
        if original is not None:
            assert replay is not None
            if (output / "formal-result.json").read_bytes() != (
                replay / "formal-result.json"
            ).read_bytes():
                raise ValueError("replay formal result bytes differ")
        return result
    except Exception as exc:
        publish_json(
            output / "failure.json",
            {
                "status": "INVALID",
                "exception": type(exc).__name__,
                "reason": str(exc),
                "claim": str(claim) if claim else None,
                "resume_permitted": False,
            },
        )
        raise
    finally:
        publish_json(
            output / "execution-receipt.json",
            {
                "started_at": started,
                "completed_at": datetime.now(UTC).isoformat(),
                "mode": "population_only" if population_only else "replay" if replay else "formal",
                "events": events,
                "formal_result_sha256": file_sha256(output / "formal-result.json")
                if (output / "formal-result.json").exists()
                else None,
            },
        )


def _named_cases(
    root: Path, contract: Mapping[str, Any], predictions: Sequence[UsagePrediction]
) -> dict[str, Any]:
    """Post-result exact source-name lookup; stable source codes alone join predictions."""
    names = ("O'Reilly", "Hume", "De Cuyper")
    found: dict[str, set[int]] = {name: set() for name in names}
    manifest = json.loads(_path(root, contract["inputs"]["manifest"]).read_bytes())
    for url, source in manifest["source_versions"].items():
        if not url.endswith("/players_raw.csv"):
            continue
        retained_source(url, source)
        reader = csv.DictReader(
            io.StringIO(Path(source["raw_file"]).read_text(encoding="utf-8-sig"))
        )
        for row in reader:
            name = row["second_name"].replace("\u2019", "'")
            if name in found:
                found[name].add(int(row["code"]))
    result: dict[str, Any] = {}
    for name, codes in found.items():
        selected = [asdict(p) for p in predictions if p.target.player_code in codes]
        result[name] = {
            "status": "OBSERVED" if selected else "NOT IN AUDITED POPULATION",
            "source_codes": sorted(codes),
            "predictions": selected,
            "identity_policy": "exact source second_name lookup; stable code prediction join",
        }
    return result


def run_diagnostics(root: Path, config: Path, original: Path, output: Path) -> dict[str, Any]:
    contract = load_contract(root, config)
    pinned = provenance(root, config, contract)
    result = _original(original)
    _same_inputs(pinned, result["provenance"])
    predictions = [
        _decode_prediction(json.loads(line))
        for line in (original / "predictions.jsonl").read_bytes().splitlines()
    ]
    by_key = {target_key(p.target): p for p in predictions}
    if len(by_key) != len(predictions):
        raise ValueError("duplicate frozen prediction identity")
    scored: list[ScoredUsage] = []
    labels = [json.loads(line) for line in (original / "scored.jsonl").read_bytes().splitlines()]
    if len(labels) != len(by_key) or {tuple(r["prediction_key"]) for r in labels} != set(by_key):
        raise ValueError("frozen outcome/prediction populations differ")
    for row in labels:
        if all(row[k] is not None for k in ("minutes", "xg", "xa")):
            key = (
                str(row["prediction_key"][0]),
                int(row["prediction_key"][1]),
                int(row["prediction_key"][2]),
            )
            scored.append(ScoredUsage(by_key[key], row["minutes"], row["xg"], row["xa"]))
    defenders = [p for p in predictions if p.target.fpl_position == "DEF"]

    def tie(p: UsagePrediction) -> tuple[int, int, int]:
        return p.target.gameweek, p.target.player_code, p.target.fixture_id

    selected = {
        "top_five": sorted(defenders, key=lambda p: (-p.attacking_role_premium_v1, *tie(p)))[:5],
        "middle_five": sorted(
            defenders, key=lambda p: (abs(p.attacking_role_premium_v1 - 0.5), *tie(p))
        )[:5],
        "lowest_five": sorted(defenders, key=lambda p: (p.attacking_role_premium_v1, *tie(p)))[:5],
    }
    diagnostic = {
        "study_id": STUDY_ID,
        "kind": "post_result_diagnostics_no_new_predictions",
        "formal_result_sha256": file_sha256(original / "formal-result.json"),
        "diagnostics": diagnostics(
            scored, primary_minutes=result["primary_minimum_target_minutes"]
        ),
        "source_determined_def_cases": {
            name: [asdict(p) for p in rows] for name, rows in selected.items()
        },
        "all_high_premium_def": {
            str(threshold): [
                asdict(p)
                for p in sorted(defenders, key=tie)
                if p.attacking_role_premium_v1 >= threshold
            ]
            for threshold in (0.9, 0.975)
        },
        "named_cases": _named_cases(root, contract, predictions),
    }
    if provenance(root, config, contract) != pinned:
        raise ValueError("diagnostic inputs changed")
    output.mkdir(parents=True, exist_ok=False)
    publish_bytes(output / "diagnostics.json", canonical(diagnostic))
    return diagnostic


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=repo_root() / CONFIG)
    parser.add_argument("--output-dir", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--population-only", action="store_true")
    mode.add_argument("--replay", type=Path)
    mode.add_argument("--diagnostics", type=Path)
    args = parser.parse_args()
    if args.diagnostics is not None:
        result = run_diagnostics(repo_root(), args.config, args.diagnostics, args.output_dir)
        print(json.dumps({"kind": result["kind"], "output": str(args.output_dir)}))
    else:
        result = run(
            repo_root(),
            args.config,
            args.output_dir,
            population_only=args.population_only,
            replay=args.replay,
        )
        print(json.dumps({"decision": result.get("decision"), "output": str(args.output_dir)}))


if __name__ == "__main__":
    main()
