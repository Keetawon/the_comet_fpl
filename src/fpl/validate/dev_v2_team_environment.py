"""Development runner for the V2 team-environment ablation and the GK saves comparison.

    python -m fpl.validate.dev_v2_team_environment --results results/

Executes `config/v2_team_environment_evaluation.yaml` and
`config/v2_gk_saves_evaluation.yaml` as written: the ablation ladder, the Phase 1 baselines
re-run on identical rows, per-season and per-slice splits, and the pre-registered gate.

**This is a development runner and its output is a development record.** Even a candidate that
clears every gate here is not promoted: both contracts declare
`promotion_requires_prospective_window`, because the historical target roster and first-kickoff
cutoff are unversioned proxies -- the same caveat that keeps every Stage B and Stage C
candidate development-only. Nothing in this module changes a prospective default.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from fpl.config import (
    load_v2_gk_saves_evaluation,
    load_v2_team_environment_evaluation,
    repo_root,
)
from fpl.models.football_engine_v2 import DEFAULT_SIGNALS, SignalSpec
from fpl.storage.db import connect
from fpl.validate.baselines import build_baselines
from fpl.validate.v2_environment_harness import (
    Prediction,
    load_goalkeeper_frame,
    load_team_frame,
    observed_folds,
    promoted_team_codes,
    relative_lift,
    run_gk_saves,
    run_team_environment,
    score,
    score_by_season,
    score_by_slice,
)

logger = logging.getLogger("fpl.dev_v2_team_environment")

RESULT_FILE = "v2_team_environment_development.json"


def _git_state() -> dict[str, str | bool]:
    """HEAD and worktree cleanliness, so a result can be tied to the code that made it."""
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=repo_root(),
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
            cwd=repo_root(),
        ).stdout.strip()
    except (subprocess.CalledProcessError, OSError) as error:
        return {"head": f"unavailable: {error}", "clean_worktree": False}
    return {"head": head, "clean_worktree": not status}


def _signals_for(names: list[str]) -> list[SignalSpec]:
    """Resolve contract signal names to specs, keeping the engine's declaration order.

    The environment-only signals (the shots-faced proxy and defensive actions) are always
    included: they never enter the goal-rate blend, so adding them cannot change a rung's
    attacking prediction, and excluding them would leave the saves comparison with no shots
    signal on the very rungs it needs one.
    """
    wanted = set(names)
    return [spec for spec in DEFAULT_SIGNALS if spec.name in wanted or not spec.blendable]


def _baseline_predictions(
    frame: pl.DataFrame,
    baseline_names: list[str],
    *,
    minimum_prior_gameweeks: int,
    limit_folds: int | None,
) -> dict[str, list[Prediction]]:
    """Re-run the Phase 1 baselines on THESE rows.

    Deliberately re-run rather than compared against their frozen Phase 1 numbers: those were
    produced on a different population definition, and quoting them here would be a
    cross-contract comparison of the kind this repository has explicitly ruled out.
    """
    from fpl.validate.baselines import TrainingWindow

    available = {baseline.name: baseline for baseline in build_baselines()}
    selected = {name: available[name] for name in baseline_names if name in available}
    results: dict[str, list[Prediction]] = {name: [] for name in selected}
    folds = observed_folds(frame, minimum_prior_gameweeks=minimum_prior_gameweeks)
    if limit_folds is not None:
        folds = folds[-limit_folds:]
    # The Phase 1 baselines read `goals_for` and `team_xg`; the V2 mart names them `goals` and
    # `expected_goals`. Aliasing here rather than renaming the mart keeps the V2 column
    # vocabulary consistent with the metric dictionary.
    aliased = frame.with_columns(
        pl.col("goals").alias("goals_for"),
        pl.col("goals_allowed").alias("goals_against"),
        pl.col("expected_goals").alias("team_xg"),
        # The Phase 1 xG baseline pairs team_xg with team_xgc, FPL's own per-player xGC
        # measurement -- not with the opponent's mirrored xG. Using the same source it used in
        # Phase 1 keeps this a re-run of that baseline rather than a variant of it.
        pl.col("expected_goals_conceded_measured").alias("team_xgc"),
        pl.lit(None, dtype=pl.Int32).alias("fdr"),
    )
    for season, gw, cutoff in folds:
        training = aliased.filter(pl.col("kickoff_time") < cutoff)
        target = aliased.filter((pl.col("season") == season) & (pl.col("gw") == gw))
        if training.is_empty() or target.is_empty():
            continue
        for name, baseline in selected.items():
            baseline.set_prediction_season(season)
            baseline.fit(TrainingWindow(training))
            distributions = baseline.predict(target)
            for row, distribution in zip(target.iter_rows(named=True), distributions, strict=True):
                goals = row["goals"]
                if goals is None or distribution is None:
                    continue
                results[name].append(
                    Prediction(
                        season=season,
                        gw=gw,
                        key=f"{season}:{row['fixture']}:{row['team_code']}",
                        distribution=distribution,
                        observed=int(goals),
                        was_home=bool(row["was_home"]),
                        cold_start=baseline.is_cold_start(row),
                    )
                )
    return results


def _common_keys(blocks: dict[str, list[Prediction]]) -> set[str]:
    """Rows every model produced. Scoring on anything else compares populations."""
    key_sets = [{prediction.key for prediction in rows} for rows in blocks.values() if rows]
    if not key_sets:
        return set()
    common = key_sets[0]
    for other in key_sets[1:]:
        common &= other
    return common


def run(
    *,
    db_path: Path | None = None,
    results_dir: Path | None = None,
    limit_folds: int | None = None,
    seasons: list[str] | None = None,
) -> dict[str, Any]:
    contract = load_v2_team_environment_evaluation()
    saves_contract = load_v2_gk_saves_evaluation()
    con = connect(db_path, read_only=True)
    try:
        frame = load_team_frame(con, provider=contract.population.provider, seasons=seasons)
        goalkeepers = load_goalkeeper_frame(con, seasons=seasons)
        promoted = promoted_team_codes(con)
    finally:
        con.close()

    if frame.is_empty():
        raise RuntimeError(
            f"provider {contract.population.provider!r} has no rows in "
            "mart_fact_team_match_stats_v2. Build the V2 layer first "
            "(`python -m fpl.jobs.build_db`), or capture the provider's data."
        )

    minimum = contract.walk_forward.minimum_training_observed_gameweeks
    blocks: dict[str, list[Prediction]] = {}
    parameters: dict[str, list[dict[str, Any]]] = {}

    logger.info("running %d ablation rung(s)", len(contract.ablation.candidates))
    for candidate in contract.ablation.candidates:
        signals = _signals_for(candidate.signals)
        predictions, fold_parameters = run_team_environment(
            frame,
            signals=signals,
            promoted=promoted,
            minimum_prior_gameweeks=minimum,
            minimum_signal_coverage=contract.ablation.minimum_signal_coverage,
            weight_step=contract.ablation.weight_step,
            limit_folds=limit_folds,
        )
        blocks[candidate.name] = predictions
        parameters[candidate.name] = fold_parameters
        logger.info("  %s: %d prediction(s)", candidate.name, len(predictions))

    logger.info("running %d baseline(s)", len(contract.baselines))
    blocks.update(
        _baseline_predictions(
            frame,
            contract.baselines,
            minimum_prior_gameweeks=minimum,
            limit_folds=limit_folds,
        )
    )

    shared = _common_keys(blocks)
    logger.info("scoring on %d row(s) common to every model", len(shared))
    scored = {
        name: score(name, [p for p in rows if p.key in shared]).as_dict()
        for name, rows in blocks.items()
    }
    by_season = {
        name: score_by_season(name, [p for p in rows if p.key in shared])
        for name, rows in blocks.items()
    }
    by_slice = {
        name: score_by_slice(name, [p for p in rows if p.key in shared])
        for name, rows in blocks.items()
    }

    best_baseline = min(
        (name for name in contract.baselines if name in scored),
        key=lambda name: float(scored[name]["mean_log_score"]),
        default=None,
    )

    logger.info("running the goalkeeper saves comparison")
    saves_blocks = run_gk_saves(
        frame,
        goalkeepers,
        signals=list(DEFAULT_SIGNALS),
        promoted=promoted,
        minimum_prior_gameweeks=minimum,
        limit_folds=limit_folds,
    )
    saves_shared = _common_keys(saves_blocks)
    saves_scored = {
        name: score(name, [p for p in rows if p.key in saves_shared]).as_dict()
        for name, rows in saves_blocks.items()
    }
    saves_by_season = {
        name: score_by_season(name, [p for p in rows if p.key in saves_shared])
        for name, rows in saves_blocks.items()
    }
    saves_by_slice = {
        name: score_by_slice(name, [p for p in rows if p.key in saves_shared])
        for name, rows in saves_blocks.items()
    }
    saves_baseline = next(
        candidate.name for candidate in saves_contract.candidates if candidate.is_baseline
    )

    report: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "development_only",
        "not_a_promotion": (
            "Both contracts declare promotion_requires_prospective_window. The historical "
            "target roster and first-kickoff cutoff are unversioned proxies, so no historical "
            "result here can establish real-deadline validity. The prospective default is "
            "unchanged."
        ),
        "git": _git_state(),
        "team_environment": {
            "contract_version": contract.contract_version,
            "provider": contract.population.provider,
            "rows_scored": len(shared),
            "folds": len(parameters.get(contract.ablation.candidates[0].name, [])),
            "best_baseline": best_baseline,
            "overall": scored,
            "by_season": by_season,
            "by_slice": by_slice,
            "lift_against_best_baseline": (
                {
                    name: {
                        "mean_log_score": round(
                            relative_lift(
                                float(scored[best_baseline]["mean_log_score"]),
                                float(block["mean_log_score"]),
                            ),
                            6,
                        ),
                        "crps": round(
                            relative_lift(
                                float(scored[best_baseline]["crps"]), float(block["crps"])
                            ),
                            6,
                        ),
                    }
                    for name, block in scored.items()
                }
                if best_baseline
                else {}
            ),
            "fold_parameters": parameters,
        },
        "gk_saves": {
            "contract_version": saves_contract.contract_version,
            "rows_scored": len(saves_shared),
            "baseline": saves_baseline,
            "overall": saves_scored,
            "by_season": saves_by_season,
            "by_slice": saves_by_slice,
            "lift_against_baseline": {
                name: {
                    "mean_log_score": round(
                        relative_lift(
                            float(saves_scored[saves_baseline]["mean_log_score"]),
                            float(block["mean_log_score"]),
                        ),
                        6,
                    ),
                    "crps": round(
                        relative_lift(
                            float(saves_scored[saves_baseline]["crps"]), float(block["crps"])
                        ),
                        6,
                    ),
                }
                for name, block in saves_scored.items()
            },
        },
    }

    if results_dir is not None:
        results_dir.mkdir(parents=True, exist_ok=True)
        path = results_dir / RESULT_FILE
        path.write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        logger.info("wrote %s", path)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the V2 development evaluation.")
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--results", type=Path, default=None)
    parser.add_argument(
        "--limit-folds", type=int, default=None, help="score only the last N folds (smoke runs)"
    )
    parser.add_argument("--season", action="append", default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    report = run(
        db_path=args.db,
        results_dir=args.results,
        limit_folds=args.limit_folds,
        seasons=args.season,
    )
    team = report["team_environment"]
    print(f"\nTeam environment -- {team['rows_scored']} rows, {team['folds']} folds")
    for name, block in sorted(team["overall"].items(), key=lambda item: item[1]["mean_log_score"]):
        margin = team["lift_against_best_baseline"].get(name, {}).get("mean_log_score", 0.0)
        print(
            f"  {name:38s} log={block['mean_log_score']:.5f} crps={block['crps']:.5f} "
            f"pit80={block['pit_interval_80_coverage']:.4f} lift={margin:+.4%}"
        )
    saves = report["gk_saves"]
    print(f"\nGoalkeeper saves -- {saves['rows_scored']} rows")
    for name, block in sorted(saves["overall"].items(), key=lambda item: item[1]["mean_log_score"]):
        margin = saves["lift_against_baseline"][name]["mean_log_score"]
        print(
            f"  {name:38s} log={block['mean_log_score']:.5f} crps={block['crps']:.5f} "
            f"pit80={block['pit_interval_80_coverage']:.4f} lift={margin:+.4%} "
            f"engine_rows={block['used_engine_signal_rows']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
