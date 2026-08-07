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
    Phase4EVBacktestConfig,
    load_phase4_ev_backtest_evaluation,
    repo_root,
)
from fpl.storage.db import connect, default_db_path
from fpl.validate.ev_backtest_adapter import (
    BpsResidualParameters,
    FixtureForecast,
    ForecastTarget,
    bps_residual_parameters_from_contract,
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
from fpl.validate.metrics import PROBABILITY_FLOOR
from fpl.validate.points_harness import default_component_suite

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


def _assert_contract_drives_runtime(contract: Phase4EVBacktestConfig) -> None:
    """Fail closed where a frozen contract value is realised by a code constant.

    Most contract fields are threaded into the call that acts on them. Two cannot be: the log
    probability floor lives in :mod:`fpl.validate.metrics` and the component identities live on
    the model classes. Asserting them here means a divergence stops the run rather than being
    recorded as though the contract had governed it.
    """
    floor = contract.scoring_calibration.log_probability_floor
    if abs(PROBABILITY_FLOOR - floor) > 1e-18:
        raise RuntimeError(
            f"Contract log_probability_floor {floor} != metrics.PROBABILITY_FLOOR "
            f"{PROBABILITY_FLOOR}"
        )

    suite = default_component_suite()
    expected = {
        "minutes": (contract.components.minutes, suite.minutes_name),
        "saves": (contract.components.saves, suite.saves_name),
        "defensive_contribution": (contract.components.defensive_contribution, suite.dc_name),
        "comparator_attacking": (contract.diagnostic_comparator.attacking, suite.goals_name),
        "comparator_assists": (contract.diagnostic_comparator.assists, suite.assists_name),
    }
    for label, (contract_name, actual_name) in expected.items():
        if contract_name != actual_name:
            raise RuntimeError(
                f"Contract component {label} is '{contract_name}' but the executed suite "
                f"installs '{actual_name}'"
            )

    # Stated as policy in the contract; the adapter implements neither a prior-season blend nor
    # an availability overlay, so any value other than the identity would be a false record.
    if contract.primary_architecture.prior_season_blend_weight != 0.0:
        raise RuntimeError("The adapter applies no prior-season appearance blend")
    if contract.primary_architecture.historical_availability_multiplier != 1.0:
        raise RuntimeError("The adapter applies no historical availability multiplier")


def _target_completeness(
    con: duckdb.DuckDBPyConnection, season: str, ruleset_id: str
) -> dict[str, object]:
    """Read and enforce `mart_target_completeness` for the scored season and ruleset.

    The backtest scores `points_under_rules_2026_27`, which silently understates a player
    whenever the season did not measure a component the ruleset needs. That is exactly what
    this table records, so the run refuses to proceed on an incomplete season and the result is
    written into the reconciliation record either way.
    """
    row = con.execute(
        """
        SELECT missing_components, is_complete, row_count
        FROM mart_target_completeness
        WHERE season = ? AND ruleset_id = ?
        """,
        [season, ruleset_id],
    ).fetchone()
    if row is None:
        raise RuntimeError(
            f"No mart_target_completeness row for season {season} / ruleset {ruleset_id}; "
            "target completeness is unproven"
        )
    missing, is_complete, row_count = row
    if not bool(is_complete):
        raise RuntimeError(
            f"Season {season} is incomplete under ruleset {ruleset_id}: missing components "
            f"'{missing}'. Replayed points would understate affected players."
        )
    return {
        "season": season,
        "ruleset_id": ruleset_id,
        "missing_components": str(missing),
        "is_complete": bool(is_complete),
        "row_count": int(row_count),
    }


def run_ev_backtest(
    con: duckdb.DuckDBPyConnection,
    *,
    season: str = "2025-26",
    start_gw: int = 29,
    end_gw: int = 38,
    draws: int = 2000,
    seed: int = 202627,
    max_support: int = 34,
    seasonal_appearance_min_rows: int = 3,
    pit_seed: int = 202627,
    pit_band: tuple[float, float] = (0.1, 0.9),
    bps_residual: BpsResidualParameters | None = None,
) -> tuple[BacktestScoreReport, BacktestScoreReport, int, int]:
    """Execute the EV walk-forward backtest over start_gw..end_gw.

    Every keyword is a frozen contract value supplied by :func:`main`; the defaults exist only
    so a test can call this directly. Nothing here re-derives a policy the contract already
    fixes.

    Returns (primary_report, comparator_report, total_derived_fixtures, total_derived_target_rows).
    """
    logger.info("Starting EV Walk-forward Backtest over %s GW%d-%d", season, start_gw, end_gw)

    bps_params = bps_residual or bps_residual_parameters_from_contract()

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

        # Primary architecture forecasts (V3 goals + coupled assists). Every argument other
        # than `use_v3_primary` is identical between the two calls, so the only thing that can
        # move a number is the attacking-goal/assist architecture itself.
        primary_fc = generate_forecasts_for_fold(
            con,
            season,
            gw,
            use_v3_primary=True,
            draws=draws,
            base_seed=seed,
            max_support=max_support,
            seasonal_appearance_min_rows=seasonal_appearance_min_rows,
            bps_residual=bps_params,
        )

        # Comparator architecture forecasts (V1 goals + V1 assists)
        comp_fc = generate_forecasts_for_fold(
            con,
            season,
            gw,
            use_v3_primary=False,
            draws=draws,
            base_seed=seed,  # Identical fixture seed!
            max_support=max_support,
            seasonal_appearance_min_rows=seasonal_appearance_min_rows,
            bps_residual=bps_params,
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

    report_primary = score_backtest_rows(
        primary_fixture_rows, seed=pit_seed, max_support=max_support, pit_band=pit_band
    )
    report_comparator = score_backtest_rows(
        comparator_fixture_rows, seed=pit_seed, max_support=max_support, pit_band=pit_band
    )

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
    _assert_contract_drives_runtime(contract)
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

    # Diagnostic only. The authoritative code identity is the clean-worktree check plus the Git
    # HEAD SHA above: together they pin every tracked file, which no hash list can. These hashes
    # exist to catch a mid-run edit -- a change made after preflight and before the postflight
    # comparison, which leaves HEAD untouched and the worktree clean at both ends. So the list
    # covers every module that determines what the architecture computes, not just the four new
    # ones, because a mid-run edit to the minutes model is as invalidating as one to the adapter.
    source_files = [
        root / "src" / "fpl" / "validate" / "ev_backtest_adapter.py",
        root / "src" / "fpl" / "validate" / "ev_backtest_harness.py",
        root / "src" / "fpl" / "validate" / "dev_ev_backtest.py",
        root / "src" / "fpl" / "validate" / "points_harness.py",
        root / "src" / "fpl" / "validate" / "points_harness_v3.py",
        root / "src" / "fpl" / "validate" / "metrics.py",
        root / "src" / "fpl" / "validate" / "baselines.py",
        root / "src" / "fpl" / "models" / "points_composition.py",
        root / "src" / "fpl" / "models" / "bps_bonus.py",
        root / "src" / "fpl" / "models" / "gk_saves_v1.py",
        root / "src" / "fpl" / "models" / "defensive_contribution_v1.py",
        root / "src" / "fpl" / "models" / "minutes_v3.py",
        root / "src" / "fpl" / "models" / "attacking_v1.py",
        root / "src" / "fpl" / "models" / "attacking_v3.py",
        root / "src" / "fpl" / "models" / "attacking_assists_v1.py",
        root / "src" / "fpl" / "jobs" / "prospective_points_v1.py",
    ]
    missing_sources = [p for p in source_files if not p.exists()]
    if missing_sources:
        logger.error("Provenance source files missing: %s", [str(p) for p in missing_sources])
        sys.exit(1)
    preflight_source_hashes = {p.name: _file_sha256(p) for p in source_files}

    # Pre-registered at amendment 1.2 and threaded into the adapter, so this records what
    # governed the run rather than what a dataclass happened to default to afterwards.
    bps_params = bps_residual_parameters_from_contract()

    created_at = _utc_now()

    con = connect(db_path, read_only=True)
    tmp_path: Path | None = None
    try:
        completeness = _target_completeness(
            con, contract.horizon.season, contract.target_population.scoring_ruleset
        )

        report_primary, report_comp, derived_fixtures, derived_target_rows = run_ev_backtest(
            con,
            season=contract.horizon.season,
            start_gw=contract.horizon.start_gw,
            end_gw=contract.horizon.end_gw,
            draws=contract.monte_carlo.draws,
            seed=contract.monte_carlo.seed,
            max_support=contract.support.max_fixture_points,
            seasonal_appearance_min_rows=(
                contract.primary_architecture.seasonal_appearance_min_rows
            ),
            pit_seed=contract.scoring_calibration.randomized_pit_seed,
            pit_band=contract.scoring_calibration.randomized_pit_band,
            bps_residual=bps_params,
        )

        # Validate derived anchors using explicit exceptions
        expected_gws = contract.horizon.expected_gws
        if (report_primary.start_gw, report_primary.end_gw) != (expected_gws[0], expected_gws[-1]):
            raise ValueError(
                f"Gameweeks ({report_primary.start_gw}, {report_primary.end_gw}) != "
                f"({expected_gws[0]}, {expected_gws[-1]})"
            )
        if len(expected_gws) != contract.horizon.expected_selected_gws:
            raise ValueError(
                f"Derived gameweek count {len(expected_gws)} != expected "
                f"{contract.horizon.expected_selected_gws}"
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
            "bps_residual_parameters_applied": dataclasses.asdict(bps_params),
            "target_completeness": completeness,
            # What the contract actually governed at runtime, as opposed to what it declares.
            "contract_policy_applied": {
                "max_fixture_points": contract.support.max_fixture_points,
                "seasonal_appearance_min_rows": (
                    contract.primary_architecture.seasonal_appearance_min_rows
                ),
                "prior_season_blend_weight": (
                    contract.primary_architecture.prior_season_blend_weight
                ),
                "historical_availability_multiplier": (
                    contract.primary_architecture.historical_availability_multiplier
                ),
                "monte_carlo_draws": contract.monte_carlo.draws,
                "monte_carlo_seed": contract.monte_carlo.seed,
                "log_probability_floor": contract.scoring_calibration.log_probability_floor,
                "randomized_pit_band": list(contract.scoring_calibration.randomized_pit_band),
                "randomized_pit_seed": contract.scoring_calibration.randomized_pit_seed,
            },
            "weekly_metric_grain": "player_gameweek",
            "overall_metric_grain": "player_fixture",
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

        # Immutable publication. The record is written whole to a UUID-named temporary file and
        # then moved into place, so a reader never sees a partial artifact and a failed run
        # leaves no output at all.
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.exists():
            raise FileExistsError(f"Destination output file {out_path} already exists")

        tmp_path = out_path.with_name(f"{out_path.name}.{uuid.uuid4().hex}.tmp")
        tmp_path.write_text(json.dumps(reconciliation, indent=2, allow_nan=False), encoding="utf-8")

        # The move is atomic; the no-clobber guarantee comes from these existence checks, NOT
        # from os.rename, which silently overwrites on POSIX. That is a bounded guarantee for a
        # single-process development runner and would not survive a concurrent writer.
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
