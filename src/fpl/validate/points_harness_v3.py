"""Stage D v3 walk-forward: match-level JOINT composition into FULL points (including bonus).

    python -m fpl.validate.points_harness_v3            # every fold, development-only

Stage D v2 (:mod:`fpl.validate.points_harness`) composes each player-fixture INDEPENDENTLY into a
**non-bonus** points distribution and scores it against realised non-bonus points. v3 keeps the
identical fitted component suite (minutes V3, goals V1, assists V1, team goals-conceded from the
promoted Stage A model, GK saves V1, DC V1) but composes a whole **fixture jointly** so it can add
**bonus**: in each Monte-Carlo world every appeared player's components are drawn once, the SAME
draw yields both the player's non-bonus points and their BPS, the fixture's BPS are ranked, and
3/2/1 bonus is awarded and added (see ``points_composition.compose_fixture_full_points``).
The BPS exact part and the fold-local point-in-time empirical residual are reused verbatim from the
development BPS simulator (:mod:`fpl.models.bps_bonus`).

Because non-bonus points and BPS come from the SAME drawn components, a world with a drawn haul
carries its own bonus -- the own-scoring<->own-bonus coupling v2 could not represent -- and only one
player can be a fixture's 3-point winner in a world, the cross-player coupling.

**This is a development-only, exploratory harness. It is NOT a promotion gate**, and it scores a
DIFFERENT label than v2 (full points vs non-bonus points), so it is a full-points quality read, not
a like-for-like delta against v2. It carries every unversioned historical proxy the earlier stages
carry, plus v2's component-independence / no-team-coupling limitation (v3 adds ONLY the bonus rank
coupling, not team-goal conservation) and the documented BPS-residual proxy caveat: the residual's
`influence`/`creativity` correction reads the target row's realised ICT values, exactly as the
development BPS study does. The player's own realised BPS/bonus for the predicted row is never a
model input.

R1: the label is the realised NON-BONUS points (recomputed from components under 2026/27 rules,
never `total_points`) PLUS the realised recorded `bonus` component -- the full recomputed total.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import duckdb

from fpl.config import (
    BpsRules,
    ScoringRules,
    load_phase2_evaluation,
    load_phase3_evaluation,
    load_scoring_rules,
)
from fpl.models.attacking_assists_baselines import AssistHistoryRow
from fpl.models.attacking_baselines import PlayerHistoryRow, TargetRowProjection
from fpl.models.bps_bonus import BpsSimConfig, PlayerRow, ResidualModel, fit_residual_model
from fpl.models.defensive_contribution_v1 import DcHistoryRow
from fpl.models.gk_saves_v1 import GkSavesHistoryRow
from fpl.models.points_composition import (
    DEFAULT_MAX_POINTS_FULL as DEFAULT_MAX_POINTS,
)
from fpl.models.points_composition import (
    BpsExactLookup,
    ComponentDistributions,
    ComposedPlayer,
    ExtraScoring,
    FixturePlayer,
    PointsLookup,
    compose_fixture_full_points,
    representative_minutes,
)
from fpl.storage.db import connect
from fpl.types import PlayerMatchStats, Position
from fpl.validate.metrics import (
    Distribution,
    ScoreReport,
    poisson_pmf,
    score_predictions,
)
from fpl.validate.minutes_baselines import MinuteBins, TargetRow, TeamCodeMap
from fpl.validate.minutes_harness import player_fixture_history, team_code_map
from fpl.validate.points_harness import (
    NO_XG_SEASON,
    REGIME_NO_XG,
    REGIME_XG,
    TARGET_RULESET,
    PointsComponentSuite,
    _team_conceded_distributions,
    assert_no_points_leakage,
    default_component_suite,
    non_bonus_points,
    observed_folds,
)

logger = logging.getLogger("fpl.validate.points_harness_v3")

# Default Monte-Carlo draws per fixture. Larger smooths the empirical pmf; this is a development
# knob, not a contract constant. Matches the v2 harness default.
DEFAULT_DRAWS = 2000


def _fixture_seed(base_seed: int, season: str, fixture: int) -> int:
    """A per-fixture Monte-Carlo seed independent of iteration order.

    Derived by hashing the base seed with ``(season, fixture)`` -- the whole fixture is one joint
    draw, so the seed is per fixture (not per player). Re-running (in any order) reproduces every
    fixture's joint pmf bit-for-bit.
    """
    key = f"{base_seed}|{season}|{fixture}".encode()
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big")


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
    expected_bonus: float
    realised_bonus: int


@dataclass(frozen=True, slots=True)
class FoldDiagnostics:
    fold: str
    save_rate: float
    dc_history_present: bool
    dc_positive_predictions: int
    predictions: int
    fixtures: int
    residual_training_rows: int


def full_points(row: dict[str, object], position: Position, rules: ScoringRules) -> tuple[int, int]:
    """Realised FULL points and the realised bonus component, both R1-safe.

    R1: `total_points` is never read. The full points are the recomputed non-bonus points (from the
    row's components under the target ruleset) PLUS the realised recorded `bonus` scoring component
    (never the cross-season recorded total). Returns ``(full_points, realised_bonus)``.
    """
    non_bonus = non_bonus_points(row, position, rules)
    realised_bonus = PlayerMatchStats.from_row(row).bonus
    return non_bonus + realised_bonus, realised_bonus


def _residual_training_rows(con: duckdb.DuckDBPyConnection, as_of: datetime) -> list[PlayerRow]:
    """Point-in-time BPS-residual training rows: appeared 4-position rows, `kickoff_time < as_of`.

    Ordered by `(kickoff_time, season, fixture, code)` so the fitted player trailing histories are
    chronological. `clearances_blocks_interceptions` NULL is preserved as ``None`` (R: NULL != 0);
    the residual absorbs its true value on those rows.
    """
    frame = con.execute(
        """
        SELECT season, fixture,
               strftime(kickoff_time, '%Y-%m-%dT%H:%M:%SZ') AS kickoff_str,
               epoch(kickoff_time) AS kickoff_epoch,
               code, position, minutes, goals_scored, assists, clean_sheets,
               penalties_saved, clearances_blocks_interceptions, influence, creativity, bps, bonus
        FROM mart_fact_player_fixture
        WHERE minutes IS NOT NULL AND kickoff_time < ?
          AND position IN ('GK', 'DEF', 'MID', 'FWD')
          AND bps IS NOT NULL AND bonus IS NOT NULL
        ORDER BY kickoff_time, season, fixture, code
        """,
        [as_of],
    ).pl()
    frame = frame.sort(["kickoff_epoch", "season", "fixture", "code"], maintain_order=True)
    rows: list[PlayerRow] = []
    for r in frame.iter_rows(named=True):
        cbi = r["clearances_blocks_interceptions"]
        rows.append(
            PlayerRow(
                code=int(r["code"]),
                position=str(r["position"]),
                minutes=int(r["minutes"]),
                goals_scored=int(r["goals_scored"]),
                assists=int(r["assists"]),
                clean_sheets=int(r["clean_sheets"]),
                penalties_saved=int(r["penalties_saved"]),
                clearances_blocks_interceptions=None if cbi is None else int(cbi),
                influence=float(r["influence"]),
                creativity=float(r["creativity"]),
                bps=int(r["bps"]),
                bonus=int(r["bonus"]),
                order_key=(float(r["kickoff_epoch"]), str(r["season"]), int(r["fixture"])),
            )
        )
    return rows


def _residual_prediction(
    model: ResidualModel, *, code: int, position: str, influence: float, creativity: float
) -> float:
    """Fold-local predicted BPS residual mean for a target row (reuses the BPS simulator model)."""
    target = PlayerRow(
        code=code,
        position=position,
        minutes=90,  # unused by predict_mean; only position/code/influence/creativity are read.
        goals_scored=0,
        assists=0,
        clean_sheets=0,
        penalties_saved=0,
        clearances_blocks_interceptions=None,
        influence=influence,
        creativity=creativity,
        bps=0,
        bonus=0,
    )
    return model.predict_mean(target)


def run_points_fold_v3(
    con: duckdb.DuckDBPyConnection,
    season: str,
    gw: int,
    *,
    suite: PointsComponentSuite,
    lookup: PointsLookup,
    bps_lookup: BpsExactLookup,
    bps: BpsRules,
    bps_config: BpsSimConfig,
    rules: ScoringRules,
    team_codes: TeamCodeMap,
    extra: ExtraScoring,
    base_seed: int,
    draws: int,
    max_points: int,
) -> tuple[str, list[PointsPredictionRecord], FoldDiagnostics]:
    """Fit every component + BPS residual fold-locally and JOINTLY compose full xP per fixture."""
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

    # --- Point-in-time component histories (identical construction to the v2 fold).
    minutes_history = tuple(player_fixture_history(con, as_of=as_of))
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

    # --- Fold-local, point-in-time BPS residual model (reused from the BPS simulator).
    residual_rows = _residual_training_rows(con, as_of)
    residual_model = fit_residual_model(
        residual_rows,
        bps,
        prior_strength=bps_config.prior_strength,
        trailing_window=bps_config.trailing_window,
        ridge_lambda=bps_config.ridge_lambda,
        sigma_floor=bps_config.sigma_floor,
        sd_floor=bps_config.sd_floor,
        minimum_position_rows=bps_config.minimum_position_rows,
    )

    # --- Targets (the fold's eligible player-fixtures), grouped by fixture for the joint draw.
    select_columns = ", ".join(_LABEL_COMPONENT_COLUMNS)
    targets_frame = con.execute(
        f"""
        SELECT season, gw, fixture, kickoff_time,
               strftime(kickoff_time, '%Y-%m-%dT%H:%M:%SZ') AS kickoff_str,
               code, position, team_id, opponent_team_id, was_home,
               influence, creativity, {select_columns}
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

    # Build a FixturePlayer per target, carrying its label alongside, grouped by fixture. The
    # fixture population spans both teams (target rows for the fixture), which is exactly the bonus
    # ranking population.
    @dataclass(frozen=True, slots=True)
    class _Target:
        player: FixturePlayer
        position: Position
        observed: int
        realised_bonus: int
        stage_a_fallback: bool

    by_fixture: dict[int, list[_Target]] = defaultdict(list)
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
        residual_mean = _residual_prediction(
            residual_model,
            code=code,
            position=position.value,
            influence=float(r["influence"]),
            creativity=float(r["creativity"]),
        )
        observed, realised_bonus = full_points(r, position, rules)
        by_fixture[fixture].append(
            _Target(
                player=FixturePlayer(
                    code=code,
                    components=components,
                    residual_mean=residual_mean,
                    residual_sigma=residual_model.sigma(position.value),
                ),
                position=position,
                observed=observed,
                realised_bonus=realised_bonus,
                stage_a_fallback=stage_a_fallback,
            )
        )

    records: list[PointsPredictionRecord] = []
    for fixture in sorted(by_fixture):
        targets = by_fixture[fixture]
        composed = compose_fixture_full_points(
            [t.player for t in targets],
            lookup,
            bps_lookup,
            extra,
            fixture_seed=_fixture_seed(base_seed, season, fixture),
            draws=draws,
            max_points=max_points,
        )
        by_code: dict[int, ComposedPlayer] = {c.code: c for c in composed}
        for t in targets:
            result = by_code[t.player.code]
            records.append(
                PointsPredictionRecord(
                    distribution=result.distribution,
                    observed=t.observed,
                    fold=fold_label,
                    season=season,
                    position=t.position,
                    regime=regime,
                    stage_a_fallback=t.stage_a_fallback,
                    expected_bonus=result.expected_bonus,
                    realised_bonus=t.realised_bonus,
                )
            )

    diagnostics = FoldDiagnostics(
        fold=fold_label,
        save_rate=float(getattr(saves_model, "save_rate", float("nan"))),
        dc_history_present=len(dc_history) > 0,
        dc_positive_predictions=dc_positive_predictions,
        predictions=len(records),
        fixtures=len(by_fixture),
        residual_training_rows=len(residual_rows),
    )
    return fold_label, records, diagnostics


@dataclass(frozen=True, slots=True)
class PointsHarnessV3Result:
    model_name: str
    folds_evaluated: int
    folds_by_season: dict[str, int]
    predictions: int
    fixtures: int
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
    # Bonus diagnostics: predicted expected bonus vs realised bonus, overall and by position.
    expected_bonus_total: float
    realised_bonus_total: float
    expected_bonus_by_position: dict[str, float]
    realised_bonus_by_position: dict[str, float]


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


def run_points_harness_v3(
    con: duckdb.DuckDBPyConnection,
    *,
    suite: PointsComponentSuite | None = None,
    seasons: Sequence[str] | None = None,
    draws: int = DEFAULT_DRAWS,
    base_seed: int = 202627,
    max_points: int = DEFAULT_MAX_POINTS,
    warmup: int = 8,
) -> PointsHarnessV3Result:
    """Jointly compose and score FULL xP across every observed fold. Development-only; no gate."""
    resolved_suite = suite or default_component_suite()
    load_phase3_evaluation()

    rules = load_scoring_rules(TARGET_RULESET)
    if rules.bps is None:
        raise SystemExit("scoring_2026_27.yaml has no bps block; nothing to compose bonus from")
    bps = rules.bps
    bps_config = BpsSimConfig()
    bins = MinuteBins.from_config(load_phase2_evaluation())
    bin_minutes = representative_minutes(bins.ranges)
    lookup = PointsLookup(rules, bin_minutes=bin_minutes)
    bps_lookup = BpsExactLookup(
        bps,
        bin_minutes=bin_minutes,
        clean_sheet_minimum_minutes=rules.clean_sheets.minimum_minutes,
    )
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
    total_fixtures = 0
    for season, gw in folds:
        _, records, diagnostics = run_points_fold_v3(
            con,
            season,
            gw,
            suite=resolved_suite,
            lookup=lookup,
            bps_lookup=bps_lookup,
            bps=bps,
            bps_config=bps_config,
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
        total_fixtures += diagnostics.fixtures
        all_records.extend(records)
        fold_diagnostics.append(diagnostics)
        logger.info("fold %s: %d predictions", f"{season}-GW{gw:02d}", len(records))

    if not all_records:
        raise RuntimeError("no eligible predictions produced across the requested folds")

    by_season_records: dict[str, list[PointsPredictionRecord]] = defaultdict(list)
    by_position_records: dict[str, list[PointsPredictionRecord]] = defaultdict(list)
    by_regime_records: dict[str, list[PointsPredictionRecord]] = defaultdict(list)
    headline_records: list[PointsPredictionRecord] = []
    expected_bonus_by_position: dict[str, float] = defaultdict(float)
    realised_bonus_by_position: dict[str, float] = defaultdict(float)
    for record in all_records:
        by_season_records[record.season].append(record)
        by_position_records[record.position.value].append(record)
        by_regime_records[record.regime].append(record)
        expected_bonus_by_position[record.position.value] += record.expected_bonus
        realised_bonus_by_position[record.position.value] += record.realised_bonus
        if record.season != NO_XG_SEASON:
            headline_records.append(record)

    save_rates = [d.save_rate for d in fold_diagnostics]
    return PointsHarnessV3Result(
        model_name="stage_d_points_composition_v3_full_points",
        folds_evaluated=evaluated,
        folds_by_season=dict(folds_by_season),
        predictions=len(all_records),
        fixtures=total_fixtures,
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
            "bonus": "hybrid_bps_bonus_match_simulator (exact_bps + fold-local residual)",
        },
        save_rate_min=min(save_rates) if save_rates else float("nan"),
        save_rate_max=max(save_rates) if save_rates else float("nan"),
        folds_with_dc_history=sum(1 for d in fold_diagnostics if d.dc_history_present),
        dc_positive_predictions=sum(d.dc_positive_predictions for d in fold_diagnostics),
        expected_bonus_total=sum(record.expected_bonus for record in all_records),
        realised_bonus_total=float(sum(record.realised_bonus for record in all_records)),
        expected_bonus_by_position=dict(sorted(expected_bonus_by_position.items())),
        realised_bonus_by_position=dict(sorted(realised_bonus_by_position.items())),
    )


def format_points_report_v3(result: PointsHarnessV3Result) -> str:
    lines = [
        "=== Stage D v3 FULL-points composition walk-forward (DEVELOPMENT ONLY) ===",
        f"folds evaluated : {result.folds_evaluated}",
        f"predictions     : {result.predictions}  (fixtures {result.fixtures})",
        f"Monte-Carlo     : {result.draws} draws, points support 0..{result.max_points}",
        f"Stage A fallbacks: {result.stage_a_fallbacks}",
        f"GK save_rate    : fold-local range [{result.save_rate_min:.4f}, "
        f"{result.save_rate_max:.4f}]",
        f"DC (prospective): folds with DC history {result.folds_with_dc_history}, "
        f"targets with p_hit>0 {result.dc_positive_predictions}",
        f"bonus (E vs realised): predicted {result.expected_bonus_total:.1f} vs realised "
        f"{result.realised_bonus_total:.1f}",
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
    lines.append("by position (E[bonus] vs realised bonus):")
    for position, report in result.by_position.items():
        predicted = result.expected_bonus_by_position.get(position, 0.0)
        realised = result.realised_bonus_by_position.get(position, 0.0)
        lines.append(row(f"  {position}", report) + f"   bonus {predicted:.0f}/{realised:.0f}")
    lines.append("")
    lines.append("by xG-coverage regime:")
    for regime, report in result.by_regime.items():
        lines.append(row(f"  {regime}", report))
    lines += [
        "",
        "DEVELOPMENT ONLY -- exploratory, not a promotion verdict and NOT a like-for-like delta",
        "against v2 (v2 scores non-bonus points; v3 scores FULL points incl. bonus). The 2021-22",
        "no-xG season is reported separately and kept out of the headline.",
        "See docs/phase4-stage-d-points-composition-v3-development.md.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the Stage D v3 FULL-points composition walk-forward (development-only)."
    )
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--season", action="append", dest="seasons", default=None)
    parser.add_argument("--draws", type=int, default=DEFAULT_DRAWS)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    con = connect(args.db, read_only=True)
    try:
        result = run_points_harness_v3(con, seasons=args.seasons, draws=args.draws)
    finally:
        con.close()
    print(format_points_report_v3(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
