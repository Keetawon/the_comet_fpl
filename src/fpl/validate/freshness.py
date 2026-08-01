"""Read-time freshness gate for prospective forecasts (Phase 0b P1).

Capture and load already fail loud, but the read path never checked that a capture covering the
most recent completed gameweek actually existed -- a missing or stale player-history capture
failed *safe but silently*: `PointInTimeView` returned whatever had ``known_at <= as_of`` and the
prospective job predicted on older history instead of refusing. This module is the fail-loud gate
for the one prospective path. It is additive: it changes no capture/load code, no model, and no
frozen evaluation contract.

The gate answers one question: has the current season's most-recent-completed gameweek been
captured into the versioned per-fixture live table by ``as_of``? It does not touch the archive or
any walk-forward fold. Season start is a legitimate cold start and MUST pass: at a pre-season or
GW1 deadline there is no completed current-season fixture, so the most recent completed gameweek
is a prior-season one whose history lives in the archive -- not the live table -- and requiring a
live capture for it would fail a valid cold-start forecast.

This module deliberately lives in ``validate/`` rather than ``features/``: it takes a raw
connection and issues its own SQL against the versioned schedule, which R4's static AST guard
(``tests/test_point_in_time.py``) forbids for any module under ``features/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final

import duckdb

# The versioned schedule. Only this staging table carries the per-fixture `finished` flag and the
# bitemporal `(known_at, capture_id)` pair; `mart_team_fixture_live` carries neither `finished`
# nor the team-neutral grain the gate needs.
_FIXTURE_VERSION_TABLE: Final[str] = "stg_live_fixture_version"
# The versioned per-fixture live table -- the source the gate requires a capture from.
_PLAYER_FIXTURE_LIVE_TABLE: Final[str] = "mart_fact_player_fixture_live"
# The archive. A season present here is a completed prior season (cold start), not a live one.
_ARCHIVE_TABLE: Final[str] = "mart_fact_player_fixture"


@dataclass(frozen=True, slots=True)
class FreshnessAssessment:
    """The outcome of the freshness gate at one ``as_of``.

    ``covered`` is the pass/fail bit the caller acts on. ``cold_start`` distinguishes the two
    pass cases -- a genuine current-season capture (``cold_start=False``) vs. season start where
    no current-season gameweek has completed yet or the most-recent-completed one belongs to a
    prior archived season (``cold_start=True``). The uncovered ``(season, gw)`` is populated only
    when ``covered`` is False.
    """

    as_of: datetime
    most_recent_completed_season: str | None
    most_recent_completed_gw: int | None
    cold_start: bool
    covered: bool
    capture_known_at: datetime | None
    uncovered_season: str | None
    uncovered_gw: int | None

    def message(self) -> str:
        """The human-readable failure diagnostic (only meaningful when ``covered`` is False)."""
        seen = self.capture_known_at.isoformat() if self.capture_known_at is not None else "none"
        return (
            f"prospective freshness gate failed: current-season gameweek "
            f"{self.uncovered_season} GW{self.uncovered_gw} has no player-history capture with "
            f"known_at <= {self.as_of.isoformat()}; newest live capture known_at <= as_of: {seen}. "
            "Load the latest player-history snapshot before emitting a forecast."
        )


class FreshnessError(RuntimeError):
    """The prospective freshness gate failed: a current-season gameweek is not yet captured."""

    def __init__(self, assessment: FreshnessAssessment) -> None:
        self.assessment = assessment
        super().__init__(assessment.message())


def _has_table(con: duckdb.DuckDBPyConnection, table: str) -> bool:
    row = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [table]
    ).fetchone()
    return bool(row and row[0])


def _most_recent_completed(
    con: duckdb.DuckDBPyConnection, *, as_of: datetime
) -> tuple[str, int] | None:
    """The ``(season, gw)`` of the newest completed fixture known at or before ``as_of``.

    Takes the newest version per ``(season, fixture)`` with ``known_at <= as_of`` and, among those
    marked finished and kicked off before ``as_of``, returns the latest by kickoff. Returns
    ``None`` when the versioned schedule is absent or holds no such fixture (season start).
    """
    if not _has_table(con, _FIXTURE_VERSION_TABLE):
        return None
    row = con.execute(
        f"""
        WITH ranked AS (
            SELECT season, gw, kickoff_time, finished,
                   row_number() OVER (
                       PARTITION BY season, fixture
                       ORDER BY known_at DESC, capture_id DESC
                   ) AS version_rank
            FROM {_FIXTURE_VERSION_TABLE}
            WHERE known_at <= ?
        )
        SELECT season, gw
        FROM ranked
        WHERE version_rank = 1 AND finished = TRUE AND kickoff_time < ? AND gw IS NOT NULL
        ORDER BY kickoff_time DESC, gw DESC
        LIMIT 1
        """,
        [as_of, as_of],
    ).fetchone()
    if row is None:
        return None
    return str(row[0]), int(row[1])


def _season_in_archive(con: duckdb.DuckDBPyConnection, season: str) -> bool:
    """True if the season is a completed prior season present in the archive."""
    if not _has_table(con, _ARCHIVE_TABLE):
        return False
    row = con.execute(
        f"SELECT 1 FROM {_ARCHIVE_TABLE} WHERE season = ? LIMIT 1", [season]
    ).fetchone()
    return row is not None


def _overall_capture_known_at(
    con: duckdb.DuckDBPyConnection, *, as_of: datetime
) -> datetime | None:
    """The newest player-history capture ``known_at <= as_of`` (None if the live table is empty).

    A single staleness figure for the failure diagnostic: the freshest live data visible at the
    deadline. A capture existing only with ``known_at > as_of`` does not count -- it is not known
    at the deadline and is never credited.
    """
    if not _has_table(con, _PLAYER_FIXTURE_LIVE_TABLE):
        return None
    # Arrow/Polars path, not fetchone(): DuckDB's TIMESTAMPTZ -> Python conversion needs pytz
    # (absent here), while Arrow carries the timezone natively. Same reason the harness reads via
    # `.pl()` (minutes_harness.py).
    values = (
        con.execute(
            f"SELECT max(known_at) AS known_at "
            f"FROM {_PLAYER_FIXTURE_LIVE_TABLE} "
            f"WHERE known_at <= ?",
            [as_of],
        )
        .pl()["known_at"]
        .to_list()
    )
    return values[0] if values and values[0] is not None else None


def _gameweek_covered(
    con: duckdb.DuckDBPyConnection, *, season: str, gw: int, as_of: datetime
) -> bool:
    """True if the live per-fixture table holds >=1 row for ``(season, gw)`` known by ``as_of``."""
    if not _has_table(con, _PLAYER_FIXTURE_LIVE_TABLE):
        return False
    row = con.execute(
        f"SELECT 1 FROM {_PLAYER_FIXTURE_LIVE_TABLE} "
        f"WHERE season = ? AND gw = ? AND known_at <= ? LIMIT 1",
        [season, gw, as_of],
    ).fetchone()
    return row is not None


def assess_prospective_freshness(
    con: duckdb.DuckDBPyConnection, *, as_of: datetime
) -> FreshnessAssessment:
    """Decide whether a prospective forecast at ``as_of`` may emit (Phase 0b P1).

    The gate passes in three cases and fails in one:

    1. No completed current-season fixture is known as of ``as_of`` (pre-season / GW1 deadline):
       cold start. The trailing window is prior-season history from the archive, which is correct
       by design, so the gate passes.
    2. The most-recent-completed gameweek belongs to a prior season already in the archive
       (e.g. a rollover where the prior season lingers in the versioned schedule): cold start,
       passes -- its history is archived, not live.
    3. The most-recent-completed gameweek belongs to the current/live season AND a player-history
       capture with ``known_at <= as_of`` covers it: passes.
    4. Same as 3 but the capture is missing or only exists with ``known_at > as_of``: FAILS.

    ``as_of`` must be timezone-aware, matching what the one caller already supplies.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware (UTC)")

    capture_known_at = _overall_capture_known_at(con, as_of=as_of)
    most_recent = _most_recent_completed(con, as_of=as_of)

    if most_recent is None:
        return FreshnessAssessment(
            as_of=as_of,
            most_recent_completed_season=None,
            most_recent_completed_gw=None,
            cold_start=True,
            covered=True,
            capture_known_at=capture_known_at,
            uncovered_season=None,
            uncovered_gw=None,
        )

    season_mrc, gw_mrc = most_recent
    if _season_in_archive(con, season_mrc):
        # Prior, fully-archived season: its most-recent GW is in the archive, not the live table.
        return FreshnessAssessment(
            as_of=as_of,
            most_recent_completed_season=season_mrc,
            most_recent_completed_gw=gw_mrc,
            cold_start=True,
            covered=True,
            capture_known_at=capture_known_at,
            uncovered_season=None,
            uncovered_gw=None,
        )

    # Current/live season: a completed GW whose result must be captured into the live table.
    if _gameweek_covered(con, season=season_mrc, gw=gw_mrc, as_of=as_of):
        return FreshnessAssessment(
            as_of=as_of,
            most_recent_completed_season=season_mrc,
            most_recent_completed_gw=gw_mrc,
            cold_start=False,
            covered=True,
            capture_known_at=capture_known_at,
            uncovered_season=None,
            uncovered_gw=None,
        )
    return FreshnessAssessment(
        as_of=as_of,
        most_recent_completed_season=season_mrc,
        most_recent_completed_gw=gw_mrc,
        cold_start=False,
        covered=False,
        capture_known_at=capture_known_at,
        uncovered_season=season_mrc,
        uncovered_gw=gw_mrc,
    )


def require_prospective_freshness(
    con: duckdb.DuckDBPyConnection, *, as_of: datetime
) -> FreshnessAssessment:
    """Assess freshness and raise :class:`FreshnessError` unless the gate passes."""
    assessment = assess_prospective_freshness(con, as_of=as_of)
    if not assessment.covered:
        raise FreshnessError(assessment)
    return assessment
