"""Synthetic current-default selector reproduction; no V3 candidate fits."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import duckdb
import pytest

from fpl.config import load_phase2_evaluation
from fpl.jobs.prospective_points_v1 import (
    last_team_code,
    prior_season_appearance_rate,
    season_boundary_minutes,
    trailing5_minute_bins,
)
from fpl.models.minutes_shrinkage import shrink_minute_bins
from fpl.models.price_starter_prior import apply_price_starter_prior
from fpl.types import Position
from fpl.validate.minutes_baselines import HistoryRow, MinuteBins, TargetRow, TeamCodeMap
from fpl.validate.prospective_incumbent_adapter import (
    FIXED_CODE_CAVEAT,
    HISTORICAL_CAVEAT,
    V3_NAME,
    DefaultMinutesInputs,
    NullablePriceEvidence,
    RegistryEvidence,
    eligible_trailing_history,
    reproduce_default_minutes,
)

AS_OF = datetime(2025, 8, 15, 17, tzinfo=UTC)
KNOWN = AS_OF - timedelta(hours=2)
RAW = (0.2, 0.1, 0.2, 0.5)
MISSING = NullablePriceEvidence(None, None, None)


def _inputs() -> DefaultMinutesInputs:
    return DefaultMinutesInputs(
        target=TargetRow("2025-26", 1, 1, AS_OF, 1001, Position.MID, 1, 2, True),
        as_of=AS_OF,
        raw_v3=RAW,
        raw_v3_as_of=AS_OF,
        raw_v3_model_name=V3_NAME,
        current_team_code=101,
        eligible_history_present=True,
        trailing5=None,
        prior_appearance=(None, 0),
        maximum_prior_event=AS_OF - timedelta(days=10),
        prior_source_identity="synthetic_fold_prior",
        registry=RegistryEvidence("archive_roster_proxy", "synthetic_target_proxy", None, False),
        price=MISSING,
        established_price=MISSING,
    )


def _known_price(value: int | None) -> NullablePriceEvidence:
    return NullablePriceEvidence(value, KNOWN, "synthetic_cutoff_bootstrap")


def _cold() -> DefaultMinutesInputs:
    return replace(
        _inputs(),
        eligible_history_present=False,
        registry=RegistryEvidence("deadline_known", "synthetic_full_registry", KNOWN, True),
        price=_known_price(50),
        established_price=_known_price(55),
    )


def test_sparse_established_path_preserves_fitted_v3_exactly() -> None:
    result = reproduce_default_minutes(_inputs())
    assert result.distribution is RAW
    assert result.selector_arithmetic_reproduced
    assert not result.historical_deadline_validity_established
    assert not result.price_dependency
    assert HISTORICAL_CAVEAT in result.caveats
    assert FIXED_CODE_CAVEAT in result.caveats
    assert (
        result.reproduction_scope == "minutes_selector_only_not_full_prospective_or_player_points"
    )


@pytest.mark.parametrize("n", [1, 2])
def test_less_than_three_rows_keeps_v3_not_trailing_shape(n: int) -> None:
    inputs = replace(_inputs(), trailing5=((0.1, 0.2, 0.3, 0.4), n))
    assert reproduce_default_minutes(inputs).distribution is RAW


@pytest.mark.parametrize("month", [1, 5, 8, 9, 10, 11, 12])
def test_current_season_boundary_function_is_reused_bit_exact(month: int) -> None:
    inputs = _inputs()
    kickoff = datetime(2026, month, 15, tzinfo=UTC)
    prior = (0.92, 38)
    inputs = replace(
        inputs, target=replace(inputs.target, kickoff_time=kickoff), prior_appearance=prior
    )
    expected = season_boundary_minutes(RAW, prior_rate=0.92, prior_n=38, target_month=month)
    assert reproduce_default_minutes(inputs).distribution == expected


def test_all_zero_trailing_uses_existing_out_of_side_profile_not_v3() -> None:
    absent_profile = (0.94, 0.02, 0.01, 0.03)
    shrunk = shrink_minute_bins(
        [5.0, 0.0, 0.0, 0.0],
        5,
        in_squad_prior=(0.2, 0.1, 0.2, 0.5),
        out_of_side_profile=absent_profile,
    )
    assert shrunk == absent_profile
    inputs = replace(_inputs(), trailing5=(absent_profile, 5))
    result = reproduce_default_minutes(inputs)
    assert result.distribution == absent_profile
    assert result.route == "current_club_filtered_shrunk_equal_weight_trailing5"
    assert result.distribution != RAW


@pytest.mark.parametrize("counts", [(0.0, 0.0, 0.0, 5.0), (2.0, 1.0, 1.0, 1.0)])
def test_equal_weight_shrinkage_then_boundary_order_matches_primitives(
    counts: tuple[float, ...],
) -> None:
    shrunk = shrink_minute_bins(
        counts, 5, in_squad_prior=(0.2, 0.1, 0.2, 0.5), out_of_side_profile=(0.9, 0.02, 0.03, 0.05)
    )
    dist = (shrunk[0], shrunk[1], shrunk[2], shrunk[3])
    inputs = replace(_inputs(), trailing5=(dist, 5), prior_appearance=(0.8, 38))
    expected = season_boundary_minutes(dist, prior_rate=0.8, prior_n=38, target_month=8)
    assert reproduce_default_minutes(inputs).distribution == expected


@pytest.mark.parametrize("maximum", [None, 45, 50, 55])
def test_cold_price_prior_matches_exact_primitive_and_strictly_dearer_rule(
    maximum: int | None,
) -> None:
    inputs = replace(_cold(), established_price=_known_price(maximum))
    behind = maximum is not None and maximum > 50
    expected = apply_price_starter_prior(
        RAW, price=50, position=Position.MID, behind_established_incumbent=behind
    )
    result = reproduce_default_minutes(inputs)
    assert result.distribution == expected
    assert result.behind_established_incumbent is behind
    assert result.price_dependency
    assert not result.historical_deadline_validity_established


def test_cold_stale_v3_shape_is_not_replaced_with_invented_position_prior() -> None:
    stale_v3_shape = (0.1, 0.5, 0.3, 0.1)
    inputs = replace(_cold(), raw_v3=stale_v3_shape)
    result = reproduce_default_minutes(inputs)
    assert result.distribution == apply_price_starter_prior(
        stale_v3_shape, price=50, position=Position.MID, behind_established_incumbent=True
    )
    assert result.distribution is not None
    assert result.distribution[1] / result.distribution[3] == pytest.approx(5.0)


def test_zero_playing_mass_uses_same_existing_price_shape_fallback() -> None:
    inputs = replace(_cold(), raw_v3=(1.0, 0.0, 0.0, 0.0))
    result = reproduce_default_minutes(inputs)
    assert result.distribution == apply_price_starter_prior(
        (1.0, 0.0, 0.0, 0.0), price=50, position=Position.MID, behind_established_incumbent=True
    )


@pytest.mark.parametrize("value", [None, 0])
def test_known_nullable_price_is_a_real_noop_not_a_missing_capture(value: int | None) -> None:
    inputs = replace(_cold(), price=_known_price(value), established_price=MISSING)
    result = reproduce_default_minutes(inputs)
    assert result.distribution is RAW
    assert not result.blockers


def test_unknown_historical_price_does_not_silently_become_api_null() -> None:
    unknown = replace(_cold(), price=MISSING)
    blocked = reproduce_default_minutes(unknown)
    assert blocked.distribution is None
    assert not blocked.selector_arithmetic_reproduced
    assert "cold_start_deadline_now_cost_unavailable" in blocked.blockers
    # A numeric archive/launch price with no captured knowledge time is still unknown.
    archive = replace(unknown, price=NullablePriceEvidence(50, None, "archive_fixture_value"))
    assert reproduce_default_minutes(archive).distribution is None


def test_unknown_or_incomplete_teammate_registry_blocks_price_dependent_cold_start() -> None:
    inputs = replace(_cold(), established_price=MISSING)
    assert (
        "cold_start_established_teammate_price_unproven"
        in reproduce_default_minutes(inputs).blockers
    )
    inputs = replace(
        _cold(), registry=RegistryEvidence("archive_roster_proxy", "proxy", None, False)
    )
    assert (
        "cold_start_complete_teammate_registry_unavailable"
        in reproduce_default_minutes(inputs).blockers
    )


def test_price_not_required_when_three_row_recent_override_erases_price_dependency() -> None:
    inputs = replace(_inputs(), eligible_history_present=False, trailing5=((0.1, 0.2, 0.3, 0.4), 3))
    result = reproduce_default_minutes(inputs)
    assert result.distribution == (0.1, 0.2, 0.3, 0.4)
    assert not result.price_dependency


def test_current_club_frontier_helper_reuses_exact_owner_rule() -> None:
    history = [
        HistoryRow(
            "2023-24", 1, 1, datetime(2023, 9, 1, tzinfo=UTC), 10, Position.MID, 1, 2, True, 90
        ),
        HistoryRow(
            "2023-24", 1, 1, datetime(2023, 9, 1, tzinfo=UTC), 20, Position.MID, 2, 1, False, 90
        ),
        HistoryRow(
            "2024-25", 1, 1, datetime(2024, 9, 1, tzinfo=UTC), 30, Position.MID, 1, 2, True, 0
        ),
    ]
    team_codes = TeamCodeMap.from_pairs(
        [("2023-24", 1, 101), ("2023-24", 2, 102), ("2024-25", 1, 101)]
    )
    result = eligible_trailing_history(
        history,
        current_club={10: 102, 20: 102, 30: 102},
        team_codes=team_codes,
        as_of=AS_OF,
        target_season="2025-26",
        target_gw=1,
    )
    assert [r.code for r in result] == [20, 30]
    assert result[1].minutes == 0  # latest-season former-club zero minutes stays eligible
    assert len(history) == 3  # raw V3 history is not modified by this selector-only helper


def test_future_or_target_gw_history_is_rejected_before_eligibility() -> None:
    row = HistoryRow("2025-26", 1, 1, AS_OF - timedelta(hours=1), 10, Position.MID, 1, 2, True, 90)
    with pytest.raises(ValueError, match="same-GW"):
        eligible_trailing_history(
            [row],
            current_club={10: 101},
            team_codes=TeamCodeMap.from_pairs([("2025-26", 1, 101)]),
            as_of=AS_OF,
            target_season="2025-26",
            target_gw=1,
        )


def test_existing_sql_helpers_reproduce_shrinkage_and_latest_season_exactly() -> None:
    con = duckdb.connect(":memory:")
    try:
        con.execute("CREATE TABLE mart_dim_team(season VARCHAR,team_id INTEGER,team_code INTEGER)")
        con.execute(
            "CREATE TABLE mart_fact_player_fixture("
            "season VARCHAR,gw INTEGER,fixture INTEGER,kickoff_time TIMESTAMPTZ,"
            "code INTEGER,position VARCHAR,team_id INTEGER,minutes INTEGER)"
        )
        con.execute("INSERT INTO mart_dim_team VALUES ('2024-25',1,101)")
        rows = [
            (
                "2024-25",
                i + 1,
                i + 1,
                datetime(2024, 9, 1, tzinfo=UTC) + timedelta(days=7 * i),
                1001,
                "MID",
                1,
                minutes,
            )
            for i, minutes in enumerate([90, 0, 90, 90, 90, 0, 90, 90, 0, 90])
        ]
        con.executemany("INSERT INTO mart_fact_player_fixture VALUES (?,?,?,?,?,?,?,?)", rows)
        bins = MinuteBins.from_config(load_phase2_evaluation())
        current = {1001: 101}
        recent = trailing5_minute_bins(con, AS_OF, bins, current_club=current)[1001]
        prior = prior_season_appearance_rate(con, AS_OF, current_club=current)[1001]
        with_history = 1001 in last_team_code(con, AS_OF, current_club=current)
        inputs = replace(
            _inputs(),
            trailing5=recent,
            prior_appearance=prior,
            eligible_history_present=with_history,
        )
        expected = season_boundary_minutes(
            recent[0], prior_rate=prior[0], prior_n=prior[1], target_month=8
        )
        assert reproduce_default_minutes(inputs).distribution == expected
    finally:
        con.close()


@pytest.mark.parametrize(
    "kind", ["history", "price", "registry", "v3", "target", "bins", "identity"]
)
def test_bad_time_or_distribution_evidence_fails_closed(kind: str) -> None:
    inputs = _cold()
    if kind == "history":
        inputs = replace(inputs, maximum_prior_event=AS_OF)
    elif kind == "price":
        inputs = replace(
            inputs, price=NullablePriceEvidence(50, AS_OF + timedelta(seconds=1), "future")
        )
    elif kind == "registry":
        inputs = replace(
            inputs, registry=replace(inputs.registry, known_at=AS_OF + timedelta(seconds=1))
        )
    elif kind == "v3":
        inputs = replace(inputs, raw_v3_as_of=AS_OF - timedelta(days=1))
    elif kind == "target":
        inputs = replace(
            inputs, target=replace(inputs.target, kickoff_time=AS_OF - timedelta(seconds=1))
        )
    elif kind == "bins":
        inputs = replace(inputs, raw_v3=(0.1, 0.1, 0.1, 0.1))
    else:
        inputs = replace(inputs, raw_v3_model_name="old_ev_adapter")
    with pytest.raises(ValueError, match=r"future|later-known|cutoff|sum to one|exact fitted"):
        reproduce_default_minutes(inputs)


def test_unresolved_history_or_club_is_a_blocker_not_an_invented_prior() -> None:
    inputs = replace(
        _inputs(),
        eligible_history_present=None,
        current_team_code=None,
        maximum_prior_event=None,
        prior_source_identity="",
    )
    result = reproduce_default_minutes(inputs)
    assert result.distribution is None
    assert len(result.blockers) == 3


def test_horizon_uses_target_month_but_frozen_prior_state() -> None:
    inputs = replace(_inputs(), prior_appearance=(0.9, 38))
    september = replace(
        inputs, target=replace(inputs.target, kickoff_time=datetime(2025, 9, 15, tzinfo=UTC))
    )
    december = replace(
        inputs, target=replace(inputs.target, kickoff_time=datetime(2025, 12, 15, tzinfo=UTC))
    )
    assert reproduce_default_minutes(september).distribution == season_boundary_minutes(
        RAW, prior_rate=0.9, prior_n=38, target_month=9
    )
    assert reproduce_default_minutes(december).distribution is RAW
