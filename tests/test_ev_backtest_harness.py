"""Offline unit tests for EV Backtest harness metrics and PMF convolution."""

from __future__ import annotations

import pytest

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

    # Actual ranks break the 10-10 tie by code ASC, NOT by EV: 103 then 105, then 101 on 6.
    # Were EV allowed into the oracle key it would still put 103 first here, which is exactly
    # why the tie must cross the top-k boundary to be diagnostic -- see the test below.
    assert details[0].actual_rank == 1
    assert details[2].actual_rank == 2
    assert details[1].actual_rank == 3


def _tie_across_rank_20_rows() -> list[PlayerGwRow]:
    """21 players whose actual-points tie straddles rank 20.

    Codes 1..19 are unambiguously the top 19 on actual points. Codes 20 and 21 both score 5, so
    exactly one of them holds the 20th oracle slot, and their EV order is deliberately inverted
    against their code order: code 21 has the higher EV and sits inside the predicted top 20,
    code 20 has the lower EV and sits outside it. Any tie policy that consults EV therefore
    awards the oracle slot to code 21 and reports a perfect overlap, while a code-only policy
    awards it to code 20 and reports 19/20.
    """
    rows = [
        PlayerGwRow("2025-26", 29, code, "MID", 1, 1, 100.0 - code, (1.0,), 50 - code)
        for code in range(1, 20)
    ]
    rows.append(PlayerGwRow("2025-26", 29, 20, "MID", 1, 1, 1.0, (1.0,), 5))
    rows.append(PlayerGwRow("2025-26", 29, 21, "MID", 1, 1, 9.0, (1.0,), 5))
    return rows


def test_top_20_overlap_equals_detail_in_both_fraction_under_an_actual_points_tie() -> None:
    """The aggregate overlap and the detail table must read one oracle, not two.

    Actual-point ties are ordinary at this grain, so a tie that crosses the rank-20 boundary is
    the normal case rather than a corner case. If `compute_ndcg_at_k` and `_top_20_details`
    resolve it differently, the headline `top_20_overlap` and the flags a reader checks it
    against disagree -- silently, and only on the rows that matter most.
    """
    rows = _tie_across_rank_20_rows()
    assert len(rows) == 21

    _ndcg, _capture, overlap = compute_ndcg_at_k(rows, k=20)
    details = _top_20_details(rows, k=20)
    assert len(details) == 20

    in_both_fraction = sum(1 for d in details if d.in_both_top_20) / len(details)
    assert overlap == in_both_fraction

    # And the specific tie is resolved by code, so the 20th oracle slot goes to code 20 -- the
    # player the model ranked OUTSIDE its top 20. Overlap is therefore 19/20, not a free 20/20.
    assert overlap == 0.95
    tied = {d.code: d for d in details if d.code in (20, 21)}
    assert 21 in tied
    assert tied[21].in_both_top_20 is False


def test_actual_rank_never_uses_predicted_ev_as_a_tiebreak() -> None:
    """EV must not enter the actual ordering: it would flatter the model being scored.

    Codes 20 and 21 have identical actual points. An EV-aware oracle hands the better actual
    rank to code 21 purely because the model liked it more; the contract is that the displayed
    actual rank depends on outcomes and player code alone.
    """
    rows = _tie_across_rank_20_rows()
    details = _top_20_details(rows, k=20)
    by_code = {d.code: d for d in details}

    # Code 21 is in the predicted top 20 (EV 9.0) and code 20 is not, so only 21 has a row.
    assert 21 in by_code
    assert 20 not in by_code
    # Ranked 21st of 21 on actuals: it loses the 5-5 tie to code 20 on the code tiebreak.
    assert by_code[21].actual_rank == 21

    # Flipping only the EVs must not move any actual rank.
    flipped = [
        PlayerGwRow(
            r.season,
            r.gw,
            r.code,
            r.position,
            r.team_code,
            r.fixture_count,
            {20: 9.0, 21: 1.0}.get(r.code, r.ev),
            r.pmf,
            r.actual_points,
        )
        for r in rows
    ]
    flipped_details = _top_20_details(flipped, k=20)
    flipped_by_code = {d.code: d for d in flipped_details}
    assert 20 in flipped_by_code
    assert flipped_by_code[20].actual_rank == 20
    assert flipped_by_code[20].in_both_top_20 is True


def test_score_backtest_rows_cumulative_and_fixture_grain() -> None:
    pmf1 = (0.5, 0.5) + (0.0,) * 33
    pmf2 = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0) + (0.0,) * 28
    pmf3 = (0.0, 0.5, 0.5) + (0.0,) * 32
    rows = [
        FixturePredictionRow("2025-26", 29, 1, 101, "MID", 1, 2, 0.5, pmf1, -2),
        FixturePredictionRow("2025-26", 29, 2, 102, "FWD", 2, 3, 6.0, pmf2, 6),
        FixturePredictionRow("2025-26", 30, 3, 101, "MID", 1, 4, 1.5, pmf3, 3),
    ]

    report = score_backtest_rows(rows, max_support=34, pit_band=(0.1, 0.9))
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


def test_max_support_is_consumed_not_assumed() -> None:
    """The PMF length check reads `max_support`, so a contract change cannot be ignored."""
    pmf = (0.5, 0.5) + (0.0,) * 33  # 35 bins, i.e. support 0..34
    rows = [FixturePredictionRow("2025-26", 29, 1, 101, "MID", 1, 2, 0.5, pmf, 1)]

    score_backtest_rows(rows, max_support=34)

    with pytest.raises(ValueError, match=r"PMF length 35 != 31"):
        score_backtest_rows(rows, max_support=30)


def test_pit_band_is_consumed_not_assumed() -> None:
    """A degenerate band must change PIT-80 coverage; a hardcoded 0.1/0.9 would not move."""
    pmf = tuple([1.0 / 35] * 35)
    rows = [
        FixturePredictionRow("2025-26", 29, fix, 100 + fix, "MID", 1, 2, 17.0, pmf, fix % 35)
        for fix in range(1, 21)
    ]

    wide = score_backtest_rows(rows, pit_band=(0.0, 1.0))
    narrow = score_backtest_rows(rows, pit_band=(0.49, 0.51))

    assert wide.pit_80_coverage == 1.0
    assert narrow.pit_80_coverage < wide.pit_80_coverage
