"""Historical Point-in-Time Adapter for Stage D EV Walk-forward Backtest.

Connects DuckDB point-in-time state (kickoff_time < as_of) to prospective model fitting
and points composition logic (compose_fixture_full_points).

All DuckDB queries and point-in-time historical extraction logic reside strictly in this
validation adapter. Domain models under src/fpl/models/ remain database-free.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

import duckdb
import polars as pl

from fpl.config import (
    load_phase2_evaluation,
    load_phase3_evaluation,
    load_scoring_rules,
)
from fpl.jobs.prospective_points_v1 import (
    appeared_assist_signals,
    appeared_attack_signals,
    league_assist_rate,
    prospective_team_scored,
    resolve_assist_signal_kind,
    resolve_share_signal_kind,
    trailing5_minute_bins,
    trailing_ict,
)
from fpl.models.attacking_assists_baselines import AssistHistoryRow
from fpl.models.attacking_baselines import (
    PlayerHistoryRow,
    TargetRowProjection,
)
from fpl.models.attacking_baselines import (
    poisson_pmf as goal_poisson_pmf,
)
from fpl.models.attacking_v2 import _RosterEntry, mean_trailing_signal
from fpl.models.attacking_v3 import allocate_minutes_gated_rates
from fpl.models.bps_bonus import BpsSimConfig, fit_residual_model
from fpl.models.defensive_contribution_v1 import DcHistoryRow
from fpl.models.gk_saves_v1 import GkSavesHistoryRow
from fpl.models.points_composition import (
    DEFAULT_MAX_POINTS_FULL,
    BpsExactLookup,
    ComponentDistributions,
    ExtraScoring,
    FixturePlayer,
    PointsLookup,
    compose_fixture_full_points,
    representative_minutes,
)
from fpl.types import Position
from fpl.validate.metrics import Distribution
from fpl.validate.metrics import poisson_pmf as team_poisson_pmf
from fpl.validate.minutes_baselines import MinuteBins, TargetRow
from fpl.validate.minutes_harness import player_fixture_history, team_code_map
from fpl.validate.points_harness import (
    default_component_suite,
)
from fpl.validate.points_harness_v3 import (
    _fixture_seed,
    _residual_prediction,
    _residual_training_rows,
)

logger = logging.getLogger("fpl.validate.ev_backtest_adapter")


@dataclass(frozen=True, slots=True)
class ForecastTarget:
    season: str
    gw: int
    fixture: int
    kickoff_str: str
    kickoff_time: datetime
    code: int
    position: Position
    team_id: int
    opponent_team_id: int
    team_code: int
    opponent_team_code: int
    was_home: bool


@dataclass(frozen=True, slots=True)
class TargetLabel:
    season: str
    gw: int
    fixture: int
    code: int
    actual_points: int


@dataclass(frozen=True, slots=True)
class FixtureForecast:
    season: str
    gw: int
    fixture: int
    code: int
    expected_points: float
    pmf_full: tuple[float, ...]  # Support 0..34 (bin 34 represents 34+)


def derive_final_ten_gws(
    con: duckdb.DuckDBPyConnection, season: str = "2025-26"
) -> tuple[int, ...]:
    """Dynamically derive the final 10 observed gameweeks of the target season.

    Returns the gameweeks in ascending order and asserts exactly (29..38).
    """
    query = """
        SELECT DISTINCT gw
        FROM mart_fact_player_fixture
        WHERE season = ? AND minutes IS NOT NULL
        ORDER BY gw DESC
        LIMIT 10
    """
    rows = con.execute(query, [season]).fetchall()
    gws = tuple(sorted(r[0] for r in rows))
    expected = (29, 30, 31, 32, 33, 34, 35, 36, 37, 38)
    if gws != expected:
        raise ValueError(f"Derived gameweeks {gws} do not match expected horizon {expected}")
    return gws


def extract_target_roster_for_gw(
    con: duckdb.DuckDBPyConnection, season: str, gw: int
) -> list[ForecastTarget]:
    """Query eligible player-fixture targets for a gameweek.

    Reads ONLY identity and schedule metadata. Joined to mart_dim_team with season-qualified keys.
    fact.minutes IS NOT NULL serves as the frozen historical target-roster proxy.
    """
    query = """
        SELECT
            f.season,
            f.gw,
            f.fixture,
            strftime(CAST(f.kickoff_time AS TIMESTAMPTZ), '%Y-%m-%dT%H:%M:%SZ') AS kickoff_str,
            f.code,
            f.position,
            f.team_id,
            f.opponent_team_id,
            club.team_code AS team_code,
            opponent.team_code AS opponent_team_code,
            f.was_home
        FROM mart_fact_player_fixture AS f
        JOIN mart_dim_team AS club
          ON club.season = f.season AND club.team_id = f.team_id
        JOIN mart_dim_team AS opponent
          ON opponent.season = f.season AND opponent.team_id = f.opponent_team_id
        WHERE f.season = ? AND f.gw = ? AND f.minutes IS NOT NULL
        ORDER BY CAST(f.kickoff_time AS TIMESTAMPTZ) ASC, f.fixture ASC, f.code ASC
    """
    rows = con.execute(query, [season, gw]).fetchall()
    targets: list[ForecastTarget] = []
    for s_sn, s_gw, fix, k_str, code, pos_str, t_id, opp_id, t_code, opp_code, is_h in rows:
        k_ts = datetime.fromisoformat(str(k_str).replace("Z", "+00:00"))
        targets.append(
            ForecastTarget(
                season=str(s_sn),
                gw=int(s_gw),
                fixture=int(fix),
                kickoff_str=str(k_str),
                kickoff_time=k_ts,
                code=int(code),
                position=Position.from_archive_label(pos_str),
                team_id=int(t_id),
                opponent_team_id=int(opp_id),
                team_code=int(t_code),
                opponent_team_code=int(opp_code),
                was_home=bool(is_h),
            )
        )
    return targets


def extract_target_labels_for_gw(
    con: duckdb.DuckDBPyConnection, season: str, gw: int
) -> dict[tuple[str, int, int], TargetLabel]:
    """Query target labels from mart_target_player_fixture without minutes filter.

    Labels are loaded separately post-forecast. Requires exact key matching and non-NULL points.
    Never performs COALESCE to zero.
    """
    query = """
        SELECT
            season,
            gw,
            fixture,
            code,
            points_under_rules_2026_27 AS actual_points
        FROM mart_target_player_fixture
        WHERE season = ? AND gw = ?
    """
    rows = con.execute(query, [season, gw]).fetchall()
    labels: dict[tuple[str, int, int], TargetLabel] = {}
    for s_sn, s_gw, fix, code, pts in rows:
        if pts is None:
            raise ValueError(
                f"NULL points_under_rules_2026_27 for ({s_sn}, GW{s_gw}, fix {fix}, code {code})"
            )
        key = (str(s_sn), int(code), int(fix))
        if key in labels:
            raise ValueError(f"Duplicate label for target key {key}")
        labels[key] = TargetLabel(
            season=str(s_sn),
            gw=int(s_gw),
            fixture=int(fix),
            code=int(code),
            actual_points=int(pts),
        )
    return labels


@dataclass(frozen=True, slots=True)
class _PendingTarget:
    target: ForecastTarget
    minutes: tuple[float, float, float, float]
    v1_goals: Distribution
    v1_assists: Distribution
    team_goals_conceded: Distribution
    saves: Distribution
    dc_hit_probability: float
    residual_mean: float
    residual_sigma: float
    signal: float
    signal_cold_start: bool
    assist_signal: float
    assist_signal_cold_start: bool
    p_play: float


def generate_forecasts_for_fold(
    con: duckdb.DuckDBPyConnection,
    season: str,
    gw: int,
    *,
    use_v3_primary: bool = True,
    draws: int = 2000,
    base_seed: int = 202627,
    max_support: int = DEFAULT_MAX_POINTS_FULL,
) -> list[FixtureForecast]:
    """Generate prospective fixture full-points forecasts for a single fold gameweek.

    Fits component models on history kickoff_time < as_of.
    When use_v3_primary=True, allocates Primary V3 goals and coupled assists by team.
    When use_v3_primary=False, uses V1 goals and V1 assists.
    Calls compose_fixture_full_points ONCE per complete fixture roster per architecture.
    """
    targets = extract_target_roster_for_gw(con, season, gw)
    if not targets:
        return []

    as_of_row = con.execute(
        """
        SELECT strftime(CAST(MIN(kickoff_time) AS TIMESTAMPTZ), '%Y-%m-%dT%H:%M:%SZ')
        FROM mart_fact_player_fixture
        WHERE season = ? AND gw = ? AND minutes IS NOT NULL
        """,
        [season, gw],
    ).fetchone()
    if as_of_row is None or as_of_row[0] is None:
        raise ValueError(f"No kickoff_time found for fold {season} GW{gw}")
    as_of: datetime = datetime.fromisoformat(str(as_of_row[0]).replace("Z", "+00:00"))

    rules = load_scoring_rules("2026_27")
    if rules.bps is None:
        raise ValueError("scoring_2026_27.yaml has no bps block")
    bps = rules.bps
    bps_config = BpsSimConfig()
    phase2_config = load_phase2_evaluation()
    phase3_config = load_phase3_evaluation()
    bins = MinuteBins.from_config(phase2_config)
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

    suite = default_component_suite()

    # Team codes mapping
    team_codes = team_code_map(con)
    team_ids = set()
    for t in targets:
        team_ids.add(t.team_id)
        team_ids.add(t.opponent_team_id)
    team_map = {tid: team_codes.code(season, tid) for tid in team_ids}
    if len(team_map) != len(team_ids):
        raise ValueError(
            f"Incomplete team code coverage: mapped {len(team_map)} out of {len(team_ids)} team_ids"
        )

    # Build Stage A schedule frame from distinct real target-side rows
    by_fix_teams: dict[int, dict[int, tuple[int, bool]]] = defaultdict(dict)
    for t in targets:
        by_fix_teams[t.fixture][t.team_id] = (t.opponent_team_id, t.was_home)

    schedule_rows: list[dict[str, object]] = []
    for fix, t_dict in by_fix_teams.items():
        if len(t_dict) != 2:
            raise ValueError(f"Fixture {fix} expected 2 team sides, got {len(t_dict)}")
        team_items = list(t_dict.items())
        (t1_id, (t1_opp, t1_home)), (t2_id, (t2_opp, t2_home)) = team_items[0], team_items[1]
        if t1_opp != t2_id or t2_opp != t1_id or t1_home == t2_home:
            raise ValueError(
                f"Fixture {fix} non-reciprocal schedule sides: side 1 "
                f"({t1_id} vs {t1_opp}, home={t1_home}) vs side 2 "
                f"({t2_id} vs {t2_opp}, home={t2_home})"
            )
        home_teams = [tid for tid, (_, is_h) in t_dict.items() if is_h]
        if len(home_teams) != 1:
            raise ValueError(f"Fixture {fix} expected exactly 1 home team, got {len(home_teams)}")

        for tid, (opp_id, is_h) in t_dict.items():
            schedule_rows.append(
                {
                    "season": season,
                    "gw": gw,
                    "fixture": fix,
                    "team_id": tid,
                    "opponent_team_id": opp_id,
                    "was_home": is_h,
                    "goals_for": None,
                    "goals_against": None,
                }
            )

    schedule_df = pl.DataFrame(schedule_rows)
    team_scored, league_conceded = prospective_team_scored(
        con, season=season, as_of=as_of, team_map=team_map, schedule=schedule_df
    )
    league_conceded_dist = team_poisson_pmf(max(league_conceded, 1e-6))

    # Signal resolution for primary V3 goals & coupled assists
    share_window = 5
    signal_kind = resolve_share_signal_kind(
        season,
        frozenset(phase3_config.xg_signal_policy.xg_covered_seasons),
        "auto",
    )
    appeared, pos_signal_mean = appeared_attack_signals(con, as_of, kind=signal_kind)
    signal_by_code = {
        code: mean_trailing_signal(rows, kind=signal_kind, window=share_window)
        for code, rows in appeared.items()
    }

    assist_kind = resolve_assist_signal_kind(
        season,
        frozenset(phase3_config.xg_signal_policy.xg_covered_seasons),
        "auto",
    )
    assist_slot_kind = "expected_goals" if assist_kind == "expected_assists" else "threat"
    assist_appeared, pos_assist_signal_mean = appeared_assist_signals(con, as_of, kind=assist_kind)
    assist_signal_by_code = {
        code: mean_trailing_signal(rows, kind=assist_slot_kind, window=share_window)
        for code, rows in assist_appeared.items()
    }
    assist_rate = league_assist_rate(con, as_of)

    # Point-in-time component histories
    minutes_history = tuple(player_fixture_history(con, as_of=as_of))
    player_history_frame = (
        con.execute(
            """
        SELECT season, gw, fixture,
               strftime(CAST(kickoff_time AS TIMESTAMPTZ), '%Y-%m-%dT%H:%M:%SZ') AS kickoff_time,
               code, position, COALESCE(goals_scored, 0) AS goals,
               COALESCE(assists, 0) AS assists, minutes,
               saves, goals_conceded, defensive_contribution,
               expected_goals, expected_assists, creativity
        FROM mart_fact_player_fixture
        WHERE minutes IS NOT NULL AND CAST(kickoff_time AS TIMESTAMPTZ) < ?
        ORDER BY CAST(kickoff_time AS TIMESTAMPTZ), season, fixture, code
        """,
            [as_of],
        )
        .pl()
        .sort(["kickoff_time", "season", "fixture", "code"], maintain_order=True)
    )

    goals_history: list[PlayerHistoryRow] = []
    assists_history: list[AssistHistoryRow] = []
    saves_history: list[GkSavesHistoryRow] = []
    dc_history: list[DcHistoryRow] = []
    for r in player_history_frame.iter_rows(named=True):
        pos = Position.from_archive_label(r["position"])
        goals_history.append(
            PlayerHistoryRow(
                season=r["season"],
                gw=r["gw"],
                fixture=r["fixture"],
                kickoff_time=r["kickoff_time"],
                code=r["code"],
                position=pos,
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
                position=pos,
                assists=r["assists"],
                minutes=r["minutes"],
                expected_assists=r["expected_assists"],
                creativity=r["creativity"],
            )
        )
        saves_history.append(
            GkSavesHistoryRow(
                position=pos,
                minutes=r["minutes"],
                saves=r["saves"],
                goals_conceded=r["goals_conceded"],
            )
        )
        if r["defensive_contribution"] is not None:
            dc_history.append(
                DcHistoryRow(
                    code=r["code"],
                    position=pos,
                    minutes=r["minutes"],
                    defensive_contribution=r["defensive_contribution"],
                )
            )

    minutes_model = suite.fit_minutes(minutes_history, as_of)
    goals_model = suite.fit_goals(goals_history)
    assists_model = suite.fit_assists(assists_history)
    saves_model = suite.fit_saves(saves_history)
    dc_model = suite.fit_dc(dc_history, rules.defensive_contribution.thresholds)

    # Point-in-time BPS residual model & ICT
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
    ict_map = trailing_ict(con, as_of)
    trailing5_bins = trailing5_minute_bins(con, as_of, bins)

    # Group targets BY FIXTURE
    pending_by_fixture: dict[int, list[_PendingTarget]] = defaultdict(list)
    for t in targets:
        minutes_target = TargetRow(
            season=season,
            gw=gw,
            fixture=t.fixture,
            kickoff_time=t.kickoff_time,
            code=t.code,
            position=t.position,
            team_id=t.team_id,
            opponent_team_id=t.opponent_team_id,
            was_home=t.was_home,
        )
        stage_c_target = TargetRowProjection(
            season=season,
            gw=gw,
            fixture=t.fixture,
            kickoff_time=t.kickoff_str,
            code=t.code,
            position=t.position,
            team_id=t.team_id,
            opponent_team_id=t.opponent_team_id,
            was_home=t.was_home,
        )

        t5_entry, t5_n = trailing5_bins.get(t.code, (0.0, 0))
        minutes_dist: tuple[float, float, float, float]
        if t5_n >= 3:
            if isinstance(t5_entry, tuple):
                minutes_dist = (
                    float(t5_entry[0]),
                    float(t5_entry[1]),
                    float(t5_entry[2]),
                    float(t5_entry[3]),
                )
            else:
                rate = float(t5_entry)
                minutes_dist = (1.0 - rate, 0.0, 0.0, rate)
        else:
            minutes_dist = minutes_model.predict(minutes_target)

        v1_goals = goals_model.predict(stage_c_target)
        v1_assists = assists_model.predict(stage_c_target)

        conceded_dist = team_scored.get((t.fixture, t.opponent_team_code))
        if conceded_dist is None:
            conceded_dist = league_conceded_dist

        lambda_conceded = sum(idx * mass for idx, mass in enumerate(conceded_dist))
        saves_dist = saves_model.predict(t.position, lambda_conceded)
        dc_probability = dc_model.predict(t.code, t.position)

        # BPS residual prediction (zero target-row ICT read!)
        inf_val, cre_val = ict_map.get(t.code, (0.0, 0.0))
        residual_mean = _residual_prediction(
            residual_model,
            code=t.code,
            position=t.position.value,
            influence=inf_val,
            creativity=cre_val,
        )
        residual_sigma = residual_model.sigma(t.position.value)

        raw_sig = signal_by_code.get(t.code)
        sig_val = pos_signal_mean if raw_sig is None else raw_sig
        raw_asig = assist_signal_by_code.get(t.code)
        asig_val = pos_assist_signal_mean if raw_asig is None else raw_asig
        p_play = max(0.0, min(1.0, 1.0 - minutes_dist[0]))

        pending_by_fixture[t.fixture].append(
            _PendingTarget(
                target=t,
                minutes=minutes_dist,
                v1_goals=v1_goals,
                v1_assists=v1_assists,
                team_goals_conceded=conceded_dist,
                saves=saves_dist,
                dc_hit_probability=dc_probability,
                residual_mean=residual_mean,
                residual_sigma=residual_sigma,
                signal=sig_val,
                signal_cold_start=(raw_sig is None),
                assist_signal=asig_val,
                assist_signal_cold_start=(raw_asig is None),
                p_play=p_play,
            )
        )

    # Fixture-level goal & assist rate allocation
    def _fixture_goals(pending_list: list[_PendingTarget], fix: int) -> dict[int, Distribution]:
        if not use_v3_primary:
            return {p.target.code: p.v1_goals for p in pending_list}
        res: dict[int, Distribution] = {}
        by_team: dict[int, list[_PendingTarget]] = defaultdict(list)
        for p in pending_list:
            by_team[p.target.team_code].append(p)
        for t_code, roster_pending in by_team.items():
            own_scored = team_scored.get((fix, t_code))
            if own_scored is None:
                for p in roster_pending:
                    res[p.target.code] = p.v1_goals
                continue
            lambda_team = sum(idx * mass for idx, mass in enumerate(own_scored))
            roster = [
                _RosterEntry(p.target.code, p.signal, p.signal_cold_start) for p in roster_pending
            ]
            p_play_map = {p.target.code: p.p_play for p in roster_pending}
            allocated = allocate_minutes_gated_rates(
                roster, p_play_map, lambda_team, minutes_gating=True
            )
            for p in roster_pending:
                rate, _path = allocated[p.target.code]
                res[p.target.code] = goal_poisson_pmf(rate)
        return res

    def _fixture_assists(pending_list: list[_PendingTarget], fix: int) -> dict[int, Distribution]:
        if not use_v3_primary:
            return {p.target.code: p.v1_assists for p in pending_list}
        res: dict[int, Distribution] = {}
        by_team: dict[int, list[_PendingTarget]] = defaultdict(list)
        for p in pending_list:
            by_team[p.target.team_code].append(p)
        for t_code, roster_pending in by_team.items():
            own_scored = team_scored.get((fix, t_code))
            if own_scored is None:
                for p in roster_pending:
                    res[p.target.code] = p.v1_assists
                continue
            lambda_team = sum(idx * mass for idx, mass in enumerate(own_scored))
            lambda_assist = lambda_team * assist_rate
            roster = [
                _RosterEntry(p.target.code, p.assist_signal, p.assist_signal_cold_start)
                for p in roster_pending
            ]
            p_play_map = {p.target.code: p.p_play for p in roster_pending}
            allocated = allocate_minutes_gated_rates(
                roster, p_play_map, lambda_assist, minutes_gating=True
            )
            for p in roster_pending:
                rate, _path = allocated[p.target.code]
                res[p.target.code] = goal_poisson_pmf(rate)
        return res

    forecasts: list[FixtureForecast] = []

    for fix in sorted(pending_by_fixture):
        pending_list = pending_by_fixture[fix]
        # Sort roster deterministically by player code
        pending_list.sort(key=lambda p: p.target.code)

        fix_team_codes = {p.target.team_code for p in pending_list}
        if len(fix_team_codes) != 2:
            raise ValueError(
                f"Fixture {fix} expected 2 distinct team_codes, found {len(fix_team_codes)}"
            )

        goals_by_code = _fixture_goals(pending_list, fix)
        assists_by_code = _fixture_assists(pending_list, fix)

        fixture_players: list[FixturePlayer] = []
        for p in pending_list:
            components = ComponentDistributions(
                position=p.target.position,
                minutes=p.minutes,
                goals=goals_by_code[p.target.code],
                assists=assists_by_code[p.target.code],
                team_goals_conceded=p.team_goals_conceded,
                saves=p.saves,
                dc_hit_probability=p.dc_hit_probability,
            )
            fixture_players.append(
                FixturePlayer(
                    code=p.target.code,
                    components=components,
                    residual_mean=p.residual_mean,
                    residual_sigma=p.residual_sigma,
                )
            )

        # Deterministic per-fixture seed (IDENTICAL base seed for Primary and Comparator)
        row_seed = _fixture_seed(base_seed, season, fix)

        # ONE compose_fixture_full_points call per complete fixture roster
        composed_list = compose_fixture_full_points(
            fixture_players,
            lookup,
            bps_lookup,
            extra,
            fixture_seed=row_seed,
            draws=draws,
            max_points=max_support,
        )

        for comp in composed_list:
            ep = sum(k * p for k, p in enumerate(comp.distribution))
            forecasts.append(
                FixtureForecast(
                    season=season,
                    gw=gw,
                    fixture=fix,
                    code=comp.code,
                    expected_points=ep,
                    pmf_full=comp.distribution,
                )
            )

    return forecasts
