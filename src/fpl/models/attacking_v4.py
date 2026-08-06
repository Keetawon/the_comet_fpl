"""Stage C Candidate V4: exposure-weighted xG team-share attacking goals (DEVELOPMENT-ONLY).

Pre-registered in ``config/phase3_evaluation.yaml`` amendment 1.4 as
``exposure_weighted_xg_team_share_attacking_goals_v4``. Candidate V4 is the controlled test of the
hypothesis that **separating per-minute attacking productivity from predicted exposure** beats the
raw per-appearance xG share of V3. It keeps V3's team-coupling / conservation skeleton and changes
THREE things at once:

    (i) the allocation signal:
        V3 share  : mean trailing xG per appearance  (a 15-min cameo counts as much as 90-min)
        V4 weight : shrunk_xg_per_min * E[minutes]    (per-minute rate x predicted exposure)
    (ii) the cold-start prior: V3's committed POOLED all-position signal mean -> fold-local
         POSITION-SPECIFIC xG/min prior;
    (iii) the signal source: V3 reads expected_goals_else_threat; V4 is xG-ONLY
          (no threat fallback).

``shrunk_xg_per_min`` is a per-MINUTE rate (``sum(xG) / sum(minutes)``); per-90 is only a reporting
conversion (``90 * rate_per_min``) and is not how the rate is defined.

so a high-xG/90 substitute is no longer tied to a 90-minute starter. Concretely, for a club with
Stage A expected goals ``lambda_team``:

    goal_weight_i  = shrunk_xg_per_min_i * E[minutes_i]
    goal_lambda_i  = lambda_team * goal_weight_i / sum_j(goal_weight_j)
    => sum_i goal_lambda_i == lambda_team   (underlying Poisson-rate conservation; in expectation).

Key point-in-time / semantic choices (all locked in the contract, none tuned after a result):

* **xG-only.** The signal is ``expected_goals`` only; there is NO threat fallback. NULL xG means
  unmeasured and is never zero-filled (it contributes neither to the signal sum nor to the minutes
  sum). ``expected_goals`` is measured 100% only from 2023-24 onward, so judging is within those
  covered seasons (the harness still scores every eligible row including 2021-22 / partial 2022-23;
  those are reported separately, never as the verdict).
* **Option-A window.** The signal is taken over the last five APPEARED prior rows (``minutes > 0``),
  then over the measured-xG rows among them -- the same five rows V3 selects, so the only difference
  is the aggregation (exposure-weighted per-min vs mean-per-appearance).
* **Position-specific prior (a deliberate change beyond per-minute normalization).** A cold-start
  player (no measured trailing row) takes the fold-local POSITION-SPECIFIC xG/min prior (a GK prior
  is ~0, a FWD prior is large). This differs from frozen V3, whose committed cold-start fill is a
  POOLED all-position signal mean despite its contract saying "positional"; V4 does not modify or
  reinterpret V3, it explicitly chooses position-specific.
* **Expected minutes.** ``E[minutes_i] = sum_b P_i(bin=b) * bin_mean_b(fold)`` where ``P_i`` is the
  frozen Stage B BASELINE ``trailing_5_player_minutes`` distribution and ``bin_mean_b`` is the
  fold-local GLOBAL empirical mean minutes in bin b (bin 0 exactly 0; deterministic empty-bin
  fallbacks 30/75/90). This is unconditional -- it already includes the zero-minute mass -- so the
  weight must NOT be multiplied by ``P(play)`` (that would double-count availability).
* **Fixed shrinkage.** ``prior_minutes = 90`` (one full-match equivalent); locked, never tuned.
* **Minutes model.** The frozen ``trailing_5_player_minutes`` baseline (the same one V3 uses), NOT
  Stage B Candidate V3 -- so productivity and minutes are not changed simultaneously.

Because V4 is fixture-coupled (weight normalisation needs the full fold roster and a Stage A
``lambda_team`` per fixture), the harness calls the optional ``prepare(targets, con, as_of)`` hook
after fitting; ``predict``/``path_for`` look up the precomputed per-target rate. Like V1/V2/V3 this
is a FIXED closed-form estimator (no parameter grid, no inner walk-forward); ``alpha`` mirrors the
v1.0 trailing baseline (5.0) and is used only by the stage-A-uninformative fallback.

Conservation here is **underlying Poisson-rate conservation in expectation**
(``sum_i goal_lambda_i == lambda_team`` by construction). It is NOT per-draw realised-count
conservation (independent Poisson draws do not sum to a fixed total) and the candidate is never fed
to the full-points composer in this slice.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import duckdb

from fpl.models.attacking_baselines import TargetRowProjection
from fpl.models.attacking_exposure import (
    BIN_MEAN_FALLBACKS,
    allocate_team_scale,
    expected_minutes,
    shrunk_rate_per_min,
    trailing_signal_minutes,
)
from fpl.models.attacking_v2 import (
    PATH_STAGE_A_FALLBACK,
    CoupledTeamShareAttackingGoalsV2,
)

# Fold-history / Stage B row helpers are reused verbatim from V3 (same point-in-time fetch + row
# conversion). V4 does not subclass V3; it imports its module-level helpers to avoid duplicating the
# DuckDB-to-HistoryRow mapping and the team-code / UTC conversions.
from fpl.models.attacking_v3 import (
    _all_team_codes,
    _optional_float,
    _position,
    _to_history_row,
    _to_stage_b_target,
    _to_utc,
)
from fpl.types import Position
from fpl.validate.dev_exposure_diagnostics import FoldDiagnosticsSink, RosterConservation
from fpl.validate.minutes_baselines import (
    HistoryRow,
    MinuteBins,
    build_minutes_baselines,
)

NAME = "exposure_weighted_xg_team_share_attacking_goals_v4"

# Per-target estimator path labels (development diagnostics, never a gate).
PATH_EXPOSURE_WEIGHTED = "stage_a_exposure_weighted"
PATH_EXPOSURE_COLD_START = "stage_a_exposure_cold_start"
PATH_EXPOSURE_EQUAL_SHARE = "stage_a_exposure_equal_share"
# The stage-A-uninformative path reuses V2's label so the fallback reads identically everywhere.


class ExposureWeightedXgTeamShareAttackingGoalsV4(CoupledTeamShareAttackingGoalsV2):
    """Fold-local exposure-weighted xG team-share attacking-goals estimator.

    Subclasses V2 to reuse ``fit`` (the v1.0-identical trailing-goals fallback components),
    ``_fit_stage_a`` (Stage A refit fold-local on ``kickoff_time < as_of``), ``_team_code_map``
    (season-scoped ``team_id -> team_code``), ``_trailing_baseline_rate`` (the exact v1.0 trailing
    rate used when Stage A is uninformative), and the inherited ``predict``/``path_for``
    lookup. V4 overrides ``prepare`` to allocate ``lambda_team`` by exposure weights instead of
    V2/V3 shares.
    """

    name: str = NAME

    def __init__(
        self,
        *,
        alpha: float,
        share_window: int,
        bins: MinuteBins,
        prior_minutes: float,
        empty_bin_fallbacks: tuple[float, float, float, float] = BIN_MEAN_FALLBACKS,
        max_goals: int = 10,
        diagnostics_sink: FoldDiagnosticsSink | None = None,
    ) -> None:
        # xG_covered_seasons is vestigial for V4: V4 is xG-only with no threat fallback, so it never
        # does season-conditional signal selection. An empty frozenset satisfies the V2 constructor;
        # V4's prepare never reads it.
        super().__init__(
            alpha=alpha,
            share_window=share_window,
            xg_covered_seasons=frozenset(),
            max_goals=max_goals,
        )
        self._bins = bins
        self.prior_minutes = prior_minutes
        # Empty-bin fallbacks are injected from the frozen contract (via the runner factory) so the
        # evaluation never relies on an independent hardcoded copy. The module default above is for
        # direct pure-model unit tests that do not load the contract.
        self._empty_bin_fallbacks = empty_bin_fallbacks
        # Optional development-diagnostics sink (conservation + exposure tags); None on the
        # baselines-only / offline-test paths.
        self._diagnostics_sink = diagnostics_sink

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
        appeared_by_code, position_rate, bin_means, stage_b_rows = self._fold_history(con, as_of)
        expected_min = self._expected_minutes(con, stage_b_rows, targets, as_of, bin_means)

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
            weights, has_measured, any_missing_prior = self._roster_weights(
                roster_targets, appeared_by_code, position_rate, expected_min
            )
            if any_missing_prior or math.fsum(weights.values()) <= 0.0:
                # A position with no measured-signal prior anywhere in the fold (pre-xG), or an
                # all-zero roster: deterministic equal-share roster fallback, still conserving
                # lambda_team. Reported per target via the path label.
                share = lambda_team / len(weights)
                for target in roster_targets:
                    rates[(target.fixture, target.code)] = share
                    paths[(target.fixture, target.code)] = PATH_EXPOSURE_EQUAL_SHARE
                roster_path = PATH_EXPOSURE_EQUAL_SHARE
            else:
                allocated = allocate_team_scale(weights, lambda_team)
                for target in roster_targets:
                    rates[(target.fixture, target.code)] = allocated[target.code]
                    paths[(target.fixture, target.code)] = (
                        PATH_EXPOSURE_WEIGHTED
                        if has_measured[target.code]
                        else PATH_EXPOSURE_COLD_START
                    )
                roster_path = PATH_EXPOSURE_WEIGHTED

            if self._diagnostics_sink is not None:
                # Underlying Poisson-rate conservation record for this coupled roster (both the
                # weighted and equal-share branches conserve lambda_team exactly).
                self._diagnostics_sink.conservation.append(
                    RosterConservation(
                        season=season,
                        fixture=roster_targets[0].fixture,
                        team_code=team_code,
                        n_rates=len(roster_targets),
                        sum_rates=math.fsum(rates[(t.fixture, t.code)] for t in roster_targets),
                        team_scale=lambda_team,
                        path=roster_path,
                    )
                )

        self._rates = rates
        self._paths = paths
        if self._diagnostics_sink is not None:
            # Per-fold exposure tags (candidate-independent: Stage B E[minutes] + trailing appeared
            # minutes). Overwritten each prepare; the runner reads them between folds.
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

    # -- fold history: appeared xG+minutes, position-specific xG/min prior, bin means, Stage B --

    def _fold_history(
        self,
        con: duckdb.DuckDBPyConnection,
        as_of: str,
    ) -> tuple[
        dict[int, list[tuple[float, int, float | None]]],
        dict[Position, float],
        tuple[float, float, float, float],
        list[HistoryRow],
    ]:
        """One fetch of minutes-not-null prior rows, split four ways.

        Returns (a) per-code appeared rows as ``(epoch, minutes, xG)`` for the Option-A window;
        (b) the fold-local POSITION-SPECIFIC xG/min prior (positions with no measured-xG appeared
        row are absent -> equal-share fallback); (c) the four fold-local GLOBAL bin means (bin 0
        exactly 0); (d) every minutes-not-null row as a Stage B ``HistoryRow`` for the trailing-5
        minutes fit. All gated by ``kickoff_time < as_of``.
        """
        frame = con.execute(
            """
            SELECT season, gw, fixture, kickoff_time, code, position,
                   team_id, opponent_team_id, was_home, minutes, expected_goals
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
        stage_b_rows: list[HistoryRow] = []
        for r in frame.iter_rows(named=True):
            minutes = int(r["minutes"])
            index = self._bins.index_of(minutes)
            bin_sum[index] += minutes
            bin_n[index] += 1
            stage_b_rows.append(_to_history_row(r, minutes))
            if minutes > 0:
                xg = _optional_float(r["expected_goals"])
                epoch = float(r["kickoff_time"].timestamp())
                appeared_by_code.setdefault(int(r["code"]), []).append((epoch, minutes, xg))
                pos = _position(r["position"])
                if xg is not None:
                    pos_sig[pos] = pos_sig.get(pos, 0.0) + xg
                    pos_min[pos] = pos_min.get(pos, 0.0) + minutes

        position_rate = {pos: pos_sig[pos] / pos_min[pos] for pos in pos_min if pos_min[pos] > 0.0}
        bin_means = (
            (bin_sum[0] / bin_n[0]) if bin_n[0] > 0 else self._empty_bin_fallbacks[0],
            (bin_sum[1] / bin_n[1]) if bin_n[1] > 0 else self._empty_bin_fallbacks[1],
            (bin_sum[2] / bin_n[2]) if bin_n[2] > 0 else self._empty_bin_fallbacks[2],
            (bin_sum[3] / bin_n[3]) if bin_n[3] > 0 else self._empty_bin_fallbacks[3],
        )
        return appeared_by_code, position_rate, bin_means, stage_b_rows

    def _expected_minutes(
        self,
        con: duckdb.DuckDBPyConnection,
        stage_b_rows: Sequence[HistoryRow],
        targets: Sequence[TargetRowProjection],
        as_of: str,
        bin_means: tuple[float, float, float, float],
    ) -> dict[int, float]:
        """``{code: E[minutes]}`` from the frozen ``trailing_5_player_minutes`` baseline.

        The baseline is fit fold-local on ``kickoff_time < as_of`` minutes history (the same frozen
        baseline V3 uses, NOT Stage B Candidate V3); the target fixture's minutes never enter. For
        each target ``E[minutes] = sum_b P(bin=b) * bin_mean_b`` (unconditional: bin 0 contributes
        the exactly-zero bin mean). Probabilities are per ``code`` (the baseline keys on ``code``).
        """
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
        """Per-player exposure weights for one fixture's roster.

        Returns ``(weights, has_measured, any_missing_prior)``. ``weights[code] = shrunk_xg_per_min
        * E[minutes]`` (zero for a player whose position has no prior); ``has_measured[code]`` flags
        a measured trailing row (weighted vs cold-start path); ``any_missing_prior`` is True if any
        roster player's position has no measured-xG prior in the fold (-> equal-share fallback).
        Players are sorted by code for a deterministic float-sum order in the normalisation.
        """
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

    def parameters(self) -> Mapping[str, float | int | bool | str]:
        return {
            "alpha": self.alpha,
            "share_window": self.share_window,
            "prior_minutes": self.prior_minutes,
            "stage_a_model": "trailing_goals_attack_defence",
            "minutes_baseline": "trailing_5_player_minutes",
            "signal": "expected_goals_only_no_fallback",
            "expected_minutes": "fold_local_global_bin_means",
            "cold_start_prior": "fold_local_position_specific_xg_per_min",
            "window": "option_a_last_five_appeared_then_measured",
        }
