"""Development-only runner for Stage C Candidate V1. This is NOT a promotion evaluation.

    python -m fpl.validate.dev_attacking_candidate_v1            # full archive, development only
    python -m fpl.validate.dev_attacking_candidate_v1 --season 2025-26

Candidate V1 (``xg_informed_trailing_player_goals_v1``) is a fixed closed-form estimator: the v1.0
trailing-player goal-rate baseline with its recent GOALS signal replaced by recent xG where xG is
measured and finishing shrunk almost fully to the positional mean, falling back to the exact v1.0
trailing-player baseline where xG is unmeasured. This runner reuses the Stage C harness unchanged --
the same observed-gameweek folds, the same two frozen baselines on the same eligible rows, the same
proper-distribution metrics, slices, and counts -- but fits Candidate V1 alongside those baselines
on the *identical* eligible rows, scores it under the unchanged contract, and prints a **DEVELOPMENT
ONLY** report that **never** emits a promotion verdict. The default harness command
(``python -m fpl.validate.attacking_harness``) is untouched and still supplies no candidate factory.

This runner is pre-registered before any V1 evaluation. Provenance closes every time-of-check /
time-of-use gap the Stage A invalidations exposed:

  * It refuses to start when the Git worktree is dirty, so the recorded SHA names the code that was
    actually scored.
  * The contract is loaded from one snapshotted read of the config bytes, and the recorded config
    fingerprint is the hash of exactly those bytes.
  * It records the Candidate V1 model-source fingerprint, so an edit to ``attacking_v1.py`` between
    capture and print is detected.
  * It records the exact clean commit SHA, the config fingerprint, the candidate-source fingerprint,
    the archive fingerprint, the fixed seed, and UTC start/end timestamps.
  * After the database is closed, it captures ``ended_at`` and re-checks the worktree, HEAD, config
    fingerprint, candidate-source fingerprint, and database fingerprint against the preflight
    snapshot. If anything moved during the run the result is suppressed as INVALID/UNPUBLISHABLE,
    and the printable provenance is constructed only after that recheck passes.

The frozen promotion gate is evaluated as **structured development diagnostics only** -- each
condition is reported as its own labelled check and is never combined into a production promotion
verdict. This module is committed before any V1 result exists; running the full evaluation is the
single explicitly authorized clean historical development run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import yaml

from fpl.config import Phase3EvaluationConfig, config_dir, repo_root
from fpl.models.attacking_baselines import PlayerHistoryRow
from fpl.storage.db import connect, default_db_path
from fpl.validate.attacking_harness import (
    AttackingCandidateFactory,
    AttackingHarnessResult,
    run_attacking_harness,
)
from fpl.validate.attacking_metrics import AttackingScoreReport, ReliabilityCurve
from fpl.validate.metrics import relative_lift

logger = logging.getLogger("fpl.validate.dev_attacking_candidate_v1")

_DEVELOPMENT_BANNER = (
    "\n"
    "============================================================================\n"
    " DEVELOPMENT ONLY -- NOT A PROMOTION RESULT\n"
    " Candidate V1 (xg_informed_trailing_player_goals_v1). The historical archive is\n"
    " development evidence (an unversioned target-roster / first-kickoff proxy), not a\n"
    " fresh holdout. Prospective 2026/27 is the untouched confirmation set, not consumed.\n"
    " No number below is a promotion verdict; V1 is judged by no promotion gate.\n"
    "============================================================================\n"
)

_DEVELOPMENT_DIAGNOSTIC_LABEL = "DEVELOPMENT DIAGNOSTIC ONLY"

# The Candidate V1 model source this runner scores. Fingerprinted so a mid-run edit is detected.
_CANDIDATE_SOURCE_REL = Path("src") / "fpl" / "models" / "attacking_v1.py"


def _utc_now() -> str:
    """A timezone-aware UTC timestamp as a fixed ``YYYY-MM-DDTHH:MM:SSZ`` string."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------------------
# Git / file fingerprinting
# --------------------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def worktree_is_clean(repo: Path) -> bool:
    return _git(repo, "status", "--porcelain") == ""


def require_clean_worktree(repo: Path) -> None:
    porcelain = _git(repo, "status", "--porcelain")
    if porcelain:
        raise SystemExit(
            "Candidate V1 refuses to run on a dirty worktree. The recorded commit SHA must name "
            "the exact code that was scored, and uncommitted changes would make it a lie. Commit "
            "or stash the following before re-running:\n" + porcelain
        )


def head_commit_sha(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def candidate_source_path(repo: Path) -> Path:
    return repo / _CANDIDATE_SOURCE_REL


def load_contract_from_bytes(config_path: Path) -> tuple[Phase3EvaluationConfig, str]:
    """Read the contract bytes once and load the typed contract from those exact bytes."""
    raw = config_path.read_bytes()
    loaded = yaml.safe_load(raw)
    if not isinstance(loaded, dict):
        raise ValueError(f"{config_path} did not parse to a mapping")
    return Phase3EvaluationConfig.model_validate(loaded), hash_bytes(raw)


# --------------------------------------------------------------------------------------
# Provenance lifecycle: preflight snapshot -> verify -> finalize
# --------------------------------------------------------------------------------------


class ProvenanceError(RuntimeError):
    """The (code, config, candidate-source, data) quadruple changed between capture and print."""


@dataclass(frozen=True, slots=True)
class PreflightSnapshot:
    candidate: str
    contract_version: str
    commit_sha: str
    config_fingerprint: str
    candidate_source_fingerprint: str
    archive_fingerprint: str
    seed: int
    started_at: str


@dataclass(frozen=True, slots=True)
class Provenance:
    candidate: str
    contract_version: str
    commit_sha: str
    config_fingerprint: str
    candidate_source_fingerprint: str
    archive_fingerprint: str
    seed: int
    started_at: str
    ended_at: str

    def as_lines(self) -> list[str]:
        return [
            "provenance",
            f"  candidate             : {self.candidate}",
            f"  contract version      : {self.contract_version}",
            f"  commit sha            : {self.commit_sha}",
            f"  config fingerprint    : {self.config_fingerprint}",
            f"  candidate source fp   : {self.candidate_source_fingerprint}",
            f"  archive fingerprint   : {self.archive_fingerprint}",
            f"  seed                  : {self.seed}",
            f"  started at (UTC)      : {self.started_at}",
            f"  ended at (UTC)        : {self.ended_at}",
        ]


def capture_preflight(
    db_path: Path,
    config: Phase3EvaluationConfig,
    *,
    repo: Path,
    config_path: Path,
    config_fp: str,
    candidate_source_path: Path,
    candidate_source_fp: str,
) -> PreflightSnapshot:
    return PreflightSnapshot(
        candidate=config.stage_c_candidate_v1.name,
        contract_version=config.contract_version,
        commit_sha=head_commit_sha(repo),
        config_fingerprint=config_fp,
        candidate_source_fingerprint=candidate_source_fp,
        archive_fingerprint=file_sha256(db_path),
        seed=config.training.seed,
        started_at=_utc_now(),
    )


def verify_snapshot(
    snapshot: PreflightSnapshot,
    *,
    db_path: Path,
    repo: Path,
    config_path: Path,
    candidate_source_path: Path,
) -> None:
    porcelain = _git(repo, "status", "--porcelain")
    if porcelain:
        raise ProvenanceError(
            "worktree became dirty during the run, so the recorded commit no longer names the "
            "scored code:\n" + porcelain
        )
    if head_commit_sha(repo) != snapshot.commit_sha:
        raise ProvenanceError("HEAD changed during the run; the result is INVALID/UNPUBLISHABLE")
    if file_sha256(config_path) != snapshot.config_fingerprint:
        raise ProvenanceError(
            "config fingerprint changed during the run; the result is INVALID/UNPUBLISHABLE"
        )
    if file_sha256(candidate_source_path) != snapshot.candidate_source_fingerprint:
        raise ProvenanceError(
            "Candidate V1 source fingerprint changed during the run; the result is "
            "INVALID/UNPUBLISHABLE"
        )
    if file_sha256(db_path) != snapshot.archive_fingerprint:
        raise ProvenanceError(
            "database fingerprint changed during the run; the result is INVALID/UNPUBLISHABLE"
        )


def finalize_provenance(snapshot: PreflightSnapshot, *, ended_at: str) -> Provenance:
    return Provenance(
        candidate=snapshot.candidate,
        contract_version=snapshot.contract_version,
        commit_sha=snapshot.commit_sha,
        config_fingerprint=snapshot.config_fingerprint,
        candidate_source_fingerprint=snapshot.candidate_source_fingerprint,
        archive_fingerprint=snapshot.archive_fingerprint,
        seed=snapshot.seed,
        started_at=snapshot.started_at,
        ended_at=ended_at,
    )


def open_database(db_path: Path) -> duckdb.DuckDBPyConnection:
    return connect(db_path, read_only=True)


# --------------------------------------------------------------------------------------
# Candidate V1 factory: fold-local, conforming to the harness protocol
# --------------------------------------------------------------------------------------


def candidate_factory(config: Phase3EvaluationConfig) -> AttackingCandidateFactory:
    """Build the fold-local Candidate V1 factory.

    The model is imported here, not at module load, so importing this runner never depends on a
    particular candidate existing. The constants are read from the frozen contract, not hardcoded.
    """
    from fpl.models.attacking_v1 import XgInformedTrailingPlayerGoalsV1

    alpha = config.stage_c_candidate_v1.alpha
    finishing_keep = config.stage_c_candidate_v1.finishing_keep

    def factory(history: Sequence[PlayerHistoryRow]) -> XgInformedTrailingPlayerGoalsV1:
        model = XgInformedTrailingPlayerGoalsV1(alpha=alpha, finishing_keep=finishing_keep)
        model.fit(history)
        return model

    return factory


# --------------------------------------------------------------------------------------
# Structured development diagnostics (one labelled check per frozen condition)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DevelopmentCheck:
    name: str
    passed: bool
    detail: str
    label: str = _DEVELOPMENT_DIAGNOSTIC_LABEL


@dataclass(frozen=True, slots=True)
class DevelopmentDiagnostics:
    candidate: str
    comparator: str
    comparable: bool
    checks: tuple[DevelopmentCheck, ...]
    note: str = ""

    def passed_count(self) -> int:
        return sum(1 for check in self.checks if check.passed)

    def as_lines(self) -> list[str]:
        lines = [
            "development diagnostics (each check is DEVELOPMENT DIAGNOSTIC ONLY):",
            f"  comparator baseline : {self.comparator}",
        ]
        if not self.comparable:
            lines.append(f"  {self.candidate} produced no comparable overall predictions")
            return lines
        for check in self.checks:
            verdict = "PASS" if check.passed else "FAIL"
            lines.append(f"  [{verdict}] {check.name} -- {check.detail} ({check.label})")
        lines.append(
            "  These checks are DEVELOPMENT DIAGNOSTICS ONLY; they are NOT combined into a "
            "promotion verdict."
        )
        return lines


def best_baseline_metric(
    result: AttackingHarnessResult, *, attr: str, higher_is_better: bool
) -> tuple[float, str]:
    """The best required-baseline value of one metric, and the baseline that supplied it.

    Each bounded guardrail is measured against the best value of ITS OWN metric across the required
    baselines (amendment ``guardrail_comparison: best_baseline_per_metric``). Lower-is-better
    metrics (RPS, Brier) take the minimum; the log-score comparator is the best-by-log baseline.
    Ties break on the frozen baseline order (``STAGE_C_ATTACKING_BASELINE_ORDER``).
    """
    scored: list[tuple[float, str]] = []
    for name in result.baseline_names:
        report = result.overall.get(name)
        if report is None:
            continue
        value = float(getattr(report, attr))
        scored.append((value, name))
    if not scored:
        raise ValueError(
            f"no required baseline has a finite {attr} value; cannot form a guardrail bar"
        )
    if higher_is_better:
        return min(scored, key=lambda value_name: -value_name[0])
    return min(scored, key=lambda value_name: value_name[0])


def _no_regression_check(
    name: str,
    baseline_metric: float,
    candidate_metric: float,
    *,
    allowed_regression: float,
    bar: str,
) -> DevelopmentCheck:
    lift = relative_lift(baseline_metric, candidate_metric)
    regression = max(0.0, -lift)
    passed = regression <= allowed_regression
    detail = (
        f"lift {lift:+.4%} (regression {regression:.4%}); allowed regression "
        f"<= {allowed_regression:.2%}; candidate {candidate_metric:.5f} vs bar {bar} "
        f"{baseline_metric:.5f}"
    )
    return DevelopmentCheck(name=name, passed=passed, detail=detail)


def compute_development_diagnostics(
    result: AttackingHarnessResult, candidate: str, config: Phase3EvaluationConfig
) -> DevelopmentDiagnostics:
    """Evaluate every frozen gate condition as an independent development diagnostic.

    Thresholds are read from the unchanged ``config.promotion`` block (never hardcoded). No check is
    combined into a verdict.
    """
    comparator = result.best_baseline_name
    if candidate not in result.overall or comparator not in result.overall:
        return DevelopmentDiagnostics(
            candidate=candidate,
            comparator=comparator,
            comparable=False,
            checks=(),
            note=f"{candidate} produced no overall predictions to compare",
        )

    base = result.overall[comparator]
    cand = result.overall[candidate]
    gate = config.promotion

    log_lift = relative_lift(base.mean_log_score, cand.mean_log_score)
    checks: list[DevelopmentCheck] = [
        DevelopmentCheck(
            name="aggregate_mean_log_score_lift_at_least_minimum",
            passed=log_lift >= gate.minimum_primary_relative_lift,
            detail=(
                f"lift {log_lift:+.4%} (candidate {cand.mean_log_score:.5f} vs bar {comparator} "
                f"{base.mean_log_score:.5f}); required >= {gate.minimum_primary_relative_lift:.2%}"
            ),
        ),
    ]

    best_rps, best_rps_name = best_baseline_metric(
        result, attr="mean_ranked_probability_score", higher_is_better=False
    )
    checks.append(
        _no_regression_check(
            "no_aggregate_ranked_probability_score_regression",
            best_rps,
            cand.mean_ranked_probability_score,
            allowed_regression=gate.maximum_ranked_probability_score_relative_regression,
            bar=best_rps_name,
        )
    )
    best_brier, best_brier_name = best_baseline_metric(
        result, attr="mean_brier_at_least_one_goal", higher_is_better=False
    )
    checks.append(
        _no_regression_check(
            "no_aggregate_brier_at_least_one_goal_regression",
            best_brier,
            cand.mean_brier_at_least_one_goal,
            allowed_regression=gate.maximum_brier_relative_regression_at_least_one_goal,
            bar=best_brier_name,
        )
    )

    # Coverage is structural: the harness scores every eligible row and excludes none.
    coverage = cand.predictions / (cand.predictions + cand.exclusions) if cand.predictions else 1.0
    folds_evaluated = sum(result.folds_by_season.values())
    checks.extend(
        [
            DevelopmentCheck(
                name="pit_interval_80_absolute_error_at_most_maximum",
                passed=cand.pit_interval_80_error <= gate.pit_interval_80_maximum_absolute_error,
                detail=(
                    f"PIT-80 absolute error {cand.pit_interval_80_error:.4f}; allowed <= "
                    f"{gate.pit_interval_80_maximum_absolute_error:.2f}"
                ),
            ),
            DevelopmentCheck(
                name="prediction_coverage_at_least_minimum",
                passed=coverage >= gate.minimum_prediction_coverage,
                detail=(
                    f"coverage {coverage:.4f}; required >= {gate.minimum_prediction_coverage:.2f}"
                ),
            ),
            DevelopmentCheck(
                name="folds_evaluated_at_least_minimum",
                passed=folds_evaluated >= gate.minimum_fold_count,
                detail=(
                    f"{folds_evaluated} folds evaluated; required >= {gate.minimum_fold_count}"
                ),
            ),
            DevelopmentCheck(
                name="zero_leakage_failures",
                passed=result.leakage_failures == 0 and gate.require_zero_leakage_failures,
                detail=f"{result.leakage_failures} leakage failures; required 0",
            ),
        ]
    )

    seasons = sorted(
        season
        for season in result.by_season
        if candidate in result.by_season[season] and comparator in result.by_season[season]
    )
    regressing: list[tuple[str, float]] = []
    for season in seasons:
        season_base = result.by_season[season][comparator]
        season_cand = result.by_season[season][candidate]
        season_lift = relative_lift(season_base.mean_log_score, season_cand.mean_log_score)
        if season_lift < 0.0:
            regressing.append((season, season_lift))
    per_season_passed = not regressing and gate.require_no_season_mean_log_score_regression
    regressing_text = ", ".join(f"{season}({lift:+.2%})" for season, lift in regressing)
    detail = f"{len(regressing)} of {len(seasons)} seasons regress" + (
        f": {regressing_text}" if regressing else ""
    )
    checks.append(
        DevelopmentCheck(
            name="no_per_season_mean_log_score_regression",
            passed=per_season_passed,
            detail=detail,
        )
    )

    return DevelopmentDiagnostics(
        candidate=candidate, comparator=comparator, comparable=True, checks=tuple(checks)
    )


# --------------------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------------------


def _format_metric_row(report: AttackingScoreReport) -> str:
    return (
        f"    log {report.mean_log_score:.5f} (SE {report.uncertainty:.5f}), "
        f"RPS {report.mean_ranked_probability_score:.5f}, "
        f"Brier(>=1) {report.mean_brier_at_least_one_goal:.5f}, "
        f"PIT-80 cov {report.pit_interval_80_coverage:.3f}, "
        f"cold {report.cold_starts}/{report.predictions}"
    )


def _format_path_split(counts: dict[str, int]) -> str:
    total = sum(counts.values())
    parts = []
    for path in sorted(counts):
        parts.append(
            f"{path}={counts[path]} ({100.0 * counts[path] / total:.2f}%)" if total else f"{path}=0"
        )
    return ", ".join(parts) if total else "none"


def format_development_report(
    result: AttackingHarnessResult,
    candidate: str,
    config: Phase3EvaluationConfig,
    *,
    provenance: Provenance,
    diagnostics: DevelopmentDiagnostics,
) -> str:
    lines = [_DEVELOPMENT_BANNER]
    lines += provenance.as_lines()
    lines += [
        "",
        f"model                  : {candidate} (development-only)",
        "primary metric         : mean log score (lower is better); RPS/Brier are guardrails",
        f"comparator baseline    : {diagnostics.comparator} "
        "(best required baseline by mean log score)",
    ]
    if diagnostics.comparable and candidate in result.overall:
        lines += [
            "",
            "overall (development diagnostics, NOT a gate):",
            f"  {candidate}",
            _format_metric_row(result.overall[candidate]),
            f"  {diagnostics.comparator}",
            _format_metric_row(result.overall[diagnostics.comparator]),
        ]
    lines += ["", *diagnostics.as_lines()]

    # xG / fallback / cold-start path split (overall and by season) -- the headline diagnostic for
    # this candidate, since it shows where the xG signal actually acts.
    if candidate in result.candidate_path_counts:
        lines += [
            "",
            f"{candidate} estimator path split (development diagnostic, NOT a gate):",
            f"  overall : {_format_path_split(result.candidate_path_counts[candidate])}",
        ]
        by_season = result.candidate_path_counts_by_season.get(candidate, {})
        for season in sorted(by_season):
            lines.append(f"  {season} : {_format_path_split(by_season[season])}")

    lines += ["", "per-season mean log score (development diagnostics, NOT a gate):"]
    for season in sorted(result.by_season):
        reports = result.by_season[season]
        if candidate in reports and diagnostics.comparator in reports:
            season_lift = relative_lift(
                reports[diagnostics.comparator].mean_log_score,
                reports[candidate].mean_log_score,
            )
            lines.append(
                f"  {season}  candidate {reports[candidate].mean_log_score:.5f}  "
                f"baseline {reports[diagnostics.comparator].mean_log_score:.5f}  "
                f"-> lift {season_lift:+.4%}"
            )

    lines += [
        "",
        "Reminder: this is a DEVELOPMENT result. Do not promote from it. The best required Stage C",
        "attacking baseline remains the Stage C model until a separately pre-registered candidate",
        "clears the unchanged promotion gate against prospective data.",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# Complete machine-readable reconciliation record
# --------------------------------------------------------------------------------------


def _json_float(value: float) -> float | None:
    return value if math.isfinite(value) else None


def _reliability_record(curve: ReliabilityCurve) -> dict[str, object]:
    return {
        "total_n": curve.total_n(),
        "buckets": [
            {
                "lower": bucket.lower,
                "upper": bucket.upper,
                "n": bucket.n,
                "mean_predicted": (
                    None if bucket.mean_predicted is None else _json_float(bucket.mean_predicted)
                ),
                "observed_rate": (
                    None if bucket.observed_rate is None else _json_float(bucket.observed_rate)
                ),
            }
            for bucket in curve.buckets
        ],
    }


def _score_record(report: AttackingScoreReport) -> dict[str, object]:
    coverage = (
        report.predictions / (report.predictions + report.exclusions) if report.predictions else 1.0
    )
    return {
        "predictions": report.predictions,
        "exclusions": report.exclusions,
        "cold_starts": report.cold_starts,
        "mean_log_score": _json_float(report.mean_log_score),
        "mean_log_score_standard_error": _json_float(report.uncertainty),
        "mean_ranked_probability_score": _json_float(report.mean_ranked_probability_score),
        "mean_brier_at_least_one_goal": _json_float(report.mean_brier_at_least_one_goal),
        "pit_interval_80_coverage": _json_float(report.pit_interval_80_coverage),
        "pit_interval_80_absolute_error": _json_float(report.pit_interval_80_error),
        "prediction_coverage": _json_float(coverage),
        "reliability_at_least_one_goal": _reliability_record(report.reliability_at_least_one_goal),
    }


def _score_map_record(
    reports: dict[str, AttackingScoreReport],
) -> dict[str, dict[str, object]]:
    return {name: _score_record(reports[name]) for name in sorted(reports)}


def _slice_record(
    slices: dict[str, dict[str, AttackingScoreReport]],
) -> dict[str, dict[str, dict[str, object]]]:
    return {key: _score_map_record(slices[key]) for key in sorted(slices)}


def build_reconciliation_record(
    result: AttackingHarnessResult,
    config: Phase3EvaluationConfig,
    *,
    provenance: Provenance,
    diagnostics: DevelopmentDiagnostics,
    schema: str = "stage_c_candidate_v1_development/v1",
) -> dict[str, object]:
    """Build the complete result emitted for independent Stage C reconciliation."""
    return {
        "schema": schema,
        "status": "development_only_not_a_promotion_result",
        "provenance": {
            "candidate": provenance.candidate,
            "contract_version": provenance.contract_version,
            "commit_sha": provenance.commit_sha,
            "config_sha256": provenance.config_fingerprint,
            "candidate_source_sha256": provenance.candidate_source_fingerprint,
            "database_sha256": provenance.archive_fingerprint,
            "seed": provenance.seed,
            "started_at_utc": provenance.started_at,
            "ended_at_utc": provenance.ended_at,
        },
        "contract": {
            "phase": config.phase,
            "candidate": provenance.candidate,
            "grain": config.target.grain,
            "identity_policy": config.target.identity_policy,
            "required_baselines": list(result.baseline_names),
            "best_required_baseline": diagnostics.comparator,
            "xg_covered_seasons": list(config.xg_signal_policy.xg_covered_seasons),
        },
        "harness": {
            "folds_evaluated": sum(result.folds_by_season.values()),
            "folds_by_season": dict(sorted(result.folds_by_season.items())),
            "predictions": result.total_predictions,
            "leakage_failures": result.leakage_failures,
            "overall": _score_map_record(result.overall),
            "by_fold": _slice_record(result.by_fold),
            "by_season": _slice_record(result.by_season),
            "by_position": _slice_record(result.by_position),
            "by_home_away": _slice_record(result.by_home_away),
            "candidate_parameters_by_fold": {
                fold: {
                    model: dict(sorted(parameters.items()))
                    for model, parameters in sorted(models.items())
                }
                for fold, models in sorted(result.parameters_by_fold.items())
            },
            "candidate_path_counts": result.candidate_path_counts,
            "candidate_path_counts_by_season": result.candidate_path_counts_by_season,
        },
        "development_diagnostics": {
            "label": _DEVELOPMENT_DIAGNOSTIC_LABEL,
            "candidate": diagnostics.candidate,
            "comparator": diagnostics.comparator,
            "comparable": diagnostics.comparable,
            "passed_count": diagnostics.passed_count(),
            "checks": [
                {
                    "name": check.name,
                    "passed": check.passed,
                    "detail": check.detail,
                    "label": check.label,
                }
                for check in diagnostics.checks
            ],
            "note": diagnostics.note,
            "combined_promotion_verdict": None,
        },
        "historical_proxy_caveats": {
            "target_roster": config.target_roster.historical_roster_status,
            "cutoff": config.cutoff.prediction_time,
            "real_deadline_knowledge_time_validity": "unproven",
            "archive_result_role": "development_diagnostic_only",
        },
    }


def format_reconciliation_record(record: dict[str, object]) -> str:
    return json.dumps(record, indent=2, sort_keys=True, allow_nan=False)


def _standard_report(result: AttackingHarnessResult) -> str:
    """A concise score table mirroring the baseline harness output."""
    lines = [
        "=== Stage C Attacking Goals Candidate V1 Development Walk-Forward ===",
        f"folds evaluated : {sum(result.folds_by_season.values())}",
        f"predictions     : {result.total_predictions}",
        f"leakage failures: {result.leakage_failures}",
        f"best baseline   : {result.best_baseline_name}",
        "",
        f"{'model':<40}{'log':>9}{'RPS':>9}{'Brier>=1':>9}{'PIT80err':>9}",
        "-" * 76,
    ]
    ordered = sorted(result.overall.items(), key=lambda item: item[1].mean_log_score)
    for name, rep in ordered:
        lines.append(
            f"{name:<40}{rep.mean_log_score:>9.5f}"
            f"{rep.mean_ranked_probability_score:>9.5f}"
            f"{rep.mean_brier_at_least_one_goal:>9.5f}"
            f"{rep.pit_interval_80_error:>9.4f}"
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run Stage C Candidate V1 as a DEVELOPMENT-ONLY evaluation. Not a promotion evaluation."
        )
    )
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--season", action="append", dest="seasons", default=None)
    parser.add_argument("--save-json", type=Path, default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    repo = repo_root()
    config_path = config_dir() / "phase3_evaluation.yaml"
    contract, config_fp = load_contract_from_bytes(config_path)
    require_clean_worktree(repo)

    db_path = args.db or default_db_path()
    cand_source = candidate_source_path(repo)
    snapshot = capture_preflight(
        db_path,
        contract,
        repo=repo,
        config_path=config_path,
        config_fp=config_fp,
        candidate_source_path=cand_source,
        candidate_source_fp=file_sha256(cand_source),
    )

    factory = candidate_factory(contract)
    con = open_database(db_path)
    try:
        result = run_attacking_harness(
            con, config=contract, seasons=args.seasons, candidate_factory=factory
        )
    finally:
        con.close()

    diagnostics = compute_development_diagnostics(result, snapshot.candidate, contract)
    ended_at = _utc_now()

    try:
        verify_snapshot(
            snapshot,
            db_path=db_path,
            repo=repo,
            config_path=config_path,
            candidate_source_path=cand_source,
        )
    except ProvenanceError as exc:
        sys.stderr.write(
            f"Candidate V1 result is INVALID / UNPUBLISHABLE and will not be printed: {exc}\n"
        )
        return 1

    provenance = finalize_provenance(snapshot, ended_at=ended_at)
    reconciliation = build_reconciliation_record(
        result, contract, provenance=provenance, diagnostics=diagnostics
    )
    standard_report = _standard_report(result)
    development_report = format_development_report(
        result, snapshot.candidate, contract, provenance=provenance, diagnostics=diagnostics
    )
    reconciliation_report = format_reconciliation_record(reconciliation)
    print(standard_report)
    print(development_report)
    print("BEGIN_STAGE_C_CANDIDATE_V1_RECONCILIATION_JSON")
    print(reconciliation_report)
    print("END_STAGE_C_CANDIDATE_V1_RECONCILIATION_JSON")

    if args.save_json:
        args.save_json.parent.mkdir(parents=True, exist_ok=True)
        args.save_json.write_text(reconciliation_report, encoding="utf-8")
        logger.info(f"Saved verbatim reconciliation JSON to {args.save_json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
