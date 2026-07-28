"""Development-only runner for Candidate V4. This is NOT a promotion evaluation.

    python -m fpl.validate.dev_candidate_v4                 # full archive, development only
    python -m fpl.validate.dev_candidate_v4 --season 2025-26

Candidate V4 (`dynamic_team_goals_v4`) is the leakage-safe structural successor to the
invalidated V3. It reuses the Stage A harness unchanged -- the same observed-gameweek folds,
the same required baselines on the same eligible rows, the same proper-distribution metrics,
slices, counts, and fold-local parameters -- but it prints a **DEVELOPMENT ONLY** report and
**never** a promotion verdict. The default harness command (`python -m fpl.validate.harness`)
is untouched and still evaluates Candidate V2.

This runner is pre-registered before any V4 evaluation. Two provenance guarantees are built in
and fix V3's defect 4:

  * It refuses to start when the Git worktree is dirty, so the recorded SHA names the code
    that was actually scored rather than a clean HEAD over uncommitted changes.
  * It records the exact clean commit SHA, the config fingerprint, the archive/input
    fingerprint, the fixed seed, and a capture timestamp, so a V4 number can be tied back to a
    single frozen (code, config, data) triple.

This module is committed before any V4 result exists; running the full evaluation is out of
scope for the pre-registration change and is not invoked here.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fpl.config import (
    Phase1EvaluationConfig,
    config_dir,
    load_phase1_evaluation,
    repo_root,
)
from fpl.storage.db import connect, default_db_path
from fpl.validate.harness import HarnessResult, format_report, run
from fpl.validate.metrics import relative_lift

logger = logging.getLogger("fpl.validate.dev_candidate_v4")

_DEVELOPMENT_BANNER = (
    "\n"
    "============================================================================\n"
    " DEVELOPMENT ONLY -- NOT A PROMOTION RESULT\n"
    " Candidate V4 (dynamic_team_goals_v4) is the leakage-safe successor to the\n"
    " invalidated V3. The historical archive is development evidence, not a fresh\n"
    " holdout. Prospective 2026/27 is the untouched confirmation set, not consumed.\n"
    " No number below is a promotion verdict; V4 is judged by no promotion gate.\n"
    "============================================================================\n"
)


@dataclass(frozen=True)
class Provenance:
    """The (code, config, data) triple a V4 development number was scored under.

    Recorded so a result can be tied back to one frozen state. ``commit_sha`` is only
    meaningful because the runner refused to start on a dirty worktree.
    """

    candidate: str
    contract_version: str
    commit_sha: str
    config_fingerprint: str
    archive_fingerprint: str
    seed: int
    captured_at: str

    def as_lines(self) -> list[str]:
        return [
            "provenance",
            f"  candidate             : {self.candidate}",
            f"  contract version      : {self.contract_version}",
            f"  commit sha            : {self.commit_sha}",
            f"  config fingerprint    : {self.config_fingerprint}",
            f"  archive fingerprint   : {self.archive_fingerprint}",
            f"  seed                  : {self.seed}",
            f"  captured at (UTC)     : {self.captured_at}",
        ]


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
    """Refuse to score unless the worktree is clean (V3 defect 4 fix).

    Recording a clean HEAD SHA over a modified tree would name the wrong code, so a dirty
    worktree is a hard stop with an explicit diagnostic rather than a warning.
    """
    porcelain = _git(repo, "status", "--porcelain")
    if porcelain:
        raise SystemExit(
            "Candidate V4 refuses to run on a dirty worktree. The recorded commit SHA must "
            "name the exact code that was scored, and uncommitted changes would make it a "
            "lie. Commit or stash the following before re-running:\n" + porcelain
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


def config_fingerprint(path: Path | None = None) -> str:
    """SHA-256 of the executable contract the candidate reads."""
    resolved = path or (config_dir() / "phase1_evaluation.yaml")
    return file_sha256(resolved)


def archive_fingerprint(db_path: Path) -> str:
    """SHA-256 of the database file the candidate is scored against (the input fingerprint)."""
    return file_sha256(db_path)


def build_provenance(
    db_path: Path, config: Phase1EvaluationConfig, *, repo: Path | None = None
) -> Provenance:
    """Assemble the provenance record. Assumes the worktree is already clean."""
    resolved_repo = repo or repo_root()
    policy = config.stage_a_candidate_v4
    name = policy.name if policy is not None else "dynamic_team_goals_v4"
    return Provenance(
        candidate=name,
        contract_version=config.contract_version,
        commit_sha=head_commit_sha(resolved_repo),
        config_fingerprint=config_fingerprint(),
        archive_fingerprint=archive_fingerprint(db_path),
        seed=config.training.seed,
        captured_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def format_development_report(
    result: HarnessResult,
    candidate: str,
    config: Phase1EvaluationConfig,
    *,
    provenance: Provenance,
) -> str:
    """The DEVELOPMENT ONLY comparison block, printed after the standard score report."""
    if candidate not in result.overall:
        return f"\n{candidate} did not produce predictions; no development comparison.\n"

    policy = config.stage_a_candidate_v4
    name = policy.name if policy is not None else candidate
    comparator = result.best_baseline()
    baseline = result.overall[comparator]
    scored = result.overall[candidate]

    log_lift = relative_lift(baseline.mean_log_score, scored.mean_log_score)
    crps_change = relative_lift(baseline.mean_crps, scored.mean_crps)

    lines = [_DEVELOPMENT_BANNER]
    lines += provenance.as_lines()
    lines += [
        "",
        f"model                  : {name} (development-only)",
        "primary metric         : mean log score (lower is better); CRPS is the guardrail",
        "",
        "comparison against the best required baseline (development diagnostics, NOT a gate):",
        f"  comparator baseline  : {comparator}",
        f"  mean log score       : {scored.mean_log_score:.4f} vs {baseline.mean_log_score:.4f} "
        f"-> lift {log_lift:+.4%}",
        f"  mean CRPS            : {scored.mean_crps:.4f} vs {baseline.mean_crps:.4f} "
        f"-> change {crps_change:+.4%}",
        f"  cold starts          : {scored.cold_starts} of {scored.predictions} predictions",
        "",
    ]

    lines.append("per-season mean log score (development diagnostics, NOT a gate):")
    for season in sorted(result.by_season):
        reports = result.by_season[season]
        if candidate in reports and comparator in reports:
            season_lift = relative_lift(
                reports[comparator].mean_log_score, reports[candidate].mean_log_score
            )
            lines.append(
                f"  {season}  candidate {reports[candidate].mean_log_score:.4f}  "
                f"baseline {reports[comparator].mean_log_score:.4f}  -> lift {season_lift:+.4%}"
            )

    parameter_values: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    for models in result.parameters_by_fold.values():
        for model, parameters in models.items():
            if model != candidate:
                continue
            for key, value in parameters.items():
                parameter_values[model][key][str(value)] += 1
    if parameter_values.get(candidate):
        lines += ["", "Candidate V4 fold-local parameter selections:"]
        for key in sorted(parameter_values[candidate]):
            counts = ", ".join(
                f"{value}={count}"
                for value, count in sorted(parameter_values[candidate][key].items())
            )
            lines.append(f"  {key}: {counts}")

    lines += [
        "",
        "Reminder: this is a DEVELOPMENT result. Do not promote from it. The trailing-goals",
        "baseline remains the Stage A model until a separately pre-registered candidate clears",
        "the unchanged promotion gate against prospective data.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run Candidate V4 as a DEVELOPMENT-ONLY evaluation. Not a promotion evaluation."
        )
    )
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--season", action="append", dest="seasons", default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    contract = load_phase1_evaluation()
    if contract.stage_a_candidate_v4 is None:
        raise SystemExit(
            "Candidate V4 is not configured (stage_a_candidate_v4 is absent). Nothing to run."
        )

    # V3 defect 4 fix: refuse to score a dirty worktree so the provenance is truthful.
    require_clean_worktree(repo_root())

    db_path = args.db or default_db_path()
    provenance = build_provenance(db_path, contract)

    # Imported here, as the harness imports Candidate V2: the harness must not depend on any
    # particular candidate existing, and this runner must not load V4 into the default path.
    from fpl.models.dynamic_team_goals_v4 import DynamicTeamGoalsV4

    candidate = DynamicTeamGoalsV4(
        contract.stage_a_candidate_v4,
        minimum_team_matches=contract.training.minimum_team_matches,
    )

    con = connect(db_path, read_only=True)
    try:
        result = run(con, config=contract, seasons=args.seasons, candidates=[candidate])
    finally:
        con.close()

    print(format_report(result))
    print(format_development_report(result, candidate.name, contract, provenance=provenance))
    return 0


if __name__ == "__main__":
    sys.exit(main())
