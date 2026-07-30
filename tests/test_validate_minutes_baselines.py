"""Deterministic offline tests for the four Stage B (player minutes) baselines and their
validation slice in ``src/fpl/validate/minutes_baselines.py``.

No database, no network. Every input row is synthetic. These tests pin the frozen contract
(``config/phase2_evaluation.yaml`` 1.0) as it is *supposed* to be honoured: the exact baseline
names/order, the nine safe target proxy columns, the config-derived four bins (open ``90`` tail),
raw ``count / n`` with no smoothing, the position -> all-position -> fail-closed fallback chain,
stable ``code`` / ``team_code`` identity, recency tie order, zero-minute retention, and every
fail-closed rejection (naive timestamps, history-at/after cutoff, target-before-cutoff, duplicate
grain, missing team mapping, invalid Position, NULL/non-int/negative minutes).

Where a test asserts behaviour the source does not yet implement, it is a recorded source defect,
not a test to weaken: see the handoff.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from fpl.config import load_phase2_evaluation
from fpl.types import Position
from fpl.validate.minutes_baselines import (
    STAGE_B_BASELINE_ORDER,
    HistoryRow,
    MinuteBins,
    TargetRow,
    TeamCodeMap,
    baseline_names,
    build_minutes_baselines,
    validate_minutes_inputs,
)

# A fixed, timezone-aware cutoff. History rows are before it; target rows are at/after it.
AS_OF = datetime(2025, 9, 20, 12, 0, tzinfo=UTC)


def _bins() -> MinuteBins:
    return MinuteBins.from_config(load_phase2_evaluation())


def _team_codes() -> TeamCodeMap:
    # Season-qualified (season, team_id) -> stable team_code. team_id is REUSED across seasons:
    # id 10 is club 1410 in 2024-25 and club 2020 in 2025-26 (the recurrence failure mode).
    return TeamCodeMap.from_pairs(
        [
            ("2024-25", 10, 1410),
            ("2025-26", 10, 2020),
            ("2024-25", 11, 1411),
            ("2025-26", 11, 2021),
            ("2025-26", 12, 2022),
        ]
    )


def _target(
    *,
    season: str = "2025-26",
    gw: int = 6,
    fixture: int = 60,
    kickoff: datetime,
    code: int = 1001,
    position: Position = Position.DEF,
    team_id: int = 10,
    opponent: int = 11,
    was_home: bool = True,
) -> TargetRow:
    return TargetRow(
        season=season,
        gw=gw,
        fixture=fixture,
        kickoff_time=kickoff,
        code=code,
        position=position,
        team_id=team_id,
        opponent_team_id=opponent,
        was_home=was_home,
    )


def _hist(
    *,
    season: str = "2024-25",
    gw: int = 1,
    fixture: int,
    kickoff: datetime,
    code: int = 1001,
    position: Position = Position.DEF,
    team_id: int = 10,
    opponent: int = 11,
    was_home: bool = True,
    minutes: int,
) -> HistoryRow:
    return HistoryRow(
        season=season,
        gw=gw,
        fixture=fixture,
        kickoff_time=kickoff,
        code=code,
        position=position,
        team_id=team_id,
        opponent_team_id=opponent,
        was_home=was_home,
        minutes=minutes,
    )


def _kick(month: int, day: int, hour: int = 12) -> datetime:
    return datetime(2025, month, day, hour, 0, tzinfo=UTC)


def _fit(
    history: list[HistoryRow],
    targets: list[TargetRow],
    *,
    as_of: datetime = AS_OF,
    team_codes: TeamCodeMap | None = None,
) -> list:
    """Validate (fail-closed) then build the four baselines, as the real harness must."""
    bins = _bins()
    validated_history, _validated_targets = validate_minutes_inputs(
        history, targets, as_of=as_of, team_codes=team_codes or _team_codes(), bins=bins
    )
    return build_minutes_baselines(
        validated_history, as_of=as_of, team_codes=team_codes or _team_codes(), bins=bins
    )


# --------------------------------------------------------------------------------------
# Contract names and order
# --------------------------------------------------------------------------------------


def test_baseline_names_match_contract_definitions_order() -> None:
    contract = load_phase2_evaluation()
    expected = tuple(d.name for d in contract.baselines.definitions)
    assert baseline_names() == expected
    assert baseline_names() == STAGE_B_BASELINE_ORDER
    assert baseline_names() == (
        "position_minutes_frequency",
        "last_observed_player_minutes",
        "trailing_5_player_minutes",
        "trailing_5_team_position_minutes",
    )


def test_build_returns_baselines_in_contract_order_with_matching_names() -> None:
    history = [_hist(fixture=1, kickoff=_kick(8, 10), minutes=90)]
    target = _target(kickoff=AS_OF)
    baselines = _fit(history, [target])
    assert [type(b).__name__ for b in baselines] == [
        "PositionMinutesFrequency",
        "LastObservedPlayerMinutes",
        "Trailing5PlayerMinutes",
        "Trailing5TeamPositionMinutes",
    ]
    assert [b.name for b in baselines] == list(STAGE_B_BASELINE_ORDER)


# --------------------------------------------------------------------------------------
# Target record carries EXACTLY the nine safe proxy columns and no outcome / element id
# --------------------------------------------------------------------------------------


def test_target_row_has_exactly_the_nine_safe_proxy_columns() -> None:
    fields = set(TargetRow.__slots__ or TargetRow.__dataclass_fields__)
    assert fields == {
        "season",
        "gw",
        "fixture",
        "kickoff_time",
        "code",
        "position",
        "team_id",
        "opponent_team_id",
        "was_home",
    }
    # The label and the season-scoped aliases are absent from the model-facing projection.
    for forbidden in ("minutes", "element_id", "element", "starts", "total_points"):
        assert forbidden not in fields


def test_history_row_adds_only_the_minutes_label() -> None:
    target_fields = set(TargetRow.__slots__ or TargetRow.__dataclass_fields__)
    history_fields = set(HistoryRow.__slots__ or HistoryRow.__dataclass_fields__)
    assert history_fields - target_fields == {"minutes"}


# --------------------------------------------------------------------------------------
# Config-derived four bins, including the open-ended 90 tail
# --------------------------------------------------------------------------------------


def test_bins_derived_from_config_with_open_90_tail() -> None:
    bins = _bins()
    assert bins.keys == ("0", "1_59", "60_89", "90")
    assert bins.ranges == ((0, 0), (1, 59), (60, 89), (90, None))
    assert bins.n_bins() == 4
    # Boundaries at every edge.
    assert [bins.index_of(m) for m in (0, 1, 59, 60, 89, 90)] == [0, 1, 1, 2, 2, 3]
    # The 90 bin is open-ended above: 90-or-above folds into the last bin.
    assert bins.index_of(120) == 3
    assert bins.index_of(10_000) == 3


def test_one_hot_is_unsmoothed_single_bin() -> None:
    bins = _bins()
    assert bins.one_hot(2) == (0.0, 0.0, 1.0, 0.0)
    assert sum(bins.one_hot(0)) == 1.0


# --------------------------------------------------------------------------------------
# Raw count / n: zero mass stays zero, no additive smoothing
# --------------------------------------------------------------------------------------


def test_position_frequency_is_raw_count_over_n_with_no_smoothing() -> None:
    # DEF history: two 0-minute, three 60-89 -> (0.4, 0.0, 0.6, 0.0). Empty bins stay exactly 0.
    history = [
        _hist(fixture=1, kickoff=_kick(8, 1), minutes=0),
        _hist(fixture=2, kickoff=_kick(8, 2), minutes=0),
        _hist(fixture=3, kickoff=_kick(8, 3), minutes=60),
        _hist(fixture=4, kickoff=_kick(8, 4), minutes=70),
        _hist(fixture=5, kickoff=_kick(8, 5), minutes=89),
    ]
    target = _target(kickoff=AS_OF, position=Position.DEF)
    [pos, *_] = _fit(history, [target])
    dist = pos.predict(target)
    assert dist == pytest.approx((0.4, 0.0, 0.6, 0.0))
    assert sum(dist) == pytest.approx(1.0)


def test_last_observed_is_one_hot_with_remaining_zeros() -> None:
    history = [_hist(fixture=1, kickoff=_kick(8, 1), minutes=60)]
    target = _target(kickoff=AS_OF, code=1001)
    [_pos, last, *_] = _fit(history, [target])
    assert last.predict(target) == (0.0, 0.0, 1.0, 0.0)


# --------------------------------------------------------------------------------------
# Position -> all-position -> fail-closed fallback chain
# --------------------------------------------------------------------------------------


def test_position_baseline_falls_back_to_all_position_prior() -> None:
    # FWD has no rows; DEF rows exist. FWD prediction must be the all-position (unsmoothed) prior.
    history = [
        _hist(fixture=1, kickoff=_kick(8, 1), position=Position.DEF, minutes=90),
        _hist(fixture=2, kickoff=_kick(8, 2), position=Position.DEF, minutes=0),
    ]
    target = _target(kickoff=AS_OF, position=Position.FWD)
    [pos, *_] = _fit(history, [target])
    assert pos.predict(target) == pytest.approx((0.5, 0.0, 0.0, 0.5))


def test_empty_history_fails_closed() -> None:
    target = _target(kickoff=AS_OF)
    [pos, *_] = _fit([], [target])
    with pytest.raises(ValueError, match="empty all-position prior"):
        pos.predict(target)


def test_player_baselines_cold_start_falls_back_to_position_frequency() -> None:
    # Unknown code: both code-baselines fall back to the position prior.
    history = [
        _hist(fixture=1, kickoff=_kick(8, 1), code=2002, minutes=90),
        _hist(fixture=2, kickoff=_kick(8, 2), code=2002, minutes=0),
    ]
    target = _target(kickoff=AS_OF, code=9999, position=Position.DEF)
    [pos, last, trail, _team] = _fit(history, [target])
    fallback = pos.predict(target)
    assert last.predict(target) == fallback
    assert trail.predict(target) == fallback


# --------------------------------------------------------------------------------------
# Stable code identity: last / trailing track code across seasons, input-order invariant
# --------------------------------------------------------------------------------------


def test_last_observed_picks_most_recent_across_seasons_by_kickoff() -> None:
    history = [
        _hist(season="2024-25", fixture=1, kickoff=_kick(8, 1), code=1001, minutes=0),
        _hist(season="2025-26", fixture=2, kickoff=_kick(8, 10), code=1001, minutes=90),
    ]
    target = _target(kickoff=AS_OF, code=1001)
    [_pos, last, *_] = _fit(history, [target])
    # Most recent (2025-26, 90 min) wins -> one-hot on the 90 bin.
    assert last.predict(target) == (0.0, 0.0, 0.0, 1.0)


def test_player_baselines_are_input_order_invariant() -> None:
    fwd = [
        _hist(fixture=i, kickoff=_kick(8, i), code=1001, minutes=m)
        for i, m in enumerate((0, 90, 60, 90, 70, 0), start=1)
    ]
    target = _target(kickoff=AS_OF, code=1001)
    shuffled = list(fwd)
    random.Random(202627).shuffle(shuffled)
    [pos_a, last_a, trail_a, team_a] = _fit(fwd, [target])
    [pos_b, last_b, trail_b, team_b] = _fit(shuffled, [target])
    assert last_a.predict(target) == last_b.predict(target)
    assert trail_a.predict(target) == trail_b.predict(target)
    assert pos_a.predict(target) == pos_b.predict(target)
    assert team_a.predict(target) == team_b.predict(target)


# --------------------------------------------------------------------------------------
# Zero-minute retention in the trailing-5 window
# --------------------------------------------------------------------------------------


def test_trailing_5_retains_zero_minute_rows() -> None:
    # Recent-first after sort: 60, then four 90s, then a dropped oldest. Window of 5 keeps the 60.
    history = [
        _hist(fixture=1, kickoff=_kick(8, 1), code=1001, minutes=90),  # oldest, dropped
        _hist(fixture=2, kickoff=_kick(8, 2), code=1001, minutes=90),
        _hist(fixture=3, kickoff=_kick(8, 3), code=1001, minutes=90),
        _hist(fixture=4, kickoff=_kick(8, 4), code=1001, minutes=90),
        _hist(fixture=5, kickoff=_kick(8, 5), code=1001, minutes=60),
        _hist(fixture=6, kickoff=_kick(8, 6), code=1001, minutes=0),
    ]
    target = _target(kickoff=AS_OF, code=1001)
    _position, _last, trail, _team = _fit(history, [target])
    # Window = most recent 5 -> minutes [0, 60, 90, 90, 90] -> counts (1, 0, 1, 3).
    assert trail.predict(target) == pytest.approx((0.2, 0.0, 0.2, 0.6))


# --------------------------------------------------------------------------------------
# Recency tie order: kickoff DESC, then season DESC, then fixture DESC
# --------------------------------------------------------------------------------------


def test_recency_tie_breaks_on_season_then_fixture_descending() -> None:
    same_kick = _kick(8, 15)
    history = [
        # Same kickoff, lower season + lower fixture: loses the tie to both others.
        _hist(season="2024-25", fixture=10, kickoff=same_kick, code=1001, minutes=0),
        # Same kickoff, later season, fixture 5: beats the 2024-25 row on season.
        _hist(season="2025-26", fixture=5, kickoff=same_kick, code=1001, minutes=60),
        # Same kickoff, same latest season, fixture 9: beats fixture 5 on fixture DESC.
        _hist(season="2025-26", fixture=9, kickoff=same_kick, code=1001, minutes=90),
    ]
    target = _target(kickoff=AS_OF, code=1001)
    _position, last, _trail, _team = _fit(history, [target])
    # Winner = (2025-26, fixture 9, 90 min) -> one-hot on the 90 bin.
    assert last.predict(target) == (0.0, 0.0, 0.0, 1.0)


# --------------------------------------------------------------------------------------
# Stable team_code resolution: (season, team_id) -> team_code, never a bare team_id join
# --------------------------------------------------------------------------------------


def test_team_baseline_uses_season_qualified_team_id_not_bare_id() -> None:
    # team_id 10 is club 1410 in 2024-25 and club 2020 in 2025-26. The 2025-26 target must resolve
    # to club 2020 and read ONLY 2025-26 club-2020 rows, never the 2024-25 club-1410 rows.
    history = [
        _hist(season="2024-25", fixture=1, kickoff=_kick(7, 1), team_id=10, minutes=90),
        _hist(season="2024-25", fixture=2, kickoff=_kick(7, 2), team_id=10, minutes=90),
        _hist(season="2024-25", fixture=3, kickoff=_kick(7, 3), team_id=10, minutes=90),
        _hist(season="2024-25", fixture=4, kickoff=_kick(7, 4), team_id=10, minutes=90),
        _hist(season="2024-25", fixture=5, kickoff=_kick(7, 5), team_id=10, minutes=90),
        # 2025-26 club 2020 (also team_id 10): all zero-minute.
        _hist(season="2025-26", fixture=11, kickoff=_kick(8, 11), team_id=10, minutes=0),
        _hist(season="2025-26", fixture=12, kickoff=_kick(8, 12), team_id=10, minutes=0),
        _hist(season="2025-26", fixture=13, kickoff=_kick(8, 13), team_id=10, minutes=0),
        _hist(season="2025-26", fixture=14, kickoff=_kick(8, 14), team_id=10, minutes=0),
        _hist(season="2025-26", fixture=15, kickoff=_kick(8, 15), team_id=10, minutes=0),
    ]
    target = _target(season="2025-26", kickoff=AS_OF, team_id=10, position=Position.DEF)
    [*_p, _l, _tr, team] = _fit(history, [target])
    # Club 2020 (2025-26) rows are all zero-minute -> one-hot on bin 0.
    # A bare team_id join would have mixed in the 2024-25 90-minute rows.
    assert team.predict(target) == (1.0, 0.0, 0.0, 0.0)


def test_team_baseline_resolves_transfer_target_to_destination_club() -> None:
    # Player 1001 played for club 1410 (team_id 10, 2024-25) in history. His target row is at
    # club 2022 (team_id 12, 2025-26) -- the destination. The team baseline must score him against
    # club 2022's fixtures, not his former club 1410.
    history = [
        # Former club 1410 history for this code (must NOT feed the team baseline for the target).
        _hist(season="2024-25", fixture=1, kickoff=_kick(7, 1), code=1001, team_id=10, minutes=90),
        _hist(season="2024-25", fixture=2, kickoff=_kick(7, 2), code=1001, team_id=10, minutes=90),
        # Destination club 2022 fixtures: a DEF played 0 and 90 minutes across two fixtures.
        _hist(season="2025-26", fixture=21, kickoff=_kick(8, 11), code=7777, team_id=12, minutes=0),
        _hist(
            season="2025-26", fixture=21, kickoff=_kick(8, 11), code=8888, team_id=12, minutes=90
        ),
        _hist(
            season="2025-26", fixture=22, kickoff=_kick(8, 12), code=7777, team_id=12, minutes=90
        ),
        _hist(season="2025-26", fixture=22, kickoff=_kick(8, 12), code=8888, team_id=12, minutes=0),
    ]
    target = _target(season="2025-26", kickoff=AS_OF, code=1001, team_id=12, position=Position.DEF)
    [*_p, _l, _tr, team] = _fit(history, [target])
    # Destination club 2022, target position DEF: rows 7777 across fixtures 21,22 -> (0, 90).
    assert team.predict(target) == pytest.approx((0.5, 0.0, 0.0, 0.5))


def test_team_baseline_uses_five_distinct_fixtures_and_target_position_only() -> None:
    # Six distinct club fixtures, each with one DEF row and one MID 0-minute row. The oldest
    # DEF has 0 minutes; the five recent DEFs have 90. A six-fixture implementation would
    # therefore produce 1/6 zero mass, while the exact five-fixture window is one-hot at 90.
    history: list[HistoryRow] = []
    for i in range(1, 7):
        history.append(
            _hist(
                season="2025-26",
                fixture=30 + i,
                kickoff=_kick(8, i),
                code=9000 + i,
                team_id=11,
                position=Position.DEF,
                minutes=0 if i == 1 else 90,
            )
        )
        history.append(
            _hist(
                season="2025-26",
                fixture=30 + i,
                kickoff=_kick(8, i),
                code=9100 + i,
                team_id=11,
                position=Position.MID,
                minutes=0,
            )
        )
    target = _target(season="2025-26", kickoff=AS_OF, code=1001, team_id=11, position=Position.DEF)
    [*_p, _l, _tr, team] = _fit(history, [target])
    # Five most-recent distinct DEF fixtures, all 90 -> one-hot on the 90 bin. The oldest DEF
    # and every MID row are excluded.
    assert team.predict(target) == (0.0, 0.0, 0.0, 1.0)


def test_team_baseline_falls_back_when_club_has_no_target_position_rows() -> None:
    history = [
        _hist(
            season="2025-26",
            fixture=1,
            kickoff=_kick(8, 1),
            team_id=11,
            position=Position.DEF,
            minutes=90,
        ),
        _hist(
            season="2025-26",
            fixture=2,
            kickoff=_kick(8, 2),
            team_id=11,
            position=Position.DEF,
            minutes=0,
        ),
        _hist(
            season="2025-26",
            fixture=3,
            kickoff=_kick(8, 3),
            code=2002,
            position=Position.FWD,
            minutes=90,
        ),
    ]
    target = _target(season="2025-26", kickoff=AS_OF, team_id=11, position=Position.FWD)
    [pos, *_rest, team] = _fit(history, [target])
    # Club 11 has fixtures but no FWD rows -> fallback to the all-position prior.
    assert team.predict(target) == pos.predict(target)


# --------------------------------------------------------------------------------------
# TeamCodeMap: duplicate key rejected, missing mapping rejected
# --------------------------------------------------------------------------------------


def test_team_code_map_rejects_duplicate_season_team_key() -> None:
    with pytest.raises(ValueError, match="duplicate team_code mapping"):
        TeamCodeMap.from_pairs([("2025-26", 10, 2020), ("2025-26", 10, 9999)])


def test_missing_team_mapping_for_target_is_rejected() -> None:
    target = _target(season="2025-26", kickoff=AS_OF, team_id=99)  # unmapped
    with pytest.raises(ValueError, match="no team_code mapping"):
        validate_minutes_inputs([], [target], as_of=AS_OF, team_codes=_team_codes(), bins=_bins())


# --------------------------------------------------------------------------------------
# Duplicate player-fixture grain rejection
# --------------------------------------------------------------------------------------


def test_duplicate_history_grain_is_rejected() -> None:
    history = [
        _hist(season="2024-25", fixture=7, kickoff=_kick(8, 1), code=1001, minutes=90),
        _hist(season="2024-25", fixture=7, kickoff=_kick(8, 2), code=1001, minutes=0),
    ]
    with pytest.raises(ValueError, match="duplicate history grain"):
        validate_minutes_inputs(
            history, [_target(kickoff=AS_OF)], as_of=AS_OF, team_codes=_team_codes(), bins=_bins()
        )


def test_duplicate_target_grain_is_rejected() -> None:
    t = _target(kickoff=AS_OF)
    with pytest.raises(ValueError, match="duplicate target grain"):
        validate_minutes_inputs([], [t, t], as_of=AS_OF, team_codes=_team_codes(), bins=_bins())


# --------------------------------------------------------------------------------------
# Timestamp awareness: naive history / target / as_of rejected
# --------------------------------------------------------------------------------------


def test_naive_history_kickoff_is_rejected() -> None:
    history = [_hist(fixture=1, kickoff=datetime(2025, 8, 1, 12, 0), minutes=90)]  # naive
    with pytest.raises(ValueError, match="timezone-aware"):
        validate_minutes_inputs(
            history, [_target(kickoff=AS_OF)], as_of=AS_OF, team_codes=_team_codes(), bins=_bins()
        )


def test_naive_target_kickoff_is_rejected() -> None:
    target = _target(kickoff=datetime(2025, 9, 20, 12, 0))  # naive
    with pytest.raises(ValueError, match="timezone-aware"):
        validate_minutes_inputs([], [target], as_of=AS_OF, team_codes=_team_codes(), bins=_bins())


@pytest.mark.parametrize("bad_as_of", [datetime(2025, 9, 20, 12, 0), "2025-09-20T12:00:00Z"])
def test_naive_or_non_datetime_as_of_is_rejected(bad_as_of: object) -> None:
    with pytest.raises((ValueError, TypeError)):
        validate_minutes_inputs(
            [],
            [_target(kickoff=AS_OF)],
            as_of=bad_as_of,
            team_codes=_team_codes(),
            bins=_bins(),  # type: ignore[arg-type]
        )


# --------------------------------------------------------------------------------------
# History cutoff: kickoff_time < as_of strictly (observed results only)
# --------------------------------------------------------------------------------------


def test_history_at_cutoff_is_rejected() -> None:
    # kickoff_time == as_of is NOT strictly before -> rejected.
    history = [_hist(fixture=1, kickoff=AS_OF, minutes=90)]
    with pytest.raises(ValueError, match="not observed before cutoff"):
        validate_minutes_inputs(
            history, [_target(kickoff=AS_OF)], as_of=AS_OF, team_codes=_team_codes(), bins=_bins()
        )


def test_history_after_cutoff_is_rejected() -> None:
    history = [_hist(fixture=1, kickoff=datetime(2025, 9, 21, 12, 0, tzinfo=UTC), minutes=90)]
    with pytest.raises(ValueError, match="not observed before cutoff"):
        validate_minutes_inputs(
            history, [_target(kickoff=AS_OF)], as_of=AS_OF, team_codes=_team_codes(), bins=_bins()
        )


# --------------------------------------------------------------------------------------
# Target cutoff: a target whose kickoff precedes as_of is a walk-forward inconsistency and
# MUST be rejected. (as_of is the first kickoff of the predicted gameweek; a target before it
# is from an already-observed gameweek.)
# --------------------------------------------------------------------------------------


def test_target_before_cutoff_is_rejected() -> None:
    # Target kickoff is one day BEFORE as_of: this is a past fixture, not a prediction target.
    past_target = _target(kickoff=datetime(2025, 9, 19, 12, 0, tzinfo=UTC))
    with pytest.raises((ValueError, TypeError)):
        validate_minutes_inputs(
            [], [past_target], as_of=AS_OF, team_codes=_team_codes(), bins=_bins()
        )


# --------------------------------------------------------------------------------------
# Invalid Position: a non-Position value must be rejected, not fed into a rate
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad_position", ["AM", "GKP", "GK", None, 2])
def test_invalid_position_is_rejected(bad_position: object) -> None:
    # Build directly so a raw non-Position value reaches validation untyped.
    target = TargetRow(
        season="2025-26",
        gw=6,
        fixture=60,
        kickoff_time=AS_OF,
        code=1001,
        position=bad_position,  # type: ignore[arg-type]
        team_id=10,
        opponent_team_id=11,
        was_home=True,
    )
    with pytest.raises((TypeError, ValueError)):
        validate_minutes_inputs([], [target], as_of=AS_OF, team_codes=_team_codes(), bins=_bins())


# --------------------------------------------------------------------------------------
# Minutes label validation on history: NULL / non-int / negative rejected
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "minutes",
    [None, 90.0, True, "90"],
)
def test_null_or_non_int_minutes_are_rejected(minutes: object) -> None:
    history = _hist(fixture=1, kickoff=_kick(8, 1), code=1001, minutes=90)  # type: ignore[arg-type]
    history = HistoryRow(
        season="2024-25",
        gw=1,
        fixture=1,
        kickoff_time=_kick(8, 1),
        code=1001,
        position=Position.DEF,
        team_id=10,
        opponent_team_id=11,
        was_home=True,
        minutes=minutes,  # type: ignore[arg-type]
    )
    with pytest.raises((TypeError, ValueError)):
        validate_minutes_inputs(
            [history], [_target(kickoff=AS_OF)], as_of=AS_OF, team_codes=_team_codes(), bins=_bins()
        )


def test_negative_minutes_are_rejected() -> None:
    history = _hist(fixture=1, kickoff=_kick(8, 1), code=1001, minutes=-5)
    with pytest.raises(ValueError, match="outside every configured minute bin"):
        validate_minutes_inputs(
            [history], [_target(kickoff=AS_OF)], as_of=AS_OF, team_codes=_team_codes(), bins=_bins()
        )
