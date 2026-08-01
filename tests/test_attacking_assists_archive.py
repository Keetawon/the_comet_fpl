"""Archive-backed assertion of the Stage C assists label/signal coverage.

Marked ``archive``: requires the built database (``python -m fpl.jobs.build_db``); skipped
otherwise. The coverage figures below are the authoritative measured archive coverage stated in
the Stage C assists contract design -- this test ASSERTS them, it does not re-derive them.
"""

from __future__ import annotations

import pytest

from fpl.config import load_phase3_stage_c_assists_evaluation

pytestmark = pytest.mark.archive


def test_assists_label_count_distribution_matches_authoritative_coverage(db) -> None:  # type: ignore[no-untyped-def]
    """assists (the FPL label) is 100% measured every season; the count distribution is fixed."""
    rows = db.execute(
        """
        SELECT assists, COUNT(*) AS n
        FROM mart_fact_player_fixture
        WHERE minutes IS NOT NULL
        GROUP BY assists
        ORDER BY assists
        """
    ).fetchall()
    counts = {int(a): int(n) for a, n in rows}
    # Authoritative measured distribution over minutes-not-null rows (max 4 assists).
    assert counts == {0: 134228, 1: 4139, 2: 314, 3: 24, 4: 2}


def test_expected_assists_coverage_matches_xg_profile(db) -> None:  # type: ignore[no-untyped-def]
    """expected_assists (xA) has the SAME measured-coverage profile as expected_goals."""
    rows = db.execute(
        """
        SELECT season,
               SUM(CASE WHEN expected_assists IS NOT NULL THEN 1 ELSE 0 END) AS measured,
               COUNT(*) AS n
        FROM mart_fact_player_fixture
        WHERE minutes IS NOT NULL
        GROUP BY season
        ORDER BY season
        """
    ).fetchall()
    coverage = {str(s): int(m) / int(n) for s, m, n in rows}
    # 2021-22 has no xA at all.
    assert coverage["2021-22"] == 0.0
    # 2022-23 is partial (xA measured only from GW16 onward).
    assert 0.0 < coverage["2022-23"] < 1.0
    # 2023-24 onward is 100%.
    assert coverage["2023-24"] == 1.0
    assert coverage["2024-25"] == 1.0
    assert coverage["2025-26"] == 1.0


def test_creativity_is_fully_measured_every_season(db) -> None:  # type: ignore[no-untyped-def]
    """creativity (the FPL-native creative signal) is 100% measured every season."""
    rows = db.execute(
        """
        SELECT season,
               SUM(CASE WHEN creativity IS NOT NULL THEN 1 ELSE 0 END) AS measured,
               COUNT(*) AS n
        FROM mart_fact_player_fixture
        WHERE minutes IS NOT NULL
        GROUP BY season
        ORDER BY season
        """
    ).fetchall()
    for season, measured, n in rows:
        assert int(measured) == int(n), f"creativity not 100% in {season}"


def test_assists_xa_covered_seasons_match_contract(db) -> None:  # type: ignore[no-untyped-def]
    """The contract's xa_covered_seasons are exactly the fully-xA-covered seasons (2023-24+)."""
    contract = load_phase3_stage_c_assists_evaluation()
    assert contract.xa_signal_policy.xa_covered_seasons == ("2023-24", "2024-25", "2025-26")
