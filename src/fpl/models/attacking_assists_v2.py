"""Stage C assists Candidate V2: exposure-weighted xA team-share assists (DEVELOPMENT-ONLY).

Pre-registered in ``config/phase3_stage_c_assists_evaluation.yaml`` amendment 1.2 as
``exposure_weighted_xa_team_share_assists_v2``. This is the assists analogue of the goals Candidate
V4 (``exposure_weighted_xg_team_share_attacking_goals_v4``): it tests whether separating per-minute
assist productivity from predicted exposure beats the raw per-appearance xA share. It keeps the
team-coupling / conservation skeleton of the goals candidates and changes THREE things versus that
raw per-appearance xA allocation: (i) the allocation signal becomes ``shrunk_xa_per_min *
E[minutes]`` (a per-MINUTE rate ``sum(xA)/sum(minutes)`` -- per-90 is only a reporting conversion,
``90 * rate_per_min`` -- times predicted exposure) instead of a mean trailing xA per appearance;
(ii) the cold-start prior is fold-local POSITION-SPECIFIC xA/min (the same deliberate
choice as goals V4; assists has no prior coupled candidate with a committed pooled behavior to
inherit); and (iii) the signal is xA-ONLY with NO creativity fallback (assists V1 reads
``expected_assists_else_creativity``; this candidate never reads ``creativity``).

Assists scale with team goals by a fold-local league assist rate (~0.90, ``sum(assists) /
sum(goals_scored)``), so a club's assisted-goal expectation is ``lambda_team * assist_rate`` and is
allocated among the club's players by an xA-exposure weight:

    assist_weight_i = shrunk_xa_per_min_i * E[minutes_i]
    team_assist_lambda = lambda_team * assist_rate
    assist_lambda_i = team_assist_lambda * assist_weight_i / sum_j(assist_weight_j)
    => sum_i assist_lambda_i == team_assist_lambda   (underlying Poisson-rate conservation).

Point-in-time / semantic choices (identical to goals V4; all locked in the contract):

* **xA-only.** The signal is ``expected_assists`` only; there is NO creativity fallback (this
  candidate never reads ``creativity``). NULL xA is unmeasured and never zero-filled (it contributes
  neither to the signal sum nor to the minutes sum). xA has the same measured-coverage profile as
  xG (NULL in 2021-22, partial 2022-23, 100% from 2023-24); judging is within those covered seasons.
* **Option-A window**, **position-specific xA/min cold-start prior**, **fold-local global bin means
  for E[minutes]**, **fixed ``prior_minutes = 90`` shrinkage**, and the frozen
  ``trailing_5_player_minutes`` baseline (not Stage B Candidate V3) -- see the goals V4 module for
  the full statement of each.

Conservation is **underlying Poisson-rate conservation in expectation**
(``sum_i assist_lambda_i == team_assist_lambda``); not per-draw realised-count conservation, and the
candidate is never fed to the full-points composer in this slice.

This is a FIXED closed-form estimator (no parameter grid, no inner walk-forward). It is standalone
(it does not subclass a goals candidate): assists have their own label, own baselines, own signal,
and the stage-A-uninformative fallback is the v1.0 trailing-ASSISTS rate (not the goals rate).
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
from fpl.models.attacking_exposure import (
    BIN_MEAN_FALLBACKS,
    allocate_team_scale,
    expected_minutes,
    shrunk_rate_per_min,
    trailing_signal_minutes,
)

# The Stage A team-match training projection is reused verbatim from the goals V2 candidate so a
# Phase 1 harness refactor cannot silently change what Stage A was fit on here; drift is caught by
# the candidate-source fingerprint. This module does NOT import the goals candidate class.
from fpl.models.attacking_v2 import _TEAM_MATCH_FROM, _TEAM_MATCH_SELECT

# Fold-history / Stage B row helpers reused from V3 (same point-in-time fetch + row conversion).
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
from fpl.validate.dev_exposure_diagnostics import FoldDiagnosticsSink, RosterConservation
from fpl.validate.minutes_baselines import (
    HistoryRow,
    MinuteBins,
    build_minutes_baselines,
)

NAME = "exposure_weighted_xa_team_share_assists_v2"

# The measured-league assist rate fallback when a fold has scored zero goals (degenerate early
# fold). Pre-registered; the fold-local ratio is used wherever it is defined.
_FALLBACK_ASSIST_RATE: float = 0.90

# Per-target estimator path labels (development diagnostics, never a gate).
PATH_EXPOSURE_WEIGHTED = "stage_a_exposure_weighted"
PATH_EXPOSURE_COLD_START = "stage_a_exposure_cold_start"
PATH_EXPOSURE_EQUAL_SHARE = "stage_a_exposure_equal_share"
PATH_STAGE_A_FALLBACK = "stage_a_uninformative_trailing"


class ExposureWeightedXaTeamShareAssistsV2:
    """Fold-local exposure-weighted xA team-share assists estimator."""

    name: str = NAME

    def __init__(
        self,
        *,
        alpha: float,
        share_window: int,
        bins: MinuteBins,
        prior_minutes: float,
        empty_bin_fallbacks: tuple[float, float, float, float] = BIN_MEAN_FALLBACKS,
        max_assists: int = 10,
        diagnostics_sink: FoldDiagnosticsSink | None = None,
    ) -> None:
        self.alpha = alpha
        self.share_window = share_window
        self._bins = bins
        self.prior_minutes = prior_minutes
        self.max_assists = max_assists
        # Empty-bin fallbacks are injected from the frozen contract (via the runner factory) so the
        # evaluation never relies on an independent hardcoded copy. The module default above is for
        # direct pure-model unit tests that do not load the contract.
        self._empty_bin_fallbacks = empty_bin_fallbacks
        # Optional development-diagnostics sink (conservation + exposure tags); None on the
        # baselines-only / offline-test paths.
        self._diagnostics_sink = diagnostics_sink
        self._positional = PositionalAssistRateBaseline()
        self._player_history: dict[int, list[AssistHistoryRow]] = {}
        # Populated by prepare(): {(fixture, code): rate} and matching path labels.
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

    # -- prepare (Stage A coupling + appeared-rows exposure shares) -------------------

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
            position_rate,
            assist_rate,
            bin_means,
            stage_b_rows,
        ) = self._fold_history(con, as_of)
        expected_min = self._expected_minutes(con, stage_b_rows, targets, as_of, bin_means)

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
            weights, has_measured, any_missing_prior = self._roster_weights(
                roster_targets, appeared_by_code, position_rate, expected_min
            )
            if any_missing_prior or math.fsum(weights.values()) <= 0.0:
                share = team_assist_lambda / len(weights)
                for target in roster_targets:
                    rates[(target.fixture, target.code)] = share
                    paths[(target.fixture, target.code)] = PATH_EXPOSURE_EQUAL_SHARE
                roster_path = PATH_EXPOSURE_EQUAL_SHARE
            else:
                allocated = allocate_team_scale(weights, team_assist_lambda)
                for target in roster_targets:
                    rates[(target.fixture, target.code)] = allocated[target.code]
                    paths[(target.fixture, target.code)] = (
                        PATH_EXPOSURE_WEIGHTED
                        if has_measured[target.code]
                        else PATH_EXPOSURE_COLD_START
                    )
                roster_path = PATH_EXPOSURE_WEIGHTED

            if self._diagnostics_sink is not None:
                self._diagnostics_sink.conservation.append(
                    RosterConservation(
                        season=season,
                        fixture=roster_targets[0].fixture,
                        team_code=team_code,
                        n_rates=len(roster_targets),
                        sum_rates=math.fsum(rates[(t.fixture, t.code)] for t in roster_targets),
                        team_scale=team_assist_lambda,
                        path=roster_path,
                    )
                )

        self._rates = rates
        self._paths = paths
        if self._diagnostics_sink is not None:
            self._diagnostics_sink.exposure_tags = {
                t.code: (
                    expected_min.get(t.code, 0.0),
                    math.fsum(
                        m
                        for _e, m, _s in list(appeared_by_code.get(t.code, []))[
                            -self.share_window :
                        ]
                    ),
                )
                for t in targets
            }

    # -- fold history: appeared xA+minutes, position prior, assist rate, bin means ------

    def _fold_history(
        self,
        con: duckdb.DuckDBPyConnection,
        as_of: str,
    ) -> tuple[
        dict[int, list[tuple[float, int, float | None]]],
        dict[Position, float],
        float,
        tuple[float, float, float, float],
        list[HistoryRow],
    ]:
        """One fetch split five ways: appeared xA rows, position xA/min prior, fold assist rate,
        global bin means, and Stage B minutes rows. All gated by ``kickoff_time < as_of``."""
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
        pos_min: dict[Position, float] = {}
        bin_sum = [0.0, 0.0, 0.0, 0.0]
        bin_n = [0, 0, 0, 0]
        sum_assists = 0.0
        sum_goals = 0.0
        stage_b_rows: list[HistoryRow] = []
        for r in frame.iter_rows(named=True):
            minutes = int(r["minutes"])
            index = self._bins.index_of(minutes)
            bin_sum[index] += minutes
            bin_n[index] += 1
            stage_b_rows.append(_to_history_row(r, minutes))
            # League assist rate = sum(assists) / sum(goals_scored) over minutes-not-null history.
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
                pos = _position(r["position"])
                if xa is not None:
                    pos_sig[pos] = pos_sig.get(pos, 0.0) + xa
                    pos_min[pos] = pos_min.get(pos, 0.0) + minutes

        position_rate = {pos: pos_sig[pos] / pos_min[pos] for pos in pos_min if pos_min[pos] > 0.0}
        assist_rate = (sum_assists / sum_goals) if sum_goals > 0.0 else _FALLBACK_ASSIST_RATE
        bin_means = (
            (bin_sum[0] / bin_n[0]) if bin_n[0] > 0 else self._empty_bin_fallbacks[0],
            (bin_sum[1] / bin_n[1]) if bin_n[1] > 0 else self._empty_bin_fallbacks[1],
            (bin_sum[2] / bin_n[2]) if bin_n[2] > 0 else self._empty_bin_fallbacks[2],
            (bin_sum[3] / bin_n[3]) if bin_n[3] > 0 else self._empty_bin_fallbacks[3],
        )
        return appeared_by_code, position_rate, assist_rate, bin_means, stage_b_rows

    def _expected_minutes(
        self,
        con: duckdb.DuckDBPyConnection,
        stage_b_rows: Sequence[HistoryRow],
        targets: Sequence[TargetRowProjection],
        as_of: str,
        bin_means: tuple[float, float, float, float],
    ) -> dict[int, float]:
        """``{code: E[minutes]}`` from frozen ``trailing_5_player_minutes`` (same as goals V4)."""
        team_codes = _all_team_codes(con)
        fitted = build_minutes_baselines(
            list(stage_b_rows), as_of=_to_utc(as_of), team_codes=team_codes, bins=self._bins
        )
        trailing5 = next(b for b in fitted if b.name == "trailing_5_player_minutes")
        out: dict[int, float] = {}
        for target in targets:
            if target.code in out:
                continue
            dist = trailing5.predict(_to_stage_b_target(target))
            out[target.code] = expected_minutes(dist, bin_means)
        return out

    def _roster_weights(
        self,
        roster_targets: Sequence[TargetRowProjection],
        appeared_by_code: dict[int, list[tuple[float, int, float | None]]],
        position_rate: dict[Position, float],
        expected_min: dict[int, float],
    ) -> tuple[dict[int, float], dict[int, bool], bool]:
        """Per-player exposure weights for one fixture's roster (assists analogue of V4)."""
        weights: dict[int, float] = {}
        has_measured: dict[int, bool] = {}
        any_missing_prior = False
        for target in sorted(roster_targets, key=lambda t: t.code):
            prior = position_rate.get(target.position)
            if prior is None:
                any_missing_prior = True
                weights[target.code] = 0.0
                has_measured[target.code] = False
                continue
            sig_sum, min_sum = trailing_signal_minutes(
                appeared_by_code.get(target.code, []), window=self.share_window
            )
            rate_per_min = shrunk_rate_per_min(
                sig_sum, min_sum, prior, prior_minutes=self.prior_minutes
            )
            weights[target.code] = rate_per_min * expected_min.get(target.code, 0.0)
            has_measured[target.code] = min_sum > 0.0
        return weights, has_measured, any_missing_prior

    # -- Stage A coupling (mirrors the goals V2 candidate's glue) ----------------------

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

    # -- predict / diagnostics --------------------------------------------------------

    def predict(self, target: TargetRowProjection) -> GoalCountDistribution:
        return poisson_pmf(self._rates[(target.fixture, target.code)], self.max_assists)

    def path_for(self, target: TargetRowProjection) -> str:
        return self._paths[(target.fixture, target.code)]

    def parameters(self) -> Mapping[str, float | int | bool | str]:
        return {
            "alpha": self.alpha,
            "share_window": self.share_window,
            "prior_minutes": self.prior_minutes,
            "stage_a_model": "trailing_goals_attack_defence",
            "minutes_baseline": "trailing_5_player_minutes",
            "signal": "expected_assists_only_no_fallback",
            "team_assist_scale": "lambda_team_times_fold_local_assist_rate",
            "expected_minutes": "fold_local_global_bin_means",
            "cold_start_prior": "fold_local_position_specific_xa_per_min",
            "window": "option_a_last_five_appeared_then_measured",
        }
