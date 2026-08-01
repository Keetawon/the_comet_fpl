"""Stage C Candidate V3: minutes-gated coupled team-share attacking goals.

Pre-registered in ``config/phase3_evaluation.yaml`` amendment 1.3 as
``minutes_gated_coupled_team_share_attacking_goals_v3``. Candidate V3 is Candidate V2 with each
player's coupled team-share rate gated by an explicit Stage B minutes input, fully separating
appearance probability from per-appearance attacking rate (R6):

    weighted_i = share_i * p_play_i
    rate_i     = lambda_team * weighted_i / sum_j(weighted_j)   =>   sum_i rate_i = lambda_team.

``share_i`` is V2's trailing attacking share (unchanged). ``p_play_i = P(minutes >= 1)`` comes from
the frozen Stage B BASELINE ``trailing_5_player_minutes``
(:class:`fpl.validate.minutes_baselines.Trailing5PlayerMinutes`) -- a deterministic baseline, not an
unpromoted candidate -- refit fold-local on player-fixture history with ``kickoff_time < as_of``.
The renormalisation keeps the V2 conservation property (rates sum to ``lambda_team``): mass from
low-``p_play`` players is redistributed to players more likely to appear, rather than dropping the
team total below ``lambda_team``.

It reduces EXACTLY to V2 when minutes gating is disabled (and to the V2 allocation when every
``p_play == 1``). The Stage B minutes input is a DEVELOPMENT PROXY (a baseline on unversioned
archive history, introducing no unpromoted-candidate dependency), stated as an additional reason the
verdict is development-only. Like V2 this is a fixed closed-form estimator (no grid, no inner
walk-forward); ``alpha`` mirrors the v1.0 trailing baseline and is used only by the
stage-A-uninformative fallback.

V3 reuses V2's share machinery (:func:`~fpl.models.attacking_v2.coupled_shares`,
:func:`~fpl.models.attacking_v2.allocate_coupled_rates`, and the inherited Stage A / appeared-rows
helpers); minutes and per-appearance attacking rate are kept as SEPARATE components (R6), never a
single joint fit.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import duckdb

from fpl.models.attacking_baselines import TargetRowProjection
from fpl.models.attacking_v2 import (
    _SIGNAL_XG,
    CoupledTeamShareAttackingGoalsV2,
    _RosterEntry,
    allocate_coupled_rates,
    coupled_shares,
    season_signal_kind,
)
from fpl.types import Position
from fpl.validate.minutes_baselines import (
    HistoryRow,
    MinuteBins,
    TargetRow,
    TeamCodeMap,
    build_minutes_baselines,
)

NAME = "minutes_gated_coupled_team_share_attacking_goals_v3"


def allocate_minutes_gated_rates(
    roster: Sequence[_RosterEntry],
    p_play: dict[int, float],
    lambda_team: float,
    *,
    minutes_gating: bool,
) -> dict[int, tuple[float, str]]:
    """Pure minutes-gated Poisson-thinning allocation over a fixture's roster.

    With ``minutes_gating=False`` this is bit-for-bit :func:`allocate_coupled_rates` (V2). With it
    on, each share is weighted by the player's appearance probability and renormalised so the rates
    still sum to ``lambda_team``. A roster whose weighted shares sum to zero (everyone ``p_play``
    zero) falls back to the unweighted V2 allocation. Returns ``{code: (rate, path)}``.
    """
    if not minutes_gating:
        return allocate_coupled_rates(roster, lambda_team)

    shares = coupled_shares(roster)
    weighted = {code: share * p_play.get(code, 1.0) for code, (share, _p) in shares.items()}
    total_weighted = sum(weighted.values())
    if total_weighted <= 0.0:
        return allocate_coupled_rates(roster, lambda_team)
    return {
        code: (lambda_team * weighted[code] / total_weighted, path)
        for code, (_share, path) in shares.items()
    }


class MinutesGatedCoupledTeamShareAttackingGoalsV3(CoupledTeamShareAttackingGoalsV2):
    """Fold-local minutes-gated coupled team-share attacking-goals estimator.

    Subclasses V2: ``fit`` and the Stage A / trailing-fallback machinery are inherited; ``prepare``
    adds the Stage B ``trailing_5_player_minutes`` appearance-probability gate on top of V2's
    shares.
    """

    name: str = NAME

    def __init__(
        self,
        *,
        alpha: float,
        share_window: int,
        xg_covered_seasons: frozenset[str],
        bins: MinuteBins,
        minutes_gating: bool = True,
    ) -> None:
        super().__init__(
            alpha=alpha,
            share_window=share_window,
            xg_covered_seasons=xg_covered_seasons,
        )
        self.bins = bins
        self.minutes_gating = minutes_gating

    def prepare(
        self,
        targets: Sequence[TargetRowProjection],
        *,
        con: duckdb.DuckDBPyConnection,
        as_of: str,
    ) -> None:
        if not targets:
            self._rates = {}
            self._paths = {}
            return
        season = targets[0].season
        kind = season_signal_kind(season, self.xg_covered_seasons)

        stage_a, stage_a_informative = self._fit_stage_a(con, as_of)
        team_code_map = self._team_code_map(con, season)
        appeared_by_code, pos_signal_mean, stage_b_rows = self._fold_player_history(
            con, as_of, kind
        )
        p_play = self._appearance_probabilities(con, stage_b_rows, targets, as_of)

        # Group targets by (fixture, team_code): each group is one club's roster in one fixture.
        groups: dict[tuple[int, int], list[TargetRowProjection]] = {}
        for target in targets:
            team_code = team_code_map.get(target.team_id, -1)
            groups.setdefault((target.fixture, team_code), []).append(target)

        rates: dict[tuple[int, int], float] = {}
        paths: dict[tuple[int, int], str] = {}
        for (_fixture, team_code), roster_targets in groups.items():
            if not stage_a_informative or team_code < 0:
                for target in roster_targets:
                    rates[(target.fixture, target.code)] = self._trailing_baseline_rate(
                        target.code, target.position
                    )
                    paths[(target.fixture, target.code)] = "stage_a_uninformative_trailing"
                continue

            lambda_team = stage_a.rate_for(
                {
                    "team_code": team_code,
                    "opponent_team_code": team_code_map.get(
                        roster_targets[0].opponent_team_id, team_code
                    ),
                    "was_home": roster_targets[0].was_home,
                }
            )
            roster = self._build_roster(roster_targets, appeared_by_code, pos_signal_mean, kind)
            coupled = allocate_minutes_gated_rates(
                roster, p_play, lambda_team, minutes_gating=self.minutes_gating
            )
            for target in roster_targets:
                rate, path = coupled[target.code]
                rates[(target.fixture, target.code)] = rate
                paths[(target.fixture, target.code)] = path

        self._rates = rates
        self._paths = paths

    # -- fold player-fixture history: appeared shares (V2) + Stage B minutes ------------

    def _fold_player_history(
        self,
        con: duckdb.DuckDBPyConnection,
        as_of: str,
        kind: str,
    ) -> tuple[
        dict[int, list[tuple[float, float | None, float | None]]],
        float,
        list[HistoryRow],
    ]:
        """One fetch of minutes-not-null prior rows, split into V2 appeared signals + Stage B rows.

        A single query serves both: the appeared subset (``minutes > 0``) feeds V2's attacking
        signals, and the full set (including zero-minute rows) feeds the Stage B minutes baseline
        (which uses ``up to 5 most recent prior rows including zero``). Both are gated by
        ``kickoff_time < as_of``.
        """
        frame = con.execute(
            """
            SELECT season, gw, fixture, kickoff_time, code, position,
                   team_id, opponent_team_id, was_home, minutes,
                   expected_goals, threat
            FROM mart_fact_player_fixture
            WHERE minutes IS NOT NULL AND kickoff_time < ?
            ORDER BY kickoff_time, season, fixture, code
            """,
            [as_of],
        ).pl()
        if not frame.is_empty():
            frame = frame.sort(["kickoff_time", "season", "fixture", "code"], maintain_order=True)

        appeared_by_code: dict[int, list[tuple[float, float | None, float | None]]] = {}
        sig_sum = 0.0
        sig_n = 0
        stage_b_rows: list[HistoryRow] = []
        for r in frame.iter_rows(named=True):
            minutes = int(r["minutes"])
            xg = _optional_float(r["expected_goals"])
            threat = _optional_float(r["threat"])
            # Appeared rows only (minutes > 0) feed the attacking signal (R6 appearance-vs-rate).
            if minutes > 0:
                epoch = float(r["kickoff_time"].timestamp())
                appeared_by_code.setdefault(int(r["code"]), []).append((epoch, xg, threat))
                value = xg if kind == _SIGNAL_XG else threat
                if value is not None:
                    sig_sum += value
                    sig_n += 1
            # Every minutes-not-null row feeds the Stage B minutes baseline (including zero-minute).
            stage_b_rows.append(_to_history_row(r, minutes))
        positional_mean = (sig_sum / sig_n) if sig_n > 0 else 0.0
        return appeared_by_code, positional_mean, stage_b_rows

    def _appearance_probabilities(
        self,
        con: duckdb.DuckDBPyConnection,
        stage_b_rows: Sequence[HistoryRow],
        targets: Sequence[TargetRowProjection],
        as_of: str,
    ) -> dict[int, float]:
        """Fit the frozen ``trailing_5_player_minutes`` baseline fold-local.

        Returns ``{code: p_play}`` where ``p_play = P(minutes >= 1) = 1 - dist[0]`` from the
        baseline's four-bin distribution. The baseline is fit on ``kickoff_time < as_of`` history
        only; the target fixture's minutes never enter (R6 / leakage-safe). Probabilities are per
        ``code`` (the baseline keys on ``code``).
        """
        team_codes = _all_team_codes(con)
        as_of_dt = _to_utc(as_of)
        fitted = build_minutes_baselines(
            list(stage_b_rows), as_of=as_of_dt, team_codes=team_codes, bins=self.bins
        )
        trailing5 = next(b for b in fitted if b.name == "trailing_5_player_minutes")
        p_play: dict[int, float] = {}
        for target in targets:
            if target.code in p_play:
                continue
            dist = trailing5.predict(_to_stage_b_target(target))
            p_play[target.code] = max(0.0, min(1.0, 1.0 - dist[0]))
        return p_play

    def parameters(self) -> dict[str, float | int | bool | str]:
        return {
            "alpha": self.alpha,
            "share_window": self.share_window,
            "stage_a_model": "trailing_goals_attack_defence",
            "minutes_baseline": "trailing_5_player_minutes",
            "minutes_gating": self.minutes_gating,
            "signal": "expected_goals_else_threat_by_fold_xg_coverage",
        }


# --------------------------------------------------------------------------------------
# Team codes, row conversion helpers
# --------------------------------------------------------------------------------------


def _all_team_codes(con: duckdb.DuckDBPyConnection) -> TeamCodeMap:
    """A complete ``TeamCodeMap`` from ``mart_dim_team`` (every season).

    Stage B history spans multiple seasons and ``team_code`` is the only cross-season club key, so
    the map must cover every season a history row references; a bare ``team_id`` is never pooled
    across seasons. ``mart_dim_team`` is small (~27 clubs x 5 seasons).
    """
    frame = con.execute("SELECT season, team_id, team_code FROM mart_dim_team").pl()
    return TeamCodeMap.from_pairs(
        (str(r["season"]), int(r["team_id"]), int(r["team_code"]))
        for r in frame.iter_rows(named=True)
    )


def _to_history_row(r: dict[str, Any], minutes: int) -> HistoryRow:
    return HistoryRow(
        season=str(r["season"]),
        gw=int(r["gw"]),
        fixture=int(r["fixture"]),
        kickoff_time=_to_utc(r["kickoff_time"]),
        code=int(r["code"]),
        position=_position(r["position"]),
        team_id=int(r["team_id"]),
        opponent_team_id=int(r["opponent_team_id"]),
        was_home=bool(r["was_home"]),
        minutes=minutes,
    )


def _to_stage_b_target(target: TargetRowProjection) -> TargetRow:
    return TargetRow(
        season=target.season,
        gw=target.gw,
        fixture=target.fixture,
        kickoff_time=_to_utc(target.kickoff_time),
        code=target.code,
        position=target.position,
        team_id=target.team_id,
        opponent_team_id=target.opponent_team_id,
        was_home=target.was_home,
    )


def _to_utc(value: object) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    # Stage C target kickoff_time is a "...Z" string.
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)


def _position(value: object) -> Position:
    if isinstance(value, Position):
        return value
    return Position.from_archive_label(str(value))


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)  # type: ignore[arg-type]
