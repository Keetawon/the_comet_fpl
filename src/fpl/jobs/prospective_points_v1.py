"""Prospective full-points xP over a multi-gameweek horizon (DEVELOPMENT-ONLY).

    python -m fpl.jobs.prospective_points_v1                     # GW1-5 2026/27 at the GW1 deadline
    python -m fpl.jobs.prospective_points_v1 --gw-from 1 --gw-to 6  # extend the planning horizon

This is the **prospective sibling** of the Stage D v3 walk-forward (`points_harness_v3`). It fits
the best-development component suite (minutes V3; the **team-coupled minutes-gated goals Candidate
V3** by default, or the independent goals V1 via ``--attacking v1``; assists V1; team goals-conceded
from the promoted Stage A `trailing_goals_attack_defence`; GK saves V1; DC V1) plus the fold-local
point-in-time BPS residual, all on the archive under the strict cutoff ``kickoff_time < as_of``,
then composes a per-player-fixture **full points** distribution (including bonus) for every fixture
in the requested *future* gameweeks. It scores nothing -- those gameweeks have not been played --
and emits the distribution, its expected points, and an aggregate expected-points total per player
across the horizon. The multi-gameweek horizon is the FPL transfer-planning use case: an extra
transfer costs a -4 hit, so a squad is planned several gameweeks ahead against one *current-form*
information set.

**Everything here is DEVELOPMENT-ONLY and NOT a validated production forecast.** Every component is
an unpromoted development-stage estimator carrying the unversioned historical proxies of its stage,
and this composition adds them independently (no team-goal conservation). Its point-in-time safety
is real -- the versioned live registry selects the roster, the versioned live schedule supplies the
fixtures, and every trailing history obeys ``kickoff_time < as_of`` -- but validity is established
prospectively as 2026/27 accrues, not here.

Prospective-specific behaviour, all documented in the output record:

  * **Current-form / frozen horizon.** All trailing windows are frozen at ``as_of``; GW2..N reuse
    the same information set as GW1 (no in-season update) -- the correct forecast at one deadline.
  * **Goals are team-coupled and opponent-aware by default (Candidate V3).** The Stage A team-goal
    expectation ``lambda_team`` (itself opponent/venue-modulated) is allocated among a club's
    players by a minutes-gated trailing attacking share, conserving the team total -- so a player's
    goals respond to the opponent across the horizon. The share signal is **xG in the xG era by
    default** (``--share-signal auto``; FPL xG embeds penalty xG, so a clinical finisher / penalty
    taker takes a larger, grounded share), overridable with ``--share-signal threat``. Assists
    remain the independent Candidate V1 (per-player, fixture-blind); ``--attacking v1`` reverts.
  * **Season-boundary appearance correction (default).** The trailing-minutes window at a GW1
    deadline is the END of the prior season -- its least representative phase, since a nailed
    starter rested in dead-rubber final fixtures reads as a rotation risk. By default
    (``--appearance seasonal``) an early-season target blends the model's recent appearance with the
    player's full prior-season appearance rate (measured: the boundary-robust nailed-ness signal
    predicts a next-season opener better than the last five rows), preserving the model's when-
    playing minute shape; ``--appearance model`` uses the raw trailing distribution. Even so,
    cross-season appearance is genuinely uncertain (measured MAE ~0.22; nailed-last-season players
    average ~0.78 early next season), so this lifts rested starters without pretending to certainty.
  * **Promoted clubs get league-average team strength.** ``trailing_goals_attack_defence`` keys
    attack and defence on ``team_code``; a club with no archive history (a genuine cold-start
    promotion) falls back to the league-average multiplier (1.0), not the promoted prior. Flagged.
  * **No transfer rescaling.** Stage C V1 carries a transferred player's own trailing rate to his
    new club without rescaling to the destination team's scale (a documented Stage C V1 limitation).
  * **Availability overlay.** The raw model does NOT consume availability. A transparent post-model
    overlay (``status`` / ``chance_of_playing_next_round`` from the deadline bootstrap) is reported
    ALONGSIDE the raw expected points, never folded into the distribution.
  * **BPS residual proxies are trailing.** A future fixture has no realised ICT, so the BPS
    residual's ``influence`` / ``creativity`` inputs are each player's trailing mean under the
    cutoff (0 when the player has no history), never a realised target value.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl

from fpl.config import (
    config_dir,
    load_phase2_evaluation,
    load_phase3_evaluation,
    load_scoring_rules,
    repo_root,
)
from fpl.features.pit import AsOf, FeatureSource, PointInTimeView
from fpl.models.attacking_assists_baselines import AssistHistoryRow
from fpl.models.attacking_baselines import (
    PlayerHistoryRow,
    TargetRowProjection,
)
from fpl.models.attacking_baselines import (
    poisson_pmf as goal_poisson_pmf,
)
from fpl.models.attacking_v2 import _RosterEntry, mean_trailing_signal, season_signal_kind
from fpl.models.attacking_v3 import allocate_minutes_gated_rates
from fpl.models.bps_bonus import BpsSimConfig, fit_residual_model
from fpl.models.defensive_contribution_v1 import DcHistoryRow
from fpl.models.gk_saves_v1 import GkSavesHistoryRow
from fpl.models.points_composition import (
    DEFAULT_MAX_POINTS_FULL,
    BpsExactLookup,
    ComponentDistributions,
    ComposedPlayer,
    ExtraScoring,
    FixturePlayer,
    PointsLookup,
    compose_fixture_full_points,
    representative_minutes,
)
from fpl.storage.db import connect, default_db_path
from fpl.types import Position
from fpl.validate.freshness import FreshnessError, require_prospective_freshness
from fpl.validate.metrics import Distribution, poisson_pmf
from fpl.validate.minutes_baselines import MinuteBins, TargetRow
from fpl.validate.minutes_harness import player_fixture_history
from fpl.validate.points_harness import (
    TARGET_RULESET,
    PointsComponentSuite,
    default_component_suite,
)
from fpl.validate.points_harness_v3 import (
    DEFAULT_DRAWS,
    _fixture_seed,
    _residual_prediction,
    _residual_training_rows,
)

if TYPE_CHECKING:
    import duckdb

logger = logging.getLogger("fpl.jobs.prospective_points_v1")

# GW1 2026/27 deadline -- the default knowledge-time cutoff for a prospective GW1-onward forecast.
GW1_2026_27_DEADLINE = datetime.fromisoformat("2026-08-21T17:30:00+00:00")
DEFAULT_SEASON = "2026-27"
DEFAULT_GW_FROM = 1
DEFAULT_GW_TO = 5
BASE_SEED = 202627

_DISCLAIMER = (
    "DEVELOPMENT-ONLY: prospective full-points xP composed from unpromoted development-stage "
    "components. NOT a validated production forecast; it claims no historical lift. Point-in-time "
    "safe (versioned registry + schedule, kickoff_time < as_of), but validity is established "
    "prospectively as 2026/27 accrues, not here. Goals are team-coupled/opponent-aware (V3 "
    "default) but assists are not; appearance uses a season-boundary correction (prior-season "
    "nailed-ness blended in early season) yet cross-season appearance stays uncertain; promoted "
    "clubs use league-average team strength; no transfer rescaling; availability is a reported "
    "overlay."
)


def _git_head(repo: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expected_points(distribution: Distribution) -> float:
    return sum(index * mass for index, mass in enumerate(distribution))


def team_code_map_live(con: duckdb.DuckDBPyConnection, season: str) -> dict[int, int]:
    """Season-scoped ``team_id -> team_code`` for a live season, from the stored bootstrap payload.

    The live snapshot loader does not populate ``stg_team``/``mart_dim_team`` for the live season,
    so the (season-scoped) team id to permanent ``team_code`` map is read from the most-recent
    ``bootstrap-static`` payload. ``team_code`` is the only cross-season club key
    ``trailing_goals_attack_defence`` accepts.
    """
    row = con.execute(
        """
        SELECT p.payload
        FROM snapshot_payload AS p
        JOIN snapshot_capture AS c ON c.capture_id = p.capture_id
        WHERE p.endpoint = 'bootstrap-static' AND c.season = ?
        ORDER BY c.captured_at DESC
        LIMIT 1
        """,
        [season],
    ).fetchone()
    if row is None or row[0] is None:
        raise ValueError(f"no bootstrap-static payload captured for season {season}")
    payload = row[0]
    data = json.loads(payload) if isinstance(payload, str) else payload
    return {int(team["id"]): int(team["code"]) for team in data["teams"]}


def player_availability(
    con: duckdb.DuckDBPyConnection, season: str
) -> dict[int, tuple[str, float | None]]:
    """``code -> (status, chance_of_playing_next_round)`` from the most-recent bootstrap payload.

    ``status`` is the FPL flag (``a`` available, ``d`` doubtful, ``i`` injured, ``s`` suspended,
    ``u`` unavailable, ``n`` not in squad). ``chance`` is a percentage in ``[0, 100]`` or ``None``.
    This feeds the reported availability OVERLAY only; it is never a model input.
    """
    row = con.execute(
        """
        SELECT p.payload
        FROM snapshot_payload AS p
        JOIN snapshot_capture AS c ON c.capture_id = p.capture_id
        WHERE p.endpoint = 'bootstrap-static' AND c.season = ?
        ORDER BY c.captured_at DESC
        LIMIT 1
        """,
        [season],
    ).fetchone()
    if row is None or row[0] is None:
        return {}
    payload = row[0]
    data = json.loads(payload) if isinstance(payload, str) else payload
    out: dict[int, tuple[str, float | None]] = {}
    for element in data["elements"]:
        chance = element.get("chance_of_playing_next_round")
        out[int(element["code"])] = (
            str(element.get("status", "a")),
            None if chance is None else float(chance),
        )
    return out


def availability_multiplier(status: str, chance: float | None) -> float:
    """Transparent overlay weight in ``[0, 1]``: an explicit chance wins, else status decides."""
    if chance is not None:
        return max(0.0, min(1.0, chance / 100.0))
    if status == "a":
        return 1.0
    if status in {"i", "s", "u", "n"}:
        return 0.0
    return 0.5  # doubtful with no published percentage


def trailing_ict(con: duckdb.DuckDBPyConnection, as_of: datetime) -> dict[int, tuple[float, float]]:
    """``code -> (mean influence, mean creativity)`` over appeared history before ``as_of``.

    The BPS residual's ICT proxies for a *future* fixture: a player's own trailing mean, never a
    realised target value. Absent codes fall back to ``(0.0, 0.0)`` at the call site.
    """
    frame = con.execute(
        """
        SELECT code,
               avg(influence) AS influence,
               avg(creativity) AS creativity
        FROM mart_fact_player_fixture
        WHERE minutes IS NOT NULL AND kickoff_time < ?
          AND influence IS NOT NULL AND creativity IS NOT NULL
        GROUP BY code
        """,
        [as_of],
    ).pl()
    return {
        int(r["code"]): (float(r["influence"]), float(r["creativity"]))
        for r in frame.iter_rows(named=True)
    }


def last_team_code(con: duckdb.DuckDBPyConnection, as_of: datetime) -> dict[int, int]:
    """``code -> team_code`` of the club a player last appeared for before ``as_of`` (transfer)."""
    frame = con.execute(
        """
        WITH ranked AS (
            SELECT f.code, t.team_code,
                   row_number() OVER (PARTITION BY f.code ORDER BY f.kickoff_time DESC) AS rn
            FROM mart_fact_player_fixture AS f
            JOIN mart_dim_team AS t ON t.season = f.season AND t.team_id = f.team_id
            WHERE f.minutes IS NOT NULL AND f.kickoff_time < ?
        )
        SELECT code, team_code FROM ranked WHERE rn = 1
        """,
        [as_of],
    ).pl()
    return {int(r["code"]): int(r["team_code"]) for r in frame.iter_rows(named=True)}


# Minimum prior-season appearances for the long-window rate to be trusted over the model estimate.
_MIN_PRIOR_SEASON_ROWS = 10


def prior_season_appearance_rate(
    con: duckdb.DuckDBPyConnection, as_of: datetime
) -> dict[int, tuple[float, int]]:
    """``code -> (appearance rate, n)`` over the player's most-recent completed season before as_of.

    The season-boundary appearance fix. A prediction at a season-start deadline has a trailing
    window that is the END of the prior season -- the least representative phase (measured: nailed
    players fall from ~0.876 appearance in Aug-Nov to ~0.804 in May, dead-rubber rotation). The full
    prior-season appearance rate ``P(minutes >= 1)`` is the boundary-robust nailed-ness signal
    (measured: it predicts next-season GW1-6 appearance better than the last-five rows). Point in
    time: only ``kickoff_time < as_of``; the "most recent season" is per ``code``.
    """
    frame = con.execute(
        """
        WITH elig AS (
            SELECT code, season,
                   CASE WHEN minutes >= 1 THEN 1.0 ELSE 0.0 END AS played
            FROM mart_fact_player_fixture
            WHERE minutes IS NOT NULL AND kickoff_time < ?
        ),
        latest AS (SELECT code, max(season) AS season FROM elig GROUP BY code)
        SELECT e.code, avg(e.played) AS rate, count(*) AS n
        FROM elig AS e
        JOIN latest AS l ON l.code = e.code AND l.season = e.season
        GROUP BY e.code
        """,
        [as_of],
    ).pl()
    return {int(r["code"]): (float(r["rate"]), int(r["n"])) for r in frame.iter_rows(named=True)}


def _season_boundary_long_weight(month: int) -> float:
    """Weight on the long (prior-season) appearance rate vs the recent model estimate, by month.

    The trailing window only straddles the summer break for early-season targets, so the long-window
    correction is applied there and fades to zero in-season (where the recent estimate is reliable).
    Grounded in the measured phase effect (Aug-Nov fullest, May worst) and the measured blend that
    best predicts a next-season opener (~0.7 long + 0.3 recent).
    """
    if month in (8, 9):
        return 0.7
    if month in (10, 11):
        return 0.5
    return 0.0


def season_boundary_minutes(
    minutes: tuple[float, float, float, float],
    *,
    prior_rate: float | None,
    prior_n: int,
    target_month: int,
) -> tuple[float, float, float, float]:
    """Reshape a 4-bin minutes distribution so appearance probability reflects nailed-ness at a
    season boundary, preserving the model's conditional (when-playing) minute shape.

    ``p_play`` is blended ``w * prior_rate + (1 - w) * recent`` (``w`` from
    :func:`_season_boundary_long_weight`); the freed/added mass is redistributed across the playing
    bins in the model's own proportions, so a nailed starter rested in dead rubbers regains his
    appearance points AND his coupled goal share without inventing a minute shape. Availability is
    NOT applied here (it stays the separate reported overlay, never double-counted).
    """
    p0, p1, p2, p3 = minutes
    p_recent = 1.0 - p0
    weight = _season_boundary_long_weight(target_month)
    if prior_rate is None or prior_n < _MIN_PRIOR_SEASON_ROWS or weight <= 0.0:
        return minutes
    p_play = max(0.0, min(1.0, weight * prior_rate + (1.0 - weight) * p_recent))
    play_model = p1 + p2 + p3
    if play_model <= 1e-12:
        # The model gives no when-playing shape; default a re-confirmed starter toward a full match.
        return (1.0 - p_play, 0.0, p_play * 0.15, p_play * 0.85)
    scale = p_play / play_model
    return (1.0 - p_play, p1 * scale, p2 * scale, p3 * scale)


def appeared_attack_signals(
    con: duckdb.DuckDBPyConnection, as_of: datetime, *, kind: str
) -> tuple[dict[int, list[tuple[float, float | None, float | None]]], float]:
    """Trailing attacking-signal history for the team-coupled (V3) goals allocation.

    Returns ``{code: [(kickoff_epoch, expected_goals, threat), ...]}`` over APPEARED prior rows
    (``minutes > 0``, ``kickoff_time < as_of``, chronological) and the pooled mean of the chosen
    ``kind`` signal (the cold-start share fill). NULL signal values are preserved as ``None`` (never
    zero-filled). Mirrors Candidate V3's appeared-signal construction so the share primitive is the
    committed one.
    """
    frame = con.execute(
        """
        SELECT season, gw, fixture, kickoff_time, code, expected_goals, threat
        FROM mart_fact_player_fixture
        WHERE minutes IS NOT NULL AND minutes > 0 AND kickoff_time < ?
        ORDER BY kickoff_time, season, fixture, code
        """,
        [as_of],
    ).pl()
    if not frame.is_empty():
        frame = frame.sort(["kickoff_time", "season", "fixture", "code"], maintain_order=True)
    appeared: dict[int, list[tuple[float, float | None, float | None]]] = {}
    sig_sum = 0.0
    sig_n = 0
    for r in frame.iter_rows(named=True):
        epoch = float(r["kickoff_time"].timestamp())
        xg = None if r["expected_goals"] is None else float(r["expected_goals"])
        threat = None if r["threat"] is None else float(r["threat"])
        appeared.setdefault(int(r["code"]), []).append((epoch, xg, threat))
        value = xg if kind == "expected_goals" else threat
        if value is not None:
            sig_sum += value
            sig_n += 1
    pos_signal_mean = (sig_sum / sig_n) if sig_n > 0 else 0.0
    return appeared, pos_signal_mean


def resolve_share_signal_kind(season: str, xg_covered: frozenset[str], mode: str) -> str:
    """The team-share signal for the coupled goals path: ``expected_goals`` or ``threat``.

    ``mode='xg'``/``'threat'`` force it. ``mode='auto'`` uses xG for an xG-era target season -- one
    in the frozen ``xg_covered_seasons`` OR a future season after the latest covered one -- because
    a future season's trailing rows come from xG-covered seasons and FPL ``expected_goals`` embeds
    penalty xG, so an xG-share captures both chance quality and the penalty-taker premium (which the
    archive cannot separate from open-play goals) on one scale. It falls back to the frozen
    per-season rule (threat) only for a genuinely pre-xG season. Kept per season (never per player):
    xG and threat are different scales and must not be mixed within one club roster.
    """
    if mode == "xg":
        return "expected_goals"
    if mode == "threat":
        return "threat"
    if season in xg_covered or (xg_covered and season > max(xg_covered)):
        return "expected_goals"
    return season_signal_kind(season, xg_covered)


def prospective_team_scored(
    con: duckdb.DuckDBPyConnection,
    *,
    season: str,
    as_of: datetime,
    team_map: dict[int, int],
    schedule: pl.DataFrame,
) -> tuple[dict[tuple[int, int], Distribution], float]:
    """Fit ``trailing_goals_attack_defence`` on history < ``as_of`` and predict each team's scored
    goals for every scheduled fixture in ``schedule``.

    Returns ``{(fixture, team_code): scored-goals distribution}`` and the league mean goals conceded
    (the explicit fallback). A player's team-conceded distribution is the OPPONENT's entry.
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
    league_conceded = 1.4
    if not window_frame.is_empty():
        conceded = window_frame["goals_against"].drop_nulls()
        if conceded.len():
            value = conceded.mean()
            if isinstance(value, (int, float)):
                league_conceded = float(value)

    model = TrailingGoalsAttackDefence()
    model.fit(TrainingWindow(window_frame))

    # Build the prediction frame from the live schedule (one row per team-side). Every column the
    # model's predict() reads is present; realised outcome columns are filled with nulls it ignores.
    rows: list[dict[str, object]] = []
    for r in schedule.iter_rows(named=True):
        team_id = int(r["team_id"])
        opponent_id = int(r["opponent_team_id"])
        team_code = team_map.get(team_id)
        opponent_code = team_map.get(opponent_id)
        if team_code is None or opponent_code is None:
            continue
        rows.append(
            {
                "season": season,
                "gw": int(r["gw"]),
                "fixture": int(r["fixture"]),
                "was_home": bool(r["was_home"]),
                "team_code": team_code,
                "opponent_team_code": opponent_code,
                "goals_for": None,
                "goals_against": None,
                "team_xg": None,
                "team_xgc": None,
                "fdr": None,
            }
        )
    if not rows:
        return {}, league_conceded
    fixtures_frame = pl.DataFrame(rows)
    predictions = model.predict(fixtures_frame)
    by_team: dict[tuple[int, int], Distribution] = {}
    for row_map, distribution in zip(
        fixtures_frame.iter_rows(named=True), predictions, strict=True
    ):
        if distribution is None:
            continue
        by_team[(int(row_map["fixture"]), int(row_map["team_code"]))] = distribution
    return by_team, league_conceded


@dataclass(frozen=True, slots=True)
class ProspectivePointsRecord:
    season: str
    gw: int
    fixture: int
    kickoff_time: datetime
    code: int
    position: str
    team_id: int
    team_code: int | None
    opponent_team_id: int
    was_home: bool
    expected_points: float
    expected_bonus: float
    availability_status: str
    availability_multiplier: float
    availability_adjusted_points: float
    stage_a_league_average_team: bool
    cold_start_player: bool
    transferred_no_rescale: bool
    distribution: Distribution


@dataclass(frozen=True, slots=True)
class ProspectivePlayerTotal:
    code: int
    position: str
    team_id: int
    team_code: int | None
    fixtures: int
    expected_points: float
    availability_adjusted_points: float
    availability_status: str
    cold_start_player: bool
    transferred_no_rescale: bool


@dataclass(frozen=True, slots=True)
class ProspectivePointsResult:
    as_of: datetime
    season: str
    gw_from: int
    gw_to: int
    draws: int
    max_points: int
    roster_size: int
    fixture_count: int
    attacking_mode: str
    share_signal_kind: str
    appearance_mode: str
    freshness_cold_start: bool
    records: tuple[ProspectivePointsRecord, ...]
    player_totals: tuple[ProspectivePlayerTotal, ...]
    component_names: dict[str, str]
    commit_sha: str | None
    config_sha256: str | None
    archive_sha256: str | None


def predict_prospective_points(
    con: duckdb.DuckDBPyConnection,
    *,
    as_of: datetime,
    season: str = DEFAULT_SEASON,
    gw_from: int = DEFAULT_GW_FROM,
    gw_to: int = DEFAULT_GW_TO,
    attacking: str = "v3",
    appearance: str = "seasonal",
    share_signal: str = "auto",
    suite: PointsComponentSuite | None = None,
    draws: int = DEFAULT_DRAWS,
    base_seed: int = BASE_SEED,
    max_points: int = DEFAULT_MAX_POINTS_FULL,
    db_path: Path | str | None = None,
    repo: Path | None = None,
) -> ProspectivePointsResult:
    """Compose prospective full-points xP for ``season`` GW ``gw_from``..``gw_to`` at ``as_of``."""
    if gw_to < gw_from:
        raise ValueError(f"gw_to ({gw_to}) < gw_from ({gw_from})")
    if attacking not in {"v1", "v3"}:
        raise ValueError(f"attacking must be 'v1' or 'v3', got {attacking!r}")
    if appearance not in {"model", "seasonal"}:
        raise ValueError(f"appearance must be 'model' or 'seasonal', got {appearance!r}")
    if share_signal not in {"auto", "xg", "threat"}:
        raise ValueError(f"share_signal must be 'auto', 'xg', or 'threat', got {share_signal!r}")
    resolved_suite = suite or default_component_suite()

    # 0. Freshness gate: refuse to emit if the current season's most-recent-completed gameweek is
    #    not captured. Season start is a legitimate cold start and passes.
    freshness = require_prospective_freshness(con, as_of=as_of)

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

    # 1. Roster + schedule from the versioned live tables (known_at <= as_of).
    view = PointInTimeView(FeatureSource(con), AsOf(as_of))
    registry = view.player_registry()
    reg_codes: list[Any] = registry["code"].to_list()
    reg_positions: list[Any] = registry["position"].to_list()
    reg_teams: list[Any] = registry["team_id"].to_list()

    gws = list(range(gw_from, gw_to + 1))
    schedule = view.schedule(seasons=[season]).filter(
        (pl.col("season") == pl.lit(season)) & (pl.col("gw").is_in(gws))
    )
    fixture_count = int(schedule["fixture"].n_unique()) if schedule.height else 0

    team_map = team_code_map_live(con, season)
    availability = player_availability(con, season)
    trailing = trailing_ict(con, as_of)
    last_team = last_team_code(con, as_of)
    codes_with_history = set(last_team)
    prior_appearance = prior_season_appearance_rate(con, as_of) if appearance == "seasonal" else {}

    # 2. Point-in-time component histories + fitted models (identical construction to the v3 fold).
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

    minutes_model = resolved_suite.fit_minutes(minutes_history, as_of)
    goals_model = resolved_suite.fit_goals(goals_history)
    assists_model = resolved_suite.fit_assists(assists_history)
    saves_model = resolved_suite.fit_saves(saves_history)
    dc_model = resolved_suite.fit_dc(dc_history, rules.defensive_contribution.thresholds)
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

    # 3. Stage A conceded distributions predicted over the scheduled fixtures.
    team_scored, league_conceded = prospective_team_scored(
        con, season=season, as_of=as_of, team_map=team_map, schedule=schedule
    )
    league_conceded_dist = poisson_pmf(max(league_conceded, 1e-6))

    # 3b. Team-coupled (V3) goals allocation inputs. The share signal (xG vs threat) is resolved per
    #     season on one scale: `--share-signal auto` uses xG for an xG-era target (default), so a
    #     clinical finisher / penalty taker takes a larger, grounded share (xG embeds penalty xG).
    #     Only built for the coupled path.
    share_window = 5
    signal_kind = resolve_share_signal_kind(
        season,
        frozenset(load_phase3_evaluation().xg_signal_policy.xg_covered_seasons),
        share_signal,
    )
    signal_by_code: dict[int, float | None] = {}
    pos_signal_mean = 0.0
    if attacking == "v3":
        appeared, pos_signal_mean = appeared_attack_signals(con, as_of, kind=signal_kind)
        signal_by_code = {
            code: mean_trailing_signal(rows, kind=signal_kind, window=share_window)
            for code, rows in appeared.items()
        }

    # 4. Assemble targets: registry players x their scheduled fixtures, grouped by fixture (the
    #    whole-fixture population is both teams -- exactly the bonus-ranking population).
    fixtures_by_team: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for r in schedule.iter_rows(named=True):
        fixtures_by_team[int(r["team_id"])].append(
            {
                "gw": int(r["gw"]),
                "fixture": int(r["fixture"]),
                "kickoff_time": r["kickoff_time"],
                "opponent_team_id": int(r["opponent_team_id"]),
                "was_home": bool(r["was_home"]),
            }
        )

    # A pending target carries every component EXCEPT goals, plus the V1 goals fallback and the
    # coupling inputs (team_code, trailing share signal, appearance probability). The goals
    # component is finalised per fixture in phase 5, because the team-coupled (V3) path allocates a
    # whole club's Stage A team-goal total among its players and so cannot be decided one row at a
    # time.
    @dataclass(frozen=True, slots=True)
    class _Pending:
        code: int
        position: Position
        team_id: int
        team_code: int | None
        opponent_team_id: int
        was_home: bool
        gw: int
        kickoff_time: datetime
        minutes: tuple[float, float, float, float]
        assists: Distribution
        team_goals_conceded: Distribution
        saves: Distribution
        dc_hit_probability: float
        residual_mean: float
        residual_sigma: float
        v1_goals: Distribution
        signal: float
        signal_cold_start: bool
        p_play: float
        stage_a_league_average: bool
        cold_start: bool
        transferred: bool

    by_fixture: dict[int, list[_Pending]] = defaultdict(list)
    for index in range(len(reg_codes)):
        code = int(reg_codes[index])
        position = Position(str(reg_positions[index]))
        team_id = int(reg_teams[index])
        team_code = team_map.get(team_id)
        cold_start = code not in codes_with_history
        transferred = (
            (not cold_start) and team_code is not None and last_team.get(code) != team_code
        )
        influence, creativity = trailing.get(code, (0.0, 0.0))
        raw_signal = signal_by_code.get(code)
        signal_cold_start = raw_signal is None
        signal_value = pos_signal_mean if raw_signal is None else raw_signal
        for fx in fixtures_by_team.get(team_id, ()):
            fixture = fx["fixture"]
            opponent_team_id = fx["opponent_team_id"]
            was_home = fx["was_home"]
            gw = fx["gw"]
            kickoff_ts: datetime = fx["kickoff_time"]
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
                kickoff_time=kickoff_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                code=code,
                position=position,
                team_id=team_id,
                opponent_team_id=opponent_team_id,
                was_home=was_home,
            )
            minutes_dist = minutes_model.predict(minutes_target)
            if appearance == "seasonal":
                prior_rate, prior_n = prior_appearance.get(code, (None, 0))
                minutes_dist = season_boundary_minutes(
                    minutes_dist,
                    prior_rate=prior_rate,
                    prior_n=prior_n,
                    target_month=kickoff_ts.month,
                )
            v1_goals = goals_model.predict(stage_c_target)
            assists_dist = assists_model.predict(stage_c_target)

            opponent_code = team_map.get(opponent_team_id)
            conceded_dist = (
                team_scored.get((fixture, opponent_code)) if opponent_code is not None else None
            )
            stage_a_league_average = conceded_dist is None
            if conceded_dist is None:
                conceded_dist = league_conceded_dist
            lambda_conceded = sum(i * mass for i, mass in enumerate(conceded_dist))
            saves_dist = saves_model.predict(position, lambda_conceded)
            dc_probability = dc_model.predict(code, position)
            residual_mean = _residual_prediction(
                residual_model,
                code=code,
                position=position.value,
                influence=influence,
                creativity=creativity,
            )
            # Appearance probability from the composer's own minutes component (P(minutes >= 1)).
            p_play = max(0.0, min(1.0, 1.0 - minutes_dist[0]))
            by_fixture[fixture].append(
                _Pending(
                    code=code,
                    position=position,
                    team_id=team_id,
                    team_code=team_code,
                    opponent_team_id=opponent_team_id,
                    was_home=was_home,
                    gw=gw,
                    kickoff_time=kickoff_ts,
                    minutes=minutes_dist,
                    assists=assists_dist,
                    team_goals_conceded=conceded_dist,
                    saves=saves_dist,
                    dc_hit_probability=dc_probability,
                    residual_mean=residual_mean,
                    residual_sigma=residual_model.sigma(position.value),
                    v1_goals=v1_goals,
                    signal=signal_value,
                    signal_cold_start=signal_cold_start,
                    p_play=p_play,
                    stage_a_league_average=stage_a_league_average,
                    cold_start=cold_start,
                    transferred=transferred,
                )
            )

    def _fixture_goals(pending: list[_Pending], fixture: int) -> dict[int, Distribution]:
        """Goals distribution per code for one fixture: team-coupled (V3) or independent (V1)."""
        if attacking != "v3":
            return {p.code: p.v1_goals for p in pending}
        goals: dict[int, Distribution] = {}
        by_team: dict[int, list[_Pending]] = defaultdict(list)
        for p in pending:
            if p.team_code is None:
                goals[p.code] = p.v1_goals  # unresolved club -> fall back to the independent rate
            else:
                by_team[p.team_code].append(p)
        for team_code, roster_pending in by_team.items():
            own_scored = team_scored.get((fixture, team_code))
            if own_scored is None:  # Stage A uninformative for this club -> independent fallback
                for p in roster_pending:
                    goals[p.code] = p.v1_goals
                continue
            lambda_team = sum(i * mass for i, mass in enumerate(own_scored))
            roster = [_RosterEntry(p.code, p.signal, p.signal_cold_start) for p in roster_pending]
            p_play_map = {p.code: p.p_play for p in roster_pending}
            allocated = allocate_minutes_gated_rates(
                roster, p_play_map, lambda_team, minutes_gating=True
            )
            for p in roster_pending:
                rate, _path = allocated[p.code]
                goals[p.code] = goal_poisson_pmf(rate)
        return goals

    # 5. Joint per-fixture composition -> full-points distribution per player.
    records: list[ProspectivePointsRecord] = []
    for fixture in sorted(by_fixture):
        targets = by_fixture[fixture]
        goals_by_code = _fixture_goals(targets, fixture)
        players = [
            FixturePlayer(
                code=t.code,
                components=ComponentDistributions(
                    position=t.position,
                    minutes=t.minutes,
                    goals=goals_by_code[t.code],
                    assists=t.assists,
                    team_goals_conceded=t.team_goals_conceded,
                    saves=t.saves,
                    dc_hit_probability=t.dc_hit_probability,
                ),
                residual_mean=t.residual_mean,
                residual_sigma=t.residual_sigma,
            )
            for t in targets
        ]
        composed = compose_fixture_full_points(
            players,
            lookup,
            bps_lookup,
            extra,
            fixture_seed=_fixture_seed(base_seed, season, fixture),
            draws=draws,
            max_points=max_points,
        )
        by_code: dict[int, ComposedPlayer] = {c.code: c for c in composed}
        for t in targets:
            result = by_code[t.code]
            expected = _expected_points(result.distribution)
            status, chance = availability.get(t.code, ("a", None))
            mult = availability_multiplier(status, chance)
            records.append(
                ProspectivePointsRecord(
                    season=season,
                    gw=t.gw,
                    fixture=fixture,
                    kickoff_time=t.kickoff_time,
                    code=t.code,
                    position=t.position.value,
                    team_id=t.team_id,
                    team_code=t.team_code,
                    opponent_team_id=t.opponent_team_id,
                    was_home=t.was_home,
                    expected_points=expected,
                    expected_bonus=result.expected_bonus,
                    availability_status=status,
                    availability_multiplier=mult,
                    availability_adjusted_points=mult * expected,
                    stage_a_league_average_team=t.stage_a_league_average,
                    cold_start_player=t.cold_start,
                    transferred_no_rescale=t.transferred,
                    distribution=result.distribution,
                )
            )

    # 6. Per-player horizon totals (sum over the player's fixtures; double gameweeks add).
    totals_acc: dict[int, dict[str, Any]] = {}
    for rec in records:
        acc = totals_acc.setdefault(
            rec.code,
            {
                "position": rec.position,
                "team_id": rec.team_id,
                "team_code": rec.team_code,
                "fixtures": 0,
                "expected_points": 0.0,
                "availability_adjusted_points": 0.0,
                "availability_status": rec.availability_status,
                "cold_start_player": rec.cold_start_player,
                "transferred_no_rescale": rec.transferred_no_rescale,
            },
        )
        acc["fixtures"] += 1
        acc["expected_points"] += rec.expected_points
        acc["availability_adjusted_points"] += rec.availability_adjusted_points
    player_totals = tuple(
        ProspectivePlayerTotal(
            code=code,
            position=acc["position"],
            team_id=acc["team_id"],
            team_code=acc["team_code"],
            fixtures=acc["fixtures"],
            expected_points=acc["expected_points"],
            availability_adjusted_points=acc["availability_adjusted_points"],
            availability_status=acc["availability_status"],
            cold_start_player=acc["cold_start_player"],
            transferred_no_rescale=acc["transferred_no_rescale"],
        )
        for code, acc in sorted(
            totals_acc.items(), key=lambda kv: kv[1]["expected_points"], reverse=True
        )
    )

    repo_path = repo or repo_root()
    return ProspectivePointsResult(
        as_of=as_of,
        season=season,
        gw_from=gw_from,
        gw_to=gw_to,
        draws=draws,
        max_points=max_points,
        roster_size=registry.height,
        fixture_count=fixture_count,
        attacking_mode=attacking,
        share_signal_kind=signal_kind if attacking == "v3" else "not_applicable",
        appearance_mode=appearance,
        freshness_cold_start=freshness.cold_start,
        records=tuple(records),
        player_totals=player_totals,
        component_names={
            "minutes": resolved_suite.minutes_name,
            "goals": (
                "minutes_gated_coupled_team_share_attacking_goals_v3 (team-coupled)"
                if attacking == "v3"
                else resolved_suite.goals_name
            ),
            "assists": resolved_suite.assists_name,
            "team_clean_sheet": "trailing_goals_attack_defence",
            "saves": resolved_suite.saves_name,
            "defensive_contribution": resolved_suite.dc_name,
            "bonus": "hybrid_bps_bonus_match_simulator (exact_bps + fold-local residual)",
        },
        commit_sha=_git_head(repo_path),
        config_sha256=_file_sha256(config_dir() / "scoring_2026_27.yaml"),
        archive_sha256=_file_sha256(Path(db_path)) if db_path is not None else None,
    )


def result_to_record(result: ProspectivePointsResult) -> dict[str, object]:
    """A strict-JSON-serialisable view of the prospective result (provenance + totals + records)."""
    return {
        "schema": "prospective_points_v1/v1",
        "status": "development_only_not_a_production_forecast",
        "label": _DISCLAIMER,
        "provenance": {
            "as_of": result.as_of.isoformat(),
            "season": result.season,
            "gw_from": result.gw_from,
            "gw_to": result.gw_to,
            "monte_carlo_draws": result.draws,
            "points_support_max": result.max_points,
            "base_seed": BASE_SEED,
            "roster_size": result.roster_size,
            "fixture_count": result.fixture_count,
            "row_count": len(result.records),
            "attacking_mode": result.attacking_mode,
            "share_signal_kind": result.share_signal_kind,
            "appearance_mode": result.appearance_mode,
            "freshness_cold_start": result.freshness_cold_start,
            "commit_sha": result.commit_sha,
            "config_sha256": result.config_sha256,
            "archive_sha256": result.archive_sha256,
            "components": result.component_names,
        },
        "player_totals": [
            {
                "code": t.code,
                "position": t.position,
                "team_id": t.team_id,
                "team_code": t.team_code,
                "fixtures": t.fixtures,
                "expected_points": t.expected_points,
                "availability_adjusted_points": t.availability_adjusted_points,
                "availability_status": t.availability_status,
                "cold_start_player": t.cold_start_player,
                "transferred_no_rescale": t.transferred_no_rescale,
            }
            for t in result.player_totals
        ],
        "records": [
            {
                "season": r.season,
                "gw": r.gw,
                "fixture": r.fixture,
                "kickoff_time": r.kickoff_time.isoformat(),
                "code": r.code,
                "position": r.position,
                "team_id": r.team_id,
                "team_code": r.team_code,
                "opponent_team_id": r.opponent_team_id,
                "was_home": r.was_home,
                "expected_points": r.expected_points,
                "expected_bonus": r.expected_bonus,
                "availability_status": r.availability_status,
                "availability_multiplier": r.availability_multiplier,
                "availability_adjusted_points": r.availability_adjusted_points,
                "stage_a_league_average_team": r.stage_a_league_average_team,
                "cold_start_player": r.cold_start_player,
                "transferred_no_rescale": r.transferred_no_rescale,
                "distribution": list(r.distribution),
            }
            for r in result.records
        ],
    }


def format_top_table(result: ProspectivePointsResult, *, top: int = 20) -> str:
    """A compact human-readable leaderboard of horizon expected points."""
    header = (
        f"=== Prospective full-points xP: {result.season} "
        f"GW{result.gw_from}-{result.gw_to} (DEVELOPMENT ONLY) ==="
    )
    lines = [
        header,
        f"as_of={result.as_of.isoformat()}  roster={result.roster_size}  "
        f"fixtures={result.fixture_count}  rows={len(result.records)}  draws={result.draws}",
        f"attacking={result.attacking_mode}"
        + (f" (share signal: {result.share_signal_kind})" if result.attacking_mode == "v3" else "")
        + f"  appearance={result.appearance_mode}",
        "",
        f"{'code':>7} {'pos':>3} {'tm':>3} {'gws':>3} {'xP':>7} {'xP_adj':>7} {'st':>3}  flags",
    ]
    for t in result.player_totals[:top]:
        flags = []
        if t.cold_start_player:
            flags.append("cold")
        if t.transferred_no_rescale:
            flags.append("transfer")
        lines.append(
            f"{t.code:>7} {t.position:>3} {t.team_code!s:>3} {t.fixtures:>3} "
            f"{t.expected_points:>7.2f} {t.availability_adjusted_points:>7.2f} "
            f"{t.availability_status:>3}  {','.join(flags)}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prospective full-points xP over a multi-gameweek horizon (DEVELOPMENT-ONLY)."
    )
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument(
        "--as-of", default=None, help="ISO 8601 as_of (default: GW1 2026/27 deadline)"
    )
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument("--gw-from", type=int, default=DEFAULT_GW_FROM)
    parser.add_argument("--gw-to", type=int, default=DEFAULT_GW_TO)
    parser.add_argument(
        "--attacking",
        choices=("v1", "v3"),
        default="v3",
        help="attacking-goals component: v3 team-coupled (default) or v1 independent per-player",
    )
    parser.add_argument(
        "--appearance",
        choices=("seasonal", "model"),
        default="seasonal",
        help="appearance probability: seasonal season-boundary fix (default) or raw model minutes",
    )
    parser.add_argument(
        "--share-signal",
        choices=("auto", "xg", "threat"),
        default="auto",
        help="team-coupled goal share signal: auto (xG in the xG era, default) / xg / threat",
    )
    parser.add_argument("--draws", type=int, default=DEFAULT_DRAWS)
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--output", type=Path, default=None, help="write JSON record to this path")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    as_of = datetime.fromisoformat(args.as_of) if args.as_of else GW1_2026_27_DEADLINE
    db_path = args.db or default_db_path()
    repo = repo_root()

    con = connect(db_path, read_only=True)
    try:
        result = predict_prospective_points(
            con,
            as_of=as_of,
            season=args.season,
            gw_from=args.gw_from,
            gw_to=args.gw_to,
            attacking=args.attacking,
            appearance=args.appearance,
            share_signal=args.share_signal,
            draws=args.draws,
            db_path=db_path,
            repo=repo,
        )
    except FreshnessError as exc:
        logger.error(str(exc))
        return 1
    finally:
        con.close()

    record = result_to_record(result)
    payload = json.dumps(record, indent=2, sort_keys=True, allow_nan=False)
    if args.output is not None:
        args.output.write_text(payload + "\n", encoding="utf-8")
        logger.info("wrote %d record(s) to %s", len(result.records), args.output)
    print(_DISCLAIMER)
    print()
    print(format_top_table(result, top=args.top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
