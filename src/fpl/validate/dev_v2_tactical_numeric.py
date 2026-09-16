"""One new numerical-only tactical amendment; never restart the consumed V1 run."""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import traceback
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict

from fpl.config import repo_root
from fpl.features.pit import AsOf
from fpl.storage.db import connect
from fpl.validate import dev_v2_real_sot as scoring
from fpl.validate import dev_v2_tactical_matchup as legacy
from fpl.validate.dev_v2_weekly_sot import _publish_result
from fpl.validate.tactical_metric_audit import build_audit
from fpl.validate.v2_environment_harness import load_team_frame, promoted_team_codes

CANDIDATE = "retrospective_tactical_matchup_team_environment_v1_numeric1"
CONFIG = "config/v2_tactical_numeric_evaluation.yaml"
RESULT = "results/v2_tactical_numeric_development.json"
DESIGN = "docs/v2-tactical-numerical-amendment.md"
PARENT_SHA = "672a36d9d6fc446bb7492eb89eebd63f15bee860"
logger = logging.getLogger(__name__)


class NumericalAmendment(BaseModel):
    """Only numerical/execution settings may differ from the hash-pinned parent."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    amendment_version: Literal["1.1"]
    candidate: Literal["retrospective_tactical_matchup_team_environment_v1_numeric1"]
    parent_candidate: Literal["retrospective_tactical_matchup_team_environment_v1"]
    parent_preregistration_sha: Literal["672a36d9d6fc446bb7492eb89eebd63f15bee860"]
    parent_config: Literal["config/v2_tactical_matchup_evaluation.yaml"]
    parent_config_sha256: Literal[
        "a640ff31f6d1701df12ee9ba3267636ea2856a49cd1496ef68d658b60317c781"
    ]
    parent_failure: Literal["results/v2_tactical_matchup_development.json"]
    parent_failure_sha256: Literal[
        "726e513660045f0e34cce9909d7e8e4ac9c0a3999d8a23630866550159bdd8ed"
    ]
    amendment_kind: Literal["numerical_method_and_execution_evidence_only"]
    statistical_procedure: Literal["inherit_parent_byte_frozen_without_override"]
    solver: Literal["poisson_offset_stable_difference_v1"]
    maximum_iterations: Literal[40]
    maximum_backtracks: Literal[30]
    armijo: float
    tolerance: float
    roundoff_multiplier: Literal[64]
    small_increment: float
    small_increment_series_degree: Literal[6]
    maximum_absolute_training_eta: Literal[20]
    initialization: Literal["zero"]
    convergence: Literal["final_gradient_and_undamped_newton_step"]
    objective_difference: Literal["actual_representable_delta_expm1_remainder"]
    failure_policy: Literal["stop_retain_failure_and_consumed_claim_no_fallback_or_resume"]
    checkpoint_policy: Literal["complete_gameweek_atomic_exclusive_fsynced_not_resumable"]
    formal_runs: Literal[1]
    require_clean_worktree: Literal[True]
    promotion_permitted: Literal[False]


def load_contract(root: Path) -> tuple[NumericalAmendment, legacy.TacticalContract]:
    amendment = NumericalAmendment.model_validate(yaml.safe_load((root / CONFIG).read_bytes()))
    for key, value in (("armijo", 1e-4), ("tolerance", 1e-9), ("small_increment", 1e-3)):
        if getattr(amendment, key) != value:
            raise ValueError(f"unsupported numerical policy: {key}")
    for path, expected in (
        (amendment.parent_config, amendment.parent_config_sha256),
        (amendment.parent_failure, amendment.parent_failure_sha256),
    ):
        if scoring.file_sha256(root / path) != expected:
            raise RuntimeError(f"frozen parent input changed: {path}")
    failure = json.loads((root / amendment.parent_failure).read_bytes())
    if (
        failure["artifact_kind"] != "execution_failure"
        or failure["completed"] is not False
        or failure["attempt_provenance"]["git_head"] != PARENT_SHA
    ):
        raise RuntimeError("parent is not the retained incomplete V1 attempt")
    return amendment, legacy.load_contract(root / amendment.parent_config)


def _snapshot(root: Path, db: Path, amendment: NumericalAmendment) -> dict[str, Any]:
    snapshot = legacy._snapshot(root, db)
    snapshot["config_sha256"] = scoring.file_sha256(root / CONFIG)
    snapshot["source_sha256"][DESIGN] = scoring.file_sha256(root / DESIGN)
    failure = json.loads((root / amendment.parent_failure).read_bytes())
    snapshot["parent_preregistration_sha"] = PARENT_SHA
    snapshot["parent_model_source_sha256"] = failure["attempt_provenance"]["model_source_sha256"]
    snapshot["parent_config_sha256"] = amendment.parent_config_sha256
    snapshot["parent_failure_sha256"] = amendment.parent_failure_sha256
    snapshot["numerical_policy"] = amendment.model_dump(mode="json")
    return snapshot


def _claim_path(root: Path) -> Path:
    return root / "data" / "evaluation-claims" / f"{CANDIDATE}.json"


def _checkpoint_path(root: Path) -> Path:
    return root / "data" / "evaluation-checkpoints" / CANDIDATE


def reserve_claim(root: Path, snapshot: Mapping[str, Any]) -> Path:
    path = _claim_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(
            {
                "candidate": CANDIDATE,
                "claimed_at_utc": datetime.now(UTC).isoformat(),
                "provenance": snapshot,
                "resume_permitted": False,
            },
            stream,
            sort_keys=True,
            allow_nan=False,
        )
        stream.flush()
        os.fsync(stream.fileno())
    return path


class Checkpoints:
    """Write-once complete-GW evidence, deliberately not a resumable evaluation cache."""

    def __init__(self, root: Path, snapshot: Mapping[str, Any]) -> None:
        self.directory = _checkpoint_path(root)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.snapshot = {
            key: snapshot[key] for key in ("git_head", "config_sha256", "database_sha256")
        }
        self.manifest: list[dict[str, Any]] = []

    def write(self, batch: dict[str, Any]) -> None:
        index = len(self.manifest) + 1
        path = self.directory / f"batch-{index:03d}.json"
        fold = batch["fold"]
        _publish_result(
            path,
            {
                "artifact_kind": "complete_gameweek_checkpoint",
                "candidate": CANDIDATE,
                "formal_evaluation_completed": False,
                "resume_permitted": False,
                "checkpointed_at_utc": datetime.now(UTC).isoformat(),
                "provenance": self.snapshot,
                "historical_batch": index,
                **batch,
            },
        )
        self.manifest.append(
            {
                "historical_batch": index,
                "season": fold["season"],
                "gw": fold["gw"],
                "rows": len(batch["rows"]),
                "path": str(path.resolve()),
                "sha256": scoring.file_sha256(path),
            }
        )


def _safe_json(value: Any) -> Any:
    """Retain exceptional nonfinite diagnostics explicitly, never as invalid JSON."""
    if is_dataclass(value) and not isinstance(value, type):
        return _safe_json(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _safe_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_json(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return {"nonfinite_diagnostic": repr(value)}
    return value


def failure_report(
    exc: BaseException,
    *,
    snapshot: Mapping[str, Any],
    reproduction: Mapping[str, Any],
    claim: Path,
    checkpoints: Checkpoints | None,
    started: str,
    postflight: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "artifact_kind": "execution_failure",
        "candidate": CANDIDATE,
        "incumbent": legacy.INCUMBENT,
        "evidence_class": "retrospective_backfill_development",
        "development_only": True,
        "promotion_permitted": False,
        "completed": False,
        "verdict": "INCONCLUSIVE",
        "scientific_performance_verdict_available": False,
        "candidate_metrics": None,
        "formal_attempts_claimed": 1,
        "restart_permitted": False,
        "failure": {
            "exception_class": type(exc).__name__,
            "message": str(exc),
            "notes": getattr(exc, "__notes__", []),
            "numerical_state": _safe_json(getattr(exc, "state", None)),
            "traceback": "".join(traceback.format_exception(exc)),
        },
        "control_reproduction": reproduction,
        "complete_batch_checkpoints": checkpoints.manifest if checkpoints is not None else [],
        "provenance": {
            **snapshot,
            "started_at_utc": started,
            "failed_at_utc": datetime.now(UTC).isoformat(),
            "execution_claim_sha256": scoring.file_sha256(claim),
            "postflight": postflight,
        },
    }


def verify_candidate_population(
    rows: Sequence[Mapping[str, Any]], incumbent: Mapping[str, Any], seasons: tuple[str, ...]
) -> None:
    expected = {key for key in incumbent if key.split(":", 1)[0] in seasons}
    actual = {row["key"] for row in rows}
    if actual != expected or len(actual) != len(rows):
        raise RuntimeError("candidate fixture identities differ from reproduced incumbent")


def run_formal(root: Path, db: Path) -> dict[str, Any]:
    scoring.require_clean_worktree(root)
    output = root / RESULT
    if output.exists() or _claim_path(root).exists() or _checkpoint_path(root).exists():
        raise FileExistsError("numerical amendment result/claim/checkpoints exist; no second run")
    if not db.is_file() or Path(str(db) + ".wal").exists():
        raise RuntimeError("explicit immutable research DB must exist without a WAL")
    amendment, contract = load_contract(root)
    snapshot = _snapshot(root, db, amendment)
    if snapshot["database_sha256"] != contract.database_sha256:
        raise RuntimeError("wrong historical database fingerprint")
    for path, expected in (
        (contract.coverage_report, contract.coverage_sha256),
        (contract.reference, contract.reference_sha256),
    ):
        if scoring.file_sha256(root / path) != expected:
            raise RuntimeError(f"frozen input changed: {path}")
    started = datetime.now(UTC).isoformat()
    with connect(db, read_only=True) as con:
        audit = build_audit(con)
        frozen_audit = json.loads((root / contract.coverage_report).read_bytes())
        for key, value in audit.items():
            if value != frozen_audit[key]:
                raise RuntimeError(f"coverage/source audit differs: {key}")
        if audit["season_eligibility_decision"]["selected_seasons"] != list(
            contract.eligible_seasons
        ):
            raise RuntimeError("coverage-derived seasons differ from parent contract")
        reference = json.loads((root / contract.reference).read_bytes())
        incumbent, reproduction = legacy.reproduce_incumbent(con, contract, reference)
        logger.info("Incumbent reproduced before numerical candidate claim: %s", reproduction)
        if _snapshot(root, db, amendment) != snapshot:
            raise RuntimeError("provenance changed during incumbent reproduction")
        claim = reserve_claim(root, snapshot)
        checkpoints: Checkpoints | None = None
        try:
            checkpoints = Checkpoints(root, snapshot)
            from fpl.validate.tactical_matchup import run_tactical_walk_forward
            from fpl.validate.tactical_numeric_solver import fit_poisson_offset_stable
            from fpl.validate.tactical_state import load_observations

            frame = load_team_frame(con, provider="fpl_archive")
            latest = frame["kickoff_time"].max()
            if not isinstance(latest, datetime):
                raise RuntimeError("archive has no event boundary")
            observations = load_observations(con, AsOf(latest + timedelta(microseconds=1)))
            measured = run_tactical_walk_forward(
                list(observations),
                incumbent,
                contract.eligible_seasons,
                goal_fitter=fit_poisson_offset_stable,
                checkpoint=checkpoints.write,
            )
            legacy.attach_reciprocal_and_slices(measured["rows"], promoted_team_codes(con))
            verify_candidate_population(measured["rows"], incumbent, contract.eligible_seasons)
            for row in measured["rows"]:
                if tuple(row["distributions"]["incumbent"]) != incumbent[row["key"]][1]:
                    raise RuntimeError("candidate plumbing changed incumbent PMF")
            report = legacy.score_experiment(measured, contract, candidate=CANDIDATE)
            if _snapshot(root, db, amendment) != snapshot:
                raise RuntimeError("provenance changed during formal numerical run")
            report.update(
                artifact_kind="completed_evaluation",
                completed=True,
                control_reproduction=reproduction,
                complete_batch_checkpoints=checkpoints.manifest,
            )
            report["provenance"] = {
                **snapshot,
                "started_at_utc": started,
                "completed_at_utc": datetime.now(UTC).isoformat(),
                "seed": contract.seed,
                "evidence_class": contract.evidence_class,
                "execution_claim_sha256": scoring.file_sha256(claim),
                "sdp_capture_manifest_sha256": audit["manifest_sha256"],
                "sdp_version_policy": contract.version_policy,
                "known_at_rewritten": False,
            }
            _publish_result(output, report)
        except BaseException as exc:
            try:
                postflight: dict[str, Any] = {
                    "snapshot_unchanged": _snapshot(root, db, amendment) == snapshot
                }
            except Exception as postflight_error:
                postflight = {
                    "snapshot_unchanged": False,
                    "error": f"{type(postflight_error).__name__}: {postflight_error}",
                }
            failure = failure_report(
                exc,
                snapshot=snapshot,
                reproduction=reproduction,
                claim=claim,
                checkpoints=checkpoints,
                started=started,
                postflight=postflight,
            )
            try:
                _publish_result(output, failure)
            except Exception as publication_error:
                logger.error("Failure artifact could not publish: %s", publication_error)
            logger.exception("Numerical amendment stopped; claim remains consumed")
            raise
    logger.info(
        "Completed %s, goal lift=%s, CS lift=%s",
        report["verdict"],
        report["relative_goal_log_lift"],
        report["relative_clean_sheet_brier_lift"],
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    run_formal(repo_root(), args.db)


if __name__ == "__main__":
    main()
