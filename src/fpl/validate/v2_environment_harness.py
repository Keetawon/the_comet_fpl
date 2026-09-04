"""Walk-forward harness for the V2 football engine and the GK saves comparison.

One fold per observed gameweek, exactly as Phase 1: train on every team-match kicked off
before the gameweek's first kickoff, predict every team-fixture in it, advance. Gameweeks come
from the values present in the facts and never from `range(1, 39)` -- 2022-23 has no gameweek
7, and assuming contiguity misaligns that whole season's split by one.

Two things this harness must not do, and does not:

  * fit anything on the full dataset. Every decay, prior strength and blend weight is chosen
    on a holdout strictly inside the fold's own training window;
  * score a row whose outcome is unmeasured. A NULL is skipped and counted, never zero-filled.

The GK saves comparison runs inside the SAME fold loop, sharing the fold's football engine, so
V1 and V2 are scored on identical rows with identical training windows. Anything else would
make the comparison about the population rather than about the model.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import duckdb
import polars as pl

from fpl.models.football_engine_v2 import MultiSignalTeamEngine, SignalSpec
from fpl.models.gk_saves_v1 import GkSavesHistoryRow, GkSavesV1
from fpl.models.gk_saves_v2 import GkSavesV2
from fpl.types import Position
from fpl.validate.metrics import Distribution, crps, log_score, poisson_pmf, randomised_pit

# Columns the engine reads. Requested explicitly so a new mart column cannot silently become
# a feature without someone naming it here.
_TEAM_COLUMNS: tuple[str, ...] = (
    "season",
    "gw",
    "fixture",
    "kickoff_time",
    "team_code",
    "opponent_team_code",
    "was_home",
    "goals",
    "expected_goals",
    "expected_goals_on_target",
    "shots_on_target",
    "shots",
    "touches_in_opposition_box",
    "big_chances_created",
    "shots_on_target_allowed_proxy",
    "defensive_actions",
    # Opponent-facing measurements. The Phase 1 baselines need a conceded series, and reading
    # it off the mirrored column keeps their fit identical to what it was in Phase 1.
    "goals_allowed",
    "expected_goals_allowed",
    "expected_goals_conceded_measured",
)


@dataclass(frozen=True, slots=True)
class Prediction:
    """One scored prediction: the distribution, the outcome, and its slice keys."""

    season: str
    gw: int
    key: str
    distribution: Distribution
    observed: int
    was_home: bool
    cold_start: bool = False
    used_engine_signal: bool = False


@dataclass
class ScoreBlock:
    """Proper scores over a set of predictions, plus the honest denominator."""

    model: str
    rows: int = 0
    mean_log_score: float = 0.0
    crps: float = 0.0
    mean_absolute_error: float = 0.0
    mean_error: float = 0.0
    pit_interval_80_coverage: float = 0.0
    used_engine_signal_rows: int = 0

    def as_dict(self) -> dict[str, float | int | str]:
        return {
            "model": self.model,
            "rows": self.rows,
            "mean_log_score": round(self.mean_log_score, 6),
            "crps": round(self.crps, 6),
            "mean_absolute_error": round(self.mean_absolute_error, 6),
            "mean_error": round(self.mean_error, 6),
            "pit_interval_80_coverage": round(self.pit_interval_80_coverage, 6),
            "used_engine_signal_rows": self.used_engine_signal_rows,
        }


def score(name: str, predictions: Sequence[Prediction], *, seed: int = 20260904) -> ScoreBlock:
    """Score a set of predictions. Deterministic: the PIT generator is seeded per call."""
    import random

    block = ScoreBlock(model=name, rows=len(predictions))
    if not predictions:
        return block
    generator = random.Random(seed)
    logs: list[float] = []
    crps_values: list[float] = []
    absolute: list[float] = []
    signed: list[float] = []
    inside = 0
    for prediction in predictions:
        logs.append(log_score(prediction.distribution, prediction.observed))
        crps_values.append(crps(prediction.distribution, prediction.observed))
        mean = sum(index * mass for index, mass in enumerate(prediction.distribution))
        absolute.append(abs(mean - prediction.observed))
        signed.append(mean - prediction.observed)
        pit = randomised_pit(prediction.distribution, prediction.observed, generator)
        inside += int(0.1 <= pit <= 0.9)
        block.used_engine_signal_rows += int(prediction.used_engine_signal)
    block.mean_log_score = sum(logs) / len(logs)
    block.crps = sum(crps_values) / len(crps_values)
    block.mean_absolute_error = sum(absolute) / len(absolute)
    block.mean_error = sum(signed) / len(signed)
    block.pit_interval_80_coverage = inside / len(predictions)
    return block


def relative_lift(baseline: float, candidate: float) -> float:
    """Fractional improvement of a lower-is-better score. Positive means better."""
    if baseline == 0:
        return 0.0
    return (baseline - candidate) / abs(baseline)


@dataclass
class FoldOutcome:
    """Everything one fold produced, kept so a run can be reconciled after the fact."""

    season: str
    gw: int
    as_of: datetime
    training_rows: int
    team_predictions: dict[str, list[Prediction]] = field(default_factory=dict)
    saves_predictions: dict[str, list[Prediction]] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)


def load_team_frame(
    con: duckdb.DuckDBPyConnection, *, provider: str, seasons: Sequence[str] | None = None
) -> pl.DataFrame:
    """Team-match rows for one provider, keyed on the cross-season club identity."""
    predicate = ""
    params: list[object] = [provider]
    if seasons:
        predicate = f"AND season IN ({', '.join('?' for _ in seasons)})"
        params.extend(seasons)
    relation = con.execute(
        f"""
        SELECT {", ".join(f'"{c}"' for c in _TEAM_COLUMNS)}
        FROM mart_fact_team_match_stats_v2
        WHERE provider = ? AND team_code IS NOT NULL AND opponent_team_code IS NOT NULL
          AND gw IS NOT NULL {predicate}
        ORDER BY kickoff_time, season, fixture, team_code
        """,
        params,
    )
    return pl.from_arrow(relation.to_arrow_table())  # type: ignore[return-value]


def load_goalkeeper_frame(
    con: duckdb.DuckDBPyConnection, *, seasons: Sequence[str] | None = None
) -> pl.DataFrame:
    """Goalkeeper appearances with both saves components measured.

    The filter is the population definition from the contract, applied once here so every
    model in the comparison sees exactly the same rows.
    """
    predicate = ""
    params: list[object] = []
    if seasons:
        predicate = f"AND p.season IN ({', '.join('?' for _ in seasons)})"
        params.extend(seasons)
    relation = con.execute(
        f"""
        SELECT p.season, p.gw, p.fixture, p.kickoff_time, p.code, p.team_id, p.was_home,
               p.minutes, p.saves, p.goals_conceded,
               dt.team_code, dopp.team_code AS opponent_team_code
        FROM mart_fact_player_fixture AS p
        LEFT JOIN mart_dim_team AS dt ON dt.season = p.season AND dt.team_id = p.team_id
        LEFT JOIN mart_dim_team AS dopp
               ON dopp.season = p.season AND dopp.team_id = p.opponent_team_id
        WHERE p.position = 'GK' AND p.minutes > 0
          AND p.saves IS NOT NULL AND p.goals_conceded IS NOT NULL
          AND dt.team_code IS NOT NULL AND dopp.team_code IS NOT NULL {predicate}
        ORDER BY p.kickoff_time, p.season, p.fixture, p.code
        """,
        params,
    )
    return pl.from_arrow(relation.to_arrow_table())  # type: ignore[return-value]


def promoted_team_codes(con: duckdb.DuckDBPyConnection) -> dict[str, frozenset[int]]:
    """Season -> `team_code` of clubs not in the league the previous season.

    Which clubs came up is known before a ball is kicked, so using it at gameweek 1 is
    reference data rather than leakage. Keyed on `team_code` because `team_id` is reassigned.
    """
    rows = con.execute(
        """
        SELECT season, team_code FROM mart_dim_team
        WHERE team_code IS NOT NULL ORDER BY season, team_code
        """
    ).fetchall()
    by_season: dict[str, set[int]] = {}
    for season, team_code in rows:
        by_season.setdefault(str(season), set()).add(int(team_code))
    ordered = sorted(by_season)
    promoted: dict[str, frozenset[int]] = {}
    for index, season in enumerate(ordered):
        previous = by_season[ordered[index - 1]] if index else set()
        promoted[season] = frozenset(by_season[season] - previous) if index else frozenset()
    return promoted


def observed_folds(
    frame: pl.DataFrame, *, minimum_prior_gameweeks: int
) -> list[tuple[str, int, datetime]]:
    """`(season, gw, cutoff)` per scoreable fold, from the gameweeks actually present."""
    gameweeks = (
        frame.group_by(["season", "gw"], maintain_order=True)
        .agg(pl.col("kickoff_time").min().alias("cutoff"))
        .sort(["cutoff", "season", "gw"])
    )
    folds: list[tuple[str, int, datetime]] = []
    for index, row in enumerate(gameweeks.iter_rows(named=True)):
        if index < minimum_prior_gameweeks:
            continue
        folds.append((str(row["season"]), int(row["gw"]), row["cutoff"]))
    return folds


def run_team_environment(
    frame: pl.DataFrame,
    *,
    signals: Sequence[SignalSpec],
    promoted: dict[str, frozenset[int]],
    minimum_prior_gameweeks: int = 8,
    minimum_signal_coverage: float = 0.25,
    weight_step: float = 0.25,
    limit_folds: int | None = None,
) -> tuple[list[Prediction], list[dict[str, Any]]]:
    """Walk forward over the archive with one signal set. Returns predictions and fold params."""
    predictions: list[Prediction] = []
    fold_parameters: list[dict[str, Any]] = []
    folds = observed_folds(frame, minimum_prior_gameweeks=minimum_prior_gameweeks)
    if limit_folds is not None:
        folds = folds[-limit_folds:]
    for season, gw, cutoff in folds:
        training = frame.filter(pl.col("kickoff_time") < cutoff)
        target = frame.filter((pl.col("season") == season) & (pl.col("gw") == gw))
        if training.is_empty() or target.is_empty():
            continue
        engine = MultiSignalTeamEngine(
            signals=signals,
            minimum_signal_coverage=minimum_signal_coverage,
            weight_step=weight_step,
        )
        engine.set_promoted(promoted)
        engine.set_prediction_season(season)
        engine.fit(training)
        for row in target.iter_rows(named=True):
            goals = row["goals"]
            if goals is None:
                continue
            team = int(row["team_code"])
            opponent = int(row["opponent_team_code"])
            was_home = bool(row["was_home"])
            rate = engine.goal_rate(team, opponent, was_home)
            predictions.append(
                Prediction(
                    season=season,
                    gw=gw,
                    key=f"{season}:{row['fixture']}:{team}",
                    distribution=poisson_pmf(rate),
                    observed=int(goals),
                    was_home=was_home,
                    cold_start=engine.is_cold_start(team, opponent),
                )
            )
        fold_parameters.append(
            {
                "season": season,
                "gw": gw,
                "training_rows": training.height,
                **engine.parameters.as_report(),
            }
        )
    return predictions, fold_parameters


def run_gk_saves(
    team_frame: pl.DataFrame,
    goalkeeper_frame: pl.DataFrame,
    *,
    signals: Sequence[SignalSpec],
    promoted: dict[str, frozenset[int]],
    minimum_prior_gameweeks: int = 8,
    limit_folds: int | None = None,
) -> dict[str, list[Prediction]]:
    """Score V1 and V2 saves models on identical goalkeeper rows in one fold loop.

    Both models are fitted on the same fold history and both are evaluated on the same rows;
    the only difference is where the shot volume comes from.
    """
    results: dict[str, list[Prediction]] = {
        "gk_saves_v1_from_team_conceded": [],
        "gk_saves_v2_from_expected_shots_faced": [],
    }
    folds = observed_folds(team_frame, minimum_prior_gameweeks=minimum_prior_gameweeks)
    if limit_folds is not None:
        folds = folds[-limit_folds:]
    for season, gw, cutoff in folds:
        training = team_frame.filter(pl.col("kickoff_time") < cutoff)
        target = goalkeeper_frame.filter((pl.col("season") == season) & (pl.col("gw") == gw))
        if training.is_empty() or target.is_empty():
            continue
        engine = MultiSignalTeamEngine(signals=signals)
        engine.set_promoted(promoted)
        engine.set_prediction_season(season)
        engine.fit(training)

        history = [
            GkSavesHistoryRow(
                position=Position.GK,
                minutes=int(row["minutes"]),
                saves=None if row["saves"] is None else int(row["saves"]),
                goals_conceded=(
                    None if row["goals_conceded"] is None else int(row["goals_conceded"])
                ),
            )
            for row in goalkeeper_frame.filter(pl.col("kickoff_time") < cutoff).iter_rows(
                named=True
            )
        ]
        v1 = GkSavesV1()
        v1.fit(history)
        v2 = GkSavesV2()
        v2.fit(history)

        for row in target.iter_rows(named=True):
            team = int(row["team_code"])
            opponent = int(row["opponent_team_code"])
            was_home = bool(row["was_home"])
            observed = int(row["saves"])
            lambda_conceded = engine.goal_rate(opponent, team, not was_home)
            side = engine.fitted_signals
            shots_faced = None
            proxy = side.get("shots_on_target_allowed_proxy")
            if proxy is not None:
                shots_faced = proxy.rate(team, opponent, was_home, minimum_matches=3)
            key = f"{season}:{row['fixture']}:{row['code']}"
            results["gk_saves_v1_from_team_conceded"].append(
                Prediction(
                    season=season,
                    gw=gw,
                    key=key,
                    distribution=v1.predict(Position.GK, lambda_conceded),
                    observed=observed,
                    was_home=was_home,
                )
            )
            detail = v2.predict_detail(
                Position.GK,
                lambda_conceded=lambda_conceded,
                expected_shots_on_target_faced=shots_faced,
            )
            results["gk_saves_v2_from_expected_shots_faced"].append(
                Prediction(
                    season=season,
                    gw=gw,
                    key=key,
                    distribution=detail.distribution,
                    observed=observed,
                    was_home=was_home,
                    used_engine_signal=detail.used_expected_shots,
                )
            )
    return results


def score_by_season(
    name: str, predictions: Sequence[Prediction]
) -> dict[str, dict[str, float | int | str]]:
    """Per-season scores. A pooled figure has misled this repository three times."""
    seasons = sorted({prediction.season for prediction in predictions})
    return {
        season: score(name, [p for p in predictions if p.season == season]).as_dict()
        for season in seasons
    }


def score_by_slice(
    name: str, predictions: Sequence[Prediction]
) -> dict[str, dict[str, float | int | str]]:
    """Venue, cold-start and engine-coverage slices."""
    slices: dict[str, list[Prediction]] = {
        "home": [p for p in predictions if p.was_home],
        "away": [p for p in predictions if not p.was_home],
        "cold_start": [p for p in predictions if p.cold_start],
        "established": [p for p in predictions if not p.cold_start],
        "engine_signal_used": [p for p in predictions if p.used_engine_signal],
        "fallback_used": [p for p in predictions if not p.used_engine_signal],
    }
    return {label: score(name, rows).as_dict() for label, rows in slices.items() if rows}


def standard_error(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance / len(values))
