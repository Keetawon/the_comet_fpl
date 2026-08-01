"""Development-only runner for Stage D v2 points composition. This is NOT a promotion evaluation.

    python -m fpl.validate.dev_points_composition_v2          # full archive, development only
    python -m fpl.validate.dev_points_composition_v2 --season 2025-26

Stage D v2 is Stage D v1 plus two additional scoring components: goalkeeper **saves** (derived from
the fixture's expected team-conceded rate, licensed by the league-constant save rate) and a
prospective **defensive-contribution** threshold-hit probability (data exists only for 2025-26). It
composes the fitted Stage A/B/C/D component distributions into a per-player-fixture points
distribution (xP) and scores it against the realised NON-BONUS points. This runner performs the
single authorized clean historical development run: it refuses a dirty worktree, fingerprints the
exact code / config / model sources / database it scored, runs the integrative harness once, then
rechecks nothing moved during the run and (only then) emits a full reconciliation record, writing
the optional ``--save-json`` file AFTER the postflight verification passes.

**Every number it prints is DEVELOPMENT-ONLY and EXPLORATORY -- not a promotion verdict.** There is
no pre-registered Stage D promotion contract; this is an end-to-end "is it any good" reading, under
the same unversioned historical proxies (target roster, first-kickoff cutoff) every stage carries,
and with the documented Stage-D-v2 limitations (component independence / no team-coupling, bonus /
penalties / own goals / cards excluded, defensive contribution prospective-only). See
``docs/phase4-stage-d-points-composition-v2-development.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fpl.config import config_dir, repo_root
from fpl.storage.db import connect, default_db_path
from fpl.validate.metrics import ScoreReport
from fpl.validate.points_harness import (
    DEFAULT_DRAWS,
    NO_XG_SEASON,
    PointsHarnessResult,
    format_points_report,
    run_points_harness,
)

logger = logging.getLogger("fpl.validate.dev_points_composition_v2")

_DEVELOPMENT_BANNER = (
    "\n"
    "============================================================================\n"
    " DEVELOPMENT ONLY -- NOT A PROMOTION RESULT\n"
    " Stage D v2 points composition (v1 + goalkeeper saves + defensive contribution).\n"
    " The historical archive is development evidence (unversioned target-roster /\n"
    " first-kickoff proxies) and every component is itself a development-stage estimator;\n"
    " this is an end-to-end reading, not a fresh holdout and with NO comparator baseline.\n"
    " Stage-D-v2 limitations: components composed independently (no team-coupling / goal\n"
    " conservation), bonus / penalties / own goals / cards excluded from the prediction,\n"
    " defensive contribution PROSPECTIVE-ONLY (data exists only for 2025-26). No number\n"
    " below is a promotion verdict.\n"
    "============================================================================\n"
)

# Files whose bytes define exactly what was scored. Any change between preflight and postflight
# invalidates the run. v2 adds the two new component models.
_SOURCE_RELS = (
    Path("src") / "fpl" / "models" / "points_composition.py",
    Path("src") / "fpl" / "validate" / "points_harness.py",
    Path("src") / "fpl" / "models" / "minutes_v3.py",
    Path("src") / "fpl" / "models" / "attacking_v1.py",
    Path("src") / "fpl" / "models" / "attacking_assists_v1.py",
    Path("src") / "fpl" / "models" / "gk_saves_v1.py",
    Path("src") / "fpl" / "models" / "defensive_contribution_v1.py",
    Path("src") / "fpl" / "validate" / "baselines.py",
)
_CONFIG_RELS = (
    Path("phase2_evaluation.yaml"),
    Path("phase3_evaluation.yaml"),
    Path("phase3_stage_c_assists_evaluation.yaml"),
    Path("scoring_2026_27.yaml"),
)


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def require_clean_worktree(repo: Path) -> None:
    porcelain = _git(repo, "status", "--porcelain")
    if porcelain:
        raise SystemExit(
            "Stage D v2 refuses to run on a dirty worktree. The recorded commit SHA must name the "
            "exact code that was scored, and uncommitted changes would make it a lie. Commit or "
            "stash the following before re-running:\n" + porcelain
        )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprints(repo: Path, rels: tuple[Path, ...], *, base: Path) -> dict[str, str]:
    return {str(rel): file_sha256(base / rel) for rel in rels}


class ProvenanceError(RuntimeError):
    """The (code, config, model-source, database) quadruple changed between capture and print."""


@dataclass(frozen=True, slots=True)
class Provenance:
    commit_sha: str
    source_fingerprints: dict[str, str]
    config_fingerprints: dict[str, str]
    database_sha256: str
    seed: int
    draws: int
    started_at: str
    ended_at: str


def verify_unchanged(
    provenance_started: Provenance,
    *,
    repo: Path,
    db_path: Path,
) -> None:
    porcelain = _git(repo, "status", "--porcelain")
    if porcelain:
        raise ProvenanceError(
            "worktree became dirty during the run; the result is INVALID/UNPUBLISHABLE:\n"
            + porcelain
        )
    if _git(repo, "rev-parse", "HEAD") != provenance_started.commit_sha:
        raise ProvenanceError("HEAD changed during the run; the result is INVALID/UNPUBLISHABLE")
    if _fingerprints(repo, _SOURCE_RELS, base=repo) != provenance_started.source_fingerprints:
        raise ProvenanceError("a model source changed during the run; INVALID/UNPUBLISHABLE")
    if (
        _fingerprints(repo, _CONFIG_RELS, base=config_dir())
        != provenance_started.config_fingerprints
    ):
        raise ProvenanceError("a config fingerprint changed during the run; INVALID/UNPUBLISHABLE")
    if file_sha256(db_path) != provenance_started.database_sha256:
        raise ProvenanceError("database fingerprint changed during the run; INVALID/UNPUBLISHABLE")


def _clean_score_record(report: ScoreReport) -> dict[str, object]:
    return {
        "predictions": report.predictions,
        "eligible_predictions": report.eligible_predictions,
        "exclusions": report.exclusions,
        "cold_starts_stage_a_fallback": report.cold_starts,
        "mean_log_score": report.mean_log_score,
        "mean_log_score_standard_error": report.mean_log_score_standard_error,
        "mean_crps": report.mean_crps,
        "mean_poisson_deviance": report.mean_poisson_deviance,
        "pit_interval_80_coverage": report.pit_interval_80_coverage,
        "pit_interval_80_absolute_error": report.pit_interval_80_absolute_error,
        "mean_absolute_error": report.mean_absolute_error,
    }


def build_reconciliation_record(
    result: PointsHarnessResult, *, provenance: Provenance
) -> dict[str, object]:
    return {
        "schema": "stage_d_points_composition_v2_development/v1",
        "status": "development_only_exploratory_not_a_promotion_result",
        "provenance": {
            "commit_sha": provenance.commit_sha,
            "source_sha256": provenance.source_fingerprints,
            "config_sha256": provenance.config_fingerprints,
            "database_sha256": provenance.database_sha256,
            "seed": provenance.seed,
            "monte_carlo_draws": provenance.draws,
            "started_at_utc": provenance.started_at,
            "ended_at_utc": provenance.ended_at,
        },
        "model": result.model_name,
        "components": result.component_names,
        "harness": {
            "folds_evaluated": result.folds_evaluated,
            "folds_by_season": dict(sorted(result.folds_by_season.items())),
            "predictions": result.predictions,
            "stage_a_fallbacks": result.stage_a_fallbacks,
            "monte_carlo_draws": result.draws,
            "points_support_max": result.max_points,
            "overall": _clean_score_record(result.overall),
            "headline_xg_present": _clean_score_record(result.headline_xg),
            "by_season": {s: _clean_score_record(r) for s, r in sorted(result.by_season.items())},
            "by_position": {
                p: _clean_score_record(r) for p, r in sorted(result.by_position.items())
            },
            "by_xg_coverage_regime": {
                k: _clean_score_record(r) for k, r in sorted(result.by_regime.items())
            },
        },
        "v2_component_diagnostics": {
            "gk_save_rate_fold_local_min": result.save_rate_min,
            "gk_save_rate_fold_local_max": result.save_rate_max,
            "dc_folds_with_history": result.folds_with_dc_history,
            "dc_targets_with_positive_hit_probability": result.dc_positive_predictions,
        },
        "limitations": {
            "component_independence": (
                "components composed independently per player; no team-coupling or conservation"
            ),
            "bonus": "bonus excluded from prediction and from the label (total_points - bonus)",
            "defensive_contribution": (
                "prospective-only: DC data exists only for 2025-26, so p_hit is 0 for every "
                "earlier fold; estimated over appearances, not conditioned on the drawn minute bin "
                "(minutes-independence approximation)"
            ),
            "saves": (
                "goalkeeper-only; derived from the fixture's expected team-conceded rate via the "
                "fold-local league save rate (no per-keeper saves history)"
            ),
            "unmodelled_components": (
                "penalties, own goals, cards not drawn (label still includes them)"
            ),
            "negative_points": "folded into the 0 bin on the TOTAL, after adding saves and DC",
        },
        "historical_proxy_caveats": {
            "no_xg_season_excluded_from_headline": NO_XG_SEASON,
            "real_deadline_knowledge_time_validity": "unproven",
            "archive_result_role": "development_diagnostic_only",
        },
    }


def format_reconciliation_record(record: dict[str, object]) -> str:
    return json.dumps(record, indent=2, sort_keys=True, allow_nan=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run Stage D v2 points composition as a DEVELOPMENT-ONLY evaluation. Not a promotion "
            "evaluation."
        )
    )
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--season", action="append", dest="seasons", default=None)
    parser.add_argument("--draws", type=int, default=DEFAULT_DRAWS)
    parser.add_argument("--save-json", type=Path, default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    repo = repo_root()
    require_clean_worktree(repo)
    db_path = args.db or default_db_path()

    seed = 202627
    started = Provenance(
        commit_sha=_git(repo, "rev-parse", "HEAD"),
        source_fingerprints=_fingerprints(repo, _SOURCE_RELS, base=repo),
        config_fingerprints=_fingerprints(repo, _CONFIG_RELS, base=config_dir()),
        database_sha256=file_sha256(db_path),
        seed=seed,
        draws=args.draws,
        started_at=_utc_now(),
        ended_at="",
    )

    con = connect(db_path, read_only=True)
    try:
        result = run_points_harness(con, seasons=args.seasons, draws=args.draws, base_seed=seed)
    finally:
        con.close()

    try:
        verify_unchanged(started, repo=repo, db_path=db_path)
    except ProvenanceError as exc:
        sys.stderr.write(
            f"Stage D v2 result is INVALID / UNPUBLISHABLE and will not be printed: {exc}\n"
        )
        return 1

    provenance = Provenance(
        commit_sha=started.commit_sha,
        source_fingerprints=started.source_fingerprints,
        config_fingerprints=started.config_fingerprints,
        database_sha256=started.database_sha256,
        seed=seed,
        draws=args.draws,
        started_at=started.started_at,
        ended_at=_utc_now(),
    )

    print(_DEVELOPMENT_BANNER)
    print(format_points_report(result))
    reconciliation = build_reconciliation_record(result, provenance=provenance)
    reconciliation_report = format_reconciliation_record(reconciliation)
    print("BEGIN_STAGE_D_POINTS_COMPOSITION_V2_RECONCILIATION_JSON")
    print(reconciliation_report)
    print("END_STAGE_D_POINTS_COMPOSITION_V2_RECONCILIATION_JSON")

    # Written only AFTER verify_unchanged passed, so the recorded commit names the exact scored code
    # and the write itself (an untracked docs/results file) cannot dirty the verified worktree.
    if args.save_json:
        args.save_json.parent.mkdir(parents=True, exist_ok=True)
        args.save_json.write_text(reconciliation_report, encoding="utf-8")
        logger.info("Saved verbatim reconciliation JSON to %s", args.save_json)

    return 0


if __name__ == "__main__":
    sys.exit(main())
