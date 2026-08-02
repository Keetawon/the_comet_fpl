"""Development-only runner for the hybrid BPS / bonus match-simulator. NOT a promotion evaluation.

    python -m fpl.validate.dev_bps_bonus_simulator                 # full archive, development only
    python -m fpl.validate.dev_bps_bonus_simulator --season 2025-26

This is the decision-gating deliverable: it measures how accurately bonus (3/2/1) can be predicted.
For every observed-gameweek walk-forward fold it reconstructs each appeared player's BPS as an
exact part (verified BPS values applied to the recorded match components) plus a fold-local,
point-in-time empirical residual (``influence``/``creativity`` and the player's trailing residual
profile), simulates the whole fixture's bonus jointly by Monte-Carlo ranking, and scores the
resulting bonus (0-3) marginal distribution against realised bonus (the label; ``total_points`` is
never read -- R1). It reports proper scores (log score, RPS), the share of realised bonus points
assigned to the right players ("how accurate"), and top-3 hit rates, overall and by season and
position.

It is **development-only and exploratory**: no promotion gate, no frozen contract, and it is NOT
integrated into the Stage D points composer. The exact part is computed from recorded components,
which isolates BPS-reconstruction accuracy (the hidden-Opta residual) from component-prediction
error; a production integration would feed predicted component distributions instead.

Provenance mirrors the Stage C dev runners: it refuses a dirty worktree, records the clean commit
SHA, the scoring-config fingerprint, the ``bps_bonus`` model-source fingerprint, the database
fingerprint, the seed, and UTC start/end, and re-verifies all of them after the database is closed;
if anything moved the result is suppressed as INVALID/UNPUBLISHABLE.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from fpl.config import BpsRules, config_dir, load_scoring_rules, repo_root
from fpl.models.bps_bonus import (
    BpsSimConfig,
    PlayerRow,
    PositionAccumulator,
    PositionalResidual,
    ResidualModel,
    exact_bps,
    positional_from_accumulator,
    simulate_fixture_bonus,
)
from fpl.storage.db import connect, default_db_path
from fpl.validate.bonus_metrics import BonusRecord, BonusScoreReport, score_bonus_predictions
from fpl.validate.folds import generate_folds

logger = logging.getLogger("fpl.validate.dev_bps_bonus_simulator")

_DEVELOPMENT_BANNER = (
    "\n"
    "============================================================================\n"
    " DEVELOPMENT ONLY -- NOT A PROMOTION RESULT\n"
    " Hybrid BPS / bonus match-simulator. Exploratory accuracy study of how well\n"
    " bonus (3/2/1) can be predicted. The exact part uses RECORDED components, so\n"
    " this isolates BPS-reconstruction accuracy from component-prediction error;\n"
    " it is not integrated into the Stage D points composer. No number below is a\n"
    " promotion verdict.\n"
    "============================================================================\n"
)

_POSITIONS: tuple[str, ...] = ("GK", "DEF", "MID", "FWD")
_RULESET = "2026_27"
_MODEL_SOURCE_REL = Path("src") / "fpl" / "models" / "bps_bonus.py"
_CONFIG_REL = Path("config") / "scoring_2026_27.yaml"
_DEFAULT_OUTPUT_REL = Path("docs") / "results" / "phase4-bps-bonus-simulator-development.json"


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def require_clean_worktree(repo: Path) -> None:
    porcelain = _git(repo, "status", "--porcelain")
    if porcelain:
        raise SystemExit(
            "The BPS/bonus simulator refuses to run on a dirty worktree. The recorded commit SHA "
            "must name the exact code that was scored. Commit or stash the following first:\n"
            + porcelain
        )


def head_commit_sha(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ProvenanceError(RuntimeError):
    """The (code, config, model-source, data) quadruple changed between capture and print."""


@dataclass(frozen=True, slots=True)
class Provenance:
    commit_sha: str
    config_fingerprint: str
    model_source_fingerprint: str
    database_fingerprint: str
    seed: int
    monte_carlo_draws: int
    started_at: str
    ended_at: str

    def as_lines(self) -> list[str]:
        return [
            "provenance",
            f"  commit sha            : {self.commit_sha}",
            f"  config fingerprint    : {self.config_fingerprint}",
            f"  model source fp       : {self.model_source_fingerprint}",
            f"  database fingerprint  : {self.database_fingerprint}",
            f"  seed                  : {self.seed}",
            f"  monte carlo draws     : {self.monte_carlo_draws}",
            f"  started at (UTC)      : {self.started_at}",
            f"  ended at (UTC)        : {self.ended_at}",
        ]


# --------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LoadedRow:
    season: str
    gw: int
    fixture: int
    kickoff_ts: float
    row: PlayerRow


def load_rows(con: duckdb.DuckDBPyConnection, bps: BpsRules) -> list[LoadedRow]:
    """Every appeared-or-not player-fixture row, chronological, with its residual precomputed.

    Assistant-manager elements (``element_type == 5``) never carry one of the four playing
    positions, so filtering to the four positions excludes them. Rows with a NULL minutes,
    ``bps``, or ``bonus`` cannot be ranked or scored and are dropped (NULL is unmeasured, never
    zero). ``clearances_blocks_interceptions`` NULL is preserved as ``None``.
    """
    frame = con.execute(
        """
        SELECT season, gw, fixture, kickoff_time, code, position, minutes, goals_scored,
               assists, clean_sheets, penalties_saved, clearances_blocks_interceptions,
               influence, creativity, bps, bonus
        FROM mart_fact_player_fixture
        WHERE position IN ('GK', 'DEF', 'MID', 'FWD')
          AND minutes IS NOT NULL AND bps IS NOT NULL AND bonus IS NOT NULL
        ORDER BY kickoff_time, season, fixture, code
        """
    ).pl()

    loaded: list[LoadedRow] = []
    for record in frame.iter_rows(named=True):
        kickoff: datetime = record["kickoff_time"]
        season = str(record["season"])
        fixture = int(record["fixture"])
        kickoff_ts = kickoff.timestamp()
        cbi = record["clearances_blocks_interceptions"]
        player_row = PlayerRow(
            code=int(record["code"]),
            position=str(record["position"]),
            minutes=int(record["minutes"]),
            goals_scored=int(record["goals_scored"]),
            assists=int(record["assists"]),
            clean_sheets=int(record["clean_sheets"]),
            penalties_saved=int(record["penalties_saved"]),
            clearances_blocks_interceptions=None if cbi is None else int(cbi),
            influence=float(record["influence"]),
            creativity=float(record["creativity"]),
            bps=int(record["bps"]),
            bonus=int(record["bonus"]),
            order_key=(kickoff_ts, season, fixture),
        )
        loaded.append(
            LoadedRow(
                season=season,
                gw=int(record["gw"]),
                fixture=fixture,
                kickoff_ts=kickoff_ts,
                row=player_row,
            )
        )
    return loaded


# --------------------------------------------------------------------------------------
# Walk-forward
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    records: list[BonusRecord]
    folds: int
    predictions: int
    fixtures: int
    cold_starts: int
    leakage_failures: int


def _build_model(
    accumulators: dict[str, PositionAccumulator],
    global_accumulator: PositionAccumulator,
    player_history: dict[int, list[float]],
    config: BpsSimConfig,
) -> ResidualModel:
    by_position: dict[str, PositionalResidual] = {}
    for position, accumulator in accumulators.items():
        if accumulator.n < config.minimum_position_rows:
            continue
        by_position[position] = positional_from_accumulator(
            accumulator,
            ridge_lambda=config.ridge_lambda,
            sigma_floor=config.sigma_floor,
            sd_floor=config.sd_floor,
        )
    fallback = positional_from_accumulator(
        global_accumulator,
        ridge_lambda=config.ridge_lambda,
        sigma_floor=config.sigma_floor,
        sd_floor=config.sd_floor,
    )
    return ResidualModel(
        by_position=by_position,
        fallback=fallback,
        player_history=player_history,
        prior_strength=config.prior_strength,
        trailing_window=config.trailing_window,
    )


def run_walk_forward(
    con: duckdb.DuckDBPyConnection,
    bps: BpsRules,
    config: BpsSimConfig,
    *,
    season_filter: str | None,
) -> WalkForwardResult:
    rows = load_rows(con, bps)
    by_gameweek: dict[tuple[str, int], list[LoadedRow]] = {}
    for loaded in rows:
        by_gameweek.setdefault((loaded.season, loaded.gw), []).append(loaded)

    folds = generate_folds(con)
    if season_filter is not None:
        folds = [fold for fold in folds if fold.season == season_filter]

    accumulators: dict[str, PositionAccumulator] = {
        position: PositionAccumulator() for position in _POSITIONS
    }
    global_accumulator = PositionAccumulator()
    player_history: dict[int, list[float]] = {}
    next_index = 0

    records: list[BonusRecord] = []
    total_predictions = 0
    total_fixtures = 0
    cold_starts = 0
    leakage_failures = 0

    for fold in folds:
        as_of_ts = fold.as_of.timestamp()
        # Advance the expanding training window to everything strictly before the cutoff.
        while next_index < len(rows) and rows[next_index].kickoff_ts < as_of_ts:
            loaded = rows[next_index]
            if loaded.row.appeared:
                residual = loaded.row.bps - exact_bps(loaded.row, bps)
                accumulators[loaded.row.position].add(
                    residual, loaded.row.influence, loaded.row.creativity
                )
                global_accumulator.add(residual, loaded.row.influence, loaded.row.creativity)
                player_history.setdefault(loaded.row.code, []).append(residual)
            next_index += 1

        model = _build_model(accumulators, global_accumulator, player_history, config)

        target_rows = by_gameweek.get((fold.season, fold.gw), [])
        by_fixture: dict[int, list[LoadedRow]] = {}
        for loaded in target_rows:
            if loaded.kickoff_ts < as_of_ts:
                leakage_failures += 1
                continue
            by_fixture.setdefault(loaded.fixture, []).append(loaded)

        for fixture, fixture_rows in by_fixture.items():
            simulation = simulate_fixture_bonus(
                [loaded.row for loaded in fixture_rows],
                model,
                bps,
                config,
                fixture_seed=config.seed + int(fold.season[:4]) * 100_000 + fixture,
            )
            if not simulation.predictions:
                continue
            total_fixtures += 1
            for prediction in simulation.predictions:
                if not player_history.get(prediction.code):
                    cold_starts += 1
                records.append(
                    BonusRecord(
                        season=fold.season,
                        fixture=fixture,
                        code=prediction.code,
                        position=prediction.position,
                        distribution=prediction.distribution,
                        expected_bonus=prediction.expected_bonus,
                        realised_bonus=prediction.realised_bonus,
                    )
                )
                total_predictions += 1

    return WalkForwardResult(
        records=records,
        folds=len(folds),
        predictions=total_predictions,
        fixtures=total_fixtures,
        cold_starts=cold_starts,
        leakage_failures=leakage_failures,
    )


# --------------------------------------------------------------------------------------
# Scoring, slicing, reconciliation
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SlicedReports:
    overall: BonusScoreReport
    by_season: dict[str, BonusScoreReport]
    by_position: dict[str, BonusScoreReport]


def score_all(records: Sequence[BonusRecord], *, seed: int) -> SlicedReports:
    overall = score_bonus_predictions(records, label="overall", seed=seed)
    seasons = sorted({record.season for record in records})
    by_season = {
        season: score_bonus_predictions(
            [record for record in records if record.season == season], label=season, seed=seed
        )
        for season in seasons
    }
    by_position = {
        position: score_bonus_predictions(
            [record for record in records if record.position == position],
            label=position,
            seed=seed,
            include_fixture_metrics=False,
        )
        for position in _POSITIONS
        if any(record.position == position for record in records)
    }
    return SlicedReports(overall=overall, by_season=by_season, by_position=by_position)


def reconcile(reports: SlicedReports) -> list[str]:
    """Independent partition checks. Seasons and positions each partition the predictions."""
    failures: list[str] = []
    overall = reports.overall

    season_predictions = sum(report.predictions for report in reports.by_season.values())
    if season_predictions != overall.predictions:
        failures.append(f"season predictions {season_predictions} != overall {overall.predictions}")
    position_predictions = sum(report.predictions for report in reports.by_position.values())
    if position_predictions != overall.predictions:
        failures.append(
            f"position predictions {position_predictions} != overall {overall.predictions}"
        )

    season_bonus = sum(report.total_realised_bonus for report in reports.by_season.values())
    if abs(season_bonus - overall.total_realised_bonus) > 1e-6:
        failures.append(
            f"season realised bonus {season_bonus} != overall {overall.total_realised_bonus}"
        )
    position_bonus = sum(report.total_realised_bonus for report in reports.by_position.values())
    if abs(position_bonus - overall.total_realised_bonus) > 1e-6:
        failures.append(
            f"position realised bonus {position_bonus} != overall {overall.total_realised_bonus}"
        )

    season_fixtures = sum(report.fixtures for report in reports.by_season.values())
    if season_fixtures != overall.fixtures:
        failures.append(f"season fixtures {season_fixtures} != overall {overall.fixtures}")
    return failures


# --------------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------------


def _report_lines(
    reports: SlicedReports, result: WalkForwardResult, hidden_share: float
) -> list[str]:
    lines: list[str] = [
        _DEVELOPMENT_BANNER,
        "hybrid BPS / bonus match-simulator -- development-only",
        "",
    ]
    overall = reports.overall
    lines.append(
        f"folds={result.folds}  fixtures={overall.fixtures}  predictions={overall.predictions}  "
        f"cold_starts={result.cold_starts}  leakage_failures={result.leakage_failures}"
    )
    lines.append(
        f"hidden-Opta share of realised bonus (unreachable by exact part): {hidden_share:.3%}"
    )
    lines.append("")
    header = (
        f"{'slice':<10}{'preds':>8}{'fixt':>7}{'logscore':>11}{'rps':>9}"
        f"{'assigned':>10}{'assign_hd':>10}{'top1':>8}{'top3ovl':>9}{'podium':>8}"
    )
    lines.append("OVERALL / BY SEASON / BY POSITION")
    lines.append(header)

    def row_line(report: BonusScoreReport) -> str:
        prefix = (
            f"{report.label:<10}{report.predictions:>8}{report.fixtures:>7}"
            f"{report.mean_log_score:>11.5f}{report.mean_ranked_probability_score:>9.5f}"
            f"{report.bonus_points_correctly_assigned:>10.4f}"
        )
        if not report.fixture_metrics_valid:
            # Per-position slices do not form complete fixtures; the rank metrics are omitted.
            return prefix + f"{'n/a':>10}{'n/a':>8}{'n/a':>9}{'n/a':>8}"
        return (
            prefix
            + f"{report.bonus_points_correctly_assigned_hard:>10.4f}"
            + f"{report.top1_hit_rate:>8.4f}{report.top3_overlap_rate:>9.4f}"
            + f"{report.exact_podium_rate:>8.4f}"
        )

    lines.append(row_line(overall))
    for season in sorted(reports.by_season):
        lines.append(row_line(reports.by_season[season]))
    lines.append("(per-position rank metrics omitted -- a position is not a complete fixture)")
    for position in _POSITIONS:
        if position in reports.by_position:
            lines.append(row_line(reports.by_position[position]))
    lines.append("")
    lines.append(
        "HEADLINE: expected share of realised bonus points assigned to the right players = "
        f"{overall.bonus_points_correctly_assigned:.2%}  "
        f"(hard-podium {overall.bonus_points_correctly_assigned_hard:.2%}); "
        f"top-1 (3-pt winner) hit rate {overall.top1_hit_rate:.2%}; "
        f"top-3 overlap {overall.top3_overlap_rate:.2%}."
    )
    return lines


def _report_dict(report: BonusScoreReport) -> dict[str, float | int | str]:
    return report.as_row()


def build_json(
    reports: SlicedReports,
    result: WalkForwardResult,
    provenance: Provenance,
    hidden_share: float,
    reconciliation_failures: Sequence[str],
) -> dict[str, object]:
    return {
        "deliverable": "phase4-bps-bonus-simulator",
        "status": "DEVELOPMENT ONLY -- NOT A PROMOTION RESULT",
        "description": (
            "Hybrid BPS/bonus match-simulator. Exact part from verified 2026/27 BPS values applied "
            "to recorded components + fold-local point-in-time empirical residual; per-fixture "
            "Monte-Carlo bonus ranking. Scored against realised bonus (0-3). Not integrated into "
            "the Stage D points composer."
        ),
        "provenance": {
            "commit_sha": provenance.commit_sha,
            "config_sha256": provenance.config_fingerprint,
            "model_source_sha256": provenance.model_source_fingerprint,
            "database_sha256": provenance.database_fingerprint,
            "seed": provenance.seed,
            "monte_carlo_draws": provenance.monte_carlo_draws,
            "started_at_utc": provenance.started_at,
            "ended_at_utc": provenance.ended_at,
        },
        "counts": {
            "folds": result.folds,
            "fixtures": result.fixtures,
            "predictions": result.predictions,
            "cold_starts": result.cold_starts,
            "leakage_failures": result.leakage_failures,
        },
        "hidden_opta_share_of_realised_bonus": round(hidden_share, 5),
        "reconciliation_failures": list(reconciliation_failures),
        "overall": _report_dict(reports.overall),
        "by_season": {
            season: _report_dict(report) for season, report in sorted(reports.by_season.items())
        },
        "by_position": {
            position: _report_dict(reports.by_position[position])
            for position in _POSITIONS
            if position in reports.by_position
        },
    }


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def _hidden_share_from_rows(con: duckdb.DuckDBPyConnection, season_filter: str | None) -> float:
    predicate = "AND season = ?" if season_filter else ""
    params = [season_filter] if season_filter else []
    row = con.execute(
        f"""
        WITH b AS (
            SELECT bonus, goals_scored, assists, clean_sheets, minutes
            FROM mart_fact_player_fixture
            WHERE bonus IS NOT NULL AND bonus > 0 AND minutes > 0 {predicate}
        )
        SELECT
            sum(bonus) AS total,
            sum(CASE WHEN goals_scored > 0 OR assists > 0 THEN 0
                     WHEN clean_sheets > 0 AND minutes >= 60 THEN 0
                     ELSE bonus END) AS hidden
        FROM b
        """,
        params,
    ).fetchone()
    if not row or not row[0]:
        return 0.0
    return float(row[1]) / float(row[0])


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(
        description="Development-only hybrid BPS/bonus match-simulator."
    )
    parser.add_argument("--season", default=None, help="restrict scored folds to one season")
    parser.add_argument("--draws", type=int, default=None, help="override Monte-Carlo draws")
    parser.add_argument("--output", default=None, help="JSON output path")
    parser.add_argument("--db", default=None, help="database path (read-only)")
    args = parser.parse_args(argv)

    repo = repo_root()
    require_clean_worktree(repo)

    db_path = Path(args.db) if args.db else default_db_path()
    config_path = config_dir() / "scoring_2026_27.yaml"
    model_source = repo / _MODEL_SOURCE_REL
    output_path = Path(args.output) if args.output else repo / _DEFAULT_OUTPUT_REL

    rules = load_scoring_rules(_RULESET)
    if rules.bps is None:
        raise SystemExit("scoring_2026_27.yaml has no bps block; nothing to simulate")
    bps = rules.bps

    config = BpsSimConfig()
    if args.draws is not None:
        config = BpsSimConfig(monte_carlo_draws=args.draws)

    commit_sha = head_commit_sha(repo)
    config_fp = file_sha256(config_path)
    model_fp = file_sha256(model_source)
    database_fp = file_sha256(db_path)
    started_at = _utc_now()

    con = connect(db_path, read_only=True)
    try:
        result = run_walk_forward(con, bps, config, season_filter=args.season)
        hidden_share = _hidden_share_from_rows(con, args.season)
    finally:
        con.close()
    ended_at = _utc_now()

    # Post-run provenance verification: nothing may have moved during the run.
    if _git(repo, "status", "--porcelain"):
        raise ProvenanceError(
            "worktree became dirty during the run; result is INVALID/UNPUBLISHABLE"
        )
    if head_commit_sha(repo) != commit_sha:
        raise ProvenanceError("HEAD changed during the run; result is INVALID/UNPUBLISHABLE")
    if file_sha256(config_path) != config_fp:
        raise ProvenanceError("config fingerprint changed during the run; INVALID/UNPUBLISHABLE")
    if file_sha256(model_source) != model_fp:
        raise ProvenanceError(
            "model source fingerprint changed during the run; INVALID/UNPUBLISHABLE"
        )
    if file_sha256(db_path) != database_fp:
        raise ProvenanceError("database fingerprint changed during the run; INVALID/UNPUBLISHABLE")

    provenance = Provenance(
        commit_sha=commit_sha,
        config_fingerprint=config_fp,
        model_source_fingerprint=model_fp,
        database_fingerprint=database_fp,
        seed=config.seed,
        monte_carlo_draws=config.monte_carlo_draws,
        started_at=started_at,
        ended_at=ended_at,
    )

    reports = score_all(result.records, seed=config.seed)
    reconciliation_failures = reconcile(reports)

    for line in _report_lines(reports, result, hidden_share):
        print(line)
    print()
    for line in provenance.as_lines():
        print(line)
    print()
    if reconciliation_failures:
        print(f"RECONCILIATION FAILURES ({len(reconciliation_failures)}):")
        for failure in reconciliation_failures:
            print(f"  - {failure}")
    else:
        print("reconciliation: 0 failures (season and position partitions agree with overall)")
    if result.leakage_failures:
        print(f"WARNING: {result.leakage_failures} leakage failures detected")

    payload = build_json(reports, result, provenance, hidden_share, reconciliation_failures)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\nwrote {output_path}")

    return 1 if (reconciliation_failures or result.leakage_failures) else 0


if __name__ == "__main__":
    sys.exit(main())
