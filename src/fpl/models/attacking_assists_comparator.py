"""Stage C assists DEVELOPMENT DIAGNOSTIC comparator: raw per-appearance xA share x P(play).

Pre-registered in ``config/phase3_stage_c_assists_evaluation.yaml`` as the
``stage_c_assists_diagnostic_comparator`` block (``raw_per_appearance_xa_team_share_times_p_play``).
This is NOT a candidate and NOT a required baseline: it is a development diagnostic that mirrors the
controlled goals V3 architecture applied to assists, so the exposure candidate V2
(``exposure_weighted_xa_team_share_assists_v2``) can be compared against the raw per-appearance xA
allocation it is hypothesised to beat. Without it the experiment cannot answer whether per-minute
exposure improves over raw per-appearance xA allocation.

It mirrors goals V3 (``minutes_gated_coupled_team_share_attacking_goals_v3``): the team scale is
``lambda_team * fold_local_assist_rate`` (``sum(assists)/sum(goals_scored)``, fallback 0.90); each
player's signal is mean raw xA per APPEARANCE over the last five appeared rows; the minutes input
is the frozen ``trailing_5_player_minutes`` baseline (``p_play = 1 - dist[0]``); the weight is
``mean_xa_per_appearance * p_play``; and the team weights are renormalised so the rates still sum to
the team scale (underlying Poisson-rate conservation in expectation). It is xA-only: there is NO
creativity fallback and it never reads ``creativity``; NULL xA is unmeasured and never zero-filled.

Cold-start fill: a player with no measured trailing xA row takes the fold-local POSITION-SPECIFIC
xA-per-appearance mean (the same policy as Candidate V2, so the comparator differs from V2 in only
the allocation signal -- mean-per-appearance x p_play vs shrunk-per-minute x E[minutes]); where a
position has no measured prior it falls back to the pooled xA-per-appearance mean. Conservation is
exact by construction (``allocate_team_scale`` renormalises so ``sum_i assist_lambda_i ==
team_assist_lambda``); it is not per-draw realised-count conservation, and it is never fed to the
full-points composer.

Like the candidates this is a FIXED closed-form estimator (no grid, no inner walk-forward);
``alpha`` mirrors the v1.0 trailing assists baseline (5.0) and is used only by the
stage-A-uninformative fallback.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import duckdb

from fpl.models.attacking_assists_baselines import (
    AssistHistoryRow,
    PositionalAssistRateBaseline,
)
from fpl.models.attacking_baselines import GoalCountDistribution, TargetRowProjection, poisson_pmf
from fpl.models.attacking_exposure import allocate_team_scale, trailing_signal_per_appearance
from fpl.models.attacking_v2 import _TEAM_MATCH_FROM, _TEAM_MATCH_SELECT
from fpl.models.attacking_v3 import (
    _all_team_codes,
    _optional_float,
    _position,
    _to_history_row,
    _to_stage_b_target,
    _to_utc,
)
from fpl.types import Position
from fpl.validate.baselines import TrailingGoalsAttackDefence, TrainingWindow
from fpl.validate.dev_exposure_diagnostics import FoldDiagnosticsSink
from fpl.validate.minutes_baselines import (
    HistoryRow,
    MinuteBins,
    build_minutes_baselines,
)

NAME = "raw_per_appearance_xa_team_share_times_p_play"

# Measured-league assist rate fallback when a fold has scored zero goals (degenerate early fold).
_FALLBACK_ASSIST_RATE: float = 0.90

# Per-target estimator path labels (development diagnostics, never a gate).
PATH_RAW_WEIGHTED = "stage_a_raw_per_appearance_weighted"
PATH_RAW_COLD_START = "stage_a_raw_per_appearance_cold_start"
PATH_RAW_EQUAL_SHARE = "stage_a_raw_per_appearance_equal_share"
PATH_STAGE_A_FALLBACK = "stage_a_uninformative_trailing"


class RawPerAppearanceXaTeamSharePplayComparator:
    """Fold-local raw per-appearance xA team-share x P(play) diagnostic comparator.

    Mirrors goals V3: mean trailing xA per appearance gated by the frozen Stage B appearance
    probability and renormalised to the club's assisted-goal expectation. Shared Stage A glue and
    fold-history fetch with the assists candidates; allocation differs (raw per-appearance, not
    exposure-weighted).
    """

    name: str = NAME

    def __init__(
        self,
        *,
        alpha: float,
        share_window: int,
        bins: MinuteBins,
        max_assists: int = 10,
        diagnostics_sink: FoldDiagnosticsSink | None = None,
    ) -> None:
        self.alpha = alpha
        self.share_window = share_window
        self._bins = bins
        self.max_assists = max_assists
        self._diagnostics_sink = diagnostics_sink
        self._positional = PositionalAssistRateBaseline()
        self._player_history: dict[int, list[AssistHistoryRow]] = {}
        self._rates: dict[tuple[int, int], float] = {}
        self._paths: dict[tuple[int, int], str] = {}

    # -- fit (v1.0-identical fallback components) -------------------------------------

    def fit(self, history: Sequence[AssistHistoryRow]) -> None:
        self._positional.fit(history)
        self._player_history = {}
        for row in history:
            self._player_history.setdefault(row.code, []).append(row)

    def _trailing_baseline_rate(self, code: int, position: Position) -> float:
        """The exact v1.0 ``trailing_player_assist_rate_poisson`` rate (stage-A fallback)."""
        pos_a = self._positional.get_rate(position)
        rows = self._player_history.get(code, [])
        recent = rows[-5:]
        n = len(recent)
        if n == 0:
            return pos_a
        sum_assists = sum(row.assists for row in recent)
        return (sum_assists + self.alpha * pos_a) / (n + self.alpha)

    # -- prepare (Stage A coupling + raw per-appearance x p_play shares) ---------------

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

        stage_a, stage_a_informative = self._fit_stage_a(con, as_of)
        team_code_map = self._team_code_map(con, season)
        (
            appeared_by_code,
            positional_xa,
            pooled_xa,
            assist_rate,
            stage_b_rows,
        ) = self._fold_history(con, as_of)
        p_play = self._appearance_probabilities(con, stage_b_rows, targets, as_of)

        groups: dict[tuple[int, int], list[TargetRowProjection]] = {}
        for target in targets:
            team_code = team_code_map.get(target.team_id)
            if team_code is None:
                team_code = -1
            groups.setdefault((target.fixture, team_code), []).append(target)

        rates: dict[tuple[int, int], float] = {}
        paths: dict[tuple[int, int], str] = {}
        for (_fixture, team_code), roster_targets in groups.items():
            if not stage_a_informative or team_code < 0:
                for target in roster_targets:
                    rates[(target.fixture, target.code)] = self._trailing_baseline_rate(
                        target.code, target.position
                    )
                    paths[(target.fixture, target.code)] = PATH_STAGE_A_FALLBACK
                continue

            opponent_code = team_code_map.get(roster_targets[0].opponent_team_id, team_code)
            lambda_team = float(
                stage_a.rate_for(
                    {
                        "team_code": team_code,
                        "opponent_team_code": opponent_code,
                        "was_home": roster_targets[0].was_home,
                    }
                )
            )
            team_assist_lambda = lambda_team * assist_rate
            weights, has_measured = self._roster_weights(
                roster_targets, appeared_by_code, positional_xa, pooled_xa, p_play
            )
            if math.fsum(weights.values()) <= 0.0:
                share = team_assist_lambda / len(weights)
                for target in roster_targets:
                    rates[(target.fixture, target.code)] = share
                    paths[(target.fixture, target.code)] = PATH_RAW_EQUAL_SHARE
            else:
                allocated = allocate_team_scale(weights, team_assist_lambda)
                for target in roster_targets:
                    rates[(target.fixture, target.code)] = allocated[target.code]
                    paths[(target.fixture, target.code)] = (
                        PATH_RAW_WEIGHTED if has_measured[target.code] else PATH_RAW_COLD_START
                    )

        self._rates = rates
        self._paths = paths

    # -- fold history: appeared xA rows, positional + pooled xA/appearance, assist rate -

    def _fold_history(
        self,
        con: duckdb.DuckDBPyConnection,
        as_of: str,
    ) -> tuple[
        dict[int, list[tuple[float, int, float | None]]],
        dict[Position, float],
        float,
        float,
        list[HistoryRow],
    ]:
        """One fetch split five ways, all gated by ``kickoff_time < as_of``."""
        frame = con.execute(
            """
            SELECT season, gw, fixture, kickoff_time, code, position,
                   team_id, opponent_team_id, was_home, minutes,
                   assists, goals_scored, expected_assists
            FROM mart_fact_player_fixture
            WHERE minutes IS NOT NULL AND kickoff_time < ?
            ORDER BY kickoff_time, season, fixture, code
            """,
            [as_of],
        ).pl()
        if not frame.is_empty():
            frame = frame.sort(["kickoff_time", "season", "fixture", "code"], maintain_order=True)

        appeared_by_code: dict[int, list[tuple[float, int, float | None]]] = {}
        pos_sig: dict[Position, float] = {}
        pos_app: dict[Position, int] = {}
        pooled_sig = 0.0
        pooled_app = 0
        sum_assists = 0.0
        sum_goals = 0.0
        stage_b_rows: list[HistoryRow] = []
        for r in frame.iter_rows(named=True):
            minutes = int(r["minutes"])
            stage_b_rows.append(_to_history_row(r, minutes))
            goals_value = r["goals_scored"]
            assists_value = r["assists"]
            if assists_value is not None:
                sum_assists += float(assists_value)
            if goals_value is not None:
                sum_goals += float(goals_value)
            if minutes > 0:
                xa = _optional_float(r["expected_assists"])
                epoch = float(r["kickoff_time"].timestamp())
                appeared_by_code.setdefault(int(r["code"]), []).append((epoch, minutes, xa))
                if xa is not None:
                    pos = _position(r["position"])
                    pos_sig[pos] = pos_sig.get(pos, 0.0) + xa
                    pos_app[pos] = pos_app.get(pos, 0) + 1
                    pooled_sig += xa
                    pooled_app += 1

        positional_xa = {pos: pos_sig[pos] / pos_app[pos] for pos in pos_app if pos_app[pos] > 0}
        pooled_xa = (pooled_sig / pooled_app) if pooled_app > 0 else 0.0
        assist_rate = (sum_assists / sum_goals) if sum_goals > 0.0 else _FALLBACK_ASSIST_RATE
        return appeared_by_code, positional_xa, pooled_xa, assist_rate, stage_b_rows

    def _appearance_probabilities(
        self,
        con: duckdb.DuckDBPyConnection,
        stage_b_rows: Sequence[HistoryRow],
        targets: Sequence[TargetRowProjection],
        as_of: str,
    ) -> dict[int, float]:
        """``{code: p_play}`` from the frozen ``trailing_5_player_minutes`` baseline.

        Returns P(minutes >= 1) for each target player code.
        """
        team_codes = _all_team_codes(con)
        fitted = build_minutes_baselines(
            list(stage_b_rows), as_of=_to_utc(as_of), team_codes=team_codes, bins=self._bins
        )
        trailing5 = next(b for b in fitted if b.name == "trailing_5_player_minutes")
        p_play: dict[int, float] = {}
        for target in targets:
            if target.code in p_play:
                continue
            dist = trailing5.predict(_to_stage_b_target(target))
            p_play[target.code] = max(0.0, min(1.0, 1.0 - dist[0]))
        return p_play

    def _roster_weights(
        self,
        roster_targets: Sequence[TargetRowProjection],
        appeared_by_code: dict[int, list[tuple[float, int, float | None]]],
        positional_xa: dict[Position, float],
        pooled_xa: float,
        p_play: dict[int, float],
    ) -> tuple[dict[int, float], dict[int, bool]]:
        """Per-player raw per-appearance xA x p_play weights for one fixture's roster."""
        weights: dict[int, float] = {}
        has_measured: dict[int, bool] = {}
        for target in sorted(roster_targets, key=lambda t: t.code):
            mean_xa, measured = trailing_signal_per_appearance(
                appeared_by_code.get(target.code, []), window=self.share_window
            )
            # Cold start: position-specific xA/appearance where available, else pooled.
            share = positional_xa.get(target.position, pooled_xa) if measured == 0 else mean_xa
            weights[target.code] = share * p_play.get(target.code, 0.0)
            has_measured[target.code] = measured > 0
        return weights, has_measured

    # -- Stage A coupling (mirrors the assists V2 candidate's glue) --------------------

    def _fit_stage_a(
        self,
        con: duckdb.DuckDBPyConnection,
        as_of: str,
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

    # -- predict / diagnostics ---------------------------------------------------------

    def predict(self, target: TargetRowProjection) -> GoalCountDistribution:
        return poisson_pmf(self._rates[(target.fixture, target.code)], self.max_assists)

    def path_for(self, target: TargetRowProjection) -> str:
        return self._paths[(target.fixture, target.code)]

    def parameters(self) -> Mapping[str, float | int | bool | str]:
        return {
            "alpha": self.alpha,
            "share_window": self.share_window,
            "stage_a_model": "trailing_goals_attack_defence",
            "minutes_baseline": "trailing_5_player_minutes",
            "signal": "mean_raw_expected_assists_per_appearance_no_creativity_fallback",
            "team_assist_scale": "lambda_team_times_fold_local_assist_rate",
            "weight": "mean_xa_per_appearance_times_p_play",
            "cold_start_prior": "fold_local_position_specific_xa_per_appearance_else_pooled",
            "window": "option_a_last_five_appeared_then_measured",
            "conservation": "underlying_poisson_rate_conservation_in_expectation",
        }
