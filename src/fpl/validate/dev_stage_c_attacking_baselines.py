"""Development-only runner for Stage C attacking goals baselines.

    uv run python -m fpl.validate.dev_stage_c_attacking_baselines

This runner executes the Stage C attacking goals baseline development evaluation
over the 181-fold walk-forward on `data/fpl.duckdb`. It performs strict provenance checks:
- Refuses to run on a dirty Git worktree.
- Fingerprints code HEAD SHA, contract config YAML, and target database.
- Re-checks provenance before emitting the verbatim reconciliation JSON.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fpl.config import config_dir, load_phase3_evaluation, repo_root
from fpl.storage.db import connect, default_db_path
from fpl.validate.attacking_harness import (
    run_attacking_harness,
    serialize_result,
)

logger = logging.getLogger("fpl.validate.dev_stage_c_attacking_baselines")


@dataclass(frozen=True, slots=True)
class Provenance:
    contract_version: str
    commit_sha: str
    config_fingerprint: str
    db_fingerprint: str
    seed: int
    capture_time_utc: str


def check_git_clean() -> bool:
    res = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root(),
        capture_output=True,
        text=True,
        check=True,
    )
    return len(res.stdout.strip()) == 0


def get_git_commit_sha() -> str:
    res = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root(),
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()


def get_file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture_provenance(config_path: Path, db_path: Path) -> Provenance:
    config = load_phase3_evaluation(config_path)
    return Provenance(
        contract_version=config.contract_version,
        commit_sha=get_git_commit_sha(),
        config_fingerprint=get_file_sha256(config_path),
        db_fingerprint=get_file_sha256(db_path),
        seed=config.training.seed,
        capture_time_utc=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def verify_provenance(initial: Provenance, config_path: Path, db_path: Path) -> None:
    if not check_git_clean():
        raise RuntimeError("Provenance verification failed: Git worktree became dirty during run.")
    current_sha = get_git_commit_sha()
    if current_sha != initial.commit_sha:
        msg = (
            f"Provenance verification failed: Commit SHA moved from {initial.commit_sha} "
            f"to {current_sha}."
        )
        raise RuntimeError(msg)
    current_config_fp = get_file_sha256(config_path)
    if current_config_fp != initial.config_fingerprint:
        raise RuntimeError(
            "Provenance verification failed: config/phase3_evaluation.yaml was modified."
        )
    current_db_fp = get_file_sha256(db_path)
    if current_db_fp != initial.db_fingerprint:
        raise RuntimeError(
            "Provenance verification failed: data/fpl.duckdb was modified during run."
        )


def run_baseline_development(
    *,
    config_path: Path | None = None,
    db_path: Path | None = None,
    out_json: Path | None = None,
    allow_dirty: bool = False,
) -> dict[str, Any]:
    if config_path is None:
        config_path = config_dir() / "phase3_evaluation.yaml"
    if db_path is None:
        db_path = default_db_path()

    if not allow_dirty and not check_git_clean():
        msg = (
            "Git worktree is dirty. Commit or stash changes before running baseline "
            "development evaluation."
        )
        raise RuntimeError(msg)

    initial_provenance = capture_provenance(config_path, db_path)
    config = load_phase3_evaluation(config_path)

    con = connect(db_path, read_only=True)
    try:
        harness_res = run_attacking_harness(con, config=config)
    finally:
        con.close()

    verify_provenance(initial_provenance, config_path, db_path)

    payload = serialize_result(harness_res, contract_version=config.contract_version)
    payload["provenance"] = asdict(initial_provenance)

    if out_json:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info(f"Saved verbatim reconciliation JSON to {out_json}")

    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage C attacking goals baseline development runner"
    )
    parser.add_argument("--save-json", help="Path to save verbatim reconciliation JSON")
    parser.add_argument(
        "--allow-dirty", action="store_true", help="Allow running on dirty worktree"
    )
    args = parser.parse_args()

    out_path = Path(args.save_json) if args.save_json else None
    payload = run_baseline_development(out_json=out_path, allow_dirty=args.allow_dirty)

    print("=== Stage C Attacking Goals Baseline Development Report ===")
    print(f"Contract Version: {payload['contract_version']}")
    print(f"Commit SHA: {payload['provenance']['commit_sha']}")
    print(f"Total Predictions: {payload['total_predictions']}")
    print(f"Best Baseline: {payload['best_baseline']}")
    print("\nOverall Scores:")
    for b_name, rep in payload["overall"].items():
        print(
            f"  {b_name:35s} | log_score={rep['mean_log_score']:.5f} | "
            f"RPS={rep['mean_ranked_probability_score']:.5f} | "
            f"Brier(>=1)={rep['mean_brier_at_least_one_goal']:.5f} | "
            f"PIT80_err={rep['pit_interval_80_error']:.4f}"
        )


if __name__ == "__main__":
    main()
