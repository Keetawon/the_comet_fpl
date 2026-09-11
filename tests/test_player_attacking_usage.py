"""Current-capture descriptive arithmetic, causality and availability contracts."""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import asdict, fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from fpl.features.attacking_role_premium_v1 import (
    UsageObservation,
    _percentile,
    _rates,
    _totals,
)
from fpl.features.pit import LeakageError
from fpl.features.player_attacking_usage import (
    PlayerAttackingUsageSnapshot,
    RegisteredUsagePlayer,
    build_player_attacking_usage,
    exposure_bucket,
    usage_bucket,
)

AS_OF = datetime(2026, 9, 8, 12, tzinfo=UTC)


def player(code: int = 1, position: str = "DEF") -> RegisteredUsagePlayer:
    return RegisteredUsagePlayer(
        "2026-27",
        code,
        f"Player {code}",
        position,
        100,
        AS_OF - timedelta(hours=1),
        AS_OF - timedelta(hours=1),
        "current-capture-1",
    )


def observation(
    code: int = 1,
    *,
    fixture: int = 1,
    minutes: int | None = 90,
    xg: float | None = 0.1,
    xa: float | None = 0.2,
    position: str = "DEF",
) -> UsageObservation:
    return UsageObservation(
        "2026-27",
        fixture,
        fixture,
        AS_OF - timedelta(days=20 - fixture),
        code,
        position,
        minutes,
        1,
        xg,
        xa,
        AS_OF - timedelta(hours=2),
        AS_OF - timedelta(hours=2),
        "CURRENT_PROSPECTIVE",
        "current-capture-1",
        "a" * 64,
    )


def encoded(rows: tuple[PlayerAttackingUsageSnapshot, ...]) -> bytes:
    return json.dumps(
        [asdict(r) for r in rows], default=str, sort_keys=True, allow_nan=False
    ).encode()


def test_fixed_arithmetic_reuses_unchanged_long_recent_and_percentile_helpers() -> None:
    history = [observation(fixture=n, xg=n / 10, xa=n / 20) for n in range(1, 7)]
    history.append(observation(2, xg=0.125, xa=0.125))
    rows = build_player_attacking_usage(history, [player(), player(2)], AS_OF)
    total_minutes, xg, xa = _totals(history)
    prior = (90 * xg / total_minutes, 90 * xa / total_minutes)
    own = [r for r in history if r.player_code == 1]
    expected_long = _rates(_totals(own), prior)
    expected_recent = _rates(_totals(own, 360), prior)
    row = rows[0]
    assert (row.long_xg90, row.long_xa90) == expected_long
    assert (row.recent_xg90, row.recent_xa90) == expected_recent
    assert row.long_xgi90 == expected_long[0] + expected_long[1]
    assert row.recent_xgi90 == expected_recent[0] + expected_recent[1]
    assert row.delta_xgi90 == row.recent_xgi90 - row.long_xgi90
    recent_xg_peers = [r.recent_xg90 for r in rows if r.recent_xg90 is not None]
    assert row.recent_xg_percentile == _percentile(expected_recent[0], recent_xg_peers)
    assert row.recent_xa_percentile is not None
    assert row.recent_usage_percentile == (row.recent_xg_percentile + row.recent_xa_percentile) / 2


def test_partial_oldest_boundary_preserves_actual_360_minutes() -> None:
    history = [observation(fixture=1, minutes=120, xg=0.8, xa=0.4)] + [
        observation(fixture=n, xg=0.2, xa=0.1) for n in (2, 3, 4)
    ]
    row = build_player_attacking_usage(history, [player()], AS_OF)[0]
    assert row.historical_minutes == 390
    assert row.recent_window_minutes == row.recent_measured_minutes == 360
    assert row.recent_xg90 == pytest.approx((90 * 1.2 + 450 * (90 * 1.4 / 390)) / 810)


def test_under_360_minutes_long_and_recent_are_exactly_equal() -> None:
    row = build_player_attacking_usage([observation()], [player()], AS_OF)[0]
    assert row.long_xg90 == row.recent_xg90
    assert row.long_xa90 == row.recent_xa90
    assert row.long_usage_percentile == row.recent_usage_percentile == 0.5
    assert row.delta_xgi90 == row.delta_usage_percentile == 0


def test_cold_start_and_dnp_only_are_unranked_even_with_positional_prior() -> None:
    rows = build_player_attacking_usage(
        [observation(), replace(observation(3, minutes=0, xg=None, xa=None), starts=0)],
        [player(), player(2), player(3)],
        AS_OF,
    )
    for row in rows[1:]:
        assert row.long_xg90 is None
        assert row.recent_usage_percentile is None
        assert row.long_usage_bucket == row.recent_usage_bucket == "UNKNOWN"
        assert row.historical_minutes == 0
        assert row.exposure_bucket == "VERY_LOW"
        assert row.long_peer_count == row.recent_peer_count == 1


def test_future_truncation_is_byte_identical_including_peer_hashes() -> None:
    history = [observation()]
    expected = encoded(build_player_attacking_usage(history, [player()], AS_OF))
    future = [
        replace(observation(fixture=2, xg=999), source_known_at=AS_OF + timedelta(seconds=1)),
        replace(observation(fixture=3, xg=999), available_at=AS_OF + timedelta(seconds=1)),
        replace(observation(fixture=4, xg=999), kickoff_time=AS_OF),
        replace(observation(2, xg=999), kickoff_time=AS_OF + timedelta(days=1)),
    ]
    players = [player(), replace(player(2), source_known_at=AS_OF + timedelta(seconds=1))]
    assert encoded(build_player_attacking_usage([*history, *future], players, AS_OF)) == expected


def test_known_at_equal_cutoff_is_eligible_but_one_second_later_is_not() -> None:
    row = replace(observation(), source_known_at=AS_OF, available_at=AS_OF)
    before = build_player_attacking_usage([row], [player()], AS_OF - timedelta(seconds=1))[0]
    current = build_player_attacking_usage([row], [player()], AS_OF)[0]
    assert before.long_xg90 is None
    assert current.long_xg90 is not None


def test_latest_eligible_revision_selected_whole_without_filling_missing_values() -> None:
    old = observation()
    revision = replace(
        old,
        xg=None,
        source_snapshot_id="current-capture-2",
        source_known_at=AS_OF - timedelta(minutes=30),
        available_at=AS_OF - timedelta(minutes=30),
        source_sha256="b" * 64,
    )
    row = build_player_attacking_usage([old, revision], [player()], AS_OF)[0]
    assert row.long_xg90 is None
    assert row.measured_minutes == 0
    assert row.historical_minutes == 90
    assert row.source_versions == (
        (revision.source_snapshot_id, revision.source_known_at.isoformat(), "b" * 64),
    )


def test_later_revision_does_not_change_earlier_snapshot() -> None:
    old = observation()
    future = replace(
        old,
        xg=10,
        source_snapshot_id="new",
        source_known_at=AS_OF + timedelta(days=1),
        available_at=AS_OF + timedelta(days=1),
    )
    assert encoded(build_player_attacking_usage([old, future], [player()], AS_OF)) == encoded(
        build_player_attacking_usage([old], [player()], AS_OF)
    )


def test_duplicate_conflict_fails_closed_identical_repeat_is_idempotent() -> None:
    old = observation()
    single = build_player_attacking_usage([old], [player()], AS_OF)
    assert encoded(build_player_attacking_usage([old, old], [player()], AS_OF)) == encoded(single)
    with pytest.raises(ValueError, match="contradictory duplicate"):
        build_player_attacking_usage([old, replace(old, xg=3)], [player()], AS_OF)


def test_missing_middle_window_does_not_pull_in_older_opportunity() -> None:
    history = [observation(fixture=n) for n in range(1, 7)]
    history[4] = replace(history[4], xg=None)
    row = build_player_attacking_usage(history, [player()], AS_OF)[0]
    assert row.long_xg90 is None
    assert row.recent_xg90 is None
    assert row.historical_minutes == 540
    assert row.measured_minutes == 450
    assert row.recent_window_minutes == 360
    assert row.recent_measured_minutes == 270
    assert row.long_profile_status == row.recent_profile_status == "INCOMPLETE_OPPORTUNITY"


def test_old_missing_opportunity_invalidates_long_but_not_complete_recent_window() -> None:
    history = [observation(fixture=1, xa=None), *[observation(fixture=n) for n in range(2, 6)]]
    row = build_player_attacking_usage(history, [player()], AS_OF)[0]
    assert row.long_xa90 is None
    assert row.recent_xa90 is not None
    assert row.long_peer_count == 0
    assert row.recent_peer_count == 1
    assert row.delta_xa90 is None


def test_unknown_minutes_inside_window_is_unavailable() -> None:
    row = build_player_attacking_usage(
        [observation(), observation(fixture=2, minutes=None)], [player()], AS_OF
    )[0]
    assert row.historical_minutes is None
    assert row.recent_window_minutes is None
    assert row.recent_measured_minutes is None
    assert row.recent_xg90 is None
    assert row.exposure_bucket == "UNKNOWN"
    assert row.historical_appearances is None
    assert row.measured_minutes == 90


def test_unknown_old_minutes_beyond_full_window_do_not_invalidate_recent() -> None:
    history = [observation(fixture=1, minutes=None), *[observation(fixture=n) for n in range(2, 6)]]
    row = build_player_attacking_usage(history, [player()], AS_OF)[0]
    assert row.long_xg90 is None
    assert row.historical_minutes is None
    assert row.recent_window_minutes == 360
    assert row.recent_xg90 is not None


def test_null_starts_remain_null_without_invalidating_measured_usage() -> None:
    row = build_player_attacking_usage([replace(observation(), starts=None)], [player()], AS_OF)[0]
    assert row.historical_starts is None
    assert row.historical_appearances == 1
    assert row.long_xg90 is not None


def test_low_exposure_players_are_in_position_percentile_peers() -> None:
    rows = build_player_attacking_usage(
        [observation(minutes=45), observation(2, minutes=90, xg=0, xa=0)],
        [player(), player(2)],
        AS_OF,
    )
    assert rows[0].exposure_bucket == "VERY_LOW"
    assert rows[0].long_peer_count == 2
    assert rows[0].long_usage_percentile == 0.75


def test_peers_use_current_roster_and_same_position_only() -> None:
    first = build_player_attacking_usage([observation()], [player()], AS_OF)[0]
    result = build_player_attacking_usage(
        [observation(), observation(2, xg=10), observation(3, xg=10, position="MID")],
        [player(), player(3, "MID")],
        AS_OF,
    )[0]
    assert result.long_xg90 == first.long_xg90
    assert result.long_usage_percentile == first.long_usage_percentile == 0.5
    assert result.long_peer_count == 1


def test_position_contradictions_fail_closed() -> None:
    with pytest.raises(ValueError, match="historical position contradicts"):
        build_player_attacking_usage([observation(position="MID")], [player()], AS_OF)
    with pytest.raises(ValueError, match="one current season"):
        build_player_attacking_usage([], [player(), replace(player(2), season="2025-26")], AS_OF)


def test_prior_season_position_and_other_evidence_classes_do_not_enter() -> None:
    rows = [
        replace(observation(), season="2025-26", fpl_position="MID"),
        replace(observation(fixture=2), evidence_class="ARCHIVED_AS_OF"),
        replace(observation(fixture=3), evidence_class="RETROSPECTIVE_DEVELOPMENT"),
    ]
    row = build_player_attacking_usage(rows, [player()], AS_OF)[0]
    assert row.long_xg90 is None
    assert row.source_versions == ()


def test_transfer_keeps_player_usage_and_current_registry_club_without_rescaling() -> None:
    before = build_player_attacking_usage([observation()], [player()], AS_OF)[0]
    after = build_player_attacking_usage(
        [observation()], [replace(player(), team_code=200)], AS_OF
    )[0]
    assert after.team_code == 200
    assert after.long_xg90 == before.long_xg90
    assert after.history_sha256 == before.history_sha256


def test_names_are_presentation_only_and_never_join_identity() -> None:
    rows = build_player_attacking_usage(
        [observation()], [player(), replace(player(2), web_name="Player 1")], AS_OF
    )
    assert rows[0].long_xg90 is not None
    assert rows[1].long_xg90 is None
    renamed = build_player_attacking_usage(
        [observation()], [replace(player(), web_name="Different")], AS_OF
    )[0]
    assert renamed.long_xg90 == rows[0].long_xg90


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [
        (None, "UNKNOWN"),
        (0, "VERY_LOW"),
        (179, "VERY_LOW"),
        (180, "LOW"),
        (449, "LOW"),
        (450, "MODERATE"),
        (899, "MODERATE"),
        (900, "ESTABLISHED"),
    ],
)
def test_exposure_bucket_boundaries(minutes: float | None, expected: str) -> None:
    assert exposure_bucket(minutes) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "UNKNOWN"),
        (0, "NORMAL"),
        (0.74999, "NORMAL"),
        (0.75, "ELEVATED"),
        (0.89999, "ELEVATED"),
        (0.9, "HIGH"),
        (0.97499, "HIGH"),
        (0.975, "EXTREME"),
        (1, "EXTREME"),
    ],
)
def test_usage_bucket_boundaries(value: float | None, expected: str) -> None:
    assert usage_bucket(value) == expected


@pytest.mark.parametrize("field", ["minutes", "starts", "xg", "xa"])
def test_impossible_numeric_values_fail_closed(field: str) -> None:
    change: dict[str, Any] = {field: -1}
    with pytest.raises(ValueError, match="invalid observed"):
        build_player_attacking_usage([replace(observation(), **change)], [player()], AS_OF)


def test_naive_timestamp_and_knowledge_inversion_fail_closed() -> None:
    with pytest.raises(LeakageError, match="timezone-aware"):
        build_player_attacking_usage([], [player()], AS_OF.replace(tzinfo=None))
    with pytest.raises(ValueError, match="availability precedes"):
        build_player_attacking_usage(
            [replace(observation(), available_at=AS_OF - timedelta(days=1))], [player()], AS_OF
        )


def test_duplicate_registry_identity_is_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate registered"):
        build_player_attacking_usage([], [player(), player()], AS_OF)


def test_deterministic_order_and_source_bound_provenance() -> None:
    history = [observation(2), observation(), observation(fixture=2)]
    players = [player(2), player()]
    result = build_player_attacking_usage(history, players, AS_OF)
    assert encoded(result) == encoded(
        build_player_attacking_usage(list(reversed(history)), list(reversed(players)), AS_OF)
    )
    assert [r.player_code for r in result] == [1, 2]
    assert result[0].source_known_at <= AS_OF
    assert result[0].available_at <= AS_OF
    assert result[0].population_history_sha256 == result[1].population_history_sha256
    assert result[0].registry_capture_id == "current-capture-1"


def test_snapshot_availability_includes_positional_peer_evidence() -> None:
    peer = replace(
        observation(2),
        source_known_at=AS_OF - timedelta(minutes=5),
        available_at=AS_OF - timedelta(minutes=4),
    )
    row = build_player_attacking_usage([observation(), peer], [player(), player(2)], AS_OF)[0]
    assert row.source_known_at == peer.source_known_at
    assert row.available_at == peer.available_at


def test_no_forecast_target_or_forbidden_feature_inputs_and_frozen_source_unchanged() -> None:
    field_names = {field.name for field in fields(PlayerAttackingUsageSnapshot)}
    assert not field_names.intersection(
        {"target", "expected_points", "predicted_minutes", "probability", "confirmed_oop"}
    )
    source = inspect.getsource(build_player_attacking_usage)
    assert "predict_batch" not in source
    assert "O'Reilly" not in source
    assert "Hume" not in source
    assert "De Cuyper" not in source
    frozen = Path(__file__).resolve().parents[1] / "src/fpl/features/attacking_role_premium_v1.py"
    assert (
        hashlib.sha256(frozen.read_bytes()).hexdigest()
        == "0b291668aea4c06e0d3066687dcca41475406c4ba0b54b8429d1be646512fae1"
    )
