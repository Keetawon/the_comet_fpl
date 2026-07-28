"""Walk-forward fold construction: observed gameweeks, cutoffs, leakage, promotion.

These run against the built archive because the properties being asserted are properties of
the real season calendar -- a synthetic fixture list would simply reproduce whatever
assumption was written into it, including the contiguous-gameweek one this file exists to
rule out.
"""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import pairwise

import duckdb
import pytest

from fpl.config import load_phase1_evaluation
from fpl.validate.folds import (
    Fold,
    assert_no_leakage,
    generate_folds,
    observed_gameweeks,
    promoted_team_codes,
)

pytestmark = pytest.mark.archive

SEASONS = ("2021-22", "2022-23", "2023-24", "2024-25", "2025-26")

# Observed gameweeks per season, measured. 2022-23 has 37: gameweek 7 was cancelled after the
# death of Queen Elizabeth II and its fixtures were redistributed.
OBSERVED_GAMEWEEK_COUNTS = {
    "2021-22": 38,
    "2022-23": 37,
    "2023-24": 38,
    "2024-25": 38,
    "2025-26": 38,
}

TOTAL_OBSERVED = sum(OBSERVED_GAMEWEEK_COUNTS.values())  # 189


def test_observed_gameweek_counts_match_the_calendar(db: duckdb.DuckDBPyConnection) -> None:
    for season, expected in OBSERVED_GAMEWEEK_COUNTS.items():
        gameweeks = observed_gameweeks(db, season)
        assert len(gameweeks) == expected, season
        assert gameweeks == sorted(gameweeks), f"{season} gameweeks came back unordered"


def test_2022_23_is_missing_gameweek_seven(db: duckdb.DuckDBPyConnection) -> None:
    """The single fact that makes `range(1, 39)` wrong.

    Gameweek 7 of 2022-23 was cancelled and its fixtures redistributed. A contiguous
    assumption would predict a gameweek that never happened and shift every later split.
    """
    gameweeks = observed_gameweeks(db, "2022-23")
    assert 7 not in gameweeks
    assert 6 in gameweeks and 8 in gameweeks
    assert max(gameweeks) == 38, "the season still ends at 38 despite having 37 gameweeks"


def test_fold_count_is_every_observed_gameweek_after_the_warm_up(
    db: duckdb.DuckDBPyConnection,
) -> None:
    minimum = load_phase1_evaluation().training.minimum_observed_gameweeks
    folds = generate_folds(db)
    assert len(folds) == TOTAL_OBSERVED - minimum == 181


def test_the_warm_up_is_counted_across_seasons_not_within_them(
    db: duckdb.DuckDBPyConnection,
) -> None:
    """The bug this policy exists to prevent.

    Counting `minimum_observed_gameweeks` within each season drops every season's opening
    eight gameweeks -- which is precisely the cold-start regime the promoted-team prior
    exists for, and precisely the horizon a manager needs when picking an opening squad.
    Under that policy the promoted baseline scored identically to the league baseline,
    because its cold-start branch never fired on a scored row.

    Only the earliest season should lose gameweeks; every later season must start at 1.
    """
    folds = generate_folds(db)
    first_gw = {season: min(f.gw for f in folds if f.season == season) for season in SEASONS}
    assert first_gw["2021-22"] == 9
    for season in SEASONS[1:]:
        assert first_gw[season] == 1, f"{season} lost its opening gameweeks to the warm-up"


def test_every_season_is_represented(db: duckdb.DuckDBPyConnection) -> None:
    folds = generate_folds(db)
    assert {fold.season for fold in folds} == set(SEASONS)
    counts = {season: sum(1 for f in folds if f.season == season) for season in SEASONS}
    assert counts == {
        "2021-22": 30,  # 38 observed, 8 spent on the warm-up
        "2022-23": 37,
        "2023-24": 38,
        "2024-25": 38,
        "2025-26": 38,
    }


def test_folds_are_ordered_and_indexed_from_one(db: duckdb.DuckDBPyConnection) -> None:
    folds = generate_folds(db)
    assert [fold.index for fold in folds] == list(range(1, len(folds) + 1))
    for season in SEASONS:
        in_season = [fold for fold in folds if fold.season == season]
        assert [f.gw for f in in_season] == sorted(f.gw for f in in_season)
        assert [f.as_of for f in in_season] == sorted(f.as_of for f in in_season)


def test_every_cutoff_is_timezone_aware_utc(db: duckdb.DuckDBPyConnection) -> None:
    """A naive cutoff would compare against timezone-aware kickoffs machine-dependently."""
    for fold in generate_folds(db):
        assert fold.as_of.tzinfo is not None, fold
        assert fold.as_of.utcoffset() == UTC.utcoffset(None), fold


def test_no_fold_leaks_its_own_gameweek(db: duckdb.DuckDBPyConnection) -> None:
    """`require_zero_leakage_failures`, exercised on every fold rather than a sample.

    The cutoff is the gameweek's first kickoff, so a strict `<` excludes the whole gameweek
    including the earliest match. Using `<=` would leak exactly one fixture per fold.
    """
    for fold in generate_folds(db):
        assert_no_leakage(db, fold)


def test_assert_no_leakage_fires_when_the_cutoff_is_moved_forward(
    db: duckdb.DuckDBPyConnection,
) -> None:
    """The assertion has to be capable of failing, or it asserts nothing."""
    fold = generate_folds(db)[0]
    leaky = Fold(
        index=fold.index,
        season=fold.season,
        gw=fold.gw,
        as_of=datetime(2030, 1, 1, tzinfo=UTC),
        prior_gameweeks_in_season=fold.prior_gameweeks_in_season,
        team_fixtures=fold.team_fixtures,
    )
    with pytest.raises(AssertionError, match="visible to training"):
        assert_no_leakage(db, leaky)


def test_fold_team_fixture_counts_are_plausible(db: duckdb.DuckDBPyConnection) -> None:
    """Twenty team-fixtures in an ordinary gameweek; more in a double, fewer in a blank."""
    folds = generate_folds(db)
    assert sum(fold.team_fixtures for fold in folds) > 0
    for fold in folds:
        assert 0 < fold.team_fixtures <= 40, fold


# --------------------------------------------------------------------------------------
# Promotion, resolved through the only stable club identity
# --------------------------------------------------------------------------------------


def test_three_clubs_are_promoted_into_every_season_after_the_first(
    db: duckdb.DuckDBPyConnection,
) -> None:
    promoted = promoted_team_codes(db)
    assert promoted["2021-22"] == frozenset(), "the earliest season has no predecessor"
    for season in SEASONS[1:]:
        assert len(promoted[season]) == 3, f"{season}: {sorted(promoted[season])}"


def test_promotion_is_resolved_by_team_code_not_team_id(
    db: duckdb.DuckDBPyConnection,
) -> None:
    """The reason `team_id` may never be used as a cross-season club identity.

    Team id 17 is a different club in every one of the five seasons: Spurs, Southampton,
    Sheffield United, Southampton again, Sunderland. Any promotion logic keyed on the id
    would be wrong in both directions -- and would look like a club that persisted across a
    season it was absent for.
    """
    rows = db.execute(
        "SELECT season, team_code FROM mart_dim_team WHERE team_id = 17 ORDER BY season"
    ).fetchall()
    codes = dict(rows)
    assert codes == {
        "2021-22": 6,  # Spurs
        "2022-23": 20,  # Southampton
        "2023-24": 49,  # Sheffield United
        "2024-25": 20,  # Southampton
        "2025-26": 56,  # Sunderland
    }

    promoted = promoted_team_codes(db)
    # Answers are in team_code, so the same id resolves to a different verdict each season.
    assert codes["2022-23"] not in promoted["2022-23"], "Southampton were up the season before"
    assert codes["2023-24"] in promoted["2023-24"], "Sheffield United came up"
    assert codes["2024-25"] in promoted["2024-25"], "Southampton came back up"
    assert codes["2025-26"] in promoted["2025-26"], "Sunderland came up"


def test_promoted_clubs_were_absent_from_the_previous_season(
    db: duckdb.DuckDBPyConnection,
) -> None:
    """The definition itself, restated as a query so the implementation cannot drift."""
    promoted = promoted_team_codes(db)
    codes_by_season = {
        season: {
            row[0]
            for row in db.execute(
                "SELECT team_code FROM mart_dim_team WHERE season = ?", [season]
            ).fetchall()
        }
        for season in SEASONS
    }
    for previous, current in pairwise(SEASONS):
        assert promoted[current] == codes_by_season[current] - codes_by_season[previous]
