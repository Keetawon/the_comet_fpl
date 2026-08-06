"""Validation harness and metric calculators for Stage D / Prospective EV Walk-forward Backtest.

Evaluates prospective EV ranking, calibration, and distribution performance over GW29-38 of
2025-26 against replayed points under scoring_2026_27.

Fixture full-points support is 0..34 (DEFAULT_MAX_POINTS_FULL).
Bin 34 represents 34+. For proper scores (Log Score, CRPS, PIT-80), actual target is clamped:
    scored_target = min(max(actual_points, 0), max_support)
Multi-fixture (DGW) PMFs are convolved without truncation over support 0..(34 * fixture_count).
Weekly EV is the exact sum of fixture EVs.
Cumulative ranking aggregates player-GW rows by player code across all 10 gameweeks.

Two grains, deliberately, and they do NOT reconcile by averaging:

* The overall report's proper scores and MAE/RMSE are computed at **fixture** grain
  ``(season, code, fixture)`` -- the contract's scored population.
* ``gw_calibration`` is computed at **player-GW** grain, on the convolved rows, because that is
  the grain a weekly decision is made at. A DGW player is one row there and two here, and each
  gameweek draws its own PIT randomisation, so the per-GW means are a separate weekly view and
  never average to the overall figure. ``ev_total``/``actual_total`` do sum across both, since
  weekly EV is the exact sum of fixture EVs.

One tie policy governs every ranking output. The oracle ordering is ``(-actual_points, code)``
everywhere -- NDCG, capture ratio, overlap, displayed ``actual_rank``, and ``in_both_top_20`` --
so ``top_20_overlap`` always equals the fraction of detail rows flagged ``in_both_top_20``.
Predicted EV must never enter the actual ordering: among actual-points ties (very common at both
grains) an EV tiebreak would hand the higher-EV player the better actual rank and the oracle
slot, flattering the model in exactly the table a reader checks it against.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from fpl.validate.metrics import crps, log_score, randomised_pit


@dataclass(frozen=True, slots=True)
class FixturePredictionRow:
    season: str
    gw: int
    fixture: int
    code: int
    position: str
    team_code: int
    opponent_team_code: int
    ev: float
    pmf: tuple[float, ...]  # 0..34 fixture points distribution (bin 34 is 34+)
    actual_points: int  # Raw fixture points under scoring_2026_27 (may be negative or > 34)


@dataclass(frozen=True, slots=True)
class PlayerGwRow:
    season: str
    gw: int
    code: int
    position: str
    team_code: int
    fixture_count: int
    ev: float
    pmf: tuple[float, ...]  # Convolved over support 0..(34 * fixture_count)
    actual_points: int


@dataclass(frozen=True, slots=True)
class Top20PlayerRow:
    code: int
    position: str
    team_code: int
    ev: float
    actual_points: int
    predicted_rank: int
    actual_rank: int
    in_both_top_20: bool


@dataclass(frozen=True, slots=True)
class GwRankingMetrics:
    gw: int
    predictions_count: int
    negative_actual_count: int
    upper_tail_actual_count: int
    ndcg_at_20: float
    top_20_capture_ratio: float
    top_20_overlap: float
    spearman_within_gw: float
    spearman_by_position: dict[str, float]
    top_20_details: tuple[Top20PlayerRow, ...]


@dataclass(frozen=True, slots=True)
class GwCalibrationMetrics:
    gw: int
    ev_total: float
    actual_total: float
    signed_bias: float
    ev_actual_ratio: float
    mae: float
    rmse: float
    mean_log_score: float
    mean_crps: float
    pit_80_coverage: float


@dataclass(frozen=True, slots=True)
class BacktestScoreReport:
    season: str
    start_gw: int
    end_gw: int
    distinct_fixture_count: int
    total_player_fixture_rows: int
    total_player_gw_rows: int
    total_unique_players: int
    total_negative_actuals: int
    total_upper_tail_actuals: int
    cumulative_ndcg_at_20: float
    cumulative_top_20_capture_ratio: float
    cumulative_top_20_overlap: float
    cumulative_spearman: float
    cumulative_spearman_by_position: dict[str, float]
    ev_total: float
    actual_total: float
    signed_bias: float
    ev_actual_ratio: float
    mae: float
    rmse: float
    mean_log_score: float
    mean_crps: float
    mean_ranked_probability_score: float
    pit_80_coverage: float
    gw_metrics: tuple[GwRankingMetrics, ...]
    gw_calibration: tuple[GwCalibrationMetrics, ...]
    cumulative_top_20_details: tuple[Top20PlayerRow, ...]


# --------------------------------------------------------------------------------------
# PMF Convolution & Aggregation Helpers
# --------------------------------------------------------------------------------------


def convolve_pmfs(pmf1: Sequence[float], pmf2: Sequence[float]) -> tuple[float, ...]:
    """Discrete linear convolution of two PMFs without truncation."""
    len1 = len(pmf1)
    len2 = len(pmf2)
    out = [0.0] * (len1 + len2 - 1)
    for i, p1 in enumerate(pmf1):
        if p1 <= 0.0:
            continue
        for j, p2 in enumerate(pmf2):
            if p2 <= 0.0:
                continue
            out[i + j] += p1 * p2
    # Re-normalise to guarantee exact sum = 1.0
    tot = sum(out)
    if tot > 0.0:
        out = [x / tot for x in out]
    return tuple(out)


def aggregate_fixture_rows_to_player_gw(
    fixture_rows: Sequence[FixturePredictionRow],
) -> list[PlayerGwRow]:
    """Group fixture-grain predictions into player-GW rows, convolving DGW PMFs without truncation.

    Weekly EV is the exact sum of fixture EVs.
    """
    grouped: dict[tuple[str, int, int], list[FixturePredictionRow]] = defaultdict(list)
    for r in fixture_rows:
        grouped[(r.season, r.gw, r.code)].append(r)

    player_gw_rows: list[PlayerGwRow] = []
    for (season, gw, code), rows in grouped.items():
        rows_sorted = sorted(rows, key=lambda x: x.fixture)
        pos = rows_sorted[0].position
        team_code = rows_sorted[0].team_code
        fixture_count = len(rows_sorted)

        # Weekly EV is exact sum of fixture EVs
        ev_sum = sum(r.ev for r in rows_sorted)
        act_sum = sum(r.actual_points for r in rows_sorted)

        # Convolve fixture PMFs
        curr_pmf = rows_sorted[0].pmf
        for next_row in rows_sorted[1:]:
            curr_pmf = convolve_pmfs(curr_pmf, next_row.pmf)

        player_gw_rows.append(
            PlayerGwRow(
                season=season,
                gw=gw,
                code=code,
                position=pos,
                team_code=team_code,
                fixture_count=fixture_count,
                ev=ev_sum,
                pmf=curr_pmf,
                actual_points=act_sum,
            )
        )

    return sorted(player_gw_rows, key=lambda x: (x.gw, -x.ev, x.code))


# --------------------------------------------------------------------------------------
# Ranking & Calibration Metric Calculators
# --------------------------------------------------------------------------------------


def compute_spearman_rank_correlation(x: Sequence[float], y: Sequence[float]) -> float:
    """Compute Spearman rank correlation between two vectors x and y with tie handling."""
    if len(x) != len(y) or len(x) < 2:
        return 0.0

    def _rank_vector(vec: Sequence[float]) -> list[float]:
        n = len(vec)
        sorted_indices = sorted(range(n), key=lambda i: vec[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j < n - 1 and vec[sorted_indices[j]] == vec[sorted_indices[j + 1]]:
                j += 1
            avg_rank = (i + j + 2) / 2.0
            for k in range(i, j + 1):
                ranks[sorted_indices[k]] = avg_rank
            i = j + 1
        return ranks

    rx = _rank_vector(x)
    ry = _rank_vector(y)

    mean_rx = sum(rx) / len(rx)
    mean_ry = sum(ry) / len(ry)

    num = sum((rx[i] - mean_rx) * (ry[i] - mean_ry) for i in range(len(rx)))
    den_x = sum((rx[i] - mean_rx) ** 2 for i in range(len(rx)))
    den_y = sum((ry[i] - mean_ry) ** 2 for i in range(len(ry)))

    if den_x <= 0.0 or den_y <= 0.0:
        return 0.0

    return num / math.sqrt(den_x * den_y)


def _predicted_order(rows: Sequence[PlayerGwRow]) -> list[PlayerGwRow]:
    """The single predicted ordering: EV DESC, then code ASC. Used by every ranking output."""
    return sorted(rows, key=lambda r: (-r.ev, r.code))


def _oracle_order(rows: Sequence[PlayerGwRow]) -> list[PlayerGwRow]:
    """The single oracle ordering: actual points DESC, then code ASC.

    EV is deliberately absent from this key. See the module docstring: an EV tiebreak inside an
    actual-points tie biases the oracle toward the model being scored.
    """
    return sorted(rows, key=lambda r: (-r.actual_points, r.code))


def compute_ndcg_at_k(rows: Sequence[PlayerGwRow], k: int = 20) -> tuple[float, float, float]:
    """Compute NDCG@k, Top-k capture ratio, and Top-k overlap for player-GW rows.

    Predicted order is (ev DESC, code ASC); oracle order is (actual_points DESC, code ASC).
    Relevance for NDCG is max(0, actual_points). :func:`_top_20_details` uses the same two
    orderings, so the overlap returned here equals the fraction of detail rows flagged
    ``in_both_top_20``.
    """
    if not rows or k <= 0:
        return 1.0, 1.0, 1.0

    pred_k = _predicted_order(rows)[:k]
    oracle_k = _oracle_order(rows)[:k]

    dcg = 0.0
    for r_idx, row in enumerate(pred_k, start=1):
        rel = max(0.0, float(row.actual_points))
        dcg += rel / math.log2(r_idx + 1)

    idcg = 0.0
    for r_idx, row in enumerate(oracle_k, start=1):
        rel = max(0.0, float(row.actual_points))
        idcg += rel / math.log2(r_idx + 1)

    ndcg = (dcg / idcg) if idcg > 0.0 else 1.0

    pred_sum = sum(row.actual_points for row in pred_k)
    oracle_sum = sum(row.actual_points for row in oracle_k)
    capture_ratio = (pred_sum / oracle_sum) if oracle_sum > 0 else 1.0

    pred_codes = {row.code for row in pred_k}
    oracle_codes = {row.code for row in oracle_k}
    overlap = len(pred_codes & oracle_codes) / float(min(k, len(rows)))

    return ndcg, capture_ratio, overlap


def _top_20_details(rows: Sequence[PlayerGwRow], k: int = 20) -> tuple[Top20PlayerRow, ...]:
    """Build detailed top-k player ranking rows under the harness's single tie policy.

    Both orderings come from :func:`_predicted_order` and :func:`_oracle_order`, the same two
    functions :func:`compute_ndcg_at_k` uses. Ties in EV break by player code ASC; ties in actual
    points also break by player code ASC and never by EV. That equality is the contract: the
    displayed ``actual_rank``, the ``in_both_top_20`` flag, and the aggregate ``top_20_overlap``
    are all reading one oracle, so the detail table cannot disagree with the headline number.
    """
    if not rows:
        return ()

    pred_sorted = _predicted_order(rows)
    actual_sorted = _oracle_order(rows)

    actual_rank_map = {r.code: rank for rank, r in enumerate(actual_sorted, start=1)}
    oracle_top_k_codes = {r.code for r in actual_sorted[:k]}

    top_k_rows: list[Top20PlayerRow] = []
    for pred_rank, r in enumerate(pred_sorted[:k], start=1):
        top_k_rows.append(
            Top20PlayerRow(
                code=r.code,
                position=r.position,
                team_code=r.team_code,
                ev=r.ev,
                actual_points=r.actual_points,
                predicted_rank=pred_rank,
                actual_rank=actual_rank_map[r.code],
                in_both_top_20=(r.code in oracle_top_k_codes),
            )
        )
    return tuple(top_k_rows)


def score_backtest_rows(
    fixture_rows: Sequence[FixturePredictionRow],
    *,
    seed: int = 202627,
    max_support: int = 34,
    pit_band: tuple[float, float] = (0.1, 0.9),
) -> BacktestScoreReport:
    """Score a backtest population of FixturePredictionRow entries.

    Proper scores (Log Score, CRPS, PIT-80) evaluated directly at fixture grain (0..34 support).
    Bin 34 represents 34+; scored_target = min(max(actual_points, 0), max_support).
    Weekly rankings evaluated on convolved player-GW rows.
    Cumulative rankings aggregated across all 10 GWs per player code.

    ``seed``, ``max_support``, and ``pit_band`` are supplied by the caller from the frozen
    contract (``monte_carlo.seed`` / ``scoring_calibration.randomized_pit_seed``,
    ``support.max_fixture_points``, ``scoring_calibration.randomized_pit_band``) rather than
    fixed here, so a contract change moves the numbers instead of being silently ignored.
    """
    if not fixture_rows:
        raise ValueError("Cannot score empty fixture prediction rows")

    pit_low, pit_high = pit_band
    expected_pmf_length = max_support + 1

    # Validate unique grain (season, code, fixture) and PMF properties
    seen_keys: set[tuple[str, int, int]] = set()
    for r in fixture_rows:
        key = (r.season, r.code, r.fixture)
        if key in seen_keys:
            raise ValueError(f"Duplicate prediction grain {key}")
        seen_keys.add(key)

        if len(r.pmf) != expected_pmf_length:
            raise ValueError(
                f"Fixture PMF length {len(r.pmf)} != {expected_pmf_length} for code {r.code}"
            )
        if not math.isfinite(r.ev):
            raise ValueError(f"Non-finite EV {r.ev} for player code {r.code}")
        for p_k in r.pmf:
            if not math.isfinite(p_k) or p_k < 0.0:
                raise ValueError(f"Invalid PMF probability {p_k} for player code {r.code}")
        if abs(sum(r.pmf) - 1.0) > 1e-4:
            raise ValueError(f"Fixture PMF sum {sum(r.pmf)} != 1.0 for player code {r.code}")
        expected_from_pmf = sum(k * p for k, p in enumerate(r.pmf))
        if abs(r.ev - expected_from_pmf) > 1e-4:
            raise ValueError(
                f"EV {r.ev} != PMF expectation {expected_from_pmf} for player code {r.code}"
            )

    season = fixture_rows[0].season
    gws = sorted({r.gw for r in fixture_rows})
    start_gw = min(gws)
    end_gw = max(gws)

    # 1. Aggregate to Player-GW rows for weekly rankings
    player_gw_rows = aggregate_fixture_rows_to_player_gw(fixture_rows)

    by_gw_player: dict[int, list[PlayerGwRow]] = defaultdict(list)
    for p_row in player_gw_rows:
        by_gw_player[p_row.gw].append(p_row)

    gw_ranking_list: list[GwRankingMetrics] = []
    gw_calib_list: list[GwCalibrationMetrics] = []

    # 2. Score Weekly GW Rankings & Calibration
    for gw in gws:
        gw_players = by_gw_player[gw]
        n_gw_players = len(gw_players)
        neg_count = sum(1 for r in gw_players if r.actual_points < 0)
        upper_count = sum(1 for r in gw_players if r.actual_points > (len(r.pmf) - 1))

        ndcg, capture, overlap = compute_ndcg_at_k(gw_players, k=20)
        top_20_det = _top_20_details(gw_players, k=20)

        ev_vec = [r.ev for r in gw_players]
        act_vec = [float(r.actual_points) for r in gw_players]
        spearman_gw = compute_spearman_rank_correlation(ev_vec, act_vec)

        by_pos_gw: dict[str, list[PlayerGwRow]] = defaultdict(list)
        for pg_row in gw_players:
            by_pos_gw[pg_row.position].append(pg_row)

        spearman_pos_gw: dict[str, float] = {}
        for pos, pos_rows in by_pos_gw.items():
            if len(pos_rows) >= 2:
                spearman_pos_gw[pos] = compute_spearman_rank_correlation(
                    [r.ev for r in pos_rows], [float(r.actual_points) for r in pos_rows]
                )

        gw_ranking_list.append(
            GwRankingMetrics(
                gw=gw,
                predictions_count=n_gw_players,
                negative_actual_count=neg_count,
                upper_tail_actual_count=upper_count,
                ndcg_at_20=ndcg,
                top_20_capture_ratio=capture,
                top_20_overlap=overlap,
                spearman_within_gw=spearman_gw,
                spearman_by_position=spearman_pos_gw,
                top_20_details=top_20_det,
            )
        )

        ev_sum = sum(ev_vec)
        act_sum = sum(act_vec)
        signed_bias = ev_sum - act_sum
        ratio = (ev_sum / act_sum) if act_sum != 0.0 else 1.0

        mae = sum(abs(e - a) for e, a in zip(ev_vec, act_vec, strict=True)) / n_gw_players
        rmse = math.sqrt(
            sum((e - a) ** 2 for e, a in zip(ev_vec, act_vec, strict=True)) / n_gw_players
        )

        rng_gw = random.Random(seed + gw)
        dist_targets = [min(max(r.actual_points, 0), len(r.pmf) - 1) for r in gw_players]
        pmfs = [r.pmf for r in gw_players]

        logs = [log_score(p, t) for p, t in zip(pmfs, dist_targets, strict=True)]
        crpss = [crps(p, t) for p, t in zip(pmfs, dist_targets, strict=True)]
        pits = [randomised_pit(p, t, rng_gw) for p, t in zip(pmfs, dist_targets, strict=True)]

        mean_log = sum(logs) / n_gw_players
        mean_crps_val = sum(crpss) / n_gw_players
        in_pit = sum(1 for p in pits if pit_low <= p <= pit_high)
        pit_cov = in_pit / float(n_gw_players)

        gw_calib_list.append(
            GwCalibrationMetrics(
                gw=gw,
                ev_total=ev_sum,
                actual_total=act_sum,
                signed_bias=signed_bias,
                ev_actual_ratio=ratio,
                mae=mae,
                rmse=rmse,
                mean_log_score=mean_log,
                mean_crps=mean_crps_val,
                pit_80_coverage=pit_cov,
            )
        )

    # 3. Cumulative Horizon Ranking (Aggregated by Player Code across all GWs)
    player_cum_ev: dict[int, float] = defaultdict(float)
    player_cum_act: dict[int, float] = defaultdict(float)
    player_pos: dict[int, str] = {}
    player_team: dict[int, int] = {}

    for p_row in player_gw_rows:
        player_cum_ev[p_row.code] += p_row.ev
        player_cum_act[p_row.code] += float(p_row.actual_points)
        player_pos[p_row.code] = p_row.position
        player_team[p_row.code] = p_row.team_code

    all_codes = sorted(player_cum_ev.keys())
    cum_ev_vec = [player_cum_ev[c] for c in all_codes]
    cum_act_vec = [player_cum_act[c] for c in all_codes]
    cum_spearman = compute_spearman_rank_correlation(cum_ev_vec, cum_act_vec)

    cum_spearman_pos: dict[str, float] = {}
    by_pos_codes: dict[str, list[int]] = defaultdict(list)
    for c in all_codes:
        by_pos_codes[player_pos[c]].append(c)

    for pos, c_list in by_pos_codes.items():
        if len(c_list) >= 2:
            cum_spearman_pos[pos] = compute_spearman_rank_correlation(
                [player_cum_ev[c] for c in c_list], [player_cum_act[c] for c in c_list]
            )

    # NDCG@20 on Cumulative Player Rows
    cum_player_rows = [
        PlayerGwRow(
            season=season,
            gw=99,
            code=c,
            position=player_pos[c],
            team_code=player_team[c],
            fixture_count=1,
            ev=player_cum_ev[c],
            pmf=(1.0,),
            actual_points=int(player_cum_act[c]),
        )
        for c in all_codes
    ]
    cum_ndcg, cum_capture, cum_overlap = compute_ndcg_at_k(cum_player_rows, k=20)
    cum_top_20_details = _top_20_details(cum_player_rows, k=20)

    # 4. Fixture-Grain Distribution Proper Scoring
    tot_fixtures = len(fixture_rows)
    all_fix_ev = [r.ev for r in fixture_rows]
    all_fix_act = [float(r.actual_points) for r in fixture_rows]
    tot_ev = sum(all_fix_ev)
    tot_act = sum(all_fix_act)
    tot_bias = tot_ev - tot_act
    tot_ratio = (tot_ev / tot_act) if tot_act != 0.0 else 1.0

    tot_mae = sum(abs(e - a) for e, a in zip(all_fix_ev, all_fix_act, strict=True)) / tot_fixtures
    tot_rmse = math.sqrt(
        sum((e - a) ** 2 for e, a in zip(all_fix_ev, all_fix_act, strict=True)) / tot_fixtures
    )

    fix_dist_targets = [min(max(r.actual_points, 0), len(r.pmf) - 1) for r in fixture_rows]
    fix_pmfs = [r.pmf for r in fixture_rows]

    rng_tot = random.Random(seed)
    tot_mean_log = (
        sum(log_score(p, t) for p, t in zip(fix_pmfs, fix_dist_targets, strict=True)) / tot_fixtures
    )
    tot_mean_crps = (
        sum(crps(p, t) for p, t in zip(fix_pmfs, fix_dist_targets, strict=True)) / tot_fixtures
    )
    all_pits = [
        randomised_pit(p, t, rng_tot) for p, t in zip(fix_pmfs, fix_dist_targets, strict=True)
    ]
    tot_pit_cov = sum(1 for p in all_pits if pit_low <= p <= pit_high) / float(tot_fixtures)

    distinct_fixtures = len({(r.season, r.gw, r.fixture) for r in fixture_rows})

    return BacktestScoreReport(
        season=season,
        start_gw=start_gw,
        end_gw=end_gw,
        distinct_fixture_count=distinct_fixtures,
        total_player_fixture_rows=tot_fixtures,
        total_player_gw_rows=len(player_gw_rows),
        total_unique_players=len(all_codes),
        total_negative_actuals=sum(1 for r in fixture_rows if r.actual_points < 0),
        total_upper_tail_actuals=sum(1 for r in fixture_rows if r.actual_points > (len(r.pmf) - 1)),
        cumulative_ndcg_at_20=cum_ndcg,
        cumulative_top_20_capture_ratio=cum_capture,
        cumulative_top_20_overlap=cum_overlap,
        cumulative_spearman=cum_spearman,
        cumulative_spearman_by_position=cum_spearman_pos,
        ev_total=tot_ev,
        actual_total=tot_act,
        signed_bias=tot_bias,
        ev_actual_ratio=tot_ratio,
        mae=tot_mae,
        rmse=tot_rmse,
        mean_log_score=tot_mean_log,
        mean_crps=tot_mean_crps,
        mean_ranked_probability_score=tot_mean_crps,
        pit_80_coverage=tot_pit_cov,
        gw_metrics=tuple(gw_ranking_list),
        gw_calibration=tuple(gw_calib_list),
        cumulative_top_20_details=cum_top_20_details,
    )
