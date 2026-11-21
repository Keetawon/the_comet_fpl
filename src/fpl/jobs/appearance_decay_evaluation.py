"""Single pre-registered evaluation of the rostered-decay appearance weight.

    python -m fpl.jobs.appearance_decay_evaluation --db data/fpl.duckdb

Runs the contract in ``config/appearance_decay_evaluation.yaml`` exactly once over the
archive season boundaries: for each target gameweek it rebuilds the REAL prospective
minutes path (equal-weighted shrunk trailing-5 bins, the trailing-history eligibility
rule with a fact-row-resolved current club, the prior-season rate under the
not-available-to-the-club rule, and the exact ``season_boundary_minutes`` blend
arithmetic) and scores the shipped calendar weight against every pre-registered decay
constant ``c`` on the appearance outcome ``minutes >= 1``.

Provenance rules (the repo's runner conventions): refuses a dirty worktree, refuses an
existing immutable result, records Git HEAD and the config SHA-256, and writes the result
atomically. The run is development-only: nothing here promotes a mode, and the
prospective default changes only in a separate recorded commit if the contract's gates
pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import subprocess
import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import polars as pl
import yaml

from fpl.config import config_dir, load_phase2_evaluation, repo_root
from fpl.jobs.prospective_points_v1 import (
    _MIN_PRIOR_SEASON_ROWS,
    _MIN_TRAILING5_ROWS,
    _season_boundary_long_weight,
    prior_season_appearance_rate,
    trailing5_minute_bins,
)
from fpl.storage.db import connect, default_db_path
from fpl.validate.minutes_baselines import MinuteBins

logger = logging.getLogger("fpl.jobs.appearance_decay_evaluation")

_RESULT_PATH = Path("results/appearance_decay_evaluation_v1.json")
_CLIP = 1.0e-6
_PHASES: tuple[tuple[int, int], ...] = ((1, 3), (4, 6), (7, 10), (11, 20))


def _git_head(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def _worktree_clean(repo: Path) -> bool:
    out = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return not out.strip()


def _phase_of(gw: int) -> str:
    for lo, hi in _PHASES:
        if lo <= gw <= hi:
            return f"gw{lo}-{hi}"
    return f"gw{_PHASES[-1][1] + 1}+"


@dataclass(frozen=True, slots=True)
class _ScoredRow:
    gw: int
    p_arm: float
    prior_rate: float
    appeared: bool


def _mean(values: list[float]) -> float:
    return math.fsum(values) / len(values) if values else math.inf


def _loss(p: float, appeared: bool) -> float:
    clipped = min(1.0 - _CLIP, max(_CLIP, p))
    return -math.log(clipped) if appeared else -math.log(1.0 - clipped)


def _mean_log_loss(rows: list[_ScoredRow]) -> float:
    return _mean([_loss(r.p_arm, r.appeared) for r in rows]) if rows else math.inf


def _summarise(rows: list[_ScoredRow]) -> dict[str, Any]:
    by_phase: dict[str, list[float]] = defaultdict(list)
    benched: list[float] = []
    established: list[float] = []
    for r in rows:
        loss = _loss(r.p_arm, r.appeared)
        by_phase[_phase_of(r.gw)].append(loss)
        if r.prior_rate < 0.2:
            benched.append(loss)
        elif r.prior_rate >= 0.6:
            established.append(loss)
    return {
        "rows": len(rows),
        "mean_log_loss": _mean_log_loss(rows),
        "phase_mean_log_loss": {k: _mean(v) for k, v in sorted(by_phase.items())},
        "benched_prior_mean_log_loss": _mean(benched),
        "benched_prior_rows": len(benched),
        "established_prior_mean_log_loss": _mean(established),
        "established_prior_rows": len(established),
    }


@dataclass(frozen=True, slots=True)
class _FoldInputs:
    season: str
    gw: int
    as_of: datetime
    trailing: dict[int, tuple[tuple[float, float, float, float], int]]
    prior: dict[int, tuple[float, int]]
    rostered: dict[int, int]
    targets: dict[int, tuple[int, bool]]  # code -> (target month, appeared)


def _replay_history(con: duckdb.DuckDBPyConnection, as_of: datetime) -> pl.DataFrame:
    """The cutoff-filtered archive frame the live path's helpers consume.

    Column-compatible with ``load_player_history`` output (the mart join supplies the
    season-qualified ``team_code``), so ``trailing5_minute_bins`` and
    ``prior_season_appearance_rate`` run their exact production code paths.
    """
    frame = con.execute(
        """
        SELECT f.season, f.gw, f.fixture, f.kickoff_time, f.code, f.position,
               f.team_id, f.opponent_team_id, f.was_home, f.minutes, t.team_code
        FROM mart_fact_player_fixture AS f
        LEFT JOIN mart_dim_team AS t ON t.season = f.season AND t.team_id = f.team_id
        WHERE f.minutes IS NOT NULL AND CAST(f.kickoff_time AS TIMESTAMPTZ) < ?
        ORDER BY f.kickoff_time, f.season, f.fixture, f.code
        """,
        [as_of],
    ).pl()
    return frame.with_columns(pl.col("kickoff_time").dt.convert_time_zone("UTC"))


def _current_club_from_fact_rows(frame: pl.DataFrame) -> dict[int, int]:
    """Fact-row club resolution at the cutoff (the AGENTS.md-sanctioned method)."""
    resolved = (
        frame.drop_nulls("team_code")
        .sort(["kickoff_time", "season", "fixture", "code"], maintain_order=True)
        .group_by("code", maintain_order=True)
        .last()
    )
    return {int(r["code"]): int(r["team_code"]) for r in resolved.iter_rows(named=True)}


def _fold_inputs(
    con: duckdb.DuckDBPyConnection,
    bins: MinuteBins,
    *,
    season: str,
    gw: int,
    as_of: datetime,
) -> _FoldInputs:
    frame = _replay_history(con, as_of)
    current_club = _current_club_from_fact_rows(frame)
    # Live-path semantics: the eligibility frontier is the most recent COMPLETED season --
    # the latest season strictly before the target (the replay mart contains the in-progress
    # target season, which the live path holds in live staging instead).
    prior_row = con.execute(
        "SELECT max(season) FROM mart_fact_player_fixture WHERE season < ?", [season]
    ).fetchone()
    prior_season = str(prior_row[0]) if prior_row is not None and prior_row[0] is not None else ""
    trailing = trailing5_minute_bins(
        con,
        as_of,
        bins,
        current_club=current_club,
        history=frame,
        frontier_season=prior_season,
    )
    # The prior rate is likewise the latest season the live path would hold archived --
    # strictly before the target season.
    prior = prior_season_appearance_rate(
        con,
        as_of,
        current_club=current_club,
        history=frame.filter(pl.col("season") < pl.lit(season)),
        frontier_season=prior_season,
    )
    rostered = {
        int(r["code"]): int(r["n"])
        for r in frame.filter(pl.col("season") == pl.lit(season))
        .group_by("code")
        .agg(pl.col("gw").n_unique().alias("n"))
        .iter_rows(named=True)
    }
    target_rows = con.execute(
        """
        SELECT f.code, epoch_us(f.kickoff_time), f.minutes >= 1
        FROM mart_fact_player_fixture AS f
        WHERE f.season = ? AND f.gw = ? AND f.minutes IS NOT NULL
        ORDER BY f.code
        """,
        [season, gw],
    ).fetchall()
    targets = {
        int(code): (datetime.fromtimestamp(kickoff_us / 1_000_000, tz=UTC).month, bool(played))
        for code, kickoff_us, played in target_rows
    }
    return _FoldInputs(
        season=season,
        gw=gw,
        as_of=as_of,
        trailing=trailing,
        prior=prior,
        rostered=rostered,
        targets=targets,
    )


def _scored_rows(
    fold: _FoldInputs, weight_of: Callable[[int, int, int], float]
) -> list[_ScoredRow]:
    """Rows for one fold under one weight function ``weight_of(code, month, rostered_gws)``.

    Both arms share ``recent_p`` (the real shrunk trailing-5 estimate) and the prior
    rate; only the weight differs. The blend arithmetic is exactly
    ``season_boundary_minutes``'s ``w * prior + (1 - w) * recent``.
    """
    rows: list[_ScoredRow] = []
    for code, (month, appeared) in fold.targets.items():
        prior_rate, prior_n = fold.prior.get(code, (None, 0))
        if prior_rate is None or prior_n < _MIN_PRIOR_SEASON_ROWS:
            continue  # blend-ineligible in BOTH arms; reported, not scored
        recent = fold.trailing.get(code)
        if recent is None or recent[1] < _MIN_TRAILING5_ROWS:
            continue  # the model-fallback route: w-independent, reported not scored
        recent_p = 1.0 - recent[0][0]
        weight = weight_of(code, month, fold.rostered.get(code, 0))
        p_play = max(0.0, min(1.0, weight * prior_rate + (1.0 - weight) * recent_p))
        rows.append(_ScoredRow(gw=fold.gw, p_arm=p_play, prior_rate=prior_rate, appeared=appeared))
    return rows


def _collect(
    folds: list[_FoldInputs], weight_of: Callable[[int, int, int], float]
) -> list[_ScoredRow]:
    rows: list[_ScoredRow] = []
    for fold in folds:
        rows.extend(_scored_rows(fold, weight_of))
    return rows


def _seasonal_weight(_code: int, month: int, _n: int) -> float:
    return _season_boundary_long_weight(month)


def _decay_weight(c: float) -> Callable[[int, int, int], float]:
    def weight(_code: int, _month: int, n: int) -> float:
        return 0.7 * c / (c + n)

    return weight


def run(db_path: Path | str) -> dict[str, Any]:
    contract = yaml.safe_load((config_dir() / "appearance_decay_evaluation.yaml").read_text())
    if str(contract["contract_version"]) != "1.0":
        raise ValueError("unexpected appearance decay contract version")
    repo = repo_root()
    result_path = repo / _RESULT_PATH
    if result_path.exists():
        raise ValueError(f"immutable evaluation result already exists: {result_path}")
    if not _worktree_clean(repo):
        raise ValueError("evaluation requires a clean Git worktree")
    bins = MinuteBins.from_config(load_phase2_evaluation())
    grid = [float(c) for c in contract["candidate"]["c_grid"]]
    training = [b["target_season"] for b in contract["evaluation_regime"]["training_boundaries"]]
    held_out = str(contract["evaluation_regime"]["held_out_boundary"]["target_season"])
    gw_lo, gw_hi = (int(v) for v in contract["evaluation_regime"]["target_gameweeks"])

    con = connect(db_path, read_only=True)
    try:
        folds: dict[str, list[_FoldInputs]] = {season: [] for season in [*training, held_out]}
        ineligible = {"model_fallback_rows": 0, "no_prior_rows": 0, "scored_rows": 0}
        for season in [*training, held_out]:
            firsts = con.execute(
                """
                SELECT gw, strftime(CAST(min(kickoff_time) AT TIME ZONE 'UTC' AS TIMESTAMP),
                       '%Y-%m-%dT%H:%M:%SZ') AS first_kickoff
                FROM mart_fact_team_match WHERE season = ? GROUP BY gw ORDER BY gw
                """,
                [season],
            ).fetchall()
            for gw_text, first_kickoff in firsts:
                gw = int(gw_text)
                if not (gw_lo <= gw <= gw_hi):
                    continue
                as_of = datetime.fromisoformat(str(first_kickoff).replace("Z", "+00:00"))
                fold = _fold_inputs(con, bins, season=season, gw=gw, as_of=as_of)
                scored = 0
                for code in fold.targets:
                    prior_rate, prior_n = fold.prior.get(code, (None, 0))
                    if prior_rate is None or prior_n < _MIN_PRIOR_SEASON_ROWS:
                        ineligible["no_prior_rows"] += 1
                        continue
                    recent = fold.trailing.get(code)
                    if recent is None or recent[1] < _MIN_TRAILING5_ROWS:
                        ineligible["model_fallback_rows"] += 1
                        continue
                    scored += 1
                ineligible["scored_rows"] += scored
                folds[season].append(fold)
                logger.info(
                    "fold %s gw%02d as_of=%s scored=%d", season, gw, as_of.isoformat(), scored
                )
        training_folds = [f for season in training for f in folds[season]]
        held_folds = folds[held_out]
        training_rows_seasonal = _collect(training_folds, _seasonal_weight)
        training_by_c = {c: _collect(training_folds, _decay_weight(c)) for c in grid}
        selected_c = min(grid, key=lambda c: (_mean_log_loss(training_by_c[c]), c))
        held_rows_seasonal = _collect(held_folds, _seasonal_weight)
        held_rows_decay = {c: _collect(held_folds, _decay_weight(c)) for c in grid}
    finally:
        con.close()

    seasonal_held = _summarise(held_rows_seasonal)
    decay_held = _summarise(held_rows_decay[selected_c])
    max_regression = 0.0
    for phase, loss in decay_held["phase_mean_log_loss"].items():
        base = seasonal_held["phase_mean_log_loss"].get(phase)
        if base is not None and 0.0 < base < math.inf:
            max_regression = max(max_regression, (loss - base) / base)
    gates = {
        "held_out_pooled_log_loss_beats_seasonal": decay_held["mean_log_loss"]
        < seasonal_held["mean_log_loss"],
        "held_out_gw7_20_log_loss_beats_seasonal": decay_held["phase_mean_log_loss"].get(
            "gw7-10", math.inf
        )
        < seasonal_held["phase_mean_log_loss"].get("gw7-10", math.inf)
        and decay_held["phase_mean_log_loss"].get("gw11-20", math.inf)
        < seasonal_held["phase_mean_log_loss"].get("gw11-20", math.inf),
        "max_phase_relative_regression": max_regression,
        "gate3_within_2pct": max_regression <= 0.02,
    }
    return {
        "schema": "appearance_decay_evaluation_v1",
        "status": "development_only_not_a_promotion",
        "contract": {
            "name": contract["name"],
            "contract_version": contract["contract_version"],
            "config_sha256": hashlib.sha256(
                (config_dir() / "appearance_decay_evaluation.yaml").read_bytes()
            ).hexdigest(),
        },
        "provenance": {
            "run_at": datetime.now(UTC).isoformat(),
            "git_head": _git_head(repo),
            "worktree_clean": True,
            "database": str(db_path),
            "folds_per_season": {s: len(f) for s, f in folds.items()},
            "population_rows": ineligible,
        },
        "training": {
            "seasonal": _summarise(training_rows_seasonal),
            "rostered_decay_by_c": {str(c): _summarise(training_by_c[c]) for c in grid},
        },
        "selected_c": selected_c,
        "held_out": {
            "season": held_out,
            "seasonal": seasonal_held,
            "rostered_decay_by_c": {str(c): _summarise(held_rows_decay[c]) for c in grid},
        },
        "gates": gates,
        "default_switch_authorised": bool(
            gates["held_out_pooled_log_loss_beats_seasonal"]
            and gates["held_out_gw7_20_log_loss_beats_seasonal"]
            and gates["gate3_within_2pct"]
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    db_path = args.db or default_db_path()
    output = args.output or (repo_root() / _RESULT_PATH)
    if output.exists():
        logger.error("immutable evaluation result already exists: %s", output)
        return 1
    summary = run(db_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".tmp")
    tmp.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    tmp.replace(output)
    logger.info("wrote %s", output)
    logger.info("selected c=%s gates=%s", summary["selected_c"], summary["gates"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
