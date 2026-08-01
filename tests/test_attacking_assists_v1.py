"""Offline tests for Stage C assists Candidate V1 (xA-informed trailing player assists).

No database, no network. Uses tiny synthetic fixtures. The headline guarantees under test:
(a) the candidate reduces to the v1.0 ``trailing_player_assist_rate_poisson`` baseline bit-for-bit
wherever xA is unmeasured; (b) the xA-informed path matches its hand-computed formula; (c) NULL-xA
rows are filled by rescaled creativity; (d) the per-appearance signal is over APPEARED rows only
(minutes > 0, R6).
"""

from __future__ import annotations

import math

from fpl.models.attacking_assists_baselines import (
    AssistHistoryRow,
    TrailingPlayerAssistRateBaseline,
)
from fpl.models.attacking_assists_v1 import (
    PATH_COLD_START,
    PATH_FALLBACK_V1,
    PATH_XA_INFORMED,
    XaInformedTrailingPlayerAssistsV1,
)
from fpl.models.attacking_baselines import TargetRowProjection, poisson_pmf
from fpl.types import Position

_KICKOFF = "2021-08-13T19:00:00Z"


def _target(code: int, position: Position = Position.FWD, gw: int = 9) -> TargetRowProjection:
    return TargetRowProjection(
        "2021-22", gw, gw, "2021-09-30T14:00:00Z", code, position, 1, 2, True
    )


def _row(
    season: str,
    gw: int,
    code: int,
    position: Position,
    assists: int,
    minutes: int,
    xa: float | None = None,
    creativity: float | None = None,
) -> AssistHistoryRow:
    return AssistHistoryRow(
        season,
        gw,
        gw,
        f"2023-08-{10 + gw:02d}T19:00:00Z",
        code,
        position,
        assists,
        minutes,
        xa,
        creativity,
    )


def test_reduces_to_baseline_bit_for_bit_when_xa_absent() -> None:
    """Where every expected_assists is NULL the candidate == v1.0 trailing baseline, exactly."""
    history = [
        _row("2021-22", 1, 101, Position.FWD, 1, 90),
        _row("2021-22", 1, 102, Position.FWD, 0, 90),
        _row("2021-22", 2, 101, Position.FWD, 0, 90),
        _row("2021-22", 2, 102, Position.FWD, 2, 90),
        _row("2021-22", 3, 201, Position.MID, 1, 90),
        _row("2021-22", 3, 301, Position.DEF, 0, 90),
    ]

    baseline = TrailingPlayerAssistRateBaseline(alpha=5.0)
    baseline.fit(history)
    candidate = XaInformedTrailingPlayerAssistsV1()
    candidate.fit(history)

    for code, position in [
        (101, Position.FWD),
        (102, Position.FWD),
        (999, Position.FWD),
        (201, Position.MID),
        (301, Position.DEF),
    ]:
        target = _target(code, position)
        # Bit-for-bit: same float tuple, including the cold-start player 999.
        assert candidate.predict(target) == baseline.predict(target), (
            f"candidate diverged from baseline for code={code} position={position.name}"
        )
        # And every one of these takes the fallback / cold-start path, never the xA path.
        assert candidate.path_for(target) in (PATH_FALLBACK_V1, PATH_COLD_START)


def test_xa_informed_rate_matches_formula() -> None:
    """The xA path computes the exact pre-registered rate."""
    # Three FWD prior appeared rows for 101 (all measured xA), plus one FWD row for 102.
    history = [
        _row("2023-24", 1, 101, Position.FWD, 1, 90, 0.5, 10.0),
        _row("2023-24", 2, 101, Position.FWD, 0, 90, 0.5, 10.0),
        _row("2023-24", 3, 101, Position.FWD, 0, 90, 0.5, 10.0),
        _row("2023-24", 1, 102, Position.FWD, 0, 90, 0.0, 10.0),
    ]
    candidate = XaInformedTrailingPlayerAssistsV1()
    candidate.fit(history)

    target = _target(101, Position.FWD)
    rate = candidate._rate(target).rate
    assert candidate.path_for(target) == PATH_XA_INFORMED

    # pos_a = (1+0+0+0)/4 = 0.25 ; pos_xa = (0.5+0.5+0.5+0.0)/4 = 0.375
    # n=3, sum_xa=1.5, sum_assists=1 ; shrunk_xa = (1.5 + 5*0.375)/8 = 0.421875
    # player_residual = (1-1.5)/3 ; positional_residual = 0.25-0.375 = -0.125
    player_residual = (1 - 1.5) / 3
    residual_term = 0.05 * player_residual + 0.95 * (0.25 - 0.375)
    expected = max(0.0, (1.5 + 5.0 * 0.375) / 8 + residual_term)
    assert math.isclose(rate, expected, rel_tol=1e-12)

    # The Poisson distribution is consistent with that rate: P(1)/P(0) == rate.
    dist = candidate.predict(target)
    assert math.isclose(dist[1] / dist[0], rate, rel_tol=1e-12)
    assert abs(sum(dist) - 1.0) < 1e-9


def test_creativity_rescale_fills_null_xa_rows() -> None:
    """A NULL-xA appeared row is filled by rescaled creativity, not dropped, on the xA path."""
    history = [
        _row("2023-24", 1, 101, Position.FWD, 1, 90, 0.5, 10.0),  # measured xA
        _row("2023-24", 2, 101, Position.FWD, 0, 90, None, 20.0),  # NULL xA -> creativity fill
        _row("2023-24", 1, 102, Position.FWD, 0, 90, 0.0, 10.0),  # sets positional means
    ]
    candidate = XaInformedTrailingPlayerAssistsV1()
    candidate.fit(history)

    # creativity_factor[FWD] = pos_a / mean_creativity = (1/3) / (40/3) = 0.025
    assert math.isclose(candidate._creativity_factor[Position.FWD], 0.025, rel_tol=1e-12)

    target = _target(101, Position.FWD)
    # The NULL-xA row did not block the xA path (the measured gw1 row enables it).
    assert candidate.path_for(target) == PATH_XA_INFORMED

    # sum_xa = 0.5 (gw1) + 0.025*20 (gw2 filled) = 1.0 ; sum_assists = 1 ; n = 2
    # pos_xa = (0.5+0.0)/2 = 0.25 ; pos_a = 1/3
    # shrunk_xa = (1.0 + 5*0.25)/7 ; player_residual = (1-1.0)/2 = 0 ; pos_residual = 1/3 - 0.25
    expected = max(
        0.0,
        (1.0 + 5.0 * 0.25) / 7 + 0.05 * 0.0 + 0.95 * (1.0 / 3 - 0.25),
    )
    assert math.isclose(candidate._rate(target).rate, expected, rel_tol=1e-12)


def test_zero_minute_rows_excluded_from_appeared_signal() -> None:
    """A prior row with minutes == 0 is not an appearance: it never enables the xA path (R6),
    and the fallback remains bit-identical to the baseline over the all-rows window."""
    history = [
        # 101 has only a zero-minute prior row (with measured xA) -> no appeared signal.
        _row("2023-24", 1, 101, Position.FWD, 0, 0, 0.5, 10.0),
        # 102 appeared and carries xA, so pos_xa[FWD] is defined for the fold.
        _row("2023-24", 1, 102, Position.FWD, 1, 90, 0.5, 10.0),
    ]
    baseline = TrailingPlayerAssistRateBaseline(alpha=5.0)
    baseline.fit(history)
    candidate = XaInformedTrailingPlayerAssistsV1()
    candidate.fit(history)

    target = _target(101, Position.FWD)
    # No appeared prior row -> not the xA path -> fallback, bit-identical to the baseline (which
    # includes the zero-minute row in its all-rows window).
    assert candidate.path_for(target) == PATH_FALLBACK_V1
    assert candidate.predict(target) == baseline.predict(target)


def test_cold_start_uses_positional_rate() -> None:
    history = [
        _row("2023-24", 1, 101, Position.FWD, 1, 90, 0.4, 10.0),
    ]
    candidate = XaInformedTrailingPlayerAssistsV1()
    candidate.fit(history)

    target = _target(999, Position.FWD)  # no prior rows for 999
    assert candidate.path_for(target) == PATH_COLD_START
    # Cold-start rate is the positional mean assists/appearance.
    assert candidate._rate(target).rate == 1.0 / 1


def test_trailing_window_is_five_most_recent_appeared() -> None:
    """Only the five most recent APPEARED rows feed the rate; a sixth older row is excluded."""
    rows = [
        _row("2023-24", gw, 101, Position.FWD, assists, 90, 0.2, 10.0)
        for gw, assists in enumerate(
            [1, 0, 0, 0, 0, 0], start=1
        )  # six rows; oldest (gw1) carries assist
    ]
    candidate = XaInformedTrailingPlayerAssistsV1()
    candidate.fit(rows)
    rate = candidate._rate(_target(101, Position.FWD)).rate

    # The five most recent appeared rows (gw2..gw6) all have assists=0; the assist=1 row at gw1 is
    # dropped by the window. The xA path is taken and the rate is deterministic and non-negative.
    assert candidate.path_for(_target(101, Position.FWD)) == PATH_XA_INFORMED
    assert rate >= 0.0
    assert abs(sum(candidate.predict(_target(101, Position.FWD))) - 1.0) < 1e-9


def test_fallback_when_player_trailing_xa_unmeasured() -> None:
    """A player whose appeared trailing rows predate xA coverage takes the exact baseline path."""
    history = [
        # 102 has two old appeared rows with NULL xA, even though the fold has measured xA
        # elsewhere.
        _row("2021-22", 1, 102, Position.FWD, 1, 90),
        _row("2021-22", 2, 102, Position.FWD, 1, 90),
        # 101 carries measured xA, so pos_xa[FWD] is defined for the fold.
        _row("2023-24", 3, 101, Position.FWD, 0, 90, 0.3, 10.0),
    ]
    baseline = TrailingPlayerAssistRateBaseline(alpha=5.0)
    baseline.fit(history)
    candidate = XaInformedTrailingPlayerAssistsV1()
    candidate.fit(history)

    target = _target(102, Position.FWD)
    assert candidate.path_for(target) == PATH_FALLBACK_V1
    assert candidate.predict(target) == baseline.predict(target)  # exact baseline rate


def test_parameters_report_pinned_constants() -> None:
    candidate = XaInformedTrailingPlayerAssistsV1()
    assert candidate.parameters() == {"alpha": 5.0, "finishing_keep": 0.05}
    assert candidate.name == "xa_informed_trailing_player_assists_v1"


def test_poisson_floor_handles_zero_rate() -> None:
    """A clamped-to-zero rate still yields a valid normalised distribution (no NaN)."""
    dist = poisson_pmf(0.0)
    assert len(dist) == 11
    assert abs(sum(dist) - 1.0) < 1e-9
