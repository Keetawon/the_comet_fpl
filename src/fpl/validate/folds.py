"""Walk-forward folds over *observed* gameweeks.

One fold per gameweek: train on everything that had kicked off before that gameweek's
deadline, predict every team-fixture in it, advance. Never a random split.

Two details that are easy to get wrong and are therefore enforced here rather than left to
each caller:

  * Gameweeks are iterated from the values present in the facts, never `range(1, 39)`.
    2022-23 has no gameweek 7 -- it was cancelled and its fixtures redistributed -- so a
    contiguity assumption silently mis-aligns the split by one for that whole season.
  * The cutoff is the first kickoff of the gameweek. The archive carries no deadline
    timestamps, and the real FPL deadline sits about ninety minutes earlier, so this is the
    latest defensible instant: with a strict `kickoff_time < as_of` filter it excludes every
    match of the gameweek being predicted, including the earliest one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise

import duckdb
import polars as pl

from fpl.config import Phase1EvaluationConfig, load_phase1_evaluation


@dataclass(frozen=True, slots=True)
class Fold:
    """One walk-forward step: predict `season`/`gw` using only data before `as_of`."""

    index: int
    season: str
    gw: int
    as_of: datetime
    prior_gameweeks_in_season: int
    team_fixtures: int

    def __str__(self) -> str:
        return f"fold {self.index:3d}  {self.season} GW{self.gw:2d}  as_of={self.as_of:%Y-%m-%d}"


def observed_gameweeks(con: duckdb.DuckDBPyConnection, season: str) -> list[int]:
    """Gameweeks that actually exist in the facts for a season, in order.

    2022-23 returns 37 values with 7 absent.
    """
    return [
        int(row[0])
        for row in con.execute(
            """
            SELECT DISTINCT gw FROM mart_fact_team_match
            WHERE season = ? ORDER BY gw
            """,
            [season],
        ).fetchall()
    ]


def generate_folds(
    con: duckdb.DuckDBPyConnection, config: Phase1EvaluationConfig | None = None
) -> list[Fold]:
    """Every scoreable walk-forward fold across the archive.

    A gameweek becomes a fold once the *training window* holds at least
    `training.minimum_observed_gameweeks` observed gameweeks, counted across seasons because
    the window is expanding. In practice that excludes only the first eight gameweeks of the
    earliest season, where there is no history at all.

    Counting within the season instead would be a serious mistake, and was the first thing
    written here. It silently drops every season's opening eight gameweeks from evaluation --
    which is exactly the cold-start regime the promoted-team prior exists for, and exactly the
    horizon a manager needs when picking an opening squad. Under that policy the promoted
    baseline scored identically to the league baseline, because its cold-start branch never
    fired on any scored row.
    """
    resolved = config or load_phase1_evaluation()
    minimum = resolved.training.minimum_observed_gameweeks

    seasons = [
        str(row[0])
        for row in con.execute(
            "SELECT DISTINCT season FROM mart_fact_team_match ORDER BY season"
        ).fetchall()
    ]

    folds: list[Fold] = []
    gameweeks_before: dict[str, int] = {}
    completed = 0
    for season in seasons:
        gameweeks_before[season] = completed
        completed += len(observed_gameweeks(con, season))

    for season in seasons:
        gameweeks = observed_gameweeks(con, season)
        for position, gw in enumerate(gameweeks):
            if gameweeks_before[season] + position < minimum:
                continue
            # Read through Arrow rather than `fetchone`: DuckDB's Python conversion of a
            # TIMESTAMPTZ requires pytz, which this project does not depend on, while the
            # Arrow path carries the timezone natively.
            frame = con.execute(
                """
                SELECT min(kickoff_time) AS as_of, count(*) AS team_fixtures
                FROM mart_fact_team_match WHERE season = ? AND gw = ?
                """,
                [season, gw],
            ).pl()
            if frame.is_empty() or frame["as_of"][0] is None:
                continue
            folds.append(
                Fold(
                    index=len(folds) + 1,
                    season=season,
                    gw=gw,
                    as_of=frame["as_of"][0],
                    prior_gameweeks_in_season=position,
                    team_fixtures=int(frame["team_fixtures"][0]),
                )
            )
    return folds


def assert_no_leakage(con: duckdb.DuckDBPyConnection, fold: Fold) -> None:
    """The fold's own matches must be invisible to its training window.

    Cheap enough to run on every fold, and it is the assertion the promotion gate's
    `require_zero_leakage_failures` is about.
    """
    leaked = con.execute(
        """
        SELECT count(*) AS leaked FROM mart_fact_team_match
        WHERE season = ? AND gw = ? AND kickoff_time < ?
        """,
        [fold.season, fold.gw, fold.as_of],
    ).pl()["leaked"][0]
    if leaked:
        raise AssertionError(
            f"{fold}: {leaked} of the gameweek's own team-fixtures fall before as_of, so "
            "they would be visible to training"
        )


def promoted_team_codes(con: duckdb.DuckDBPyConnection) -> dict[str, frozenset[int]]:
    """Season -> `team_code` of clubs that were not in the league the previous season.

    Both the question and the answer are in `team_code`, the only stable club identity across
    seasons. Returning team ids instead would hand a caller a key that is only valid inside
    one season, which is how the same mistake gets made one layer down.

    The earliest season has no predecessor and therefore reports no promoted clubs.
    """
    frame = con.execute(
        """
        SELECT season, team_id, team_code FROM mart_dim_team
        WHERE team_code IS NOT NULL ORDER BY season
        """
    ).pl()
    seasons = sorted(set(frame["season"].to_list()))
    by_season = {season: frame.filter(pl.col("season") == season) for season in seasons}
    promoted: dict[str, frozenset[int]] = {seasons[0]: frozenset()} if seasons else {}
    for previous, current in pairwise(seasons):
        before = set(by_season[previous]["team_code"].to_list())
        promoted[current] = frozenset(
            int(row["team_code"])
            for row in by_season[current].iter_rows(named=True)
            if row["team_code"] not in before
        )
    return promoted
