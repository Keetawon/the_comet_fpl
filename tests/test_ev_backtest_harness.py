"""Offline unit tests for EV Backtest harness metrics and PMF convolution."""

from __future__ import annotations

from fpl.validate.ev_backtest_harness import (
    FixturePredictionRow,
    PlayerGwRow,
    _top_20_details,
    aggregate_fixture_rows_to_player_gw,
    compute_ndcg_at_k,
    compute_spearman_rank_correlation,
    convolve_pmfs,
    score_backtest_rows,
)


def test_pmf_convolution_without_truncation() -> None:
    # 0..34 support PMFs (len 35)
    pmf1 = [0.0] * 35
    pmf1[2] = 0.6
    pmf1[3] = 0.4

    pmf2 = [0.0] * 35
    pmf2[1] = 0.5
    pmf2[4] = 0.5

    convolved = convolve_pmfs(pmf1, pmf2)
    # Support length should be 35 + 35 - 1 = 69
    assert len(convolved) == 69
    # Sum must equal 1.0 exactly
    assert abs(sum(convolved) - 1.0) < 1e-12
    # Non-zero mass points: 2+1=3, 2+4=6, 3+1=4, 3+4=7
    assert abs(convolved[3] - 0.3) < 1e-6
    assert abs(convolved[4] - 0.2) < 1e-6
    assert abs(convolved[6] - 0.3) < 1e-6
    assert abs(convolved[7] - 0.2) < 1e-6


def test_aggregate_fixture_rows_to_player_gw_dgw() -> None:
    pmf_a = (0.5, 0.5) + (0.0,) * 33  # support 0..34
    pmf_b = (0.4, 0.6) + (0.0,) * 33

    rows = [
        FixturePredictionRow("2025-26", 29, 101, 10, "MID", 1, 2, 2.5, pmf_a, 4),
        FixturePredictionRow("2025-26", 29, 102, 10, "MID", 1, 3, 3.5, pmf_b, 6),
    ]

    gw_rows = aggregate_fixture_rows_to_player_gw(rows)
    assert len(gw_rows) == 1
    gw_row = gw_rows[0]

    assert gw_row.code == 10
    assert gw_row.fixture_count == 2
    # Weekly EV is exact sum of fixture EVs (2.5 + 3.5 = 6.0)
    assert abs(gw_row.ev - 6.0) < 1e-6
    # Weekly actual points is exact sum of fixture actual points (4 + 6 = 10)
    assert gw_row.actual_points == 10
    # Convolved PMF support is 35 + 35 - 1 = 69
    assert len(gw_row.pmf) == 69
    assert abs(sum(gw_row.pmf) - 1.0) < 1e-12


def test_spearman_rank_correlation_hand_computable() -> None:
    assert abs(compute_spearman_rank_correlation([1.0, 2.0, 3.0], [10.0, 20.0, 30.0]) - 1.0) < 1e-6
    assert (
        abs(compute_spearman_rank_correlation([1.0, 2.0, 3.0], [30.0, 20.0, 10.0]) - (-1.0)) < 1e-6
    )


def test_ndcg_and_capture_ratio() -> None:
    rows = [
        PlayerGwRow("2025-26", 29, 1, "MID", 1, 1, 10.0, (1.0,), 10),
        PlayerGwRow("2025-26", 29, 2, "FWD", 2, 1, 8.0, (1.0,), 5),
        PlayerGwRow("2025-26", 29, 3, "DEF", 3, 1, 5.0, (1.0,), 2),
    ]
    ndcg, capture, overlap = compute_ndcg_at_k(rows, k=2)
    assert ndcg > 0.99
    assert capture > 0.99
    assert overlap == 1.0


def test_top_20_details_deterministic_tie_handling() -> None:
    rows = [
        PlayerGwRow("2025-26", 29, 105, "MID", 10, 1, 5.0, (1.0,), 10),
        PlayerGwRow("2025-26", 29, 101, "MID", 10, 1, 5.0, (1.0,), 6),
        PlayerGwRow("2025-26", 29, 103, "FWD", 20, 1, 8.0, (1.0,), 10),
    ]

    details = _top_20_details(rows, k=20)
    assert len(details) == 3

    # Rank 1: code 103 (EV 8.0)
    assert details[0].code == 103
    assert details[0].predicted_rank == 1

    # Rank 2: code 101 (EV 5.0, code 101 < 105 tie-breaker)
    assert details[1].code == 101
    assert details[1].predicted_rank == 2

    # Rank 3: code 105 (EV 5.0)
    assert details[2].code == 105
    assert details[2].predicted_rank == 3

    # Actual rank: code 103 (actual 10, EV 8.0), code 105 (actual 10, EV 5.0), code 101 (actual 6)
    assert details[0].actual_rank == 1
    assert details[2].actual_rank == 2
    assert details[1].actual_rank == 3


def test_score_backtest_rows_cumulative_and_fixture_grain() -> None:
    pmf1 = (0.5, 0.5) + (0.0,) * 33
    pmf2 = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0) + (0.0,) * 28
    pmf3 = (0.0, 0.5, 0.5) + (0.0,) * 32
    rows = [
        FixturePredictionRow("2025-26", 29, 1, 101, "MID", 1, 2, 0.5, pmf1, -2),
        FixturePredictionRow("2025-26", 29, 2, 102, "FWD", 2, 3, 6.0, pmf2, 6),
        FixturePredictionRow("2025-26", 30, 3, 101, "MID", 1, 4, 1.5, pmf3, 3),
    ]

    report = score_backtest_rows(rows)
    assert report.season == "2025-26"
    assert report.start_gw == 29
    assert report.end_gw == 30
    assert report.distinct_fixture_count == 3
    assert report.total_player_fixture_rows == 3
    assert report.total_player_gw_rows == 3
    assert report.total_unique_players == 2
    assert report.total_negative_actuals == 1
    # Raw actual total preserves negative points (-2 + 6 + 3 = 7)
    assert report.actual_total == 7.0
    assert report.ev_total == 8.0
    assert report.cumulative_spearman > 0.0
    assert report.mean_ranked_probability_score == report.mean_crps
    assert len(report.cumulative_top_20_details) == 2
