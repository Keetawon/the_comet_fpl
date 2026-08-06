"""Development-only runner for Stage C Candidate V4. This is NOT a promotion evaluation.

    python -m fpl.validate.dev_attacking_candidate_v4            # full archive, development only
    python -m fpl.validate.dev_attacking_candidate_v4 --season 2025-26

Candidate V4 (``exposure_weighted_xg_team_share_attacking_goals_v4``) is the controlled test of
whether **per-minute attacking productivity times predicted exposure** beats V3's raw per-appearance
xG share. It keeps V3's team-coupling / conservation skeleton and changes THREE things at once:
``shrunk_xg_per_min * E[minutes]`` replaces V3's mean-per-appearance share (a per-MINUTE rate
``sum(xG)/sum(minutes)``; per-90 is reporting-only), the cold-start prior becomes fold-local
position-specific (not V3's committed pooled mean), and the signal is xG-only (no threat fallback).
Constants: Option-A window, fixed ``prior_minutes = 90``, E[minutes] from the frozen
``trailing_5_player_minutes`` distribution via fold-local global bin means. It reuses the Stage C
goals harness unchanged and scores V4 against the two v1.0 baselines on identical eligible
rows.

For the V4-vs-V3 diagnostic (NOT a gate) this runner re-scores Candidate V3 live on the same
archive, folds, eligible rows, and gate (a like-for-like co-run): V3 is the existing Stage C
architecture the exposure hypothesis is tested against. V4 is the provenance-fingerprinted
candidate.

Provenance closes every time-of-check / time-of-use gap (refuses a dirty worktree; one
snapshotted config read; candidate-source + shared-exposure-source + V3-comparator-source
fingerprints; phase-2 minutes-contract fingerprint; exact clean commit SHA; archive fingerprint;
fixed seed; UTC start/end; preflight + postflight recheck that suppresses the result as
INVALID/UNPUBLISHABLE if anything moved during the run). The frozen promotion gate is reported
as **structured development diagnostics only**
-- never a promotion verdict. This module is committed before any V4 result exists; running the full
evaluation is the single explicitly authorized clean historical development run.
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

import yaml

from fpl.config import (
    Phase2EvaluationConfig,
    Phase3EvaluationConfig,
    config_dir,
    load_phase2_from_bytes,
    repo_root,
)
from fpl.models.attacking_baselines import PlayerHistoryRow
from fpl.storage.db import connect, default_db_path
from fpl.validate.attacking_harness import (
    AttackingCandidateFactory,
    AttackingHarnessResult,
    run_attacking_harness,
)
from fpl.validate.attacking_metrics import AttackingScoreReport, ReliabilityCurve
from fpl.validate.dev_attacking_candidate_v1 import (
    DevelopmentDiagnostics,
    compute_development_diagnostics,
)
from fpl.validate.metrics import relative_lift
from fpl.validate.minutes_baselines import MinuteBins

logger = logging.getLogger("fpl.validate.dev_attacking_candidate_v4")

_DEVELOPMENT_BANNER = (
    "\n"
    "============================================================================\n"
    " DEVELOPMENT ONLY -- NOT A PROMOTION RESULT\n"
    " Candidate V4 (exposure_weighted_xg_team_share_attacking_goals_v4). The historical\n"
    " archive is development evidence (an unversioned target-roster / first-kickoff proxy)\n"
    " and the Stage B minutes input is itself a development proxy; neither is a fresh holdout.\n"
    " V4 scores COMPONENT-LEVEL GOALS only; it is never fed to the full-points composer in\n"
    " this slice. Prospective 2026/27 is the untouched confirmation set, not consumed.\n"
    " No number below is a promotion verdict; V4 is judged by no promotion gate.\n"
    "============================================================================\n"
)

_DEVELOPMENT_DIAGNOSTIC_LABEL = "DEVELOPMENT DIAGNOSTIC ONLY"

V3_NAME = "minutes_gated_coupled_team_share_attacking_goals_v3"

_CANDIDATE_SOURCE_REL = Path("src") / "fpl" / "models" / "attacking_v4.py"
_EXPOSURE_SOURCE_REL = Path("src") / "fpl" / "models" / "attacking_exposure.py"
_V3_SOURCE_REL = Path("src") / "fpl" / "models" / "attacking_v3.py"
_PHASE2_CONTRACT = "phase2_evaluation.yaml"


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------------------
# Git / file fingerprinting
# --------------------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def require_clean_worktree(repo: Path) -> None:
    porcelain = _git(repo, "status", "--porcelain")
    if porcelain:
        raise SystemExit(
            "Candidate V4 refuses to run on a dirty worktree. The recorded commit SHA must name "
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


def load_contract_from_bytes(config_path: Path) -> tuple[Phase3EvaluationConfig, str]:
    raw = config_path.read_bytes()
    loaded = yaml.safe_load(raw)
    if not isinstance(loaded, dict):
        raise ValueError(f"{config_path} did not parse to a mapping")
    return Phase3EvaluationConfig.model_validate(loaded), hash_bytes(raw)


# --------------------------------------------------------------------------------------
# Provenance lifecycle
# --------------------------------------------------------------------------------------


class ProvenanceError(RuntimeError):
    """The (code, config, candidate-source, minutes-contract, data) set changed mid-run."""


@dataclass(frozen=True, slots=True)
class PreflightSnapshot:
    candidate: str
    contract_version: str
    commit_sha: str
    config_fingerprint: str
    phase2_config_fingerprint: str
    candidate_source_fingerprint: str
    exposure_source_fingerprint: str
    v3_source_fingerprint: str
    archive_fingerprint: str
    seed: int
    started_at: str


@dataclass(frozen=True, slots=True)
class Provenance:
    candidate: str
    contract_version: str
    commit_sha: str
    config_fingerprint: str
    phase2_config_fingerprint: str
    candidate_source_fingerprint: str
    exposure_source_fingerprint: str
    v3_source_fingerprint: str
    archive_fingerprint: str
    seed: int
    started_at: str
    ended_at: str

    def as_lines(self) -> list[str]:
        return [
            "provenance",
            f"  candidate               : {self.candidate}",
            f"  contract version        : {self.contract_version}",
            f"  commit sha              : {self.commit_sha}",
            f"  config fingerprint      : {self.config_fingerprint}",
            f"  phase2 minutes fp       : {self.phase2_config_fingerprint}",
            f"  candidate source fp     : {self.candidate_source_fingerprint}",
            f"  exposure source fp      : {self.exposure_source_fingerprint}",
            f"  v3 comparator source fp : {self.v3_source_fingerprint}",
            f"  archive fingerprint     : {self.archive_fingerprint}",
            f"  seed                    : {self.seed}",
            f"  started at (UTC)        : {self.started_at}",
            f"  ended at (UTC)          : {self.ended_at}",
        ]


def verify_snapshot(
    snapshot: PreflightSnapshot,
    *,
    db_path: Path,
    repo: Path,
    config_path: Path,
    phase2_config_path: Path,
    candidate_source_path: Path,
    exposure_source_path: Path,
    v3_source_path: Path,
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
    if file_sha256(phase2_config_path) != snapshot.phase2_config_fingerprint:
        raise ProvenanceError(
            "phase2 minutes-contract fingerprint changed during the run; the result is "
            "INVALID/UNPUBLISHABLE"
        )
    if file_sha256(candidate_source_path) != snapshot.candidate_source_fingerprint:
        raise ProvenanceError(
            "Candidate V4 source fingerprint changed during the run; the result is "
            "INVALID/UNPUBLISHABLE"
        )
    if file_sha256(exposure_source_path) != snapshot.exposure_source_fingerprint:
        raise ProvenanceError(
            "shared exposure-source fingerprint changed during the run; the result is "
            "INVALID/UNPUBLISHABLE"
        )
    if file_sha256(v3_source_path) != snapshot.v3_source_fingerprint:
        raise ProvenanceError(
            "Candidate V3 comparator source fingerprint changed during the run; the result is "
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
        phase2_config_fingerprint=snapshot.phase2_config_fingerprint,
        candidate_source_fingerprint=snapshot.candidate_source_fingerprint,
        exposure_source_fingerprint=snapshot.exposure_source_fingerprint,
        v3_source_fingerprint=snapshot.v3_source_fingerprint,
        archive_fingerprint=snapshot.archive_fingerprint,
        seed=snapshot.seed,
        started_at=snapshot.started_at,
        ended_at=ended_at,
    )


# --------------------------------------------------------------------------------------
# Candidate factories: V4 (candidate), V3 (diagnostic co-score)
# --------------------------------------------------------------------------------------


def candidate_factory(
    config: Phase3EvaluationConfig, bins: MinuteBins
) -> AttackingCandidateFactory:
    """Build the fold-local Candidate V4 factory (constants read from the frozen contract)."""
    from fpl.models.attacking_v4 import ExposureWeightedXgTeamShareAttackingGoalsV4

    policy = config.stage_c_candidate_v4

    def factory(history: Sequence[PlayerHistoryRow]) -> ExposureWeightedXgTeamShareAttackingGoalsV4:
        model = ExposureWeightedXgTeamShareAttackingGoalsV4(
            alpha=policy.alpha,
            share_window=policy.history_window,
            bins=bins,
            prior_minutes=policy.prior_minutes,
            empty_bin_fallbacks=policy.expected_minutes_empty_bin_fallbacks,
            max_goals=policy.poisson_max_goals,
        )
        model.fit(history)
        return model

    return factory


def v3_factory(config: Phase3EvaluationConfig, bins: MinuteBins) -> AttackingCandidateFactory:
    """Build the Candidate V3 factory for the V4-vs-V3 diagnostic co-score (NOT a gate)."""
    from fpl.models.attacking_v3 import MinutesGatedCoupledTeamShareAttackingGoalsV3

    policy = config.stage_c_candidate_v3
    xg_covered = frozenset(config.xg_signal_policy.xg_covered_seasons)

    def factory(
        history: Sequence[PlayerHistoryRow],
    ) -> MinutesGatedCoupledTeamShareAttackingGoalsV3:
        model = MinutesGatedCoupledTeamShareAttackingGoalsV3(
            alpha=policy.alpha,
            share_window=policy.history_window,
            xg_covered_seasons=xg_covered,
            bins=bins,
            minutes_gating=True,
        )
        model.fit(history)
        return model

    return factory


# --------------------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------------------


def _format_metric_row(report: AttackingScoreReport) -> str:
    return (
        f"log {report.mean_log_score:.5f} (SE {report.uncertainty:.5f}), "
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
    v3_report: AttackingScoreReport,
    v4_vs_v3_lift: float,
) -> str:
    lines = [_DEVELOPMENT_BANNER, *provenance.as_lines()]
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
            "    " + _format_metric_row(result.overall[candidate]),
            f"  {diagnostics.comparator}",
            "    " + _format_metric_row(result.overall[diagnostics.comparator]),
        ]
    lines += ["", *diagnostics.as_lines()]

    if candidate in result.overall:
        lines += [
            "",
            "V4-vs-V3 diagnostic (DEVELOPMENT DIAGNOSTIC ONLY, NOT a gate):",
            f"  {candidate:<50}{_format_metric_row(result.overall[candidate])}",
            f"  {V3_NAME:<50}{_format_metric_row(v3_report)}",
            f"  -> V4 vs V3 mean-log-score lift {v4_vs_v3_lift:+.4%} "
            f"(V4 {result.overall[candidate].mean_log_score:.5f} vs V3 "
            f"{v3_report.mean_log_score:.5f})",
        ]

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
            covered = season in config.xg_signal_policy.xg_covered_seasons
            tag = "covered  " if covered else "pre-xA/xG"
            lines.append(
                f"  {season} ({tag}) candidate {reports[candidate].mean_log_score:.5f}  "
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
# Reconciliation record
# --------------------------------------------------------------------------------------


def _json_float(value: float) -> float | None:
    return value if math.isfinite(value) else None


def _reliability_record(curve: ReliabilityCurve) -> dict[str, object]:
    return {
        "total_n": curve.total_n(),
        "buckets": [
            {
                "lower": b.lower,
                "upper": b.upper,
                "n": b.n,
                "mean_predicted": (
                    None if b.mean_predicted is None else _json_float(b.mean_predicted)
                ),
                "observed_rate": None if b.observed_rate is None else _json_float(b.observed_rate),
            }
            for b in curve.buckets
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


def _score_map_record(reports: dict[str, AttackingScoreReport]) -> dict[str, dict[str, object]]:
    return {name: _score_record(reports[name]) for name in sorted(reports)}


def _slice_record(
    slices: dict[str, dict[str, AttackingScoreReport]],
) -> dict[str, dict[str, dict[str, object]]]:
    return {key: _score_map_record(slices[key]) for key in sorted(slices)}


def build_reconciliation_record(
    result: AttackingHarnessResult,
    config: Phase3EvaluationConfig,
    phase2: Phase2EvaluationConfig,
    *,
    provenance: Provenance,
    diagnostics: DevelopmentDiagnostics,
    v3_report: AttackingScoreReport,
    v4_vs_v3_lift: float,
    schema: str = "stage_c_candidate_v4_development/v1",
) -> dict[str, object]:
    candidate = provenance.candidate
    return {
        "schema": schema,
        "status": "development_only_not_a_promotion_result",
        "provenance": {
            "candidate": candidate,
            "contract_version": provenance.contract_version,
            "commit_sha": provenance.commit_sha,
            "config_sha256": provenance.config_fingerprint,
            "phase2_minutes_contract_sha256": provenance.phase2_config_fingerprint,
            "candidate_source_sha256": provenance.candidate_source_fingerprint,
            "exposure_source_sha256": provenance.exposure_source_fingerprint,
            "v3_comparator_source_sha256": provenance.v3_source_fingerprint,
            "database_sha256": provenance.archive_fingerprint,
            "seed": provenance.seed,
            "started_at_utc": provenance.started_at,
            "ended_at_utc": provenance.ended_at,
        },
        "contract": {
            "phase": config.phase,
            "candidate": candidate,
            "grain": config.target.grain,
            "identity_policy": config.target.identity_policy,
            "required_baselines": list(result.baseline_names),
            "best_required_baseline": diagnostics.comparator,
            "xg_covered_seasons": list(config.xg_signal_policy.xg_covered_seasons),
            "minutes_baseline": config.stage_c_candidate_v4.minutes_baseline,
            "prior_minutes": config.stage_c_candidate_v4.prior_minutes,
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
                {"name": c.name, "passed": c.passed, "detail": c.detail, "label": c.label}
                for c in diagnostics.checks
            ],
            "note": diagnostics.note,
            "combined_promotion_verdict": None,
        },
        "v4_vs_v3_diagnostic": {
            "label": _DEVELOPMENT_DIAGNOSTIC_LABEL,
            "v3_candidate": V3_NAME,
            "v3_overall": _score_record(v3_report),
            "v4_overall": _score_record(result.overall[candidate]),
            "v4_vs_v3_mean_log_score_lift": _json_float(v4_vs_v3_lift),
            "note": (
                "V3 re-scored live on the same archive, folds, eligible rows, and gate; NOT a gate."
            ),
        },
        "covered_season_judging": {
            "xg_covered_seasons": list(config.xg_signal_policy.xg_covered_seasons),
            "full_population_reported_separately": (
                "every eligible row (incl. 2021-22 / partial 2022-23) is scored; the verdict uses "
                "only the covered-season subset, reported separately"
            ),
        },
        "historical_proxy_caveats": {
            "target_roster": config.target_roster.historical_roster_status,
            "cutoff": config.cutoff.prediction_time,
            "stage_b_minutes_input": "development_proxy_frozen_baseline_on_unversioned_archive",
            "phase2_minutes_contract_version": phase2.contract_version,
            "real_deadline_knowledge_time_validity": "unproven",
            "archive_result_role": "development_diagnostic_only",
            "composer_integration": "none_in_this_slice_component_level_goals_only",
        },
    }


def format_reconciliation_record(record: dict[str, object]) -> str:
    return json.dumps(record, indent=2, sort_keys=True, allow_nan=False)


def _standard_report(result: AttackingHarnessResult, v3_report: AttackingScoreReport) -> str:
    lines = [
        "=== Stage C Attacking Goals Candidate V4 Development Walk-Forward ===",
        f"folds evaluated : {sum(result.folds_by_season.values())}",
        f"predictions     : {result.total_predictions}",
        f"leakage failures: {result.leakage_failures}",
        f"best baseline   : {result.best_baseline_name}",
        "",
        f"{'model':<50}{'log':>9}{'RPS':>9}{'Brier>=1':>9}{'PIT80err':>9}",
        "-" * 86,
    ]
    merged: dict[str, AttackingScoreReport] = dict(result.overall)
    merged[V3_NAME] = v3_report
    ordered = sorted(merged.items(), key=lambda item: item[1].mean_log_score)
    for name, rep in ordered:
        lines.append(
            f"{name:<50}{rep.mean_log_score:>9.5f}"
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
            "Run Stage C Candidate V4 as a DEVELOPMENT-ONLY evaluation. Not a promotion evaluation."
        )
    )
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--season", action="append", dest="seasons", default=None)
    parser.add_argument("--save-json", type=Path, default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    repo = repo_root()
    config_path = config_dir() / "phase3_evaluation.yaml"
    phase2_config_path = config_dir() / _PHASE2_CONTRACT
    contract, config_fp = load_contract_from_bytes(config_path)
    require_clean_worktree(repo)

    # Parse the Phase 2 contract from its exact bytes ONCE: the object MinuteBins is built from and
    # the recorded fingerprint come from the same read (no second cached load_phase2_evaluation()).
    phase2, phase2_fp = load_phase2_from_bytes(phase2_config_path)
    bins = MinuteBins.from_config(phase2)

    db_path = args.db or default_db_path()
    cand_source = repo / _CANDIDATE_SOURCE_REL
    exposure_source = repo / _EXPOSURE_SOURCE_REL
    v3_source = repo / _V3_SOURCE_REL
    snapshot = PreflightSnapshot(
        candidate=contract.stage_c_candidate_v4.name,
        contract_version=contract.contract_version,
        commit_sha=head_commit_sha(repo),
        config_fingerprint=config_fp,
        phase2_config_fingerprint=phase2_fp,
        candidate_source_fingerprint=file_sha256(cand_source),
        exposure_source_fingerprint=file_sha256(exposure_source),
        v3_source_fingerprint=file_sha256(v3_source),
        archive_fingerprint=file_sha256(db_path),
        seed=contract.training.seed,
        started_at=_utc_now(),
    )

    factory = candidate_factory(contract, bins)
    v3f = v3_factory(contract, bins)
    con = connect(db_path, read_only=True)
    try:
        result = run_attacking_harness(
            con, config=contract, seasons=args.seasons, candidate_factory=factory
        )
        result_v3 = run_attacking_harness(
            con, config=contract, seasons=args.seasons, candidate_factory=v3f
        )
    finally:
        con.close()

    diagnostics = compute_development_diagnostics(result, snapshot.candidate, contract)
    v3_report = result_v3.overall[V3_NAME]
    v4_log = result.overall[snapshot.candidate].mean_log_score
    v4_vs_v3_lift = relative_lift(v3_report.mean_log_score, v4_log)
    ended_at = _utc_now()

    try:
        verify_snapshot(
            snapshot,
            db_path=db_path,
            repo=repo,
            config_path=config_path,
            phase2_config_path=phase2_config_path,
            candidate_source_path=cand_source,
            exposure_source_path=exposure_source,
            v3_source_path=v3_source,
        )
    except ProvenanceError as exc:
        sys.stderr.write(
            f"Candidate V4 result is INVALID / UNPUBLISHABLE and will not be printed: {exc}\n"
        )
        return 1

    provenance = finalize_provenance(snapshot, ended_at=ended_at)
    reconciliation = build_reconciliation_record(
        result,
        contract,
        phase2,
        provenance=provenance,
        diagnostics=diagnostics,
        v3_report=v3_report,
        v4_vs_v3_lift=v4_vs_v3_lift,
    )
    print(_standard_report(result, v3_report))
    print(
        format_development_report(
            result,
            snapshot.candidate,
            contract,
            provenance=provenance,
            diagnostics=diagnostics,
            v3_report=v3_report,
            v4_vs_v3_lift=v4_vs_v3_lift,
        )
    )
    reconciliation_report = format_reconciliation_record(reconciliation)
    print("BEGIN_STAGE_C_CANDIDATE_V4_RECONCILIATION_JSON")
    print(reconciliation_report)
    print("END_STAGE_C_CANDIDATE_V4_RECONCILIATION_JSON")

    if args.save_json:
        args.save_json.parent.mkdir(parents=True, exist_ok=True)
        args.save_json.write_text(reconciliation_report, encoding="utf-8")
        logger.info(f"Saved verbatim reconciliation JSON to {args.save_json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
