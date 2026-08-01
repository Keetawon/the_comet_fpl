"""Stage D v1 integrative walk-forward: compose components into xP and score against points.

    python -m fpl.validate.points_harness            # every fold, development-only

This is the first end-to-end evaluation. For every observed gameweek fold it fits each component
on point-in-time history (``kickoff_time < as_of``), composes a per-player-fixture points
distribution with :func:`fpl.models.points_composition.compose_points_distribution`, and scores it
against the realised NON-BONUS points with the frozen count-distribution metrics. It reads outcomes
-- the label -- which the feature layer may not; the label is computed here, in the validation
layer, from components under the target ruleset (R1: never the recorded ``total_points``).

**This is a development-only, exploratory harness. It is NOT a promotion gate.** Nothing here has a
pre-registered promotion contract; the number it produces is a first "is it any good" reading of the
composed pipeline, under the same unversioned historical proxies every stage carries.

Components (swappable -- the harness is component-agnostic via :class:`PointsComponentSuite`):
* minutes  -- Stage B Candidate V3 (best dev mean log score; note it fails the Stage B
  starter-ranking gate -- recorded caveat, it is a development component not a promoted one);
* goals    -- Stage C attacking Candidate V1 ``xg_informed_trailing_player_goals_v1`` (best dev mean
  log score of the three attacking candidates, and a per-player independent rate);
* assists  -- Stage C assists Candidate V1 ``xa_informed_trailing_player_assists_v1`` (only one);
* team clean sheet / goals conceded -- derived from the promoted Stage A model
  ``trailing_goals_attack_defence`` (the OPPONENT's scored-goals distribution), fit fold-locally;
* saves    -- Stage D **v2** GK saves ``gk_saves_poisson_from_team_conceded_v1``: for a goalkeeper,
  ``Poisson(k * lambda_conceded)`` with ``k`` from the fold-local league save rate (67.3% constant),
  zero for outfielders;
* defensive contribution -- Stage D **v2** ``trailing_dc_threshold_hit_bernoulli_v1``: a per-player
  ``P(DC >= threshold)``, PROSPECTIVE-ONLY (DC data exists only in 2025-26; 0 for earlier folds).

Stage D v2 adds saves and DC to the v1 composer. Penalties, own goals, and cards remain unmodelled
(a documented support gap); the realised label still includes them.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import duckdb

from fpl.config import (
    ScoringRules,
    load_phase2_evaluation,
    load_phase3_evaluation,
    load_scoring_rules,
)
from fpl.models.attacking_assists_baselines import AssistHistoryRow
from fpl.models.attacking_baselines import PlayerHistoryRow, TargetRowProjection
from fpl.models.defensive_contribution_v1 import DcHistoryRow
from fpl.models.gk_saves_v1 import GkSavesHistoryRow
from fpl.models.points_composition import (
    DEFAULT_MAX_POINTS,
    ComponentDistributions,
    ExtraScoring,
    PointsLookup,
    compose_points_distribution,
    representative_minutes,
)
from fpl.models.scoring import decompose_points
from fpl.storage.db import connect
from fpl.types import PlayerMatchStats, Position
from fpl.validate.metrics import (
    Distribution,
    ScoreReport,
    poisson_pmf,
    score_predictions,
)
from fpl.validate.minutes_baselines import (
    HistoryRow,
    MinuteBins,
    MinutesDistribution,
    TargetRow,
    TeamCodeMap,
)
from fpl.validate.minutes_harness import player_fixture_history, team_code_map

logger = logging.getLogger("fpl.validate.points_harness")

# Default Monte-Carlo draws per player-fixture. Larger smooths the empirical pmf; this is a
# development knob, not a contract constant.
DEFAULT_DRAWS = 2000

# The single season with zero xG coverage: its Stage C components degenerate to their goals/assists
# fallbacks, so it is reported separately and kept OUT of the headline, never averaged into it.
NO_XG_SEASON = "2021-22"
REGIME_NO_XG = "no_xg_2021_22"
REGIME_XG = "xg_present"

# The composer scores the realised NON-BONUS points under this ruleset (R1: recomputed from
# components, never the cross-season recorded total).
TARGET_RULESET = "2026_27"


# --------------------------------------------------------------------------------------
# Component predictor protocols (duck-typed; the harness never imports a concrete model)
# --------------------------------------------------------------------------------------


class MinutesPredictor(Protocol):
    name: str

    def predict(self, target: TargetRow) -> MinutesDistribution: ...


class CountPredictor(Protocol):
    name: str

    def predict(self, target: TargetRowProjection) -> Distribution: ...


class SavesPredictor(Protocol):
    name: str

    def predict(self, position: Position, lambda_conceded: float) -> Distribution: ...


class DcPredictor(Protocol):
    name: str

    def predict(self, code: int, position: Position) -> float: ...


@dataclass(frozen=True)
class PointsComponentSuite:
    """The swappable component set. Each callable fits ONE fold-local predictor on that fold's
    point-in-time history; swapping a component is a one-line change here.

    Stage D v2 adds the goalkeeper-saves and defensive-contribution fitters. ``fit_dc`` also gets
    the rules' per-position DC thresholds, which the DC hit-probability estimate is defined against.
    """

    minutes_name: str
    goals_name: str
    assists_name: str
    saves_name: str
    dc_name: str
    fit_minutes: Callable[[tuple[HistoryRow, ...], datetime], MinutesPredictor]
    fit_goals: Callable[[Sequence[PlayerHistoryRow]], CountPredictor]
    fit_assists: Callable[[Sequence[AssistHistoryRow]], CountPredictor]
    fit_saves: Callable[[Sequence[GkSavesHistoryRow]], SavesPredictor]
    fit_dc: Callable[[Sequence[DcHistoryRow], Mapping[Position, int]], DcPredictor]


def default_component_suite() -> PointsComponentSuite:
    """The v2 suite: minutes V3, goals V1, assists V1, GK saves V1, DC V1 (see module docstring)."""
    from fpl.models.attacking_assists_v1 import XaInformedTrailingPlayerAssistsV1
    from fpl.models.attacking_v1 import XgInformedTrailingPlayerGoalsV1
    from fpl.models.defensive_contribution_v1 import NAME as DC_NAME
    from fpl.models.defensive_contribution_v1 import DefensiveContributionV1
    from fpl.models.gk_saves_v1 import NAME as SAVES_NAME
    from fpl.models.gk_saves_v1 import GkSavesV1
    from fpl.models.minutes_v3 import fit_minutes_v3

    def fit_minutes(history: tuple[HistoryRow, ...], as_of: datetime) -> MinutesPredictor:
        return fit_minutes_v3(history, as_of=as_of)

    def fit_goals(history: Sequence[PlayerHistoryRow]) -> CountPredictor:
        model = XgInformedTrailingPlayerGoalsV1()
        model.fit(history)
        return model

    def fit_assists(history: Sequence[AssistHistoryRow]) -> CountPredictor:
        model = XaInformedTrailingPlayerAssistsV1()
        model.fit(history)
        return model

    def fit_saves(history: Sequence[GkSavesHistoryRow]) -> SavesPredictor:
        model = GkSavesV1()
        model.fit(history)
        return model

    def fit_dc(history: Sequence[DcHistoryRow], thresholds: Mapping[Position, int]) -> DcPredictor:
        model = DefensiveContributionV1(thresholds)
        model.fit(history)
        return model

    return PointsComponentSuite(
        minutes_name="concentration_adaptive_shrinkage_player_minutes_v3",
        goals_name="xg_informed_trailing_player_goals_v1",
        assists_name="xa_informed_trailing_player_assists_v1",
        saves_name=SAVES_NAME,
        dc_name=DC_NAME,
        fit_minutes=fit_minutes,
        fit_goals=fit_goals,
        fit_assists=fit_assists,
        fit_saves=fit_saves,
        fit_dc=fit_dc,
    )


# --------------------------------------------------------------------------------------
# The realised non-bonus label (validation layer only; R1-safe)
# --------------------------------------------------------------------------------------


def non_bonus_points(row: dict[str, object], position: Position, rules: ScoringRules) -> int:
    """Realised points under ``rules`` MINUS bonus, recomputed from the row's components.

    R1: the recorded ``total_points`` is never read. Points are recomputed from the component
    columns under the target ruleset and the bonus bucket subtracted, so prediction (which models no
    bonus) and label share the same non-bonus support. ``defensive_contribution`` is NULL before
    2025-26 and scores zero there, exactly as the calculator treats an unmeasured component.
    """
    stats = PlayerMatchStats.from_row(row)
    breakdown = decompose_points(stats, rules, position)
    return breakdown.total - breakdown.bonus


def _stable_seed(base_seed: int, season: str, code: int, fixture: int) -> int:
    """A per-player-fixture Monte-Carlo seed that is independent of iteration order.

    Derived by hashing the base seed with the grain key, so re-running (in any order) reproduces
    every player-fixture's pmf bit-for-bit.
    """
    key = f"{base_seed}|{season}|{code}|{fixture}".encode()
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big")


# --------------------------------------------------------------------------------------
# One fold
# --------------------------------------------------------------------------------------

_LABEL_COMPONENT_COLUMNS = (
    "minutes",
    "goals_scored",
    "assists",
    "clean_sheets",
    "goals_conceded",
    "saves",
    "penalties_saved",
    "penalties_missed",
    "own_goals",
    "yellow_cards",
    "red_cards",
    "bonus",
    "defensive_contribution",
)


@dataclass(frozen=True, slots=True)
class PointsPredictionRecord:
    distribution: Distribution
    observed: int
    fold: str
    season: str
    position: Position
    regime: str
    stage_a_fallback: bool


@dataclass(frozen=True, slots=True)
class FoldDiagnostics:
    """Development diagnostics for one fold's v2 components (never a gate).

    ``save_rate`` is the fold-local derived goalkeeper save rate; ``dc_history_present`` is True if
    the fold's training window carried any DC-measured position prior (only 2025-26 folds do);
    ``dc_positive_predictions`` counts target rows given a strictly positive DC hit probability.
    """

    fold: str
    save_rate: float
    dc_history_present: bool
    dc_positive_predictions: int
    predictions: int


def assert_no_points_leakage(
    targets: Sequence[tuple[datetime, str, int, int]], as_of: datetime
) -> None:
    """No predicted-gameweek player-fixture may kick off before ``as_of``.

    ``as_of`` is the gameweek's first kickoff, so this is zero by construction on a correct fold;
    the assertion fails loudly if a fold is ever mis-built. Each tuple is ``(kickoff, season, code,
    fixture)``.
    """
    for kickoff, season, code, fixture in targets:
        if kickoff.astimezone(UTC) < as_of.astimezone(UTC):
            raise AssertionError(
                f"leakage: target ({season}, code {code}, fixture {fixture}) kicks off "
                f"{kickoff!r} before fold cutoff as_of {as_of!r}"
            )


def observed_folds(con: duckdb.DuckDBPyConnection, *, warmup: int) -> list[tuple[str, int]]:
    """Every observed ``(season, gw)`` after the cross-season warmup, in order (never ``1..38``)."""
    frame = con.sql(
        """
        SELECT DISTINCT season, gw
        FROM mart_fact_player_fixture
        WHERE minutes IS NOT NULL
        ORDER BY season, gw
        """
    ).pl()
    frame = frame.sort(["season", "gw"], maintain_order=True)
    ordered = [(r["season"], int(r["gw"])) for r in frame.iter_rows(named=True)]
    return ordered[warmup:]


def _team_conceded_distributions(
    con: duckdb.DuckDBPyConnection,
    season: str,
    gw: int,
    as_of: datetime,
) -> tuple[dict[tuple[str, int, int], Distribution], float]:
    """Fit the promoted Stage A model fold-locally and return each team's scored-goals distribution.

    Keyed by ``(season, fixture, team_code)`` -- a team's own scored goals in a fixture. A player's
    team-conceded distribution is looked up as the OPPONENT's entry. Also returns the league mean
    goals conceded from the training window, the explicit cold-start / missing-fixture fallback.
    """
    from fpl.validate.baselines import TrailingGoalsAttackDefence, TrainingWindow

    select = """
        m.season, m.gw, m.fixture, m.was_home,
        club.team_code AS team_code,
        opponent.team_code AS opponent_team_code,
        m.goals_for, m.goals_against, m.team_xg, m.team_xgc, m.fdr
    """
    join = """
        FROM mart_fact_team_match AS m
        JOIN mart_dim_team AS club
          ON club.season = m.season AND club.team_id = m.team_id
        JOIN mart_dim_team AS opponent
          ON opponent.season = m.season AND opponent.team_id = m.opponent_team_id
    """
    window_frame = con.execute(f"SELECT {select} {join} WHERE m.kickoff_time < ?", [as_of]).pl()
    fixtures_frame = con.execute(
        f"""
        SELECT {select} {join}
        WHERE m.season = ? AND m.gw = ? AND m.goals_for IS NOT NULL
        ORDER BY m.fixture, m.team_id
        """,
        [season, gw],
    ).pl()

    league_conceded = 1.4
    if not window_frame.is_empty():
        conceded = window_frame["goals_against"].drop_nulls()
        if conceded.len():
            value = conceded.mean()
            if isinstance(value, (int, float)):
                league_conceded = float(value)

    model = TrailingGoalsAttackDefence()
    model.fit(TrainingWindow(window_frame))
    by_team: dict[tuple[str, int, int], Distribution] = {}
    if not fixtures_frame.is_empty():
        predictions = model.predict(fixtures_frame)
        rows = fixtures_frame.iter_rows(named=True)
        for row, distribution in zip(rows, predictions, strict=True):
            if distribution is None:
                continue
            key = (str(row["season"]), int(row["fixture"]), int(row["team_code"]))
            by_team[key] = distribution
    return by_team, league_conceded


def run_points_fold(
    con: duckdb.DuckDBPyConnection,
    season: str,
    gw: int,
    *,
    suite: PointsComponentSuite,
    lookup: PointsLookup,
    rules: ScoringRules,
    team_codes: TeamCodeMap,
    extra: ExtraScoring,
    base_seed: int,
    draws: int,
    max_points: int,
) -> tuple[str, list[PointsPredictionRecord], FoldDiagnostics]:
    """Fit every component on the fold's point-in-time history and compose xP for its gameweek."""
    as_of_row = con.execute(
        """
        SELECT min(kickoff_time) AS as_of
        FROM mart_fact_player_fixture
        WHERE season = ? AND gw = ? AND minutes IS NOT NULL
        """,
        [season, gw],
    ).pl()
    if as_of_row.is_empty() or as_of_row["as_of"][0] is None:
        raise ValueError(f"no kickoff_time for fold {season} GW{gw}")
    as_of: datetime = as_of_row["as_of"][0]

    # --- Point-in-time component histories.
    minutes_history = tuple(player_fixture_history(con, as_of=as_of))
    # ``saves`` and ``goals_conceded`` are required components (present all five seasons for played
    # rows); ``defensive_contribution`` is selected RAW and never coalesced -- it is NULL before
    # 2025-26 and a NULL must not become a zero (R: NULL != 0). The DC history builder below skips
    # NULL rows so they carry no signal instead of a fabricated zero.
    player_history_frame = con.execute(
        """
        SELECT season, gw, fixture,
               strftime(kickoff_time, '%Y-%m-%dT%H:%M:%SZ') AS kickoff_time,
               code, position, COALESCE(goals_scored, 0) AS goals,
               COALESCE(assists, 0) AS assists, minutes,
               saves, goals_conceded, defensive_contribution,
               expected_goals, expected_assists, creativity
        FROM mart_fact_player_fixture
        WHERE minutes IS NOT NULL AND kickoff_time < ?
        ORDER BY kickoff_time, season, fixture, code
        """,
        [as_of],
    ).pl()
    player_history_frame = player_history_frame.sort(
        ["kickoff_time", "season", "fixture", "code"], maintain_order=True
    )
    goals_history: list[PlayerHistoryRow] = []
    assists_history: list[AssistHistoryRow] = []
    saves_history: list[GkSavesHistoryRow] = []
    dc_history: list[DcHistoryRow] = []
    for r in player_history_frame.iter_rows(named=True):
        position = Position.from_archive_label(r["position"])
        goals_history.append(
            PlayerHistoryRow(
                season=r["season"],
                gw=r["gw"],
                fixture=r["fixture"],
                kickoff_time=r["kickoff_time"],
                code=r["code"],
                position=position,
                goals=r["goals"],
                expected_goals=r["expected_goals"],
            )
        )
        assists_history.append(
            AssistHistoryRow(
                season=r["season"],
                gw=r["gw"],
                fixture=r["fixture"],
                kickoff_time=r["kickoff_time"],
                code=r["code"],
                position=position,
                assists=r["assists"],
                minutes=r["minutes"],
                expected_assists=r["expected_assists"],
                creativity=r["creativity"],
            )
        )
        saves_history.append(
            GkSavesHistoryRow(
                position=position,
                minutes=r["minutes"],
                saves=r["saves"],
                goals_conceded=r["goals_conceded"],
            )
        )
        # Preserve NULL DC (unmeasured before 2025-26); never zero-fill. Only measured rows carry a
        # DC signal, so a NULL row is simply not added to the DC history.
        if r["defensive_contribution"] is not None:
            dc_history.append(
                DcHistoryRow(
                    code=r["code"],
                    position=position,
                    minutes=r["minutes"],
                    defensive_contribution=r["defensive_contribution"],
                )
            )

    minutes_model = suite.fit_minutes(minutes_history, as_of)
    goals_model = suite.fit_goals(goals_history)
    assists_model = suite.fit_assists(assists_history)
    saves_model = suite.fit_saves(saves_history)
    dc_model = suite.fit_dc(dc_history, rules.defensive_contribution.thresholds)
    conceded_by_team, league_conceded = _team_conceded_distributions(con, season, gw, as_of)
    league_conceded_dist = poisson_pmf(max(league_conceded, 1e-6))

    # --- Targets (the fold's eligible player-fixtures) and the realised non-bonus label.
    select_columns = ", ".join(_LABEL_COMPONENT_COLUMNS)
    targets_frame = con.execute(
        f"""
        SELECT season, gw, fixture, kickoff_time,
               strftime(kickoff_time, '%Y-%m-%dT%H:%M:%SZ') AS kickoff_str,
               code, position, team_id, opponent_team_id, was_home, {select_columns}
        FROM mart_fact_player_fixture
        WHERE season = ? AND gw = ? AND minutes IS NOT NULL
        ORDER BY kickoff_time, fixture, code
        """,
        [season, gw],
    ).pl()

    regime = REGIME_NO_XG if season == NO_XG_SEASON else REGIME_XG
    fold_label = f"{season}-GW{gw:02d}"
    assert_no_points_leakage(
        [
            (r["kickoff_time"], season, int(r["code"]), int(r["fixture"]))
            for r in targets_frame.iter_rows(named=True)
        ],
        as_of,
    )
    records: list[PointsPredictionRecord] = []
    dc_positive_predictions = 0
    for r in targets_frame.iter_rows(named=True):
        position = Position.from_archive_label(r["position"])
        code = int(r["code"])
        fixture = int(r["fixture"])
        team_id = int(r["team_id"])
        opponent_team_id = int(r["opponent_team_id"])
        was_home = bool(r["was_home"])
        kickoff_ts: datetime = r["kickoff_time"]

        minutes_target = TargetRow(
            season=season,
            gw=gw,
            fixture=fixture,
            kickoff_time=kickoff_ts,
            code=code,
            position=position,
            team_id=team_id,
            opponent_team_id=opponent_team_id,
            was_home=was_home,
        )
        stage_c_target = TargetRowProjection(
            season=season,
            gw=gw,
            fixture=fixture,
            kickoff_time=r["kickoff_str"],
            code=code,
            position=position,
            team_id=team_id,
            opponent_team_id=opponent_team_id,
            was_home=was_home,
        )

        minutes_dist = minutes_model.predict(minutes_target)
        goals_dist = goals_model.predict(stage_c_target)
        assists_dist = assists_model.predict(stage_c_target)

        opponent_code = team_codes.code(season, opponent_team_id)
        conceded_dist = conceded_by_team.get((season, fixture, opponent_code))
        stage_a_fallback = conceded_dist is None
        if conceded_dist is None:
            conceded_dist = league_conceded_dist

        # Stage D v2: saves are derived from the fixture's expected team-conceded rate (a per-match
        # team quantity, wired explicitly rather than through the generic per-player protocol), and
        # DC is a per-player threshold-hit probability. lambda_conceded = sum(i * p_i) over the
        # ordered conceded distribution (fixed length, so the float sum is order-stable).
        lambda_conceded = sum(index * mass for index, mass in enumerate(conceded_dist))
        saves_dist = saves_model.predict(position, lambda_conceded)
        dc_probability = dc_model.predict(code, position)
        if dc_probability > 0.0:
            dc_positive_predictions += 1

        components = ComponentDistributions(
            position=position,
            minutes=minutes_dist,
            goals=goals_dist,
            assists=assists_dist,
            team_goals_conceded=conceded_dist,
            saves=saves_dist,
            dc_hit_probability=dc_probability,
        )
        points_dist = compose_points_distribution(
            components,
            lookup,
            seed=_stable_seed(base_seed, season, code, fixture),
            draws=draws,
            max_points=max_points,
            extra=extra,
        )
        label = non_bonus_points(r, position, rules)
        records.append(
            PointsPredictionRecord(
                distribution=points_dist,
                observed=label,
                fold=fold_label,
                season=season,
                position=position,
                regime=regime,
                stage_a_fallback=stage_a_fallback,
            )
        )
    diagnostics = FoldDiagnostics(
        fold=fold_label,
        save_rate=float(getattr(saves_model, "save_rate", float("nan"))),
        dc_history_present=len(dc_history) > 0,
        dc_positive_predictions=dc_positive_predictions,
        predictions=len(records),
    )
    return fold_label, records, diagnostics


# --------------------------------------------------------------------------------------
# Full run
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PointsHarnessResult:
    model_name: str
    folds_evaluated: int
    folds_by_season: dict[str, int]
    predictions: int
    stage_a_fallbacks: int
    draws: int
    max_points: int
    overall: ScoreReport
    headline_xg: ScoreReport
    by_season: dict[str, ScoreReport]
    by_position: dict[str, ScoreReport]
    by_regime: dict[str, ScoreReport]
    component_names: dict[str, str]
    save_rate_min: float
    save_rate_max: float
    folds_with_dc_history: int
    dc_positive_predictions: int


def _score(name: str, records: Sequence[PointsPredictionRecord], *, seed: int) -> ScoreReport:
    return score_predictions(
        name,
        [record.distribution for record in records],
        [record.observed for record in records],
        seed=seed,
        eligible_predictions=len(records),
        cold_starts=[record.stage_a_fallback for record in records],
        rank_groups=[record.fold for record in records],
    )


def run_points_harness(
    con: duckdb.DuckDBPyConnection,
    *,
    suite: PointsComponentSuite | None = None,
    seasons: Sequence[str] | None = None,
    draws: int = DEFAULT_DRAWS,
    base_seed: int = 202627,
    max_points: int = DEFAULT_MAX_POINTS,
    warmup: int = 8,
) -> PointsHarnessResult:
    """Compose and score xP across every observed fold. Development-only; no promotion gate."""
    resolved_suite = suite or default_component_suite()
    # Loaded to confirm the Stage C goals contract is present; components read their own frozen
    # constants. The xG-coverage regime split uses only the 2021-22 no-xG season constant.
    load_phase3_evaluation()

    rules = load_scoring_rules(TARGET_RULESET)
    bins = MinuteBins.from_config(load_phase2_evaluation())
    lookup = PointsLookup(rules, bin_minutes=representative_minutes(bins.ranges))
    # Stage D v2 saves / DC scoring constants, resolved once from the rules (the composer is
    # config-free and receives these explicitly).
    extra = ExtraScoring(
        saves_unit=rules.saves.unit,
        dc_points=rules.defensive_contribution.points,
        saves_positions=rules.saves.positions,
        dc_positions=frozenset(rules.defensive_contribution.thresholds),
    )
    team_codes = team_code_map(con)

    folds = observed_folds(con, warmup=warmup)
    if seasons is not None:
        allowed = set(seasons)
        folds = [fold for fold in folds if fold[0] in allowed]

    all_records: list[PointsPredictionRecord] = []
    folds_by_season: dict[str, int] = defaultdict(int)
    fold_diagnostics: list[FoldDiagnostics] = []
    evaluated = 0
    for season, gw in folds:
        _, records, diagnostics = run_points_fold(
            con,
            season,
            gw,
            suite=resolved_suite,
            lookup=lookup,
            rules=rules,
            team_codes=team_codes,
            extra=extra,
            base_seed=base_seed,
            draws=draws,
            max_points=max_points,
        )
        if not records:
            continue
        evaluated += 1
        folds_by_season[season] += 1
        all_records.extend(records)
        fold_diagnostics.append(diagnostics)
        logger.info("fold %s: %d predictions", f"{season}-GW{gw:02d}", len(records))

    if not all_records:
        raise RuntimeError("no eligible predictions produced across the requested folds")

    by_season_records: dict[str, list[PointsPredictionRecord]] = defaultdict(list)
    by_position_records: dict[str, list[PointsPredictionRecord]] = defaultdict(list)
    by_regime_records: dict[str, list[PointsPredictionRecord]] = defaultdict(list)
    headline_records: list[PointsPredictionRecord] = []
    for record in all_records:
        by_season_records[record.season].append(record)
        by_position_records[record.position.value].append(record)
        by_regime_records[record.regime].append(record)
        if record.season != NO_XG_SEASON:
            headline_records.append(record)

    save_rates = [d.save_rate for d in fold_diagnostics]
    return PointsHarnessResult(
        model_name="stage_d_points_composition_v2",
        folds_evaluated=evaluated,
        folds_by_season=dict(folds_by_season),
        predictions=len(all_records),
        stage_a_fallbacks=sum(1 for record in all_records if record.stage_a_fallback),
        draws=draws,
        max_points=max_points,
        overall=_score("overall", all_records, seed=base_seed),
        headline_xg=_score("headline_xg", headline_records, seed=base_seed)
        if headline_records
        else _score("overall", all_records, seed=base_seed),
        by_season={
            s: _score(s, recs, seed=base_seed) for s, recs in sorted(by_season_records.items())
        },
        by_position={
            p: _score(p, recs, seed=base_seed) for p, recs in sorted(by_position_records.items())
        },
        by_regime={
            r: _score(r, recs, seed=base_seed) for r, recs in sorted(by_regime_records.items())
        },
        component_names={
            "minutes": resolved_suite.minutes_name,
            "goals": resolved_suite.goals_name,
            "assists": resolved_suite.assists_name,
            "team_clean_sheet": "trailing_goals_attack_defence",
            "saves": resolved_suite.saves_name,
            "defensive_contribution": resolved_suite.dc_name,
        },
        save_rate_min=min(save_rates) if save_rates else float("nan"),
        save_rate_max=max(save_rates) if save_rates else float("nan"),
        folds_with_dc_history=sum(1 for d in fold_diagnostics if d.dc_history_present),
        dc_positive_predictions=sum(d.dc_positive_predictions for d in fold_diagnostics),
    )


def format_points_report(result: PointsHarnessResult) -> str:
    lines = [
        "=== Stage D v2 points composition walk-forward (DEVELOPMENT ONLY) ===",
        f"folds evaluated : {result.folds_evaluated}",
        f"predictions     : {result.predictions}",
        f"Monte-Carlo     : {result.draws} draws, points support 0..{result.max_points}",
        f"Stage A fallbacks: {result.stage_a_fallbacks}",
        f"GK save_rate    : fold-local range [{result.save_rate_min:.4f}, "
        f"{result.save_rate_max:.4f}]",
        f"DC (prospective): folds with DC history {result.folds_with_dc_history}, "
        f"targets with p_hit>0 {result.dc_positive_predictions}",
        "components      : " + ", ".join(f"{k}={v}" for k, v in result.component_names.items()),
        "",
        f"{'slice':<22}{'log':>9}{'CRPS':>9}{'PIT80':>9}{'MAE':>9}{'n':>9}",
        "-" * 68,
    ]

    def row(label: str, report: ScoreReport) -> str:
        return (
            f"{label:<22}{report.mean_log_score:>9.4f}{report.mean_crps:>9.4f}"
            f"{report.pit_interval_80_coverage:>9.3f}{report.mean_absolute_error:>9.3f}"
            f"{report.predictions:>9d}"
        )

    lines.append(row("overall (all seasons)", result.overall))
    lines.append(row("HEADLINE (xG present)", result.headline_xg))
    lines.append("")
    lines.append("by season:")
    for season, report in result.by_season.items():
        marker = "  [no-xG, excluded]" if season == NO_XG_SEASON else ""
        lines.append(row(f"  {season}", report) + marker)
    lines.append("")
    lines.append("by position:")
    for position, report in result.by_position.items():
        lines.append(row(f"  {position}", report))
    lines.append("")
    lines.append("by xG-coverage regime:")
    for regime, report in result.by_regime.items():
        lines.append(row(f"  {regime}", report))
    lines += [
        "",
        "DEVELOPMENT ONLY -- exploratory, not a promotion verdict. The 2021-22 no-xG season is",
        "reported separately and kept out of the headline. DC is prospective-only (2025-26 data). "
        "See docs/phase4-stage-d-points-composition-v2-development.md.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the Stage D v2 points-composition walk-forward (development-only)."
    )
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--season", action="append", dest="seasons", default=None)
    parser.add_argument("--draws", type=int, default=DEFAULT_DRAWS)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    con = connect(args.db, read_only=True)
    try:
        result = run_points_harness(con, seasons=args.seasons, draws=args.draws)
    finally:
        con.close()
    print(format_points_report(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
