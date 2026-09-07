"""Hand-computable tactical state and separate retrospective source boundary checks."""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import duckdb
import pytest

from fpl.features.pit import FeatureSource, LeakageError, PointInTimeView
from fpl.storage.db import initialise
from fpl.transform.pl_sdp import SdpIdentityError
from fpl.validate.tactical_metric_audit import self_check
from fpl.validate.tactical_state import (
    DIMENSIONS,
    RECENCY_WEIGHTS,
    WHITELIST,
    RetrospectiveTacticalBackfillView,
    TacticalObservation,
    current_state,
    load_observations,
    tactical_values,
)

from .test_retrospective_sdp import AS_OF, KICKOFF, _archive_fixture, _raw_capture

SEASON = "2024-25"
CUTOFF = datetime(2024, 9, 30, tzinfo=UTC)
CAPTURED = datetime(2026, 9, 5, tzinfo=UTC)


def observation(
    value: float | None,
    gw: int = 1,
    *,
    team_code: int = 101,
    fixture: int | None = None,
    season: str = SEASON,
) -> TacticalObservation:
    return TacticalObservation(
        season=season,
        gw=gw,
        fixture=gw if fixture is None else fixture,
        team_code=team_code,
        opponent_team_code=202 if team_code == 101 else 101,
        was_home=True,
        kickoff=KICKOFF + timedelta(days=gw),
        goals=2,
        goals_allowed=1,
        values=(value, value, value, value, value),
        sdp_match_id=9000 + gw,
        capture_id=f"capture-{gw}",
        source_known_at=CAPTURED,
        payload_sha256=f"sha-{gw}",
    )


@pytest.fixture
def con() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = initialise(":memory:")
    yield connection
    connection.close()


def extra_metrics(con: duckdb.DuckDBPyConnection, capture: str, *, multiplier: int = 1) -> None:
    for side, shots, box, possession, forward, passes in (
        ("home", 10, 30, 60, 100, 500),
        ("away", 20, 15, 40, 80, 200),
    ):
        for key, local, value in (
            ("totalScoringAtt", "shots", shots * multiplier),
            ("touchesInOppBox", "touches_in_opposition_box", box * multiplier),
            ("possessionPercentage", "possession", possession),
            ("fwdPass", "forward_passes", forward),
            ("totalPass", "passes", passes),
        ):
            con.execute(
                """INSERT INTO stg_pl_sdp_team_match_metric
                (sdp_match_id,side,payload_id,provider_field,local_field,value_numeric)
                VALUES (9001,?,?,?,?,?)""",
                [side, capture, key, local, value],
            )


def test_audit_hand_checks() -> None:
    self_check()


def test_weighted_current_state_and_shrinkage_hand_calculation() -> None:
    state = current_state([observation(2, 1), observation(4, 2)], 101, SEASON, CUTOFF, 3)
    recent = (4 + 0.707 * 2) / (1 + 0.707)
    assert state.recent_raw == pytest.approx((recent,) * 5)
    assert state.prior == (3.0,) * 5
    assert state.counts == (2,) * 5
    assert state.values == pytest.approx((0.5 * recent + 0.5 * 3,) * 5)


def test_missing_consumes_chronological_rank_and_never_becomes_zero() -> None:
    history = [observation(2, 1), observation(4, 2), observation(None, 3)]
    state = current_state(history, 101, SEASON, CUTOFF, 4)
    expected = (4 * 0.707 + 2 * 0.5) / (0.707 + 0.5)
    assert state.recent_raw == pytest.approx((expected,) * 5)
    assert state.counts == (2,) * 5
    assert history[-1].values == (None,) * 5
    assert history[-1].key in state.source_keys


def test_last_five_cap_and_recency_order_are_fixed() -> None:
    history = [observation(float(gw), gw) for gw in range(1, 8)]
    expected = sum(
        value * weight for value, weight in zip((7, 6, 5, 4, 3), RECENCY_WEIGHTS, strict=True)
    )
    expected /= sum(RECENCY_WEIGHTS)
    state = current_state(history, 101, SEASON, CUTOFF, 8)
    reversed_state = current_state(list(reversed(history)), 101, SEASON, CUTOFF, 8)
    assert state.recent_raw == pytest.approx((expected,) * 5)
    assert state.counts == (5,) * 5
    assert state == reversed_state


def test_explicit_zero_remains_measured() -> None:
    state = current_state([observation(0.0)], 101, SEASON, CUTOFF, 2)
    assert state.counts == (1,) * 5
    assert state.recent_raw == (0.0,) * 5
    assert state.values == (0.0,) * 5


def test_season_reset_has_no_previous_club_state_carry() -> None:
    previous = replace(observation(2), season="2023-24", kickoff=datetime(2024, 5, 1, tzinfo=UTC))
    other = replace(previous, team_code=303, opponent_team_code=404, values=(6.0,) * 5)
    state = current_state([previous, other], 101, SEASON, CUTOFF, 1)
    assert state.counts == (0,) * 5
    assert state.recent_raw == (None,) * 5
    assert state.prior == (4.0,) * 5
    assert state.values == (4.0,) * 5


def test_promoted_team_and_empty_state_use_only_explicit_available_prior() -> None:
    state = current_state([observation(4.0)], 999, SEASON, CUTOFF, 2)
    assert state.counts == (0,) * 5
    assert state.recent_raw == (None,) * 5
    assert state.values == (4.0,) * 5
    empty = current_state([], 999, SEASON, CUTOFF, 2)
    assert empty.values == (None,) * 5
    assert empty.prior == (None,) * 5


def test_stable_team_code_not_season_scoped_position_or_opponent() -> None:
    first = observation(2.0, team_code=101)
    other = observation(10.0, team_code=999)
    state = current_state([first, other], 101, SEASON, CUTOFF, 2)
    assert state.recent_raw == (2.0,) * 5
    assert state.counts == (1,) * 5
    assert state.prior == (6.0,) * 5


def test_future_truncation_equivalence_including_prior_normalization() -> None:
    history = [observation(2.0), observation(4.0, 2)]
    future = replace(observation(999.0, 3), kickoff=CUTOFF)
    before = current_state(history, 101, SEASON, CUTOFF, 4)
    after = current_state([*history, future], 101, SEASON, CUTOFF, 4)
    assert before == after


def test_entire_same_gameweek_batch_and_dgw_legs_excluded_until_next_gw() -> None:
    old = observation(2.0)
    leg1 = observation(100.0, 2, fixture=20)
    leg2 = observation(200.0, 2, fixture=21)
    history = [old, leg1, leg2]
    first_cutoff = leg1.kickoff - timedelta(hours=1)
    between_cutoff = leg1.kickoff + timedelta(hours=1)
    before = current_state(history, 101, SEASON, first_cutoff, 2)
    between = current_state(history, 101, SEASON, between_cutoff, 2)
    assert before == between
    assert before.counts == (1,) * 5
    after = current_state(history, 101, SEASON, CUTOFF, 3)
    assert after.counts == (3,) * 5


def test_postponed_previous_gw_leg_requires_actual_kickoff_before_cutoff() -> None:
    old = observation(2.0)
    delayed = replace(observation(9.0, 1, fixture=20), kickoff=CUTOFF + timedelta(days=1))
    before = current_state([old, delayed], 101, SEASON, CUTOFF, 3)
    assert before.counts == (1,) * 5
    after = current_state([old, delayed], 101, SEASON, CUTOFF + timedelta(days=2), 4)
    assert after.counts == (2,) * 5


def test_target_goals_never_enter_current_state() -> None:
    row = observation(3.0)
    changed = replace(row, goals=99, goals_allowed=88)
    assert current_state([row], 101, SEASON, CUTOFF, 2) == current_state(
        [changed], 101, SEASON, CUTOFF, 2
    )


def test_duplicate_visible_match_rejected() -> None:
    row = observation(3.0)
    with pytest.raises(ValueError, match="duplicate"):
        current_state([row, row], 101, SEASON, CUTOFF, 2)


def test_naive_cutoff_rejected() -> None:
    with pytest.raises(LeakageError, match="timezone-aware"):
        current_state([], 101, SEASON, datetime(2024, 9, 1), 2)


def test_observed_dimension_formulas_and_opponent_direction() -> None:
    own = dict(zip(WHITELIST, (3.0, 10.0, 30.0, 60.0, 100.0, 500.0), strict=True))
    opposite = {"totalScoringAtt": 20.0}
    assert tactical_values(own, opposite) == pytest.approx(
        (0.3, math.log(31), 0.6, 0.2, -math.log(21))
    )
    assert DIMENSIONS[-1] == "defensive_suppression"


def test_missing_and_zero_denominator_dimensions_stay_null() -> None:
    assert tactical_values({}, {}) == (None,) * 5
    values = tactical_values(
        {"ontargetScoringAtt": 0.0, "totalScoringAtt": 0.0, "fwdPass": 0.0, "totalPass": 0.0},
        {"totalScoringAtt": 0.0},
    )
    assert values == (None, None, None, None, 0.0)


@pytest.mark.parametrize(
    "own",
    [
        {"ontargetScoringAtt": 5.0, "totalScoringAtt": 4.0},
        {"fwdPass": 10.0, "totalPass": 8.0},
        {"possessionPercentage": 101.0},
        {"touchesInOppBox": -1.0},
        {"totalPass": 2.5},
        {"totalScoringAtt": float("nan")},
    ],
)
def test_invalid_provider_values_fail_closed(own: dict[str, float]) -> None:
    with pytest.raises(ValueError, match=r"exceeds|exceed|invalid|not integral"):
        tactical_values(own, {})


def test_reader_earliest_whole_payload_crosswalk_and_metrics(
    con: duckdb.DuckDBPyConnection,
) -> None:
    _archive_fixture(con, pulse_id=123)
    _raw_capture(con, payload_id="first", fetched_at=CAPTURED)
    extra_metrics(con, "first")
    _raw_capture(con, payload_id="revision", fetched_at=CAPTURED + timedelta(hours=1), sot=(9, 9))
    extra_metrics(con, "revision", multiplier=2)
    rows = load_observations(con, AS_OF)
    home, away = rows
    assert home.capture_id == "first"
    assert home.source_known_at == CAPTURED
    assert home.source_known_at > AS_OF.ts
    assert home.sdp_match_id == 9001
    assert home.team_code == 101
    assert away.team_code == 202
    assert home.values == pytest.approx((0.3, math.log(31), 0.6, 0.2, -math.log(21)))
    assert away.values[-1] == pytest.approx(-math.log(11))
    assert rows == load_observations(con, AS_OF)


def test_earliest_missing_metric_not_filled_from_later_revision(
    con: duckdb.DuckDBPyConnection,
) -> None:
    _archive_fixture(con)
    _raw_capture(con, payload_id="first", fetched_at=CAPTURED, sot=(None, 4.0))
    extra_metrics(con, "first")
    _raw_capture(con, payload_id="revision", fetched_at=CAPTURED + timedelta(hours=1))
    extra_metrics(con, "revision")
    assert load_observations(con, AS_OF)[0].values[0] is None


def test_reader_no_future_match_stats_and_truncation(con: duckdb.DuckDBPyConnection) -> None:
    _archive_fixture(con)
    _raw_capture(con, payload_id="first", fetched_at=CAPTURED)
    extra_metrics(con, "first")
    before = load_observations(con, AS_OF)
    _archive_fixture(con, fixture=2, match_id=9002, kickoff=AS_OF.ts)
    _raw_capture(con, payload_id="future", fetched_at=CAPTURED, match_id=9002, sot=(999, 999))
    assert before == load_observations(con, AS_OF)


def test_wrong_provider_team_identity_rejected(con: duckdb.DuckDBPyConnection) -> None:
    _archive_fixture(con)
    _raw_capture(con, payload_id="wrong", fetched_at=CAPTURED, sides=(("home", 999), ("away", 202)))
    with pytest.raises(SdpIdentityError, match="permanent team_code"):
        load_observations(con, AS_OF)


def test_retrospective_capability_cannot_supply_production_features(
    con: duckdb.DuckDBPyConnection,
) -> None:
    view = RetrospectiveTacticalBackfillView(con, AS_OF)
    assert not isinstance(view, FeatureSource)
    assert not isinstance(view, PointInTimeView)
    assert view.evidence_class == "retrospective_backfill_development"
    with pytest.raises(AttributeError):
        PointInTimeView(view, AS_OF).observed_team_football()  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="AsOf"):
        RetrospectiveTacticalBackfillView(con, AS_OF.ts)  # type: ignore[arg-type]


def test_observation_immutable_and_cannot_be_relabelled_prospective() -> None:
    row = observation(1.0)
    with pytest.raises(FrozenInstanceError):
        row.goals = 3  # type: ignore[misc]
    with pytest.raises(ValueError, match="cannot be relabelled"):
        replace(row, evidence_class="strict_prospective")  # type: ignore[arg-type]
