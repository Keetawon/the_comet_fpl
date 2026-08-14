"""Thin CLI for the DEV-ROADMAP P0.3 default-versus-diagnostic decision comparison.

It reads two frozen prospective forecasts and their two optimizer plans, derives the comparison, and
prints the Markdown decision aid to stdout. ``--output PATH`` additionally writes the immutable,
identity-bearing JSON artifact, and ``--report PATH`` writes the rendered Markdown; both refuse to
overwrite an existing file.

No database is touched and nothing is re-solved or re-forecast: the ledger run id is re-derived from
each forecast's own manifest and canonical bytes, exactly as ``fpl.jobs.record_forecast`` does. All
schema, derivation, identity, and atomic-write logic lives in
:mod:`fpl.artifacts.decision_comparison`; this entry point only resolves paths and reports.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from pathlib import Path

from fpl.artifacts.decision_comparison import (
    DecisionComparisonError,
    build_decision_comparison,
    read_decision_comparison,
    render_decision_comparison,
    write_decision_comparison_atomic,
)
from fpl.artifacts.optimizer_plan import OptimizerArtifactError, read_optimizer_artifact
from fpl.artifacts.prospective_points import ArtifactError, read_artifact

logger = logging.getLogger("fpl.jobs.compare_decisions")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare the DEVELOPMENT-ONLY default and diagnostic GW decisions. A decision aid, "
            "not a promotion test."
        )
    )
    parser.add_argument("--default-forecast", type=Path, required=True)
    parser.add_argument("--default-plan", type=Path, required=True)
    parser.add_argument("--diagnostic-forecast", type=Path, required=True)
    parser.add_argument("--diagnostic-plan", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="atomically write the immutable comparison JSON artifact to this path",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="also write the rendered Markdown decision aid to this path",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    for destination in (args.output, args.report):
        if destination is not None and destination.exists():
            logger.error("refusing to overwrite an existing immutable output at %s", destination)
            return 1

    try:
        default_forecast = read_artifact(args.default_forecast)
        diagnostic_forecast = read_artifact(args.diagnostic_forecast)
        default_plan = read_optimizer_artifact(args.default_plan)
        diagnostic_plan = read_optimizer_artifact(args.diagnostic_plan)
        comparison = build_decision_comparison(
            default_forecast=default_forecast,
            default_plan=default_plan,
            default_forecast_path=str(args.default_forecast),
            default_plan_sha256=_sha256(args.default_plan),
            diagnostic_forecast=diagnostic_forecast,
            diagnostic_plan=diagnostic_plan,
            diagnostic_forecast_path=str(args.diagnostic_forecast),
            diagnostic_plan_sha256=_sha256(args.diagnostic_plan),
        )
    except (OSError, ArtifactError, OptimizerArtifactError, ValueError) as exc:
        # ValueError covers DecisionComparisonError and any Pydantic ValidationError raised while
        # assembling the comparison: an operator gets a message and a non-zero exit, never a
        # traceback, and nothing is written.
        logger.error("%s", exc)
        return 1

    report = render_decision_comparison(comparison)

    if args.output is not None:
        try:
            digest = write_decision_comparison_atomic(args.output, comparison)
        except (OSError, DecisionComparisonError) as exc:
            logger.error("%s", exc)
            return 1
        read_decision_comparison(args.output)
        logger.info(
            "wrote decision comparison comparison_id=%s to %s (sha256=%s)",
            comparison.comparison_id,
            args.output,
            digest,
        )
    if args.report is not None:
        try:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            with args.report.open("x", encoding="utf-8") as handle:
                handle.write(report)
        except OSError as exc:
            logger.error("%s", exc)
            return 1
        logger.info("wrote decision report to %s", args.report)

    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
