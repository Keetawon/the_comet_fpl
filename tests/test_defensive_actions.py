"""The source-neutral DC rebuild contract and its reconciliation check.

Offline and deterministic: the formula and the check are exercised on hand-built rows. One
archive-marked test reruns the rebuild over the real 2025-26 archive to prove the formula is
FPL's own definition, matching the runnable `fpl.jobs.validate_dc_overlap`.
"""

from __future__ import annotations

import duckdb
import pytest

from fpl.transform.defensive_actions import (
    DC_SCORING_POSITIONS,
    DcObservation,
    ExternalDefensiveActions,
    check_dc_reconstruction,
    combine_cbi,
    reconstruct_defensive_contribution,
)
from fpl.types import Position


def test_combine_cbi_sums_the_three_parts() -> None:
    assert combine_cbi(clearances=5, blocks=2, interceptions=3) == 10
    assert combine_cbi(clearances=0, blocks=0, interceptions=0) == 0


def test_def_uses_cbit_and_ignores_recoveries() -> None:
    """DEF -> tackles + CBI. A real 2025-26 DEF row: dc=23, tackles=1, cbi=22, recoveries=1."""
    assert reconstruct_defensive_contribution(Position.DEF, tackles=1, cbi=22, recoveries=1) == 23
    # recoveries must not enter the DEF total.
    assert reconstruct_defensive_contribution(Position.DEF, tackles=1, cbi=22, recoveries=99) == 23


def test_mid_and_fwd_use_cbitr_including_recoveries() -> None:
    """MID/FWD -> tackles + CBI + recoveries. Real 2025-26 MID row: dc=29, t=7, cbi=8, rec=14."""
    assert reconstruct_defensive_contribution(Position.MID, tackles=7, cbi=8, recoveries=14) == 29
    assert reconstruct_defensive_contribution(Position.FWD, tackles=7, cbi=8, recoveries=14) == 29
    # recoveries genuinely changes the total for these positions.
    assert reconstruct_defensive_contribution(Position.MID, tackles=7, cbi=8, recoveries=0) == 15


def test_gk_returns_cbit_but_is_not_a_scoring_position() -> None:
    """GK has no DC threshold, so the value is unused; it is defined as CBIT for completeness."""
    assert Position.GK not in DC_SCORING_POSITIONS
    assert reconstruct_defensive_contribution(Position.GK, tackles=2, cbi=3, recoveries=5) == 5


def test_all_zero_actions_rebuild_to_zero() -> None:
    for position in Position:
        assert reconstruct_defensive_contribution(position, tackles=0, cbi=0, recoveries=0) == 0


def test_external_record_derives_cbi_and_rebuilds_dc() -> None:
    """An external row keeps CBI parts separate; the property re-sums them as FPL stores them."""
    actions = ExternalDefensiveActions(
        season="2025-26",
        external_player_id="fbref-abc123",
        player_name="David Raya Martín",
        team_name="Arsenal",
        match_date="2025-08-16",
        tackles=3,
        interceptions=4,
        blocks=1,
        clearances=6,
        recoveries=8,
    )
    assert actions.cbi == 11  # 6 + 1 + 4
    assert actions.rebuilt_dc(Position.DEF) == 14  # 3 + 11
    assert actions.rebuilt_dc(Position.MID) == 22  # 3 + 11 + 8


def test_check_reconciles_when_every_scoring_row_matches() -> None:
    rows = [
        DcObservation(Position.DEF, tackles=1, cbi=22, recoveries=1, recorded_dc=23),
        DcObservation(Position.MID, tackles=7, cbi=8, recoveries=14, recorded_dc=29),
        DcObservation(Position.FWD, tackles=2, cbi=3, recoveries=5, recorded_dc=10),
        # A GK row that would NOT match either formula: it must be ignored, not counted.
        DcObservation(Position.GK, tackles=0, cbi=1, recoveries=9, recorded_dc=4),
    ]
    report = check_dc_reconstruction(rows)
    assert report.total_rows == 4
    assert report.scoring_rows == 3
    assert report.exact_matches == 3
    assert report.mismatches == 0
    assert report.reconciles is True
    assert report.agreement_rate == 1.0
    assert report.by_position[Position.DEF] == (1, 1)
    assert report.by_position[Position.MID] == (1, 1)
    assert report.by_position[Position.FWD] == (1, 1)
    assert Position.GK not in report.by_position


def test_check_flags_a_mismatch_with_error_and_example() -> None:
    rows = [
        DcObservation(Position.DEF, tackles=1, cbi=22, recoveries=1, recorded_dc=23),
        # Wrong recorded value: rebuild is 15, recorded says 18 -> abs error 3.
        DcObservation(Position.MID, tackles=7, cbi=8, recoveries=0, recorded_dc=18),
    ]
    report = check_dc_reconstruction(rows)
    assert report.scoring_rows == 2
    assert report.exact_matches == 1
    assert report.mismatches == 1
    assert report.reconciles is False
    assert report.agreement_rate == 0.5
    assert report.max_abs_error == 3
    assert report.mismatch_examples == ((Position.MID, 15, 18),)


def test_empty_input_reconciles_vacuously() -> None:
    report = check_dc_reconstruction([])
    assert report.scoring_rows == 0
    assert report.agreement_rate == 1.0
    assert report.reconciles is True


@pytest.mark.archive
def test_formula_reconciles_on_real_2025_26_archive(db: duckdb.DuckDBPyConnection) -> None:
    """The rebuild reproduces FPL's recorded DC on every 2025-26 scoring row (9733/13309/3278).

    This is the offline mirror of `fpl.jobs.validate_dc_overlap`; if the archive's DC ever
    stops matching CBIT/CBITR the contract fails here, not silently in a backfill.
    """
    rows = db.execute(
        """
        SELECT position, tackles, clearances_blocks_interceptions, recoveries,
               defensive_contribution
        FROM mart_fact_player_fixture
        WHERE season = '2025-26'
          AND tackles IS NOT NULL
          AND clearances_blocks_interceptions IS NOT NULL
          AND recoveries IS NOT NULL
          AND defensive_contribution IS NOT NULL
        """
    ).fetchall()
    observations = [
        DcObservation(
            position=Position(pos),
            tackles=int(t),
            cbi=int(cbi),
            recoveries=int(rec),
            recorded_dc=int(dc),
        )
        for pos, t, cbi, rec, dc in rows
    ]
    report = check_dc_reconstruction(observations)
    assert report.reconciles, report.mismatch_examples
    assert report.by_position[Position.DEF][0] == 9733
    assert report.by_position[Position.MID][0] == 13309
    assert report.by_position[Position.FWD][0] == 3278
    assert report.scoring_rows == 26320
