"""One write-once six-arm historical development experiment, never production inference."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from fpl.features.pit import AsOf
from fpl.storage.db import connect
from fpl.validate import chance_creation as chance
from fpl.validate import dev_v2_chance_creation as legacy
from fpl.validate import dev_v2_real_sot as scoring
from fpl.validate import sot_zero_audit
from fpl.validate.audit_json import canonical
from fpl.validate.chance_coverage import load_chance_targets
from fpl.validate.metrics import log_score
from fpl.validate.tactical_state import load_observations
from fpl.validate.team_venue_form import ARMS, WEIGHTS, interpreted_observations, style_walk_forward
from fpl.validate.v2_environment_harness import promoted_team_codes

NAME = "team_venue_form_v1_20260921"
CONFIG = "config/team_venue_form_v1.yaml"
BRANCH = "codex/team-venue-form-v1"
logger = logging.getLogger(__name__)


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def publish(path: Path, value: object) -> str:
    """Exclusive create; deterministic compressed artifact, no rolling replacement."""
    body = canonical(value)
    if body != canonical(json.loads(body)):
        raise ValueError("canonical replay differs")
    if path.suffix == ".gz":
        body = gzip.compress(body, compresslevel=6, mtime=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        output.write(body)
    return digest(body)


def fingerprints(root: Path) -> dict[str, str]:
    paths = scoring._git(root, "ls-files").splitlines()
    return {
        p: scoring.file_sha256(root / p)
        for p in paths
        if p.startswith(("src/", "config/", "results/", "docs/"))
        or p
        in {
            "AGENTS.md",
            "DEV-ROADMAP.md",
            "README.md",
            "pyproject.toml",
            "uv.lock",
            ".gitattributes",
        }
    }


def compare(
    experiments: dict[str, Any], candidate: str, control: str, contract: dict[str, Any]
) -> dict[str, Any]:
    paired = deepcopy(experiments[candidate])
    reference = {r["key"]: r for r in experiments[control]["history_rows"]}
    if {r["key"] for r in paired["history_rows"]} != set(reference):
        raise ValueError("arm populations differ")
    c0_rows = {r["key"]: r for r in experiments["C0"]["history_rows"]}
    for r in paired["history_rows"]:
        ref = reference[r["key"]]
        if any(
            r[k] != ref[k] for k in ("observed_goals", "goals_allowed", "as_of", "kickoff_time")
        ):
            raise ValueError("paired target or cutoff differs")
        r["distributions"]["incumbent"] = ref["distributions"]["candidate"]
        r["clean_sheet_probabilities"]["incumbent"] = ref["clean_sheet_probabilities"]["candidate"]
        r["paired_log_loss_difference"] = log_score(
            tuple(r["distributions"]["candidate"]), r["observed_goals"]
        ) - log_score(tuple(r["distributions"]["incumbent"]), r["observed_goals"])
        r["paired_cs_brier_difference"] = (
            r["clean_sheet_probabilities"]["candidate"] - r["observed_clean_sheet"]
        ) ** 2 - (r["clean_sheet_probabilities"]["incumbent"] - r["observed_clean_sheet"]) ** 2
        # Common C0 cohort labels, not arm-dependent selection of favourable slices.
        c0 = c0_rows[r["key"]]
        for key in ("state_cold_start", "high_confidence", "promoted_team"):
            r[key] = c0[key]
    # JSON round trips do not preserve shared Python object identities.
    updated = {r["key"]: r for r in paired["history_rows"]}
    paired["rows"] = [updated[r["key"]] for r in paired["rows"]]
    scored = legacy.score_experiment(paired, contract)
    scored["candidate"], scored["control"] = candidate, control
    scored["overall"]["candidate"]["model"] = candidate
    scored["overall"]["incumbent"]["model"] = control
    for value in scored["paired_uncertainty"].values():
        value["negative_favours"] = candidate
    return scored


def run(root: Path, db: Path) -> dict[str, Any]:
    root, db = root.resolve(), db.resolve()
    scoring.require_clean_worktree(root)
    if scoring._git(root, "branch", "--show-current") != BRANCH:
        raise ValueError("research branch required")
    legacy._assert_database(db)
    contract = yaml.safe_load((root / CONFIG).read_bytes())
    if (
        contract["experiment"] != NAME
        or contract["arms"] != list(ARMS)
        or contract["recent_weights"] != list(WEIGHTS)
    ):
        raise ValueError("unregistered experiment definition")
    if scoring.file_sha256(db) != contract["database_sha256"]:
        raise ValueError("database differs from preregistered source")
    original = legacy.load_contract(root)
    settings = {**original, **contract}
    before = fingerprints(root)
    head = scoring._git(root, "rev-parse", "HEAD")
    destination = root / "data/artifacts" / NAME
    if destination.exists():
        raise FileExistsError("experiment identity already reserved")
    provenance = {
        "git_head": head,
        "branch": BRANCH,
        "source_sha256": before,
        "database_sha256": contract["database_sha256"],
        "database_path": str(db),
        "model_parameter_sha256": before["config/sdp_v2_frozen_parameters.json"],
        "created_at": datetime.now(UTC).isoformat(),
        "contract": contract,
        "evidence_class": "retrospective_backfill_development",
        "known_at_rewritten": False,
        "cached_upstream_predictions_used_as_features": False,
    }
    publish(destination / "claim.json", provenance)
    try:
        with connect(db, read_only=True) as con:
            audit = sot_zero_audit.build_audit(
                con, sot_zero_audit.load_policy(root / "config/pl_sdp_sot_zero_interpretation.yaml")
            )
            retained = json.loads((root / "results/pl_sdp_sot_zero_audit.json").read_bytes())
            if any(audit[k] != retained[k] for k in audit):
                raise ValueError("original SOT audit does not reproduce")
            targets = load_chance_targets(con)
            cutoff = legacy._timestamp(max(t["kickoff_time"] for t in targets)) + timedelta(
                microseconds=1
            )
            raw = list(load_observations(con, AsOf(cutoff)))
            view = sot_zero_audit.CorroboratedSotBackfillView(con, AsOf(cutoff), audit)
            interpreted = view.observed_corroborated_sot().to_dicts()
            corrected = interpreted_observations(raw, interpreted, targets)
            # Old cache provides comparison identities ONLY to independently refit
            # the unchanged incumbent. Every arm's style inputs are regenerated below.
            reference = legacy._load_upstream(root, original)
            cache, reproduction = legacy.reproduce_incumbent(con, settings, reference)
            promoted = promoted_team_codes(con)
        artifacts = {
            "inputs": publish(
                destination / "inputs.json.gz",
                {
                    "targets": targets,
                    "raw_states": [asdict(r) for r in raw],
                    "interpreted_sot": interpreted,
                    "audit": audit,
                },
            )
        }
        experiments: dict[str, Any] = {}
        validations = {}
        c0_reconciliation = None
        for arm in ARMS:
            logger.info("BEGIN %s: regenerating all historical state/style predictions", arm)
            upstream = style_walk_forward(
                raw if arm == "C0" else corrected, arm, progress=logger.info
            )
            observations = legacy.make_observations(targets, upstream, cache)

            def progress(batch: dict[str, Any], label: str = arm) -> None:
                f = batch["fold"]
                logger.info("%s chance %s GW%s", label, f["season"], f["gw"])

            experiment = chance.run_chance_walk_forward(
                observations, tuple(contract["eligible_seasons"]), checkpoint=progress
            )
            legacy.attach_evidence(experiment, upstream, promoted)
            validations[arm] = legacy.verify_run(experiment, observations, settings)
            if arm == "C0":
                frozen = json.loads(
                    (root / "results/v2_chance_creation_development.json").read_bytes()
                )
                old_rows = {r["key"]: r for r in frozen["historical_chance_predictions"]}
                maximum = max(
                    abs(x - y)
                    for r in experiment["history_rows"]
                    for x, y in zip(
                        r["distributions"]["candidate"],
                        old_rows[r["key"]]["distributions"]["candidate"],
                        strict=True,
                    )
                )
                if maximum > 1e-12:
                    raise ValueError(f"C0 fails production-procedure reconciliation: {maximum}")
                c0_reconciliation = {
                    "rows": len(old_rows),
                    "maximum_pmf_difference": maximum,
                    "tolerance": 1e-12,
                }
            artifacts[arm] = publish(
                destination / f"{arm}.json.gz",
                {"upstream": upstream, "chance": experiment, "validation": validations[arm]},
            )
            experiments[arm] = experiment
            logger.info("FROZEN %s artifact %s", arm, artifacts[arm])
        # All six prediction/fitted-parameter artifacts are durable before comparative scoring.
        comparisons = {
            f"{a}_vs_{b}": compare(experiments, a, b, settings)
            for a, b in (
                ("C1", "C0"),
                ("A", "C1"),
                ("B", "A"),
                ("C", "A"),
                ("C", "B"),
                ("D", "C"),
                ("C", "C0"),
                ("C", "C1"),
            )
        }
        primary = [comparisons["C_vs_C0"], comparisons["C_vs_C1"]]
        verdict = (
            "SUPPORTED" if all(p["verdict"] == "SUPPORTED" for p in primary) else "INCONCLUSIVE"
        )
        if any(p["verdict"] == "REFUTED" for p in primary):
            verdict = "REFUTED"
        if (
            fingerprints(root) != before
            or scoring.file_sha256(db) != contract["database_sha256"]
            or scoring._git(root, "rev-parse", "HEAD") != head
        ):
            raise ValueError("source, database or model freeze changed during run")
        scoring.require_clean_worktree(root)
        report = {
            "experiment": NAME,
            "completed": True,
            "verdict": verdict,
            "development_only": True,
            "promotion_permitted": False,
            "provenance": provenance,
            "artifacts_sha256": artifacts,
            "artifact_directory": str(destination),
            "validation": validations,
            "c0_reconciliation": c0_reconciliation,
            "incumbent_reproduction": reproduction,
            "sot_audit_reproduced": True,
            "raw_payloads_verified": audit["raw_payloads_verified"],
            "omission_rows": len(audit["missing_sot_decisions"]),
            "frozen_files_unchanged": True,
            "database_unchanged": True,
            "comparisons": comparisons,
            "arms": {
                arm: {
                    "scores": legacy.score_experiment(experiments[arm], settings),
                    "stages": chance.chance_target_metrics(experiments[arm]["rows"]),
                    "fallback_rows": sum(r["incumbent_fallback"] for r in experiments[arm]["rows"]),
                }
                for arm in ARMS
            },
            "completed_at": datetime.now(UTC).isoformat(),
        }
        publish(root / "results" / f"{NAME}.json", report)
        publish(
            destination / "completion.json",
            {
                "result_sha256": scoring.file_sha256(root / "results" / f"{NAME}.json"),
                "artifacts_sha256": artifacts,
            },
        )
        return report
    except Exception as error:
        publish(
            destination / "invalid.json",
            {
                "experiment": NAME,
                "completed": False,
                "error": str(error),
                "type": type(error).__name__,
                "time": datetime.now(UTC).isoformat(),
            },
        )
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    report = run(Path(__file__).resolve().parents[3], args.db)
    print(json.dumps({"experiment": NAME, "verdict": report["verdict"], "completed": True}))


if __name__ == "__main__":
    main()
