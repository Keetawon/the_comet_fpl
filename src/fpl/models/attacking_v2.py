"""Stage C Candidate V2: coupled team-share attacking goals (Poisson thinning).

Pre-registered in ``config/phase3_evaluation.yaml`` amendment 1.2 as
``coupled_team_share_attacking_goals_v2``. Instead of predicting each player's goals
independently (V1), V2 allocates the frozen Stage A team-goal expectation among a club's
players by a trailing attacking share:

    rate_i = lambda_team * share_i ,   sum_i share_i = 1   =>   sum_i rate_i = lambda_team.

Conservation is structural (Poisson thinning): the per-player marginals are exact independent
Poissons that add up to the Stage A team total on the coupled path.

``lambda_team`` comes from the FROZEN Stage A ``trailing_goals_attack_defence`` baseline
(:class:`fpl.validate.baselines.TrailingGoalsAttackDefence`), refit fold-local on team-match
history with ``kickoff_time < as_of`` -- reused, never reimplemented. Club identity is the stable
``team_code`` (resolved from the season-qualified ``team_id`` via ``mart_dim_team``); a bare
``team_id`` is never joined across seasons (it is reassigned every summer and recurs).

R6 appearance-vs-rate correction: each player's trailing attacking signal is computed over
APPEARED prior rows only (``minutes > 0``), so a did-not-play prior row cannot dilute a
per-appearance rate. The signal is ``expected_goals`` (xG) in xG-covered seasons and ``threat``
otherwise -- chosen PER FOLD by the contract's ``xg_covered_seasons`` so every roster player's
share is on one scale (xG and threat are different scales; mixing them in one roster would distort
the shares). A cold-start player (no appeared prior row) takes the positional mean of the SAME
signal type, keeping the scale uniform; a roster whose signals sum to zero takes equal shares.

This is a FIXED closed-form estimator: no parameter grid, no inner walk-forward. ``alpha`` mirrors
the v1.0 trailing baseline (5.0) and is used only by the stage-A-uninformative fallback.

Because V2 is fixture-coupled (share normalisation needs the full fold roster and a Stage A
``lambda_team`` per fixture), the harness calls the optional ``prepare(targets, con, as_of)``
hook after fitting; ``predict``/``path_for`` then look up the precomputed per-target rate.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

import duckdb

from fpl.models.attacking_baselines import (
    GoalCountDistribution,
    PlayerHistoryRow,
    PositionalGoalRateBaseline,
    TargetRowProjection,
    poisson_pmf,
)
from fpl.types import Position, Season
from fpl.validate.baselines import TrailingGoalsAttackDefence, TrainingWindow

NAME = "coupled_team_share_attacking_goals_v2"

# Frozen contract constants (config/phase3_evaluation.yaml stage_c_candidate_v2). ``alpha`` mirrors
# the v1.0 trailing baseline; ``share_window`` is the trailing appeared-rows window.
ALPHA: float = 5.0
SHARE_WINDOW: int = 5
POISSON_MAX_GOALS: int = 10

# Per-target estimator path labels (development diagnostics, never a gate).
PATH_COUPLED = "stage_a_coupled_appeared"
PATH_COLD_START_SHARE = "stage_a_coupled_cold_start"
PATH_EQUAL_SHARE = "stage_a_coupled_equal_share"
PATH_STAGE_A_FALLBACK = "stage_a_uninformative_trailing"

_SIGNAL_XG = "expected_goals"
_SIGNAL_THREAT = "threat"

# Stage A team-match training projection -- mirrors the Phase 1 harness
# (src/fpl/validate/harness.py _TEAM_MATCH_SELECT/_FROM): the frozen Stage A training source. Kept
# inline (not imported) so V2 owns its integration and a Phase 1 harness refactor cannot silently
# change what Stage A was fit on here; drift is caught by the candidate-source fingerprint.
_TEAM_MATCH_SELECT = """
    m.season, m.gw, m.fixture, m.kickoff_time,
    club.team_code AS team_code,
    opponent.team_code AS opponent_team_code,
    m.was_home, m.goals_for, m.goals_against
"""
_TEAM_MATCH_FROM = """
    FROM mart_fact_team_match AS m
    JOIN mart_dim_team AS club
      ON club.season = m.season AND club.team_id = m.team_id
    JOIN mart_dim_team AS opponent
      ON opponent.season = m.season AND opponent.team_id = m.opponent_team_id
"""


@dataclass(frozen=True, slots=True)
class _RosterEntry:
    """One roster player's resolved share signal and whether it is a cold-start fill."""

    code: int
    signal: float
    cold_start: bool


def season_signal_kind(season: str, xg_covered_seasons: frozenset[str]) -> str:
    """The attacking signal type for a fold's season: xG where the contract covers it, else threat.

    Chosen per fold (not per row) so every roster player's share sits on one scale:
    ``expected_goals`` and ``threat`` are different scales, and mixing them in one roster would
    let the larger-scaled signal dominate the shares for reasons of units rather than attacking
    share. This also matches the contract's xG-covered-seasons judging rule.
    """
    return _SIGNAL_XG if season in xg_covered_seasons else _SIGNAL_THREAT


def mean_trailing_signal(
    rows: Sequence[tuple[float, float | None, float | None]],
    *,
    kind: str,
    window: int,
) -> float | None:
    """Mean per-appearance signal over the trailing ``window`` appeared rows, or ``None``.

    ``rows`` are ``(kickoff_epoch, expected_goals, threat)`` already filtered to appeared rows
    (``minutes > 0``) and supplied in chronological order (the history query is
    ``ORDER BY kickoff_time, season, fixture, code``, so arrival order IS chronological; re-sorting
    by epoch alone would break same-kickoff ties non-deterministically). The most recent ``window``
    rows are kept. For the chosen ``kind`` only non-NULL values count (NULL means unmeasured and is
    never zero-filled); ``None`` is returned when no measured value remains -- which marks the
    player as cold-start for the share allocation.
    """
    if not rows:
        return None
    recent = list(rows)[-window:]
    values: list[float] = []
    for _epoch, xg, threat in recent:
        value = xg if kind == _SIGNAL_XG else threat
        if value is not None:
            values.append(value)
    if not values:
        return None
    return sum(values) / len(values)


def allocate_coupled_rates(
    roster: Sequence[_RosterEntry],
    lambda_team: float,
) -> dict[int, tuple[float, str]]:
    """Pure Poisson-thinning allocation of ``lambda_team`` over a fixture's roster.

    Shares are ``signal / sum(signal)`` and rates are ``lambda_team * share``; on the coupled
    path the rates sum to ``lambda_team`` by construction (the conservation / thinning identity).
    A roster whose signals sum to zero takes equal shares (still summing to ``lambda_team``).
    Returns ``{code: (rate, path)}``.
    """
    if not roster:
        return {}
    total = sum(entry.signal for entry in roster)
    rates: dict[int, tuple[float, str]] = {}
    if total <= 0.0:
        share = 1.0 / len(roster)
        for entry in roster:
            rates[entry.code] = (lambda_team * share, PATH_EQUAL_SHARE)
        return rates
    for entry in roster:
        rates[entry.code] = (
            lambda_team * (entry.signal / total),
            PATH_COLD_START_SHARE if entry.cold_start else PATH_COUPLED,
        )
    return rates


class CoupledTeamShareAttackingGoalsV2:
    """Fold-local coupled team-share attacking-goals estimator.

    ``fit`` builds the v1.0-identical positional and trailing-player goal components (used by the
    stage-A-uninformative fallback). ``prepare`` fits Stage A fold-local and computes the
    fixture-coupled shares; ``predict``/``path_for`` look up the precomputed per-target rate.
    """

    name: str = NAME

    def __init__(
        self,
        *,
        alpha: float = ALPHA,
        share_window: int = SHARE_WINDOW,
        xg_covered_seasons: frozenset[Season] = frozenset(),
        max_goals: int = POISSON_MAX_GOALS,
    ) -> None:
        self.alpha = alpha
        self.share_window = share_window
        self.xg_covered_seasons = frozenset(xg_covered_seasons)
        self.max_goals = max_goals
        self._positional = PositionalGoalRateBaseline()
        # Per-code prior player-fixture rows (goals only) for the v1.0-identical fallback rate.
        self._player_goals_history: dict[int, list[PlayerHistoryRow]] = {}
        # Populated by prepare(): {(fixture, code): rate} and the matching path labels.
        self._rates: dict[tuple[int, int], float] = {}
        self._paths: dict[tuple[int, int], str] = {}

    # -- fit (v1.0-identical fallback components) -------------------------------------

    def fit(self, history: Sequence[PlayerHistoryRow]) -> None:
        self._positional.fit(history)
        self._player_goals_history = {}
        for row in history:
            self._player_goals_history.setdefault(row.code, []).append(row)

    def _trailing_baseline_rate(self, code: int, position: Position) -> float:
        """The exact v1.0 ``trailing_player_goal_rate_poisson`` rate.

        This is the stage-A-uninformative fallback rate.

        Computed from the same fold history the v1.0 baseline uses (all rows including zero-minute),
        so it is bit-for-bit identical to ``TrailingPlayerGoalRateBaseline`` with the same alpha.
        """
        pos_g = self._positional.get_rate(position)
        rows = self._player_goals_history.get(code, [])
        recent = rows[-5:]
        n = len(recent)
        if n == 0:
            return pos_g
        sum_goals = sum(row.goals for row in recent)
        return (sum_goals + self.alpha * pos_g) / (n + self.alpha)

    # -- prepare (Stage A coupling + appeared-rows shares) ----------------------------

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
        appeared_by_code, pos_signal_mean = self._appeared_history(con, as_of, kind)

        # Group targets by (fixture, team_code): each group is one club's roster in one fixture.
        groups: dict[tuple[int, int], list[TargetRowProjection]] = {}
        for target in targets:
            team_code = team_code_map.get(target.team_id)
            if team_code is None:
                team_code = -1  # unresolved -> forced fallback path below
            groups.setdefault((target.fixture, team_code), []).append(target)

        rates: dict[tuple[int, int], float] = {}
        paths: dict[tuple[int, int], str] = {}
        for (_fixture, team_code), roster_targets in groups.items():
            if not stage_a_informative or team_code < 0:
                # Stage A uninformative (empty training window) or unresolved club: exact v1.0
                # trailing rate per player, uncoupled.
                for target in roster_targets:
                    rate = self._trailing_baseline_rate(target.code, target.position)
                    rates[(target.fixture, target.code)] = rate
                    paths[(target.fixture, target.code)] = PATH_STAGE_A_FALLBACK
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
            coupled = allocate_coupled_rates(roster, lambda_team)
            for target in roster_targets:
                rate, path = coupled[target.code]
                rates[(target.fixture, target.code)] = rate
                paths[(target.fixture, target.code)] = path

        self._rates = rates
        self._paths = paths

    def _build_roster(
        self,
        roster_targets: Sequence[TargetRowProjection],
        appeared_by_code: dict[int, list[tuple[float, float | None, float | None]]],
        pos_signal_mean: float,
        kind: str,
    ) -> list[_RosterEntry]:
        # Sort by code for a deterministic float-sum order in the share normalisation.
        roster: list[_RosterEntry] = []
        for target in sorted(roster_targets, key=lambda t: t.code):
            rows = appeared_by_code.get(target.code, [])
            signal = mean_trailing_signal(rows, kind=kind, window=self.share_window)
            if signal is None or signal <= 0.0:
                # Cold-start (no appeared prior row) or zero attacking output: positional-mean
                # signal of the same scale, so the new player is not zeroed and shares stay
                # single-scale.
                roster.append(_RosterEntry(target.code, pos_signal_mean, cold_start=signal is None))
            else:
                roster.append(_RosterEntry(target.code, signal, cold_start=False))
        return roster

    def _fit_stage_a(
        self, con: duckdb.DuckDBPyConnection, as_of: str
    ) -> tuple[TrailingGoalsAttackDefence, bool]:
        frame = con.execute(
            f"SELECT {_TEAM_MATCH_SELECT} {_TEAM_MATCH_FROM} WHERE m.kickoff_time < ?",
            [as_of],
        ).pl()
        stage_a = TrailingGoalsAttackDefence()
        stage_a.fit(TrainingWindow(frame))
        return stage_a, not frame.is_empty()

    def _team_code_map(self, con: duckdb.DuckDBPyConnection, season: str) -> dict[int, int]:
        frame = con.execute(
            "SELECT team_id, team_code FROM mart_dim_team WHERE season = ?",
            [season],
        ).pl()
        return {int(r["team_id"]): int(r["team_code"]) for r in frame.iter_rows(named=True)}

    def _appeared_history(
        self, con: duckdb.DuckDBPyConnection, as_of: str, kind: str
    ) -> tuple[
        dict[int, list[tuple[float, float | None, float | None]]],
        float,
    ]:
        """Per-code appeared prior rows (minutes > 0) and the fold positional mean signal.

        The positional mean is over appeared rows only and uses the fold's signal ``kind`` so a
        cold-start player's share fill is on the same scale as appeared players' shares.
        """
        frame = con.execute(
            """
            SELECT code, position,
                   kickoff_time, season, fixture,
                   expected_goals, threat
            FROM mart_fact_player_fixture
            WHERE minutes IS NOT NULL AND minutes > 0 AND kickoff_time < ?
            ORDER BY kickoff_time, season, fixture, code
            """,
            [as_of],
        ).pl()
        if not frame.is_empty():
            frame = frame.sort(["kickoff_time", "season", "fixture", "code"], maintain_order=True)

        by_code: dict[int, list[tuple[float, float | None, float | None]]] = {}
        sig_sum = 0.0
        sig_n = 0
        for r in frame.iter_rows(named=True):
            epoch = _epoch_seconds(r["kickoff_time"])
            xg = _optional_float(r["expected_goals"])
            threat = _optional_float(r["threat"])
            by_code.setdefault(int(r["code"]), []).append((epoch, xg, threat))
            value = xg if kind == _SIGNAL_XG else threat
            if value is not None:
                sig_sum += value
                sig_n += 1
        positional_mean = (sig_sum / sig_n) if sig_n > 0 else 0.0
        return by_code, positional_mean

    # -- predict / diagnostics --------------------------------------------------------

    def predict(self, target: TargetRowProjection) -> GoalCountDistribution:
        return poisson_pmf(self._rates[(target.fixture, target.code)], self.max_goals)

    def path_for(self, target: TargetRowProjection) -> str:
        return self._paths[(target.fixture, target.code)]

    def parameters(self) -> Mapping[str, float | int | bool | str]:
        return {
            "alpha": self.alpha,
            "share_window": self.share_window,
            "stage_a_model": "trailing_goals_attack_defence",
            "signal": "expected_goals_else_threat_by_fold_xg_coverage",
        }


def _epoch_seconds(kickoff: object) -> float:
    """Kickoff as POSIX seconds for chronological ordering (point-in-time order only).

    DuckDB returns ``datetime.datetime`` for a TIMESTAMP/TIMESTAMPTZ cell on both the archive and
    the in-memory test database.
    """
    assert isinstance(kickoff, datetime), f"expected datetime kickoff, got {type(kickoff)!r}"
    return float(kickoff.timestamp())


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)  # type: ignore[arg-type]
