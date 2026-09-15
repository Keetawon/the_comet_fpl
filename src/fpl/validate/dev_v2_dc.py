"""Development runner for the V2 defensive-contribution comparison.

    python -m fpl.validate.dev_v2_dc --results results/

Executes `config/v2_dc_evaluation.yaml`. V1 and V2 are fitted on the same fold history and
scored on identical player-fixture rows; the only difference is where the DC expectation comes
from -- a personal trailing hit rate, or a team environment allocated by role share.

The transferred-player split is the point of the exercise, not a detail. This repository's
measured rule says DC is a property of the team system (team hit rates 0.333 to 0.146) and that
a transferred player's expectation must be rescaled to the destination club. If that rule is
right, V2 should beat V1 by MORE on players who changed club than on those who did not. A
candidate that wins overall but not there has not shown the mechanism it claims.

**Development-only.** The contract declares `promotion_requires_prospective_window`, and DC
exists in exactly one archived season, so no result here can promote anything.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from fpl.config import load_scoring_rules, load_v2_dc_evaluation, repo_root
from fpl.models.defensive_contribution_v1 import DcHistoryRow, DefensiveContributionV1
from fpl.models.defensive_environment_v2 import (
    DcEnvironmentHistoryRow,
    DefensiveEnvironmentV2,
)
from fpl.storage.db import connect
from fpl.types import Position

logger = logging.getLogger("fpl.dev_v2_dc")

RESULT_FILE = "v2_dc_development.json"
PROBABILITY_FLOOR = 1e-12


class ProvenanceError(RuntimeError):
    """The run cannot be tied to a reproducible code state."""


def _git_state() -> dict[str, str | bool]:
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


@dataclass(frozen=True, slots=True)
class DcPrediction:
    """One scored player-fixture, with the slice keys the contract requires."""

    season: str
    gw: int
    code: int
    probability: float
    observed: bool
    position: Position
    transferred: bool


def load_dc_frame(con: Any, *, seasons: list[str] | None = None) -> pl.DataFrame:
    """Player-fixture rows with measured DC, plus their club's measured DC total.

    The team total comes from `mart_fact_team_match_stats_v2` (`fpl_archive` provider), which
    already sums the DC-relevant actions per club per fixture. Reading it there rather than
    re-summing keeps V2's denominator identical to the one the football engine predicts.
    """
    predicate = ""
    params: list[object] = []
    if seasons:
        predicate = f"AND p.season IN ({', '.join('?' for _ in seasons)})"
        params.extend(seasons)
    relation = con.execute(
        f"""
        SELECT p.season, p.gw, p.fixture, p.kickoff_time, p.code, p.position, p.team_id,
               p.minutes, p.defensive_contribution,
               dt.team_code,
               t.defensive_actions AS team_defensive_actions
        FROM mart_fact_player_fixture AS p
        LEFT JOIN mart_dim_team AS dt ON dt.season = p.season AND dt.team_id = p.team_id
        LEFT JOIN mart_fact_team_match_stats_v2 AS t
               ON t.season = p.season AND t.fixture = p.fixture AND t.team_id = p.team_id
              AND t.provider = 'fpl_archive'
        WHERE p.position IN ('DEF', 'MID', 'FWD')
          AND p.minutes > 0
          AND p.defensive_contribution IS NOT NULL
          AND dt.team_code IS NOT NULL {predicate}
        ORDER BY p.kickoff_time, p.season, p.fixture, p.code
        """,
        params,
    )
    return pl.from_arrow(relation.to_arrow_table())  # type: ignore[return-value]


def transferred_codes(con: Any) -> set[tuple[str, int]]:
    """`(season, code)` for players with more than one club stint inside a season.

    Read from `mart_dim_player_stint`, never from `mart_dim_player`: the dimension records only
    the club a player FINISHED the season at, and is wrong for roughly half of all transfer
    stints (measured 242 stints, of which the dimension matches 120).
    """
    return {
        (str(season), int(code))
        for season, code in con.execute(
            """
            SELECT season, code FROM mart_dim_player_stint
            GROUP BY season, code HAVING count(*) > 1
            """
        ).fetchall()
    }


def _thresholds() -> dict[Position, int]:
    """DC thresholds from the 2026/27 scoring rules. Never hard-coded here.

    Goalkeepers are absent from the rules' threshold map by design, so they fall out of the
    population without needing a special case anywhere.
    """
    return dict(load_scoring_rules("2026_27").defensive_contribution.thresholds)


def _log_score(probability: float, observed: bool) -> float:
    mass = probability if observed else 1.0 - probability
    return -math.log(max(mass, PROBABILITY_FLOOR))


def _auc(predictions: list[DcPrediction]) -> float | None:
    """Rank-based AUC.

    AUC rather than a rank correlation, deliberately: this repository measured that on a binary
    outcome with a large tie block a Spearman over average ranks read -10.9% where AUC read
    +2.2%, and recorded that the AUC figure is the correct one. Ties in the predicted
    probability contribute 0.5, which is what makes a constant predictor score exactly 0.5
    rather than looking informative.
    """
    positives = [p.probability for p in predictions if p.observed]
    negatives = [p.probability for p in predictions if not p.observed]
    if not positives or not negatives:
        return None
    ordered = sorted(
        [(value, 1) for value in positives] + [(value, 0) for value in negatives],
        key=lambda item: item[0],
    )
    rank_sum = 0.0
    index = 0
    while index < len(ordered):
        end = index
        while end + 1 < len(ordered) and ordered[end + 1][0] == ordered[index][0]:
            end += 1
        average_rank = (index + end) / 2.0 + 1.0
        for position in range(index, end + 1):
            if ordered[position][1] == 1:
                rank_sum += average_rank
        index = end + 1
    n_pos, n_neg = len(positives), len(negatives)
    return (rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def score(name: str, predictions: list[DcPrediction]) -> dict[str, Any]:
    """Proper scores for a binary probability, plus the honest denominator."""
    if not predictions:
        return {"model": name, "rows": 0}
    logs = [_log_score(p.probability, p.observed) for p in predictions]
    briers = [(p.probability - float(p.observed)) ** 2 for p in predictions]
    return {
        "model": name,
        "rows": len(predictions),
        "mean_log_score": round(sum(logs) / len(logs), 6),
        "brier_score": round(sum(briers) / len(briers), 6),
        "auc": None if (auc := _auc(predictions)) is None else round(auc, 6),
        "mean_predicted": round(sum(p.probability for p in predictions) / len(predictions), 6),
        "observed_rate": round(sum(p.observed for p in predictions) / len(predictions), 6),
    }


def reliability_bins(predictions: list[DcPrediction], *, bins: int = 10) -> list[dict[str, Any]]:
    """Observed rate against mean predicted probability, per decile of prediction."""
    buckets: dict[int, list[DcPrediction]] = defaultdict(list)
    for prediction in predictions:
        index = min(int(prediction.probability * bins), bins - 1)
        buckets[index].append(prediction)
    return [
        {
            "bin_low": round(index / bins, 3),
            "bin_high": round((index + 1) / bins, 3),
            "rows": len(rows),
            "mean_predicted": round(sum(r.probability for r in rows) / len(rows), 6),
            "observed_rate": round(sum(r.observed for r in rows) / len(rows), 6),
        }
        for index, rows in sorted(buckets.items())
    ]


def relative_lift(baseline: float, candidate: float) -> float:
    if baseline == 0:
        return 0.0
    return (baseline - candidate) / abs(baseline)


def run_folds(
    frame: pl.DataFrame,
    *,
    transferred: set[tuple[str, int]],
    thresholds: dict[Position, int],
    minimum_prior_gameweeks: int,
) -> dict[str, list[DcPrediction]]:
    """Walk forward, fitting and scoring both models on identical rows in one loop."""
    gameweeks = (
        frame.group_by(["season", "gw"], maintain_order=True)
        .agg(pl.col("kickoff_time").min().alias("cutoff"))
        .sort(["cutoff", "season", "gw"])
    )
    results: dict[str, list[DcPrediction]] = {
        "trailing_dc_threshold_hit_bernoulli_v1": [],
        "team_environment_share_dc_threshold_v2": [],
    }
    for index, row in enumerate(gameweeks.iter_rows(named=True)):
        if index < minimum_prior_gameweeks:
            continue
        season, gw, cutoff = str(row["season"]), int(row["gw"]), row["cutoff"]
        training = frame.filter(pl.col("kickoff_time") < cutoff)
        target = frame.filter((pl.col("season") == season) & (pl.col("gw") == gw))
        if training.is_empty() or target.is_empty():
            continue

        v1 = DefensiveContributionV1(thresholds)
        v1.fit(
            [
                DcHistoryRow(
                    code=int(r["code"]),
                    position=Position(r["position"]),
                    minutes=int(r["minutes"]),
                    defensive_contribution=r["defensive_contribution"],
                )
                for r in training.iter_rows(named=True)
            ]
        )
        v2 = DefensiveEnvironmentV2()
        v2.fit(
            [
                DcEnvironmentHistoryRow(
                    code=int(r["code"]),
                    team_code=int(r["team_code"]),
                    position=Position(r["position"]),
                    minutes=int(r["minutes"]),
                    defensive_contribution=r["defensive_contribution"],
                    team_defensive_actions=r["team_defensive_actions"],
                )
                for r in training.iter_rows(named=True)
            ]
        )

        for r in target.iter_rows(named=True):
            position = Position(r["position"])
            threshold = thresholds.get(position)
            if threshold is None:
                continue
            code = int(r["code"])
            observed = int(r["defensive_contribution"]) >= threshold
            moved = (season, code) in transferred
            probabilities = {
                "trailing_dc_threshold_hit_bernoulli_v1": v1.predict(code=code, position=position),
                "team_environment_share_dc_threshold_v2": v2.predict(
                    code=code,
                    position=position,
                    threshold=threshold,
                    team_defensive_actions=r["team_defensive_actions"],
                    # The REALISED on-pitch share. This evaluation isolates the DC allocation
                    # from the minutes model: handing V2 a predicted exposure would test two
                    # models at once, and V1 conditions on nothing at all.
                    minutes_exposure=min(int(r["minutes"]) / 90.0, 1.0),
                ),
            }
            for model, probability in probabilities.items():
                results[model].append(
                    DcPrediction(
                        season=season,
                        gw=gw,
                        code=code,
                        probability=probability,
                        observed=observed,
                        position=position,
                        transferred=moved,
                    )
                )
    return results


def run(
    *,
    db_path: Path | None = None,
    results_dir: Path | None = None,
    allow_dirty: bool = False,
) -> dict[str, Any]:
    provenance = _git_state()
    if not provenance["clean_worktree"] and not allow_dirty:
        raise ProvenanceError(
            "refusing to run against a dirty worktree: the result could not be reproduced "
            "from its recorded HEAD. Commit or stash first, or pass --allow-dirty."
        )
    contract = load_v2_dc_evaluation()
    thresholds = _thresholds()

    con = connect(db_path, read_only=True)
    try:
        frame = load_dc_frame(con)
        transferred = transferred_codes(con)
    finally:
        con.close()

    if frame.is_empty():
        raise RuntimeError(
            "no player-fixture row carries a measured defensive_contribution. DC exists in "
            "2025-26 only; build the database first."
        )

    blocks = run_folds(
        frame,
        transferred=transferred,
        thresholds=thresholds,
        minimum_prior_gameweeks=contract.walk_forward.minimum_training_observed_gameweeks,
    )
    baseline = next(c.name for c in contract.candidates if c.is_baseline)

    def slices(predictions: list[DcPrediction]) -> dict[str, dict[str, Any]]:
        groups: dict[str, list[DcPrediction]] = {
            "transferred": [p for p in predictions if p.transferred],
            "not_transferred": [p for p in predictions if not p.transferred],
            **{
                f"position_{position.value}": [p for p in predictions if p.position is position]
                for position in (Position.DEF, Position.MID, Position.FWD)
            },
        }
        return {label: score(label, rows) for label, rows in groups.items() if rows}

    overall = {name: score(name, rows) for name, rows in blocks.items()}
    by_slice = {name: slices(rows) for name, rows in blocks.items()}
    by_season = {
        name: {
            season: score(name, [p for p in rows if p.season == season])
            for season in sorted({p.season for p in rows})
        }
        for name, rows in blocks.items()
    }

    transferred_lift = None
    if by_slice[baseline].get("transferred") and by_slice[
        "team_environment_share_dc_threshold_v2"
    ].get("transferred"):
        transferred_lift = relative_lift(
            float(by_slice[baseline]["transferred"]["mean_log_score"]),
            float(
                by_slice["team_environment_share_dc_threshold_v2"]["transferred"]["mean_log_score"]
            ),
        )

    report: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "development_only",
        "contract_version": contract.contract_version,
        "git": provenance,
        "allow_dirty": allow_dirty,
        "not_a_promotion": (
            "The contract declares promotion_requires_prospective_window, and DC exists in one "
            "archived season, so this result cannot promote anything."
        ),
        "population": {
            "rows_scored": len(blocks[baseline]),
            "seasons": sorted({p.season for p in blocks[baseline]}),
            "transferred_rows": sum(p.transferred for p in blocks[baseline]),
            "thresholds": {position.value: value for position, value in thresholds.items()},
        },
        "baseline": baseline,
        "overall": overall,
        "by_season": by_season,
        "by_slice": by_slice,
        "reliability": {name: reliability_bins(rows) for name, rows in blocks.items()},
        "lift_against_baseline": {
            name: {
                "mean_log_score": round(
                    relative_lift(
                        float(overall[baseline]["mean_log_score"]),
                        float(block["mean_log_score"]),
                    ),
                    6,
                ),
                "brier_score": round(
                    relative_lift(
                        float(overall[baseline]["brier_score"]), float(block["brier_score"])
                    ),
                    6,
                ),
            }
            for name, block in overall.items()
        },
        "transferred_slice_log_lift": (
            None if transferred_lift is None else round(transferred_lift, 6)
        ),
        "limitations": contract.limitations.model_dump(),
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
    parser = argparse.ArgumentParser(description="Run the V2 DC development evaluation.")
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--results", type=Path, default=None)
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    report = run(db_path=args.db, results_dir=args.results, allow_dirty=args.allow_dirty)

    population = report["population"]
    print(
        f"\nDefensive contribution -- {population['rows_scored']} rows, "
        f"seasons {','.join(population['seasons'])}, "
        f"{population['transferred_rows']} transferred-player rows"
    )
    for name, block in sorted(
        report["overall"].items(), key=lambda item: item[1]["mean_log_score"]
    ):
        lift = report["lift_against_baseline"][name]["mean_log_score"]
        print(
            f"  {name:42s} log={block['mean_log_score']:.5f} brier={block['brier_score']:.5f} "
            f"auc={block['auc']} lift={lift:+.4%}"
        )
    print("\n  by slice (log score):")
    for label in sorted(report["by_slice"][report["baseline"]]):
        base = report["by_slice"][report["baseline"]][label]
        cand = report["by_slice"]["team_environment_share_dc_threshold_v2"][label]
        print(
            f"    {label:20s} rows={cand['rows']:5d} v1={base['mean_log_score']:.5f} "
            f"v2={cand['mean_log_score']:.5f} "
            f"lift={relative_lift(base['mean_log_score'], cand['mean_log_score']):+.4%}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
