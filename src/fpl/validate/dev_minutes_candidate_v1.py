"""Development-only runner for Stage B Candidate V1. This is NOT a promotion evaluation.

    python -m fpl.validate.dev_minutes_candidate_v1            # full archive, development only
    python -m fpl.validate.dev_minutes_candidate_v1 --season 2025-26

Candidate V1 (``shrunk_trailing_5_player_minutes_v1``) is a closed-form shrinkage estimator. This
runner reuses the Stage B harness unchanged -- the same observed-gameweek folds, the same four
frozen baselines on the same eligible rows, the same proper-distribution metrics, slices, and
counts -- but fits Candidate V1 alongside those baselines on the *identical* eligible rows, scores
it under the unchanged contract, and prints a **DEVELOPMENT ONLY** report that **never** emits a
promotion verdict. The default harness command (``python -m fpl.validate.minutes_harness``) is
untouched and still supplies no candidate factory.

This runner is pre-registered before any V1 evaluation. Provenance closes every time-of-check /
time-of-use gap the Stage A invalidations exposed:

  * It refuses to start when the Git worktree is dirty, so the recorded SHA names the code that was
    actually scored.
  * The contract is loaded from one snapshotted read of the config bytes, and the recorded config
    fingerprint is the hash of exactly those bytes.
  * It records the Candidate V1 model-source fingerprint, so an edit to ``minutes_v1.py`` between
    capture and print is detected.
  * It records the exact clean commit SHA, the config fingerprint, the candidate-source
    fingerprint, the archive fingerprint, the fixed seed, and UTC start/end timestamps.
  * After the database is closed, it captures ``ended_at`` and re-checks the worktree, HEAD, config
    fingerprint, candidate-source fingerprint, and database fingerprint against the preflight
    snapshot. If anything moved during the run the result is suppressed as INVALID/UNPUBLISHABLE,
    and the printable provenance is constructed only after that recheck passes.

The frozen promotion gate is evaluated as **structured development diagnostics only** -- each
condition is reported as its own labelled check and is never combined into a production promotion
verdict. This module is committed before any V1 result exists; running the full evaluation is out
of scope for the pre-registration slice and is not invoked here.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
import yaml

from fpl.config import Phase2EvaluationConfig, config_dir, repo_root
from fpl.storage.db import connect, default_db_path
from fpl.validate.metrics import relative_lift
from fpl.validate.minutes_baselines import HistoryRow, TargetRow
from fpl.validate.minutes_harness import (
    MinutesCandidateFactory,
    MinutesHarnessResult,
    format_minutes_report,
    run_minutes_harness,
)
from fpl.validate.minutes_metrics import MinutesDistribution, MinutesScoreReport

if TYPE_CHECKING:
    from fpl.models.minutes_v1 import ShrunkTrailing5PlayerMinutesV1

logger = logging.getLogger("fpl.validate.dev_minutes_candidate_v1")

_DEVELOPMENT_BANNER = (
    "\n"
    "============================================================================\n"
    " DEVELOPMENT ONLY -- NOT A PROMOTION RESULT\n"
    " Candidate V1 (shrunk_trailing_5_player_minutes_v1). The historical archive is\n"
    " development evidence (an unversioned target-roster / first-kickoff proxy), not a\n"
    " fresh holdout. Prospective 2026/27 is the untouched confirmation set, not consumed.\n"
    " No number below is a promotion verdict; V1 is judged by no promotion gate.\n"
    "============================================================================\n"
)

# Every diagnostic check is labelled so it cannot be read as a promotion verdict.
_DEVELOPMENT_DIAGNOSTIC_LABEL = "DEVELOPMENT DIAGNOSTIC ONLY"

# The Candidate V1 model source this runner scores. Fingerprinted so a mid-run edit is detected.
_CANDIDATE_SOURCE_REL = Path("src") / "fpl" / "models" / "minutes_v1.py"


def _utc_now() -> str:
    """A timezone-aware UTC timestamp as a fixed ``YYYY-MM-DDTHH:MM:SSZ`` string."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------------------
# Git / file fingerprinting
# --------------------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    """One git invocation in ``repo``; stdout stripped. Raises if git fails."""
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def worktree_is_clean(repo: Path) -> bool:
    """True iff ``git status --porcelain`` is empty in ``repo``."""
    return _git(repo, "status", "--porcelain") == ""


def require_clean_worktree(repo: Path) -> None:
    """Refuse to score unless the worktree is clean.

    Recording a clean HEAD SHA over a modified tree would name the wrong code, so a dirty
    worktree is a hard stop with an explicit diagnostic rather than a warning.
    """
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
    """Stable SHA-256 of a file's bytes, streamed so the database hash is not loaded whole."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_bytes(data: bytes) -> str:
    """SHA-256 of an in-memory byte string (the config bytes already read for loading)."""
    return hashlib.sha256(data).hexdigest()


def candidate_source_path(repo: Path) -> Path:
    """The Candidate V1 model source path whose fingerprint the runner records."""
    return repo / _CANDIDATE_SOURCE_REL


def load_contract_from_bytes(config_path: Path) -> tuple[Phase2EvaluationConfig, str]:
    """Read the contract bytes once and load the typed contract from those exact bytes.

    Returns the loaded contract and the SHA-256 of the bytes it was parsed from. Fingerprinting
    the same bytes that were parsed closes the load-then-hash window in which the file could change
    between parsing and fingerprinting, so the recorded config fingerprint names exactly the
    contract that was scored.
    """
    raw = config_path.read_bytes()
    loaded = yaml.safe_load(raw)
    if not isinstance(loaded, dict):
        raise ValueError(f"{config_path} did not parse to a mapping")
    return Phase2EvaluationConfig.model_validate(loaded), hash_bytes(raw)


# --------------------------------------------------------------------------------------
# Provenance lifecycle: preflight snapshot -> verify -> finalize
# --------------------------------------------------------------------------------------


class ProvenanceError(RuntimeError):
    """The (code, config, candidate-source, data) quadruple changed between capture and print."""


@dataclass(frozen=True, slots=True)
class PreflightSnapshot:
    """The frozen triple captured BEFORE the evaluation runs (no ``ended_at``).

    ``commit_sha`` is only meaningful because the runner refused to start on a dirty worktree. The
    config and candidate-source fingerprints are the hashes of the exact bytes parsed / scored.
    """

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
    """The finalized, printable provenance, constructed only after the postflight recheck passes."""

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
    config: Phase2EvaluationConfig,
    *,
    repo: Path,
    config_path: Path,
    config_fp: str | None = None,
    candidate_source_path: Path,
    candidate_source_fp: str | None = None,
) -> PreflightSnapshot:
    """Capture every fingerprint, HEAD, seed, and ``started_at`` BEFORE the evaluation runs.

    ``config_fp`` / ``candidate_source_fp`` let the caller pass an already-computed hash of the
    exact bytes parsed / scored (the runner passes the config hash from
    :func:`load_contract_from_bytes`); when omitted they are recomputed from the path.
    """
    return PreflightSnapshot(
        candidate=config.stage_b_candidate_v1.name,
        contract_version=config.contract_version,
        commit_sha=head_commit_sha(repo),
        config_fingerprint=config_fp if config_fp is not None else file_sha256(config_path),
        candidate_source_fingerprint=(
            candidate_source_fp
            if candidate_source_fp is not None
            else file_sha256(candidate_source_path)
        ),
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
    """Re-check that (code, config, candidate-source, data) still match the preflight snapshot.

    Called after the database connection is closed and before any result is printed. If anything
    moved during the run the captured snapshot is no longer truthful, so this raises
    :class:`ProvenanceError` and the caller suppresses the result rather than printing numbers under
    a stale quadruple.
    """
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
    """Construct the printable provenance from the verified snapshot and the post-run ``ended_at``.

    Called only after :func:`verify_snapshot` has passed, so every fingerprint still describes what
    was scored.
    """
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
    """Open the archive read-only; the runner never writes to the scored database."""
    return connect(db_path, read_only=True)


# --------------------------------------------------------------------------------------
# Candidate V1 adapter: a fold-local factory conforming to the harness protocol
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class _FittedCandidate:
    """Adapts Candidate V1's overloaded predict surface to the harness's uniform candidate shape.

    Wrapping the fitted model here keeps the harness model-agnostic (it only knows the
    :class:`~fpl.validate.minutes_harness.MinutesCandidate` protocol) and gives a single-target
    ``predict`` returning one four-bin distribution.
    """

    name: str
    _model: ShrunkTrailing5PlayerMinutesV1

    def predict(self, target: TargetRow) -> MinutesDistribution:
        return self._model.predict(target)

    def parameters(self) -> dict[str, float | int | bool | str]:
        return self._model.parameters()


def candidate_factory(config: Phase2EvaluationConfig) -> MinutesCandidateFactory:
    """Build the fold-local Candidate V1 factory.

    The model is imported here, not at module load, so importing this runner (and the harness's
    default path) never depends on a particular candidate existing.
    """
    from fpl.models.minutes_v1 import ShrunkTrailing5PlayerMinutesV1

    def factory(history: tuple[HistoryRow, ...], as_of: datetime) -> _FittedCandidate:
        model = ShrunkTrailing5PlayerMinutesV1(config=config).fit(history, as_of=as_of)
        return _FittedCandidate(model.name, model)

    return factory


# --------------------------------------------------------------------------------------
# Structured development diagnostics (one labelled check per frozen condition)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DevelopmentCheck:
    """One frozen gate condition evaluated as a development diagnostic, never a verdict."""

    name: str
    passed: bool
    detail: str
    label: str = _DEVELOPMENT_DIAGNOSTIC_LABEL


@dataclass(frozen=True, slots=True)
class DevelopmentDiagnostics:
    """The structured record of every unchanged gate condition for one development run.

    Each check carries the ``DEVELOPMENT DIAGNOSTIC ONLY`` label and is reported independently; the
    record is explicitly NOT combined into a production promotion verdict. ``comparable`` is False
    only if the candidate produced no overall predictions to compare.
    """

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


def _no_regression_check(
    name: str, baseline_metric: float, candidate_metric: float, *, allowed_regression: float
) -> DevelopmentCheck:
    """A lower-is-better non-regression check (RPS / Brier): the candidate must not regress.

    ``relative_lift`` is positive when the candidate improved; regression is the clamped negative
    lift. The check passes when the regression is within the gate's allowed amount.
    """
    lift = relative_lift(baseline_metric, candidate_metric)
    regression = max(0.0, -lift)
    passed = regression <= allowed_regression
    detail = (
        f"lift {lift:+.4%} (regression {regression:.4%}); allowed regression "
        f"<= {allowed_regression:.2%}; candidate {candidate_metric:.5f} vs baseline "
        f"{baseline_metric:.5f}"
    )
    return DevelopmentCheck(name=name, passed=passed, detail=detail)


def compute_development_diagnostics(
    result: MinutesHarnessResult, candidate: str, config: Phase2EvaluationConfig
) -> DevelopmentDiagnostics:
    """Evaluate every frozen gate condition as an independent development diagnostic.

    Thresholds are read from the unchanged ``config.promotion`` block (never hardcoded). No check is
    combined into a verdict: the function returns the structured record and the caller renders it.
    """
    comparator = result.best_baseline()
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
                f"lift {log_lift:+.4%} (candidate {cand.mean_log_score:.5f} vs baseline "
                f"{base.mean_log_score:.5f}); required >= {gate.minimum_primary_relative_lift:.2%}"
            ),
        ),
        _no_regression_check(
            "no_aggregate_ranked_probability_score_regression",
            base.mean_ranked_probability_score,
            cand.mean_ranked_probability_score,
            allowed_regression=gate.maximum_ranked_probability_score_relative_regression,
        ),
        _no_regression_check(
            "no_aggregate_brier_any_minutes_regression",
            base.mean_brier_any_minutes,
            cand.mean_brier_any_minutes,
            allowed_regression=gate.maximum_brier_relative_regression_any_minutes,
        ),
        _no_regression_check(
            "no_aggregate_brier_60_plus_regression",
            base.mean_brier_60_plus,
            cand.mean_brier_60_plus,
            allowed_regression=gate.maximum_brier_relative_regression_60_plus,
        ),
        DevelopmentCheck(
            name="pit_interval_80_absolute_error_at_most_maximum",
            passed=(
                cand.pit_interval_80_absolute_error <= gate.pit_interval_80_maximum_absolute_error
            ),
            detail=(
                f"PIT-80 absolute error {cand.pit_interval_80_absolute_error:.4f}; allowed <= "
                f"{gate.pit_interval_80_maximum_absolute_error:.2f}"
            ),
        ),
        DevelopmentCheck(
            name="prediction_coverage_at_least_minimum",
            passed=cand.prediction_coverage >= gate.minimum_prediction_coverage,
            detail=(
                f"coverage {cand.prediction_coverage:.4f}; required >= "
                f"{gate.minimum_prediction_coverage:.2f}"
            ),
        ),
        DevelopmentCheck(
            name="folds_evaluated_at_least_minimum",
            passed=result.folds_evaluated >= gate.minimum_fold_count,
            detail=(
                f"{result.folds_evaluated} folds evaluated; required >= {gate.minimum_fold_count}"
            ),
        ),
        DevelopmentCheck(
            name="zero_leakage_failures",
            passed=result.leakage_failures == 0 and gate.require_zero_leakage_failures,
            detail=f"{result.leakage_failures} leakage failures; required 0",
        ),
    ]

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


def _parameter_selections(
    result: MinutesHarnessResult, candidate: str
) -> dict[str, dict[str, int]]:
    """Aggregate a candidate's fold-local scalar parameters into selection counts."""
    counts: dict[str, dict[str, int]] = {}
    for models in result.parameters_by_fold.values():
        parameters = models.get(candidate)
        if not parameters:
            continue
        for key, value in parameters.items():
            selections = counts.setdefault(key, {})
            selections[str(value)] = selections.get(str(value), 0) + 1
    return counts


def _format_metric_row(report: MinutesScoreReport) -> str:
    return (
        f"    log {report.mean_log_score:.5f} (SE {report.mean_log_score_standard_error:.5f}), "
        f"RPS {report.mean_ranked_probability_score:.5f}, "
        f"Brier-any {report.mean_brier_any_minutes:.5f}, "
        f"Brier-60+ {report.mean_brier_60_plus:.5f}, PIT-80 {report.pit_interval_80_coverage:.3f}, "
        f"coverage {report.prediction_coverage:.4f}, cold {report.cold_starts}/{report.predictions}"
    )


def format_development_report(
    result: MinutesHarnessResult,
    candidate: str,
    config: Phase2EvaluationConfig,
    *,
    provenance: Provenance,
    diagnostics: DevelopmentDiagnostics,
) -> str:
    """The DEVELOPMENT ONLY comparison block, printed after the standard score report."""
    lines = [_DEVELOPMENT_BANNER]
    lines += provenance.as_lines()
    lines += [
        "",
        f"model                  : {config.stage_b_candidate_v1.name} (development-only)",
        "primary metric         : mean log score (lower is better); RPS/Brier are guardrails",
        "comparator baseline    : "
        f"{diagnostics.comparator} (best required baseline by mean log score)",
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

    selections = _parameter_selections(result, candidate)
    if selections:
        lines += ["", "Candidate V1 fold-local parameter selections:"]
        for key in sorted(selections):
            counts = ", ".join(
                f"{value}={count}" for value, count in sorted(selections[key].items())
            )
            lines.append(f"  {key}: {counts}")

    lines += [
        "",
        "Reminder: this is a DEVELOPMENT result. Do not promote from it. The best required Stage B",
        "baseline remains the Stage B model until a separately pre-registered candidate clears the",
        "unchanged promotion gate against prospective data.",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run Stage B Candidate V1 as a DEVELOPMENT-ONLY evaluation. Not a promotion evaluation."
        )
    )
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--season", action="append", dest="seasons", default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    repo = repo_root()
    config_path = config_dir() / "phase2_evaluation.yaml"
    # Load the contract from one snapshotted read of the config bytes, and fingerprint exactly
    # those bytes, so the recorded provenance names the contract that was actually scored.
    contract, config_fp = load_contract_from_bytes(config_path)
    # Refuse to score a dirty worktree so the provenance is truthful.
    require_clean_worktree(repo)

    db_path = args.db or default_db_path()
    cand_source = candidate_source_path(repo)
    # Every fingerprint, HEAD, seed, and started_at are captured BEFORE the evaluation runs.
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
        result = run_minutes_harness(
            con, config=contract, seasons=args.seasons, candidate_factory=factory
        )
    finally:
        # The database is closed before postflight verification reads its fingerprint again.
        con.close()

    diagnostics = compute_development_diagnostics(result, snapshot.candidate, contract)
    ended_at = _utc_now()

    # Postflight verification against the original preflight fingerprints. A mid-run change makes
    # the captured snapshot a lie, so the result is suppressed as INVALID/UNPUBLISHABLE rather than
    # printed under a quadruple that no longer holds.
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

    # The printable provenance is constructed only after the recheck passes.
    provenance = finalize_provenance(snapshot, ended_at=ended_at)
    print(format_minutes_report(result, config=contract))
    print(
        format_development_report(
            result, snapshot.candidate, contract, provenance=provenance, diagnostics=diagnostics
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
