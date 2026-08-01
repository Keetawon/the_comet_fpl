"""Run the Stage B (player minutes) walk-forward defined by `config/phase2_evaluation.yaml`.

    python -m fpl.validate.minutes_harness                 # every baseline, every fold
    python -m fpl.validate.minutes_harness --season 2025-26

Stage B predicts a four-bin minutes distribution over the registered FPL player population at
`(season, code, fixture)` grain. This harness is **baselines-only**: it fits and refits the four
frozen baselines inside every fold and scores them on identical rows. No candidate is fitted and
no promotion gate is executed here -- that is explicitly deferred to a separately-named change
once a candidate exists. The historical number it would produce is a development number, not an
upper bound.

Like the Stage A harness, this module reads outcomes (the `minutes` label), which the feature
layer may not. Scoring a prediction needs the label, and the label is exactly what a feature must
never see. Training history is restricted to `kickoff_time < as_of` by the fold, every fold
asserts its own gameweek is invisible before it is used, and the label is split from the
nine-column `TargetRow` before any baseline sees a row.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import duckdb
import polars as pl

from fpl.config import Phase2EvaluationConfig, load_phase2_evaluation
from fpl.features.pit import AsOf, FeatureSource, PointInTimeView
from fpl.storage.db import connect
from fpl.types import Position
from fpl.validate.minutes_baselines import (
    STAGE_B_BASELINE_ORDER,
    HistoryRow,
    MinuteBins,
    MinutesDistribution,
    TargetRow,
    TeamCodeMap,
    baseline_names,
    build_minutes_baselines,
    validate_minutes_inputs,
)
from fpl.validate.minutes_metrics import MinutesScoreReport, score_minutes_predictions

logger = logging.getLogger("fpl.validate.minutes_harness")

# The exact columns the model may see on a target row (the contract's nine-column proxy). The
# minutes label is selected alongside but split off before any baseline touches a TargetRow.
_TARGET_COLUMNS = (
    "season",
    "gw",
    "fixture",
    "kickoff_time",
    "code",
    "position",
    "team_id",
    "opponent_team_id",
    "was_home",
)

# The chronological key every history frame is sorted on. The tuple is unique per player-fixture
# (a shared season+fixture implies distinct codes), so the order is deterministic without relying
# on sort stability -- which matters because the live union concatenates two sources.
_HISTORY_ORDER = ("kickoff_time", "season", "fixture", "code")

# transfer_status values: fold-local, PIT-safe comparisons against the most recent PRIOR row's club.
TRANSFER_NO_PRIOR = "no_prior_player_fixture"
TRANSFER_SAME = "same_team_code_as_last_observed_fixture"
TRANSFER_CHANGED = "changed_team_code_since_last_observed_fixture"

# player_history_cohort values, and the cold-start rule (the first two cohorts are cold starts).
COHORT_NO_PRIOR = "no_prior_player_fixture"
COHORT_NO_POSITIVE = "prior_player_fixtures_no_positive_minutes"
COHORT_PRIOR_POSITIVE = "prior_positive_minutes"
_COLD_COHORTS = frozenset({COHORT_NO_PRIOR, COHORT_NO_POSITIVE})

# --------------------------------------------------------------------------------------
# Candidate integration (development-only, opt-in)
# --------------------------------------------------------------------------------------


class MinutesCandidate(Protocol):
    """A fold-local fitted minutes predictor with the baseline ``predict`` / ``parameters`` shape.

    A Stage B candidate is fitted inside :func:`run_minutes_fold` on the exact validated history
    the baselines use, so it is scored on the identical eligible rows. The harness never imports a
    candidate model: a development runner supplies a factory returning an object conforming to this
    protocol. The default harness path passes no factory and is unchanged.
    """

    name: str

    def predict(self, target: TargetRow) -> MinutesDistribution: ...

    def parameters(self) -> Mapping[str, float | int | bool | str]: ...


# Fits one candidate on a fold's validated history and returns its fitted predictor. Optional and
# opt-in; the default baselines-only CLI supplies no factory.
MinutesCandidateFactory = Callable[[tuple[HistoryRow, ...], datetime], MinutesCandidate]

# --------------------------------------------------------------------------------------
# Folds over observed gameweeks
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MinutesFold:
    """One Stage B walk-forward step: predict `season`/`gw` using only data before `as_of`."""

    index: int
    season: str
    gw: int
    as_of: datetime
    prior_observed_gameweeks: int
    target_rows: int

    def __str__(self) -> str:
        return f"fold {self.index:3d}  {self.season} GW{self.gw:2d}  as_of={self.as_of:%Y-%m-%d}"


def _observed_player_gameweeks(con: duckdb.DuckDBPyConnection, season: str) -> list[int]:
    """Gameweeks actually present in the player facts for a season, in order.

    Sourced from `minutes IS NOT NULL` rows, so a gameweek with only NULL-minute rows (none in
    this archive) would not appear. Never `range(1, 39)`: 2022-23 has no GW7.
    """
    return [
        int(row[0])
        for row in con.execute(
            """
            SELECT DISTINCT gw FROM mart_fact_player_fixture
            WHERE season = ? AND minutes IS NOT NULL ORDER BY gw
            """,
            [season],
        ).fetchall()
    ]


def _observed_player_seasons(con: duckdb.DuckDBPyConnection) -> list[str]:
    return [
        str(row[0])
        for row in con.execute(
            """
            SELECT DISTINCT season FROM mart_fact_player_fixture
            WHERE minutes IS NOT NULL ORDER BY season
            """
        ).fetchall()
    ]


def generate_minutes_folds(
    con: duckdb.DuckDBPyConnection, config: Phase2EvaluationConfig | None = None
) -> list[MinutesFold]:
    """Every scoreable Stage B walk-forward fold across the archive.

    A gameweek becomes a fold once the expanding training window holds at least
    `training.minimum_observed_gameweeks` observed gameweeks, counted ACROSS SEASONS. Counting
    within a season instead is the Phase 1 bug: it would drop every season's opening gameweeks,
    which is exactly the cold-start regime the minutes fallback exists for.
    """
    resolved = config or load_phase2_evaluation()
    minimum = resolved.training.minimum_observed_gameweeks

    seasons = _observed_player_seasons(con)

    # Cumulative observed-gameweek count before each season begins. The expanding window is
    # counted across seasons, not within them.
    gameweeks_before: dict[str, int] = {}
    completed = 0
    for season in seasons:
        gameweeks_before[season] = completed
        completed += len(_observed_player_gameweeks(con, season))

    folds: list[MinutesFold] = []
    for season in seasons:
        gameweeks = _observed_player_gameweeks(con, season)
        for position, gw in enumerate(gameweeks):
            if gameweeks_before[season] + position < minimum:
                continue
            # Arrow/Polars path: DuckDB's Python TIMESTAMPTZ conversion needs pytz, which this
            # project does not depend on, while Arrow carries the timezone natively.
            frame = con.execute(
                """
                SELECT min(kickoff_time) AS as_of,
                       count(*) FILTER (WHERE minutes IS NOT NULL) AS target_rows
                FROM mart_fact_player_fixture
                WHERE season = ? AND gw = ?
                """,
                [season, gw],
            ).pl()
            if frame.is_empty() or frame["as_of"][0] is None:
                continue
            folds.append(
                MinutesFold(
                    index=len(folds) + 1,
                    season=season,
                    gw=gw,
                    as_of=frame["as_of"][0],
                    prior_observed_gameweeks=gameweeks_before[season] + position,
                    target_rows=int(frame["target_rows"][0]),
                )
            )
    return folds


def assert_no_minutes_leakage(con: duckdb.DuckDBPyConnection, fold: MinutesFold) -> None:
    """No predicted-GW player row may kick off before `as_of`.

    `as_of` is the gameweek's first kickoff, so under a correct fold this is zero by
    construction. The assertion exists to fail loudly if a fold is ever mis-built; it is the
    Stage B analogue of the gate's `require_zero_leakage_failures`.
    """
    leaked = con.execute(
        """
        SELECT count(*) AS leaked FROM mart_fact_player_fixture
        WHERE season = ? AND gw = ? AND kickoff_time < ?
        """,
        [fold.season, fold.gw, fold.as_of],
    ).pl()["leaked"][0]
    if leaked:
        raise AssertionError(
            f"{fold}: {leaked} of the gameweek's own player-fixtures kick off before as_of, so "
            "they would be visible to training"
        )


# --------------------------------------------------------------------------------------
# Stable team identity: built from mart_dim_team only
# --------------------------------------------------------------------------------------


def team_code_map(con: duckdb.DuckDBPyConnection) -> TeamCodeMap:
    """The only path from a row's season-qualified `team_id` to the stable `team_code`.

    Built from `mart_dim_team` rows with a non-NULL `team_code`. A duplicated
    `(season, team_id)` is rejected by `TeamCodeMap.from_pairs`; an unresolved mapping for a
    target/history row is rejected when that row is validated. Never `mart_dim_player.team_id`.
    """
    pairs = con.execute(
        "SELECT season, team_id, team_code FROM mart_dim_team WHERE team_code IS NOT NULL"
    ).fetchall()
    return TeamCodeMap.from_pairs(
        (str(season), int(team_id), int(team_code)) for season, team_id, team_code in pairs
    )


# --------------------------------------------------------------------------------------
# Fold-local row construction: history, targets, and the label/proxy split
# --------------------------------------------------------------------------------------


def _column_lists(frame: pl.DataFrame) -> dict[str, list[Any]]:
    """The nine proxy columns plus `minutes`, as plain Python lists."""
    wanted = [*_TARGET_COLUMNS, "minutes"]
    return {name: frame[name].to_list() for name in wanted}


def _history_rows(frame: pl.DataFrame) -> list[HistoryRow]:
    """Build typed history rows (with the minutes label) from a Polars frame.

    Positions are converted through `Position.from_archive_label` (canonicalises `GKP`, rejects
    the manager element). Explicit kwargs -- not a `**dict` spread -- so the types are checked.
    """
    columns = _column_lists(frame)
    positions = [Position.from_archive_label(str(value)) for value in columns["position"]]
    kickoffs = columns["kickoff_time"]
    rows: list[HistoryRow] = []
    for index in range(len(columns["season"])):
        rows.append(
            HistoryRow(
                season=str(columns["season"][index]),
                gw=int(columns["gw"][index]),
                fixture=int(columns["fixture"][index]),
                kickoff_time=kickoffs[index],
                code=int(columns["code"][index]),
                position=positions[index],
                team_id=int(columns["team_id"][index]),
                opponent_team_id=int(columns["opponent_team_id"][index]),
                was_home=bool(columns["was_home"][index]),
                minutes=int(columns["minutes"][index]),
            )
        )
    return rows


def _target_rows(frame: pl.DataFrame) -> tuple[list[TargetRow], list[int]]:
    """Build typed target rows and the minutes label, held apart.

    The rows are plain `TargetRow` (the nine-column proxy, no minutes); the labels are returned
    in parallel so a baseline never sees the outcome on a target record. Explicit kwargs keep the
    construction type-checked.
    """
    columns = _column_lists(frame)
    positions = [Position.from_archive_label(str(value)) for value in columns["position"]]
    kickoffs = columns["kickoff_time"]
    rows: list[TargetRow] = []
    labels: list[int] = []
    for index in range(len(columns["season"])):
        rows.append(
            TargetRow(
                season=str(columns["season"][index]),
                gw=int(columns["gw"][index]),
                fixture=int(columns["fixture"][index]),
                kickoff_time=kickoffs[index],
                code=int(columns["code"][index]),
                position=positions[index],
                team_id=int(columns["team_id"][index]),
                opponent_team_id=int(columns["opponent_team_id"][index]),
                was_home=bool(columns["was_home"][index]),
            )
        )
        labels.append(int(columns["minutes"][index]))
    return rows, labels


def player_fixture_history(con: duckdb.DuckDBPyConnection, *, as_of: datetime) -> list[HistoryRow]:
    """Every eligible prior player-fixture (minutes non-null, kickoff < as_of), including zeros.

    The single builder for a fold's (or a prospective run's) training history: prior eligible
    rows under the strict cutoff, with the minutes label. Shared by the walk-forward folds and
    the prospective minutes job so the two cannot drift on what "history" means.

    Sourced through the point-in-time union (`PointInTimeView.observed_player_fixtures`): prior
    seasons come from the archive by `kickoff_time < as_of`, and the current season comes from
    the versioned live table as the newest `known_at <= as_of` version per `(season, code,
    fixture)`. When the live table is absent or empty -- the historical-backtest case -- the
    union is a no-op and the rows are byte-identical to the archive-only read. `as_of` must be
    timezone-aware (enforced by `AsOf`), matching what both callers already pass.
    """
    columns = (*_TARGET_COLUMNS, "minutes")
    view = PointInTimeView(FeatureSource(con), AsOf(as_of))
    frame = view.observed_player_fixtures(columns=columns)
    frame = frame.filter(pl.col("minutes").is_not_null()).sort(_HISTORY_ORDER)
    return _history_rows(frame)


def _training_history(con: duckdb.DuckDBPyConnection, fold: MinutesFold) -> list[HistoryRow]:
    return player_fixture_history(con, as_of=fold.as_of)


def _fold_targets(
    con: duckdb.DuckDBPyConnection, fold: MinutesFold
) -> tuple[list[TargetRow], list[int]]:
    """The predicted gameweek's eligible rows, as TargetRows plus the minutes label held apart."""
    select = ", ".join((*_TARGET_COLUMNS, "minutes"))
    frame = con.execute(
        f"""
        SELECT {select} FROM mart_fact_player_fixture
        WHERE season = ? AND gw = ? AND minutes IS NOT NULL
        ORDER BY kickoff_time, fixture, code
        """,
        [fold.season, fold.gw],
    ).pl()
    return _target_rows(frame)


# --------------------------------------------------------------------------------------
# Fold-local, PIT-safe cohort / transfer / cold-start derivation
# --------------------------------------------------------------------------------------


def _prior_by_code(history: Sequence[HistoryRow]) -> dict[int, list[HistoryRow]]:
    """`code -> prior rows`, most-recent-first (kickoff DESC, season DESC, fixture DESC).

    The same recency order the baselines use, so "the most recent prior fact-row club" is the
    first element. Derived from prior history only, so it is point-in-time safe by construction.
    """
    ordered = sorted(history, key=lambda r: (r.kickoff_time, r.season, r.fixture), reverse=True)
    by_code: dict[int, list[HistoryRow]] = {}
    for row in ordered:
        by_code.setdefault(row.code, []).append(row)
    return by_code


def _cohort(prior_rows: Sequence[HistoryRow]) -> str:
    if not prior_rows:
        return COHORT_NO_PRIOR
    if any(row.minutes > 0 for row in prior_rows):
        return COHORT_PRIOR_POSITIVE
    return COHORT_NO_POSITIVE


def _transfer_status(
    target: TargetRow,
    prior_rows: Sequence[HistoryRow],
    team_codes: TeamCodeMap,
) -> str:
    if not prior_rows:
        return TRANSFER_NO_PRIOR
    last = prior_rows[0]
    target_code = team_codes.code(target.season, target.team_id)
    last_code = team_codes.code(last.season, last.team_id)
    return TRANSFER_SAME if target_code == last_code else TRANSFER_CHANGED


# --------------------------------------------------------------------------------------
# One fold
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MinutesPredictionRecord:
    """One scored prediction, carrying the slice keys the contract reports on."""

    distribution: MinutesDistribution
    observed_bin: int
    fold: str
    season: str
    position: Position
    home_away: str
    transfer_status: str
    player_history_cohort: str
    cold_start: bool
    rank_group: str


@dataclass(frozen=True, slots=True)
class MinutesFoldPredictions:
    fold: MinutesFold
    targets: tuple[TargetRow, ...]
    observed_bins: tuple[int, ...]
    by_baseline: dict[str, tuple[MinutesDistribution, ...]]
    transfer_status: tuple[str, ...]
    player_history_cohort: tuple[str, ...]
    cold_starts: tuple[bool, ...]
    home_away: tuple[str, ...]
    positions: tuple[Position, ...]
    rank_groups: tuple[str, ...]
    # Candidate predictions (development-only). Empty unless a candidate factory was supplied, so
    # the default baselines-only path is unchanged. Candidate predictions carry the same observed
    # bin and slice keys as the baselines, so they are scored and sliced on identical eligible rows.
    by_candidate: dict[str, tuple[MinutesDistribution, ...]] = field(default_factory=dict)
    candidate_parameters: dict[str, dict[str, float | int | bool | str]] = field(
        default_factory=dict
    )


def run_minutes_fold(
    con: duckdb.DuckDBPyConnection,
    fold: MinutesFold,
    *,
    bins: MinuteBins,
    config: Phase2EvaluationConfig,
    candidate_factory: MinutesCandidateFactory | None = None,
) -> MinutesFoldPredictions | None:
    """Fit all four baselines on the fold's training window and predict its gameweek.

    Returns ``None`` only if the gameweek has no eligible targets (no minutes-not-null rows),
    which does not occur on the archive but is handled defensively.
    """
    assert_no_minutes_leakage(con, fold)

    history = _training_history(con, fold)
    targets, labels = _fold_targets(con, fold)
    if not targets:
        return None

    team_codes = team_code_map(con)
    # Validate before fitting: grain uniqueness, strict cutoff, NULL/range minutes, Position, and
    # that every (season, team_id) resolves to a team_code. The label is already split off the
    # targets, so baselines never see `minutes` on a TargetRow.
    validated_history, validated_targets = validate_minutes_inputs(
        history, targets, as_of=fold.as_of, team_codes=team_codes, bins=bins
    )

    baselines = build_minutes_baselines(
        validated_history, as_of=fold.as_of, team_codes=team_codes, bins=bins
    )
    if [baseline.name for baseline in baselines] != list(STAGE_B_BASELINE_ORDER):
        raise RuntimeError(
            "build_minutes_baselines returned baselines out of contract order: "
            f"{[b.name for b in baselines]}"
        )

    by_baseline: dict[str, tuple[MinutesDistribution, ...]] = {}
    for baseline in baselines:
        predicted = tuple(baseline.predict(target) for target in validated_targets)
        if len(predicted) != len(validated_targets):
            raise RuntimeError(
                f"{baseline.name} returned {len(predicted)} predictions for "
                f"{len(validated_targets)} eligible targets"
            )
        by_baseline[baseline.name] = predicted

    # Fold-local, PIT-safe per-target metadata, derived from prior history only.
    prior_by_code = _prior_by_code(validated_history)
    transfer: list[str] = []
    cohort: list[str] = []
    cold: list[bool] = []
    home_away: list[str] = []
    positions: list[Position] = []
    rank_groups: list[str] = []
    observed_bins: list[int] = []
    for target, label in zip(validated_targets, labels, strict=True):
        prior_rows = prior_by_code.get(target.code, [])
        cohort_value = _cohort(prior_rows)
        transfer_value = _transfer_status(target, prior_rows, team_codes)
        transfer.append(transfer_value)
        cohort.append(cohort_value)
        cold.append(cohort_value in _COLD_COHORTS)
        home_away.append("home" if target.was_home else "away")
        positions.append(target.position)
        rank_groups.append(f"{target.season}-{target.gw}-{target.position}")
        observed_bins.append(bins.index_of(label))

    by_candidate: dict[str, tuple[MinutesDistribution, ...]] = {}
    candidate_parameters: dict[str, dict[str, float | int | bool | str]] = {}
    if candidate_factory is not None:
        # Fit the candidate on the SAME validated history the baselines used and predict the SAME
        # targets, so identical eligible rows is structural rather than aspirational. The label
        # never reaches the candidate: validated_targets are label-free TargetRow objects.
        fitted = candidate_factory(validated_history, fold.as_of)
        if fitted.name in by_baseline:
            raise RuntimeError(
                f"development candidate name {fitted.name!r} collides with a required "
                "Stage B baseline"
            )
        candidate_predicted = tuple(fitted.predict(target) for target in validated_targets)
        if len(candidate_predicted) != len(validated_targets):
            raise RuntimeError(
                f"{fitted.name} returned {len(candidate_predicted)} predictions for "
                f"{len(validated_targets)} eligible targets"
            )
        by_candidate[fitted.name] = candidate_predicted
        candidate_parameters[fitted.name] = dict(fitted.parameters())

    return MinutesFoldPredictions(
        fold=fold,
        targets=validated_targets,
        observed_bins=tuple(observed_bins),
        by_baseline=by_baseline,
        transfer_status=tuple(transfer),
        player_history_cohort=tuple(cohort),
        cold_starts=tuple(cold),
        home_away=tuple(home_away),
        positions=tuple(positions),
        rank_groups=tuple(rank_groups),
        by_candidate=by_candidate,
        candidate_parameters=candidate_parameters,
    )


# --------------------------------------------------------------------------------------
# Full run: scoring across all six frozen dimensions
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MinutesHarnessResult:
    folds_evaluated: int
    folds_by_season: dict[str, int]
    predictions: int
    eligible_predictions: int
    leakage_failures: int
    required_baselines: frozenset[str]
    overall: dict[str, MinutesScoreReport]
    by_fold: dict[str, dict[str, MinutesScoreReport]]
    by_season: dict[str, dict[str, MinutesScoreReport]]
    by_position: dict[str, dict[str, MinutesScoreReport]]
    by_home_away: dict[str, dict[str, MinutesScoreReport]]
    by_transfer_status: dict[str, dict[str, MinutesScoreReport]]
    by_player_history_cohort: dict[str, dict[str, MinutesScoreReport]]
    # Per-fold candidate parameter provenance (development-only). Empty unless a candidate factory
    # was supplied; the full per-fold mapping is preserved for independent reconciliation.
    parameters_by_fold: dict[str, dict[str, dict[str, float | int | bool | str]]] = field(
        default_factory=dict
    )

    def best_baseline(self) -> str:
        """Lowest mean log score among the required baselines -- the bar a candidate must beat."""
        eligible = {
            name: self.overall[name] for name in self.required_baselines if name in self.overall
        }
        return min(eligible, key=lambda name: eligible[name].mean_log_score)


def _score_records(
    name: str, records: Sequence[MinutesPredictionRecord], *, config: Phase2EvaluationConfig
) -> MinutesScoreReport:
    """Score one baseline's records under the contract, with cold starts and rank groups."""
    return score_minutes_predictions(
        [record.distribution for record in records],
        [record.observed_bin for record in records],
        config=config,
        eligible_predictions=len(records),
        cold_starts=[record.cold_start for record in records],
        rank_groups=[record.rank_group for record in records],
        name=name,
    )


def _slice_records(
    records: dict[str, list[MinutesPredictionRecord]], attribute: str
) -> dict[str, dict[str, list[MinutesPredictionRecord]]]:
    sliced: dict[str, dict[str, list[MinutesPredictionRecord]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for name, predictions in records.items():
        for prediction in predictions:
            sliced[str(getattr(prediction, attribute))][name].append(prediction)
    return sliced


def _score_slices(
    sliced: dict[str, dict[str, list[MinutesPredictionRecord]]],
    *,
    config: Phase2EvaluationConfig,
) -> dict[str, dict[str, MinutesScoreReport]]:
    return {
        key: {name: _score_records(name, preds, config=config) for name, preds in names.items()}
        for key, names in sliced.items()
    }


def run_minutes_harness(
    con: duckdb.DuckDBPyConnection,
    *,
    config: Phase2EvaluationConfig | None = None,
    seasons: list[str] | None = None,
    candidate_factory: MinutesCandidateFactory | None = None,
) -> MinutesHarnessResult:
    """Score every required Stage B baseline on exactly the same eligible predictions.

    ``seasons`` restricts the evaluated folds only; it never shortens the prior training history
    behind a fold, so a season-restricted run stays comparable to a full run. By default this is
    baselines-only. A separately named development runner may opt in one fold-local candidate via
    ``candidate_factory``; no promotion gate is executed on either path.
    """
    resolved = config or load_phase2_evaluation()
    bins = MinuteBins.from_config(resolved)

    folds = generate_minutes_folds(con, resolved)
    if seasons:
        allowed = set(seasons)
        folds = [fold for fold in folds if fold.season in allowed]

    records: dict[str, list[MinutesPredictionRecord]] = defaultdict(list)
    folds_by_season: dict[str, int] = defaultdict(int)
    evaluated = 0
    eligible_predictions = 0
    parameters_by_fold: dict[str, dict[str, dict[str, float | int | bool | str]]] = {}

    for fold in folds:
        result = run_minutes_fold(
            con, fold, bins=bins, config=resolved, candidate_factory=candidate_factory
        )
        if result is None:
            continue
        if len(result.targets) != fold.target_rows:
            raise RuntimeError(
                f"{fold}: target query returned {len(result.targets)} eligible rows after fold "
                f"generation counted {fold.target_rows}"
            )
        evaluated += 1
        eligible_predictions += fold.target_rows
        folds_by_season[fold.season] += 1
        fold_key = f"{fold.season}-GW{fold.gw}"
        # Baselines and any candidate are scored on the identical eligible rows: the candidate
        # predictions carry the same observed bin and slice keys. The population-equality check
        # below therefore enforces identical row counts for every model in `records`, candidate
        # included.
        for name, distributions in {**result.by_baseline, **result.by_candidate}.items():
            for index, distribution in enumerate(distributions):
                records[name].append(
                    MinutesPredictionRecord(
                        distribution=distribution,
                        observed_bin=result.observed_bins[index],
                        fold=fold_key,
                        season=fold.season,
                        position=result.positions[index],
                        home_away=result.home_away[index],
                        transfer_status=result.transfer_status[index],
                        player_history_cohort=result.player_history_cohort[index],
                        cold_start=result.cold_starts[index],
                        rank_group=result.rank_groups[index],
                    )
                )
        if result.candidate_parameters:
            parameters_by_fold[fold_key] = {
                name: dict(parameters) for name, parameters in result.candidate_parameters.items()
            }

    overall = {
        name: _score_records(name, preds, config=resolved) for name, preds in records.items()
    }
    by_fold = _score_slices(_slice_records(records, "fold"), config=resolved)
    by_season = _score_slices(_slice_records(records, "season"), config=resolved)
    by_position = _score_slices(_slice_records(records, "position"), config=resolved)
    by_home_away = _score_slices(_slice_records(records, "home_away"), config=resolved)
    by_transfer_status = _score_slices(_slice_records(records, "transfer_status"), config=resolved)
    by_player_history_cohort = _score_slices(
        _slice_records(records, "player_history_cohort"), config=resolved
    )

    prediction_counts = {name: len(predictions) for name, predictions in records.items()}
    if prediction_counts and set(prediction_counts.values()) != {eligible_predictions}:
        raise RuntimeError(
            "required Stage B baselines did not score the same eligible population: "
            f"{prediction_counts}, eligible={eligible_predictions}"
        )
    predictions = len(next(iter(records.values()))) if records else 0
    return MinutesHarnessResult(
        folds_evaluated=evaluated,
        folds_by_season=dict(folds_by_season),
        predictions=predictions,
        eligible_predictions=eligible_predictions,
        leakage_failures=0,
        required_baselines=frozenset(baseline_names()),
        overall=overall,
        by_fold=by_fold,
        by_season=by_season,
        by_position=by_position,
        by_home_away=by_home_away,
        by_transfer_status=by_transfer_status,
        by_player_history_cohort=by_player_history_cohort,
        parameters_by_fold=parameters_by_fold,
    )


# --------------------------------------------------------------------------------------
# Concise formatter (report-only; the contract and result object are authoritative)
# --------------------------------------------------------------------------------------


def format_minutes_report(
    result: MinutesHarnessResult, config: Phase2EvaluationConfig | None = None
) -> str:
    resolved = config or load_phase2_evaluation()
    additional_models = sorted(set(result.overall) - result.required_baselines)
    run_scope = (
        "development candidate + frozen baselines; no promotion verdict"
        if additional_models
        else "baselines-only; gate deferred"
    )
    lines = [
        f"contract       : {resolved.contract_version} (Stage B, {run_scope})",
        f"folds evaluated : {result.folds_evaluated}",
        f"predictions     : {result.predictions} / {result.eligible_predictions} eligible",
        f"leakage failures: {result.leakage_failures}",
        f"report slices   : {len(result.by_fold)} folds, {len(result.by_season)} seasons, "
        f"{len(result.by_position)} positions, {len(result.by_home_away)} venues, "
        f"{len(result.by_transfer_status)} transfer, "
        f"{len(result.by_player_history_cohort)} history cohorts",
        "",
        f"{'model':<34}{'log':>8}{'SE':>8}{'RPS':>8}{'bAny':>8}{'b60+':>8}"
        f"{'PIT80':>8}{'rhoP60':>8}{'cover':>8}{'n':>8}{'cold':>8}",
        "-" * 102,
    ]
    ordered = sorted(result.overall.values(), key=lambda report: report.mean_log_score)
    for report in ordered:
        lines.append(
            f"{report.name:<34}{report.mean_log_score:>8.4f}"
            f"{report.mean_log_score_standard_error:>8.4f}"
            f"{report.mean_ranked_probability_score:>8.4f}"
            f"{report.mean_brier_any_minutes:>8.4f}{report.mean_brier_60_plus:>8.4f}"
            f"{report.pit_interval_80_coverage:>8.3f}"
            f"{report.spearman_p60_within_position_gameweek:>8.3f}"
            f"{report.prediction_coverage:>8.3f}{report.predictions:>8d}{report.cold_starts:>8d}"
        )
    if result.overall:
        best = result.overall[result.best_baseline()]
        lines += ["", f"best required baseline: {best.name} (log score {best.mean_log_score:.4f})"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Stage B (player minutes) walk-forward.")
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--season", action="append", dest="seasons", default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    contract = load_phase2_evaluation()
    con = connect(args.db, read_only=True)
    try:
        result = run_minutes_harness(con, config=contract, seasons=args.seasons)
    finally:
        con.close()
    print(format_minutes_report(result, config=contract))
    return 0


if __name__ == "__main__":
    sys.exit(main())
