"""Development-only runner for Candidate V3. This is NOT a promotion evaluation.

    python -m fpl.validate.dev_candidate_v3                 # full archive, development only
    python -m fpl.validate.dev_candidate_v3 --season 2025-26

Candidate V3 (`dynamic_team_goals_v3`) is a structural probe pre-registered for one
historical *development* evaluation. It reuses the Stage A harness unchanged -- the same
observed-gameweek folds, the same required baselines on the same eligible rows, the same
proper-distribution metrics, slices, counts, and fold-local parameters -- but it prints a
**DEVELOPMENT ONLY** report and **never** a promotion verdict. The default harness command
(`python -m fpl.validate.harness`) is untouched and still evaluates Candidate V2.

Why the separation is structural, not cosmetic: V3 is not a promotion candidate. The
historical archive (2021-22 through 2025-26) is development evidence -- it has already
shaped V1, V2, and now V3 -- so a good historical number is necessary but not sufficient.
Prospective 2026/27 data is reserved as the untouched confirmation set and is not consumed
here. A genuine promotion attempt would be a separately pre-registered candidate evaluated
against prospective data under the unchanged promotion gate.
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

from fpl.config import Phase1EvaluationConfig, load_phase1_evaluation
from fpl.storage.db import connect
from fpl.validate.harness import HarnessResult, format_report, run
from fpl.validate.metrics import relative_lift

logger = logging.getLogger("fpl.validate.dev_candidate_v3")

_DEVELOPMENT_BANNER = (
    "\n"
    "============================================================================\n"
    " DEVELOPMENT ONLY -- NOT A PROMOTION RESULT\n"
    " Candidate V3 (dynamic_team_goals_v3) is a structural development probe.\n"
    " The historical archive is development evidence, not a fresh holdout.\n"
    " Prospective 2026/27 is the untouched confirmation set and is not consumed.\n"
    " No number below is a promotion verdict; V3 is judged by no promotion gate.\n"
    "============================================================================\n"
)


def _commit_sha() -> str:
    """The commit this evaluation runs under, so the report names the exact frozen code.

    Commit 1 freezes the design, config, implementation, and tests before this runs, so
    HEAD is that pre-registration. Falling back to 'unknown' keeps the runner usable from
    a dirty tree rather than crashing.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[3],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return "unknown (not a clean git checkout)"


def format_development_report(
    result: HarnessResult,
    candidate: str,
    config: Phase1EvaluationConfig,
    *,
    commit_sha: str,
) -> str:
    """The DEVELOPMENT ONLY comparison block, printed after the standard score report.

    The standard `format_report` already lists every model's metrics, the season /
    promoted-status / home-away slices, and the fold-local parameter selections. This adds
    the signed lift of V3 against the best required baseline (overall and per season) and
    the framing that makes a development number impossible to read as a promotion verdict.
    """
    if candidate not in result.overall:
        return f"\n{candidate} did not produce predictions; no development comparison.\n"

    policy = config.stage_a_candidate_v3
    name = policy.name if policy is not None else candidate
    comparator = result.best_baseline()
    baseline = result.overall[comparator]
    scored = result.overall[candidate]

    log_lift = relative_lift(baseline.mean_log_score, scored.mean_log_score)
    crps_change = relative_lift(baseline.mean_crps, scored.mean_crps)

    lines = [_DEVELOPMENT_BANNER]
    lines += [
        f"model                  : {name} (development-only)",
        f"config identity        : stage_a_candidate_v3, contract v{config.contract_version}",
        f"evaluated under commit : {commit_sha}",
        "primary metric         : mean log score (lower is better); CRPS is the guardrail",
        "",
        "comparison against the best required baseline (development diagnostics, NOT a gate):",
        f"  comparator baseline  : {comparator}",
        f"  mean log score       : {scored.mean_log_score:.4f} vs {baseline.mean_log_score:.4f} "
        f"-> lift {log_lift:+.4%}",
        f"  mean log-score SE    : {scored.mean_log_score_standard_error:.4f} "
        f"vs {baseline.mean_log_score_standard_error:.4f}",
        f"  mean CRPS            : {scored.mean_crps:.4f} vs {baseline.mean_crps:.4f} "
        f"-> change {crps_change:+.4%}",
        f"  PIT 80% coverage     : {scored.pit_interval_80_coverage:.3f} ",
        f"  raw 80% coverage     : {scored.interval_80_coverage:.3f} "
        f"(PIT error {scored.pit_interval_80_absolute_error:.3f})",
        f"  cold starts          : {scored.cold_starts} of {scored.predictions} predictions",
        "",
    ]

    lines.append("per-season mean log score (development diagnostics, NOT a gate):")
    seasons = sorted(result.by_season)
    for season in seasons:
        reports = result.by_season[season]
        if candidate in reports and comparator in reports:
            season_lift = relative_lift(
                reports[comparator].mean_log_score, reports[candidate].mean_log_score
            )
            lines.append(
                f"  {season}  candidate {reports[candidate].mean_log_score:.4f}  "
                f"baseline {reports[comparator].mean_log_score:.4f}  -> lift {season_lift:+.4%}"
            )

    # Boundary selections are diagnostics: which grid corners and the fallback were chosen.
    parameter_values: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    for models in result.parameters_by_fold.values():
        for model, parameters in models.items():
            if model != candidate:
                continue
            for key, value in parameters.items():
                parameter_values[model][key][str(value)] += 1
    if parameter_values.get(candidate):
        lines += ["", "Candidate V3 fold-local parameter selections:"]
        for key in sorted(parameter_values[candidate]):
            counts = ", ".join(
                f"{value}={count}"
                for value, count in sorted(parameter_values[candidate][key].items())
            )
            lines.append(f"  {key}: {counts}")

    fallback_count = sum(
        1
        for models in result.parameters_by_fold.values()
        if models.get(candidate, {}).get("used_inner_holdout") in (False, "False")
    )
    lines += [
        "",
        f"folds using the inner-holdout fallback: {fallback_count} of {result.folds_evaluated}",
        "(fallback folds had insufficient inner history; recorded as a diagnostic)",
        "",
        "caveat: the archive cutoff is the first kickoff of each predicted gameweek, the",
        "latest proxy that excludes every outcome in it -- not an authoritative deadline.",
        "",
        "Reminder: this is a DEVELOPMENT result. Do not promote from it. The trailing-goals",
        "baseline remains the Stage A model until a separately pre-registered candidate clears",
        "the unchanged promotion gate against prospective data.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run Candidate V3 as a DEVELOPMENT-ONLY evaluation. Not a promotion evaluation."
        )
    )
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--season", action="append", dest="seasons", default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    contract = load_phase1_evaluation()
    if contract.stage_a_candidate_v3 is None:
        raise SystemExit(
            "Candidate V3 is not configured (stage_a_candidate_v3 is absent). Nothing to run."
        )

    # Imported here, as the harness imports Candidate V2: the harness must not depend on any
    # particular candidate existing, and this runner must not load V3 into the default path.
    from fpl.models.dynamic_team_goals import DynamicTeamGoalsV3

    candidate = DynamicTeamGoalsV3(
        contract.stage_a_candidate_v3,
        minimum_team_matches=contract.training.minimum_team_matches,
    )

    con = connect(args.db, read_only=True)
    try:
        result = run(con, config=contract, seasons=args.seasons, candidates=[candidate])
    finally:
        con.close()

    print(format_report(result))
    print(format_development_report(result, candidate.name, contract, commit_sha=_commit_sha()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
