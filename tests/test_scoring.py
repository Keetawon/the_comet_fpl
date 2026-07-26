"""Scoring calculator: unit rules plus the full-season replay.

The replay is the Phase 0 exit criterion. It reads recorded `total_points` from
`stg_player_fixture` -- the only place it lives -- because the replay validates ingest and
the calculator together, which is a staging concern rather than a mart one.
"""

from __future__ import annotations

import duckdb
import pytest

from fpl.config import load_scoring_rules
from fpl.models.scoring import calculate_points, decompose_points
from fpl.types import PlayerMatchStats, Position

RULES_2025_26 = load_scoring_rules("2025_26")
RULES_2026_27 = load_scoring_rules("2026_27")

# Row count of the 2025-26 season after deduplication (29,757 landed - 10 exact duplicates).
SEASON_2025_26_ROWS = 29_747


def stats(**overrides: int | None) -> PlayerMatchStats:
    """A zeroed stat line, so each test states only the field it is about."""
    base: dict[str, int | None] = {
        "minutes": 0,
        "goals_scored": 0,
        "assists": 0,
        "clean_sheets": 0,
        "goals_conceded": 0,
        "saves": 0,
        "penalties_saved": 0,
        "penalties_missed": 0,
        "own_goals": 0,
        "yellow_cards": 0,
        "red_cards": 0,
        "bonus": 0,
        "defensive_contribution": None,
    }
    base.update(overrides)
    return PlayerMatchStats(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# Appearance points: a step function at exactly 60 minutes (R3)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [(0, 0), (1, 1), (59, 1), (60, 2), (89, 2), (90, 2), (120, 2)],
)
def test_appearance_points_step_at_60(minutes: int, expected: int) -> None:
    assert calculate_points(stats(minutes=minutes), RULES_2026_27, Position.MID) == expected


# --------------------------------------------------------------------------------------
# Goals, assists, clean sheets
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("position", "expected"),
    [(Position.GK, 10), (Position.DEF, 6), (Position.MID, 5), (Position.FWD, 4)],
)
def test_goal_value_by_position(position: Position, expected: int) -> None:
    scored = calculate_points(stats(minutes=90, goals_scored=1), RULES_2026_27, position)
    blank = calculate_points(stats(minutes=90), RULES_2026_27, position)
    assert scored - blank == expected


def test_gk_goal_value_is_untested_against_real_data(db: duckdb.DuckDBPyConnection) -> None:
    """The GK goal value of 10 is unvalidated: no goalkeeper has scored in the data.

    This test does not check that 10 is correct -- nothing available can. It pins the
    reason, so the day a goalkeeper scores, this fails and tells the next reader that the
    branch has finally become exercisable.
    """
    row = db.execute(
        """
        SELECT coalesce(sum(goals_scored), 0) FROM mart_fact_player_fixture
        WHERE position = 'GK'
        """
    ).fetchone()
    assert row is not None
    assert row[0] == 0, (
        "a goalkeeper has now scored -- the GK goal value of 10 is finally exercisable by "
        "the replay, so remove goals_scored.GK from the `unverified` block of the scoring "
        "configs and assert it directly"
    )


def test_assist_value_is_position_independent() -> None:
    for position in Position:
        scored = calculate_points(stats(minutes=90, assists=1), RULES_2026_27, position)
        blank = calculate_points(stats(minutes=90), RULES_2026_27, position)
        assert scored - blank == 3


@pytest.mark.parametrize(
    ("position", "expected"),
    [(Position.GK, 4), (Position.DEF, 4), (Position.MID, 1), (Position.FWD, 0)],
)
def test_clean_sheet_value_by_position(position: Position, expected: int) -> None:
    with_cs = calculate_points(stats(minutes=90, clean_sheets=1), RULES_2026_27, position)
    without = calculate_points(stats(minutes=90), RULES_2026_27, position)
    assert with_cs - without == expected


def test_clean_sheet_requires_60_minutes() -> None:
    """A clean sheet at 59 minutes pays nothing -- another exact threshold."""
    at_59 = calculate_points(stats(minutes=59, clean_sheets=1), RULES_2026_27, Position.DEF)
    at_60 = calculate_points(stats(minutes=60, clean_sheets=1), RULES_2026_27, Position.DEF)
    assert at_59 == 1  # short appearance only
    assert at_60 == 6  # long appearance + clean sheet


# --------------------------------------------------------------------------------------
# Goals conceded and saves: integer division, position-restricted
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("conceded", "expected_penalty"),
    [(0, 0), (1, 0), (2, -1), (3, -1), (4, -2), (5, -2), (6, -3)],
)
def test_goals_conceded_is_minus_one_per_two(conceded: int, expected_penalty: int) -> None:
    """-1 per 2 conceded, floored. 3 conceded costs 1 point, not 1.5.

    Exactly why R3 forbids computing points from an expected goals-conceded: the mean does
    not determine this, and it does not determine the clean-sheet probability either.
    """
    for position in (Position.GK, Position.DEF):
        base = calculate_points(stats(minutes=90), RULES_2026_27, position)
        got = calculate_points(stats(minutes=90, goals_conceded=conceded), RULES_2026_27, position)
        assert got - base == expected_penalty


def test_goals_conceded_does_not_penalise_mid_or_fwd() -> None:
    for position in (Position.MID, Position.FWD):
        base = calculate_points(stats(minutes=90), RULES_2026_27, position)
        got = calculate_points(stats(minutes=90, goals_conceded=6), RULES_2026_27, position)
        assert got == base


@pytest.mark.parametrize(
    ("saves", "expected"), [(0, 0), (1, 0), (2, 0), (3, 1), (5, 1), (6, 2), (9, 3)]
)
def test_saves_are_one_per_three_gk_only(saves: int, expected: int) -> None:
    base = calculate_points(stats(minutes=90), RULES_2026_27, Position.GK)
    got = calculate_points(stats(minutes=90, saves=saves), RULES_2026_27, Position.GK)
    assert got - base == expected
    # An outfield player's `saves` never scores.
    assert calculate_points(
        stats(minutes=90, saves=saves), RULES_2026_27, Position.DEF
    ) == calculate_points(stats(minutes=90), RULES_2026_27, Position.DEF)


# --------------------------------------------------------------------------------------
# Cards -- the Barnes case
# --------------------------------------------------------------------------------------


def test_cards_are_not_gated_on_minutes() -> None:
    """FPL scores a booking for an unused substitute.

    Gating cards behind `minutes > 0` is the single difference between a 100.000% replay
    and a 99.997% one. See the regression test below for the row that proves it.
    """
    assert calculate_points(stats(minutes=0, yellow_cards=1), RULES_2026_27, Position.FWD) == -1
    assert calculate_points(stats(minutes=0, red_cards=1), RULES_2026_27, Position.FWD) == -3


def test_ashley_barnes_gw22_regression(db: duckdb.DuckDBPyConnection) -> None:
    """The exact 2025-26 row that distinguishes a correct calculator.

    Ashley Barnes, GW22: 0 minutes, 1 yellow card, bps -3, recorded total_points -1. Booked
    as an unused substitute. Pinned by identity, not by index, so it survives a rebuild.
    """
    row = db.execute(
        """
        SELECT s.minutes, s.yellow_cards, s.red_cards, s.bps, s.total_points, s.position
        FROM stg_player_fixture AS s
        JOIN stg_player AS p ON p.season = s.season AND p.element = s.element
        WHERE s.season = '2025-26' AND s.gw = 22 AND s.minutes = 0 AND s.total_points <> 0
        """
    ).fetchall()
    assert len(row) == 1, f"expected exactly one zero-minute scoring row in 2025-26 GW22, got {row}"
    minutes, yellows, reds, bps, recorded, position = row[0]
    assert (minutes, yellows, reds, bps, recorded) == (0, 1, 0, -3, -1)

    computed = calculate_points(
        stats(minutes=minutes, yellow_cards=yellows, red_cards=reds),
        RULES_2025_26,
        Position(position),
    )
    assert computed == recorded == -1


# --------------------------------------------------------------------------------------
# Defensive contribution: rules-gated AND stat-gated
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("position", "count", "expected"),
    [
        (Position.DEF, 9, 0),
        (Position.DEF, 10, 2),
        (Position.DEF, 21, 2),
        (Position.MID, 11, 0),
        (Position.MID, 12, 2),
        (Position.FWD, 11, 0),
        (Position.FWD, 12, 2),
    ],
)
def test_defensive_contribution_thresholds(position: Position, count: int, expected: int) -> None:
    """DEF pays at 10, MID and FWD at 12. Forwards already earned this in 2025-26."""
    base = calculate_points(stats(minutes=90), RULES_2026_27, position)
    got = calculate_points(stats(minutes=90, defensive_contribution=count), RULES_2026_27, position)
    assert got - base == expected


def test_goalkeepers_never_earn_defensive_contribution() -> None:
    base = calculate_points(stats(minutes=90), RULES_2026_27, Position.GK)
    got = calculate_points(stats(minutes=90, defensive_contribution=30), RULES_2026_27, Position.GK)
    assert got == base


def test_null_defensive_contribution_is_not_zero() -> None:
    """A NULL DC scores nothing, but for a different reason than a zero does.

    Both score 0 points here, so this test exists to pin that NULL does not raise, is not
    coerced, and is distinguishable downstream -- the seasons before 2025-26 have no DC
    measurement at all, and treating that as "made no defensive actions" would bias every
    defender's rate.
    """
    unmeasured = stats(minutes=90, defensive_contribution=None)
    measured_zero = stats(minutes=90, defensive_contribution=0)
    assert calculate_points(unmeasured, RULES_2026_27, Position.DEF) == 2
    assert calculate_points(measured_zero, RULES_2026_27, Position.DEF) == 2
    assert unmeasured.defensive_contribution is None
    assert measured_zero.defensive_contribution == 0


# --------------------------------------------------------------------------------------
# Breakdown and bonus
# --------------------------------------------------------------------------------------


def test_breakdown_sums_to_total() -> None:
    line = stats(
        minutes=90,
        goals_scored=2,
        assists=1,
        clean_sheets=1,
        goals_conceded=0,
        yellow_cards=1,
        bonus=3,
        defensive_contribution=11,
    )
    breakdown = decompose_points(line, RULES_2026_27, Position.MID)
    assert breakdown.total == calculate_points(line, RULES_2026_27, Position.MID)
    assert breakdown.as_dict() == {
        "appearance": 2,
        "goals": 10,
        "assists": 3,
        "clean_sheet": 1,
        "goals_conceded": 0,
        "saves": 0,
        "penalties_saved": 0,
        "penalties_missed": 0,
        "own_goals": 0,
        "cards": -1,
        "defensive_contribution": 0,  # MID needs 12, had 11
        "bonus": 3,
    }


def test_bonus_is_passed_through_not_derived() -> None:
    """Phase 0 passes recorded bonus through; deriving it is Stage D only."""
    assert RULES_2026_27.bonus.mode == "passthrough"
    with_bonus = calculate_points(stats(minutes=90, bonus=3), RULES_2026_27, Position.MID)
    without = calculate_points(stats(minutes=90), RULES_2026_27, Position.MID)
    assert with_bonus - without == 3


def test_penalties_and_own_goals() -> None:
    base = calculate_points(stats(minutes=90), RULES_2026_27, Position.GK)
    assert (
        calculate_points(stats(minutes=90, penalties_saved=1), RULES_2026_27, Position.GK) - base
        == 5
    )
    assert (
        calculate_points(stats(minutes=90, penalties_missed=1), RULES_2026_27, Position.FWD)
        - calculate_points(stats(minutes=90), RULES_2026_27, Position.FWD)
        == -2
    )
    assert (
        calculate_points(stats(minutes=90, own_goals=1), RULES_2026_27, Position.DEF)
        - calculate_points(stats(minutes=90), RULES_2026_27, Position.DEF)
        == -2
    )


# --------------------------------------------------------------------------------------
# THE REPLAY -- Phase 0 exit criterion
# --------------------------------------------------------------------------------------


@pytest.mark.archive
def test_replay_2025_26_reproduces_every_recorded_total(db: duckdb.DuckDBPyConnection) -> None:
    """Replay the whole 2025-26 season: components + that season's rules == recorded points.

    The specification's target is 99.997% (29,746/29,747), treating one row as an
    unreproducible glitch. That row -- Ashley Barnes, GW22 -- is in fact reproducible once
    card points are not gated on minutes, so this asserts **exact** equality on all 29,747
    rows. Anything less is a bug in the calculator, not a tolerance to loosen.
    """
    rows = db.execute(
        """
        SELECT position, minutes, goals_scored, assists, clean_sheets, goals_conceded, saves,
               penalties_saved, penalties_missed, own_goals, yellow_cards, red_cards, bonus,
               defensive_contribution, total_points, element, fixture
        FROM stg_player_fixture WHERE season = '2025-26'
        """
    ).fetchall()
    assert len(rows) == SEASON_2025_26_ROWS

    mismatches: list[tuple[int, int, int, int]] = []
    for row in rows:
        line = PlayerMatchStats(
            minutes=row[1],
            goals_scored=row[2],
            assists=row[3],
            clean_sheets=row[4],
            goals_conceded=row[5],
            saves=row[6],
            penalties_saved=row[7],
            penalties_missed=row[8],
            own_goals=row[9],
            yellow_cards=row[10],
            red_cards=row[11],
            bonus=row[12],
            defensive_contribution=row[13],
        )
        computed = calculate_points(line, RULES_2025_26, Position(row[0]))
        if computed != row[14]:
            mismatches.append((row[15], row[16], computed, row[14]))

    assert not mismatches, (
        f"{len(mismatches)} of {len(rows)} rows failed to replay "
        f"({100 * (1 - len(mismatches) / len(rows)):.5f}% matched). "
        f"First 5 (element, fixture, computed, recorded): {mismatches[:5]}"
    )


@pytest.mark.archive
def test_replay_every_season_under_its_contemporaneous_rules(
    db: duckdb.DuckDBPyConnection,
) -> None:
    """All five seasons replay exactly, not just 2025-26.

    This works because `defensive_contribution` is NULL before 2025-26 rather than zero: the
    2025-26 ruleset applied to an earlier season therefore awards no DC, which is what that
    season's rules did. It is a strong end-to-end check on the null-vs-zero handling -- had
    the DC column been zero-filled, the pre-2025-26 seasons would still replay, but a
    genuinely-zero DC would have become indistinguishable from an unmeasured one.
    """
    rows = db.execute(
        """
        SELECT season,
               count(*) AS n,
               sum(CASE WHEN total_points_as_recorded = points_under_rules_2025_26
                        THEN 1 ELSE 0 END) AS matched
        FROM mart_target_player_fixture GROUP BY season ORDER BY season
        """
    ).fetchall()
    assert rows, "no target rows"
    for season, total, matched in rows:
        assert matched == total, f"{season}: only {matched}/{total} replayed"


@pytest.mark.archive
def test_recomputed_target_differs_from_recorded_where_rules_changed(
    db: duckdb.DuckDBPyConnection,
) -> None:
    """R1 made concrete: 2026/27 rules on pre-2025-26 data are NOT the recorded points.

    The recorded column and the recomputed column must not be interchangeable, or the whole
    target split would be pointless. They diverge exactly where a ruleset needs a component
    the season did not measure -- which is what `mart_target_completeness` records.
    """
    incomplete = db.execute(
        """
        SELECT season, missing_components FROM mart_target_completeness
        WHERE ruleset_id = '2026_27' AND NOT is_complete ORDER BY season
        """
    ).fetchall()
    assert incomplete, "expected pre-2025-26 seasons to lack defensive_contribution"
    for _, missing in incomplete:
        assert "defensive_contribution" in missing

    complete = db.execute(
        """
        SELECT season FROM mart_target_completeness
        WHERE ruleset_id = '2026_27' AND is_complete ORDER BY season
        """
    ).fetchall()
    assert [row[0] for row in complete] == ["2025-26"]
