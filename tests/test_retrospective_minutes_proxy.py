"""Synthetic retrospective price amendment; no fitting or real model scoring."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from fpl.jobs.prospective_points_v1 import season_boundary_minutes
from fpl.models.price_starter_prior import apply_price_starter_prior
from fpl.types import Position
from fpl.validate.minutes_baselines import TargetRow
from fpl.validate.prospective_incumbent_adapter import (
    V3_NAME,
    DefaultMinutesInputs,
    NullablePriceEvidence,
    RegistryEvidence,
    reproduce_default_minutes,
)
from fpl.validate.retrospective_minutes_proxy import (
    EVIDENCE_CLASS,
    NAME,
    PROXY_CAVEAT,
    ArchiveFixturePrice,
    HistoricalPriceRoster,
    HistoricalRosterMember,
    reproduce_with_archive_cold_price_proxy,
)

AS_OF = datetime(2025, 8, 15, 17, tzinfo=UTC)
PRIOR = AS_OF - timedelta(days=10)
CAPTURE = datetime(2026, 9, 5, tzinfo=UTC)
RAW = (0.2, 0.1, 0.2, 0.5)
MISSING = NullablePriceEvidence(None, None, None)


def _inputs() -> DefaultMinutesInputs:
    return DefaultMinutesInputs(
        TargetRow("2025-26", 1, 1, AS_OF, 1001, Position.MID, 1, 2, True),
        AS_OF,
        RAW,
        AS_OF,
        V3_NAME,
        101,
        False,
        None,
        (None, 0),
        PRIOR,
        "synthetic-prior",
        RegistryEvidence("archive_roster_proxy", "synthetic-roster", None, False),
        MISSING,
        MISSING,
    )


def _roster() -> HistoricalPriceRoster:
    return HistoricalPriceRoster(
        "2025-26",
        1,
        AS_OF,
        "synthetic-complete-archive-roster",
        "a" * 64,
        True,
        (
            HistoricalRosterMember(1001, 101, Position.MID, False, (None, 0), None),
            HistoricalRosterMember(1002, 101, Position.MID, True, (0.8, 20), PRIOR),
        ),
        (
            ArchiveFixturePrice(
                "2025-26", 1, 1, 1001, 101, Position.MID, AS_OF, 50, "own-row", CAPTURE
            ),
            ArchiveFixturePrice(
                "2025-26", 1, 1, 1002, 101, Position.MID, AS_OF, 55, "mate-row", CAPTURE
            ),
        ),
    )


def _must_not_read_prices() -> HistoricalPriceRoster:
    raise AssertionError("established or already resolved path accessed archive prices")


@pytest.mark.parametrize("trailing", [None, ((0.1, 0.2, 0.3, 0.4), 2), ((0.1, 0.2, 0.3, 0.4), 5)])
def test_established_own_prediction_never_reads_archive_prices(trailing: object) -> None:
    inputs = replace(_inputs(), eligible_history_present=True, trailing5=trailing)  # type: ignore[arg-type]
    result = reproduce_with_archive_cold_price_proxy(inputs, load_archive=_must_not_read_prices)
    assert result.selector == reproduce_default_minutes(inputs)
    assert not result.proxy_dependent
    assert result.archive_price_lineage == ()


def test_recent_override_that_removes_price_dependency_never_reads_prices() -> None:
    inputs = replace(_inputs(), trailing5=((0.1, 0.2, 0.3, 0.4), 3))
    result = reproduce_with_archive_cold_price_proxy(inputs, load_archive=_must_not_read_prices)
    assert result.selector.distribution == (0.1, 0.2, 0.3, 0.4)
    assert not result.proxy_dependent


def test_exact_current_price_and_boundary_arithmetic_with_retained_proxy_taint() -> None:
    inputs = _inputs()
    result = reproduce_with_archive_cold_price_proxy(inputs, load_archive=_roster)
    expected = apply_price_starter_prior(
        RAW, price=50, position=Position.MID, behind_established_incumbent=True
    )
    expected = season_boundary_minutes(expected, prior_rate=None, prior_n=0, target_month=8)
    assert result.selector.distribution == expected
    assert result.selector.behind_established_incumbent
    assert result.selector.selector_arithmetic_reproduced
    assert not result.selector.historical_deadline_validity_established
    assert result.proxy_dependent and result.cold_start
    assert result.comparator == NAME
    assert result.evidence_class == EVIDENCE_CLASS
    assert not result.promotion_permitted
    assert PROXY_CAVEAT in result.selector.caveats
    assert [use.code for use in result.archive_price_lineage] == [1001, 1002]
    assert result.archive_price_lineage[1].role == "established_cold_cap_witness"
    assert all(
        r.source_known_at == CAPTURE for use in result.archive_price_lineage for r in use.rows
    )
    assert inputs.price is MISSING  # no invented known_at or mutation of strict inputs
    assert reproduce_default_minutes(inputs).distribution is None


@pytest.mark.parametrize("price", [0, 45, 50, 55, 60])
def test_strictly_dearer_cap_and_explicit_zero_preserve_existing_math(price: int) -> None:
    roster = _roster()
    roster = replace(roster, prices=(replace(roster.prices[0], value=price), roster.prices[1]))
    result = reproduce_with_archive_cold_price_proxy(_inputs(), load_archive=lambda: roster)
    assert result.selector.distribution == apply_price_starter_prior(
        RAW, price=price, position=Position.MID, behind_established_incumbent=price < 55
    )
    assert result.proxy_dependent
    if price == 0:
        assert [use.code for use in result.archive_price_lineage] == [1001]
        assert result.selector.distribution is RAW


@pytest.mark.parametrize("field", ["own", "witness"])
def test_missing_archive_price_does_not_become_known_api_null(field: str) -> None:
    roster = _roster()
    index = 0 if field == "own" else 1
    prices = list(roster.prices)
    prices[index] = replace(prices[index], value=None)
    roster = replace(roster, prices=tuple(prices))
    result = reproduce_with_archive_cold_price_proxy(_inputs(), load_archive=lambda: roster)
    assert result.selector.distribution is None
    assert "archive_price_unmeasured" in result.selector.blockers[0]


def test_known_deadline_prices_precede_archive_and_do_not_call_loader() -> None:
    inputs = replace(
        _inputs(),
        registry=RegistryEvidence("deadline_known", "real-capture", PRIOR, True),
        price=NullablePriceEvidence(65, PRIOR, "real-own"),
        established_price=NullablePriceEvidence(55, PRIOR, "real-max"),
    )
    result = reproduce_with_archive_cold_price_proxy(inputs, load_archive=_must_not_read_prices)
    assert result.selector == reproduce_default_minutes(inputs)
    assert not result.proxy_dependent


def test_only_missing_witness_price_is_proxied_when_own_price_is_deadline_known() -> None:
    inputs = replace(_inputs(), price=NullablePriceEvidence(60, PRIOR, "known-own"))
    result = reproduce_with_archive_cold_price_proxy(inputs, load_archive=_roster)
    assert [use.code for use in result.archive_price_lineage] == [1002]
    assert not result.selector.behind_established_incumbent
    assert result.selector.distribution == apply_price_starter_prior(
        RAW, price=60, position=Position.MID
    )


def test_unqualified_or_other_club_position_players_prices_are_not_consulted() -> None:
    roster = _roster()
    extras = (
        HistoricalRosterMember(1003, 102, Position.MID, True, (0.9, 38), PRIOR),
        HistoricalRosterMember(1004, 101, Position.DEF, True, (0.9, 38), PRIOR),
        HistoricalRosterMember(1005, 101, Position.MID, True, (0.69, 38), PRIOR),
        HistoricalRosterMember(1006, 101, Position.MID, True, (1.0, 9), PRIOR),
    )
    roster = replace(roster, members=(*roster.members, *extras))
    result = reproduce_with_archive_cold_price_proxy(_inputs(), load_archive=lambda: roster)
    assert not result.selector.blockers
    assert [use.code for use in result.archive_price_lineage] == [1001, 1002]


def test_known_nullable_witness_price_is_not_archive_null() -> None:
    roster = _roster()
    mate = replace(roster.members[1], known_price=NullablePriceEvidence(None, PRIOR, "known-null"))
    roster = replace(roster, members=(roster.members[0], mate))
    result = reproduce_with_archive_cold_price_proxy(_inputs(), load_archive=lambda: roster)
    assert not result.selector.behind_established_incumbent
    assert [use.code for use in result.archive_price_lineage] == [1001]


def test_every_consulted_proxy_witness_is_retained_even_when_not_the_maximum() -> None:
    roster = _roster()
    lesser = replace(roster.members[1], code=1003)
    price = replace(roster.prices[1], code=1003, value=45, source_identity="lesser-witness")
    roster = replace(roster, members=(*roster.members, lesser), prices=(*roster.prices, price))
    result = reproduce_with_archive_cold_price_proxy(_inputs(), load_archive=lambda: roster)
    assert result.selector.behind_established_incumbent
    assert [use.code for use in result.archive_price_lineage] == [1001, 1002, 1003]
    # The established member's OWN selector ignores this price entirely.
    established = replace(_inputs(), eligible_history_present=True)
    assert not reproduce_with_archive_cold_price_proxy(
        established, load_archive=_must_not_read_prices
    ).proxy_dependent


@pytest.mark.parametrize("shape", [(0.1, 0.5, 0.3, 0.1), (1.0, 0.0, 0.0, 0.0)])
def test_stale_or_degenerate_v3_shape_is_preserved_by_exact_existing_price_rule(
    shape: tuple[float, float, float, float],
) -> None:
    inputs = replace(_inputs(), raw_v3=shape)
    result = reproduce_with_archive_cold_price_proxy(inputs, load_archive=_roster)
    assert result.selector.distribution == apply_price_starter_prior(
        shape, price=50, position=Position.MID, behind_established_incumbent=True
    )


def test_target_fixture_kickoff_mismatch_cannot_hide_inside_valid_gameweek() -> None:
    roster = _roster()
    roster = replace(
        roster,
        prices=(replace(roster.prices[0], kickoff=AS_OF + timedelta(hours=1)), roster.prices[1]),
    )
    result = reproduce_with_archive_cold_price_proxy(_inputs(), load_archive=lambda: roster)
    assert result.selector.blockers == ("archive_target_fixture_kickoff_mismatch",)


@pytest.mark.parametrize("price", [-1, True, 50.5])
def test_invalid_measured_archive_price_fails_closed(price: object) -> None:
    roster = _roster()
    roster = replace(roster, prices=(replace(roster.prices[0], value=price), roster.prices[1]))
    with pytest.raises(ValueError, match="nonnegative integer"):
        reproduce_with_archive_cold_price_proxy(_inputs(), load_archive=lambda: roster)


def test_duplicate_archive_fixture_price_is_not_a_provider_revision_policy() -> None:
    roster = _roster()
    roster = replace(roster, prices=(*roster.prices, roster.prices[0]))
    with pytest.raises(ValueError, match="duplicate"):
        reproduce_with_archive_cold_price_proxy(_inputs(), load_archive=lambda: roster)


def test_consistent_dgw_legs_retain_all_rows_and_give_identical_price_selection() -> None:
    roster = _roster()
    extra = replace(
        roster.prices[0], fixture=2, kickoff=AS_OF + timedelta(days=4), source_identity="leg2"
    )
    roster = replace(roster, prices=(*roster.prices, extra))
    first = reproduce_with_archive_cold_price_proxy(_inputs(), load_archive=lambda: roster)
    second_input = replace(
        _inputs(), target=replace(_inputs().target, fixture=2, kickoff_time=extra.kickoff)
    )
    second = reproduce_with_archive_cold_price_proxy(second_input, load_archive=lambda: roster)
    assert first.selector.distribution == second.selector.distribution
    assert first.archive_price_lineage == second.archive_price_lineage
    assert len(first.archive_price_lineage[0].rows) == 2


@pytest.mark.parametrize("change", ["price", "club", "position", "season", "gw", "missing"])
@pytest.mark.parametrize("which", [0, 1])
def test_ambiguous_required_dgw_legs_fail_closed(change: str, which: int) -> None:
    roster = _roster()
    extra = replace(roster.prices[which], fixture=2, kickoff=AS_OF + timedelta(days=4))
    changes = {
        "price": {"value": 99},
        "club": {"team_code": 102},
        "position": {"position": Position.DEF},
        "season": {"season": "2024-25"},
        "gw": {"gw": 2},
        "missing": {"value": None},
    }
    extra = replace(extra, **changes[change])  # type: ignore[arg-type]
    roster = replace(roster, prices=(*roster.prices, extra))
    result = reproduce_with_archive_cold_price_proxy(_inputs(), load_archive=lambda: roster)
    assert result.selector.distribution is None
    assert result.selector.blockers


@pytest.mark.parametrize(
    "change", ["incomplete", "duplicate_member", "missing_own", "missing_fixture"]
)
def test_roster_or_missing_target_evidence_blocks(change: str) -> None:
    roster = _roster()
    if change == "incomplete":
        roster = replace(roster, complete_for_declared_archive_population=False)
    elif change == "duplicate_member":
        roster = replace(roster, members=(*roster.members, roster.members[0]))
    elif change == "missing_own":
        roster = replace(roster, members=(roster.members[1],))
    else:
        roster = replace(roster, prices=(replace(roster.prices[0], fixture=2), roster.prices[1]))
    assert (
        reproduce_with_archive_cold_price_proxy(
            _inputs(), load_archive=lambda: roster
        ).selector.distribution
        is None
    )


def test_unrelated_prior_blocker_does_not_unlock_archive_access() -> None:
    inputs = replace(_inputs(), current_team_code=None)
    result = reproduce_with_archive_cold_price_proxy(inputs, load_archive=_must_not_read_prices)
    assert result.selector.distribution is None
    assert not result.proxy_dependent


def test_same_gw_witness_appearance_is_rejected() -> None:
    roster = _roster()
    roster = replace(
        roster, members=(roster.members[0], replace(roster.members[1], maximum_prior_event=AS_OF))
    )
    with pytest.raises(ValueError, match="target-GW"):
        reproduce_with_archive_cold_price_proxy(_inputs(), load_archive=lambda: roster)


def test_future_prospective_season_has_no_boolean_escape_hatch() -> None:
    inputs = replace(_inputs(), target=replace(_inputs().target, season="2026-27"))
    with pytest.raises(ValueError, match="three historical seasons"):
        reproduce_with_archive_cold_price_proxy(inputs, load_archive=_must_not_read_prices)


def test_control_candidate_receive_identical_deterministic_proxy_input() -> None:
    first = reproduce_with_archive_cold_price_proxy(_inputs(), load_archive=_roster)
    assert first == reproduce_with_archive_cold_price_proxy(_inputs(), load_archive=_roster)


def test_contract_pins_and_prospective_import_boundary() -> None:
    from .frozen_source_checks import assert_minutes_reference_sources

    root = Path(__file__).resolve().parents[1]
    contract = yaml.safe_load(
        (root / "config/retrospective_current_minutes_proxy_v1.yaml").read_text()
    )
    assert contract["comparator"] == NAME
    assert contract["evidence_class"] == EVIDENCE_CLASS
    assert contract["parameters_changed"] == []
    assert contract["formal_model_runs_authorized_by_this_contract"] == 0
    assert sum(contract["readiness_audit"]["cold_price_sensitive_rows"].values()) == 821
    assert_minutes_reference_sources(root, contract)
    for directory in ("jobs", "features", "models", "optimize"):
        for source in (root / "src/fpl" / directory).rglob("*.py"):
            assert "retrospective_minutes_proxy" not in source.read_text(encoding="utf-8")
