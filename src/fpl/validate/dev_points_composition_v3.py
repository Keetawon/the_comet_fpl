"""Development-only runner for Stage D v3 FULL-points composition. NOT a promotion evaluation.

    python -m fpl.validate.dev_points_composition_v3          # full archive, development only
    python -m fpl.validate.dev_points_composition_v3 --season 2025-26

Stage D v3 composes a whole fixture JOINTLY so it can add bonus: in each Monte-Carlo world every
appeared player's components are drawn once, the SAME draw yields both the player's non-bonus points
and their BPS, the fixture's BPS are ranked, and 3/2/1 bonus is awarded and added. It scores the
resulting FULL-points distribution (incl. bonus) against realised full points -- the recomputed
non-bonus points (R1: never `total_points`) PLUS the realised recorded `bonus` component.

This runner performs the single authorized clean historical development run: it refuses a dirty
worktree, fingerprints the exact code / config / model sources / database it scored (including BOTH
`points_composition.py` and `bps_bonus.py`), runs the integrative harness once, then rechecks that
nothing moved during the run and (only then) emits a full reconciliation record, writing the
optional ``--save-json`` file AFTER the postflight verification passes. Writing before that check
dirties the verified worktree, exactly the failure mode the v1 runner tripped; this runner writes
last.

**Every number it prints is DEVELOPMENT-ONLY and EXPLORATORY -- not a promotion verdict.** There is
no pre-registered Stage D promotion contract; this is an end-to-end "is it any good" reading, under
the same unversioned historical proxies (target roster, first-kickoff cutoff) every stage carries.
It scores a DIFFERENT label than v2 (full points vs non-bonus points), so it is a full-points
quality read, not a like-for-like delta. See
``docs/phase4-stage-d-points-composition-v3-development.md``.
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
from fpl.validate.points_harness import NO_XG_SEASON
from fpl.validate.points_harness_v3 import (
    DEFAULT_DRAWS,
    PointsHarnessV3Result,
    format_points_report_v3,
    run_points_harness_v3,
)

logger = logging.getLogger("fpl.validate.dev_points_composition_v3")

_DEVELOPMENT_BANNER = (
    "\n"
    "============================================================================\n"
    " DEVELOPMENT ONLY -- NOT A PROMOTION RESULT\n"
    " Stage D v3 FULL-points composition (match-level joint draw adds bonus).\n"
    " The historical archive is development evidence (unversioned target-roster /\n"
    " first-kickoff proxies) and every component is itself a development-stage estimator;\n"
    " this is an end-to-end reading, not a fresh holdout and with NO comparator baseline.\n"
    " It scores FULL points (incl. bonus) -- a DIFFERENT label than v2's non-bonus points --\n"
    " so it is NOT a like-for-like delta against v2. Stage-D limitations: components drawn\n"
    " independently ACROSS players (the only added coupling is the bonus rank; no team-goal\n"
    " conservation); penalties / own goals / cards excluded from the prediction; the BPS\n"
    " residual reads the target row's realised influence/creativity (as the BPS study does).\n"
    " No number below is a promotion verdict.\n"
    "============================================================================\n"
)

# Files whose bytes define exactly what was scored. Any change between preflight and postflight
# invalidates the run. v3 adds the joint composer and the reused BPS simulator source.
_SOURCE_RELS = (
    Path("src") / "fpl" / "models" / "points_composition.py",
    Path("src") / "fpl" / "models" / "bps_bonus.py",
    Path("src") / "fpl" / "validate" / "points_harness_v3.py",
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
            "Stage D v3 refuses to run on a dirty worktree. The recorded commit SHA must name the "
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
    result: PointsHarnessV3Result, *, provenance: Provenance
) -> dict[str, object]:
    return {
        "schema": "stage_d_points_composition_v3_development/v1",
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
        "scored_label": "full_points_incl_bonus (non-bonus under 2026/27 + realised bonus)",
        "components": result.component_names,
        "harness": {
            "folds_evaluated": result.folds_evaluated,
            "folds_by_season": dict(sorted(result.folds_by_season.items())),
            "predictions": result.predictions,
            "fixtures": result.fixtures,
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
        "bonus_diagnostics": {
            "expected_bonus_total": result.expected_bonus_total,
            "realised_bonus_total": result.realised_bonus_total,
            "expected_bonus_by_position": result.expected_bonus_by_position,
            "realised_bonus_by_position": result.realised_bonus_by_position,
        },
        "v2_component_diagnostics": {
            "gk_save_rate_fold_local_min": result.save_rate_min,
            "gk_save_rate_fold_local_max": result.save_rate_max,
            "dc_folds_with_history": result.folds_with_dc_history,
            "dc_targets_with_positive_hit_probability": result.dc_positive_predictions,
        },
        "limitations": {
            "cross_player_component_independence": (
                "components are drawn independently ACROSS players; the ONLY joint coupling added "
                "by v3 is the within-match bonus rank. No team-goal-total conservation."
            ),
            "bonus_residual_proxy": (
                "the BPS residual's influence/creativity correction reads the target row's "
                "realised ICT values (development-only, exactly as the standalone BPS study does); "
                "the player's own realised BPS/bonus for the predicted row is never a model input"
            ),
            "unmodelled_components": (
                "penalties, own goals, cards not drawn (label still includes them)"
            ),
            "defensive_contribution": (
                "prospective-only: DC data exists only for 2025-26, so p_hit is 0 for every "
                "earlier fold"
            ),
            "negative_points": "folded into the 0 bin on the TOTAL, after saves, DC, and bonus",
        },
        "historical_proxy_caveats": {
            "no_xg_season_excluded_from_headline": NO_XG_SEASON,
            "real_deadline_knowledge_time_validity": "unproven",
            "archive_result_role": "development_diagnostic_only",
            "not_a_like_for_like_delta_against_v2": (
                "v2 scores non-bonus points; v3 scores full points incl. bonus"
            ),
        },
    }


def format_reconciliation_record(record: dict[str, object]) -> str:
    return json.dumps(record, indent=2, sort_keys=True, allow_nan=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run Stage D v3 FULL-points composition as a DEVELOPMENT-ONLY evaluation. Not a "
            "promotion evaluation."
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
        result = run_points_harness_v3(con, seasons=args.seasons, draws=args.draws, base_seed=seed)
    finally:
        con.close()

    try:
        verify_unchanged(started, repo=repo, db_path=db_path)
    except ProvenanceError as exc:
        sys.stderr.write(
            f"Stage D v3 result is INVALID / UNPUBLISHABLE and will not be printed: {exc}\n"
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
    print(format_points_report_v3(result))
    reconciliation = build_reconciliation_record(result, provenance=provenance)
    reconciliation_report = format_reconciliation_record(reconciliation)
    print("BEGIN_STAGE_D_POINTS_COMPOSITION_V3_RECONCILIATION_JSON")
    print(reconciliation_report)
    print("END_STAGE_D_POINTS_COMPOSITION_V3_RECONCILIATION_JSON")

    # Written only AFTER verify_unchanged passed, so the recorded commit names the exact scored code
    # and the write itself (an untracked docs/results file) cannot dirty the verified worktree.
    if args.save_json:
        args.save_json.parent.mkdir(parents=True, exist_ok=True)
        args.save_json.write_text(reconciliation_report, encoding="utf-8")
        logger.info("Saved verbatim reconciliation JSON to %s", args.save_json)

    return 0


if __name__ == "__main__":
    sys.exit(main())
