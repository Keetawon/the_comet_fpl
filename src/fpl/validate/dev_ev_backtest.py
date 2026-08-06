"""Development-only runner for Stage D / Prospective EV Walk-forward Backtest.

    python -m fpl.validate.dev_ev_backtest

Evaluates prospective EV ranking and points-distribution performance over GW29-38 of 2025-26
against replayed points under scoring_2026_27 rules.

This runner is DEVELOPMENT-ONLY. It carries the known composer conditionality defect (team-coupled
event rates already contain P(play), and the composer gates events again through sampled minutes).
It measures the current development architecture and CANNOT authorize production deployment.

DuckDB is opened READ-ONLY; no database mutation or prospective artifact overwrite occurs.
Output writing is immutable, no-clobber, and atomic via a UUID temporary file.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import logging
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from fpl.config import (
    load_phase4_ev_backtest_evaluation,
    repo_root,
)
from fpl.storage.db import connect, default_db_path
from fpl.validate.ev_backtest_adapter import (
    FixtureForecast,
    ForecastTarget,
    derive_final_ten_gws,
    extract_target_labels_for_gw,
    extract_target_roster_for_gw,
    generate_forecasts_for_fold,
)
from fpl.validate.ev_backtest_harness import (
    BacktestScoreReport,
    FixturePredictionRow,
    score_backtest_rows,
)

logger = logging.getLogger("fpl.validate.dev_ev_backtest")

_DEVELOPMENT_BANNER = (
    "\n"
    "============================================================================\n"
    " DEVELOPMENT ONLY -- NOT A PROMOTION RESULT\n"
    " Prospective EV Walk-forward Backtest (2025-26 GW29-38).\n"
    " Historical archive targets and first-kickoff cutoffs are unversioned proxies.\n"
    " Carries the known composer conditionality defect (P(play) double-gating).\n"
    " Measures the current prospective architecture; CANNOT authorize production use.\n"
    "============================================================================\n"
)


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_commit_sha() -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
        sha = res.stdout.strip()
        if not sha or sha == "unknown":
            raise RuntimeError("Git rev-parse returned empty or unknown commit SHA")
        return sha
    except Exception as e:
        raise RuntimeError(f"Git commit SHA lookup failed: {e}") from e


def _check_clean_worktree() -> bool:
    try:
        res = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
        )
        return len(res.stdout.strip()) == 0
    except Exception:
        return False


def run_ev_backtest(
    con: duckdb.DuckDBPyConnection,
    *,
    season: str = "2025-26",
    start_gw: int = 29,
    end_gw: int = 38,
    draws: int = 2000,
    seed: int = 202627,
) -> tuple[BacktestScoreReport, BacktestScoreReport, int, int]:
    """Execute the EV walk-forward backtest over start_gw..end_gw.

    Returns (primary_report, comparator_report, total_derived_fixtures, total_derived_target_rows).
    """
    logger.info("Starting EV Walk-forward Backtest over %s GW%d-%d", season, start_gw, end_gw)

    derived_gws = derive_final_ten_gws(con, season=season)
    expected_gws = tuple(range(start_gw, end_gw + 1))
    if derived_gws != expected_gws:
        raise ValueError(f"Derived gameweeks {derived_gws} != expected {expected_gws}")

    primary_fixture_rows: list[FixturePredictionRow] = []
    comparator_fixture_rows: list[FixturePredictionRow] = []

    derived_fixtures_set: set[tuple[str, int, int]] = set()
    derived_target_rows_count = 0

    # Generate forecasts for all gameweeks FIRST
    primary_fc_by_gw: dict[int, list[FixtureForecast]] = {}
    comp_fc_by_gw: dict[int, list[FixtureForecast]] = {}
    targets_by_gw: dict[int, list[ForecastTarget]] = {}

    for gw in derived_gws:
        logger.info("Generating forecasts for GW%d...", gw)

        targets = extract_target_roster_for_gw(con, season, gw)
        derived_target_rows_count += len(targets)
        for t in targets:
            derived_fixtures_set.add((t.season, t.gw, t.fixture))
        targets_by_gw[gw] = targets

        # Primary architecture forecasts (V3 goals + coupled assists)
        primary_fc = generate_forecasts_for_fold(
            con,
            season,
            gw,
            use_v3_primary=True,
            draws=draws,
            base_seed=seed,
        )

        # Comparator architecture forecasts (V1 goals + V1 assists)
        comp_fc = generate_forecasts_for_fold(
            con,
            season,
            gw,
            use_v3_primary=False,
            draws=draws,
            base_seed=seed,  # Identical fixture seed!
        )
        primary_fc_by_gw[gw] = primary_fc
        comp_fc_by_gw[gw] = comp_fc

    # Load target labels AFTER forecasts are generated
    for gw in derived_gws:
        logger.info("Scoring GW%d...", gw)

        targets = targets_by_gw[gw]
        labels_map = extract_target_labels_for_gw(con, season, gw)

        target_keys = {(t.season, t.code, t.fixture) for t in targets}
        label_keys = set(labels_map.keys())
        if target_keys != label_keys:
            missing = target_keys - label_keys
            extra = label_keys - target_keys
            raise ValueError(
                f"Target/label key mismatch in GW{gw}: missing={missing}, extra={extra}"
            )

        primary_fc = primary_fc_by_gw[gw]
        comp_fc = comp_fc_by_gw[gw]

        primary_keys = {(f.season, f.code, f.fixture) for f in primary_fc}
        comp_keys = {(f.season, f.code, f.fixture) for f in comp_fc}
        if primary_keys != target_keys:
            raise ValueError(f"Primary forecast keys != target keys in GW{gw}")
        if comp_keys != target_keys:
            raise ValueError(f"Comparator forecast keys != target keys in GW{gw}")

        target_by_code_fix = {(t.code, t.fixture): t for t in targets}

        for p_fc, c_fc in zip(primary_fc, comp_fc, strict=True):
            if (p_fc.code, p_fc.fixture) != (c_fc.code, c_fc.fixture):
                raise ValueError("Primary and Comparator forecast code/fixture mismatch")

            t = target_by_code_fix[(p_fc.code, p_fc.fixture)]
            label = labels_map[(season, t.code, t.fixture)]

            primary_fixture_rows.append(
                FixturePredictionRow(
                    season=t.season,
                    gw=t.gw,
                    fixture=t.fixture,
                    code=t.code,
                    position=str(t.position.value),
                    team_code=t.team_code,
                    opponent_team_code=t.opponent_team_code,
                    ev=p_fc.expected_points,
                    pmf=p_fc.pmf_full,
                    actual_points=label.actual_points,
                )
            )
            comparator_fixture_rows.append(
                FixturePredictionRow(
                    season=t.season,
                    gw=t.gw,
                    fixture=t.fixture,
                    code=t.code,
                    position=str(t.position.value),
                    team_code=t.team_code,
                    opponent_team_code=t.opponent_team_code,
                    ev=c_fc.expected_points,
                    pmf=c_fc.pmf_full,
                    actual_points=label.actual_points,
                )
            )

    report_primary = score_backtest_rows(primary_fixture_rows, seed=seed)
    report_comparator = score_backtest_rows(comparator_fixture_rows, seed=seed)

    return (
        report_primary,
        report_comparator,
        len(derived_fixtures_set),
        derived_target_rows_count,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage D Prospective EV Walk-forward Backtest")
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Optional explicit output path (default: results/ev_backtest_2025_26_gw29_38.json)",
    )
    args = parser.parse_args()

    sys.stdout.write(_DEVELOPMENT_BANNER)

    contract = load_phase4_ev_backtest_evaluation()
    root = repo_root()

    out_path = (
        Path(args.output) if args.output else root / "results" / "ev_backtest_2025_26_gw29_38.json"
    )
    if out_path.exists():
        logger.error(
            "Destination output file %s already exists; immutable no-clobber policy enforced.",
            out_path,
        )
        sys.exit(1)

    db_path = default_db_path()
    if not db_path.exists():
        logger.error("Database path %s does not exist", db_path)
        sys.exit(1)

    # Preflight clean worktree & snapshot check
    if not _check_clean_worktree():
        logger.error("Preflight check failed: worktree is dirty. Refusing to run.")
        sys.exit(1)

    preflight_commit_sha = _git_commit_sha()
    preflight_db_sha256 = _file_sha256(db_path)
    preflight_contract_sha256 = _file_sha256(root / "config" / "phase4_ev_backtest_evaluation.yaml")
    preflight_scoring_sha256 = _file_sha256(root / "config" / "scoring_2026_27.yaml")

    source_files = [
        root / "src" / "fpl" / "validate" / "ev_backtest_adapter.py",
        root / "src" / "fpl" / "validate" / "ev_backtest_harness.py",
        root / "src" / "fpl" / "validate" / "dev_ev_backtest.py",
        root / "src" / "fpl" / "models" / "points_composition.py",
        root / "src" / "fpl" / "jobs" / "prospective_points_v1.py",
    ]
    preflight_source_hashes = {p.name: _file_sha256(p) for p in source_files}

    created_at = _utc_now()

    con = connect(db_path, read_only=True)
    tmp_path: Path | None = None
    try:
        report_primary, report_comp, derived_fixtures, derived_target_rows = run_ev_backtest(
            con,
            season=contract.horizon.season,
            start_gw=contract.horizon.start_gw,
            end_gw=contract.horizon.end_gw,
            draws=contract.monte_carlo.draws,
            seed=contract.monte_carlo.seed,
        )

        # Validate derived anchors using explicit exceptions
        if report_primary.start_gw != 29 or report_primary.end_gw != 38:
            raise ValueError(
                f"Gameweeks ({report_primary.start_gw}, {report_primary.end_gw}) != (29, 38)"
            )
        exp_fix = contract.horizon.expected_fixtures
        if derived_fixtures != exp_fix:
            raise ValueError(f"derived fixtures ({derived_fixtures}) != expected ({exp_fix})")
        exp_rows = contract.horizon.expected_player_fixture_rows
        if derived_target_rows != exp_rows:
            raise ValueError(
                f"derived target rows ({derived_target_rows}) != expected ({exp_rows})"
            )

        completed_at = _utc_now()

    finally:
        # Close DuckDB connection before postflight checks
        con.close()

    # Postflight checks
    if not _check_clean_worktree():
        raise RuntimeError("Postflight check failed: worktree became dirty during run.")
    if _git_commit_sha() != preflight_commit_sha:
        raise RuntimeError("Postflight check failed: Git HEAD commit SHA changed during run.")
    if _file_sha256(db_path) != preflight_db_sha256:
        raise RuntimeError("Postflight check failed: DuckDB database SHA256 changed during run.")
    if (
        _file_sha256(root / "config" / "phase4_ev_backtest_evaluation.yaml")
        != preflight_contract_sha256
    ):
        raise RuntimeError("Postflight check failed: Contract YAML SHA256 changed during run.")
    if _file_sha256(root / "config" / "scoring_2026_27.yaml") != preflight_scoring_sha256:
        raise RuntimeError("Postflight check failed: Scoring YAML SHA256 changed during run.")
    for p in source_files:
        if _file_sha256(p) != preflight_source_hashes[p.name]:
            raise RuntimeError(
                f"Postflight check failed: Source file {p.name} SHA256 changed during run."
            )

    try:
        # Helper to convert dataclass report to dict for JSON serialization
        def _report_dict(r: BacktestScoreReport) -> dict[str, object]:
            d = dataclasses.asdict(r)
            return d

        reconciliation = {
            "contract_version": contract.contract_version,
            "created_at": created_at,
            "completed_at": completed_at,
            "git_commit_sha": preflight_commit_sha,
            "database_sha256": preflight_db_sha256,
            "contract_sha256": preflight_contract_sha256,
            "scoring_sha256": preflight_scoring_sha256,
            "source_hashes": preflight_source_hashes,
            "derived_anchors": {
                "season": contract.horizon.season,
                "start_gw": report_primary.start_gw,
                "end_gw": report_primary.end_gw,
                "distinct_fixture_count": derived_fixtures,
                "total_player_fixture_rows": derived_target_rows,
            },
            "primary_architecture": _report_dict(report_primary),
            "diagnostic_comparator": _report_dict(report_comp),
        }

        # Immutable, no-clobber, UUID-bearing temporary publication
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.exists():
            raise FileExistsError(f"Destination output file {out_path} already exists")

        tmp_path = out_path.with_name(f"{out_path.name}.{uuid.uuid4().hex}.tmp")
        tmp_path.write_text(json.dumps(reconciliation, indent=2, allow_nan=False), encoding="utf-8")

        # Atomic no-clobber rename
        if out_path.exists():
            raise FileExistsError(f"Destination output file {out_path} already exists")
        os.rename(tmp_path, out_path)
        tmp_path = None

        sys.stdout.write("\n=== BACKTEST RECONCILIATION EMITTED ===\n")
        sys.stdout.write(f"Output: {out_path}\n")
        sys.stdout.write(f"Primary NDCG@20: {report_primary.cumulative_ndcg_at_20:.4f}\n")
        sys.stdout.write(f"Primary Spearman: {report_primary.cumulative_spearman:.4f}\n")

    except Exception as e:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()
        logger.error("Run failed with error: %s. Cleaned temporary output.", e)
        raise e


if __name__ == "__main__":
    main()
