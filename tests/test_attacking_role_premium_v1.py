"""Synthetic causal/rate contracts for fixed development-only usage persistence V1."""

from __future__ import annotations

import json
from dataclasses import asdict, fields, replace
from datetime import UTC, datetime, timedelta

import pytest

from fpl.features.attacking_role_premium_v1 import (
    RECENT_WINDOW_MINUTES,
    SHRINKAGE_MINUTES,
    UsageObservation,
    UsagePrediction,
    UsageTarget,
    predict_batch,
)
from fpl.features.pit import LeakageError

AS_OF = datetime(2023, 10, 1, tzinfo=UTC)


def observed(
    player: int = 1,
    *,
    fixture: int = 1,
    gw: int = 1,
    minutes: int | None = 90,
    xg: float | None = 0.1,
    xa: float | None = 0.2,
    position: str = "DEF",
) -> UsageObservation:
    kickoff = datetime(2023, 8, 10, tzinfo=UTC) + timedelta(days=gw)
    return UsageObservation(
        season="2023-24",
        gameweek=gw,
        fixture_id=fixture,
        kickoff_time=kickoff,
        player_code=player,
        fpl_position=position,
        minutes=minutes,
        starts=1,
        xg=xg,
        xa=xa,
        source_known_at=kickoff + timedelta(days=1),
        available_at=kickoff + timedelta(days=1),
        evidence_class="ARCHIVED_AS_OF",
        source_snapshot_id=f"{gw:040x}",
        source_sha256=f"{gw:064x}",
    )


def target(player: int = 1, *, fixture: int = 100, position: str = "DEF") -> UsageTarget:
    return UsageTarget(
        season="2023-24",
        gameweek=10,
        fixture_id=fixture,
        kickoff_time=AS_OF + timedelta(days=1),
        player_code=player,
        fpl_position=position,
        team_code=10,
        opponent_team_code=20,
        venue="HOME",
    )


def encoded(rows: tuple[UsagePrediction, ...]) -> bytes:
    return json.dumps(
        [asdict(row) for row in rows], sort_keys=True, default=str, allow_nan=False
    ).encode()


def test_exact_fixed_shrinkage_and_xgi_sum() -> None:
    history = [observed(xg=1.0, xa=0.2), observed(2, xg=0.0, xa=0.4)]
    row = predict_batch(history, [target()], as_of=AS_OF)[0]
    assert SHRINKAGE_MINUTES == 450.0 and RECENT_WINDOW_MINUTES == 360.0
    assert row.positional_prior_xg90 == 0.5
    assert row.positional_prior_xa90 == pytest.approx(0.3)
    assert row.control_xg90 == row.candidate_xg90 == (90 + 450 * 0.5) / (90 + 450)
    assert row.candidate_xa90 == pytest.approx((90 * 0.2 + 450 * 0.3) / 540)
    assert row.control_xgi90 == row.control_xg90 + row.control_xa90
    assert row.candidate_xgi90 == row.candidate_xg90 + row.candidate_xa90
    assert row.recent_shift_xgi90 == row.candidate_xgi90 - row.control_xgi90


def test_partial_oldest_appearance_is_prorated_at_360_minutes() -> None:
    history = [observed(fixture=1, gw=1, minutes=120, xg=0.8, xa=0.4)] + [
        observed(fixture=gw, gw=gw, xg=0.2, xa=0.1) for gw in (2, 3, 4)
    ]
    row = predict_batch(history, [target()], as_of=AS_OF)[0]
    assert row.historical_minutes == 390
    assert row.recent_window_minutes == 360
    assert row.candidate_xg90 == pytest.approx(
        (90 * (0.8 * 0.75 + 0.6) + 450 * (90 * 1.4 / 390)) / 810
    )
    assert row.candidate_xa90 == pytest.approx(
        (90 * (0.4 * 0.75 + 0.3) + 450 * (90 * 0.7 / 390)) / 810
    )
    assert row.historical_starts == 4
    assert row.historical_appearances == row.historical_meaningful_appearances == 4


def test_oldest_history_beyond_window_changes_control_but_not_recent_numerator() -> None:
    history = [observed(fixture=1, gw=1, xg=2.0)] + [
        observed(fixture=gw, gw=gw, xg=0.1) for gw in (2, 3, 4, 5)
    ]
    row = predict_batch(history, [target()], as_of=AS_OF)[0]
    assert row.historical_minutes == 450 and row.recent_window_minutes == 360
    assert row.candidate_xg90 == pytest.approx((90 * 0.4 + 450 * row.positional_prior_xg90) / 810)
    assert row.control_xg90 > row.candidate_xg90


def test_small_sample_is_shrunk_more_than_large_sample_without_player_tuning() -> None:
    history = [observed(minutes=45, xg=0.5), observed(2, minutes=90, xg=0.0)]
    row = predict_batch(history, [target()], as_of=AS_OF)[0]
    assert row.candidate_xg90 == pytest.approx((45 * 1.0 + 450 * row.positional_prior_xg90) / 495)
    assert row.positional_prior_xg90 < row.candidate_xg90 < 1.0
    assert row.historical_meaningful_appearances == 1


def test_cold_start_returns_position_prior_exactly_and_does_not_create_peer() -> None:
    history = [observed(xg=0.13, xa=0.07)]
    rows = predict_batch(history, [target(), target(99)], as_of=AS_OF)
    row = next(value for value in rows if value.target.player_code == 99)
    assert row.control_xg90 == row.candidate_xg90 == row.positional_prior_xg90
    assert row.control_xa90 == row.candidate_xa90 == row.positional_prior_xa90
    assert row.historical_minutes == row.recent_window_minutes == 0
    assert row.historical_starts == row.historical_appearances == 0
    assert row.peer_count == 1


def test_no_positional_prior_fails_closed_instead_of_zero_filling() -> None:
    with pytest.raises(ValueError, match="no measured positional prior"):
        predict_batch([observed(2, position="MID")], [target()], as_of=AS_OF)
    with pytest.raises(ValueError, match="no measured positional prior"):
        predict_batch([], [target()], as_of=AS_OF)


def test_missing_paired_stat_excludes_whole_row_and_dnp_has_no_rate_exposure() -> None:
    history = [
        observed(xg=None, xa=9.0),
        observed(fixture=2, gw=2, minutes=0, xg=8.0, xa=8.0),
        observed(2, xg=0.2, xa=0.1),
    ]
    row = predict_batch(history, [target()], as_of=AS_OF)[0]
    assert row.historical_minutes == row.recent_window_minutes == 0
    assert row.candidate_xg90 == row.positional_prior_xg90 == 0.2
    assert row.candidate_xa90 == row.positional_prior_xa90 == 0.1
    assert row.paired_history_rows == 0 and row.unavailable_paired_rows == 1
    assert row.zero_minute_history_rows == 1
    assert row.history_rows == 2 and row.historical_appearances == 1
    assert history[0].xg is None


def test_unknown_starts_remain_unknown_in_count_metadata() -> None:
    missing = replace(observed(), starts=None)
    row = predict_batch([missing, observed(2)], [target()], as_of=AS_OF)[0]
    assert row.historical_starts is None
    assert row.historical_appearances == row.historical_meaningful_appearances == 1


def test_unknown_minutes_in_unfilled_recent_window_fail_closed() -> None:
    with pytest.raises(ValueError, match="unknown minutes inside recent window"):
        predict_batch([observed(minutes=None), observed(2)], [target()], as_of=AS_OF)


def test_missing_opportunity_consumes_window_without_pulling_older_stats() -> None:
    history = [
        observed(fixture=1, gw=1, xg=9.0, xa=9.0),
        observed(fixture=2, gw=2, xg=0.3, xa=0.2),
        observed(fixture=3, gw=3, xg=None, xa=8.0),
        observed(fixture=4, gw=4, xg=0.3, xa=0.2),
        observed(fixture=5, gw=5, xg=0.3, xa=0.2),
    ]
    row = predict_batch(history, [target()], as_of=AS_OF)[0]
    assert row.recent_window_minutes == 270
    assert row.candidate_xg90 == pytest.approx((90 * 0.9 + 450 * row.positional_prior_xg90) / 720)
    assert row.candidate_xa90 == pytest.approx((90 * 0.6 + 450 * row.positional_prior_xa90) / 720)


def test_unknown_minutes_older_than_completed_window_cannot_change_recent_exposure() -> None:
    history = [observed(fixture=1, gw=1, minutes=None)] + [
        observed(fixture=gw, gw=gw) for gw in (2, 3, 4, 5)
    ]
    row = predict_batch(history, [target()], as_of=AS_OF)[0]
    assert row.recent_window_minutes == 360
    assert row.historical_appearances is None


def test_midrank_percentiles_are_position_relative_and_equal_weighted() -> None:
    history = [
        observed(xg=0.8, xa=0.1),
        observed(2, xg=0.0, xa=0.9),
        observed(3, position="MID", xg=9.0),
    ]
    row = predict_batch(history, [target()], as_of=AS_OF)[0]
    assert row.peer_count == 2
    assert row.xg_premium_percentile == 0.75
    assert row.xa_premium_percentile == 0.25
    assert row.attacking_role_premium_v1 == 0.5
    assert row.positional_prior_xg90 == 0.4


def test_tied_peers_receive_midpoint_and_one_player_counts_once() -> None:
    history = [
        observed(xg=0.125, xa=0.25),
        observed(fixture=2, gw=2, xg=0.125, xa=0.25),
        observed(2, xg=0.125, xa=0.25),
    ]
    rows = predict_batch(history, [target(), target(2)], as_of=AS_OF)
    assert all(row.peer_count == 2 for row in rows)
    assert all(row.xg_premium_percentile == row.xa_premium_percentile == 0.5 for row in rows)


def test_target_population_does_not_determine_training_peer_distribution() -> None:
    history = [observed(), observed(2, xg=0.8)]
    one = predict_batch(history, [target()], as_of=AS_OF)[0]
    many = predict_batch(history, [target(99), target(), target(98)], as_of=AS_OF)
    assert next(row for row in many if row.target.player_code == 1) == one


@pytest.mark.parametrize("field", ["xg", "xa", "minutes", "starts", "fpl_position"])
def test_target_fixture_observation_never_changes_its_predictor(field: str) -> None:
    history = [observed(), observed(2)]
    leaking = replace(observed(fixture=100, gw=10), **{field: 999})
    assert encoded(predict_batch([*history, leaking], [target()], as_of=AS_OF)) == encoded(
        predict_batch(history, [target()], as_of=AS_OF)
    )


def test_whole_gameweek_and_every_target_double_gameweek_fixture_excluded() -> None:
    history = [observed(), observed(2)]
    same_gw_other_fixture = observed(fixture=77, gw=10, xg=100)
    conflicting_old_gw_target_leg = observed(fixture=101, gw=8, xg=100)
    targets = [target(fixture=100), target(fixture=101)]
    assert predict_batch(
        [*history, same_gw_other_fixture, conflicting_old_gw_target_leg], targets, as_of=AS_OF
    ) == predict_batch(history, targets, as_of=AS_OF)


@pytest.mark.parametrize("field", ["kickoff_time", "source_known_at", "available_at"])
def test_future_truncation_is_byte_identical_for_each_availability_axis(field: str) -> None:
    history = [observed(), observed(2)]
    future = replace(observed(3, fixture=3, gw=3, xg=999), **{field: AS_OF + timedelta(days=1)})
    assert encoded(predict_batch([*history, future], [target()], as_of=AS_OF)) == encoded(
        predict_batch(history, [target()], as_of=AS_OF)
    )


def test_earliest_whole_version_preserves_missing_value_and_excludes_later_revision() -> None:
    earliest = observed(xg=None)
    correction = replace(
        earliest,
        source_snapshot_id="f" * 40,
        source_known_at=earliest.source_known_at + timedelta(days=1),
        available_at=earliest.available_at + timedelta(days=1),
        xg=9.0,
    )
    history = [earliest, observed(2)]
    assert predict_batch([correction, *history], [target()], as_of=AS_OF) == predict_batch(
        history, [target()], as_of=AS_OF
    )


def test_contradictory_duplicate_source_version_is_rejected() -> None:
    first = observed()
    with pytest.raises(ValueError, match="contradictory observation source"):
        predict_batch([first, replace(first, xg=0.9)], [target()], as_of=AS_OF)
    assert predict_batch([first, first], [target()], as_of=AS_OF) == predict_batch(
        [first], [target()], as_of=AS_OF
    )


@pytest.mark.parametrize(
    "kind", ["RETROSPECTIVE_DEVELOPMENT", "CURRENT_PROSPECTIVE", "STRICT_HISTORICAL_PIT"]
)
def test_only_preregistered_archived_as_of_class_enters_features(kind: str) -> None:
    permitted = observed()
    ignored = replace(observed(2, xg=100), evidence_class=kind)
    assert predict_batch([permitted, ignored], [target()], as_of=AS_OF) == predict_batch(
        [permitted], [target()], as_of=AS_OF
    )


def test_prior_season_is_excluded_and_transfer_context_does_not_rescale_usage() -> None:
    history = [observed()]
    old = replace(observed(2, xg=100), season="2022-23")
    base = predict_batch(history, [target()], as_of=AS_OF)[0]
    moved_target = replace(target(), team_code=30, opponent_team_code=40, venue="AWAY")
    moved = predict_batch([*history, old], [moved_target], as_of=AS_OF)[0]
    assert replace(moved, target=target()) == base


def test_historical_and_target_position_contradictions_fail_closed() -> None:
    with pytest.raises(ValueError, match="historical registered position"):
        predict_batch(
            [observed(), observed(fixture=2, gw=2, position="MID")], [target()], as_of=AS_OF
        )
    with pytest.raises(ValueError, match="target position contradicts"):
        predict_batch([observed()], [target(position="MID")], as_of=AS_OF)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("xg", float("nan")),
        ("xa", float("inf")),
        ("xg", -1.0),
        ("minutes", 121),
        ("minutes", True),
        ("starts", 2),
    ],
)
def test_invalid_eligible_numeric_values_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValueError, match="invalid observed"):
        predict_batch([replace(observed(), **{field: value})], [target()], as_of=AS_OF)


def test_empty_batch_duplicate_targets_naive_time_and_nonfuture_targets() -> None:
    assert predict_batch([], [], as_of=AS_OF) == ()
    with pytest.raises(ValueError, match="duplicate target"):
        predict_batch([observed()], [target(), target()], as_of=AS_OF)
    with pytest.raises(ValueError, match="one complete"):
        predict_batch([observed()], [target(), replace(target(2), gameweek=11)], as_of=AS_OF)
    with pytest.raises(LeakageError, match="timezone-aware"):
        predict_batch([observed()], [target()], as_of=AS_OF.replace(tzinfo=None))
    with pytest.raises(ValueError, match="remain future"):
        predict_batch([observed()], [replace(target(), kickoff_time=AS_OF)], as_of=AS_OF)


def test_deterministic_replay_source_order_and_provenance() -> None:
    history = [observed(), observed(2, fixture=2, gw=2)]
    first = predict_batch(history, [target(2), target()], as_of=AS_OF)
    second = predict_batch(list(reversed(history)), [target(), target(2)], as_of=AS_OF)
    assert encoded(first) == encoded(second)
    assert all(len(row.history_sha256) == len(row.player_history_sha256) == 64 for row in first)
    assert all(len(row.source_versions) == 2 for row in first)


def test_input_contract_has_no_same_match_outcomes_or_unsupported_source_fields() -> None:
    assert {field.name for field in fields(UsageTarget)} == {
        "season",
        "gameweek",
        "fixture_id",
        "kickoff_time",
        "player_code",
        "fpl_position",
        "team_code",
        "opponent_team_code",
        "venue",
    }
    assert {field.name for field in fields(UsageObservation)} == {
        "season",
        "gameweek",
        "fixture_id",
        "kickoff_time",
        "player_code",
        "fpl_position",
        "minutes",
        "starts",
        "xg",
        "xa",
        "source_known_at",
        "available_at",
        "evidence_class",
        "source_snapshot_id",
        "source_sha256",
    }
